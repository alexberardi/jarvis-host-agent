#!/usr/bin/env bash
# Install the host agent as a per-user LaunchAgent.
#
# Never a LaunchDaemon: a daemon has no window server and cannot hold the
# Accessibility grant, so window control and `open` would both be dead.
set -euo pipefail

LABEL="io.jarvis.host-agent"
AGENT_BIN="${JARVIS_HOST_AGENT_BIN:-$(command -v jarvis-host-agent || true)}"
PLIST_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/launchd/${LABEL}.plist"

if [[ -z "$AGENT_BIN" ]]; then
  echo "jarvis-host-agent not on PATH; set JARVIS_HOST_AGENT_BIN to its full path" >&2
  exit 1
fi

mkdir -p "$PLIST_DIR" "$LOG_DIR"
sed -e "s|__AGENT_BIN__|${AGENT_BIN}|g" -e "s|__LOG_DIR__|${LOG_DIR}|g" \
  "$SRC" > "$PLIST_DIR/${LABEL}.plist"

# bootout first so a re-run reloads rather than erroring on an existing label.
launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_DIR/${LABEL}.plist"
launchctl kickstart -k "gui/$(id -u)/${LABEL}"

echo "installed: $PLIST_DIR/${LABEL}.plist"
echo "logs:      $LOG_DIR/jarvis-host-agent.log"
echo
echo "Grant Accessibility to the agent's binary under"
echo "System Settings > Privacy & Security > Accessibility, or window control"
echo "will report itself unavailable (volume and open still work)."
