#!/usr/bin/env bash
# One-command AfterQuery standard-harness evaluation (Harbor 0.26.0 + OpenCode):
# Runs (1) reference (oracle), (2) do-nothing (nop), (3) stop-early (stop()), and (4) 3 frontier agent runs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

MODEL="anthropic/claude-fable-5-2"
TRIALS=3
CONCURRENCY=3
TASK_DIR="${REPO_ROOT}/tasks/fulfillment-cell-bench"
SEEDS_FILE=""
OUT_DIR="${REPO_ROOT}/artifacts/judge-harbor-eval"
CONTROLS_ONLY=0
HARBOR_BIN="${HARBOR_BIN:-harbor}"
PYTHON_BIN="${PYTHON_BIN:-}"

usage() {
  cat <<'EOF'
Usage: bash scripts/run_judge_harbor.sh [options]

Runs the standard AfterQuery judge suite via Harbor + OpenCode:
  1. Reference run       (harbor run -a oracle)
  2. Do-nothing baseline (harbor run -a nop)
  3. Stop-early baseline (calls MCP stop() -> reward 0.0)
  4. Frontier agent runs (harbor run -a opencode -m <provider/model> -k 3 -n 3)

Options:
  -m, --model PROVIDER/MODEL   OpenCode model (default: anthropic/claude-fable-5-2)
  -k, --trials N               Number of frontier trials (default: 3)
  -n, --concurrency N          Parallel trial concurrency (default: 3)
  -p, --task-dir DIR           Harbor task directory (default: ./tasks/fulfillment-cell-bench)
      --seeds-file JSON        Holdout seeds JSON (default: ./evidence/benchmark-v2/blind_seeds.json)
  -o, --out DIR                Output directory for Harbor logs (default: ./artifacts/judge-harbor-eval)
      --controls-only          Run oracle, nop, and stop_early only (skip opencode LLM trials)
  -h, --help                   Show this help message
EOF
}

