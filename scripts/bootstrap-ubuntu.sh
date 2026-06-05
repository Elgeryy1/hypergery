#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
venv_dir="${HYPERGERY_VENV:-$HOME/.venvs/hypergery}"
venv_python="$venv_dir/bin/python"

mode="interactive"
system_only=0

usage() {
  cat <<'EOF'
Usage: scripts/bootstrap-ubuntu.sh [--check-only] [--install] [--no-install] [--system-only] [--help]

Checks and optionally prepares an Ubuntu/Linux host for HyperGery.

Modes:
  --check-only   Print readiness report only; do not install anything.
  --install      Install/fix missing items without an interactive prompt except sudo/pkexec.
  --no-install   Print readiness report and fail if anything is missing.
  --system-only  Install/check system dependencies only; skip Python venv setup.
  --help         Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check-only) mode="check-only" ;;
    --install) mode="install" ;;
    --no-install) mode="no-install" ;;
    --system-only) system_only=1 ;;
    --help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

has_cmd() {
  command -v "$1" >/dev/null 2>&1
}

service_exists() {
  systemctl list-unit-files "$1" >/dev/null 2>&1 || systemctl list-unit-files "$1.socket" >/dev/null 2>&1
}

service_active() {
  systemctl is-active --quiet "$1" 2>/dev/null || systemctl is-active --quiet "$1.socket" 2>/dev/null
}

apt_has_candidate() {
  apt-cache policy "$1" 2>/dev/null | awk '/Candidate:/ {print $2}' | grep -qv '^\(none\)$'
}

sudo_runner() {
  if has_cmd sudo; then
    sudo "$@"
  elif has_cmd pkexec; then
    pkexec "$@"
  else
    echo "Neither sudo nor pkexec is available; cannot install system dependencies." >&2
    return 1
  fi
}

missing_packages=()
missing_items=()
inactive_services=()
missing_groups=()
python_notes=()

need_package_for_cmd() {
  local cmd="$1"
  local package="$2"
  if ! has_cmd "$cmd"; then
    missing_items+=("$cmd")
    missing_packages+=("$package")
  fi
}

check_system() {
  missing_packages=()
  missing_items=()
  inactive_services=()
  missing_groups=()

  need_package_for_cmd qemu-system-x86_64 qemu-system-x86
  need_package_for_cmd qemu-img qemu-utils
  need_package_for_cmd virsh libvirt-clients
  if ! has_cmd virt-viewer && ! has_cmd remote-viewer; then
    missing_items+=("virt-viewer or remote-viewer")
    missing_packages+=("virt-viewer")
  fi
  need_package_for_cmd python3 python3-minimal

  if ! python3 -m venv --help >/dev/null 2>&1; then
    missing_items+=("python3-venv")
    missing_packages+=("python3-venv")
  fi
  if ! python3 -m pip --version >/dev/null 2>&1; then
    missing_items+=("python3-pip")
    missing_packages+=("python3-pip")
  fi

  if [[ ! -e /dev/kvm ]]; then
    missing_items+=("/dev/kvm")
  elif [[ ! -r /dev/kvm || ! -w /dev/kvm ]]; then
    missing_items+=("/dev/kvm accessible by current user")
  fi

  local libvirt_active=1
  if service_exists libvirtd.service && service_active libvirtd.service; then
    libvirt_active=0
  elif service_exists virtqemud.service && service_active virtqemud.service; then
    libvirt_active=0
  elif service_exists virtqemud.socket && service_active virtqemud.socket; then
    libvirt_active=0
  fi
  if [[ "$libvirt_active" -ne 0 ]]; then
    if service_exists libvirtd.service; then
      inactive_services+=("libvirtd")
    elif service_exists virtqemud.service || service_exists virtqemud.socket; then
      inactive_services+=("virtqemud")
    else
      inactive_services+=("libvirtd or virtqemud")
      missing_packages+=("libvirt-daemon-system")
    fi
  fi

  local groups
  groups="$(id -nG)"
  if ! grep -qw kvm <<<"$groups"; then
    missing_groups+=("kvm")
  fi
  if ! grep -qw libvirt <<<"$groups"; then
    missing_groups+=("libvirt")
  fi
}

check_python_env() {
  python_notes=()
  if [[ "$system_only" -eq 1 ]]; then
    return
  fi
  if [[ ! -x "$venv_python" ]]; then
    python_notes+=("venv missing: $venv_dir")
    return
  fi
  if ! "$venv_python" - <<'PY' >/dev/null 2>&1
import PySide6
PY
  then
    python_notes+=("PySide6 missing in $venv_dir")
  fi
  if ! "$venv_python" - <<'PY' >/dev/null 2>&1
import hypergery_ubuntu
PY
  then
    python_notes+=("HyperGery package not installed editable in $venv_dir")
  fi
}

dedupe_packages() {
  local -A seen=()
  local out=()
  local pkg
  for pkg in "$@"; do
    [[ -n "$pkg" ]] || continue
    if [[ -z "${seen[$pkg]:-}" ]]; then
      seen[$pkg]=1
      out+=("$pkg")
    fi
  done
  printf '%s\n' "${out[@]}"
}

