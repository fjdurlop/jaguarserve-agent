"""Catalog ingestion: product sheet (CSV/XLSX) + documents (Markdown, HTML, PDF) -> store.

Rules
- Unknown or missing visibility defaults to `internal` (fail closed).
- Chunks of an internal product are internal, whatever the document says.
- A public chunk that contains an internal-only price is rejected (price leak through text).
- Invalid product rows are rejected with a reason; nothing half-valid is stored.
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from agent.catalog import CatalogStore, Chunk, Product
from agent.text import canon_number, numbers
from ingest.parsers import Doc, parse_doc, read_product_rows, specs_from_markdown
from ingest.validate import RowError, product_from_row

DOC_SUFFIXES = {".md", ".txt", ".html", ".htm", ".pdf"}


@dataclass
class Report:
    products: int = 0
    documents: int = 0
    chunks: int = 0
    rejects: list[dict] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"products={self.products} documents={self.documents} chunks={self.chunks} "
            f"rejects={len(self.rejects)}"
        )


def chunk_doc(doc: Doc, max_chars: int = 1200) -> list[tuple[str, str]]:
    """Short docs stay whole (one chunk keeps product context). Longer ones split on '## ' headings,
    long sections on paragraphs. Returns (heading, text)."""
    body = "\n".join(ln for ln in doc.text.splitlines() if not ln.startswith("# ")).strip()
    if len(body) <= max_chars:
        return [("", body)] if body else []
    sections: list[tuple[str, list[str]]] = [("", [])]
    for line in doc.text.splitlines():
        if line.startswith("## "):
            sections.append((line[3:].strip(), []))
        elif not line.startswith("# "):
            sections[-1][1].append(line)
    out = []
    for heading, lines in sections:
        buf = ""
        for para in "\n".join(lines).split("\n\n"):
            para = para.strip()
            if not para:
                continue
            if buf and len(buf) + len(para) > max_chars:
                out.append((heading, buf))
                buf = ""
            buf = f"{buf}\n\n{para}".strip()
        if buf:
            out.append((heading, buf))
    return out


def load_catalog(root: Path, store: CatalogStore, dry_run: bool = False) -> Report:
    root = Path(root)
    report = Report()
    products: dict[str, Product] = {}
    for path in sorted(root.glob("products.*")):
        for i, row in enumerate(read_product_rows(path), start=2):
            try:
                p = product_from_row(row, source=str(path.relative_to(root)))
                products[p.sku] = p
            except RowError as exc:
                report.rejects.append({"file": path.name, "row": i, "reason": str(exc)})

    docs = [
        parse_doc(p, root)
        for p in sorted(root.rglob("*"))
        if p.suffix.lower() in DOC_SUFFIXES and p.is_file()
    ]
    docs = [d for d in docs if d is not None]
    for d in sorted(docs, key=lambda d: d.lang != "en"):  # English sheet wins for structured specs
        if d.sku in products and not products[d.sku].specs:
            products[d.sku].specs = specs_from_markdown(d.text)

    internal_prices = {
        canon_number(f"{p.price:.2f}")
        for p in products.values()
        if p.price is not None and (p.price_visibility == "internal" or p.visibility == "internal")
    }
    report.products = len(products)
    if not dry_run:
        store.upsert_products(list(products.values()))

    for d in docs:
        if d.sku and d.sku not in products:
            report.rejects.append({"file": d.source, "reason": f"unknown sku {d.sku}"})
            continue
        vis = d.visibility
        if d.sku and products[d.sku].visibility == "internal":
            vis = "internal"
        chunks = []
        for idx, (heading, text) in enumerate(chunk_doc(d)):
            if vis == "public" and internal_prices & set(numbers(text)):
                report.rejects.append(
                    {"file": d.source, "chunk": idx, "reason": "internal price in public text"}
                )
                continue
            cid = hashlib.sha1(f"{d.source}#{idx}".encode(), usedforsecurity=False).hexdigest()[:16]
            title = f"{d.title} — {heading}" if heading else d.title
            chunks.append(
                Chunk(
                    id=cid,
                    sku=d.sku,
                    title=title,
                    text=text,
                    source=d.source,
                    visibility=vis,
                    lang=d.lang,
                    page=d.page,
                )
            )
        report.documents += 1
        report.chunks += len(chunks)
        if not dry_run:
            store.replace_chunks(d.source, chunks)
    return report
