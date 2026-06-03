#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 /path/to/ubuntu-or-debian.iso [vm-name]" >&2
  exit 64
fi

ISO_PATH="$1"
VM_NAME="${2:-hg-acceptance-ubuntu-test}"

exec "$(dirname "$0")/acceptance-ubuntu.sh" --iso "$ISO_PATH" --name "$VM_NAME"
