import os
import logging
import pickle
import threading
import hashlib
import numpy as np
import time 

from dataclasses import dataclass
from typing import Optional
from sqlalchemy.orm import Session

from sklearn.metrics.pairwise import cosine_similarity
from sklearn.cluster import KMeans
from app.models.osca import OscaOccupation
from app.services.matrix_cache import get_matrix
from config import settings

logger = logging.getLogger(__name__)

# ── Authorship Fingerprint ─────────────────────────────────
_FP = hashlib.sha256(
    f"{settings.AUTHOR_KEY}:{settings.APP_NAME}:{settings.APP_VERSION}".encode()
).hexdigest()[:12]

_SIGNATURE = hashlib.sha256(settings.AUTHOR_KEY.encode()).hexdigest()[:8].upper()


# ── KMeans model cache ───────────────────────────────────────────────────────

@dataclass
class _KMeansCache:
    model:      object     # fitted sklearn KMeans instance
    labels:    np.ndarray[np.float64, np.dtype[np.float64]]  # shape: (n_occupations,)  int labels per occ
    k:          int
    occ_count:  int        # occupation count at fit time — used for invalidation

_KMEANS_CACHE: Optional[_KMeansCache] = None
_KMEANS_LOCK  = threading.Lock()

_CACHE_DIR       = os.path.dirname(os.path.abspath(__file__))
_KMEANS_PKL_PATH = os.path.join(_CACHE_DIR, "skillpulse_kmeans.pkl")


# ── Disk cache ─────────────────────────────────────────────────────────

