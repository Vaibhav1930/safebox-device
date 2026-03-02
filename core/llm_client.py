import requests
import time
from config.settings import API_BASE_URL
from core.logger import get_logger

log = get_logger("cloud")

MAX_HISTORY = 10
_conversations = {}


def internet_available():
    """
    Checks reachability of Clarity Cloud via health endpoint.
    Fast and reliable for embedded device.
    """
    try:
        response = requests.get(
            f"{API_BASE_URL}/health",
            timeout=3
        )
        return response.status_code == 200
    except requests.RequestException:
        return False


def _get_history(device_id: str):
    if device_id not in _conversations:
        _conversations[device_id] = []
    return _conversations[device_id]


def _trim(history):
    if len(history) > MAX_HISTORY:
        return history[-MAX_HISTORY:]
    return history


def ask_llm(message: str, device_id: str):
    if not internet_available():
        log.warning("cloud.no_internet")
        return None

    url = f"{API_BASE_URL}/v1/chat"
    history = _get_history(device_id)

    history.append({"role": "user", "content": message})
    history = _trim(history)
    _conversations[device_id] = history

    payload = {
        "message": message,
        "history": history,
        "device": {
            "device_id": device_id,
            "caller_type": "device",
            "clock_status": "synced"
        }
    }

    try:
        log.info("cloud.connecting")

        start_time = time.time()

        response = requests.post(
            url,
            json=payload,
            timeout=(5, 20)  # FIXED: 5s connect, 20s read
        )

        latency_ms = int((time.time() - start_time) * 1000)
        log.info(f"cloud.latency_ms={latency_ms}")

        response.raise_for_status()
        data = response.json()

        if data.get("status") != "success":
            log.warning("cloud.status_not_success")
            return None

        reply = data.get("response")
        if not reply:
            log.warning("cloud.empty_response")
            return None

        history.append({"role": "assistant", "content": reply})
        _conversations[device_id] = _trim(history)

        return {
            "request_id": data.get("request_id"),
            "response": reply,
            "latency_ms": latency_ms
        }

    except requests.exceptions.Timeout:
        log.warning("cloud.timeout")
        return None

    except requests.exceptions.RequestException as e:
        log.warning(f"cloud.request_error {e}")
        return None
