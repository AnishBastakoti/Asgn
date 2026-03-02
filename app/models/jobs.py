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
    occupation_id    = Column(Integer, ForeignKey("osca_occupations.id"), nullable=True) #ocsa occupation was this posting classified as? this is the result of classification, not the source of truth. we can use this to track how many job posts are classified into each occupation, and how it changes over time. we can also use this to track the accuracy of our classification model by comparing it with human labels on a sample of job posts.
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

class JobPost(Base):
    __tablename__ = "job_posts"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    occupation_id = Column(Integer, ForeignKey("occupations.id"))
    company_id = Column(Integer, ForeignKey("companies.id"))
    city_id = Column(Integer, ForeignKey("cities.id"))
    posted_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    # Relationships
    occupation = relationship("Occupation")
    company = relationship("Company", back_populates="job_posts")
    city = relationship("City")
    skills = relationship("Skill", secondary="job_post_skills")

    def __repr__(self):
        return f"<JobPost {self.id}: {self.title!r} @ {self.company.name!r}>"

class Company(Base):
    __tablename__ = "companies"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    job_posts = relationship("JobPost", back_populates="company")

    def __repr__(self):
        return f"<Company {self.id}: {self.name!r}>"

class City(Base):
    __tablename__ = "cities"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    state = Column(String) # e.g., "NSW", "VIC"
    job_posts = relationship("JobPost", back_populates="city")  
    def __repr__(self):
        return f"<City {self.id}: {self.name!r}, {self.state!r}>"   