import numpy as np
import soundfile as sf
import time


class SpeechRecorder:
    def __init__(self, sample_rate=16000, min_duration=0.5):
        self.sample_rate = sample_rate
        self.min_samples = int(min_duration * sample_rate)
        self.frames = []
        self.recording = False

    def start(self):
        self.frames = []
        self.recording = True
        print("[REC] Recording started")

    def add(self, audio: np.ndarray):
        if self.recording:
            self.frames.append(audio.copy())

    def stop_and_save(self):
        self.recording = False

        if not self.frames:
            print("[REC] No audio captured")
            return None

        audio = np.concatenate(self.frames, axis=0)

        if len(audio) < self.min_samples:
            duration = len(audio) / self.sample_rate
            print(f"[REC] Ignored (too short: {duration:.2f}s)")
            return None

        filename = f"/tmp/command_{int(time.time())}.wav"
        sf.write(filename, audio, self.sample_rate)

        print(f"[REC] Recording saved: {filename}")
        return filename
