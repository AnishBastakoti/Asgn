from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.orm import Session

from core.auth_deps import require_auth,require_admin
from core.rate_limiter import limiter          
from app.database import get_db
from app.services.jobs_service import (
    get_cities_by_occupation,
    get_skill_overlap,
    get_top_companies,
    get_city_lead_indicator,
    get_hot_skills_for_occupation,
    get_skill_gap_radar
)

router = APIRouter(
    prefix="/api/jobs",
    tags=["Jobs"],
    dependencies=[Depends(require_admin)],
)

# ── Schemas ────────────────────────────────────────────────

class CityResponse(BaseModel):
    city:      str
    job_count: int

class TrendPoint(BaseModel):
    date:  str
    count: int
    day:   int
    rate:  Optional[float] = None

class SkillTrendResponse(BaseModel):
    skill_id:       int
    skill_name:     str
    concept_uri:    Optional[str] = None
    points:         List[TrendPoint]
    trend:          str
    velocity:       float
    momentum:       str
    latest_count:   int
    peak_count:     int
    snapshot_count: int
    is_fallback:    bool

class OverlapResponse(BaseModel):
    skills:      List[str]
    occupations: List[str]
    matrix:      List[List[int]]

class CompanyResponse(BaseModel):
    company:  str
    postings: int

class CityLeadResponse(BaseModel):
    city:           str
    first_seen:     Optional[str] = None
    total_postings: int
    is_lead:        bool
    rank:           int

class HotSkillResponse(BaseModel):
    skill_name:     str
    total_mentions: int
    share_pct:      float

class SkillGapTypeItem(BaseModel):
    key:            str
    label:          str
    official_count: int
    matched_count:  int
    missing_count:  int
    coverage_pct:   float
    top_matched:    List[str]
    top_missing:    List[str]

class SkillGapRadarResponse(BaseModel):
    occupation_id: int
    radar:         dict
    summary:       dict
    by_type:       List[SkillGapTypeItem]


# ── Endpoints ──────────────────────────────────────────────

@router.get("/cities/", response_model=List[CityResponse])
@limiter.limit("20/minute")
def city_demand(
    request:       Request,           
    occupation_id: int,
    db:            Session = Depends(get_db),
):
    """Australian city demand distribution for an occupation."""
    result = get_cities_by_occupation(db, occupation_id)
    if not result:
        raise HTTPException(
            status_code=404,
            detail="No city distribution found for this occupation.",
        )
    return result


@router.get("/skill-gap-radar/{occupation_id}", response_model=SkillGapRadarResponse)
@limiter.limit("20/minute")
def skill_gap_radar(
    request:       Request,           
    occupation_id: int,
    db:            Session = Depends(get_db),
):
    """
    Compares official OSCA skill mapping against skills extracted from real
    job postings. Returns a 5-axis radar payload plus per-skill-type coverage
    breakdowns (matched vs gap skills).
    """
    result = get_skill_gap_radar(db, occupation_id)
    if not result:
        raise HTTPException(
            status_code=404,
            detail="No official skills found for this occupation.",
        )
    return result


@router.get("/overlap/", response_model=OverlapResponse)
@limiter.limit("20/minute")
def skill_overlap(
    request:       Request,           
    occupation_id: int,
    db:            Session = Depends(get_db),
):
    """Skill overlap heatmap between related occupations."""
    result = get_skill_overlap(db, occupation_id)
    if not result:
        raise HTTPException(
            status_code=404,
            detail="No skill overlaps found for this occupation.",
        )
    return result


@router.get("/companies/", response_model=List[CompanyResponse])
@limiter.limit("20/minute")
def top_companies(
    request:       Request,           
    occupation_id: int,
    db:            Session = Depends(get_db),
):
    """Top hiring companies for an occupation."""
    result = get_top_companies(db, occupation_id)
    if not result:
        raise HTTPException(
            status_code=404,
            detail="No top companies found for this occupation.",
        )
    return result


@router.get("/lead-cities/", response_model=List[CityLeadResponse])
@limiter.limit("20/minute")
def lead_cities(
    request:       Request,           
    occupation_id: int,
    db:            Session = Depends(get_db),
):
    """City lead indicators — which cities post first."""
    result = get_city_lead_indicator(db, occupation_id)
    if not result:
        raise HTTPException(
            status_code=404,
            detail="No lead cities found for this occupation.",
        )
    return result


@router.get("/hot-skills/", response_model=List[HotSkillResponse])
@limiter.limit("20/minute")
def hot_skills_for_occupation(
    request:       Request,           
    occupation_id: int,
    days:          int = 30,
    db:            Session = Depends(get_db),
):
    """Top skills across all job posts in the last N days."""
    result = get_hot_skills_for_occupation(db, occupation_id, days)
    if not result:
        raise HTTPException(
            status_code=404,
            detail="No trending skills found for this occupation.",
        )
    return result