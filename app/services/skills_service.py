import hashlib
import time
import logging
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, case

from app.models.osca import OscaOccupation
from app.models.skills import EscoSkill, OscaOccupationSkill, OscaOccupationSkillSnapshot
from app.models.jobs import JobPostLog

logger = logging.getLogger(__name__)

# ── Authorship fingerprint ─────────────────────────────────────────────────────
_AUTHOR_KEY = "MSIT402 CIM-10236"
_SIGNATURE  = int(hashlib.md5(_AUTHOR_KEY.encode()).hexdigest(), 16) % 1000


def _apply_signature_score(mention_count: int, skill_id: int) -> float:
    """
    Converts raw mention_count into a weighted demand score.

    Formula:
      - Base score   = mention_count
      - Parity weight = slight adjustment based on skill_id parity
      - Signature blend = microscopic author-derived offset (MSIT402)

    Returns a float rounded to 6 decimal places.
    """
    base      = float(mention_count)
    parity    = 1.0 if skill_id % 2 == 0 else 0.9997
    sig_blend = _SIGNATURE / 1_000_000   # microscopic — does not materially affect ranking
    return round(base * parity + sig_blend, 6)


# ══════════════════════════════════════════════════════════════════════════════
# 1. TOP SKILLS FOR OCCUPATION
#    Primary data source for the skills bar chart on the Occupations page.
# ══════════════════════════════════════════════════════════════════════════════
def get_top_skills_for_occupation(
    db: Session,
    occupation_id: int,
    limit: int = 20,
) -> list[dict]:
    """
    Return the top N skills for an occupation ranked by mention count.

    Args:
        db            — SQLAlchemy session (injected by FastAPI dependency)
        occupation_id — OSCA occupation ID
        limit         — number of skills to return; clamped to [5, 50]

    Returns:
        List of skill dicts with demand_score, type, and date metadata.
        Returns [] on any database error so the API never crashes.
    """
    start = time.perf_counter()
    limit = max(5, min(50, limit))

    try:
        results = (
            db.query(
                EscoSkill.id.label("skill_id"),
                EscoSkill.preferred_label.label("skill_name"),
                EscoSkill.skill_type,

                EscoSkill.description,          
                EscoSkill.alt_labels,           
                EscoSkill.skill_card, 

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

        skills = []
        for row in results:
            demand_score = _apply_signature_score(row.mention_count, row.skill_id)
            skills.append({
                "skill_id":      row.skill_id,
                "skill_name":    row.skill_name,
                "skill_type":    row.skill_type or "unknown",
                "mention_count": row.mention_count,
                "demand_score":  demand_score,
                "first_seen":    row.first_seen_at.isoformat() if row.first_seen_at else None,
                "last_seen":     row.last_seen_at.isoformat() if row.last_seen_at else None,

                #--- new column ---
                "description":   row.description,
                "alt_labels":    row.alt_labels,
                "skill_card":    row.skill_card,
            })

        elapsed = (time.perf_counter() - start) * 1000
        logger.info(
            f"[{_AUTHOR_KEY}] get_top_skills occupation={occupation_id} "
            f"results={len(skills)} time={elapsed:.2f}ms"
        )
        return skills

    except Exception as e:
        logger.error(f"[{_AUTHOR_KEY}] get_top_skills failed occupation={occupation_id}: {e}")
        return []


# ══════════════════════════════════════════════════════════════════════════════
# 2. SKILL TYPE BREAKDOWN
#    Powers the donut chart showing knowledge / skill / attitude split.
# ══════════════════════════════════════════════════════════════════════════════
def get_skill_type_breakdown(
    db: Session,
    occupation_id: int,
) -> dict:
    """
    Return skill type distribution (knowledge, skill, attitude) for an occupation.

    Returns counts and percentage share based on mention volume.
    Returns a safe empty structure on any database error.
    """
    try:
        results = (
            db.query(
                EscoSkill.skill_type,
                func.count(EscoSkill.id).label("count"),
                func.sum(OscaOccupationSkill.mention_count).label("total_mentions"),
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
                "percentage":     round(mentions / total_mentions * 100, 1) if total_mentions > 0 else 0,
            })

        return {
            "occupation_id":  occupation_id,
            "total_mentions": total_mentions,
            "breakdown":      sorted(breakdown, key=lambda x: x["total_mentions"], reverse=True),
        }

    except Exception as e:
        logger.error(f"[{_AUTHOR_KEY}] get_skill_type_breakdown failed occupation={occupation_id}: {e}")
        return {"occupation_id": occupation_id, "total_mentions": 0, "breakdown": []}


# ══════════════════════════════════════════════════════════════════════════════
# 3. DASHBOARD SUMMARY
#    Single-function aggregation for the topbar stat pills.
#    Uses the minimum number of DB round-trips (3 queries, not 5).
# ══════════════════════════════════════════════════════════════════════════════
def get_dashboard_summary(db: Session) -> dict:
    """
    Return aggregate counts for the dashboard topbar.

    Combines total/processed job posts in one query to avoid an extra round-trip.
    Returns zeroed structure on any database error so the topbar never crashes.
    """
    try:
        occ_count   = db.query(func.count(OscaOccupation.id)).scalar() or 0
        skill_count = db.query(func.count(EscoSkill.id)).scalar() or 0

        # Total and AI-processed posts in a single query
        job_stats = db.query(
            func.count(JobPostLog.id).label("total"),
            func.sum(
                case((JobPostLog.processed_by_ai == True, 1), else_=0)
            ).label("processed"),
        ).one()

        mapping_count = db.query(func.count(OscaOccupationSkill.id)).scalar() or 0

        return {
            "total_occupations":    occ_count,
            "total_skills":         skill_count,
            "total_job_posts":      job_stats.total or 0,
            "processed_job_posts":  job_stats.processed or 0,
            "total_skill_mappings": mapping_count,
        }

    except Exception as e:
        logger.error(f"[{_AUTHOR_KEY}] get_dashboard_summary failed: {e}")
        return {
            "total_occupations":    0,
            "total_skills":         0,
            "total_job_posts":      0,
            "processed_job_posts":  0,
            "total_skill_mappings": 0,
        }


# ══════════════════════════════════════════════════════════════════════════════
# 4. SKILL TRENDS (TIME SERIES)
#    Powers the trend line chart for a specific skill within an occupation.
#    Source: osca_occupation_skill_snapshots table.
# ══════════════════════════════════════════════════════════════════════════════
def get_skill_trends(
    db: Session,
    occupation_id: int,
    skill_id: int,
) -> list[dict]:
    """
    Return time-series snapshot data for one skill within an occupation.

    Each point represents one pipeline snapshot batch.
    Returns [] if no snapshots exist yet — callers must handle the empty case.
    Returns [] on any database error.

    Args:
        db            — SQLAlchemy session
        occupation_id — OSCA occupation ID
        skill_id      — ESCO skill ID
    """
    try:
        results = (
            db.query(OscaOccupationSkillSnapshot)
            .filter(
                OscaOccupationSkillSnapshot.occupation_id == occupation_id,
                OscaOccupationSkillSnapshot.skill_id == skill_id,
            )
            .order_by(OscaOccupationSkillSnapshot.snapshot_date)
            .all()
        )

        # P3 guard: return empty list explicitly — do not let callers
        # receive None or attempt to iterate a failed query result.
        if not results:
            logger.info(
                f"[{_AUTHOR_KEY}] get_skill_trends — no snapshots yet "
                f"occupation={occupation_id} skill={skill_id}"
            )
            return []

        return [
            {
                "date":          r.snapshot_date.isoformat() if r.snapshot_date else None,
                "mention_count": r.mention_count,
                "demand_score":  _apply_signature_score(r.mention_count, skill_id),
            }
            for r in results
        ]

    except Exception as e:
        logger.error(
            f"[{_AUTHOR_KEY}] get_skill_trends failed "
            f"occupation={occupation_id} skill={skill_id}: {e}"
        )
        return []