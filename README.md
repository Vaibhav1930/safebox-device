# SafeBox Device

A voice-first personal AI assistant running on a Raspberry Pi 5. SafeBox connects to the ClarityPath cloud backend when online (**Cloud Mode**) and falls back to a local LLM when offline (**Survival Mode**). All interactions are logged to an encrypted vault on an external SSD.

This repository contains the **device-side software stack only**. The cloud backend is maintained separately.

---

## Hardware Requirements

| Component | Spec |
|---|---|
| Board | Raspberry Pi 5 (4 GB or 8 GB RAM) |
| Storage | External SSD ≥ 128 GB (auto-mounted at `/mnt/ssd`) |
| Audio | ReSpeaker XVF3800 USB mic/speaker array |
| NFC Reader | PN532 (SPI — CS=GPIO4, RST=GPIO20) |
| Smart Plug | Tapo or Kasa (on the same local network) |
| OS | Raspberry Pi OS Lite 64-bit (Debian 12 Bookworm) |
| Network | Wi-Fi via NetworkManager (`nmcli`) |

---

## Architecture

SafeBox runs as five systemd services:

| Service | Port | Role |
|---|---|---|
| `llama-server` | 8080 | llama.cpp — TinyLlama local LLM for Survival Mode |
| `safebox-cloud` | 8000 | Local FastAPI gateway — heartbeat and health |
| `safebox-wake` | — | Mic pipeline — wake word, STT, intent routing, NFC manager |
| `safebox-web` | 8081 | Flask Web UI — status, setup wizard, NFC management |
| `safebox-device` | — | Network monitor, Cloud/Survival mode switching |

The device operates in one of two modes at any time:

- **Cloud Mode** — requests are routed to the ClarityPath cloud API. Active when internet is reachable and no manual override is set.
- **Survival Mode** — requests are handled locally by TinyLlama via llama.cpp. Activates automatically on network loss or manually via voice/script. Announces the mode change through the speaker.

Mode state is persisted to `/opt/safebox/runtime/mode.json`. Manual overrides expire after 10 minutes by default (`SAFEBOX_MANUAL_MODE_TTL_SECONDS`).

---

## Repository Structure

```
safebox-device/
├── cloud/                  # Cloud gateway (FastAPI heartbeat + config fetch)
│   ├── main.py
│   ├── requirements.txt
│   └── config_bundles/     # Versioned config snapshots from cloud
├── config/
│   ├── device_config.json  # Static device config (device ID, etc.)
│   ├── settings.py         # Runtime settings (API URL, sync interval)
│   └── synced/             # Cloud-synced config releases (symlink: active/)
├── core/
│   ├── audio/              # Mic capture, VAD, wake word, STT, TTS
│   ├── conversation/       # Session management
│   ├── execution/          # Action dispatcher
│   ├── intent/             # Intent parsing pipeline
│   ├── vault/              # Encrypted interaction + note storage
│   ├── bluetooth_manager.py
│   ├── config_sync.py      # Cloud config sync manager
│   ├── nfc_manager.py      # PN532 polling, tag registry, Tap KEY vault gating
│   ├── runtime_mode.py     # Cloud/Survival mode state machine
│   ├── smart_plug.py       # Tapo/Kasa control
│   ├── survival_mode.py    # Survival mode controller
│   └── temperature.py      # DS18B20 sensor reader
├── deployment/
│   ├── install.sh          # Full production installer
│   ├── systemd/            # Service unit files
│   ├── showoff.sh          # Demo runner
│   └── post_reboot_check.sh
├── models/
│   └── wake/               # Porcupine wake word model (.ppn)
├── offline_kit/            # Offline docs for Survival Mode retrieval
├── Scripts/                # Utility scripts (mode override, config sync, etc.)
├── web/                    # Flask Web UI + NFC management API
├── requirements.txt
└── runtime/                # Runtime state files (mode, Bluetooth state)
```

---

## Installation

### Prerequisites

