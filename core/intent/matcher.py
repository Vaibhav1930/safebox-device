from difflib import SequenceMatcher
from core.intent.intents import INTENTS

def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()

def match_intent(text: str):
    best_intent = None
    best_score = 0.0

    for intent, phrases in INTENTS.items():
        for phrase in phrases:
            score = similarity(text, phrase)
            if score > best_score:
                best_score = score
                best_intent = intent

    return best_intent, best_score
