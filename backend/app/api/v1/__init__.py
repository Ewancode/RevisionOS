from fastapi import APIRouter

from app.api.deps import PROTECTED
from app.api.v1 import (
    ai,
    analytics,
    auth,
    chat,
    coding,
    documents,
    exports,
    health,
    learning,
    materials,
    planner,
    practice,
    search,
    settings,
    structure,
)

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
protected.include_router(materials.router)
protected.include_router(learning.router)
protected.include_router(practice.router)
protected.include_router(planner.router)
protected.include_router(analytics.router)
protected.include_router(coding.router)
protected.include_router(exports.router)
router.include_router(protected)
