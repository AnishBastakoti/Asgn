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
 