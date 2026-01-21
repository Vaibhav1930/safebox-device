import time
from core.logger import setup_logger, with_request_id

logger = setup_logger("survival", "device.log")

COOLDOWN_SECONDS = 30
LISTEN_TIMEOUT = 5

# --- Lazy audio loading (CRITICAL FIX) ---
AUDIO_AVAILABLE = False
WakeWordListener = None


def _load_audio():
    """
    Lazy-load audio stack to avoid blocking systemd startup.
    """
    global AUDIO_AVAILABLE, WakeWordListener

    if AUDIO_AVAILABLE:
        return

    try:
        from audio.wake_word import WakeWordListener as WW
        WakeWordListener = WW
        AUDIO_AVAILABLE = True
        logger.info(
            "audio.init.success",
            extra=with_request_id()
        )
    except Exception as e:
        AUDIO_AVAILABLE = False
        logger.error(
            f"audio.init.failed reason={e}",
            extra=with_request_id()
        )


class SurvivalModeController:
    def __init__(self):
        self.state = "idle"
        self.wakeword = None
        self.last_trigger_time = 0
        self.active = False

    def enter(self):
        if self.active:
            logger.debug(
                "survival.enter.skipped.active",
                extra=with_request_id()
            )
            return

        now = time.time()
        if now - self.last_trigger_time < COOLDOWN_SECONDS:
            logger.info(
                "survival.cooldown.active",
                extra=with_request_id()
            )
            return

        # Lazy-load audio only when needed
        _load_audio()

        if not AUDIO_AVAILABLE:
            logger.warning(
                "audio.disabled.survival.skip",
                extra=with_request_id()
            )
            return

        if self.wakeword is None:
            self.wakeword = WakeWordListener()

        self.active = True
        self.state = "listening"

        logger.info(
            "survival.enter",
            extra=with_request_id()
        )

    def run_cycle(self):
        if not self.active or self.state != "listening":
            return

        logger.info(
            "state=listening",
            extra=with_request_id()
        )

        try:
            detected = self.wakeword.listen(timeout=LISTEN_TIMEOUT)
        except Exception as e:
            logger.warning(
                f"wake_word.failure reason={e}",
                extra=with_request_id()
            )
            self._reset()
            return

        if not detected:
            self._reset()
            return

        self.state = "processing"
        logger.info("state=processing", extra=with_request_id())
        time.sleep(1)

        self.state = "speaking"
        logger.info("state=speaking", extra=with_request_id())

        logger.info(
            'response="I am offline"',
            extra=with_request_id()
        )

        self.last_trigger_time = time.time()
        self._reset()

    def _reset(self):
        if self.state != "idle":
            self.state = "idle"
            logger.info(
                "state=idle",
                extra=with_request_id()
            )
        self.active = False

    def exit(self):
        """
        Called when device leaves survival mode.
        Must cleanly reset state.
        """
        if not self.active:
            return

        self.active = False
        self.state = "idle"

        logger.info(
            "survival.exit",
            extra=with_request_id()
        )

