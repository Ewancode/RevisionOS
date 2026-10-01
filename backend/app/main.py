"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from app.api.v1 import router as v1_router
from app.core.config import get_config
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.settings import Settings, get_settings
from app.db.session import create_engine, create_session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    # Fail fast on a bad config file rather than at first use.
    get_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.database_url.get_secret_value())
        redis = Redis.from_url(settings.redis_url)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        app.state.redis = redis
        try:
            yield
        finally:
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
    app.include_router(v1_router)
    return app
