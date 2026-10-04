"""ADMIN_PASSWORD cookie session for /admin."""

from __future__ import annotations

import hashlib
import hmac
import os
import time

from fastapi import HTTPException, Request, Response

COOKIE_NAME = "kalchas_admin"
TOKEN_TTL_SEC = 12 * 60 * 60
_COOKIE_SALT = b"kalchas-admin-v1"


def admin_password() -> str:
    return os.environ.get("ADMIN_PASSWORD") or ""


def admin_configured() -> bool:
    return bool(admin_password())


def _sign(payload: str) -> str:
    return hmac.new(admin_password().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def mint_token() -> str:
    issued = str(int(time.time()))
    return f"{issued}.{_sign(issued)}"


def token_valid(token: str | None) -> bool:
    if not admin_configured() or not token or "." not in token:
        return False
    issued, given = token.split(".", 1)
    try:
        age = time.time() - int(issued)
    except ValueError:
        return False
    if age < 0 or age > TOKEN_TTL_SEC:
        return False
    return hmac.compare_digest(given, _sign(issued))


def password_matches(given: str) -> bool:
    expected = admin_password()
    if not expected:
        return False
    left = hmac.new(_COOKIE_SALT, given.encode("utf-8"), hashlib.sha256).digest()
    right = hmac.new(_COOKIE_SALT, expected.encode("utf-8"), hashlib.sha256).digest()
    return hmac.compare_digest(left, right)


def cookie_secure() -> bool:
    return bool(os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("HTTPS"))


def set_session_cookie(response: Response) -> None:
    response.set_cookie(
        COOKIE_NAME,
        mint_token(),
        max_age=TOKEN_TTL_SEC,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(),
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def require_admin(request: Request) -> None:
    if not admin_configured():
        raise HTTPException(status_code=503, detail="ADMIN_PASSWORD is not set")
    token = request.cookies.get(COOKIE_NAME)
    if not token_valid(token):
        raise HTTPException(status_code=401, detail="admin login required")
