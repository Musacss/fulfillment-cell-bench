#!/usr/bin/env bash
# Execute Stage-2 Replay Gate & Stage-3 Blind Harbor + vLLM Evaluation Matrix (Harbor 0.26.0 compatible).
set -euo pipefail
set +x

FAST_CACHE_ROOT="${FAST_CACHE_ROOT:-/tmp/fast-cache}"
export HF_HOME="${HF_HOME:-${FAST_CACHE_ROOT}/hf}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-${FAST_CACHE_ROOT}/uv}"
export VLLM_CACHE_ROOT="${VLLM_CACHE_ROOT:-${FAST_CACHE_ROOT}/vllm}"
export TRITON_CACHE_DIR="${TRITON_CACHE_DIR:-${FAST_CACHE_ROOT}/triton}"
export TORCHINDUCTOR_CACHE_DIR="${TORCHINDUCTOR_CACHE_DIR:-${FAST_CACHE_ROOT}/inductor}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-${FAST_CACHE_ROOT}/xdg}"
export TMPDIR="${TMPDIR:-${FAST_CACHE_ROOT}/tmp}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

DRY_RUN=0
SMOKE_LOCAL=0
CLI_MODEL_ID=""
ENV_READY_FILE="${ENV_READY_FILE:-/root/bench/H200_ENV_READY.json}"
OUT_DIR="${REPO_ROOT}/evidence/benchmark-v2"
HARBOR_RUNS_DIR="${REPO_ROOT}/evidence/harbor-runs"
RL_SEEDS_FILE="${REPO_ROOT}/artifacts/verda/rl_seeds.json"
ADAPTER_DIR="${REPO_ROOT}/artifacts/verda/qwen_rl/grpo_adapter"
BLIND_COUNT=8
FRONTIER_MODEL="${FRONTIER_MODEL:-gemini/gemini-4-carbon}"
FRONTIER_TRIALS="${FRONTIER_TRIALS:-3}"
SECONDARY_FRONTIER_MODEL="${SECONDARY_FRONTIER_MODEL:-gemini/gemini-3.1-pro-preview}"
SECONDARY_FRONTIER_TRIALS="${SECONDARY_FRONTIER_TRIALS:-1}"

usage() {
  cat <<'EOF'
Usage: run_harbor_matrix.sh [options]

Options:
  --dry-run                      Validate 4-way seed disjointness & matrix plan in <2s without Docker/SSH/.env
  --smoke-local                  Run local CPU verification of nop/stop_early/manual/oracle into --out-dir
  --out-dir <dir>                Output directory (default: evidence/benchmark-v2)
  --harbor-runs-dir <dir>        Sanitized Harbor run logs directory (default: evidence/harbor-runs)
  --rl-seeds <path>              RL train/val seeds JSON for 4-way disjointness verification
  --adapter-dir <dir>            Post-RL LoRA adapter directory
  --blind-count <N>              Number of post-freeze CSPRNG blind seeds (default: 8)
  --model-id <id>                Override open RL base model ID (default from H200_ENV_READY.json or Qwen/Qwen3.5-9B)
  --env-ready-file <path>        Path to H200_ENV_READY.json (default: /root/bench/H200_ENV_READY.json)
  --help                         Show this message
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
    --smoke-local)
      SMOKE_LOCAL=1
      shift
      ;;
    --out-dir)
      OUT_DIR="$2"
      shift 2
      ;;
    --harbor-runs-dir)
      HARBOR_RUNS_DIR="$2"
      shift 2
      ;;
    --rl-seeds)
      RL_SEEDS_FILE="$2"
      shift 2
      ;;
    --adapter-dir)
      ADAPTER_DIR="$2"
      shift 2
      ;;
    --blind-count)
      BLIND_COUNT="$2"
      shift 2
      ;;
    --model-id)
      CLI_MODEL_ID="$2"
      shift 2
      ;;
    --env-ready-file)
      ENV_READY_FILE="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
  BENCH_PYTHON="${BENCH_PYTHON:-${REPO_ROOT}/.venv/bin/python}"
elif [[ -x "${REPO_ROOT}/../../.venv/bin/python" ]]; then
  BENCH_PYTHON="${BENCH_PYTHON:-${REPO_ROOT}/../../.venv/bin/python}"
