import os
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

SAFEBOX_VAULT_ROOT = os.environ.get(
    "SAFEBOX_VAULT_ROOT",
    "/mnt/ssd/safebox-device/vault"
)
DEVICE_ID = os.environ.get("DEVICE_NAME", "safebox-001")
TIMEZONE  = os.environ.get("SAFEBOX_TIMEZONE", "Asia/Kolkata")

INTERACTIONS_DIR = Path(SAFEBOX_VAULT_ROOT) / "interactions"
NOTES_DIR = Path(SAFEBOX_VAULT_ROOT) / "notes"

def ensure_vault_dirs() -> None:
    Path(SAFEBOX_VAULT_ROOT).mkdir(parents=True, exist_ok=True)
    INTERACTIONS_DIR.mkdir(parents=True, exist_ok=True)
    NOTES_DIR.mkdir(parents=True, exist_ok=True)

ensure_vault_dirs()

def save_interaction(
    user_text: str,
    assistant_text: str,
    request_id: str = None,
    mode: str = "cloud",
    latency_ms: int = None,
    audio_path: str = None,
):
    try:
        ensure_vault_dirs()
        now = datetime.now(ZoneInfo(TIMEZONE))
        date_folder = now.strftime("%Y-%m-%d")
        time_prefix = now.strftime("%H-%M-%S")

        day_path = INTERACTIONS_DIR / date_folder
        day_path.mkdir(parents=True, exist_ok=True)

        filename_base = time_prefix
        if request_id:
            filename_base += f"_{request_id[:8]}"

        json_path = day_path / f"{filename_base}.json"

        data = {
            "timestamp": now.isoformat(),
            "request_id": request_id,
            "device_id": DEVICE_ID,
            "user_text": user_text,
            "assistant_text": assistant_text,
            "mode": mode,
            "latency_ms": latency_ms,
            "audio_file": audio_path,
        }

        with open(json_path, "w") as f:
            json.dump(data, f, indent=2)

        print(f"[VAULT] Saved request_id={request_id} -> {json_path}")

        return str(json_path)

    except Exception as e:
        print("[VAULT ERROR]", e)
        raise
