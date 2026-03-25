import numpy as np


class SimpleVAD:
    """
    Slightly improved energy VAD with hysteresis.

    - speech_threshold: enter speech state above this level
    - silence_threshold: remain in speech until energy falls below this level
    - trailing_silence_frames: number of low-energy frames required to end speech
    """

    def __init__(
        self,
        speech_threshold: float = 260.0,
        silence_threshold: float = 180.0,
        trailing_silence_frames: int = 22,
        smoothing: float = 0.25,
    ):
        self.speech_threshold = speech_threshold
        self.silence_threshold = silence_threshold
        self.trailing_silence_frames = trailing_silence_frames
        self.smoothing = smoothing

        self._ema_energy = 0.0
        self._in_speech = False
        self._silence_count = 0

    def reset(self):
        self._ema_energy = 0.0
        self._in_speech = False
        self._silence_count = 0

    def energy(self, frame: np.ndarray) -> float:
        x = frame.astype(np.float32)
        rms = float(np.sqrt(np.mean(np.square(x)))) if x.size else 0.0
        self._ema_energy = (self.smoothing * rms) + ((1.0 - self.smoothing) * self._ema_energy)
        return self._ema_energy

    def is_speech(self, frame: np.ndarray) -> bool:
        e = self.energy(frame)

        if not self._in_speech:
            if e >= self.speech_threshold:
                self._in_speech = True
                self._silence_count = 0
                return True
            return False

        # already in speech
        if e < self.silence_threshold:
            self._silence_count += 1
        else:
            self._silence_count = 0

        if self._silence_count >= self.trailing_silence_frames:
            self._in_speech = False
            return False

        return True
