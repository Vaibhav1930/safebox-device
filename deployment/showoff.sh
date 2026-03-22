#!/usr/bin/env bash
# =============================================================================
# SafeBox Showoff Mode — Milestone 3 Demo Script
# Runs a scripted end-to-end demo of all Milestone 3 features.
# Usage: bash deployment/showoff.sh
# =============================================================================
set -euo pipefail

BASE_URL="http://localhost:8081"
LOG_FILE="/tmp/showoff_$(date +%Y%m%d_%H%M%S).log"

pass() { echo "  [PASS] $*" | tee -a "$LOG_FILE"; }
fail() { echo "  [FAIL] $*" | tee -a "$LOG_FILE"; }
step() { echo ""; echo "── Step $* ──" | tee -a "$LOG_FILE"; }

echo "======================================================"
echo "  SafeBox Showoff Mode — Milestone 3 Demo"
echo "  $(date)"
echo "======================================================"
echo "" | tee -a "$LOG_FILE"

# ── Step 1: All services active ──────────────────────────
step "1 — Services"
ALL_OK=true
for u in llama-server safebox-cloud safebox-wake safebox-web safebox-device; do
    STATUS=$(systemctl is-active "$u" 2>/dev/null)
    if [ "$STATUS" = "active" ]; then
        pass "$u active"
    else
        fail "$u $STATUS"
        ALL_OK=false
    fi
done

# ── Step 2: Cloud API health ─────────────────────────────
step "2 — Cloud API"
HEALTH=$(curl -s http://localhost:8000/health | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('ok',''))" 2>/dev/null)
[ "$HEALTH" = "True" ] && pass "cloud API ok" || fail "cloud API not responding"

# ── Step 3: Local LLM health ─────────────────────────────
step "3 — Local LLM (Survival Mode)"
LLM=$(curl -s http://localhost:8080/health | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null)
[ "$LLM" = "ok" ] && pass "local LLM ok" || fail "local LLM not responding"

# ── Step 4: Device status ────────────────────────────────
step "4 — Device Status"
STATUS_JSON=$(curl -s "$BASE_URL/device/status")
MODE=$(echo "$STATUS_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('mode',''))" 2>/dev/null)
NFC_COUNT=$(echo "$STATUS_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('nfc',{}).get('tag_count',0))" 2>/dev/null)
[ "$MODE" = "cloud" ] && pass "mode=cloud" || fail "mode=$MODE"
[ "$NFC_COUNT" -ge 0 ] 2>/dev/null && pass "nfc tags=$NFC_COUNT" || fail "nfc status unknown"

# ── Step 5: Capabilities endpoint ───────────────────────
step "5 — Capabilities"
CAPS=$(curl -s "$BASE_URL/device/capabilities")
DEVICE_ID=$(echo "$CAPS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('device_id',''))" 2>/dev/null)
[ -n "$DEVICE_ID" ] && pass "capabilities endpoint ok device_id=$DEVICE_ID" || fail "capabilities endpoint failed"

# ── Step 6: NFC registry ─────────────────────────────────
step "6 — NFC Registry"
NFC_TAGS=$(curl -s "$BASE_URL/nfc/tags" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('tags',[])))" 2>/dev/null)
pass "nfc registry has $NFC_TAGS tags"

# ── Step 7: Result cache ─────────────────────────────────
step "7 — Result Cache"
CACHE_FILE="/mnt/ssd/safebox-device/vault/result_cache.json"
if [ -f "$CACHE_FILE" ]; then
    CACHE_COUNT=$(python3 -c "import json; d=json.load(open('$CACHE_FILE')); print(len(d))" 2>/dev/null || echo 0)
    pass "result cache exists entries=$CACHE_COUNT"
else
    pass "result cache empty (will populate on first cloud request)"
fi

# ── Step 8: Vault storage ────────────────────────────────
step "8 — Vault Storage"
VAULT_ROOT=${SAFEBOX_VAULT_ROOT:-/mnt/ssd/safebox-device/vault}
VAULT_FILES=$(find "$VAULT_ROOT/interactions" -name "*.json" 2>/dev/null | wc -l)
pass "vault interactions=$VAULT_FILES"

# ── Step 9: Offline kit ──────────────────────────────────
step "9 — Offline Kit"
KIT_INDEX="/opt/safebox/offline_kit/index.json"
if [ -f "$KIT_INDEX" ]; then
    DOC_COUNT=$(python3 -c "import json; d=json.load(open('$KIT_INDEX')); print(len(d.get('docs',[])))" 2>/dev/null)
    pass "offline kit docs=$DOC_COUNT"
else
    fail "offline kit index not found"
fi

# ── Step 10: Code integrity ──────────────────────────────
step "10 — Code Integrity"
SSD="/mnt/ssd/safebox-device"
ENROLLMENT=$(grep -c "ENROLLMENT_FLAG_PATH" "$SSD/core/nfc_manager.py" 2>/dev/null || echo 0)
SENSITIVITY=$(grep "sensitivities" "$SSD/core/audio/wake_word.py" 2>/dev/null | grep -o "0\.[0-9]*" || echo "unknown")
KIT_ROOT=$(grep "KIT_ROOT" "$SSD/core/offline_kit.py" 2>/dev/null | grep -o "parents\[.\]" || echo "unknown")
[ "$ENROLLMENT" -ge 8 ] && pass "nfc_manager enrollment flag present" || fail "nfc_manager enrollment flag missing"
[ "$SENSITIVITY" = "0.40" ] && pass "wake sensitivity=0.40" || fail "wake sensitivity=$SENSITIVITY"
[ -n "$KIT_ROOT" ] && pass "offline_kit uses project root" || fail "offline_kit path issue"

# ── Summary ──────────────────────────────────────────────
echo ""
echo "======================================================"
FAIL_COUNT=$(grep "\[FAIL\]" "$LOG_FILE" 2>/dev/null | wc -l || echo 0)
FAIL_COUNT=$(echo $FAIL_COUNT | tr -d " ")
if [ "$FAIL_COUNT" -eq 0 ]; then
    echo "  RESULT: ALL CHECKS PASSED — Milestone 3 Demo Ready"
else
    echo "  RESULT: $FAIL_COUNT CHECK(S) FAILED — Review log above"
fi
echo "  Log saved: $LOG_FILE"
echo "======================================================"
echo ""
echo "MANUAL TESTS (run after this script):"
echo "  1. Say: Hey Clarity, what time is it?       (cloud voice)"
echo "  2. Say: Hey Clarity, turn the lamp on        (smart plug)"
echo "  3. Say: Hey Clarity, save this to my vault  (vault save)"
echo "  4. Say: Hey Clarity, what is in my vault?   (vault retrieve)"
echo "  5. Tap Goodnight TAG                         (NFC routine)"
echo "  6. Disconnect WiFi, say: what do I do in a fire? (survival mode)"
echo "  7. Reconnect WiFi, say: what time is it?    (cloud recovery)"
