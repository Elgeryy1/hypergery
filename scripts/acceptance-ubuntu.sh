#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/acceptance-ubuntu.sh --iso /path/to/ubuntu-or-debian.iso [--name hg-acceptance-ubuntu-test]

This runs the HyperGery v0.1 real-host acceptance flow with the same backend
used by the GUI. It creates a real libvirt VM, starts it, opens a real console,
creates/reverts a real snapshot, shuts down, and optionally deletes the VM.
USAGE
}

ISO=""
NAME="hg-acceptance-ubuntu-test"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --iso)
      ISO="${2:-}"
      shift 2
      ;;
    --name)
      NAME="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$ISO" ]]; then
  usage >&2
  exit 2
fi

if [[ ! -f "$ISO" ]]; then
  echo "ISO not found: $ISO" >&2
  exit 2
fi

cd "$(dirname "$0")/../hypergery-ubuntu"

run_cli() {
  python3 -m hypergery_ubuntu.cli "$@"
}

echo "== HyperGery preflight =="
run_cli preflight

echo
echo "== Creating VM =="
run_cli create-vm \
  --name "$NAME" \
  --iso "$ISO" \
  --os-type Linux \
  --ram-mib 4096 \
  --vcpus 2 \
  --disk-gb 40 \
  --network nat \
  --display spice \
  --lab-id default-lab

echo
echo "== Starting VM =="
run_cli start "$NAME"
run_cli wait-state "$NAME" running --timeout 90 --interval 2
run_cli validate-vm "$NAME"

echo
echo "== Opening real console =="
run_cli open-console "$NAME"
echo "Confirm that virt-viewer/remote-viewer shows the real ISO installer, then press Enter."
read -r

echo
echo "== Requesting ACPI shutdown =="
run_cli shutdown "$NAME"
if ! run_cli wait-state "$NAME" "shut off" --timeout 180 --interval 3; then
  echo "ACPI shutdown did not complete before timeout; forcing off test VM."
  run_cli force-off "$NAME"
  run_cli wait-state "$NAME" "shut off" --timeout 60 --interval 2
fi
run_cli validate-vm "$NAME"

SNAPSHOT_NAME="hg-acceptance-snapshot"
echo
echo "== Creating snapshot =="
run_cli snapshot create "$NAME" "$SNAPSHOT_NAME" --description "HyperGery v0.1 acceptance snapshot"
run_cli snapshot list "$NAME"

echo
echo "== Reverting snapshot =="
run_cli snapshot revert "$NAME" "$SNAPSHOT_NAME"
run_cli validate-vm "$NAME"

echo
echo "== Deleting snapshot =="
run_cli snapshot delete "$NAME" "$SNAPSHOT_NAME"

echo
echo "== Delete VM? =="
read -r -p "Delete $NAME and its HyperGery-managed disk now? [y/N] " DELETE_REPLY
if [[ "$DELETE_REPLY" == "y" || "$DELETE_REPLY" == "Y" ]]; then
  run_cli delete-vm "$NAME" --delete-disks
else
  echo "VM kept. Delete later with:"
  echo "  cd hypergery-ubuntu && python3 -m hypergery_ubuntu.cli delete-vm $NAME --delete-disks"
fi
