import os
import numpy as np
import pvporcupine

class WakeWordEngine:
    def __init__(self, keyword="computer", sample_rate=16000):
        access_key = os.getenv("PICOVOICE_ACCESS_KEY")
        if not access_key:
            raise RuntimeError("PICOVOICE_ACCESS_KEY not set")

        if keyword != "computer":
            raise ValueError("Only 'computer' supported for now")

        # Create Porcupine FIRST
        self.porcupine = pvporcupine.create(
            access_key=access_key,
            keywords=["computer"],
        )

        # THEN read frame length
        self.frame_length = self.porcupine.frame_length
        self.sample_rate = sample_rate

        # Debug print (now safe)
        print("[WAKE] Porcupine frame length:", self.frame_length)

    def process_audio(self, audio_window: np.ndarray) -> bool:
        if audio_window.dtype != np.int16:
            audio_window = audio_window.astype(np.int16)

        num_frames = len(audio_window) // self.frame_length

        for i in range(num_frames):
            frame = audio_window[
                i * self.frame_length : (i + 1) * self.frame_length
            ]
            result = self.porcupine.process(frame)
            if result >= 0:
                return True

        return False
