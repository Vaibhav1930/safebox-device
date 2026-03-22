#!/usr/bin/env bash
# =============================================================================
# SafeBox Production Installer
# Tested on: Raspberry Pi 5, Raspberry Pi OS Lite 64-bit (Bookworm)
# Run as: bash deployment/install.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "===== SafeBox Production Installer ====="
echo "Project root : $PROJECT_ROOT"
echo "Running as   : $USER"
echo ""

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
INSTALL_DIR="/opt/safebox"
SSD_DIR="/mnt/ssd/safebox-device"
RUNTIME_DIR="$INSTALL_DIR/runtime"
ENV_DIR="/etc/safebox"
ENV_FILE="$ENV_DIR/safebox.env"
SERVICE_USER="$USER"
LLAMA_DIR="/opt/llama.cpp"
UNITS=("llama-server" "safebox-cloud" "safebox-wake" "safebox-web" "safebox-device")

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
info()  { echo "[INFO]  $*"; }
ok()    { echo "[OK]    $*"; }
warn()  { echo "[WARN]  $*"; }
die()   { echo "[ERROR] $*" >&2; exit 1; }

check_pi() {
    if ! grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
        warn "Not running on a Raspberry Pi — some hardware steps may fail."
    fi
}

# ---------------------------------------------------------------------------
# 1. System dependencies
# ---------------------------------------------------------------------------
install_system_deps() {
    info "Installing system dependencies..."
    sudo apt-get update -qq

    sudo apt-get install -y \
        python3 python3-venv python3-full python3-pip \
        git build-essential cmake pkg-config \
        libasound2-dev portaudio19-dev \
        wget curl nmap \
        \
        bluez bluetooth bluez-tools \
        playerctl pipewire pipewire-pulse wireplumber \
        libspa-0.2-bluetooth \
        \
        network-manager \
        \
        libnfc-bin libnfc-dev \
        \
        python3-libgpiod \
        libgpiod-dev \
        \
        i2c-tools \
        \
        ffmpeg \
        \
        jq

    ok "System dependencies installed."
}

# ---------------------------------------------------------------------------
# 2. Enable SPI and I2C for PN532 NFC reader
# ---------------------------------------------------------------------------
enable_interfaces() {
    info "Enabling SPI and I2C interfaces..."

    # Enable SPI
    if ! grep -q "^dtparam=spi=on" /boot/firmware/config.txt 2>/dev/null && \
       ! grep -q "^dtparam=spi=on" /boot/config.txt 2>/dev/null; then
        CONFIG_FILE="/boot/firmware/config.txt"
        [ -f "/boot/config.txt" ] && CONFIG_FILE="/boot/config.txt"
        echo "dtparam=spi=on" | sudo tee -a "$CONFIG_FILE" > /dev/null
        ok "SPI enabled in $CONFIG_FILE"
    else
        ok "SPI already enabled."
    fi

    # Enable I2C
    if ! grep -q "^dtparam=i2c_arm=on" /boot/firmware/config.txt 2>/dev/null && \
       ! grep -q "^dtparam=i2c_arm=on" /boot/config.txt 2>/dev/null; then
        CONFIG_FILE="/boot/firmware/config.txt"
        [ -f "/boot/config.txt" ] && CONFIG_FILE="/boot/config.txt"
        echo "dtparam=i2c_arm=on" | sudo tee -a "$CONFIG_FILE" > /dev/null
        ok "I2C enabled in $CONFIG_FILE"
    else
        ok "I2C already enabled."
    fi

    # Enable 1-Wire for DS18B20 temperature sensor (GPIO 4)
    if ! grep -q "dtoverlay=w1-gpio" /boot/firmware/config.txt 2>/dev/null && \
       ! grep -q "dtoverlay=w1-gpio" /boot/config.txt 2>/dev/null; then
        CONFIG_FILE="/boot/firmware/config.txt"
        [ -f "/boot/config.txt" ] && CONFIG_FILE="/boot/config.txt"
        echo "dtoverlay=w1-gpio,gpiopin=4" | sudo tee -a "$CONFIG_FILE" > /dev/null
        ok "1-Wire enabled in $CONFIG_FILE (GPIO 4 for DS18B20)"
    else
        ok "1-Wire already enabled."
    fi

    # Add user to required groups
    sudo usermod -aG spi,i2c,gpio,bluetooth,audio,dialout "$SERVICE_USER" 2>/dev/null || true
    ok "User $SERVICE_USER added to hardware groups."
}

