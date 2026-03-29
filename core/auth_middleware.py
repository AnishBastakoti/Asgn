from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse
from app.services.auth_service import decode_access_token
import logging

logger = logging.getLogger(__name__)

# ── Routes that never require auth ────────────────────────────
EXEMPT_PATHS = {
    "/login",
    "/health",
    "/docs",
    "/redocs",
    "/openapi.json",
    "/manifest.json",
    "/service-worker.js",
}

EXEMPT_PREFIXES = (
    "/api/auth/",     # login/logout endpoints
    "/templates/",    # static JS/CSS files
)


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Checks every request for a valid session cookie.
    HTML pages → redirect to /login if not authenticated.
    API routes → pass through (handled by Depends(require_auth)).
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # ── Always allow exempt paths ──
        if path in EXEMPT_PATHS:
            return await call_next(request)

        if any(path.startswith(p) for p in EXEMPT_PREFIXES):
            return await call_next(request)

        # ── API routes — pass through, let Depends handle auth ──
        if path.startswith("/api/"):
            return await call_next(request)

        # ── HTML page routes — check cookie ──
        token = request.cookies.get("sp_token")

        if not token:
            logger.debug(f"[Auth] No token for {path} → redirecting to /login")
            return RedirectResponse(url="/login", status_code=302)

        payload = decode_access_token(token)
        if not payload:
            logger.debug(f"[Auth] Invalid/expired token for {path} → redirecting to /login")
            # Clear the bad cookie and redirect
            response = RedirectResponse(url="/login", status_code=302)
            response.delete_cookie(key="sp_token", path="/")
            return response

        # ── Valid token — attach user info to request state ──
        request.state.user = {
            "user_id": int(payload.get("sub", 0)),
            "email":   payload.get("email", ""),
            "role":    payload.get("role", "viewer"),
        }

        return await call_next(request)