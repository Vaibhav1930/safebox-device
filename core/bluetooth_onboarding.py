"""
bluetooth_onboarding.py
SafeBox Bluetooth onboarding service.

Purpose:
- During fresh setup, accept Wi-Fi credentials over Bluetooth RFCOMM.
- Save config, join the requested Wi-Fi, and return handoff info.
- Keep networking logic centralized and explicit.

Protocol:
- Client sends one JSON line terminated by '\n':
  {
    "device_name": "safebox-001",
    "wifi_ssid": "HomeWiFi",
    "wifi_password": "supersecret"
  }

- Server responds with one JSON line:
  {
    "ok": true,
    "message": "Setup complete",
    "local_url": "http://raspberrypi.local:8081/status",
    "fallback_ip": "10.151.5.195"
  }
"""

from __future__ import annotations

import json
import socket
import subprocess
import threading
import time
from pathlib import Path

from core.audio.tts_player import speak
from core.logger import get_logger
from core.onboarding_state import (
    get_hostname_url,
    is_setup_complete,
    setup_complete_message,
)

log = get_logger("bt_onboarding")

PROJECT_ROOT = Path("/opt/safebox")
CONFIG_FILE = PROJECT_ROOT / "config" / "device_config.json"

SERVICE_NAME = "SafeBox Setup"
SERVICE_UUID = "94f39d29-7d6d-437d-973b-fba39e49d4ee"
RFCOMM_PORT = 3

_server_thread: threading.Thread | None = None
_stop_event = threading.Event()


def load_config() -> dict:
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_config(data: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def validate_ssid(ssid: str) -> bool:
    return bool(ssid and len(ssid) <= 32 and not any(c in ssid for c in [";", "|", "&", "`", "$"]))


def get_primary_ip() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def verify_wifi_connected(expected_ssid: str) -> bool:
    try:
        result = subprocess.run(
            ["sudo", "nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        for line in result.stdout.strip().splitlines():
            if line.startswith("yes:") and line.split(":", 1)[1] == expected_ssid:
                return True
    except Exception as e:
        log.warning(f"wifi.verify.failed | {e}")
    return False


def stop_hotspot_if_running() -> None:
    try:
        subprocess.run(
            ["sudo", "nmcli", "connection", "down", "SafeBox-Setup"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception as e:
        log.warning(f"bt_onboarding.hotspot_down.failed | {e}")


def connect_wifi(ssid: str, password: str) -> tuple[bool, str]:
    if not validate_ssid(ssid):
        return False, "Invalid SSID"

    stop_hotspot_if_running()

    try:
        result = subprocess.run(
            ["sudo", "nmcli", "dev", "wifi", "connect", ssid, "password", password],
            capture_output=True,
            text=True,
            timeout=40,
        )
        if result.returncode != 0:
            return False, result.stderr.strip() or "Failed to connect to Wi-Fi"

        # Give NetworkManager a moment to settle.
        time.sleep(3)

        if not verify_wifi_connected(ssid):
            return False, "Wi-Fi command succeeded but join could not be verified"

        return True, "connected"
    except subprocess.TimeoutExpired:
        return False, "Wi-Fi connection timed out"
    except Exception as e:
        return False, str(e)


def apply_provisioning(payload: dict) -> dict:
    device_name = str(payload.get("device_name", "")).strip()
    wifi_ssid = str(payload.get("wifi_ssid", "")).strip()
    wifi_password = str(payload.get("wifi_password", "")).strip()

    if not device_name:
        return {"ok": False, "error": "device_name_required"}
    if not validate_ssid(wifi_ssid):
        return {"ok": False, "error": "wifi_ssid_invalid"}
    if not wifi_password:
        return {"ok": False, "error": "wifi_password_required"}

    cfg = load_config()
    cfg["device_name"] = device_name
    cfg["wifi_ssid"] = wifi_ssid
    save_config(cfg)

    ok, detail = connect_wifi(wifi_ssid, wifi_password)
    if not ok:
        return {"ok": False, "error": "wifi_connect_failed", "detail": detail}

    try:
        speak(setup_complete_message())
    except Exception as e:
        log.warning(f"bt_onboarding.setup_complete_announce_failed | {e}")

    return {
        "ok": True,
        "message": "Setup complete",
        "local_url": get_hostname_url(),
        "fallback_ip": get_primary_ip(),
    }


def _handle_client(sock) -> None:
    try:
        data = b""
        while not data.endswith(b"\n"):
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk

        raw = data.decode("utf-8", errors="replace").strip()
        log.info(f"bt_onboarding.client_payload_received bytes={len(raw)}")

        try:
            payload = json.loads(raw)
        except Exception:
            response = {"ok": False, "error": "invalid_json"}
            sock.sendall((json.dumps(response) + "\n").encode("utf-8"))
            return

        response = apply_provisioning(payload)
        sock.sendall((json.dumps(response) + "\n").encode("utf-8"))
    except Exception as e:
        log.warning(f"bt_onboarding.client_failed | {e}")
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _server_loop() -> None:
    try:
        from bluetooth import (
            BluetoothSocket,
            RFCOMM,
            SERIAL_PORT_CLASS,
            SERIAL_PORT_PROFILE,
            advertise_service,
        )
    except Exception as e:
        log.error(f"bt_onboarding.import_failed | {e}")
        return

    server = None
    try:
        server = BluetoothSocket(RFCOMM)
        server.bind(("", RFCOMM_PORT))
        server.listen(1)

        advertise_service(
            server,
            SERVICE_NAME,
            service_id=SERVICE_UUID,
            service_classes=[SERVICE_UUID, SERIAL_PORT_CLASS],
            profiles=[SERIAL_PORT_PROFILE],
        )

        log.info(f"bt_onboarding.server_started port={RFCOMM_PORT} name={SERVICE_NAME}")

        while not _stop_event.is_set():
            try:
                server.settimeout(1.0)
                client_sock, client_info = server.accept()
                log.info(f"bt_onboarding.client_connected addr={client_info}")
                _handle_client(client_sock)
            except OSError:
                continue
            except Exception as e:
                log.warning(f"bt_onboarding.accept_failed | {e}")
    except Exception as e:
        log.error(f"bt_onboarding.server_failed | {e}")
    finally:
        if server is not None:
            try:
                server.close()
            except Exception:
                pass
        log.info("bt_onboarding.server_stopped")


def start_bluetooth_onboarding() -> None:
    global _server_thread

    if is_setup_complete():
        log.info("bt_onboarding.not_started setup_complete=true")
        return

    if _server_thread and _server_thread.is_alive():
        log.info("bt_onboarding.already_running")
        return

    _stop_event.clear()
    _server_thread = threading.Thread(
        target=_server_loop,
        daemon=True,
        name="safebox-bt-onboarding",
    )
    _server_thread.start()
    log.info("bt_onboarding.thread_started")


def stop_bluetooth_onboarding() -> None:
    _stop_event.set()
    log.info("bt_onboarding.stop_requested")