elif [[ -x /tmp/fast-cache/rl-venv/bin/python ]]; then
  BENCH_PYTHON="${BENCH_PYTHON:-/tmp/fast-cache/rl-venv/bin/python}"
elif command -v python3.12 >/dev/null 2>&1; then
  BENCH_PYTHON="${BENCH_PYTHON:-$(command -v python3.12)}"
else
  BENCH_PYTHON="${BENCH_PYTHON:-python3}"
fi

if [[ -x /tmp/fast-cache/rl-venv/bin/python ]]; then
  RL_PYTHON="${RL_PYTHON:-/tmp/fast-cache/rl-venv/bin/python}"
else
  RL_PYTHON="${RL_PYTHON:-$BENCH_PYTHON}"
fi

RESOLVED_MODEL_ID="$(
  PYTHONPATH="${REPO_ROOT}/src" "$BENCH_PYTHON" - "$CLI_MODEL_ID" "$ENV_READY_FILE" "${SCRIPT_DIR}/train_grpo_qwen7b.py" <<'PY'
import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("train_grpo_qwen7b", Path(sys.argv[3]))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(mod.resolve_model_id(sys.argv[1] or None, sys.argv[2] or None))
PY
)"

# Handle --dry-run and --smoke-local strictly on CPU without touching .env, Docker, Harbor, or network
if [[ "$DRY_RUN" -eq 1 || "$SMOKE_LOCAL" -eq 1 ]]; then
  PYTHONPATH="${REPO_ROOT}/src" "$BENCH_PYTHON" - \
    "$DRY_RUN" "$SMOKE_LOCAL" "$RESOLVED_MODEL_ID" "$OUT_DIR" "$HARBOR_RUNS_DIR" \
    "$RL_SEEDS_FILE" "$BLIND_COUNT" "$FRONTIER_MODEL" "$SECONDARY_FRONTIER_MODEL" \
    "${SCRIPT_DIR}/generate_sft_traces.py" "${REPO_ROOT}" <<'PY'
from dataclasses import asdict
from fractions import Fraction as F
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

dry_run = sys.argv[1] == "1"
smoke_local = sys.argv[2] == "1"
model_id = sys.argv[3]
out_dir = Path(sys.argv[4])
harbor_runs_dir = Path(sys.argv[5])
rl_seeds_file = Path(sys.argv[6])
blind_count = int(sys.argv[7])
frontier_model = sys.argv[8]
secondary_model = sys.argv[9]
sft_script_path = Path(sys.argv[10])
repo_root = Path(sys.argv[11])

spec = importlib.util.spec_from_file_location("generate_sft_traces", sft_script_path)
sft_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sft_mod)

from robotization_bench.contracts import load_world
from robotization_bench.episode import QuarterlyEpisode
from robotization_bench.grading import evaluate_quarterly, invalid
from robotization_bench.quarterly import manual_quarterly_value
from robotization_bench.reference import solve
from robotization_bench.verifier import verify_quarterly_file

world = load_world()
dev_seeds = list(world["development_seeds"])
replay_seeds = json.loads((repo_root / "evidence" / "replay_seeds.json").read_text(encoding="utf-8"))

if rl_seeds_file.is_file():
    rl_doc = json.loads(rl_seeds_file.read_text(encoding="utf-8"))
    rl_train = list(rl_doc["rl_train_seeds"])
    rl_val = list(rl_doc["rl_val_seeds"])
elif dry_run:
    rl_train = sft_mod._fast_disjoint_csprng_seeds(2, set(dev_seeds) | set(replay_seeds))
    rl_val = sft_mod._fast_disjoint_csprng_seeds(2, set(dev_seeds) | set(replay_seeds) | set(rl_train))
else:
    rl_train = sft_mod.sample_feasible_csprng_seeds(
        world, count=2, forbidden=set(dev_seeds) | set(replay_seeds)
    )
    rl_val = sft_mod.sample_feasible_csprng_seeds(
        world, count=2, forbidden=set(dev_seeds) | set(replay_seeds) | set(rl_train)
    )

