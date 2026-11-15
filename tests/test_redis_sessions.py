"""Sessions and rate limits in Redis (fakeredis): several agent-api replicas share one conversation."""

from datetime import UTC, datetime

import fakeredis
import pytest
from fastapi.testclient import TestClient

from agent import metrics
from agent.session import Pending, RedisSessions, Session, get_or_create
from agent.tools import Source
from api import app as app_module
from api.ratelimit import RedisRateLimiter
from tests.conftest import answer, call


@pytest.fixture
def server():
    return fakeredis.FakeServer()


@pytest.fixture
def rsessions(server):
    return RedisSessions(fakeredis.FakeAsyncRedis(server=server), ttl_minutes=5, lock_ttl_s=30)


def test_session_json_round_trip():
    s = Session(id="abc", role="internal", lang="es")
    s.history = [{"role": "user", "content": "hola ñ"}]
    s.sources = {"S1": Source("S1", "price", "Price VM-US-01", "VM-US-01")}
    s.pending = Pending("p1", "c1", {"name": "Ana"}, datetime(2026, 11, 17, 10, tzinfo=UTC), "demo")
    s.confirmed = {"p0": "a1"}
    s.bookings = {"a1", "a2"}
    assert Session.from_json(s.to_json()) == s


async def test_store_save_get_and_role_binding(rsessions):
    s = await get_or_create(rsessions, None, "internal")
    s.history.append({"role": "user", "content": "hi"})
    await rsessions.save(s)
    assert (await rsessions.get(s.id)).history == s.history
    public = await get_or_create(rsessions, s.id, "public")  # other role -> new session
    assert public.id != s.id and public.history == []
    assert await rsessions.get("missing") is None


async def test_lock_is_exclusive_and_owned(rsessions):
    t1 = await rsessions.try_lock("s1")
    assert t1 and await rsessions.try_lock("s1") is None
    await rsessions.unlock("s1", "not-the-owner")
    assert await rsessions.try_lock("s1") is None
    await rsessions.unlock("s1", t1)
    assert await rsessions.try_lock("s1")


async def test_redis_rate_limit(server):
    rl = RedisRateLimiter(fakeredis.FakeAsyncRedis(server=server))
    assert await rl.check("k", 2, 60) == 0
    assert await rl.check("k", 2, 60) == 0
    assert await rl.check("k", 2, 60) >= 1
    assert await rl.check("other", 2, 60) == 0


@pytest.fixture
def replicas(settings, make_deps, server, monkeypatch):
    """Build agent-api replicas that share one (fake) Redis, like pods behind one Service."""
    settings.redis_url = "redis://fake"
    monkeypatch.setattr(
        app_module.RedisSessions,
        "from_url",
        classmethod(lambda cls, url, **kw: cls(fakeredis.FakeAsyncRedis(server=server), **kw)),
    )

    def _make(replies):
        return TestClient(app_module.create_app(settings, make_deps(replies)))

    return _make


def test_conversation_and_booking_move_between_replicas(replicas, calendar):
    slot = calendar.list_slots("demo")[0].isoformat()
    a = replicas(
        [
            call(
                "book_appointment",
                appointment_type="demo",
                slot_start=slot,
                name="Ana Ruiz",
                contact="ana@example.com",
            )
        ]
    )
    b = replicas([answer("Booked, see you then.")])
    with a, b:
        r = a.post("/v1/chat", json={"message": "book a demo", "stream": False}).json()
        sid = r["session_id"]
        pending = next(e for e in r["events"] if e["type"] == "confirm")
        c = b.post(  # confirm lands on the other replica
            "/v1/chat",
            json={
                "session_id": sid,
                "stream": False,
                "confirm": {
                    "pending_id": pending["pending_id"],
                    "confirm": True,
                    "accept_privacy_notice": True,
                },
            },
        ).json()
        assert c["session_id"] == sid and c["text"] == "Booked, see you then."
        appt_id = next(e for e in c["events"] if e["type"] == "booking")["id"]
        got = a.get(f"/v1/appointments/{appt_id}", headers={"X-Session-Id": sid})
        assert got.status_code == 200 and got.json()["status"] == "booked"


def test_busy_session_rejected_across_replicas(replicas, server):
    a = replicas([answer("one")])
    b = replicas([answer("two")])
    with a, b:
        sid = a.post("/v1/chat", json={"message": "hi", "stream": False}).json()["session_id"]
        fakeredis.FakeRedis(server=server).set(f"lock:{sid}", "held-by-a", px=30_000)
        r = b.post("/v1/chat", json={"message": "again", "session_id": sid, "stream": False})
        assert r.status_code == 409


def test_rate_limit_shared_across_replicas(replicas, settings):
    settings.rate_chat_per_min_ip = 2
    a = replicas([answer("1"), answer("3")])
    b = replicas([answer("2")])
    with a, b:
        assert a.post("/v1/chat", json={"message": "hi", "stream": False}).status_code == 200
        assert b.post("/v1/chat", json={"message": "hi", "stream": False}).status_code == 200
        assert a.post("/v1/chat", json={"message": "hi", "stream": False}).status_code == 429


def test_waiting_gauge_counts_cold_turns(client_for_cold):
    client, seen = client_for_cold
    with client:
        r = client.post("/v1/chat", json={"message": "hi", "stream": False}).json()
    assert any(e.get("state") == "warming_up" for e in r["events"])
    assert seen and max(seen) == 1  # gauge was 1 while the turn waited
    assert metrics.LLM_WAITING._value.get() == 0  # and back to 0 after


@pytest.fixture
def client_for_cold(settings, make_deps):
    """LLM not ready at the first probe, ready at the next one (~2 s); records the gauge at each probe."""
    settings.llm_ready_timeout = 30
    deps = make_deps([answer("warm now")], ready=False)
    seen: list[float] = []
    probes = iter([False])

    async def ready():
        seen.append(metrics.LLM_WAITING._value.get())
        return next(probes, True)

    deps.llm.ready = ready
    return TestClient(app_module.create_app(settings, deps)), seen
