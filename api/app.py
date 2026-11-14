"""agent-api: chat over SSE, roles, booking confirm, appointment lookup, handoff, feedback, ops endpoints.

Run:  uv run uvicorn api.app:app --port 8080
"""

import asyncio
import hmac
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from agent.calendar.mock import MockCalendar
from agent.catalog.memory import MemoryCatalog
from agent.config import Settings, get_settings
from agent.embeddings import get_embedder
from agent.llm import OpenAICompatLLM
from agent.loop import Deps, Event, chat_turn, confirm_booking
from agent.search import WebSearch
from agent.session import Sessions
from api.ratelimit import RateLimiter

log = logging.getLogger("api")
WEB = Path(__file__).resolve().parent.parent / "web"


class ConfirmIn(BaseModel):
    pending_id: str = Field(max_length=64)
    confirm: bool
    accept_privacy_notice: bool = False


class ChatIn(BaseModel):
    message: str | None = Field(default=None, max_length=2000)
    session_id: str | None = Field(default=None, max_length=64)
    stream: bool = True
    confirm: ConfirmIn | None = None


class HandoffIn(BaseModel):
    session_id: str = Field(max_length=64)
    contact: str | None = Field(default=None, max_length=120)


class FeedbackIn(BaseModel):
    session_id: str = Field(max_length=64)
    rating: int = Field(ge=-1, le=1)


def build_deps(s: Settings) -> tuple[Deps, object | None]:
    embedder = get_embedder(s.embedding_model)
    pool = None
    if s.store == "pg":
        from agent.catalog.pg import PgCatalog
        from agent.db import check_embedder, make_pool

        pool = make_pool(s.database_url)
        check_embedder(pool, embedder.name, write=False)
        store = PgCatalog(pool, embedder)
    else:
        from ingest import load_catalog

        store = MemoryCatalog(embedder)
        report = load_catalog(Path(s.catalog_path), store)
        log.info("memory catalog loaded: %s", report.summary())
    calendar = MockCalendar(
        s.appointment_type_list, s.business_hours, s.timezone, s.slot_minutes, s.booking_lead_hours, pool=pool
    )
    web = WebSearch(s.search_provider, s.allow_list, s.search_url, s.search_api_key)
    llm = OpenAICompatLLM(
        s.llm_base_url,
        s.llm_model,
        s.llm_api_key,
        s.llm_timeout,
        s.llm_enable_thinking,
        s.llm_temperature,
        s.llm_max_tokens,
    )
    fallback = None
    if s.llm_fallback_base_url and s.llm_fallback_model:
        fallback = OpenAICompatLLM(
            s.llm_fallback_base_url,
            s.llm_fallback_model,
            s.llm_fallback_api_key,
            s.llm_timeout,
            temperature=s.llm_temperature,
            max_tokens=s.llm_max_tokens,
            vllm_extras=False,
        )
    return Deps(s, store, calendar, web, llm, fallback), pool


