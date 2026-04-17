import json
from pathlib import Path

SYNC_ROOT = Path("/mnt/ssd/safebox-device/config/synced")
DEVICE_CONFIG_PATH = Path("/mnt/ssd/safebox-device/config/device_config.json")

def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def get_sync_state() -> dict:
    return _read_json(SYNC_ROOT / "sync_state.json")

def get_active_release_dir() -> Path | None:
    state = get_sync_state()
    version = state.get("active_version") or state.get("current_version")
    if not version:
        return None
    candidate = SYNC_ROOT / "releases" / version
    return candidate if candidate.exists() else None

def get_effective_runtime_config() -> dict:
    release_dir = get_active_release_dir()

    # fallback to local device config if synced release missing
    device_cfg = _read_json(DEVICE_CONFIG_PATH)

    if not release_dir:
        return {
            "version": "local-device-config",
            "persona": {},
            "behavior": {},
            "tuning": {},
            "tap_tags": {},
            "device": device_cfg,
        }

    return {
        "version": release_dir.name,
        "persona": _read_json(release_dir / "persona.json"),
        "behavior": _read_json(release_dir / "behavior.json"),
        "tuning": _read_json(release_dir / "tuning.json"),
        "tap_tags": _read_json(release_dir / "tap_tags.json"),
        "device": device_cfg,
    }

def build_runtime_context(mode: str) -> dict:
    cfg = get_effective_runtime_config()

    persona = cfg.get("persona", {})
    behavior = cfg.get("behavior", {})
    device = cfg.get("device", {})
    tuning = cfg.get("tuning", {})

    timezone = (
        device.get("timezone")
        or tuning.get("timezone")
        or "Asia/Kolkata"
    )

    return {
        "config_version": cfg.get("version"),
        "mode": mode,
        "assistant_name": persona.get("assistant_name", "Clarity"),
        "persona_greeting": persona.get("persona_greeting", "Hello. SafeBox is ready."),
        "survival_mode_disclosure": behavior.get(
            "survival_mode_disclosure",
            "Offline mode active. Some capabilities are limited."
        ),
        "timezone": timezone,
        "device_profile": {
            "device_name": device.get("device_name", "safebox-001"),
            "active_persona": persona.get("active_persona", "household"),
        },
    }