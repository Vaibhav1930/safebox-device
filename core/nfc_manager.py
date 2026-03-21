"""
core/nfc_manager.py
SafeBox NFC Manager — Production Grade

Implements:
  - PN532 SPI polling loop with debounce
  - 4 Tap TAG behaviors: ONBOARDING, GOODNIGHT, MORNING, PLAY_MUSIC
  - Tap KEY enrollment and vault gating
  - Tag registry (persistent JSON store)

Wiring: CS=GPIO4(board.D4), RST=GPIO20(board.D20), SPI standard pins
"""

import time
import json
import os
import threading
from pathlib import Path
from core.logger import get_logger

log = get_logger("nfc")

NFC_REGISTRY_PATH = Path("/mnt/ssd/safebox-device/vault/nfc_tags.json")
DEBOUNCE_SECONDS = 2.0
POLL_TIMEOUT = 0.5

BEHAVIORS = ["ONBOARDING", "GOODNIGHT", "MORNING", "PLAY_MUSIC", "TAP_KEY", "NONE"]


def _load_registry() -> dict:
    try:
        if NFC_REGISTRY_PATH.exists():
            with open(NFC_REGISTRY_PATH) as f:
                return json.load(f)
    except Exception as e:
        log.warning(f"nfc.registry_load_failed | {e}")
    return {"tags": {}, "tap_key": None}


def _save_registry(registry: dict):
    try:
        NFC_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(NFC_REGISTRY_PATH, "w") as f:
            json.dump(registry, f, indent=2)
    except Exception as e:
        log.warning(f"nfc.registry_save_failed | {e}")


def register_tag(uid: str, name: str, behavior: str) -> dict:
    registry = _load_registry()
    registry["tags"][uid] = {"uid": uid, "name": name, "behavior": behavior, "enrolled_at": time.time()}
    _save_registry(registry)
    log.info(f"nfc.tag_registered | uid={uid} name={name} behavior={behavior}")
    return registry["tags"][uid]


def enroll_tap_key(uid: str) -> bool:
    registry = _load_registry()
    registry["tap_key"] = uid
    registry["tags"][uid] = {"uid": uid, "name": "Tap KEY", "behavior": "TAP_KEY", "enrolled_at": time.time()}
    _save_registry(registry)
    log.info(f"nfc.tap_key_enrolled | uid={uid}")
    return True


def is_tap_key(uid: str) -> bool:
    return _load_registry().get("tap_key") == uid


def get_tag(uid: str) -> dict:
    return _load_registry()["tags"].get(uid)


def list_tags() -> list:
    return list(_load_registry()["tags"].values())


def remove_tag(uid: str) -> bool:
    registry = _load_registry()
    if uid in registry["tags"]:
        del registry["tags"][uid]
        if registry.get("tap_key") == uid:
            registry["tap_key"] = None
        _save_registry(registry)
        log.info(f"nfc.tag_removed | uid={uid}")
        return True
    return False


_vault_unlocked = False
_vault_unlock_time = 0
VAULT_UNLOCK_DURATION = 300


def unlock_vault():
    global _vault_unlocked, _vault_unlock_time
    _vault_unlocked = True
    _vault_unlock_time = time.time()
    log.info("nfc.vault_unlocked | duration=300s")


def is_vault_unlocked() -> bool:
    global _vault_unlocked, _vault_unlock_time
    if _vault_unlocked:
        if time.time() - _vault_unlock_time > VAULT_UNLOCK_DURATION:
            _vault_unlocked = False
            log.info("nfc.vault_lock_expired")
            return False
        return True
    return False


def _execute_behavior(behavior: str, uid: str, tag_name: str):
    log.info(f"nfc.behavior | behavior={behavior} uid={uid} tag={tag_name}")
    try:
        from core.audio.tts_player import speak
        from core.execution.executor import handle_goodnight, handle_play

        if behavior == "ONBOARDING":
            speak(
                "Welcome to SafeBox! I am Clarity, your personal AI assistant. "
                "Say Hey Clarity to talk to me. Your tag has been recognized. Setup is complete."
            )
        elif behavior == "GOODNIGHT":
            reply = handle_goodnight()
            if reply:
                speak(reply)
        elif behavior == "MORNING":
            speak("Good morning! SafeBox is online and ready. Say Hey Clarity to ask me anything. Have a great day!")
        elif behavior == "PLAY_MUSIC":
            reply = handle_play()
            if reply:
                speak(reply)
            else:
                speak("Starting music. Make sure your phone is connected via Bluetooth.")
        elif behavior == "TAP_KEY":
            unlock_vault()
            speak("Vault unlocked. You have 5 minutes of access.")
        else:
            log.warning(f"nfc.unknown_behavior | behavior={behavior}")
    except Exception as e:
        log.warning(f"nfc.behavior_failed | behavior={behavior} reason={e}")


