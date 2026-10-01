"""Claude vision transcription of page images into Markdown + LaTeX."""

import base64
import io
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import ClaudeClient, image_tokens, parse_json, text_tokens

TASK = "maths_transcription"
PROMPT_VERSION = "maths_transcription.v2"
PROMPT_FILE = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.md"
# How much of the (possibly garbled) text layer to send as a hint.
TEXT_HINT_MAX_CHARS = 4000

Confidence = Literal["high", "medium", "low"]

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "markdown": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "notes": {"type": "string"},
    },
    "required": ["markdown", "confidence", "notes"],
    "additionalProperties": False,
}


@lru_cache
def system_prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8")


@dataclass(frozen=True)
class Transcription:
    markdown: str
    confidence: Confidence
    notes: str


@dataclass(frozen=True)
class PageImage:
    data: bytes
    media_type: Literal["image/png", "image/jpeg"]
    width: int
    height: int


def prepare_image(data: bytes, max_long_edge: int) -> PageImage:
    """Downscale so the long edge fits (the API would do it anyway, at our
    cost), and re-encode as PNG or JPEG."""
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        image = img.convert("RGB") if img.mode not in ("RGB", "L") else img.copy()
        fmt = img.format
    longest = max(image.size)
    if longest > max_long_edge:
        scale = max_long_edge / longest
        image = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.Resampling.LANCZOS,
        )
    buffer = io.BytesIO()
    if fmt == "JPEG":
        image.save(buffer, "JPEG", quality=90)
        media: Literal["image/png", "image/jpeg"] = "image/jpeg"
    else:
        image.save(buffer, "PNG", optimize=True)
        media = "image/png"
    return PageImage(buffer.getvalue(), media, image.width, image.height)


async def transcribe_page(
    client: ClaudeClient,
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    document_id: uuid.UUID | None,
    module_id: uuid.UUID | None,
    image: PageImage,
    page_no: int,
    filename: str,
    text_hint: str = "",
) -> Transcription:
    hint = text_hint.strip()[:TEXT_HINT_MAX_CHARS]
    instruction = f"Transcribe this page (position {page_no} in the file “{filename}”)."
    if hint:
        instruction += (
            "\n\nMachine-extracted text layer for this page (may be garbled):\n"
            f"<text_layer>\n{hint}\n</text_layer>"
        )
    content: list[dict[str, Any]] = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": image.media_type,
                "data": base64.standard_b64encode(image.data).decode("ascii"),
            },
        },
        {"type": "text", "text": instruction},
    ]
    result = await client.run(
        db,
        user_id=user_id,
        task=TASK,
        prompt_version=PROMPT_VERSION,
        system=system_prompt(),
        content=content,
        estimated_input_tokens=(
            image_tokens(image.width, image.height)
            + text_tokens(system_prompt())
            + text_tokens(instruction)
        ),
        output_schema=OUTPUT_SCHEMA,
        document_id=document_id,
        module_id=module_id,
    )
    data = parse_json(result.text)
    confidence = data.get("confidence")
    return Transcription(
        markdown=str(data.get("markdown", "")).strip(),
        confidence=confidence if confidence in ("high", "medium", "low") else "low",
        notes=str(data.get("notes", "")).strip(),
    )
