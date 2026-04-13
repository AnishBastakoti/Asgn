from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, Integer
from app.database import Base


class ApiKey(Base):
    __tablename__ = "api_keys"

    id          = Column(Integer, primary_key=True)
    key_hash    = Column(String(64), unique=True, nullable=False)
    name        = Column(String(100), nullable=False)
    owner_email = Column(String(255), nullable=False)
    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=datetime.utcnow)
    expires_at  = Column(DateTime, nullable=True)
    rate_limit  = Column(Integer, default=1000)