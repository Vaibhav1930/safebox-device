import os
import pvporcupine

class WakeWordEngine:
    def __init__(self, keyword: str):
        self.keyword = keyword

        MODEL_MAP = {
            "computer": "computer.ppn",
            "hey-clarity": "hey-clarity_raspberry-pi.ppn",
        }

        if keyword not in MODEL_MAP:
            raise ValueError(f"Unsupported wake word: {keyword}")

        model_path = f"/opt/safebox/models/wake/{MODEL_MAP[keyword]}"

        if not os.path.exists(model_path):
            raise FileNotFoundError(model_path)

        self.porcupine = pvporcupine.create(
            access_key=os.environ["PICOVOICE_ACCESS_KEY"],
            keyword_paths=[model_path],
        )

    def process_audio(self, pcm):
        return self.porcupine.process(pcm) >= 0
