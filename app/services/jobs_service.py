import logging
import hashlib

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from app.models.jobs import JobPostLog, JobPostSkill
from app.models.skills import EscoSkill, OscaOccupationSkill
from app.models.osca import OscaOccupation
from config import settings

logger = logging.getLogger(__name__)

# ── Authorship Fingerprint ─────────────────────────────────
_SIGNATURE = hashlib.sha256(settings.AUTHOR_KEY.encode()).hexdigest()[:8].upper()

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
# def get_skill_trends_by_occupation(db: Session, occupation_id: int) -> list[dict]:
#     """
#     Real time-weighted x-axis actual days
#     Normalised relative slope (% change per day, scale-independent)
#     Smoothed signal via rolling average (removes single-pipeline noise)
#     Minimum data guard (requires at least 2 snapshots to call a trend)
#     Consistent classification thresholds across both trend functions
#     """
#     try:
#         rows = (
#             db.query(
#                 EscoSkill.id.label("skill_id"),
#                 EscoSkill.preferred_label.label("skill_name"),
#                 EscoSkill.concept_uri,
#                 OscaOccupationSkillSnapshot.snapshot_date,
#                 OscaOccupationSkillSnapshot.mention_count,
#             )
#             .join(
#                 EscoSkill,
#                 EscoSkill.id == OscaOccupationSkillSnapshot.skill_id
#             )
#             .filter(OscaOccupationSkillSnapshot.occupation_id == occupation_id)
#             .order_by(OscaOccupationSkillSnapshot.snapshot_date.asc())
#             .all()
#         )

#         if not rows:
#             return []
        
#         # Fetch jobs_scraped per run date — one row per pipeline run
#         run_rows = (
#             db.query(
#                 cast(PipelineRun.run_date, Date).label("run_date"),
#                 PipelineRun.jobs_scraped
#             )
#             .filter(PipelineRun.status == "completed")   # ignore failed runs
#             .filter(PipelineRun.jobs_scraped > 0)        # ignore zero-count runs
#             .all()
#         )

#         # Build lookup: "2025-03-01" --> 500
#         jobs_per_date = {
#             str(r.run_date): r.jobs_scraped
#             for r in run_rows
#         }

#         # Group by skill -real time axis
        
#         all_dates  = sorted(set(r.snapshot_date for r in rows))
#         origin     = all_dates[0]
#         day_index  = {d: (d - origin).days for d in all_dates}
#         snapshot_count = len(all_dates)

#         skill_map = defaultdict(lambda: {"name": "", "uri": None, "points": []})
#         for r in rows:
#             entry = skill_map[r.skill_id]
#             entry["name"] = r.skill_name
#             entry["uri"]  = r.concept_uri
#             date_str       = str(r.snapshot_date)[:10]
#             total_that_run = jobs_per_date.get(date_str, None)
#             entry["points"].append({
#                 "date":     str(r.snapshot_date)[:10],
#                 "day":      day_index[r.snapshot_date],
#                 "count":    r.mention_count,
#                 "rate": round(r.mention_count / total_that_run, 6) if total_that_run else None,
#             })

#         # Score and classify each skill ─────────────────────────────
#         result = []
#         for sid, data in skill_map.items():
#             points = data["points"]
#             counts = [p["count"] for p in points]
#             days   = [p["day"]   for p in points]
#             rates = [p["rate"] for p in points]

#             latest_count = counts[-1]
#             peak_count   = max(counts)
#             use_rates = all(r is not None for r in rates)
#             signal    = rates if use_rates else counts

#             # Smoothed signal (rolling average with window=2) ───────
#             # Removes noise from single pipeline runs that caught unusually
#             # many or few job posts. With only 2 points, no smoothing needed.
#             SMOOTH_WINDOW = 3

#             if len(signal) >= SMOOTH_WINDOW + 1:
#                 smoothed = [
#                     sum(signal[max(0, i - 1):i + 2]) /
#                     len(signal[max(0, i - 1):i + 2])
#                     for i in range(len(signal))
#                 ]
#             else:
#                 smoothed = signal[:]

