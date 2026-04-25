import os
import random
import shlex
import signal
import subprocess
from pathlib import Path

from core.logger import get_logger

log = get_logger("local_music")

VAULT_ROOT = Path(os.environ.get("SAFEBOX_VAULT_ROOT", "/mnt/ssd/safebox-device/vault"))
MUSIC_DIR = VAULT_ROOT / "uploads"
PID_FILE = Path(os.environ.get("LOCAL_MUSIC_PID_FILE", "/opt/safebox/runtime/local_music.pid"))

OUTPUT_DEVICE = os.environ.get("AUDIO_OUTPUT_DEVICE", "plughw:2,0")
OUTPUT_SAMPLE_RATE = int(os.environ.get("AUDIO_OUTPUT_SAMPLE_RATE", "44100"))
OUTPUT_CHANNELS = int(os.environ.get("AUDIO_OUTPUT_CHANNELS", "2"))

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"}


def _list_tracks():
    if not MUSIC_DIR.exists():
        return []
    return [
        str(p) for p in MUSIC_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS
    ]


def _read_pid():
    try:
        return int(PID_FILE.read_text().strip())
    except Exception:
        return None


def _write_pid(pid: int):
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(pid))


def _clear_pid():
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def is_playing_local() -> bool:
    pid = _read_pid()
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        _clear_pid()
        return False


def stop_local() -> bool:
    pid = _read_pid()
    if not pid:
        return False
    try:
        os.killpg(pid, signal.SIGTERM)
        _clear_pid()
        log.info("local_music.stopped | pid=%s", pid)
        return True
    except Exception as e:
        log.warning(f"local_music.stop_failed | {e}")
        _clear_pid()
        return False


def play_local() -> str:
    tracks = _list_tracks()
    if not tracks:
        log.info("local_music.no_tracks | dir=%s", MUSIC_DIR)
        return "No offline songs found in vault uploads."

    if is_playing_local():
        return "Offline music is already playing."

    random.shuffle(tracks)
    track = tracks[0]
    quoted_track = shlex.quote(track)
    quoted_device = shlex.quote(OUTPUT_DEVICE)

    cmd = [
        "bash",
        "-lc",
        (
            f"ffmpeg -nostdin -v error -i {quoted_track} "
            f"-f wav -acodec pcm_s16le -ar {OUTPUT_SAMPLE_RATE} -ac {OUTPUT_CHANNELS} - "
            f"| aplay -D {quoted_device} -q"
        ),
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _write_pid(proc.pid)
        log.info(
            "local_music.play | file=%s pid=%d dir=%s device=%s rate=%d channels=%d",
            track,
            proc.pid,
            MUSIC_DIR,
            OUTPUT_DEVICE,
            OUTPUT_SAMPLE_RATE,
            OUTPUT_CHANNELS,
        )
        return "Playing your offline music from vault uploads."
    except Exception as e:
        log.warning(f"local_music.play_failed | {e}")
        return "Sorry, I couldn't play offline music right now."
