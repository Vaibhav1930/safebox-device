#!/usr/bin/env bash
set -euo pipefail

sudo mkdir -p /var/lib/safebox
sudo tee /var/lib/safebox/setup_state.json > /dev/null <<'EOF'
{
  "setup_completed": false,
  "completed_at": null,
  "setup_version": 1
}
EOF

sudo chown root:root /var/lib/safebox/setup_state.json
sudo chmod 644 /var/lib/safebox/setup_state.json

echo "[OK] Onboarding state reset."
