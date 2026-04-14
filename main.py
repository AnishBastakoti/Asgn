from __future__ import annotations

import uvicorn
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.database import verify_connection
from app.logger import setup_logging
from app.routers import analytics, auth, jobs, occupations, pipeline, skills
from app.routers.api_keys import router as api_keys_router
from app.routers.public_api import router as public_router
from config import settings
from core.auth_middleware import AuthMiddleware
from core.docs import router as docs_router
from core.rate_limiter import limiter

# ── Logging ────────────────────────────────────────────────────────────────
# Must happen before any other import that calls logging.getLogger()
setup_logging()
logger = logging.getLogger(__name__)


# ── Application ────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
SkillPulse — Australian Job Market Intelligence Platform

Analyses skill demand across ANZSCO occupations using
real job-posting data and the ESCO skill taxonomy.
    """.strip(),
    # Disable FastAPI's built-in docs/schema endpoints unconditionally.
    # core/docs.py mounts /docs and /openapi.json with HTTPBasic auth instead.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# ── Rate limiter state ────────────────────────────────────────────────────────
app.state.limiter = limiter


# ── Middleware (added in outermost-last order) ─────────────────────────────
#
# Execution order for an incoming request:
#   SlowAPIMiddleware → AuthMiddleware → CORSMiddleware → route handler
#
# SlowAPIMiddleware is outermost so rate-limit rejections are returned before
# any auth or CORS logic runs (avoids wasted DB calls on floods).

app.add_middleware(CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_methods=settings.CORS_ALLOW_METHODS,
    allow_headers=settings.CORS_ALLOW_HEADERS,
    allow_credentials=True,
)
app.add_middleware(AuthMiddleware)
app.add_middleware(SlowAPIMiddleware)


# ──  Exception handlers ─────────────────────────────────────────────────────

@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Please try again later."},
    )


# ──  Routers ────────────────────────────────────────────────────────────────
# Custom /docs + /openapi.json MUST be included first so FastAPI registers
# those paths before any wildcard or catch-all route can shadow them.

app.include_router(docs_router)          # ← /docs, /openapi.json  (admin only)

app.include_router(skills.router)
app.include_router(occupations.router)
app.include_router(jobs.router)
app.include_router(analytics.router)
app.include_router(pipeline.router)
app.include_router(auth.router)
app.include_router(public_router)
app.include_router(api_keys_router)


# ── Static files ───────────────────────────────────────────────────────────
# Mount AFTER routers — StaticFiles is a catch-all; if mounted first it would
# intercept requests that should go to your API routes.

app.mount("/templates", StaticFiles(directory="templates"), name="static")
templates = Jinja2Templates(directory="templates")


# ── Cache-control middleware for static assets ────────────────────────────────

@app.middleware("http")
async def _no_cache_static(request: Request, call_next):
    """Prevent browsers caching JS/CSS/HTML served from /templates/*."""
    response = await call_next(request)
    if request.url.path.startswith("/templates/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ── Template helper ───────────────────────────────────────────────────────────

def _render(request: Request, template_name: str, page: str) -> HTMLResponse:
    """Render a Jinja2 template with the standard context variables."""
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={
            "active_page": page,
            "app_name":    settings.APP_NAME,
            "app_version": settings.APP_VERSION,
        },
    )


# ── HTML page routes ──────────────────────────────────────────────────────────
# These are protected by AuthMiddleware.

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def serve_dashboard(request: Request):
    return _render(request, "main.html", "dashboard")

@app.get("/skills", response_class=HTMLResponse, include_in_schema=False)
def serve_skills(request: Request):
    return _render(request, "skills.html", "skills")

@app.get("/occupations", response_class=HTMLResponse, include_in_schema=False)
def serve_occupations(request: Request):
    return _render(request, "occupations.html", "occupations")

@app.get("/analytics", response_class=HTMLResponse, include_in_schema=False)
def serve_analytics(request: Request):
    return _render(request, "analytics.html", "analytics")

@app.get("/career", response_class=HTMLResponse, include_in_schema=False)
def serve_career(request: Request):
    return _render(request, "career.html", "career")

@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
def serve_login(request: Request):
    # Login page is exempt from AuthMiddleware (EXEMPT_PATHS in auth_middleware)
    return _render(request, "login.html", "login")

@app.get("/model-status", response_class=HTMLResponse, include_in_schema=False)
def serve_model_status(request: Request):
    return _render(request, "model_status.html", "model_status")


# ── PWA assets ────────────────────────────────────────────────────────────────

@app.get("/service-worker.js", include_in_schema=False)
async def get_service_worker() -> FileResponse:
    return FileResponse(
        "templates/js/service-worker.js",
        media_type="application/javascript",
    )

@app.get("/manifest.json", include_in_schema=False)
async def get_manifest() -> FileResponse:
    return FileResponse("templates/js/manifest.json")


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"], summary="Liveness probe")
def health_check() -> dict:
    """
    Returns ``200 OK`` when the application is running.
    Used by load balancers, container orchestrators, and uptime monitors.
    Does NOT check the database — use a dedicated readiness probe for that.
    """
    return {
        "status":  "healthy",
        "app":     settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


# ── Startup event ─────────────────────────────────────────────────────────────

@app.on_event("startup")
async def _startup() -> None:
    """
    Runs once when the ASGI server starts.
    Verifies the database connection so we fail fast instead of serving
    broken responses if the DB is unreachable.
    """
    verify_connection()
    logger.info("%s v%s starting …", settings.APP_NAME, settings.APP_VERSION)

    if settings.DEBUG:
        logger.info("  Dashboard : http://localhost:8000/")
        logger.info("  API Docs  : http://localhost:8000/docs  (admin credentials required)")
    else:
        logger.info("Running in PRODUCTION mode.")


# ── Direct execution ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,  # hot-reload in development only
        loop="asyncio",
    )