#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"

echo "HyperGery Ubuntu system dependency installer"
echo "This uses the same checks as ./scripts/dev-run.sh and only installs system packages/services/groups."
echo

exec "$repo_root/scripts/bootstrap-ubuntu.sh" --install --system-only