# ---------------------------------------------------------------------------
# 3. SSD mount setup
# ---------------------------------------------------------------------------
setup_ssd() {
    info "Setting up SSD mount at $SSD_DIR..."

    sudo mkdir -p "$SSD_DIR/vault/notes"
    sudo mkdir -p "$SSD_DIR/vault/interactions"
    sudo mkdir -p "$SSD_DIR/core"
    sudo mkdir -p "$SSD_DIR/core/audio"
    sudo mkdir -p "$SSD_DIR/core/execution"
    sudo mkdir -p "$SSD_DIR/core/intent"
    sudo mkdir -p "$SSD_DIR/web/templates"
    sudo chown -R "$SERVICE_USER:$SERVICE_USER" /mnt/ssd 2>/dev/null || true

    ok "SSD directories created."
}

# ---------------------------------------------------------------------------
# 4. Install project to /opt/safebox
# ---------------------------------------------------------------------------
install_project() {
    info "Installing project to $INSTALL_DIR..."

    sudo rm -rf "$INSTALL_DIR"
    sudo mkdir -p "$INSTALL_DIR"
    sudo cp -r "$PROJECT_ROOT/." "$INSTALL_DIR/"
    sudo chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

    # Create runtime and log directories
    mkdir -p "$RUNTIME_DIR"
    mkdir -p "$INSTALL_DIR/logs"
    mkdir -p "$INSTALL_DIR/models"
    mkdir -p "$INSTALL_DIR/vault/interactions"

    # Write initial mode file so services don't fail on first read
    echo "cloud" > "$RUNTIME_DIR/mode"

    ok "Project installed to $INSTALL_DIR."
}

# ---------------------------------------------------------------------------
# 5. Environment file
# ---------------------------------------------------------------------------
setup_env() {
    info "Creating environment file at $ENV_FILE..."

    sudo mkdir -p "$ENV_DIR"

    # Only create if it doesn't exist — never overwrite secrets
    if [ ! -f "$ENV_FILE" ]; then
        sudo tee "$ENV_FILE" > /dev/null << 'ENV'
# SafeBox Environment Configuration
# Edit this file with your actual credentials before starting services.

# ── Device ──────────────────────────────────────────
DEVICE_NAME=safebox-001
ENV=production
LOG_LEVEL=INFO

# ── Cloud API ───────────────────────────────────────
# CLARITY_API_BASE_URL=https://your-cloud-api-url

# ── Vault Storage ───────────────────────────────────
SAFEBOX_VAULT_ROOT=/mnt/ssd/safebox-device/vault

# ── Smart Plug (Tapo/Kasa) ──────────────────────────
# TAPO_PLUG_IP=192.168.1.x
# TAPO_USER=your-tapo-email
# TAPO_PASS=your-tapo-password

# ── PipeWire / Audio (do not change unless you know why) ──
XDG_RUNTIME_DIR=/run/user/1000
DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
PIPEWIRE_RUNTIME_DIR=/run/user/1000
PULSE_SERVER=unix:/run/user/1000/pulse/native
ENV
        sudo chown root:"$SERVICE_USER" "$ENV_FILE"
        sudo chmod 640 "$ENV_FILE"
        ok "Environment file created. Edit $ENV_FILE before starting services."
    else
        ok "Environment file already exists — not overwritten."
    fi
}

