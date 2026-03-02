import numpy as np
import threading

class RingBuffer:
    def __init__(self, capacity_frames: int, frame_size: int):
        self.capacity = capacity_frames
        self.frame_size = frame_size

        self.buffer = np.zeros(
            (capacity_frames, frame_size),
            dtype=np.int16
        )

        self.write_idx = 0
        self.size = 0
        self.lock = threading.Lock()

    def write(self, frames: np.ndarray):
        with self.lock:
            self.buffer[self.write_idx] = frames
            self.write_idx = (self.write_idx + 1) % self.capacity
            self.size = min(self.size + 1, self.capacity)

    def read_latest(self, n_frames: int) -> np.ndarray:
        with self.lock:
            if n_frames > self.size:
                return None

            start = (self.write_idx - n_frames) % self.capacity
            if start + n_frames <= self.capacity:
                return self.buffer[start:start + n_frames].copy()
            else:
                part1 = self.buffer[start:]
                part2 = self.buffer[:n_frames - len(part1)]
                return np.vstack((part1, part2))
