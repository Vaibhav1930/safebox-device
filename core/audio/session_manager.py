"""
session_manager.py — SafeBox audio session state machine

STATE MACHINE:
    IDLE ──wake/trigger──► LISTENING ──finalize──► PROCESSING
                                                        │
    IDLE ◄──cooldown expires── COOLDOWN ◄──────────────┘
                                              (via set_cooldown)
    SPEAKING is entered while TTS plays; wake word can still fire
    from SPEAKING state (barge-in support).

THREAD SAFETY:
    audio_callback (sounddevice thread) calls: tick(), can_run_wake(),
    listening(), speaking(), start_listening().

    task_worker thread calls: set_processing(), set_speaking(),
    set_cooldown(), set_idle().

    All public methods are protected by a single re-entrant lock so
    state is never observed half-written across threads.
"""

import threading
from dataclasses import dataclass

# ── States ────────────────────────────────────────────────────────────────────
STATE_IDLE       = "idle"
STATE_LISTENING  = "listening"
STATE_PROCESSING = "processing"
STATE_SPEAKING   = "speaking"
STATE_COOLDOWN   = "cooldown"


@dataclass
class SessionConfig:
    post_wake_grace_frames:      int
    speech_start_timeout_frames: int
    max_utterance_frames:        int
    cooldown_frames:             int


class SessionManager:
    """
    Thread-safe audio session state machine.

    All methods acquire self._lock before reading or writing state so
    the audio callback thread and the task worker thread never race.
    """

    def __init__(self, config: SessionConfig) -> None:
        self.config = config
        self._lock  = threading.Lock()

        # State
        self.state = STATE_IDLE

        # Countdown counters (in frames)
        self.post_wake_remaining              = 0
        self.speech_start_timeout_remaining   = 0
        self.max_utterance_remaining          = 0
        self.cooldown_remaining               = 0

        # VAD flag
        self.has_seen_speech = False

    # ── Transitions (called from task_worker thread) ──────────────────────────

    def set_idle(self) -> None:
        with self._lock:
            self.state                          = STATE_IDLE
            self.post_wake_remaining            = 0
            self.speech_start_timeout_remaining = 0
            self.max_utterance_remaining        = 0
            self.cooldown_remaining             = 0
            self.has_seen_speech                = False

    def set_speaking(self) -> None:
        with self._lock:
            self.state = STATE_SPEAKING

    def set_processing(self) -> None:
        with self._lock:
            self.state = STATE_PROCESSING

    def set_cooldown(self) -> None:
        with self._lock:
            self.state                          = STATE_COOLDOWN
            self.cooldown_remaining             = self.config.cooldown_frames
            self.post_wake_remaining            = 0
            self.speech_start_timeout_remaining = 0
            self.max_utterance_remaining        = 0
            self.has_seen_speech                = False

    # ── Transitions (called from audio_callback thread) ───────────────────────

    def start_listening(self) -> None:
        with self._lock:
            self.state                          = STATE_LISTENING
            self.post_wake_remaining            = self.config.post_wake_grace_frames
            self.speech_start_timeout_remaining = self.config.speech_start_timeout_frames
            self.max_utterance_remaining        = self.config.max_utterance_frames
            self.has_seen_speech                = False

    def tick(self) -> None:
        """Advance all frame counters by one. Called once per audio frame."""
        with self._lock:
            if self.state == STATE_COOLDOWN:
                if self.cooldown_remaining > 0:
                    self.cooldown_remaining -= 1
                if self.cooldown_remaining <= 0:
                    # Transition back to idle inline — no external call needed.
                    self.state                          = STATE_IDLE
                    self.post_wake_remaining            = 0
                    self.speech_start_timeout_remaining = 0
                    self.max_utterance_remaining        = 0
                    self.has_seen_speech                = False

            elif self.state == STATE_LISTENING:
                if self.post_wake_remaining > 0:
                    self.post_wake_remaining -= 1

                if self.speech_start_timeout_remaining > 0 and not self.has_seen_speech:
                    self.speech_start_timeout_remaining -= 1

                if self.max_utterance_remaining > 0:
                    self.max_utterance_remaining -= 1

    # ── Queries (called from audio_callback thread) ───────────────────────────

    def can_run_wake(self) -> bool:
        """
        Wake word detection and manual trigger checks run only when
        idle or speaking (barge-in). Never run during recording,
        processing, or cooldown — those states have their own handlers.
        """
        with self._lock:
            return self.state in (STATE_IDLE, STATE_SPEAKING)

    def listening(self) -> bool:
        with self._lock:
            return self.state == STATE_LISTENING

    def speaking(self) -> bool:
        with self._lock:
            return self.state == STATE_SPEAKING

    def processing(self) -> bool:
        with self._lock:
            return self.state == STATE_PROCESSING

    def in_cooldown(self) -> bool:
        with self._lock:
            return self.state == STATE_COOLDOWN

    # ── VAD flag (written from audio_callback, readable from both) ────────────

    def mark_speech_seen(self) -> None:
        with self._lock:
            self.has_seen_speech = True

    def get_has_seen_speech(self) -> bool:
        with self._lock:
            return self.has_seen_speech

    def get_post_wake_remaining(self) -> int:
        with self._lock:
            return self.post_wake_remaining

    def get_speech_start_timeout_remaining(self) -> int:
        with self._lock:
            return self.speech_start_timeout_remaining

    def get_max_utterance_remaining(self) -> int:
        with self._lock:
            return self.max_utterance_remaining

    def get_state(self) -> str:
        with self._lock:
            return self.state
