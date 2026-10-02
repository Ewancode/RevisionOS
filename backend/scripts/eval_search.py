"""Measure search quality on the golden question set (local only).

Usage: ``make eval-search`` (or ``python -m scripts.eval_search``).

Reads ``samples/golden.yaml`` (git-ignored: it points into your own lecture
files), runs every question through the real search against your account,
and reports page-level Recall@5 and MRR@10, plus the misses. Documents are
matched by filename. No AI calls; no cost.
"""

import asyncio
import sys
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select

from app.core.config import get_config
from app.core.settings import BACKEND_ROOT, get_settings
from app.db.session import create_engine, create_session_factory
from app.models import User
from app.retrieval.embeddings import create_provider
from app.retrieval.search import Scope, SearchService

GOLDEN = BACKEND_ROOT.parent / "samples" / "golden.yaml"
# Agreed targets (ARCHITECTURE.md section 13: "above agreed thresholds").
TARGET_RECALL_AT_5 = 0.85
TARGET_MRR = 0.7


def load_questions(golden_path: Path) -> list[dict[str, Any]] | None:
    if not golden_path.exists():
        print(f"No golden set at {golden_path}.", file=sys.stderr)
        return None
    questions: list[dict[str, Any]] = yaml.safe_load(golden_path.read_text(encoding="utf-8"))[
        "questions"
    ]
    return questions


async def main(questions: list[dict[str, Any]]) -> int:
    settings, config = get_settings(), get_config()
    engine = create_engine(settings.database_url.get_secret_value())
    embedder = create_provider(config.retrieval.embeddings, settings.model_cache_dir)
    search_config = config.retrieval.search.model_copy(update={"results": 10})
    hits, reciprocal, misses = 0, 0.0, []
    try:
        async with create_session_factory(engine)() as db:
            users = (await db.scalars(select(User))).all()
            if len(users) != 1:
                print(
                    "Expected exactly one account; this script evaluates the owner's.",
                    file=sys.stderr,
                )
                return 2
            service = SearchService(db, users[0].id, embedder, search_config)
            for item in questions:
                expected = {(doc, page) for doc, pages in item["expect"].items() for page in pages}
                result = await service.search(item["q"], Scope())
                ranked = [(p.filename, p.page_no) for p in result.passages]
                first = next((i for i, key in enumerate(ranked) if key in expected), None)
                if first is not None and first < 5:
                    hits += 1
                else:
                    top = ", ".join(f"{f} p{p}" for f, p in ranked[:3]) or "nothing"
                    misses.append(f"{item['q']}  (got: {top})")
                reciprocal += 1 / (first + 1) if first is not None else 0.0
    finally:
        await engine.dispose()

    recall, mrr = hits / len(questions), reciprocal / len(questions)
    print(
        f"{len(questions)} questions  Recall@5 {recall:.2f} (target {TARGET_RECALL_AT_5})"
        f"  MRR@10 {mrr:.2f} (target {TARGET_MRR})"
    )
    for miss in misses:
        print("  miss:", miss)
    return 0 if recall >= TARGET_RECALL_AT_5 and mrr >= TARGET_MRR else 1


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else GOLDEN
    questions = load_questions(path)
    sys.exit(2 if questions is None else asyncio.run(main(questions)))