def create_app(settings: Settings | None = None, deps: Deps | None = None) -> FastAPI:
    s = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        pool = None
        if deps is None:
            app.state.deps, pool = await asyncio.to_thread(build_deps, s)
        else:
            app.state.deps = deps
        app.state.pool = pool
        yield
        if pool is not None:
            pool.close()

    app = FastAPI(title="jaguarserve-agent", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.sessions = Sessions(s.session_ttl_minutes)
    app.state.limits = RateLimiter()
    if s.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[o.strip() for o in s.cors_origins.split(",")],
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "X-Session-Id"],
        )

    def role_of(authorization: str | None) -> str:
        if not authorization:
            return "public"
        token = authorization.removeprefix("Bearer ").strip()
        if any(hmac.compare_digest(token, t) for t in s.internal_token_list):
            return "internal"
        raise HTTPException(401, "invalid token")

    def limit(key: str, n: int, window: float) -> None:
        wait = app.state.limits.check(key, n, window)
        if wait:
            raise HTTPException(429, "rate limited", headers={"Retry-After": str(int(wait) + 1)})

    @app.post("/v1/chat")
    async def chat(body: ChatIn, request: Request, authorization: str | None = Header(default=None)):
        role = role_of(authorization)
        ip = request.client.host if request.client else "unknown"
        limit(f"ip:{ip}", s.rate_chat_per_min_ip, 60)
        if not body.confirm and not (body.message and body.message.strip()):
            raise HTTPException(422, "message or confirm required")
        session = app.state.sessions.get_or_create(body.session_id, role)
        limit(f"session:{session.id}", s.rate_chat_per_min_session, 60)
        if body.confirm:
            if body.confirm.confirm:
                limit(f"book:{session.id}", s.rate_book_per_hour_session, 3600)
                limit(f"book-ip:{ip}", s.rate_book_per_hour_session * 3, 3600)
            if body.session_id != session.id:
                raise HTTPException(409, "session expired; start again")
        if session.lock.locked():
            raise HTTPException(409, "a reply is still in progress for this session")
        d: Deps = app.state.deps

        async def events() -> AsyncIterator[Event]:
            async with session.lock:
                yield Event("session", {"session_id": session.id, "role": session.role})
                if body.confirm:
                    gen = confirm_booking(
                        session,
                        d,
                        body.confirm.pending_id,
                        body.confirm.confirm,
                        body.confirm.accept_privacy_notice,
                    )
                else:
                    gen = chat_turn(session, d, body.message.strip())
                async for ev in gen:
                    yield ev

        if not body.stream:
            collected: dict = {"events": []}
            async for ev in events():
                collected["events"].append({**ev.data, "type": ev.type})
            done = next((e for e in reversed(collected["events"]) if e["type"] == "done"), {})
            return {"session_id": session.id, "text": done.get("text", ""), **collected}

        async def sse() -> AsyncIterator[bytes]:
            try:
                async for ev in events():
                    yield f"event: {ev.type}\ndata: {json.dumps(ev.data, ensure_ascii=False)}\n\n".encode()
            except Exception:
                log.exception("turn failed")
                yield b'event: error\ndata: {"code": "internal_error"}\n\n'

        return StreamingResponse(
            sse(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    def own_appointment(appt_id: str, session_id: str | None):
        session = app.state.sessions.get(session_id or "")
        if session is None or appt_id not in session.bookings:
            raise HTTPException(404, "not found")
        appt = app.state.deps.calendar.get(appt_id)
        if appt is None:
            raise HTTPException(404, "not found")
        return appt

    def view(appt) -> dict:
        return {"id": appt.id, "type": appt.type, "slot": appt.slot_start.isoformat(), "status": appt.status}

    @app.get("/v1/appointments/{appt_id}")
    async def get_appointment(appt_id: str, x_session_id: str | None = Header(default=None)):
        return view(await asyncio.to_thread(own_appointment, appt_id, x_session_id))

    @app.post("/v1/appointments/{appt_id}/cancel")
    async def cancel_appointment(appt_id: str, x_session_id: str | None = Header(default=None)):
        await asyncio.to_thread(own_appointment, appt_id, x_session_id)
        return view(await asyncio.to_thread(app.state.deps.calendar.cancel, appt_id))

    @app.post("/v1/handoff", status_code=202)
    async def handoff(body: HandoffIn, request: Request):
        limit(f"handoff:{request.client.host if request.client else 'x'}", 5, 3600)
        session = app.state.sessions.get(body.session_id)
        if session is None:
            raise HTTPException(404, "session not found")
        payload = {
            "session": session.id[:6],
            "role": session.role,
            "lang": session.lang,
            "contact": body.contact,
            "bookings": sorted(session.bookings),
        }
        if s.handoff_webhook_url:
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    (await client.post(s.handoff_webhook_url, json=payload)).raise_for_status()
            except httpx.HTTPError:
                log.warning("handoff webhook failed")
                raise HTTPException(502, "handoff unavailable") from None
        else:
            log.info(json.dumps({"event": "handoff", "session": payload["session"], "role": session.role}))
        return {"status": "accepted"}

    @app.post("/v1/feedback", status_code=204)
    async def feedback(body: FeedbackIn):
        if body.rating == 0 or app.state.sessions.get(body.session_id) is None:
            raise HTTPException(422, "rating must be -1 or 1 for an active session")
        pool = app.state.pool
        if pool is not None:

            def write():
                with pool.connection() as conn:
                    conn.execute(
                        "INSERT INTO feedback (session_id, rating) VALUES (%s, %s)",
                        (body.session_id[:6], body.rating),
                    )

            await asyncio.to_thread(write)
        return Response(status_code=204)

    @app.get("/v1/status")
    async def status():
        return {
            "llm_ready": await app.state.deps.llm.ready(),
            "model": app.state.deps.llm.name,
            "web_search": app.state.deps.web.enabled,
        }

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.get("/readyz")
    async def readyz():  # does not depend on the LLM: the GPU may be scaled to zero
        ok = await asyncio.to_thread(app.state.deps.store.ping)
        return JSONResponse({"ok": ok}, status_code=200 if ok else 503)

    @app.get("/metrics")
    async def metrics():  # keep off the public ingress
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/")
    async def index():
        return FileResponse(WEB / "index.html")

    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
app = create_app()
