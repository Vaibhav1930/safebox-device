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
SSD_ROOT="/mnt/ssd"
SSD_DIR="$SSD_ROOT/safebox-device"
RUNTIME_DIR="$INSTALL_DIR/runtime"
ENV_DIR="/etc/safebox"
ENV_FILE="$ENV_DIR/safebox.env"
SERVICE_USER="$USER"
LLAMA_DIR="/opt/llama.cpp"
UNITS=("llama-server" "safebox-cloud" "safebox-wake" "safebox-web" "safebox-device")

IS_REMOTE_INSTALL=false
if [[ -n "${SSH_CONNECTION:-}" || -n "${SSH_CLIENT:-}" ]]; then
    IS_REMOTE_INSTALL=true
fi

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
# ---------------------------------------------------------------------------
# 3. SSD encrypted mount setup
# ---------------------------------------------------------------------------

SAFEBOX_CRYPT_NAME="${SAFEBOX_CRYPT_NAME:-safebox_crypt}"
SAFEBOX_KEY_DIR="${SAFEBOX_KEY_DIR:-/etc/safebox/keys}"
SAFEBOX_KEY_FILE="${SAFEBOX_KEY_FILE:-$SAFEBOX_KEY_DIR/ssd.key}"
SAFEBOX_CRYPTTAB="${SAFEBOX_CRYPTTAB:-/etc/crypttab}"
SAFEBOX_FSTAB="${SAFEBOX_FSTAB:-/etc/fstab}"

find_ssd_device() {
    # Prefer the first non-root disk with a transport typical for external SSDs.
    # Fallback: first non-root disk.
    local root_disk candidate
    root_disk="$(findmnt -n -o SOURCE / | sed 's#/dev/##' | sed 's#p[0-9]\+$##')"

    while read -r name type tran; do
        [ "$type" = "disk" ] || continue
        [ "$name" = "$root_disk" ] && continue
        case "$tran" in
            usb|sata|nvme)
                echo "/dev/$name"
                return 0
                ;;
        esac
    done < <(lsblk -dn -o NAME,TYPE,TRAN)

    while read -r name type; do
        [ "$type" = "disk" ] || continue
        [ "$name" = "$root_disk" ] && continue
        echo "/dev/$name"
        return 0
    done < <(lsblk -dn -o NAME,TYPE)

    return 1
}

ensure_keyfile() {
    sudo mkdir -p "$SAFEBOX_KEY_DIR"
    if [ ! -f "$SAFEBOX_KEY_FILE" ]; then
        info "Creating SSD encryption keyfile..."
        sudo dd if=/dev/urandom of="$SAFEBOX_KEY_FILE" bs=4096 count=1 status=none
        sudo chmod 600 "$SAFEBOX_KEY_FILE"
        sudo chown root:root "$SAFEBOX_KEY_FILE"
        ok "Created keyfile at $SAFEBOX_KEY_FILE"
    else
        sudo chmod 600 "$SAFEBOX_KEY_FILE"
        sudo chown root:root "$SAFEBOX_KEY_FILE"
        ok "SSD keyfile already exists."
    fi
}

ensure_partition() {
    local disk="$1"
    local part="${disk}1"

    if [ -b "$part" ]; then
        echo "$part"
        return 0
    fi

    info "Creating GPT + primary partition on $disk ..." >&2
    sudo sgdisk --zap-all "$disk" >/dev/null
    sudo sgdisk -n 1:0:0 -t 1:8300 "$disk" >/dev/null
    sudo partprobe "$disk"
    sudo udevadm settle
    sleep 2

    if [ ! -b "$part" ]; then
        die "Partition creation failed for $disk"
    fi

    echo "$part"
}

is_luks_partition() {
    local part="$1"
    local fstype
    fstype="$(lsblk -dn -o FSTYPE "$part" 2>/dev/null || true)"
    [ "$fstype" = "crypto_LUKS" ] || [ "$fstype" = "crypto" ]
}

is_plain_filesystem_present() {
    local part="$1"
    local fstype
    fstype="$(lsblk -dn -o FSTYPE "$part" 2>/dev/null || true)"
    [ -n "$fstype" ] && [ "$fstype" != "crypto_LUKS" ] && [ "$fstype" != "crypto" ]
}

ensure_luks_container() {
    local part="$1"

    if is_luks_partition "$part"; then
        ok "SSD partition already encrypted with LUKS."
        return 0
    fi

    if is_plain_filesystem_present "$part"; then
        err "Refusing to overwrite existing non-LUKS filesystem on $part."
        err "Run an explicit migration or wipe step first."
        exit 1
    fi

    info "Formatting $part as LUKS..."
    sudo cryptsetup luksFormat "$part" "$SAFEBOX_KEY_FILE" --batch-mode
    ok "LUKS container created on $part"
}

