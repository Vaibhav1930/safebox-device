from flask import Flask, jsonify, render_template
import subprocess
import socket
import time
import os

app = Flask(__name__, template_folder="templates")

# --------------------------------------------------
# Helpers
# --------------------------------------------------

def is_online() -> bool:
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=2)
        return True
    except OSError:
        return False


def get_uptime_seconds() -> int:
    with open("/proc/uptime", "r") as f:
        return int(float(f.readline().split()[0]))


def get_mode() -> str:
    return "cloud" if is_online() else "survival"


def status_payload() -> dict:
    return {
        "online": is_online(),
        "mode": get_mode(),
        "uptime": get_uptime_seconds(),
        "timestamp": time.time()
    }

# --------------------------------------------------
# UI Routes
# --------------------------------------------------

@app.route("/setup")
def setup():
    return render_template("setup.html")


@app.route("/status")
def status():
    return render_template("status.html", data=status_payload())

# --------------------------------------------------
# API Routes
# --------------------------------------------------

@app.route("/device/status")
def device_status():
    return jsonify(status_payload())


@app.route("/health")
def health():
    return jsonify({
        "ok": True,
        "service": "web",
        "timestamp": time.time()
    })

# --------------------------------------------------
# Entry Point
# --------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
