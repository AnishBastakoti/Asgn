import logging
import hashlib
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from app.models.jobs import JobPostLog
from app.models.skills import EscoSkill, OscaOccupationSkillSnapshot, OscaOccupationSkill
from app.models.osca import OscaOccupation

logger = logging.getLogger(__name__)

# ── Authorship Fingerprint ─────────────────────────────────
_AUTHOR_KEY = "MSIT402 CIM-10236"
_SIGNATURE  = int(hashlib.md5(_AUTHOR_KEY.encode()).hexdigest(), 16) % 1000


# ── 1. City Demand ─────────────────────────────────────────
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


# ── 2. Skill Trends Over Time ──────────────────────────────
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


# ── 3. Skill Overlap ───────────────────────────────────────
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


# ── 4. Top Companies ───────────────────────────────────────
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


# ── 5. City Lead Indicator ─────────────────────────────────
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

def get_cities_by_occupation(db: Session, occupation_id: int):
    return db.query(
        City.name.label("city"),
        func.count(JobPost.id).label("job_count")
    ).join(JobPost).filter(JobPost.occupation_id == occupation_id)\
    .group_by(City.name).order_by(desc("job_count")).all()

def get_skill_trends_by_occupation(db: Session, occupation_id: int):
    # This logic groups skills by month to show demand over time
    results = db.query(
        Skill.name,
        func.date_trunc('month', JobPost.posted_at).label("month"),
        func.count(JobPost.id).label("count")
    ).join(JobPostSkill, Skill.id == JobPostSkill.skill_id)\
     .join(JobPost, JobPostSkill.job_post_id == JobPost.id)\
     .filter(JobPost.occupation_id == occupation_id)\
     .group_by(Skill.name, "month").all()

    # Note: You'll need a helper to format this into your TrendPoint schema
    # (Grouping the flat list into SkillTrendResponse objects)
    return format_trends(results) 

def get_top_companies(db: Session, occupation_id: int):
    return db.query(
        Company.name.label("company"),
        func.count(JobPost.id).label("postings")
    ).join(JobPost).filter(JobPost.occupation_id == occupation_id)\
    .group_by(Company.name).order_by(desc("postings")).limit(10).all()

def get_city_lead_indicator(db: Session, occupation_id: int):
    """
    Finds which cities saw a job posting for this occupation first.
    Calculates if a city is a 'Lead' based on the earliest 'posted_at' date.
    """
    subquery = db.query(
        City.name.label("city"),
        func.min(JobPost.posted_at).label("first_seen"),
        func.count(JobPost.id).label("total_postings")
    ).join(JobPost).filter(JobPost.occupation_id == occupation_id)\
    .group_by(City.name).subquery()

    # Get the global 'first seen' date for this occupation
    min_date = db.query(func.min(JobPost.posted_at)).filter(JobPost.occupation_id == occupation_id).scalar()

    leads = db.query(
        subquery.c.city,
        subquery.c.first_seen,
        subquery.c.total_postings,
        (subquery.c.first_seen == min_date).label("is_lead")
    ).order_by(desc(subquery.c.total_postings)).all()
    
    # Add ranking in Python for simplicity
    return [{"rank": i+1, **row._asdict()} for i, row in enumerate(leads)]