from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional

from app.database import get_db
from app.models.osca import (
    OscaMajorGroup, OscaSubMajorGroup, OscaMinorGroup,
    OscaUnitGroup, OscaOccupation, OscaAlternativeTitle
)
from app.models.skills import OscaOccupationSkill

router = APIRouter(prefix="/api/occupations", tags=["occupations"])


@router.get("/major-groups")
def get_major_groups(db: Session = Depends(get_db)):
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
    db: Session = Depends(get_db)
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
    db: Session = Depends(get_db)
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
    # limit:              int = Query(2000, le=2000),
    major_group_id:     Optional[int] = Query(None),
    sub_major_group_id: Optional[int] = Query(None),
    minor_group_id:     Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    
    #Aggregate Skill IDs instead of just counting them
    # Using array_agg to get a list of skill IDs for each occupation
    skill_data = (
        db.query(
            OscaOccupationSkill.occupation_id,
            func.count(OscaOccupationSkill.skill_id).label("skill_count"),
            func.array_agg(OscaOccupationSkill.skill_id).label("skill_ids") 
        )
        .group_by(OscaOccupationSkill.occupation_id)
        .subquery()
    )

    q = (
        db.query(
            OscaOccupation.id,
            OscaOccupation.principal_title.label("title"),
            OscaOccupation.skill_level,
            OscaOccupation.unit_group_id,
            func.coalesce(skill_data.c.skill_count, 0).label("skill_count"),
            func.coalesce(skill_data.c.skill_ids, []).label("skill_ids")
        )
        .outerjoin(skill_data, skill_data.c.occupation_id == OscaOccupation.id)
        .join(OscaUnitGroup, OscaUnitGroup.id == OscaOccupation.unit_group_id)
    )
    """
    Flat list of occupations for the sidebar occupation list.
    Includes skill_count and has_data flag so the UI can dim
    occupations with no skill data.

    Filters cascade: major → sub-major → minor group.Count skills per occupation in one subquery

    """

    # Apply hierarchy filters
    if minor_group_id:
        q = q.filter(OscaUnitGroup.minor_group_id == minor_group_id)
    elif sub_major_group_id:
        q = (q
             .join(OscaMinorGroup, OscaMinorGroup.id == OscaUnitGroup.minor_group_id)
             .filter(OscaMinorGroup.sub_major_group_id == sub_major_group_id))
    elif major_group_id:
        q = (q
             .join(OscaMinorGroup, OscaMinorGroup.id == OscaUnitGroup.minor_group_id)
             .join(OscaSubMajorGroup, OscaSubMajorGroup.id == OscaMinorGroup.sub_major_group_id)
             .filter(OscaSubMajorGroup.major_group_id == major_group_id))

    rows = q.order_by(OscaOccupation.principal_title).all()
    
    # alternative title search
    occ_ids = [r.id for r in rows]
    alt_rows = (
        db.query(OscaAlternativeTitle.occupation_id, OscaAlternativeTitle.title)
        .filter(OscaAlternativeTitle.occupation_id.in_(occ_ids))
        .all()
    )
    alt_map = {}
    for a in alt_rows:
        alt_map.setdefault(a.occupation_id, []).append(a.title.lower())

    return [
        {
            "id":          r.id,
            "title":       r.title,
            "skill_level": r.skill_level,
            "skill_count": r.skill_count,
            "unit_group_id": r.unit_group_id,
            "skill_ids":   [str(s) for s in r.skill_ids] if r.skill_ids else [], # Convert to strings for easier JS searching
            "has_data":    r.skill_count > 0,
            "alt_titles":  alt_map.get(r.id, [])
        }
        for r in rows
    ]


# debug 
@router.get("/debug/data-coverage")
def data_coverage(db: Session = Depends(get_db)):
    """Temporary — shows which major groups have skill data."""
    from sqlalchemy import func
    rows = (
        db.query(
            OscaMajorGroup.title,
            func.count(OscaOccupationSkill.skill_id.distinct()).label("skill_mappings")
        )
        .join(OscaSubMajorGroup, OscaSubMajorGroup.major_group_id == OscaMajorGroup.id)
        .join(OscaMinorGroup,    OscaMinorGroup.sub_major_group_id == OscaSubMajorGroup.id)
        .join(OscaUnitGroup,     OscaUnitGroup.minor_group_id == OscaMinorGroup.id)
        .join(OscaOccupation,    OscaOccupation.unit_group_id == OscaUnitGroup.id)
        .outerjoin(OscaOccupationSkill, OscaOccupationSkill.occupation_id == OscaOccupation.id)
        .group_by(OscaMajorGroup.title)
        .order_by(func.count(OscaOccupationSkill.skill_id.distinct()).desc())
        .all()
    )
    return [{"major_group": r.title, "skill_mappings": r.skill_mappings} for r in rows]