# ---------------------------------------------------------------------------
# 6. Python virtual environment + pip packages
# ---------------------------------------------------------------------------
install_python_deps() {
    info "Creating Python virtual environment..."

    cd "$INSTALL_DIR"
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip wheel setuptools

    info "Installing Python packages..."
    # Install numpy first — it's a base dependency for sounddevice and faster-whisper
    pip install numpy
    pip install -r requirements.txt
    pip install -r cloud/requirements.txt

    # Verify critical packages installed correctly
    python -c "import numpy, sounddevice, flask, requests" || die "Critical Python packages failed to install"

    deactivate
    ok "Python environment ready."
}

# ---------------------------------------------------------------------------
# 7. Adafruit Blinka + PN532 NFC library
# ---------------------------------------------------------------------------
install_nfc_libs() {
    info "Installing NFC libraries (Adafruit Blinka + PN532)..."

    # lgpio system package required by adafruit-blinka on Pi 5.
    # Do NOT install lgpio via pip — it requires swig to build and fails.
    # Copy the pre-compiled system .so directly into the venv instead.
    sudo apt-get install -y python3-lgpio swig

    VENV_SITE="$INSTALL_DIR/venv/lib/python3.$(python3 -c 'import sys; print(sys.version_info.minor)')/site-packages"
    find /usr/lib/python3 -name "*lgpio*" ! -type d -exec cp {} "$VENV_SITE/" \; 2>/dev/null || true
    ok "lgpio copied to venv."

    cd "$INSTALL_DIR"
    source venv/bin/activate

    pip install \
        adafruit-blinka \
        adafruit-circuitpython-pn532 \
        RPi.GPIO

    deactivate
    ok "NFC libraries installed."
}

# ---------------------------------------------------------------------------
# 8. python-kasa for Tapo/Kasa smart plug
# ---------------------------------------------------------------------------
install_kasa() {
    info "Installing python-kasa for smart plug control..."

    cd "$INSTALL_DIR"
    source venv/bin/activate
    pip install python-kasa
    deactivate

    ok "python-kasa installed."
}

# ---------------------------------------------------------------------------
# 9. llama.cpp for local LLM (Survival Mode)
# ---------------------------------------------------------------------------
install_llama() {
    info "Installing llama.cpp..."

    if [ ! -d "$LLAMA_DIR" ]; then
        sudo git clone https://github.com/ggerganov/llama.cpp.git "$LLAMA_DIR"
        sudo chown -R "$SERVICE_USER:$SERVICE_USER" "$LLAMA_DIR"
    else
        ok "llama.cpp already cloned."
    fi

    if [ ! -f "$LLAMA_DIR/build/bin/llama-server" ]; then
        info "Building llama.cpp (this takes ~10 minutes on Pi 5)..."
        cd "$LLAMA_DIR"
        cmake -B build -DGGML_NATIVE=OFF
        cmake --build build --config Release -j4
        cd "$INSTALL_DIR"
        ok "llama.cpp built."
    else
        ok "llama.cpp already built."
    fi
}

# ---------------------------------------------------------------------------
# 10. TinyLlama model
# ---------------------------------------------------------------------------
install_model() {
    MODEL_FILE="$INSTALL_DIR/models/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
    MODEL_URL="https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"

    if [ ! -s "$MODEL_FILE" ]; then
        info "Downloading TinyLlama model (~638MB)..."
        curl -L --progress-bar -o "$MODEL_FILE" "$MODEL_URL"
        [ -s "$MODEL_FILE" ] || die "TinyLlama download failed or file is empty."
        ok "TinyLlama downloaded."
    else
        ok "TinyLlama already exists."
    fi
}

