import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import uuid
from typing import Dict

# -------------------------------------------------
# Configuration
# -------------------------------------------------
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "logs"
os.makedirs(LOG_DIR, exist_ok=True)

DEFAULT_LOG_FORMAT = (
    "%(asctime)s | %(levelname)s | %(request_id)s | %(name)s | %(message)s"
)

# -------------------------------------------------
# Formatter
# -------------------------------------------------
class SafeFormatter(logging.Formatter):
    """
    Ensures that request_id is always present in log records,
    even if the caller does not supply it.
    """
    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return super().format(record)

# -------------------------------------------------
# Core Logger Factory (Primary API)
# -------------------------------------------------
def get_logger(name: str) -> logging.Logger:
    """
    Primary logger factory used across the codebase.
    Creates a rotating file + stdout logger scoped by name.
    Log file: /opt/safebox/logs/{name}.log
    Log level: controlled via SAFEBOX_LOG_LEVEL env var (default: INFO)
    """
    logger = logging.getLogger(name)

    
    level = os.getenv("SAFEBOX_LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, level, logging.INFO))

    # Prevent duplicate handlers on repeated imports
    if logger.handlers:
        return logger

    formatter = SafeFormatter(DEFAULT_LOG_FORMAT)

    # Rotating file handler
    fh = RotatingFileHandler(
        filename=f"{LOG_DIR}/{name}.log",
        maxBytes=1_000_000,  # 1 MB
        backupCount=3
    )
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(formatter)
    logger.addHandler(sh)

    logger.propagate = False
    return logger

# -------------------------------------------------
# Compatibility Layer (Legacy Imports)
# -------------------------------------------------
def setup_logger(name: str, filename: str) -> logging.Logger:
    """
    Backward-compatible wrapper for legacy code.
    - `filename` is accepted for API compatibility
    - Internally delegates to get_logger()
    """
    return get_logger(name)

def with_request_id() -> Dict[str, str]:
    """
    Generates a request_id payload for structured logging.
    Usage:
        logger.info("message", extra=with_request_id())
    """
    return {"request_id": str(uuid.uuid4())}
