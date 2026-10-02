"""A scripted stand-in for the Anthropic SDK, and a job queue that records.

No test calls the real Claude API (ARCHITECTURE.md section 13).
"""

import copy
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

Responder = Callable[[dict[str, Any]], dict[str, Any]]


def transcription(markdown: str, confidence: str = "high", notes: str = "") -> dict[str, Any]:
    return {"text": json.dumps({"markdown": markdown, "confidence": confidence, "notes": notes})}


# --- streamed replies (the assistant) ------------------------------------------------


def cite(index: int, source: str, cited_text: str = "quoted passage") -> SimpleNamespace:
    """A search_result citation, as the API returns it."""
    return SimpleNamespace(
        type="search_result_location",
        search_result_index=index,
        source=source,
        title="title",
        cited_text=cited_text,
        start_block_index=0,
        end_block_index=1,
    )


def text(value: str, *citations: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=value, citations=list(citations) or None)


def tool_use(name: str, tool_input: dict[str, Any], tool_id: str = "toolu_1") -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=tool_input)


def reply(*blocks: SimpleNamespace, stop_reason: str | None = None, **usage: int) -> dict[str, Any]:
    if stop_reason is None:
        uses_tools = any(b.type == "tool_use" for b in blocks)
        stop_reason = "tool_use" if uses_tools else "end_turn"
    return {"blocks": list(blocks), "stop_reason": stop_reason, **usage}


@dataclass
class FakeStream:
    message: SimpleNamespace
    # Raised after the first text piece, to simulate a dropped connection.
    fail_midway: BaseException | None = None
    # Raised when the stream opens, as the SDK does for API errors.
    error: Exception | None = None

    async def __aenter__(self) -> "FakeStream":
        if self.error is not None:
            raise self.error
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    @property
    def current_message_snapshot(self) -> SimpleNamespace:
        return self.message

    def __aiter__(self) -> AsyncIterator[SimpleNamespace]:
        return self._events()

    async def _events(self) -> AsyncIterator[SimpleNamespace]:
        for block in self.message.content:
            if block.type != "text":
                continue
            # Two pieces per block, as text streams in deltas.
            half = len(block.text) // 2
            for piece in (block.text[:half], block.text[half:]):
                yield SimpleNamespace(type="text", text=piece, snapshot="")
                if self.fail_midway is not None:
                    raise self.fail_midway

    async def get_final_message(self) -> SimpleNamespace:
        return self.message


@dataclass
class FakeMessages:
    owner: "FakeAnthropic"
    beta: bool

    async def create(self, **kwargs: Any) -> Any:
        self.owner.requests.append({"beta": self.beta, **kwargs})
        if self.owner.error is not None:
            raise self.owner.error
        reply = self.owner.respond(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=reply.get("text", ""))],
            usage=SimpleNamespace(
                input_tokens=reply.get("input_tokens", 1500),
                output_tokens=reply.get("output_tokens", 400),
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
            ),
            stop_reason=reply.get("stop_reason", "end_turn"),
            model=reply.get("model", kwargs["model"]),
            _request_id="req_test",
        )

    def stream(self, **kwargs: Any) -> FakeStream:
        # The loop appends to `messages` after each call: keep what was sent.
        self.owner.requests.append(
            {"beta": self.beta, **copy.copy(kwargs), "messages": list(kwargs["messages"])}
        )
        script = self.owner.stream_script
        scripted = script.pop(0) if script else reply(text("I could not find that."))
        if callable(scripted):
            # A reply that depends on the request (e.g. which passages were sent).
            scripted = scripted(kwargs)
        message = SimpleNamespace(
            content=scripted["blocks"],
            usage=SimpleNamespace(
                input_tokens=scripted.get("input_tokens", 3000),
                output_tokens=scripted.get("output_tokens", 300),
                cache_creation_input_tokens=scripted.get("cache_write", 0),
                cache_read_input_tokens=scripted.get("cache_read", 0),
            ),
            stop_reason=scripted["stop_reason"],
            model=kwargs["model"],
        )
        return FakeStream(message, self.owner.stream_failure, self.owner.error)


@dataclass
class FakeBeta:
    messages: FakeMessages


@dataclass
class FakeAnthropic:
    respond: Responder = field(default=lambda _: transcription("$$x^2$$"))
    error: Exception | None = None
    requests: list[dict[str, Any]] = field(default_factory=list)
    # Replies for streamed calls, used in order (see `reply`).
    stream_script: list[Any] = field(default_factory=list)
    stream_failure: BaseException | None = None

    def __post_init__(self) -> None:
        self.messages = FakeMessages(self, beta=False)
        self.beta = FakeBeta(FakeMessages(self, beta=True))


@dataclass
class RecordingQueue:
    jobs: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)

    async def enqueue(self, function: str, *args: Any, job_id: str | None = None) -> None:
        self.jobs.append((function, args))
