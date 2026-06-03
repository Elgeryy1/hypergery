#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../hypergery-ubuntu"
python3 -m hypergery_ubuntu.cli preflight
