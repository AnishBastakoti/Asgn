import os
import logging
import numpy as np
import pickle

from sqlalchemy.orm import Session

from app.models.skills import OscaOccupationSkill

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
 