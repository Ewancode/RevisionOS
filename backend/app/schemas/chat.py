import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from app.schemas.common import Input, Output
from app.schemas.documents import SourceTier

Provenance = Literal["university", "own", "general"]


class ConversationCreate(Input):
    """Start a conversation, optionally from a module or topic (searches
    start there and widen when they find little)."""

    module_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None


class ConversationOut(Output):
    id: uuid.UUID
    title: str
    module_id: uuid.UUID | None
    topic_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class CitationOut(Output):
    n: int
    document_id: uuid.UUID
    filename: str
    page_no: int
    source_tier: SourceTier
    module_code: str
    heading_path: str
    quote: str


class PendingActionOut(Output):
    id: uuid.UUID
    action: Literal["delete_document", "delete_topic", "delete_module"]
    preview: str
    status: Literal["pending", "confirmed", "cancelled", "expired"]
    expires_at: datetime


class MessageOut(Output):
    id: uuid.UUID
    role: Literal["user", "assistant"]
    # Markdown with LaTeX. Assistant answers mark citations as
    # `[[n]](#cite-n)`, referring to citations[n-1].
    content: str
    citations: list[CitationOut]
    provenance: list[Provenance]
    steps: list[str]
    status: Literal["complete", "stopped", "error"]
    error_code: str | None
    created_at: datetime
    actions: list[PendingActionOut] = Field(default_factory=list)


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class MessageCreate(Input):
    # The configured limit (ai.yaml chat.max_message_chars) is checked by the
    # service; this is only a hard ceiling.
    content: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)
    ]


# --- AI usage dashboard --------------------------------------------------------------


class UsageTotals(Output):
    requests: int
    blocked_requests: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost: float


class UsageBreakdown(Output):
    key: str
    label: str
    requests: int
    tokens: int
    cost: float


class UsageDay(Output):
    day: date
    requests: int
    cost: float


class UsageOut(Output):
    currency: str
    days: int
    since: date
    totals: UsageTotals
    by_feature: list[UsageBreakdown]
    by_model: list[UsageBreakdown]
    by_module: list[UsageBreakdown]
    by_day: list[UsageDay]
