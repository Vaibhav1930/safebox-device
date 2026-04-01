import os
import uuid
import queue
import threading

import sounddevice as sd

from core.logger import get_logger
from core.cloud_heartbeat import start_heartbeat
from core.audio.stt import SpeechToText
from core.audio.tts_player import speak, stop_audio
from core.audio.wake_word import WakeWordEngine
from core.audio.recorder import SpeechRecorder
from core.audio.front_end import FrontEnd, FrontEndConfig
from core.audio.session_manager import (
    SessionManager,
    SessionConfig,
    STATE_IDLE,
    STATE_LISTENING,
    STATE_PROCESSING,
    STATE_SPEAKING,
)
from core.intent.pipeline import process_command
from core.execution.executor import execute_intent
from core.llm_client import ask_llm, internet_available
from core.local_llm_client import ask_local_llm
from core.vault.storage import save_interaction
import re
log = get_logger("mic_stream")

MIN_INTENT_CONFIDENCE = 0.60
SAMPLE_RATE = 16000
FRAME_SIZE = 512
CHANNELS = 2

POST_WAKE_SECONDS = 1.2
SPEECH_START_TIMEOUT_SECONDS = 2.5
MAX_UTTERANCE_SECONDS = 8.0
COOLDOWN_SECONDS = 0.5

MODE_CLOUD = "cloud"
MODE_SURVIVAL = "survival"

task_queue = queue.Queue()


def find_device_by_name(name: str):
    devices = sd.query_devices()
    for i, d in enumerate(devices):
        if name.lower() in d["name"].lower():
            return i
    raise RuntimeError(f"Audio device not found: {name}")


DEVICE = find_device_by_name("reSpeaker XVF3800")
def strip_wake_prefix(text: str) -> str:
    if not text:
        return text

    text = text.strip()

    patterns = [
        r"^(hey\s+clarity[\s,.:!-]*)",
        r"^(clarity[\s,.:!-]*)",
    ]

    for pattern in patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()

    return text

def bootstrap_services():
    print("[SYS] Starting mic stream")
    start_heartbeat()

    try:
        from core.bluetooth_manager import start_auto_trust_watcher, restore_trusted_devices
        restore_trusted_devices()
        start_auto_trust_watcher()
    except Exception as e:
        print(f"[BT] Auto-trust watcher failed to start: {e}")

    def _start_nfc():
        import time
        for attempt in range(3):
            try:
                from core.nfc_manager import get_manager
                nfc = get_manager()
                if nfc.start():
                    print("[NFC] Started successfully")
                time.sleep(2)
                return
            except Exception as e:
                print(f"[NFC] Attempt {attempt + 1} failed: {e}")
                time.sleep(2)
        print("[NFC] Failed to start after 3 attempts")

    threading.Thread(target=_start_nfc, daemon=True).start()


