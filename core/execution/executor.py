# core/execution/executor.py
# Production Grade — SafeBox M3 — Complete

import time
from core.logger import get_logger

log = get_logger("EXECUTOR")


def execute_intent(result: dict) -> str:
    intent = result.get("intent")
    log.info(f"executor.intent | intent={intent}")

    if intent == "STATUS":
        return handle_status()
    elif intent == "OPEN_BOX":
        return handle_open_box()
    elif intent == "CLOSE_BOX":
        return handle_close_box()
    elif intent == "PLUG_ON":
        return handle_plug_on()
    elif intent == "PLUG_OFF":
        return handle_plug_off()
    elif intent == "PLUG_STATUS":
        return handle_plug_status()
    elif intent == "GET_TEMPERATURE":
        return handle_temperature()
    elif intent == "GOODNIGHT":
        return handle_goodnight()
    elif intent == "BT_PAIR":
        return handle_bt_pair()
    elif intent == "BT_DISCONNECT":
        return handle_bt_disconnect()
    elif intent == "BT_STATUS":
        return handle_bt_status()
    elif intent == "PLAY_MUSIC":
        return handle_play()
    elif intent == "PAUSE_MUSIC":
        return handle_pause()
    elif intent == "NEXT_TRACK":
        return handle_next()
    elif intent == "PREV_TRACK":
        return handle_previous()
    elif intent == "VOLUME_UP":
        return handle_volume_up()
    elif intent == "VOLUME_DOWN":
        return handle_volume_down()
    elif intent == "NFC_ENROLL_ONBOARDING":
        return handle_nfc_enroll_onboarding()
    elif intent == "NFC_ENROLL_GOODNIGHT":
        return handle_nfc_enroll_goodnight()
    elif intent == "NFC_ENROLL_MORNING":
        return handle_nfc_enroll_morning()
    elif intent == "NFC_ENROLL_MUSIC":
        return handle_nfc_enroll_music()
    elif intent == "NFC_ENROLL_TAP_KEY":
        return handle_nfc_enroll_tap_key()
    elif intent == "NFC_LIST_TAGS":
        return handle_nfc_list_tags()
    elif intent == "VAULT_SAVE":
        return handle_vault_save(result.get("raw_text", ""))
    elif intent == "VAULT_RETRIEVE":
        return handle_vault_retrieve()
    else:
        log.warning(f"executor.no_handler | intent={intent}")
        return None


# ── Core ──────────────────────────────────────────────────────────────────

def handle_status() -> str:
    return "Safebox is online and locked."

def handle_open_box() -> str:
    time.sleep(0.5)
    return "Box opened."

def handle_close_box() -> str:
    time.sleep(0.5)
    return "Box closed."


# ── WS2: Smart Plug ───────────────────────────────────────────────────────

def handle_plug_on() -> str:
    try:
        from core.smart_plug import turn_on
        return turn_on()
    except Exception as e:
        log.warning(f"executor.plug_on.failed | {e}")
        return "Sorry, I couldn't turn on the plug right now."

def handle_plug_off() -> str:
    try:
        from core.smart_plug import turn_off
        return turn_off()
    except Exception as e:
        log.warning(f"executor.plug_off.failed | {e}")
        return "Sorry, I couldn't turn off the plug right now."

def handle_plug_status() -> str:
    try:
        from core.smart_plug import get_power_usage
        return get_power_usage()
    except Exception as e:
        log.warning(f"executor.plug_status.failed | {e}")
        return "Sorry, I couldn't get the plug status right now."


# ── WS2: Temperature ──────────────────────────────────────────────────────

def handle_temperature() -> str:
    try:
        from core.temperature import get_temperature_response
        return get_temperature_response()
    except Exception as e:
        log.warning(f"executor.temperature.failed | {e}")
        return "Sorry, I couldn't read the temperature sensor right now."


# ── WS2: Goodnight ────────────────────────────────────────────────────────

