# SafeBox

Embedded device software stack.

Production-grade, headless Raspberry Pi system.

## Structure
- core/
- audio/
- survival/
- web/
- nfc/
- telemetry/
- config/
- logs/
- scripts/

# SafeBox Device – OS Build & Boot Guide (Milestone 1)

## Hardware
- Raspberry Pi (tested on Pi 4)
- reSpeaker USB Mic Array
- Internet optional (offline safe)

## OS
- Debian GNU/Linux 13 (trixie)

## 1. Flash OS
Flash Debian 13 using Raspberry Pi Imager.

Enable:
- SSH
- Ethernet or USB networking

## 2. Clone Repository
```bash
sudo mkdir -p /opt/safebox
sudo chown $USER:$USER /opt/safebox
cd /opt/safebox
git clone https://github.com/<your-username>/safebox-device.git

