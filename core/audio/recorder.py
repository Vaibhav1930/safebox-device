import time
import numpy as np
import soundfile as sf


class SpeechRecorder:
    def __init__(self, sample_rate: int = 16000, min_duration: float = 0.60):
        self.sample_rate = sample_rate
        self.min_samples = int(sample_rate * min_duration)
        self.frames = []
        self.recording = False

    def start(self, initial_audio: np.ndarray | None = None):
        self.frames = []
        self.recording = True

        if initial_audio is not None and len(initial_audio) > 0:
            initial_audio = np.asarray(initial_audio, dtype=np.int16)
            if initial_audio.ndim == 1:
                initial_audio = initial_audio.reshape(-1, 1)
            self.frames.append(initial_audio.copy())

        print("[REC] Recording started")

    def add(self, audio: np.ndarray):
        if not self.recording:
            return

        audio = np.asarray(audio, dtype=np.int16)
        if audio.ndim == 1:
            audio = audio.reshape(-1, 1)

        self.frames.append(audio.copy())

    def stop_and_save(self):
        self.recording = False

        if not self.frames:
            print("[REC] No audio captured")
            return None

        audio = np.concatenate(self.frames, axis=0)

        if audio.shape[0] < self.min_samples:
            dur = audio.shape[0] / self.sample_rate
            print(f"[REC] Ignored (too short: {dur:.2f}s)")
            return None

        path = f"/tmp/command_{int(time.time())}.wav"
        sf.write(path, audio, self.sample_rate)
        print(f"[REC] Recording saved: {path}")
        return path
