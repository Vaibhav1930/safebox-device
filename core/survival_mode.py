import time
from core.logger import setup_logger, with_request_id

logger = setup_logger("survival", "device.log")

COOLDOWN_SECONDS = 30


def _announce(text: str):
    """Play a spoken announcement through the speaker."""
    try:
        from core.audio.tts_player import speak
        speak(text)
        logger.info(f"survival.announce text={text!r}", extra=with_request_id())
    except Exception as e:
        logger.warning(f"survival.announce.failed reason={e}", extra=with_request_id())


class SurvivalModeController:
    def __init__(self):
        self.state = "idle"
        self.active = False
        self.last_trigger_time = 0

    def enter(self):
        if self.active:
            logger.debug("survival.enter.skipped.active", extra=with_request_id())
            return

        now = time.time()
        if now - self.last_trigger_time < COOLDOWN_SECONDS:
            remaining = int(COOLDOWN_SECONDS - (now - self.last_trigger_time))
            logger.info(
                f"survival.cooldown.active remaining={remaining}s",
                extra=with_request_id()
            )
            return

        self.active = True
        self.state = "survival"
        self.last_trigger_time = time.time()
        logger.info("survival.enter | mic_stream owns audio pipeline", extra=with_request_id())

        _announce(
            "I've lost connection to my cloud brain. "
            "I'm now running in Survival Mode. "
            "I can still answer basic questions and access your vault."
        )

    def run_cycle(self):
        # mic_stream.py owns mic, wake word, and audio pipeline
        # survival_mode only tracks network state - nothing to do here
        pass

    def exit(self):
        if not self.active:
            return

        self.active = False
        self.state = "idle"
        logger.info("survival.exit", extra=with_request_id())

        _announce(
            "I'm back online. Switching to Cloud Mode."
        )
