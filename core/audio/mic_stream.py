import numpy as np
import sounddevice as sd
import queue
import time
from core.execution.executor import execute_intent
from core.cloud_heartbeat import start_heartbeat

from core.audio.stt import SpeechToText
from core.intent.pipeline import process_command
from core.audio.wake_word import WakeWordEngine
from core.audio.simple_vad import SimpleVAD
from core.audio.recorder import SpeechRecorder

# ================= CONFIG =================
MIN_INTENT_CONFIDENCE = 0.75

SAMPLE_RATE = 16000
FRAME_SIZE = 512

CHANNELS = 2          # reSpeaker DSP provides 2 channels (stereo)
DEVICE = None         # MUST be None → PortAudio / ALSA default

STATE_IDLE = 0
STATE_RECORDING = 1

POST_WAKE_SECONDS = 0.4
COOLDOWN_SECONDS = 0.5

# =========================================

print(">>> mic_stream module loaded")

# Queue for processing completed recordings outside callback
task_queue = queue.Queue()


def main():
    print(">>> main() entered")
    print("[SYS] Starting cloud heartbeat")
    start_heartbeat()

    state = STATE_IDLE

    POST_WAKE_FRAMES = int(POST_WAKE_SECONDS * SAMPLE_RATE / FRAME_SIZE)
    COOLDOWN_FRAMES = int(COOLDOWN_SECONDS * SAMPLE_RATE / FRAME_SIZE)

    post_wake_counter = 0
    cooldown_counter = 0

    # Heavy components (NOT inside callback)
    stt = SpeechToText()
    wake_word = WakeWordEngine(keyword="computer")
    vad = SimpleVAD(threshold=500, silence_frames=15)

    # Recorder supports STEREO
    recorder = SpeechRecorder(sample_rate=SAMPLE_RATE)

    # ================= AUDIO CALLBACK =================
    def audio_callback(indata, frames, time_info, status):
        nonlocal state, post_wake_counter, cooldown_counter

        if status:
            print("[AUDIO]", status)

        # Cooldown after a completed command
        if cooldown_counter > 0:
            cooldown_counter -= 1
            return

        # indata shape: (frames, 2)
        left = indata[:, 0].astype(np.int16)
        right = indata[:, 1].astype(np.int16)

        mono_for_wake = left                       # BEST signal
        stereo_for_record = np.column_stack((left, right))

        # -------- IDLE → WAIT FOR WAKE --------
        if state == STATE_IDLE:
            if wake_word.process_audio(mono_for_wake):
                print("[SYS] Wake detected → start recording")
                recorder.start()
                post_wake_counter = POST_WAKE_FRAMES
                state = STATE_RECORDING

        # -------- RECORDING --------
        elif state == STATE_RECORDING:
            recorder.add(stereo_for_record)

            # Ignore early frames just after wake word
            if post_wake_counter > 0:
                post_wake_counter -= 1
                return

            if not vad.update(mono_for_wake):
                print("[SYS] Silence detected → stop recording")

                path = recorder.stop_and_save()

                if path is not None:
                    task_queue.put(path)

                state = STATE_IDLE
                cooldown_counter = COOLDOWN_FRAMES

    # ================= AUDIO STREAM =================
    print(">>> opening audio stream")

    with sd.InputStream(
        device=DEVICE,               # DO NOT CHANGE
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,            # MUST be 2
        dtype="int16",
        blocksize=FRAME_SIZE,
        callback=audio_callback,
    ):
        print("??? Mic stream running (say: computer)")

        try:
            while True:
                try:
                    # -------- PROCESS COMPLETED RECORDINGS --------
                    path = task_queue.get(timeout=1)

                    text = stt.transcribe(path)
                    print("[STT] Text:", text)

                    if not text or not text.strip():
                        print("[STT] Empty transcription")
                        continue

                    result = process_command(text)

                    if not result["safe"]:
                        print("[INTENT] Rejected:", text)
                        continue

                    if result["confidence"] < MIN_INTENT_CONFIDENCE:
                        print("[INTENT] Low confidence:", result)
                        continue
                    print("[INTENT]", result)

                    from core.execution.executor import execute_intent
                    execute_intent(result)



                    # ===== STEP 8: EXECUTION (NEXT) =====
                    # execute_intent(result)

                except queue.Empty:
                    pass

        except KeyboardInterrupt:
            print("Stopping mic stream")


if __name__ == "__main__":
    main()
