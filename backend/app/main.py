"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from redis.asyncio import Redis

from app.ai.client import create_client
from app.api.v1 import router as v1_router
from app.core.config import get_config
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.security_headers import SecurityHeadersMiddleware
from app.core.settings import Settings, get_settings
from app.db.session import create_engine, create_session_factory
from app.storage import create_storage
from app.workers.queue import ArqQueue


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    # Fail fast on a bad config file rather than at first use.
    get_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.database_url.get_secret_value())
        redis = Redis.from_url(settings.redis_url)
        arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        app.state.redis = redis
        app.state.jobs = ArqQueue(arq)
        app.state.storage = create_storage(settings)
        app.state.claude = create_client(key, get_config().ai)
        try:
            yield
        finally:
            await arq.aclose()
            await redis.aclose()
            await engine.dispose()

    is_prod = settings.app_env == "production"
    app = FastAPI(
        title="Revision OS",
        version="0.1.0",
        lifespan=lifespan,
        # The schema drives the generated frontend client; the interactive
        # docs are a development convenience only.
        docs_url=None if is_prod else "/api/docs",
        redoc_url=None,
        openapi_url=None if is_prod else "/api/openapi.json",
    )
    register_error_handlers(app)
    app.add_middleware(RequestContextMiddleware)
    # Added last = outermost, so even last-resort 500 responses get the headers.
    app.add_middleware(SecurityHeadersMiddleware, hsts=is_prod)
    app.include_router(v1_router)
    return app
