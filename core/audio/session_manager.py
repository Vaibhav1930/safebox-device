from dataclasses import dataclass


STATE_IDLE = "idle"
STATE_WAKE_DETECTED = "wake_detected"
STATE_LISTENING = "listening"
STATE_PROCESSING = "processing"
STATE_SPEAKING = "speaking"
STATE_COOLDOWN = "cooldown"


@dataclass
class SessionConfig:
    post_wake_grace_frames: int
    speech_start_timeout_frames: int
    max_utterance_frames: int
    cooldown_frames: int


class SessionManager:
    def __init__(self, config: SessionConfig):
        self.config = config
        self.state = STATE_IDLE
        self.post_wake_remaining = 0
        self.speech_start_timeout_remaining = 0
        self.max_utterance_remaining = 0
        self.cooldown_remaining = 0
        self.has_seen_speech = False

    def set_idle(self):
        self.state = STATE_IDLE
        self.post_wake_remaining = 0
        self.speech_start_timeout_remaining = 0
        self.max_utterance_remaining = 0
        self.has_seen_speech = False

    def set_speaking(self):
        self.state = STATE_SPEAKING

    def set_processing(self):
        self.state = STATE_PROCESSING

    def set_cooldown(self):
        self.state = STATE_COOLDOWN
        self.cooldown_remaining = self.config.cooldown_frames
        self.post_wake_remaining = 0
        self.speech_start_timeout_remaining = 0
        self.max_utterance_remaining = 0
        self.has_seen_speech = False

    def start_listening(self):
        self.state = STATE_LISTENING
        self.post_wake_remaining = self.config.post_wake_grace_frames
        self.speech_start_timeout_remaining = self.config.speech_start_timeout_frames
        self.max_utterance_remaining = self.config.max_utterance_frames
        self.has_seen_speech = False

    def tick(self):
        if self.state == STATE_COOLDOWN and self.cooldown_remaining > 0:
            self.cooldown_remaining -= 1
            if self.cooldown_remaining <= 0:
                self.set_idle()

        if self.state == STATE_LISTENING:
            if self.post_wake_remaining > 0:
                self.post_wake_remaining -= 1

            if self.speech_start_timeout_remaining > 0 and not self.has_seen_speech:
                self.speech_start_timeout_remaining -= 1

            if self.max_utterance_remaining > 0:
                self.max_utterance_remaining -= 1

    def can_run_wake(self) -> bool:
        return self.state in (STATE_IDLE, STATE_SPEAKING)

    def in_cooldown(self) -> bool:
        return self.state == STATE_COOLDOWN

    def listening(self) -> bool:
        return self.state == STATE_LISTENING

    def speaking(self) -> bool:
        return self.state == STATE_SPEAKING

    def processing(self) -> bool:
        return self.state == STATE_PROCESSING
