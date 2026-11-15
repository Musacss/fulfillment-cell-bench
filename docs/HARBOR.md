# Black-Box Harbor `0.26.0` Packaging & Privilege Separation

**Fulfillment-Cell-Bench** ships a ready-to-run Harbor `0.26.0` task bundle at `./tasks/fulfillment-cell-bench` (built from `integration/harbor/` via `scripts/prepare_harbor.py`) engineered so coding agents with bash and Python access inside the container cannot read simulator source code, reset pilot rollout budgets, or inspect evaluation seeds.

---

## 1. Threat Model & Two-Tier Container Boundary

Coding agents such as **OpenCode** execute arbitrary shell commands via `docker exec` inside the task environment container. If simulator internals (`engine.py`, `quarterly.py`, `scenarios.py`, `economics.py`, `grading.py`) or in-memory counters are exposed to the agent user, an agent can import the simulator directly and grid-search thousands of plans offline, or kill/restart stdio processes to reset rollout budgets.

We defeat both attack classes via Unix privilege separation inside `environment/Dockerfile` plus an airgapped verifier container:

1. **Privileged Episode Backend (`/srv/bench_daemon`, `root:root`, mode `0700`)**:
   - Holds the private simulator modules (`contracts.py`, `validation.py`, `scenarios.py`, `engine.py`, `quarterly.py`, `economics.py`, `episode.py`, `mcp_server.py`), `data/world_spec.json`, `data/plans/manual.json`, and `docs/SPEC.md`.
   - Completely unreadable and untraversable (`EACCES`) by `USER agent` (`uid=1000`).
2. **Setuid Zero-Argument Daemon Launcher (`/usr/local/bin/bench-daemon-start`, `root:root`, mode `04755`)**:
   - Because Harbor `0.26.0` enters the container as the Dockerfile's final `USER` (`USER agent`), `mcp_proxy.py` invokes `/usr/local/bin/bench-daemon-start` on first connection if `/run/bench/bench.sock` is not yet listening.
   - The compiled C launcher clears environment variables (`PYTHONPATH`, `PYTHONHOME`, `LD_PRELOAD`), acquires an exclusive lockfile, and spawns `python3 -I -m robotization_bench.mcp_server --mode quarterly --socket /run/bench/bench.sock --state /srv/bench_daemon/state.json ...` as `euid=0` without accepting user-controlled paths or flags.
3. **Non-Resettable Rollout State (`/srv/bench_daemon/state.json`, `root:root`, mode `0600`)**:
   - Every valid `pilot` call atomically increments `pilot_used` (`fsync` + `os.replace`) before returning simulation output.
   - Killing and respawning `mcp_proxy.py` 50+ times (`stdio_restart_flood`) reconnects to the same Unix socket `/run/bench/bench.sock` and hits `PilotBudgetExceeded` once `pilot_used == 24`.
4. **Unprivileged Agent Workspace (`/app`, `USER agent`, `uid=1000`, `HOME=/home/agent`)**:
   - Contains **only** public artifacts: `AGENT.md` (`instruction.md`), `docs/SPEC.md`, `docs/CONTRACTS.md`, `data/world_spec.json`, `data/plans/manual.json`, `data/development/{11,29,47}.json`, and `src/robotization_bench/mcp_proxy.py` (stdlib + `mcp` stdio client only, zero simulator imports).
5. **Airgapped Verifier Container (`tests/Dockerfile`, `environment_mode = "separate"`, `network_mode = "no-network"`)**:
   - Held-out evaluation `seeds.json` and `grading.py` exist **only** in `tests/`, never in `environment/`.
   - `python -I /tests/grade.py` reads `/logs/artifacts/submission.json` (`O_NOFOLLOW`, regular file `<= 16,384` bytes), evaluates `verify_quarterly_file` in exact `fractions.Fraction`, writes `/logs/verifier/evaluation.json` (with `reward_num`, `reward_den`, and `seeds_sha256`), and emits the scalar float to `/logs/verifier/reward.txt`.

---

## 2. Running Frontier & Compact Open-Model Evaluations with Harbor `0.26.0`

Export your provider API key as an ephemeral shell variable (never commit `.env` or bake keys into `task.toml` or Dockerfiles; note Harbor `0.26.0` uses the `gemini/...` model prefix to forward `GEMINI_API_KEY` / `GOOGLE_GENERATIVE_AI_API_KEY`):

```sh
# Sanity-check task wiring & anti-exploit gates
harbor run -p ./tasks/fulfillment-cell-bench --agent nop
harbor run -p ./tasks/fulfillment-cell-bench --agent oracle

# Evaluate Frontier OpenCode agents over MCP
export GEMINI_API_KEY="..."
harbor run -p ./tasks/fulfillment-cell-bench -a opencode -m gemini/gemini-4-carbon
harbor run -p ./tasks/fulfillment-cell-bench -a opencode -m gemini/gemini-3.1-pro-preview
```

### Compact Open-Weights RL Evaluation (`Qwen/Qwen3.5-9B` via vLLM on Verda H200)

Both frontier coding agents (`gemini/gemini-4-carbon` and `gemini/gemini-3.1-pro-preview` via OpenCode) and the compact open-weights model **`Qwen/Qwen3.5-9B`** (Base checkpoint and Post-RL LoRA SFT + multi-turn GRPO adapter served via colocated vLLM on Verda Cloud `NVIDIA H200` via `scripts/verda/run_harbor_matrix.sh` and `scripts/verda/train_grpo_qwen7b.py`) evaluate against the identical privilege-separated `/srv/bench_daemon` Unix socket (`/run/bench/bench.sock`, non-resettable `max_pilots = 24`) and airgapped `no-network` verifier (`tests/grade.py`). Model reasoning blocks (`<think>...</think>`) are stripped at tool-call / JSON submission boundaries while enforcing the exact same `16,384`-byte `submission.json` schema and `fractions.Fraction` grading contract.

Expected sanity invariants on every seed split:
- `nop` (no submission) -> `reward = 0.0` (`0/1`)
- `stop_early` (`stop({})` or `null` submission) -> `reward = 0.0` (`0/1`)
- `oracle` (`integration/harbor/solution/oracle.py` over `/run/bench/bench.sock`) -> `win = True`, `reward > 0.35`

---

## 3. Staging Custom Seed Splits (`scripts/prepare_harbor.py`)

Operators and judges can stage a fresh Harbor task bundle with any custom seed JSON array (strictly positive unique integers disjoint from `development_seeds = [11, 29, 47]`):

```sh
uv run python scripts/prepare_harbor.py \
  --out artifacts/harbor-custom \
  --seeds-file evidence/replay_seeds.json \
  --overwrite
```

`prepare_harbor.py` enforces the public `/app` allowlist, embeds `provenance.json` (`world_spec.json` SHA-256 and `seeds.json` SHA-256) into `tests/`, and refuses seed files that overlap public development history.
