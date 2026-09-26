from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from .config import get_settings
from .security import sanitize_display_name

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthUser:
    sub: str
    email: str | None
    display_name: str


@lru_cache
def _jwks_client() -> PyJWKClient:
    return PyJWKClient(get_settings().cognito_jwks_url, cache_jwk_set=True, lifespan=3600)


def _display_name(claims: dict) -> str:
    email = claims.get("email") or ""
    return sanitize_display_name(
        claims.get("name") or claims.get("preferred_username") or email.split("@")[0] or "Neighbor"
    )


def verify_cognito_token(token: str) -> AuthUser:
    settings = get_settings()
    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.cognito_app_client_id,
            issuer=settings.cognito_issuer,
            leeway=60,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "Sign in again — that session is not valid.") from exc

    if claims.get("token_use") not in {None, "id"}:
        raise HTTPException(401, "Sign in again — that session is not valid.")
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(401, "Sign in again — that session is not valid.")
    return AuthUser(sub=sub, email=claims.get("email"), display_name=_display_name(claims))


def require_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthUser:
    settings = get_settings()
    if not settings.cognito_configured:
        raise HTTPException(
            503,
            "Sign-in is not configured. Set COGNITO_USER_POOL_ID and COGNITO_APP_CLIENT_ID.",
        )
    if not creds or creds.scheme.lower() != "bearer" or not creds.credentials:
        raise HTTPException(401, "Sign in to share a report.")
    return verify_cognito_token(creds.credentials)
