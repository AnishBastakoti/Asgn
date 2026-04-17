import logging
import hashlib
import threading
import numpy as np
from dataclasses import dataclass, field
from typing import Optional, List, Dict

from sqlalchemy.orm import Session
from app.models.skills import OscaOccupationSkill
from app.models.osca import OscaOccupation
from config import settings

logger = logging.getLogger(__name__)

_FP = hashlib.sha256(
    f"{settings.AUTHOR_KEY}:{settings.APP_NAME}:{settings.APP_VERSION}".encode()
).hexdigest()[:12]

# ── Data container ──────────────────────────────────────────────────────────

@dataclass
class OccupationMatrix:
    """
    Holds the skill matrix and all index maps needed by services.
    Treat this as read-only once built.
    """
    matrix:      np.ndarray          # shape: (n_occupations, n_skills)  float32
    all_occ_ids: List[int]           # sorted list of occupation IDs
    all_skill_ids: List[int]         # sorted list of skill IDs
    occ_index:   Dict[int, int]      # occupation_id → row index
    skill_index: Dict[int, int]      # skill_id      → column index

    @property
    def n_occupations(self) -> int:
        return self.matrix.shape[0]

    @property
    def n_skills(self) -> int:
        return self.matrix.shape[1]


# ── Module-level in-memory cache ────────────────────────────────────────────

_cache: Optional[OccupationMatrix] = None
_cache_occ_count: Optional[int]    = None
_lock = threading.Lock()           # safe for multi-threaded


# ── Public API ───────────────────────────────────────────────────────────────

def get_matrix(db: Session, force_rebuild: bool = False) -> OccupationMatrix:
    """
    Returns the cached OccupationMatrix, rebuilding it only when:
      - the cache is empty (first call), OR
      - the number of occupations has changed, OR
      - force_rebuild=True is passed explicitly.

    This is the ONLY function both similarity_service and cluster_service calls. 
    """
    global _cache, _cache_occ_count

    with _lock:
        if not force_rebuild and _cache is not None:
            # Quick row-count check — cheap single-column COUNT query
            # Optimization: Count primary occupations instead of the massive mapping table
            current_count = db.query(OscaOccupation.id).count()
            if current_count == _cache_occ_count:
                return _cache          # cache hit, return immediately

        logger.info("[MatrixCache] Building occupation-skill matrix from DB …")
        _cache = _build_matrix(db)
        _cache_occ_count = _cache.n_occupations
        logger.info(
            f"[MatrixCache] Built {_cache.n_occupations} × {_cache.n_skills} "
            f"matrix ({_cache.matrix.nbytes / 1e6:.1f} MB)"
        )
        return _cache


def invalidate_cache() -> None:
    """ this from your pipeline during production if needed for us /import endpoints after bulk data changes."""
    global _cache, _cache_occ_count
    with _lock:
        _cache = None
        _cache_occ_count = None
    logger.info("[MatrixCache] Cache invalidated.")


# ── Internal builder ─────────────────────────────────────────────────────────

def _build_matrix(db: Session) -> OccupationMatrix:
    rows = (
        db.query(
            OscaOccupationSkill.occupation_id,
            OscaOccupationSkill.skill_id,
        ).all()
    )

    if not rows:
        raise ValueError("OscaOccupationSkill table is empty — cannot build matrix.")

    all_skill_ids = sorted(set(r.skill_id for r in rows))
    all_occ_ids   = sorted(set(r.occupation_id for r in rows))

    skill_index = {sid: i for i, sid in enumerate(all_skill_ids)}
    occ_index   = {oid: i for i, oid in enumerate(all_occ_ids)}

    matrix = np.zeros((len(all_occ_ids), len(all_skill_ids)), dtype=np.float32)
    for r in rows:
        matrix[occ_index[r.occupation_id], skill_index[r.skill_id]] = 1.0

    return OccupationMatrix(
        matrix=matrix,
        all_occ_ids=all_occ_ids,
        all_skill_ids=all_skill_ids,
        occ_index=occ_index,
        skill_index=skill_index,
    )