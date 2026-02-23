import os
import pvporcupine
from pathlib import Path
class WakeWordEngine:
    def __init__(self, keyword: str):
        self.keyword = keyword

        MODEL_MAP = {
            "computer": "computer.ppn",
            "hey-clarity": "hey-clarity_raspberry-pi.ppn",
        }

        if keyword not in MODEL_MAP:
            raise ValueError(f"Unsupported wake word: {keyword}")

        

        PROJECT_ROOT = Path(__file__).resolve().parents[2]
        MODEL_PATH = PROJECT_ROOT / "models" / "wake"

        model_path = MODEL_PATH / f"{keyword}_raspberry-pi.ppn"

        if not os.path.exists(model_path):
            raise FileNotFoundError(model_path)

        self.porcupine = pvporcupine.create(
            access_key=os.environ["PICOVOICE_ACCESS_KEY"],
            keyword_paths=[model_path],
            sensitivities=[0.90]  # increase sensitivity
        )

    def process_audio(self, pcm):
        return self.porcupine.process(pcm) >= 0
