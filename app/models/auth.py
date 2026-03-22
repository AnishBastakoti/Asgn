from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from app.database import Base


class SystemRole(Base):
    __tablename__ = "system_role"

    id           = Column(Integer, primary_key=True)
    name         = Column(String, nullable=False, unique=True)   # e.g. "admin", "analyst"
    display_name = Column(String, nullable=True)
    description  = Column(String, nullable=True)

    # Relationships
    users      = relationship("SystemEndUser", back_populates="role")
    role_pages = relationship("SystemRolePage", back_populates="role")


class SystemPage(Base):
    __tablename__ = "system_page"

    id          = Column(Integer, primary_key=True)
    page_icon   = Column(String, nullable=True)
    page_title  = Column(String, nullable=True)
    route_path  = Column(String, nullable=True)   

    # Relationships
    role_pages = relationship("SystemRolePage", back_populates="page")


class SystemRolePage(Base):
    """Junction table — which roles can access which pages."""
    __tablename__ = "system_role_page"

    id      = Column(Integer, primary_key=True)
    role_id = Column(Integer, ForeignKey("system_role.id"))
    page_id = Column(Integer, ForeignKey("system_page.id"))

    role = relationship("SystemRole", back_populates="role_pages")
    page = relationship("SystemPage", back_populates="role_pages")


class SystemEndUser(Base):
    __tablename__ = "system_end_user"

    id            = Column(Integer, primary_key=True)
    email         = Column(String, nullable=False, unique=True)
    password_hash = Column(String, nullable=False)
    enabled       = Column(Boolean, default=True, nullable=False)
    role_id       = Column(Integer, ForeignKey("system_role.id"), nullable=True)
    created_at    = Column(DateTime, nullable=True)

    # Relationships
    role = relationship("SystemRole", back_populates="users")

    def __repr__(self):
        return f"<SystemEndUser email={self.email!r} role={self.role_id}>"