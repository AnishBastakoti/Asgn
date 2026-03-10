from sqlalchemy import Column, BigInteger, String, DateTime
from app.database import Base

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