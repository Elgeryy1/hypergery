#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"
WRAPPER="$BIN_DIR/hypergery"
DESKTOP_FILE="$APP_DIR/hypergery.desktop"

mkdir -p "$BIN_DIR" "$APP_DIR"

cat > "$WRAPPER" <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "$PROJECT_ROOT/hypergery-ubuntu"
exec python3 -m hypergery_ubuntu
EOF
chmod +x "$WRAPPER"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=HyperGery
Comment=Ubuntu KVM/QEMU/libvirt virtual machine manager
Exec=$WRAPPER
Terminal=false
Categories=System;Emulator;
StartupNotify=true
EOF

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APP_DIR" >/dev/null 2>&1 || true
fi

echo "Installed desktop launcher:"
echo "  $DESKTOP_FILE"
echo "Run HyperGery from the application menu or with:"
echo "  $WRAPPER"
