"""In-memory catalog store: tests and the no-database demo (`STORE=memory`)."""

from agent.catalog import Chunk, Hit, Product, visible_to
from agent.catalog.rank import bm25_scores, rrf
from agent.embeddings import Embedder, cosine
from agent.text import fold, tokens


class MemoryCatalog:
    def __init__(self, embedder: Embedder):
        self.embedder = embedder
        self.embedder_name = embedder.name
        self.products: dict[str, Product] = {}
        self.chunks: dict[str, Chunk] = {}

    def upsert_products(self, products: list[Product]) -> None:
        for p in products:
            self.products[p.sku] = p

    def replace_chunks(self, source: str, chunks: list[Chunk]) -> None:
        self.chunks = {cid: c for cid, c in self.chunks.items() if c.source != source}
        missing = [c for c in chunks if c.embedding is None]
        for c, vec in zip(
            missing, self.embedder.embed([c.title + "\n" + c.text for c in missing]), strict=True
        ):
            c.embedding = vec
        self.chunks.update({c.id: c for c in chunks})

    def get_product(self, sku_or_name: str, role: str) -> Product | None:
        allowed = visible_to(role)
        key = fold(sku_or_name.strip())
        for p in self.products.values():
            if p.visibility in allowed and key in (fold(p.sku), fold(p.name)):
                return p
        return None

    def list_products(self, role: str) -> list[Product]:
        allowed = visible_to(role)
        return [p for p in self.products.values() if p.visibility in allowed]

    def search(self, query: str, role: str, k: int = 6, category: str | None = None) -> list[Hit]:
        allowed = visible_to(role)
        pool = [c for c in self.chunks.values() if c.visibility in allowed]
        if category:
            cats = {p.sku for p in self.products.values() if fold(p.category) == fold(category)}
            pool = [c for c in pool if c.sku in cats]
        if not pool:
            return []
        qtok = set(tokens(query))
        exact = [c.id for c in pool if c.sku and fold(c.sku) in qtok]
        lexical = bm25_scores(query, [c.title + " " + c.text for c in pool])
        qvec = self.embedder.embed([query])[0]
        by_lex = [c.id for s, c in sorted(zip(lexical, pool, strict=True), key=lambda x: -x[0]) if s > 0]
        by_vec = sorted(pool, key=lambda c: -cosine(qvec, c.embedding or qvec))
        fused = rrf([exact, by_lex[:20], [c.id for c in by_vec[:20]]])
        for cid in exact:  # an exact model number always ranks first
            fused[cid] += 1.0
        best = sorted(fused.items(), key=lambda x: -x[1])[:k]
        return [Hit(self.chunks[cid], score) for cid, score in best]

    def internal_prices(self) -> set[float]:
        return {
            p.price
            for p in self.products.values()
            if p.price is not None and (p.price_visibility == "internal" or p.visibility == "internal")
        }

    def ping(self) -> bool:
        return True
