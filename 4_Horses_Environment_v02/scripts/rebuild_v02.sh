#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BLENDER="${BLENDER_BIN:-/Applications/Blender.app/Contents/MacOS/Blender}"
SOURCE="${1:?Pass the original v01 warehouse_environment.blend as the first argument}"
if [[ "$SOURCE" == "$ROOT/warehouse_environment.blend" ]]; then
  echo 'Use the original v01 source to preserve the original character animation data.' >&2
  exit 2
fi
cd "$ROOT"
"$BLENDER" -b --factory-startup -t 6 --python-exit-code 1 --python scripts/build_environment.py -- --output "$ROOT"
"$BLENDER" -b "$ROOT/warehouse_environment.blend" -t 6 --python-exit-code 1 --python scripts/flexsim_finish.py -- --output "$ROOT" --source "$SOURCE" --render
