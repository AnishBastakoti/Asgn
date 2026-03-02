# # All logic in services.

# from fastapi import APIRouter, Depends, HTTPException, Query, Path
# from pydantic import BaseModel
# from typing import Optional
# from sqlalchemy.orm import Session

# from app.database import get_db
# from app.services.skills_service import (
#     get_top_skills_for_occupation,
#     get_skill_type_breakdown,
#     get_dashboard_summary,
#     get_skill_trends
# )

# router = APIRouter(prefix="/api/skills", tags=["Skills"])


# #---- Response Schemas 


# class SkillResponse(BaseModel):
#     skill_id:      int
#     skill_name:    str
#     skill_type:    str
#     mention_count: int
#     demand_score:  float
#     first_seen:    Optional[str]
#     last_seen:     Optional[str]

#     class Config:
#         from_attributes = True


# class SkillTypeBreakdown(BaseModel):
#     skill_type:     str
#     count:          int
#     total_mentions: int
#     percentage:     float


# class BreakdownResponse(BaseModel):
#     occupation_id:  int
#     total_mentions: int
#     breakdown:      list[SkillTypeBreakdown]


# class SummaryResponse(BaseModel):
#     total_occupations:    int
#     total_skills:         int
#     total_job_posts:      int
#     processed_job_posts:  int
#     total_skill_mappings: int
#     signature:            str  # visible in API!


# class TrendPoint(BaseModel):
#     date:          Optional[str]
#     mention_count: int
#     demand_score:  float


# # --- Endpoints 

# @router.get("/summary", response_model=SummaryResponse)
# def get_summary(db: Session = Depends(get_db)):
#     """
#     Dashboard header stats.
#     Called once when the page loads.
#     Depends(get_db) — FastAPI automatically:
#     """
#     return get_dashboard_summary(db)


# @router.get("/top/{occupation_id}", response_model=list[SkillResponse])
# def get_top_skills(
#     occupation_id: int,
#     limit: int = Query(default=20, ge=5, le=50, description="Number of skills to return"),
#     db: Session = Depends(get_db)
# ):
#     """
#     Top N skills for a specific occupation ranked by demand score.
#     Powers the main bar chart.
    
#     ge=5  means minimum value is 5
#     le=50 means maximum value is 50
#     FastAPI validates this automatically — no manual checking needed.
#     """
#     skills = get_top_skills_for_occupation(db, occupation_id, limit)

#     if not skills:
#         raise HTTPException(
#             status_code=404,
#             detail=f"No skill data found for occupation {occupation_id}"
#         )

#     return skills


# @router.get("/breakdown/{occupation_id}", response_model=BreakdownResponse)
# def get_breakdown(
#     occupation_id: int,
#     db: Session = Depends(get_db)
# ):
#     """
#     Skill type distribution for an occupation.
#     Powers the donut chart.
#     """
#     return get_skill_type_breakdown(db, occupation_id)


# @router.get("/trends/{occupation_id}/{skill_id}", response_model=list[TrendPoint])
# def get_trends(
#     occupation_id: int,
#     skill_id:      int,
#     db: Session = Depends(get_db)
# ):
#     """
#     Time series trend for a skill within an occupation.
#     Powers the trend line chart.
#     """
#     trends = get_skill_trends(db, occupation_id, skill_id)

#     if not trends:
#         raise HTTPException(
#             status_code=404,
#             detail=f"No trend data found for skill {skill_id} in occupation {occupation_id}"
#         )

#     return trends



"""
routers/skills.py
=================
Endpoints the frontend calls for charts and KPI cards.

GET /api/skills/summary
GET /api/skills/top/{occupation_id}?limit=20
GET /api/skills/breakdown/{occupation_id}
"""

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
    total_occupations   = db.query(OscaOccupation).count()
    total_skills        = db.query(EscoSkill).count()
    total_job_posts     = db.query(JobPostLog).count()
    total_skill_mappings = db.query(OscaOccupationSkill).count()

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
    Groups skills by ESCO type (knowledge / skill/competence / attitude).
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