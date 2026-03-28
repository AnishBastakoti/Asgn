import logging
import pandas as pd

from sklearn.linear_model import Ridge # Ridge handles multicollinearity
from sklearn.preprocessing import StandardScaler
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.skills import OscaOccupationSkill, SkillpulseCityOccupationDemand
from app.models.jobs import JobPostLog

logger = logging.getLogger(__name__)


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


"""
    features from multiple tables to create a training matrix.
    Formula to predict future demand (job counts) for occupations based on current demand and shadow skill signals:
    Predicted Demand = β^0+ (β^1x Current Count)+ (β^2x Shadow Skills)
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
 
    # current demand per occupation ──
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
 
    # ── shadow skill count ──
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
 
    # official skill count + avg mention count ──
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
 
    occ_data = db.query(SkillpulseCityOccupationDemand.occupation_title).filter(SkillpulseCityOccupationDemand.occupation_id == occupation_id).first()
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
 
def get_occupation_prediction(db: Session, occupation_id: int, model_preference: str = None):
    """
    Predicts future demand using Ridge regression when trained,
    falling back to momentum forecasting otherwise.
    Model retrains automatically when data changes.
    """
    features = get_occupation_features(db, occupation_id)
 
    if features["current_demand"] == 0:
        return None
 
    force_momentum = (model_preference == "momentum")
    model_ready = False if force_momentum else _ensure_model_trained(db)
 
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
 
 