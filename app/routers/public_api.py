from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel
from typing import List, Optional

from core.auth_deps import require_api_key
from app.database import get_db
from app.models.osca import OscaOccupation
from app.models.skills import EscoSkill, OscaOccupationSkill

router = APIRouter(prefix="/api/public", tags=["Public API"])

# ── Schemas ────────────────────────────────────────────────

class OccupationPublicResponse(BaseModel):
    id: int
    title: str
    skill_level: Optional[int]

class SkillPublicResponse(BaseModel):
    skill_name: str
    skill_type: Optional[str]
    concept_uri: Optional[str]
    mention_count: int

# ── Endpoints ──────────────────────────────────────────────

@router.get("/occupations", response_model=List[OccupationPublicResponse])
def public_occupations(
    # Enforce pagination with clear bounds
    limit: int = Query(50, ge=1, le=200, description="Max 200 items per page"),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    api_key = Depends(require_api_key)
):
    """
    Returns a paginated list of occupations. 
    Requires X-API-Key header.
    """
    rows = db.query(
        OscaOccupation.id,
        OscaOccupation.principal_title,
        OscaOccupation.skill_level,
    ).order_by(OscaOccupation.principal_title)\
     .offset(offset)\
     .limit(limit)\
     .all()

    return [
        {
            "id": r.id,
            "title": r.principal_title,
            "skill_level": r.skill_level,
        }
        for r in rows
    ]


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