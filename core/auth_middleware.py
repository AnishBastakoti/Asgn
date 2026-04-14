from __future__ import annotations

import logging
from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app.services.auth_service import decode_access_token

logger = logging.getLogger(__name__)


# ── Paths that never require a session cookie ─────────────────────────────────

# Exact-match set — checked with 'path in EXEMPT_PATHS' (O(1))
EXEMPT_PATHS: frozenset[str] = frozenset(
    {
        "/login",
        "/health",
        # Docs routes are protected by the application session cookie and
        # admin-role check in core/docs.py.
        "/redocs",
        # PWA / manifest files — must load before any auth check
        "/manifest.json",
        "/service-worker.js",
    }
)

# Prefix-match tuple — checked with 'path.startswith(EXEMPT_PREFIXES)'
# Using a tuple (not a list/set) so startswith() accepts it natively.
EXEMPT_PREFIXES: tuple[str, ...] = (
    "/api/auth/",    # login, logout, refresh — no cookie yet
    "/templates/",   # static JS/CSS/images — no auth needed
)


# ── Middleware ─────────────────────────────────────────────────────────────────

class AuthMiddleware(BaseHTTPMiddleware):
    """
    Validates the 'sp_token' session cookie on every non-exempt request.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path: str = request.url.path

        # ──  Always-exempt exact paths ──────────────────────────────────────
        if path in EXEMPT_PATHS:
            return await call_next(request)

        # ── Always-exempt prefix paths ─────────────────────────────────────
        if path.startswith(EXEMPT_PREFIXES):
            return await call_next(request)

        # ── API routes — pass through, let Depends(require_auth) decide ────
        if path.startswith("/api/"):
            return await call_next(request)

        # ──  HTML page routes — validate session cookie ─────────────────────
        token: str | None = request.cookies.get("sp_token")

        if not token:
            logger.debug("[AuthMiddleware] No token for %r → /login", path)
            return RedirectResponse(url="/login", status_code=302)

        payload: dict | None = decode_access_token(token)

        if not payload:
            logger.debug(
                "[AuthMiddleware] Invalid/expired token for %r → /login", path
            )
            response = RedirectResponse(url="/login", status_code=302)
            # Delete the stale cookie so the browser doesn't keep sending it
            response.delete_cookie(key="sp_token", path="/", httponly=True)
            return response

        # ── Valid token — hydrate request.state.user ───────────────────────
        # Downstream handlers (templates, page routes) can read:
        #   request.state.user["user_id"]
        #   request.state.user["email"]
        #   request.state.user["role"]
        request.state.user = {
            "user_id": int(payload.get("sub", 0)),
            "email":   payload.get("email", ""),
            "role":    payload.get("role", "viewer"),
        }

        return await call_next(request)