from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from typing import Optional


from core.auth_deps import require_auth
from app.database import get_db
from app.models.osca import (
    OscaMajorGroup, OscaSubMajorGroup, OscaMinorGroup,
    OscaUnitGroup, OscaOccupation, OscaAlternativeTitle
)
from app.models.skills import OscaOccupationSkill

router = APIRouter(prefix="/api/occupations", tags=["occupations"])

_auth = [Depends(require_auth)]

@router.get("/major-groups")
def get_major_groups(db: Session = Depends(get_db), user = Depends(require_auth)):
    """
    All major groups with how many occupations fall under each.
    Used to populate the first sidebar dropdown.
    """
    rows = (
        db.query(
            OscaMajorGroup.id,
            OscaMajorGroup.title,
            func.count(OscaOccupation.id).label("occupation_count"),
            func.count(OscaOccupationSkill.skill_id).label("data_count")
        )
        .join(OscaSubMajorGroup, OscaSubMajorGroup.major_group_id == OscaMajorGroup.id)
        .join(OscaMinorGroup,    OscaMinorGroup.sub_major_group_id == OscaSubMajorGroup.id)
        .join(OscaUnitGroup,     OscaUnitGroup.minor_group_id == OscaMinorGroup.id)
        .join(OscaOccupation,    OscaOccupation.unit_group_id == OscaUnitGroup.id)
        .group_by(OscaMajorGroup.id, OscaMajorGroup.title)
        .order_by(OscaMajorGroup.id)
        .all()
    )
    return [{"id": r.id, "title": r.title, "occupation_count": r.occupation_count, "data_count": r.data_count > 0}
            for r in rows]


@router.get("/sub-major-groups")
def get_sub_major_groups(
    major_group_id: int = Query(...),
    db: Session = Depends(get_db), 
    user = Depends(require_auth)
):
    """Sub-major groups for a given major group."""
    rows = (
        db.query(OscaSubMajorGroup)
        .filter(OscaSubMajorGroup.major_group_id == major_group_id)
        .order_by(OscaSubMajorGroup.id)
        .all()
    )
    return [{"id": r.id, "title": r.title} for r in rows]


@router.get("/minor-groups")
def get_minor_groups(
    sub_major_group_id: int = Query(...),
    db: Session = Depends(get_db),
    user = Depends(require_auth)
):
    """Minor groups for a given sub-major group."""
    rows = (
        db.query(OscaMinorGroup)
        .filter(OscaMinorGroup.sub_major_group_id == sub_major_group_id)
        .order_by(OscaMinorGroup.id)
        .all()
    )
    return [{"id": r.id, "title": r.title} for r in rows]

@router.get("/list")
def list_occupations(
    major_group_id:     Optional[int] = Query(None),
    sub_major_group_id: Optional[int] = Query(None),
    minor_group_id:     Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user = Depends(require_auth)
):
    
    # array_agg is omitted — COUNT alone is enough for the skill badge and
    # avoids the expensive per-occupation skill ID aggregation.
    sql = """
        SELECT
            o.id, o.principal_title as title,
            o.skill_level, o.unit_group_id,
            COALESCE(s.skill_count, 0) as skill_count
        FROM osca_occupations o
        LEFT JOIN (
            SELECT occupation_id, COUNT(skill_id) as skill_count
            FROM osca_occupation_skills
            GROUP BY occupation_id
        ) s ON s.occupation_id = o.id
        LEFT JOIN osca_unit_groups ug ON ug.id = o.unit_group_id
    """

    params = {}

    if minor_group_id:
        sql += " WHERE ug.minor_group_id = :minor_id"
        params['minor_id'] = minor_group_id
    elif sub_major_group_id:
        sql += """
            JOIN osca_minor_groups mg ON mg.id = ug.minor_group_id
            WHERE mg.sub_major_group_id = :sub_major_id
        """
        params['sub_major_id'] = sub_major_group_id
    elif major_group_id:
        sql += """
            JOIN osca_minor_groups mg ON mg.id = ug.minor_group_id
            JOIN osca_sub_major_groups smg ON smg.id = mg.sub_major_group_id
            WHERE smg.major_group_id = :major_id
        """
        params['major_id'] = major_group_id

    sql += " ORDER BY o.principal_title"

    rows = db.execute(text(sql), params).fetchall()

    alt_map: dict = {}
    if rows:
        occ_ids = [r.id for r in rows]
        alt_rows = (
            db.query(OscaAlternativeTitle.occupation_id, OscaAlternativeTitle.title)
            .filter(OscaAlternativeTitle.occupation_id.in_(occ_ids))
            .all()
        )
        for a in alt_rows:
            alt_map.setdefault(a.occupation_id, []).append(a.title.lower())

    return [
        {
            "id":            r.id,
            "title":         r.title,
            "skill_level":   r.skill_level,
            "skill_count":   r.skill_count,
            "unit_group_id": r.unit_group_id,
            "skill_ids":     [],
            "has_data":      r.skill_count > 0,
            "alt_titles":    alt_map.get(r.id, [])
        }
        for r in rows
    ]

@router.get("/{occupation_id}")
def get_occupation_detail(occupation_id: int, db: Session = Depends(get_db), user = Depends(require_auth)):
    occupation = (
        db.query(
            OscaOccupation.id,
            OscaOccupation.principal_title,
            OscaOccupation.skill_level,
            OscaOccupation.lead_statement,
            OscaOccupation.caveats,
            OscaOccupation.licensing,
            OscaOccupation.nec_category,
            OscaOccupation.skill_attributes,
            OscaOccupation.specialisations,
            OscaOccupation.main_tasks,
            OscaOccupation.information_card,
            # embedding excluded
        )
        .filter(OscaOccupation.id == occupation_id)
        .first()
    )

    if not occupation:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Occupation not found")

    return {
        "id":                occupation.id,
        "title":             occupation.principal_title,
        "skill_level":       occupation.skill_level,
        "lead_statement":    occupation.lead_statement,
        "caveats":           occupation.caveats,
        "licensing":         occupation.licensing,
        "nec_category":      occupation.nec_category,
        "skill_attributes":  occupation.skill_attributes,
        "specialisations":   occupation.specialisations,
        "main_tasks":        occupation.main_tasks,
        "information_card":  occupation.information_card,
}