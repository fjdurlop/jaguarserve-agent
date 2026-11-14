"""Postgres + pgvector store and calendar. Skipped unless TEST_DATABASE_URL points at a disposable database.

    docker run -d --rm --name agent-pg-test -e POSTGRES_PASSWORD=test -p 127.0.0.1:55432:5432 \
        pgvector/pgvector:pg16
    TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:55432/postgres uv run pytest -m pg
"""

import os

import pytest

from agent.calendar import Appointment, SlotTaken
from agent.calendar.mock import MockCalendar
from agent.embeddings import HashEmbedder
from ingest import load_catalog
from tests.conftest import CATALOG, NOW

URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = [pytest.mark.pg, pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")]


@pytest.fixture(scope="module")
def pool():
    import psycopg

    from agent.db import make_pool

    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS chunks, products, appointments, feedback, meta CASCADE")
    p = make_pool(URL)
    yield p
    p.close()


@pytest.fixture(scope="module")
def pg_store(pool):
    from agent.catalog.pg import PgCatalog
    from agent.db import check_embedder

    check_embedder(pool, "hash", write=True)
    store = PgCatalog(pool, HashEmbedder())
    report = load_catalog(CATALOG, store)
    assert report.rejects == [] and report.products == 30
    return store


def test_ingest_is_idempotent(pg_store):
    with pg_store.pool.connection() as conn:
        before = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
    load_catalog(CATALOG, pg_store)
    with pg_store.pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == before


def test_embedder_mismatch_refused(pool, pg_store):
    from agent.db import check_embedder

    with pytest.raises(RuntimeError, match="re-run ingest"):
        check_embedder(pool, "another-model", write=False)


def test_lookup_and_role_filter(pg_store):
    assert pg_store.get_product("vm-us-210", "public").specs["Battery"] == "2.5 h"
    assert pg_store.get_product("VM-US-9X", "public") is None
    assert pg_store.get_product("VM-US-9X", "internal") is not None
    assert pg_store.search("KI-PM-500 specs", "public")[0].chunk.sku == "KI-PM-500"
    for q in ["SonoLite 9X preview", "sales notes distributors discount", "refurbished ventilator"]:
        assert all(h.chunk.visibility == "public" for h in pg_store.search(q, "public", k=8))
    assert any(
        "sales_notes" in h.chunk.source for h in pg_store.search("distributors volume rule", "internal", k=8)
    )
    assert 42500.0 in pg_store.internal_prices() and 18900.0 not in pg_store.internal_prices()


def test_accent_folded_full_text(pg_store):
    hits = pg_store.search("oximetro de mesa con impresora", "public")
    assert any(h.chunk.sku == "KI-PO-60" for h in hits[:3])


def test_pg_calendar(pool):
    cal = MockCalendar(["demo"], "mon-fri 09:00-17:00", "UTC", pool=pool, now=lambda: NOW)
    slot = cal.list_slots("demo")[0]
    a = Appointment("pg1", "key-1", "s", "demo", slot, "Ana", "ana@example.com")
    assert cal.book(a).id == "pg1"
    assert cal.book(Appointment("pg2", "key-1", "s", "demo", slot, "Ana", "ana@example.com")).id == "pg1"
    with pytest.raises(SlotTaken):
        cal.book(Appointment("pg3", "key-3", "s", "demo", slot, "Bo", "bo@example.com"))
    assert cal.cancel("pg1").status == "cancelled"
    assert slot in cal.list_slots("demo")
