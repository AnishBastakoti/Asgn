from __future__ import annotations          # enables forward refs without quotes
from sqlalchemy import Integer, String, Boolean, ForeignKey, BigInteger, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from typing import TYPE_CHECKING, Optional
from datetime import datetime               # ← import datetime CLASS
from app.database import Base

if TYPE_CHECKING:
    from app.models.occupations import OscaOccupation
    from app.models.skills import EscoSkill


class JobPostLog(Base):
    """
    Raw job posting scraped from the web.
    AI processing stats (as of last pipeline run)
    """

    __tablename__ = "job_post_logs"

    id:               Mapped[int]            = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_name:     Mapped[Optional[str]]  = mapped_column(String(255))
    job_title:        Mapped[Optional[str]]  = mapped_column(String(255))
    content_hash:     Mapped[Optional[str]]  = mapped_column(String(64), unique=True)
    city:             Mapped[Optional[str]]  = mapped_column(String(255))
    raw_description:  Mapped[Optional[str]]  = mapped_column(Text)
    json_file_path:   Mapped[Optional[str]]  = mapped_column(String(255))
    processed_by_ai:  Mapped[bool]           = mapped_column(Boolean, nullable=False, default=False)
    ingested_at:      Mapped[Optional[datetime]]

    # FK to osca_occupations — set by AI classification pipeline
    occupation_id:    Mapped[Optional[int]]  = mapped_column(Integer, ForeignKey("osca_occupations.id"))
    # FK to batch_job_execution — which pipeline run produced this record
    job_execution_id: Mapped[Optional[int]]  = mapped_column(BigInteger, ForeignKey("batch_job_execution.job_execution_id"))

    # ── Relationships ─────────────────────────────────────────────────────────
    occupation:   Mapped[Optional["OscaOccupation"]] = relationship(
        "OscaOccupation",
        back_populates="job_post_logs",
    )
    post_skills:  Mapped[list["JobPostSkill"]] = relationship(
        "JobPostSkill",
        back_populates="job_post",
        lazy="select",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<JobPostLog id={self.id} title={self.job_title!r} company={self.company_name!r}>"


class JobPostSkill(Base):
    """
    Join table: job_post_logs ↔ esco_skills  (many-to-many).
    Each row records that a particular skill was extracted from a job posting.
    """

    __tablename__ = "job_post_skills"

    id:          Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_post_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("job_post_logs.id"), nullable=False)
    skill_id:    Mapped[int] = mapped_column(BigInteger, ForeignKey("esco_skills.id"),   nullable=False)

    # ── Relationships ─────────────────────────────────────────────────────────
    job_post: Mapped["JobPostLog"] = relationship("JobPostLog", back_populates="post_skills")
    skill:    Mapped["EscoSkill"]  = relationship("EscoSkill",  back_populates="job_post_skills")

    def __repr__(self) -> str:
        return f"<JobPostSkill post_id={self.job_post_id} skill_id={self.skill_id}>"