def handle_goodnight() -> str:
    log.info("executor.goodnight.start")
    parts = []
    try:
        from core.temperature import read_celsius
        celsius = read_celsius()
        if celsius is not None:
            parts.append(f"The room temperature is {celsius} degrees Celsius.")
        else:
            parts.append("I couldn't read the room temperature.")
    except Exception as e:
        log.warning(f"executor.goodnight.temperature.failed | {e}")
        parts.append("I couldn't read the room temperature.")
    try:
        from core.smart_plug import turn_off
        turn_off()
        parts.append("I've turned off the smart plug.")
    except Exception as e:
        log.warning(f"executor.goodnight.plug.failed | {e}")
    try:
        from core.bluetooth_manager import pause
        pause()
        parts.append("Music paused.")
    except Exception:
        pass
    parts.append("Goodnight! Sleep well.")
    return " ".join(parts)


# ── WS3: Bluetooth Pairing ────────────────────────────────────────────────

def handle_bt_pair() -> str:
    try:
        from core.bluetooth_manager import start_pairing_mode
        return start_pairing_mode()
    except Exception as e:
        log.warning(f"executor.bt_pair.failed | {e}")
        return "Sorry, I couldn't start Bluetooth pairing right now."

def handle_bt_disconnect() -> str:
    try:
        from core.bluetooth_manager import disconnect_device
        return disconnect_device()
    except Exception as e:
        log.warning(f"executor.bt_disconnect.failed | {e}")
        return "Sorry, I couldn't disconnect the phone."

def handle_bt_status() -> str:
    try:
        from core.bluetooth_manager import get_state
        state = get_state()
        if state["connected"]:
            name = state["device_name"] or "your phone"
            playing = "and music is playing" if state["playing"] else "but nothing is playing"
            return f"{name} is connected {playing}."
        return "No phone is connected. Say pair my phone to connect."
    except Exception as e:
        log.warning(f"executor.bt_status.failed | {e}")
        return "I couldn't get the Bluetooth status right now."


# ── WS3: AVRCP Playback ───────────────────────────────────────────────────

def handle_play() -> str:
    try:
        from core.bluetooth_manager import play
        return play()
    except Exception as e:
        log.warning(f"executor.play.failed | {e}")
        return "Sorry, I couldn't play music right now."

def handle_pause() -> str:
    try:
        from core.bluetooth_manager import pause
        return pause()
    except Exception as e:
        log.warning(f"executor.pause.failed | {e}")
        return "Sorry, I couldn't pause music right now."

def handle_next() -> str:
    try:
        from core.bluetooth_manager import next_track
        return next_track()
    except Exception as e:
        log.warning(f"executor.next.failed | {e}")
        return "Sorry, I couldn't skip the track."

def handle_previous() -> str:
    try:
        from core.bluetooth_manager import previous_track
        return previous_track()
    except Exception as e:
        log.warning(f"executor.previous.failed | {e}")
        return "Sorry, I couldn't go to the previous track."

def handle_volume_up() -> str:
    try:
        from core.bluetooth_manager import volume_up
        return volume_up()
    except Exception as e:
        log.warning(f"executor.volume_up.failed | {e}")
        return "Sorry, I couldn't adjust the volume."

def handle_volume_down() -> str:
    try:
        from core.bluetooth_manager import volume_down
        return volume_down()
    except Exception as e:
        log.warning(f"executor.volume_down.failed | {e}")
        return "Sorry, I couldn't adjust the volume."


# ── WS1: NFC Enrollment ───────────────────────────────────────────────────

def handle_nfc_enroll_onboarding() -> str:
    try:
        from core.nfc_manager import start_enrollment
        start_enrollment("tag", "ONBOARDING", "Onboarding")
        return "Ready to enroll onboarding tag. Tap your NFC tag now."
    except Exception as e:
        log.warning(f"executor.nfc_enroll.failed | {e}")
        return "Sorry, I couldn't start NFC enrollment right now."

def handle_nfc_enroll_goodnight() -> str:
    try:
        from core.nfc_manager import start_enrollment
        start_enrollment("tag", "GOODNIGHT", "Goodnight")
        return "Ready to enroll goodnight tag. Tap your NFC tag now."
    except Exception as e:
        log.warning(f"executor.nfc_enroll.failed | {e}")
        return "Sorry, I couldn't start NFC enrollment right now."

