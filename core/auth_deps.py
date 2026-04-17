from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.api_key import ApiKey
from app.services.auth_service import get_current_user
from config import settings

logger = logging.getLogger(__name__)

# ── Role constants ────────────────────────────────────────────────────────────
_ADMIN_ROLES:    frozenset[str] = frozenset({"admin", "administrator"})
_ANALYST_ROLES:  frozenset[str] = frozenset({"admin", "administrator", "analyst"})

# ── API key header scheme ─────────────────────────────────────────────────────
_API_KEY_HEADER = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,   # we raise our own typed errors below
    description="Public API key (format: `sp_<hex>`)",
)


# ─────────────────────────────────────────────────────────────────────────────
# Public API key  (external partners / machine-to-machine)
# ─────────────────────────────────────────────────────────────────────────────

def require_api_key(
    api_key: str | None = Security(_API_KEY_HEADER),
    db: Session = Depends(get_db),
) -> ApiKey:
    
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key header is required.",
        )

    if not api_key.startswith(settings.KEY_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key format.",
        )

    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    record: ApiKey | None = (
        db.query(ApiKey)
        .filter(ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True))
        .first()
    )

    if not record:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or inactive API key.",
        )

    # Compare timezone-naive UTC datetimes consistently
    if record.expires_at:
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        if record.expires_at < now_utc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="API key has expired.",
            )

    return record


# ─────────────────────────────────────────────────────────────────────────────
# Session-cookie auth  (browser / Jinja2 frontend)
# ─────────────────────────────────────────────────────────────────────────────

def require_auth(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """
    Check request.state first to see if AuthMiddleware already
    validated and hydrated the user, avoiding a redundant DB/Token lookup.
    """
    state_user = getattr(request.state, "user", None)
    if state_user:
        return state_user

    token: str | None = request.cookies.get("sp_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please log in again.",
        )

    user: dict | None = get_current_user(db, token)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session. Please log in again.",
        )

    return user


# ─────────────────────────────────────────────────────────────────────────────
# Role-based guards
# ─────────────────────────────────────────────────────────────────────────────

def require_admin(user: dict = Depends(require_auth)) -> dict:
    """
    Requires ''admin'' or ''administrator'' role.
    Raises HTTP 403 if the authenticated user's role is insufficient.
    """
    role: str = (user.get("role") or "").lower().strip()

    if role not in _ADMIN_ROLES:
        logger.warning(
            "[AuthDeps] Admin access denied — user_id=%s role=%r",
            user.get("user_id"),
            role,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )

    return user


def require_analyst(user: dict = Depends(require_auth)) -> dict:
    """
    Requires ''analyst'', ''admin'', or ''administrator'' role.

    Use on read-heavy / analytics endpoints that viewers cannot access.

    Raises HTTP 403 if the authenticated user's role is insufficient.
    """
    role: str = (user.get("role") or "").lower().strip()

    if role not in _ANALYST_ROLES:
        logger.warning(
            "[AuthDeps] Analyst access denied — user_id=%s role=%r",
            user.get("user_id"),
            role,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Analyst or admin access required.",
        )

    return user


# ─────────────────────────────────────────────────────────────────────────────
# Optional auth  (public endpoints that show richer data when logged in)
# ─────────────────────────────────────────────────────────────────────────────

def optional_auth(
    request: Request,
    db: Session = Depends(get_db),
) -> dict | None:
    """
    Soft authentication — never raises an error.

    Returns the user dict if a valid ''sp_token'' cookie is present,
    ''None'' otherwise.

    Typical use-case: a public endpoint that returns extra fields
    """
    token: str | None = request.cookies.get("sp_token")

    if not token:
        return None

    return get_current_user(db, token)   # returns None on invalid/expired token