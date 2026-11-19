"""One chat turn: scope check -> wait for LLM -> tool loop -> guardrails -> events.

Events (also the SSE event names): status, tool, slots, confirm, booking, token, citation, error, done.
Booking is never executed from a model tool call: the call becomes a `confirm` event and the booking
happens only when the user confirms through the API (`confirm_booking`).
"""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from agent import guardrails, metrics
from agent.calendar import Appointment, BookingError, Calendar, SlotTaken
from agent.catalog import CatalogStore
from agent.config import Settings
from agent.llm import LLM, LLMUnavailable, Reply
from agent.prompts import system_prompt
from agent.search import WebSearch
from agent.session import Pending, Session
from agent.text import is_email, is_phone
from agent.tools import ToolContext, parse_slot, run_tool, tools_for

log = logging.getLogger("agent")


@dataclass
class Event:
    type: str
    data: dict[str, Any]


@dataclass
class Deps:
    settings: Settings
    store: CatalogStore
    calendar: Calendar
    web: WebSearch
    llm: LLM
    fallback: LLM | None = None


def _ctx(session: Session, deps: Deps) -> ToolContext:
    return ToolContext(
        role=session.role,
        session_id=session.id,
        store=deps.store,
        calendar=deps.calendar,
        web=deps.web,
        max_web_calls=deps.settings.agent_max_web_calls,
        sources=session.sources,
    )


def _tool_msg(call_id: str, result: dict) -> dict:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps(result, ensure_ascii=False, default=str),
    }


# --- entry points ----------------------------------------------------------------------------------
async def chat_turn(session: Session, deps: Deps, message: str) -> AsyncIterator[Event]:
    started = time.monotonic()
    session.lang = guardrails.lang_of(message)
    if session.pending:  # user moved on without confirming
        session.history.append(
            _tool_msg(
                session.pending.call_id,
                {"status": "not_confirmed", "note": "user sent a new message instead"},
            )
        )
        session.pending = None
    session.history.append({"role": "user", "content": message})
    if deps.settings.log_chat_content:  # dev only; off by default (personal data)
        log.info(json.dumps({"event": "user_message", "session": session.id[:6], "text": message}))
    reason = guardrails.out_of_scope(message)
    if reason:
        text = guardrails.message(reason, session.lang)
        session.history.append({"role": "assistant", "content": text})
        metrics.REFUSALS.labels(reason).inc()
        metrics.TURNS.labels(session.role, "refused").inc()
        yield Event("token", {"text": text})
        yield Event("done", {"text": text, "citations": [], "refused": True, "reason": reason})
        return
    async for ev in _agent(session, deps, started):
        yield ev


async def confirm_booking(
    session: Session, deps: Deps, pending_id: str, accept: bool, privacy_accepted: bool
) -> AsyncIterator[Event]:
    started = time.monotonic()
    if pending_id in session.confirmed:  # repeated confirm: same booking, no new call
        appt = deps.calendar.get(session.confirmed[pending_id])
        if appt:
            yield Event("booking", _booking_view(appt))
        yield Event("done", {"text": "", "citations": [], "refused": False})
        return
    pending = session.pending
    if pending is None or pending.id != pending_id:
        yield Event("error", {"code": "no_pending_booking"})
        return
    session.pending = None
    if not accept or not privacy_accepted:
        result = {
            "status": "not_booked",
            "reason": "user declined" if not accept else "privacy notice not accepted; booking needs it",
        }
        metrics.BOOKINGS.labels("declined").inc()
    else:
        appt = Appointment(
            id=uuid.uuid4().hex[:12],
            idempotency_key=pending.id,
            session_id=session.id,
            type=pending.args["appointment_type"],
            slot_start=pending.slot,
            name=pending.args["name"].strip(),
            contact=pending.args["contact"].strip(),
            product_sku=pending.args.get("product_sku"),
        )
        try:
            appt = await asyncio.to_thread(deps.calendar.book, appt)
            session.confirmed[pending.id] = appt.id
            session.bookings.add(appt.id)
            metrics.BOOKINGS.labels("booked").inc()
            result = {"status": "booked", **_booking_view(appt)}
            yield Event("booking", _booking_view(appt))
        except SlotTaken:
            metrics.BOOKINGS.labels("slot_taken").inc()
            result = {"status": "not_booked", "error": "slot_taken", "note": "offer other slots"}
            yield Event("status", {"state": "slot_taken"})
        except BookingError as exc:
            metrics.BOOKINGS.labels("invalid").inc()
            result = {"status": "not_booked", "error": exc.code, "detail": str(exc)}
    session.history.append(_tool_msg(pending.call_id, result))
    async for ev in _agent(session, deps, started):
        yield ev


