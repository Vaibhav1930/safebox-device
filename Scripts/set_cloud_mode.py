"""
set_cloud.py — Manually return to Cloud Mode (M4 Point 6A)
Logs the mode change so it appears in journalctl for signoff evidence.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.audio.tts_player import speak
from core.runtime_mode import set_cloud_mode
from core.logger import get_logger

log = get_logger("set_cloud")


def main() -> None:
    state = set_cloud_mode(reason="manual_cli")
    log.info(
        f"device.mode.set | mode=cloud "
        f"manual_override={state['manual_override']} reason=manual_cli"
    )
    print({"ok": True, "mode": state["mode"], "manual_override": state["manual_override"]})
    try:
        speak("Switching to Cloud Mode.")
    except Exception as e:
        log.warning(f"set_cloud.announce_failed | {e}")


if __name__ == "__main__":
    main()
