from sqlalchemy import Column, BigInteger, String, DateTime, Integer
from app.database import Base

class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id              = Column(Integer, primary_key=True)
    run_date        = Column(DateTime(timezone=True), nullable=False)
    total_jobs      = Column(Integer, nullable=False)   # ← the key field
    status          = Column(String, default="completed")

class BatchJobInstance(Base):
    __tablename__ = "batch_job_instance"
    job_instance_id = Column(BigInteger, primary_key=True)
    version         = Column(BigInteger)
    job_name        = Column(String(100))
    job_key         = Column(String(32))

class BatchJobExecution(Base):
    __tablename__ = "batch_job_execution"
    job_execution_id = Column(BigInteger, primary_key=True)
    version          = Column(BigInteger)
    job_instance_id  = Column(BigInteger)
    create_time      = Column(DateTime)
    start_time       = Column(DateTime)
    end_time         = Column(DateTime)
    status           = Column(String(10))
    exit_code        = Column(String(2500))
    exit_message     = Column(String(2500))
    last_updated     = Column(DateTime)