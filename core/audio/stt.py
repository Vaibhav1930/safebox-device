from faster_whisper import WhisperModel


class SpeechToText:
    def __init__(self):
        self.model = WhisperModel(
            "tiny.en",
            device="cpu",
            compute_type="int8"
        )

    def transcribe(self, wav_path: str) -> str:
        segments, _ = self.model.transcribe(
            wav_path,
            language="en",
            beam_size=1,
            best_of=1,
            vad_filter=False
        )
        return " ".join(seg.text.strip() for seg in segments).strip()
