"""Hybrid search over a user's chunks, plus name search over their structure
(ARCHITECTURE.md section 7, "Retrieval at question time", steps 1, 3, 5, 7).

keyword (Postgres full text, OR of query terms) + meaning (pgvector cosine)
-> weighted Reciprocal Rank Fusion -> source-tier boost -> relevance floor
-> best chunk per page. Scoped searches widen (topic -> module -> year -> all)
when they find too little. Every query is filtered by the owner.
"""

import uuid
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import Select, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import SearchConfig
from app.models import Chunk, Document, Module, Topic
from app.retrieval.embeddings import EmbeddingProvider

ScopeLevel = Literal["topic", "module", "year", "all"]
_SCOPES: list[ScopeLevel] = ["topic", "module", "year", "all"]


@dataclass(frozen=True)
class Scope:
    year_id: uuid.UUID | None = None
    module_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None

    def level(self) -> ScopeLevel:
        if self.topic_id:
            return "topic"
        if self.module_id:
            return "module"
        if self.year_id:
            return "year"
        return "all"

    def widen(self) -> "Scope | None":
        """The next scope up, or None at the top. Widening a module search
        keeps its year (if given), then drops everything."""
        level = self.level()
        if level == "topic":
            return Scope(self.year_id, self.module_id, None)
        if level == "module":
            return Scope(self.year_id) if self.year_id else Scope()
        if level == "year":
            return Scope()
        return None


@dataclass
class Passage:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    module_id: uuid.UUID
    module_code: str
    page_no: int
    heading_path: str
    content: str
    source_tier: str
    score: float
    matched: Literal["keyword", "meaning", "both"]