ensure_crypt_mapping_open() {
    local part="$1"

    if [ -e "/dev/mapper/$SAFEBOX_CRYPT_NAME" ]; then
        ok "Crypt mapping $SAFEBOX_CRYPT_NAME already open."
        return 0
    fi

    info "Opening encrypted SSD as $SAFEBOX_CRYPT_NAME..."
    sudo cryptsetup open "$part" "$SAFEBOX_CRYPT_NAME" --key-file "$SAFEBOX_KEY_FILE"
    ok "Opened encrypted SSD."
}

ensure_inner_filesystem() {
    local mapper="/dev/mapper/$SAFEBOX_CRYPT_NAME"
    local fstype
    fstype="$(lsblk -dn -o FSTYPE "$mapper" 2>/dev/null || true)"

    if [ "$fstype" = "ext4" ]; then
        ok "Inner ext4 filesystem already exists."
        return 0
    fi

    if [ -n "$fstype" ]; then
        err "Unexpected filesystem '$fstype' inside $mapper"
        exit 1
    fi

    info "Creating ext4 filesystem inside encrypted SSD..."
    sudo mkfs.ext4 -L safebox_ssd "$mapper"
    ok "Inner ext4 filesystem created."
}

ensure_crypttab_entry() {
    local part="$1"
    local luks_uuid
    luks_uuid="$(sudo cryptsetup luksUUID "$part")"

    sudo touch "$SAFEBOX_CRYPTTAB"
    if grep -qE "^[# ]*${SAFEBOX_CRYPT_NAME}[[:space:]]" "$SAFEBOX_CRYPTTAB"; then
        sudo sed -i \
            "s#^[# ]*${SAFEBOX_CRYPT_NAME}[[:space:]].*#${SAFEBOX_CRYPT_NAME} UUID=${luks_uuid} ${SAFEBOX_KEY_FILE} luks#" \
            "$SAFEBOX_CRYPTTAB"
    else
        echo "${SAFEBOX_CRYPT_NAME} UUID=${luks_uuid} ${SAFEBOX_KEY_FILE} luks" | sudo tee -a "$SAFEBOX_CRYPTTAB" > /dev/null
    fi

    ok "crypttab entry ensured."
}

ensure_fstab_entry() {
    local mapper="/dev/mapper/$SAFEBOX_CRYPT_NAME"
    local fs_uuid
    fs_uuid="$(sudo blkid -s UUID -o value "$mapper")"

    sudo mkdir -p "$SSD_DIR"
    sudo touch "$SAFEBOX_FSTAB"

    # Remove old direct /dev/sdX mount entries for /mnt/ssd if present.
    sudo sed -i "\#${SSD_DIR}[[:space:]]#d" "$SAFEBOX_FSTAB"

    echo "UUID=${fs_uuid} ${SSD_DIR} ext4 defaults,nofail 0 2" | sudo tee -a "$SAFEBOX_FSTAB" > /dev/null
    ok "fstab entry ensured."
}

mount_encrypted_ssd() {
    local mapper="/dev/mapper/$SAFEBOX_CRYPT_NAME"

    sudo mkdir -p "$SSD_DIR"

    if findmnt -rno SOURCE "$SSD_DIR" >/dev/null 2>&1; then
        local src
        src="$(findmnt -rno SOURCE "$SSD_DIR")"
        if [ "$src" = "$mapper" ]; then
            ok "$SSD_DIR already mounted from $mapper"
            return 0
        fi
        err "$SSD_DIR is mounted from unexpected source: $src"
        exit 1
    fi

    info "Mounting encrypted SSD at $SSD_DIR..."
    sudo mount "$mapper" "$SSD_DIR"
    ok "Encrypted SSD mounted."
}

create_ssd_directories() {
    info "Creating SafeBox directories on encrypted SSD..."

    sudo mkdir -p "$SSD_DIR/vault/notes"
    sudo mkdir -p "$SSD_DIR/vault/interactions"
    sudo mkdir -p "$SSD_DIR/proofs"
    sudo mkdir -p "$SSD_DIR/uploads"
    sudo chown -R "$SERVICE_USER:$SERVICE_USER" "$SSD_DIR"

    ok "SafeBox SSD directories created."
}

