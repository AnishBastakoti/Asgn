import logging
from sqlalchemy.orm import Session
from app.models.pipeline import BatchJobExecution, BatchJobInstance

logger = logging.getLogger(__name__)

def get_pipeline_executions(db: Session, limit: int = 20) -> list[dict]:
    try:
        rows = (
            db.query(BatchJobExecution, BatchJobInstance.job_name)
            .join(BatchJobInstance,
                  BatchJobInstance.job_instance_id == BatchJobExecution.job_instance_id)
            .order_by(BatchJobExecution.job_execution_id.desc())
            .limit(limit)
            .all()
        )
        results = []
        for exec_, job_name in rows:
            duration = None
            if exec_.start_time and exec_.end_time:
                duration = int((exec_.end_time - exec_.start_time).total_seconds())
            results.append({
                "job_execution_id": exec_.job_execution_id,
                "job_instance_id":  exec_.job_instance_id,
                "job_name":         job_name,
                "start_time":       exec_.start_time.isoformat() if exec_.start_time else None,
                "end_time":         exec_.end_time.isoformat()   if exec_.end_time   else None,
                "status":           exec_.status,
                "exit_code":        exec_.exit_code,
                "exit_message":     exec_.exit_message,
                "duration_seconds": duration,
            })
        return results
    except Exception as e:
        logger.error(f"[MSIT402|SP] get_pipeline_executions failed: {e}")
        return []