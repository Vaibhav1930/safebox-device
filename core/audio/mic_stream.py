"""
mic_stream.py - SafeBox main audio pipeline
"""

import os
import queue
import threading
import re
import time
from pathlib import Path

import sounddevice as sd

from core.config_runtime import build_runtime_context
from core.logger import get_logger, with_request_id
from core.request_context import new_request_id, clear_request_id, set_request_id
from core.cloud_heartbeat import start_heartbeat
from core.audio.stt import SpeechToText
from core.audio.tts_player import speak, stop_audio
from core.audio.wake_word import WakeWordEngine
from core.audio.recorder import SpeechRecorder
from core.audio.front_end import FrontEnd, FrontEndConfig
from core.audio.session_manager import SessionManager, SessionConfig
from core.intent.pipeline import process_command
from core.execution.executor import execute_intent
from core.llm_client import ask_llm, warm_cloud_auth
from core.local_llm_client import ask_local_llm
from core.vault.storage import save_interaction
from core.runtime_mode import (
    MODE_CLOUD,
    MODE_SURVIVAL,
    load_runtime_mode_state,
    manual_override_active,
    save_runtime_mode_state,
)
from core.llm_client import internet_available
from core.ap_setup import ensure_hotspot
from core.setup_state import is_setup_completed

log = get_logger("mic_stream")

# ---------------------------------------------------------------------------
# Env-driven config
# ---------------------------------------------------------------------------
MIN_INTENT_CONFIDENCE = float(os.getenv("MIN_INTENT_CONFIDENCE", "0.60"))

SAMPLE_RATE = int(os.getenv("AUDIO_INPUT_SAMPLE_RATE", "16000"))
FRAME_SIZE = int(os.getenv("AUDIO_FRAME_SIZE", "512"))
CHANNELS = int(os.getenv("AUDIO_INPUT_CHANNELS", "2"))

POST_WAKE_SECONDS = float(os.getenv("AUDIO_POST_WAKE_SECONDS", "1.2"))
SPEECH_START_TIMEOUT_SECONDS = float(
    os.getenv("AUDIO_SPEECH_START_TIMEOUT_SECONDS", "2.5")
)
MAX_UTTERANCE_SECONDS = float(os.getenv("AUDIO_MAX_UTTERANCE_SECONDS", "8.0"))
COOLDOWN_SECONDS = float(os.getenv("AUDIO_COOLDOWN_SECONDS", "0.5"))

MANUAL_VOICE_TRIGGER_FILE = os.getenv(
    "MANUAL_VOICE_TRIGGER_FILE",
    "/opt/safebox/runtime/manual_voice_trigger",
)

FRONTEND_PREROLL_SECONDS = float(os.getenv("AUDIO_PREROLL_SECONDS", "1.0"))
FRONTEND_SPEECH_THRESHOLD = float(os.getenv("AUDIO_VAD_SPEECH_THRESHOLD", "260.0"))
FRONTEND_SILENCE_THRESHOLD = float(os.getenv("AUDIO_VAD_SILENCE_THRESHOLD", "180.0"))
FRONTEND_TRAILING_SILENCE_FRAMES = int(
    os.getenv("AUDIO_VAD_TRAILING_SILENCE_FRAMES", "22")
)

RECORDER_MIN_DURATION = float(os.getenv("AUDIO_MIN_RECORD_SECONDS", "0.60"))

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------
task_queue: queue.Queue = queue.Queue()
_last_runtime_mode: str | None = None
_mode_lock = threading.Lock()

_cached_persona: dict = {}
_cached_behavior: dict = {}
_config_cache_lock = threading.Lock()
# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_runtime_persona_behavior() -> tuple[dict, dict]:
    try:
        from core.config_sync import ConfigSyncManager as _CSM
        mgr = _CSM(device_id=os.environ.get("DEVICE_NAME", "safebox-001"))
        return mgr.get_persona(), mgr.get_behavior()
    except Exception as e:
        log.warning(f"runtime_config.load_failed | {e}")
        return {}, {}


