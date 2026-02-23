from flask import Flask, jsonify, render_template, request, redirect, url_for
from core.cloud_heartbeat import send_heartbeat
from core.survival_mode import SurvivalModeController

import subprocess
import time
import json
import os
import shutil
from werkzeug.utils import secure_filename

# --------------------------------------------------
# Paths
# --------------------------------------------------

BASE_DIR = "/opt/safebox"
CONFIG_FILE = f"{BASE_DIR}/config/device_config.json"
VAULT_DIR = f"{BASE_DIR}/vault/uploads"

# --------------------------------------------------
# App Init
# --------------------------------------------------

app = Flask(__name__, template_folder="templates")
app.config["UPLOAD_FOLDER"] = VAULT_DIR

# Global survival controller (read-only for UI)
survival_controller = SurvivalModeController()

# --------------------------------------------------
# Utilities
# --------------------------------------------------

@app.route("/")
def home():
    return redirect("/setup")
def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def save_config(data):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)

def is_cloud_api_alive():
    try:
        return send_heartbeat({"source": "web-status", "status": "check"})
    except Exception:
        return False

def get_uptime():
    with open("/proc/uptime") as f:
        return int(float(f.readline().split()[0]))

def get_disk_usage():
    total, used, free = shutil.disk_usage("/")
    return {
        "total_gb": round(total / (1024**3), 2),
        "used_gb": round(used / (1024**3), 2),
        "free_gb": round(free / (1024**3), 2)
    }

def count_vault_files():
    if not os.path.exists(VAULT_DIR):
        return 0
    return len(os.listdir(VAULT_DIR))
def scan_wifi_networks():
    try:
        # Force fresh WiFi scan
        subprocess.run(
            ["nmcli", "device", "wifi", "rescan"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5
        )

        time.sleep(2)

        result = subprocess.run(
            ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list"],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            print("NMCLI ERROR:", result.stderr)
            return []

        networks = []

        for line in result.stdout.strip().split("\n"):
            if not line:
                continue

            parts = line.split(":")
            if len(parts) >= 3:
                ssid = parts[0]
                signal = parts[1]
                security = parts[2]

                if ssid:
                    networks.append({
                        "ssid": ssid,
                        "signal": signal,
                        "security": security
                    })

        # Remove duplicates by SSID
        unique = {n["ssid"]: n for n in networks}
        return list(unique.values())

    except Exception as e:
        print("WiFi scan error:", e)
        return []
def get_current_wifi():
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"],
            capture_output=True,
            text=True,
            timeout=5
        )

        for line in result.stdout.strip().split("\n"):
            if line.startswith("yes:"):
                return line.split(":")[1]

        return None

    except Exception:
        return None
def status_payload():
    cloud_alive = is_cloud_api_alive()
    survival_active = survival_controller.active

    if survival_active:
        mode = "survival"
    else:
        mode = "cloud" if cloud_alive else "survival"

    return {
        "cloud_api_alive": cloud_alive,
        "survival_active": survival_active,
        "mode": mode,
        "uptime": get_uptime(),
        "disk": get_disk_usage(),
        "vault_files": count_vault_files(),
        "timestamp": time.time()
    }

# --------------------------------------------------
# Setup Routes
# --------------------------------------------------

@app.route("/setup", methods=["GET", "POST"])
def setup():
    config = load_config()
    error_message = None
    success_message = None

    if request.method == "POST":
        device_name = request.form.get("device_name")
        wifi_ssid = request.form.get("wifi_ssid")
        wifi_password = request.form.get("wifi_password")

        config["device_name"] = device_name
        config["wifi_ssid"] = wifi_ssid
        save_config(config)

        current_ssid = get_current_wifi()

# If already connected to selected network
        if wifi_ssid and wifi_ssid == current_ssid:
            return redirect(url_for("status"))

        # Otherwise attempt connection
        if wifi_ssid and wifi_password:
            try:
                result = subprocess.run(
                    [
                        "nmcli", "dev", "wifi", "connect",
                        wifi_ssid,
                        "password",
                        wifi_password
                    ],
                    capture_output=True,
                    text=True,
                    timeout=20
                )

                if result.returncode == 0:
                    return redirect(url_for("status"))
                else:
                    error_message = "Failed to connect. Check password."

            except subprocess.TimeoutExpired:
                error_message = "Connection timed out."

            except Exception as e:
                error_message = f"WiFi error: {e}"

    return render_template(
    "setup.html",
    config=config,
    networks=scan_wifi_networks(),
    current_wifi=get_current_wifi(),
    error=error_message
)
# --------------------------------------------------
# Status UI
# --------------------------------------------------

@app.route("/status")
def status():
    return render_template("status.html", data=status_payload())

# --------------------------------------------------
# Vault Upload
# --------------------------------------------------

@app.route("/vault/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return "No file", 400

    file = request.files["file"]
    filename = secure_filename(file.filename)

    os.makedirs(VAULT_DIR, exist_ok=True)
    file.save(os.path.join(VAULT_DIR, filename))

    return redirect(url_for("status"))

# --------------------------------------------------
# API
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
# Run (for manual testing only)
# --------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
