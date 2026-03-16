import hashlib
from fastapi import APIRouter, Depends, Query, Path
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.osca import OscaOccupation
from app.models.skills import EscoSkill, OscaOccupationSkill
from app.models.jobs import JobPostLog
from config import settings

router = APIRouter(prefix="/api/skills", tags=["skills"])

# Fingerprint — matches your config.py pattern
_AUTHOR = "MSIT402 CIM-10236"
_FP = hashlib.sha256(
    f"{_AUTHOR}:{settings.APP_NAME}:{settings.APP_VERSION}".encode()
).hexdigest()[:12]


@router.get("/summary")
def get_summary(db: Session = Depends(get_db)):
    """
    KPI cards in the header.
    Returns counts + your fingerprint signature.
    """
    # Using func.count() for efficiency, since we don't need the actual records.
    from sqlalchemy import func
    total_occupations = db.query(func.count(OscaOccupation.id)).scalar()
    total_skills        = db.query(func.count(EscoSkill.id)).scalar()
    total_job_posts     = db.query(func.count(JobPostLog.id)).scalar()
    total_skill_mappings = db.query(func.count(OscaOccupationSkill.id)).scalar()

    return {
        "total_occupations":    total_occupations,
        "total_skills":         total_skills,
        "total_job_posts":      total_job_posts,
        "total_skill_mappings": total_skill_mappings,
        "signature":            _FP,
        "_meta": {
            "app":     settings.APP_NAME,
            "version": settings.APP_VERSION,
            "fp":      _FP,
        }
    }


@router.get("/top/{occupation_id}")
def get_top_skills(
    occupation_id: int = Path(...),
    limit: int = Query(20, ge=5, le=50),
    db: Session = Depends(get_db)
):
    """
    Top N skills for a given occupation, ranked by mention_count.
    Powers the horizontal bar chart.

    Returns:
        skill_name, mention_count, demand_score (normalised 0-100),
        skill_type, first_seen, last_seen
    """
    rows = (
        db.query(
            EscoSkill.preferred_label.label("skill_name"),
            EscoSkill.skill_type,
            OscaOccupationSkill.mention_count,
            OscaOccupationSkill.first_seen_at.label("first_seen"),
            OscaOccupationSkill.last_seen_at.label("last_seen"),
            EscoSkill.description,     
            EscoSkill.alt_labels,      
            EscoSkill.skill_card, 
        )
        .join(EscoSkill, EscoSkill.id == OscaOccupationSkill.skill_id)
        .filter(OscaOccupationSkill.occupation_id == occupation_id)
        .order_by(OscaOccupationSkill.mention_count.desc())
        .limit(limit)
        .all()
    )

    if not rows:
        return []

    max_count = rows[0].mention_count or 1

    return [
        {
            "skill_name":    r.skill_name,
            "skill_type":    r.skill_type,
            "mention_count": r.mention_count,
            "demand_score":  round((r.mention_count / max_count) * 100, 1),
            "first_seen":    r.first_seen.isoformat() if r.first_seen else None,
            "last_seen":     r.last_seen.isoformat()  if r.last_seen  else None,
            #"description":   r.description,
            "alt_labels":    r.alt_labels,
            "skill_card":    r.skill_card,
        }
        for r in rows
    ]


@router.get("/breakdown/{occupation_id}")
def get_skill_breakdown(
    occupation_id: int = Path(...),
    db: Session = Depends(get_db)
):
    """
    Skill type distribution for the donut chart.
    Groups skills by ESCO type (knowledge / skill/ competence).
    """
    rows = (
        db.query(
            EscoSkill.skill_type,
            func.count(OscaOccupationSkill.skill_id).label("count"),
            func.sum(OscaOccupationSkill.mention_count).label("total_mentions"),
        )
        .join(EscoSkill, EscoSkill.id == OscaOccupationSkill.skill_id)
        .filter(OscaOccupationSkill.occupation_id == occupation_id)
        .group_by(EscoSkill.skill_type)
        .order_by(func.sum(OscaOccupationSkill.mention_count).desc())
        .all()
    )

    total = sum(r.total_mentions or 0 for r in rows)

    breakdown = [
        {
            "skill_type":     r.skill_type or "unknown",
            "count":          r.count,
            "total_mentions": r.total_mentions or 0,
            "percentage":     round((r.total_mentions or 0) / total * 100, 1) if total else 0,
        }
        for r in rows
    ]

    return {
        "occupation_id":  occupation_id,
        "total_mentions": total,
        "breakdown":      breakdown,
    }