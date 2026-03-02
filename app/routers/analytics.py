from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.analytics_service import (
    get_hot_skills,
    get_shadow_skills,
    get_skill_decay
)

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])


# ── Schemas ──────────────────────────────────────────────
class HotSkillResponse(BaseModel):
    skill_name:     str
    total_mentions: int
    share_pct:      float

class ShadowSkillResponse(BaseModel):
    skill_name: str

class SkillDecayResponse(BaseModel):
    skill_name:       str
    past_mentions:    int
    current_mentions: int
    decline:          int
    decline_pct:      float


# ── Endpoints ────────────────────────────────────────────

# 1. HOT SKILLS — no occupation filter, across all job posts
@router.get("/hot-skills", response_model=List[HotSkillResponse])
def hot_skills(days: int = 30, db: Session = Depends(get_db)):
    """Top skills across all job posts in the last N days."""
    return get_hot_skills(db, days)


# 2. SHADOW SKILLS — FIX: was osca_code:str, real PK is occupation_id:int
@router.get("/shadow-skills/{occupation_id}", response_model=List[ShadowSkillResponse])
def shadow_skills(occupation_id: int, db: Session = Depends(get_db)):
    """
    Skills appearing in job postings for this occupation
    that are not in the official OSCA skill mapping.
    """
    return get_shadow_skills(db, occupation_id)


# 3. SKILL DECAY — FIX: was osca_code:str, real PK is occupation_id:int
@router.get("/skill-decay/{occupation_id}", response_model=List[SkillDecayResponse])
def skill_decay(occupation_id: int, db: Session = Depends(get_db)):
    """
    Skills with significant demand decline for this occupation,
    comparing earliest vs most recent snapshot batch.
    """
    return get_skill_decay(db, occupation_id)