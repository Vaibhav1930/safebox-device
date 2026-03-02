import os
import pvporcupine
from pathlib import Path
from core.logger import get_logger

log = get_logger("wake_word")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = PROJECT_ROOT / "models" / "wake"


MODEL_MAP = {
    "computer":     MODEL_PATH / "computer_raspberry-pi.ppn",
    "hey-clarity":  MODEL_PATH / "hey-clarity_raspberry-pi.ppn",
}


class WakeWordEngine:
    def __init__(self, keyword: str):
        if keyword not in MODEL_MAP:
            raise ValueError(
                f"Unsupported wake word: '{keyword}'. "
                f"Available: {list(MODEL_MAP.keys())}"
            )

        model_path = MODEL_MAP[keyword]

        if not model_path.exists():
            raise FileNotFoundError(
                f"Wake word model not found: {model_path}"
            )

        access_key = os.environ.get("PICOVOICE_ACCESS_KEY")
        if not access_key:
            raise EnvironmentError(
                "PICOVOICE_ACCESS_KEY is not set. "
                "Add it to /etc/safebox/safebox.env"
            )

        self.keyword = keyword
        self.porcupine = pvporcupine.create(
            access_key=access_key,
            keyword_paths=[str(model_path)],
            sensitivities=[0.90]
        )

        log.info(f"wake_word.init keyword={keyword}")

    def process_audio(self, pcm) -> bool:
        """Returns True if wake word detected in this PCM frame."""
        result = self.porcupine.process(pcm)
        detected = result >= 0
        if detected:
            log.info(f"wake_word.detected keyword={self.keyword} index={result}")
        return detected

    def cleanup(self):
        """Release native Porcupine resources."""
        if self.porcupine:
            self.porcupine.delete()
            self.porcupine = None
            log.info("wake_word.cleanup done")

    def __del__(self):
        self.cleanup()
