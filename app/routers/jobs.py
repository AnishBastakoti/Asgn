from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from core.auth_deps import require_auth
from app.database import get_db
from app.services.jobs_service import (
    get_cities_by_occupation,
    get_skill_trends_by_occupation,
    get_skill_overlap,
    get_top_companies,
    get_city_lead_indicator,
    get_hot_skills_for_occupation,
)

router = APIRouter(prefix="/api/jobs", tags=["Jobs"], dependencies=[Depends(require_auth)])


# ── Schemas ────────────────────────────────────────────────
class CityResponse(BaseModel):
    city:      str
    job_count: int

class TrendPoint(BaseModel):
    date:  str
    count: int
    day: int
    rate: Optional[float]  # Only for single-snapshot fallback

class SkillTrendResponse(BaseModel):
    skill_id:       int
    skill_name:     str
    concept_uri:    Optional[str] = None
    points:         list[TrendPoint]
    trend:          str
    velocity:       float
    momentum:       str             
    latest_count:   int             
    peak_count:     int             
    snapshot_count: int             
    is_fallback:    bool

class OverlapResponse(BaseModel):
    skills:      list[str]
    occupations: list[str]
    matrix:      list[list[int]]

class CompanyResponse(BaseModel):
    company:  str
    postings: int

class CityLeadResponse(BaseModel):
    city:           str
    first_seen:     Optional[str]
    total_postings: int
    is_lead:        bool
    rank:           int

class HotSkillResponse(BaseModel):
    skill_name:     str
    total_mentions: int
    share_pct:      float


# ── Endpoints ──────────────────────────────────────────────
@router.get("/cities/", response_model=list[CityResponse])
def city_demand(occupation_id: int, db: Session = Depends(get_db)):
    """Australian city demand distribution for an occupation."""
    return get_cities_by_occupation(db, occupation_id)


@router.get("/trends/", response_model=list[SkillTrendResponse])
def skill_trends(occupation_id: int, db: Session = Depends(get_db)):
    """Skill demand trends over time with velocity scores."""
    return get_skill_trends_by_occupation(db, occupation_id)


@router.get("/overlap/", response_model=OverlapResponse)
def skill_overlap(occupation_id: int, db: Session = Depends(get_db)):
    """Skill overlap heatmap between related occupations."""
    return get_skill_overlap(db, occupation_id)


@router.get("/companies/", response_model=list[CompanyResponse])
def top_companies(occupation_id: int, db: Session = Depends(get_db)):
    """Top hiring companies for an occupation."""
    return get_top_companies(db, occupation_id)


@router.get("/lead-cities/", response_model=list[CityLeadResponse])
def lead_cities(occupation_id: int, db: Session = Depends(get_db)):
    """City lead indicators — which cities post first."""
    return get_city_lead_indicator(db, occupation_id)

# HOT SKILLS — no occupation filter, across all job posts
@router.get("/hot-skills/", response_model=None)
def hot_skills_for_occupation(occupation_id: int, days: int = 30, db: Session = Depends(get_db)):
    """Top skills across all job posts in the last N days."""
    return get_hot_skills_for_occupation(db, occupation_id, days)