setup_ssd() {
    info "Setting up encrypted SSD mount at $SSD_DIR..."

    local ssd_disk ssd_part
    ssd_disk="$(find_ssd_device)" || {
        err "No secondary SSD detected."
        exit 1
    }

    ok "Detected SSD disk: $ssd_disk"

    ensure_keyfile
    ssd_part="$(ensure_partition "$ssd_disk")"
    ok "Using SSD partition: $ssd_part"
    if ! is_luks_partition "$ssd_part"; then
        info "Clearing stale signatures on $ssd_part..."
        sudo wipefs -a "$ssd_part" 2>/dev/null || true
        sudo dd if=/dev/zero of="$ssd_part" bs=4M count=8 conv=fsync status=none || true
        sudo partprobe "$ssd_disk" || true
        sudo udevadm settle || true
    fi

    ensure_luks_container "$ssd_part"
    ensure_crypt_mapping_open "$ssd_part"
    ensure_inner_filesystem
    ensure_crypttab_entry "$ssd_part"
    ensure_fstab_entry
    mount_encrypted_ssd
    create_ssd_directories

    sudo update-initramfs -u

    ok "Encrypted SSD setup complete."
}




init_setup_state() {
    info "Initializing onboarding state..."

    sudo mkdir -p /var/lib/safebox
    sudo chown -R "$SERVICE_USER:$SERVICE_USER" /var/lib/safebox
    sudo chmod 755 /var/lib/safebox

    sudo tee /var/lib/safebox/setup_state.json > /dev/null <<'EOF'
{
  "setup_completed": false,
  "completed_at": null,
  "setup_version": 1
}
EOF

    sudo chown "$SERVICE_USER:$SERVICE_USER" /var/lib/safebox/setup_state.json
    sudo chmod 664 /var/lib/safebox/setup_state.json

    ok "Onboarding state reset for fresh install."
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
    pip install scipy
    pip install -r requirements.txt
    pip install -r cloud/requirements.txt

    # Verify critical packages installed correctly
    python -c "import numpy, scipy, sounddevice, flask, requests" || die "Critical Python packages failed to install"

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

    local piper_dir="$INSTALL_DIR/piper"
    local piper_venv="$piper_dir/venv"
    local piper_model_dir="$INSTALL_DIR/models/piper"

    mkdir -p "$piper_dir" "$piper_model_dir"

    if [ ! -d "$piper_venv" ]; then
        python3 -m venv "$piper_venv"
    fi

    source "$piper_venv/bin/activate"
    pip install --upgrade pip
    pip install piper-tts pathvalidate
    deactivate

    local onnx_file="$piper_model_dir/en_US-lessac-low.onnx"
    local json_file="$piper_model_dir/en_US-lessac-low.onnx.json"
    local base_url="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/low"

    [ -f "$onnx_file" ] || wget -q --show-progress -O "$onnx_file" "$base_url/en_US-lessac-low.onnx"
    [ -f "$json_file" ] || wget -q --show-progress -O "$json_file" "$base_url/en_US-lessac-low.onnx.json"

    [ -x "$piper_venv/bin/piper" ] || die "Piper binary missing after install."
    [ -f "$onnx_file" ] || die "Piper ONNX voice missing after download."
    [ -f "$json_file" ] || die "Piper voice JSON missing after download."

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

    sudo rsync -a --delete \
        --exclude '.git' \
        --exclude '.venv' \
        --exclude 'venv' \
        --exclude '__pycache__' \
        --exclude '*.pyc' \
        --exclude 'logs' \
        --exclude 'runtime' \
        --exclude 'vault' \
        "$INSTALL_DIR/" "$SSD_DIR/"

    sudo chown -R "$SERVICE_USER:$SERVICE_USER" "$SSD_DIR"

    ok "SSD sync complete."
}

# ---------------------------------------------------------------------------
# 15. Start services
# ---------------------------------------------------------------------------
start_services() {
    info "Starting services..."

    for u in "${UNITS[@]}"; do
        if [[ "$IS_REMOTE_INSTALL" == "true" && "$u" == "safebox-wake" ]]; then
            warn "Skipping safebox-wake start during SSH install to avoid dropping the network session."
            continue
        fi

        sudo systemctl restart "$u" || warn "$u failed to start — check journalctl -u $u"
    done
}

# ---------------------------------------------------------------------------
# 16. Health check
# ---------------------------------------------------------------------------
health_check() {
    info "Running health check..."
    local all_ok=true

    mount | grep /mnt/ssd >/dev/null || die "SSD not mounted"
    test -d /mnt/ssd/safebox-device/vault || die "Vault directory missing"

    for u in "${UNITS[@]}"; do
        if [[ "$IS_REMOTE_INSTALL" == "true" && "$u" == "safebox-wake" ]]; then
            echo "  $u ... skipped during SSH install (will start after reboot)"
            continue
        fi

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
        ok "All checked services running."
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
    if [[ "$IS_REMOTE_INSTALL" == "true" ]]; then
        echo "NOTE:"
        echo "  safebox-wake was intentionally not started during SSH install."
        echo "  It will start after reboot to avoid dropping your network session."
        echo ""
    fi
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
init_setup_state
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
