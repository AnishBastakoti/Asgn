import logging
import sys
import os
from logging.handlers import RotatingFileHandler
from config import settings


def setup_logging() -> None:
    """
    Call once at startup (in main.py lifespan).
    Sets format, level, and handlers for the whole application.
    """
    log_level = logging.DEBUG if settings.DEBUG else logging.INFO

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(log_level)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(console_handler)

    # File handler (Industry standard for persistence)
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # Use RotatingFileHandler to prevent disk exhaustion
    file_handler = RotatingFileHandler(
        filename=os.path.join(log_dir, "skillpulse.log"),
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,              # Keep 5 old log files
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(log_level)
    root_logger.addHandler(file_handler)

    # Quieten noisy libraries
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.DEBUG else logging.WARNING
    )
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    
    logging.info(f"Logging initialized. Level: {logging.getLevelName(log_level)} | Console: OK | File: {file_handler.baseFilename}")


def get_logger(name: str) -> logging.Logger:
    """
    Usage in any module:
        from app.logger import get_logger
        logger = get_logger(__name__)
    """
    return logging.getLogger(name)