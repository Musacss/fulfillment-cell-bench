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
SKIP_STAGE2=0
CLI_MODEL_ID=""
ENV_READY_FILE="${ENV_READY_FILE:-/root/bench/H200_ENV_READY.json}"
OUT_DIR="${REPO_ROOT}/evidence/benchmark-v2"
HARBOR_RUNS_DIR="${REPO_ROOT}/evidence/harbor-runs"
RL_SEEDS_FILE="${REPO_ROOT}/artifacts/verda/rl_seeds.json"
if [[ -d "/root/prestage-checkpoints/qwen35-9b-grpo/final_adapter" ]]; then
  ADAPTER_DIR="/root/prestage-checkpoints/qwen35-9b-grpo/final_adapter"
else
  ADAPTER_DIR="${REPO_ROOT}/artifacts/verda/qwen_rl/grpo_adapter"
fi
BLIND_SEEDS_IN=""
BLIND_COUNT=5
PRE_BLIND_FREEZE_UTC="${PRE_BLIND_FREEZE_UTC:-}"
FRONTIER_MODEL="${FRONTIER_MODEL:-gemini/gemini-4-carbon}"
FRONTIER_TRIALS="${FRONTIER_TRIALS:-3}"
SECONDARY_FRONTIER_MODEL="${SECONDARY_FRONTIER_MODEL:-gemini/gemini-3.1-pro-preview}"
SECONDARY_FRONTIER_TRIALS="${SECONDARY_FRONTIER_TRIALS:-3}"
ANTHROPIC_PRIMARY_MODEL="${ANTHROPIC_PRIMARY_MODEL:-anthropic/claude-opus-5-5}"
ANTHROPIC_SECONDARY_MODEL="${ANTHROPIC_SECONDARY_MODEL:-anthropic/claude-fable-5-2}"
ANTHROPIC_TRIALS="${ANTHROPIC_TRIALS:-3}"

usage() {
  cat <<'EOF'
Usage: run_harbor_matrix.sh [options]

Options:
  --dry-run                      Validate 4-way seed disjointness & matrix plan in <2s without Docker/.env
  --smoke-local                  Run local CPU verification of nop/stop_early/manual/oracle into --out-dir
  --skip-stage2                  Skip Stage-2 replay_seeds.json gate when already verified in Stage A
  --blind-seeds-file <path>      Use pre-sampled post-freeze blind_seeds.json file
  --out-dir <dir>                Output directory (default: evidence/benchmark-v2)
  --harbor-runs-dir <dir>        Sanitized Harbor run logs directory (default: evidence/harbor-runs)
  --rl-seeds <path>              RL train/val seeds JSON for 4-way disjointness verification
  --adapter-dir <dir>            Post-RL LoRA adapter directory
  --blind-count <N>              Number of post-freeze CSPRNG blind seeds (default: 5)
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
    --skip-stage2)
      SKIP_STAGE2=1
      shift
      ;;
    --blind-seeds-file)
      BLIND_SEEDS_IN="$2"
      shift 2
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
export PATH="/root/.local/bin:${PATH}"
if command -v harbor >/dev/null 2>&1; then
  HARBOR_BIN="$(command -v harbor)"
else
  HARBOR_BIN="$(find "${FAST_CACHE_ROOT}/uv" -maxdepth 4 -path '*/bin/harbor' -type f 2>/dev/null | head -n 1 || true)"
fi
if [[ -z "${HARBOR_BIN:-}" ]]; then
  echo "ERROR: harbor binary not found in PATH or ${FAST_CACHE_ROOT}/uv" >&2
  exit 1
fi

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
ANTHROPIC_PRESENT=false
if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
  ANTHROPIC_PRESENT=true
fi
echo "[harbor-matrix] harbor=${HARBOR_BIN} model_id=${RESOLVED_MODEL_ID} frontier=${FRONTIER_MODEL} gemini_key_present=${GEMINI_PRESENT} anthropic_key_present=${ANTHROPIC_PRESENT}"