@dataclass
class SearchResult:
    passages: list[Passage]
    scope_used: ScopeLevel
    widened: bool
    modules: list[Module] = field(default_factory=list)
    topics: list[Topic] = field(default_factory=list)
    documents: list[Document] = field(default_factory=list)


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class SearchService:
    def __init__(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        embedder: EmbeddingProvider,
        config: SearchConfig,
    ) -> None:
        self.db = db
        self.user_id = user_id
        self.embedder = embedder
        self.config = config

    # --- candidates -----------------------------------------------------------

    def _scoped(self, stmt: Select, scope: Scope) -> Select:  # type: ignore[type-arg]
        stmt = (
            stmt.join(Document, Document.id == Chunk.document_id)
            .join(Module, Module.id == Chunk.module_id)
            .where(
                Chunk.user_id == self.user_id,
                Document.deleted_at.is_(None),
                Module.deleted_at.is_(None),
            )
        )
        if scope.topic_id:
            stmt = stmt.where(Chunk.topic_id == scope.topic_id)
        if scope.module_id:
            stmt = stmt.where(Chunk.module_id == scope.module_id)
        if scope.year_id:
            stmt = stmt.where(Module.academic_year_id == scope.year_id)
        return stmt

    async def _tsquery(self, query: str) -> str | None:
        """OR of the query's stemmed terms. Postgres's websearch syntax ANDs
        every word, which fails natural questions; ranking still rewards
        chunks that match more terms."""
        lexemes = await self.db.scalar(
            select(func.tsvector_to_array(func.to_tsvector("english", query)))
        )
        if not lexemes:
            return None
        return " | ".join("'" + lex.replace("'", "''") + "'" for lex in lexemes)

    async def _keyword(self, query: str, scope: Scope) -> list[uuid.UUID]:
        ts = await self._tsquery(query)
        if ts is None:
            return []
        tsq = func.to_tsquery("simple", ts)
        stmt = self._scoped(select(Chunk.id), scope).where(Chunk.tsv.op("@@")(tsq))
        stmt = stmt.order_by(func.ts_rank_cd(Chunk.tsv, tsq).desc()).limit(
            self.config.keyword_candidates
        )
        return list((await self.db.scalars(stmt)).all())

    async def _vector(self, vector: list[float], scope: Scope) -> list[tuple[uuid.UUID, float]]:
        # Iterative index scans keep returning neighbours until the owner/scope
        # filters are satisfied, instead of filtering a fixed top-k (pgvector >= 0.8).
        await self.db.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        distance = Chunk.embedding.cosine_distance(vector)
        stmt = self._scoped(select(Chunk.id, (1 - distance).label("similarity")), scope)
        stmt = stmt.order_by(distance).limit(self.config.vector_candidates)
        return [(row.id, float(row.similarity)) for row in (await self.db.execute(stmt)).all()]

    # --- fusion ---------------------------------------------------------------

    def fuse(
        self,
        keyword: list[uuid.UUID],
        vector: list[tuple[uuid.UUID, float]],
    ) -> list[tuple[uuid.UUID, float, Literal["keyword", "meaning", "both"]]]:
        """Weighted RRF, then the relevance floor for meaning-only matches."""
        k = self.config.rrf_k
        scores: dict[uuid.UUID, float] = {}
        for rank, chunk_id in enumerate(keyword, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + self.config.keyword_weight / (k + rank)
        similarity = dict(vector)
        for rank, (chunk_id, _) in enumerate(vector, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
        keyword_set = set(keyword)
        fused = []
        for chunk_id, score in scores.items():
            in_kw, in_vec = chunk_id in keyword_set, chunk_id in similarity
            if not in_kw and similarity[chunk_id] < self.config.min_vector_similarity:
                continue  # found only by meaning, and not similar enough
            matched: Literal["keyword", "meaning", "both"] = (
                "both" if in_kw and in_vec else "keyword" if in_kw else "meaning"
            )
            fused.append((chunk_id, score, matched))
        return sorted(fused, key=lambda item: -item[1])

    async def _passages_in(self, query: str, vector: list[float], scope: Scope) -> list[Passage]:
        fused = self.fuse(await self._keyword(query, scope), await self._vector(vector, scope))
        if not fused:
            return []
        ids = [chunk_id for chunk_id, _, _ in fused]
        rows = {
            row.Chunk.id: row
            for row in (
                await self.db.execute(
                    select(Chunk, Document.original_filename, Module.code)
                    .join(Document, Document.id == Chunk.document_id)
                    .join(Module, Module.id == Chunk.module_id)
                    .where(Chunk.id.in_(ids), Chunk.user_id == self.user_id)
                )
            ).all()
        }
        tiers = self.config.tier_weights.model_dump()
        passages = []
        for chunk_id, score, matched in fused:
            row = rows.get(chunk_id)
            if row is None:
                continue
            chunk = row.Chunk
            passages.append(
                Passage(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    filename=row.original_filename,
                    module_id=chunk.module_id,
                    module_code=row.code,
                    page_no=chunk.page_no,
                    heading_path=chunk.heading_path,
                    content=chunk.content,
                    source_tier=chunk.source_tier,
                    score=score * tiers.get(chunk.source_tier, 1.0),
                    matched=matched,
                )
            )
        passages.sort(key=lambda p: -p.score)
        # One result per page: the best chunk stands for it.
        seen: set[tuple[uuid.UUID, int]] = set()
        best = []
        for passage in passages:
            key = (passage.document_id, passage.page_no)
            if key not in seen:
                seen.add(key)
                best.append(passage)
        return best[: self.config.results]

    # --- public ---------------------------------------------------------------

    async def search(self, query: str, scope: Scope) -> SearchResult:
        """Search `scope`; if it yields too little, append results from wider
        scopes after the in-scope ones (which always stay first)."""
        query = query.strip()
        vector = await self.embedder.embed_query(query)
        passages = await self._passages_in(query, vector, scope)
        used = scope
        wider = scope.widen()
        while len(passages) < self.config.widen_below and wider is not None:
            seen = {p.chunk_id for p in passages}
            extra = [
                p for p in await self._passages_in(query, vector, wider) if p.chunk_id not in seen
            ]
            if extra:
                passages = (passages + extra)[: self.config.results]
                used = wider
            wider = wider.widen()
        result = SearchResult(passages, used.level(), used != scope)
        await self._names(query, result)
        return result

    async def _names(self, query: str, result: SearchResult) -> None:
        """Modules, topics and files whose names contain the query."""
        like = _like(query)
        limit = 5
        result.modules = list(
            (
                await self.db.scalars(
                    select(Module)
                    .where(
                        Module.user_id == self.user_id,
                        Module.deleted_at.is_(None),
                        (Module.code.ilike(like)) | (Module.title.ilike(like)),
                    )
                    .order_by(Module.code)
                    .limit(limit)
                )
            ).all()
        )
        result.topics = list(
            (
                await self.db.scalars(
                    select(Topic)
                    .join(Module, Module.id == Topic.module_id)
                    .where(
                        Topic.user_id == self.user_id,
                        Topic.deleted_at.is_(None),
                        Module.deleted_at.is_(None),
                        Topic.title.ilike(like),
                    )
                    .order_by(Topic.title)
                    .limit(limit)
                )
            ).all()
        )
        result.documents = list(
            (
                await self.db.scalars(
                    select(Document)
                    .join(Module, Module.id == Document.module_id)
                    .where(
                        Document.user_id == self.user_id,
                        Document.deleted_at.is_(None),
                        Module.deleted_at.is_(None),
                        Document.original_filename.ilike(like),
                    )
                    .order_by(Document.original_filename)
                    .limit(limit)
                )
            ).all()
        )