#             # Normalised slope (% change per day) ───────────────────
#             # Divides by the mean count so a +5 slope on a skill averaging
#             # 100 mentions = 5% growth/day, same as +1 on a skill averaging 20.
#             # This makes thresholds meaningful regardless of skill popularity.
#             if len(smoothed) >= 2 and days[-1] > days[0]:
#                 time_span   = days[-1] - days[0]
#                 mean_count  = sum(smoothed) / len(smoothed) or 1

#                 # Weighted least-squares slope using real day axis
#                 n   = len(smoothed)
#                 sx  = sum(days)
#                 sy  = sum(smoothed)
#                 sxy = sum(days[i] * smoothed[i] for i in range(n))
#                 sx2 = sum(d * d for d in days)
#                 denom = n * sx2 - sx * sx

#                 raw_slope        = (n * sxy - sx * sy) / denom if denom else 0
#                 normalised_slope = raw_slope / mean_count  # fraction per day

#                 # Consistent thresholds (% change per day) ─────────
#                 # 3% per month growth
#                 if normalised_slope > 0.001:
#                     trend = "growing"
#                 elif normalised_slope < -0.001:
#                     trend = "declining"
#                 else:
#                     trend = "stable"

#                 velocity = round(normalised_slope * 100, 3)  # as % per day

#             else:
#                 trend    = "stable"
#                 velocity = 0.0

#             # Momentum — recent change vs overall trend ─────────────
#             # Flags skills where the LAST interval differs from the overall
#             # trend — early warning of reversals.
#             if len(counts) >= 3:
#                 recent_delta  = counts[-1] - counts[-2]
#                 overall_delta = counts[-1] - counts[0]
#                 momentum = "accelerating" if (recent_delta > 0 and overall_delta > 0 and
#                                                recent_delta > overall_delta / max(len(counts)-1, 1)) \
#                       else "decelerating" if (recent_delta < 0 and trend == "growing") \
#                       else "steady"
#             else:
#                 momentum = "steady"

#             result.append({
#                 "skill_id":      sid,
#                 "skill_name":    data["name"],
#                 "concept_uri":   data["uri"],
#                 "points":        points,          # full time series for chart
#                 "trend":         trend,
#                 "velocity":      velocity,        # % per day
#                 "momentum":      momentum,
#                 "latest_count":  latest_count,
#                 "peak_count":    peak_count,
#                 "snapshot_count": snapshot_count,
#             })

#         # growing first by velocity, then by latest count ─────
#         result.sort(key=lambda x: (
#             x["trend"] != "growing",       # growing first
#             -x["velocity"],                 # fastest growing
#             -x["latest_count"],             # then by current demand
#         ))

#         return result[:10]   # top 10 is enough for a chart

