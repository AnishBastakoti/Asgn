import os
import logging
import pandas as pd
import numpy as np
import pickle

from sklearn.linear_model import Ridge # Ridge handles multicollinearity
from sklearn.preprocessing import StandardScaler
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, not_, exists

from app.models.skills import EscoSkill, OscaOccupationSkill, OscaOccupationSkillSnapshot, SkillpulseCityOccupationDemand
from app.models.jobs import JobPostLog, JobPostSkill

logger = logging.getLogger(__name__)

# Cache paths for trained models and K-Means results

_CACHE_DIR        = os.path.dirname(os.path.abspath(__file__))
_MODEL_PKL_PATH   = os.path.join(_CACHE_DIR, "skillpulse_model.pkl")
_KMEANS_PKL_PATH  = os.path.join(_CACHE_DIR, "skillpulse_kmeans.pkl")

# ── K-Means optimal K cache ────────────────────────────────────
_OPTIMAL_K_CACHE: dict = {"k": None, "occ_count": None}

# ── Model cache functions ────────────────────────────────────

def _save_model_cache(cache: dict) -> None:
    """Serialise model cache to disk so it survives restarts."""
    try:
        # Save everything except the model object itself is fine with pickle
        with open(_MODEL_PKL_PATH, "wb") as f:
            pickle.dump(cache, f, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info(f"[MSIT402|SP] Model cache saved to {_MODEL_PKL_PATH}")
    except Exception as e:
        logger.warning(f"[MSIT402|SP] Could not save model cache: {e}")
 
 
def _load_model_cache() -> dict:
    """Load model cache from disk if it exists."""
    empty = {
        "model": None, "scaler": None, "feature_cols": None,
        "occ_count": None, "job_count": None,
        "r2_score": None, "trained_at": None,
    }
    if not os.path.exists(_MODEL_PKL_PATH):
        return empty
    try:
        with open(_MODEL_PKL_PATH, "rb") as f:
            cache = pickle.load(f)
        logger.info(
            f"[MSIT402|SP] Loaded cached model from disk "
            f"(R²={cache.get('r2_score', 'N/A')}, "
            f"trained={cache.get('trained_at', 'unknown')})"
        )
        return cache
    except Exception as e:
        logger.warning(f"[MSIT402|SP] Could not load model cache: {e}")
        return empty
 
 
def _save_kmeans_cache(cache: dict) -> None:
    """Serialise K-Means cache to disk."""
    try:
        with open(_KMEANS_PKL_PATH, "wb") as f:
            pickle.dump(cache, f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as e:
        logger.warning(f"[MSIT402|SP] Could not save K-Means cache: {e}")
 
 
def _load_kmeans_cache() -> dict:
    """Load K-Means cache from disk if it exists."""
    if not os.path.exists(_KMEANS_PKL_PATH):
        return {"k": None, "occ_count": None}
    try:
        with open(_KMEANS_PKL_PATH, "rb") as f:
            return pickle.load(f)
    except Exception:
        return {"k": None, "occ_count": None}
 
 
# ── Load caches from disk on module import ──
_MODEL_CACHE    = _load_model_cache()
_OPTIMAL_K_CACHE = _load_kmeans_cache()
 

# ─────────────────────────────────────────────
# HOT SKILLS
# Returns top 50 most-mentioned skills from job posts in the last N days.
# Date filter uses job_post_logs.ingested_at.
# ─────────────────────────────────────────────

def get_hot_skills(db: Session, days: int = 30) -> list[dict]:
    """
    Top skills extracted from job postings in the last N days.
    Ranks by raw mention count across all occupations.
    """
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        rows = (
            db.query(
                EscoSkill.preferred_label.label("skill_name"),
                func.count(JobPostSkill.id).label("total_mentions")
            )
            .join(JobPostSkill, JobPostSkill.skill_id == EscoSkill.id)
            .join(JobPostLog, JobPostLog.id == JobPostSkill.job_post_id)
            .filter(JobPostLog.ingested_at >= cutoff)
            .group_by(EscoSkill.preferred_label)
            .order_by(func.count(JobPostSkill.id).desc())
            .limit(50)
            .all()
        )

        if not rows:
            return []

        max_mentions = rows[0].total_mentions or 1

        return [
            {
                "skill_name":     r.skill_name.title() if r.skill_name else r.skill_name,
                "total_mentions": r.total_mentions,
                "share_pct":      round((r.total_mentions / max_mentions) * 100, 2)
            }
            for r in rows
        ]

    except Exception as e:
        logger.error(f"[MSIT402|SP] get_hot_skills failed: {e}")
        return []


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
        # Subquery: skill_ids already mapped to this occupation
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
# Regression  model
# MODEL CACHE
# Stores the trained Ridge model and metadata in memory.
# Retrains automatically when new data is detected
# (occupation count or job post count changes).

# ─────────────────────────────────────────────

_MODEL_CACHE: dict = {
    "model":       None,   # trained Ridge instance
    "scaler":      None,   # fitted StandardScaler
    "feature_cols": None,  # list of feature names used
    "occ_count":   None,   # occupation count at last train
    "job_count":   None,   # job post count at last train
    "r2_score":    None,   # last cross-val R² score
    "trained_at":  None,   # datetime of last training
}

# ─────────────────────────────────────────────
# REGRESSION DATA
# Builds a real multi-feature training matrix from live DB data.
# Features:
#   current_demand   — total job count across all cities
#   shadow_count     — unlisted/emerging skills in job posts
#   skill_count      — number of officially mapped skills
#   city_diversity   — number of cities this occ appears in
#   avg_mention      — average skill mention count (skill depth)
# Target (y):
#   demand_per_skill — current_demand / skill_count
#   occupations with strong signal-per-skill ratios.
# ─────────────────────────────────────────────

"""
    Harvests features from multiple tables to create a training matrix.
    Formula to predict future demand (job counts) for occupations based on current demand and shadow skill signals:
    Predicted Demand = β^0+ (β^1× Current Count)+ (β^2× Shadow Skills)
    β₀ represents the intercept of the model.
    β₁ indicates the relationship between the current job count and future demand, representing the growth trend.
    β₂ measures the influence of shadow skills on future job demand and helps determine 
    whether these skills act as a leading indicator of future employment opportunities.
"""
def get_regression_data(db: Session) -> pd.DataFrame:
    """
    Builds a multi-feature training matrix for Ridge regression.
    Returns a DataFrame with features and target column ready for model.fit().
    Called automatically by _ensure_model_trained().
    """
    from sqlalchemy import text
 
    # ── Feature 1: current demand per occupation ──
    demand_rows = db.query(
        SkillpulseCityOccupationDemand.occupation_id,
        func.sum(SkillpulseCityOccupationDemand.job_count).label("current_demand"),
        func.count(func.distinct(SkillpulseCityOccupationDemand.city)).label("city_diversity")
    ).group_by(SkillpulseCityOccupationDemand.occupation_id).all()
 
    if not demand_rows:
        return pd.DataFrame()
 
    df = pd.DataFrame(
        [(r.occupation_id, r.current_demand, r.city_diversity) for r in demand_rows],
        columns=["occ_id", "current_demand", "city_diversity"]
    )
 
    # ── Feature 2: shadow skill count ──
    shadow_rows = db.execute(text("""
        SELECT jp.occupation_id, COUNT(jps.id) as shadow_count
        FROM job_post_logs jp
        JOIN job_post_skills jps ON jps.job_post_id = jp.id
        WHERE jp.occupation_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM osca_occupation_skills oos
              WHERE oos.skill_id = jps.skill_id
                AND oos.occupation_id = jp.occupation_id
          )
        GROUP BY jp.occupation_id
    """)).fetchall()
    shadow_df = pd.DataFrame(shadow_rows, columns=["occ_id", "shadow_count"])
 
    # ── Feature 3: official skill count + avg mention count ──
    skill_rows = db.query(
        OscaOccupationSkill.occupation_id,
        func.count(OscaOccupationSkill.skill_id).label("skill_count"),
        func.avg(OscaOccupationSkill.mention_count).label("avg_mention")
    ).group_by(OscaOccupationSkill.occupation_id).all()
    skill_df = pd.DataFrame(
        [(r.occupation_id, r.skill_count, float(r.avg_mention or 0)) for r in skill_rows],
        columns=["occ_id", "skill_count", "avg_mention"]
    )
 
    # ── Merge all features ──
    df = df.merge(shadow_df, on="occ_id", how="left")
    df = df.merge(skill_df,  on="occ_id", how="left")
    df = df.fillna(0)
 
    # ── Target: demand efficiency (demand per mapped skill) ──
    # More stable than raw demand; rewards occupations with
    # strong market signal relative to their skill complexity
    df["target"] = df.apply(
        lambda r: r["current_demand"] / max(r["skill_count"], 1), axis=1
    )
 
    return df
 
 
# ─────────────────────────────────────────────
# MODEL TRAINING
# Trains Ridge regression on the feature matrix.
# Uses K-Fold cross-validation to compute R² score.
# Stores model + scaler in _MODEL_CACHE.
# ─────────────────────────────────────────────
 
def _ensure_model_trained(db: Session) -> bool:
    """
    Checks if the model needs (re)training based on data changes.
    Trains if: first run, or occupation/job count has changed.
    Returns True if model is ready, False if insufficient data.
    """
    global _MODEL_CACHE
    from sklearn.model_selection import cross_val_score
 
    # Check current data size
    current_occ_count = db.query(
        func.count(func.distinct(SkillpulseCityOccupationDemand.occupation_id))
    ).scalar() or 0
 
    current_job_count = db.query(
        func.count(JobPostLog.id)
    ).scalar() or 0
 
    # Use cache if data hasn't changed
    if (_MODEL_CACHE["model"] is not None and
            _MODEL_CACHE["occ_count"] == current_occ_count and
            _MODEL_CACHE["job_count"] == current_job_count):
        logger.info(f"[MSIT402|SP] Using cached Ridge model (R²={_MODEL_CACHE['r2_score']:.3f})")
        return True
 
    # ── Build training matrix ──
    logger.info("[MSIT402|SP] Training Ridge regression model...")
    df = get_regression_data(db)
 
    if df.empty or len(df) < 10:
        logger.warning("[MSIT402|SP] Insufficient data to train model")
        return False
 
    feature_cols = ["current_demand", "shadow_count", "skill_count", "city_diversity", "avg_mention"]
    X = df[feature_cols].values
    y = df["target"].values
 
    # ── Scale features ──
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
 
    # ── Train Ridge regression ──
    # alpha=1.0 penalises large coefficients — prevents overfitting
    # on correlated features (current_demand and skill_count often correlate)
    model = Ridge(alpha=1.0)
    model.fit(X_scaled, y)
 
    # ── Cross-validation R² score ──
    try:
        from sklearn.model_selection import KFold
        kf = KFold(n_splits=min(5, len(df)), shuffle=True, random_state=42)
        cv_scores = cross_val_score(model, X_scaled, y, cv=kf, scoring="r2")
        r2 = round(float(cv_scores.mean()), 4)
    except Exception:
        r2 = round(float(model.score(X_scaled, y)), 4)
 
    # ── Store in cache ──
    _MODEL_CACHE["model"]        = model
    _MODEL_CACHE["scaler"]       = scaler
    _MODEL_CACHE["feature_cols"] = feature_cols
    _MODEL_CACHE["occ_count"]    = current_occ_count
    _MODEL_CACHE["job_count"]    = current_job_count
    _MODEL_CACHE["r2_score"]     = r2
    _MODEL_CACHE["trained_at"]   = datetime.now().isoformat()
 
    logger.info(
        f"[MSIT402|SP] Ridge model trained: {len(df)} occupations, "
        f"R²={r2:.3f}, features={feature_cols}"
    )
    return True
 
 
def get_occupation_features(db: Session, occupation_id: int):
    """
    Extracts features for regression inference:
    current_demand, shadow_count, skill_count, city_diversity, avg_mention.
    Also returns title for the response payload.
    """
    from sqlalchemy import text
 
    current_demand = db.query(
        func.sum(SkillpulseCityOccupationDemand.job_count)
    ).filter(SkillpulseCityOccupationDemand.occupation_id == occupation_id).scalar() or 0
 
    city_diversity = db.query(
        func.count(func.distinct(SkillpulseCityOccupationDemand.city))
    ).filter(SkillpulseCityOccupationDemand.occupation_id == occupation_id).scalar() or 0
 
    shadow_count = db.execute(text("""
        SELECT COUNT(jps.id)
        FROM job_post_logs jp
        JOIN job_post_skills jps ON jps.job_post_id = jp.id
        WHERE jp.occupation_id = :occ_id
          AND NOT EXISTS (
              SELECT 1 FROM osca_occupation_skills oos
              WHERE oos.skill_id = jps.skill_id
                AND oos.occupation_id = :occ_id
          )
    """), {"occ_id": occupation_id}).scalar() or 0
 
    skill_row = db.query(
        func.count(OscaOccupationSkill.skill_id).label("skill_count"),
        func.avg(OscaOccupationSkill.mention_count).label("avg_mention")
    ).filter(OscaOccupationSkill.occupation_id == occupation_id).first()
 
    skill_count = skill_row.skill_count if skill_row else 0
    avg_mention = float(skill_row.avg_mention or 0) if skill_row else 0.0
 
    occ_data = db.query(SkillpulseCityOccupationDemand.occupation_title)        .filter(SkillpulseCityOccupationDemand.occupation_id == occupation_id).first()
    title = occ_data.occupation_title if occ_data else "Unknown"
 
    return {
        "current_demand": int(current_demand),
        "shadow_count":   int(shadow_count),
        "skill_count":    int(skill_count),
        "city_diversity": int(city_diversity),
        "avg_mention":    avg_mention,
        "title":          title,
    }
 
 
# ─────────────────────────────────────────────
# OCCUPATION PREDICTION
# Uses trained Ridge model for inference.
# Falls back to momentum forecasting if model not ready.
# Automatically retrains when new data is available.
# ─────────────────────────────────────────────
 
def get_occupation_prediction(db: Session, occupation_id: int):
    """
    Predicts future demand using Ridge regression when trained,
    falling back to momentum forecasting otherwise.
    Model retrains automatically when data changes.
    """
    features = get_occupation_features(db, occupation_id)
 
    if features["current_demand"] == 0:
        return None
 
    model_ready = _ensure_model_trained(db)
 
    if model_ready and _MODEL_CACHE["model"] is not None:
        # ── Ridge model inference ──
        import numpy as np
        X = np.array([[
            features["current_demand"],
            features["shadow_count"],
            features["skill_count"],
            features["city_diversity"],
            features["avg_mention"],
        ]], dtype=np.float32)
        X_scaled = _MODEL_CACHE["scaler"].transform(X)
        demand_per_skill = float(_MODEL_CACHE["model"].predict(X_scaled)[0])
 
        # Convert back from demand_per_skill to absolute demand
        predicted_demand = int(max(demand_per_skill * max(features["skill_count"], 1), 0))
        growth_rate = round(
            ((predicted_demand - features["current_demand"]) / features["current_demand"]) * 100, 2
        ) if features["current_demand"] > 0 else 0.0
        confidence = min(0.5 + _MODEL_CACHE["r2_score"] * 0.5, 0.95)
        method = "ridge_regression"
 
    else:
        # ── Momentum forecasting fallback ──
        avg_historical = db.query(
            func.avg(SkillpulseCityOccupationDemand.job_count)
        ).filter(
            SkillpulseCityOccupationDemand.occupation_id == occupation_id
        ).scalar() or features["current_demand"]
 
        velocity = (
            (features["current_demand"] - float(avg_historical)) / float(avg_historical)
            if avg_historical > 0 else 0
        )
        momentum_factor  = 1.05 + (velocity * 0.5)
        shadow_bonus     = features["shadow_count"] * 0.1
        predicted_demand = int(features["current_demand"] * momentum_factor + shadow_bonus)
        growth_rate      = round(
            ((predicted_demand - features["current_demand"]) / features["current_demand"]) * 100, 2
        )
        confidence = 0.90 if velocity != 0 else 0.65
        method     = "momentum_forecast"
 
    return {
        "occupation_id":    occupation_id,
        "occupation_title": features["title"],
        "current_demand":   features["current_demand"],
        "predicted_demand": predicted_demand,
        "growth_rate":      growth_rate,
        "confidence_score": round(confidence, 2),
        "method":           method,
        "r2_score":         _MODEL_CACHE.get("r2_score"),
    }
 
 
# ─────────────────────────────────────────────
# DEMAND FORECAST BY CITY
# Runs trained Ridge model for all occupations in a city.
# Returns ranked forecast sorted by predicted growth.
# ─────────────────────────────────────────────
 
def get_demand_forecast(db: Session, city: str) -> list:
    """
    Predicts demand for all occupations in a given city
    using the trained Ridge regression model.
    Falls back to momentum if model not trained.
    """
    raw_data = db.query(
        SkillpulseCityOccupationDemand.occupation_id,
        SkillpulseCityOccupationDemand.occupation_title,
        func.sum(SkillpulseCityOccupationDemand.job_count).label("current_jobs")
    ).filter(
        SkillpulseCityOccupationDemand.city == city
    ).group_by(
        SkillpulseCityOccupationDemand.occupation_id,
        SkillpulseCityOccupationDemand.occupation_title
    ).all()
 
    if not raw_data or len(raw_data) < 3:
        return []
 
    forecasts = []
    for row in raw_data:
        prediction = get_occupation_prediction(db, row.occupation_id)
        if not prediction:
            continue
        change = (
            (prediction["predicted_demand"] - row.current_jobs) / row.current_jobs * 100
            if row.current_jobs > 0 else 0
        )
        forecasts.append({
            "occupation_title": row.occupation_title,
            "occupation_id":    row.occupation_id,
            "current_jobs":     int(row.current_jobs),
            "predicted_jobs":   prediction["predicted_demand"],
            "growth_trend":     round(change, 2),
            "confidence_score": prediction["confidence_score"],
            "method":           prediction["method"],
        })
 
    return sorted(forecasts, key=lambda x: x["growth_trend"], reverse=True)
 
 
# ─────────────────────────────────────────────
# MODEL STATUS
# Returns current model training status and metrics.
# Used by the /model-status endpoint for monitoring.
# ─────────────────────────────────────────────
 
def get_model_status(db: Session) -> dict:
    """Returns current Ridge model training status and metrics."""
    model_ready = _ensure_model_trained(db)
    return {
        "model_ready":   model_ready,
        "trained_at":    _MODEL_CACHE.get("trained_at"),
        "r2_score":      _MODEL_CACHE.get("r2_score"),
        "occ_count":     _MODEL_CACHE.get("occ_count"),
        "job_count":     _MODEL_CACHE.get("job_count"),
        "feature_cols":  _MODEL_CACHE.get("feature_cols"),
        "method":        "ridge_regression" if model_ready else "momentum_forecast",
    }
 
 
# ─────────────────────────────────────────────
# SKILL VELOCITY
# Measures whether each skill for an occupation is rising or falling
# in demand over time using snapshot data.
# If only one snapshot exists, returns ranked skills with "stable" status.
# Automatically becomes meaningful as more pipeline runs accumulate.
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
# main_tasks, lead_statement, licensing, caveats,
# specialisations, skill_attributes, information_card
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
        from app.models.osca import OscaOccupation
        from app.models.skills import OscaOccupationSkill

        from_occ = db.query(OscaOccupation).filter(OscaOccupation.id == from_id).first()
        to_occ   = db.query(OscaOccupation).filter(OscaOccupation.id == to_id).first()

        if not from_occ or not to_occ:
            return {"error": "One or both occupations not found"}

        def get_skills(occ_id):
            rows = (
                db.query(
                    EscoSkill.id,
                    EscoSkill.preferred_label,
                    EscoSkill.skill_type,
                    OscaOccupationSkill.mention_count
                )
                .join(OscaOccupationSkill, OscaOccupationSkill.skill_id == EscoSkill.id)
                .filter(OscaOccupationSkill.occupation_id == occ_id)
                .order_by(OscaOccupationSkill.mention_count.desc())
                .all()
            )
            return {r.id: {"name": r.preferred_label, "type": r.skill_type, "count": r.mention_count} for r in rows}

        from_skills = get_skills(from_id)
        to_skills   = get_skills(to_id)

        from_ids = set(from_skills.keys())
        to_ids   = set(to_skills.keys())

        shared_ids = from_ids & to_ids
        gap_ids    = to_ids - from_ids

        shared = sorted(
            [{"skill_name": to_skills[sid]["name"], "skill_type": to_skills[sid]["type"], "mention_count": to_skills[sid]["count"]} for sid in shared_ids],
            key=lambda x: x["mention_count"], reverse=True
        )[:20]

        gap = sorted(
            [{"skill_name": to_skills[sid]["name"], "skill_type": to_skills[sid]["type"], "mention_count": to_skills[sid]["count"]} for sid in gap_ids],
            key=lambda x: x["mention_count"], reverse=True
        )[:20]

        difficulty_score = round((len(gap_ids) / len(to_ids)) * 100) if to_ids else 0

        if difficulty_score >= 70:
            difficulty_label = "Hard"
            difficulty_color = "#EF4444"
        elif difficulty_score >= 40:
            difficulty_label = "Moderate"
            difficulty_color = "#F59E0B"
        else:
            difficulty_label = "Easy"
            difficulty_color = "#10B981"

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
            "overlap_pct":      round((len(shared_ids) / len(to_ids)) * 100) if to_ids else 0,
            "difficulty_score": difficulty_score,
            "difficulty_label": difficulty_label,
            "difficulty_color": difficulty_color,
            "shared_skills":    shared,
            "gap_skills":       gap,
        }

    except Exception as e:
        logger.error(f"[MSIT402|SP] get_career_transition failed: {e}")
        return {"error": str(e)}


# ─────────────────────────────────────────────
# COSINE SIMILARITY
# Builds a binary skill vector for every occupation and computes
# cosine similarity between the selected occupation and all others.
# Returns the top N most similar occupations ranked by score.
#
# Formula:
#   cos(A, B) = (A · B) / (||A|| × ||B||)
# ─────────────────────────────────────────────
 
def get_occupation_similarity(db: Session, occupation_id: int, top_n: int = 8) -> dict:
    """
    Computes cosine similarity between the selected occupation and all others
    based on their ESCO skill vectors. Returns the top N most similar occupations.
    """
    try:
        import numpy as np
        from sklearn.metrics.pairwise import cosine_similarity
 
        # Fetch all occupation-skill mappings in one query
        rows = (
            db.query(
                OscaOccupationSkill.occupation_id,
                OscaOccupationSkill.skill_id
            )
            .all()
        )
 
        if not rows:
            return {"error": "No skill mapping data available"}
 
        # Build skill universe and occupation index
        all_skill_ids   = sorted(set(r.skill_id     for r in rows))
        all_occ_ids     = sorted(set(r.occupation_id for r in rows))
 
        if occupation_id not in all_occ_ids:
            return {"error": "Occupation has no mapped skills"}
 
        skill_index = {sid: i for i, sid in enumerate(all_skill_ids)}
        occ_index   = {oid: i for i, oid in enumerate(all_occ_ids)}
 
        # Build binary skill matrix [n_occupations × n_skills]
        matrix = np.zeros((len(all_occ_ids), len(all_skill_ids)), dtype=np.float32)
        for r in rows:
            matrix[occ_index[r.occupation_id], skill_index[r.skill_id]] = 1.0
 
        # Compute cosine similarity for the target occupation vs all others
        target_vec = matrix[occ_index[occupation_id]].reshape(1, -1)
        scores     = cosine_similarity(target_vec, matrix)[0]  # shape: (n_occupations,)
 
        # Rank — exclude self (score = 1.0 at own index)
        ranked = sorted(
            [(all_occ_ids[i], float(scores[i])) for i in range(len(all_occ_ids))
             if all_occ_ids[i] != occupation_id],
            key=lambda x: x[1],
            reverse=True
        )[:top_n]
 
        if not ranked:
            return {"similar": [], "total_skills": int(target_vec.sum())}
 
        # Fetch titles for top results
        from app.models.osca import OscaOccupation
        top_ids    = [r[0] for r in ranked]
        score_map  = {r[0]: r[1] for r in ranked}
        occ_rows   = (
            db.query(OscaOccupation.id, OscaOccupation.principal_title, OscaOccupation.skill_level)
            .filter(OscaOccupation.id.in_(top_ids))
            .all()
        )
        title_map = {o.id: {"title": o.principal_title, "level": o.skill_level} for o in occ_rows}
 
        similar = [
            {
                "occupation_id":    oid,
                "title":            title_map.get(oid, {}).get("title", f"occ_{oid}"),
                "skill_level":      title_map.get(oid, {}).get("level"),
                "similarity_score": round(score_map[oid] * 100, 1),
            }
            for oid in top_ids
            if oid in title_map
        ]
 
        return {
            "occupation_id": occupation_id,
            "total_skills":  int(target_vec.sum()),
            "similar":       similar
        }
 
    except Exception as e:
        logger.error(f"[MSIT402|SP] get_occupation_similarity failed: {e}")
        return {"error": str(e)}
 
# ─────────────────────────────────────────────
# ELBOW METHOD FOR K-MEANS 
# `get_elbow_data` computes the optimal number of clusters (K) for K-Means
# by analyzing the inertia (within-cluster sum of squares) across a range of K values
# ─────────────────────────────────────────────

def get_elbow_data(db: Session, k_max: int = 25) -> dict:
    try:
        import numpy as np
        from sklearn.cluster import KMeans

        rows = (
            db.query(
                OscaOccupationSkill.occupation_id,
                OscaOccupationSkill.skill_id
            ).all()
        )

        if not rows:
            return {"optimal_k": 16}

        all_skill_ids = sorted(set(r.skill_id      for r in rows))
        all_occ_ids   = sorted(set(r.occupation_id for r in rows))

        skill_index = {sid: i for i, sid in enumerate(all_skill_ids)}
        occ_index   = {oid: i for i, oid in enumerate(all_occ_ids)}

        matrix = np.zeros((len(all_occ_ids), len(all_skill_ids)), dtype=np.float32)
        for r in rows:
            matrix[occ_index[r.occupation_id], skill_index[r.skill_id]] = 1.0

        k_max    = min(k_max, len(all_occ_ids))
        k_range  = list(range(2, k_max + 1))
        inertias = []

        for k in k_range:
            km = KMeans(n_clusters=k, random_state=42, n_init=5, max_iter=100)
            km.fit(matrix)
            inertias.append(float(km.inertia_))

        inertia_arr  = np.array(inertias)
        inertia_norm = (inertia_arr - inertia_arr.min()) / (inertia_arr.max() - inertia_arr.min() + 1e-9)

        if len(inertia_norm) >= 3:
            second_deriv = np.diff(inertia_norm, n=2)
            elbow_idx    = int(np.argmax(np.abs(second_deriv))) + 2
            # If index 0 of second_deriv represents k=3
            optimal_k = k_range[int(np.argmax(np.abs(second_deriv))) + 1]
        else:
            optimal_k = k_range[0]

        return {"optimal_k": optimal_k, "k_range": k_range, "inertias": inertias}

    except Exception as e:
        logger.error(f"[MSIT402|SP] get_elbow_data failed: {e}")
        return {"optimal_k": 16}

# ─────────────────────────────────────────────
# OCCUPATION CLUSTERING
# Uses K-Means on binary skill vectors to group all occupations
# into clusters based on shared skill profiles.
# Returns the cluster the selected occupation belongs to,
# and all other members of that cluster.
# ─────────────────────────────────────────────
 
def get_occupation_clusters(db: Session, occupation_id: int, n_clusters: int = None) -> dict:
    """
    Clusters all occupations by skill profile using K-Means.
    Returns the cluster the selected occupation belongs to
    and the other members of that cluster ranked by similarity.
    """
    try:
        from sklearn.cluster import KMeans
        from sklearn.metrics.pairwise import cosine_similarity
 
        # Fetch all occupation-skill mappings
        rows = (
            db.query(
                OscaOccupationSkill.occupation_id,
                OscaOccupationSkill.skill_id
            )
            .all()
        )
 
        if not rows:
            return {"error": "No skill mapping data available"}
 
        all_skill_ids = sorted(set(r.skill_id      for r in rows))
        all_occ_ids   = sorted(set(r.occupation_id for r in rows))
 
        if occupation_id not in all_occ_ids:
            return {"error": "Occupation has no mapped skills — cannot cluster"}
 
        skill_index = {sid: i for i, sid in enumerate(all_skill_ids)}
        occ_index   = {oid: i for i, oid in enumerate(all_occ_ids)}
 
        # Build binary skill matrix
        matrix = np.zeros((len(all_occ_ids), len(all_skill_ids)), dtype=np.float32)
        for r in rows:
            matrix[occ_index[r.occupation_id], skill_index[r.skill_id]] = 1.0


        # Auto-detect optimal K unless explicitly overridden
        if n_clusters is None:
            global _OPTIMAL_K_CACHE
            current_count = len(all_occ_ids)
            if (_OPTIMAL_K_CACHE["k"] is not None and
                    _OPTIMAL_K_CACHE["occ_count"] == current_count):
                n_clusters = _OPTIMAL_K_CACHE["k"]
                logger.info(f"[MSIT402|SP] Using cached K={n_clusters}")
            else:
                logger.info("[MSIT402|SP] Recomputing optimal K via elbow method...")
                elbow      = get_elbow_data(db, k_max=20)
                n_clusters = elbow.get("optimal_k", 16)
                _OPTIMAL_K_CACHE["k"]         = n_clusters
                _OPTIMAL_K_CACHE["occ_count"] = current_count
                logger.info(f"[MSIT402|SP] Optimal K = {n_clusters} for {current_count} occupations")

        # K-Means clustering — cap n_clusters to available occupations
        k = min(n_clusters, len(all_occ_ids))
        kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = kmeans.fit_predict(matrix)
 
        # Find the cluster of the selected occupation
        target_cluster = int(labels[occ_index[occupation_id]])
 
        # Members of the same cluster
        cluster_member_ids = [
            all_occ_ids[i] for i, lbl in enumerate(labels)
            if lbl == target_cluster and all_occ_ids[i] != occupation_id
        ]
 
        # Rank cluster members by cosine similarity to target
        target_vec = matrix[occ_index[occupation_id]].reshape(1, -1)
        if cluster_member_ids:
            member_indices = [occ_index[oid] for oid in cluster_member_ids]
            member_matrix  = matrix[member_indices]
            sim_scores     = cosine_similarity(target_vec, member_matrix)[0]
            ranked_members = sorted(
                zip(cluster_member_ids, sim_scores.tolist()),
                key=lambda x: x[1], reverse=True
            )[:10]
        else:
            ranked_members = []
 
        # Fetch titles
        from app.models.osca import OscaOccupation
        all_needed_ids = [occupation_id] + [r[0] for r in ranked_members]
        occ_rows = (
            db.query(OscaOccupation.id, OscaOccupation.principal_title, OscaOccupation.skill_level)
            .filter(OscaOccupation.id.in_(all_needed_ids))
            .all()
        )
        title_map = {o.id: {"title": o.principal_title, "level": o.skill_level} for o in occ_rows}
 
        members = [
            {
                "occupation_id":    oid,
                "title":            title_map.get(oid, {}).get("title", f"occ_{oid}"),
                "skill_level":      title_map.get(oid, {}).get("level"),
                "similarity_score": round(score * 100, 1),
            }
            for oid, score in ranked_members
            if oid in title_map
        ]
 
        return {
            "occupation_id":    occupation_id,
            "cluster_id":       target_cluster,
            "cluster_label":    f"{target_cluster + 1}",
            "cluster_size":     len(cluster_member_ids) + 1,
            "n_clusters":       k,
            "cluster_members":  members,
        }
 
    except Exception as e:
        logger.error(f"[MSIT402|SP] get_occupation_clusters failed: {e}")
        return {"error": str(e)}
 