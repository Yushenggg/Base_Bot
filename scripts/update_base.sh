#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

cp pyproject.toml base/pyproject.toml
cp uv.lock base/uv.lock

echo "Updated base/pyproject.toml and base/uv.lock from current files"