#     except Exception as e:
#         logger.error(f"[MSIT402|SP] get_skill_trends_by_occupation failed: {e}")
#         return []


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
def get_hot_skills_for_occupation(db: Session, occupation_id: int, days: int = 30) -> list[dict]:
    try:
        # Calculate cutoff - strip tzinfo if DB stores naive timestamps
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        
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

        # Fallback logic
        if not rows:
            logger.warning(f"No hot skills in last {days} for {occupation_id}. Falling back.")
            rows = run_query(None) 

        if not rows: 
            return [] # Return empty list, not a dict

        max_mentions = rows[0].total_mentions or 1
        
        # Return ONLY the list of skills to match the response_model
        return [
            {
                "skill_name": r.skill_name[:1].upper() + r.skill_name[1:] if r.skill_name else "Unknown",
                "concept_uri": r.concept_uri,
                "total_mentions": r.total_mentions,
                "share_pct": round((r.total_mentions / max_mentions) * 100, 1),
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"get_hot_skills_for_occupation failed: {e}")
        return [] # Return empty list on error


# ─────────────────────────────────────────────
# SKILL GAP RADAR
# Compares official OSCA-mapped skills for an occupation
# against what actually appears in scraped job postings.
# Returns 5-axis radar data + per-type coverage breakdowns.
# ─────────────────────────────────────────────
 
def get_skill_gap_radar(db: Session, occupation_id: int) -> dict | None:
    """
    For each skill type (knowledge / competence / attitude):
      - How many official OSCA skills exist for this occupation?
      - How many of those appear in real job postings?
      - Which ones are confirmed (matched) vs absent (gap)?
 
    Also computes:
      - market_intensity  : avg posting frequency of matched skills, normalised 0-100
      - shadow_ratio      : shadow skills as % of official count, capped at 100
    """
    try:
        # Official skills mapped to this occupation via OSCA
        official = (
            db.query(
                EscoSkill.id,
                EscoSkill.preferred_label,
                EscoSkill.skill_type,
            )
            .join(OscaOccupationSkill, OscaOccupationSkill.skill_id == EscoSkill.id)
            .filter(OscaOccupationSkill.occupation_id == occupation_id)
            .all()
        )
 
        if not official:
            return None
 
        official_ids = {r.id for r in official}
 
        # Skills extracted from job postings for this occupation
        posting_rows = (
            db.query(
                JobPostSkill.skill_id,
                func.count(JobPostSkill.id).label("mention_count"),
            )
            .join(JobPostLog, JobPostLog.id == JobPostSkill.job_post_id)
            .filter(JobPostLog.occupation_id == occupation_id)
            .group_by(JobPostSkill.skill_id)
            .all()
        )
        posting_map: dict[int, int] = {r.skill_id: r.mention_count for r in posting_rows}
 
        # Per-type coverage breakdown
        TYPE_MAP = [
            ("knowledge",        "Knowledge"),
            ("skill/competence", "Competence"),
            ("attitude",         "Attitude"),
        ]
        by_type: list[dict] = []
        type_coverage: dict[str, float] = {}
 
        for raw_type, label in TYPE_MAP:
            bucket  = [s for s in official if (s.skill_type or "").lower() == raw_type]
            if not bucket:
                type_coverage[raw_type] = 0.0
                continue
 
            matched = [s for s in bucket if s.id in posting_map]
            missing = [s for s in bucket if s.id not in posting_map]
            coverage = round(len(matched) / len(bucket) * 100, 1)
            type_coverage[raw_type] = coverage
 
            matched_sorted = sorted(matched, key=lambda s: posting_map.get(s.id, 0), reverse=True)
 
            by_type.append({
                "key":            raw_type,
                "label":          label,
                "official_count": len(bucket),
                "matched_count":  len(matched),
                "missing_count":  len(missing),
                "coverage_pct":   coverage,
                "top_matched":    [s.preferred_label for s in matched_sorted[:5]],
                "top_missing":    [s.preferred_label for s in missing[:5]],
            })
 
        # Shadow skills: in postings but absent from the official OSCA mapping
        shadow_count = len([sid for sid in posting_map if sid not in official_ids])
 
        # Overall coverage
        overall_matched  = len([s for s in official if s.id in posting_map])
        overall_coverage = round(overall_matched / len(official) * 100, 1)
 
        # Market intensity (avg freq of matched official skills, normalised 0-100)
        if posting_map:
            max_v = max(posting_map.values()) or 1
            official_mentions = [posting_map[s.id] for s in official if s.id in posting_map]
            avg_freq = sum(official_mentions) / len(official_mentions) if official_mentions else 0
            market_intensity = round(min(avg_freq / max_v * 100, 100), 1)
        else:
            market_intensity = 0.0
 
        # Shadow ratio (capped at 100 for radar scale)
        shadow_ratio = round(min(shadow_count / max(len(official_ids), 1) * 100, 100), 1)
 
        return {
            "occupation_id": occupation_id,
            "radar": {
                "knowledge_coverage":  type_coverage.get("knowledge", 0.0),
                "competence_coverage": type_coverage.get("skill/competence", 0.0),
                "attitude_coverage":   type_coverage.get("attitude", 0.0),
                "market_intensity":    market_intensity,
                "shadow_ratio":        shadow_ratio,
            },
            "summary": {
                "official_skill_count": len(official),
                "matched_in_postings":  overall_matched,
                "unmatched_official":   len(official) - overall_matched,
                "shadow_skills":        shadow_count,
                "overall_coverage_pct": overall_coverage,
            },
            "by_type": by_type,
        }
    except Exception as e:
        logger.error(f"[MSIT402|SP] get_skill_gap_radar failed: {e}")
        return None
 