def refresh_runtime_persona_behavior() -> None:
    global _cached_persona, _cached_behavior
    persona, behavior = load_runtime_persona_behavior()
    with _config_cache_lock:
        _cached_persona = persona or {}
        _cached_behavior = behavior or {}


def get_runtime_persona_behavior() -> tuple[dict, dict]:
    with _config_cache_lock:
        return dict(_cached_persona), dict(_cached_behavior)

def log_mode_transition(new_mode: str, reason: str) -> None:
    global _last_runtime_mode
    with _mode_lock:
        old_mode = _last_runtime_mode
        if old_mode != new_mode:
            log.info(
                f"mode.transition {old_mode}->{new_mode} reason={reason}",
                extra=with_request_id(),
            )
        _last_runtime_mode = new_mode


def find_device_by_name(name: str) -> int:
    for i, d in enumerate(sd.query_devices()):
        device_name = str(d.get("name", ""))
        if name.lower() in device_name.lower():
            return i
    raise RuntimeError(f"Audio device not found: {name}")


def resolve_input_device() -> int:
    """
    Resolve input device from env in this order:
    1. AUDIO_INPUT_DEVICE_INDEX
    2. AUDIO_INPUT_DEVICE_NAME
    """
    device_index_raw = os.getenv("AUDIO_INPUT_DEVICE_INDEX", "").strip()
    device_name = os.getenv("AUDIO_INPUT_DEVICE_NAME", "reSpeaker XVF3800").strip()

    if device_index_raw:
        try:
            resolved = int(device_index_raw)
            log.info(f"audio.input.device.index={resolved}")
            return resolved
        except ValueError as e:
            raise RuntimeError(
                f"Invalid AUDIO_INPUT_DEVICE_INDEX: {device_index_raw!r}"
            ) from e

    resolved = find_device_by_name(device_name)
    log.info(f"audio.input.device.name={device_name} resolved_index={resolved}")
    return resolved


def get_wake_word_config() -> tuple[str, float]:
    keyword = os.getenv("AUDIO_WAKE_WORD", "hey-clarity").strip() or "hey-clarity"
    sensitivity = float(os.getenv("AUDIO_WAKE_SENSITIVITY", "0.58"))
    return keyword, sensitivity


def strip_wake_prefix(text: str) -> str:
    if not text:
        return text
    text = text.strip()
    for pattern in (
        r"^(hey\s+clarity[\s,.:!-]*)",
        r"^(okay\s+clarity[\s,.:!-]*)",
        r"^(ok\s+clarity[\s,.:!-]*)",
        r"^(a\s+clarity[\s,.:!-]*)",
        r"^(take\s+clarity[\s,.:!-]*)",
        r"^(clarity[\s,.:!-]*)",
    ):
        text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
    return text


def consume_manual_voice_trigger() -> bool:
    try:
        path = Path(MANUAL_VOICE_TRIGGER_FILE)
        if path.exists():
            path.unlink()
            return True
    except Exception as e:
        log.warning(
            f"manual.voice_trigger.consume_failed | {e}",
            extra=with_request_id(),
        )
    return False


# ---------------------------------------------------------------------------
# Device resolution (fail fast at import time)
# ---------------------------------------------------------------------------
DEVICE = None


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
def bootstrap_services() -> None:
    log.info("bootstrap.start")
    start_heartbeat()

    try:
        from core.bluetooth_manager import (
            start_auto_trust_watcher,
            restore_trusted_devices,
        )

        restore_trusted_devices()
        start_auto_trust_watcher()
    except Exception as e:
        log.warning(f"bootstrap.bluetooth.failed | {e}")

    def _start_nfc() -> None:
        import time as _time

        for attempt in range(3):
            try:
                from core.nfc_manager import get_manager

                nfc = get_manager()
                if nfc.start():
                    log.info("bootstrap.nfc.started")
                _time.sleep(2)
                return
            except Exception as e:
                log.warning(f"bootstrap.nfc.attempt_{attempt + 1}.failed | {e}")
                _time.sleep(2)
        log.error("bootstrap.nfc.failed_all_attempts")

    threading.Thread(target=_start_nfc, daemon=True).start()
    log.info("bootstrap.done")


