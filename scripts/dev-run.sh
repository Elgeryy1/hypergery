#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
venv_dir="${HYPERGERY_VENV:-$HOME/.venvs/hypergery}"
python_bin="${HYPERGERY_PYTHON:-$venv_dir/bin/python}"
bootstrap_mode=()
check_only=0

usage() {
  cat <<'EOF'
Usage: ./scripts/dev-run.sh [--check-only] [--install] [--no-install] [--help]

First-run friendly launcher for HyperGery on Ubuntu/Linux.

Options:
  --check-only   Check host, services, groups, and Python env; do not install or launch.
  --install      Install/fix missing dependencies without an interactive prompt except sudo/pkexec.
  --no-install   Do not install; fail if anything required is missing.
  --help         Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check-only)
      bootstrap_mode=(--check-only)
      check_only=1
      ;;
    --install)
      bootstrap_mode=(--install)
      ;;
    --no-install)
      bootstrap_mode=(--no-install)
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ "${#bootstrap_mode[@]}" -eq 0 ]]; then
  bootstrap_mode=()
fi

"$repo_root/scripts/bootstrap-ubuntu.sh" "${bootstrap_mode[@]}"

if [[ "$check_only" -eq 1 ]]; then
  exit 0
fi

if [[ ! -x "$python_bin" ]]; then
  echo "Python environment is missing: $python_bin" >&2
  echo "Run ./scripts/dev-run.sh --install to create $venv_dir safely with --copies." >&2
  exit 2
fi

echo "Running HyperGery preflight..."
if ! "$python_bin" -m hypergery_ubuntu.cli preflight; then
  cat >&2 <<EOF

Preflight did not pass. If user groups were just changed, log out and back in
before starting HyperGery so kvm/libvirt permissions apply.
EOF
  exit 2
fi

cd "$repo_root/hypergery-ubuntu"

exec "$python_bin" -m hypergery_ubuntu
