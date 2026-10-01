"""A scripted stand-in for the Anthropic SDK, and a job queue that records.

No test calls the real Claude API (ARCHITECTURE.md section 13).
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

Responder = Callable[[dict[str, Any]], dict[str, Any]]


def transcription(markdown: str, confidence: str = "high", notes: str = "") -> dict[str, Any]:
    return {"text": json.dumps({"markdown": markdown, "confidence": confidence, "notes": notes})}


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


@dataclass
class FakeBeta:
    messages: FakeMessages


@dataclass
class FakeAnthropic:
    respond: Responder = field(default=lambda _: transcription("$$x^2$$"))
    error: Exception | None = None
    requests: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.messages = FakeMessages(self, beta=False)
        self.beta = FakeBeta(FakeMessages(self, beta=True))


@dataclass
class RecordingQueue:
    jobs: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)

    async def enqueue(self, function: str, *args: Any, job_id: str | None = None) -> None:
        self.jobs.append((function, args))