# ---------------------------------------------------------------------------
# Mode resolution
# ---------------------------------------------------------------------------
def resolve_mode() -> tuple[str, bool]:
    state = load_runtime_mode_state()

    if manual_override_active(state):
        return state.get("mode", MODE_CLOUD), False

    if state.get("manual_override"):
        if internet_available():
            save_runtime_mode_state(
                {
                    "mode": MODE_CLOUD,
                    "manual_override": False,
                    "override_expires_at": None,
                    "reason": "auto_recovered_to_cloud",
                }
            )
            log.info("mode.auto_recovered survival->cloud reason=override_expired")
            return MODE_CLOUD, True

        save_runtime_mode_state(
            {
                "mode": MODE_SURVIVAL,
                "manual_override": False,
                "override_expires_at": None,
                "reason": "override_expired_cloud_unhealthy",
            }
        )
        log.info("mode.auto_retained survival reason=override_expired_cloud_unhealthy")
        return MODE_SURVIVAL, False

    return state.get("mode", MODE_CLOUD), False


# ---------------------------------------------------------------------------
# Persist + play helpers
# ---------------------------------------------------------------------------
def _persist_interaction(
    user_text: str,
    assistant_text: str,
    device_request_id: str,
    *,
    cloud_request_id: str | None,
    mode: str | None,
    latency_ms: int | None,
) -> None:
    try:
        save_interaction(
            user_text=user_text,
            assistant_text=assistant_text,
            request_id=device_request_id,
            device_request_id=device_request_id,
            cloud_request_id=cloud_request_id,
            mode=mode,
            latency_ms=latency_ms,
        )
    except Exception as e:
        log.warning(
            f"vault.save_failed | mode={mode} | {e}",
            extra=with_request_id(device_request_id),
        )


def _play_reply(reply: str, session: SessionManager, device_request_id: str) -> None:
    session.set_speaking()
    log.info("tts.generate.start", extra=with_request_id(device_request_id))
    try:
        speak(reply)
    except Exception as e:
        log.warning(f"tts.speak_failed | {e}", extra=with_request_id(device_request_id))
    log.info("tts.play.done", extra=with_request_id(device_request_id))
    session.set_cooldown()
    clear_request_id()


