from fastapi import APIRouter

from app.api.deps import PROTECTED
from app.api.v1 import ai, auth, chat, documents, health, search, settings, structure

router = APIRouter(prefix="/api/v1")

# Public: the only routes reachable without a session.
router.include_router(health.router)
router.include_router(auth.public_router)

# Everything else requires a session, and a CSRF token on unsafe methods.
protected = APIRouter(dependencies=PROTECTED)
protected.include_router(auth.router)
protected.include_router(settings.router)
protected.include_router(structure.router)
protected.include_router(documents.router)
protected.include_router(search.router)
protected.include_router(chat.router)
protected.include_router(ai.router)
router.include_router(protected)
