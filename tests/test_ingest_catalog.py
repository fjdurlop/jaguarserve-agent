"""Phase 3: parsers, validation, retrieval and the role filter."""

from pathlib import Path

import pytest

from agent.catalog.memory import MemoryCatalog
from agent.embeddings import HashEmbedder
from ingest import load_catalog
from ingest.parsers import specs_from_markdown
from ingest.validate import RowError, product_from_row
from tests.conftest import CATALOG


def test_demo_catalog_ingests_cleanly():
    report = load_catalog(CATALOG, MemoryCatalog(HashEmbedder()))
    assert report.products == 30
    assert report.rejects == []
    assert report.chunks > 60


def test_specs_extracted_from_english_sheet(store):
    p = store.get_product("VM-US-210", "public")
    assert p.specs["Battery"] == "2.5 h"
    assert p.price == 18900.0 and p.currency == "USD"


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        ({"sku": "", "name": "x", "category": "y"}, "missing sku"),
        ({"sku": "A B", "name": "x", "category": "y"}, "sku"),
        ({"sku": "AB-1", "name": "x", "category": "y", "price": "ten", "currency": "USD"}, "price"),
        ({"sku": "AB-1", "name": "x", "category": "y", "price": "10", "currency": "dollars"}, "currency"),
        ({"sku": "AB-1", "name": "x", "category": "y", "stock": "-1"}, "stock"),
        ({"sku": "AB-1", "name": "x", "category": "y", "visibility": "everyone"}, "visibility"),
    ],
)
def test_invalid_rows_rejected(row, reason):
    with pytest.raises(RowError, match=reason):
        product_from_row(row, "x.csv")


def test_missing_visibility_fails_closed():
    p = product_from_row({"sku": "AB-1", "name": "x", "category": "y"}, "x.csv")
    assert p.visibility == "internal" and p.price_visibility == "internal"


def test_public_text_with_internal_price_is_rejected(tmp_path: Path):
    (tmp_path / "products.csv").write_text(
        "sku,name,category,price,currency,price_visibility,visibility\n"
        "AB-1,Thing,misc,4321.00,USD,internal,public\n"
    )
    (tmp_path / "leak.md").write_text("---\nsku: AB-1\nvisibility: public\n---\n# Thing\n\nOnly 4,321 USD!\n")
    report = load_catalog(tmp_path, MemoryCatalog(HashEmbedder()))
    assert any(r["reason"] == "internal price in public text" for r in report.rejects)


def test_markdown_spec_table():
    md = "## Specifications\n\n| Spec | Value |\n|---|---|\n| Weight | 2 kg |\n\n## Notes\n"
    assert specs_from_markdown(md) == {"Weight": "2 kg"}


def test_model_number_lookup_ranks_first(store):
    hits = store.search("specs of KI-PM-500", "public")
    assert hits[0].chunk.sku == "KI-PM-500"


def test_search_by_need_spanish(store):
    hits = store.search("ultrasonido portátil", "public")
    assert any(h.chunk.sku and h.chunk.sku.startswith("VM-US") for h in hits[:3])


def test_public_never_sees_internal_rows(store):
    assert store.get_product("VM-US-9X", "public") is None
    assert store.get_product("VM-US-9X", "internal") is not None
    for q in ["SonoLite 9X preview", "sales notes distributors discount", "refurbished ventilator"]:
        for h in store.search(q, "public", k=8):
            assert h.chunk.visibility == "public"
            assert h.chunk.sku not in {"VM-US-9X", "QB-VT-40R"}
    assert all(p.visibility == "public" for p in store.list_products("public"))


def test_internal_sees_sales_notes(store):
    hits = store.search("sales notes distributors discount", "internal", k=8)
    assert any("sales_notes" in h.chunk.source for h in hits)
