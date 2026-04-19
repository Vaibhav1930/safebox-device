from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SETUP_STATE_PATH = Path("/var/lib/safebox/setup_state.json")


@dataclass
class SetupState:
    setup_completed: bool = False
    completed_at: str | None = None
    setup_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "setup_completed": self.setup_completed,
            "completed_at": self.completed_at,
            "setup_version": self.setup_version,
        }


def _default_state() -> SetupState:
    return SetupState(setup_completed=False, completed_at=None, setup_version=1)


def ensure_setup_state_file() -> None:
    SETUP_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not SETUP_STATE_PATH.exists():
        state = _default_state()
        SETUP_STATE_PATH.write_text(json.dumps(state.to_dict(), indent=2) + "\n")


def load_setup_state() -> SetupState:
    ensure_setup_state_file()
    try:
        raw = json.loads(SETUP_STATE_PATH.read_text())
        return SetupState(
            setup_completed=bool(raw.get("setup_completed", False)),
            completed_at=raw.get("completed_at"),
            setup_version=int(raw.get("setup_version", 1)),
        )
    except Exception:
        state = _default_state()
        SETUP_STATE_PATH.write_text(json.dumps(state.to_dict(), indent=2) + "\n")
        return state


def save_setup_state(state: SetupState) -> None:
    SETUP_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETUP_STATE_PATH.write_text(json.dumps(state.to_dict(), indent=2) + "\n")


def mark_setup_completed() -> None:
    state = load_setup_state()
    state.setup_completed = True
    state.completed_at = datetime.now(timezone.utc).isoformat()
    save_setup_state(state)


def mark_setup_incomplete() -> None:
    state = _default_state()
    save_setup_state(state)


def is_setup_completed() -> bool:
    return load_setup_state().setup_completed
