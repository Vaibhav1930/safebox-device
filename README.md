# SafeBox Device — Milestone 2

**Platform:** Raspberry Pi 5 + SSD  
**Phase:** 1 — Device-Only Build  
**Milestone:** 2 — Cloud Voice Integrated + Survival Mode + Vault Logging  
**Contractor:** Vaibhav Mishra  
**Client:** ClarityPath AI Consulting, LLC

---

## What This Is

SafeBox is a voice-first personal AI assistant running on a Raspberry Pi 5. It connects to the ClarityPath cloud backend when online ("Cloud Mode") and falls back to a local LLM when offline ("Survival Mode"). All interactions are logged to an encrypted local vault on SSD.

This repository contains the **device-side software stack** only. The cloud backend (ClarityOS wrapper, LLM orchestration, weather/music/calendar tools) is maintained separately by the cloud engineer.

---

## Milestone 2 Scope

Milestone 2 delivers:

- ✅ Cloud Voice device path — wake word → STT → cloud LLM → TTS → speaker
- ✅ Automatic Cloud ↔ Survival Mode switching with hysteresis (3 failures / 3 successes)
- ✅ Spoken announcements on mode transitions via Piper TTS
- ✅ Local LLM fallback via TinyLlama 1.1B (llama.cpp)
- ✅ Vault interaction logging with `request_id` traceability
- ✅ Local Web UI — setup wizard and status page
- ✅ All 5 systemd services running and enabled on boot
- ✅ Secrets loaded from `EnvironmentFile` — no keys in repo

---

## Hardware Requirements

| Component | Spec |
|---|---|
| Board | Raspberry Pi 5 (4GB or 8GB RAM) |
| Storage | SSD ≥ 128GB (mounted at `/mnt/ssd`) |
| Audio Input | USB microphone |
| Audio Output | Speaker via `aplay` (`plughw:2,0`) |
| OS | Raspberry Pi OS Lite 64-bit (Debian 12) |
| Network | WiFi (nmcli managed) |

---

## Project Structure

```
safebox-device/
├── cloud/                      # Local cloud API gateway (FastAPI)
│   └── main.py                 # Heartbeat + health endpoints
├── config/
│   ├── device_config.json      # Device name, WiFi SSID, cloud link status
│   └── settings.py             # API base URL from env
├── core/
│   ├── audio/
│   │   ├── mic_stream.py       # Mic owner — wake word, STT, cloud/local routing
│   │   ├── wake_word.py        # Porcupine wake word engine
│   │   ├── stt.py              # Faster-Whisper speech-to-text
│   │   ├── tts_player.py       # Piper TTS — text to speaker
│   │   ├── recorder.py         # SpeechRecorder + read_frame()
│   │   ├── vad.py              # Voice activity detection
│   │   └── ring_buffer.py      # Audio ring buffer
│   ├── conversation/
│   │   └── session.py          # Conversation history management
│   ├── execution/
│   │   ├── actions.py          # Device action handlers (smart plug stubs)
│   │   └── executor.py         # Intent executor
│   ├── intent/
│   │   ├── pipeline.py         # normalize → match → guard → execute
│   │   ├── matcher.py          # difflib SequenceMatcher intent matching
│   │   ├── guard.py            # Confidence threshold (0.75)
│   │   ├── normalize.py        # Text normalization
│   │   └── intents.py          # Intent definitions
│   ├── vault/
│   │   └── storage.py          # Interaction logging to JSON files on SSD
│   ├── device_controller.py    # Network monitor + mode orchestrator
│   ├── survival_mode.py        # Survival state tracker (mic owned by mic_stream)
│   ├── llm_client.py           # Cloud LLM client (ClarityPath API)
│   ├── local_llm_client.py     # Local LLM client (llama.cpp / TinyLlama)
│   ├── cloud_heartbeat.py      # Heartbeat sender to local cloud gateway
│   └── logger.py               # Rotating file logger with request_id tracing
├── deployment/
│   ├── install.sh              # Full production installer
│   └── systemd/
│       ├── llama-server.service
│       ├── safebox-cloud.service
│       ├── safebox-device.service
│       ├── safebox-wake.service
│       └── safebox-web.service
├── models/
│   └── wake/
│       └── hey-clarity_raspberry-pi.ppn   # Porcupine wake word model
├── web/
│   ├── app.py                  # Flask Web UI
│   ├── health.py               # Web health endpoint
│   └── templates/
│       ├── setup.html          # WiFi setup wizard
│       └── status.html         # Device status page
├── vault/
│   └── uploads/                # User-uploaded files
├── requirements.txt
└── .env.example
```

