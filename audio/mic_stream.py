import sounddevice as sd
import queue
from core.logger import setup_logger, with_request_id

audio_logger = setup_logger("audio", "device.log")

class MicStream:
    def __init__(self, samplerate=16000, blocksize=1024):
        self.samplerate = samplerate
        self.blocksize = blocksize
        self.q = queue.Queue()

    def _callback(self, indata, frames, time, status):
        if status:
            audio_logger.warning(
                f"mic.status {status}",
                extra=with_request_id()
            )
        self.q.put(indata.copy())

    def start(self):
        audio_logger.info(
            "mic.start",
            extra=with_request_id()
        )
        self.stream = sd.InputStream(
            samplerate=self.samplerate,
            channels=1,
            blocksize=self.blocksize,
            callback=self._callback
        )
        self.stream.start()

    def read(self):
        return self.q.get()

    def stop(self):
        audio_logger.info(
            "mic.stop",
            extra=with_request_id()
        )
        self.stream.stop()
        self.stream.close()
