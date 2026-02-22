import subprocess
import tempfile
import threading
import os

PIPER_BIN = "/opt/piper/piper/piper"
PIPER_MODEL = "/opt/piper/models/en_US-lessac-medium.onnx"
OUTPUT_DEVICE = "plughw:2,0"

_current_player = None
_lock = threading.Lock()


def stop_audio():
    global _current_player
    with _lock:
        if _current_player and _current_player.poll() is None:
            _current_player.terminate()
        _current_player = None


def speak(text: str):
    global _current_player

    if not text:
        return

    stop_audio()

    try:
        print("[TTS] Generating speech...")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            wav_path = tmp.name

        subprocess.run(
            [PIPER_BIN, "--model", PIPER_MODEL, "--output_file", wav_path],
            input=text.encode("utf-8"),
            check=True,
        )

        print("[TTS] Playing audio...")

        with _lock:
            _current_player = subprocess.Popen(
                ["aplay", "-D", OUTPUT_DEVICE, wav_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    except Exception as e:
        print("[TTS ERROR]", e)
