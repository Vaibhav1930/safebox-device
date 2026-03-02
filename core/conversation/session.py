# core/conversation/session.py

class ConversationSession:
    def __init__(self, max_turns=6):
        self.history = []
        self.max_turns = max_turns

    def add_user(self, text: str):
        self.history.append(("User", text))
        self._trim()

    def add_assistant(self, text: str):
        self.history.append(("Assistant", text))
        self._trim()

    def build_prompt(self, new_user_text: str) -> str:
        self.add_user(new_user_text)

        prompt = ""
        for role, text in self.history:
            prompt += f"{role}: {text}\n"

        return prompt.strip()

    def _trim(self):
        if len(self.history) > self.max_turns:
            self.history = self.history[-self.max_turns:]
