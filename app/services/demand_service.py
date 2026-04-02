import logging
import math

from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.skills import EscoSkill, OscaOccupationSkill, SkillpulseCityOccupationDemand
from app.models.jobs import JobPostLog
from app.models.osca import (
    OscaOccupation, 
    OscaUnitGroup,
    OscaMinorGroup,
    OscaSubMajorGroup,
)

logger = logging.getLogger(__name__)
# ─────────────────────────────────────────────
# CITY DEMAND SUMMARY
# Returns all cities with their total job counts.
# Used to populate the city selector cards.
# ─────────────────────────────────────────────
def get_city_demand_summary(db: Session, from_date: str = None, to_date: str = None) -> list[dict]:
    try:
        if from_date or to_date:
            # Query live job_post_logs with date filter
            q = db.query(
                JobPostLog.city,
                func.count(JobPostLog.id).label("total_jobs"),
                func.count(func.distinct(JobPostLog.occupation_id)).label("occupation_count")
            ).filter(JobPostLog.city.isnot(None))

            if from_date:
                q = q.filter(JobPostLog.ingested_at >= datetime.fromisoformat(from_date))
            if to_date:
                q = q.filter(JobPostLog.ingested_at <= datetime.fromisoformat(to_date + "T23:59:59"))

            rows = q.group_by(JobPostLog.city).order_by(func.count(JobPostLog.id).desc()).all()
        else:
            rows = (
                db.query(
                    SkillpulseCityOccupationDemand.city,
                    func.sum(SkillpulseCityOccupationDemand.job_count).label("total_jobs"),
                    func.count(SkillpulseCityOccupationDemand.occupation_id).label("occupation_count")
                )
                .group_by(SkillpulseCityOccupationDemand.city)
                .order_by(func.sum(SkillpulseCityOccupationDemand.job_count).desc())
                .all()
            )

        if not rows:
            return []

        max_jobs = rows[0].total_jobs or 1
        return [
            {
                "city":             r.city,
                "total_jobs":       r.total_jobs,
                "occupation_count": r.occupation_count,
                "demand_pct":       round((r.total_jobs / max_jobs) * 100, 1)
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"[MSIT402|SP] get_city_demand_summary failed: {e}")
        return []


# ─────────────────────────────────────────────
# CITY DEMAND DETAIL
# Returns top N occupations for a given city.
# Used to populate the bar chart on city selection.
# ─────────────────────────────────────────────

def get_city_demand_detail(db: Session, city: str, limit: int = 10, from_date: str = None, to_date: str = None) -> list[dict]:
    try:
        if from_date or to_date:
            from app.models.osca import OscaOccupation
            q = db.query(
                OscaOccupation.principal_title.label("occupation_title"),
                JobPostLog.occupation_id,
                func.count(JobPostLog.id).label("total_jobs")
            ).join(OscaOccupation, JobPostLog.occupation_id == OscaOccupation.id)\
             .filter(JobPostLog.city == city, JobPostLog.occupation_id.isnot(None))

            if from_date:
                q = q.filter(JobPostLog.ingested_at >= datetime.fromisoformat(from_date))
            if to_date:
                q = q.filter(JobPostLog.ingested_at <= datetime.fromisoformat(to_date + "T23:59:59"))

            rows = q.group_by(JobPostLog.occupation_id, OscaOccupation.principal_title)\
                    .order_by(func.count(JobPostLog.id).desc())\
                    .limit(limit).all()
        else:
            rows = (
                db.query(
                    SkillpulseCityOccupationDemand.occupation_title,
                    SkillpulseCityOccupationDemand.occupation_id,
                    func.sum(SkillpulseCityOccupationDemand.job_count).label("total_jobs")
                )
                .filter(SkillpulseCityOccupationDemand.city == city)
                .group_by(SkillpulseCityOccupationDemand.occupation_title, SkillpulseCityOccupationDemand.occupation_id)
                .order_by(func.sum(SkillpulseCityOccupationDemand.job_count).desc())
                .limit(limit).all()
            )

        if not rows:
            return []

        max_jobs = rows[0].total_jobs or 1
        return [
            {
                "occupation_title": r.occupation_title,
                "occupation_id":    r.occupation_id,
                "total_jobs":       r.total_jobs,
                "demand_pct":       round((r.total_jobs / max_jobs) * 100, 1)
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"[MSIT402|SP] get_city_demand_detail failed: {e}")
        return []


# ─────────────────────────────────────────────
# MARKET SATURATION
# Determines if an occupation is undersupplied (hot) or
# oversupplied (saturated) relative to the platform average.
#
# Formula:
#   demand_ratio    = occupation_demand / platform_avg_demand
#   complexity_ratio = occupation_skills / platform_avg_skills
#   saturation_score = demand_ratio / complexity_ratio
#
#   score > 1.2  → HOT  (high demand, relatively low skill barrier)
#   score < 0.8  → SATURATED (low demand, high skill barrier)
#   otherwise    → BALANCED
# ─────────────────────────────────────────────

def get_market_saturation(db: Session, occupation_id: int) -> dict:
    """
    Compares an occupation's job demand and skill complexity against
    platform averages to determine if it is undersupplied or saturated.
    """
    try:
        from sqlalchemy import text

        # Total job demand for this occupation across all cities
        occ_demand = (
            db.query(func.sum(SkillpulseCityOccupationDemand.job_count))
            .filter(SkillpulseCityOccupationDemand.occupation_id == occupation_id)
            .scalar() or 0
        )

        if occ_demand == 0:
            return {
                "status":          "no_data",
                "saturation_score": 0.0,
                "demand_ratio":     0.0,
                "complexity_ratio": 0.0,
                "occ_demand":       0,
                "platform_avg_demand": 0,
                "occ_skill_count":  0,
                "platform_avg_skills": 0,
                "label":           "Insufficient Data",
                "insight":         "No job posting data found for this occupation yet."
            }

        # Platform average demand per occupation
        platform_avg_demand = (
            db.query(func.avg(
                db.query(func.sum(SkillpulseCityOccupationDemand.job_count))
                  .group_by(SkillpulseCityOccupationDemand.occupation_id)
                  .subquery()
                  .c[0]
            ))
            .scalar()
        )

        # Fallback using raw SQL if ORM subquery avg is tricky
        if platform_avg_demand is None:
            result = db.execute(text(
                "SELECT AVG(total) FROM "
                "(SELECT SUM(job_count) as total FROM skillpulse_city_occupation_demand "
                " GROUP BY occupation_id) sub"
            )).scalar()
            platform_avg_demand = float(result) if result else float(occ_demand)

        platform_avg_demand = float(platform_avg_demand) or 1.0

        # Skill count for this occupation
        occ_skill_count = (
            db.query(func.count(OscaOccupationSkill.skill_id))
            .filter(OscaOccupationSkill.occupation_id == occupation_id)
            .scalar() or 0
        )

        # Platform average skill count per occupation
        platform_avg_skills_result = db.execute(text(
            "SELECT AVG(cnt) FROM "
            "(SELECT COUNT(skill_id) as cnt FROM osca_occupation_skills "
            " GROUP BY occupation_id) sub"
        )).scalar()
        platform_avg_skills = float(platform_avg_skills_result) if platform_avg_skills_result else 1.0

        # Calculate ratios
        demand_ratio     = round(float(occ_demand) / platform_avg_demand, 3)
        complexity_ratio = round(float(occ_skill_count) / platform_avg_skills, 3) if platform_avg_skills > 0 else 1.0
        saturation_score = round(demand_ratio / complexity_ratio, 3) if complexity_ratio > 0 else demand_ratio

        # Classify
        if saturation_score >= 1.2:
            status  = "hot"
            label   = "Undersupplied — High Demand"
            insight = (
                f"This occupation has {round(demand_ratio * 100)}% of platform average demand "
                f"but only {round(complexity_ratio * 100)}% of average skill complexity. "
                f"More jobs than qualified candidates — strong hiring conditions."
            )
        elif saturation_score <= 0.8:
            status  = "saturated"
            label   = "Saturated — Competitive Market"
            insight = (
                f"Demand is below average relative to skill complexity. "
                f"The market may have more qualified candidates than open roles. "
                f"Upskilling into adjacent roles could improve career mobility."
            )
        else:
            status  = "balanced"
            label   = "Balanced Market"
            insight = (
                f"Supply and demand appear roughly aligned for this occupation. "
                f"Demand is at {round(demand_ratio * 100)}% of platform average "
                f"with {round(complexity_ratio * 100)}% of average skill complexity."
            )

        return {
            "status":               status,
            "saturation_score":     saturation_score,
            "demand_ratio":         demand_ratio,
            "complexity_ratio":     complexity_ratio,
            "occ_demand":           int(occ_demand),
            "platform_avg_demand":  round(platform_avg_demand, 1),
            "occ_skill_count":      occ_skill_count,
            "platform_avg_skills":  round(platform_avg_skills, 1),
            "label":                label,
            "insight":              insight
        }

    except Exception as e:
        logger.error(f"[MSIT402|SP] get_market_saturation failed: {e}")
        return {
            "status": "error", "saturation_score": 0.0,
            "demand_ratio": 0.0, "complexity_ratio": 0.0,
            "occ_demand": 0, "platform_avg_demand": 0.0,
            "occ_skill_count": 0, "platform_avg_skills": 0.0,
            "label": "Error", "insight": "Could not compute saturation."
        }
    
# ─────────────────────────────────────────────
#  OCCUPATION PROFILE
# Returns rich occupation metadata from osca_occupations:
# ─────────────────────────────────────────────

def get_occupation_profile(db: Session, occupation_id: int) -> dict:
    try:
        from app.models.osca import OscaOccupation
        from app.models.skills import OscaOccupationSkill

        occ = db.query(OscaOccupation).filter(OscaOccupation.id == occupation_id).first()
        if not occ:
            return {"error": "Occupation not found"}

        skill_rows = (
            db.query(EscoSkill.skill_type, func.count(OscaOccupationSkill.id).label("cnt"))
            .join(OscaOccupationSkill, OscaOccupationSkill.skill_id == EscoSkill.id)
            .filter(OscaOccupationSkill.occupation_id == occupation_id)
            .group_by(EscoSkill.skill_type)
            .all()
        )
        skill_breakdown = {r.skill_type or "unknown": r.cnt for r in skill_rows}
        total_skills = sum(skill_breakdown.values())

        return {
            "occupation_id":    occupation_id,
            "title":            occ.principal_title,
            "skill_level":      occ.skill_level,
            "lead_statement":   occ.lead_statement or "",
            "main_tasks":       occ.main_tasks or "",
            "licensing":        occ.licensing or "",
            "caveats":          occ.caveats or "",
            "specialisations":  occ.specialisations or "",
            "skill_attributes": occ.skill_attributes or "",
            "information_card": occ.information_card or "",
            "total_skills":     total_skills,
            "skill_breakdown":  skill_breakdown,
        }

    except Exception as e:
        logger.error(f"[MSIT402|SP] get_occupation_profile failed: {e}")
        return {"error": str(e)}


# ─────────────────────────────────────────────
# CAREER TRANSITION ANALYZER
# Compares two occupations' skill sets:
#   - Shared skills 
#   - Transition difficulty score (0–100)
# ─────────────────────────────────────────────

def get_career_transition(db: Session, from_id: int, to_id: int) -> dict:
    try:
        # both occupations with full hierarchy ──────────────────
        def _get_occ_with_hierarchy(occ_id: int):
            return (
                db.query(
                    OscaOccupation.id,
                    OscaOccupation.principal_title,
                    OscaOccupation.skill_level,
                    OscaOccupation.unit_group_id,
                    OscaUnitGroup.minor_group_id,
                    OscaMinorGroup.sub_major_group_id,
                    OscaSubMajorGroup.major_group_id,
                )
                .join(OscaUnitGroup,
                      OscaUnitGroup.id == OscaOccupation.unit_group_id,
                      isouter=True)
                .join(OscaMinorGroup,
                      OscaMinorGroup.id == OscaUnitGroup.minor_group_id,
                      isouter=True)
                .join(OscaSubMajorGroup,
                      OscaSubMajorGroup.id == OscaMinorGroup.sub_major_group_id,
                      isouter=True)
                .filter(OscaOccupation.id == occ_id)
                .first()
            )

        from_occ = _get_occ_with_hierarchy(from_id)
        to_occ   = _get_occ_with_hierarchy(to_id)

        if not from_occ or not to_occ:
            return {"error": "One or both occupations not found"}

        # skill sets with mention counts ────────────────────────
        def _get_skills(occ_id: int) -> dict:
            rows = (
                db.query(
                    EscoSkill.id,
                    EscoSkill.preferred_label,
                    EscoSkill.skill_type,
                    OscaOccupationSkill.mention_count,
                )
                .join(OscaOccupationSkill,
                      OscaOccupationSkill.skill_id == EscoSkill.id)
                .filter(OscaOccupationSkill.occupation_id == occ_id)
                .order_by(OscaOccupationSkill.mention_count.desc())
                .all()
            )
            return {
                r.id: {
                    "name":  r.preferred_label,
                    "type":  r.skill_type,
                    "count": r.mention_count or 1,  # floor at 1 to avoid log(0)
                }
                for r in rows
            }

        from_skills = _get_skills(from_id)
        to_skills   = _get_skills(to_id)

        from_ids   = set(from_skills.keys())
        to_ids     = set(to_skills.keys())
        shared_ids = from_ids & to_ids
        gap_ids    = to_ids - from_ids

        #  Weighted Skill Gap (0.0 → 1.0) ────────────────────────
        # Log-scale so one extremely popular skill doesn't dominate everything.
        # log(200) ≈ 5.3 vs log(1) = 0 — meaningful difference, not 200×.
        def _log_weight(count: int) -> float:
            return math.log1p(count)

        total_weight    = sum(_log_weight(to_skills[sid]["count"]) for sid in to_ids)
        gap_weight      = sum(_log_weight(to_skills[sid]["count"]) for sid in gap_ids)
        f1_weighted_gap = gap_weight / total_weight if total_weight > 0 else 0.0

        # Skill Level Jump (0.0 → 1.0) ──────────────────────────
        # OSCA: Level 1 = degree-required, Level 4 = entry level.
        # Moving DOWN in number = harder (more qualification needed).
        # Moving UP in number = easier (less qualification needed) → small bonus.
        from_level  = from_occ.skill_level or 2
        to_level    = to_occ.skill_level   or 2
        level_delta = from_level - to_level  # positive = moving to harder role

        if level_delta > 0:
            f2_level_jump = min(level_delta / 3.0, 1.0)
        elif level_delta < 0:
            f2_level_jump = max(level_delta / 6.0, -0.15)  # small bonus
        else:
            f2_level_jump = 0.0

        #Taxonomy Distance (0.0 → 1.0) ─────────────────────────
        same_unit      = from_occ.unit_group_id     == to_occ.unit_group_id
        same_minor     = from_occ.minor_group_id    == to_occ.minor_group_id
        same_sub_major = from_occ.sub_major_group_id == to_occ.sub_major_group_id
        same_major     = from_occ.major_group_id    == to_occ.major_group_id

        if same_unit:
            f3_taxonomy = 0.0   # same job family — very transferable
        elif same_minor:
            f3_taxonomy = 0.20  # adjacent roles in the same minor group
        elif same_sub_major:
            f3_taxonomy = 0.45  # same broad category e.g. both ICT Professionals
        elif same_major:
            f3_taxonomy = 0.70  # same major division e.g. both Professionals
        else:
            f3_taxonomy = 1.0   # completely different sector

        # Skill Breadth Penalty (0.0 → 1.0) ────────────────────
        # Penalises targets that require far more skills overall.
        # Saturates at 3× breadth so extreme outliers don't dominate.
        from_count    = max(len(from_ids), 1)
        to_count      = max(len(to_ids),   1)
        breadth_ratio = to_count / from_count

        if breadth_ratio <= 1.0:
            f4_breadth = 0.0
        else:
            f4_breadth = min((breadth_ratio - 1.0) / 2.0, 1.0)

        # Composite Score ─────────────────────────────────────────────
        W1, W2, W3, W4 = 0.45, 0.25, 0.20, 0.10

        raw = (W1 * f1_weighted_gap) + \
              (W2 * f2_level_jump)   + \
              (W3 * f3_taxonomy)     + \
              (W4 * f4_breadth)

        difficulty_score = int(round(max(0.0, min(raw, 1.0)) * 100))

        # Label & colour ──────────────────────────────────────────────
        if difficulty_score >= 65:
            difficulty_label = "Hard"
            difficulty_color = "#EF4444"
        elif difficulty_score >= 35:
            difficulty_label = "Moderate"
            difficulty_color = "#F59E0B"
        else:
            difficulty_label = "Easy"
            difficulty_color = "#10B981"

        # Skill lists for display ─────────────────────────────────────
        shared = sorted(
            [
                {
                    "skill_name":    to_skills[sid]["name"],
                    "skill_type":    to_skills[sid]["type"],
                    "mention_count": to_skills[sid]["count"],
                }
                for sid in shared_ids
            ],
            key=lambda x: x["mention_count"],
            reverse=True,
        )[:20]

        gap = sorted(
            [
                {
                    "skill_name":    to_skills[sid]["name"],
                    "skill_type":    to_skills[sid]["type"],
                    "mention_count": to_skills[sid]["count"],
                }
                for sid in gap_ids
            ],
            key=lambda x: x["mention_count"],
            reverse=True,
        )[:20]

        overlap_pct = round((len(shared_ids) / len(to_ids)) * 100) if to_ids else 0

        # Factor breakdown (exposed to frontend for transparency) ────
        score_breakdown = {
            "weighted_skill_gap": round(f1_weighted_gap * 100),
            "level_jump":         round(f2_level_jump   * 100),
            "taxonomy_distance":  round(f3_taxonomy      * 100),
            "breadth_penalty":    round(f4_breadth       * 100),
        }

        return {
            "from_id":          from_id,
            "from_title":       from_occ.principal_title,
            "from_skill_level": from_occ.skill_level,
            "to_id":            to_id,
            "to_title":         to_occ.principal_title,
            "to_skill_level":   to_occ.skill_level,
            "shared_count":     len(shared_ids),
            "gap_count":        len(gap_ids),
            "total_target":     len(to_ids),
            "overlap_pct":      overlap_pct,
            "difficulty_score": difficulty_score,
            "difficulty_label": difficulty_label,
            "difficulty_color": difficulty_color,
            "score_breakdown":  score_breakdown,
            "shared_skills":    shared,
            "gap_skills":       gap,
        }

    except Exception as e:
        logger.error(f"[MSIT402|SP] get_career_transition failed: {e}")
        return {"error": str(e)}