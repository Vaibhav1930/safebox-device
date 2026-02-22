#!/bin/bash

set -e

echo "?? Installing SafeBox..."

PROJECT_DIR="/mnt/ssd/safebox"
LLAMA_DIR="/opt/llama.cpp"
MODEL_DIR="$PROJECT_DIR/models"
VENV_DIR="$PROJECT_DIR/venv"

echo "?? Installing system dependencies..."
sudo apt update
sudo apt install -y python3 python3-venv python3-full \
                    git build-essential cmake \
                    libasound2-dev portaudio19-dev

echo "?? Fixing permissions..."
sudo chown -R $USER:$USER $PROJECT_DIR

echo "?? Creating virtual environment..."
rm -rf $VENV_DIR
python3 -m venv $VENV_DIR --upgrade-deps

source $VENV_DIR/bin/activate

echo "?? Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt
pip install -r cloud/requirements.txt

deactivate

echo "?? Installing llama.cpp..."
if [ ! -d "$LLAMA_DIR" ]; then
    sudo git clone https://github.com/ggerganov/llama.cpp.git $LLAMA_DIR
    sudo chown -R $USER:$USER $LLAMA_DIR
fi

cd $LLAMA_DIR
cmake -B build
cmake --build build -j4

echo "?? Checking TinyLlama model..."
if [ ! -f "$MODEL_DIR/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf" ]; then
    echo "?? Model not found."
    echo "Please place TinyLlama GGUF inside:"
    echo "$MODEL_DIR"
fi

echo "?? Installing systemd services..."
sudo cp deployment/systemd/*.service /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable llama-server
sudo systemctl enable safebox-cloud
sudo systemctl enable safebox-wake
sudo systemctl enable safebox-web

echo "? Starting services..."
sudo systemctl restart llama-server
sudo systemctl restart safebox-cloud
sudo systemctl restart safebox-wake
sudo systemctl restart safebox-web

echo "? SafeBox installation complete!"
