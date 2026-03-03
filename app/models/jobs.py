from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, BigInteger, DateTime
from sqlalchemy.orm import relationship
from app.database import Base
import datetime

class JobPostLog(Base): #scraped from  web based on ERD.
    __tablename__ = "job_post_logs"

    id               = Column(Integer, primary_key=True)
    company_name     = Column(String, nullable=True)
    job_title        = Column(String, nullable=True)
    content_hash     = Column(String, nullable=True)
    city             = Column(String, nullable=True)
    raw_description   = Column(String, nullable=True) # the original job description text as scraped
    json_file_path     = Column(String, nullable=True) # where is the raw json file stored
    processed_by_ai  = Column(Boolean, nullable=True, default=False)

    """
     for now I have set it to true as production
    1. false	4545	98.83 
    2. true	    54	    1.17 -only 54 jobs have been processed by AI.
    """
    occupation_id    = Column(Integer, ForeignKey("osca_occupations.id"), nullable=True)
    job_execution_id = Column(BigInteger, nullable=True) # which pipeline run created this record?

    # Navigate to related objects
    occupation  = relationship(
        "OscaOccupation",
        back_populates="job_post_logs"
    )
    post_skills = relationship(
        "JobPostSkill",
        back_populates="job_post",
        lazy="select"
    )

    def __repr__(self): # !r means raw string.
        return f"<JobPost {self.id}: {self.job_title!r} @ {self.company_name!r}>"


class JobPostSkill(Base):
    """
    job posting to the skill extraction
    many to many relationship
    """
    __tablename__ = "job_post_skills"

    id          = Column(Integer, primary_key=True)
    job_post_id = Column(Integer, ForeignKey("job_post_logs.id"), nullable=True)
    skill_id    = Column(Integer, ForeignKey("esco_skills.id"), nullable=True)

    # Navigate to related objects
    job_post = relationship("JobPostLog", back_populates="post_skills")
    skill    = relationship("EscoSkill", back_populates="job_post_skills")

    def __repr__(self):
        return f"<JobPostSkill post={self.job_post_id!r} skill={self.skill_id!r}>"
