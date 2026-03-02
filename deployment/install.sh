#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "===== SafeBox Production Installer ====="

INSTALL_DIR="/opt/safebox"
SERVICE_USER="$USER"
LLAMA_DIR="/opt/llama.cpp"
UNITS=("llama-server" "safebox-cloud" "safebox-wake" "safebox-web" "safebox-device")

echo "Installing to $INSTALL_DIR"

# ------------------------------------------
# Install system dependencies
# ------------------------------------------
echo "Installing system dependencies..."
sudo apt update
sudo apt install -y python3 python3-venv python3-full \
                    git build-essential cmake \
                    libasound2-dev portaudio19-dev wget curl

# ------------------------------------------
# Copy project to /opt/safebox
# ------------------------------------------
echo "Copying project to $INSTALL_DIR..."
sudo rm -rf "$INSTALL_DIR"
sudo mkdir -p "$INSTALL_DIR"
sudo cp -r . "$INSTALL_DIR"
sudo chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
cd "$INSTALL_DIR"

# ------------------------------------------
# Create directories
# ------------------------------------------
echo "Creating required directories..."
mkdir -p models
mkdir -p vault/interactions
mkdir -p logs

# ------------------------------------------
# Create virtual environment
# ------------------------------------------
echo "Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -r cloud/requirements.txt
deactivate

# ------------------------------------------
# Install llama.cpp
# ------------------------------------------
echo "Installing llama.cpp..."
if [ ! -d "$LLAMA_DIR" ]; then
    sudo git clone https://github.com/ggerganov/llama.cpp.git "$LLAMA_DIR"
    sudo chown -R "$SERVICE_USER:$SERVICE_USER" "$LLAMA_DIR"
fi

if [ ! -f "$LLAMA_DIR/build/bin/llama-server" ]; then
    echo "Building llama.cpp..."
    cd "$LLAMA_DIR"
    cmake -B build
    cmake --build build -j4
else
    echo "llama.cpp already built, skipping."
fi

cd "$INSTALL_DIR"  # restore working directory

# ------------------------------------------
# Download TinyLlama
# ------------------------------------------
MODEL_FILE="$INSTALL_DIR/models/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
MODEL_URL="https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"

echo "Checking TinyLlama model..."
if [ ! -s "$MODEL_FILE" ]; then
    echo "Downloading TinyLlama (~638MB)..."
    curl -L -o "$MODEL_FILE" "$MODEL_URL"
    if [ ! -s "$MODEL_FILE" ]; then
        echo "ERROR: TinyLlama download failed or file is empty"
        exit 1
    fi
    echo "TinyLlama downloaded successfully."
else
    echo "TinyLlama already exists, skipping."
fi

# ------------------------------------------
# Install Piper TTS
# ------------------------------------------
echo "Installing Piper TTS..."

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

# Download Piper voice model
if [ ! -f "$PIPER_MODEL_DIR/en_US-lessac-medium.onnx" ]; then
    echo "Downloading Piper voice model..."
    wget -O "$PIPER_MODEL_DIR/en_US-lessac-medium.onnx" \
    https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx
else
    echo "Piper voice model already exists, skipping."
fi

# Download Piper model config
if [ ! -f "$PIPER_MODEL_DIR/en_US-lessac-medium.onnx.json" ]; then
    echo "Downloading Piper model config..."
    wget -O "$PIPER_MODEL_DIR/en_US-lessac-medium.onnx.json" \
    https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json
else
    echo "Piper model config already exists, skipping."
fi

# Verify Piper installation
if [ ! -f "$PIPER_MODEL_DIR/en_US-lessac-medium.onnx" ] || \
   [ ! -f "$PIPER_MODEL_DIR/en_US-lessac-medium.onnx.json" ]; then
    echo "ERROR: Piper voice installation failed"
    exit 1
fi

echo "Piper installation complete."

# ------------------------------------------
# Install systemd services
# ------------------------------------------
echo "Configuring systemd services..."
for service in "${UNITS[@]}"; do
    sudo cp "deployment/systemd/$service.service" /etc/systemd/system/
done

sudo systemctl daemon-reload

for u in "${UNITS[@]}"; do
    sudo systemctl enable "$u"
    sudo systemctl restart "$u"
done

# ------------------------------------------
# Health check
# ------------------------------------------
echo "Running health check..."
for u in "${UNITS[@]}"; do
    echo "Checking $u..."
    for i in {1..15}; do
        STATUS=$(systemctl is-active "$u")
        if [ "$STATUS" = "active" ]; then
            echo "$u is active ✓"
            break
        fi
        if [ "$STATUS" = "failed" ]; then
            echo "FAIL: $u failed to start"
            journalctl -u "$u" --no-pager -n 20
            exit 1
        fi
        sleep 2
    done
    if [ "$(systemctl is-active "$u")" != "active" ]; then
        echo "FAIL: $u did not become active in time"
        journalctl -u "$u" --no-pager -n 20
        exit 1
    fi
done

echo "===== SafeBox Installation Complete ====="
echo "INSTALL PASS"