---

## Services

Five systemd services run on the device:

| Service | Port | Role |
|---|---|---|
| `llama-server` | 8080 | llama.cpp server — serves TinyLlama for Survival Mode |
| `safebox-cloud` | 8000 | Local FastAPI gateway — heartbeat + health |
| `safebox-wake` | — | mic_stream — wake word, STT, cloud/local routing |
| `safebox-web` | 8081 | Flask Web UI — setup and status |
| `safebox-device` | — | Device orchestrator — network monitor, mode switching |

---

## Architecture

### Cloud Mode (online)

```
Speaker ← TTS ← Cloud LLM (ClarityPath API)
                      ↑
Mic → VAD → Wake Word → STT → llm_client.py → POST /v1/chat
```

### Survival Mode (offline)

```
Speaker ← Piper TTS ← TinyLlama (llama.cpp)
                            ↑
Mic → VAD → Wake Word → STT → local_llm_client.py → POST localhost:8080
```

### Mode Switching

`device_controller.py` checks network every 10 seconds by attempting a TCP connection to `8.8.8.8:53`. Switching uses hysteresis to prevent flapping:

- **Cloud → Survival**: 3 consecutive failures
- **Survival → Cloud**: 3 consecutive successes

On each transition, `survival_mode.py` triggers a spoken announcement via Piper TTS.

### Vault Logging

Every interaction writes a JSON file to `$SAFEBOX_VAULT_ROOT/interactions/YYYY-MM-DD/`:

```json
{
  "timestamp": "2026-03-02T13:00:05.007397+05:30",
  "request_id": "de5b9fa9-c8a1-4bb0-9510-702f70c468d2",
  "device_id": "safebox-001",
  "user_text": "What is the weather today?",
  "assistant_text": "It is currently 72°F and sunny in your area.",
  "mode": "cloud",
  "latency_ms": 1919,
  "audio_file": null
}
```

The `request_id` is generated server-side and returned in the cloud API response. It is stored in the vault JSON and appears in all device-side log lines for full traceability.

---

## Installation

### Prerequisites

