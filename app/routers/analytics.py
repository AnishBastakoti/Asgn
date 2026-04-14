from fastapi import APIRouter, Depends, Request, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional
from datetime import date
from core.rate_limiter import limiter
from sqlalchemy.orm import Session

from core.auth_deps import require_admin
from app.database import get_db

# ── Service Imports ──────────────────────────────────────────
from app.services.analytics_service import (
    get_shadow_skills,
    get_skill_decay, 
    get_skill_velocity,
)
from app.services.demand_service import (
    get_city_demand_summary,
    get_city_demand_detail,
    get_market_saturation,
    get_occupation_profile,
    get_career_transition,
)
from app.services.ridge_service import (
    get_demand_forecast,
    get_model_status,
    get_occupation_prediction,
)
from app.services.similarity_service import get_occupation_similarity
from app.services.cluster_service import get_occupation_clusters, get_elbow_data

router = APIRouter(prefix="/api/analytics", tags=["Analytics"], dependencies=[Depends(require_admin)])

# ── Schemas ──────────────────────────────────────────────

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
    information_card: str

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

@router.get("/shadow-skills/{occupation_id}", response_model=List[ShadowSkillResponse])
@limiter.limit("20/minute")
def shadow_skills(request: Request, occupation_id: int, db: Session = Depends(get_db), admin = Depends(require_admin)):
    return get_shadow_skills(db, occupation_id)

@router.get("/skill-decay/{occupation_id}", response_model=List[SkillDecayResponse])
@limiter.limit("20/minute")
def skill_decay(request: Request, occupation_id: int, db: Session = Depends(get_db), admin = Depends(require_admin)):
    return get_skill_decay(db, occupation_id)

@router.get("/city-demand", response_model=List[CityDemandSummaryResponse])
@limiter.limit("20/minute")
def city_demand_summary(
    request: Request,
    from_date: Optional[date] = Query(None),
    to_date:   Optional[date] = Query(None),
    db: Session = Depends(get_db),
    admin = Depends(require_admin)
):
    return get_city_demand_summary(db, from_date, to_date)

@router.get("/city-demand/{city}", response_model=List[CityDemandDetailResponse])
@limiter.limit("20/minute")
def city_demand_detail(
    request: Request,
    city: str,
    limit: int = 20,
    from_date: Optional[date] = Query(None),
    to_date:   Optional[date] = Query(None),
    db: Session = Depends(get_db), 
    admin = Depends(require_admin)
):
    return get_city_demand_detail(db, city, limit, from_date, to_date)

@router.get("/predict-demand-by-occ/{occupation_id}", response_model=DemandPredictionResponse)
@limiter.limit("20/minute")
def predict_occ_demand(
    request: Request,
    occupation_id: int,
    model: Optional[str] = None,
    db: Session = Depends(get_db),
    admin = Depends(require_admin)
):
    prediction = get_occupation_prediction(db, occupation_id, model_preference=model)
    if not prediction:
        raise HTTPException(status_code=404, detail="No demand data found")
    return prediction

@router.get("/skill-velocity/{occupation_id}", response_model=SkillVelocityResponse)
@limiter.limit("20/minute")
def skill_velocity(request: Request, occupation_id: int, db: Session = Depends(get_db), admin = Depends(require_admin)):
    return get_skill_velocity(db, occupation_id)

@router.get("/market-saturation/{occupation_id}", response_model=MarketSaturationResponse)
@limiter.limit("20/minute")
def market_saturation(request: Request, occupation_id: int, db: Session = Depends(get_db), admin = Depends(require_admin)):
    return get_market_saturation(db, occupation_id)

@router.get("/occupation-profile/{occupation_id}", response_model=OccupationProfileResponse)
@limiter.limit("20/minute")
def occupation_profile(request: Request, occupation_id: int, db: Session = Depends(get_db), admin = Depends(require_admin)):
    result = get_occupation_profile(db, occupation_id)
    if not result:
        raise HTTPException(status_code=404, detail="Profile not found")
    return result

@router.get("/career-transition")
@limiter.limit("20/minute")
def career_transition(request: Request, from_id: int, to_id: int, db: Session = Depends(get_db), admin = Depends(require_admin)):
    return get_career_transition(db, from_id, to_id)

@router.get("/occupation-similarity/{occupation_id}")
@limiter.limit("20/minute")
def occupation_similarity(request: Request, occupation_id: int, top_n: int = 8, db: Session = Depends(get_db), admin = Depends(require_admin)):
    return get_occupation_similarity(db, occupation_id, top_n)

@router.get("/occupation-clusters/{occupation_id}")
@limiter.limit("20/minute")
def occupation_clusters(request: Request, occupation_id: int, n_clusters: Optional[int] = None, db: Session = Depends(get_db), admin = Depends(require_admin)):
    return get_occupation_clusters(db, occupation_id, n_clusters)

@router.get("/city-forecast/{city}")
@limiter.limit("20/minute")
def city_demand_forecast(request: Request, city: str, db: Session = Depends(get_db), admin = Depends(require_admin)):
    return get_demand_forecast(db, city)

@router.get("/model-status")
@limiter.limit("20/minute")
def model_status(request: Request, db: Session = Depends(get_db), admin = Depends(require_admin)):
    return get_model_status(db)

@router.get("/elbow-analysis")
@limiter.limit("20/minute")
def elbow_analysis(request: Request, k_max: int = 20, db: Session = Depends(get_db), admin = Depends(require_admin)):
    return get_elbow_data(db, k_max)