- Raspberry Pi OS Lite 64-bit flashed and booted
- External SSD connected (installer will detect and encrypt it automatically)
- Internet connection for first install
- Picovoice access key — get one free at [console.picovoice.ai](https://console.picovoice.ai)

### 1. Clone the repository

```bash
git clone https://github.com/your-org/safebox-device.git ~/safebox-device
cd ~/safebox-device
```

### 2. Configure secrets

Create the secrets file before running the installer:

```bash
sudo mkdir -p /etc/safebox
sudo tee /etc/safebox/safebox.env > /dev/null << 'ENV'
PICOVOICE_ACCESS_KEY=------------------------------------------
SAFEBOX_VAULT_ROOT=/mnt/ssd/safebox-device/vault
SAFEBOX_LOG_LEVEL=INFO
CLARITY_API_BASE_URL=https://cl-1446b1cdb7464773a91ee73e5b8cc20d.ecs.us-east-1.on.aws
TAPO_PLUG_IP=-------------
TAPO_USER=---------------------------
TAPO_PASS=-------------
DEVICE_NAME=safebox-001
SAFEBOX_TIMEZONE=---------------
NETWORK_CHECK_HOST=8.8.8.8
CLARITY_LOGIN_EMAIL=-----------------------------
CLARITY_LOGIN_PASSWORD=--------------------------
SAFEBOX_MANUAL_MODE_TTL_SECONDS=120
ENV=production
# Audio input selection
AUDIO_INPUT_DEVICE_NAME="reSpeaker XVF3800"
# AUDIO_INPUT_DEVICE_INDEX=2
# Wake word configuration
AUDIO_WAKE_WORD=hey-clarity
AUDIO_WAKE_SENSITIVITY=0.80
# Channel selection for wake detection:
#   mean  -> average all channels
#   first -> first channel only
#   index -> use AUDIO_WAKE_CHANNEL_INDEX
AUDIO_WAKE_CHANNEL_MODE=mean
AUDIO_WAKE_CHANNEL_INDEX=0
# Recording behavior
AUDIO_PREROLL_MS=900
AUDIO_POST_WAKE_SECONDS=1.5
AUDIO_MIN_RECORD_SECONDS=0.20
AUDIO_SAVE_MONO=true
# VAD tuning
AUDIO_VAD_THRESHOLD=350
AUDIO_VAD_SILENCE_FRAMES=10
ENV
sudo chmod 600 /etc/safebox/safebox.env
sudo chown root:root /etc/safebox/safebox.env
```

### 3. Run the installer

```bash
chmod +x deployment/install.sh
./deployment/install.sh
```

The installer handles everything: system packages, SPI/I2C/1-Wire interfaces, Python venv, NFC libs, python-kasa, llama.cpp build, TinyLlama model download (~638 MB), Piper TTS, Bluetooth A2DP, SSD LUKS encryption, systemd services, and SSD sync.

> **Note:** If installing over SSH, `safebox-wake` will not start until after reboot to avoid dropping your session. All other services start immediately.

### 4. Reboot

```bash
sudo reboot
```

SPI and 1-Wire interfaces require a reboot to activate.

### 5. Verify

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
| `PICOVOICE_ACCESS_KEY` | YES | Porcupine wake word engine key |
| `CLARITY_API_BASE_URL` | YES | ClarityPath cloud backend URL |
| `SAFEBOX_VAULT_ROOT` | YES | Vault storage root on SSD |
| `SAFEBOX_LOG_LEVEL` | YES | Log verbosity (`INFO`, `DEBUG`) |
| `TAPO_PLUG_IP` | YES | Smart plug local IP address |
| `TAPO_USER` | YES | Tapo/Kasa account email |
| `TAPO_PASS` | YES | Tapo/Kasa account password |
| `SAFEBOX_MANUAL_MODE_TTL_SECONDS` | NO | Manual mode override TTL (default: 600) |
| `CONFIG_SYNC_INTERVAL_SECONDS` | NO | Cloud config poll interval (default: 900) |

---

## Web UI

```
http://<device-ip>:8081/status         # Status dashboard + NFC management
http://<device-ip>:8081/setup          # Wi-Fi setup wizard
http://<device-ip>:8081/device/status  # JSON status API
http://<device-ip>:8081/nfc/poll       # Live NFC state (2-second polling)
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
- "Hey Clarity, goodnight" — turns off plug, reads temperature, pauses music, speaks goodnight

---

## NFC

SafeBox uses a PN532 NFC reader over SPI. Tags are registered in a persistent JSON registry on the SSD. Each tag can be assigned one of five behaviors: `ONBOARDING`, `GOODNIGHT`, `MORNING`, `PLAY_MUSIC`, or `TAP_KEY`.

**Tap KEY** is a special enrollment that gates vault access. Once a Tap KEY is enrolled, vault saves and retrieves require a tap within the past 5 minutes (configurable TTL). Vault gating can be toggled from the Web UI.

Cross-process enrollment (Web UI → NFC polling loop) is coordinated via a shared file at `/mnt/ssd/safebox-device/vault/nfc_enrollment.json` — no IPC or shared memory required.

### PN532 Wiring (SPI)

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

## Cloud Config Sync

SafeBox polls the ClarityPath cloud for config updates on a configurable interval (default 15 minutes). Config bundles are versioned and stored under `config/synced/releases/`. The active release is pointed to by the `config/synced/active` symlink.

Each config bundle contains:

| File | Contents |
|---|---|
| `persona.json` | Assistant name, greeting, feature flags |
| `behavior.json` | Feature toggles, music provider, Survival Mode disclosure |
| `tap_tags.json` | NFC tap behavior spoken phrases |
| `tuning.json` | API version, timezone, sync interval, boot document |
| `raw_cloud_config.json` | Raw response from cloud for debugging |

The device falls back to the `local-bootstrap` config if the cloud is unreachable or no sync has succeeded yet.

To trigger a manual sync:

```bash
python Scripts/config_sync_once.py
```

---

## Utility Scripts

| Script | Purpose |
|---|---|
| `Scripts/config_sync_once.py` | Trigger an immediate cloud config sync |
| `Scripts/set_cloud_mode.py` | Force switch to Cloud Mode |
| `Scripts/set_survival_mode.py` | Force switch to Survival Mode |
| `Scripts/manual_voice_trigger.py` | Simulate a voice trigger for testing |

---

## Logs

```bash
journalctl -u safebox-wake -f      # Voice pipeline + NFC events
journalctl -u safebox-device -f    # Mode transitions
journalctl -u safebox-web -f       # Web UI requests
journalctl -u safebox-cloud -f     # Heartbeat + config sync
journalctl -u llama-server -f      # Local LLM (Survival Mode)

# Latest vault interaction
cat $(find $SAFEBOX_VAULT_ROOT/interactions -name "*.json" | sort -r | head -1) | python3 -m json.tool
```

---

## SSD & Vault

The installer automatically detects the external SSD, creates a LUKS-encrypted partition using a keyfile at `/etc/safebox/keys/ssd.key`, and mounts it at `/mnt/ssd`. The keyfile is root-only (chmod 600) and registered in `/etc/crypttab` so the SSD unlocks on every boot without user intervention.

Vault data is stored at `$SAFEBOX_VAULT_ROOT` (default `/mnt/ssd/safebox-device/vault`):

```
vault/
├── interactions/        # Timestamped JSON interaction logs (one folder per day)
├── notes/               # Saved voice notes
├── nfc_tags.json        # NFC tag registry
└── nfc_enrollment.json  # Cross-process enrollment flag
```

---

## Security Notes

- No secrets are committed to this repository
- All keys are loaded via `EnvironmentFile=/etc/safebox/safebox.env` (chmod 600, root owned)
- SSD is LUKS-encrypted at rest; keyfile is root-only
- Web UI has no authentication (LAN-only, pre-production)
- Tap KEY vault gating uses a 5-minute unlock TTL that auto-expires

---

## Dependencies

| Package | Purpose |
|---|---|
| `pvporcupine` | Wake word detection |
| `faster-whisper` | On-device speech-to-text |
| `piper-tts` | On-device text-to-speech |
| `llama.cpp` | Local LLM inference (Survival Mode) |
| `sounddevice` | Mic audio capture |
| `soundfile` | WAV file I/O |
| `flask` | Web UI + NFC management API |
| `requests` | Cloud API client |
| `numpy` / `scipy` | Audio processing |
| `python-kasa` | Tapo/Kasa smart plug control |
| `adafruit-blinka` | GPIO/SPI hardware abstraction |
| `adafruit-circuitpython-pn532` | PN532 NFC driver |
| `playerctl` | Bluetooth AVRCP controls |
| `pipewire` | Bluetooth A2DP audio sink |
