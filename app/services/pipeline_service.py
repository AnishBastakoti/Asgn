import logging
import hashlib
from sqlalchemy.orm import Session
from app.models.pipeline import BatchJobExecution
from config import settings

logger = logging.getLogger(__name__)

_FP = hashlib.sha256(
    f"{settings.AUTHOR_KEY}:{settings.APP_NAME}:{settings.APP_VERSION}".encode()
).hexdigest()[:12]

def get_last_pipeline_run(db: Session) -> dict | None:
    """Return the most recent COMPLETED pipeline execution timestamp."""
    try:
        row = (
            db.query(BatchJobExecution.end_time, BatchJobExecution.status)
            .filter(BatchJobExecution.status == "COMPLETED")
            .order_by(BatchJobExecution.end_time.desc())
            .first()
        )
        if not row or not row.end_time:
            return None
        return {
            "last_run": row.end_time.isoformat(),
            "status":   row.status,
        }
    except Exception as e:
        logger.error(f"[MSIT402|SP] get_last_pipeline_run failed: {e}")
        return None