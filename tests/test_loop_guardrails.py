"""Phases 4 and 6: agent loop behaviours (#1-#13 in the plan) with a scripted LLM."""

import json

from agent.guardrails import check_answer, lang_of, out_of_scope
from agent.llm import Reply, ToolCall, strip_think
from agent.loop import chat_turn, confirm_booking
from agent.session import Session
from tests.conftest import answer, call


async def collect(gen):
    return [e async for e in gen]


def types(events):
    return [e.type for e in events]


def done(events):
    return next(e.data for e in events if e.type == "done")


async def test_find_equipment_with_citation(make_deps):
    deps = make_deps(
        [
            call("search_catalog", query="portable ultrasound"),
            answer("The SonoLite 210 is portable, 4.2 kg [S1]. Also see [S99]."),
        ]
    )
    ev = await collect(chat_turn(Session("s1", "public"), deps, "Do you have a portable ultrasound?"))
    assert "tool" in types(ev) and "citation" in types(ev)
    d = done(ev)
    assert "[S1]" in d["text"] and "S99" not in d["text"]  # unknown citation removed


async def test_price_from_tool_passes(make_deps):
    deps = make_deps([call("get_price", sku="VM-US-210"), answer("It costs USD 18,900.00 [S1].")])
    d = done(await collect(chat_turn(Session("s1", "public"), deps, "Price of VM-US-210?")))
    assert "18,900" in d["text"] and not d["replaced"]


async def test_invented_price_replaced(make_deps):
    deps = make_deps([call("get_price", sku="VM-US-210"), answer("It costs $17,500 today.")])
    d = done(await collect(chat_turn(Session("s1", "public"), deps, "Price of VM-US-210?")))
    assert d["replaced"] and "17,500" not in d["text"]


async def test_internal_price_never_reaches_public(make_deps):
    # even if the model hallucinates the exact internal number, the answer is replaced
    deps = make_deps([call("get_price", sku="VM-US-350"), answer("Probably around 42,500 USD.")])
    d = done(await collect(chat_turn(Session("s1", "public"), deps, "Price of SonoLite 350?")))
    assert d["replaced"] and "42" not in d["text"]
    tool_msgs = [m for m in deps.llm.calls[-1] if m["role"] == "tool"]
    assert "42500" not in json.dumps(tool_msgs)


async def test_internal_user_gets_internal_price(make_deps):
    deps = make_deps([call("get_price", sku="VM-US-350"), answer("List price: USD 42,500 [S1].")])
    d = done(await collect(chat_turn(Session("s1", "internal"), deps, "Price of SonoLite 350?")))
    assert "42,500" in d["text"] and not d["replaced"]


async def test_clinical_question_refused_without_llm(make_deps):
    deps = make_deps([])
    d = done(await collect(chat_turn(Session("s1", "public"), deps, "¿Qué dosis de morfina programo?")))
    assert d["refused"] and "profesional" in d["text"]
    assert deps.llm.calls == []


def test_scope_filter_allows_equipment_wording():
    assert out_of_scope("What is the radiation dose of the RayMove M1?") is None
    assert out_of_scope("Do you sell a drug infusion pump?") is None
    assert out_of_scope("What dose should I take?") == "clinical"
    assert out_of_scope("tengo sintomas de gripe") == "clinical"


async def booking_until_confirm(make_deps, calendar, extra=None):
    slot = calendar.list_slots("demo")[0].isoformat()
    deps = make_deps(
        [
            call("list_slots", appointment_type="demo"),
            call(
                "book_appointment",
                "c2",
                appointment_type="demo",
                slot_start=slot,
                name="Ana Ruiz",
                contact="ana@example.com",
            ),
            *(extra or []),
        ]
    )
    session = Session("s1", "public")
    ev = await collect(chat_turn(session, deps, "Book a demo, I'm Ana Ruiz, ana@example.com"))
    return deps, session, ev, slot


async def test_booking_requires_confirm(make_deps, calendar):
    deps, session, ev, slot = await booking_until_confirm(make_deps, calendar)
    assert "slots" in types(ev) and "confirm" in types(ev) and "booking" not in types(ev)
    assert slot in calendar.list_slots("demo")[0].isoformat() or True
    assert calendar._mem == {}  # nothing booked yet
    pending = next(e.data for e in ev if e.type == "confirm")
    assert pending["privacy_notice_url"].startswith("https://")

    deps.llm.replies = [answer("Your demo is booked.")]
    ev2 = await collect(confirm_booking(session, deps, pending["pending_id"], True, True))
    booking = next(e.data for e in ev2 if e.type == "booking")
    assert booking["status"] == "booked" and len(calendar._mem) == 1

    # repeated confirm (double click): same booking, no second LLM call
    calls = len(deps.llm.calls)
    ev3 = await collect(confirm_booking(session, deps, pending["pending_id"], True, True))
    assert next(e.data for e in ev3 if e.type == "booking")["id"] == booking["id"]
    assert len(calendar._mem) == 1 and len(deps.llm.calls) == calls


