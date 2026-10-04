"""Claude's weekly summary of the learning profile (runs in the worker)."""

import json
import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import ClaudeClient, text_tokens
from app.core.config import AppConfig
from app.core.errors import AppError
from app.models import LearningProfileSnapshot

logger = logging.getLogger(__name__)

PROMPT_VERSION = "learning_profile.v1"
PROMPT = Path(__file__).parent.parent / "ai" / "prompts" / f"{PROMPT_VERSION}.md"


async def summarise(
    db: AsyncSession, claude: ClaudeClient, config: AppConfig, snapshot_id: int
) -> None:
    snapshot = await db.get(LearningProfileSnapshot, snapshot_id)
    if snapshot is None or snapshot.summary_md:
        return
    system = PROMPT.read_text(encoding="utf-8")
    data = json.dumps(snapshot.metrics, indent=1)
    try:
        result = await claude.run(
            db,
            user_id=snapshot.user_id,
            task="learning_profile",
            prompt_version=PROMPT_VERSION,
            system=system,
            content=[{"type": "text", "text": f"Statistics:\n{data}"}],
            estimated_input_tokens=text_tokens(system) + text_tokens(data),
        )
    except AppError as exc:
        logger.warning("profile summary skipped", extra={"error": exc.code})
        return
    snapshot.summary_md = result.text.strip()
    snapshot.ai_interaction_id = result.interaction_id
    await db.commit()
