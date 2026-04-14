from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from fastapi.responses import JSONResponse

from app.database import get_db
from config import settings
from app.services.auth_service import authenticate_user, get_allowed_pages
from core.auth_deps import require_auth
from core.rate_limiter import limiter

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

# ── Request / Response schemas ────────────────────────────────

class LoginRequest(BaseModel):
    # EmailStr for automatic format validation and better error messages
    email: EmailStr 
    password: str

class LoginResponse(BaseModel):
    """
    The JWT token is set in an httpOnly cookie, not returned in the body.
    """
    user_id:      int
    email:        str
    display_name: str
    role:         str
    expires_in:   int

class UserResponse(BaseModel):
    user_id:      int
    email:        str
    display_name: str
    role:         str

# ── Endpoints ─────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
@limiter.limit("10/minute")
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    """
    Authenticates user and sets an httpOnly cookie.
    Prevents XSS by keeping the token out of JavaScript reach.
    """
    result = authenticate_user(db, body.email, body.password)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Securely move the token from body to Cookie
    token = result.pop("access_token")
    response = JSONResponse(content=result)

    response.set_cookie(
        key="sp_token",
        value=token,
        httponly=True,               # Shield from XSS
        samesite="lax",              # Shield from CSRF
        max_age=result["expires_in"],
        path="/",
        secure=not settings.DEBUG,   # HTTPS only in production
    )
    return response

@router.post("/logout")
def logout():
    """
    Consolidated Logout Clears the httpOnly session cookie.
    """
    response = JSONResponse(content={"message": "Logged out successfully"})
    response.delete_cookie(key="sp_token", path="/")
    return response

@router.get("/me", response_model=UserResponse)
def get_me(user: dict = Depends(require_auth)):
    """Returns current authenticated user's info from the decoded JWT."""
    return user

@router.get("/my-pages")
def get_my_pages(user: dict = Depends(require_auth), db: Session = Depends(get_db)):
    """Used by frontend for Role-Based Access Control (RBAC) UI rendering."""
    pages = get_allowed_pages(db, user["role"])
    return {
        "role":  user["role"],
        "pages": pages,
    }
