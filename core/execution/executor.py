# core/execution/executor.py

import time
from core.logger import get_logger

log = get_logger("EXECUTOR")


def execute_intent(result: dict):
    """
    Executes a SAFE and CONFIRMED intent.
    """
    intent = result.get("intent")

    log.info(f"Executing intent: {intent}")

    if intent == "STATUS":
        handle_status()

    elif intent == "OPEN_BOX":
        handle_open_box()

    elif intent == "CLOSE_BOX":
        handle_close_box()

    else:
        log.warning(f"No executor for intent: {intent}")


# ---------------- HANDLERS ---------------- #

def handle_status():
    log.info("Status requested")
    print("?? Safebox is ONLINE and LOCKED")


def handle_open_box():
    log.info("Opening box...")
    print("?? Box OPEN command issued")
    time.sleep(0.5)
    print("? Box opened (simulated)")


def handle_close_box():
    log.info("Closing box...")
    print("?? Box CLOSE command issued")
    time.sleep(0.5)
    print("? Box closed (simulated)")
