import logging
import hashlib
import numpy as np
import math

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy import func, cast
from sqlalchemy.types import Date

from app.models.pipeline import PipelineRun
from app.models.jobs import JobPostLog, JobPostSkill
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
    Real time-weighted x-axis actual days
    Normalised relative slope (% change per day, scale-independent)
    Smoothed signal via rolling average (removes single-pipeline noise)
    Minimum data guard (requires at least 2 snapshots to call a trend)
    Consistent classification thresholds across both trend functions
    """
    try:
        rows = (
            db.query(
                EscoSkill.id.label("skill_id"),
                EscoSkill.preferred_label.label("skill_name"),
                EscoSkill.concept_uri,
                OscaOccupationSkillSnapshot.snapshot_date,
                OscaOccupationSkillSnapshot.mention_count,
            )
            .join(
                EscoSkill,
                EscoSkill.id == OscaOccupationSkillSnapshot.skill_id
            )
            .filter(OscaOccupationSkillSnapshot.occupation_id == occupation_id)
            .order_by(OscaOccupationSkillSnapshot.snapshot_date.asc())
            .all()
        )

        if not rows:
            return []
        
        # Fetch jobs_scraped per run date — one row per pipeline run
        run_rows = (
            db.query(
                cast(PipelineRun.run_date, Date).label("run_date"),
                PipelineRun.jobs_scraped
            )
            .filter(PipelineRun.status == "completed")   # ignore failed runs
            .filter(PipelineRun.jobs_scraped > 0)        # ignore zero-count runs
            .all()
        )

        # Build lookup: "2025-03-01" --> 500
        jobs_per_date = {
            str(r.run_date): r.jobs_scraped
            for r in run_rows
        }

        # Group by skill -real time axis
        
        all_dates  = sorted(set(r.snapshot_date for r in rows))
        origin     = all_dates[0]
        day_index  = {d: (d - origin).days for d in all_dates}
        snapshot_count = len(all_dates)

        skill_map = defaultdict(lambda: {"name": "", "uri": None, "points": []})
        for r in rows:
            entry = skill_map[r.skill_id]
            entry["name"] = r.skill_name
            entry["uri"]  = r.concept_uri
            date_str       = str(r.snapshot_date)[:10]
            total_that_run = jobs_per_date.get(date_str, None)
            entry["points"].append({
                "date":     str(r.snapshot_date)[:10],
                "day":      day_index[r.snapshot_date],
                "count":    r.mention_count,
                "rate": round(r.mention_count / total_that_run, 6) if total_that_run else None,
            })

        # Score and classify each skill ─────────────────────────────
        result = []
        for sid, data in skill_map.items():
            points = data["points"]
            counts = [p["count"] for p in points]
            days   = [p["day"]   for p in points]
            rates = [p["rate"] for p in points]

            latest_count = counts[-1]
            peak_count   = max(counts)
            use_rates = all(r is not None for r in rates)
            signal    = rates if use_rates else counts

            # Smoothed signal (rolling average with window=2) ───────
            # Removes noise from single pipeline runs that caught unusually
            # many or few job posts. With only 2 points, no smoothing needed.
            SMOOTH_WINDOW = 3

            if len(signal) >= SMOOTH_WINDOW + 1:
                smoothed = [
                    sum(signal[max(0, i - 1):i + 2]) /
                    len(signal[max(0, i - 1):i + 2])
                    for i in range(len(signal))
                ]
            else:
                smoothed = signal[:]

            # Normalised slope (% change per day) ───────────────────
            # Divides by the mean count so a +5 slope on a skill averaging
            # 100 mentions = 5% growth/day, same as +1 on a skill averaging 20.
            # This makes thresholds meaningful regardless of skill popularity.
            if len(smoothed) >= 2 and days[-1] > days[0]:
                time_span   = days[-1] - days[0]
                mean_count  = sum(smoothed) / len(smoothed) or 1

                # Weighted least-squares slope using real day axis
                n   = len(smoothed)
                sx  = sum(days)
                sy  = sum(smoothed)
                sxy = sum(days[i] * smoothed[i] for i in range(n))
                sx2 = sum(d * d for d in days)
                denom = n * sx2 - sx * sx

                raw_slope        = (n * sxy - sx * sy) / denom if denom else 0
                normalised_slope = raw_slope / mean_count  # fraction per day

                # Consistent thresholds (% change per day) ─────────
                # 3% per month growth
                if normalised_slope > 0.001:
                    trend = "growing"
                elif normalised_slope < -0.001:
                    trend = "declining"
                else:
                    trend = "stable"

                velocity = round(normalised_slope * 100, 3)  # as % per day

            else:
                trend    = "stable"
                velocity = 0.0

            # Momentum — recent change vs overall trend ─────────────
            # Flags skills where the LAST interval differs from the overall
            # trend — early warning of reversals.
            if len(counts) >= 3:
                recent_delta  = counts[-1] - counts[-2]
                overall_delta = counts[-1] - counts[0]
                momentum = "accelerating" if (recent_delta > 0 and overall_delta > 0 and
                                               recent_delta > overall_delta / max(len(counts)-1, 1)) \
                      else "decelerating" if (recent_delta < 0 and trend == "growing") \
                      else "steady"
            else:
                momentum = "steady"

            result.append({
                "skill_id":      sid,
                "skill_name":    data["name"],
                "concept_uri":   data["uri"],
                "points":        points,          # full time series for chart
                "trend":         trend,
                "velocity":      velocity,        # % per day
                "momentum":      momentum,
                "latest_count":  latest_count,
                "peak_count":    peak_count,
                "snapshot_count": snapshot_count,
            })

        # growing first by velocity, then by latest count ─────
        result.sort(key=lambda x: (
            x["trend"] != "growing",       # growing first
            -x["velocity"],                 # fastest growing
            -x["latest_count"],             # then by current demand
        ))

        return result[:10]   # top 10 is enough for a chart

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

        if not rows: return {"skills": [], "is_fallback": False, "days": days}

        max_mentions = rows[0].total_mentions or 1
        return {
            "skills": [
                {
                    "skill_name":     r.skill_name[:1].upper() + r.skill_name[1:] if r.skill_name else "Unknown",
                    "concept_uri":    r.concept_uri,
                    "skill_type":     r.skill_type or "unknown",
                    "total_mentions": r.total_mentions,
                    "share_pct":      round((r.total_mentions / max_mentions) * 100, 1),
                }
                for r in rows
            ],
            "is_fallback": is_fallback,
            "days":        days,
        }
    except Exception as e:
        logger.error(f"get_hot_skills_for_occupation failed occ={occupation_id}: {e}")
        return {"skills": [], "is_fallback": False, "days": days}
