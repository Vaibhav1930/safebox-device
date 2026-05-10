import os
import subprocess
import threading
import hashlib
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

PIPER_BIN = BASE_DIR / "piper" / "venv" / "bin" / "piper"
PIPER_MODEL = BASE_DIR / "models" / "piper" / "en_US-lessac-low.onnx"
OUTPUT_DEVICE = os.getenv("AUDIO_OUTPUT_DEVICE", "plughw:2,0")

TTS_CACHE_DIR = Path(os.getenv("TTS_CACHE_DIR", "/opt/safebox/runtime/tts_cache"))
TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_current_player = None
_lock = threading.Lock()


def stop_audio():
    global _current_player
    with _lock:
        if _current_player and _current_player.poll() is None:
            _current_player.terminate()
        _current_player = None


def _cache_path(text: str) -> Path:
    key = hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:16]
    return TTS_CACHE_DIR / f"{key}.wav"


def speak(text: str):
    global _current_player

    if not text:
        return

    text = text.strip()
    stop_audio()

    try:
        wav_path = _cache_path(text)

        if not wav_path.exists():
            print("[TTS] Generating speech...")
            subprocess.run(
                [
                    str(PIPER_BIN),
                    "--model",
                    str(PIPER_MODEL),
                    "--output_file",
                    str(wav_path),
                ],
                input=text.encode("utf-8"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
        else:
            print("[TTS] Using cached speech...")

        print("[TTS] Playing audio...")

        with _lock:
            _current_player = subprocess.Popen(
                ["aplay", "-D", OUTPUT_DEVICE, str(wav_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    except Exception as e:
        print("[TTS ERROR]", e)
