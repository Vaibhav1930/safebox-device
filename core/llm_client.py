import os
import time
import requests

from config.settings import API_BASE_URL
from core.logger import get_logger, with_request_id
from core.result_cache import get_cached, store_result

log = get_logger("cloud")

MAX_HISTORY = 10
_conversations: dict[str, list[dict]] = {}

# Reuse one HTTP session for connection pooling / cookies.
_http = requests.Session()
_session_token: str | None = None

def warm_cloud_auth() -> None:
    try:
        _login_and_get_token()
    except Exception as e:
        log.warning(f"cloud.warmup.failed {e}", extra=with_request_id())

def _mask_token(token: str | None) -> str:
    if not token:
        return "None"
    if len(token) <= 12:
        return "***"
    return f"{token[:6]}...{token[-4:]}"


def internet_available() -> bool:
    try:
        response = _http.get(f"{API_BASE_URL}/health", timeout=3)
        return response.status_code == 200
    except requests.RequestException:
        return False


def _get_history(device_id: str) -> list[dict]:
    if device_id not in _conversations:
        _conversations[device_id] = []
    return _conversations[device_id]


def _trim(history: list[dict]) -> list[dict]:
    if len(history) > MAX_HISTORY:
        return history[-MAX_HISTORY:]
    return history


def _extract_token(data: dict) -> str | None:
    """
    Accept multiple backend token shapes so device auth stays robust.
    """
    return (
        data.get("session_token")
        or data.get("token")
        or data.get("access_token")
        or (data.get("data") or {}).get("session_token")
        or (data.get("data") or {}).get("token")
        or (data.get("data") or {}).get("access_token")
    )


def _login_and_get_token() -> str | None:
    global _session_token

    if _session_token:
        log.info(
            f"cloud.login.cached_token={_mask_token(_session_token)}",
            extra=with_request_id(),
        )
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

        response = _http.post(login_url, json=payload, timeout=(5, 15))
        response.raise_for_status()

        data = response.json()
        token = _extract_token(data)

        if not token:
            log.warning(
                f"cloud.login.no_token payload={data}",
                extra=with_request_id(),
            )
            return None

        _session_token = token
        log.info(
            f"cloud.login.success token={_mask_token(_session_token)}",
            extra=with_request_id(),
        )
        return _session_token

    except requests.exceptions.RequestException as e:
        log.warning(f"cloud.login.failed {e}", extra=with_request_id())
        return None
    except ValueError as e:
        log.warning(f"cloud.login.bad_json {e}", extra=with_request_id())
        return None


def _extract_reply(data: dict) -> str | None:
    reply = (
        data.get("response")
        or data.get("reply")
        or data.get("message")
        or data.get("answer")
        or (data.get("data") or {}).get("response")
        or (data.get("data") or {}).get("reply")
        or (data.get("data") or {}).get("message")
        or (data.get("data") or {}).get("answer")
    )

    if reply is None:
        return None

    if isinstance(reply, str):
        cleaned = reply.strip()
        return cleaned or None

    # Never trust non-string backend payloads as a user-facing reply.
    return str(reply).strip() or None


def _is_backend_error_reply(reply: str | None) -> bool:
    if not reply:
        return False

    normalized = reply.strip().lower()
    return (
        normalized.startswith("error:")
        or "traceback" in normalized
        or "exception" in normalized
        or "attributeerror" in normalized
    )


def ask_llm(
    message: str,
    device_context: dict,
    runtime_context: dict,
    request_context: dict | None = None,
):
    request_context = request_context or {}

    device_request_id = request_context.get("device_request_id")
    log_extra = with_request_id(device_request_id)

    device_id = device_context.get(
        "device_id",
        os.getenv("DEVICE_NAME", "safebox-001"),
    )

    history = _get_history(device_id)
    history.append({"role": "user", "content": message})
    history = _trim(history)
    _conversations[device_id] = history

    payload = {
        "message": message,
        "history": history,
        "device": {
            "device_id": device_id,
            "caller_type": device_context.get("caller_type", "device"),
            "clock_status": device_context.get("clock_status", "synced"),
            "timezone": device_context.get(
                "timezone",
                os.getenv("SAFEBOX_TIMEZONE", "Asia/Kolkata"),
            ),
            "location": device_context.get("location"),
        },
        "runtime_context": runtime_context,
        "request_context": request_context,
    }

    cached = get_cached(message)
    if cached:
        log.info("cloud.cache_hit", extra=log_extra)
        return cached

    token = _login_and_get_token()

    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    debug_headers = {}
    if "Authorization" in headers:
        debug_headers["Authorization"] = f"Bearer {_mask_token(token)}"

    log.info(f"cloud.headers={debug_headers}", extra=log_extra)

    try:
        log.info(
            f"cloud.connecting device_id={device_id} "
            f"tz={payload['device'].get('timezone')} "
            f"mode={runtime_context.get('mode')} "
            f"config_version={runtime_context.get('config_version')}",
            extra=log_extra,
        )

        start_time = time.time()

        response = _http.post(
            f"{API_BASE_URL}/v1/chat",
            json=payload,
            headers=headers,
            timeout=(5, 20),
        )

        latency_ms = int((time.time() - start_time) * 1000)
        log.info(f"cloud.latency_ms={latency_ms}", extra=log_extra)

        response.raise_for_status()
        data = response.json()

        log.warning(f"cloud.response_payload={data}", extra=log_extra)

        reply = _extract_reply(data)
        status = data.get("status")
        ok_flag = data.get("ok")
        cloud_request_id = (
            data.get("request_id")
            or data.get("cloud_request_id")
            or (data.get("data") or {}).get("request_id")
        )

        if _is_backend_error_reply(reply):
            log.warning(
                f"cloud.backend_error_reply request_id={cloud_request_id} reply={reply!r}",
                extra=log_extra,
            )
            return None

        success = (
            status == "success"
            or ok_flag is True
            or (reply is not None and status not in {"error", "failed"})
        )

        if not success:
            log.warning(
                f"cloud.status_not_success payload={data}",
                extra=log_extra,
            )
            return None

        if not reply:
            log.warning(
                f"cloud.empty_response payload={data}",
                extra=log_extra,
            )
            return None

        history.append({"role": "assistant", "content": reply})
        _conversations[device_id] = _trim(history)

        result = {
            "cloud_request_id": cloud_request_id,
            "response": reply,
            "latency_ms": latency_ms,
            "config_version": data.get("config_version")
            or (data.get("data") or {}).get("config_version"),
        }

        store_result(message, result)
        return result

    except requests.exceptions.Timeout:
        log.warning("cloud.timeout", extra=log_extra)
        return None

    except requests.exceptions.RequestException as e:
        response_text = None
        try:
            response_text = e.response.text if e.response is not None else None
        except Exception:
            response_text = None

        if response_text:
            log.warning(
                f"cloud.request_error {e} response_body={response_text}",
                extra=log_extra,
            )
        else:
            log.warning(f"cloud.request_error {e}", extra=log_extra)
        return None

    except ValueError as e:
        log.warning(f"cloud.bad_json {e}", extra=log_extra)
        return None
