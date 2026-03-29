import logging

from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.skills import EscoSkill, OscaOccupationSkill, OscaOccupationSkillSnapshot
from app.models.jobs import JobPostLog, JobPostSkill

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# HOT SKILLS
# Returns top 50 most-mentioned skills from job posts in the last N days.
# ─────────────────────────────────────────────
def get_hot_skills(db: Session, days: int = 30) -> list[dict]:
    try:
        # recent window first
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        def run_query(timestamp_filter=None):
            q = db.query(
                EscoSkill.preferred_label.label("skill_name"),
                func.count(JobPostSkill.id).label("total_mentions")
            ).join(JobPostSkill, JobPostSkill.skill_id == EscoSkill.id) \
             .join(JobPostLog, JobPostLog.id == JobPostSkill.job_post_id)
            
            if timestamp_filter:
                q = q.filter(JobPostLog.ingested_at >= timestamp_filter)
            
            return q.group_by(EscoSkill.preferred_label) \
                    .order_by(func.count(JobPostSkill.id).desc()) \
                    .limit(50).all()

        rows = run_query(cutoff)

        # Fallback: If empty, just get the most recent 50 overall
        if not rows:
            logger.warning(f"No hot skills in last {days} days. Falling back to all-time.")
            rows = run_query(None) 

        if not rows: return []

        max_mentions = rows[0].total_mentions or 1
        return [
            {
                "skill_name": r.skill_name.title() if r.skill_name else "Unknown",
                "total_mentions": r.total_mentions,
                "share_pct": round((r.total_mentions / max_mentions) * 100, 2)
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"get_hot_skills failed: {e}")
        return []
# def get_hot_skills(db: Session, days: int = 30) -> list[dict]:
#     """
#     Top skills extracted from job postings in the last N days.
#     Ranks by raw mention count across all occupations.
#     """
#     try:
#         cutoff = datetime.now(timezone.utc) - timedelta(days=days)

#         rows = (
#             db.query(
#                 EscoSkill.preferred_label.label("skill_name"),
#                 func.count(JobPostSkill.id).label("total_mentions")
#             )
#             .join(JobPostSkill, JobPostSkill.skill_id == EscoSkill.id)
#             .join(JobPostLog, JobPostLog.id == JobPostSkill.job_post_id)
#             .filter(JobPostLog.ingested_at >= cutoff)
#             .group_by(EscoSkill.preferred_label)
#             .order_by(func.count(JobPostSkill.id).desc())
#             .limit(50)
#             .all()
#         )

#         if not rows:
#             return []

#         max_mentions = rows[0].total_mentions or 1

#         return [
#             {
#                 "skill_name":     r.skill_name.title() if r.skill_name else r.skill_name,
#                 "total_mentions": r.total_mentions,
#                 "share_pct":      round((r.total_mentions / max_mentions) * 100, 2)
#             }
#             for r in rows
#         ]

#     except Exception as e:
#         logger.error(f"[MSIT402|SP] get_hot_skills failed: {e}")
#         return []


# ─────────────────────────────────────────────
# SHADOW SKILLS
# Skills appearing in job postings for an occupation but NOT in the
# official osca_occupation_skills mapping for that occupation.
# ─────────────────────────────────────────────

def get_shadow_skills(db: Session, occupation_id: int) -> list[dict]:
    """
    Skills seen in real job postings for this occupation that are
    not yet in the official OSCA→ESCO skill mapping table.
    These are "shadow" signals — emerging or unlisted skills.
    """
    try:
        mapped = (
            db.query(OscaOccupationSkill.skill_id)
            .filter(OscaOccupationSkill.occupation_id == occupation_id)
        )

        rows = (
            db.query(EscoSkill.preferred_label.label("skill_name"))
            .join(JobPostSkill, JobPostSkill.skill_id == EscoSkill.id)
            .join(JobPostLog, JobPostLog.id == JobPostSkill.job_post_id)
            .filter(JobPostLog.occupation_id == occupation_id)
            .filter(~EscoSkill.id.in_(mapped))
            .group_by(EscoSkill.preferred_label)
            .order_by(func.count(JobPostSkill.id).desc())
            .limit(50)
            .all()
        )

        return [{"skill_name": r.skill_name} for r in rows]

    except Exception as e:
        logger.error(f"[MSIT402|SP] get_shadow_skills failed: {e}")
        return []


# ─────────────────────────────────────────────
# SKILL DECAY
# Detects skills whose demand has dropped significantly.
# Compares earliest snapshot batch vs most recent snapshot batch
# for a given occupation using osca_occupation_skill_snapshots.
# ─────────────────────────────────────────────

def get_skill_decay(db: Session, occupation_id: int) -> list[dict]:
    """
    Skills where demand has dropped by 50%+ comparing the earliest
    recorded snapshot batch vs the most recent batch for this occupation.

    Uses osca_occupation_skill_snapshots — the point-in-time trend table.
    """
    try:
        # Earliest and latest snapshot dates for this occupation
        date_bounds = (
            db.query(
                func.min(OscaOccupationSkillSnapshot.snapshot_date).label("earliest"),
                func.max(OscaOccupationSkillSnapshot.snapshot_date).label("latest")
            )
            .filter(OscaOccupationSkillSnapshot.occupation_id == occupation_id)
            .first()
        )

        if not date_bounds or not date_bounds.earliest or not date_bounds.latest:
            return []

        # Need at least two distinct dates to compare
        if date_bounds.earliest == date_bounds.latest:
            return []

        # Early snapshot: use the earliest job_execution_id batch
        earliest_exec = (
            db.query(OscaOccupationSkillSnapshot.job_execution_id)
            .filter(OscaOccupationSkillSnapshot.occupation_id == occupation_id)
            .filter(OscaOccupationSkillSnapshot.snapshot_date == date_bounds.earliest)
            .limit(1)
            .scalar()
        )

        # Latest snapshot: use the most recent job_execution_id batch
        latest_exec = (
            db.query(OscaOccupationSkillSnapshot.job_execution_id)
            .filter(OscaOccupationSkillSnapshot.occupation_id == occupation_id)
            .filter(OscaOccupationSkillSnapshot.snapshot_date == date_bounds.latest)
            .limit(1)
            .scalar()
        )

        if not earliest_exec or not latest_exec or earliest_exec == latest_exec:
            return []

        # Fetch both snapshots as dictionaries keyed by skill_id
        early_rows = (
            db.query(
                OscaOccupationSkillSnapshot.skill_id,
                OscaOccupationSkillSnapshot.mention_count.label("early_count")
            )
            .filter(OscaOccupationSkillSnapshot.occupation_id == occupation_id)
            .filter(OscaOccupationSkillSnapshot.job_execution_id == earliest_exec)
            .all()
        )

        late_rows = (
            db.query(
                OscaOccupationSkillSnapshot.skill_id,
                OscaOccupationSkillSnapshot.mention_count.label("late_count")
            )
            .filter(OscaOccupationSkillSnapshot.occupation_id == occupation_id)
            .filter(OscaOccupationSkillSnapshot.job_execution_id == latest_exec)
            .all()
        )

        # Build lookup maps
        early_map = {r.skill_id: r.early_count for r in early_rows}
        late_map  = {r.skill_id: r.late_count  for r in late_rows}

        # Identify skills present in both batches where demand dropped 50%+
        decaying_ids = [
            sid for sid in early_map
            if sid in late_map and late_map[sid] < early_map[sid] * 0.5
        ]

        if not decaying_ids:
            return []

        # Fetch skill labels
        skill_labels = (
            db.query(EscoSkill.id, EscoSkill.preferred_label)
            .filter(EscoSkill.id.in_(decaying_ids))
            .all()
        )
        label_map = {s.id: s.preferred_label for s in skill_labels}

        results = []
        for sid in decaying_ids:
            past    = early_map[sid]
            current = late_map[sid]
            decline = past - current
            results.append({
                "skill_name":       label_map.get(sid, f"skill_{sid}"),
                "past_mentions":    past,
                "current_mentions": current,
                "decline":          decline,
                "decline_pct":      round((decline / past) * 100, 2) if past else 0
            })

        # Sort by absolute decline descending
        return sorted(results, key=lambda x: x["decline"], reverse=True)

    except Exception as e:
        logger.error(f"[MSIT402|SP] get_skill_decay failed: {e}")
        return []
    
# ─────────────────────────────────────────────
# SKILL VELOCITY
# Measures whether each skill for an occupation is rising or falling
# in demand over time using snapshot data.
# ─────────────────────────────────────────────

def get_skill_velocity(db: Session, occupation_id: int) -> dict:
    """
    Calculates demand velocity (slope) per skill using snapshot history.
    Returns rising skills, falling skills, and the snapshot count available.

    Slope > 0  → Rising demand
    Slope < 0  → Falling demand
    Slope = 0  → Stable / single snapshot
    """
    try:
        # Fetch all snapshots for this occupation ordered by date
        rows = (
            db.query(
                OscaOccupationSkillSnapshot.skill_id,
                OscaOccupationSkillSnapshot.mention_count,
                OscaOccupationSkillSnapshot.snapshot_date
            )
            .filter(OscaOccupationSkillSnapshot.occupation_id == occupation_id)
            .order_by(OscaOccupationSkillSnapshot.snapshot_date)
            .all()
        )

        if not rows:
            return {"snapshot_count": 0, "rising": [], "falling": [], "stable": []}

        # Build per-skill timeline: {skill_id: [(date_index, mention_count), ...]}
        from collections import defaultdict
        skill_timelines = defaultdict(list)
        all_dates = sorted(set(r.snapshot_date for r in rows))
        date_index = {d: i for i, d in enumerate(all_dates)}
        snapshot_count = len(all_dates)

        for r in rows:
            skill_timelines[r.skill_id].append(
                (date_index[r.snapshot_date], r.mention_count)
            )

        # Fetch skill labels in one query
        skill_ids = list(skill_timelines.keys())
        label_map = {
            s.id: s.preferred_label
            for s in db.query(EscoSkill.id, EscoSkill.preferred_label)
                       .filter(EscoSkill.id.in_(skill_ids))
                       .all()
        }

        rising, falling, stable = [], [], []

        for sid, timeline in skill_timelines.items():
            name = label_map.get(sid, f"skill_{sid}")
            latest_count = timeline[-1][1]

            if snapshot_count < 2 or len(timeline) < 2:
                # Not enough data to calculate slope — rank by current count
                stable.append({
                    "skill_name":    name,
                    "latest_count":  latest_count,
                    "slope":         0.0,
                    "status":        "stable"
                })
                continue

            # Simple linear slope: (last - first) / time_span
            first_t, first_c = timeline[0]
            last_t,  last_c  = timeline[-1]
            time_span = last_t - first_t or 1
            slope = round((last_c - first_c) / time_span, 4)

            entry = {
                "skill_name":   name,
                "latest_count": latest_count,
                "slope":        slope,
                "status":       "rising" if slope > 0 else "falling"
            }

            if slope > 0:
                rising.append(entry)
            else:
                falling.append(entry)

        # Sort each group
        rising  = sorted(rising,  key=lambda x: x["slope"],  reverse=True)[:15]
        falling = sorted(falling, key=lambda x: x["slope"])[:15]
        stable  = sorted(stable,  key=lambda x: x["latest_count"], reverse=True)[:15]

        return {
            "snapshot_count": snapshot_count,
            "rising":         rising,
            "falling":        falling,
            "stable":         stable
        }

    except Exception as e:
        logger.error(f"[MSIT402|SP] get_skill_velocity failed: {e}")
        return {"snapshot_count": 0, "rising": [], "falling": [], "stable": []}