# ---------------------------------------------------------------------------
# Task worker
# ---------------------------------------------------------------------------
def task_worker(get_stt_fn, session: SessionManager) -> None:
    """
    Dedicated daemon thread. Pulls (wav_path, request_id) from task_queue,
    runs STT -> intent -> LLM -> TTS. The audio callback is never blocked.

    IMPORTANT: every code path must call session.set_cooldown() or
    session.set_idle() before continuing, otherwise the session stays
    in STATE_PROCESSING and can_run_wake() returns False forever.
    """
    while True:
        try:
            path, device_request_id = task_queue.get(timeout=1)
            set_request_id(device_request_id)

            try:
                text = get_stt_fn().transcribe(path)
            except Exception as e:
                log.exception(
                    f"stt.transcribe_failed | {e}",
                    extra=with_request_id(device_request_id),
                )
                session.set_cooldown()
                clear_request_id()
                continue
            finally:
                try:
                    Path(path).unlink(missing_ok=True)
                except Exception:
                    pass

            text = strip_wake_prefix(text)
            log.info(
                f"stt.completed text={text!r}",
                extra=with_request_id(device_request_id),
            )

            if not text or not text.strip():
                log.info(
                    "stt.empty_result -> cooldown",
                    extra=with_request_id(device_request_id),
                )
                session.set_cooldown()
                clear_request_id()
                continue

            clean = text.strip().lower()

            if any(cmd in clean for cmd in ("stop", "cancel", "shut up")):
                stop_audio()
                log.info(
                    "tts.stop.requested",
                    extra=with_request_id(device_request_id),
                )
                session.set_idle()
                clear_request_id()
                continue

            selected_mode, recovered_to_cloud = resolve_mode()
            log_mode_transition(selected_mode, "pre_dispatch")

            if recovered_to_cloud:
                try:
                    speak("Cloud connection restored. Switching back to Cloud Mode.")
                except Exception as e:
                    log.warning(f"mode.auto_recovered.announce_failed | {e}")

            reply: str | None = None
            actual_mode: str | None = None
            cloud_request_id: str | None = None
            latency_ms: int | None = None

            intent_result = process_command(text)
            if (
                intent_result["safe"]
                and intent_result["confidence"] >= MIN_INTENT_CONFIDENCE
            ):
                reply = execute_intent(intent_result)
                actual_mode = "intent"
                if reply:
                    _persist_interaction(
                        text,
                        reply,
                        device_request_id,
                        cloud_request_id=None,
                        mode=actual_mode,
                        latency_ms=None,
                    )
                    _play_reply(reply, session, device_request_id)
                else:
                    session.set_idle()
                    clear_request_id()
                continue

            _persona, _behavior = get_runtime_persona_behavior()

            if selected_mode == MODE_CLOUD:
                log.info(
                    "route.selected=cloud",
                    extra=with_request_id(device_request_id),
                )
                log_mode_transition(MODE_CLOUD, "mode_file_selected")
                try:
                    runtime_context = build_runtime_context(selected_mode)

                    cloud = ask_llm(
                        message=text,
                        device_context={
                            "device_id": os.environ.get("DEVICE_NAME", "safebox-001"),
                            "timezone": runtime_context["timezone"],
                            "clock_status": "synced",
                            "caller_type": "device",
                        },
                        runtime_context=runtime_context,
                        request_context={
                            "device_request_id": device_request_id,
                            "mode": selected_mode,
                        },
                    )
                    if cloud and cloud.get("response"):
                        reply = cloud["response"]
                        cloud_request_id = (
                            cloud.get("cloud_request_id") or cloud.get("request_id")
                        )
                        latency_ms = cloud.get("latency_ms")
                        actual_mode = MODE_CLOUD
                        log.info(
                            f"cloud.response_received cloud_request_id={cloud_request_id}",
                            extra=with_request_id(device_request_id),
                        )
                        log_mode_transition(MODE_CLOUD, "cloud_request_succeeded")
                    else:
                        raise ValueError("empty cloud response")
                except Exception as e:
                    log.warning(
                        f"cloud.request_failed | {e} | fallback=survival",
                        extra=with_request_id(device_request_id),
                    )
                    log_mode_transition(MODE_SURVIVAL, "cloud_request_failed")
                    reply = ask_local_llm(
                        text,
                        persona=_persona,
                        behavior=_behavior,
                        survival_fallback=True,
                    )
                    actual_mode = MODE_SURVIVAL if reply else None
            else:
                log.info(
                    "route.selected=survival",
                    extra=with_request_id(device_request_id),
                )
                log_mode_transition(MODE_SURVIVAL, "mode_file_selected")
                reply = ask_local_llm(
                    text,
                    persona=_persona,
                    behavior=_behavior,
                    survival_fallback=True,
                )
                actual_mode = MODE_SURVIVAL if reply else None

            if not reply:
                reply = "I cannot answer that right now."
                log.warning(
                    "reply.empty -> fallback_phrase",
                    extra=with_request_id(device_request_id),
                )

            _persist_interaction(
                text,
                reply,
                device_request_id,
                cloud_request_id=cloud_request_id,
                mode=actual_mode,
                latency_ms=latency_ms,
            )
            _play_reply(reply, session, device_request_id)

        except queue.Empty:
            continue
        except Exception as e:
            log.exception(f"task_worker.unhandled | {e}", extra=with_request_id())
            try:
                session.set_cooldown()
            except Exception:
                pass
            clear_request_id()


def startup_announcement_text() -> str:
    if not is_setup_completed():
        return (
            "Welcome to SafeBox. Setup is not complete yet. "
            "If you are using a phone, tap the setup tag to open setup. "
            "If you are using a laptop, connect to the SafeBox setup Wi Fi network "
            "and open the local setup page in your browser."
        )

    return "Hello. SafeBox is ready."


def should_enable_wake() -> bool:
    return is_setup_completed()


