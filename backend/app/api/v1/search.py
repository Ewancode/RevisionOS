"""Global search: passages from your materials, plus modules, topics and files
by name (ARCHITECTURE.md section 7, "Global search")."""

import uuid
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.api.deps import Config, CurrentUser, DbSession
from app.retrieval.search import Scope, SearchService
from app.schemas.search import NamedDocument, NamedModule, NamedTopic, PassageOut, SearchOut

router = APIRouter(tags=["search"])


@router.get("/search", response_model=SearchOut)
async def search(
    request: Request,
    db: DbSession,
    user: CurrentUser,
    config: Config,
    q: Annotated[str, Query(min_length=1, max_length=300)],
    year_id: uuid.UUID | None = None,
    module_id: uuid.UUID | None = None,
    topic_id: uuid.UUID | None = None,
) -> SearchOut:
    service = SearchService(db, user.id, request.app.state.embedder, config.retrieval.search)
    result = await service.search(q, Scope(year_id, module_id, topic_id))
    return SearchOut(
        query=q.strip(),
        scope_used=result.scope_used,
        widened=result.widened,
        passages=[PassageOut.model_validate(asdict(p)) for p in result.passages],
        modules=[NamedModule.model_validate(m) for m in result.modules],
        topics=[NamedTopic.model_validate(t) for t in result.topics],
        documents=[NamedDocument.model_validate(d) for d in result.documents],
    )
