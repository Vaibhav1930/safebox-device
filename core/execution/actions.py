# core/execution/actions.py

def open_box():
    print("[EXEC] Opening box")
    # TODO: GPIO / motor / relay
    # Example:
    # gpio.open_relay()

def close_box():
    print("[EXEC] Closing box")

def get_status():
    print("[EXEC] Fetching status")
    return {
        "box": "closed",
        "battery": "80%",
        "lock": "armed"
    }
