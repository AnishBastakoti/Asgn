import logging
import hashlib
import numpy as np

from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.jobs import JobPostLog
from app.models.skills import EscoSkill, OscaOccupationSkillSnapshot, OscaOccupationSkill
from app.models.osca import OscaOccupation

logger = logging.getLogger(__name__)

# ── Authorship Fingerprint ─────────────────────────────────
_AUTHOR_KEY = "MSIT402 CIM-10236"
_SIGNATURE  = int(hashlib.md5(_AUTHOR_KEY.encode()).hexdigest(), 16) % 1000


# ── City Demand ─────────────────────────────────────────
def get_cities_by_occupation(db: Session, occupation_id: int) -> list[dict]:
    """
    Get Australian cities where this occupation has job demand.
    Source: job_post_logs.city grouped by count.
    """
    try:
        cities = (
            db.query(
                JobPostLog.city,
                func.count(JobPostLog.id).label("job_count")
            )
            .filter(JobPostLog.occupation_id == occupation_id)
            .filter(JobPostLog.city.isnot(None))
            .filter(JobPostLog.city != "")
            .group_by(JobPostLog.city)
            .order_by(func.count(JobPostLog.id).desc())
            .limit(15)
            .all()
        )
        return [{"city": c.city, "job_count": c.job_count} for c in cities]
    except Exception as e:
        logger.error(f"[MSIT402|SP] get_cities_by_occupation failed: {e}")
        return []


# ── Skill Trends Over Time ──────────────────────────────
def get_skill_trends_by_occupation(db: Session, occupation_id: int) -> list[dict]:
    """
    Get skill demand trends over time using snapshot data.
    Returns time series per skill with velocity score using linear regression.
    """
    try:
        trends = (
            db.query(
                EscoSkill.preferred_label,
                OscaOccupationSkillSnapshot.snapshot_date,
                OscaOccupationSkillSnapshot.mention_count
            )
            .join(
                EscoSkill,
                EscoSkill.id == OscaOccupationSkillSnapshot.skill_id
            )
            .filter(OscaOccupationSkillSnapshot.occupation_id == occupation_id)
            .order_by(OscaOccupationSkillSnapshot.snapshot_date.asc())
            .all()
        )

        # Group by skill
        skill_map = {}
        for row in trends:
            if row.preferred_label not in skill_map:
                skill_map[row.preferred_label] = []
            skill_map[row.preferred_label].append({
                "date":  str(row.snapshot_date),
                "count": row.mention_count
            })

        # Keep only top 5 skills by latest mention count
        sorted_skills = sorted(
            skill_map.items(),
            key=lambda x: x[1][-1]["count"] if x[1] else 0,
            reverse=True
        )[:5]

        result = []
        for name, points in sorted_skills:
            # Calculate velocity using linear regression (numpy)
            if len(points) >= 2:
                x = np.arange(len(points), dtype=float)
                y = np.array([p["count"] for p in points], dtype=float)
                slope = float(np.polyfit(x, y, 1)[0])
                if slope > 0.5:
                    trend = "growing"
                elif slope < -0.5:
                    trend = "declining"
                else:
                    trend = "stable"
                velocity = round(slope, 2)
            else:
                trend    = "stable"
                velocity = 0.0

            result.append({
                "skill_name": name,
                "points":     points,
                "trend":      trend,
                "velocity":   velocity
            })

        return result
    except Exception as e:
        logger.error(f"[MSIT402|SP] get_skill_trends_by_occupation failed: {e}")
        return []


# ── Skill Overlap ───────────────────────────────────────
def get_skill_overlap(db: Session, occupation_id: int) -> dict:
    """
    Find occupations that share skills with the selected occupation.
    Returns matrix data for heatmap visualisation.
    """
    try:
        # Get top 8 skills for selected occupation
        my_skills = (
            db.query(
                OscaOccupationSkill.skill_id,
                EscoSkill.preferred_label
            )
            .join(EscoSkill, EscoSkill.id == OscaOccupationSkill.skill_id)
            .filter(OscaOccupationSkill.occupation_id == occupation_id)
            .order_by(OscaOccupationSkill.mention_count.desc())
            .limit(8)
            .all()
        )

        if not my_skills:
            return {"skills": [], "occupations": [], "matrix": []}

        my_skill_ids    = [s.skill_id for s in my_skills]
        my_skill_labels = [s.preferred_label for s in my_skills]

        # Find related occupations that share these skills
        related = (
            db.query(
                OscaOccupation.id,
                OscaOccupation.principal_title,
                func.count(OscaOccupationSkill.skill_id).label("shared_count")
            )
            .join(
                OscaOccupationSkill,
                OscaOccupationSkill.occupation_id == OscaOccupation.id
            )
            .filter(OscaOccupationSkill.skill_id.in_(my_skill_ids))
            .filter(OscaOccupation.id != occupation_id)
            .group_by(OscaOccupation.id, OscaOccupation.principal_title)
            .order_by(func.count(OscaOccupationSkill.skill_id).desc())
            .limit(6)
            .all()
        )

        if not related:
            return {"skills": my_skill_labels, "occupations": [], "matrix": []}

        related_ids    = [r.id for r in related]
        related_labels = [r.principal_title for r in related]

        # Build shared skill sets per related occupation
        related_skills = (
            db.query(
                OscaOccupationSkill.occupation_id,
                OscaOccupationSkill.skill_id
            )
            .filter(OscaOccupationSkill.occupation_id.in_(related_ids))
            .filter(OscaOccupationSkill.skill_id.in_(my_skill_ids))
            .all()
        )

        # Build lookup set
        shared_lookup = set()
        for rs in related_skills:
            shared_lookup.add((rs.occupation_id, rs.skill_id))

        # Build matrix: rows = skills, cols = related occupations
        matrix = []
        for skill_id in my_skill_ids:
            row = []
            for occ_id in related_ids:
                row.append(1 if (occ_id, skill_id) in shared_lookup else 0)
            matrix.append(row)

        return {
            "skills":      my_skill_labels,
            "occupations": related_labels,
            "matrix":      matrix
        }
    except Exception as e:
        logger.error(f"[MSIT402|SP] get_skill_overlap failed: {e}")
        return {"skills": [], "occupations": [], "matrix": []}


