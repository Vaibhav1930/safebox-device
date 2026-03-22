"""
core/nfc_manager.py
SafeBox NFC Manager — Production Grade

Implements:
  - PN532 SPI polling loop with debounce
  - 4 Tap TAG behaviors: ONBOARDING, GOODNIGHT, MORNING, PLAY_MUSIC
  - Tap KEY enrollment and vault gating
  - Tag registry (persistent JSON store)

Wiring: CS=GPIO4(board.D4), RST=GPIO20(board.D20), SPI standard pins

Cross-process enrollment:
  safebox-web  (Flask)  calls start_enrollment() from a browser request.
  safebox-device        runs the NFC polling loop.
  These are two separate OS processes with no shared memory.

  Enrollment state is therefore persisted to ENROLLMENT_FLAG_PATH on disk.
  Both processes read the same file so the polling loop sees the flag the
  moment the web process writes it — no IPC, no sockets, no shared memory.
"""

import time
import json
import os
import threading
from pathlib import Path
from core.logger import get_logger

log = get_logger("nfc")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

NFC_REGISTRY_PATH   = Path("/mnt/ssd/safebox-device/vault/nfc_tags.json")
ENROLLMENT_FLAG_PATH = Path("/mnt/ssd/safebox-device/vault/nfc_enrollment.json")

DEBOUNCE_SECONDS    = 2.0
POLL_TIMEOUT        = 0.5

BEHAVIORS = ["ONBOARDING", "GOODNIGHT", "MORNING", "PLAY_MUSIC", "TAP_KEY", "NONE"]

# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------

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
    registry["tags"][uid] = {
        "uid": uid, "name": name,
        "behavior": behavior, "enrolled_at": time.time(),
    }
    _save_registry(registry)
    log.info(f"nfc.tag_registered | uid={uid} name={name} behavior={behavior}")
    return registry["tags"][uid]


def enroll_tap_key(uid: str) -> bool:
    registry = _load_registry()
    registry["tap_key"] = uid
    registry["tags"][uid] = {
        "uid": uid, "name": "Tap KEY",
        "behavior": "TAP_KEY", "enrolled_at": time.time(),
    }
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

# ---------------------------------------------------------------------------
# Vault unlock state
# NOTE: This is intentionally in-memory only — vault unlock is a temporary
# session grant that should NOT persist across process restarts.
# The web process checks is_vault_unlocked() by reading the registry file
# for tap_key presence, so this in-memory state only matters inside the
# device process where unlock_vault() is actually called.
# ---------------------------------------------------------------------------

_vault_unlocked    = False
_vault_unlock_time = 0

# Vault unlock state file — shared across processes (web + wake)
VAULT_UNLOCK_STATE_PATH = Path("/mnt/ssd/safebox-device/vault/vault_unlock_state.json")
VAULT_UNLOCK_DURATION = 300


def unlock_vault():
    global _vault_unlocked, _vault_unlock_time
    _vault_unlocked    = True
    _vault_unlock_time = time.time()
    log.info("nfc.vault_unlocked | duration=300s")
    # Write unlock state to file so web process can read it cross-process
    try:
        VAULT_UNLOCK_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(VAULT_UNLOCK_STATE_PATH, "w") as f:
            json.dump({"unlocked": True, "unlock_time": _vault_unlock_time}, f)
    except Exception as e:
        log.warning(f"nfc.vault_unlock_state_write_failed | {e}")


def is_vault_unlocked() -> bool:
    global _vault_unlocked, _vault_unlock_time

    # Check in-memory first (same process — fast path)
    if _vault_unlocked:
        if time.time() - _vault_unlock_time > VAULT_UNLOCK_DURATION:
            _vault_unlocked = False
            try:
                if VAULT_UNLOCK_STATE_PATH.exists():
                    VAULT_UNLOCK_STATE_PATH.unlink()
            except Exception:
                pass

    # Cross-process fallback — read state file (web process calling into nfc module)
    if not _vault_unlocked and VAULT_UNLOCK_STATE_PATH.exists():
        try:
            with open(VAULT_UNLOCK_STATE_PATH) as f:
                state = json.load(f)
            unlock_time = state.get("unlock_time", 0)
            if state.get("unlocked") and time.time() - unlock_time <= VAULT_UNLOCK_DURATION:
                return True
            else:
                VAULT_UNLOCK_STATE_PATH.unlink(missing_ok=True)
        except Exception:
            pass
            log.info("nfc.vault_lock_expired")
            return False
        return True
    return False

# ---------------------------------------------------------------------------
# Enrollment flag — file-based so both processes share state
# ---------------------------------------------------------------------------

def _load_enrollment() -> dict:
    """
    Read the enrollment flag from disk.
    Returns {"mode": None} when no enrollment is active.
    Both safebox-web and safebox-device call this — never read the old
    module-level globals directly.
    """
    try:
        if ENROLLMENT_FLAG_PATH.exists():
            with open(ENROLLMENT_FLAG_PATH) as f:
                data = json.load(f)
            # Treat stale flags (older than 60s) as expired so a crashed
            # web process can never leave the device permanently in enroll mode.
            if time.time() - data.get("armed_at", 0) > 60:
                _clear_enrollment_flag()
                return {"mode": None}
            return data
    except Exception as e:
        log.warning(f"nfc.enrollment_flag_load_failed | {e}")
    return {"mode": None}


