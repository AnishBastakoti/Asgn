from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse

from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Documentation"])

# ── Admin roles  ────────────────────────────────────────
_ADMIN_ROLES: frozenset[str] = frozenset({"admin", "administrator"})


# ── Dependency: validate admin session role ───────────────────────────────

async def _validate_docs_access(request: Request) -> str:

    user = getattr(request.state, "user", None)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Login required to access API documentation.",
        )

    role = (user.get("role", "") or "").lower().strip()
    if role not in _ADMIN_ROLES:
        logger.warning(
            "[Docs] Access denied — user=%r role=%r",
            user.get("email"),
            role,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required to view API documentation.",
        )

    logger.info(
        "[Docs] Admin access granted — user=%r",
        user.get("email"),
    )
    return user["email"]


# ── Swagger UI ────────────────────────────────────────────────────────────────

@router.get(
    "/docs",
    response_class=HTMLResponse,
    include_in_schema=False,   # keep the docs route itself out of the schema
    summary="Swagger UI (admin only)",
)
async def swagger_ui(
    _username: str = Depends(_validate_docs_access),
) -> HTMLResponse:
    """
    Serves the Swagger UI HTML page.

    Credentials are validated by _validate_docs_access before this runs.
    The openapi_url points to our custom /openapi.json which is ALSO gated,
    so the JS fetch Swagger makes internally will prompt for credentials again
    (the browser sends the cached Basic header automatically).
    """
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title=f"{settings.APP_NAME} — API Docs",
        swagger_favicon_url="/templates/img/favicon.ico",   # optional branding
    )


# ── OpenAPI schema JSON ───────────────────────────────────────────────────────

@router.get(
    "/openapi.json",
    response_class=JSONResponse,
    include_in_schema=False,
    summary="OpenAPI schema (admin only)",
)
async def openapi_schema(
    request: Request,
    _username: str = Depends(_validate_docs_access),
) -> JSONResponse:

    # Lazy import avoids circular dependency (main imports docs, docs needs app)
    from main import app

    return JSONResponse(
        get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
    )