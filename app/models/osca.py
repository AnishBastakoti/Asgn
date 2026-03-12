# Matches exact database schema from ERD

from sqlalchemy import Boolean, Column, Float, Integer, String, Text, ForeignKey, BigInteger
from sqlalchemy.orm import relationship
from app.database import Base


class OscaMajorGroup(Base):
    __tablename__ = "osca_major_groups"

    id             = Column(Integer, primary_key=True)
    title          = Column(String, nullable=False)
    lead_statement = Column(Text, nullable=True)

    sub_major_groups = relationship(
        "OscaSubMajorGroup",
        back_populates="major_group",
        lazy="select"
    )

    def __repr__(self):
        return f"<MajorGroup {self.id}: {self.title}>"


class OscaSubMajorGroup(Base):
    __tablename__ = "osca_sub_major_groups"

    id             = Column(Integer, primary_key=True)
    title          = Column(String, nullable=False)
    major_group_id = Column(Integer, ForeignKey("osca_major_groups.id"))
    lead_statement = Column(Text, nullable=True)

    major_group  = relationship("OscaMajorGroup", back_populates="sub_major_groups")
    minor_groups = relationship("OscaMinorGroup", back_populates="sub_major_group", lazy="select")

    def __repr__(self):
        return f"<SubMajorGroup {self.id}: {self.title}>"


class OscaMinorGroup(Base):
    __tablename__ = "osca_minor_groups"

    id                 = Column(Integer, primary_key=True)
    title              = Column(String, nullable=False)
    sub_major_group_id = Column(Integer, ForeignKey("osca_sub_major_groups.id"))
    lead_statement     = Column(Text, nullable=True)

    sub_major_group = relationship("OscaSubMajorGroup", back_populates="minor_groups")
    unit_groups     = relationship("OscaUnitGroup", back_populates="minor_group", lazy="select")

    def __repr__(self):
        return f"<MinorGroup {self.id}: {self.title}>"


class OscaUnitGroup(Base):
    __tablename__ = "osca_unit_groups"

    id             = Column(Integer, primary_key=True)
    title          = Column(String, nullable=False)
    minor_group_id = Column(Integer, ForeignKey("osca_minor_groups.id"))
    lead_statement = Column(Text, nullable=True)

    minor_group = relationship("OscaMinorGroup", back_populates="unit_groups")
    occupations = relationship("OscaOccupation", back_populates="unit_group", lazy="select")

    def __repr__(self):
        return f"<UnitGroup {self.id}: {self.title}>"


class OscaOccupation(Base):
    __tablename__ = "osca_occupations"

    id                    = Column(Integer, primary_key=True)
    principal_title       = Column(String, nullable=False)
    skill_level           = Column(Integer, nullable=True)
    unit_group_id         = Column(Integer, ForeignKey("osca_unit_groups.id"))
    lead_statement        = Column(Text, nullable=True)
      
    # added new tables from new ERD:
    content_hash          = Column(String,  nullable=True)
    embedding             = Column(Text,    nullable=True)
    caveats               = Column(Text,    nullable=True)
    licensing             = Column(Text,    nullable=True)
    nec_category          = Column(String,  nullable=True)
    skill_attributes      = Column(Text,    nullable=True)
    specialisations       = Column(Text,    nullable=True)
    main_tasks            = Column(Text,    nullable=True)
    information_card      = Column(Text,    nullable=True)

    unit_group         = relationship("OscaUnitGroup", back_populates="occupations")
    alternative_titles = relationship("OscaAlternativeTitle", back_populates="occupation", lazy="select")
    job_post_logs      = relationship("JobPostLog", back_populates="occupation", lazy="select")
    occupation_skills  = relationship("OscaOccupationSkill", back_populates="occupation", lazy="select")

    def __repr__(self):
        return f"<Occupation {self.id}: {self.principal_title}>"


class OscaAlternativeTitle(Base):
    __tablename__ = "osca_alternative_titles"

    id                = Column(BigInteger, primary_key=True)
    title             = Column(String, nullable=True)
    is_specialisation = Column(Boolean, nullable=True)
    # status            = Column(String, nullable=True)
    occupation_id     = Column(BigInteger, ForeignKey("osca_occupations.id"))

    occupation = relationship("OscaOccupation", back_populates="alternative_titles")

    def __repr__(self):
        return f"<AltTitle: {self.title}>"