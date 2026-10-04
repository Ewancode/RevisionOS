"""Arq worker entry point: ``arq app.workers.settings.WorkerSettings``.

The separate cron ``scheduler`` process from ARCHITECTURE.md section 4 is
added in the first phase that has a scheduled job.
"""

from typing import Any, ClassVar

from arq.connections import RedisSettings
from arq.worker import func

from app.ai.client import create_client
from app.core.config import get_config
from app.core.logging import configure_logging
from app.core.settings import get_settings
from app.db.session import create_engine, create_session_factory
from app.ingestion.pipeline import Deps
from app.retrieval.embeddings import create_provider
from app.storage import create_storage
from app.workers.tasks import (
    generate_draft_job,
    mark_attempt_job,
    ping,
    process_document_job,
    reindex_document_job,
    retranscribe_page_job,
    summarise_profile_job,
)

_config = get_config()
_timeout = _config.platform.ingestion.job_timeout_seconds


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_engine(settings.database_url.get_secret_value())
    key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
    embedder = create_provider(get_config().retrieval.embeddings, settings.model_cache_dir)
    # Load (and on first run download) the model now, not mid-document.
    await embedder.warm_up()
    ctx["engine"] = engine
    ctx["deps"] = Deps(
        sessions=create_session_factory(engine),
        storage=create_storage(settings),
        claude=create_client(key, get_config().ai),
        config=get_config(),
        embedder=embedder,
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["engine"].dispose()


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        ping,
        func(process_document_job, name="process_document", timeout=_timeout, max_tries=2),
        func(retranscribe_page_job, name="retranscribe_page", timeout=_timeout, max_tries=1),
        func(reindex_document_job, name="reindex_document", timeout=_timeout, max_tries=2),
        # Not retried: a retry would pay for the same Claude calls twice.
        func(generate_draft_job, name="generate_draft", timeout=_timeout, max_tries=1),
        func(mark_attempt_job, name="mark_attempt", timeout=_timeout, max_tries=1),
        func(summarise_profile_job, name="summarise_profile", timeout=_timeout, max_tries=1),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
