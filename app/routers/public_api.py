from fastapi import APIRouter, Depends, Query, HTTPException, Path
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from pydantic import BaseModel
from typing import List, Optional

from core.auth_deps import require_api_key
from app.database import get_db
from app.models.osca import OscaOccupation, OscaMajorGroup, OscaSubMajorGroup, OscaMinorGroup, OscaUnitGroup
from app.models.skills import EscoSkill, OscaOccupationSkill
from app.services.jobs_service import get_cities_by_occupation, get_skill_gap_radar, get_hot_skills_for_occupation
from app.services.analytics_service import get_shadow_skills
from app.services.demand_service import get_market_saturation, get_career_transition
from app.services.ridge_service import get_occupation_prediction, get_demand_forecast
from app.services.similarity_service import get_occupation_similarity

router = APIRouter(prefix="/api/public", tags=["Public API"])

# ── Schemas ────────────────────────────────────────────────

class SkillPublicResponse(BaseModel):
    skill_name: str
    skill_type: Optional[str]
    concept_uri: Optional[str]
    mention_count: int

# ── 1. Occupations ─────────────────────────────────────────

@router.get("/occupations/major-groups")
def public_major_groups(db: Session = Depends(get_db), api_key = Depends(require_api_key)):
    """Get all major occupation groups."""
    rows = (
        db.query(
            OscaMajorGroup.id,
            OscaMajorGroup.title,
            func.count(OscaOccupation.id).label("occupation_count")
        )
        .join(OscaSubMajorGroup, OscaSubMajorGroup.major_group_id == OscaMajorGroup.id)
        .join(OscaMinorGroup,    OscaMinorGroup.sub_major_group_id == OscaSubMajorGroup.id)
        .join(OscaUnitGroup,     OscaUnitGroup.minor_group_id == OscaMinorGroup.id)
        .join(OscaOccupation,    OscaOccupation.unit_group_id == OscaUnitGroup.id)
        .group_by(OscaMajorGroup.id, OscaMajorGroup.title)
        .order_by(OscaMajorGroup.id)
        .all()
    )
    return [{"id": r.id, "title": r.title, "occupation_count": r.occupation_count} for r in rows]

@router.get("/occupations/list")
def public_occupations_list(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    api_key = Depends(require_api_key)
):
    """Paginated list of ANZSCO occupations."""
    rows = db.query(OscaOccupation.id, OscaOccupation.principal_title, OscaOccupation.skill_level)\
             .order_by(OscaOccupation.principal_title).offset(offset).limit(limit).all()
    return [{"id": r.id, "title": r.principal_title, "skill_level": r.skill_level} for r in rows]

@router.get("/occupations/{occupation_id}")
def public_occupation_detail(
    occupation_id: int = Path(...),
    db: Session = Depends(get_db),
    api_key = Depends(require_api_key)
):
    """Get detailed profile for an occupation."""
    occ = db.query(OscaOccupation).filter(OscaOccupation.id == occupation_id).first()
    if not occ: raise HTTPException(status_code=404, detail="Occupation not found")
    return {
        "id": occ.id, "title": occ.principal_title, "skill_level": occ.skill_level,
        "tasks": occ.main_tasks, "specialisations": occ.specialisations
    }

# ── 2. Jobs & Demand ───────────────────────────────────────

@router.get("/jobs/cities/")
def public_city_demand(occupation_id: int, db: Session = Depends(get_db), api_key = Depends(require_api_key)):
    return get_cities_by_occupation(db, occupation_id)

@router.get("/jobs/skill-gap-radar/{occupation_id}")
def public_gap_radar(occupation_id: int, db: Session = Depends(get_db), api_key = Depends(require_api_key)):
    return get_skill_gap_radar(db, occupation_id)

@router.get("/jobs/hot-skills/")
def public_hot_skills(occupation_id: int, days: int = 30, db: Session = Depends(get_db), api_key = Depends(require_api_key)):
    return get_hot_skills_for_occupation(db, occupation_id, days)

# ── 3. Advanced Analytics ──────────────────────────────────

@router.get("/analytics/shadow-skills/{occupation_id}")
def public_shadow_skills(occupation_id: int, db: Session = Depends(get_db), api_key = Depends(require_api_key)):
    return get_shadow_skills(db, occupation_id)

@router.get("/analytics/predict-demand-by-occ/{occupation_id}")
def public_predict_demand(occupation_id: int, db: Session = Depends(get_db), api_key = Depends(require_api_key)):
    return get_occupation_prediction(db, occupation_id)

@router.get("/analytics/market-saturation/{occupation_id}")
def public_saturation(occupation_id: int, db: Session = Depends(get_db), api_key = Depends(require_api_key)):
    return get_market_saturation(db, occupation_id)

@router.get("/analytics/career-transition")
def public_transition(from_id: int, to_id: int, db: Session = Depends(get_db), api_key = Depends(require_api_key)):
    return get_career_transition(db, from_id, to_id)

@router.get("/analytics/occupation-similarity/{occupation_id}")
def public_similarity(occupation_id: int, db: Session = Depends(get_db), api_key = Depends(require_api_key)):
    return get_occupation_similarity(db, occupation_id)

@router.get("/analytics/city-forecast/{city}")
def public_city_forecast(city: str, db: Session = Depends(get_db), api_key = Depends(require_api_key)):
    return get_demand_forecast(db, city)


@router.get("/skills/top/{occupation_id}", response_model=List[SkillPublicResponse])
def public_top_skills(
    occupation_id: int,
    #Prevent users from requesting thousands of rows
    limit: int = Query(10, ge=1, le=50, description="Max 50 skills per request"),
    db: Session = Depends(get_db),
    api_key = Depends(require_api_key)
):
    """
    Returns top skills for an occupation. 
    Requires X-API-Key header.
    """
    # Verify occupation exists first 
    exists = db.query(OscaOccupation.id).filter(OscaOccupation.id == occupation_id).first()
    if not exists:
        raise HTTPException(status_code=404, detail="Occupation not found")

    rows = (
        db.query(
            EscoSkill.preferred_label.label("skill_name"),
            EscoSkill.skill_type,
            EscoSkill.concept_uri,
            OscaOccupationSkill.mention_count,
        )
        .join(EscoSkill, EscoSkill.id == OscaOccupationSkill.skill_id)
        .filter(OscaOccupationSkill.occupation_id == occupation_id)
        .order_by(desc(OscaOccupationSkill.mention_count))
        .limit(limit)
        .all()
    )

    return [
        {
            "skill_name":    r.skill_name,
            "skill_type":    r.skill_type,
            "concept_uri":   r.concept_uri,
            "mention_count": r.mention_count,
        }
        for r in rows
    ]