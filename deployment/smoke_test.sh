#!/usr/bin/env bash

set -u
set -o pipefail

PASS_COUNT=0
FAIL_COUNT=0

STATUS_JSON="/tmp/safebox_status.json"
MIC_TEST_WAV="/tmp/smoke_mic.wav"

ENV_FILE="/etc/safebox/safebox.env"
SAFEBOX_ROOT="/opt/safebox"
VAULT_ROOT="/mnt/ssd/safebox-device/vault"
MOUNT_PATH="/mnt/ssd/safebox-device"

WEB_ROOT_URL="http://127.0.0.1:8081"
WEB_STATUS_URL="http://127.0.0.1:8081/device/status"

STATUS_READY=0

log_pass() {
  echo "[PASS] $1"
  PASS_COUNT=$((PASS_COUNT + 1))
}

log_fail() {
  echo "[FAIL] $1"
  FAIL_COUNT=$((FAIL_COUNT + 1))
}

run_check() {
  local name="$1"
  shift

  if "$@"; then
    log_pass "$name"
  else
    log_fail "$name"
  fi
}

echo "====================================="
echo " SafeBox Smoke Test Starting..."
echo "====================================="

########################################
# Helpers
########################################

get_env_value() {
  local key="$1"

  awk -F= -v k="$key" '
    $1 == k {
      gsub(/"/, "", $2)
      print $2
      exit
    }
  ' "$ENV_FILE"
}

fetch_status_json_once() {
  rm -f "$STATUS_JSON"

  for attempt in 1 2 3; do
    if curl -fsS --max-time 25 "$WEB_STATUS_URL" -o "$STATUS_JSON" \
      && python3 -m json.tool "$STATUS_JSON" >/dev/null 2>&1; then
      STATUS_READY=1
      return 0
    fi

    echo "[INFO] /device/status not ready, retry $attempt/3..."
    sleep 2
  done

  STATUS_READY=0
  echo "[DEBUG] Last /device/status response:"
  cat "$STATUS_JSON" 2>/dev/null || echo "[DEBUG] No response captured"
  return 1
}

require_status_json() {
  [ "$STATUS_READY" -eq 1 ] && [ -s "$STATUS_JSON" ]
}

cleanup() {
  rm -f "$MIC_TEST_WAV" "$STATUS_JSON"
}

restore_wake_service_silent() {
  systemctl start safebox-wake >/dev/null 2>&1 || true
}

########################################
# 1. Service Checks
########################################

check_service() {
  systemctl is-active --quiet "$1"
}

run_check "safebox-wake service" check_service safebox-wake
run_check "safebox-device service" check_service safebox-device
run_check "safebox-web service" check_service safebox-web
run_check "safebox-cloud service" check_service safebox-cloud

########################################
# 2. Vault / Storage Checks
########################################

check_mount() {
  findmnt "$MOUNT_PATH" >/dev/null 2>&1
}

check_vault_exists() {
  [ -d "$VAULT_ROOT" ]
}

check_vault_writable() {
  local test_file="$VAULT_ROOT/smoke_test.txt"
  echo "SafeBox vault smoke test $(date)" > "$test_file" && rm -f "$test_file"
}

run_check "SSD mounted at $MOUNT_PATH" check_mount
run_check "Vault path exists" check_vault_exists
run_check "Vault writable" check_vault_writable

########################################
# 3. Web UI / Status API Checks
########################################

check_web() {
  curl -fsS -L --max-time 10 "$WEB_ROOT_URL" >/dev/null
}

check_status_api() {
  fetch_status_json_once
}

run_check "Web UI reachable" check_web
run_check "/device/status returns valid JSON" check_status_api

########################################
# 4. Status Data Checks
########################################

check_status_vault() {
  require_status_json || return 1

  python3 - <<PY
import json
with open("$STATUS_JSON") as f:
    data = json.load(f)

vault = data.get("vault", {})
ok = (
    vault.get("available") is True
    and vault.get("root") == "$VAULT_ROOT"
)
raise SystemExit(0 if ok else 1)
PY
}

check_status_temperature() {
  require_status_json || return 1

  python3 - <<PY
import json
with open("$STATUS_JSON") as f:
    data = json.load(f)

temp = data.get("temperature", {})
ok = "celsius" in temp and temp.get("status") in ("ok", "unknown", "missing")
raise SystemExit(0 if ok else 1)
PY
}

check_status_disk() {
  require_status_json || return 1

  python3 - <<PY
import json
with open("$STATUS_JSON") as f:
    data = json.load(f)

disk = data.get("disk_usage") or data.get("disk") or {}
ok = all(k in disk for k in ("free_gb", "total_gb", "used_gb"))
raise SystemExit(0 if ok else 1)
PY
}

check_cloud_connectivity() {
  require_status_json || return 1

  python3 - <<PY
import json
with open("$STATUS_JSON") as f:
    data = json.load(f)

connectivity = data.get("connectivity", {})
ok = (
    data.get("cloud_api_alive") is True
    or connectivity.get("cloud_api_reachable") is True
)
raise SystemExit(0 if ok else 1)
PY
}

run_check "/device/status vault state" check_status_vault
run_check "/device/status temperature" check_status_temperature
run_check "/device/status disk usage" check_status_disk
run_check "Cloud connectivity from status" check_cloud_connectivity

########################################
# 5. Audio Input / Output Checks
########################################

check_audio_env() {
  local output_device
  output_device="$(get_env_value AUDIO_OUTPUT_DEVICE)"
  [ -n "$output_device" ]
}

check_mic_capture() {
  systemctl stop safebox-wake >/dev/null 2>&1 || true

  rm -f "$MIC_TEST_WAV"

  arecord -D hw:2,0 -f S16_LE -r 16000 -c 2 -d 2 "$MIC_TEST_WAV" >/dev/null 2>&1

  [ -s "$MIC_TEST_WAV" ]
}

check_speaker_playback() {
  local output_device
  output_device="$(get_env_value AUDIO_OUTPUT_DEVICE)"

  [ -n "$output_device" ] || return 1
  [ -s "$MIC_TEST_WAV" ] || return 1

  aplay -D "$output_device" "$MIC_TEST_WAV" >/dev/null 2>&1
}

check_tts_playback() {
  cd "$SAFEBOX_ROOT" || return 1

  PYTHONPATH="$SAFEBOX_ROOT" "$SAFEBOX_ROOT/venv/bin/python" - <<'PY'
from core.audio.tts_player import speak
speak("SafeBox smoke test successful.")
PY
}

run_check "Audio output env configured" check_audio_env
run_check "Microphone capture" check_mic_capture
run_check "Speaker playback" check_speaker_playback
run_check "TTS playback" check_tts_playback

########################################
# 6. Wake Service Restore Check
########################################

check_restore_wake_service() {
  restore_wake_service_silent
  sleep 2
  systemctl is-active --quiet safebox-wake
}

run_check "safebox-wake restored after audio test" check_restore_wake_service

########################################
# Cleanup
########################################

cleanup

########################################
# Final Result
########################################

echo "====================================="
echo " Smoke Test Summary"
echo "====================================="
echo "PASS: $PASS_COUNT"
echo "FAIL: $FAIL_COUNT"

if [ "$FAIL_COUNT" -eq 0 ]; then
  echo "RESULT: PASS"
  exit 0
else
  echo "RESULT: FAIL"
  exit 1
fi