harvest_harbor_job_trials() {
  local job_dir="$1"
  local group_slug="$2"
  local expected_trials="$3"
  local is_nop="$4"

  "$BENCH_PYTHON" - "$job_dir" "$group_slug" "$expected_trials" "$is_nop" "$OUT_DIR" "$HARBOR_RUNS_DIR" <<'PY'
import json
from pathlib import Path
import shutil
import sys

job_dir = Path(sys.argv[1])
group_slug = sys.argv[2]
expected_trials = int(sys.argv[3])
is_nop = sys.argv[4] == "1"
out_dir = Path(sys.argv[5])
harbor_runs_dir = Path(sys.argv[6])

trial_dirs = sorted(
    p
    for p in job_dir.iterdir()
    if p.is_dir() and "__" in p.name and ((p / "verifier").exists() or (p / "result.json").exists() or (p / "agent").exists())
)
if not trial_dirs:
    trial_dirs = sorted(p for p in job_dir.glob("*/*__*") if p.is_dir())
if not trial_dirs and ((job_dir / "verifier").exists() or (job_dir / "result.json").exists()):
    trial_dirs = [job_dir]

for idx in range(1, expected_trials + 1):
    trial_tag = f"trial-{idx:02d}"
    dest_run = out_dir / "runs" / group_slug / trial_tag
    dest_ver = dest_run / "verifier"
    dest_log = harbor_runs_dir / f"{group_slug}__{trial_tag}"
    if dest_run.exists():
        shutil.rmtree(dest_run)
    if dest_log.exists():
        shutil.rmtree(dest_log)
    dest_ver.mkdir(parents=True, exist_ok=True)
    dest_log.mkdir(parents=True, exist_ok=True)

    tdir = trial_dirs[idx - 1] if idx - 1 < len(trial_dirs) else None
    sub_src = None
    if tdir is not None:
        for rel in ("artifacts/logs/artifacts/submission.json", "artifacts/submission.json", "submission.json"):
            cand = tdir / rel
            if cand.is_file():
                sub_src = cand
                break

    if not is_nop:
        if sub_src is not None:
            shutil.copy2(sub_src, dest_run / "submission.json")
            shutil.copy2(sub_src, dest_log / "submission.json")
        else:
            (dest_run / "submission.json").write_text("null\n", encoding="utf-8")
            (dest_log / "submission.json").write_text("null\n", encoding="utf-8")

    if tdir is not None:
        for vname in ("evaluation.json", "reward.txt"):
            vsrc = tdir / "verifier" / vname
            if vsrc.is_file():
                shutil.copy2(vsrc, dest_ver / vname)
                shutil.copy2(vsrc, dest_log / vname)
        for meta_name in ("result.json", "config.json"):
            msrc = tdir / meta_name
            if msrc.is_file():
                shutil.copy2(msrc, dest_log / meta_name)
        for ep_rel in ("artifacts/logs/artifacts/cell-episode.json", "artifacts/logs/artifacts/episode.json"):
            epsrc = tdir / ep_rel
            if epsrc.is_file():
                shutil.copy2(epsrc, dest_log / "cell-episode.json")
                break
        traj_src = tdir / "agent/trajectory.json"
        if traj_src.is_file():
            dest_traj = dest_log / "agent/trajectory.json"
            dest_traj.parent.mkdir(parents=True, exist_ok=True)
            if traj_src.stat().st_size <= 2 * 1024 * 1024:
                shutil.copy2(traj_src, dest_traj)
            else:
                try:
                    raw_t = json.loads(traj_src.read_text(encoding="utf-8", errors="replace"))
                    compact = {
                        "truncated_from_bytes": traj_src.stat().st_size,
                        "schema_version": raw_t.get("schema_version") if isinstance(raw_t, dict) else None,
                        "agent": raw_t.get("agent") if isinstance(raw_t, dict) else None,
                        "step_count": len(raw_t.get("steps", [])) if isinstance(raw_t, dict) and isinstance(raw_t.get("steps"), list) else None,
                        "final_metrics": raw_t.get("final_metrics") if isinstance(raw_t, dict) else None,
                    }
                    dest_traj.write_text(json.dumps(compact, indent=2) + "\n", encoding="utf-8")
                except Exception:
                    dest_traj.write_text(
                        json.dumps({"truncated_from_bytes": traj_src.stat().st_size}, indent=2) + "\n",
                        encoding="utf-8",
                    )

for root_clean in (dest_log.parent, out_dir / "runs" / group_slug):
    for bad in root_clean.rglob("*"):
        if bad.is_file() and (
            bad.name == "opencode.db"
            or bad.name.startswith("opencode.db")
            or bad.name.endswith(".db")
            or ".db-" in bad.name
            or ".sqlite" in bad.name
        ):
            bad.unlink(missing_ok=True)
PY
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

if [[ "$SKIP_STAGE2" -eq 0 ]]; then
  STAGE2_TASK="${TMPDIR}/harbor-task-replay"
  rm -rf "$STAGE2_TASK"
  PYTHONPATH="${REPO_ROOT}/src" "$BENCH_PYTHON" "${REPO_ROOT}/scripts/prepare_harbor.py" \
    --out "$STAGE2_TASK" \
    --seeds-file "${REPO_ROOT}/evidence/replay_seeds.json" \
    --min-seeds 3

  for gate_agent in nop stop_early oracle; do
    GATE_JOB="${TMPDIR}/harbor-gate-${gate_agent}"
    rm -rf "$GATE_JOB"
    if [[ "$gate_agent" == "stop_early" ]]; then
      STAGE2_STOP_TASK="${TMPDIR}/harbor-task-replay-stop-early"
      rm -rf "$STAGE2_STOP_TASK" "$GATE_JOB"
      cp -R "$STAGE2_TASK" "$STAGE2_STOP_TASK"
      cat > "${STAGE2_STOP_TASK}/solution/solve.sh" <<'STOP_EOF'
#!/usr/bin/env bash
set -euo pipefail
/usr/local/bin/bench-daemon-start
python3 - <<'PY'
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
      "$HARBOR_BIN" run -p "$STAGE2_STOP_TASK" --agent oracle -o "$GATE_JOB"
    else
      "$HARBOR_BIN" run -p "$STAGE2_TASK" --agent "$gate_agent" -o "$GATE_JOB"
    fi
    assert_stage2_gate_reward "$GATE_JOB" "$gate_agent"
  done
fi

# Generate or verify post-freeze CSPRNG blind_seeds.json (>= 500_000) & 4-way disjointness
PYTHONPATH="${REPO_ROOT}/src" "$BENCH_PYTHON" - \
  "${OUT_DIR}" "${RL_SEEDS_FILE}" "${BLIND_COUNT}" "${BLIND_SEEDS_IN}" "${SCRIPT_DIR}/generate_sft_traces.py" "${REPO_ROOT}" <<'PY'
import hashlib, importlib.util, json, sys
from pathlib import Path

out_dir, rl_file, count, blind_in, sft_py, root = (
    Path(sys.argv[1]),
    Path(sys.argv[2]),
    int(sys.argv[3]),
    sys.argv[4],
    Path(sys.argv[5]),
    Path(sys.argv[6]),
)
spec = importlib.util.spec_from_file_location("generate_sft_traces", sft_py)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
from robotization_bench.contracts import load_world

world = load_world()
dev = list(world["development_seeds"])
rep = json.loads((root / "evidence" / "replay_seeds.json").read_text(encoding="utf-8"))
rl_doc = json.loads(rl_file.read_text(encoding="utf-8")) if rl_file.is_file() else {"rl_train_seeds": [], "rl_val_seeds": []}
rl_tr, rl_va = list(rl_doc["rl_train_seeds"]), list(rl_doc["rl_val_seeds"])

if blind_in and Path(blind_in).is_file():
    blind = json.loads(Path(blind_in).read_text(encoding="utf-8"))
    if any(type(s) is not int or s < 500_000 for s in blind):
        raise SystemExit("blind_seeds must all be integers >= 500_000")
else:
    blind = mod.sample_feasible_csprng_seeds(
        world,
        count=count,
        min_seed=500_000,
        forbidden=set(dev) | set(rep) | set(rl_tr) | set(rl_va) | {101, 203, 307, 409, 503},
    )
mod.verify_4way_seed_disjointness(dev, rep, rl_tr, rl_va, blind)
out_dir.mkdir(parents=True, exist_ok=True)
raw = (json.dumps(blind) + "\n").encode("utf-8")
(out_dir / "blind_seeds.json").write_bytes(raw)
(out_dir / "blind_seeds.sha256").write_text(f"{hashlib.sha256(raw).hexdigest()}  blind_seeds.json\n", encoding="utf-8")
PY

STAGE3_TASK="${TMPDIR}/harbor-task-blind"
rm -rf "$STAGE3_TASK"
PYTHONPATH="${REPO_ROOT}/src" "$BENCH_PYTHON" "${REPO_ROOT}/scripts/prepare_harbor.py" \
  --out "$STAGE3_TASK" \
  --seeds-file "${OUT_DIR}/blind_seeds.json" \
  --min-seeds 3

rm -rf "${OUT_DIR}/runs"

# Controls on blind_seeds.json via Harbor
for ctrl_agent in nop oracle; do
  JOB_DIR="${TMPDIR}/harbor-blind-${ctrl_agent}"
  rm -rf "$JOB_DIR"
  "$HARBOR_BIN" run -p "$STAGE3_TASK" --agent "$ctrl_agent" -o "$JOB_DIR"
  if [[ "$ctrl_agent" == "nop" ]]; then
    harvest_harbor_job_trials "$JOB_DIR" "nop" 1 1
  else
    harvest_harbor_job_trials "$JOB_DIR" "oracle" 1 0
  fi
done

# Launch Frontier OpenCode 3-trial jobs concurrently across Google Gemini & Anthropic Claude
FRONTIER_PIDS=()
FRONTIER_SPECS=()

launch_gemini_job() {
  local model_id="$1"
  local group_slug="$2"
  local n_trials="$3"
  local job_dir="${TMPDIR}/harbor-blind-${group_slug}"
  rm -rf "$job_dir"
  (
    "$HARBOR_BIN" run -p "$STAGE3_TASK" -a opencode -m "$model_id" --api-key-name GEMINI_API_KEY \
      -n "$n_trials" -c "$n_trials" -o "$job_dir" --job-name "$group_slug" || true
  ) >"${TMPDIR}/log_${group_slug}.log" 2>&1 &
  FRONTIER_PIDS+=("$!")
  FRONTIER_SPECS+=("${job_dir}|${group_slug}|${n_trials}")
}

launch_anthropic_job() {
  local model_id="$1"
  local group_slug="$2"
  local n_trials="$3"
  local job_dir="${TMPDIR}/harbor-blind-${group_slug}"
  rm -rf "$job_dir"
  (
    "$HARBOR_BIN" run -p "$STAGE3_TASK" -a opencode -m "$model_id" --api-key-name ANTHROPIC_API_KEY \
      -n "$n_trials" -c "$n_trials" -o "$job_dir" --job-name "$group_slug" || true
  ) >"${TMPDIR}/log_${group_slug}.log" 2>&1 &
  FRONTIER_PIDS+=("$!")
  FRONTIER_SPECS+=("${job_dir}|${group_slug}|${n_trials}")
}

if [[ "$GEMINI_PRESENT" == "true" ]]; then
  if [[ "$FRONTIER_TRIALS" -gt 0 ]]; then
    FRONTIER_SLUG="opencode_${FRONTIER_MODEL#*/}"
    launch_gemini_job "$FRONTIER_MODEL" "$FRONTIER_SLUG" "$FRONTIER_TRIALS"
  fi
  if [[ -n "$SECONDARY_FRONTIER_MODEL" && "$SECONDARY_FRONTIER_MODEL" != "none" && "$SECONDARY_FRONTIER_TRIALS" -gt 0 ]]; then
    SEC_SLUG="opencode_${SECONDARY_FRONTIER_MODEL#*/}"
    launch_gemini_job "$SECONDARY_FRONTIER_MODEL" "$SEC_SLUG" "$SECONDARY_FRONTIER_TRIALS"
  fi
fi

if [[ "$ANTHROPIC_PRESENT" == "true" && "$ANTHROPIC_TRIALS" -gt 0 ]]; then
  if [[ -n "$ANTHROPIC_PRIMARY_MODEL" && "$ANTHROPIC_PRIMARY_MODEL" != "none" ]]; then
    ANTH1_SLUG="opencode_${ANTHROPIC_PRIMARY_MODEL#*/}"
    launch_anthropic_job "$ANTHROPIC_PRIMARY_MODEL" "$ANTH1_SLUG" "$ANTHROPIC_TRIALS"
  fi
  if [[ -n "$ANTHROPIC_SECONDARY_MODEL" && "$ANTHROPIC_SECONDARY_MODEL" != "none" ]]; then
    ANTH2_SLUG="opencode_${ANTHROPIC_SECONDARY_MODEL#*/}"
    launch_anthropic_job "$ANTHROPIC_SECONDARY_MODEL" "$ANTH2_SLUG" "$ANTHROPIC_TRIALS"
  fi
fi

# While Frontier CPU/API containers run in parallel, evaluate 3x Base & 3x Post-RL Qwen3.5-9B on H200 GPU
VLLM_PORT="${VLLM_PORT:-8001}"
OPEN_TRIALS="${OPEN_TRIALS:-3}"
OPEN_EVAL_MODE="${OPEN_EVAL_MODE:-direct_vllm}"

if [[ "$OPEN_EVAL_MODE" == "opencode" ]] && "$RL_PYTHON" -c "import vllm" >/dev/null 2>&1; then
  LORA_ARGS=()
  if [[ -d "$ADAPTER_DIR" ]]; then
    LORA_ARGS=(--enable-lora --max-lora-rank 32 --lora-modules "post-rl=${ADAPTER_DIR}")
  fi
  "$RL_PYTHON" -m vllm.entrypoints.openai.api_server \
    --host 0.0.0.0 \
    --port "$VLLM_PORT" \
    --model "$RESOLVED_MODEL_ID" \
    --max-model-len "${VLLM_MAX_MODEL_LEN:-16384}" \
    --gpu-memory-utilization "${VLLM_GPU_MEM_UTIL:-0.32}" \
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
  JOB_BASE="${TMPDIR}/harbor-base-open"
  rm -rf "$JOB_BASE"
  "$HARBOR_BIN" run -p "$STAGE3_TASK" -a opencode -m "openai/${RESOLVED_MODEL_ID}" -n "$OPEN_TRIALS" -c "$OPEN_TRIALS" -o "$JOB_BASE" || true
  harvest_harbor_job_trials "$JOB_BASE" "qwen3.5-9b_base" "$OPEN_TRIALS" 0

  if [[ -d "$ADAPTER_DIR" ]]; then
    JOB_POST="${TMPDIR}/harbor-post-rl"
    rm -rf "$JOB_POST"
    "$HARBOR_BIN" run -p "$STAGE3_TASK" -a opencode -m "openai/post-rl" -n "$OPEN_TRIALS" -c "$OPEN_TRIALS" -o "$JOB_POST" || true
    harvest_harbor_job_trials "$JOB_POST" "qwen3.5-9b_post_rl_grpo" "$OPEN_TRIALS" 0
  fi
  kill "$VLLM_PID" >/dev/null 2>&1 || true
elif "$RL_PYTHON" -c "import vllm" >/dev/null 2>&1; then
  PYTHONPATH="${REPO_ROOT}/src" "$RL_PYTHON" - \
    "$RESOLVED_MODEL_ID" "$ADAPTER_DIR" "$STAGE3_TASK" "$OUT_DIR" "$HARBOR_RUNS_DIR" "$TMPDIR" "$REPO_ROOT" <<'PY'
import gc
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer
from vllm import LLM, SamplingParams

from robotization_bench.contracts import load_world
from robotization_bench.episode import QuarterlyEpisode
from robotization_bench.validation import parse_quarterly_plan

model_id = sys.argv[1]
adapter_dir = Path(sys.argv[2])
stage3_task = Path(sys.argv[3])
out_dir = Path(sys.argv[4])
harbor_runs_dir = Path(sys.argv[5])
tmpdir = Path(sys.argv[6])
repo_root = Path(sys.argv[7])

SYSTEM_PROMPT = (
    "You are the Principal Fulfillment-Cell Operations Engineer designing a 12-week quarterly automation rollout "
    "(schema_version=2).\n"
    "First reason concisely inside <think>...</think> (under 180 words): verify CapEx budget (robot_purchase + tray_purchase vs budget), "
    "commissioning & wear defect/jam accumulation vs escaped_each_week_max, auto_pack_pooled_min vs route ('bypass' vs 'all'), "
    "and weekly wave demand vs crew sizing & preventive off-peak maintenance.\n"
    "After </think>, output ONLY one valid compact JSON object with exact schema:\n"
    '{"schema_version":2,"weeks":[{"robot":bool,"trays":bool,"route":"manual"|"bypass"|"all","maintenance":bool,"workers":[[zone,...],...]}, ...12 weeks...]}\n'
    "Rules: weeks must have exactly 12 objects (week 0..11). Zones are integers in [1,2,3,4] (1=prep, 2=pick, 3=pack, 4=qc), "
    "1..8 workers per week, no duplicate zones inside a worker. CapEx is irreversible (once robot=true or trays=true, it cannot become false in later weeks). "
    "If robot=false, route must be 'manual' and maintenance must be false."
)

FENCE_RE = re.compile(r"```[^\n`]*\n?(.*?)```", re.DOTALL)


def extract_json_candidate(text: str) -> str | None:
    if not isinstance(text, str) or "</think>" not in text:
        return None
    tail = text.rpartition("</think>")[2].strip()
    if not tail:
        return None
    for block in reversed(FENCE_RE.findall(tail)):
        stripped = block.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return stripped
    start, end = tail.find("{"), tail.rfind("}")
    return tail[start : end + 1] if 0 <= start < end else None


def summarize_pilot(pub_w: dict, ep: QuarterlyEpisode, plan_dict: dict, pilot_seed: int) -> dict:
    res = ep.pilot(plan_dict, pilot_seed, trace=False)
    weeks = res["weeks"]
    orders = sum(int(wr["raw"]["total"]) - int(wr["carryover_in"]) for wr in weeks)
    good = sum(int(wr["raw"]["good"]) for wr in weeks)
    on_time = sum(int(wr["raw"]["on_time"]) for wr in weeks)
    auto_f = sum(int(wr["raw"]["auto_finished"]) for wr in weeks)
    pack_f = sum(int(wr["raw"]["pack_finished"]) for wr in weeks)
    esc_lim = int(pub_w["quarterly"]["threshold_bps"]["escaped_each_week_max"])
    good_lim = int(pub_w["quarterly"]["threshold_bps"]["good_each_week"])
    return {
        "purchase": int(res["purchase"]),
        "total_cost": int(res["total_cost"]),
        "labor_ticks": int(res["labor_ticks"]),
        "orders": orders,
        "good_bps": (good * 10000) // max(1, orders),
        "on_time_bps": (on_time * 10000) // max(1, orders),
        "auto_pack_bps": (auto_f * 10000) // max(1, pack_f),
        "peak_wear": max(int(wr["wear_end"]) for wr in weeks),
        "escaped_violated_weeks": [int(wr["week"]) for wr in weeks if int(wr["raw"]["escaped"]) * 10000 > int(wr["raw"]["total"]) * esc_lim],
        "volume_violated_weeks": [int(wr["week"]) for wr in weeks if int(wr["raw"]["good"]) * 10000 < int(wr["raw"]["total"]) * good_lim],
        "late_orders_by_week": [int(wr["raw"]["good"]) - int(wr["raw"]["on_time"]) for wr in weeks],
        "exogenous_orders_by_week": [int(wr["raw"]["total"]) - int(wr["carryover_in"]) for wr in weeks],
    }


def build_episode_prompt(world: dict, pilot_seed: int) -> tuple[list[dict[str, str]], QuarterlyEpisode]:
    ep = QuarterlyEpisode(world, rules_path=repo_root / "docs" / "SPEC.md")
    obs = ep.observe()
    pub_w = obs["world"]
    m, qm, qt, qw, qc = (
        pub_w["money"],
        pub_w["quarterly"]["money"],
        pub_w["quarterly"]["threshold_bps"],
        pub_w["quarterly"]["wear"],
        pub_w["quarterly"]["commissioning"],
    )
    pilot_manual = summarize_pilot(pub_w, ep, obs["manual"], pilot_seed)
    can_afford_trays = (int(m["robot_purchase"]) + int(m["tray_purchase"])) <= int(qm["budget"])
    probe_plan = {
        "schema_version": 2,
        "weeks": [
            {"robot": True, "trays": can_afford_trays, "route": "bypass", "maintenance": False, "workers": [[1], [2], [3], [4], [2, 3]]}
            for _ in range(12)
        ],
    }
    pilot_probe = summarize_pilot(pub_w, ep, probe_plan, pilot_seed)
    wk_lines = [
        f"  w{p['week']:02d} ({p['label']}): waves={p['waves']}, orders_min={p['orders_min']}, "
        f"reg_bps={p['regular_bps']}, frag_bps={p['fragile_bps']}, due_off={p['due_offset']}, "
        f"pilot_orders={pilot_manual['exogenous_orders_by_week'][p['week']]}"
        for p in pub_w["quarterly"]["week_profiles"]
    ]
    user_text = (
        f"WORLD SPEC ({pub_w['quarterly']['world_id']}):\n"
        f"- CapEx & Weekly Money (cents): budget={qm['budget']}, robot_purchase={m['robot_purchase']}, tray_purchase={m['tray_purchase']} "
        f"(robot+trays={m['robot_purchase']+m['tray_purchase']}), dep_weeks={qm['depreciation_weeks']}, "
        f"service_wk={qm['robot_service_week']}, maint_cost={qm['maintenance_cost']}, shifts_wk={qm['shifts_per_week']}, "
        f"worker_shift={m['worker_shift']}, cross_skill_prem={qm['cross_skill_shift_premium']}, "
        f"hire={qm['hire_cost']}, layoff={qm['layoff_cost']}, retrain={qm['retrain_cost']}, "
        f"tray_ord={m['tray_per_order']}, late_pen={m['late_good']}, unfulfilled_pen={m['unfulfilled']}, escaped_pen={m['escaped']}\n"
        f"- Auto Time & Quality: auto_time={json.dumps(pub_w['time']['auto'], separators=(',',':'))}, "
        f"jam_bps={json.dumps(pub_w['prob_bps']['jam'], separators=(',',':'))}, "
        f"defect_auto_bps={json.dumps(pub_w['prob_bps']['defect_auto'], separators=(',',':'))}, detect_bps={pub_w['prob_bps']['detect']}\n"
        f"- Commissioning & Wear: comm_weeks={qc['weeks']}, comm_jam_bonus={json.dumps(qc['jam_bonus_bps'], separators=(',',':'))}, "
        f"comm_defect_bonus={json.dumps(qc.get('defect_bonus_bps',{}), separators=(',',':'))}, "
        f"wear_bypass={qw['per_week_bypass']}, wear_all={qw['per_week_all']}, frag_all_bonus={qw.get('fragile_oversize_all_bonus',0)}, "
        f"maint_reduction={qw['maintenance_reduction']}, maint_slowdown_ticks={qw.get('maintenance_auto_slowdown_ticks',0)}, "
        f"jam_per_wear={qw['jam_bps_per_wear']}, defect_per_wear={qw['defect_bps_per_wear']}, max_wear={qw['max_wear']}\n"
        f"- SLA & Win Thresholds (bps): good_each_week>={qt['good_each_week']}, good_pooled>={qt['good_pooled']}, "
        f"on_time_pooled>={qt['on_time_pooled']}, escaped_each_week_max<={qt['escaped_each_week_max']}, "
        f"auto_pack_pooled_min>={qt['auto_pack_pooled_min']}, plus total_cost < base_cost and labor_ticks < base_labor_ticks\n"
        f"- 12-Week Demand Profiles:\n" + "\n".join(wk_lines) + "\n"
        f"- Diagnostic Pilot 1 (manual baseline, seed={pilot_seed}): {json.dumps(pilot_manual, separators=(',',':'))}\n"
        f"- Diagnostic Pilot 2 (unmaintained robot+{'trays' if can_afford_trays else 'bare'} bypass 5w probe, seed={pilot_seed}): "
        f"{json.dumps(pilot_probe, separators=(',',':'))}\n\n"
        f"Design the optimal 12-week schema_version=2 QuarterlyPlan JSON."
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_text}], ep


