from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
<<<<<<< HEAD
from fastapi.responses import JSONResponse

from app.database import get_db
from config import settings
=======

from app.database import get_db
>>>>>>> dc9ff5da2beacc545df23e12bc139397f3583791
from app.services.auth_service import authenticate_user, get_allowed_pages
from core.auth_deps import require_auth
from core.rate_limiter import limiter

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

<<<<<<< HEAD
# ── Request / Response schemas ────────────────────────────────

class LoginRequest(BaseModel):
    # EmailStr for automatic format validation and better error messages
    email: EmailStr 
    password: str

class LoginResponse(BaseModel):
    """
    The JWT token is set in an httpOnly cookie, not returned in the body.
    """
=======

# ── Request / Response schemas ────────────────────────────────

class LoginRequest(BaseModel):
    email:    str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type:   str
>>>>>>> dc9ff5da2beacc545df23e12bc139397f3583791
    user_id:      int
    email:        str
    display_name: str
    role:         str
    expires_in:   int

<<<<<<< HEAD
=======

>>>>>>> dc9ff5da2beacc545df23e12bc139397f3583791
class UserResponse(BaseModel):
    user_id:      int
    email:        str
    display_name: str
    role:         str

<<<<<<< HEAD
=======

>>>>>>> dc9ff5da2beacc545df23e12bc139397f3583791
# ── Endpoints ─────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
@limiter.limit("10/minute")
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    """
<<<<<<< HEAD
    Authenticates user and sets an httpOnly cookie.
    Prevents XSS by keeping the token out of JavaScript reach.
    """
=======
    Authenticates user with email + password.
    Returns a JWT token valid for 8 hours.
    Also sets an httpOnly cookie so server-side middleware can protect HTML pages.
    Rate limited to 10 attempts/minute per IP to prevent brute force.
    """
    from fastapi.responses import JSONResponse

>>>>>>> dc9ff5da2beacc545df23e12bc139397f3583791
    result = authenticate_user(db, body.email, body.password)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

<<<<<<< HEAD
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
=======
    # Return JSON + set httpOnly cookie so server middleware can verify pages
    response = JSONResponse(content=result)
    response.set_cookie(
        key="sp_token",
        value=result["access_token"],
        httponly=True,       # JS cannot read it — prevents XSS token theft
        samesite="lax",      # prevents CSRF on cross-site requests
        max_age=result["expires_in"],
        path="/",
    )
    return response


@router.post("/logout-session")
def logout_session():
    """Clears the httpOnly session cookie."""
    from fastapi.responses import JSONResponse
    response = JSONResponse(content={"message": "Logged out"})
    response.delete_cookie(key="sp_token", path="/")
    return response


@router.get("/me", response_model=UserResponse)
def get_me(user: dict = Depends(require_auth)):
    """
    Returns current authenticated user's info.
    The frontend calls this on page load to check if logged in.
    """
    return {
        "user_id":      user["user_id"],
        "email":        user["email"],
        "display_name": user["display_name"],
        "role":         user["role"],
    }


@router.get("/my-pages")
def get_my_pages(user: dict = Depends(require_auth), db: Session = Depends(get_db)):
    """
    Returns the list of route paths this user's role can access.
    Used by the frontend to show/hide navigation items.
    """
>>>>>>> dc9ff5da2beacc545df23e12bc139397f3583791
    pages = get_allowed_pages(db, user["role"])
    return {
        "role":  user["role"],
        "pages": pages,
<<<<<<< HEAD
    }
=======
    }


@router.post("/logout")
def logout():
    """
    JWT is stateless — there's no server-side session to destroy.
    The client just deletes the token from localStorage/cookies.
    This endpoint exists for consistency and to confirm the action.
    """
    return {"message": "Logged out successfully. Please delete your token."}
>>>>>>> dc9ff5da2beacc545df23e12bc139397f3583791
