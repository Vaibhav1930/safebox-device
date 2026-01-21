from core.intent.normalize import normalize
from core.intent.matcher import match_intent
from core.intent.guard import is_safe

def process_command(text: str):
    clean = normalize(text)
    intent, confidence = match_intent(clean)

    if not is_safe(intent, confidence):
        return {
            "intent": None,
            "confidence": confidence,
            "safe": False,
        }

    return {
        "intent": intent,
        "confidence": round(confidence, 2),
        "safe": True,
    }
