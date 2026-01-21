import logging
from logging.handlers import RotatingFileHandler
import os

LOG_DIR = "/opt/safebox/logs"
os.makedirs(LOG_DIR, exist_ok=True)


class SafeFormatter(logging.Formatter):
    def format(self, record):
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return super().format(record)


def get_logger(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    handler = RotatingFileHandler(
        f"{LOG_DIR}/{name}.log",
        maxBytes=1_000_000,
        backupCount=3
    )

    formatter = SafeFormatter(
        "%(asctime)s | %(levelname)s | %(request_id)s | %(message)s"
    )

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger
