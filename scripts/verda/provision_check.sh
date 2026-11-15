#!/usr/bin/env bash
# Provision & pre-flight verification for Verda H200 / H100 nodes without reinstalling pre-warmed RL packages.
set -euo pipefail

FAST_CACHE_ROOT="${FAST_CACHE_ROOT:-/tmp/fast-cache}"
export HF_HOME="${HF_HOME:-${FAST_CACHE_ROOT}/hf}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-${FAST_CACHE_ROOT}/uv}"
export VLLM_CACHE_ROOT="${VLLM_CACHE_ROOT:-${FAST_CACHE_ROOT}/vllm}"
export TRITON_CACHE_DIR="${TRITON_CACHE_DIR:-${FAST_CACHE_ROOT}/triton}"
export TORCHINDUCTOR_CACHE_DIR="${TORCHINDUCTOR_CACHE_DIR:-${FAST_CACHE_ROOT}/inductor}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-${FAST_CACHE_ROOT}/xdg}"
export TMPDIR="${TMPDIR:-${FAST_CACHE_ROOT}/tmp}"

DRY_RUN=0
CLI_MODEL_ID=""
ENV_READY_FILE="${ENV_READY_FILE:-/root/bench/H200_ENV_READY.json}"
MOCK_GPU_SPEC="${VERDA_GPU_SPEC:-}"

usage() {
  cat <<'EOF'
Usage: provision_check.sh [--dry-run] [--model-id <id>] [--env-ready-file <path>] [--mock-gpu-spec <count:vram_gb:name>] [--help]

Arms the 6h budget dead-man timer (`sudo shutdown -h +360`), exports all 7 `/tmp/fast-cache/*`
RAM-tmpfs cache directories, reuses `/tmp/fast-cache/rl-venv/bin/python` and `/root/bench/H200_ENV_READY.json`
without reinstalling PyTorch/vLLM/TRL/PEFT, prunes dangling Docker layers, and auto-detects GPU topology.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --model-id)
      CLI_MODEL_ID="$2"
      shift 2
      ;;
    --env-ready-file)
      ENV_READY_FILE="$2"
      shift 2
      ;;
    --mock-gpu-spec)
      MOCK_GPU_SPEC="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [[ -x /tmp/fast-cache/rl-venv/bin/python ]]; then
  RL_PYTHON="${RL_PYTHON:-/tmp/fast-cache/rl-venv/bin/python}"
elif [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
  RL_PYTHON="${RL_PYTHON:-${REPO_ROOT}/.venv/bin/python}"
elif [[ -x "${REPO_ROOT}/../../.venv/bin/python" ]]; then
  RL_PYTHON="${RL_PYTHON:-${REPO_ROOT}/../../.venv/bin/python}"
elif command -v python3.12 >/dev/null 2>&1; then
  RL_PYTHON="${RL_PYTHON:-$(command -v python3.12)}"
else
  RL_PYTHON="${RL_PYTHON:-python3}"
fi

if [[ "$DRY_RUN" -eq 0 ]]; then
  mkdir -p "$HF_HOME" "$UV_CACHE_DIR" "$VLLM_CACHE_ROOT" "$TRITON_CACHE_DIR" "$TORCHINDUCTOR_CACHE_DIR" "$XDG_CACHE_HOME" "$TMPDIR"
  sudo shutdown -h +360 "6h budget guard" >/dev/null 2>&1 || true
  if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi -L >/dev/null 2>&1 || true
  fi
  if command -v docker >/dev/null 2>&1; then
    docker image prune -f >/dev/null 2>&1 || true
  fi
fi

PYTHONPATH="${REPO_ROOT}/src" "$RL_PYTHON" - "$DRY_RUN" "$CLI_MODEL_ID" "$ENV_READY_FILE" "$MOCK_GPU_SPEC" "$RL_PYTHON" "${SCRIPT_DIR}/train_grpo_qwen7b.py" <<'PY'
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

dry_run = sys.argv[1] == "1"
cli_model_id = sys.argv[2] or None
env_ready_file = sys.argv[3]
mock_gpu_spec = sys.argv[4] or None
rl_python = sys.argv[5]
grpo_path = Path(sys.argv[6]).resolve()

grpo_spec = importlib.util.spec_from_file_location("train_grpo_qwen7b", grpo_path)
mod = importlib.util.module_from_spec(grpo_spec)
grpo_spec.loader.exec_module(mod)

model_id = mod.resolve_model_id(cli_model_id, env_ready_file)
topology = mod.detect_gpu_topology(mock_gpu_spec)
hf_home = Path(os.environ["HF_HOME"])
hub_slug = "models--" + model_id.replace("/", "--")
model_cached = (hf_home / "hub" / hub_slug).exists() or (hf_home / hub_slug).exists()

disk_usage = shutil.disk_usage("/")
root_free_gb = round(disk_usage.free / (1024**3), 2)

base_image_cached = False
if not dry_run and shutil.which("docker"):
    insp = subprocess.run(
        ["docker", "image", "inspect", "python:3.12.14-slim-bookworm"],
        capture_output=True,
        text=True,
    )
    base_image_cached = insp.returncode == 0

report = {
    "status": "dry_run_ok" if dry_run else "live_ok",
    "deadman_shutdown": "sudo shutdown -h +360",
    "docker_prune": "docker image prune -f",
    "rl_python": rl_python,
    "prewarmed_rl_venv": Path("/tmp/fast-cache/rl-venv/bin/python").is_file(),
    "env_ready_present": Path(env_ready_file).is_file(),
    "model_id": model_id,
    "model_cached_in_hf_home": model_cached,
    "python_slim_bookworm_cached": base_image_cached,
    "root_free_gb": root_free_gb,
    "gpu_topology": topology,
    "fast_cache_env": {k: os.environ[k] for k in mod.FAST_CACHE_DEFAULTS},
}
print(json.dumps(report, indent=2))

if not dry_run:
    if topology["mode"] == "cpu_only":
        raise SystemExit("ERROR: Live provision_check requires >= 1 NVIDIA GPU")
    if root_free_gb < 8.0:
        raise SystemExit(f"ERROR: Root filesystem critically low ({root_free_gb} GB free)")
PY
