import os
from pathlib import Path

import pvporcupine

from core.logger import get_logger

log = get_logger("wake_word")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = PROJECT_ROOT / "models" / "wake"

MODEL_MAP = {
    "computer": MODEL_PATH / "computer_raspberry-pi.ppn",
    "hey-clarity": MODEL_PATH / "hey-clarity_raspberry-pi.ppn",
}


class WakeWordEngine:
    def __init__(self, keyword: str, sensitivity: float = 0.58):
        if keyword not in MODEL_MAP:
            raise ValueError(f"Unsupported wake word: {keyword}. Available: {list(MODEL_MAP.keys())}")

        keyword_path = MODEL_MAP[keyword]
        if not keyword_path.exists():
            raise FileNotFoundError(f"Wake word model not found: {keyword_path}")

        access_key = os.environ.get("PICOVOICE_ACCESS_KEY")
        if not access_key:
            raise EnvironmentError("PICOVOICE_ACCESS_KEY is not set")

        self.keyword = keyword
        self.sensitivity = sensitivity
        self.porcupine = pvporcupine.create(
            access_key=access_key,
            keyword_paths=[str(keyword_path)],
            sensitivities=[self.sensitivity],
        )

        log.info(f"wake_word.init keyword={keyword} sensitivity={self.sensitivity}")

    @property
    def frame_length(self) -> int:
        return self.porcupine.frame_length

    def process_audio(self, pcm) -> bool:
        result = self.porcupine.process(pcm)
        detected = result >= 0
        if detected:
            log.info(f"wake_word.detected keyword={self.keyword}")
        return detected

    def cleanup(self):
        if getattr(self, "porcupine", None) is not None:
            self.porcupine.delete()
            self.porcupine = None
            log.info("wake_word.cleanup done")

    def __del__(self):
        self.cleanup()
