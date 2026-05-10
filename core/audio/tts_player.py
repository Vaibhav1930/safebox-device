import os
import re
import time
import queue
import hashlib
import subprocess
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

PIPER_BIN = BASE_DIR / "piper" / "venv" / "bin" / "piper"
PIPER_MODEL = BASE_DIR / "models" / "piper" / "en_US-lessac-low.onnx"
OUTPUT_DEVICE = os.getenv("AUDIO_OUTPUT_DEVICE", "plughw:2,0")

TTS_CACHE_DIR = Path(os.getenv("TTS_CACHE_DIR", "/opt/safebox/runtime/tts_cache"))
TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

TTS_CHUNK_MAX_CHARS = int(os.getenv("TTS_CHUNK_MAX_CHARS", "500"))
TTS_PREFETCH_CHUNKS = int(os.getenv("TTS_PREFETCH_CHUNKS", "2"))

_current_player = None
_stop_event = threading.Event()
_lock = threading.Lock()


def stop_audio():
    global _current_player

    _stop_event.set()

    with _lock:
        if _current_player and _current_player.poll() is None:
            _current_player.terminate()
        _current_player = None


def _cache_path(text: str) -> Path:
    key = hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:16]
    return TTS_CACHE_DIR / f"{key}.wav"


def _clean_tts_text(text: str) -> str:
    text = text or ""

    # ASCII-safe markdown cleanup.
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)

    # Remove markdown headings.
    text = re.sub(r"^[ \t]*#{1,6}[ \t]*", "", text, flags=re.MULTILINE)

    # Remove ASCII bullets only.
    text = re.sub(r"^[ \t]*[-*][ \t]+", "", text, flags=re.MULTILINE)

    # Remove numbered list prefixes like "1. "
    text = re.sub(r"^[ \t]*[0-9]+[.)][ \t]+", "", text, flags=re.MULTILINE)

    # Remove markdown table rows.
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            continue
        if "|" in stripped and "---" in stripped:
            continue
        lines.append(line)

    text = " ".join(lines)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def _split_into_chunks(text: str, max_chars: int) -> list[str]:
    text = _clean_tts_text(text)
    if not text:
        return []

    # Split mainly by sentence endings.
    sentences = re.split(r"(?<=[.!?])\s+", text)

    chunks = []
    current = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        # If one sentence is too long, split by comma.
        if len(sentence) > max_chars:
            parts = re.split(r"(?<=,)\s+", sentence)
        else:
            parts = [sentence]

        for part in parts:
            part = part.strip()
            if not part:
                continue

            if len(current) + len(part) + 1 <= max_chars:
                current = f"{current} {part}".strip()
            else:
                if current:
                    chunks.append(current)
                current = part

    if current:
        chunks.append(current)

    return chunks


def _generate_wav(text: str) -> Path:
    wav_path = _cache_path(text)

    if wav_path.exists():
        print("[TTS] Prefetch cache hit")
        return wav_path

    print("[TTS] Prefetch generating")
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

    return wav_path


def _play_wav(wav_path: Path):
    global _current_player

    if _stop_event.is_set():
        return

    print("[TTS] Playing chunk")

    with _lock:
        _current_player = subprocess.Popen(
            ["aplay", "-D", OUTPUT_DEVICE, str(wav_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    while True:
        if _stop_event.is_set():
            with _lock:
                if _current_player and _current_player.poll() is None:
                    _current_player.terminate()
            return

        with _lock:
            proc = _current_player

        if proc is None or proc.poll() is not None:
            return

        time.sleep(0.05)


def _producer(chunks: list[str], out_queue: queue.Queue):
    for index, chunk in enumerate(chunks):
        if _stop_event.is_set():
            break

        try:
            wav_path = _generate_wav(chunk)
            out_queue.put((index, wav_path))
        except Exception as e:
            print("[TTS PRODUCER ERROR]", e)
            out_queue.put((index, None))

    out_queue.put((None, None))


def speak(text: str):
    if not text:
        return

    stop_audio()
    _stop_event.clear()

    chunks = _split_into_chunks(text, TTS_CHUNK_MAX_CHARS)

    if not chunks:
        return

    print(f"[TTS] chunks={len(chunks)} prefetch={TTS_PREFETCH_CHUNKS}")

    # Queue size controls how far ahead generation can run.
    wav_queue = queue.Queue(maxsize=max(1, TTS_PREFETCH_CHUNKS))

    producer_thread = threading.Thread(
        target=_producer,
        args=(chunks, wav_queue),
        daemon=True,
    )
    producer_thread.start()

    next_index = 0
    pending = {}

    try:
        while not _stop_event.is_set():
            index, wav_path = wav_queue.get()

            if index is None:
                break

            pending[index] = wav_path

            # Play chunks in correct order.
            while next_index in pending:
                next_wav = pending.pop(next_index)
                next_index += 1

                if next_wav is None:
                    continue

                _play_wav(next_wav)

                if _stop_event.is_set():
                    break

    except Exception as e:
        print("[TTS ERROR]", e)
