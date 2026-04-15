#!/usr/bin/env bash
# =============================================================================
# SafeBox Showoff Mode — Milestone 4 Guided Demo Runner
#
# Real-hardware guided runner for the final M4 Showoff Mode gate.
# It:
#   - runs preflight
#   - records artifacts per run
#   - guides the operator through the exact demo sequence
#   - validates expected logs/state after each step
#   - checks for forbidden service restarts during the run
#
# Usage:
#   bash deployment/showoff_mode.sh 1
#   bash deployment/showoff_mode.sh 2
#   bash deployment/showoff_mode.sh 3
#
# Notes:
#   - Run number is REQUIRED.
#   - Run the exact same sequence 3 times.
#   - Any failed run resets the consecutive count per checklist.
# =============================================================================
set -euo pipefail

RUN_NUMBER="${1:-}"
[[ -n "$RUN_NUMBER" ]] || { echo "Usage: bash deployment/showoff_mode.sh <run_number>"; exit 1; }

BASE_URL="${BASE_URL:-http://127.0.0.1:8081}"
PROJECT_ROOT="${PROJECT_ROOT:-/opt/safebox}"
VENV_PY="${VENV_PY:-$PROJECT_ROOT/venv/bin/python3}"
ARTIFACT_ROOT="${ARTIFACT_ROOT:-$PROJECT_ROOT/showoff_runs}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
RUN_DIR="$ARTIFACT_ROOT/run_${RUN_NUMBER}_${TIMESTAMP}"
MAIN_LOG="$RUN_DIR/showoff_mode.log"
JOURNAL_LOG="$RUN_DIR/safebox_wake_journal.log"
STATUS_JSON="$RUN_DIR/final_status.json"
PRECHECK_LOG="$RUN_DIR/preflight.log"

mkdir -p "$RUN_DIR"

log()  { echo "[$(date +%H:%M:%S)] $*" | tee -a "$MAIN_LOG"; }
pass() { log "PASS  $*"; }
fail() { log "FAIL  $*"; exit 1; }

say() {
  local text="$1"
  "$VENV_PY" - <<PY
from core.audio.tts_player import speak
speak(${text@Q})
PY
}

capture_service_state() {
  local service="$1"
  systemctl show "$service" \
    -p ActiveState \
    -p MainPID \
    -p ExecMainStartTimestampMonotonic \
    -p ActiveEnterTimestampMonotonic
}

snapshot_services_start() {
  mkdir -p "$RUN_DIR/service_snapshots_start"
  for svc in safebox-wake safebox-web safebox-device llama-server safebox-cloud; do
    capture_service_state "$svc" > "$RUN_DIR/service_snapshots_start/$svc.txt" || true
  done
}

snapshot_services_end() {
  mkdir -p "$RUN_DIR/service_snapshots_end"
  for svc in safebox-wake safebox-web safebox-device llama-server safebox-cloud; do
    capture_service_state "$svc" > "$RUN_DIR/service_snapshots_end/$svc.txt" || true
  done
}

check_no_restart() {
  log "Checking service stability during run..."
  local bad=0
  for svc in safebox-wake safebox-web safebox-device llama-server safebox-cloud; do
    local start_file="$RUN_DIR/service_snapshots_start/$svc.txt"
    local end_file="$RUN_DIR/service_snapshots_end/$svc.txt"
    [[ -f "$start_file" && -f "$end_file" ]] || continue

    local start_pid end_pid start_ts end_ts start_state end_state
    start_pid="$(grep '^MainPID=' "$start_file" | cut -d= -f2)"
    end_pid="$(grep '^MainPID=' "$end_file" | cut -d= -f2)"
    start_ts="$(grep '^ExecMainStartTimestampMonotonic=' "$start_file" | cut -d= -f2)"
    end_ts="$(grep '^ExecMainStartTimestampMonotonic=' "$end_file" | cut -d= -f2)"
    start_state="$(grep '^ActiveState=' "$start_file" | cut -d= -f2)"
    end_state="$(grep '^ActiveState=' "$end_file" | cut -d= -f2)"

    if [[ "$start_state" != "active" || "$end_state" != "active" ]]; then
      log "Service not active throughout run: $svc ($start_state -> $end_state)"
      bad=1
      continue
    fi

    if [[ "$start_ts" != "$end_ts" ]]; then
      log "Service restart detected: $svc"
      bad=1
    fi

    if [[ "$start_pid" != "$end_pid" && "$start_pid" != "0" && "$end_pid" != "0" ]]; then
      log "Service PID changed during run: $svc ($start_pid -> $end_pid)"
      bad=1
    fi
  done

  [[ "$bad" -eq 0 ]] || fail "One or more services restarted or became inactive during run"
  pass "No forbidden service restarts detected"
}

status_snapshot() {
  curl -fsS "$BASE_URL/device/status" | tee "$STATUS_JSON" >/dev/null
}

journal_tail() {
  journalctl -u safebox-wake --no-pager -n 400 > "$JOURNAL_LOG" || true
}

wait_for_log() {
  local pattern="$1"
  local timeout="${2:-30}"
  local start now elapsed
  start="$(date +%s)"
  while true; do
    if journalctl -u safebox-wake --no-pager -n 400 | grep -F "$pattern" >/dev/null 2>&1; then
      return 0
    fi
    now="$(date +%s)"
    elapsed=$((now - start))
    if [[ "$elapsed" -ge "$timeout" ]]; then
      return 1
    fi
    sleep 1
  done
}

prompt_and_wait() {
  local instruction="$1"
  local pattern="$2"
  local timeout="${3:-45}"

  echo
  log "$instruction"
  read -r -p "Press Enter after completing the action..."
  if wait_for_log "$pattern" "$timeout"; then
    pass "Observed expected log: $pattern"
  else
    journal_tail
    fail "Expected log not found within ${timeout}s: $pattern"
  fi
}

