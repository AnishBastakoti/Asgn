import logging
import hashlib
import math

from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, Float

from app.models.skills import EscoSkill, OscaOccupationSkill, SkillpulseCityOccupationDemand
from app.models.jobs import JobPostLog
from app.models.osca import (
    OscaOccupation, 
    OscaUnitGroup,
    OscaMinorGroup,
    OscaSubMajorGroup,
)
from config import settings

logger = logging.getLogger(__name__)

_FP = hashlib.sha256(
    f"{settings.AUTHOR_KEY}:{settings.APP_NAME}:{settings.APP_VERSION}".encode()
).hexdigest()[:12]

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

def get_city_demand_detail(db: Session, city: str, limit: int = 10, from_date: str = None, to_date: str = None) -> dict:
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
            return {"occupations": [], "warning": None}

        max_jobs = rows[0].total_jobs or 1
        results = [
            {
                "occupation_title": r.occupation_title,
                "occupation_id":    r.occupation_id,
                "total_jobs":       r.total_jobs,
                "demand_pct":       round((r.total_jobs / max_jobs) * 100, 1)
            }
            for r in rows
        ]

        warning = None
        if len(results) < limit:
            warning = f"Only {len(results)} occupations found for {city} (requested {limit})."

        return {"occupations": results, "warning": warning}

    except Exception as e:
        logger.error(f"[MSIT402|SP] get_city_demand_detail failed: {e}")
        return {"occupations": [], "warning": "Error fetching data"}


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
#   score > 1.2  --> HOT  (high demand, relatively low skill barrier)
#   score < 0.8  --> SATURATED (low demand, high skill barrier)
#   otherwise    --> BALANCED
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
#   - Transition difficulty score (0-100)
# ─────────────────────────────────────────────
"""
Difficulty is computed from 4 independent signals:
    F1  Weighted Skill Gap  (45%)
    Fraction of target skill demand-weight.
    High-mention skills cost more than rarely-seen ones
    what recruiters actually screen for.

    F2  Skill Level Jump    (25%)
    OSCA skill levels 1-4 represent formal qualification bands.
    Every level crossed requires measurable investment.

    F3  Taxonomy Distance   (20%)
    How far apart the two occupations sit in the OSCA hierarchy
    (Unit --> Minor --> Sub-Major --> Major). Reflects sector familiarity
    and the size of the cultural/domain shift involved.
    
    F4  Skill Breadth Penalty (10%)
    Target occupations with many more skills than the source demand
    proportionally more new learning, regardless of overlap.

    Score is clamped to 0-100.  Thresholds:
   >= 65  Hard
   >= 35  Moderate
   <  35  Easy
"""

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
        total_occupation_count = db.query(func.count(OscaOccupation.id)).scalar()

        # ── Skill fetcher ─────────────────────────────────────────────────────
        def _get_skills(occ_id: int, major_group_id: int | None = None, sub_major_group_id: int | None = None,) -> dict:
            MAX_OCCUPATION_COVERAGE = 0.60
            MIN_CONCENTRATION_MAJOR     = 0.25
            MIN_CONCENTRATION_SUB_MAJOR = 0.15 
            # Inverse Document Frequency floor (concept from search engine text ranking)
            high_frequency_skill_ids = (
                db.query(OscaOccupationSkill.skill_id)
                .group_by(OscaOccupationSkill.skill_id)
                .having(
                    func.count(func.distinct(OscaOccupationSkill.occupation_id))
                    > (total_occupation_count * MAX_OCCUPATION_COVERAGE)
                )
                .subquery()
            )

            # Concentration filter (fixed — two-step subquery)
            if major_group_id is not None:
                skill_group_counts = (
                    db.query(
                        OscaOccupationSkill.skill_id.label("skill_id"),
                        OscaSubMajorGroup.major_group_id.label("major_group_id"),
                        OscaMinorGroup.sub_major_group_id.label("sub_major_group_id"),
                        func.count(OscaOccupationSkill.occupation_id).label("grp_count"),
                    )
                    .join(OscaOccupation,
                          OscaOccupation.id == OscaOccupationSkill.occupation_id)
                    .join(OscaUnitGroup,
                          OscaUnitGroup.id == OscaOccupation.unit_group_id,
                          isouter=True)
                    .join(OscaMinorGroup,
                          OscaMinorGroup.id == OscaUnitGroup.minor_group_id,
                          isouter=True)
                    .join(OscaSubMajorGroup,
                          OscaSubMajorGroup.id == OscaMinorGroup.sub_major_group_id,
                          isouter=True)
                    .filter(OscaSubMajorGroup.major_group_id.isnot(None))
                    .group_by(
                        OscaOccupationSkill.skill_id,
                        OscaSubMajorGroup.major_group_id,
                        OscaMinorGroup.sub_major_group_id,
                    )
                    .subquery()
                )

                skill_total_counts = (
                    db.query(
                        skill_group_counts.c.skill_id.label("skill_id"),
                        func.sum(skill_group_counts.c.grp_count).label("total_count"),
                    )
                    .group_by(skill_group_counts.c.skill_id)
                    .subquery()
                )

                major_passing = (
                    db.query(skill_group_counts.c.skill_id)
                    .join(skill_total_counts,
                        skill_total_counts.c.skill_id == skill_group_counts.c.skill_id)
                    .filter(
                        skill_group_counts.c.major_group_id == major_group_id,
                        func.cast(skill_group_counts.c.grp_count, Float)
                        / func.cast(skill_total_counts.c.total_count, Float)
                        >= MIN_CONCENTRATION_MAJOR,
                    )
                    .subquery()
                )

                #skills passing the SUB-MAJOR group threshold (≥15%)
                sub_major_passing = (
                    db.query(skill_group_counts.c.skill_id)
                    .join(skill_total_counts,
                        skill_total_counts.c.skill_id == skill_group_counts.c.skill_id)
                    .filter(
                        skill_group_counts.c.sub_major_group_id == sub_major_group_id,
                        func.cast(skill_group_counts.c.grp_count, Float)
                        / func.cast(skill_total_counts.c.total_count, Float)
                        >= MIN_CONCENTRATION_SUB_MAJOR,
                    )
                    .subquery()
                )

                concentrated_skill_ids = (
                    db.query(major_passing.c.skill_id)
                    .join(sub_major_passing,
                        sub_major_passing.c.skill_id == major_passing.c.skill_id)
                    .subquery()
                )
            else:
                concentrated_skill_ids = None

            # Semantic soft-skill blocklist
            SOFT_SKILL_PATTERNS = [
                "show %", "demonstrate %", "work in %", "work independently",
                "work closely %", "approach % positively", "meet %",
                "interact %", "cooperate %", "adapt to %", "focus on %",
                "attend to %",
            ]
            soft_skill_clause = or_(
                *[EscoSkill.preferred_label.ilike(p) for p in SOFT_SKILL_PATTERNS]
            )

            # Hard-type filter
            ALLOWED_SKILL_TYPES = {"skill/competence", "knowledge"}

            # Final query
            filters = [
                OscaOccupationSkill.occupation_id == occ_id,
                EscoSkill.skill_type.in_(ALLOWED_SKILL_TYPES),
                ~EscoSkill.id.in_(db.query(high_frequency_skill_ids.c.skill_id)),
                ~soft_skill_clause,
            ]
            if concentrated_skill_ids is not None:
                filters.append(
                    EscoSkill.id.in_(db.query(concentrated_skill_ids.c.skill_id))
                )

            rows = (
                db.query(
                    EscoSkill.id,
                    EscoSkill.preferred_label,
                    EscoSkill.skill_type,
                    func.max(OscaOccupationSkill.mention_count).label("mention_count"),
                )
                .join(OscaOccupationSkill, OscaOccupationSkill.skill_id == EscoSkill.id)
                .filter(*filters)
                .group_by(EscoSkill.id, EscoSkill.preferred_label, EscoSkill.skill_type)
                .order_by(func.max(OscaOccupationSkill.mention_count).desc())
                .all()
            )

            return {
                r.id: {
                    "name":  r.preferred_label,
                    "type":  r.skill_type,
                    "count": r.mention_count or 1,
                }
                for r in rows
            }

        #pass major_group_id at both call sites
        from_skills = _get_skills(from_id, major_group_id=from_occ.major_group_id, sub_major_group_id=from_occ.sub_major_group_id,)
        to_skills   = _get_skills(to_id,   major_group_id=to_occ.major_group_id, sub_major_group_id=to_occ.sub_major_group_id,)

        from_ids   = set(from_skills.keys())
        to_ids     = set(to_skills.keys())
        shared_ids = from_ids & to_ids
        gap_ids    = to_ids - from_ids

        # F1 — Weighted Skill Gap
        def _log_weight(count: int) -> float:
            return math.log1p(count)

        total_weight    = sum(_log_weight(to_skills[sid]["count"]) for sid in to_ids)
        gap_weight      = sum(_log_weight(to_skills[sid]["count"]) for sid in gap_ids)
        f1_weighted_gap = gap_weight / total_weight if total_weight > 0 else 0.0

        # F2 — Skill Level Jump
        from_level  = from_occ.skill_level or 2
        to_level    = to_occ.skill_level   or 2
        level_delta = from_level - to_level

        if level_delta > 0:
            f2_level_jump = min(level_delta / 3.0, 1.0)
        elif level_delta < 0:
            f2_level_jump = max(level_delta / 6.0, -0.15)
        else:
            f2_level_jump = 0.0

        # F3 — Taxonomy Distance
        def _safe_same(a, b) -> bool:
            return a is not None and b is not None and a == b

        same_unit      = _safe_same(from_occ.unit_group_id,      to_occ.unit_group_id)
        same_minor     = _safe_same(from_occ.minor_group_id,     to_occ.minor_group_id)
        same_sub_major = _safe_same(from_occ.sub_major_group_id, to_occ.sub_major_group_id)
        same_major     = _safe_same(from_occ.major_group_id,     to_occ.major_group_id)

        if same_unit:
            f3_taxonomy = 0.0
        elif same_minor:
            f3_taxonomy = 0.20
        elif same_sub_major:
            f3_taxonomy = 0.45
        elif same_major:
            f3_taxonomy = 0.70
        else:
            f3_taxonomy = 1.0

        # F4 — Skill Breadth Penalty
        from_count    = max(len(from_ids), 1)
        to_count      = max(len(to_ids),   1)
        breadth_ratio = to_count / from_count

        if breadth_ratio <= 1.0:
            f4_breadth = 0.0
        else:
            f4_breadth = min((breadth_ratio - 1.0) / 2.0, 1.0)

        # Composite Score
        W1, W2, W3, W4 = 0.45, 0.25, 0.20, 0.10
        raw = (W1 * f1_weighted_gap) + \
              (W2 * f2_level_jump)   + \
              (W3 * f3_taxonomy)     + \
              (W4 * f4_breadth)

        difficulty_score = int(round(max(0.0, min(raw, 1.0)) * 100))

        if difficulty_score >= 65:
            difficulty_label = "Hard"
            difficulty_color = "#EF4444"
        elif difficulty_score >= 35:
            difficulty_label = "Moderate"
            difficulty_color = "#F59E0B"
        else:
            difficulty_label = "Easy"
            difficulty_color = "#10B981"

        shared = sorted(
            [{"skill_name": to_skills[sid]["name"],
              "skill_type": to_skills[sid]["type"],
              "mention_count": to_skills[sid]["count"]}
             for sid in shared_ids],
            key=lambda x: x["mention_count"], reverse=True,
        )[:20]

        gap = sorted(
            [{"skill_name": to_skills[sid]["name"],
              "skill_type": to_skills[sid]["type"],
              "mention_count": to_skills[sid]["count"]}
             for sid in gap_ids],
            key=lambda x: x["mention_count"], reverse=True,
        )[:20]

        overlap_pct = round((len(shared_ids) / len(to_ids)) * 100) if to_ids else 0

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