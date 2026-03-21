import time
import requests
import subprocess
from core.logger import get_logger

log = get_logger("heartbeat")

HEARTBEAT_URL = "http://127.0.0.1:8000/heartbeat"
TIMEOUT       = 3
DEVICE_ID     = "safebox-001"
MODE_FILE     = "/opt/safebox/runtime/mode"


def _get_mode() -> str:
    try:
        with open(MODE_FILE) as f:
            return f.read().strip() or "cloud"
    except FileNotFoundError:
        return "cloud"


def _get_uptime() -> str:
    try:
        result = subprocess.run(["uptime", "-p"], capture_output=True, text=True)
        return result.stdout.strip()
    except Exception:
        return "unknown"


def send_heartbeat(payload: dict = None) -> bool:
    """
    Send heartbeat to local cloud API.
    If payload is provided it is used as-is (called from device_controller).
    If not provided, builds the correct payload from system state.
    """
    if payload is None:
        mode = _get_mode()
        payload = {
            "device_id": DEVICE_ID,
            "mode":      mode,
            "online":    mode == "cloud",
            "uptime":    _get_uptime(),
            "timestamp": time.time(),
        }
    try:
        r = requests.post(HEARTBEAT_URL, json=payload, timeout=TIMEOUT)
        log.info(f"heartbeat sent status={r.status_code}")
        return r.ok
    except Exception as e:
        log.warning(f"heartbeat failed: {e}")
        return False


def start_heartbeat(source: str = "wake") -> None:
    """
    Called by safebox-wake on startup.
    Sends a single heartbeat with correct payload so the 422 error is gone.
    """
    send_heartbeat()
