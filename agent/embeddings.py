"""Text embeddings on CPU, so retrieval works while the GPU is scaled to zero.

- "hash": deterministic hashed bag of words + character trigrams. No download; used in tests
  and for a quick offline demo. Good at keyword overlap, weak at meaning.
- any other name: a fastembed (ONNX) model, e.g.
  "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2" (384 dims, es/en).
"""

import hashlib
import math
from functools import lru_cache
from typing import Protocol

from agent.text import tokens

DIM = 384


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    name = "hash"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * DIM
        for tok in tokens(text):
            feats = [tok] + [tok[i : i + 3] for i in range(max(1, len(tok) - 2))]
            for feat in feats:
                digest = hashlib.blake2b(feat.encode(), digest_size=8).digest()
                idx = int.from_bytes(digest[:4], "little") % DIM
                vec[idx] += 1.0 if digest[4] & 1 else -1.0
        return _unit(vec)


class FastEmbedder:
    def __init__(self, model: str):
        from fastembed import TextEmbedding  # optional dependency: `uv sync --extra embed`

        self.name = model
        self._model = TextEmbedding(model_name=model)

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = [_unit(list(map(float, v))) for v in self._model.embed(texts)]
        if out and len(out[0]) != DIM:
            raise ValueError(f"{self.name} returns {len(out[0])} dims; the schema expects {DIM}")
        return out


@lru_cache
def get_embedder(name: str) -> Embedder:
    return HashEmbedder() if name == "hash" else FastEmbedder(name)


def _unit(v: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))
