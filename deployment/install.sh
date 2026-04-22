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
        jq \
        \
        cryptsetup

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
        echo "dtoverlay=w1-gpio-pi5,gpiopin=17" | sudo tee -a "$CONFIG_FILE" > /dev/null
        ok "1-Wire enabled in $CONFIG_FILE (GPIO 17 for DS18B20)"
    else
        ok "1-Wire already enabled."
    fi

    # Add user to required groups
    sudo usermod -aG spi,i2c,gpio,bluetooth,audio,dialout "$SERVICE_USER" 2>/dev/null || true
    ok "User $SERVICE_USER added to hardware groups."

    # Allow service user to run nmcli without a password prompt.
    # Required because safebox-wake runs as $SERVICE_USER (no TTY) and
    # ap_setup.py calls nmcli with sudo to manage the onboarding hotspot.
    local sudoers_file="/etc/sudoers.d/safebox-nmcli"
    echo "$SERVICE_USER ALL=(ALL) NOPASSWD: /usr/bin/nmcli" | sudo tee "$sudoers_file" > /dev/null
    sudo chmod 440 "$sudoers_file"
    sudo visudo -c -f "$sudoers_file" > /dev/null \
        && ok "sudoers rule added for nmcli (passwordless)." \
        || { sudo rm -f "$sudoers_file"; warn "sudoers validation failed — rule not installed."; }
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

