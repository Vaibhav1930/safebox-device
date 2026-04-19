"""
web/app.py
SafeBox Local Web Server — Production Grade

Serves the setup wizard, status dashboard, vault upload, and the
full NFC management surface (tag list, rename, assign, enroll Tap KEY,
toggle vault gating).

All NFC state is owned by core.nfc_manager — this module is a thin
HTTP adapter. No NFC business logic lives here.

Vault upload is gated by Tap KEY when gating is enabled; the gate is
checked server-side on every POST, not just in the UI.
"""
from core.runtime_mode import (
    load_runtime_mode_state,
    manual_override_active,
    save_runtime_mode_state,
    set_cloud_mode,
    set_survival_mode,
)
from core.llm_client import internet_available
from flask import Flask, jsonify, render_template, request, redirect, url_for
from core.cloud_heartbeat import send_heartbeat
from core.logger import get_logger
from core.config_sync import ConfigSyncManager
import subprocess
import time
import json
import os
import threading
import shutil
import socket
from pathlib import Path
from werkzeug.utils import secure_filename
from core.audio.tts_player import speak
from core.ap_setup import stop_hotspot
from core.onboarding_state import get_hostname_url, setup_complete_message
from core.setup_state import load_setup_state, mark_setup_completed
from core.ap_setup import stop_hotspot
log = get_logger("web")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR    = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_FILE = os.path.join(BASE_DIR, "config", "device_config.json")
SAFEBOX_VAULT_ROOT = os.environ.get("SAFEBOX_VAULT_ROOT", "/mnt/ssd/safebox-device/vault")
VAULT_DIR   = os.path.join(SAFEBOX_VAULT_ROOT, "uploads")
MODE_FILE   = "/opt/safebox/runtime/mode"
MANUAL_VOICE_TRIGGER_FILE = "/opt/safebox/runtime/manual_voice_trigger"
# ---------------------------------------------------------------------------
# App init
# ---------------------------------------------------------------------------

app = Flask(__name__, template_folder="templates")
app.config["UPLOAD_FOLDER"] = VAULT_DIR


config_sync_manager = ConfigSyncManager(
    device_id=os.environ.get("DEVICE_NAME", "safebox-001")
)
# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------
def get_effective_persona() -> dict:
    return config_sync_manager.get_effective_config().get("persona", {})

def get_effective_behavior() -> dict:
    return config_sync_manager.get_effective_config().get("behavior", {})

def get_effective_tuning() -> dict:
    return config_sync_manager.get_effective_config().get("tuning", {})

def get_effective_tap_tags() -> dict:
    return config_sync_manager.get_effective_config().get("tap_tags", {})
