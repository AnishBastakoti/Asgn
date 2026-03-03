from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker, DeclarativeBase
from sqlalchemy.pool import QueuePool
from contextlib import contextmanager
import logging
import hashlib
import time

from config import settings  # ← only import, no redefinition

logger = logging.getLogger(__name__)

_AUTHOR = "MSIT402 CIM-10236"
_FP = hashlib.sha256(
    f"{_AUTHOR}:{settings.APP_NAME}:{settings.APP_VERSION}".encode()
).hexdigest()[:12]


def _build_engine():
    engine = create_engine(
        settings.DATABASE_URL,
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        echo=settings.DEBUG,
        pool_recycle=3600,
        pool_pre_ping=True
    )
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version()")).scalar()
            logger.info(f"[{_AUTHOR}|SkillPulse:{_FP}] Connected to: {version[:50]}")
    except Exception as e:
        logger.error(f"[{_AUTHOR}|SkillPulse:{_FP}] Database connection failed: {e}")
        raise
    return engine


_engine = _build_engine()

SessionLocal = sessionmaker(
    bind=_engine,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    start = time.perf_counter()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.debug(f"[{_AUTHOR}|SkillPulse:{_FP}] session closed ({elapsed_ms:.1f}ms)")
        db.close()


@contextmanager
def get_db_context():
    """Use outside FastAPI request context — scripts, pipeline, etc."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()