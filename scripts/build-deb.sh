#!/usr/bin/env bash
# Construye dist/hypergery_<version>_all.deb a partir del código fuente.
#
# El paquete instala:
#   /usr/lib/hypergery/hypergery_ubuntu/   código Python (puro, arch "all")
#   /usr/bin/hypergery{,-cli,-agent}       lanzadores
#   /usr/share/applications/hypergery.desktop
#   /usr/share/icons/hicolor/scalable/apps/hypergery.svg
#   /usr/share/doc/hypergery/copyright
#
# No toca datos de usuario (~/.config/hypergery, ~/.local/share/hypergery):
# desinstalar el paquete los conserva (U1).
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$PROJECT_ROOT/hypergery-ubuntu"
PKG_DIR="$SRC_DIR/packaging"
DIST_DIR="${HYPERGERY_DIST_DIR:-$PROJECT_ROOT/dist}"

command -v dpkg-deb >/dev/null 2>&1 || { echo "ERROR: dpkg-deb no encontrado (instala el paquete 'dpkg-dev' o usa un sistema Debian/Ubuntu)" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 no encontrado en PATH" >&2; exit 2; }
if [ ! -d "$SRC_DIR/hypergery_ubuntu" ]; then
  echo "ERROR: no encuentro el código fuente en $SRC_DIR/hypergery_ubuntu" >&2
  echo "Este script debe vivir en <raíz del repo>/scripts/build-deb.sh; ejecútalo desde la raíz: ./scripts/build-deb.sh" >&2
  exit 2
fi

VERSION="$(PYTHONPATH="$SRC_DIR" python3 -c 'import hypergery_ubuntu; print(hypergery_ubuntu.__version__)')"
# PEP 440 → versión Debian: 1.1.0.dev0 → 1.1.0~dev0; 1.5.0rc0 → 1.5.0~rc0
# (las pre-releases ordenan antes que la final).
DEB_VERSION="${VERSION/.dev/\~dev}"
DEB_VERSION="${DEB_VERSION/rc/\~rc}"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

install -d "$STAGE/DEBIAN" \
  "$STAGE/usr/lib/hypergery" \
  "$STAGE/usr/bin" \
  "$STAGE/usr/share/applications" \
  "$STAGE/usr/share/icons/hicolor/scalable/apps" \
  "$STAGE/usr/share/doc/hypergery"

# Código fuente (sin caches ni metadatos de build).
cp -a "$SRC_DIR/hypergery_ubuntu" "$STAGE/usr/lib/hypergery/"
find "$STAGE/usr/lib/hypergery" -type d -name __pycache__ -prune -exec rm -rf {} +

# Lanzadores.
for entry in hypergery:hypergery_ubuntu hypergery-cli:hypergery_ubuntu.cli hypergery-agent:hypergery_ubuntu.agent; do
  bin_name="${entry%%:*}"
  module="${entry##*:}"
  cat > "$STAGE/usr/bin/$bin_name" <<WRAPPER
#!/bin/sh
export PYTHONPATH="/usr/lib/hypergery\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m $module "\$@"
WRAPPER
  chmod 0755 "$STAGE/usr/bin/$bin_name"
done

install -m 0644 "$PKG_DIR/hypergery.desktop" "$STAGE/usr/share/applications/hypergery.desktop"
install -m 0644 "$PKG_DIR/hypergery.svg" "$STAGE/usr/share/icons/hicolor/scalable/apps/hypergery.svg"
install -m 0644 "$PROJECT_ROOT/LICENSE" "$STAGE/usr/share/doc/hypergery/copyright"

INSTALLED_SIZE="$(du -ks "$STAGE/usr" | cut -f1)"

cat > "$STAGE/DEBIAN/control" <<CONTROL
Package: hypergery
Version: $DEB_VERSION
Section: admin
Priority: optional
Architecture: all
Installed-Size: $INSTALLED_SIZE
Depends: python3 (>= 3.10), python3-pyside6.qtwidgets | python3-pyside6, python3-pyside6.qtnetwork | python3-pyside6, python3-pyside6.qtgui | python3-pyside6, python3-pyside6.qtcore | python3-pyside6
Recommends: qemu-kvm, libvirt-daemon-system, libvirt-clients, virt-viewer, qemu-utils, ovmf, swtpm, swtpm-tools
Maintainer: HyperGery <gerard.alpo17@gmail.com>
Homepage: https://github.com/Elgeryy1/hypergery
Description: Personal KVM/QEMU/libvirt virtual machine manager
 HyperGery is a desktop virtual machine manager for Ubuntu built on
 KVM, QEMU and libvirt, with multi-host support (Hub/registry, agents),
 labs, templates and safe VM migration.
CONTROL

cat > "$STAGE/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q /usr/share/icons/hicolor || true
fi
exit 0
POSTINST

cat > "$STAGE/DEBIAN/postrm" <<'POSTRM'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || true
fi
exit 0
POSTRM

chmod 0755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm"

mkdir -p "$DIST_DIR"
OUT="$DIST_DIR/hypergery_${DEB_VERSION}_all.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$OUT" >/dev/null
# stdout = solo la ruta del .deb (contrato usado por los tests); lo humano va a stderr.
echo "$OUT"
echo "OK: paquete generado. Para instalarlo:" >&2
echo "  sudo apt install \"$OUT\"" >&2
