# These tables are the CORE of the dashboard — they power every insight about skill demand and trends.
# mention_count drives every chart and insight about skill demand.

''' i didnot work on vector embedding for now but
 i have added the content_hash field in esco_skill table which 
 will be used to check if the skill has changed or not and 
 if it has changed then we can update the embedding for that skill.

 '''
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, BigInteger
from sqlalchemy.orm import relationship
from app.database import Base


class EscoSkill(Base):
    __tablename__ = "esco_skills"

    id            = Column(BigInteger, primary_key=True)
    concept_uri   = Column(String, nullable=True)
    preferred_label = Column(String, nullable=False)# The main name of the skill, used for display and matching
    skill_type    = Column(String, nullable=True)
    content_hash  = Column(String, nullable=True) 

    #-- new columns 
    alt_labels   = Column(Text,   nullable=True)
    description  = Column(Text,   nullable=True)
    embedding    = Column(Text,    nullable=True)
    skill_card   = Column(String, nullable=True)
    created_at   = Column(String, nullable=True)
    #embedding     = Column(String, nullable=True)  # Store as JSON string or base64-encoded vector

    #hash of the skill content, used to detect duplicates
    #this is a fingerprinting technique for data
    

    # Relationships
    occupation_skills = relationship(
        "OscaOccupationSkill",
        back_populates="skill",
        lazy="select"
    )
    job_post_skills = relationship(
        "JobPostSkill",
        back_populates="skill",
        lazy="select"
    )
    snapshots = relationship(
        "OscaOccupationSkillSnapshot",
        back_populates="skill",
        lazy="select"
    )

    def __repr__(self):
        return f"<EscoSkill {self.id}: {self.preferred_label}>"


class OscaOccupationSkill(Base):
    __tablename__ = "osca_occupation_skills"

    id            = Column(BigInteger, primary_key=True)
    occupation_id = Column(Integer, ForeignKey("osca_occupations.id"))
    skill_id      = Column(BigInteger, ForeignKey("esco_skills.id"))
    mention_count = Column(Integer, nullable=False, default=0) # bar chart, every ranking, every trend line from here 
    first_seen_at = Column(DateTime, nullable=True)
    last_seen_at  = Column(DateTime, nullable=True)

    # Navigate to related objects
    occupation = relationship("OscaOccupation", back_populates="occupation_skills")
    skill      = relationship("EscoSkill", back_populates="occupation_skills")

    def __repr__(self):
        return f"<OccupationSkill occ={self.occupation_id} skill={self.skill_id} count={self.mention_count}>"


class OscaOccupationSkillSnapshot(Base):
    __tablename__ = "osca_occupation_skill_snapshots"

    id               = Column(BigInteger, primary_key=True)
    occupation_id    = Column(BigInteger, ForeignKey("osca_occupations.id"))
    skill_id         = Column(BigInteger, ForeignKey("esco_skills.id"))
    job_execution_id = Column(BigInteger, nullable=True)
    mention_count    = Column(Integer, nullable=False, default=0) # Every bar chart, every ranking, every trend line comes from here
    snapshot_date    = Column(DateTime, nullable=True)

    occupation = relationship("OscaOccupation", lazy="select")
    skill      = relationship("EscoSkill", back_populates="snapshots")

    def __repr__(self):
        return f"<Snapshot occ={self.occupation_id} skill={self.skill_id} date={self.snapshot_date}>"


class SkillpulseCityOccupationDemand(Base):
    __tablename__ = "skillpulse_city_occupation_demand"

    id               = Column(Integer, primary_key=True)
    city             = Column(String,  nullable=False)
    computed_at      = Column(String,  nullable=True)
    job_count        = Column(Integer, nullable=True)
    occupation_id    = Column(Integer, nullable=True)
    occupation_title = Column(String,  nullable=True)
