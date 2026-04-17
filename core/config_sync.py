import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import requests

from core.logger import get_logger, with_request_id
from config.settings import API_BASE_URL

log = get_logger("config_sync")

BASE_DIR = Path(__file__).resolve().parents[1]
SYNC_ROOT = BASE_DIR / "config" / "synced"
RELEASES_DIR = SYNC_ROOT / "releases"
ACTIVE_LINK = SYNC_ROOT / "active"
STATE_FILE = SYNC_ROOT / "sync_state.json"

DEFAULT_STATE = {
    "current_version": "local-bootstrap",
    "last_successful_sync_at": None,
    "last_attempt_at": None,
    "last_attempt_status": "never",
    "last_error": None,
    "source_endpoint": None,
}

DEFAULT_FALLBACK_CONFIG = {
    "version": "local-bootstrap",
    "persona": {
        "assistant_name": "SafeBox",
        "greeting": "Hello. SafeBox is ready.",
        "flags": {},
        "persona_id": None,
        "persona_version": None,
    },
    "behavior": {
        "feature_toggles": {},
        "features": {},
        "source_toggles": {},
        "briefing_preferences": {},
        "bluetooth_pairing_instructions": None,
        "music_provider": None,
        "survival_mode_disclosure": "Offline mode active. Some capabilities are limited.",
    },
    "tap_tags": {
        "GOODNIGHT": {
            "spoken_text": "Good night. I will keep watch."
        }
    },
    "tuning": {
        "api_version": None,
        "timezone": None,
        "version": "local-bootstrap",
        "bluetooth_state": None,
        "boot_document": None,
        "sync_interval_seconds": 900,
    },
}


class ConfigSyncError(Exception):
    pass