def handle_nfc_enroll_morning() -> str:
    try:
        from core.nfc_manager import start_enrollment
        start_enrollment("tag", "MORNING", "Morning")
        return "Ready to enroll morning tag. Tap your NFC tag now."
    except Exception as e:
        log.warning(f"executor.nfc_enroll.failed | {e}")
        return "Sorry, I couldn't start NFC enrollment right now."

def handle_nfc_enroll_music() -> str:
    try:
        from core.nfc_manager import start_enrollment
        start_enrollment("tag", "PLAY_MUSIC", "Play Music")
        return "Ready to enroll music tag. Tap your NFC tag now."
    except Exception as e:
        log.warning(f"executor.nfc_enroll.failed | {e}")
        return "Sorry, I couldn't start NFC enrollment right now."

def handle_nfc_enroll_tap_key() -> str:
    try:
        from core.nfc_manager import start_enrollment
        start_enrollment("tap_key", "TAP_KEY", "Tap KEY")
        return "Ready to enroll Tap KEY. Tap your key tag now. It will unlock your vault for 5 minutes."
    except Exception as e:
        log.warning(f"executor.nfc_tap_key.failed | {e}")
        return "Sorry, I couldn't start Tap KEY enrollment right now."

def handle_nfc_list_tags() -> str:
    try:
        from core.nfc_manager import list_tags
        tags = list_tags()
        if not tags:
            return "No NFC tags enrolled yet. Say enroll goodnight tag to get started."
        names = ", ".join(f"{t['name']} ({t['behavior']})" for t in tags)
        count = len(tags)
        return f"You have {count} tag{'s' if count > 1 else ''} enrolled: {names}."
    except Exception as e:
        log.warning(f"executor.nfc_list.failed | {e}")
        return "Sorry, I couldn't list your tags right now."


# ── Vault Voice Commands ──────────────────────────────────────────────────

def handle_vault_save(text: str) -> str:
    """
    Save a voice note to the vault.
    Strips common trigger phrases so only the actual content is stored.
    e.g. "save this to my vault — I need to buy milk" saves "I need to buy milk"
    """
    import time
    import json
    from pathlib import Path

    triggers = [
        "save this to my vault", "save to vault", "add to vault",
        "save this", "remember this", "save a note", "save note",
        "vault save", "store this", "keep this",
    ]
    content = text.strip()
    for t in triggers:
        if content.lower().startswith(t):
            content = content[len(t):].lstrip(" .,—-").strip()
            break
        elif t in content.lower():
            idx = content.lower().find(t)
            content = content[idx + len(t):].lstrip(" .,—-").strip()
            break

    if not content:
        return "What would you like me to save? Say save this to my vault followed by your note."

    try:
        vault_dir = Path("/mnt/ssd/safebox-device/vault/notes")
        vault_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y-%m-%dT%H-%M-%S")
        note_path = vault_dir / f"{timestamp}.json"
        with open(note_path, "w") as f:
            json.dump({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "content": content,
                "source": "voice",
            }, f, indent=2)
        log.info(f"vault.note_saved | path={note_path} content={content!r}")
        return f"Saved to your vault: {content}"
    except Exception as e:
        log.warning(f"vault.note_save_failed | {e}")
        return "Sorry, I couldn't save that to your vault right now."


def handle_vault_retrieve() -> str:
    """
    Read back the most recent vault notes by voice.
    Returns the last 3 notes as a spoken summary.
    """
    import json
    from pathlib import Path

    vault_dir = Path("/mnt/ssd/safebox-device/vault/notes")
    if not vault_dir.exists():
        return "Your vault is empty. Say save this to my vault followed by a note to add something."

    note_files = sorted(vault_dir.glob("*.json"), reverse=True)[:3]
    if not note_files:
        return "Your vault is empty. Say save this to my vault followed by a note to add something."

    notes = []
    for path in note_files:
        try:
            with open(path) as f:
                data = json.load(f)
            notes.append(data.get("content", "").strip())
        except Exception:
            pass

    if not notes:
        return "I couldn't read your vault notes right now."

    if len(notes) == 1:
        return f"Your most recent vault note: {notes[0]}"

    joined = ". ".join(f"Note {i+1}: {n}" for i, n in enumerate(notes))
    return f"Your last {len(notes)} vault notes. {joined}"
