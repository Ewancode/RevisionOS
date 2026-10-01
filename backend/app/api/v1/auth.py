from fastapi import APIRouter, Request, Response, status

from app.api.deps import Auth, AuthCtx, Client
from app.core.security import CSRF_COOKIE, SESSION_COOKIE
from app.schemas.auth import ChangePasswordRequest, LoginRequest, SessionOut
from app.services.auth import IssuedSession

public_router = APIRouter(prefix="/auth", tags=["auth"])
router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookies(response: Response, issued: IssuedSession) -> None:
    # The CSRF cookie is readable by the SPA so it can echo it in the
    # X-CSRF-Token header; the session cookie is not readable by scripts.
    for name, value, httponly in (
        (SESSION_COOKIE, issued.session_token, True),
        (CSRF_COOKIE, issued.csrf_token, False),
    ):
        response.set_cookie(
            name,
            value,
            max_age=issued.max_age_seconds,
            path="/",
            secure=True,
            httponly=httponly,
            samesite="lax",
        )


def _clear_session_cookies(response: Response) -> None:
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/", secure=True, samesite="lax")


@public_router.post("/login", response_model=SessionOut)
async def login(
    body: LoginRequest, request: Request, response: Response, auth: Auth, client: Client
) -> SessionOut:
    issued = await auth.login(
        body.email, body.password, client, previous_token=request.cookies.get(SESSION_COOKIE)
    )
    _set_session_cookies(response, issued)
    return SessionOut.model_validate({"user": issued.user, "settings": issued.user.settings})


@router.get("/session", response_model=SessionOut)
async def session(context: AuthCtx) -> SessionOut:
    return SessionOut.model_validate({"user": context.user, "settings": context.user.settings})


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(context: AuthCtx, auth: Auth, client: Client, response: Response) -> None:
    await auth.logout(context, client)
    _clear_session_cookies(response)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest, context: AuthCtx, auth: Auth, client: Client
) -> None:
    await auth.change_password(context, body.current_password, body.new_password, client)
