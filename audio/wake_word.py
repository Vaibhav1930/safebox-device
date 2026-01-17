import time
import sounddevice as sd
import numpy as np

from core.logger import setup_logger, with_request_id

logger = setup_logger("audio", "device.log")

class WakeWordListener:
    def __init__(self, threshold=0.02, sample_rate=16000):
        self.threshold = threshold
        self.sample_rate = sample_rate
        self.running = False

    def listen(self, timeout=5):
        """
        Listens for sound above threshold.
        Returns True if detected.
        """
        try:
            logger.info("wake_word.listening", extra=with_request_id())

            self.running = True
            detected = False
            start = time.time()

            def callback(indata, frames, time_info, status):
                nonlocal detected
                volume = np.linalg.norm(indata) / frames
                if volume > self.threshold:
                    detected = True
                    raise sd.CallbackStop()

            with sd.InputStream(
                channels=1,
                samplerate=self.sample_rate,
                callback=callback
            ):
                while time.time() - start < timeout and not detected:
                    time.sleep(0.1)

            if detected:
                logger.info("wake_word.detected", extra=with_request_id())
                return True

            return False

        except Exception as e:
            logger.warning(
                f"wake_word.error reason={str(e)}",
                extra=with_request_id()
            )
            return False
        finally:
            self.running = False