prepare_ssd_target() {
    # Returns the block device path to use for LUKS formatting.
    # Strategy:
    #   1. If a valid partition /dev/sdX1 already exists as a block device → use it.
    #   2. Try to create one via sgdisk + partx/partprobe (needs no reboot when
    #      the kernel has no stale reference to the old table).
    #   3. If the kernel still refuses to expose the partition node (common on Pi
    #      when repartitioning a previously-used disk without rebooting) →
    #      fall back to using the whole disk directly for LUKS. This is safe
    #      because we zeroed all headers already.
    local disk="$1"
    local part="${disk}1"

    info "Preparing SSD target on $disk..." >&2

    # ── Step A: zero header regions so the kernel sees a truly blank disk ────
    info "Zeroing header regions on $disk..." >&2
    sudo dd if=/dev/zero of="$disk" bs=1M count=64 conv=fsync status=none 2>/dev/null || true
    local disk_bytes
    disk_bytes="$(sudo blockdev --getsize64 "$disk" 2>/dev/null || echo 0)"
    if [ "$disk_bytes" -gt $((128 * 1024 * 1024)) ]; then
        local skip_mb=$(( disk_bytes / 1024 / 1024 - 32 ))
        sudo dd if=/dev/zero of="$disk" bs=1M seek="$skip_mb" count=32 \
            conv=fsync status=none 2>/dev/null || true
    fi
    sync

    # ── Step B: remove kernel's stale partition entries ──────────────────────
    sudo partx --delete --nr 1 "$disk" 2>/dev/null || true
    sudo udevadm settle
    sleep 1

    # ── Step C: write new GPT with sgdisk ────────────────────────────────────
    # Redirect stdout→stderr so sgdisk's progress messages don't get captured
    # by callers who do: ssd_part="$(prepare_ssd_target ...)"
    info "Writing fresh GPT on $disk..." >&2
    sudo sgdisk --zap-all "$disk" >/dev/null 2>&1 || true
    sudo sgdisk -n 1:2048:0 -t 1:8300 -c 1:safebox_data "$disk" >/dev/null 2>&1
    sync

    # ── Step D: try every method to get the kernel to see sda1 ──────────────
    # Method 1: partx --add (BLKPG ioctl — most direct)
    sudo partx --add --nr 1 "$disk" 2>/dev/null || true
    sudo udevadm settle; sleep 1

    # Method 2: partprobe
    if [ ! -b "$part" ]; then
        sudo partprobe "$disk" 2>/dev/null || true
        sudo udevadm settle; sleep 2
    fi

    # Method 3: full udev rescan
    if [ ! -b "$part" ]; then
        sudo udevadm trigger --action=add --subsystem-match=block
        sudo udevadm settle; sleep 2
    fi

    # ── Step E: if partition node still not visible, use whole-disk LUKS ─────
    # This is not a degraded mode — LUKS on a whole disk (no partition table)
    # is perfectly valid and commonly used. We already zeroed the disk so
    # there is no old data. We skip the partition table entirely.
    if [ ! -b "$part" ]; then
        warn "$part not visible after partitioning — kernel holds stale table reference." >&2
        warn "Falling back to whole-disk LUKS on $disk (no partition table)." >&2
        warn "To get a clean partition table, reboot and re-run install.sh." >&2
        echo "$disk"
        return 0
    fi

    ok "Using partition $part" >&2
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

    if [ ! -b "$part" ]; then
        die "Partition $part does not exist"
    fi

    info "Checking if $part already has a valid LUKS header..."

    if sudo cryptsetup isLuks "$part" 2>/dev/null; then
        # Verify that our keyfile actually opens this LUKS container.
        # If it doesn't, the header belongs to a previous/mismatched format run.
        if sudo cryptsetup open --test-passphrase "$part" --key-file "$SAFEBOX_KEY_FILE" 2>/dev/null; then
            ok "SSD partition already encrypted with LUKS and keyfile matches."
            return 0
        fi
        warn "LUKS header found but keyfile does not match. Re-formatting $part..."
    else
        info "No valid LUKS header found. Formatting $part as LUKS..."
    fi

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

reset_ssd_state() {
    # Tears down everything SafeBox owns on the SSD:
    #   - unmounts $SSD_DIR
    #   - closes any open LUKS/dm-crypt mapping
    #   - wipes all signatures and zeros header regions
    #   - removes stale crypttab / fstab entries and the old keyfile
    # Called automatically by setup_ssd on every install run, and can also
    # be invoked directly:  bash deployment/install.sh --reset-ssd
    local disk="$1"
    local part="${disk}1"

    info "Resetting SSD $disk to a clean state..."

    # 1. Unmount SafeBox directories
    for mnt_path in "$SSD_DIR" "$SSD_ROOT"; do
        if findmnt -rno TARGET "$mnt_path" &>/dev/null; then
            sudo umount -l "$mnt_path" 2>/dev/null \
                && info "Unmounted $mnt_path" \
                || warn "Could not unmount $mnt_path — continuing"
        fi
    done

    # 2. Close our named LUKS mapping
    if [ -e "/dev/mapper/$SAFEBOX_CRYPT_NAME" ]; then
        info "Closing LUKS mapping $SAFEBOX_CRYPT_NAME..."
        sudo cryptsetup close "$SAFEBOX_CRYPT_NAME" 2>/dev/null || true
    fi

    # 3. Close any other dm-crypt mappings backed by this disk
    local disk_base
    disk_base="$(basename "$disk")"
    while read -r dm_name; do
        local dm_dev="/dev/mapper/$dm_name"
        [ -e "$dm_dev" ] || continue
        local backing
        backing="$(sudo dmsetup deps -o blkdevname "$dm_dev" 2>/dev/null \
                   | grep -oP '\(\K[^)]+' | head -1 || true)"
        if [[ "$backing" == "${disk_base}"* ]]; then
            info "Closing stale mapping $dm_name (backed by $backing)..."
            sudo cryptsetup close "$dm_name" 2>/dev/null \
                || sudo dmsetup remove "$dm_name" 2>/dev/null || true
        fi
    done < <(ls /dev/mapper/ 2>/dev/null | grep -v control || true)

    # 4. Wipe filesystem/partition signatures
    sudo wipefs -a "$disk" >/dev/null 2>&1 || true
    sudo wipefs -a "$part" >/dev/null 2>&1 || true

    # 5. Zero first 64 MB (GPT + LUKS header) and last 32 MB (backup GPT)
    sudo dd if=/dev/zero of="$disk" bs=1M count=64 conv=fsync status=none 2>/dev/null || true
    local disk_bytes
    disk_bytes="$(sudo blockdev --getsize64 "$disk" 2>/dev/null || echo 0)"
    if [ "$disk_bytes" -gt $((128 * 1024 * 1024)) ]; then
        local skip_mb=$(( disk_bytes / 1024 / 1024 - 32 ))
        sudo dd if=/dev/zero of="$disk" bs=1M seek="$skip_mb" count=32 \
            conv=fsync status=none 2>/dev/null || true
    fi

    # 6. Remove stale crypttab entry
    if [ -f "$SAFEBOX_CRYPTTAB" ]; then
        sudo sed -i "/^${SAFEBOX_CRYPT_NAME}[[:space:]]/d" "$SAFEBOX_CRYPTTAB"
        info "Removed stale crypttab entry."
    fi

    # 7. Remove stale fstab entry for SSD_DIR
    if [ -f "$SAFEBOX_FSTAB" ]; then
        sudo sed -i "\#${SSD_DIR}[[:space:]]#d" "$SAFEBOX_FSTAB"
        info "Removed stale fstab entry."
    fi

    # 8. Remove old keyfile so ensure_keyfile generates a fresh one
    if [ -f "$SAFEBOX_KEY_FILE" ]; then
        info "Removing old SSD keyfile..."
        sudo rm -f "$SAFEBOX_KEY_FILE"
    fi

    ok "SSD $disk reset complete."
}

setup_ssd() {
    info "Setting up encrypted SSD mount at $SSD_DIR..."

    local ssd_disk ssd_part
    ssd_disk="$(find_ssd_device)" || {
        die "No secondary SSD detected. Plug in the SSD and re-run."
    }
    ok "Detected SSD disk: $ssd_disk"

    # ── Confirm wipe before touching the disk ───────────────────────────────
    echo ""
    warn "install.sh will WIPE ALL DATA on $ssd_disk."
    warn "The SSD is used exclusively as an encrypted SafeBox vault."
    echo ""

    if [ -t 0 ]; then
        read -r -p "  Continue and erase $ssd_disk? [yes/N]: " WIPE_CONFIRM
        if [[ "$WIPE_CONFIRM" != "yes" ]]; then
            die "Aborted by user. SSD not modified."
        fi
    else
        info "Non-interactive mode — proceeding with SSD wipe automatically."
    fi

    # ── Always reset to clean state before partitioning ─────────────────────
    reset_ssd_state "$ssd_disk"

    ensure_keyfile

    ssd_part="$(prepare_ssd_target "$ssd_disk")"
    ok "Using SSD target: $ssd_part"

    ensure_luks_container "$ssd_part"
    ensure_crypt_mapping_open "$ssd_part"
    ensure_inner_filesystem
    ensure_crypttab_entry "$ssd_part"
    ensure_fstab_entry
    mount_encrypted_ssd
    create_ssd_directories

    sudo update-initramfs -u 2>/dev/null || warn "initramfs update failed — not critical on Pi."

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

    # pvporcupine MUST be explicitly installed inside the venv.
    # It appears in requirements.txt but on ARM/Pi it can silently resolve
    # to a cached system-level install instead of landing in the venv,
    # causing "ModuleNotFoundError: No module named pvporcupine" at runtime.
    info "Ensuring pvporcupine is installed in venv..."
    pip install pvporcupine
    python -c "import pvporcupine; print('[OK] pvporcupine', pvporcupine.__version__)" \
        || die "pvporcupine failed to install in venv — check pip output above"

    # Verify all critical packages
    python -c "import numpy, scipy, sounddevice, flask, requests, faster_whisper" \
        || die "Critical Python packages failed to install"

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
# 6b. Pre-download AI models during install so services never need internet
#     at runtime.  Both Whisper tiny.en and pvporcupine resolve their models
#     from the local cache — no HuggingFace DNS calls on every boot.
# ---------------------------------------------------------------------------
pre_download_models() {
    info "Pre-downloading Whisper tiny.en model (prevents DNS crash-loop at runtime)..."

    cd "$INSTALL_DIR"
    source venv/bin/activate

    # Download Whisper tiny.en into the HF cache under the SERVICE_USER home.
    # WhisperModel() will find it there on every subsequent start — no network needed.
    # We set HF_HOME so the cache lands in a predictable, persistent location
    # that survives across reboots.
    local hf_cache="/opt/safebox/models/huggingface"
    mkdir -p "$hf_cache"

    HF_HOME="$hf_cache" python - << 'PYINLINE'
import sys
try:
    from faster_whisper import WhisperModel
    import os
    hf_home = os.environ.get("HF_HOME", "")
    print(f"[INFO]  Downloading Whisper tiny.en to {hf_home} ...")
    m = WhisperModel("tiny.en", device="cpu", compute_type="int8",
                     download_root=hf_home if hf_home else None)
    print("[OK]    Whisper tiny.en downloaded and cached.")
    del m
except Exception as e:
    print(f"[ERROR] Whisper download failed: {e}", file=sys.stderr)
    sys.exit(1)
PYINLINE

    # Persist the HF_HOME path into the env file so the service uses it
    if ! sudo grep -q "HF_HOME" "$ENV_FILE" 2>/dev/null; then
        echo "HF_HOME=/opt/safebox/models/huggingface" | sudo tee -a "$ENV_FILE" > /dev/null
        ok "HF_HOME written to $ENV_FILE"
    fi

    sudo chown -R "$SERVICE_USER:$SERVICE_USER" "$hf_cache"
    deactivate
    ok "AI models pre-downloaded."
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
# 12b. Patch stt.py to always load Whisper from local cache (offline-safe)
# ---------------------------------------------------------------------------
patch_stt_offline() {
    info "Patching stt.py to use offline-safe Whisper model path..."

    local stt_file="$INSTALL_DIR/core/audio/stt.py"

    # Write a fully offline-safe stt.py — uses download_root pointing to the
    # pre-downloaded HF cache, with local_files_only=True so it never attempts
    # a network call even if HF_HOME is not set in the environment.
    sudo tee "$stt_file" > /dev/null << 'STTPY'
import os
from pathlib import Path
from faster_whisper import WhisperModel

# Prefer the pre-downloaded model cache set by the installer.
# Falls back to the default HF cache (~/.cache/huggingface) if not set.
_HF_HOME = os.environ.get("HF_HOME", str(Path.home() / ".cache" / "huggingface"))


class SpeechToText:
    def __init__(self):
        model_root = _HF_HOME if Path(_HF_HOME).exists() else None
        try:
            # First attempt: load from local cache only — zero network calls
            self.model = WhisperModel(
                "tiny.en",
                device="cpu",
                compute_type="int8",
                download_root=model_root,
                local_files_only=True,
            )
        except Exception:
            # Fallback: allow download if model is somehow missing from cache
            self.model = WhisperModel(
                "tiny.en",
                device="cpu",
                compute_type="int8",
                download_root=model_root,
            )

    def transcribe(self, wav_path: str) -> str:
        segments, _ = self.model.transcribe(
            wav_path,
            language="en",
            beam_size=1,
            best_of=1,
            vad_filter=False,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()
STTPY

    sudo chown "$SERVICE_USER:$SERVICE_USER" "$stt_file"
    ok "stt.py patched for offline Whisper loading."
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

# --reset-ssd flag: wipe the SSD to a clean state and exit without a full install.
# Useful when the disk is in a bad state before running install.sh.
# Usage: bash deployment/install.sh --reset-ssd
if [[ "${1:-}" == "--reset-ssd" ]]; then
    echo "===== SafeBox SSD Reset ====="
    _reset_disk="$(find_ssd_device)" || die "No secondary SSD detected."
    echo ""
    warn "ALL DATA on $_reset_disk will be permanently erased."
    echo ""
    if [ -t 0 ]; then
        read -r -p "  Type 'yes' to confirm wipe of $_reset_disk: " _CONFIRM
        [[ "$_CONFIRM" == "yes" ]] || die "Aborted — disk not modified."
    fi
    reset_ssd_state "$_reset_disk"
    echo ""
    ok "SSD wiped. Run   bash deployment/install.sh   to do a full install."
    exit 0
fi

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
pre_download_models
install_llama
install_model
install_piper
setup_bluetooth
patch_stt_offline
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
