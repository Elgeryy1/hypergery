#!/usr/bin/env bash
set -euo pipefail

# Install the HyperGery host agent as a systemd --user service so it starts
# automatically with your session and keeps this host online in the Hub.
#
# Usage:
#   ./scripts/install-agent-user-service.sh [--hub-url URL] [--uninstall]
#
# Defaults:
#   Hub URL:  --hub-url > HYPERGERY_HUB_URL env > http://192.168.1.150:8765.
#             The default is the Hub on Gerard's own NAS (private LAN), NOT a
#             universal value: on any other deployment pass --hub-url or set
#             HYPERGERY_HUB_URL. The agent's own config precedence still
#             applies: HYPERGERY_HUB_URL env > ~/.config/hypergery/agent.json
#             > this default.
#   Python:   ~/.venvs/hypergery/bin/python (override with HYPERGERY_VENV).
#
# Notes:
# - No sudo required: this is a per-user service.
# - No passwords, tokens, or NAS credentials are written anywhere.
# - The service stops when you log out. To keep the agent running without an
#   open session (e.g. a headless target host), enable lingering once:
#       sudo loginctl enable-linger "$USER"
#   That is the only optional step that needs sudo, and it is manual on purpose.

venv_dir="${HYPERGERY_VENV:-$HOME/.venvs/hypergery}"
python_bin="${HYPERGERY_PYTHON:-$venv_dir/bin/python}"
hub_url="${HYPERGERY_HUB_URL:-http://192.168.1.150:8765}"
unit_dir="$HOME/.config/systemd/user"
unit_file="$unit_dir/hypergery-agent.service"
uninstall=0

usage() {
  sed -n '4,26p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hub-url)
      shift
      hub_url="${1:?--hub-url requires a value}"
      ;;
    --uninstall)
      uninstall=1
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if ! command -v systemctl >/dev/null; then
  echo "systemctl not found; this installer requires systemd." >&2
  exit 2
fi

if [[ "$uninstall" -eq 1 ]]; then
  systemctl --user disable --now hypergery-agent.service 2>/dev/null || true
  rm -f "$unit_file"
  systemctl --user daemon-reload
  echo "hypergery-agent.service removed."
  exit 0
fi

if [[ ! -x "$python_bin" ]]; then
  echo "Python environment is missing: $python_bin" >&2
  echo "Run ./scripts/dev-run.sh --install first to create it." >&2
  exit 2
fi

mkdir -p "$unit_dir"
cat > "$unit_file" <<EOF
[Unit]
Description=HyperGery host agent (registers this host in the Hub)
After=network-online.target

[Service]
Environment=HYPERGERY_HUB_URL=$hub_url
ExecStart=$python_bin -m hypergery_ubuntu.cli agent run
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now hypergery-agent.service

echo "hypergery-agent.service installed and started."
echo "Hub URL: $hub_url"
echo "Check:   systemctl --user status hypergery-agent.service"
echo "Logs:    journalctl --user -u hypergery-agent.service -f"
echo
echo "Optional (headless hosts): keep the agent running without a login session:"
echo "  sudo loginctl enable-linger $USER"
