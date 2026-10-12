"""Login: Replit Auth (OpenID Connect) on Replit, a one-click dev login locally.

Replit Auth is standard OIDC: issuer https://replit.com/oidc, and the Repl's
REPL_ID is the client id (a public client, so PKCE and no client secret).
"""

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from . import repo
from .config import get_settings

router = APIRouter()
_oauth: OAuth | None = None


def _client():
    global _oauth
    s = get_settings()
    if _oauth is None:
        _oauth = OAuth()
        _oauth.register(
            name="replit",
            client_id=s.oidc_client_id,
            server_metadata_url=f"{s.oidc_issuer.rstrip('/')}/.well-known/openid-configuration",
            client_kwargs={
                "scope": "openid email profile",
                "code_challenge_method": "S256",
                "token_endpoint_auth_method": "none",
            },
        )
    return _oauth.replit


def current_user(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


def _sign_in(request: Request, user_id: str, email: str | None, name: str | None) -> None:
    repo.upsert_user(user_id, email, name)
    request.session.clear()
    request.session["user"] = {"id": user_id, "email": email, "name": name}


@router.get("/auth/login")
async def login(request: Request):
    s = get_settings()
    if s.auth_mode == "dev":
        _sign_in(request, "dev-user", "dev@localhost", "Local Developer")
        return RedirectResponse("/", status_code=303)
    redirect_uri = str(request.url_for("auth_callback"))
    return await _client().authorize_redirect(request, redirect_uri)


@router.get("/auth/callback", name="auth_callback")
async def callback(request: Request):
    try:
        token = await _client().authorize_access_token(request)
    except OAuthError as e:
        raise HTTPException(status_code=400, detail=f"Sign-in failed: {e.error}")
    info = token.get("userinfo") or await _client().userinfo(token=token)
    name = " ".join(p for p in (info.get("first_name"), info.get("last_name")) if p) or info.get("name")
    _sign_in(request, str(info["sub"]), info.get("email"), name)
    return RedirectResponse("/", status_code=303)


@router.post("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}
