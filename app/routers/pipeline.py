from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.pipeline_service import get_pipeline_executions

router = APIRouter(prefix="/api/pipeline", tags=["Pipeline"])

@router.get("/executions")
def pipeline_executions(limit: int = 20, db: Session = Depends(get_db)):
    """Recent Spring Batch pipeline executions with duration and error detail."""
    return get_pipeline_executions(db, limit)