class ConfigSyncManager:
    def __init__(self, device_id: str = "safebox-001"):
        self.device_id = device_id
        self.config_url = f"{API_BASE_URL.rstrip('/')}/v1/config"
        self._ensure_layout()

    def _ensure_layout(self):
        RELEASES_DIR.mkdir(parents=True, exist_ok=True)

        if not STATE_FILE.exists():
            self._write_json(STATE_FILE, DEFAULT_STATE)

        bootstrap_dir = RELEASES_DIR / "local-bootstrap"
        if not bootstrap_dir.exists():
            bootstrap_dir.mkdir(parents=True, exist_ok=True)

            manifest = {
                "version": "local-bootstrap",
                "schema_version": 1,
                "domains": ["persona", "behavior", "tap_tags", "tuning"],
                "files": [
                    "persona.json",
                    "behavior.json",
                    "tap_tags.json",
                    "tuning.json",
                    "raw_cloud_config.json",
                ],
            }

            self._write_json(bootstrap_dir / "manifest.json", manifest)
            self._write_json(bootstrap_dir / "persona.json", DEFAULT_FALLBACK_CONFIG["persona"])
            self._write_json(bootstrap_dir / "behavior.json", DEFAULT_FALLBACK_CONFIG["behavior"])
            self._write_json(bootstrap_dir / "tap_tags.json", DEFAULT_FALLBACK_CONFIG["tap_tags"])
            self._write_json(bootstrap_dir / "tuning.json", DEFAULT_FALLBACK_CONFIG["tuning"])
            self._write_json(bootstrap_dir / "raw_cloud_config.json", {})

        if not ACTIVE_LINK.exists():
            if ACTIVE_LINK.is_symlink() or ACTIVE_LINK.exists():
                ACTIVE_LINK.unlink()
            ACTIVE_LINK.symlink_to(bootstrap_dir.resolve(), target_is_directory=True)

    def _utc_now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _read_json(self, path: Path, default=None):
        if not path.exists():
            return {} if default is None else default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write_json(self, path: Path, data: dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _get_state(self) -> dict:
        state = self._read_json(STATE_FILE, DEFAULT_STATE.copy())
        for k, v in DEFAULT_STATE.items():
            state.setdefault(k, v)
        return state

    def _save_state(self, **updates):
        state = self._get_state()
        state.update(updates)
        self._write_json(STATE_FILE, state)

    def get_state(self) -> dict:
        state = self._get_state()
        return {
            "current_version": state.get("current_version"),
            "last_successful_sync_at": state.get("last_successful_sync_at"),
            "last_attempt_at": state.get("last_attempt_at"),
            "last_attempt_status": state.get("last_attempt_status"),
            "last_error": state.get("last_error"),
            "source_endpoint": state.get("source_endpoint"),
        }

    def get_active_version(self) -> str:
        return self._get_state().get("current_version", "local-bootstrap")

    def get_active_config(self) -> dict:
        active_dir = ACTIVE_LINK.resolve()
        return {
            "version": self.get_active_version(),
            "persona": self._read_json(active_dir / "persona.json", DEFAULT_FALLBACK_CONFIG["persona"].copy()),
            "behavior": self._read_json(active_dir / "behavior.json", DEFAULT_FALLBACK_CONFIG["behavior"].copy()),
            "tap_tags": self._read_json(active_dir / "tap_tags.json", DEFAULT_FALLBACK_CONFIG["tap_tags"].copy()),
            "tuning": self._read_json(active_dir / "tuning.json", DEFAULT_FALLBACK_CONFIG["tuning"].copy()),
            "raw_cloud_config": self._read_json(active_dir / "raw_cloud_config.json", {}),
        }

    # ------------------------------------------------------------------
    # Convenience getters
    # ------------------------------------------------------------------

    def get_persona(self) -> dict:
        cfg = self.get_active_config()
        return cfg.get("persona", {}) or {}

    def get_behavior(self) -> dict:
        cfg = self.get_active_config()
        return cfg.get("behavior", {}) or {}

    def get_tap_tags(self) -> dict:
        cfg = self.get_active_config()
        return cfg.get("tap_tags", {}) or {}

    def get_tuning(self) -> dict:
        cfg = self.get_active_config()
        return cfg.get("tuning", {}) or {}

    def get_persona_name(self) -> str:
        return (
            self.get_persona().get("assistant_name")
            or DEFAULT_FALLBACK_CONFIG["persona"]["assistant_name"]
        )

    def get_persona_greeting(self) -> str:
        return (
            self.get_persona().get("greeting")
            or DEFAULT_FALLBACK_CONFIG["persona"]["greeting"]
        )

    def get_persona_flags(self) -> dict:
        flags = self.get_persona().get("flags")
        return flags if isinstance(flags, dict) else {}

    def get_persona_id(self):
        return self.get_persona().get("persona_id")

    def get_persona_version(self):
        return self.get_persona().get("persona_version")

    def get_feature_toggles(self) -> dict:
        value = self.get_behavior().get("feature_toggles")
        return value if isinstance(value, dict) else {}

    def get_features(self) -> dict:
        value = self.get_behavior().get("features")
        return value if isinstance(value, dict) else {}

    def get_source_toggles(self) -> dict:
        value = self.get_behavior().get("source_toggles")
        return value if isinstance(value, dict) else {}

    def get_briefing_preferences(self) -> dict:
        value = self.get_behavior().get("briefing_preferences")
        return value if isinstance(value, dict) else {}

    def get_bluetooth_pairing_instructions(self):
        return self.get_behavior().get("bluetooth_pairing_instructions")

    def get_music_provider(self):
        return self.get_behavior().get("music_provider")

    def get_survival_mode_disclosure(self) -> str:
        return (
            self.get_behavior().get("survival_mode_disclosure")
            or DEFAULT_FALLBACK_CONFIG["behavior"]["survival_mode_disclosure"]
        )

    def get_tap_tag_phrase(self, behavior_name: str, default: str = "") -> str:
        return (
            self.get_tap_tags()
            .get(behavior_name, {})
            .get("spoken_text", default)
        )

    def get_timezone(self):
        return self.get_tuning().get("timezone")

    def get_api_version(self):
        return self.get_tuning().get("api_version")

    def get_bluetooth_state(self):
        return self.get_tuning().get("bluetooth_state")

    def get_boot_document(self):
        return self.get_tuning().get("boot_document")

    def get_sync_interval_seconds(self) -> int:
        value = self.get_tuning().get("sync_interval_seconds")
        if isinstance(value, int) and value > 0:
            return value
        return DEFAULT_FALLBACK_CONFIG["tuning"]["sync_interval_seconds"]

    def get_effective_config(self) -> dict:
        """
        Human-friendly read model for UI/status/API use.
        Keeps cloud-synced config separate from local device_config.json.
        """
        return {
            "version": self.get_active_version(),
            "persona": {
                "assistant_name": self.get_persona_name(),
                "greeting": self.get_persona_greeting(),
                "flags": self.get_persona_flags(),
                "persona_id": self.get_persona_id(),
                "persona_version": self.get_persona_version(),
            },
            "behavior": {
                "feature_toggles": self.get_feature_toggles(),
                "features": self.get_features(),
                "source_toggles": self.get_source_toggles(),
                "briefing_preferences": self.get_briefing_preferences(),
                "bluetooth_pairing_instructions": self.get_bluetooth_pairing_instructions(),
                "music_provider": self.get_music_provider(),
                "survival_mode_disclosure": self.get_survival_mode_disclosure(),
            },
            "tap_tags": self.get_tap_tags(),
            "tuning": self.get_tuning(),
            "raw_cloud_config": self.get_active_config().get("raw_cloud_config", {}),
        }

    # ------------------------------------------------------------------
    # Cloud fetch/apply
    # ------------------------------------------------------------------

    def check_for_update(self) -> dict:
        current_version = self.get_active_version()
        params = {
            "device_id": self.device_id,
            "version": current_version,
        }

        log.info(
            f"config.check.started endpoint={self.config_url} current_version={current_version}",
            extra=with_request_id(),
        )

        r = requests.get(self.config_url, params=params, timeout=10)

        if r.status_code == 404:
            raise ConfigSyncError(
                f"/v1/config not found at {self.config_url}. Cloud config endpoint is unavailable."
            )

        r.raise_for_status()
        body = r.json()

        log.info(
            f"config.check.completed status={body.get('status')} version={body.get('version')}",
            extra=with_request_id(),
        )

        status = body.get("status")
        returned_version = body.get("version")
        returned_config = body.get("config") or {}

        if status != "success":
            raise ConfigSyncError(f"config endpoint returned non-success status={status}")

        if not returned_version:
            raise ConfigSyncError("config response missing version")

        if not isinstance(returned_config, dict):
            raise ConfigSyncError("config response missing valid config object")

        if returned_version == current_version:
            return {
                "update_available": False,
                "target_version": current_version,
                "config": returned_config,
            }

        return {
            "update_available": True,
            "target_version": returned_version,
            "config": returned_config,
        }

    def _normalize_cloud_config(self, version: str, config: dict) -> dict:
        if not isinstance(config, dict):
            raise ConfigSyncError("config must be an object")

        persona = {}
        behavior = {}
        tap_tags = {}
        tuning = {}

        persona["assistant_name"] = config.get("active_persona") or "SafeBox"

        persona_flags = config.get("persona_flags")
        if isinstance(persona_flags, dict):
            persona["flags"] = persona_flags
        else:
            persona["flags"] = {}

        persona["persona_id"] = config.get("persona_id")
        persona["persona_version"] = config.get("persona_version")

        greeting = config.get("greeting") or config.get("persona_greeting")
        if isinstance(greeting, str) and greeting.strip():
            persona["greeting"] = greeting.strip()
        else:
            persona["greeting"] = DEFAULT_FALLBACK_CONFIG["persona"]["greeting"]

        feature_toggles = config.get("feature_toggles")
        if isinstance(feature_toggles, dict):
            behavior["feature_toggles"] = feature_toggles

        features = config.get("features")
        if isinstance(features, dict):
            behavior["features"] = features

        source_toggles = config.get("source_toggles")
        if isinstance(source_toggles, dict):
            behavior["source_toggles"] = source_toggles

        briefing_preferences = config.get("briefing_preferences")
        if isinstance(briefing_preferences, dict):
            behavior["briefing_preferences"] = briefing_preferences

        bluetooth_pairing_instructions = config.get("bluetooth_pairing_instructions")
        if bluetooth_pairing_instructions is not None:
            behavior["bluetooth_pairing_instructions"] = bluetooth_pairing_instructions

        music_provider = config.get("music_provider")
        if music_provider is not None:
            behavior["music_provider"] = music_provider

        behavior["survival_mode_disclosure"] = (
            config.get("survival_mode_disclosure")
            or DEFAULT_FALLBACK_CONFIG["behavior"]["survival_mode_disclosure"]
        )

        cloud_tap_tags = config.get("tap_tags")
        if isinstance(cloud_tap_tags, dict):
            tap_tags = cloud_tap_tags
        else:
            tap_tags = DEFAULT_FALLBACK_CONFIG["tap_tags"].copy()

        tuning["api_version"] = config.get("api_version")
        tuning["timezone"] = config.get("timezone")
        tuning["version"] = config.get("version") or version

        bluetooth_state = config.get("bluetooth_state")
        if bluetooth_state is not None:
            tuning["bluetooth_state"] = bluetooth_state

        boot_document = config.get("boot_document")
        if boot_document is not None:
            tuning["boot_document"] = boot_document

        if "sync_interval_seconds" in config:
            tuning["sync_interval_seconds"] = config.get("sync_interval_seconds")
        else:
            tuning["sync_interval_seconds"] = DEFAULT_FALLBACK_CONFIG["tuning"]["sync_interval_seconds"]

        return {
            "persona": persona,
            "behavior": behavior,
            "tap_tags": tap_tags,
            "tuning": tuning,
            "raw_cloud_config": config,
        }

    def _write_release_from_config(self, version: str, config: dict) -> Path:
        normalized = self._normalize_cloud_config(version, config)

        release_dir = RELEASES_DIR / version
        if release_dir.exists():
            shutil.rmtree(release_dir)

        release_dir.mkdir(parents=True, exist_ok=True)

        manifest = {
            "version": version,
            "schema_version": 1,
            "domains": ["persona", "behavior", "tap_tags", "tuning"],
            "files": [
                "persona.json",
                "behavior.json",
                "tap_tags.json",
                "tuning.json",
                "raw_cloud_config.json",
            ],
        }

        self._write_json(release_dir / "manifest.json", manifest)
        self._write_json(release_dir / "persona.json", normalized["persona"])
        self._write_json(release_dir / "behavior.json", normalized["behavior"])
        self._write_json(release_dir / "tap_tags.json", normalized["tap_tags"])
        self._write_json(release_dir / "tuning.json", normalized["tuning"])
        self._write_json(release_dir / "raw_cloud_config.json", normalized["raw_cloud_config"])

        return release_dir

    def _activate_release(self, release_dir: Path):
        tmp_link = SYNC_ROOT / "active_tmp"
        if tmp_link.exists() or tmp_link.is_symlink():
            tmp_link.unlink()
        tmp_link.symlink_to(release_dir.resolve(), target_is_directory=True)
        os.replace(tmp_link, ACTIVE_LINK)

    def sync_once(self) -> dict:
        attempt_at = self._utc_now()
        self._save_state(
            last_attempt_at=attempt_at,
            last_attempt_status="running",
            last_error=None,
            source_endpoint=self.config_url,
        )

        try:
            check = self.check_for_update()

            if not check.get("update_available"):
                self._save_state(
                    last_attempt_status="no_update",
                    last_error=None,
                    source_endpoint=self.config_url,
                )
                return {
                    "ok": True,
                    "status": "no_update",
                    "current_version": self.get_active_version(),
                }

            version = check["target_version"]
            config = check["config"]

            log.info(
                f"config.activate.started version={version}",
                extra=with_request_id(),
            )

            release_dir = self._write_release_from_config(version, config)
            self._activate_release(release_dir)

            self._save_state(
                current_version=version,
                last_successful_sync_at=self._utc_now(),
                last_attempt_status="success",
                last_error=None,
                source_endpoint=self.config_url,
            )

            log.info(
                f"config.activate.completed version={version}",
                extra=with_request_id(),
            )

            return {
                "ok": True,
                "status": "updated",
                "current_version": version,
            }

        except Exception as e:
            log.warning(f"config.sync.failed error={e}", extra=with_request_id())
            self._save_state(
                last_attempt_status="failed",
                last_error=str(e),
                source_endpoint=self.config_url,
            )
            raise
