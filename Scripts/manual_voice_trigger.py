"""
trigger_voice.py — Arm the manual voice trigger (M4 Point 6B)
Creates the sentinel file that mic_stream picks up on the next
audio frame, starting the voice loop without a wake word.
Logs the trigger so it appears in journalctl for signoff evidence.
"""

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.logger import get_logger

log = get_logger("trigger_voice")

TRIGGER_FILE = Path("/opt/safebox/runtime/manual_voice_trigger")


def main() -> None:
    TRIGGER_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRIGGER_FILE.write_text(str(time.time()), encoding="utf-8")
    log.info("manual.voice_trigger.armed | trigger_file written")
    print({"ok": True, "trigger": "manual_voice_trigger_armed"})


if __name__ == "__main__":
    main()
