CONFIDENCE_THRESHOLD = 0.75

def is_safe(intent, confidence):
    if intent is None:
        return False
    if confidence < CONFIDENCE_THRESHOLD:
        return False
    return True
