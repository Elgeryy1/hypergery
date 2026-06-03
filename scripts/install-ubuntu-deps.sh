#!/usr/bin/env bash
set -euo pipefail

echo "HyperGery Ubuntu dependencies"
echo "This script installs packages with apt and enables libvirt. It will ask for sudo."

sudo apt update

required_packages=(
  qemu-system-x86 \
  qemu-utils \
  libvirt-daemon-system \
  libvirt-clients \
  libvirt-daemon-driver-qemu \
  libvirt-daemon-config-network \
  virt-viewer \
  ovmf \
  dnsmasq-base \
  python3-pip \
  python3-venv \
  python3-dev \
  python3-tk \
  libxcb-cursor0 \
  libxcb-icccm4 \
  libxcb-image0 \
  libxcb-keysyms1 \
  libxcb-render-util0 \
  libxkbcommon-x11-0
)

sudo apt install -y "${required_packages[@]}"

if apt-cache show qemu-kvm >/dev/null 2>&1; then
  sudo apt install -y qemu-kvm || echo "Warning: optional qemu-kvm package could not be installed; continuing." >&2
else
  echo "Optional package qemu-kvm is not available on this Ubuntu release; using qemu-system-x86." >&2
fi

if systemctl list-unit-files libvirtd.service >/dev/null 2>&1; then
  sudo systemctl enable --now libvirtd
elif systemctl list-unit-files virtqemud.service >/dev/null 2>&1; then
  sudo systemctl enable --now virtqemud
else
  echo "Warning: neither libvirtd.service nor virtqemud.service was found." >&2
fi

sudo usermod -aG kvm,libvirt "$USER"

echo
echo "Post-install checks:"
if [[ -e /dev/kvm ]]; then
  echo "  OK: /dev/kvm exists"
else
  echo "  ERROR: /dev/kvm is missing. Enable hardware virtualization in BIOS/UEFI and confirm KVM modules are loaded."
fi

if command -v virsh >/dev/null 2>&1; then
  echo "  OK: virsh installed"
else
  echo "  ERROR: virsh is missing"
fi

if command -v qemu-system-x86_64 >/dev/null 2>&1; then
  echo "  OK: qemu-system-x86_64 installed"
else
  echo "  ERROR: qemu-system-x86_64 is missing"
fi

if command -v virt-viewer >/dev/null 2>&1 || command -v remote-viewer >/dev/null 2>&1; then
  echo "  OK: console viewer installed"
else
  echo "  ERROR: no console viewer found"
fi

echo
echo "Done. Log out and back in so the kvm/libvirt group changes take effect."
echo "Install Python UI dependencies from the project with:"
echo "  python3 -m venv --copies ~/.venvs/hypergery"
echo "  source ~/.venvs/hypergery/bin/activate"
echo "  python -m pip install -e ./hypergery-ubuntu"
echo "After logging back in, run: ./scripts/preflight.sh"
