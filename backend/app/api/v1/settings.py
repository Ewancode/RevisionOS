from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.schemas.auth import SessionOut, SettingsUpdate
from app.services.users import update_settings

router = APIRouter(prefix="/settings", tags=["settings"])


@router.patch("", response_model=SessionOut)
async def patch_settings(body: SettingsUpdate, user: CurrentUser, db: DbSession) -> SessionOut:
    user = await update_settings(db, user, body)
    return SessionOut.model_validate({"user": user, "settings": user.settings})
