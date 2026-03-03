import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from config import settings
from app.routers import skills, occupations, analytics, jobs

# ── Logging Setup 
# Configure logging once here — all other files use getLogger()

logging.basicConfig(
    level=logging.INFO if settings.DEBUG else logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
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
    docs_url="/docs",      # Swagger UI at /docs
    redoc_url="/redoc"     # ReDoc UI at /redoc
)


# ── CORS Middleware 
# CORS = Cross Origin Resource Sharing
# Allows our frontend (port) to call our API (port) without browser blocking
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routers ──────
# Register all routers — each brings its own set of endpoints
app.include_router(skills.router)
app.include_router(occupations.router)
app.include_router(jobs.router)
app.include_router(analytics.router)


# ── Static Files ─
# Serve frontend files from the static folder
app.mount("/templates", StaticFiles(directory="templates"), name="static")
templates = Jinja2Templates(directory="templates")

# ── Root Route ───

# -- jinga2 templates setup for dynamic rendering

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def serve_frontend(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "activate_page": "dashboard",
        "app_name": settings.APP_NAME,
        "app_version": settings.APP_VERSION
    })

@app.get("/skills", response_class=HTMLResponse, include_in_schema=False)
def skills_page(request: Request):
    return templates.TemplateResponse("skills.html", {
        "request": request,
        "active_page": "skills"
    })

@app.get("/occupations", response_class=HTMLResponse, include_in_schema=False)
def occupations_page(request: Request):
    return templates.TemplateResponse("occupations.html", {
        "request": request,
        "active_page": "occupations"
    })

@app.get("/analytics", response_class=HTMLResponse, include_in_schema=False)
def analytics_page(request: Request):
    return templates.TemplateResponse("analytics.html", {
        "request": request,
        "active_page": "analytics"
    })

@app.get("/pipeline", response_class=HTMLResponse, include_in_schema=False)
def pipeline_page(request: Request):
    return templates.TemplateResponse("pipeline.html", {
        "request": request,
        "active_page": "pipeline"
    })


@app.get("/occupation/{occupation_id}", response_class=HTMLResponse, include_in_schema=False)
def occupation_dashboard(
    occupation_id: int,
    request: Request,
):
  return templates.TemplateResponse(
        "occupation_analytics.html",
        {
            "request": request,
            "occupation": None  # Default value if occupation is not found
        }
    )

@app.get("/dashboard/hot-skills", response_class=HTMLResponse)
def hot_skills_page(request: Request):
    """
    Render dashboard HTML for hot skills.
    """
    return templates.TemplateResponse("hot_skills.html", {"request": request})


@app.get("/dashboard/skill-decay/{osca_code}", response_class=HTMLResponse)
def skill_decay_page(request: Request, osca_code: str):
    """
    Render dashboard HTML for skill decay of a specific occupation.
    """
    return templates.TemplateResponse("skill_decay.html", {
        "request": request,
        "osca_code": osca_code
    })

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
        reload=settings.DEBUG  # auto-reload on code changes in dev
    )
