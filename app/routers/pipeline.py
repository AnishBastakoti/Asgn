from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.auth_deps import require_admin, require_auth
from app.database import get_db
from app.services.pipeline_service import get_last_pipeline_run


router = APIRouter(prefix="/api/pipeline", tags=["Pipeline"])


# Public to all authenticated users — just shows pipeline status in sidebar
@router.get("/last-run")
def pipeline_last_run(db: Session = Depends(get_db), user = Depends(require_admin)):
    """Returns the timestamp of the most recent completed pipeline run."""
    result = get_last_pipeline_run(db)
    if not result:
        return {"last_run": None, "status": "UNKNOWN"}
    return result


# Keep require_admin only on sensitive/destructive routes
@router.post("/trigger")
def trigger_pipeline(
    admin = Depends(require_admin)      
):
    raise HTTPException(status_code=501, detail="Not yet implemented")
    
@router.delete("/clear-runs")
def clear_pipeline_runs(
    admin = Depends(require_admin)      
):
    
    raise HTTPException(status_code=501, detail="Not yet implemented")