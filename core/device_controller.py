#!/usr/bin/env python3
import os
import time
import socket
import subprocess
from core.logger import setup_logger, with_request_id
from core.survival_mode import SurvivalModeController
from core.cloud_heartbeat import send_heartbeat

CHECK_INTERVAL = 10
NETWORK_FAIL_THRESHOLD = 3
NETWORK_SUCCESS_THRESHOLD = 3
RUNTIME_DIR = "/opt/safebox/runtime"
MODE_FILE = os.path.join(RUNTIME_DIR, "mode")

device_logger = setup_logger("device", "device.log")
network_logger = setup_logger("network", "network.log")

def ensure_runtime():
    os.makedirs(RUNTIME_DIR, exist_ok=True)

def write_mode(mode: str):
    with open(MODE_FILE, "w") as f:
        f.write(mode)

def network_check():
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return True
    except OSError:
        return False

def health_snapshot():
    result = subprocess.run(["uptime", "-p"], capture_output=True, text=True)
    return result.stdout.strip()

def main():
    print("DEVICE_CONTROLLER: starting", flush=True)
    device_logger.info("device.booted", extra=with_request_id())
    ensure_runtime()
    survival = SurvivalModeController()

    online = network_check()
    current_state = "online" if online else "offline"
    success_count = NETWORK_SUCCESS_THRESHOLD if online else 0
    fail_count = 0 if online else NETWORK_FAIL_THRESHOLD
    current_mode = "cloud" if current_state == "online" else "survival"
    write_mode(current_mode)

    device_logger.warning(
        f"[BOOT] initial_state={current_state}, mode={current_mode}",
        extra=with_request_id()
    )

    if current_mode == "survival":
        survival.enter()
        survival.run_cycle()

    while True:
        online = network_check()

        if online:
            success_count += 1
            fail_count = 0
        else:
            fail_count += 1
            success_count = 0

        # ---- NETWORK TRANSITIONS ----
        if success_count >= NETWORK_SUCCESS_THRESHOLD and current_state != "online":
            current_state = "online"
            network_logger.warning(
                f"[NET] OFFLINE -> ONLINE | successes={success_count} threshold={NETWORK_SUCCESS_THRESHOLD}",
                extra=with_request_id()
            )

        if fail_count >= NETWORK_FAIL_THRESHOLD and current_state != "offline":
            current_state = "offline"
            network_logger.warning(
                f"[NET] ONLINE -> OFFLINE | failures={fail_count} threshold={NETWORK_FAIL_THRESHOLD}",
                extra=with_request_id()
            )

        # ---- MODE DECISION ----
        new_mode = "cloud" if current_state == "online" else "survival"

        if new_mode != current_mode:
            device_logger.warning(
                f"[MODE] {current_mode.upper()} -> {new_mode.upper()} | failures={fail_count} successes={success_count}",
                extra=with_request_id()
            )
            if new_mode == "survival":
                survival.enter()
            else:
                survival.exit()
            write_mode(new_mode)
            current_mode = new_mode

        # ---- SURVIVAL CYCLE ----
        if current_mode == "survival":
            survival.run_cycle()

        # ---- HEARTBEAT ----
        send_heartbeat({
            "device_id": "safebox-001",
            "mode": current_mode,
            "online": current_mode == "cloud",
            "uptime": health_snapshot(),
            "timestamp": time.time(),
        })

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
