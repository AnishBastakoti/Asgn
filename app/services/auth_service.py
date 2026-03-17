import jwt
import bcrypt
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from app.models.auth import SystemEndUser, SystemRolePage, SystemPage
from config import settings

# ── JWT config ────────────────────────────────────────────────
JWT_ALGORITHM  = "HS256"
JWT_EXPIRES_HRS = 8  # token valid for 8 hours


# ─────────────────────────────────────────────
# PASSWORD VERIFICATION
# ─────────────────────────────────────────────

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Checks plain text password against bcrypt hash.
    hash the plain password and compare the hashes.
    Returns True if they match, False otherwise.
    """
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8")
        )
    except Exception:
        return False


def hash_password(plain_password: str) -> str:
    """
    Creates a bcrypt hash of a plain text password.
    Used when creating new users.
    """
    salt = bcrypt.gensalt(rounds=10)  # higher rounds = slower = more secure
    return bcrypt.hashpw(plain_password.encode("utf-8"), salt).decode("utf-8")


# ─────────────────────────────────────────────
# JWT TOKEN CREATION & VALIDATION
# ─────────────────────────────────────────────

def create_access_token(user_id: int, email: str, role: str) -> str:
    """
    Creates a signed JWT token containing user identity.

    The token payload:
        sub  — subject (user id)
        email
        role — user's role name (e.g. "admin")
        exp  — expiry timestamp
        iat  — issued at timestamp

    The token is signed with SECRET_KEY from .env.
    Anyone who modifies the token will fail signature verification.
    """
    now     = datetime.now(timezone.utc)
    expires = now + timedelta(hours=JWT_EXPIRES_HRS)

    payload = {
        "sub":   str(user_id),
        "email": email,
        "role":  role,
        "exp":   expires,
        "iat":   now,
    }

    return jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """
    Validates and decodes a JWT token.
    Returns the payload dict if valid, None if expired or tampered.
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[JWT_ALGORITHM]
        )
        return payload
    except jwt.ExpiredSignatureError:
        return None   # token expired — user must log in again
    except jwt.InvalidTokenError:
        return None   # token tampered or invalid


# ─────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────

def authenticate_user(db: Session, email: str, password: str) -> dict | None:
    """
    Verifies credentials and returns a JWT token on success.

    Returns:
        {
            "access_token": "eyJ...",
            "token_type":   "bearer",
            "user_id":      1,
            "email":        "user@example.com",
            "display_name": "random user",
            "role":         "admin",
            "expires_in":   28800,   # seconds
        }
    Or None if credentials are invalid.
    """
    # Find user by email
    user = (
        db.query(SystemEndUser)
        .filter(SystemEndUser.email == email.lower().strip())
        .first()
    )

    if not user:
        return None  # no such user

    if not user.enabled:
        return None  # account disabled

    if not verify_password(password, user.password_hash):
        return None  # wrong password

    # Get role name
    role_name = user.role.name if user.role else "viewer"

    # Create JWT token
    token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=role_name,
    )

    return {
        "access_token": token,
        "token_type":   "bearer",
        "user_id":      user.id,
        "email":        user.email,
        "display_name": user.email,
        "role":         role_name,
        "expires_in":   JWT_EXPIRES_HRS * 3600,
    }


# ─────────────────────────────────────────────
# GET CURRENT USER FROM TOKEN
# ─────────────────────────────────────────────

def get_current_user(db: Session, token: str) -> dict | None:
    """
    Decodes token and fetches current user from DB.
    Used by FastAPI dependency injection on protected routes.
    """
    payload = decode_access_token(token)
    if not payload:
        return None

    user_id = int(payload.get("sub", 0))
    user    = db.query(SystemEndUser).filter(SystemEndUser.id == user_id).first()

    if not user or not user.enabled:
        return None

    return {
        "user_id":      user.id,
        "email":        user.email,
        "display_name": user.email,
        "role":         payload.get("role", "viewer"),
    }


# ─────────────────────────────────────────────
# PAGE ACCESS CHECK
# ─────────────────────────────────────────────

def get_allowed_pages(db: Session, role_name: str) -> list[str]:
    """
    Returns list of route paths this role can access.
    Used to show/hide nav items per user role.
    """
    role_pages = (
        db.query(SystemPage.route_path)
        .join(SystemRolePage, SystemRolePage.page_id == SystemPage.id)
        .join(
            __import__("app.models.auth", fromlist=["SystemRole"]).SystemRole,
            __import__("app.models.auth", fromlist=["SystemRole"]).SystemRole.id == SystemRolePage.role_id
        )
        .filter(
            __import__("app.models.auth", fromlist=["SystemRole"]).SystemRole.name == role_name
        )
        .all()
    )
    return [r.route_path for r in role_pages if r.route_path]