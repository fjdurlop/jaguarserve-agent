"""Validate one product row (from CSV/XLSX) into a Product, or raise RowError with the reason."""

import re
from datetime import date

from agent.catalog import Product

REQUIRED = ("sku", "name", "category")


class RowError(ValueError):
    pass


def _date(value: str, field: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise RowError(f"{field}: not an ISO date") from exc


def product_from_row(row: dict[str, str], source: str) -> Product:
    for f in REQUIRED:
        if not row.get(f):
            raise RowError(f"missing {f}")
    sku = row["sku"].upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{2,31}", sku):
        raise RowError("sku: use A-Z, 0-9 and '-' (3-32 chars)")

    price = None
    if row.get("price"):
        try:
            price = float(row["price"].replace(",", ""))
        except ValueError as exc:
            raise RowError("price: not a number") from exc
        if not 0 <= price < 10_000_000:
            raise RowError("price: out of range")
        if not re.fullmatch(r"[A-Z]{3}", row.get("currency", "")):
            raise RowError("currency: ISO 4217 code required with a price")

    stock = None
    if row.get("stock"):
        if not row["stock"].isdigit():
            raise RowError("stock: whole number >= 0")
        stock = int(row["stock"])

    vis, pvis = row.get("visibility") or "internal", row.get("price_visibility") or "internal"
    if vis not in ("public", "internal") or pvis not in ("public", "internal"):
        raise RowError("visibility / price_visibility: public or internal")

    return Product(
        sku=sku,
        name=row["name"],
        category=row["category"].lower(),
        manufacturer=row.get("manufacturer", ""),
        summary=row.get("summary", ""),
        price=price,
        currency=row.get("currency") or None,
        price_valid_until=_date(row.get("price_valid_until", ""), "price_valid_until"),
        price_visibility=pvis,
        stock=stock,
        stock_location=row.get("stock_location") or None,
        stock_as_of=_date(row.get("stock_as_of", ""), "stock_as_of"),
        visibility=vis,
        source=source,
    )
