from flask import Flask, jsonify, render_template
import subprocess
import socket
import time

app = Flask(__name__)

def is_online():
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=2)
        return True
    except OSError:
        return False

def get_uptime_seconds():
    uptime = subprocess.check_output("cut -d. -f1 /proc/uptime", shell=True)
    return int(uptime.strip())

def get_mode():
    return "cloud" if is_online() else "survival"

@app.route("/setup")
def setup():
    return render_template("setup.html")

@app.route("/status")
def status():
    data = {
        "online": is_online(),
        "mode": get_mode(),
        "uptime": get_uptime_seconds()
    }
    return render_template("status.html", data=data)

@app.route("/device/status")
def device_status():
    return jsonify({
        "online": is_online(),
        "mode": get_mode(),
        "uptime": get_uptime_seconds()
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
