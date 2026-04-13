from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import desc

from core.auth_deps import require_api_key
from app.database import get_db
from app.models.osca import OscaOccupation
from app.models.skills import EscoSkill, OscaOccupationSkill

router = APIRouter(prefix="/api/public", tags=["Public API"])


@router.get("/occupations")
def public_occupations(
    db:      Session = Depends(get_db),
    api_key = Depends(require_api_key)
):
    """Returns list of all occupations. Requires X-API-Key header."""
    rows = db.query(
        OscaOccupation.id,
        OscaOccupation.principal_title,
        OscaOccupation.skill_level,
    ).order_by(OscaOccupation.principal_title).all()

    return [
        {
            "id":          r.id,
            "title":       r.principal_title,
            "skill_level": r.skill_level,
        }
        for r in rows
    ]


@router.get("/skills/top/{occupation_id}")
def public_top_skills(
    occupation_id: int,
    limit:   int = 10,
    db:      Session = Depends(get_db),
    api_key = Depends(require_api_key)
):
    """Returns top skills for an occupation. Requires X-API-Key header."""
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