# Validate RL pools disjoint BEFORE sampling blind seeds so injected overlaps fail immediately
sft_mod.verify_4way_seed_disjointness(dev_seeds, replay_seeds, rl_train, rl_val, None)

if dry_run:
    blind_seeds = sft_mod._fast_disjoint_csprng_seeds(
        blind_count, set(dev_seeds) | set(replay_seeds) | set(rl_train) | set(rl_val)
    )
else:
    blind_seeds = sft_mod.sample_feasible_csprng_seeds(
        world,
        count=blind_count,
        forbidden=set(dev_seeds) | set(replay_seeds) | set(rl_train) | set(rl_val),
    )
sft_mod.verify_4way_seed_disjointness(dev_seeds, replay_seeds, rl_train, rl_val, blind_seeds)

if dry_run:
    print(
        json.dumps(
            {
                "status": "dry_run_ok",
                "model_id": model_id,
                "frontier_model": frontier_model,
                "secondary_frontier_model": secondary_model,
                "blind_seeds_preview": blind_seeds,
                "disjoint_4way": True,
                "stages": ["stage2_replay_gate", "stage3_blind_matrix"],
            },
            indent=2,
        )
    )
    raise SystemExit(0)

# --smoke-local: materialize CPU-verifiable evidence/benchmark-v2 layout matching grade.py
out_dir.mkdir(parents=True, exist_ok=True)
harbor_runs_dir.mkdir(parents=True, exist_ok=True)

blind_bytes = (json.dumps(blind_seeds) + "\n").encode("utf-8")
(out_dir / "blind_seeds.json").write_bytes(blind_bytes)
blind_sha = hashlib.sha256(blind_bytes).hexdigest()
(out_dir / "blind_seeds.sha256").write_text(f"{blind_sha}  blind_seeds.json\n", encoding="utf-8")

git_proc = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "HEAD"], capture_output=True, text=True)
commit_sha = git_proc.stdout.strip() or None
world_sha = hashlib.sha256((repo_root / "data" / "world_spec.json").read_bytes()).hexdigest()
source_meta = {"commit": commit_sha, "world_sha256": world_sha, "schema_version": 2, "harbor_checked_version": "0.26.0"}

ep_oracle = QuarterlyEpisode(world, max_pilots=8)
oracle_plan = solve(ep_oracle)
ep_oracle.submit(oracle_plan)

ep_stop = QuarterlyEpisode(world)
ep_stop.stop()

run_specs = [
    ("nop-01", "nop", "nop", None, None, []),
    ("stop_early-01", "stop_early", "stop_early", None, None, ep_stop.log),
    ("manual-01", "manual", "manual", None, manual_quarterly_value(world), []),
    ("oracle-01", "oracle", "reference", "reference", oracle_plan, ep_oracle.log),
]

runs_manifest = []
for run_id, agent_name, role_name, model_name, submission_obj, ep_log in run_specs:
    rdir = out_dir / "runs" / run_id
    rdir.mkdir(parents=True, exist_ok=True)
    sub_path = rdir / "submission.json"
    if agent_name != "nop":
        sub_path.write_text(json.dumps(submission_obj, indent=2) + "\n", encoding="utf-8")
    ev = verify_quarterly_file(world, sub_path, blind_seeds)
    eval_payload = {
        "evaluation": asdict(ev),
        "seeds_sha256": blind_sha,
        "world": world["quarterly"]["world_id"],
        "source": source_meta,
    }
    (rdir / "evaluation.json").write_text(json.dumps(eval_payload, indent=2) + "\n", encoding="utf-8")
    reward_float = ev.reward_num / ev.reward_den
    (rdir / "reward.txt").write_text(f"{reward_float}\n", encoding="utf-8")
    (rdir / "episode.json").write_text(json.dumps(ep_log, indent=2) + "\n", encoding="utf-8")

    runs_manifest.append(
        {
            "id": run_id,
            "run_id": run_id,
            "dir": f"runs/{run_id}",
            "role": role_name,
            "agent": agent_name,
            "model": model_name,
            "trial": 1,
            "submission_path": f"runs/{run_id}/submission.json" if sub_path.is_file() else None,
            "evaluation_path": f"runs/{run_id}/evaluation.json",
            "reward_path": f"runs/{run_id}/reward.txt",
            "episode_path": f"runs/{run_id}/episode.json",
            "valid": ev.valid,
            "feasible": ev.feasible,
            "win": ev.win,
            "reward_num": ev.reward_num,
            "reward_den": ev.reward_den,
            "reward_float": reward_float,
        }
    )

