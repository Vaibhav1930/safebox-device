from collections import deque
import numpy as np


class AudioRingBuffer:
    def __init__(self, max_samples: int):
        self.max_samples = max_samples
        self._buf = deque()
        self._count = 0

    def append(self, frame: np.ndarray):
        if frame is None or len(frame) == 0:
            return

        frame = np.asarray(frame, dtype=np.int16).reshape(-1)
        self._buf.append(frame)
        self._count += len(frame)

        while self._count > self.max_samples and self._buf:
            removed = self._buf.popleft()
            self._count -= len(removed)

    def clear(self):
        self._buf.clear()
        self._count = 0

    def get_audio(self) -> np.ndarray:
        if not self._buf:
            return np.zeros((0,), dtype=np.int16)
        return np.concatenate(list(self._buf), axis=0)

    def get_audio_2d(self) -> np.ndarray:
        audio = self.get_audio()
        if audio.size == 0:
            return np.zeros((0, 1), dtype=np.int16)
        return audio.reshape(-1, 1)
