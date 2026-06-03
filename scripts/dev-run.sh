#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../hypergery-ubuntu"
python_bin="${HYPERGERY_PYTHON:-python3}"

if ! "$python_bin" - <<'PY' >/dev/null 2>&1
import PySide6
PY
then
  cat >&2 <<EOF
HyperGery Qt UI requires PySide6 in the Python environment used to run it.

Recommended setup, especially when the repo is on a NAS:
  python3 -m venv --copies ~/.venvs/hypergery
  source ~/.venvs/hypergery/bin/activate
  python -m pip install --upgrade pip
  python -m pip install -e ./hypergery-ubuntu

Then run:
  source ~/.venvs/hypergery/bin/activate
  ./scripts/dev-run.sh

You can also set HYPERGERY_PYTHON=/path/to/python.
EOF
  exit 2
fi

exec "$python_bin" -m hypergery_ubuntu
