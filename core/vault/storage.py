import os
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

SAFEBOX_VAULT_ROOT = os.environ.get(
    "SAFEBOX_VAULT_ROOT",
    "/mnt/ssd/safebox-device/vault"
)

INTERACTIONS_DIR = Path(SAFEBOX_VAULT_ROOT) / "interactions"
INTERACTIONS_DIR.mkdir(parents=True, exist_ok=True)


def save_interaction(
    user_text: str,
    assistant_text: str,
    request_id: str = None,
    mode: str = "cloud",
    latency_ms: int = None,
    audio_path: str = None,
):
    try:
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
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
            "device_id": "safebox-001",
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
