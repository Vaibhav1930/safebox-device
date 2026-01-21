import sounddevice as sd
import numpy as np

DEVICE_INDEX = None  # set this
SAMPLE_RATE = 16000
CHANNELS = 1
DURATION = 3

print("Recording...")
audio = sd.rec(
    int(DURATION * SAMPLE_RATE),
    samplerate=SAMPLE_RATE,
    channels=CHANNELS,
    dtype="int16",
    device=DEVICE_INDEX
)
sd.wait()
print("Done. Frames:", audio.shape)