# ── Top Companies ───────────────────────────────────────
def get_top_companies(db: Session, occupation_id: int) -> list[dict]:
    """
    Get top hiring companies for this occupation.
    Source: job_post_logs.company_name grouped by count.
    """
    try:
        companies = (
            db.query(
                JobPostLog.company_name,
                func.count(JobPostLog.id).label("posting_count")
            )
            .filter(JobPostLog.occupation_id == occupation_id)
            .filter(JobPostLog.company_name.isnot(None))
            .filter(JobPostLog.company_name != "")
            .group_by(JobPostLog.company_name)
            .order_by(func.count(JobPostLog.id).desc())
            .limit(10)
            .all()
        )
        return [
            {"company": c.company_name, "postings": c.posting_count}
            for c in companies
        ]
    except Exception as e:
        logger.error(f"[MSIT402|SP] get_top_companies failed: {e}")
        return []


# ── City Lead Indicator ─────────────────────────────────
def get_city_lead_indicator(db: Session, occupation_id: int) -> list[dict]:
    """
    Identify which Australian cities are lead indicators for skill demand.
    Compares job posting dates by city to find which cities post first.
    """
    try:
        city_first_seen = (
            db.query(
                JobPostLog.city,
                func.min(JobPostLog.ingested_at).label("first_seen"),
                func.count(JobPostLog.id).label("total_postings")
            )
            .filter(JobPostLog.occupation_id == occupation_id)
            .filter(JobPostLog.city.isnot(None))
            .filter(JobPostLog.city != "")
            .group_by(JobPostLog.city)
            .order_by(func.min(JobPostLog.ingested_at).asc())
            .all()
        )

        if not city_first_seen:
            return []

        # First city is the lead indicator
        results = []
        for i, c in enumerate(city_first_seen):
            results.append({
                "city":           c.city,
                "first_seen":     str(c.first_seen)[:10] if c.first_seen else None,
                "total_postings": c.total_postings,
                "is_lead":        i == 0,
                "rank":           i + 1
            })
        return results
    except Exception as e:
        logger.error(f"[MSIT402|SP] get_city_lead_indicator failed: {e}")
        return []

# ─────────────────────────────────────────────
# HOT SKILLS FOR EACH OCCUPATIONS
# Returns top most-mentioned skills from job posts in the last N days.
# ─────────────────────────────────────────────
def get_hot_skills_for_occupation(db: Session, occupation_id:int, days: int = 30) -> list[dict]:
    
    """
    Top skills for a specific occupation from job posts in last N days.
    Falls back to all-time data if no pipeline has run in that window.
    Returns the data + a flag indicating whether fallback was used.
    """
    try:
        # recent window first
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        def run_query(timestamp_filter=None):
            q = (
                db.query(
                    EscoSkill.preferred_label.label("skill_name"),
                    EscoSkill.concept_uri,
                    EscoSkill.skill_type,
                    func.count(JobPostSkill.id).label("total_mentions")
                )
                .join(JobPostSkill, JobPostSkill.skill_id == EscoSkill.id)
                .join(JobPostLog, JobPostLog.id == JobPostSkill.job_post_id)
                .filter(JobPostLog.occupation_id == occupation_id)
            )
            if timestamp_filter:
                q = q.filter(JobPostLog.ingested_at >= timestamp_filter)

            return q.group_by(
                EscoSkill.preferred_label,
                EscoSkill.concept_uri,
                EscoSkill.skill_type
            ).order_by(func.count(JobPostSkill.id).desc()).limit(20).all()

        rows = run_query(cutoff)
        is_fallback = False

        # Fallback: If empty, just get the most recent 50 overall
        if not rows:
            logger.warning(f"No hot skills in last {days} for occupation {occupation_id}. Falling back to all-time.")
            rows = run_query(None) 

        if not rows: return []

        max_mentions = rows[0].total_mentions or 1
        return {
            "skills": [
                {
                    "skill_name":     r.skill_name[:1].upper() + r.skill_name[1:] if r.skill_name else "Unknown",
                    "concept_uri":    r.concept_uri,
                    "skill_type":     r.skill_type or "unknown",
                    "total_mentions": r.total_mentions,
                    "share_pct":      round((r.total_mentions / max_m) * 100, 1),
                }
                for r in rows
            ],
            "is_fallback": is_fallback,
            "days":        days,
        }
    except Exception as e:
        logger.error(f"get_hot_skills_for_occupation failed occ={occupation_id}: {e}")
        return {"skills": [], "is_fallback": False, "days": days}
