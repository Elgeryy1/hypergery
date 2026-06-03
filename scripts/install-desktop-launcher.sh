#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"
WRAPPER="$BIN_DIR/hypergery"
DESKTOP_FILE="$APP_DIR/hypergery.desktop"
DEFAULT_VENV_PYTHON="$HOME/.venvs/hypergery/bin/python"

if [[ -x "${HYPERGERY_PYTHON:-}" ]]; then
  PYTHON_BIN="$HYPERGERY_PYTHON"
elif [[ -x "$DEFAULT_VENV_PYTHON" ]]; then
  PYTHON_BIN="$DEFAULT_VENV_PYTHON"
else
  PYTHON_BIN="$(command -v python3)"
fi

mkdir -p "$BIN_DIR" "$APP_DIR"

cat > "$WRAPPER" <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "$PROJECT_ROOT/hypergery-ubuntu"
exec "$PYTHON_BIN" -m hypergery_ubuntu
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
echo
echo "Launcher Python:"
echo "  $PYTHON_BIN"
echo
echo "If PySide6 is installed in a different virtualenv, rerun with:"
echo "  HYPERGERY_PYTHON=/path/to/venv/bin/python ./scripts/install-desktop-launcher.sh"
echo
echo "Recommended external venv:"
echo "  python3 -m venv --copies ~/.venvs/hypergery"
echo "  source ~/.venvs/hypergery/bin/activate"
echo "  python -m pip install -e ./hypergery-ubuntu"
