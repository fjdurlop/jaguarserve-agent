"""Phase 4: tools, role-filtered prices, allow-listed web, mock calendar."""

import json
from datetime import timedelta

import pytest

from agent.calendar import Appointment, InvalidBooking, SlotTaken
from agent.search import host_allowed
from agent.tools import ToolContext, run_tool, tools_for


def ctx(role, store, calendar, web, max_web=2):
    return ToolContext(
        role=role, session_id="s", store=store, calendar=calendar, web=web, max_web_calls=max_web
    )


def run(name, c, **args):
    return run_tool(name, json.dumps(args), c)


def test_price_visible_to_public(store, calendar, web):
    out = run("get_price", ctx("public", store, calendar, web), sku="VM-US-210", quantity=2)
    assert out["price_visible"] and out["unit_price"] == 18900.0 and out["total"] == 37800.0
    assert out["source_id"] == "S1"


def test_internal_price_hidden_from_public(store, calendar, web):
    out = run("get_price", ctx("public", store, calendar, web), sku="VM-US-350")
    assert out["price_visible"] is False and "unit_price" not in out
    assert "42500" not in json.dumps(out)


def test_internal_price_visible_to_internal(store, calendar, web):
    out = run("get_price", ctx("internal", store, calendar, web), sku="VM-US-350")
    assert out["unit_price"] == 42500.0


def test_internal_product_is_not_found_for_public(store, calendar, web):
    c = ctx("public", store, calendar, web)
    assert run("get_product", c, sku="VM-US-9X") == {"error": "product not found"}
    assert run("get_price", c, sku="VM-US-9X") == {"error": "product not found"}


def test_availability_has_date(store, calendar, web):
    out = run("check_availability", ctx("public", store, calendar, web), sku="QB-VT-T2")
    assert out["units_in_stock"] == 0 and out["as_of"] == "2026-11-10"


def test_bad_arguments(store, calendar, web):
    c = ctx("public", store, calendar, web)
    assert "missing" in run("get_price", c)["error"]
    assert run_tool("get_price", "not json", c)["error"].startswith("arguments")
    assert run_tool("drop_tables", "{}", c)["error"].startswith("unknown tool")


def test_source_ids_are_stable(store, calendar, web):
    c = ctx("public", store, calendar, web)
    a = run("get_product", c, sku="KI-PO-10")["source_id"]
    b = run("get_product", c, sku="KI-PO-10")["source_id"]
    assert a == b


def test_allow_list():
    allow = ["example.org"]
    assert host_allowed("https://www.example.org/x", allow)
    assert not host_allowed("https://example.org.evil.net/x", allow)
    assert not host_allowed("http://169.254.169.254/latest", allow)
    assert not host_allowed("file:///etc/passwd", allow)


def test_fetch_outside_allow_list_refused(store, calendar, web):
    out = run("fetch_page", ctx("public", store, calendar, web), url="https://evil.example.net/x")
    assert "not in allow-list" in out["error"]


def test_web_results_marked_untrusted_and_limited(store, calendar, web):
    c = ctx("public", store, calendar, web, max_web=1)
    first = run("web_search", c, query="electrical safety standards")
    assert first["results"] and "Untrusted" in first["note"]
    assert "limit" in run("web_search", c, query="again")["error"]


def test_web_tools_hidden_when_disabled():
    names = {t["function"]["name"] for t in tools_for("public", False, ["demo"])}
    assert "web_search" not in names and "search_catalog" in names


def test_slots_in_business_hours(calendar):
    slots = calendar.list_slots("demo", days=7)
    assert slots and all(s.weekday() < 5 and 9 <= s.hour < 17 for s in slots)
    assert slots[0].hour >= 10  # 08:00 now + 2 h lead


def _appt(calendar, slot, key="k1"):
    return Appointment(
        id=key + "-id",
        idempotency_key=key,
        session_id="s",
        type="demo",
        slot_start=slot,
        name="Ana",
        contact="ana@example.com",
    )


def test_book_idempotent_and_slot_taken(calendar):
    slot = calendar.list_slots("demo")[0]
    a = calendar.book(_appt(calendar, slot))
    assert calendar.book(_appt(calendar, slot)).id == a.id  # same key -> same booking
    with pytest.raises(SlotTaken):
        calendar.book(_appt(calendar, slot, key="k2"))
    assert slot not in calendar.list_slots("demo")
    calendar.cancel(a.id)
    assert slot in calendar.list_slots("demo")


def test_book_outside_hours_rejected(calendar):
    slot = calendar.list_slots("demo")[0].replace(hour=22)
    with pytest.raises(InvalidBooking):
        calendar.validate("demo", slot)
    with pytest.raises(InvalidBooking):
        calendar.validate("demo", calendar.list_slots("demo")[0] - timedelta(days=10))
    with pytest.raises(InvalidBooking):
        calendar.list_slots("massage")
