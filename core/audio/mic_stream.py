import numpy as np
import sounddevice as sd
import queue
import time
from core.vault.storage import save_interaction
from core.llm_client import ask_llm, internet_available

from core.execution.executor import execute_intent
from core.cloud_heartbeat import start_heartbeat
from core.audio.stt import SpeechToText
from core.intent.pipeline import process_command
from core.audio.wake_word import WakeWordEngine
from core.audio.simple_vad import SimpleVAD
from core.audio.recorder import SpeechRecorder
from core.audio.tts_player import speak, stop_audio
from core.local_llm_client import ask_local_llm

MIN_INTENT_CONFIDENCE = 0.75
SAMPLE_RATE = 16000
FRAME_SIZE = 512
CHANNELS = 2

POST_WAKE_SECONDS = 0.4
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

    state = STATE_IDLE
    mode = MODE_CLOUD

    POST_WAKE_FRAMES = int(POST_WAKE_SECONDS * SAMPLE_RATE / FRAME_SIZE)
    COOLDOWN_FRAMES = int(COOLDOWN_SECONDS * SAMPLE_RATE / FRAME_SIZE)

    post_wake_counter = 0
    cooldown_counter = 0

    stt = SpeechToText()
    wake_word = WakeWordEngine(keyword="hey-clarity")
    vad = SimpleVAD(threshold=500, silence_frames=15)
    recorder = SpeechRecorder(sample_rate=SAMPLE_RATE)
    import threading

    def network_monitor():
        nonlocal mode
        last_status = internet_available()

        while True:
            current_status = internet_available()

            if current_status != last_status:
                if current_status:
                    print("[NET] Internet connected")
                    mode = MODE_CLOUD
                    speak("Internet connected. Cloud mode active.")
                else:
                    print("[NET] Internet disconnected")
                    mode = MODE_SURVIVAL
                    speak("Internet disconnected. Entering survival mode.")

                last_status = current_status

            time.sleep(5)  # check every 5 seconds

    def audio_callback(indata, frames, time_info, status):
        nonlocal state, post_wake_counter, cooldown_counter

        left = indata[:, 0].astype(np.int16)
        right = indata[:, 1].astype(np.int16)

        mono = left
        stereo = np.column_stack((left, right))

        if wake_word.process_audio(mono):
            stop_audio()
            recorder.start()
            post_wake_counter = POST_WAKE_FRAMES
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
                cooldown_counter = COOLDOWN_FRAMES
    threading.Thread(target=network_monitor, daemon=True).start()

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

                text = stt.transcribe(path)
                print("[STT]", text)

                if not text:
                    continue

                clean = text.strip().lower()

                if any(cmd in clean for cmd in ["stop", "cancel", "shut up"]):
                    stop_audio()
                    continue

                # Intent first
                result = process_command(text)
                if result["safe"] and result["confidence"] >= MIN_INTENT_CONFIDENCE:
                    execute_intent(result)
                    continue

                reply = None

                # ---------- CLOUD MODE ----------
                if mode == MODE_CLOUD:
                    print("[MODE] CLOUD")
                    cloud = ask_llm(text, device_id="safebox-001")

                    if cloud:
                        reply = cloud.get("response")
                        request_id = cloud.get("request_id")
                        latency_ms = cloud.get("latency_ms")

                    else:
                        # Cloud request failed but network might still be up
                        # Just fallback locally without changing mode
                        reply = ask_local_llm(text)


                # ---------- SURVIVAL MODE ----------
                elif mode == MODE_SURVIVAL:
                    print("[MODE] SURVIVAL")
                    reply = ask_local_llm(text)



                # ---------- Final Check ----------
                if not reply:
                    speak("I cannot answer that right now.")
                    continue

                # Save interaction to vault
                try:
                    save_interaction(
                        user_text=text,
                        assistant_text=reply,
                        request_id=None,
                        mode=mode,
                        latency_ms=None,
                        audio_path=path
                    )
                except Exception as e:
                    print("[VAULT ERROR]", e)

                speak(reply)


            except queue.Empty:
                pass


if __name__ == "__main__":
    main()