def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(data: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


def config_get(key: str, default=None):
    return load_config().get(key, default)


def config_set(key: str, value) -> None:
    cfg = load_config()
    cfg[key] = value
    save_config(cfg)

# ---------------------------------------------------------------------------
# System helpers
# ---------------------------------------------------------------------------

def get_current_mode() -> str:
    """Read current mode from runtime state and auto-recover if override expired."""
    try:
        state = load_runtime_mode_state()

        if manual_override_active(state):
            return state.get("mode", "cloud")

        if state.get("manual_override"):
            if internet_available():
                save_runtime_mode_state({
                    "mode": "cloud",
                    "manual_override": False,
                    "override_expires_at": None,
                    "reason": "auto_recovered_to_cloud_status_check",
                })
                return "cloud"

            save_runtime_mode_state({
                "mode": "survival",
                "manual_override": False,
                "override_expires_at": None,
                "reason": "override_expired_cloud_unhealthy_status_check",
            })
            return "survival"

        return state.get("mode", "cloud")
    except Exception:
        return "cloud"


def is_cloud_api_alive() -> bool:
    try:
        import requests
        r = requests.get("http://127.0.0.1:8000/health", timeout=3)
        return r.ok
    except Exception:
        return False


def get_uptime() -> int:
    with open("/proc/uptime") as f:
        return int(float(f.readline().split()[0]))


def get_disk_usage() -> dict:
    total, used, free = shutil.disk_usage("/")
    return {
        "total_gb": round(total / (1024 ** 3), 2),
        "used_gb":  round(used  / (1024 ** 3), 2),
        "free_gb":  round(free  / (1024 ** 3), 2),
    }


def count_vault_files() -> int:
    if not os.path.exists(VAULT_DIR):
        return 0
    return len(os.listdir(VAULT_DIR))

def get_temperature_state() -> dict:
    try:
        from core.temperature import get_status
        return get_status()
    except Exception as e:
        log.warning(f"temperature.status_block.error | {e}")

    candidates = [
        "/sys/class/thermal/thermal_zone0/temp",
        "/sys/class/hwmon/hwmon0/temp1_input",
    ]
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read().strip()
            value = float(raw)
            if value > 1000:
                value = value / 1000.0
            return {
                "connected": True,
                "celsius": round(value, 1),
                "fahrenheit": round((value * 9 / 5) + 32, 1),
                "status": "ok" if value < 75 else "warm" if value < 85 else "hot",
                "source": "cpu_fallback",
            }
        except Exception:
            continue

    return {
        "connected": False,
        "celsius": None,
        "fahrenheit": None,
        "status": "unknown",
        "source": "unavailable",
    }


def _tcp_check(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def get_connectivity_state() -> dict:
    api_base = os.environ.get("CLARITY_API_BASE_URL", "").strip()
    api_reachable = False

    if api_base.startswith("http://") or api_base.startswith("https://"):
        try:
            from urllib.parse import urlparse
            parsed = urlparse(api_base)
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if host:
                api_reachable = _tcp_check(host, port, timeout=2.0)
        except Exception:
            api_reachable = False

    network_check_host = os.environ.get("NETWORK_CHECK_HOST", "8.8.8.8").strip()
    internet_reachable = _tcp_check(network_check_host, 53, timeout=2.0)

    return {
        "internet_reachable": internet_reachable,
        "cloud_api_reachable": api_reachable,
        "cloud_api_base_url": api_base,
    }


def get_plug_state() -> dict:
    try:
        from core.smart_plug import get_status
        raw = get_status() or {}
    except Exception as e:
        log.warning(f"plug.status_block.error | {e}")
        return {
            "configured": bool(os.environ.get("TAPO_PLUG_IP")),
            "connected": False,
            "on": None,
            "state": "unknown",
            "alias": None,
            "ip": os.environ.get("TAPO_PLUG_IP"),
            "power_w": None,
        }

    # Normalize values
    on = raw.get("on")
    state = raw.get("state")
    power_w = raw.get("power_w")

    # Infer ON/OFF if missing
    if on is None:
        if state == "on":
            on = True
        elif state == "off":
            on = False

    # Infer connection
    connected = raw.get("connected")
    if connected is None:
        connected = (on is not None) or (power_w is not None)

    # Normalize state
    if state not in ("on", "off"):
        if on is True:
            state = "on"
        elif on is False:
            state = "off"
        elif connected:
            state = "connected"
        else:
            state = "unknown"

    return {
        "configured": raw.get("configured", True),
        "connected": bool(connected),
        "on": on,
        "state": state,
        "power_w": power_w,
        "alias": raw.get("alias"),
        "ip": raw.get("ip") or os.environ.get("TAPO_PLUG_IP"),
    }


def get_vault_state() -> dict:
    vault_root = Path(SAFEBOX_VAULT_ROOT)
    uploads_dir = Path(VAULT_DIR)

    upload_count = 0
    if uploads_dir.exists():
        try:
            upload_count = sum(1 for p in uploads_dir.iterdir() if p.is_file())
        except Exception:
            upload_count = 0

    interactions_dir = vault_root / "interactions"
    interaction_count = 0
    if interactions_dir.exists():
        try:
            interaction_count = sum(1 for _ in interactions_dir.rglob("*.json"))
        except Exception:
            interaction_count = 0

    return {
        "root": str(vault_root),
        "available": vault_root.exists(),
        "upload_count": upload_count,
        "interaction_count": interaction_count,
        "gating_enabled": bool(config_get("tap_key_gating", False)),
        "unlocked": _nfc_status_block().get("vault_unlocked", False),
    }

def validate_ssid(ssid: str) -> bool:
    """Reject SSIDs that could cause unexpected nmcli behaviour."""
    if not ssid or len(ssid) > 32:
        return False
    if any(c in ssid for c in [";", "|", "&", "`", "$"]):
        return False
    return True

# ---------------------------------------------------------------------------
# WiFi helpers
# ---------------------------------------------------------------------------
def _run_nmcli(args: list[str], timeout: int = 40) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sudo", "nmcli", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _active_wifi_ssid() -> str | None:
    try:
        result = _run_nmcli(["-t", "-f", "ACTIVE,SSID", "dev", "wifi"], timeout=10)
        for line in result.stdout.strip().splitlines():
            if line.startswith("yes:"):
                return line.split(":", 1)[1].strip()
    except Exception as e:
        log.warning(f"wifi.active_ssid.failed | {e}")
    return None


def _wait_for_ssid(expected_ssid: str, timeout: int = 35) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _active_wifi_ssid() == expected_ssid:
            return True
        time.sleep(1)
    return False


def _get_primary_ip() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def _handoff_to_home_wifi(device_name: str, wifi_ssid: str, wifi_password: str) -> None:
    try:
        log.info(f"onboarding.switch.begin ssid={wifi_ssid}")

        # Stop hotspot first
        _run_nmcli(["connection", "down", "SafeBox-Setup"], timeout=15)
        _run_nmcli(["connection", "delete", "SafeBox-Setup"], timeout=15)

        time.sleep(2)

        # Clear stale saved profile for target SSID if needed
        _run_nmcli(["connection", "delete", wifi_ssid], timeout=15)

        # Scan and connect
        _run_nmcli(["radio", "wifi", "on"], timeout=10)
        _run_nmcli(["dev", "set", "wlan0", "managed", "yes"], timeout=10)
        _run_nmcli(["dev", "wifi", "rescan", "ifname", "wlan0"], timeout=20)

        result = _run_nmcli(
            ["dev", "wifi", "connect", wifi_ssid, "password", wifi_password, "ifname", "wlan0"],
            timeout=60,
        )

        if result.returncode != 0:
            log.warning(
                f"onboarding.switch.connect_failed ssid={wifi_ssid} stderr={result.stderr.strip()}"
            )
            return

        if not _wait_for_ssid(wifi_ssid, timeout=35):
            log.warning(f"onboarding.switch.verify_failed ssid={wifi_ssid}")
            return

        log.info(f"onboarding.switch.connected ssid={wifi_ssid} ip={_get_primary_ip()}")
        
        try:
            mark_setup_completed()
            log.info("onboarding.completed.state_updated")
        except Exception as e:
            log.warning(f"onboarding.complete.state_failed | {e}")
        try:
            stop_hotspot()
            log.info("onboarding.hotspot.stopped")
        except Exception as e:
            log.warning(f"onboarding.hotspot.stop_failed | {e}")
        try:
            speak(setup_complete_message())
        except Exception as e:
            log.warning(f"onboarding.switch.announce_failed | {e}")

    except Exception as e:
        log.warning(f"onboarding.switch.failed | {e}")
        
        
def verify_wifi_connected(expected_ssid: str) -> bool:
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.strip().splitlines():
            if line.startswith("yes:") and line.split(":", 1)[1] == expected_ssid:
                return True
    except Exception as e:
        log.warning(f"wifi.verify.failed | {e}")
    return False

def scan_wifi_networks() -> list:
    try:
        subprocess.run(
            ["nmcli", "device", "wifi", "rescan"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
        )
        time.sleep(2)
        result = subprocess.run(
            ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            log.warning(f"nmcli.error {result.stderr}")
            return []
        networks = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split(":")
            if len(parts) >= 3 and parts[0]:
                networks.append({"ssid": parts[0], "signal": parts[1], "security": parts[2]})
        unique = {n["ssid"]: n for n in networks}
        return list(unique.values())
    except Exception as e:
        log.warning(f"wifi.scan.error {e}")
        return []


def get_current_wifi():
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.strip().split("\n"):
            if line.startswith("yes:"):
                return line.split(":")[1]
        return None
    except Exception:
        return None

# ---------------------------------------------------------------------------
# NFC helpers — thin wrappers, no logic here
# ---------------------------------------------------------------------------

def _nfc():
    """Lazy import — web server starts cleanly even without libnfc hardware."""
    import core.nfc_manager as m
    return m


def _nfc_status_block() -> dict:
    """
    Build the NFC section of the status payload.
    Returns safe defaults on any failure so the rest of the payload
    is never affected by an NFC hardware error.
    """
    try:
        nfc       = _nfc()
        registry  = nfc._load_registry()
        tags      = list(registry.get("tags", {}).values())
        tap_key   = registry.get("tap_key")
        gating_on = config_get("tap_key_gating", False)
        unlocked  = nfc.is_vault_unlocked()
        return {
            "tap_key_enrolled":     tap_key is not None,
            "tap_key_uid":          tap_key,
            "vault_gating_enabled": gating_on,
            "vault_unlocked":       unlocked,
            "tags":                 tags,
            "tag_count":            len(tags),
        }
    except Exception as e:
        log.warning(f"nfc_status_block.error | {e}")
        return {
            "tap_key_enrolled":     False,
            "tap_key_uid":          None,
            "vault_gating_enabled": False,
            "vault_unlocked":       False,
            "tags":                 [],
            "tag_count":            0,
        }


def _vault_access_allowed() -> bool:
    """
    Returns True when the caller may access vault content.

    The gate is only active when BOTH conditions are met:
      1. tap_key_gating is True in device config
      2. A Tap KEY is actually enrolled in the NFC registry

    If no key is enrolled, gating is a no-op — we never lock the user
    out of their own device. On any import/hardware error we fail open
    for the same reason.
    """
    gating_on = config_get("tap_key_gating", False)
    if not gating_on:
        return True
    try:
        nfc = _nfc()
        if nfc._load_registry().get("tap_key") is None:
            return True   # Gating on but no key enrolled — treat as open
        return nfc.is_vault_unlocked()
    except Exception as e:
        log.warning(f"vault_access_check.error | {e}")
        return True       # Fail open — never hardware-lock the user out

# ---------------------------------------------------------------------------
# Status payload (shared by HTML dashboard and JSON API)
# ---------------------------------------------------------------------------
def status_payload() -> dict:
    current_mode = get_current_mode()
    runtime_mode = load_runtime_mode_state()

    effective = config_sync_manager.get_effective_config()
    persona = effective.get("persona", {})
    behavior = effective.get("behavior", {})
    tuning = effective.get("tuning", {})
    tap_tags = effective.get("tap_tags", {})
    config_sync_state = config_sync_manager.get_state()
    setup_state = load_setup_state()
    status = {
        "mode": current_mode,
        "setup": {
                    "completed": setup_state.setup_completed,
                    "completed_at": setup_state.completed_at,
                    "mode": "ready" if setup_state.setup_completed else "onboarding"
                },
        "connectivity": get_connectivity_state(),
        "cloud_api_alive": is_cloud_api_alive(),
        "uptime": get_uptime(),
        "disk_usage": get_disk_usage(),
        "disk": get_disk_usage(),  # keep for backward compatibility
        "temperature": get_temperature_state(),
        "plug": get_plug_state(),
        "vault": get_vault_state(),
        "vault_files": count_vault_files(),
        "nfc": _nfc_status_block(),
        "config_sync": config_sync_state,
        "last_config_sync": (
            config_sync_state.get("last_attempt_at")
            or config_sync_state.get("last_successful_sync_at")
        ),
        "plug_state": get_plug_state().get("state"),
        # Expanded synced config exposure
        "persona": {
            "assistant_name": persona.get("assistant_name"),
            "greeting": persona.get("greeting"),
            "flags": persona.get("flags", {}),
            "persona_id": persona.get("persona_id"),
            "persona_version": persona.get("persona_version"),
        },
        "behavior": {
            "feature_toggles": behavior.get("feature_toggles", {}),
            "features": behavior.get("features", {}),
            "source_toggles": behavior.get("source_toggles", {}),
            "briefing_preferences": behavior.get("briefing_preferences", {}),
            "bluetooth_pairing_instructions": behavior.get("bluetooth_pairing_instructions"),
            "music_provider": behavior.get("music_provider"),
            "survival_mode_disclosure": behavior.get("survival_mode_disclosure"),
        },
        "tuning": {
            "api_version": tuning.get("api_version"),
            "timezone": tuning.get("timezone"),
            "version": tuning.get("version"),
            "bluetooth_state": tuning.get("bluetooth_state"),
            "boot_document": tuning.get("boot_document"),
            "sync_interval_seconds": tuning.get("sync_interval_seconds"),
        },
        "tap_tags_summary": {
            "count": len(tap_tags),
            "keys": sorted(list(tap_tags.keys())),
        },

        # Backward compatibility
        "persona_greeting": config_sync_manager.get_persona_greeting(),

        "timestamp": time.time(),
        "health": {"ok": True},
        "runtime_mode": {
            "mode": runtime_mode.get("mode", current_mode),
            "manual_override": bool(runtime_mode.get("manual_override")),
            "override_active": manual_override_active(runtime_mode),
            "override_expires_at": runtime_mode.get("override_expires_at"),
            "reason": runtime_mode.get("reason"),
        },
    }

    return status
 
# ---------------------------------------------------------------------------
# Routes — Setup wizard
# ---------------------------------------------------------------------------

@app.post("/setup/complete")
def setup_complete():
    mark_setup_completed()
    return {"ok": True, "setup_completed": True}

@app.route("/")
def home():
    return redirect("/setup")


@app.route("/setup", methods=["GET", "POST"])
def setup():
    config = load_config()
    error_message = None

    if request.method == "POST":
        device_name = request.form.get("device_name", "").strip()
        wifi_ssid = request.form.get("wifi_ssid", "").strip()
        wifi_password = request.form.get("wifi_password", "").strip()

        if not device_name or not wifi_ssid or not wifi_password:
            error_message = "Please enter device name, Wi-Fi name, and password."
        else:
            try:
                cfg = load_config()
                cfg["device_name"] = device_name
                cfg["wifi_ssid"] = wifi_ssid
                save_config(cfg)

                threading.Thread(
                    target=_handoff_to_home_wifi,
                    args=(device_name, wifi_ssid, wifi_password),
                    daemon=True,
                ).start()

                return render_template(
                    "setup_switching.html",
                    local_url=get_hostname_url(),
                )
            except Exception as e:
                log.warning(f"setup.submit.failed | {e}")
                error_message = f"Setup error: {e}"

    return render_template(
        "setup.html",
        config=config,
        networks=scan_wifi_networks(),
        current_wifi=get_current_wifi(),
        error=error_message,
    )
# ---------------------------------------------------------------------------
# Routes — Status dashboard
# ---------------------------------------------------------------------------

@app.route("/status")
def status():
    return render_template("status.html", data=status_payload())

# ---------------------------------------------------------------------------
# Routes — Vault
# ---------------------------------------------------------------------------

@app.route("/vault/upload", methods=["POST"])
def upload_file():
    """
    Upload a file to the encrypted vault directory.
    Gated by Tap KEY when vault gating is enabled.
    Returns 403 + JSON on lock, not a redirect — phone browsers need
    a clear message rather than a silent redirect to an error page.
    """
    if not _vault_access_allowed():
        log.warning("vault.upload.blocked | vault locked, tap_key_gating active")
        return jsonify({
            "error":   "vault_locked",
            "message": "Tap KEY required. Tap your registered NFC key to unlock the vault.",
        }), 403

    if "file" not in request.files:
        return jsonify({"error": "no_file", "message": "No file part in request."}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "empty_filename", "message": "Filename is empty."}), 400

    filename = secure_filename(file.filename)
    os.makedirs(VAULT_DIR, exist_ok=True)
    file.save(os.path.join(VAULT_DIR, filename))
    log.info(f"vault.upload.ok | file={filename}")
    return redirect(url_for("status"))

# ---------------------------------------------------------------------------
# Routes — NFC Management API
# ---------------------------------------------------------------------------

@app.route("/nfc/tags", methods=["GET"])
def nfc_list_tags():
    """Return all registered NFC tags as JSON."""
    try:
        tags = _nfc().list_tags()
        return jsonify({"ok": True, "tags": tags})
    except Exception as e:
        log.warning(f"nfc.list_tags.error | {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/nfc/poll")
def nfc_poll():
    """
    Lightweight endpoint polled by the UI every 2 seconds.
    Returns only the NFC state the UI needs to diff — not the full
    status payload — to keep the polling overhead minimal.
    Includes a `pending` list of tags with NONE behavior that the
    user still needs to assign.
    """
    try:
        nfc      = _nfc()
        registry = nfc._load_registry()
        all_tags = list(registry.get("tags", {}).values())
        pending  = [t for t in all_tags if t.get("behavior") == "NONE"]
        assigned = [t for t in all_tags if t.get("behavior") not in ("NONE", "TAP_KEY")]
        return jsonify({
            "ok":              True,
            "tag_count":       len(all_tags),
            "pending":         pending,
            "pending_count":   len(pending),
            "assigned":        assigned,
            "tap_key_enrolled": registry.get("tap_key") is not None,
            "vault_unlocked":  nfc.is_vault_unlocked(),
        })
    except Exception as e:
        log.warning(f"nfc.poll.error | {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/nfc/tags/<uid>/rename", methods=["POST"])
def nfc_rename_tag(uid: str):
    """
    Rename a tag's display label.
    Body: { "name": "Bedside Goodnight" }
    Only touches the display name — behavior is unchanged.
    """
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name or len(name) > 64:
        return jsonify({"ok": False, "error": "name_invalid",
                        "message": "Name must be 1–64 characters."}), 400
    try:
        nfc      = _nfc()
        registry = nfc._load_registry()
        if uid not in registry.get("tags", {}):
            return jsonify({"ok": False, "error": "tag_not_found"}), 404
        registry["tags"][uid]["name"] = name
        nfc._save_registry(registry)
        log.info(f"nfc.tag_renamed | uid={uid} name={name}")
        return jsonify({"ok": True, "uid": uid, "name": name})
    except Exception as e:
        log.warning(f"nfc.rename_tag.error | uid={uid} {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/nfc/tags/<uid>/assign", methods=["POST"])
def nfc_assign_behavior(uid: str):
    """
    Assign a predefined behavior to an existing tag.
    Body: { "behavior": "GOODNIGHT" }
    TAP_KEY is not assignable here — use /nfc/tap-key/enroll.
    """
    body     = request.get_json(silent=True) or {}
    behavior = (body.get("behavior") or "").strip().upper()
    allowed  = [b for b in _nfc().BEHAVIORS if b not in ("TAP_KEY", "NONE")]

    if behavior not in allowed:
        return jsonify({
            "ok":      False,
            "error":   "behavior_invalid",
            "message": f"Must be one of: {', '.join(allowed)}",
        }), 400

    try:
        nfc      = _nfc()
        registry = nfc._load_registry()
        if uid not in registry.get("tags", {}):
            return jsonify({"ok": False, "error": "tag_not_found"}), 404
        registry["tags"][uid]["behavior"] = behavior
        nfc._save_registry(registry)
        log.info(f"nfc.behavior_assigned | uid={uid} behavior={behavior}")
        return jsonify({"ok": True, "uid": uid, "behavior": behavior})
    except Exception as e:
        log.warning(f"nfc.assign_behavior.error | uid={uid} {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/nfc/tags/<uid>", methods=["DELETE"])
def nfc_delete_tag(uid: str):
    """Remove a tag from the registry. Clears the tap_key slot if it matches."""
    try:
        removed = _nfc().remove_tag(uid)
        if not removed:
            return jsonify({"ok": False, "error": "tag_not_found"}), 404
        return jsonify({"ok": True, "uid": uid, "removed": True})
    except Exception as e:
        log.warning(f"nfc.delete_tag.error | uid={uid} {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/nfc/tap-key/enroll", methods=["POST"])
def nfc_enroll_tap_key():
    """
    Arms the NFC polling loop to register the next tag it sees as
    the Tap KEY.  Caller should instruct the user to tap within ~10s.
    """
    try:
        _nfc().start_enrollment("tap_key", "TAP_KEY", "Tap KEY")
        log.info("nfc.tap_key_enroll.started | source=web_ui")
        return jsonify({"ok": True, "message": "Enrollment active. Tap your NFC key tag now."})
    except Exception as e:
        log.warning(f"nfc.enroll_tap_key.error | {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/nfc/tap-key", methods=["DELETE"])
def nfc_remove_tap_key():
    """
    Clear the enrolled Tap KEY.
    Automatically disables vault gating to prevent the user from
    being permanently locked out after key removal.
    """
    try:
        nfc      = _nfc()
        registry = nfc._load_registry()
        uid      = registry.get("tap_key")
        if uid is None:
            return jsonify({"ok": False, "error": "no_tap_key_enrolled"}), 404

        registry["tap_key"] = None
        if uid in registry.get("tags", {}):
            del registry["tags"][uid]
        nfc._save_registry(registry)

        # Safety: always disable gating when the key is removed
        config_set("tap_key_gating", False)
        log.info(f"nfc.tap_key_removed | uid={uid} gating_disabled=True")
        return jsonify({"ok": True, "removed_uid": uid, "gating_disabled": True})
    except Exception as e:
        log.warning(f"nfc.remove_tap_key.error | {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/nfc/gating", methods=["POST"])
def nfc_set_gating():
    """
    Enable or disable Tap KEY vault gating.
    Body: { "enabled": true }

    Enabling gating when no key is enrolled returns 409 to prevent
    the user from immediately locking themselves out.
    """
    body    = request.get_json(silent=True) or {}
    enabled = bool(body.get("enabled", False))

    if enabled:
        try:
            tap_key = _nfc()._load_registry().get("tap_key")
        except Exception:
            tap_key = None
        if tap_key is None:
            return jsonify({
                "ok":      False,
                "error":   "no_tap_key_enrolled",
                "message": "Enroll a Tap KEY before enabling vault gating.",
            }), 409

    config_set("tap_key_gating", enabled)
    log.info(f"nfc.gating_set | enabled={enabled}")
    return jsonify({"ok": True, "vault_gating_enabled": enabled})

# ---------------------------------------------------------------------------
# Routes — Device API
# ---------------------------------------------------------------------------

@app.route("/device/status")
def device_status():
    return jsonify(status_payload())


@app.route("/health")
def health():
    return jsonify({"ok": True, "service": "web", "timestamp": time.time()})


# ---------------------------------------------------------------------------
# Capability stub — Phase 1.5 alignment
# Reports what hardware and software features this device supports.
# The cloud uses this to know what tools are available on this device.
# ---------------------------------------------------------------------------

@app.route("/device/config/sync", methods=["POST"])
def device_config_sync():
    try:
        result = config_sync_manager.sync_once()
        return jsonify(result)
    except Exception as e:
        log.warning(f"device.config.sync.failed error={e}")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/device/config/effective", methods=["GET"])
def device_config_effective():
    return jsonify(config_sync_manager.get_effective_config())

@app.route("/device/config/active", methods=["GET"])
def device_config_active():
    return jsonify(config_sync_manager.get_active_config())

@app.route("/device/config/debug-summary", methods=["GET"])
def device_config_debug_summary():
    effective = config_sync_manager.get_effective_config()
    return jsonify({
        "ok": True,
        "version": effective.get("version"),
        "assistant_name": effective.get("persona", {}).get("assistant_name"),
        "greeting": effective.get("persona", {}).get("greeting"),
        "music_provider": effective.get("behavior", {}).get("music_provider"),
        "survival_mode_disclosure": effective.get("behavior", {}).get("survival_mode_disclosure"),
        "timezone": effective.get("tuning", {}).get("timezone"),
        "sync_interval_seconds": effective.get("tuning", {}).get("sync_interval_seconds"),
        "tap_tag_keys": sorted(list((effective.get("tap_tags") or {}).keys())),
    })


@app.route("/device/mode", methods=["POST"])
def device_set_mode():
    body = request.get_json(silent=True) or {}
    mode = (body.get("mode") or "").strip().lower()

    if mode not in ("cloud", "survival"):
        return jsonify({"ok": False, "error": "invalid_mode"}), 400

    try:
        if mode == "survival":
            state = set_survival_mode(reason="manual_ui")
            speak("Switching to Survival Mode.")
        else:
            state = set_cloud_mode(reason="manual_ui")
            speak("Switching to Cloud Mode.")

        log.info(
            f"device.mode.set | mode={state['mode']} manual_override={state['manual_override']}"
        )
        return jsonify({
            "ok": True,
            "mode": state["mode"],
            "manual_override": state["manual_override"],
            "override_expires_at": state.get("override_expires_at"),
        })
    except Exception as e:
        log.warning(f"device.mode.set.failed error={e}")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/device/voice-trigger", methods=["POST"])
def device_voice_trigger():
    try:
        Path(MANUAL_VOICE_TRIGGER_FILE).parent.mkdir(parents=True, exist_ok=True)
        Path(MANUAL_VOICE_TRIGGER_FILE).write_text(str(time.time()), encoding="utf-8")
        log.info("device.voice_trigger.armed")
        return jsonify({"ok": True, "trigger": "manual_voice_trigger_armed"})
    except Exception as e:
        log.warning(f"device.voice_trigger.failed error={e}")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/device/capabilities")
def device_capabilities():
    """
    Phase 1.5 alignment: capability stub.
    Returns a structured report of all features this device supports,
    their current status, and the firmware/software versions.
    """
    import os

    # Check what hardware is actually connected
    nfc_connected = False
    temp_connected = False
    plug_connected = False

    try:
        from core.nfc_manager import get_manager
        nfc = get_manager()
        nfc_connected = nfc is not None
    except Exception:
        pass

    try:
        from core.temperature import read_celsius
        temp_connected = read_celsius() is not None
    except Exception:
        pass

    try:
        plug_ip = os.environ.get("TAPO_PLUG_IP", "")
        plug_connected = bool(plug_ip)
    except Exception:
        pass

    return jsonify({
        "device_id":   os.environ.get("DEVICE_NAME", "safebox-001"),
        "schema_version": "1.0",
        "firmware": {
            "safebox": "milestone-3",
            "python":  __import__("sys").version.split()[0],
        },
        "capabilities": {
            "voice": {
                "wake_word":    True,
                "stt":          True,
                "tts":          True,
                "cloud_llm":    True,
                "local_llm":    True,
            },
            "nfc": {
                "supported":    True,
                "connected":    nfc_connected,
                "tap_tags":     True,
                "tap_key":      True,
                "vault_gating": True,
            },
            "bluetooth": {
                "supported":    True,
                "a2dp_sink":    True,
                "avrcp":        True,
            },
            "smart_plug": {
                "supported":    True,
                "connected":    plug_connected,
                "protocol":     "kasa",
            },
            "temperature_sensor": {
                "supported":    True,
                "connected":    temp_connected,
                "protocol":     "1wire",
            },
            "offline_kit": {
                "supported":    True,
                "doc_count":    len(__import__("glob").glob("/opt/safebox/offline_kit/docs/*.txt")),
            },
            "vault": {
                "supported":    True,
                "voice_save":   True,
                "voice_retrieve": True,
                "tap_key_gating": True,
            },
            "survival_mode": {
                "supported":    True,
                "local_llm":    True,
                "offline_kit":  True,
            },
        },
        "timestamp": __import__("time").time(),
    })

# ---------------------------------------------------------------------------
# Dev runner  (gunicorn / systemd in production — never use debug=True)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8081, debug=False)
