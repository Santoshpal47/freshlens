#!/usr/bin/env bash
# Install (or reinstall) the macOS launchd job that runs scripts/sync_daily.sh at 18:30 and 22:30 local
# time. A run missed while the Mac was asleep fires once on wake. Uninstall: scripts/install_scheduler.sh --remove
set -euo pipefail
cd "$(dirname "$0")/.."
label=com.freshlens.sync
plist="$HOME/Library/LaunchAgents/$label.plist"
launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
if [ "${1:-}" = "--remove" ]; then rm -f "$plist"; echo "removed $label"; exit 0; fi
mkdir -p "$HOME/Library/LaunchAgents" data
cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$PWD/scripts/sync_daily.sh</string></array>
  <key>WorkingDirectory</key><string>$PWD</string>
  <key>StartCalendarInterval</key><array>
    <dict><key>Hour</key><integer>18</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>22</integer><key>Minute</key><integer>30</integer></dict>
  </array>
  <key>StandardOutPath</key><string>$PWD/data/sync.log</string>
  <key>StandardErrorPath</key><string>$PWD/data/sync.log</string>
</dict></plist>
PLIST
launchctl bootstrap "gui/$(id -u)" "$plist"
echo "installed $label → runs scripts/sync_daily.sh at 18:30 and 22:30 (log: data/sync.log)"
