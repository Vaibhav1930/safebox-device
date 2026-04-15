import json
import os
import time
from pathlib import Path
from typing import Any

from core.logger import get_logger

log = get_logger("runtime_mode")

MODE_CLOUD = "cloud"
MODE_SURVIVAL = "survival"

RUNTIME_MODE_FILE = Path("/opt/safebox/runtime/mode.json")
DEFAULT_MANUAL_OVERRIDE_SECONDS = int(
    os.environ.get("SAFEBOX_MANUAL_MODE_TTL_SECONDS", "600")
)


def _default_state() -> dict[str, Any]:
    return {
        "mode": MODE_CLOUD,
        "manual_override": False,
        "override_expires_at": None,
        "updated_at": time.time(),
        "reason": "default",
    }


def _normalize_mode(mode: str | None) -> str:
    value = (mode or "").strip().lower()
    return value if value in (MODE_CLOUD, MODE_SURVIVAL) else MODE_CLOUD


def load_runtime_mode_state() -> dict[str, Any]:
    try:
        if not RUNTIME_MODE_FILE.exists():
            return _default_state()

        with open(RUNTIME_MODE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        state = _default_state()
        state.update(data or {})
        state["mode"] = _normalize_mode(state.get("mode"))
        return state
    except Exception as e:
        log.warning(f"runtime_mode.load_failed | {e}")
        return _default_state()


def save_runtime_mode_state(state: dict[str, Any]) -> dict[str, Any]:
    normalized = _default_state()
    normalized.update(state or {})
    normalized["mode"] = _normalize_mode(normalized.get("mode"))
    normalized["updated_at"] = time.time()

    try:
        RUNTIME_MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(RUNTIME_MODE_FILE, "w", encoding="utf-8") as f:
            json.dump(normalized, f, indent=2)
    except Exception as e:
        log.warning(f"runtime_mode.save_failed | {e}")

    return normalized


def set_manual_mode(
    mode: str,
    reason: str = "manual",
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    ttl = DEFAULT_MANUAL_OVERRIDE_SECONDS if ttl_seconds is None else int(ttl_seconds)
    now = time.time()

    state = {
        "mode": _normalize_mode(mode),
        "manual_override": True,
        "override_expires_at": now + ttl,
        "updated_at": now,
        "reason": reason,
    }
    saved = save_runtime_mode_state(state)
    log.info(
        f"runtime_mode.manual_set mode={saved['mode']} ttl_seconds={ttl} reason={reason}"
    )
    return saved


def set_cloud_mode(reason: str = "manual_cloud") -> dict[str, Any]:
    state = {
        "mode": MODE_CLOUD,
        "manual_override": False,
        "override_expires_at": None,
        "reason": reason,
    }
    saved = save_runtime_mode_state(state)
    log.info(f"runtime_mode.cloud_set reason={reason}")
    return saved


def set_survival_mode(reason: str = "manual_survival", ttl_seconds: int | None = None) -> dict[str, Any]:
    return set_manual_mode(MODE_SURVIVAL, reason=reason, ttl_seconds=ttl_seconds)


def clear_manual_override(reason: str = "clear_override") -> dict[str, Any]:
    state = load_runtime_mode_state()
    state["manual_override"] = False
    state["override_expires_at"] = None
    state["reason"] = reason
    saved = save_runtime_mode_state(state)
    log.info(f"runtime_mode.override_cleared reason={reason}")
    return saved


def manual_override_active(state: dict[str, Any] | None = None) -> bool:
    current = state or load_runtime_mode_state()
    if not current.get("manual_override"):
        return False

    expiry = current.get("override_expires_at")
    if expiry is None:
        return True

    try:
        return time.time() < float(expiry)
    except Exception:
        return False
