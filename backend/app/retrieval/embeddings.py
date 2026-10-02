"""Embedding providers behind one interface (ARCHITECTURE.md section 7).

The default runs a local ONNX model (fastembed), so embedding is free,
private and needs no second vendor. Swapping to a hosted model means one new
class, plus `make reindex` because every vector records its model.
"""

import asyncio
import hashlib
import math
import re
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from app.core.config import EmbeddingsConfig

if TYPE_CHECKING:
    from fastembed import TextEmbedding


class EmbeddingProvider(Protocol):
    model_name: str
    dimensions: int

    async def embed_passages(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class FastEmbedProvider:
    """Local BGE model. Loaded on first use (the first use downloads it)."""

    def __init__(self, config: EmbeddingsConfig, cache_dir: Path) -> None:
        self.model_name = config.model
        self.dimensions = config.dimensions
        self._config = config
        self._cache_dir = cache_dir
        self._model: TextEmbedding | None = None
        self._lock = threading.Lock()

    def _load(self) -> "TextEmbedding":
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding

                self._cache_dir.mkdir(parents=True, exist_ok=True)
                self._model = TextEmbedding(self.model_name, cache_dir=str(self._cache_dir))
            return self._model

    def _passages(self, texts: Sequence[str]) -> list[list[float]]:
        model = self._load()
        vectors = model.embed(list(texts), batch_size=self._config.batch_size)
        return [[float(x) for x in v] for v in vectors]

    def _query(self, text: str) -> list[float]:
        # query_embed applies the model's own query handling; it is what the
        # retrieval evaluation measured.
        vector = next(iter(self._load().query_embed([text])))
        return [float(x) for x in vector]

    async def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return await asyncio.to_thread(self._passages, texts)

    async def embed_query(self, text: str) -> list[float]:
        return await asyncio.to_thread(self._query, text)

    async def warm_up(self) -> None:
        await asyncio.to_thread(self._load)


_WORD = re.compile(r"[a-z0-9]+")


class HashingProvider:
    """Deterministic bag-of-words vectors for tests: texts sharing words are
    similar, so the vector path is exercised without downloading a model."""

    model_name = "test/hashing-bow"

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        for word in _WORD.findall(text.lower()):
            digest = hashlib.sha256(word.encode()).digest()
            vec[int.from_bytes(digest[:4], "big") % self.dimensions] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    async def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


def create_provider(config: EmbeddingsConfig, cache_dir: Path) -> FastEmbedProvider:
    return FastEmbedProvider(config, cache_dir)