def _write_enrollment_flag(mode: str, behavior: str = None, name: str = None):
    try:
        ENROLLMENT_FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(ENROLLMENT_FLAG_PATH, "w") as f:
            json.dump({
                "mode":     mode,
                "behavior": behavior,
                "name":     name or behavior,
                "armed_at": time.time(),
            }, f)
    except Exception as e:
        log.warning(f"nfc.enrollment_flag_write_failed | {e}")


def _clear_enrollment_flag():
    try:
        if ENROLLMENT_FLAG_PATH.exists():
            ENROLLMENT_FLAG_PATH.unlink()
    except Exception as e:
        log.warning(f"nfc.enrollment_flag_clear_failed | {e}")


def start_enrollment(mode: str, behavior: str = None, name: str = None):
    """
    Arm enrollment mode.  Called by the web process (safebox-web) when the
    user clicks "Enroll" in the browser.  Writes a flag file so the device
    process polling loop picks it up on the next tick.
    """
    _write_enrollment_flag(mode, behavior, name)
    log.info(f"nfc.enrollment_started | mode={mode} behavior={behavior}")


def cancel_enrollment():
    """Disarm enrollment mode and remove the flag file."""
    _clear_enrollment_flag()
    log.info("nfc.enrollment_cancelled")


def _handle_enrollment(uid: str, flag: dict):
    """
    Called by the polling loop when enrollment is active and a tag is tapped.
    Clears the flag file first so subsequent taps are treated normally even
    if the write or speak below takes time.

    flag — the dict returned by _load_enrollment(), passed in to avoid a
           second file read inside the hot polling loop.
    """
    mode     = flag.get("mode")
    behavior = flag.get("behavior")
    name     = flag.get("name") or behavior

    # Disarm immediately — do this before any I/O so a crash mid-enrollment
    # doesn't leave the device permanently armed.
    _clear_enrollment_flag()
    log.info(f"nfc.enrollment_flag_cleared | uid={uid}")

    # ── Step 1: persist to registry — isolated from TTS ──────────────────
    speech_text = None
    try:
        if mode == "tap_key":
            enroll_tap_key(uid)
            speech_text = "Tap KEY enrolled successfully. Tap this tag to unlock your vault."
            log.info(f"nfc.enrollment_complete | mode=tap_key uid={uid}")
        elif mode == "tag":
            register_tag(uid, name, behavior)
            speech_text = f"Tag enrolled for {name} routine. Tap it anytime to trigger."
            log.info(f"nfc.enrollment_complete | mode=tag uid={uid} behavior={behavior}")
        else:
            log.warning(f"nfc.enrollment_unknown_mode | mode={mode}")
            return
    except Exception as e:
        log.warning(f"nfc.enrollment_write_failed | mode={mode} uid={uid} reason={e}")
        return

    # ── Step 2: speak confirmation — failure here is non-fatal ───────────
    try:
        from core.audio.tts_player import speak
        speak(speech_text)
    except Exception as e:
        log.warning(f"nfc.enrollment_speak_failed | {e}")

# ---------------------------------------------------------------------------
# Behavior executor
# ---------------------------------------------------------------------------

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
        elif behavior == "NONE":
            # Tag is registered but has no behavior assigned yet — guide user to UI.
            try:
                speak("This tag has no behavior assigned. Check the SafeBox web interface to set one.")
            except Exception:
                pass
        else:
            log.warning(f"nfc.unknown_behavior | behavior={behavior}")
    except Exception as e:
        log.warning(f"nfc.behavior_failed | behavior={behavior} reason={e}")

# ---------------------------------------------------------------------------
# NFCManager — polling loop
# ---------------------------------------------------------------------------

class NFCManager:
    def __init__(self):
        self.running    = False
        self._thread    = None
        self._last_uid  = None
        self._last_seen = 0
        self._pn532     = None

    def _init_hardware(self) -> bool:
        try:
            import board
            import busio
            from digitalio import DigitalInOut
            from adafruit_pn532.spi import PN532_SPI

            spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
            cs  = DigitalInOut(board.D4)
            rst = DigitalInOut(board.D20)
            self._pn532 = PN532_SPI(spi, cs, reset=rst, debug=False)
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
                    now     = time.time()

                    # Debounce — ignore same UID within window
                    if uid_hex == self._last_uid and (now - self._last_seen) < DEBOUNCE_SECONDS:
                        continue

                    self._last_uid  = uid_hex
                    self._last_seen = now
                    log.info(f"nfc.tag_detected | uid={uid_hex}")

                    # ── Check enrollment flag from disk ──────────────────
                    # Read once per detected tag — not on every poll tick —
                    # so the file I/O only happens when a tag is actually present.
                    flag = _load_enrollment()
                    if flag.get("mode"):
                        _handle_enrollment(uid_hex, flag)
                        continue

                    # ── Normal tag dispatch ──────────────────────────────
                    if is_tap_key(uid_hex):
                        _execute_behavior("TAP_KEY", uid_hex, "Tap KEY")
                        continue

                    tag = get_tag(uid_hex)
                    if tag:
                        _execute_behavior(tag["behavior"], uid_hex, tag["name"])
                    else:
                        # Unknown tag — register as NONE so it appears in
                        # the Web UI immediately without a page reload.
                        register_tag(uid_hex, f"Tag {uid_hex[-4:]}", "NONE")
                        log.info(f"nfc.unknown_tag.registered | uid={uid_hex}")
                        try:
                            from core.audio.tts_player import speak
                            speak("New tag detected. Check the SafeBox web interface to assign a behavior.")
                        except Exception:
                            pass

                else:
                    # No tag present — reset debounce UID after window expires
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
        self.running  = True
        self._thread  = threading.Thread(target=self._poll, daemon=True)
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
