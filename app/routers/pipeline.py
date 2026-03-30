from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.pipeline_service import get_last_pipeline_run

router = APIRouter(prefix="/api/pipeline", tags=["Pipeline"])

@router.get("/last-run")
def pipeline_last_run(db: Session = Depends(get_db)):
    """Returns the timestamp of the most recent completed pipeline run."""
    result = get_last_pipeline_run(db)
    if not result:
        return {"last_run": None, "status": "UNKNOWN"}
    return result