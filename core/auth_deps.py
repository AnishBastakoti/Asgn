from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.auth_service import get_current_user

# HTTPBearer reads the "Authorization: Bearer <token>" header automatically
_bearer = HTTPBearer(auto_error=False)


# ─────────────────────────────────────────────
# REQUIRE AUTH — any logged-in user
# ─────────────────────────────────────────────

def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> dict:
    """
    Protects a route — requires a valid JWT token.
    Raises 401 if no token or token is invalid/expired.

    Returns the current user dict on success.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_current_user(db, credentials.credentials)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


# ─────────────────────────────────────────────
# REQUIRE ADMIN — admin role only
# ─────────────────────────────────────────────

def require_admin(user: dict = Depends(require_auth)) -> dict:
    role = (user.get("role") or "").lower().strip()
    """
    Protects a route — requires admin role.
    Raises 403 if user is authenticated but not admin.

    Use for: /pipeline, /model-status, /elbow-analysis
    """
    admin_roles = {"admin", "administrator"}
    if role not in admin_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required for this endpoint.",
        )
    return user


# ─────────────────────────────────────────────
# REQUIRE ANALYST OR ABOVE
# ─────────────────────────────────────────────

def require_analyst(user: dict = Depends(require_auth)) -> dict:
    role = (user.get("role") or "").lower().strip()
    """
    Protects a route — requires analyst or admin role.
    Raises 403 for viewers.

    Use for: analytics endpoints, career transition, clustering
    """
    
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
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> dict | None:
    """
    Does NOT raise an error if no token is provided.
    Returns user dict if authenticated, None if not.

    Use for: public endpoints that show more data when logged in.
    """
    if not credentials:
        return None
    return get_current_user(db, credentials.credentials)