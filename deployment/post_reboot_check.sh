#!/usr/bin/env bash
set -euo pipefail

SSD_ROOT="/mnt/ssd"
SSD_DIR="$SSD_ROOT/safebox-device"
CRYPT_NAME="safebox_crypt"
UNITS=("llama-server" "safebox-cloud" "safebox-wake" "safebox-web" "safebox-device")

info()  { echo "[INFO]  $*"; }
ok()    { echo "[OK]    $*"; }
die()   { echo "[ERROR] $*" >&2; exit 1; }

info "Running SafeBox post-reboot validation..."

findmnt "$SSD_ROOT" >/dev/null 2>&1 || die "$SSD_ROOT is not mounted"
ok "$SSD_ROOT is mounted"

[ -e "/dev/mapper/$CRYPT_NAME" ] || die "/dev/mapper/$CRYPT_NAME is missing"
ok "Encrypted mapper is present"

[ -d "$SSD_DIR/vault" ] || die "Vault directory missing at $SSD_DIR/vault"
ok "Vault directory present"

[ -x /opt/safebox/piper/venv/bin/piper ] || die "Piper binary missing"
[ -f /opt/safebox/models/piper/en_US-lessac-low.onnx ] || die "Piper voice model missing"
[ -f /opt/safebox/models/piper/en_US-lessac-low.onnx.json ] || die "Piper voice config missing"
ok "Piper runtime present"

failed=0
for u in "${UNITS[@]}"; do
    if systemctl is-active --quiet "$u"; then
        ok "$u is active"
    else
        echo "[ERROR] $u is NOT active" >&2
        failed=1
    fi
done

if ! curl -fsS http://127.0.0.1:8081/device/status >/dev/null; then
    echo "[ERROR] /device/status is not responding" >&2
    failed=1
else
    ok "/device/status is responding"
fi

if [ "$failed" -ne 0 ]; then
    exit 1
fi

ok "Post-reboot validation passed."
