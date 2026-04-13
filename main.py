import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates

from config import settings

from app.routers import skills, occupations, analytics, jobs, pipeline, auth
from app.logger import setup_logging
from app.database import verify_connection
from app.routers.public_api import router as public_router
from app.routers.api_keys  import router as api_keys_router
 
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded

from core.auth_middleware import AuthMiddleware
from core.rate_limiter import limiter
# ── Logging Setup 
setup_logging()

logger = logging.getLogger(__name__)


# ── App Instance ─
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
    SkillPulse — Australian Job Market Intelligence Platform
    
    Analyses skill demand across OSCA occupations using
    real job posting data and ESCO skill taxonomy.
    """,
    
    docs_url="/docs" if settings.DEBUG else None,      # Swagger UI at /docs
    redoc_url="/redocs" if settings.DEBUG else None,   # ReDoc UI at /redoc
    # Register limiter
)
app.state.limiter = limiter
app.add_middleware(AuthMiddleware)
app.add_middleware(SlowAPIMiddleware)



# Global exception handler for rate limits
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Please try again later."}
    )
# ── CORS Middleware 
# CORS = Cross Origin Resource Sharing
# Allows our frontend (port) to call our API (port) without browser blocking
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_methods=settings.CORS_ALLOW_METHODS,
    allow_headers=settings.CORS_ALLOW_HEADERS,
    allow_credentials=True,
)


# ── Routers ──────
# Register all routers — each brings its own set of endpoints
app.include_router(skills.router)
app.include_router(occupations.router)
app.include_router(jobs.router)
app.include_router(analytics.router)
app.include_router(pipeline.router)
app.include_router(auth.router)
app.include_router(public_router)
app.include_router(api_keys_router)
#app.include_router(printfile.router)


# ── Static Files ─
# Serve frontend files from the static folder
app.mount("/templates", StaticFiles(directory="templates"), name="static")
templates = Jinja2Templates(directory="templates")

# After mount on  static files, add a middleware:
@app.middleware("http")
async def no_cache_middleware(request: Request, call_next):
    response = await call_next(request)
    # Only apply to JS/CSS/HTML files
    if request.url.path.startswith("/templates/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


def _render(request, template_name, page):
    return templates.TemplateResponse(
        request=request,        # request goes FIRST now
        name=template_name,     # then the template name
        context={               
            "active_page": page,
            "app_name":    settings.APP_NAME,
            "app_version": settings.APP_VERSION,
        },
    )

# ── Root Route ───

# -- jinga2 templates setup for dynamic rendering

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def serve_frontend(request: Request):
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
    return _render(request, "login.html", "login")

@app.get("/model-status", response_class=HTMLResponse, include_in_schema=False)
def serve_model_status(request: Request):
    return _render(request, "model_status.html", "model_status")

@app.get("/service-worker.js")
async def get_sw():
    # Point this to the actual physical path of the file
    return FileResponse("templates/js/service-worker.js", media_type="application/javascript")

@app.get("/manifest.json")
async def get_manifest():
    return FileResponse("templates/js/manifest.json")
# ── Health Check ─
@app.get("/health", tags=["System"])
def health_check():
    """
    Health check endpoint.
    Returns 200 OK if everything is fine.
    """
    return {
        "status":  "healthy",
        "app":     settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


# ── Startup Event 
@app.on_event("startup")
async def startup_event():
    """
    Runs once when the application starts.
    """
    verify_connection()  # Check DB connection before accepting requests
    logger.info(f" {settings.APP_NAME} v{settings.APP_VERSION} starting...")
    logger.info(f" Dashboard: http://localhost:8000")
    logger.info(f" API Docs:  http://localhost:8000/docs")

# ── Run directly ─
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,  # auto-reload on code changes in dev
        loop="asyncio"
    )