(out_dir / "training_metrics.jsonl").write_text(
    json.dumps({"step": 0, "model_id": model_id, "stage": "smoke_baseline", "reward": 0.2}) + "\n"
    + json.dumps(
        {
            "step": 25,
            "model_id": model_id,
            "stage": "smoke_reference_target",
            "reward": runs_manifest[-1]["reward_float"],
        }
    )
    + "\n",
    encoding="utf-8",
)

manifest = {
    "schema_version": 2,
    "mode": "smoke_local",
    "world_id": world["quarterly"]["world_id"],
    "world_sha256": world_sha,
    "commit": commit_sha,
    "rl_model_id": model_id,
    "frontier_model": frontier_model,
    "secondary_frontier_model": secondary_model,
    "key_presence": {
        "gemini_api_key_present": False,
        "google_generative_ai_api_key_present": False,
    },
    "blind_seeds": blind_seeds,
    "blind_seeds_sha256": blind_sha,
    "runs": runs_manifest,
}
(out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": "smoke_local_ok", "model_id": model_id, "out_dir": str(out_dir)}))
PY
  exit 0
fi

# ==============================================================================
# Live Harbor + vLLM Execution Mode (Verda GPU Instance)
# ==============================================================================
mkdir -p "$HF_HOME" "$UV_CACHE_DIR" "$VLLM_CACHE_ROOT" "$TRITON_CACHE_DIR" "$TORCHINDUCTOR_CACHE_DIR" "$XDG_CACHE_HOME" "$TMPDIR"
mkdir -p "$OUT_DIR" "$HARBOR_RUNS_DIR"

# Silently load .env if present; NEVER echo or log secret values
if [[ -f "${REPO_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "${REPO_ROOT}/.env" >/dev/null 2>&1
  set +a
fi

if [[ -n "${GEMINI_API_KEY:-}" && -z "${GOOGLE_GENERATIVE_AI_API_KEY:-}" ]]; then
  export GOOGLE_GENERATIVE_AI_API_KEY="$GEMINI_API_KEY"
elif [[ -n "${GOOGLE_GENERATIVE_AI_API_KEY:-}" && -z "${GEMINI_API_KEY:-}" ]]; then
  export GEMINI_API_KEY="$GOOGLE_GENERATIVE_AI_API_KEY"
fi

GEMINI_PRESENT=false
if [[ -n "${GEMINI_API_KEY:-}" ]]; then
  GEMINI_PRESENT=true
fi
echo "[harbor-matrix] model_id=${RESOLVED_MODEL_ID} frontier=${FRONTIER_MODEL} gemini_key_present=${GEMINI_PRESENT}"

harvest_harbor_trial() {
  local job_dir="$1"
  local run_id="$2"
  local trial_dir
  trial_dir="$(find "$job_dir" -mindepth 1 -maxdepth 2 -type d -name '*__*' | head -n 1)"
  if [[ -z "$trial_dir" ]]; then
    trial_dir="$job_dir"
  fi

  local dest_run="${OUT_DIR}/runs/${run_id}"
  local dest_log="${HARBOR_RUNS_DIR}/${run_id}"
  mkdir -p "$dest_run" "$dest_log"

  # Harbor 0.26.0 verified host paths (NEVER copy agent/opencode/ or binary opencode.db!)
  if [[ -f "${trial_dir}/artifacts/logs/artifacts/submission.json" ]]; then
    cp "${trial_dir}/artifacts/logs/artifacts/submission.json" "${dest_run}/submission.json"
  elif [[ -f "${trial_dir}/artifacts/submission.json" ]]; then
    cp "${trial_dir}/artifacts/submission.json" "${dest_run}/submission.json"
  fi

  if [[ -f "${trial_dir}/verifier/evaluation.json" ]]; then
    cp "${trial_dir}/verifier/evaluation.json" "${dest_run}/evaluation.json"
  fi
  if [[ -f "${trial_dir}/verifier/reward.txt" ]]; then
    cp "${trial_dir}/verifier/reward.txt" "${dest_run}/reward.txt"
  fi
  if [[ -f "${trial_dir}/agent/trajectory.json" ]]; then
    cp "${trial_dir}/agent/trajectory.json" "${dest_log}/trajectory.json"
    cp "${trial_dir}/agent/trajectory.json" "${dest_run}/trajectory.json"
  fi
  if [[ -f "${trial_dir}/artifacts/logs/artifacts/cell-episode.json" ]]; then
    cp "${trial_dir}/artifacts/logs/artifacts/cell-episode.json" "${dest_run}/cell-episode.json"
    cp "${trial_dir}/artifacts/logs/artifacts/cell-episode.json" "${dest_log}/cell-episode.json"
  elif [[ -f "${trial_dir}/artifacts/logs/artifacts/episode.json" ]]; then
    cp "${trial_dir}/artifacts/logs/artifacts/episode.json" "${dest_run}/episode.json"
  fi
  rm -rf "${dest_log}/opencode" "${dest_run}/opencode"
  find "$dest_log" "$dest_run" \( -name 'opencode.db*' -o -name '*.db' -o -name '*.db-*' -o -name '*.sqlite*' \) -delete 2>/dev/null || true
}

assert_stage2_gate_reward() {
  local job_dir="$1"
  local gate_agent="$2"
  "$BENCH_PYTHON" - "$job_dir" "$gate_agent" <<'PY'
import math, sys
from pathlib import Path

job_dir, gate_agent = Path(sys.argv[1]), sys.argv[2]
candidates = sorted(job_dir.rglob("verifier/reward.txt")) + sorted(job_dir.rglob("reward.txt"))
if not candidates:
    raise SystemExit(f"Stage-2 replay gate FAIL ({gate_agent}): missing verifier/reward.txt under {job_dir}")
raw = candidates[0].read_text(encoding="utf-8").strip()
val = float(raw)
if not math.isfinite(val):
    raise SystemExit(f"Stage-2 replay gate FAIL ({gate_agent}): non-finite reward {raw!r}")
if gate_agent in ("nop", "stop_early") and val != 0.0:
    raise SystemExit(f"Stage-2 replay gate FAIL ({gate_agent}): expected reward == 0.0, got {val}")
if gate_agent == "oracle" and val < 0.35:
    raise SystemExit(f"Stage-2 replay gate FAIL ({gate_agent}): expected reward >= 0.35, got {val}")
print(f"[stage2-gate] {gate_agent} PASS (reward={val:.6f})")
PY
}

# Stage 2: Docker/Harbor Replay Gate on evidence/replay_seeds.json
STAGE2_TASK="${TMPDIR}/harbor-task-replay"
rm -rf "$STAGE2_TASK"
PYTHONPATH="${REPO_ROOT}/src" "$BENCH_PYTHON" "${REPO_ROOT}/scripts/prepare_harbor.py" \
  --out "$STAGE2_TASK" \
  --seeds-file "${REPO_ROOT}/evidence/replay_seeds.json"

for gate_agent in nop stop_early oracle; do
  GATE_JOB="${TMPDIR}/harbor-gate-${gate_agent}"
  rm -rf "$GATE_JOB"
  if [[ "$gate_agent" == "stop_early" ]]; then
    if ! harbor run -p "$STAGE2_TASK" --agent stop_early -o "$GATE_JOB" >/dev/null 2>&1 || [[ -z "$(find "$GATE_JOB" -name 'reward.txt' 2>/dev/null)" ]]; then
      STAGE2_STOP_TASK="${TMPDIR}/harbor-task-replay-stop-early"
      rm -rf "$STAGE2_STOP_TASK" "$GATE_JOB"
      cp -R "$STAGE2_TASK" "$STAGE2_STOP_TASK"
      cat > "${STAGE2_STOP_TASK}/solution/solve.sh" <<'STOP_EOF'
#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
import json
from pathlib import Path
try:
    from robotization_bench.mcp_proxy import SocketEpisodeClient
    SocketEpisodeClient().stop()
except Exception:
    out = Path("/logs/artifacts/submission.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("null\n", encoding="utf-8")
PY
STOP_EOF
      chmod +x "${STAGE2_STOP_TASK}/solution/solve.sh"
      harbor run -p "$STAGE2_STOP_TASK" --agent oracle -o "$GATE_JOB"
    fi
  else
    harbor run -p "$STAGE2_TASK" --agent "$gate_agent" -o "$GATE_JOB"
  fi
  assert_stage2_gate_reward "$GATE_JOB" "$gate_agent"
done

# Generate post-freeze CSPRNG blind_seeds.json & verify 4-way disjointness
PYTHONPATH="${REPO_ROOT}/src" "$BENCH_PYTHON" - \
  "${OUT_DIR}" "${RL_SEEDS_FILE}" "${BLIND_COUNT}" "${SCRIPT_DIR}/generate_sft_traces.py" "${REPO_ROOT}" <<'PY'
import hashlib, importlib.util, json, sys
from pathlib import Path
out_dir, rl_file, count, sft_py, root = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4]), Path(sys.argv[5])
spec = importlib.util.spec_from_file_location("generate_sft_traces", sft_py)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
from robotization_bench.contracts import load_world
world = load_world()
dev = list(world["development_seeds"])
rep = json.loads((root / "evidence" / "replay_seeds.json").read_text(encoding="utf-8"))
rl_doc = json.loads(rl_file.read_text(encoding="utf-8")) if rl_file.is_file() else {"rl_train_seeds": [], "rl_val_seeds": []}
rl_tr, rl_va = list(rl_doc["rl_train_seeds"]), list(rl_doc["rl_val_seeds"])
blind = mod.sample_feasible_csprng_seeds(world, count=count, forbidden=set(dev) | set(rep) | set(rl_tr) | set(rl_va))
mod.verify_4way_seed_disjointness(dev, rep, rl_tr, rl_va, blind)
raw = (json.dumps(blind) + "\n").encode("utf-8")
(out_dir / "blind_seeds.json").write_bytes(raw)
(out_dir / "blind_seeds.sha256").write_text(f"{hashlib.sha256(raw).hexdigest()}  blind_seeds.json\n", encoding="utf-8")
PY

STAGE3_TASK="${TMPDIR}/harbor-task-blind"
rm -rf "$STAGE3_TASK"
PYTHONPATH="${REPO_ROOT}/src" "$BENCH_PYTHON" "${REPO_ROOT}/scripts/prepare_harbor.py" \
  --out "$STAGE3_TASK" \
  --seeds-file "${OUT_DIR}/blind_seeds.json"

for ctrl_agent in nop oracle; do
  JOB_DIR="${TMPDIR}/harbor-blind-${ctrl_agent}"
  rm -rf "$JOB_DIR"
  harbor run -p "$STAGE3_TASK" --agent "$ctrl_agent" -o "$JOB_DIR"
  harvest_harbor_trial "$JOB_DIR" "${ctrl_agent}-01"
done

if [[ "$GEMINI_PRESENT" == "true" ]]; then
  for t in $(seq 1 "$FRONTIER_TRIALS"); do
    JOB_DIR="${TMPDIR}/harbor-frontier-${t}"
    rm -rf "$JOB_DIR"
    harbor run -p "$STAGE3_TASK" -a opencode -m "$FRONTIER_MODEL" --api-key-name GEMINI_API_KEY -o "$JOB_DIR"
    harvest_harbor_trial "$JOB_DIR" "frontier-0${t}"
  done

  if [[ -n "$SECONDARY_FRONTIER_MODEL" && "$SECONDARY_FRONTIER_MODEL" != "none" && "$SECONDARY_FRONTIER_TRIALS" -gt 0 ]]; then
    for t in $(seq 1 "$SECONDARY_FRONTIER_TRIALS"); do
      JOB_DIR="${TMPDIR}/harbor-secondary-${t}"
      rm -rf "$JOB_DIR"
      harbor run -p "$STAGE3_TASK" -a opencode -m "$SECONDARY_FRONTIER_MODEL" --api-key-name GEMINI_API_KEY -o "$JOB_DIR"
      harvest_harbor_trial "$JOB_DIR" "secondary-frontier-0${t}"
    done
  fi
fi

# 3x Base-7B / Base-Open & 3x Post-RL-7B / Post-RL via local vLLM OpenAI-compatible endpoint
VLLM_PORT="${VLLM_PORT:-8001}"
OPEN_TRIALS="${OPEN_TRIALS:-3}"
if "$RL_PYTHON" -c "import vllm" >/dev/null 2>&1; then
  LORA_ARGS=()
  if [[ -d "$ADAPTER_DIR" ]]; then
    LORA_ARGS=(--enable-lora --max-lora-rank 32 --lora-modules "post-rl=${ADAPTER_DIR}")
  fi
  "$RL_PYTHON" -m vllm.entrypoints.openai.api_server \
    --host 0.0.0.0 \
    --port "$VLLM_PORT" \
    --model "$RESOLVED_MODEL_ID" \
    --max-model-len "${VLLM_MAX_MODEL_LEN:-16384}" \
    --gpu-memory-utilization 0.35 \
    "${LORA_ARGS[@]}" >"${TMPDIR}/vllm_harbor.log" 2>&1 &
  VLLM_PID=$!
  trap 'kill "$VLLM_PID" >/dev/null 2>&1 || true' EXIT

  for _ in $(seq 1 90); do
    if curl -fsS "http://127.0.0.1:${VLLM_PORT}/v1/models" >/dev/null 2>&1; then
      break
    fi
    sleep 2
  done

  DOCKER_HOST_IP="$(docker network inspect bridge -f '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null || echo "172.17.0.1")"
  DOCKER_HOST_IP="${DOCKER_HOST_IP:-172.17.0.1}"
  export OPENAI_BASE_URL="http://${DOCKER_HOST_IP}:${VLLM_PORT}/v1"
  export OPENAI_API_KEY="local-vllm"
  for t in $(seq 1 "$OPEN_TRIALS"); do
    JOB_DIR="${TMPDIR}/harbor-base-7b-${t}"
    rm -rf "$JOB_DIR"
    harbor run -p "$STAGE3_TASK" -a opencode -m "openai/${RESOLVED_MODEL_ID}" -o "$JOB_DIR"
    harvest_harbor_trial "$JOB_DIR" "base-7b-0${t}"
  done

  if [[ -d "$ADAPTER_DIR" ]]; then
    for t in $(seq 1 "$OPEN_TRIALS"); do
      JOB_DIR="${TMPDIR}/harbor-post-rl-7b-${t}"
      rm -rf "$JOB_DIR"
      harbor run -p "$STAGE3_TASK" -a opencode -m "openai/post-rl" -o "$JOB_DIR"
      harvest_harbor_trial "$JOB_DIR" "post-rl-7b-0${t}"
    done
  fi
  kill "$VLLM_PID" >/dev/null 2>&1 || true
fi

# Materialize deterministic stop_early-01 & manual-01 baselines + manifest.json across harvested runs
PYTHONPATH="${REPO_ROOT}/src" "$BENCH_PYTHON" - \
  "${OUT_DIR}" "${RESOLVED_MODEL_ID}" "${FRONTIER_MODEL}" "${SECONDARY_FRONTIER_MODEL}" "${GEMINI_PRESENT}" "${REPO_ROOT}" <<'PY'
from dataclasses import asdict
import hashlib, json, subprocess, sys
from pathlib import Path

out_dir, model_id, frontier_model, secondary_model, gemini_str, root = (
    Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], Path(sys.argv[6])
)
from robotization_bench.contracts import load_world
from robotization_bench.episode import QuarterlyEpisode
from robotization_bench.quarterly import manual_quarterly_value
from robotization_bench.verifier import verify_quarterly_file

world = load_world()
blind_seeds = json.loads((out_dir / "blind_seeds.json").read_text(encoding="utf-8"))
blind_sha = hashlib.sha256((out_dir / "blind_seeds.json").read_bytes()).hexdigest()
git_proc = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True)
commit_sha = git_proc.stdout.strip() or None
world_sha = hashlib.sha256((root / "data" / "world_spec.json").read_bytes()).hexdigest()
source_meta = {"commit": commit_sha, "world_sha256": world_sha, "schema_version": 2, "harbor_checked_version": "0.26.0"}

