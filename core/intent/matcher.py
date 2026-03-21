from difflib import SequenceMatcher
from core.intent.intents import INTENTS


def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()


def match_intent(text: str):
    
    text_lower = text.lower().strip()

    best_intent = None
    best_score  = 0.0

    for intent, phrases in INTENTS.items():
        for phrase in phrases:
            phrase_lower = phrase.lower()

            
            if text_lower == phrase_lower:
                return intent, 1.0

            
            if text_lower.startswith(phrase_lower):
                score = 0.95
                if score > best_score:
                    best_score  = score
                    best_intent = intent
                continue

            
            if phrase_lower in text_lower:
                score = 0.90
                if score > best_score:
                    best_score  = score
                    best_intent = intent
                continue

            
            score = similarity(text_lower, phrase_lower)
            if score > best_score:
                best_score  = score
                best_intent = intent

    return best_intent, best_score
