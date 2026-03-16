from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from typing import List, Optional
from core.rate_limiter import limiter
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.analytics_service import (
    get_hot_skills,
    get_shadow_skills,
    get_skill_decay, 
    get_city_demand_detail,
    get_city_demand_summary,
    get_skill_velocity,
    get_market_saturation,
    get_occupation_profile,
    get_career_transition,
    get_occupation_similarity,
    get_occupation_clusters,
    get_demand_forecast,
    get_model_status,
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



class SkillVelocityItem(BaseModel):
    skill_name:   str
    latest_count: int
    slope:        float
    status:       str
 
class SkillVelocityResponse(BaseModel):
    snapshot_count: int
    rising:         List[SkillVelocityItem]
    falling:        List[SkillVelocityItem]
    stable:         List[SkillVelocityItem]
 
class MarketSaturationResponse(BaseModel):
    status:               str
    saturation_score:     float
    demand_ratio:         float
    complexity_ratio:     float
    occ_demand:           int
    platform_avg_demand:  float
    occ_skill_count:      int
    platform_avg_skills:  float
    label:                str
    insight:              str

class OccupationProfileResponse(BaseModel):
    occupation_id:    int
    title:            str
    skill_level:      Optional[int]
    lead_statement:   str
    main_tasks:       str
    licensing:        str
    caveats:          str
    specialisations:  str
    skill_attributes: str
    total_skills:     int
    skill_breakdown:  dict
# ══════════════════════════════════════════════════════════════════════════════
# RESPONSE MODELS FOR ANALYTICS ENDPOINTS

class DemandPredictionResponse(BaseModel):
    occupation_id: int
    occupation_title: str
    current_demand: int
    predicted_demand: int
    growth_rate: float
    confidence_score: float
    method: Optional[str] = None
    r2_score: Optional[float] = None

# ── Endpoints ────────────────────────────────────────────

# HOT SKILLS — no occupation filter, across all job posts
@router.get("/hot-skills", response_model=List[HotSkillResponse])
@limiter.limit("10/minute")
def hot_skills(request: Request, days: int = 30, db: Session = Depends(get_db)):
    """Top skills across all job posts in the last N days."""
    return get_hot_skills(db, days)


# SHADOW SKILLS 
@router.get("/shadow-skills/{occupation_id}", response_model=List[ShadowSkillResponse])
@limiter.limit("10/minute")
def shadow_skills(request: Request, occupation_id: int, db: Session = Depends(get_db)):
    """
    Skills appearing in job postings for this occupation
    that are not in the official OSCA skill mapping.
    """
    return get_shadow_skills(db, occupation_id)


# SKILL DECAY PK is occupation_id:int
@router.get("/skill-decay/{occupation_id}", response_model=List[SkillDecayResponse])
@limiter.limit("10/minute")
def skill_decay(request: Request, occupation_id: int, db: Session = Depends(get_db)):
    """
    Skills with significant demand decline for this occupation,
    comparing earliest vs most recent snapshot batch.
    """
    return get_skill_decay(db, occupation_id)


# CITY DEMAND SUMMARY — all cities with total job counts
@router.get("/city-demand", response_model=List[CityDemandSummaryResponse])
@limiter.limit("20/minute")
def city_demand_summary(
    request: Request,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: Session = Depends(get_db)
):
    return get_city_demand_summary(db, from_date, to_date)

# CITY DEMAND DETAIL — top N occupations for a specific city

@router.get("/city-demand/{city}", response_model=List[CityDemandDetailResponse])
@limiter.limit("20/minute")
def city_demand_detail(
    request: Request,
    city: str,
    limit: int = 10,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: Session = Depends(get_db)
):
    return get_city_demand_detail(db, city, limit, from_date, to_date)

    
# DEMAND FORECAST — Regression-based prediction for a city
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


# SKILL VELOCITY — rising/falling skills for an occupation
@router.get("/skill-velocity/{occupation_id}", response_model=SkillVelocityResponse)
#@limiter.limit("20/minute")
def skill_velocity(
    request: Request,
    occupation_id: int,
    db: Session = Depends(get_db)
):
    """
    Rising and falling skills for this occupation based on snapshot history.
    Returns stable list if only one snapshot exists.
    """
    return get_skill_velocity(db, occupation_id)
 
 
# MARKET SATURATION — supply/demand balance for an occupation
@router.get("/market-saturation/{occupation_id}", response_model=MarketSaturationResponse)
#@limiter.limit("20/minute")
def market_saturation(
    request: Request,
    occupation_id: int,
    db: Session = Depends(get_db)
):
    """
    Determines if occupation is undersupplied (hot), saturated,
    or balanced relative to platform averages.
    """
    return get_market_saturation(db, occupation_id)

# OCCUPATION PROFILE — official profile details for an occupation
@router.get("/occupation-profile/{occupation_id}", response_model=dict)
@limiter.limit("30/minute")
def occupation_profile(request: Request, occupation_id: int, db: Session = Depends(get_db)):
    return get_occupation_profile(db, occupation_id)


# CAREER TRANSITION ANALYZER
@router.get("/career-transition")
@limiter.limit("20/minute")
def career_transition(
    request: Request,
    from_id: int,
    to_id: int,
    db: Session = Depends(get_db)
):
    """Compare two occupations — shared skills, gaps, and difficulty score."""
    return get_career_transition(db, from_id, to_id)

# ── COSINE SIMILARITY — top N most similar occupations by skill vector
@router.get("/occupation-similarity/{occupation_id}")
@limiter.limit("20/minute")
def occupation_similarity(
    request: Request,
    occupation_id: int,
    top_n: int = 8,
    db: Session = Depends(get_db)
):
    """Top N occupations most similar to the selected one using cosine similarity on skill vectors."""
    from app.services.analytics_service import get_occupation_similarity
    return get_occupation_similarity(db, occupation_id, top_n)
 
 
# ── OCCUPATION CLUSTERING — K-Means cluster 
@router.get("/occupation-clusters/{occupation_id}")
@limiter.limit("10/minute")
def occupation_clusters(
    request: Request,
    occupation_id: int,
    n_clusters: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """Returns the K-Means cluster the occupation belongs to and its cluster peers."""
    from app.services.analytics_service import get_occupation_clusters
    return get_occupation_clusters(db, occupation_id, n_clusters)


# ── CITY DEMAND FORECAST — Ridge regression per city
@router.get("/city-forecast/{city}")
@limiter.limit("10/minute")
def city_demand_forecast(
    request: Request,
    city: str,
    db: Session = Depends(get_db)
):
    """Predicts demand for all occupations in a city using trained Ridge model."""
    return get_demand_forecast(db, city)
 
 
# ── MODEL STATUS — training metrics and cache state
@router.get("/model-status")
@limiter.limit("10/minute")
def model_status(request: Request, db: Session = Depends(get_db)):
    """Returns Ridge model training status, R² score, and feature list."""
    return get_model_status(db)
 
 
# ── ELBOW ANALYSIS — optimal K for K-Means
@router.get("/elbow-analysis")
@limiter.limit("5/minute")
def elbow_analysis(
    request: Request,
    k_max: int = 20,
    db: Session = Depends(get_db)
):
    """Runs K-Means for k=2..k_max and returns inertia values + optimal K."""
    from app.services.analytics_service import get_elbow_data
    return get_elbow_data(db, k_max)
 