# ---------------------------------------------------------------------------
# 11. Piper TTS
# ---------------------------------------------------------------------------
install_piper() {
    info "Installing Piper TTS..."

    PIPER_DIR="$INSTALL_DIR/piper"
    PIPER_VENV="$PIPER_DIR/venv"
    PIPER_MODEL_DIR="$INSTALL_DIR/models/piper"

    mkdir -p "$PIPER_DIR" "$PIPER_MODEL_DIR"

    if [ ! -d "$PIPER_VENV" ]; then
        python3 -m venv "$PIPER_VENV"
    fi

    source "$PIPER_VENV/bin/activate"
    pip install --upgrade pip
    pip install piper-tts pathvalidate
    deactivate

    ONNX_FILE="$PIPER_MODEL_DIR/en_US-lessac-medium.onnx"
    JSON_FILE="$PIPER_MODEL_DIR/en_US-lessac-medium.onnx.json"
    BASE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"

    [ -f "$ONNX_FILE" ] || wget -q --show-progress -O "$ONNX_FILE" "$BASE_URL/en_US-lessac-medium.onnx"
    [ -f "$JSON_FILE" ] || wget -q --show-progress -O "$JSON_FILE" "$BASE_URL/en_US-lessac-medium.onnx.json"

    [ -f "$ONNX_FILE" ] && [ -f "$JSON_FILE" ] || die "Piper model download failed."
    ok "Piper TTS installed."
}

# ---------------------------------------------------------------------------
# 12. Bluetooth A2DP sink setup (PipeWire)
# ---------------------------------------------------------------------------
setup_bluetooth() {
    info "Configuring Bluetooth A2DP sink..."

    # Enable and start bluetooth
    sudo systemctl enable bluetooth
    sudo systemctl start bluetooth

    # Set Pi as always discoverable and pairable
    sudo tee /etc/bluetooth/main.conf > /dev/null << 'BT'
[Policy]
AutoEnable=true

[General]
DiscoverableTimeout=0
PairableTimeout=0
JustWorksRepairing=always

[GATT]
Cache=always
BT

    # Set up auto-accept Bluetooth agent as a persistent systemd service
    sudo tee /etc/systemd/system/bt-agent.service > /dev/null << 'BTAGENT'
[Unit]
Description=Bluetooth Auto-Accept Agent
After=bluetooth.service
Requires=bluetooth.service

[Service]
Type=simple
ExecStart=/usr/bin/bt-agent -c NoInputNoOutput
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
BTAGENT

    # Enable bt-agent if bt-agent binary exists, otherwise use bluetoothctl
    if command -v bt-agent &>/dev/null; then
        sudo systemctl enable bt-agent
        sudo systemctl start bt-agent
        ok "bt-agent auto-accept service enabled"
    else
        sudo apt-get install -y bluez-tools 2>/dev/null || true
        if command -v bt-agent &>/dev/null; then
            sudo systemctl enable bt-agent
            sudo systemctl start bt-agent
            ok "bt-agent auto-accept service enabled"
        else
            ok "bt-agent not available — pairing will use bluetoothctl agent"
        fi
    fi

    ok "Bluetooth configured."
}

# ---------------------------------------------------------------------------
# 13. Systemd service files
# ---------------------------------------------------------------------------
install_services() {
    info "Installing systemd services..."

    # Replace hardcoded 'vaibhav' username with actual SERVICE_USER
    for service in "${UNITS[@]}"; do
        SRC="$INSTALL_DIR/deployment/systemd/$service.service"
        DST="/etc/systemd/system/$service.service"
        sudo sed "s/User=vaibhav/User=$SERVICE_USER/g" "$SRC" | sudo tee "$DST" > /dev/null
    done

    sudo systemctl daemon-reload

    for u in "${UNITS[@]}"; do
        sudo systemctl enable "$u"
    done

    ok "Services installed and enabled."
}

