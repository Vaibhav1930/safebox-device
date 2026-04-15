from __future__ import annotations

import json
import socket
from pathlib import Path

PROJECT_ROOT = Path("/opt/safebox")
CONFIG_FILE = PROJECT_ROOT / "config" / "device_config.json"


def load_config() -> dict:
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def is_setup_complete() -> bool:
    cfg = load_config()
    device_name = str(cfg.get("device_name", "")).strip()
    wifi_ssid = str(cfg.get("wifi_ssid", "")).strip()
    return bool(device_name and wifi_ssid)


def get_hostname_url() -> str:
    hostname = socket.gethostname().strip() or "raspberrypi"
    return f"http://{hostname}.local:8081/status"


def onboarding_message() -> str:
    if is_setup_complete():
        return "Hello. SafeBox is ready."
    return (
        "Hello. SafeBox is ready for setup. "
        "Connect to the SafeBox Setup Wi Fi network. "
        "Then open the setup page on your laptop."
    )


def setup_complete_message() -> str:
    hostname = socket.gethostname().strip() or "raspberrypi"
    spoken_host = hostname.replace("-", " dash ")
    return (
        "Setup complete. SafeBox has joined your home Wi Fi. "
        f"Reconnect your laptop to your home Wi Fi, then open {spoken_host} dot local colon 8081 slash status."
    )
