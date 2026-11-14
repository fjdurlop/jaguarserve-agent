"""BM25 and reciprocal-rank fusion for the in-memory store."""

import math
from collections import Counter

from agent.text import terms


def bm25_scores(query: str, docs: list[str], k1: float = 1.4, b: float = 0.75) -> list[float]:
    q = terms(query)
    toks = [terms(d) for d in docs]
    if not docs or not q:
        return [0.0] * len(docs)
    avg = sum(map(len, toks)) / len(toks) or 1.0
    df = Counter(t for doc in toks for t in set(doc))
    n = len(docs)
    out = []
    for doc in toks:
        tf = Counter(doc)
        score = 0.0
        for term in q:
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * tf[term] * (k1 + 1) / (tf[term] + k1 * (1 - b + b * len(doc) / avg))
        out.append(score)
    return out


def rrf(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    """Fuse ranked id lists: score = sum 1 / (k + rank)."""
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            fused[item] = fused.get(item, 0.0) + 1.0 / (k + rank + 1)
    return fused
