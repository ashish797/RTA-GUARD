#!/usr/bin/env bash
set -e

# RTA-GUARD Mission Control Auto-Updater & Publisher
# Runs the Python updater then publishes to here.now

cd /data/.openclaw/workspace/rta-cto/rta-guard-mvp

echo "🔄 Updating Mission Control..."
python3 tools/update_mission_control.py

# Get claim token for the slug (from state file)
if command -v jq &> /dev/null; then
    CLAIM_TOKEN=$(jq -r '.publishes["earthy-knoll-6kzg"].claimToken // empty' .herenow/state.json)
else
    # Fallback grep/sed
    CLAIM_TOKEN=$(grep -A2 '"earthy-knoll-6kzg"' .herenow/state.json | grep 'claimToken' | cut -d'"' -f4)
fi

if [ -z "$CLAIM_TOKEN" ] || [ "$CLAIM_TOKEN" = "null" ]; then
    echo "❌ Could not find claim token for earthy-knoll-6kzg"
    exit 1
fi

echo "🚀 Publishing to here.now (using claim token)..."
~/.agents/skills/here-now/scripts/publish.sh mission-control/ --slug earthy-knoll-6kzg --claim-token "$CLAIM_TOKEN" --client rta-guard

echo "✅ Mission Control update complete"
