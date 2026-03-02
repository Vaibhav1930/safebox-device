import numpy as np

class SimpleVAD:
    def __init__(self, threshold=500, silence_frames=15):
        self.threshold = threshold
        self.silence_frames = silence_frames
        self.silent_count = 0

    def is_speech(self, frame):
        energy = np.sqrt(np.mean(frame.astype(np.float32) ** 2))
        return energy > self.threshold

    def update(self, frame):
        if self.is_speech(frame):
            self.silent_count = 0
            return True
        else:
            self.silent_count += 1
            return self.silent_count < self.silence_frames
