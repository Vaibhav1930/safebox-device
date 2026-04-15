#!/usr/bin/env bash
# =============================================================================
# SafeBox Showoff Preflight — Milestone 4 Demo Validation
# Checks that the device is healthy before a real Showoff Mode run.
# Usage: bash deployment/showoff_preflight.sh
# =============================================================================
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8081}"
CLOUD_URL="${CLOUD_URL:-http://127.0.0.1:8000/health}"
LOCAL_LLM_URL="${LOCAL_LLM_URL:-http://127.0.0.1:8080/health}"
LOG_FILE="${LOG_FILE:-/tmp/showoff_preflight_$(date +%Y%m%d_%H%M%S).log}"
VAULT_ROOT="${SAFEBOX_VAULT_ROOT:-/mnt/ssd/safebox-device/vault}"

pass() { echo "  [PASS] $*" | tee -a "$LOG_FILE"; }
fail() { echo "  [FAIL] $*" | tee -a "$LOG_FILE"; }
step() { echo ""; echo "── Step $* ──" | tee -a "$LOG_FILE"; }

echo "======================================================" | tee -a "$LOG_FILE"
echo "  SafeBox Showoff Preflight — Milestone 4" | tee -a "$LOG_FILE"
echo "  $(date)" | tee -a "$LOG_FILE"
echo "======================================================" | tee -a "$LOG_FILE"

ALL_OK=true

step "1 — Required services"
for u in llama-server safebox-cloud safebox-wake safebox-web safebox-device; do
    STATUS="$(systemctl is-active "$u" 2>/dev/null || true)"
    if [[ "$STATUS" == "active" ]]; then
        pass "$u active"
    else
        fail "$u $STATUS"
        ALL_OK=false
    fi
done

step "2 — Cloud API"
HEALTH="$(
  curl -fsS "$CLOUD_URL" 2>/dev/null \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(str(d.get('ok','')).lower())" \
  || true
)"
if [[ "$HEALTH" == "true" ]]; then
    pass "cloud API healthy"
else
    fail "cloud API not healthy"
    ALL_OK=false
fi

step "3 — Local LLM"
LLM_STATUS="$(
  curl -fsS "$LOCAL_LLM_URL" 2>/dev/null \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" \
  || true
)"
if [[ "$LLM_STATUS" == "ok" ]]; then
    pass "local LLM healthy"
else
    fail "local LLM not healthy"
    ALL_OK=false
fi

step "4 — Device status"
STATUS_JSON="$(curl -fsS "$BASE_URL/device/status" 2>/dev/null || true)"
if [[ -n "$STATUS_JSON" ]]; then
    MODE="$(echo "$STATUS_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('mode',''))" 2>/dev/null || true)"
    UPTIME="$(echo "$STATUS_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('uptime',''))" 2>/dev/null || true)"
    pass "status endpoint reachable mode=$MODE uptime=$UPTIME"
else
    fail "status endpoint unreachable"
    ALL_OK=false
fi

step "5 — Vault storage"
if [[ -d "$VAULT_ROOT/interactions" ]]; then
    COUNT="$(find "$VAULT_ROOT/interactions" -name '*.json' 2>/dev/null | wc -l | tr -d ' ')"
    pass "vault interactions present count=$COUNT"
else
    fail "vault interactions directory missing"
    ALL_OK=false
fi

step "6 — NFC registry"
NFC_JSON="$(curl -fsS "$BASE_URL/nfc/tags" 2>/dev/null || true)"
if [[ -n "$NFC_JSON" ]]; then
    NFC_COUNT="$(echo "$NFC_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('tags',[])))" 2>/dev/null || true)"
    pass "nfc registry reachable tags=$NFC_COUNT"
else
    fail "nfc registry unreachable"
    ALL_OK=false
fi

step "7 — Smart plug visibility"
PLUG_STATE="$(echo "$STATUS_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('plug',{}).get('state',''))" 2>/dev/null || true)"
if [[ -n "$PLUG_STATE" ]]; then
    pass "plug visible state=$PLUG_STATE"
else
    fail "plug state unavailable"
    ALL_OK=false
fi

step "8 — Offline kit presence"
KIT_INDEX="/opt/safebox/offline_kit/index.json"
if [[ -f "$KIT_INDEX" ]]; then
    DOC_COUNT="$(python3 -c "import json; d=json.load(open('$KIT_INDEX')); print(len(d.get('docs',[])))" 2>/dev/null || echo 0)"
    pass "offline kit present docs=$DOC_COUNT"
else
    fail "offline kit missing"
    ALL_OK=false
fi

echo "" | tee -a "$LOG_FILE"
if [[ "$ALL_OK" == "true" ]]; then
    echo "RESULT: PRECHECKS PASSED — Ready for Milestone 4 Showoff Mode run" | tee -a "$LOG_FILE"
    exit 0
else
    echo "RESULT: PRECHECKS FAILED — Fix issues before Showoff Mode" | tee -a "$LOG_FILE"
    exit 1
fi
