#!/bin/bash
set -e

echo "===== SafeBox Production Installer ====="

# ------------------------------------------
# Detect project root dynamically
# ------------------------------------------
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LLAMA_DIR="/opt/llama.cpp"
MODEL_DIR="$PROJECT_DIR/models"
VENV_DIR="$PROJECT_DIR/venv"

echo "Project directory: $PROJECT_DIR"

# ------------------------------------------
# Install system dependencies
# ------------------------------------------
echo "Installing system dependencies..."
sudo apt update
sudo apt install -y python3 python3-venv python3-full \
                    git build-essential cmake \
                    libasound2-dev portaudio19-dev wget

# ------------------------------------------
# Create required directories
# ------------------------------------------
echo "Creating required directories..."
mkdir -p "$MODEL_DIR"
mkdir -p "$PROJECT_DIR/vault/interactions"
mkdir -p "$PROJECT_DIR/logs"

# ------------------------------------------
# Create virtual environment
# ------------------------------------------
echo "Creating virtual environment..."
rm -rf "$VENV_DIR"
python3 -m venv "$VENV_DIR" --upgrade-deps

source "$VENV_DIR/bin/activate"

echo "Installing Python dependencies..."
pip install --upgrade pip
pip install -r "$PROJECT_DIR/requirements.txt"
pip install -r "$PROJECT_DIR/cloud/requirements.txt"

deactivate

# ------------------------------------------
# Install llama.cpp
# ------------------------------------------
echo "Installing llama.cpp..."
if [ ! -d "$LLAMA_DIR" ]; then
    sudo git clone https://github.com/ggerganov/llama.cpp.git "$LLAMA_DIR"
    sudo chown -R $USER:$USER "$LLAMA_DIR"
fi

cd "$LLAMA_DIR"
cmake -B build
cmake --build build -j4

# ------------------------------------------
# Download TinyLlama model if missing
# ------------------------------------------
cd "$MODEL_DIR"

MODEL_FILE="tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"

if [ ! -f "$MODEL_FILE" ]; then
    echo "Downloading TinyLlama model..."
    wget https://huggingface.co/TinyLlama/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf
fi

# ------------------------------------------
# Inject dynamic paths into systemd files
# ------------------------------------------
echo "Configuring systemd services..."

SERVICE_TMP_DIR="$PROJECT_DIR/deployment/systemd"

for file in "$SERVICE_TMP_DIR"/*.service; do
    sudo sed -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
             -e "s|__VENV_DIR__|$VENV_DIR|g" \
             -e "s|__SERVICE_USER__|$USER|g" \
             "$file" | sudo tee "/etc/systemd/system/$(basename "$file")" > /dev/null
done

sudo systemctl daemon-reload

sudo systemctl enable llama-server
sudo systemctl enable safebox-cloud
sudo systemctl enable safebox-wake
sudo systemctl enable safebox-web

echo "Starting services..."
sudo systemctl restart llama-server
sudo systemctl restart safebox-cloud
sudo systemctl restart safebox-wake
sudo systemctl restart safebox-web

echo "===== SafeBox Installation Complete ====="