# --- core ------------------------------------------------------------------------------------------
async def _agent(session: Session, deps: Deps, started: float) -> AsyncIterator[Event]:
    s = deps.settings
    llm = None
    async for ev in _wait_for_llm(deps):
        if isinstance(ev, Event):
            yield ev
        else:
            llm = ev
    if llm is None:
        yield from_error(session, "llm_unavailable")
        metrics.TURNS.labels(session.role, "llm_unavailable").inc()
        yield Event(
            "done",
            {"text": guardrails.message("llm_unavailable", session.lang), "citations": [], "refused": False},
        )
        return

    ctx = _ctx(session, deps)
    tools = tools_for(session.role, deps.web.enabled, deps.calendar.types)
    sys_msg = {
        "role": "system",
        "content": system_prompt(session.role, s.timezone, deps.calendar.types, datetime.now(UTC)),
    }
    live = s.stream_answer == "live"
    used_tools: list[str] = []
    reply = Reply()
    for step in range(s.agent_max_steps + 1):
        last = step == s.agent_max_steps
        try:
            reply = Reply()
            t0 = time.monotonic()
            first = True
            async for kind, value in llm.stream([sys_msg, *session.history], None if last else tools):
                if kind == "token":
                    if first:
                        metrics.FIRST_TOKEN.observe(time.monotonic() - t0)
                        first = False
                    if live:
                        yield Event("token", {"text": value})
                else:
                    reply = value
        except LLMUnavailable as exc:
            log.warning("llm error: %s", exc)
            metrics.TURNS.labels(session.role, "llm_error").inc()
            yield from_error(session, "llm_unavailable")
            yield Event(
                "done",
                {
                    "text": guardrails.message("llm_unavailable", session.lang),
                    "citations": [],
                    "refused": False,
                },
            )
            return
        if not reply.tool_calls:
            break
        session.history.append(
            {
                "role": "assistant",
                "content": reply.content or None,
                "tool_calls": [
                    {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                    for c in reply.tool_calls
                ],
            }
        )
        for i, call in enumerate(reply.tool_calls):
            used_tools.append(call.name)
            yield Event("tool", {"name": call.name})
            if call.name == "book_appointment":
                pending, error = await asyncio.to_thread(
                    _pending_from, call.id, call.arguments, deps.calendar
                )
                if error:
                    metrics.TOOL_CALLS.labels(call.name, "error").inc()
                    session.history.append(_tool_msg(call.id, {"error": error}))
                    continue
                for later in reply.tool_calls[i + 1 :]:
                    session.history.append(_tool_msg(later.id, {"error": "skipped: waiting for booking"}))
                session.pending = pending
                metrics.TOOL_CALLS.labels(call.name, "confirm").inc()
                yield Event(
                    "confirm",
                    {
                        "pending_id": pending.id,
                        "summary": pending.summary,
                        "slot": pending.slot.isoformat(),
                        "appointment_type": pending.args["appointment_type"],
                        "privacy_notice_url": s.privacy_notice_url,
                    },
                )
                text = (
                    "Please confirm the appointment below."
                    if session.lang == "en"
                    else "Confirma la cita a continuación."
                )
                yield Event("done", {"text": text, "citations": [], "refused": False, "awaiting": "confirm"})
                _log_turn(session, started, used_tools, "awaiting_confirm")
                return
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(run_tool, call.name, call.arguments, ctx), timeout=s.tool_timeout
                )
            except TimeoutError:
                result = {"error": "tool timed out"}
            metrics.TOOL_CALLS.labels(call.name, "error" if "error" in result else "ok").inc()
            if call.name == "list_slots" and result.get("slots"):
                yield Event(
                    "slots", {"appointment_type": result["appointment_type"], "slots": result["slots"]}
                )
            session.history.append(_tool_msg(call.id, result))

    evidence = [
        m["content"] for m in session.history if m.get("role") in ("tool", "user") and m.get("content")
    ]
    checked = guardrails.check_answer(
        reply.content or "",
        known_sources=set(ctx.sources),
        evidence=evidence,
        role=session.role,
        internal_prices=await asyncio.to_thread(deps.store.internal_prices)
        if session.role != "internal"
        else set(),
        lang=session.lang,
    )
    for v in checked.violations:
        metrics.GUARD.labels(v).inc()
    if not checked.text.strip():
        checked.text = guardrails.message("empty", session.lang)
    session.history.append({"role": "assistant", "content": checked.text})
    session.trim()
    if not live:
        for piece in _chunks(checked.text):
            yield Event("token", {"text": piece})
    for sid in checked.citations:
        src = ctx.sources[sid]
        yield Event(
            "citation",
            {
                "id": sid,
                "kind": src.kind,
                "title": src.title,
                "ref": src.ref if src.kind in ("web", "catalog") else src.title,
            },
        )
    yield Event(
        "done",
        {
            "text": checked.text,
            "citations": checked.citations,
            "refused": False,
            "replaced": checked.replaced,
        },
    )
    outcome = "replaced" if checked.replaced else "ok"
    metrics.TURNS.labels(session.role, outcome).inc()
    metrics.TURN_SECONDS.observe(time.monotonic() - started)
    _log_turn(session, started, used_tools, outcome, checked.violations)


