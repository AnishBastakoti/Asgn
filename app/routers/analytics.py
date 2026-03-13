from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from typing import List
from core.rate_limiter import limiter
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.analytics_service import (
    get_hot_skills,
    get_shadow_skills,
    get_skill_decay, 
    get_city_demand_detail,
    get_city_demand_summary
)
#from main import Limiter

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])


# ── Schemas ──────────────────────────────────────────────
class HotSkillResponse(BaseModel):
    skill_name:     str
    total_mentions: int
    share_pct:      float

class ShadowSkillResponse(BaseModel):
    skill_name: str

class SkillDecayResponse(BaseModel):
    skill_name:       str
    past_mentions:    int
    current_mentions: int
    decline:          int
    decline_pct:      float

class CityDemandSummaryResponse(BaseModel):
    city:             str
    total_jobs:       int
    occupation_count: int
    demand_pct:       float

class CityDemandDetailResponse(BaseModel):
    occupation_title: str
    occupation_id:    int
    total_jobs:       int
    demand_pct:       float


# ══════════════════════════════════════════════════════════════════════════════
# RESPONSE MODELS FOR ANALYTICS ENDPOINTS

class DemandPredictionResponse(BaseModel):
    occupation_id: int
    occupation_title: str
    current_demand: int
    predicted_demand: int
    growth_rate: float
    confidence_score: float

# ── Endpoints ────────────────────────────────────────────

# 1. HOT SKILLS — no occupation filter, across all job posts
@router.get("/hot-skills", response_model=List[HotSkillResponse])
@limiter.limit("10/minute")
def hot_skills(request: Request, days: int = 30, db: Session = Depends(get_db)):
    """Top skills across all job posts in the last N days."""
    return get_hot_skills(db, days)


# 2. SHADOW SKILLS — FIX: was osca_code:str, real PK is occupation_id:int
@router.get("/shadow-skills/{occupation_id}", response_model=List[ShadowSkillResponse])
@limiter.limit("10/minute")
def shadow_skills(request: Request, occupation_id: int, db: Session = Depends(get_db)):
    """
    Skills appearing in job postings for this occupation
    that are not in the official OSCA skill mapping.
    """
    return get_shadow_skills(db, occupation_id)


# 3. SKILL DECAY — FIX: was osca_code:str, real PK is occupation_id:int
@router.get("/skill-decay/{occupation_id}", response_model=List[SkillDecayResponse])
@limiter.limit("10/minute")
def skill_decay(request: Request, occupation_id: int, db: Session = Depends(get_db)):
    """
    Skills with significant demand decline for this occupation,
    comparing earliest vs most recent snapshot batch.
    """
    return get_skill_decay(db, occupation_id)



# 4. CITY DEMAND SUMMARY — all cities with total job counts
@router.get("/city-demand", response_model=List[CityDemandSummaryResponse])
@limiter.limit("20/minute")
def city_demand_summary(request: Request, db: Session = Depends(get_db)):
    """All cities with total job counts for city selector cards."""
    return get_city_demand_summary(db)


# 5. CITY DEMAND DETAIL — top N occupations for a specific city
@router.get("/city-demand/{city}", response_model=List[CityDemandDetailResponse])
@limiter.limit("20/minute")
def city_demand_detail(
    request: Request,
    city: str,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """Top N occupations demanded in a specific city."""
    return get_city_demand_detail(db, city, limit)


# 6. DEMAND FORECAST — Regression-based prediction for a city
@router.get("/predict-demand-by-occ/{occupation_id}", response_model=DemandPredictionResponse)
@limiter.limit("20/minute")
def predict_occ_demand(
    request: Request,
    occupation_id: int,
    limit: int = 10, 
    db: Session = Depends(get_db)):
    """
    Fetches the regression-based demand forecast for a specific occupation.
    """
    from app.services.analytics_service import get_occupation_prediction
    prediction = get_occupation_prediction(db, occupation_id)
    if not prediction:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="No demand data found")
    return prediction