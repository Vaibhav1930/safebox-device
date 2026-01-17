import requests
import time
from core.logger import setup_logger, with_request_id

heartbeat_logger = setup_logger("heartbeat", "network.log")

HEARTBEAT_URL = "http://example.com/device/heartbeat"  # STUB
TIMEOUT = 3

def send_heartbeat(payload):
    try:
        response = requests.post(
            HEARTBEAT_URL,
            json=payload,
            timeout=TIMEOUT
        )
        heartbeat_logger.info(
            f"heartbeat sent status={response.status_code}",
            extra=with_request_id()
        )
    except Exception as e:
        heartbeat_logger.info(
            f"heartbeat failed reason={str(e)}",
            extra=with_request_id()
        )