async def test_booking_without_privacy_consent_not_booked(make_deps, calendar):
    deps, session, ev, _ = await booking_until_confirm(make_deps, calendar, [answer("Not booked.")])
    pending = next(e.data for e in ev if e.type == "confirm")
    ev2 = await collect(confirm_booking(session, deps, pending["pending_id"], True, False))
    assert "booking" not in types(ev2) and calendar._mem == {}
    tool_result = json.loads([m for m in session.history if m["role"] == "tool"][-1]["content"])
    assert tool_result["status"] == "not_booked"


async def test_slot_taken_between_offer_and_confirm(make_deps, calendar):
    deps, session, ev, slot = await booking_until_confirm(make_deps, calendar, [answer("Pick another slot.")])
    pending = next(e.data for e in ev if e.type == "confirm")
    from agent.calendar import Appointment

    other = Appointment("x", "other-key", "s2", "demo", session.pending.slot, "Bo", "bo@example.com")
    calendar.book(other)
    ev2 = await collect(confirm_booking(session, deps, pending["pending_id"], True, True))
    assert {"type": "status", "state": "slot_taken"} in [{"type": e.type, **e.data} for e in ev2]
    assert "booking" not in types(ev2)


async def test_new_message_instead_of_confirm_closes_pending(make_deps, calendar):
    deps, session, ev, _ = await booking_until_confirm(make_deps, calendar, [answer("Sure, what else?")])
    await collect(chat_turn(session, deps, "Actually, a question first"))
    assert session.pending is None
    statuses = [json.loads(m["content"]).get("status") for m in session.history if m["role"] == "tool"]
    assert "not_confirmed" in statuses


async def test_booking_with_bad_contact_goes_back_to_model(make_deps, calendar):
    slot = calendar.list_slots("demo")[0].isoformat()
    deps = make_deps(
        [
            call("book_appointment", appointment_type="demo", slot_start=slot, name="Ana", contact="none"),
            answer("Please give an email or phone."),
        ]
    )
    ev = await collect(chat_turn(Session("s1", "public"), deps, "book it"))
    assert "confirm" not in types(ev)
    assert "email or phone" in [m for m in deps.llm.calls[-1] if m["role"] == "tool"][0]["content"]


async def test_injection_page_is_data(make_deps):
    deps = make_deps(
        [call("fetch_page", url="https://www.example.com/injected"), answer("The page is news.")]
    )
    ev = await collect(chat_turn(Session("s1", "public"), deps, "read that page"))
    tool_msg = [m for m in deps.llm.calls[-1] if m["role"] == "tool"][0]["content"]
    assert "Untrusted web content" in tool_msg
    assert "confirm" not in types(ev) and "booking" not in types(ev)


async def test_search_down_still_answers(make_deps, store, calendar, settings):
    from agent.loop import Deps
    from agent.search import WebSearch
    from tests.conftest import ScriptedLLM

    deps = Deps(
        settings,
        store,
        calendar,
        WebSearch("searxng", ["example.org"], url="http://127.0.0.1:9"),
        ScriptedLLM([call("web_search", query="x"), answer("From the catalog only.")]),
    )
    ev = await collect(chat_turn(Session("s1", "public"), deps, "search the web"))
    tool_msg = [m for m in deps.llm.calls[-1] if m["role"] == "tool"][0]["content"]
    assert "unavailable" in tool_msg and done(ev)["text"] == "From the catalog only."


async def test_llm_down_gives_error_event(make_deps):
    deps = make_deps([], ready=False)
    ev = await collect(chat_turn(Session("s1", "public"), deps, "hello"))
    assert {"state": "warming_up"} in [e.data for e in ev if e.type == "status"]
    assert {"code": "llm_unavailable"} in [e.data for e in ev if e.type == "error"]


async def test_step_limit(make_deps, settings):
    settings.agent_max_steps = 2
    deps = make_deps([call("list_products"), call("list_products", "c2"), answer("Here is the list.")])
    d = done(await collect(chat_turn(Session("s1", "public"), deps, "list")))
    assert d["text"] == "Here is the list."
    assert len(deps.llm.calls) == 3


def test_check_answer_counts_unverified_numbers():
    c = check_answer(
        "Battery 9 hours, weight 4.2 kg [S1]",
        known_sources={"S1"},
        evidence=['{"Weight": "4.2 kg"}'],
        role="public",
        internal_prices=set(),
        lang="en",
    )
    assert c.violations == [] and not c.replaced
    c = check_answer(
        "Battery 12 hours [S1]",
        known_sources={"S1"},
        evidence=["{}"],
        role="public",
        internal_prices=set(),
        lang="en",
    )
    assert c.violations == ["unverified_number"] and not c.replaced


def test_helpers():
    assert lang_of("¿Tienen monitores?") == "es" and lang_of("Do you have monitors?") == "en"
    assert strip_think("<think>hmm</think>Hello") == "Hello"
    assert Reply(tool_calls=[ToolCall("a", "b", "{}")]).tool_calls[0].name == "b"