def main():
    bootstrap_services()

    mode_file = "/opt/safebox/runtime/mode"

    def get_mode():
        try:
            with open(mode_file, "r", encoding="utf-8") as f:
                value = f.read().strip().lower()
                return value if value in (MODE_CLOUD, MODE_SURVIVAL) else MODE_CLOUD
        except FileNotFoundError:
            return MODE_CLOUD
        except Exception as e:
            log.warning(f"mode.read_failed | {e}")
            return MODE_CLOUD

    frames_per_second = SAMPLE_RATE / FRAME_SIZE

    session = SessionManager(
        SessionConfig(
            post_wake_grace_frames=int(POST_WAKE_SECONDS * frames_per_second),
            speech_start_timeout_frames=int(SPEECH_START_TIMEOUT_SECONDS * frames_per_second),
            max_utterance_frames=int(MAX_UTTERANCE_SECONDS * frames_per_second),
            cooldown_frames=int(COOLDOWN_SECONDS * frames_per_second),
        )
    )

    front_end = FrontEnd(
        FrontEndConfig(
            sample_rate=SAMPLE_RATE,
            frame_size=FRAME_SIZE,
            preroll_seconds=1.0,
            speech_threshold=260.0,
            silence_threshold=180.0,
            trailing_silence_frames=22,
        )
    )

    stt = SpeechToText()
    wake_word = WakeWordEngine(keyword="hey-clarity", sensitivity=0.58)
    recorder = SpeechRecorder(sample_rate=SAMPLE_RATE, min_duration=0.60)

    def finalize_recording(reason: str):
        path = recorder.stop_and_save()
        session.set_processing()
        log.info(f"recording.finalized reason={reason}")

        if path:
            task_queue.put(path)
        else:
            session.set_cooldown()

    def audio_callback(indata, frames, time_info, status):
        if status:
            log.warning(f"audio_callback.status | {status}")

        if indata is None or len(indata) == 0:
            return

        session.tick()

        _, _, wake_pcm, speech_pcm, mono_record = front_end.split_channels(indata)
        front_end.push_preroll(speech_pcm)

        # Wake detection allowed in idle and speaking for barge-in
        if session.can_run_wake():
            try:
                if wake_word.process_audio(wake_pcm):
                    if session.speaking():
                        stop_audio()
                        log.info("barge_in.detected -> stop_audio")

                    front_end.reset_vad()
                    preroll = front_end.get_preroll_audio()
                    recorder.start(initial_audio=preroll)
                    recorder.add(mono_record)
                    session.start_listening()
                    log.info("wake.detected -> state=LISTENING")
                    return
            except Exception as e:
                log.warning(f"wake.process_failed | {e}")

        if session.listening():
            recorder.add(mono_record)

            # During initial grace, do not endpoint
            if session.post_wake_remaining > 0:
                return

            speech_active = front_end.is_speech(speech_pcm)
            if speech_active:
                session.has_seen_speech = True

            # no speech started after wake
            if not session.has_seen_speech and session.speech_start_timeout_remaining <= 0:
                finalize_recording("speech_start_timeout")
                return

            # speech ended after having started
            if session.has_seen_speech and not speech_active:
                finalize_recording("trailing_silence")
                return

            # safety max utterance
            if session.max_utterance_remaining <= 0:
                finalize_recording("max_utterance")
                return

    print("[SYS] Listening...")

    with sd.InputStream(
        device=DEVICE,
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="int16",
        blocksize=FRAME_SIZE,
        callback=audio_callback,
    ):
        while True:
            try:
                path = task_queue.get(timeout=1)

                text = stt.transcribe(path)
                text = strip_wake_prefix(text)
                print("[STT]", text)

                if not text or not text.strip():
                    session.set_cooldown()
                    continue

                clean = text.strip().lower()

                if any(cmd in clean for cmd in ["stop", "cancel", "shut up"]):
                    stop_audio()
                    session.set_idle()
                    continue

                selected_mode = get_mode()
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

                        session.set_speaking()
                        speak(reply)
                        session.set_cooldown()
                    else:
                        session.set_idle()
                    continue

                if selected_mode == MODE_CLOUD :
                    log.info("route.selected=cloud")
                    cloud = ask_llm(text, device_id=os.environ.get("DEVICE_NAME", "safebox-001"))

                    if cloud and cloud.get("response"):
                        reply = cloud.get("response")
                        request_id = cloud.get("request_id") or request_id
                        latency_ms = cloud.get("latency_ms")
                        actual_mode = MODE_CLOUD
                    else:
                        log.warning("cloud.request_failed | fallback=survival")
                        reply = ask_local_llm(text)
                        actual_mode = MODE_SURVIVAL if reply else None
                else:
                    log.info("route.selected=survival")
                    reply = ask_local_llm(text)
                    actual_mode = MODE_SURVIVAL if reply else None

                if not reply:
                    session.set_speaking()
                    speak("I cannot answer that right now.")
                    session.set_cooldown()
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

                session.set_speaking()
                speak(reply)
                session.set_cooldown()

            except queue.Empty:
                continue
            except KeyboardInterrupt:
                print("[SYS] Stopped by user")
                break
            except Exception as e:
                log.exception(f"main.loop_failed | {e}")
                session.set_cooldown()


if __name__ == "__main__":
    main()
