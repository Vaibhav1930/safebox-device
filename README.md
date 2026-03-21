# SafeBox Device — Milestone 3

**Platform:** Raspberry Pi 5 + SSD  
**Phase:** 1 — Device-Only Build  
**Milestone:** 3 — Survival Mode Polish + NFC + Smart Plug + Bluetooth + Vault  
**Contractor:** Vaibhav Mishra  
**Client:** ClarityPath AI Consulting, LLC

---

## What This Is

SafeBox is a voice-first personal AI assistant running on a Raspberry Pi 5. It connects to the ClarityPath cloud backend when online ("Cloud Mode") and falls back to a local LLM when offline ("Survival Mode"). All interactions are logged to an encrypted local vault on SSD.

This repository contains the **device-side software stack** only. The cloud backend is maintained separately by the cloud engineer.

---

## Milestone 3 Scope

Milestone 3 delivers everything from Milestone 2 plus:

- NFC polling loop with debounce (PN532 SPI)
- Tap TAGS — 4 behaviors: Onboarding, Goodnight, Morning, Play Music
- Tap KEY enrollment + vault gating (5-minute unlock TTL)
- Cross-process NFC enrollment via file-based flag (fixes web UI -> device process gap)
- Unknown tags auto-registered, appear in Web UI within 2s without page reload
- Smart plug on/off by voice — Tapo/Kasa (aiohttp leak fixed)
- Temperature sensor voice query
- Goodnight routine — plug off + temp + music pause + spoken response
- Bluetooth A2DP sink — phone streams audio to SafeBox speaker
- Bluetooth AVRCP — play/pause/next/previous/volume by voice
- Offline digital kit ingestion and retrieval in Survival Mode
- Vault save and retrieve by voice
- Full NFC management Web UI — live tag table, rename, assign, Tap KEY enrollment, gating toggle
- Showoff Mode dry run passed — all steps clean, no blocking bugs

---

## Hardware Requirements

| Component | Spec |
|---|---|
| Board | Raspberry Pi 5 (4GB or 8GB RAM) |
| Storage | SSD >= 128GB (mounted at /mnt/ssd) |
| Audio | ReSpeaker XVF3800 USB mic/speaker array |
| NFC Reader | PN532 (SPI, CS=GPIO4, RST=GPIO20) |
| Smart Plug | Tapo or Kasa (on same local network) |
| OS | Raspberry Pi OS Lite 64-bit (Debian 12 Bookworm) |
| Network | WiFi (nmcli managed) |

---

## Services

| Service | Port | Role |
|---|---|---|
| llama-server | 8080 | llama.cpp — TinyLlama for Survival Mode |
| safebox-cloud | 8000 | Local FastAPI gateway — heartbeat + health |
| safebox-wake | — | mic_stream — wake word, STT, routing, NFC manager |
| safebox-web | 8081 | Flask Web UI + NFC management API |
| safebox-device | — | Network monitor, mode switching |

---

## Installation

### Prerequisites

- Raspberry Pi OS Lite 64-bit flashed to SD card
- SSD mounted at /mnt/ssd
- Internet connection for first install
- Picovoice access key (get one free at console.picovoice.ai)

### Secrets setup

Create the secrets file before running the installer:

```bash
sudo mkdir -p /etc/safebox
sudo tee /etc/safebox/safebox.env > /dev/null << 'ENV'
PICOVOICE_ACCESS_KEY=your_key_here
SAFEBOX_VAULT_ROOT=/mnt/ssd/safebox-device/vault
SAFEBOX_LOG_LEVEL=INFO
CLARITY_API_BASE_URL=https://your-cloud-api-url
TAPO_PLUG_IP=192.168.x.x
TAPO_USER=your-tapo-email
TAPO_PASS=your-tapo-password
ENV
sudo chmod 600 /etc/safebox/safebox.env
sudo chown root:root /etc/safebox/safebox.env
```

### Run installer

```bash
git clone https://github.com/your-org/safebox-device.git /mnt/ssd/safebox-device
cd /mnt/ssd/safebox-device
chmod +x deployment/install.sh
./deployment/install.sh
sudo reboot
```

The installer handles everything: system packages, SPI/I2C, Python venv, NFC libs, python-kasa, llama.cpp, TinyLlama model, Piper TTS, Bluetooth A2DP config, systemd services, SSD sync.

### Verify

```bash
for u in llama-server safebox-cloud safebox-wake safebox-web safebox-device; do
  printf "%-20s : " "$u"; systemctl is-active "$u"
done
```

All five should show `active`.

---

## Environment Variables

