"""Phase 5: HTTP contract — SSE events, roles, session binding, appointments, limits, ops endpoints."""

import json

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from tests.conftest import answer, call


def sse(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


@pytest.fixture
def client_for(settings, make_deps):
    def _make(replies, **overrides):
        for k, v in overrides.items():
            setattr(settings, k, v)
        deps = make_deps(replies)
        return TestClient(create_app(settings, deps)), deps

    return _make


def test_chat_streams_events(client_for):
    client, _ = client_for([call("get_price", sku="KI-PO-10"), answer("USD 45.00 [S1]")])
    with client:
        r = client.post("/v1/chat", json={"message": "price of KI-PO-10"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = sse(r.text)
    assert events[0][0] == "session" and events[0][1]["role"] == "public"
    assert [e for e, _ in events][-1] == "done"
    assert any(e == "citation" for e, _ in events)


def test_non_stream_json(client_for):
    client, _ = client_for([answer("Hello!")])
    with client:
        r = client.post("/v1/chat", json={"message": "hi", "stream": False})
    assert r.json()["text"] == "Hello!"


def test_roles_and_session_binding(client_for):
    client, _ = client_for([answer("a"), answer("b")])
    with client:
        r1 = client.post(
            "/v1/chat",
            json={"message": "hi", "stream": False},
            headers={"Authorization": "Bearer staff-token"},
        )
        sid = r1.json()["session_id"]
        assert r1.json()["events"][0]["role"] == "internal"
        # same session id without the token -> new public session, never the internal history
        r2 = client.post("/v1/chat", json={"message": "hi", "session_id": sid, "stream": False})
        assert r2.json()["session_id"] != sid and r2.json()["events"][0]["role"] == "public"
        assert (
            client.post(
                "/v1/chat", json={"message": "hi"}, headers={"Authorization": "Bearer wrong"}
            ).status_code
            == 401
        )


def test_booking_flow_and_appointment_endpoints(client_for, calendar):
    slot = calendar.list_slots("demo")[0].isoformat()
    client, _ = client_for(
        [
            call(
                "book_appointment",
                appointment_type="demo",
                slot_start=slot,
                name="Ana Ruiz",
                contact="ana@example.com",
            ),
            answer("Booked, see you then."),
        ]
    )
    with client:
        r = client.post("/v1/chat", json={"message": "book", "stream": False}).json()
        sid = r["session_id"]
        pending = next(e for e in r["events"] if e["type"] == "confirm")
        c = client.post(
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
        appt_id = next(e for e in c["events"] if e["type"] == "booking")["id"]

        assert (
            client.get(f"/v1/appointments/{appt_id}", headers={"X-Session-Id": sid}).json()["status"]
            == "booked"
        )
        assert client.get(f"/v1/appointments/{appt_id}", headers={"X-Session-Id": "other"}).status_code == 404
        assert (
            client.post(f"/v1/appointments/{appt_id}/cancel", headers={"X-Session-Id": sid}).json()["status"]
            == "cancelled"
        )


def test_confirm_needs_matching_session(client_for):
    client, _ = client_for([])
    with client:
        r = client.post(
            "/v1/chat", json={"session_id": "nope", "confirm": {"pending_id": "x", "confirm": True}}
        )
    assert r.status_code == 409


def test_rate_limit(client_for):
    client, _ = client_for([answer("ok")] * 5, rate_chat_per_min_ip=2)
    with client:
        codes = [
            client.post("/v1/chat", json={"message": "hi", "stream": False}).status_code for _ in range(3)
        ]
    assert codes[:2] == [200, 200] and codes[2] == 429


def test_validation_and_ops(client_for):
    client, _ = client_for([])
    with client:
        assert client.post("/v1/chat", json={}).status_code == 422
        assert client.post("/v1/chat", json={"message": "x" * 2001}).status_code == 422
        assert client.get("/healthz").json() == {"ok": True}
        assert client.get("/readyz").status_code == 200
        assert "agent_turns_total" in client.get("/metrics").text
        assert client.get("/").status_code == 200
        assert client.post("/v1/handoff", json={"session_id": "missing"}).status_code == 404
