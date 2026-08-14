#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

cp base/pyproject.toml pyproject.toml
cp base/uv.lock uv.lock
uv sync

echo "Restored pyproject.toml and uv.lock from base/"
