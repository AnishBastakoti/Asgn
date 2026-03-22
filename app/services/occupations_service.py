import logging
import hashlib
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import String, func

from app.models.osca import (
    OscaMajorGroup,
    OscaSubMajorGroup,
    OscaMinorGroup,
    OscaUnitGroup,
    OscaOccupation,
    OscaAlternativeTitle
)
from app.models.skills import OscaOccupationSkill

logger = logging.getLogger(__name__)

# --- Authorship Fingerprint
_AUTHOR_KEY = "MSIT402 CIM-10236" 
_SIGNATURE  = int(hashlib.md5(_AUTHOR_KEY.encode()).hexdigest(), 16) % 1000


# ── Hierarchy Functions

def get_major_groups(db: Session) -> list[dict]:
    """
    Get all OSCA major groups.
    """
    groups = (
        db.query(
            OscaMajorGroup.id,
            OscaMajorGroup.title,
            func.count(OscaOccupation.id).label("occupation_count")
        )
        .outerjoin(OscaSubMajorGroup, OscaSubMajorGroup.major_group_id == OscaMajorGroup.id)
        .outerjoin(OscaMinorGroup, OscaMinorGroup.sub_major_group_id == OscaSubMajorGroup.id)
        .outerjoin(OscaUnitGroup, OscaUnitGroup.minor_group_id == OscaMinorGroup.id)
        .outerjoin(OscaOccupation, OscaOccupation.unit_group_id == OscaUnitGroup.id)
        .group_by(OscaMajorGroup.id, OscaMajorGroup.title)
        .order_by(OscaMajorGroup.id)
        .all()
    )

    return [
        {
            "id":               g.id,
            "title":            g.title,
            "occupation_count": g.occupation_count
        }
        for g in groups
    ]


def get_sub_major_groups(
    db: Session,
    major_group_id: Optional[int] = None
) -> list[dict]:
    """
    Get sub-major groups, optionally filtered by major group.
    """
    query = db.query(
        OscaSubMajorGroup.id,
        OscaSubMajorGroup.title,
        OscaSubMajorGroup.major_group_id
    )

    if major_group_id:
        query = query.filter(
            OscaSubMajorGroup.major_group_id == major_group_id
        )

    groups = query.order_by(OscaSubMajorGroup.id).all()

    return [
        {
            "id":             g.id,
            "title":          g.title,
            "major_group_id": g.major_group_id
        }
        for g in groups
    ]


def get_minor_groups(
    db: Session,
    sub_major_group_id: Optional[int] = None
) -> list[dict]:
    """
    Get minor groups, optionally filtered by sub-major group.
    """
    query = db.query(
        OscaMinorGroup.id,
        OscaMinorGroup.title,
        OscaMinorGroup.sub_major_group_id
    )

    if sub_major_group_id:
        query = query.filter(
            OscaMinorGroup.sub_major_group_id == sub_major_group_id
        )

    groups = query.order_by(OscaMinorGroup.id).all()

    return [
        {
            "id":                  g.id,
            "title":               g.title,
            "sub_major_group_id":  g.sub_major_group_id
        }
        for g in groups
    ]


def get_occupations(
    db: Session,
    unit_group_id:  Optional[int] = None,
    search:         Optional[str] = None,
    limit:          int = 100
) -> list[dict]:
    """
    Get occupations with optional filtering and search.
    """
    query = db.query(
        OscaOccupation.id,
        OscaOccupation.principal_title,
        OscaOccupation.skill_level,
        OscaOccupation.unit_group_id,
        func.count(OscaOccupationSkill.id).label("skill_count")
    ).outerjoin(
        OscaOccupationSkill,
        OscaOccupationSkill.occupation_id == OscaOccupation.id
    )

    if unit_group_id:
        query = query.filter(OscaOccupation.unit_group_id == unit_group_id)

    if search:
        # Case insensitive search
        query = query.filter(
            OscaOccupation.principal_title.ilike(f"%{search}%")|
            (OscaOccupation.id.cast(String).ilike(f"%{search}%"))
        )

    occupations = (
        query
        .group_by(
            OscaOccupation.id,
            OscaOccupation.principal_title,
            OscaOccupation.skill_level,
            OscaOccupation.unit_group_id
        )
        .order_by(OscaOccupation.principal_title)
        .limit(limit)
        .all()
    )

    return [
        {
            "id":              o.id,
            "title":           o.principal_title,
            "skill_level":     o.skill_level,
            "unit_group_id":   o.unit_group_id,
            "skill_count":     o.skill_count,
            "has_data":        o.skill_count > 0  #on UI it shows to grey out empty ones
        }
        for o in occupations
    ]


def get_occupation_detail(
    db: Session,
    occupation_id: int
) -> Optional[dict]:
    """
    Get full details for a single occupation including breadcrumb path.
    """
    occupation = (
        db.query(OscaOccupation)
        .filter(OscaOccupation.id == occupation_id)
        .first()
    )

    if not occupation:
        return None

    # the hierarchy to build breadcrumb
    unit_group    = db.query(OscaUnitGroup).filter(
                        OscaUnitGroup.id == occupation.unit_group_id
                    ).first()

    minor_group   = db.query(OscaMinorGroup).filter(
                        OscaMinorGroup.id == unit_group.minor_group_id
                    ).first() if unit_group else None

    sub_major     = db.query(OscaSubMajorGroup).filter(
                        OscaSubMajorGroup.id == minor_group.sub_major_group_id
                    ).first() if minor_group else None

    major         = db.query(OscaMajorGroup).filter(
                        OscaMajorGroup.id == sub_major.major_group_id
                    ).first() if sub_major else None

    return {
        "id":            occupation.id,
        "title":         occupation.principal_title,
        "skill_level":   occupation.skill_level,
        "lead_statement": occupation.lead_statement,
        "caveats":           occupation.caveats,
        "licensing":         occupation.licensing,
        "nec_category":      occupation.nec_category,
        "skill_attributes":  occupation.skill_attributes,
        "specialisations":   occupation.specialisations,
        "main_tasks":        occupation.main_tasks,
        "information_card":  occupation.information_card,
        # content_hash, embedding excluded for now
        "breadcrumb": [
            {"level": "major",      "title": major.title        if major       else None},
            {"level": "sub_major",  "title": sub_major.title    if sub_major   else None},
            {"level": "minor",      "title": minor_group.title  if minor_group else None},
            {"level": "unit",       "title": unit_group.title   if unit_group  else None},
            {"level": "occupation", "title": occupation.principal_title},
        ],
        "signature": f"SP-{_SIGNATURE:03d}"
    }