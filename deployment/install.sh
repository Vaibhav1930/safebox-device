#!/bin/bash
set -e

echo "======================================"
echo " SafeBox Installation Starting..."
echo "======================================"

APP_DIR="/opt/safebox"
SERVICE_DIR="/etc/systemd/system"
SYSTEMD_SOURCE="$APP_DIR/deployment/systemd"

# --------------------------------------
# 1. Validate location
# --------------------------------------

if [ ! -d "$APP_DIR" ]; then
  echo "Error: $APP_DIR not found."
  exit 1
fi

cd $APP_DIR

# --------------------------------------
# 2. Create Python virtual environment
# --------------------------------------

if [ ! -d "venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
fi

echo "Activating virtual environment..."
source venv/bin/activate

echo "Upgrading pip..."
pip install --upgrade pip

if [ -f "requirements.txt" ]; then
  echo "Installing dependencies..."
  pip install -r requirements.txt
else
  echo "Warning: requirements.txt not found."
fi

# --------------------------------------
# 3. Install systemd services
# --------------------------------------

echo "Installing systemd services..."

if [ -d "$SYSTEMD_SOURCE" ]; then
  sudo cp $SYSTEMD_SOURCE/*.service $SERVICE_DIR/
else
  echo "Error: systemd service folder not found."
  exit 1
fi

# --------------------------------------
# 4. Reload systemd
# --------------------------------------

sudo systemctl daemon-reload

echo "Enabling services..."

sudo systemctl enable safebox-cloud
sudo systemctl enable safebox-web
sudo systemctl enable safebox-wake

echo "Restarting services..."

sudo systemctl restart safebox-cloud
sudo systemctl restart safebox-web
sudo systemctl restart safebox-wake

echo "======================================"
echo " SafeBox Installation Complete."
echo "======================================"
