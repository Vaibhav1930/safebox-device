import requests
import time
import threading
from core.logger import get_logger

log = get_logger("heartbeat")

HEARTBEAT_URL = "http://127.0.0.1:8000/heartbeat"
INTERVAL = 10
TIMEOUT = 3


def _heartbeat_loop():
    while True:
        try:
            payload = {
                "device_id": "safebox-001",
                "timestamp": time.time()
            }

            r = requests.post(
                HEARTBEAT_URL,
                json=payload,
                timeout=TIMEOUT
            )

            log.info(f"heartbeat ok status={r.status_code}")

        except Exception as e:
            log.warning(f"heartbeat failed: {e}")

        time.sleep(INTERVAL)


def start_heartbeat():
    t = threading.Thread(target=_heartbeat_loop, daemon=True)
    t.start()
