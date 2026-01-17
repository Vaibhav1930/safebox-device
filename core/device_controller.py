#!/usr/bin/env python3
import os
import time
import socket
from datetime import datetime, timezone

from core.cloud_heartbeat import send_heartbeat
from core.survival_mode import SurvivalModeController
from core.logger import setup_logger, with_request_id

LOG_FILE = "/opt/safebox/logs/device.log"

CHECK_INTERVAL = 10          # seconds
DEBOUNCE_COUNT = 3           # prevent flapping

device_logger = setup_logger("device", "device.log")
network_logger = setup_logger("network", "network.log")


def network_check():
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return True
    except OSError:
        return False


def decide_mode(network_state):
    return "cloud" if network_state == "online" else "survival"


def health_snapshot():
    return os.popen("uptime -p").read().strip()


def main():
    device_logger.info("booted", extra=with_request_id())

    survival = SurvivalModeController()

    success_count = 0
    fail_count = 0
    current_state = "offline"
    current_mode = None

    while True:
        online = network_check()

        # ---- NETWORK DEBOUNCE ----
        if online:
            success_count += 1
            fail_count = 0
        else:
            fail_count += 1
            success_count = 0

        if success_count >= DEBOUNCE_COUNT and current_state != "online":
            current_state = "online"
            network_logger.info(
                "offline -> online",
                extra=with_request_id()
            )

        if fail_count >= DEBOUNCE_COUNT and current_state != "offline":
            current_state = "offline"
            network_logger.info(
                "online -> offline",
                extra=with_request_id()
            )

        # ---- MODE DECISION ----
        mode = decide_mode(current_state)
        health = health_snapshot()

        # ---- MODE TRANSITION (SIDE EFFECTS ONLY HERE) ----
        if mode != current_mode:
            device_logger.info(
                f"mode.transition {current_mode} -> {mode}",
                extra=with_request_id()
            )

            if mode == "survival":
                survival.enter()
            else:
                survival.exit()

            current_mode = mode

        # ---- HEARTBEAT / STATUS LOG ----
        device_logger.info(
            f"mode={current_mode} health={health}",
            extra=with_request_id()
        )

        heartbeat_payload = {
            "device_id": "safebox-001",
            "mode": current_mode,
            "online": (current_mode == "cloud"),
            "uptime": health,
            "timestamp": time.time()
        }

        send_heartbeat(heartbeat_payload)

        # ---- SURVIVAL EXECUTION (NO RE-ENTRY) ----
        if current_mode == "survival":
            survival.run_cycle()

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
