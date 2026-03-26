#!/usr/bin/env bash
set -e

# RTA-GUARD Mission Control Auto-Updater & Publisher
# Runs the Python updater then publishes to here.now

cd /data/.openclaw/workspace/rta-cto/rta-guard-mvp

echo "🔄 Updating Mission Control..."
python3 tools/update_mission_control.py

# Get claim token for the slug (from state file)
if command -v jq &> /dev/null; then
    CLAIM_TOKEN=$(jq -r '.publishes["glacial-falcon-vtds"].claimToken // empty' .herenow/state.json)
else
    # Fallback grep/sed
    CLAIM_TOKEN=$(grep -A2 '"glacial-falcon-vtds"' .herenow/state.json | grep 'claimToken' | cut -d'"' -f4)
fi

if [ -z "$CLAIM_TOKEN" ] || [ "$CLAIM_TOKEN" = "null" ]; then
    echo "⚠️  No claim token found — creating fresh publish..."
    ~/.agents/skills/here-now/scripts/publish.sh mission-control/ --client rta-guard
else
    echo "🚀 Publishing to here.now (using claim token)..."
    ~/.agents/skills/here-now/scripts/publish.sh mission-control/ --slug glacial-falcon-vtds --claim-token "$CLAIM_TOKEN" --client rta-guard
fi

echo "✅ Mission Control update complete"
