#!/usr/bin/env bash
# Delegado de conveniencia: el build real vive en <raíz del repo>/scripts/build-deb.sh.
# Existe porque el UAT U1 se ejecutó con cwd=hypergery-ubuntu/ y `./scripts/build-deb.sh`
# no existía desde ahí. Ambas rutas deben funcionar.
set -euo pipefail

REAL="$(cd "$(dirname "$0")/../.." && pwd)/scripts/build-deb.sh"
if [ ! -f "$REAL" ]; then
  echo "ERROR: no encuentro el script de build en $REAL" >&2
  echo "Ejecuta ./scripts/build-deb.sh desde la raíz del repositorio." >&2
  exit 2
fi
exec bash "$REAL" "$@"