- Raspberry Pi OS Lite 64-bit flashed to SD card
- SSD mounted at `/mnt/ssd`
- Internet connection for first install
- Picovoice access key (get one free at [console.picovoice.ai](https://console.picovoice.ai))

### Secrets Setup

Create the secrets file before running the installer:

```bash
sudo mkdir -p /etc/safebox
sudo tee /etc/safebox/safebox.env > /dev/null << EOF
PICOVOICE_ACCESS_KEY=your_key_here
SAFEBOX_VAULT_ROOT=/mnt/ssd/safebox-device/vault
SAFEBOX_LOG_LEVEL=INFO
EOF
sudo chmod 600 /etc/safebox/safebox.env
sudo chown root:root /etc/safebox/safebox.env
```

### Run Installer

```bash
git clone https://github.com/your-org/safebox-device.git /mnt/ssd/safebox-device
cd /mnt/ssd/safebox-device
chmod +x deployment/install.sh
./deployment/install.sh
```

The installer will:
1. Install system dependencies (Python, PortAudio, build tools)
2. Copy project to `/opt/safebox`
3. Create Python virtualenv and install requirements
4. Build llama.cpp from source
5. Download TinyLlama 1.1B (~638MB)
6. Install Piper TTS and voice model
7. Deploy and enable all 5 systemd services
8. Run a 15-attempt health check per service

### Verify Installation

```bash
for u in llama-server safebox-cloud safebox-wake safebox-web safebox-device; do
  printf "%-20s : " "$u"; systemctl is-active "$u"
done
```

All five should show `active`.

---

## Web UI

Access the Web UI from any browser on the same network:

```
http://<device-ip>:8081/setup     # WiFi setup wizard
http://<device-ip>:8081/status    # Device status
http://<device-ip>:8081/device/status  # JSON status API
http://<device-ip>:8081/health    # Health check
```

Find your device IP:
```bash
hostname -I
```

---

## Configuration

### `config/device_config.json`

```json
{
  "device_name": "SafeBox",
  "wifi_ssid": "",
  "cloud_linked": false
}
```

### `config/settings.py`

```python
API_BASE_URL = os.getenv(
    "CLARITY_API_BASE_URL",
    "https://vzjih8wca2.us-east-1.awsapprunner.com"
)
```

Override via environment variable:
```bash
CLARITY_API_BASE_URL=https://your-api.example.com
```

---

## Environment Variables

All secrets and environment-specific config are loaded from `/etc/safebox/safebox.env`:

| Variable | Required | Description |
|---|---|---|
| `PICOVOICE_ACCESS_KEY` | ✅ | Porcupine wake word engine key |
| `SAFEBOX_VAULT_ROOT` | ✅ | Vault storage root path |
| `SAFEBOX_LOG_LEVEL` | Optional | Log level (default: INFO) |
| `CLARITY_API_BASE_URL` | Optional | Override cloud API URL |

---

## Logs

Logs are written to `/opt/safebox/logs/` with rotating files (1MB, 3 backups):

| File | Service | Content |
|---|---|---|
| `device.log` | safebox-device | Mode transitions, boot events, survival state |
| `network.log` | safebox-device | Network check results, threshold counters |
| `wake.log` | safebox-wake | Wake word detection, STT, cloud requests |
| `survival.log` | safebox-device | Survival mode enter/exit, announcements |

Live log monitoring:
```bash
# All device services
sudo journalctl -u safebox-device -u safebox-wake -u safebox-cloud -f

# Mode transitions only
sudo journalctl -u safebox-device -f | grep "\[NET\]\|\[MODE\]"

# Specific request_id
sudo journalctl -u safebox-cloud -u safebox-wake | grep "YOUR_REQUEST_ID"
```

---

## Vault Evidence

After a voice interaction:

```bash
# List recent interactions
ls -lt $SAFEBOX_VAULT_ROOT/interactions/$(date +%Y-%m-%d)/

# Read latest interaction
cat $(find $SAFEBOX_VAULT_ROOT/interactions -name "*.json" | sort -r | head -1) | python3 -m json.tool
```

---

## Milestone 2 Acceptance Checklist

| Section | Check | Status |
|---|---|---|
| A | Device boots, no failed units | ✅ |
| A | All 5 services active | ✅ |
| A | Audio devices present | ✅ |
| B | Web UI loads from another device | ✅ |
| B | Setup flow works | ✅ |
| C | Wake word triggers voice loop | ✅ |
| C | Cloud response received and played | ✅ |
| D | Internet OFF → survival mode within threshold | ✅ |
| D | Survival announcement plays | ✅ |
| D | Internet ON → cloud mode recovered | ✅ |
| D | Cloud recovery announcement plays | ✅ |
| E | Local LLM (TinyLlama) responds in survival mode | ✅ |
| F | Each interaction writes vault JSON | ✅ |
| G | `request_id` in vault JSON matches device logs | ✅ |

---

## Out of Scope (Phase 1 M3/M4)

The following are planned for Milestone 3 and 4:

- NFC (Tap TAGS + Tap KEY)
- Smart plug + temperature sensor (Tapo/Kasa)
- Offline digital kit ingestion and retrieval
- Config sync client
- Bluetooth A2DP sink (Music Addendum)
- Showoff Mode demo script
- SSD encryption

---

## Security Notes

- No secrets are committed to this repository
- All keys loaded via `EnvironmentFile=/etc/safebox/safebox.env` (chmod 600, root owned)
- Web UI has no authentication (LAN-only, pre-production)
- Cloud API has no authentication (noted in API Integration Guide — production TODO)

---

## Dependencies

| Package | Purpose |
|---|---|
| `pvporcupine` | Wake word detection |
| `faster-whisper` | On-device STT |
| `piper-tts` | On-device TTS |
| `llama.cpp` | Local LLM inference |
| `sounddevice` | Mic audio capture |
| `soundfile` | WAV file I/O |
| `flask` | Web UI server |
| `requests` | Cloud API client |
| `numpy` | Audio processing |