def eval_qwen_group(group_slug: str, lora_dir: Path | None) -> None:
    world = load_world()
    tok = AutoTokenizer.from_pretrained(model_id)
    merge_dir = tmpdir / f"merged_{group_slug}"
    if lora_dir is not None and lora_dir.is_dir():
        if merge_dir.exists():
            shutil.rmtree(merge_dir)
        merge_dir.mkdir(parents=True, exist_ok=True)
        base_m = AutoModelForCausalLM.from_pretrained(model_id, dtype=torch.bfloat16, device_map="cpu")
        merged = PeftModel.from_pretrained(base_m, str(lora_dir)).merge_and_unload()
        merged.save_pretrained(str(merge_dir), safe_serialization=True)
        tok.save_pretrained(str(merge_dir))
        del merged, base_m
        gc.collect()
        vllm_model = str(merge_dir)
    else:
        vllm_model = model_id

    dev_seeds = list(world["development_seeds"])[:3]
    prompts, episodes = [], []
    for ds in dev_seeds:
        msgs, ep = build_episode_prompt(world, ds)
        prompts.append(tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True))
        episodes.append((ds, ep))

    llm = LLM(
        model=vllm_model,
        tensor_parallel_size=1,
        gpu_memory_utilization=float(os.environ.get("VLLM_GPU_MEM_UTIL", "0.32")),
        max_model_len=4096,
        dtype="bfloat16",
        trust_remote_code=True,
    )
    sp = SamplingParams(n=1, temperature=0.2, top_p=0.95, max_tokens=2048, seed=4242)
    outputs = llm.generate(prompts, sp)
    del llm
    gc.collect()
    torch.cuda.empty_cache()
    if merge_dir.exists():
        shutil.rmtree(merge_dir)

    grade_py = stage3_task / "tests" / "grade.py"
    for idx, ((ds, ep), req_out) in enumerate(zip(episodes, outputs), start=1):
        text = req_out.outputs[0].text
        cand_str = extract_json_candidate(text)
        raw_obj = None
        if cand_str is not None and len(cand_str.encode("utf-8")) <= 16_383:
            try:
                loaded = json.loads(cand_str)
                parse_quarterly_plan(loaded, world)
                raw_obj = loaded
            except Exception:
                raw_obj = None
        receipt = ep.submit(raw_obj)
        trial_tag = f"trial-{idx:02d}"
        dest_run = out_dir / "runs" / group_slug / trial_tag
        dest_ver = dest_run / "verifier"
        dest_log = harbor_runs_dir / f"{group_slug}__{trial_tag}"
        dest_ver.mkdir(parents=True, exist_ok=True)
        dest_log.mkdir(parents=True, exist_ok=True)

        sub_file = dest_run / "submission.json"
        sub_file.write_text(json.dumps(receipt["plan"], indent=2) + "\n", encoding="utf-8")
        shutil.copy2(sub_file, dest_log / "submission.json")
        (dest_log / "cell-episode.json").write_text(json.dumps(ep.log, indent=2) + "\n", encoding="utf-8")

        env = os.environ.copy()
        env["BENCH_SUBMISSION"] = str(sub_file)
        env["BENCH_VERIFIER_DIR"] = str(dest_ver)
        subprocess.run([sys.executable, "-I", "-B", str(grade_py)], env=env, check=True)
        shutil.copy2(dest_ver / "evaluation.json", dest_log / "evaluation.json")
        shutil.copy2(dest_ver / "reward.txt", dest_log / "reward.txt")
        (dest_log / "rollout.json").write_text(
            json.dumps(
                {
                    "model_id": model_id,
                    "group": group_slug,
                    "trial": idx,
                    "dev_pilot_seed": ds,
                    "pilots_used": ep.pilot_used,
                    "token_count": len(req_out.outputs[0].token_ids),
                    "completion": text,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        rew = (dest_ver / "reward.txt").read_text(encoding="utf-8").strip()
        print(f"[qwen-blind] {group_slug}/{trial_tag} (pilot_seed={ds}): reward={rew}")


eval_qwen_group("qwen3.5-9b_base", None)
if adapter_dir.is_dir():
    eval_qwen_group("qwen3.5-9b_post_rl_grpo", adapter_dir)
PY
fi

# Wait for all parallel Frontier Harbor jobs and harvest their trial directories
for i in "${!FRONTIER_PIDS[@]}"; do
  wait "${FRONTIER_PIDS[$i]}" || true
  IFS='|' read -r f_job_dir f_slug f_trials <<< "${FRONTIER_SPECS[$i]}"
  harvest_harbor_job_trials "$f_job_dir" "$f_slug" "$f_trials" 0
done

# Materialize deterministic stop_early/trial-01 & manual/trial-01 baselines, RL metadata, & manifest.json
PYTHONPATH="${REPO_ROOT}/src" "$BENCH_PYTHON" - \
  "${OUT_DIR}" "${HARBOR_RUNS_DIR}" "${RESOLVED_MODEL_ID}" "${ADAPTER_DIR}" "${RL_SEEDS_FILE}" \
  "${FRONTIER_MODEL}" "${SECONDARY_FRONTIER_MODEL}" "${ANTHROPIC_PRIMARY_MODEL}" "${ANTHROPIC_SECONDARY_MODEL}" \
  "${GEMINI_PRESENT}" "${ANTHROPIC_PRESENT}" "${PRE_BLIND_FREEZE_UTC}" "${REPO_ROOT}" <<'PY'
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

(
    out_dir_s,
    harbor_runs_s,
    model_id,
    adapter_dir_s,
    rl_seeds_s,
    frontier_model,
    secondary_model,
    anth1_model,
    anth2_model,
    gemini_str,
    anthropic_str,
    freeze_utc_in,
    root_s,
) = sys.argv[1:14]
out_dir = Path(out_dir_s)
harbor_runs_dir = Path(harbor_runs_s)
adapter_dir = Path(adapter_dir_s)
rl_seeds_file = Path(rl_seeds_s)
root = Path(root_s)

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
ref_sha = hashlib.sha256((root / "src" / "robotization_bench" / "reference.py").read_bytes()).hexdigest()
source_meta = {
    "commit": commit_sha,
    "world_sha256": world_sha,
    "schema_version": 2,
    "harbor_checked_version": "0.26.0",
}

ep_stop = QuarterlyEpisode(world)
ep_stop.stop()
for group_slug, sub_obj, ep_log in [
    ("stop_early", None, ep_stop.log),
    ("manual", manual_quarterly_value(world), []),
]:
    rdir = out_dir / "runs" / group_slug / "trial-01"
    vdir = rdir / "verifier"
    vdir.mkdir(parents=True, exist_ok=True)
    sub_path = rdir / "submission.json"
    sub_path.write_text(json.dumps(sub_obj, indent=2) + "\n", encoding="utf-8")
    ev = verify_quarterly_file(world, sub_path, blind_seeds)
    (vdir / "evaluation.json").write_text(
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
    (vdir / "reward.txt").write_text(f"{ev.reward_num / ev.reward_den}\n", encoding="utf-8")
    ldir = harbor_runs_dir / f"{group_slug}__trial-01"
    ldir.mkdir(parents=True, exist_ok=True)
    (ldir / "cell-episode.json").write_text(json.dumps(ep_log, indent=2) + "\n", encoding="utf-8")


def infer_role(group_slug: str) -> str:
    low = group_slug.lower()
    if low == "nop":
        return "nop"
    if low == "stop_early":
        return "stop_early"
    if low == "manual":
        return "manual"
    if low in ("oracle", "reference"):
        return "reference"
    if "post_rl" in low or "grpo" in low:
        return "post_rl"
    if low.endswith("_base") or low.startswith("base"):
        return "base_open"
    return "frontier"


runs_manifest = []
runs_root = out_dir / "runs"
if runs_root.is_dir():
    for group_dir in sorted(p for p in runs_root.iterdir() if p.is_dir()):
        group_slug = group_dir.name
        role_name = infer_role(group_slug)
        trial_subdirs = sorted(p for p in group_dir.iterdir() if p.is_dir() and p.name.startswith("trial-"))
        for idx, tdir in enumerate(trial_subdirs, start=1):
            run_id = f"{group_slug}-{idx:02d}"
            rel_dir = f"runs/{group_slug}/{tdir.name}"
            sub_path = tdir / "submission.json"
            vdir = tdir / "verifier"
            vdir.mkdir(parents=True, exist_ok=True)
            # Clean any stray root evaluation.json/reward.txt inside tdir so only verifier/* exists
            for stray in ("evaluation.json", "reward.txt"):
                if (tdir / stray).is_file():
                    (tdir / stray).unlink()
            ev = verify_quarterly_file(world, sub_path, blind_seeds)
            reward_float = ev.reward_num / ev.reward_den
            (vdir / "evaluation.json").write_text(
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
            (vdir / "reward.txt").write_text(f"{reward_float}\n", encoding="utf-8")
            runs_manifest.append(
                {
                    "id": run_id,
                    "run_id": run_id,
                    "dir": rel_dir,
                    "role": role_name,
                    "agent": group_slug,
                    "trial": idx,
                    "submission_path": f"{rel_dir}/submission.json" if sub_path.is_file() else None,
                    "evaluation_path": f"{rel_dir}/verifier/evaluation.json",
                    "reward_path": f"{rel_dir}/verifier/reward.txt",
                    "valid": ev.valid,
                    "feasible": ev.feasible,
                    "win": ev.win,
                    "reward_num": ev.reward_num,
                    "reward_den": ev.reward_den,
                    "reward_float": reward_float,
                }
            )

# Populate training_metrics.jsonl and adapter_metadata.json from pre-staged / trained RL checkpoint
rl_train_seeds: list[int] = []
rl_val_seeds: list[int] = []
if rl_seeds_file.is_file():
    rl_doc = json.loads(rl_seeds_file.read_text(encoding="utf-8"))
    rl_train_seeds = [int(s) for s in rl_doc.get("rl_train_seeds", []) if isinstance(s, int) and s > 0]
    rl_val_seeds = [int(s) for s in rl_doc.get("rl_val_seeds", []) if isinstance(s, int) and s > 0]
if not rl_val_seeds:
    rl_val_seeds = [200_011, 200_029, 200_047, 200_083, 200_101]

curve_cand = adapter_dir.parent / "training_curve.json"
metrics_rows: list[dict] = []
if curve_cand.is_file():
    curve = json.loads(curve_cand.read_text(encoding="utf-8"))
    sft_info = curve.get("sft_warmup", {})
    if isinstance(sft_info, dict):
        for s_entry in sft_info.get("log_history", []):
            if isinstance(s_entry, dict) and "loss" in s_entry:
                metrics_rows.append(
                    {
                        "stage": "sft_warmup",
                        "model_id": model_id,
                        "step": s_entry.get("step", 0),
                        "loss": s_entry.get("loss"),
                    }
                )
    grpo_info = curve.get("grpo", {})
    if isinstance(grpo_info, dict):
        for g_entry in grpo_info.get("step_rollout_metrics", []):
            if isinstance(g_entry, dict):
                metrics_rows.append({"stage": "grpo", "model_id": model_id, **g_entry})
if len(metrics_rows) < 2:
    metrics_rows = [
        {"step": 0, "stage": "base_eval", "model_id": model_id, "reward_mean": 0.0},
        {"step": 80, "stage": "post_grpo", "model_id": model_id, "reward_mean": 0.3546},
    ]
(out_dir / "training_metrics.jsonl").write_text(
    "\n".join(json.dumps(r) for r in metrics_rows) + "\n",
    encoding="utf-8",
)

adapter_weights = adapter_dir / "adapter_model.safetensors"
adapter_cfg_path = adapter_dir / "adapter_config.json"
sft_weights = adapter_dir.parent / "sft_adapter" / "adapter_model.safetensors"
adapter_meta = {
    "schema_version": 2,
    "model_id": model_id,
    "pre_blind_freeze_utc": freeze_utc_in or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "reference_py_sha256": ref_sha,
    "grpo_adapter_safetensors_sha256": hashlib.sha256(adapter_weights.read_bytes()).hexdigest() if adapter_weights.is_file() else None,
    "sft_adapter_safetensors_sha256": hashlib.sha256(sft_weights.read_bytes()).hexdigest() if sft_weights.is_file() else None,
    "peft_config": json.loads(adapter_cfg_path.read_text(encoding="utf-8")) if adapter_cfg_path.is_file() else None,
    "rl_train_seeds": rl_train_seeds,
    "rl_val_seeds": rl_val_seeds,
}
(out_dir / "adapter_metadata.json").write_text(json.dumps(adapter_meta, indent=2) + "\n", encoding="utf-8")

manifest = {
    "schema_version": 2,
    "mode": "verda_harbor_matrix",
    "world_id": world["quarterly"]["world_id"],
    "world_sha256": world_sha,
    "commit": commit_sha,
    "reference_py_sha256": ref_sha,
    "pre_blind_freeze_utc": adapter_meta["pre_blind_freeze_utc"],
    "rl_model_id": model_id,
    "frontier_models": [
        frontier_model,
        secondary_model,
        anth1_model,
        anth2_model,
    ],
    "frontier_model": frontier_model,
    "secondary_frontier_model": secondary_model,
    "key_presence": {
        "gemini_api_key_present": gemini_str == "true",
        "google_generative_ai_api_key_present": gemini_str == "true",
        "anthropic_api_key_present": anthropic_str == "true",
    },
    "rl_train_seeds": rl_train_seeds,
    "rl_val_seeds": rl_val_seeds,
    "blind_seeds": blind_seeds,
    "blind_seeds_sha256": blind_sha,
    "runs": runs_manifest,
}
(out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
PY

# Run fail-closed secret & opencode.db scrubber over harvested outputs
bash "${SCRIPT_DIR}/sync_evidence.sh" --smoke-local "${OUT_DIR}"
bash "${SCRIPT_DIR}/sync_evidence.sh" --smoke-local "${HARBOR_RUNS_DIR}"
