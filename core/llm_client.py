import os
import time
import requests

from config.settings import API_BASE_URL
from core.logger import get_logger, with_request_id
from core.result_cache import get_cached, store_result

log = get_logger("cloud")

MAX_HISTORY = 10
_conversations = {}
_session_token = None


def internet_available():
    try:
        response = requests.get(f"{API_BASE_URL}/health", timeout=3)
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


def _login_and_get_token():
    global _session_token

    if _session_token:
        return _session_token

    email = os.getenv("CLARITY_LOGIN_EMAIL", "").strip()
    password = os.getenv("CLARITY_LOGIN_PASSWORD", "").strip()

    if not email or not password:
        log.warning("cloud.login_missing_credentials", extra=with_request_id())
        return None

    login_url = f"{API_BASE_URL}/v1/auth/login"
    payload = {
        "email": email,
        "password": password,
    }

    try:
        log.info("cloud.login.start", extra=with_request_id())

        response = requests.post(login_url, json=payload, timeout=(5, 15))
        response.raise_for_status()

        data = response.json()
        token = data.get("token")

        if not token:
            log.warning("cloud.login.no_token", extra=with_request_id())
            return None

        _session_token = token
        log.info("cloud.login.success", extra=with_request_id())
        return _session_token

    except requests.exceptions.RequestException as e:
        log.warning(f"cloud.login.failed {e}", extra=with_request_id())
        return None


def ask_llm(message: str, device_id: str):
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
            "clock_status": "synced",
        },
    }

    cached = get_cached(message)
    if cached:
        log.info("cloud.cache_hit", extra=with_request_id())
        return cached

    token = _login_and_get_token()

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        log.info("cloud.connecting", extra=with_request_id())

        start_time = time.time()

        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=(5, 20),
        )

        latency_ms = int((time.time() - start_time) * 1000)
        log.info(f"cloud.latency_ms={latency_ms}", extra=with_request_id())

        response.raise_for_status()
        data = response.json()

        if data.get("status") != "success":
            log.warning("cloud.status_not_success", extra=with_request_id())
            return None

        reply = data.get("response")
        if not reply:
            log.warning("cloud.empty_response", extra=with_request_id())
            return None

        history.append({"role": "assistant", "content": reply})
        _conversations[device_id] = _trim(history)

        result = {
            "cloud_request_id": data.get("request_id"),
            "response": reply,
            "latency_ms": latency_ms,
        }

        store_result(message, result)
        return result

    except requests.exceptions.Timeout:
        log.warning("cloud.timeout", extra=with_request_id())
        return None

    except requests.exceptions.RequestException as e:
        log.warning(f"cloud.request_error {e}", extra=with_request_id())
        return None