def _save_kmeans_to_disk(cache: _KMeansCache) -> None:
    try:
        with open(_KMEANS_PKL_PATH, "wb") as f:
            pickle.dump(cache, f, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info(f"[MSIT402|SP] KMeans cache saved to disk (k={cache.k})")
    except Exception as e:
        logger.warning(f"[MSIT402|SP] Could not save KMeans to disk: {e}")


def _load_kmeans_from_disk() -> Optional[_KMeansCache]:
    if not os.path.exists(_KMEANS_PKL_PATH):
        return None
    try:
        with open(_KMEANS_PKL_PATH, "rb") as f:
            cache = pickle.load(f)
        logger.info(f"[MSIT402|SP] KMeans cache loaded from disk (k={cache.k})")
        return cache
    except Exception as e:
        logger.warning(f"[MSIT402|SP] Could not load KMeans from disk: {e}")
        return None


# ── Load from disk at module import ──────────────────────────────────────────
_KMEANS_CACHE = _load_kmeans_from_disk()


# ── get or fit KMeans ──────────────────────────────────────────────

def _get_kmeans(db: Session, n_clusters: Optional[int] = None) -> _KMeansCache:
    """
    Returns a fitted KMeans cache, rebuilding only when:
      - cache is empty, OR
      - occupation count has changed
    """
    global _KMEANS_CACHE

    mc = get_matrix(db)   # shared matrix — already cached after first call

    try:
        with _KMEANS_LOCK:
            # Cache hit: same occupation count and no explicit override
            if (
                _KMEANS_CACHE is not None
                and _KMEANS_CACHE.occ_count == mc.n_occupations
                and (n_clusters is None or n_clusters == _KMEANS_CACHE.k)
            ):
                return _KMEANS_CACHE

            # Determine K
            if n_clusters is None:
                if _KMEANS_CACHE is not None and _KMEANS_CACHE.occ_count == mc.n_occupations:
                    # occupation count unchanged — reuse stored K
                    k = _KMEANS_CACHE.k
                else:
                    logger.info("[MSIT402|SP] Computing optimal K via elbow method …")
                    k = _compute_optimal_k(mc.matrix)
                    logger.info(f"[MSIT402|SP] Optimal K = {k}")
            else:
                k = n_clusters

            k = min(k, mc.n_occupations)

            logger.info(f"[MSIT402|SP] Fitting KMeans k={k} on {mc.n_occupations} occupations …")
            kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
            labels = kmeans.fit_predict(mc.matrix)

            _KMEANS_CACHE = _KMeansCache(
                model=kmeans,
                labels=labels,
                k=k,
                occ_count=mc.n_occupations,
            )
            _save_kmeans_to_disk(_KMEANS_CACHE)
            return _KMEANS_CACHE
    except Exception as e:
        logger.error(f"[MSIT402|SP] _get_kmeans failed: {e}")
        raise


def _compute_optimal_k_from_inertias(inertias: list[float], k_range: list[int]) -> int:
    """Mathematical elbow detection using second derivative of inertia."""
    inertia_arr  = np.array(inertias)
    denom        = inertia_arr.max() - inertia_arr.min() + 1e-9
    inertia_norm = (inertia_arr - inertia_arr.min()) / denom

    if len(inertia_norm) >= 3:
        second_deriv = np.diff(inertia_norm, n=2)
        optimal_k    = k_range[int(np.argmax(np.abs(second_deriv))) + 1]
    else:
        optimal_k = k_range[0]

    return optimal_k


def _compute_optimal_k(matrix: np.ndarray, k_max: int = 20) -> int:
    """Elbow method on the already-built matrix — no DB access needed."""

    k_max    = min(k_max, matrix.shape[0])
    k_range  = list(range(2, k_max + 1))
    inertias = []

    for k in k_range:
        km = KMeans(n_clusters=k, random_state=42, n_init=5, max_iter=100)
        km.fit(matrix)
        inertias.append(float(km.inertia_))

    return _compute_optimal_k_from_inertias(inertias, k_range)


# ── Public API ────────────────────────────────────────────────────────────────

def get_elbow_data(db: Session, k_max: int = 25) -> dict:
    """
    Returns inertia values and optimal K.
    Re-uses the shared matrix — never queries OscaOccupationSkill directly.
    """
    try:
        mc       = get_matrix(db)
        k_max    = min(k_max, mc.n_occupations)
        k_range  = list(range(2, k_max + 1))
        inertias = []

        for k in k_range:
            km = KMeans(n_clusters=k, random_state=42, n_init=5, max_iter=100)
            km.fit(mc.matrix)
            inertias.append(float(km.inertia_))

        optimal_k = _compute_optimal_k_from_inertias(inertias, k_range)

        return {"optimal_k": optimal_k, "k_range": k_range, "inertias": inertias}

    except Exception as e:
        logger.error(f"[MSIT402|SP] get_elbow_data failed: {e}")
        return {"optimal_k": 16}


def get_occupation_clusters(db: Session, occupation_id: int, n_clusters: Optional[int] = None) -> dict:
    """
    Clusters all occupations by skill profile using K-Means.
    Returns the cluster the selected occupation belongs to
    and its members ranked by cosine similarity.
    """
    try:
        starttime= time.time()
        mc     = get_matrix(db)
        kc     = _get_kmeans(db, n_clusters)

        if occupation_id not in mc.occ_index:
            return {"error": "Occupation has no mapped skills — cannot cluster"}

        target_idx     = mc.occ_index[occupation_id]
        target_cluster = int(kc.labels[target_idx])

        cluster_member_ids = [
            mc.all_occ_ids[i]
            for i, lbl in enumerate(kc.labels)
            if lbl == target_cluster and mc.all_occ_ids[i] != occupation_id
        ]

        elapsed_clustering = (time.time() - starttime) * 1000
        logger.debug(f"[MSIT402|SP] Cluster retrieval took {elapsed_clustering:.2f}ms")

        # Optimization: We want top_n items TOTAL. 
        # Since the target is 1 item, we fetch (top_n - 1) similar members.
        members_to_fetch = max(0, top_n - 1)

        target_vec = mc.matrix[target_idx].reshape(1, -1)
        if cluster_member_ids:
            member_indices = [mc.occ_index[oid] for oid in cluster_member_ids]
            sim_scores     = cosine_similarity(target_vec, mc.matrix[member_indices])[0]
            ranked_members = sorted(
                zip(cluster_member_ids, sim_scores.tolist()),
                key=lambda x: x[1],
                reverse=True,
            )[:members_to_fetch]
        else:
            ranked_members = []

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
        total_elapsed = (time.time() - starttime) * 1000
        logger.info(f"[MSIT402|SP] get_occupation_clusters for {occupation_id} completed in {total_elapsed:.2f}ms")

        # Logic for Warning if data is less than requested
        warning = None
        total_returned = len(members) + 1
        if total_returned < top_n:
            warning = f"Only {total_returned} occupations found in this cluster (requested {top_n})."

        return {
            "occupation_id":   occupation_id,
            "cluster_id":      target_cluster,
            "cluster_label":   f"{target_cluster + 1}",
            "cluster_size":    len(cluster_member_ids) + 1,
            "n_clusters":      kc.k,
            "cluster_members": members,
            "warning":         warning
        }

    except Exception as e:
        logger.error(f"[MSIT402|SP] get_occupation_clusters failed: {e}")
        return {"error": str(e)}