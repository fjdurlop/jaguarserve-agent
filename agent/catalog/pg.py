"""Postgres + pgvector catalog store. Hybrid retrieval: exact SKU, full-text, vector, fused by RRF."""

import json

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from agent.catalog import Chunk, Hit, Product, visible_to
from agent.catalog.rank import rrf
from agent.embeddings import Embedder
from agent.text import fold, terms, tokens

_PRODUCT_COLS = (
    "sku, name, category, manufacturer, summary, specs, price, currency, price_valid_until, "
    "price_visibility, stock, stock_location, stock_as_of, visibility, source"
)


def _product(row: dict) -> Product:
    row = dict(row)
    row["price"] = float(row["price"]) if row["price"] is not None else None
    return Product(**row)


class PgCatalog:
    def __init__(self, pool: ConnectionPool, embedder: Embedder):
        self.pool = pool
        self.embedder = embedder
        self.embedder_name = embedder.name

    def upsert_products(self, products: list[Product]) -> None:
        cols = _PRODUCT_COLS.split(", ")
        sql = (
            f"INSERT INTO products ({_PRODUCT_COLS}) VALUES ({', '.join(['%s'] * len(cols))}) "  # noqa: S608
            f"ON CONFLICT (sku) DO UPDATE SET "
            + ", ".join(f"{c} = EXCLUDED.{c}" for c in cols[1:])
            + ", updated_at = now()"
        )
        with self.pool.connection() as conn:
            for p in products:
                values = [getattr(p, c) for c in cols]
                values[cols.index("specs")] = json.dumps(p.specs)
                conn.execute(sql, values)

    def replace_chunks(self, source: str, chunks: list[Chunk]) -> None:
        missing = [c for c in chunks if c.embedding is None]
        for c, vec in zip(
            missing, self.embedder.embed([c.title + "\n" + c.text for c in missing]), strict=True
        ):
            c.embedding = vec
        with self.pool.connection() as conn, conn.transaction():
            conn.execute("DELETE FROM chunks WHERE source = %s", (source,))
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO chunks (id, sku, title, text, source, page, lang, visibility, embedding, "
                    "search_text) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s)",
                    [
                        (
                            c.id,
                            c.sku,
                            c.title,
                            c.text,
                            c.source,
                            c.page,
                            c.lang,
                            c.visibility,
                            c.embedding,
                            fold(c.title + " " + c.text),
                        )
                        for c in chunks
                    ],
                )

    def get_product(self, sku_or_name: str, role: str) -> Product | None:
        with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            row = cur.execute(
                f"SELECT {_PRODUCT_COLS} FROM products "  # noqa: S608
                "WHERE visibility = ANY(%s) AND (lower(sku) = lower(%s) OR lower(name) = lower(%s))",
                (list(visible_to(role)), sku_or_name.strip(), sku_or_name.strip()),
            ).fetchone()
        return _product(row) if row else None

    def list_products(self, role: str) -> list[Product]:
        with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            rows = cur.execute(
                f"SELECT {_PRODUCT_COLS} FROM products WHERE visibility = ANY(%s) ORDER BY sku",  # noqa: S608
                (list(visible_to(role)),),
            ).fetchall()
        return [_product(r) for r in rows]

    def search(self, query: str, role: str, k: int = 6, category: str | None = None) -> list[Hit]:
        allowed = list(visible_to(role))
        cat_sql = "AND c.sku IN (SELECT sku FROM products WHERE lower(category) = lower(%(cat)s))"
        where = "c.visibility = ANY(%(vis)s) " + (cat_sql if category else "")
        params = {
            "vis": allowed,
            "cat": category,
            "q": " or ".join(terms(query)),
            "skus": [t for t in tokens(query) if "-" in t],
            "vec": self.embedder.embed([query])[0],
        }
        base = "SELECT c.id FROM chunks c WHERE " + where  # noqa: S608 - fixed SQL fragments, values bound
        with self.pool.connection() as conn:
            exact = conn.execute(base + " AND lower(c.sku) = ANY(%(skus)s)", params).fetchall()
            lexical = conn.execute(
                base + " AND c.tsv @@ websearch_to_tsquery('simple', %(q)s) "
                "ORDER BY ts_rank(c.tsv, websearch_to_tsquery('simple', %(q)s)) DESC LIMIT 20",
                params,
            ).fetchall()
            vector = conn.execute(
                base + " ORDER BY c.embedding <=> %(vec)s::vector LIMIT 20", params
            ).fetchall()
            exact_ids = [r[0] for r in exact]
            fused = rrf([exact_ids, [r[0] for r in lexical], [r[0] for r in vector]])
            for cid in exact_ids:
                fused[cid] += 1.0
            best = sorted(fused.items(), key=lambda x: -x[1])[:k]
            if not best:
                return []
            with conn.cursor(row_factory=dict_row) as cur:
                rows = cur.execute(
                    "SELECT id, sku, title, text, source, visibility, lang, page FROM chunks "
                    "WHERE id = ANY(%s) AND visibility = ANY(%s)",
                    ([cid for cid, _ in best], allowed),
                ).fetchall()
        by_id = {r["id"]: Chunk(**r) for r in rows}
        return [Hit(by_id[cid], score) for cid, score in best if cid in by_id]

    def internal_prices(self) -> set[float]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                "SELECT price FROM products WHERE price IS NOT NULL "
                "AND (price_visibility = 'internal' OR visibility = 'internal')"
            ).fetchall()
        return {float(r[0]) for r in rows}

    def ping(self) -> bool:
        try:
            with self.pool.connection(timeout=3) as conn:
                conn.execute("SELECT 1")
            return True
        except Exception:
            return False