All secrets live in `/etc/safebox/safebox.env` (chmod 600, root owned):

| Variable | Required | Description |
|---|---|---|
| PICOVOICE_ACCESS_KEY | YES | Porcupine wake word engine key |
| SAFEBOX_VAULT_ROOT | YES | Vault storage root on SSD |
| SAFEBOX_LOG_LEVEL | YES | Log level (INFO) |
| CLARITY_API_BASE_URL | YES | ClarityPath cloud backend URL |
| TAPO_PLUG_IP | YES | Smart plug local IP address |
| TAPO_USER | YES | Tapo/Kasa account email |
| TAPO_PASS | YES | Tapo/Kasa account password |

---

## Web UI

```
http://<device-ip>:8081/status         # Status + NFC management
http://<device-ip>:8081/setup          # WiFi setup wizard
http://<device-ip>:8081/device/status  # JSON status API
http://<device-ip>:8081/nfc/poll       # Live NFC state (2s polling)
```

---

## Voice Commands

**Smart home**
- "Hey Clarity, turn the lamp on / off"
- "Hey Clarity, what's the temperature?"

**Music (Bluetooth)**
- "Hey Clarity, pair my phone"
- "Hey Clarity, play music / pause / next / previous / volume up / volume down"

**Vault**
- "Hey Clarity, save this to my vault — [your note]"
- "Hey Clarity, what's in my vault?"

**NFC enrollment**
- "Hey Clarity, enroll goodnight tag"
- "Hey Clarity, enroll morning tag"
- "Hey Clarity, enroll tap key"

**Routines**
- "Hey Clarity, goodnight" or tap Goodnight tag

---

## Logs

```bash
journalctl -u safebox-wake -f     # Voice + NFC
journalctl -u safebox-device -f   # Mode transitions
journalctl -u safebox-web -f      # Web UI

# Latest vault interaction
cat $(find $SAFEBOX_VAULT_ROOT/interactions -name "*.json" | sort -r | head -1) | python3 -m json.tool
```

---

## NFC Wiring (PN532 SPI)

| PN532 Pin | Pi Pin |
|---|---|
| VCC | 3.3V (Pin 1) |
| GND | GND (Pin 6) |
| SCK | GPIO11 / SPI_CLK (Pin 23) |
| MOSI | GPIO10 / SPI_MOSI (Pin 19) |
| MISO | GPIO9 / SPI_MISO (Pin 21) |
| CS | GPIO4 (Pin 7) |
| RST | GPIO20 (Pin 38) |

---

## Milestone 3 Acceptance Checklist

| Section | Check | Status |
|---|---|---|
| M2 | All Milestone 2 items | PASS |
| A | NFC polling loop + debounce | PASS |
| A | Tap TAG Goodnight — plug + temp + music pause | PASS |
| A | Tap TAG Morning, Onboarding, Play Music | PASS |
| A | Tap KEY enrollment via Web UI | PASS |
| A | Vault gating enforced with Tap KEY | PASS |
| B | Smart plug on/off by voice | PASS |
| B | Temperature reading by voice | PASS |
| C | Bluetooth pairing + play/pause/next by voice | PASS |
| D | Survival Mode offline kit retrieval | PASS |
| D | Survival Mode local LLM answers | PASS |
| E | Vault save by voice | PASS |
| E | Vault retrieve by voice | PASS |
| F | Web UI NFC live table (no reload) | PASS |
| G | Showoff Mode dry run — no blocking bugs | PASS |

---

## Out of Scope (Milestone 4)

- Config sync client
- Showoff Mode final scripted demo
- SSD encryption
- NAS-lite drop folder

---

## Security Notes

- No secrets committed to this repository
- All keys loaded via EnvironmentFile=/etc/safebox/safebox.env (chmod 600, root owned)
- Web UI has no authentication (LAN-only, pre-production)
- Tap KEY vault gating — 5-minute unlock TTL, auto-expires

---

## Dependencies

| Package | Purpose |
|---|---|
| pvporcupine | Wake word detection |
| faster-whisper | On-device STT |
| piper-tts | On-device TTS |
| llama.cpp | Local LLM inference (Survival Mode) |
| sounddevice | Mic audio capture |
| soundfile | WAV file I/O |
| flask | Web UI + NFC API |
| requests | Cloud API client |
| numpy | Audio processing |
| python-kasa | Tapo/Kasa smart plug control |
| adafruit-blinka | GPIO/SPI hardware access |
| adafruit-circuitpython-pn532 | PN532 NFC reader driver |
| playerctl | AVRCP Bluetooth controls |
| pipewire | A2DP Bluetooth audio sink |
