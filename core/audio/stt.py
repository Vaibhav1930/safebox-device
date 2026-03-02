from faster_whisper import WhisperModel

class SpeechToText:
    def __init__(self):
        self.model = WhisperModel(
            "base",
            device="cpu",
            compute_type="int8"
        )

    def transcribe(self, wav_path: str) -> str:
        segments, _ = self.model.transcribe(
            wav_path,
            language="en"
        )
        return " ".join(seg.text.strip() for seg in segments)