# ---------------------------------------------------------------------------
# 14. Sync project to SSD (so safebox-wake loads correct code)
# ---------------------------------------------------------------------------
sync_to_ssd() {
    info "Syncing project files to SSD at $SSD_DIR..."

    # Core modules that safebox-wake loads from SSD
    for f in \
        core/nfc_manager.py \
        core/smart_plug.py \
        core/execution/executor.py \
        core/intent/intents.py \
        core/intent/matcher.py \
        core/intent/pipeline.py \
        core/audio/mic_stream.py \
        web/app.py \
        web/templates/status.html
    do
        SRC="$INSTALL_DIR/$f"
        DST="$SSD_DIR/$f"
        if [ -f "$SRC" ]; then
            mkdir -p "$(dirname "$DST")"
            cp "$SRC" "$DST"
        fi
    done

    # Clear pycache on SSD
    find "$SSD_DIR" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
    find "$SSD_DIR" -name '*.pyc' -delete 2>/dev/null || true

    ok "SSD sync complete."
}

# ---------------------------------------------------------------------------
# 15. Start services
# ---------------------------------------------------------------------------
start_services() {
    info "Starting services..."

    for u in "${UNITS[@]}"; do
        sudo systemctl restart "$u" || warn "$u failed to start — check journalctl -u $u"
    done
}

# ---------------------------------------------------------------------------
# 16. Health check
# ---------------------------------------------------------------------------
health_check() {
    info "Running health check..."
    local all_ok=true

    for u in "${UNITS[@]}"; do
        echo -n "  $u ... "
        for i in {1..15}; do
            STATUS=$(systemctl is-active "$u" 2>/dev/null || echo "unknown")
            if [ "$STATUS" = "active" ]; then
                echo "active ✓"
                break
            fi
            if [ "$STATUS" = "failed" ]; then
                echo "FAILED ✗"
                journalctl -u "$u" --no-pager -n 15
                all_ok=false
                break
            fi
            sleep 2
        done
        if [ "$(systemctl is-active "$u" 2>/dev/null)" != "active" ]; then
            echo "TIMEOUT ✗"
            all_ok=false
        fi
    done

    if [ "$all_ok" = true ]; then
        echo ""
        ok "All services running."
    else
        echo ""
        warn "Some services failed. Check logs above."
        return 1
    fi
}

# ---------------------------------------------------------------------------
# 17. Post-install instructions
# ---------------------------------------------------------------------------
print_next_steps() {
    echo ""
    echo "======================================================"
    echo "  SafeBox Installation Complete"
    echo "======================================================"
    echo ""
    echo "REQUIRED — edit before rebooting:"
    echo "  sudo nano $ENV_FILE"
    echo ""
    echo "  Set these values:"
    echo "    CLARITY_API_BASE_URL  — your cloud API endpoint"
    echo "    TAPO_PLUG_IP          — smart plug IP address"
    echo "    TAPO_USER             — Tapo/Kasa account email"
    echo "    TAPO_PASS             — Tapo/Kasa account password"
    echo ""
    echo "REBOOT REQUIRED for SPI/I2C to take effect:"
    echo "  sudo reboot"
    echo ""
    echo "After reboot, check status:"
    echo "  systemctl is-active safebox-wake safebox-web safebox-device"
    echo ""
    echo "Web UI: http://safebox.local:8081"
    echo "Logs:   journalctl -u safebox-wake -f"
    echo "======================================================"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
check_pi
install_system_deps
enable_interfaces
setup_ssd
install_project
setup_env
install_python_deps
install_nfc_libs
install_kasa
install_llama
install_model
install_piper
setup_bluetooth
install_services
sync_to_ssd
start_services
health_check
print_next_steps

# ── Prompt reboot ──────────────────────────────────────────────────────────
echo ""
echo "A reboot is required to activate SPI and 1-Wire interfaces."
echo ""
read -r -p "Reboot now? [Y/n]: " REBOOT_ANSWER
REBOOT_ANSWER=${REBOOT_ANSWER:-Y}

if [[ "$REBOOT_ANSWER" =~ ^[Yy]$ ]]; then
    echo "Rebooting in 5 seconds... (Ctrl+C to cancel)"
    sleep 5
    sudo reboot
else
    echo "Skipping reboot. Remember to reboot manually before using SafeBox."
    echo "  sudo reboot"
fi
