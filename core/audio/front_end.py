from dataclasses import dataclass
import numpy as np

from core.audio.ring_buffer import AudioRingBuffer
from core.audio.simple_vad import SimpleVAD


@dataclass
class FrontEndConfig:
    sample_rate: int = 16000
    frame_size: int = 512
    preroll_seconds: float = 1.0
    speech_threshold: float = 260.0
    silence_threshold: float = 180.0
    trailing_silence_frames: int = 22


class FrontEnd:
    """
    Audio front-end:
    - chooses the ASR channel from XVF3800
    - maintains pre-roll buffer
    - runs VAD
    """

    def __init__(self, config: FrontEndConfig):
        self.config = config
        self.preroll = AudioRingBuffer(
            max_samples=int(config.sample_rate * config.preroll_seconds)
        )
        self.vad = SimpleVAD(
            speech_threshold=config.speech_threshold,
            silence_threshold=config.silence_threshold,
            trailing_silence_frames=config.trailing_silence_frames,
        )

    def reset_vad(self):
        self.vad.reset()

    def split_channels(self, indata: np.ndarray):
        left = indata[:, 0].astype(np.int16)
        right = indata[:, 1].astype(np.int16) if indata.shape[1] > 1 else left

        # XVF3800 USB firmware:
        # ch0 = conference
        # ch1 = ASR
        wake_pcm = right
        speech_pcm = right
        mono_record = speech_pcm.reshape(-1, 1)

        return left, right, wake_pcm, speech_pcm, mono_record

    def push_preroll(self, speech_pcm: np.ndarray):
        self.preroll.append(speech_pcm)

    def get_preroll_audio(self) -> np.ndarray:
        return self.preroll.get_audio_2d()

    def is_speech(self, speech_pcm: np.ndarray) -> bool:
        return self.vad.is_speech(speech_pcm)
