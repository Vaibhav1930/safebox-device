import requests
from core.logger import get_logger

log = get_logger("heartbeat")

HEARTBEAT_URL = "http://127.0.0.1:8000/heartbeat"
TIMEOUT = 3


def send_heartbeat(payload: dict) -> bool:
    """
    Send a single heartbeat payload to the local cloud API.

    Returns:
        True if heartbeat succeeded, False otherwise
    """
    try:
        r = requests.post(
            HEARTBEAT_URL,
            json=payload,
            timeout=TIMEOUT
        )
        log.info(f"heartbeat sent status={r.status_code}")
        return r.ok
    except Exception as e:
        log.warning(f"heartbeat failed: {e}")
        return False


def start_heartbeat(source: str = "wake") -> None:
    """
    Backward-compatible wrapper used by wake/audio services.
    This keeps the API stable and prevents future breakage.
    """
    send_heartbeat({
        "source": source,
        "status": "alive"
    })
