import os
import json
from datetime import datetime

VAULT_BASE = "/opt/safebox/vault/interactions"


def save_interaction(user_text: str,
                     assistant_text: str,
                     request_id: str = None,
                     mode: str = "cloud",
                     latency_ms: int = None):
    """
    Saves conversation interaction to local Vault.
    """

    os.makedirs(VAULT_BASE, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}.json"
    path = os.path.join(VAULT_BASE, filename)

    data = {
        "timestamp_utc": datetime.utcnow().isoformat(),
        "mode": mode,
        "request_id": request_id,
        "latency_ms": latency_ms,
        "user": user_text,
        "assistant": assistant_text
    }

    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"[VAULT] Saved interaction ? {filename}")
