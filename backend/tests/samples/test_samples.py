"""Local-only checks on your real files in ../samples (never in CI).

Run with: uv run pytest -m samples -s
Extraction only: no Claude calls, no cost. Prints, per file, which pages
would go to vision and why, so the damage threshold can be sanity-checked
against real lecture notes.
"""

from pathlib import Path

import pytest

from app.core.config import get_config
from app.ingestion.extract import extract
from app.ingestion.filenames import extension
from app.ingestion.validation import EXTENSIONS, validate_upload

SAMPLES = Path(__file__).resolve().parents[3] / "samples"
FILES = (
    sorted(
        p
        for p in SAMPLES.glob("*")
        if p.is_file() and p.name != "README.md" and extension(p.name) in EXTENSIONS
    )
    if SAMPLES.is_dir()
    else []
)

pytestmark = pytest.mark.samples


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_sample_extracts(path: Path, tmp_path: Path) -> None:
    config = get_config().platform
    copy = tmp_path / "upload"
    copy.write_bytes(path.read_bytes())
    validated = validate_upload(copy, extension(path.name), config.uploads)
    pages = extract(copy, validated.kind, config.ingestion)

    assert pages, "no pages extracted"
    flagged = [p for p in pages if p.vision_reason is not None]
    print(f"\n{path.name}: {len(pages)} pages, {len(flagged)} to vision")
    for page in flagged:
        print(f"  page {page.page_no}: {page.vision_reason} (damage {page.damage:.2f})")
    # Most pages of a real document have usable text or are flagged; none
    # should come back silently empty unless genuinely blank.
    silent = [p for p in pages if not p.markdown.strip() and p.vision_reason is None]
    assert len(silent) <= max(1, len(pages) // 10), f"{len(silent)} empty unflagged pages"
