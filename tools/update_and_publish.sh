#!/usr/bin/env bash
set -e

# RTA-GUARD Mission Control Auto-Updater & Publisher
# Runs the Python updater then publishes to here.now

cd /data/.openclaw/workspace/rta-cto/rta-guard-mvp

echo "🔄 Updating Mission Control..."
python3 tools/update_mission_control.py

echo "🚀 Publishing to here.now..."
~/.agents/skills/here-now/scripts/publish.sh mission-control/ --slug bitter-medley-z5w7 --client rta-guard

echo "✅ Mission Control update complete"