require_opt_arg() {
  if [[ $# -lt 2 || -z "${2:-}" || "${2:-}" == -* ]]; then
    echo "Error: Option '$1' requires a non-empty value." >&2
    usage >&2
    exit 2
  fi
}

canon_path() {
  local raw="$1"
  if [[ "$raw" != /* ]]; then
    raw="$(pwd -P)/${raw}"
  fi
  local IFS='/'
  local -a parts=()
  local -a norm=()
  read -r -a parts <<< "$raw"
  local seg
  for seg in "${parts[@]}"; do
    if [[ -z "$seg" || "$seg" == "." ]]; then
      continue
    elif [[ "$seg" == ".." ]]; then
      if [[ ${#norm[@]} -gt 0 ]]; then
        unset 'norm[${#norm[@]}-1]'
      fi
    else
      norm+=("$seg")
    fi
  done
  if [[ ${#norm[@]} -eq 0 ]]; then
    echo "/"
    return 0
  fi
  local probe=""
  local idx=0
  local last_existing_idx=-1
  for (( idx=0; idx<${#norm[@]}; idx++ )); do
    probe="${probe}/${norm[$idx]}"
    if [[ -e "$probe" || -L "$probe" ]]; then
      last_existing_idx=$idx
    else
      break
    fi
  done
  if [[ $last_existing_idx -lt 0 ]]; then
    local joined=""
    for seg in "${norm[@]}"; do
      joined="${joined}/${seg}"
    done
    echo "$joined"
    return 0
  fi
  local existing_prefix=""
  for (( idx=0; idx<=last_existing_idx; idx++ )); do
    existing_prefix="${existing_prefix}/${norm[$idx]}"
  done
  local resolved_prefix=""
  if [[ -d "$existing_prefix" ]]; then
    resolved_prefix="$(cd -P "$existing_prefix" 2>/dev/null && pwd -P)" || resolved_prefix="$existing_prefix"
  else
    local parent_dir
    parent_dir="$(cd -P "$(dirname "$existing_prefix")" 2>/dev/null && pwd -P)" || parent_dir="$(dirname "$existing_prefix")"
    resolved_prefix="${parent_dir%/}/$(basename "$existing_prefix")"
  fi
  local result="${resolved_prefix%/}"
  for (( idx=last_existing_idx+1; idx<${#norm[@]}; idx++ )); do
    result="${result}/${norm[$idx]}"
  done
  [[ -z "$result" ]] && result="/"
  echo "$result"
}

validate_safe_out_dir() {
  local raw_out="$1"
  shift
  if [[ -z "$raw_out" || "$raw_out" == "/" || "$raw_out" == "." || "$raw_out" == ".." ]]; then
    echo "Error: Unsafe --out directory '$raw_out'." >&2
    exit 2
  fi
  local out_real
  out_real="$(canon_path "$raw_out")"
  if [[ -z "$out_real" || "$out_real" == "/" ]]; then
    echo "Error: Unsafe --out directory '$raw_out' (resolves to '/')." >&2
    exit 2
  fi
  local guarded_raw guarded_real
  for guarded_raw in "$@"; do
    [[ -z "$guarded_raw" ]] && continue
    guarded_real="$(canon_path "$guarded_raw")"
    if [[ "$out_real" == "$guarded_real" || "$guarded_real" == "${out_real}/"* ]]; then
      echo "Error: Refusing destructive --out '$raw_out' overlapping protected path '$guarded_raw'." >&2
      exit 2
    fi
  done
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -m|--model) require_opt_arg "$@"; MODEL="$2"; shift 2 ;;
    -k|--trials) require_opt_arg "$@"; TRIALS="$2"; shift 2 ;;
    -n|--concurrency) require_opt_arg "$@"; CONCURRENCY="$2"; shift 2 ;;
    -p|--task-dir) require_opt_arg "$@"; TASK_DIR="$2"; shift 2 ;;
    --seeds-file) require_opt_arg "$@"; SEEDS_FILE="$2"; shift 2 ;;
    -o|--out)
      if [[ $# -lt 2 || -z "${2:-}" || "${2:-}" == -* ]]; then
        echo "Error: Option '$1' requires a non-empty directory path." >&2
        usage >&2
        exit 2
      fi
      OUT_DIR="$2"
      shift 2
      ;;
    --controls-only) CONTROLS_ONLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if ! [[ "$TRIALS" =~ ^[1-9][0-9]*$ ]]; then
  echo "Error: --trials must be an integer >= 1 (got '$TRIALS')." >&2
  usage >&2
  exit 2
fi
if ! [[ "$CONCURRENCY" =~ ^[1-9][0-9]*$ ]]; then
  echo "Error: --concurrency must be an integer >= 1 (got '$CONCURRENCY')." >&2
  usage >&2
  exit 2
fi

validate_safe_out_dir "$OUT_DIR" "$REPO_ROOT" "$TASK_DIR"

if ! command -v "$HARBOR_BIN" >/dev/null 2>&1; then
  echo "Error: '$HARBOR_BIN' CLI not found in PATH (install harbor==0.26.0)." >&2
  exit 1
fi

if [[ "$CONTROLS_ONLY" -eq 0 ]]; then
  case "$MODEL" in
    gemini/*)
      if [[ -z "${GEMINI_API_KEY:-}" && -z "${GOOGLE_GENERATIVE_AI_API_KEY:-}" ]]; then
        echo "Error: GEMINI_API_KEY (or GOOGLE_GENERATIVE_AI_API_KEY) must be set and non-empty for model '$MODEL' (or pass --controls-only)." >&2
        exit 1
      fi
      ;;
    anthropic/*)
      if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
        echo "Error: ANTHROPIC_API_KEY must be set and non-empty for model '$MODEL' (or pass --controls-only)." >&2
        exit 1
      fi
      ;;
    openai/*)
      if [[ -z "${OPENAI_API_KEY:-}" ]]; then
        echo "Error: OPENAI_API_KEY must be set and non-empty for model '$MODEL' (or pass --controls-only)." >&2
        exit 1
      fi
      ;;
    openrouter/*)
      if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
        echo "Error: OPENROUTER_API_KEY must be set and non-empty for model '$MODEL' (or pass --controls-only)." >&2
        exit 1
      fi
      ;;
  esac
fi

if [[ -n "$PYTHON_BIN" ]]; then
  PY_CMD=("$PYTHON_BIN")
elif command -v uv >/dev/null 2>&1; then
  PY_CMD=(uv run python)
elif [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
  PY_CMD=("${REPO_ROOT}/.venv/bin/python")
else
  PY_CMD=(python3)
fi

WORK_TMP="$(mktemp -d "${TMPDIR:-/tmp}/fcb-judge.XXXXXX")"
trap 'rm -rf "$WORK_TMP"' EXIT

ACTIVE_TASK="$TASK_DIR"
if [[ -z "$SEEDS_FILE" && "$TASK_DIR" == "${REPO_ROOT}/tasks/fulfillment-cell-bench" && -f "${REPO_ROOT}/evidence/benchmark-v2/blind_seeds.json" ]]; then
  SEEDS_FILE="${REPO_ROOT}/evidence/benchmark-v2/blind_seeds.json"
fi
if [[ -n "$SEEDS_FILE" ]]; then
  ACTIVE_TASK="${WORK_TMP}/custom-task"
  PYTHONPATH="${REPO_ROOT}/src" "${PY_CMD[@]}" "${REPO_ROOT}/scripts/prepare_harbor.py" \
    --out "$ACTIVE_TASK" \
    --seeds-file "$SEEDS_FILE"
fi

validate_safe_out_dir "$OUT_DIR" "$REPO_ROOT" "$TASK_DIR" "$ACTIVE_TASK"
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

echo "==> [1/4] Running Reference solver (oracle) on ${ACTIVE_TASK} ..."
"$HARBOR_BIN" run -p "$ACTIVE_TASK" -a oracle -o "${OUT_DIR}/oracle"

echo "==> [2/4] Running Do-Nothing baseline (nop) ..."
"$HARBOR_BIN" run -p "$ACTIVE_TASK" -a nop -o "${OUT_DIR}/nop"

echo "==> [3/4] Running Stop-Early baseline (MCP stop()) ..."
STOP_TASK="${WORK_TMP}/stop-early-task"
cp -R "$ACTIVE_TASK" "$STOP_TASK"
cat > "${STOP_TASK}/solution/solve.sh" <<'STOP_EOF'
#!/usr/bin/env bash
set -euo pipefail
/usr/local/bin/bench-daemon-start
python3 - <<'PY'
from robotization_bench.mcp_proxy import SocketEpisodeClient
SocketEpisodeClient().stop()
PY
STOP_EOF
chmod +x "${STOP_TASK}/solution/solve.sh"
"$HARBOR_BIN" run -p "$STOP_TASK" -a oracle -o "${OUT_DIR}/stop_early"

if [[ "$CONTROLS_ONLY" -eq 0 ]]; then
  echo "==> [4/4] Running ${TRIALS}x OpenCode frontier trials (${MODEL}, concurrency=${CONCURRENCY}) ..."
  API_ARGS=()
  if [[ "$MODEL" == gemini/* ]]; then
    if [[ -n "${GEMINI_API_KEY:-}" ]]; then
      export GOOGLE_GENERATIVE_AI_API_KEY="${GOOGLE_GENERATIVE_AI_API_KEY:-$GEMINI_API_KEY}"
      API_ARGS=(--api-key-name GEMINI_API_KEY)
    elif [[ -n "${GOOGLE_GENERATIVE_AI_API_KEY:-}" ]]; then
      export GEMINI_API_KEY="$GOOGLE_GENERATIVE_AI_API_KEY"
      API_ARGS=(--api-key-name GOOGLE_GENERATIVE_AI_API_KEY)
    fi
  elif [[ "$MODEL" == anthropic/* && -n "${ANTHROPIC_API_KEY:-}" ]]; then
    API_ARGS=(--api-key-name ANTHROPIC_API_KEY)
  elif [[ "$MODEL" == openai/* && -n "${OPENAI_API_KEY:-}" ]]; then
    API_ARGS=(--api-key-name OPENAI_API_KEY)
  elif [[ "$MODEL" == openrouter/* && -n "${OPENROUTER_API_KEY:-}" ]]; then
    API_ARGS=(--api-key-name OPENROUTER_API_KEY)
  fi
  "$HARBOR_BIN" run -p "$ACTIVE_TASK" -a opencode -m "$MODEL" \
    "${API_ARGS[@]}" -k "$TRIALS" -n "$CONCURRENCY" -o "${OUT_DIR}/opencode" || true
fi

"${PY_CMD[@]}" - "$OUT_DIR" "$MODEL" "$CONTROLS_ONLY" <<'PY'
import statistics
import sys
from pathlib import Path

out_dir, model, controls_only = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])

def collect(sub: str) -> list[float]:
    base = out_dir / sub
    if not base.exists():
        return []
    files = sorted(base.rglob("verifier/reward.txt"))
    return [float(p.read_text(encoding="utf-8").strip()) for p in files]

rows = [
    ("reference (oracle)", collect("oracle")),
    ("do_nothing (nop)", collect("nop")),
    ("stop_early (stop())", collect("stop_early")),
]
if not controls_only:
    rows.append((f"opencode ({model})", collect("opencode")))

print("\n=== Judge Harbor Evaluation Summary ===")
print("| Run Group | Trials | Mean Reward | Individual Trial Rewards |")
print("|---|---:|---:|---|")
for label, vals in rows:
    if vals:
        mean_str = f"{statistics.mean(vals):.6f}"
        indiv = ", ".join(f"{v:.6f}" for v in vals)
    else:
        mean_str, indiv = "N/A", "missing reward.txt"
    print(f"| {label} | {len(vals)} | {mean_str} | {indiv} |")
PY
