#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  echo 'Create the project .venv first, or set PYTHON_BIN to its Python executable.' >&2
  exit 1
fi
cd "$ROOT"
PYTHONPATH=src "$PYTHON" scripts/export_3d_pack.py --out artifacts/3d-pack --seeds 11 29 47
exec "$PYTHON" scripts/serve_3d.py --dir artifacts/3d-pack --host 127.0.0.1 --port 8765