run_preflight() {
  log "Running preflight..."
  LOG_FILE="$PRECHECK_LOG" bash "$PROJECT_ROOT/deployment/showoff_preflight.sh" || fail "Preflight failed"
  pass "Preflight passed"
}

intro_sequence() {
  log "Starting Showoff Mode run $RUN_NUMBER"
  say "Starting SafeBox Showoff Mode. This is run number $RUN_NUMBER."
  sleep 1
  say "I will demonstrate voice, tags, smart plug, vault, survival mode, and cloud recovery."
  pass "Intro sequence completed"
}

switch_to_survival() {
  log "Switching to survival mode"
  "$VENV_PY" "$PROJECT_ROOT/Scripts/set_survival_mode.py" | tee -a "$MAIN_LOG" >/dev/null
  sleep 1
  if curl -fsS "$BASE_URL/device/status" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('mode',''))" | grep -Fx "survival" >/dev/null; then
    pass "Mode switched to survival"
  else
    fail "Mode did not switch to survival"
  fi
}

switch_to_cloud() {
  log "Switching to cloud mode"
  "$VENV_PY" "$PROJECT_ROOT/Scripts/set_cloud_mode.py" | tee -a "$MAIN_LOG" >/dev/null
  sleep 1
  if curl -fsS "$BASE_URL/device/status" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('mode',''))" | grep -Fx "cloud" >/dev/null; then
    pass "Mode switched to cloud"
  else
    fail "Mode did not switch to cloud"
  fi
}

check_final_health() {
  log "Checking final healthy state"
  status_snapshot

  local mode health web wake
  mode="$(python3 -c "import json; d=json.load(open('$STATUS_JSON')); print(d.get('mode',''))" 2>/dev/null || true)"
  health="$(python3 -c "import json; d=json.load(open('$STATUS_JSON')); print(str(d.get('health',{}).get('ok','')).lower())" 2>/dev/null || true)"
  web="$(systemctl is-active safebox-web 2>/dev/null || true)"
  wake="$(systemctl is-active safebox-wake 2>/dev/null || true)"

  [[ "$health" == "true" ]] || fail "Final status health not ok"
  [[ "$web" == "active" ]] || fail "safebox-web not active at end"
  [[ "$wake" == "active" ]] || fail "safebox-wake not active at end"
  [[ "$mode" == "cloud" || "$mode" == "survival" ]] || fail "Final mode invalid: $mode"

  pass "Final health state valid mode=$mode web=$web wake=$wake"
}

# -----------------------------------------------------------------------------
# Main flow
# -----------------------------------------------------------------------------
echo "======================================================" | tee -a "$MAIN_LOG"
echo "  SafeBox Showoff Mode — Milestone 4" | tee -a "$MAIN_LOG"
echo "  Run Number: $RUN_NUMBER" | tee -a "$MAIN_LOG"
echo "  Started: $(date)" | tee -a "$MAIN_LOG"
echo "  Artifact Dir: $RUN_DIR" | tee -a "$MAIN_LOG"
echo "======================================================" | tee -a "$MAIN_LOG"

snapshot_services_start
run_preflight
intro_sequence

# Step 1 — Wake word interaction
prompt_and_wait \
  "STEP 1: Say the wake-word interaction now. Example: 'Hey Clarity, what can you do?'" \
  "wake_word.detected keyword=hey-clarity" \
  60

prompt_and_wait \
  "Waiting for cloud route selection from the wake-word interaction..." \
  "route.selected=cloud" \
  60

# Step 2 — Tap TAG routine
prompt_and_wait \
  "STEP 2: Tap the known demo NFC tag now." \
  "nfc.tag.routine_triggered" \
  30

# Step 3 — Smart plug control
prompt_and_wait \
  "STEP 3: Trigger the smart plug demo now. Use voice or tag routine." \
  "smart_plug" \
  45

# Step 4 — Vault save
prompt_and_wait \
  "STEP 4: Save a vault note now. Example: 'Save note: medicine at eight P M.'" \
  "[VAULT] Saved" \
  60

# Step 5 — Vault retrieve
prompt_and_wait \
  "STEP 5: Retrieve the saved vault note now." \
  "tts.play.start" \
  60

# Step 6 — Survival Mode transition
switch_to_survival
prompt_and_wait \
  "STEP 6: Ask one offline-safe question now. Example: 'What is artificial intelligence?'" \
  "route.selected=survival" \
  60

prompt_and_wait \
  "Waiting for local LLM response..." \
  "local_llm.response_received" \
  60

# Step 7 — Return to cloud / normal mode
switch_to_cloud
prompt_and_wait \
  "STEP 7: Ask one normal cloud question now. Example: 'What time is it?'" \
  "route.selected=cloud" \
  60

prompt_and_wait \
  "Waiting for cloud response..." \
  "cloud.response_received" \
  60

# Step 8 — Closing state
check_final_health
snapshot_services_end
check_no_restart
journal_tail

pass "Showoff Mode run $RUN_NUMBER completed successfully"

echo
echo "======================================================" | tee -a "$MAIN_LOG"
echo "RESULT: SHOWOFF RUN $RUN_NUMBER PASSED" | tee -a "$MAIN_LOG"
echo "Artifacts:" | tee -a "$MAIN_LOG"
echo "  Main log     : $MAIN_LOG" | tee -a "$MAIN_LOG"
echo "  Journal tail : $JOURNAL_LOG" | tee -a "$MAIN_LOG"
echo "  Final status : $STATUS_JSON" | tee -a "$MAIN_LOG"
echo "======================================================" | tee -a "$MAIN_LOG"
