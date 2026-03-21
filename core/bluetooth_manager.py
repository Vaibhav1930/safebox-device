"""
core/bluetooth_manager.py
SafeBox Bluetooth Manager — A2DP + AVRCP + Pairing + State Detection

BT-1: A2DP Sink — phone streams audio to Pi speakers via PipeWire
BT-2: AVRCP — play/pause/next/previous/volume via playerctl
BT-3: Pairing + trust + auto-reconnect
BT-4: State detection — paired/connected/playing

Wiring: PipeWire handles A2DP, playerctl handles AVRCP
"""

import subprocess
import json
import time
import os
import threading
from pathlib import Path
from core.logger import get_logger

log = get_logger("bluetooth")

BT_STATE_PATH = Path("/opt/safebox/runtime/bt_state.json")
BT_TRUSTED_PATH = Path("/opt/safebox/runtime/bt_trusted.json")

PIPEWIRE_ENV = {
    **os.environ,
    "XDG_RUNTIME_DIR": "/run/user/1000",
    "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
}


# ── State ─────────────────────────────────────────────────────────────────

def get_state() -> dict:
    try:
        if BT_STATE_PATH.exists():
            with open(BT_STATE_PATH) as f:
                return json.load(f)
    except Exception:
        pass
    return {"paired": False, "connected": False, "playing": False,
            "device_name": None, "device_mac": None, "updated_at": 0}


def _save_state(state: dict):
    try:
        BT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(BT_STATE_PATH, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log.warning(f"bt.state_save_failed | {e}")


def _detect_state() -> dict:
    state = {"paired": False, "connected": False, "playing": False,
             "device_name": None, "device_mac": None, "updated_at": time.time()}
    try:
        result = subprocess.run(
            ["bluetoothctl", "info"],
            capture_output=True, text=True, timeout=5
        )
        output = result.stdout
        if "Device" in output:
            state["paired"] = True
            if "Connected: yes" in output:
                state["connected"] = True
            for line in output.splitlines():
                if "Name:" in line:
                    state["device_name"] = line.split("Name:")[-1].strip()
                if "Device " in line and ":" in line:
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        state["device_mac"] = parts[1]
    except Exception as e:
        log.warning(f"bt.detect_state.failed | {e}")

    try:
        result = subprocess.run(
            ["playerctl", "--player=%any", "status"],
            capture_output=True, text=True, timeout=3, env=PIPEWIRE_ENV
        )
        state["playing"] = result.stdout.strip() == "Playing"
    except Exception:
        pass

    log.info(f"bt.state | {state}")
    _save_state(state)
    return state


# ── AVRCP Controls ────────────────────────────────────────────────────────

def _playerctl(cmd: str) -> bool:
    try:
        result = subprocess.run(
            ["playerctl", "--player=%any", cmd],
            capture_output=True, text=True, timeout=5, env=PIPEWIRE_ENV
        )
        success = result.returncode == 0
        log.info(f"avrcp.{cmd} | success={success}")
        return success
    except Exception as e:
        log.warning(f"avrcp.{cmd}.failed | {e}")
        return False


def play() -> str:
    state = _detect_state()
    if not state["connected"]:
        return "No phone connected. Say pair my phone to connect."
    _playerctl("play")
    return "Playing music."


def pause() -> str:
    state = _detect_state()
    if not state["connected"]:
        return "No phone connected."
    _playerctl("pause")
    return "Music paused."


def next_track() -> str:
    _playerctl("next")
    return "Next track."


def previous_track() -> str:
    _playerctl("previous")
    return "Previous track."


def volume_up() -> str:
    try:
        subprocess.run(
            ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "10%+"],
            env=PIPEWIRE_ENV, timeout=3
        )
        log.info("bt.volume_up")
        return "Volume up."
    except Exception as e:
        log.warning(f"bt.volume_up.failed | {e}")
        return "Sorry, couldn't adjust volume."


def volume_down() -> str:
    try:
        subprocess.run(
            ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "10%-"],
            env=PIPEWIRE_ENV, timeout=3
        )
        log.info("bt.volume_down")
        return "Volume down."
    except Exception as e:
        log.warning(f"bt.volume_down.failed | {e}")
        return "Sorry, couldn't adjust volume."


# ── Pairing ───────────────────────────────────────────────────────────────

def start_pairing_mode() -> str:
    try:
        subprocess.run(["bluetoothctl", "pairable", "on"], timeout=5)
        subprocess.run(["bluetoothctl", "discoverable", "on"], timeout=5)
        log.info("bt.pairing_mode.started")
        return "Pairing mode on. Open Bluetooth on your phone and connect to SafeBox."
    except Exception as e:
        log.warning(f"bt.pairing_mode.failed | {e}")
        return "Sorry, couldn't start pairing mode."


def trust_device(mac: str) -> bool:
    try:
        subprocess.run(["bluetoothctl", "trust", mac], timeout=5)
        trusted = _load_trusted()
        if mac not in trusted:
            trusted.append(mac)
            _save_trusted(trusted)
        log.info(f"bt.device_trusted | mac={mac}")
        return True
    except Exception as e:
        log.warning(f"bt.trust_failed | {e}")
        return False


def disconnect_device() -> str:
    try:
        state = get_state()
        mac = state.get("device_mac")
        if mac:
            subprocess.run(["bluetoothctl", "disconnect", mac], timeout=5)
            log.info(f"bt.disconnected | mac={mac}")
            return "Phone disconnected."
        return "No phone connected."
    except Exception as e:
        log.warning(f"bt.disconnect.failed | {e}")
        return "Sorry, couldn't disconnect."


def _load_trusted() -> list:
    try:
        if BT_TRUSTED_PATH.exists():
            with open(BT_TRUSTED_PATH) as f:
                return json.load(f)
    except Exception:
        pass
    return []


def _save_trusted(trusted: list):
    try:
        BT_TRUSTED_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(BT_TRUSTED_PATH, "w") as f:
            json.dump(trusted, f)
    except Exception as e:
        log.warning(f"bt.trusted_save_failed | {e}")


def restore_trusted_devices():
    trusted = _load_trusted()
    for mac in trusted:
        try:
            subprocess.run(["bluetoothctl", "trust", mac], timeout=5)
        except Exception:
            pass
    if trusted:
        log.info(f"bt.trusted_restored | count={len(trusted)}")


# ── State Monitor ─────────────────────────────────────────────────────────

class BTStateMonitor:
    def __init__(self, interval=10):
        self.interval = interval
        self._thread = None
        self.running = False

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while self.running:
            try:
                _detect_state()
            except Exception:
                pass
            time.sleep(self.interval)

    def stop(self):
        self.running = False
