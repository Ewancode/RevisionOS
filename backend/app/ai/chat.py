"""The assistant's answer to one message (ARCHITECTURE.md sections 7-9).

1. Retrieve passages for the message from where the student is asking
   (no model call), and send them with the question as citable
   `search_result` blocks. If nothing clears the relevance floor, Claude is
   told so plainly.
2. Run the agent loop: stream Claude's reply; when it asks for tools, run
   them (it can search again with a better query, read a whole page, list
   materials or request a deletion) and continue, up to
   `chat.max_model_calls` calls, each checked against the budget.
3. Keep only citations that point at passages the server actually sent
   (same position and same source id); log and drop anything else.
4. Compute the provenance badge from the verified citations, never from
   what Claude says it used, and save the answer.

The caller receives events to stream to the browser.
"""

import asyncio
import json
import logging
import re
import uuid
from collections.abc import AsyncGenerator
from contextlib import aclosing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import tools
from app.ai.client import ClaudeClient, StreamedReply, TextDelta, text_tokens
from app.ai.tools import Source, ToolContext
from app.core.clock import utcnow
from app.core.config import AppConfig
from app.core.errors import AppError
from app.models import Conversation, Message, Module, PendingAction, Topic
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.search import Scope, SearchService
from app.services.common import ClientInfo
from app.workers.queue import JobQueue

logger = logging.getLogger(__name__)

TASK = "chat"
PROMPT_VERSION = "chat.v2"
PROMPT_FILE = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.md"
CITE_MARKER = re.compile(r" ?\[\[\d+\]\]\(#cite-\d+\)")


def system_prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8")


# --- events for the browser ---------------------------------------------------------


@dataclass(frozen=True)
class Status:
    text: str


@dataclass(frozen=True)
class Delta:
    text: str


@dataclass(frozen=True)
class ActionRequested:
    action: PendingAction


@dataclass(frozen=True)
class LinkAdded:
    link: dict[str, Any]


@dataclass(frozen=True)
class Done:
    message: Message


@dataclass(frozen=True)
class Failed:
    code: str
    message: str
    saved: Message


ChatEvent = Status | Delta | ActionRequested | LinkAdded | Done | Failed


# --- building the answer ---------------------------------------------------------------


@dataclass
class Answer:
    """The answer as it is assembled, with verified citations numbered by page."""

    max_quote: int
    parts: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    _numbers: dict[str, int] = field(default_factory=dict)
    dropped: int = 0

    def _number(self, source: Source, quote: str) -> int:
        if source.source not in self._numbers:
            self.citations.append(
                {
                    "n": len(self.citations) + 1,
                    "document_id": str(source.document_id),
                    "filename": source.filename,
                    "page_no": source.page_no,
                    "source_tier": source.source_tier,
                    "module_code": source.module_code,
                    "heading_path": source.heading_path,
                    "quote": quote[: self.max_quote],
                }
            )
            self._numbers[source.source] = len(self.citations)
        return self._numbers[source.source]

    def add_text_block(self, block: Any, sources: list[Source]) -> None:
        text: str = block.text
        numbers: list[int] = []
        for citation in getattr(block, "citations", None) or []:
            source = verify(citation, sources)
            if source is None:
                self.dropped += 1
                continue
            n = self._number(source, str(getattr(citation, "cited_text", "")))
            if n not in numbers:
                numbers.append(n)
        if numbers:
            # Markers go after the cited text, before any trailing whitespace.
            stripped = text.rstrip()
            markers = "".join(f"[[{n}]](#cite-{n})" for n in numbers)
            text = f"{stripped} {markers}{text[len(stripped) :]}"
        self.parts.append(text)

    def separate_rounds(self) -> None:
        """Text from separate calls of the loop are separate paragraphs."""
        if self.parts and not self.parts[-1].endswith("\n\n"):
            self.parts.append("\n\n")

    @property
    def content(self) -> str:
        return "".join(self.parts).strip()

    @property
    def provenance(self) -> list[str]:
        tiers = sorted({c["source_tier"] for c in self.citations})
        return tiers or ["general"]


