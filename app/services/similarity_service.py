import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session
from sklearn.metrics.pairwise import cosine_similarity

from app.services.matrix_cache import get_matrix

logger = logging.getLogger(__name__)

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
    based on their OSCA skill vectors. Returns the top N most similar occupations.
    """
    try:
        # ── replaces the entire DB query + matrix build ──
        mc = get_matrix(db)

        if occupation_id not in mc.occ_index:
            raise ValueError(f"Occupation {occupation_id} has no mapped skills.")

        target_vec = mc.matrix[mc.occ_index[occupation_id]].reshape(1, -1)
        scores     = cosine_similarity(target_vec, mc.matrix)[0]

        ranked = sorted(
            [
                (mc.all_occ_ids[i], float(scores[i]))
                for i in range(mc.n_occupations)
                if mc.all_occ_ids[i] != occupation_id
            ],
            key=lambda x: x[1],
            reverse=True,
        )[:top_n]

        if not ranked:
            return {"similar": [], "total_skills": int(target_vec.sum())}

        from app.models.osca import OscaOccupation
        top_ids   = [r[0] for r in ranked]
        score_map = {r[0]: r[1] for r in ranked}
        occ_rows  = (
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
            "similar":       similar,
        }

    except Exception as e:
        logger.error(f"[SimilarityService] get_occupation_similarity failed: {e}")
        return {"error": str(e)}