def try_init_wake_word(current_wake_word):
    if current_wake_word is not None:
        return current_wake_word

    if not should_enable_wake():
        return None

    try:
        keyword, sensitivity = get_wake_word_config()
        log.info(
            f"wake_word.runtime_init.begin keyword={keyword} sensitivity={sensitivity}"
        )
        current_wake_word = WakeWordEngine(
            keyword=keyword,
            sensitivity=sensitivity,
        )
        log.info("wake_word.runtime_init.done")
        return current_wake_word
    except Exception as e:
        log.warning(f"wake_word.runtime_init.failed | {e}")
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    bootstrap_services()
    refresh_runtime_persona_behavior()
    threading.Thread(target=warm_cloud_auth, daemon=True, name="cloud-auth-warmup").start()
    global DEVICE
    DEVICE = resolve_input_device()
    log.info(f"startup.audio_input.ready device={DEVICE} sample_rate={SAMPLE_RATE} channels={CHANNELS}")

    if not is_setup_completed():
        try:
            ensure_hotspot()
            log.info("startup.ap_setup.enabled")
        except Exception as e:
            log.warning(f"startup.ap_setup.failed | {e}")

    startup_mode, startup_recovered = resolve_mode()
    log_mode_transition(startup_mode, "startup")

    try:
        if startup_recovered:
            log.info("mode.auto_recovered.announce.start")
            speak("Cloud connection restored. Switching back to Cloud Mode.")
            log.info("mode.auto_recovered.announce.done")
        else:
            log.info("startup.onboarding_announce.start")
            speak(startup_announcement_text())
            log.info("startup.onboarding_announce.done")
    except Exception as e:
        log.warning(f"startup.announce_failed | {e}")

    frames_per_second = SAMPLE_RATE / FRAME_SIZE

    session = SessionManager(
        SessionConfig(
            post_wake_grace_frames=int(POST_WAKE_SECONDS * frames_per_second),
            speech_start_timeout_frames=int(
                SPEECH_START_TIMEOUT_SECONDS * frames_per_second
            ),
            max_utterance_frames=int(MAX_UTTERANCE_SECONDS * frames_per_second),
            cooldown_frames=int(COOLDOWN_SECONDS * frames_per_second),
        )
    )

    front_end = FrontEnd(
        FrontEndConfig(
            sample_rate=SAMPLE_RATE,
            frame_size=FRAME_SIZE,
            preroll_seconds=FRONTEND_PREROLL_SECONDS,
            speech_threshold=FRONTEND_SPEECH_THRESHOLD,
            silence_threshold=FRONTEND_SILENCE_THRESHOLD,
            trailing_silence_frames=FRONTEND_TRAILING_SILENCE_FRAMES,
        )
    )

    try:
        log.info("startup.init.wake_word.begin")
        wake_word = None

        if should_enable_wake():
            try:
                keyword, sensitivity = get_wake_word_config()
                log.info(
                    f"startup.init.wake_word.config keyword={keyword} sensitivity={sensitivity}"
                )
                wake_word = WakeWordEngine(
                    keyword=keyword,
                    sensitivity=sensitivity,
                )
                log.info("startup.init.wake_word.done")
            except Exception as e:
                wake_word = None
                log.warning(f"startup.init.wake_word.failed_nonfatal | {e}")
        else:
            log.info("startup.init.wake_word.skipped")

        log.info("startup.init.recorder.begin")
        recorder = SpeechRecorder(
            sample_rate=SAMPLE_RATE,
            min_duration=RECORDER_MIN_DURATION,
        )
        log.info("startup.init.recorder.done")
    except Exception as e:
        log.exception(f"startup.init.failed | {e}")
        raise

    stt: SpeechToText | None = None
    stt_lock = threading.Lock()

    def get_stt() -> SpeechToText:
        nonlocal stt
        if stt is None:
            with stt_lock:
                if stt is None:
                    log.info("startup.init.stt.begin")
                    stt = SpeechToText()
                    log.info("startup.init.stt.done")
        return stt

    get_stt()

    def _start_worker() -> threading.Thread:
        t = threading.Thread(
            target=task_worker,
            args=(get_stt, session),
            daemon=True,
            name="safebox-task-worker",
        )
        t.start()
        return t

    worker = _start_worker()
    log.info("startup.task_worker.started")

    def finalize_recording(reason: str) -> None:
        path = recorder.stop_and_save()
        session.set_processing()
        device_request_id = getattr(recorder, "_device_request_id", None)

        log.info(
            f"recording.finalized reason={reason}",
            extra=with_request_id(device_request_id),
        )

        if path:
            task_queue.put((path, device_request_id))
        else:
            log.warning(
                "recording.no_path -> cooldown",
                extra=with_request_id(device_request_id),
            )
            session.set_cooldown()
            clear_request_id()

    def audio_callback(indata, frames, time_info, status) -> None:
        if status:
            log.warning(f"audio_callback.status | {status}", extra=with_request_id())

        if indata is None or len(indata) == 0:
            return

        session.tick()

        _, _, wake_pcm, speech_pcm, mono_record = front_end.split_channels(indata)
        front_end.push_preroll(speech_pcm)

        if session.can_run_wake():
            try:
                if consume_manual_voice_trigger():
                    device_request_id = new_request_id()
                    recorder._device_request_id = device_request_id

                    if session.speaking():
                        stop_audio()
                        log.info(
                            "barge_in.detected -> stop_audio",
                            extra=with_request_id(device_request_id),
                        )

                    log.info(
                        "manual.voice_trigger.detected",
                        extra=with_request_id(device_request_id),
                    )
                    try:
                        speak("Listening.")
                    except Exception as e:
                        log.warning(
                            f"manual.voice_trigger.announce_failed | {e}",
                            extra=with_request_id(device_request_id),
                        )

                    front_end.reset_vad()
                    preroll = front_end.get_preroll_audio()
                    recorder.start(initial_audio=preroll)
                    recorder.add(mono_record)
                    session.start_listening()
                    log.info(
                        "manual.voice_trigger -> state=LISTENING",
                        extra=with_request_id(device_request_id),
                    )
                    return

                if wake_word is not None and wake_word.process_audio(wake_pcm):
                    device_request_id = new_request_id()
                    recorder._device_request_id = device_request_id

                    if session.speaking():
                        stop_audio()
                        log.info(
                            "barge_in.detected -> stop_audio",
                            extra=with_request_id(device_request_id),
                        )

                    keyword, _ = get_wake_word_config()
                    log.info(
                        f"wake_word.detected keyword={keyword}",
                        extra=with_request_id(device_request_id),
                    )
                    front_end.reset_vad()
                    preroll = front_end.get_preroll_audio()
                    recorder.start(initial_audio=preroll)
                    recorder.add(mono_record)
                    session.start_listening()
                    log.info(
                        "wake.detected -> state=LISTENING",
                        extra=with_request_id(device_request_id),
                    )
                    return

            except Exception as e:
                log.warning(f"wake.process_failed | {e}", extra=with_request_id())

        if session.listening():
            recorder.add(mono_record)

            if session.get_post_wake_remaining() > 0:
                return

            speech_active = front_end.is_speech(speech_pcm)
            if speech_active:
                session.mark_speech_seen()

            if (
                not session.get_has_seen_speech()
                and session.get_speech_start_timeout_remaining() <= 0
            ):
                finalize_recording("speech_start_timeout")
                return

            if session.get_has_seen_speech() and not speech_active:
                finalize_recording("trailing_silence")
                return

            if session.get_max_utterance_remaining() <= 0:
                finalize_recording("max_utterance")
                return

    log.info("startup.stream.opening")
    print("[SYS] Listening...")

    with sd.InputStream(
        device=DEVICE,
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="int16",
        blocksize=FRAME_SIZE,
        callback=audio_callback,
    ):
        log.info("startup.stream.open")
        try:
            last_wake_retry = 0.0

            while True:
                now = time.time()

                if wake_word is None and now - last_wake_retry > 10:
                    wake_word = try_init_wake_word(wake_word)
                    last_wake_retry = now

                if not worker.is_alive():
                    log.error("task_worker.died -> restarting")
                    worker = _start_worker()

                worker.join(timeout=1)
        except KeyboardInterrupt:
            log.info("main.keyboard_interrupt -> shutting down")
            print("[SYS] Stopped by user")


if __name__ == "__main__":
    main()