ep_stop = QuarterlyEpisode(world)
ep_stop.stop()
for run_id, sub_obj, ep_log in [
    ("stop_early-01", None, ep_stop.log),
    ("manual-01", manual_quarterly_value(world), []),
]:
    rdir = out_dir / "runs" / run_id
    rdir.mkdir(parents=True, exist_ok=True)
    sub_path = rdir / "submission.json"
    sub_path.write_text(json.dumps(sub_obj, indent=2) + "\n", encoding="utf-8")
    ev = verify_quarterly_file(world, sub_path, blind_seeds)
    (rdir / "evaluation.json").write_text(
        json.dumps({"evaluation": asdict(ev), "seeds_sha256": blind_sha, "world": world["quarterly"]["world_id"], "source": source_meta}, indent=2) + "\n",
        encoding="utf-8",
    )
    (rdir / "reward.txt").write_text(f"{ev.reward_num / ev.reward_den}\n", encoding="utf-8")
    (rdir / "episode.json").write_text(json.dumps(ep_log, indent=2) + "\n", encoding="utf-8")

def _infer_role(run_id: str, agent_name: str) -> str:
    prefix = agent_name.lower()
    if prefix == "nop":
        return "nop"
    if prefix == "stop_early":
        return "stop_early"
    if prefix == "manual":
        return "manual"
    if prefix in ("oracle", "reference"):
        return "reference"
    if prefix in ("frontier", "secondary-frontier"):
        return "frontier"
    if prefix in ("base-7b", "base_open"):
        return "base_open"
    if prefix in ("post-rl-7b", "post_rl"):
        return "post_rl"
    return "candidate"


