"""Split page Markdown into retrieval chunks (ARCHITECTURE.md section 7, step 3).

Rules:
- Chunks never cross a page boundary, so a corrected page re-indexes alone
  and every chunk cites exactly one page.
- A block (paragraph, list, table, display equation, code) is never split,
  except a table or plain paragraph that alone exceeds the size cap, which is
  cut between lines/rows. Equations and code are kept whole even if long.
- Headings and the starts of theorems, definitions, examples and proofs are
  preferred boundaries.
- A chunk cut purely for size repeats its last short block at the start of
  the next chunk (overlap), so text near the cut is findable from both sides.
- Each chunk records the heading path in force where it starts; headings
  carry across pages ("1 Numbers > 1.1 Sets").
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from app.core.config import ChunkingConfig

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_STRUCTURE = re.compile(
    r"^[*_\s]*(Theorem|Definition|Lemma|Proposition|Corollary|Example|Examples|Proof|"
    r"Remark|Exercise|Exercises|Question|Solution|Notation|Convention|Axiom)s?\b",
    re.IGNORECASE,
)
_FENCE = re.compile(r"^\s*(```|~~~)")
_BEGIN = re.compile(r"\\begin\{([a-zA-Z*]+)\}")
_END = re.compile(r"\\end\{([a-zA-Z*]+)\}")
_HEADING_SEP = " › "


@dataclass(frozen=True)
class Block:
    text: str
    kind: str  # heading | maths | code | table | text


@dataclass(frozen=True)
class Chunk:
    page_no: int
    position: int  # order within the page
    heading_path: str
    content: str
    token_estimate: int


def _open_display_maths(text: str) -> bool:
    """True while a $$ display block or a \\begin{...} environment is open."""
    if text.count("$$") % 2 == 1:
        return True
    return len(_BEGIN.findall(text)) > len(_END.findall(text))


def split_blocks(markdown: str) -> list[Block]:
    """Blank-line separated blocks, merged so that maths environments and
    fenced code spanning blank lines stay in one block."""
    blocks: list[Block] = []
    current: list[str] = []
    in_fence = False

    def flush() -> None:
        if current and "".join(current).strip():
            text = "\n".join(current).strip("\n")
            blocks.append(Block(text, _kind(text)))
        current.clear()

    for line in markdown.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            current.append(line)
            continue
        if in_fence:
            current.append(line)
            continue
        if not line.strip():
            if current and _open_display_maths("\n".join(current)):
                current.append(line)
                continue
            flush()
            continue
        if _HEADING.match(line):
            # A heading is always a block of its own.
            flush()
            current.append(line)
            flush()
            continue
        current.append(line)
    flush()
    return blocks


def _kind(text: str) -> str:
    first = text.lstrip()
    if _HEADING.match(first):
        return "heading"
    if _FENCE.match(first):
        return "code"
    if first.startswith("$$") or first.startswith("\\begin"):
        return "maths"
    if all(line.lstrip().startswith("|") for line in text.splitlines() if line.strip()):
        return "table"
    return "text"


class _Sizer:
    def __init__(self, config: ChunkingConfig) -> None:
        self.config = config

    def tokens(self, text: str) -> int:
        return int(len(text) / self.config.chars_per_token) + 1


def _split_oversized(block: Block, sizer: _Sizer, limit: int) -> list[Block]:
    """Cut a too-long text block or table between lines (tables repeat their
    header rows). Maths and code are returned whole."""
    if block.kind in ("maths", "code") or sizer.tokens(block.text) <= limit:
        return [block]
    lines = block.text.splitlines()
    header = lines[:2] if block.kind == "table" and len(lines) > 2 else []
    body = lines[len(header) :]
    pieces: list[list[str]] = [[]]
    for line in body:
        candidate = "\n".join(header + pieces[-1] + [line])
        if pieces[-1] and sizer.tokens(candidate) > limit:
            pieces.append([])
        pieces[-1].append(line)
    if len(pieces) == 1 and block.kind == "text":
        # One enormous line: cut at sentence ends instead.
        sentences = re.split(r"(?<=[.!?])\s+", block.text)
        pieces = [[]]
        for sentence in sentences:
            if pieces[-1] and sizer.tokens(" ".join(pieces[-1] + [sentence])) > limit:
                pieces.append([])
            pieces[-1].append(sentence)
        return [Block(" ".join(p), "text") for p in pieces if p]
    return [Block("\n".join(header + p), block.kind) for p in pieces if p]


def chunk_document(pages: Iterable[tuple[int, str]], config: ChunkingConfig) -> list[Chunk]:
    """Chunks for a whole document, in order. Heading context carries across
    pages; chunks themselves never do."""
    sizer = _Sizer(config)
    headings: list[tuple[int, str]] = []  # (level, title) stack
    chunks: list[Chunk] = []

    for page_no, markdown in pages:
        current: list[Block] = []
        path_at_start = _HEADING_SEP.join(t for _, t in headings)
        position = 0

        def emit(blocks: list[Block], path: str, page: int = page_no) -> None:
            nonlocal position
            if not [b for b in blocks if b.kind != "heading"]:
                return
            content = "\n\n".join(b.text for b in blocks)
            chunks.append(Chunk(page, position, path, content, sizer.tokens(content)))
            position += 1

        def carry(blocks: list[Block], incoming: Block) -> list[Block]:
            """The overlap carried into the next chunk after a cut for size."""
            last = blocks[-1]
            fits = (
                last.kind != "heading"
                and sizer.tokens(last.text) <= config.overlap_max_tokens
                and sizer.tokens(last.text + incoming.text) <= config.max_tokens
            )
            return [last] if fits else []

        for raw in split_blocks(markdown):
            for block in _split_oversized(raw, sizer, config.max_tokens):
                size = sizer.tokens("\n\n".join(b.text for b in [*current, block]))
                current_size = sizer.tokens("\n\n".join(b.text for b in current)) if current else 0

                if block.kind == "heading":
                    emit(current, path_at_start)
                    match = _HEADING.match(block.text.strip())
                    assert match is not None  # noqa: S101  # kind == heading
                    level, title = len(match.group(1)), match.group(2).strip()
                    headings[:] = [(lv, t) for lv, t in headings if lv < level] + [(level, title)]
                    path_at_start = _HEADING_SEP.join(t for _, t in headings)
                    current = [block]
                    continue

                structural = bool(_STRUCTURE.match(block.text))
                if structural and current_size >= config.min_tokens:
                    emit(current, path_at_start)
                    current = []
                elif current and (size > config.max_tokens or current_size >= config.target_tokens):
                    # A cut for size, not at a natural boundary: overlap.
                    emit(current, path_at_start)
                    current = carry(current, block)
                current.append(block)
        emit(current, path_at_start)
    return chunks
