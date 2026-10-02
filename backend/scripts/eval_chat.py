"""Check that the assistant cites the right pages (local only; costs money).

Usage: ``make eval-chat`` (or ``python -m scripts.eval_chat --yes [--limit N]``).

Takes questions spread across ``samples/golden.yaml``, asks each one the way
you would ("Where did my lecturer explain ...?") through the real assistant
(retrieval, Claude, tools, citation checks), and reports how often a verified
citation points at an expected page. Each question runs in a temporary
conversation that is deleted afterwards. Calls go through the budget guard
and are recorded in the usage dashboard like any other.

Without ``--yes`` it only prints the estimated cost.
"""

import argparse
import asyncio
import sys
import uuid
from typing import Any

from sqlalchemy import delete, select

from app.ai.chat import ChatOrchestrator, Done, Failed
from app.ai.client import create_client
from app.core.config import get_config
from app.core.settings import get_settings
from app.db.session import create_engine, create_session_factory
from app.models import AIUsage, Conversation, User
from app.retrieval.embeddings import create_provider
from app.services.common import ClientInfo
from scripts.eval_search import GOLDEN, load_questions

TARGET_CITED_HIT = 0.8
# Rough worst case per question in the budget currency, for the estimate only (two calls of
# about 6k input and 600 output tokens each on Sonnet).
ESTIMATE_PER_QUESTION = 0.03


def spread(items: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    """`n` questions evenly spread over the set (not just the first chapter)."""
    if n >= len(items):
        return items
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


async def main(questions: list[dict[str, Any]]) -> int:
    settings, config = get_settings(), get_config()
    key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
    if not key:
        print("ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        return 2
    engine = create_engine(settings.database_url.get_secret_value())
    embedder = create_provider(config.retrieval.embeddings, settings.model_cache_dir)
    claude = create_client(key, config.ai)
    hits, misses, failures, cited_pages, on_target = 0, [], 0, 0, 0
    try:
        async with create_session_factory(engine)() as db:
            users = (await db.scalars(select(User))).all()
            if len(users) != 1:
                print("Expected exactly one account; this evaluates the owner's.", file=sys.stderr)
                return 2
            user = users[0]
            started = await db.scalar(select(AIUsage.id).order_by(AIUsage.id.desc()).limit(1)) or 0
            for item in questions:
                expected = {(doc, page) for doc, pages in item["expect"].items() for page in pages}
                conversation = Conversation(id=uuid.uuid4(), user_id=user.id, title="[eval]")
                db.add(conversation)
                await db.commit()
                orchestrator = ChatOrchestrator(
                    db,
                    user.id,
                    ClientInfo(None, "eval_chat"),
                    claude=claude,
                    embedder=embedder,
                    config=config,
                )
                question = f"Where did my lecturer explain {item['q']}?"
                result = None
                async for event in orchestrator.answer(conversation, question):
                    if isinstance(event, Done | Failed):
                        result = event
                await db.execute(delete(Conversation).where(Conversation.id == conversation.id))
                await db.commit()
                if not isinstance(result, Done):
                    failures += 1
                    code = result.code if isinstance(result, Failed) else "no answer"
                    misses.append(f"{item['q']}  (failed: {code})")
                    continue
                cited = [(c["filename"], c["page_no"]) for c in result.message.citations]
                cited_pages += len(cited)
                on_target += sum(1 for c in cited if c in expected)
                if any(c in expected for c in cited):
                    hits += 1
                else:
                    got = ", ".join(f"{f} p{p}" for f, p in cited[:3]) or "no citations"
                    misses.append(f"{item['q']}  (cited: {got})")
            spent_usd = sum(
                (
                    await db.scalars(select(AIUsage.estimated_cost_usd).where(AIUsage.id > started))
                ).all()
            )
    finally:
        await engine.dispose()

    rate = hits / len(questions)
    precision = on_target / cited_pages if cited_pages else 0.0
    spent = config.ai.budget.from_usd(spent_usd)
    print(
        f"{len(questions)} questions  cited the right page: {rate:.2f} (target {TARGET_CITED_HIT})"
        f"  citations on expected pages: {precision:.2f}  failures: {failures}"
        f"  cost: {spent:.3f} {config.ai.budget.currency}"
    )
    for miss in misses:
        print("  miss:", miss)
    return 0 if rate >= TARGET_CITED_HIT else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=10, help="questions to ask (default 10)")
    parser.add_argument("--yes", action="store_true", help="spend money on real API calls")
    args = parser.parse_args()
    loaded = load_questions(GOLDEN)
    if loaded is None:
        sys.exit(2)
    chosen = spread(loaded, args.limit)
    estimate = len(chosen) * ESTIMATE_PER_QUESTION
    if not args.yes:
        currency = get_config().ai.budget.currency
        print(
            f"Would ask {len(chosen)} questions, costing up to about {estimate:.2f} {currency}. "
            "Run again with --yes to go ahead."
        )
        sys.exit(0)
    sys.exit(asyncio.run(main(chosen)))
