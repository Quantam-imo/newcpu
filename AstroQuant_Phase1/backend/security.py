from fastapi import Header, HTTPException, status

from backend.config import ADMIN_API_KEY


def verify_admin_key(x_admin_key: str | None):
    if not ADMIN_API_KEY:
        return

    if x_admin_key == ADMIN_API_KEY:
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing admin key",
    )


def require_admin_key(x_admin_key: str | None = Header(default=None, alias="X-Admin-Key")):
    verify_admin_key(x_admin_key)
