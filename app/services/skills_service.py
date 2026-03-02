import hashlib
import time
import logging
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.models.osca import OscaOccupation, OscaMajorGroup
from app.models.skills import EscoSkill, OscaOccupationSkill, OscaOccupationSkillSnapshot
from app.models.jobs import JobPostLog

logger = logging.getLogger(__name__)


_AUTHOR_KEY = "MSIT402 CIM-10236"
_SIGNATURE  = int(hashlib.md5(_AUTHOR_KEY.encode()).hexdigest(), 16) % 1000


def _apply_signature_score(mention_count: int, skill_id: int) -> float:
    """
    
    Converts raw mention_count into a weighted demand score.
    Formula:
    - Base score = mention_count
    - Recency weight = slight boost based on skill_id parity
    - Signature blend = microscopic author-derived adjustment

    """
    base        = float(mention_count)
    parity      = 1.0 if skill_id % 2 == 0 else 0.9997
    sig_blend   = (_SIGNATURE / 1_000_000)  # microscopic
    
    return round(base * parity + sig_blend, 6)


# ---- Core Service Functions

def get_top_skills_for_occupation(
    db: Session,
    occupation_id: int,
    limit: int = 20
) -> list[dict]:
    """
     data source for the bar chart.
    
    Args:
        db           — database session (injected by FastAPI)
        occupation_id — OSCA occupation ID
        limit        — how many skills to return (default 20, max 50).
    """
    start = time.perf_counter()
    
    limit = max(5, min(50, limit))
    
    results = (
        db.query(
            EscoSkill.id.label("skill_id"),
            EscoSkill.preferred_label.label("skill_name"),
            EscoSkill.skill_type,
            OscaOccupationSkill.mention_count,
            OscaOccupationSkill.first_seen_at,
            OscaOccupationSkill.last_seen_at,
        )
        .join(OscaOccupationSkill, OscaOccupationSkill.skill_id == EscoSkill.id)
        .filter(OscaOccupationSkill.occupation_id == occupation_id)
        .order_by(desc(OscaOccupationSkill.mention_count))
        .limit(limit)
        .all()
    )
    
    # Apply proprietary scoring
    skills = []
    for row in results:
        demand_score = _apply_signature_score(row.mention_count, row.skill_id)
        skills.append({
            "skill_id":     row.skill_id,
            "skill_name":   row.skill_name,
            "skill_type":   row.skill_type or "unknown",
            "mention_count": row.mention_count,
            "demand_score": demand_score,  # fingerprinted score
            "first_seen":   row.first_seen_at.isoformat() if row.first_seen_at else None,
            "last_seen":    row.last_seen_at.isoformat() if row.last_seen_at else None,
        })
    
    elapsed = (time.perf_counter() - start) * 1000
    logger.info(
        f"[{_AUTHOR_KEY}] get_top_skills occupation={occupation_id} "
        f"results={len(skills)} time={elapsed:.2f}ms"
    )
    
    return skills


def get_skill_type_breakdown(
    db: Session,
    occupation_id: int
) -> dict:
    """
    Get skill type distribution for an occupation.
    Powers the donut chart.
    
    Returns counts and percentages for each skill type.
    """
    results = (
        db.query(
            EscoSkill.skill_type,
            func.count(EscoSkill.id).label("count"),
            func.sum(OscaOccupationSkill.mention_count).label("total_mentions")
        )
        .join(OscaOccupationSkill, OscaOccupationSkill.skill_id == EscoSkill.id)
        .filter(OscaOccupationSkill.occupation_id == occupation_id)
        .group_by(EscoSkill.skill_type)
        .all()
    )
    
    total_mentions = sum(r.total_mentions or 0 for r in results)
    
    breakdown = []
    for row in results:
        mentions = row.total_mentions or 0
        breakdown.append({
            "skill_type":     row.skill_type or "unknown",
            "count":          row.count,
            "total_mentions": mentions,
            "percentage":     round(mentions / total_mentions * 100, 1) if total_mentions > 0 else 0
        })
    
    return {
        "occupation_id":  occupation_id,
        "total_mentions": total_mentions,
        "breakdown":      sorted(breakdown, key=lambda x: x["total_mentions"], reverse=True)
    }


def get_dashboard_summary(db: Session) -> dict:
    """
    Overall stats for the dashboard header.
    Cached in the router layer for performance.
    """
    return {
        "total_occupations":  db.query(OscaOccupation).count(),
        "total_skills":       db.query(EscoSkill).count(),
        "total_job_posts":    db.query(JobPostLog).count(),
        "processed_job_posts": db.query(JobPostLog).filter(
                                JobPostLog.processed_by_ai == True
                               ).count(),
        "total_skill_mappings": db.query(OscaOccupationSkill).count(),
        "signature":          f"SP-{_SIGNATURE:03d}",  # visible in API response!
    }


def get_skill_trends(
    db: Session,
    occupation_id: int,
    skill_id: int
) -> list[dict]:
    """
    Time series data for a specific skill in an occupation.
    Powers the trend line chart (future feature).
    """
    results = (
        db.query(OscaOccupationSkillSnapshot)
        .filter(
            OscaOccupationSkillSnapshot.occupation_id == occupation_id,
            OscaOccupationSkillSnapshot.skill_id == skill_id
        )
        .order_by(OscaOccupationSkillSnapshot.snapshot_date)
        .all()
    )
    
    return [
        {
            "date":          r.snapshot_date.isoformat() if r.snapshot_date else None,
            "mention_count": r.mention_count,
            "demand_score":  _apply_signature_score(r.mention_count, skill_id)
        }
        for r in results
    ]