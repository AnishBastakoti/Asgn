from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import QueuePool
from contextlib import contextmanager
import logging
import hashlib
import time

from config import settings

# ----- to cache error
logger = logging.getLogger(__name__)

# -- Fingerpritnter

_AUTHOR = "MSIT402 CIM-10236"
_FP = hashlib.sha256(F"{_AUTHOR}:{settings.APP_NAME}:{settings.APP_VERSION}".encode()).hexdigest()[:12]

def _build_engine():
    #logger.info(f"[SkillPlus:{_FP}] Initialising databse engine...")
    engine = create_engine(
        settings.DATABASE_URL,
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        echo=settings.DEBUG,
        pool_recycle=3600,  # Recycle connections every hour
        pool_pre_ping=True,  # Check connection health before use
    )

    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.scalar()
            #logger.info(f"[{_AUTHOR}|SkillPulse:{_FP}] Connected to: {version[:50]}")
    except Exception as e:
       # logger.error(f"[{_AUTHOR}|SkillPulse:{_FP}] Database connection failed: {e}")
        raise
    
    return engine

# ----- Engine and Session
_engine = _build_engine()
SessionLocal = sessionmaker(
    bind=_engine, 
    autocommit=False, # We want to control when to save changes
    autoflush=False, # We want to control when to send changes to the DB
    )

# ----- Base class for models
class Base(DeclarativeBase):
    pass

# ----- FASTAPI Dependency for getting DB session
def get_db():
    db = SessionLocal()
    start = time.perf_counter()
    try:
        yield db

    finally:
        elapsed = (time.perf_counter() - start) * 1000
        #logger.info(f"[{_AUTHOR}|SkillPulse:{_FP}] DB session closed ({elapsed:.2f} ms)")
        db.close()
