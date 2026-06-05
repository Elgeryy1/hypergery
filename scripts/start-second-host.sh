#!/usr/bin/env bash
set -euo pipefail

# Launch HyperGery on a secondary host pointing at a remote Hub, so both
# machines see each other in Remote Hosts.
#
# Usage:
#   ./scripts/start-second-host.sh [HUB_URL]
#
# HUB_URL defaults to http://192.168.1.150:8765 (the Hub running in
# Container Station on the NAS). Override it if the Hub lives somewhere else:
#   ./scripts/start-second-host.sh http://192.168.1.50:8765
#
# What it does:
#   1. Checks the Hub is reachable.
#   2. Starts the host agent in the background (heartbeat -> this host shows
#      up as online in the Hub).
#   3. Launches the HyperGery Qt app pointing at the same Hub.
#
# It does not write any config files: the Hub URL is passed via the
# HYPERGERY_HUB_URL environment variable, so nothing persists after exit.

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
venv_dir="${HYPERGERY_VENV:-$HOME/.venvs/hypergery}"
python_bin="${HYPERGERY_PYTHON:-$venv_dir/bin/python}"
hub_url="${1:-${HYPERGERY_HUB_URL:-http://192.168.1.150:8765}}"
agent_log="${TMPDIR:-/tmp}/hypergery-agent.log"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  sed -n '3,21p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
fi

if [[ ! -x "$python_bin" ]]; then
  echo "Python environment is missing: $python_bin" >&2
  echo "Run ./scripts/dev-run.sh --install first to create it." >&2
  exit 2
fi

export HYPERGERY_HUB_URL="$hub_url"

echo "Hub URL: $hub_url"
echo "Checking Hub health..."
if ! curl -fsS -m 5 "$hub_url/health" >/dev/null; then
  echo "Cannot reach the Hub at $hub_url" >&2
  echo "Check that the Hub is running on the primary host and that the" >&2
  echo "firewall allows port 8765 on the LAN." >&2
  exit 2
fi
echo "Hub is reachable."

if pgrep -f "hypergery_ubuntu.cli agent run" >/dev/null; then
  echo "Host agent already running; leaving it as is."
else
  echo "Starting host agent in the background (log: $agent_log)..."
  nohup "$python_bin" -m hypergery_ubuntu.cli agent run >"$agent_log" 2>&1 &
  disown
  sleep 2
  if ! pgrep -f "hypergery_ubuntu.cli agent run" >/dev/null; then
    echo "Agent failed to start; last log lines:" >&2
    tail -n 20 "$agent_log" >&2 || true
    exit 2
  fi
  echo "Agent started."
fi

echo "Launching HyperGery..."
cd "$repo_root/hypergery-ubuntu"
exec "$python_bin" -m hypergery_ubuntu
