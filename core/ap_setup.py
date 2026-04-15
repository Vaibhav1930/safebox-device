from __future__ import annotations

import subprocess
from dataclasses import dataclass

from core.logger import get_logger

log = get_logger("ap_setup")

AP_CONNECTION_NAME = "SafeBox-Setup"
AP_SSID = "SafeBox-Setup"
AP_PASSWORD = "safeboxsetup"


@dataclass
class APStatus:
    active: bool
    ssid: str
    connection_name: str


def _run(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    if cmd and cmd[0] == "nmcli":
        cmd = ["sudo"] + cmd
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def get_active_wifi_connection_name() -> str | None:
    try:
        result = _run(["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"])
        for line in result.stdout.strip().splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[2] == "wlan0" and parts[1] in ("wifi", "802-11-wireless"):
                return parts[0]
    except Exception as e:
        log.warning(f"ap.active_wifi.failed | {e}")
    return None


def hotspot_is_active() -> bool:
    return get_active_wifi_connection_name() == AP_CONNECTION_NAME


def ensure_hotspot() -> APStatus:
    if hotspot_is_active():
        log.info("ap.ensure_hotspot.already_active")
        return APStatus(True, AP_SSID, AP_CONNECTION_NAME)

    active = get_active_wifi_connection_name()
    if active and active != AP_CONNECTION_NAME:
        down = _run(["nmcli", "connection", "down", active], timeout=20)
        if down.returncode != 0:
            raise RuntimeError(f"Failed to bring down active Wi-Fi connection {active}: {down.stderr.strip()}")
        log.info(f"ap.client_connection_down name={active}")

    _run(["nmcli", "connection", "delete", AP_CONNECTION_NAME], timeout=15)

    add = _run([
        "nmcli", "connection", "add",
        "type", "wifi",
        "ifname", "wlan0",
        "con-name", AP_CONNECTION_NAME,
        "autoconnect", "no",
        "ssid", AP_SSID,
    ], timeout=20)
    if add.returncode != 0:
        raise RuntimeError(f"Failed to add hotspot profile: {add.stderr.strip()}")

    _run(["nmcli", "connection", "modify", AP_CONNECTION_NAME, "802-11-wireless.mode", "ap"], timeout=15)
    _run(["nmcli", "connection", "modify", AP_CONNECTION_NAME, "802-11-wireless.band", "bg"], timeout=15)
    _run(["nmcli", "connection", "modify", AP_CONNECTION_NAME, "wifi-sec.key-mgmt", "wpa-psk"], timeout=15)
    _run(["nmcli", "connection", "modify", AP_CONNECTION_NAME, "wifi-sec.psk", AP_PASSWORD], timeout=15)
    _run(["nmcli", "connection", "modify", AP_CONNECTION_NAME, "ipv4.method", "shared"], timeout=15)
    _run(["nmcli", "connection", "modify", AP_CONNECTION_NAME, "ipv6.method", "ignore"], timeout=15)

    up = _run(["nmcli", "connection", "up", AP_CONNECTION_NAME], timeout=40)
    if up.returncode != 0:
        raise RuntimeError(f"Failed to start hotspot: {up.stderr.strip()}")

    log.info(f"ap.started ssid={AP_SSID}")
    return APStatus(True, AP_SSID, AP_CONNECTION_NAME)


def stop_hotspot() -> None:
    try:
        _run(["nmcli", "connection", "down", AP_CONNECTION_NAME], timeout=20)
        _run(["nmcli", "connection", "delete", AP_CONNECTION_NAME], timeout=20)
        log.info("ap.stopped")
    except Exception as e:
        log.warning(f"ap.stop_failed | {e}")
