import hashlib
from fastapi import Security, Depends, HTTPException, status, Request
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from config import settings
from app.models.api_key import ApiKey
from app.database import get_db
from app.services.auth_service import get_current_user

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

def require_api_key(
    api_key: str = Security(API_KEY_HEADER),
    db: Session = Depends(get_db)
):
    """
    Validates the X-API-Key header.
    Checks prefix, hashes the key, and verifies expiration/active status.
    """
    if not api_key:
        raise HTTPException(status_code=401, detail="X-API-Key header missing")

    if not api_key.startswith(settings.KEY_PREFIX):
        raise HTTPException(status_code=403, detail="Invalid API key format")

    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    record = db.query(ApiKey).filter(
        ApiKey.key_hash == key_hash,
        ApiKey.is_active == True
    ).first()

    if not record:
        raise HTTPException(status_code=403, detail="Invalid or inactive API key")

    if record.expires_at:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if record.expires_at < now:
            raise HTTPException(status_code=403, detail="API key expired")

    return record

# ── REQUIRE AUTH ───────────────────────────────────

def require_auth(request: Request, db: Session = Depends(get_db)) -> dict:
    """
    Protects a route — requires a valid JWT token.
    Raises 401 if no token or token is invalid/expired.
    """
    token = request.cookies.get("sp_token")
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please log in again.",
        )
    
    user = get_current_user(db, token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session. Please log in again.",
        )
    return user

# ── REQUIRE ADMIN ──────────────────────────────────

def require_admin(user: dict = Depends(require_auth)) -> dict:
    """
    Protects a route — requires admin role.
    Raises 403 if user is authenticated but not admin.
    """
    role = (user.get("role") or "").lower().strip()
    admin_roles = {"admin", "administrator"}
    
    if role not in admin_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required for this endpoint.",
        )
    return user

# ── REQUIRE ANALYST ────────────────────────────────

def require_analyst(user: dict = Depends(require_auth)) -> dict:
    """
    Protects a route — requires analyst or admin role.
    Raises 403 for viewers.
    """
    role = (user.get("role") or "").lower().strip()
    allowed_roles = {"admin", "administrator", "analyst"}
    
    if role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Analyst or admin access required.",
        )
    return user

# ─────────────────────────────────────────────
# OPTIONAL AUTH — works with or without token
# ─────────────────────────────────────────────

def optional_auth(
    request: Request,
    db: Session = Depends(get_db),
) -> dict | None:
    """
    Does NOT raise an error if no token is provided.
    Returns user dict if authenticated, None if not.

    Use for: public endpoints that show more data when logged in.
    """
    token = request.cookies.get("sp_token")
    
    if not token:
        return None
    return get_current_user(db, token)