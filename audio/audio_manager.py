import subprocess
import shutil
from core.logger import setup_logger, with_request_id

audio_logger = setup_logger("audio", "device.log")

TEST_FILE = "/opt/safebox/audio/test_record.wav"

def _command_exists(cmd):
    return shutil.which(cmd) is not None

def mic_available():
    if not _command_exists("arecord"):
        return False
    result = subprocess.run(
        ["arecord", "-l"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    return "card" in result.stdout.lower()

def speaker_available():
    if not _command_exists("aplay"):
        return False
    result = subprocess.run(
        ["aplay", "-l"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    return "card" in result.stdout.lower()

def record_test(duration=3):
    if not mic_available():
        audio_logger.warning(
            "audio.record.skipped reason=mic_not_available",
            extra=with_request_id()
        )
        return False

    try:
        subprocess.run(
            ["arecord", "-f", "cd", "-t", "wav", "-d", str(duration), TEST_FILE],
            check=True
        )
        audio_logger.info(
            "audio.record.success",
            extra=with_request_id()
        )
        return True
    except Exception as e:
        audio_logger.error(
            f"audio.record.failed reason={e}",
            extra=with_request_id()
        )
        return False

def play_test():
    if not speaker_available():
        audio_logger.warning(
            "audio.play.skipped reason=speaker_not_available",
            extra=with_request_id()
        )
        return False

    try:
        subprocess.run(
            ["aplay", TEST_FILE],
            check=True
        )
        audio_logger.info(
            "audio.play.success",
            extra=with_request_id()
        )
        return True
    except Exception as e:
        audio_logger.error(
            f"audio.play.failed reason={e}",
            extra=with_request_id()
        )
        return False

def full_audio_test():
    audio_logger.info(
        "audio.test.start",
        extra=with_request_id()
    )

    recorded = record_test()
    if recorded:
        play_test()

    audio_logger.info(
        "audio.test.end",
        extra=with_request_id()
    )