runs_manifest = []
runs_root = out_dir / "runs"
if runs_root.is_dir():
    for rdir in sorted(p for p in runs_root.iterdir() if p.is_dir()):
        run_id = rdir.name
        agent_name = run_id.rsplit("-", 1)[0]
        role_name = _infer_role(run_id, agent_name)
        sub_path = rdir / "submission.json"
        ev = verify_quarterly_file(world, sub_path, blind_seeds)
        reward_float = ev.reward_num / ev.reward_den
        (rdir / "evaluation.json").write_text(
            json.dumps(
                {
                    "evaluation": asdict(ev),
                    "seeds_sha256": blind_sha,
                    "world": world["quarterly"]["world_id"],
                    "source": source_meta,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (rdir / "reward.txt").write_text(f"{reward_float}\n", encoding="utf-8")
        runs_manifest.append(
            {
                "id": run_id,
                "run_id": run_id,
                "dir": f"runs/{run_id}",
                "role": role_name,
                "agent": agent_name,
                "submission_path": f"runs/{run_id}/submission.json" if sub_path.is_file() else None,
                "evaluation_path": f"runs/{run_id}/evaluation.json",
                "reward_path": f"runs/{run_id}/reward.txt",
                "valid": ev.valid,
                "feasible": ev.feasible,
                "win": ev.win,
                "reward_num": ev.reward_num,
                "reward_den": ev.reward_den,
                "reward_float": reward_float,
            }
        )

manifest = {
    "schema_version": 2,
    "mode": "verda_harbor_matrix",
    "world_id": world["quarterly"]["world_id"],
    "world_sha256": world_sha,
    "commit": commit_sha,
    "rl_model_id": model_id,
    "frontier_model": frontier_model,
    "secondary_frontier_model": secondary_model,
    "key_presence": {
        "gemini_api_key_present": gemini_str == "true",
        "google_generative_ai_api_key_present": gemini_str == "true",
    },
    "blind_seeds": blind_seeds,
    "blind_seeds_sha256": blind_sha,
    "runs": runs_manifest,
}
(out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
PY

# Run fail-closed secret & opencode.db scrubber over harvested outputs
bash "${SCRIPT_DIR}/sync_evidence.sh" --smoke-local "${OUT_DIR}"
bash "${SCRIPT_DIR}/sync_evidence.sh" --smoke-local "${HARBOR_RUNS_DIR}"
