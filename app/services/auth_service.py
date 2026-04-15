import secrets

import jwt
import bcrypt
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from app.models.auth import SystemEndUser, SystemRolePage, SystemPage, SystemRole

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
    except Exception as e:
        logger.error(f"[MSIT402|SP] Password verification error: {e}")
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

def create_access_token(data: dict):
    now = datetime.now(timezone.utc)
    payload = {
        "sub":   str(data["user_id"]),
        "email": data["email"],
        "role":  data["role"],
        "exp":   now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "iat":   now,          #  issued-at makes token unique every login
        "jti":   secrets.token_hex(8),  # unique token ID
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


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
        logger.debug("[MSIT402|SP] Token expired")
        return None   # token expired — user must log in again
    except jwt.InvalidTokenError as e:
        logger.error(f"[MSIT402|SP] Invalid token: {e}")
        return None   # token tampered or invalid


# ─────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────

def authenticate_user(db: Session, email: str, password: str) -> dict | None:
    """
    Verifies credentials and returns a JWT token on success.
    """
    try:
        # Find user by email
        user = (
            db.query(SystemEndUser)
            .filter(SystemEndUser.email == email.lower().strip())
            .first()
        )

        if not user:
            logger.info(f"[MSIT402|SP] Auth failed: user not found ({email})")
            return None  # no such user

        if not user.enabled:
            logger.warning(f"[MSIT402|SP] Auth blocked: account disabled ({email})")
            return None  # account disabled

        if not verify_password(password, user.password_hash):
            logger.info(f"[MSIT402|SP] Auth failed: incorrect password ({email})")
            return None  # wrong password

        # Get role name
        role_name = user.role.name if user.role else "viewer"

        # Create JWT token
        token = create_access_token({
            "user_id": user.id,
            "email": user.email,
            "role": role_name,
        })

        logger.info(f"[MSIT402|SP] User authenticated: {email} (Role: {role_name})")
        return {
            "access_token": token,
            "token_type":   "bearer",
            "user_id":      user.id,
            "email":        user.email,
            "display_name": user.email,
            "role":         role_name,
            "expires_in":   JWT_EXPIRES_HRS * 3600,
        }
    except Exception as e:
        logger.error(f"[MSIT402|SP] authenticate_user system error: {e}")
        return None


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
    try:
        role_pages = (
            db.query(SystemPage.route_path)
            .join(SystemRolePage, SystemRolePage.page_id == SystemPage.id)
            .join(SystemRole, SystemRole.id == SystemRolePage.role_id)
            .filter(SystemRole.name == role_name)
            .all()
        )
        return [r.route_path for r in role_pages if r.route_path]
    except Exception as e:
        logger.error(f"[MSIT402|SP] get_allowed_pages failed for {role_name}: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# HTML page access helpers
# ─────────────────────────────────────────────────────────────────────────────

_HTML_PAGE_ROUTES: set[str] = {
    "dashboard",
    "skills",
    "occupations",
    "analytics",
    "career",
    "model-status",
    "api-keys",
    "docs",
}
_DEFAULT_VIEWER_ROUTES: set[str] = {"dashboard",
    "skills",
    "occupations",
    "analytics",
    "career",
    "model-status",}
_ADMIN_ROLES: frozenset[str] = frozenset({"admin", "administrator"})


def is_admin_role(role_name: str) -> bool:
    return (role_name or "").lower().strip() in _ADMIN_ROLES


def get_allowed_html_pages(role_name: str) -> set[str]:
    if is_admin_role(role_name):
        return _HTML_PAGE_ROUTES.copy()
    return _DEFAULT_VIEWER_ROUTES.copy()


def normalize_page_route(path: str) -> str:
    if path == "/" or path == "":
        return "dashboard"
    return path.lstrip("/")