async def _wait_for_llm(deps: Deps) -> AsyncIterator[Any]:
    """Yield status events while the LLM warms up, then yield the LLM to use (or nothing)."""
    if await deps.llm.ready():
        yield deps.llm
        return
    if deps.fallback and await deps.fallback.ready():
        yield Event("status", {"state": "fallback"})
        yield deps.fallback
        return
    yield Event("status", {"state": "warming_up"})
    t0 = time.monotonic()
    deadline = t0 + deps.settings.llm_ready_timeout
    delay = 2.0
    ready = False
    metrics.LLM_WAITING.inc()
    try:
        while time.monotonic() < deadline:
            await asyncio.sleep(min(delay, max(0.0, deadline - time.monotonic())))
            if await deps.llm.ready():
                ready = True
                break
            yield Event("status", {"state": "warming_up", "waited_s": round(time.monotonic() - t0)})
            delay = min(delay * 1.5, 15.0)
    finally:
        metrics.LLM_WAITING.dec()
    if ready:
        metrics.LLM_WAIT.observe(time.monotonic() - t0)
        yield Event("status", {"state": "ready"})
        yield deps.llm


def _pending_from(call_id: str, raw: str, calendar: Calendar) -> tuple[Pending | None, str | None]:
    try:
        args = json.loads(raw or "{}")
        slot = parse_slot(str(args["slot_start"]))
        name, contact, appt_type = (
            str(args["name"]).strip(),
            str(args["contact"]).strip(),
            args["appointment_type"],
        )
    except (ValueError, KeyError, TypeError):
        return None, "need appointment_type, slot_start (ISO from list_slots), name and contact"
    if not (2 <= len(name) <= 80):
        return None, "ask the user for their name"
    if not (is_email(contact) or is_phone(contact)):
        return None, "ask the user for a valid email or phone"
    try:
        calendar.validate(appt_type, slot)
    except SlotTaken:
        return None, "slot_taken: offer other slots from list_slots"
    except BookingError as exc:
        return None, f"{exc.code}: {exc}"
    masked = contact[:2] + "***" + contact[-4:] if len(contact) > 6 else "***"
    summary = f"{appt_type.replace('_', ' ')} · {slot.isoformat(timespec='minutes')} · {name} · {masked}"
    return Pending(id=uuid.uuid4().hex, call_id=call_id, args=args, slot=slot, summary=summary), None


def _booking_view(appt: Appointment) -> dict:
    return {
        "id": appt.id,
        "slot": appt.slot_start.isoformat(),
        "appointment_type": appt.type,
        "status": appt.status,
    }


def from_error(session: Session, code: str) -> Event:
    return Event("error", {"code": code})


def _chunks(text: str, size: int = 24) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


def _log_turn(
    session: Session, started: float, tools: list[str], outcome: str, violations: list[str] | None = None
) -> None:
    log.info(
        json.dumps(
            {
                "event": "turn",
                "session": session.id[:6],
                "role": session.role,
                "outcome": outcome,
                "tools": tools,
                "violations": violations or [],
                "ms": int((time.monotonic() - started) * 1000),
            }
        )
    )
