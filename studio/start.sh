#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
RUNTIME="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies"
if command -v node >/dev/null 2>&1; then
  NODE="$(command -v node)"
elif [[ -x "$RUNTIME/node/bin/node" ]]; then
  NODE="$RUNTIME/node/bin/node"
else
  echo 'Node.js 20.19+ is required to run the local player.' >&2
  exit 1
fi
export PATH="$(dirname "$NODE"):$PATH"
cd "$ROOT"
if [[ ! -f node_modules/vite/bin/vite.js ]]; then
  if command -v npm >/dev/null 2>&1; then
    npm install --ignore-scripts
  elif command -v pnpm >/dev/null 2>&1; then
    pnpm install --frozen-lockfile --ignore-scripts
  elif [[ -x "$RUNTIME/bin/fallback/pnpm" ]]; then
    "$RUNTIME/bin/fallback/pnpm" install --frozen-lockfile --ignore-scripts --store-dir "${TMPDIR:-/tmp}/four-horses-pnpm-store" --cache-dir "${TMPDIR:-/tmp}/four-horses-pnpm-cache"
  else
    echo 'Install npm or pnpm, then run this command again.' >&2
    exit 1
  fi
fi
"$NODE" scripts/prepare-assets.mjs
exec "$NODE" node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort
