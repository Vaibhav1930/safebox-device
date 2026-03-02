import numpy as np
import soundfile as sf
import sounddevice as sd
import time


class SpeechRecorder:
    def __init__(self, sample_rate=16000, min_duration=0.15):
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


def read_frame(frame_length: int):
    """
    Read one PCM frame of exactly frame_length samples from the mic.
    Called by SurvivalModeController on each wake word detection cycle.
    Returns a list of int16 samples, or None if mic is unavailable.
    """
    try:
        audio = sd.rec(
            frame_length,
            samplerate=16000,
            channels=1,
            dtype='int16',
            blocking=True
        )
        return audio.flatten().tolist()
    except Exception as e:
        print(f"[REC] read_frame failed: {e}")
        return None