print_summary() {
  echo "HyperGery setup check:"
  echo
  if [[ "${#missing_packages[@]}" -gt 0 || "${#missing_items[@]}" -gt 0 ]]; then
    echo "Missing system packages/tools:"
    local pkg
    while IFS= read -r pkg; do
      [[ -n "$pkg" ]] && echo "- $pkg"
    done < <(dedupe_packages "${missing_packages[@]}")
    local item
    for item in "${missing_items[@]}"; do
      echo "- $item"
    done
  else
    echo "Missing system packages/tools: none"
  fi
  echo
  if [[ "${#inactive_services[@]}" -gt 0 ]]; then
    echo "Services not active:"
    printf -- '- %s\n' "${inactive_services[@]}"
  else
    echo "Services not active: none"
  fi
  echo
  if [[ "${#missing_groups[@]}" -gt 0 ]]; then
    echo "User groups missing:"
    printf -- '- %s\n' "${missing_groups[@]}"
  else
    echo "User groups missing: none"
  fi
  echo
  if [[ "${#python_notes[@]}" -gt 0 ]]; then
    echo "Python environment:"
    printf -- '- %s\n' "${python_notes[@]}"
  else
    echo "Python environment: ready"
  fi
  echo
}

has_missing() {
  [[ "${#missing_packages[@]}" -gt 0 || "${#missing_items[@]}" -gt 0 || "${#inactive_services[@]}" -gt 0 || "${#missing_groups[@]}" -gt 0 || "${#python_notes[@]}" -gt 0 ]]
}

install_system_packages() {
  local packages=(
    qemu-system-x86
    qemu-utils
    libvirt-daemon-system
    libvirt-clients
    libvirt-daemon-driver-qemu
    libvirt-daemon-config-network
    virt-viewer
    ovmf
    dnsmasq-base
    python3-pip
    python3-venv
    python3-dev
    python3-tk
    libxcb-cursor0
    libxcb-icccm4
    libxcb-image0
    libxcb-keysyms1
    libxcb-render-util0
    libxkbcommon-x11-0
  )

  echo "Installing Ubuntu packages. Sudo/pkexec may ask for your password."
  sudo_runner apt update
  sudo_runner apt install -y "${packages[@]}"

  if apt_has_candidate qemu-kvm; then
    sudo_runner apt install -y qemu-kvm || echo "Warning: optional qemu-kvm could not be installed; continuing." >&2
  else
    echo "Optional package qemu-kvm has no candidate on this Ubuntu release; continuing with qemu-system-x86." >&2
  fi
}

enable_services() {
  echo "Enabling libvirt services when available."
  if service_exists libvirtd.service; then
    sudo_runner systemctl enable --now libvirtd
  fi
  if service_exists virtlogd.service; then
    sudo_runner systemctl enable --now virtlogd
  fi
  local unit
  for unit in virtqemud virtnetworkd virtstoraged virtlogd virtproxyd; do
    if service_exists "$unit.socket"; then
      sudo_runner systemctl enable --now "$unit.socket"
    elif service_exists "$unit.service"; then
      sudo_runner systemctl enable --now "$unit.service"
    fi
  done
}

fix_groups() {
  if [[ "${#missing_groups[@]}" -eq 0 ]]; then
    return
  fi
  echo "Adding $USER to kvm/libvirt groups. Sudo/pkexec may ask for your password."
  sudo_runner usermod -aG kvm,libvirt "$USER"
  echo
  echo "You must log out and log back in before KVM/libvirt permissions fully apply."
  if has_cmd sg; then
    echo "Temporary option if group membership is already visible in /etc/group:"
    echo "  sg libvirt -c './scripts/dev-run.sh --no-install'"
  fi
}

setup_python_env() {
  if [[ "$system_only" -eq 1 ]]; then
    return
  fi
  echo "Preparing Python environment in $venv_dir"
  if [[ ! -x "$venv_python" ]]; then
    python3 -m venv --copies "$venv_dir"
  fi
  "$venv_python" -m pip install --upgrade pip
  "$venv_python" -m pip install -e "$repo_root/hypergery-ubuntu"
  if ! "$venv_python" - <<'PY' >/dev/null 2>&1
import PySide6
PY
  then
    "$venv_python" -m pip install PySide6
  fi
}

check_system
check_python_env
print_summary

if ! has_missing; then
  exit 0
fi

case "$mode" in
  check-only)
    exit 2
    ;;
  no-install)
    echo "HyperGery setup is incomplete and --no-install was requested." >&2
    exit 2
    ;;
  interactive)
    echo "HyperGery can install/fix most of this now."
    echo "Sudo permission will be requested."
    echo
    read -r -p "Continue? [y/N] " answer
    case "$answer" in
      y|Y|yes|YES) ;;
      *) echo "Setup cancelled."; exit 2 ;;
    esac
    ;;
  install)
    echo "--install selected; installing/fixing missing items. Sudo permission may be requested."
    ;;
esac

install_system_packages
enable_services
fix_groups
setup_python_env

check_system
check_python_env
print_summary

if has_missing; then
  echo "HyperGery setup still has missing items. Review the summary above." >&2
  exit 2
fi

exit 0
