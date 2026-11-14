"""File parsers. PDF and XLSX need the optional `docs` extra (`uv sync --extra docs`)."""

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from agent.search import html_to_text

VISIBILITIES = ("public", "internal")


@dataclass
class Doc:
    source: str
    title: str
    text: str
    visibility: str
    lang: str = ""
    sku: str | None = None
    page: int | None = None


def _front_matter(raw: str) -> tuple[dict[str, str], str]:
    m = re.match(r"---\n(.*?)\n---\n", raw, re.S)
    if not m:
        return {}, raw
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip()
    return meta, raw[m.end() :]


def _vis(value: str | None) -> str:
    return value if value in VISIBILITIES else "internal"  # fail closed


def parse_doc(path: Path, root: Path) -> Doc | None:
    rel = str(path.relative_to(root))
    suffix = path.suffix.lower()
    if suffix in (".md", ".txt"):
        meta, body = _front_matter(path.read_text(encoding="utf-8"))
        title = meta.get("title") or next(
            (ln[2:] for ln in body.splitlines() if ln.startswith("# ")), path.stem
        )
        return Doc(
            rel, title, body, _vis(meta.get("visibility")), meta.get("lang", ""), meta.get("sku") or None
        )
    if suffix in (".html", ".htm"):
        raw = path.read_text(encoding="utf-8", errors="replace")
        vis = re.search(r'<meta\s+name="visibility"\s+content="(\w+)"', raw)
        title, text = html_to_text(raw)
        return Doc(rel, title or path.stem, text, _vis(vis.group(1) if vis else None))
    if suffix == ".pdf":
        from pypdf import PdfReader  # optional

        reader = PdfReader(str(path))
        text = "\n\n".join(
            f"## Page {i + 1}\n\n{page.extract_text() or ''}" for i, page in enumerate(reader.pages)
        )
        sku = path.stem if re.fullmatch(r"[A-Z0-9][A-Z0-9-]{2,31}", path.stem) else None
        # PDFs carry no visibility tag: internal unless placed under a "public" folder
        vis = "public" if "public" in path.relative_to(root).parts else "internal"
        return Doc(rel, path.stem, text, vis, sku=sku)
    return None


def read_product_rows(path: Path) -> list[dict[str, str]]:
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as f:
            return [
                {k.strip().lower(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)
            ]
    if path.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook  # optional

        ws = load_workbook(path, read_only=True, data_only=True).active
        rows = list(ws.iter_rows(values_only=True))
        head = [str(h).strip().lower() for h in rows[0]]
        return [
            {h: "" if v is None else str(v).strip() for h, v in zip(head, r, strict=False)} for r in rows[1:]
        ]
    return []


def specs_from_markdown(text: str) -> dict[str, str]:
    """Rows of the first two-column table under a Specifications/Especificaciones heading."""
    m = re.search(r"## (Specifications|Especificaciones)\s*\n(.*?)(\n## |\Z)", text, re.S)
    if not m:
        return {}
    specs = {}
    for line in m.group(2).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 2 and cells[0] and not set(cells[0]) <= {"-"} and cells[0].lower() != "spec":
            specs[cells[0]] = cells[1]
    return specs
