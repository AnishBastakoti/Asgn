import logging
import numpy as np

from fastapi import HTTPException
from sqlalchemy.orm import Session
from sklearn.metrics.pairwise import cosine_similarity

from app.models.skills import OscaOccupationSkill


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
    based on their ESCO skill vectors. Returns the top N most similar occupations.
    """
    try:
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