def verify(citation: Any, sources: list[Source]) -> Source | None:
    """A citation counts only if it points at a passage we sent, at the
    position we sent it, under the same source id."""
    if getattr(citation, "type", None) != "search_result_location":
        return None
    index = getattr(citation, "search_result_index", None)
    if not isinstance(index, int) or not 0 <= index < len(sources):
        logger.warning("citation dropped: index out of range", extra={"index": index})
        return None
    source = sources[index]
    if getattr(citation, "source", None) != source.source:
        logger.warning("citation dropped: source mismatch", extra={"index": index})
        return None
    return source


def echo_content(content: list[Any]) -> list[Any]:
    """The assistant turn to send back on the next call of the loop:
    unchanged, except that after a mid-answer server-side fallback, blocks
    other than text before the last `fallback` marker are omitted (as the
    API requires)."""
    marks = [i for i, b in enumerate(content) if getattr(b, "type", None) == "fallback"]
    if not marks:
        return list(content)
    last = marks[-1]
    return [b for i, b in enumerate(content) if i >= last or getattr(b, "type", None) == "text"]


# --- the orchestrator ------------------------------------------------------------------


class ChatOrchestrator:
    def __init__(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        client: ClientInfo,
        *,
        claude: ClaudeClient,
        embedder: EmbeddingProvider,
        config: AppConfig,
        jobs: JobQueue | None = None,
    ) -> None:
        self.jobs = jobs
        self.db = db
        self.user_id = user_id
        self.client = client
        self.claude = claude
        self.embedder = embedder
        self.config = config
        self.chat = config.ai.chat

    async def _scope(self, conversation: Conversation) -> tuple[Scope, str | None]:
        """Where the student is asking from, and a description for Claude."""
        if conversation.topic_id:
            topic = await self.db.get(Topic, conversation.topic_id)
            module = await self.db.get(Module, topic.module_id) if topic else None
            if topic and module and topic.deleted_at is None and module.deleted_at is None:
                where = f"the topic “{topic.title}” in {module.code} {module.title}"
                return Scope(module.academic_year_id, module.id, topic.id), where
        if conversation.module_id:
            module = await self.db.get(Module, conversation.module_id)
            if module and module.deleted_at is None:
                where = f"the module {module.code} {module.title}"
                return Scope(module.academic_year_id, module.id), where
        return Scope(), None

    async def _history(self, conversation_id: uuid.UUID, before: uuid.UUID) -> list[dict[str, Any]]:
        """Earlier messages as plain text (passages and tool calls are not
        resent; Claude searches again when it needs them)."""
        rows = (
            await self.db.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id, Message.id != before)
                .order_by(Message.created_at.desc())
                .limit(self.chat.history_messages)
            )
        ).all()
        history = []
        for message in reversed(rows):
            text = CITE_MARKER.sub("", message.content).strip()
            if not text:
                continue
            history.append({"role": message.role, "content": text})
        # The conversation sent to the API must start with the student.
        while history and history[0]["role"] != "user":
            history.pop(0)
        return history

    def _question_block(self, text: str, where: str | None, found: bool) -> dict[str, Any]:
        lines = []
        if where:
            lines.append(f"The student is asking from {where}.")
        if not found:
            lines.append(
                "No passages in the student's materials matched this message. Search with "
                "different words if it is about their course; otherwise say it is not from "
                "their materials."
            )
        lines.append(f"Student's message:\n{text}")
        return {"type": "text", "text": "\n\n".join(lines)}

    async def answer(self, conversation: Conversation, text: str) -> AsyncGenerator[ChatEvent]:
        """Answer `text` in `conversation`, saving both messages."""
        question = Message(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            user_id=self.user_id,
            role="user",
            content=text,
            status="complete",
        )
        self.db.add(question)
        conversation.updated_at = utcnow()
        await self.db.commit()

        conversation_id, reply_id = conversation.id, uuid.uuid4()
        answer = Answer(self.chat.cited_text_max_chars)
        steps: list[str] = []
        scope, where = await self._scope(conversation)
        ctx = ToolContext(
            db=self.db,
            user_id=self.user_id,
            client=self.client,
            embedder=self.embedder,
            config=self.config,
            scope=scope,
            conversation_id=conversation.id,
            message_id=reply_id,
            jobs=self.jobs,
        )
        streamed: list[str] = []

        async def save(status: str, error_code: str | None = None) -> Message:
            content = answer.content
            if status != "complete" and not content:
                content = "".join(streamed).strip()
            message = Message(
                id=reply_id,
                conversation_id=conversation_id,
                user_id=self.user_id,
                role="assistant",
                content=content,
                citations=answer.citations,
                provenance=answer.provenance if answer.citations or content else [],
                steps=steps,
                links=ctx.links,
                status=status,
                error_code=error_code,
            )
            self.db.add(message)
            # By id: after a rollback the loaded conversation is expired.
            await self.db.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(updated_at=utcnow())
            )
            await self.db.commit()
            return message

        try:
            steps.append("Searching your materials")
            yield Status(steps[-1])
            search = SearchService(
                self.db, self.user_id, self.embedder, self.config.retrieval.search
            )
            found = (await search.search(text, scope)).passages
            blocks = [ctx.add_source(p) for p in found]
            history = await self._history(conversation.id, question.id)
            messages = [
                *history,
                {
                    "role": "user",
                    "content": [*blocks, self._question_block(text, where, bool(found))],
                },
            ]
            system = system_prompt()
            definitions = tools.definitions()
            fixed_tokens = text_tokens(system) + text_tokens(json.dumps(definitions))

            for call in range(self.chat.max_model_calls):
                final_call = call == self.chat.max_model_calls - 1
                reply: StreamedReply | None = None
                # aclosing: if the student stops the answer, the call is closed
                # (and its usage recorded) before the stopped answer is saved.
                async with aclosing(
                    self.claude.stream(
                        self.db,
                        user_id=self.user_id,
                        task=TASK,
                        prompt_version=PROMPT_VERSION,
                        system=system,
                        messages=messages,
                        tools=definitions,
                        estimated_input_tokens=fixed_tokens
                        + text_tokens(json.dumps(messages, default=str)),
                        final_call=final_call,
                        module_id=scope.module_id,
                    )
                ) as replies:
                    async for event in replies:
                        if isinstance(event, TextDelta):
                            streamed.append(event.text)
                            yield Delta(event.text)
                        else:
                            reply = event
                if reply is None:  # the client always ends with the reply
                    raise RuntimeError("stream ended without a reply")

                if reply.stop_reason == "refusal":
                    # A refused partial answer is discarded, not shown as complete.
                    answer.parts.clear()
                    answer.citations.clear()
                    saved = await save("error", "ai_refused")
                    yield Failed("ai_refused", "Claude declined to answer this.", saved)
                    return

                content = list(reply.message.content)
                for block in content:
                    if getattr(block, "type", None) == "text":
                        answer.add_text_block(block, ctx.sources)
                calls = [b for b in content if getattr(b, "type", None) == "tool_use"]

                if reply.stop_reason == "max_tokens":
                    answer.parts.append("\n\n*(This answer was cut off at the length limit.)*")
                    break
                if reply.stop_reason != "tool_use" or not calls or final_call:
                    break

                results = []
                for block in calls:
                    prepared = tools.prepare(block.name, block.input)
                    if prepared.status:
                        steps.append(prepared.status)
                        yield Status(prepared.status)
                    before, links_before = len(ctx.actions), len(ctx.links)
                    output = await tools.run(ctx, prepared)
                    for action in ctx.actions[before:]:
                        yield ActionRequested(action)
                    for link in ctx.links[links_before:]:
                        yield LinkAdded(link)
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": output.content,
                            "is_error": output.is_error,
                        }
                    )
                messages.append({"role": "assistant", "content": echo_content(content)})
                messages.append({"role": "user", "content": results})
                answer.separate_rounds()

            if answer.dropped:
                logger.warning("unverified citations dropped", extra={"count": answer.dropped})
            yield Done(await save("complete"))
        except AppError as exc:
            yield Failed(exc.code, exc.message, await save("error", exc.code))
        except (asyncio.CancelledError, GeneratorExit):
            # Stopped by the student (or the connection dropped): keep what
            # they saw, marked as stopped.
            try:
                await self.db.rollback()
                await save("stopped")
            except Exception:  # best effort while unwinding
                logger.exception("could not save a stopped answer")
            raise
