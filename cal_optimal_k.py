"""
SkillPulse — Elbow Method Analysis
"""

import numpy as np
from sklearn.cluster import KMeans
from app.database import SessionLocal
from app.models.skills import OscaOccupationSkill

def find_optimal_k(k_max=20):
    print("=" * 55)
    print("  SkillPulse — K-Means Elbow Analysis")
    print("=" * 55)

    db = SessionLocal()
    try:
        # ── Build skill matrix ──────────────────────────────
        print("\n[1/3] Fetching occupation-skill mappings...")
        rows = db.query(
            OscaOccupationSkill.occupation_id,
            OscaOccupationSkill.skill_id
        ).all()

        all_skill_ids = sorted(set(r.skill_id      for r in rows))
        all_occ_ids   = sorted(set(r.occupation_id for r in rows))
        print(f"      Occupations : {len(all_occ_ids)}")
        print(f"      Skills      : {len(all_skill_ids)}")
        print(f"      Mappings    : {len(rows)}")

        skill_index = {sid: i for i, sid in enumerate(all_skill_ids)}
        occ_index   = {oid: i for i, oid in enumerate(all_occ_ids)}

        print("\n[2/3] Building binary skill matrix...")
        matrix = np.zeros((len(all_occ_ids), len(all_skill_ids)), dtype=np.float32)
        for r in rows:
            matrix[occ_index[r.occupation_id], skill_index[r.skill_id]] = 1.0
        print(f"      Matrix shape: {matrix.shape}")

        # ── Run K-Means for each K ──────────────────────────
        print(f"\n[3/3] Running K-Means for k=2..{k_max}...")
        print(f"\n  {'K':>4}  {'Inertia':>14}  {'Drop %':>8}")
        print(f"  {'-'*4}  {'-'*14}  {'-'*8}")

        k_range  = list(range(2, k_max + 1))
        inertias = []

        for k in k_range:
            km = KMeans(n_clusters=k, random_state=42, n_init=5, max_iter=100)
            km.fit(matrix)
            inertias.append(float(km.inertia_))

            drop = ""
            if len(inertias) > 1:
                pct  = (inertias[-2] - inertias[-1]) / inertias[-2] * 100
                drop = f"{pct:7.1f}%"

            print(f"  k={k:2d}   {km.inertia_:>13.1f}  {drop}")

        # ── Elbow detection (second derivative) ────────────
        inertia_arr  = np.array(inertias)
        inertia_norm = (inertia_arr - inertia_arr.min()) / \
                       (inertia_arr.max() - inertia_arr.min() + 1e-9)
        second_deriv = np.diff(inertia_norm, n=2)
        elbow_idx    = int(np.argmax(np.abs(second_deriv))) + 2
        optimal_k    = k_range[elbow_idx]

        print("\n" + "=" * 55)
        print(f"  OPTIMAL K = {optimal_k}  (second-derivative elbow method)")
        print("=" * 55)
        print(f"Done..")
        return optimal_k

    finally:
        db.close()


if __name__ == "__main__":
    find_optimal_k(k_max=20)