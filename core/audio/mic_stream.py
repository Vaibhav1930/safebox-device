import uuid
import numpy as np
import sounddevice as sd
import queue

from core.vault.storage import save_interaction
from core.llm_client import ask_llm, internet_available
from core.execution.executor import execute_intent
from core.cloud_heartbeat import start_heartbeat
from core.logger import get_logger
from core.audio.stt import SpeechToText
from core.intent.pipeline import process_command
from core.audio.wake_word import WakeWordEngine
from core.audio.simple_vad import SimpleVAD
from core.audio.recorder import SpeechRecorder
from core.audio.tts_player import speak, stop_audio
from core.local_llm_client import ask_local_llm

log = get_logger("mic_stream")

MIN_INTENT_CONFIDENCE = 0.60
SAMPLE_RATE = 16000
FRAME_SIZE = 512
CHANNELS = 2
POST_WAKE_SECONDS = 2.0
COOLDOWN_SECONDS = 0.5

STATE_IDLE = 0
STATE_RECORDING = 1

MODE_CLOUD = "cloud"
MODE_SURVIVAL = "survival"


def find_device_by_name(name):
    devices = sd.query_devices()
    for i, d in enumerate(devices):
        if name.lower() in d["name"].lower():
            return i
    raise RuntimeError("XVF device not found")


DEVICE = find_device_by_name("reSpeaker XVF3800")
task_queue = queue.Queue()


def main():
    print("[SYS] Starting mic stream")
    start_heartbeat()

    # Start NFC manager (with retry for boot timing)
    def _start_nfc():
        import time
        for attempt in range(3):
            try:
                from core.nfc_manager import get_manager
                nfc = get_manager()
                if nfc.start():
                    print("[NFC] Started successfully")
                    return
                time.sleep(2)
            except Exception as e:
                print(f"[NFC] Attempt {attempt+1} failed: {e}")
                time.sleep(2)
        print("[NFC] Failed to start after 3 attempts")
    import threading
    threading.Thread(target=_start_nfc, daemon=True).start()

    state = STATE_IDLE
    mode_file = "/opt/safebox/runtime/mode"

    def get_mode():
        try:
            with open(mode_file) as f:
                value = f.read().strip().lower()
                return value if value in (MODE_CLOUD, MODE_SURVIVAL) else MODE_CLOUD
        except FileNotFoundError:
            return MODE_CLOUD
        except Exception as e:
            log.warning(f"mode.read_failed | {e}")
            return MODE_CLOUD

    post_wake_frames = int(POST_WAKE_SECONDS * SAMPLE_RATE / FRAME_SIZE)
    cooldown_frames = int(COOLDOWN_SECONDS * SAMPLE_RATE / FRAME_SIZE)

    post_wake_counter = 0
    cooldown_counter = 0

    stt = SpeechToText()
    wake_word = WakeWordEngine(keyword="hey-clarity")
    vad = SimpleVAD(threshold=500, silence_frames=15)
    recorder = SpeechRecorder(sample_rate=SAMPLE_RATE)

    def audio_callback(indata, frames, time_info, status):
        nonlocal state, post_wake_counter, cooldown_counter

        if status:
            log.warning(f"audio_callback.status | {status}")

        left = indata[:, 0].astype(np.int16)
        right = indata[:, 1].astype(np.int16)

        mono = left
        stereo = np.column_stack((left, right))

        # Suppress wake word detection while TTS is playing to avoid
        # the speaker audio triggering false wake word detections.
        if False:  # is_speaking removed — stop_audio called on wake word
            return

        if wake_word.process_audio(mono):
            stop_audio()
            recorder.start()
            post_wake_counter = post_wake_frames
            state = STATE_RECORDING
            return

        if cooldown_counter > 0:
            cooldown_counter -= 1
            return

        if state == STATE_RECORDING:
            recorder.add(stereo)

            if post_wake_counter > 0:
                post_wake_counter -= 1
                return

            if not vad.update(mono):
                path = recorder.stop_and_save()
                if path:
                    task_queue.put(path)

                state = STATE_IDLE
                cooldown_counter = cooldown_frames

    with sd.InputStream(
        device=DEVICE,
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="int16",
        blocksize=FRAME_SIZE,
        callback=audio_callback,
    ):
        print("[SYS] Listening...")

        while True:
            try:
                path = task_queue.get(timeout=1)
                selected_mode = get_mode()
                text = stt.transcribe(path)
                print("[STT]", text)

                if not text:
                    continue

                clean = text.strip().lower()

                if any(cmd in clean for cmd in ["stop", "cancel", "shut up"]):
                    stop_audio()
                    continue

                request_id = str(uuid.uuid4())
                latency_ms = None
                actual_mode = None
                reply = None

                result = process_command(text)
                if result["safe"] and result["confidence"] >= MIN_INTENT_CONFIDENCE:
                    reply = execute_intent(result)
                    actual_mode = "intent"
                    if reply:
                        try:
                            save_interaction(
                                user_text=text,
                                assistant_text=reply,
                                request_id=request_id,
                                mode=actual_mode,
                                latency_ms=None,
                            )
                        except Exception as e:
                            log.warning(f"vault.save_failed | intent | {e}")
                        speak(reply)
                    continue

                if selected_mode == MODE_CLOUD and internet_available():
                    log.info("route.selected=cloud")
                    cloud = ask_llm(text, device_id=os.environ.get("DEVICE_NAME", "safebox-001"))

                    if cloud and cloud.get("response"):
                        reply = cloud.get("response")
                        request_id = cloud.get("request_id") or request_id
                        latency_ms = cloud.get("latency_ms")
                        actual_mode = MODE_CLOUD
                        log.info(f"route.actual=cloud request_id={request_id}")
                    else:
                        log.warning("cloud.request_failed | fallback=survival")
                        reply = ask_local_llm(text)
                        actual_mode = MODE_SURVIVAL if reply else None

                else:
                    log.info("route.selected=survival")
                    reply = ask_local_llm(text)
                    actual_mode = MODE_SURVIVAL if reply else None

                if not reply:
                    speak("I cannot answer that right now.")
                    continue

                try:
                    save_interaction(
                        user_text=text,
                        assistant_text=reply,
                        request_id=request_id,
                        mode=actual_mode,
                        latency_ms=latency_ms,
                    )
                except Exception as e:
                    log.warning(f"vault.save_failed | {e}")

                speak(reply)

            except queue.Empty:
                pass


if __name__ == "__main__":
    main()
