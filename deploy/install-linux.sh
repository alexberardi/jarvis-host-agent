#!/usr/bin/env bash
# Install the host agent as a systemd USER unit.
#
# Never a system unit: it would run as root outside the graphical session with
# no DISPLAY/WAYLAND_DISPLAY, so window control and `open` would silently do
# nothing while volume kept working.
set -euo pipefail

UNIT="jarvis-host-agent.service"
AGENT_BIN="${JARVIS_HOST_AGENT_BIN:-$(command -v jarvis-host-agent || true)}"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/systemd/${UNIT}"

if [[ -z "$AGENT_BIN" ]]; then
  echo "jarvis-host-agent not on PATH; set JARVIS_HOST_AGENT_BIN to its full path" >&2
  exit 1
fi

mkdir -p "$UNIT_DIR"
sed -e "s|__AGENT_BIN__|${AGENT_BIN}|g" "$SRC" > "$UNIT_DIR/${UNIT}"

systemctl --user daemon-reload
systemctl --user enable --now "$UNIT"
systemctl --user --no-pager status "$UNIT" | head -5 || true

echo
echo "installed: $UNIT_DIR/${UNIT}"
if ! loginctl show-user "$USER" -p Linger --value 2>/dev/null | grep -qi yes; then
  echo "NOTE: linger is off, so this stops when you log out. For a headless box:"
  echo "  sudo loginctl enable-linger $USER"
fi
echo "NOTE: on Wayland, window control is unavailable by design; /capabilities"
echo "will omit it and window routes answer 501. Volume and open still work."
