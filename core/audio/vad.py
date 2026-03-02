import numpy as np
import time

class EnergyVAD:
    def __init__(
        self,
        energy_threshold: float = 650.0,
        start_frames: int = 8,
        end_frames: int = 40,
        min_speech_duration: float = 1.2,  # seconds
    ):
        self.energy_threshold = energy_threshold
        self.start_frames = start_frames
        self.end_frames = end_frames
        self.min_speech_duration = min_speech_duration

        self.in_speech = False
        self.speech_start_time = None
        self.above_count = 0
        self.below_count = 0

    def rms_energy(self, frame: np.ndarray) -> float:
        frame = frame.astype(np.float32)
        return np.sqrt(np.mean(frame * frame))

    def process(self, frame: np.ndarray) -> bool:
        energy = self.rms_energy(frame)

        if energy > self.energy_threshold:
            self.above_count += 1
            self.below_count = 0
        else:
            self.below_count += 1
            self.above_count = 0

        # Speech START
        if not self.in_speech and self.above_count >= self.start_frames:
            self.in_speech = True
            self.speech_start_time = time.time()
            print("[VAD] SPEECH_START")

        # Speech END (with hysteresis + min duration)
        if self.in_speech and self.below_count >= self.end_frames:
            duration = time.time() - self.speech_start_time
            if duration >= self.min_speech_duration:
                self.in_speech = False
                self.speech_start_time = None
                print("[VAD] SPEECH_END")

        return self.in_speech
