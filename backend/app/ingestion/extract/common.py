from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class VisionReason(StrEnum):
    """Why a page's content has to be read from its image."""

    SCANNED = "scanned"  # no usable text layer
    MATHS_DAMAGE = "maths_damage"  # text layer mangles the maths
    IMAGE = "image"  # the upload is a photo / screenshot
    EQUATION_OBJECTS = "equation_objects"  # slide equations python-pptx cannot read


@dataclass(frozen=True)
class ExtractedPage:
    page_no: int
    markdown: str
    damage: float
    vision_reason: VisionReason | None


def markdown_table(header: Sequence[object], rows: Sequence[Sequence[object]]) -> str:
    def cell(value: object) -> str:
        text = "" if value is None else str(value)
        return text.replace("|", "\\|").replace("\n", " ").strip()

    width = len(header)
    lines = [
        "| " + " | ".join(cell(h) for h in header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in rows:
        padded = list(row)[:width] + [""] * (width - len(row))
        lines.append("| " + " | ".join(cell(v) for v in padded) + " |")
    return "\n".join(lines)
