import logging
from logging.handlers import RotatingFileHandler
import uuid
import os

LOG_DIR = "/opt/safebox/logs"
os.makedirs(LOG_DIR, exist_ok=True)

def setup_logger(name, filename):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Prevent duplicate handlers on re-run
    if logger.handlers:
        return logger

    handler = RotatingFileHandler(
        f"{LOG_DIR}/{filename}",
        maxBytes=1_000_000,   # 1 MB
        backupCount=3
    )

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(request_id)s | %(message)s"
    )

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger

def with_request_id():
    return {"request_id": str(uuid.uuid4())}