_enrollment_mode = None
_enrollment_behavior = None
_enrollment_name = None


def start_enrollment(mode: str, behavior: str = None, name: str = None):
    global _enrollment_mode, _enrollment_behavior, _enrollment_name
    _enrollment_mode = mode
    _enrollment_behavior = behavior
    _enrollment_name = name or behavior
    log.info(f"nfc.enrollment_started | mode={mode} behavior={behavior}")


def cancel_enrollment():
    global _enrollment_mode, _enrollment_behavior, _enrollment_name
    _enrollment_mode = None
    _enrollment_behavior = None
    _enrollment_name = None
    log.info("nfc.enrollment_cancelled")


def _handle_enrollment(uid: str):
    global _enrollment_mode, _enrollment_behavior, _enrollment_name
    mode = _enrollment_mode
    behavior = _enrollment_behavior
    name = _enrollment_name
    cancel_enrollment()
    try:
        from core.audio.tts_player import speak
        if mode == "tap_key":
            enroll_tap_key(uid)
            speak("Tap KEY enrolled successfully. Tap this tag to unlock your vault.")
        elif mode == "tag":
            register_tag(uid, name or behavior, behavior)
            speak(f"Tag enrolled for {name} routine. Tap it anytime to trigger.")
    except Exception as e:
        log.warning(f"nfc.enrollment_failed | {e}")


class NFCManager:
    def __init__(self):
        self.running = False
        self._thread = None
        self._last_uid = None
        self._last_seen = 0
        self._pn532 = None

    def _init_hardware(self) -> bool:
        try:
            import board
            import busio
            from digitalio import DigitalInOut
            from adafruit_pn532.spi import PN532_SPI

            spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
            cs = DigitalInOut(board.D4)
            reset = DigitalInOut(board.D20)
            self._pn532 = PN532_SPI(spi, cs, reset=reset, debug=False)
            self._pn532.SAM_configuration()
            ic, ver, rev, support = self._pn532.firmware_version
            log.info(f"nfc.init | firmware={ver}.{rev}")
            return True
        except Exception as e:
            log.warning(f"nfc.init_failed | reason={e}")
            return False

    def _poll(self):
        log.info("nfc.polling_loop.start")
        while self.running:
            try:
                uid = self._pn532.read_passive_target(timeout=POLL_TIMEOUT)
                if uid is not None:
                    uid_hex = "".join(f"{x:02X}" for x in uid)
                    now = time.time()

                    if uid_hex == self._last_uid and (now - self._last_seen) < DEBOUNCE_SECONDS:
                        continue

                    self._last_uid = uid_hex
                    self._last_seen = now
                    log.info(f"nfc.tag_detected | uid={uid_hex}")

                    if _enrollment_mode:
                        _handle_enrollment(uid_hex)
                        continue

                    if is_tap_key(uid_hex):
                        _execute_behavior("TAP_KEY", uid_hex, "Tap KEY")
                        continue

                    tag = get_tag(uid_hex)
                    if tag:
                        _execute_behavior(tag["behavior"], uid_hex, tag["name"])
                    else:
                        log.info(f"nfc.unknown_tag | uid={uid_hex}")
                        try:
                            from core.audio.tts_player import speak
                            speak("New tag detected. Go to the SafeBox web interface to assign a behavior.")
                        except Exception:
                            pass
                else:
                    if time.time() - self._last_seen > DEBOUNCE_SECONDS:
                        self._last_uid = None
            except Exception as e:
                log.warning(f"nfc.poll_error | {e}")
                time.sleep(1)

    def start(self) -> bool:
        if self.running:
            return True
        if not self._init_hardware():
            log.warning("nfc.start_failed | hardware init failed")
            return False
        self.running = True
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()
        log.info("nfc.manager.started")
        return True

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=3)
        log.info("nfc.manager.stopped")


_manager = None

def get_manager() -> NFCManager:
    global _manager
    if _manager is None:
        _manager = NFCManager()
    return _manager
