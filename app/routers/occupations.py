# from fastapi import APIRouter, Depends, HTTPException, Query
# from pydantic import BaseModel
# from typing import Optional
# from sqlalchemy.orm import Session

# from app.database import get_db
# from app.services.occupation_service import (
#     get_major_groups,
#     get_sub_major_groups,
#     get_minor_groups,
#     get_occupations,
#     get_occupation_detail
# )

# router = APIRouter(prefix="/api/occupations", tags=["Occupations"])


# # --- Response Schemas

# class MajorGroupResponse(BaseModel):
#     id:               int
#     title:            str
#     occupation_count: int

#     class Config:
#         from_attributes = True


# class SubMajorGroupResponse(BaseModel):
#     id:             int
#     title:          str
#     major_group_id: int

#     class Config:
#         from_attributes = True


# class MinorGroupResponse(BaseModel):
#     id:                 int
#     title:              str
#     sub_major_group_id: int

#     class Config:
#         from_attributes = True


# class OccupationResponse(BaseModel):
#     id:            int
#     title:         str
#     skill_level:   Optional[int]
#     unit_group_id: int
#     skill_count:   int
#     has_data:      bool

#     class Config:
#         from_attributes = True


# class BreadcrumbItem(BaseModel):
#     level: str
#     title: Optional[str]


# class OccupationDetailResponse(BaseModel):
#     id:             int
#     title:          str
#     skill_level:    Optional[int]
#     lead_statement: Optional[str]
#     breadcrumb:     list[BreadcrumbItem]
#     signature:      str

#     class Config:
#         from_attributes = True


# # --- Endpoints 

# @router.get("/major-groups", response_model=list[MajorGroupResponse])
# def list_major_groups(db: Session = Depends(get_db)):
#     """
#     Get all OSCA major groups with occupation counts.
#     Powers the first dropdown in the sidebar.
#     Called once on page load.
#     """
#     return get_major_groups(db)


# @router.get("/sub-major-groups", response_model=list[SubMajorGroupResponse])
# def list_sub_major_groups(
#     major_group_id: Optional[int] = Query(
#         default=None,
#         description="Filter by major group ID"
#     ),
#     db: Session = Depends(get_db)
# ):
#     """
#     Get sub-major groups optionally filtered by major group.
#     Powers the second dropdown.
#     Called when user selects a major group.
#     """
#     return get_sub_major_groups(db, major_group_id)


# @router.get("/minor-groups", response_model=list[MinorGroupResponse])
# def list_minor_groups(
#     sub_major_group_id: Optional[int] = Query(
#         default=None,
#         description="Filter by sub-major group ID"
#     ),
#     db: Session = Depends(get_db)
# ):
#     """
#     Get minor groups optionally filtered by sub-major group.
#     Powers the third dropdown.
#     Called when user selects a sub-major group.
#     """
#     return get_minor_groups(db, sub_major_group_id)


# @router.get("/list", response_model=list[OccupationResponse])
# def list_occupations(
#     unit_group_id: Optional[int] = Query(
#         default=None,
#         description="Filter by unit group ID"
#     ),
#     search: Optional[str] = Query(
#         default=None,
#         min_length=2,
#         max_length=100,
#         description="Search occupation titles"
#     ),
#     limit: int = Query(
#         default=100,
#         ge=10,
#         le=500,
#         description="Maximum results to return"
#     ),
#     db: Session = Depends(get_db)
# ):
#     """
#     List occupations with optional filtering and search.
#     Powers the occupation list in the sidebar.

#     min_length=2 prevents single character searches
#     that would return too many results.
#     """
#     return get_occupations(db, unit_group_id, search, limit)


# @router.get("/{occupation_id}", response_model=OccupationDetailResponse)
# def get_occupation(
#     occupation_id: int,
#     db: Session = Depends(get_db)
# ):
#     """
#     Get full details for a single occupation.
#     Includes breadcrumb path through the hierarchy.
#     Called when user clicks an occupation in the sidebar.
#     """
#     occupation = get_occupation_detail(db, occupation_id)

#     if not occupation:
#         raise HTTPException(
#             status_code=404,
#             detail=f"Occupation {occupation_id} not found"
#         )

#     return occupation

"""
routers/occupations.py
======================
Endpoints the frontend calls for sidebar + hierarchy dropdowns.

GET /api/occupations/major-groups
GET /api/occupations/sub-major-groups?major_group_id=
GET /api/occupations/minor-groups?sub_major_group_id=
GET /api/occupations/list?limit=500&major_group_id=&sub_major_group_id=&minor_group_id=
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional

from app.database import get_db
from app.models.osca import (
    OscaMajorGroup, OscaSubMajorGroup, OscaMinorGroup,
    OscaUnitGroup, OscaOccupation
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
    #limit:              int = Query(2000, le=2000),
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

    return [
        {
            "id":          r.id,
            "title":       r.title,
            "skill_level": r.skill_level,
            "skill_count": r.skill_count,
            "unit_group_id": r.unit_group_id,
            "skill_ids":   [str(s) for s in r.skill_ids] if r.skill_ids else [], # Convert to strings for easier JS searching
            "has_data":    r.skill_count > 0,
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