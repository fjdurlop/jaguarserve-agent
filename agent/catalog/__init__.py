"""Catalog records, role visibility and the store interface.

Visibility is enforced inside every store query (SQL `WHERE` / list filter), never only in the prompt.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

ROLES = ("public", "internal")


def visible_to(role: str) -> tuple[str, ...]:
    """Visibility tags a role may read."""
    return ("public", "internal") if role == "internal" else ("public",)


@dataclass
class Product:
    sku: str
    name: str
    category: str
    manufacturer: str
    summary: str
    specs: dict[str, str] = field(default_factory=dict)
    price: float | None = None
    currency: str | None = None
    price_valid_until: date | None = None
    price_visibility: str = "internal"
    stock: int | None = None
    stock_location: str | None = None
    stock_as_of: date | None = None
    visibility: str = "public"
    source: str = ""


@dataclass
class Chunk:
    id: str
    sku: str | None
    title: str
    text: str
    source: str
    visibility: str
    lang: str = ""
    page: int | None = None
    embedding: list[float] | None = None


@dataclass
class Hit:
    chunk: Chunk
    score: float


class CatalogStore(Protocol):
    embedder_name: str

    def upsert_products(self, products: list[Product]) -> None: ...
    def replace_chunks(self, source: str, chunks: list[Chunk]) -> None: ...
    def get_product(self, sku_or_name: str, role: str) -> Product | None: ...
    def list_products(self, role: str) -> list[Product]: ...
    def search(self, query: str, role: str, k: int = 6, category: str | None = None) -> list[Hit]: ...
    def internal_prices(self) -> set[float]: ...
    def ping(self) -> bool: ...
