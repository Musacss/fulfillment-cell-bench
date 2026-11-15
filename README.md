# Fulfillment-Cell-Bench

**Fulfillment-Cell-Bench** is a black-box warehouse automation planning benchmark and discrete-event ROI simulator built for **Junction 2026 (AfterQuery)**. It tests whether coding agents and RL-trained open models can plan a profitable **12-week warehouse automation rollout** under capital constraints, stochastic machine jams, cumulative wear, seasonal demand spikes, and bounded simulation budgets -- without access to simulator source code.

## 1. What the Agent Has to Do

Inside `./tasks/fulfillment-cell-bench`, an unprivileged agent (`USER agent`, `uid=1000`) plans a 12-week operating quarter (`week = 0..11`, `schema_version = 2`) for a four-stage fulfillment cell (**Zone 1 Prep -> Zone 2 Pick -> Zone 3 Pack -> Zone 4 QC**) handling `regular`, `fragile`, and `oversize` orders.

The agent receives public rules ([`AGENT.md`](AGENT.md), [`docs/SPEC.md`](docs/SPEC.md), [`docs/CONTRACTS.md`](docs/CONTRACTS.md)), the parameter catalog ([`data/world_spec.json`](data/world_spec.json)), three historical development seeds (`[11, 29, 47]`), and four MCP tools (`observe`, `pilot`, `submit`, `stop`) backed by a root-owned daemon (`/srv/bench_daemon`, mode `0700`) over `/run/bench/bench.sock`:

```json
{
  "schema_version": 2,
  "weeks": [
    {
      "robot": true,
      "trays": true,
      "route": "bypass",
      "maintenance": false,
      "workers": [[1], [2], [2, 3], [4]]
    }
  ]
}
```

- **Weekly decisions (`weeks[0..11]`, exact 12 entries)**:
  - `robot` (`EUR 13,500` CapEx) and `trays` (`EUR 1,800` CapEx) -- irreversible equipment purchases capped at **EUR 18,000** (`1,800,000` cents), depreciated straight-line over `52` weeks plus `EUR 35/week` robot service.
  - `route` -- `"manual"`, `"bypass"` (robot packs first-pass `regular` orders; humans pack `fragile`, `oversize`, and all rework), or `"all"` (robot attempts all first-pass SKUs).
  - `maintenance` -- weekly preventive service (`EUR 45/week`, reduces start-of-week wear by `5`, adds `+1` tick to automated pack cycle times that week).
  - `workers` -- `1..8` shift workers, each assigned an ordered list of certified zones from `[1, 2, 3, 4]` (`workers[i][0]` sets starting position; list order sets dispatch priority).
- **Non-resettable rollout budget**: **`max_pilots = 24`** valid 12-week simulations on public development seeds, persisted atomically in `0600` `/srv/bench_daemon/state.json`. Respawning stdio MCP clients (`mcp_proxy.py`) reconnects to `/run/bench/bench.sock` without resetting `pilot_budget`.

## 2. Why It Is Hard

Real warehouse automation rollouts lose money when operators buy hardware upfront without adapting routing, maintenance, and shift staffing across waves. Static or greedy frontier policies fail across five coupled mechanics:

1. **Commissioning jam deadlocks**: The first `2` active robot weeks add `+1400` bps (`bare`) / `+650` bps (`tray`) jam risk and `+200` / `+80` bps auto-defect risk. A jammed robot holds its order and downstream `Q4` reservation until a human certified in **Zone 3** clears it (`jam_service = 8` ticks + `2`-tick walk). Omitting Zone-3 coverage deadlocks automated packing for the remainder of the `1080`-tick shift.
2. **Cumulative wear from rigid routing**: Running `route="all"` adds `+3` wear/week (`+4` during elevated `fragile`/`oversize` weeks `3, 7, 8, 9`), versus `+1` under `route="bypass"`. Each wear point (`0..12`) adds `+350` bps jam probability and `+120` bps auto-defect probability until mitigated by timed `maintenance`.
3. **Holiday wave & SKU-mix shifts**: Weeks `7..9` (`singles_day_wave`, `black_friday_peak`, `cyber_week_peak`) combine `13` arrival waves with `38%-42%` `fragile`/`oversize` share and tighter due-date slack (`150` ticks vs `165-170` baseline).
4. **Inter-week backlog carryover**: Unfinished orders at tick `1080` (`9` hours: `960` shift + `120` overtime at `30s`/tick) carry into week `w + 1` at `arrival = 0, due = 0` (`carryover_cap = 80`, `EUR 6/order` weekly holding fee), cascading congestion and late-delivery penalties across consecutive weeks.
5. **Staffing & retraining friction**: Week-to-week crew transitions relative to the 6-worker manual baseline (`[[1],[2],[3],[3],[4],[2,3]]`) incur `EUR 90` hiring, `EUR 110` layoff, and `EUR 35` zone-retraining fees, plus `EUR 45/week` cross-skill premiums per multi-zone worker.

## 3. How We Score It

Authoritative grading runs in an isolated **`no-network`** Harbor verifier container (`tests/grade.py`, `environment_mode = "separate"`) reading `/logs/artifacts/submission.json` (`O_NOFOLLOW`, regular file `<= 16,384` bytes). Neither `engine.py`, `quarterly.py`, `grading.py`, nor evaluation `seeds.json` ever enter `/app`. All metrics use exact `fractions.Fraction` arithmetic (`reward_num / reward_den`), converting to `float` only when writing `/logs/verifier/reward.txt`.

- **Feasibility gates** (all four required across held-out seeds):
  1. CapEx `purchase <= EUR 18,000` (`1,800,000` cents).
  2. Weekly `good >= 90.0%` (`9000` bps) of total weekly orders in every week **and** pooled `good >= 95.0%` (`9500` bps) of exogenous quarterly orders.
  3. Pooled `on_time >= 88.0%` (`8800` bps) of exogenous quarterly orders.
  4. Weekly `escaped <= 1.2%` (`120` bps) of total weekly orders in every week.
- **Win gate** (all three required on top of feasibility):
  - `total_cost < base_cost` (strictly lower 12-week EUR cost than manual baseline),
  - `labor_ticks < base_labor_ticks` (strictly lower active human labor ticks), and
  - `auto_finished / pack_finished >= 30.0%` (`3000` bps pooled across all completed pack attempts, including manual rework).
- **Strict anti-reward-hacking hierarchy**:
  ```text
  0/1 == invalid == nop == stop_early
    < infeasible       in (0, 9/100]      (1/10000 rational floor on total jam deadlock)
    < feasible_no_win  in (1/10, 1/5]     (penalizes idle CapEx & token Week-11 robot buys)
   <= manual_baseline  == 1/5 (0.2000)
    < automation_win   in (1/5, 1)        (1/5 + 4/5 * (base_cost - total_cost) / base_cost)
  ```

## 4. Reproduce in One Command & Benchmark Results

Requires Python `>=3.12,<3.13` and [`uv`](https://docs.astral.sh/uv/) (plus Docker and `harbor==0.26.0` for container evaluations):

```sh
# 1. Run the 12-week quarterly benchmark locally (Manual baseline vs Reference Optimizer)
uv run python scripts/run_bench.py

# 2. Verify blind evaluation seeds, SHA-256 digests, and exact reward parity in < 5s on CPU
uv run python scripts/run_bench.py --verify-evidence evidence/benchmark-v2

# 3. Grade an external v2 or v1 plan JSON on custom disjoint seeds
uv run python scripts/run_bench.py --plan data/plans/manual.json --seeds-file evidence/replay_seeds.json --out artifacts/check

# 4. Run black-box Harbor + OpenCode frontier agent evaluations
export GEMINI_API_KEY="..."
harbor run -p ./tasks/fulfillment-cell-bench -a opencode -m gemini/gemini-4-carbon
harbor run -p ./tasks/fulfillment-cell-bench -a opencode -m gemini/gemini-3.1-pro-preview

# 5. Run full unit, MCP, packaging, and adversarial exploit test suite
uv run --group mcp python -m pytest -q
```

### Blind Quarterly Evaluation (`evidence/benchmark-v2/` & `evidence/harbor-runs/`)

All blind evaluations use post-freeze CSPRNG `blind_seeds.json` strictly disjoint from `development_seeds` (`[11, 29, 47]`), `evidence/replay_seeds.json`, and Verda Cloud RL training/validation worlds:

| Policy / Agent | Harness & Budget | Valid / Feasible | Win | Exact Fraction (`blind_seeds`) | Scalar Reward | Notes |
|---|---|---|---|---:|---:|---|
| `Reference Optimizer` | Public `observe` + `<= 20` pilots | `pending M5 sync` | `pending M5 sync` | `pending M5 blind run sync` | `pending M5 sync` | Phased `bypass` + `trays` + Zone-3 flex + pre-peak `maintenance` |
| `Qwen/Qwen3.5-9B (Post-RL SFT+GRPO)` | LoRA SFT + multi-turn GRPO (`<= 24` pilots) | `pending M5 sync` | `pending M5 sync` | `pending M5 blind run sync` | `pending M5 sync` | Trained on Verda H200 over domain-randomized worlds |
| `gemini/gemini-4-carbon (OpenCode)` | Harbor `0.26.0` MCP (`3` blind runs) | `pending M5 sync` | `pending M5 sync` | `pending M5 blind run sync` | `pending M5 sync` | Primary frontier coding agent baseline |
| `gemini/gemini-3.1-pro-preview (OpenCode)` | Harbor `0.26.0` MCP (`1-3` blind runs) | `pending M5 sync` | `pending M5 sync` | `pending M5 blind run sync` | `pending M5 sync` | Secondary frontier coding agent comparison |
| `Qwen/Qwen3.5-9B (Base)` | Pre-RL open checkpoint (`3` blind runs) | `pending M5 sync` | `pending M5 sync` | `pending M5 blind run sync` | `pending M5 sync` | Unadapted compact open-weights baseline |
| `Manual Baseline` | Deterministic 6-worker manual crew | `yes / yes` | `no` | `1/5` | `0.2000` | Zero CapEx reference point across all seed splits |
| `nop / stop_early` | No submission or early `stop({})` | `no / no` | `no` | `0/1` | `0.0000` | Verified zero-credit floor |

*(Cells marked `pending M5 sync` are populated directly from `evidence/benchmark-v2/manifest.json` after the live Verda blind matrix sync and verified via `scripts/run_bench.py --verify-evidence evidence/benchmark-v2`.)*

On the public `development_seeds` (`[11, 29, 47]`) and public 8-seed `evidence/replay_seeds.json`, all deterministic baselines and exploit probes (`nop`, `stop_early`, `buy_capex_idle`, `unstaffed_jam_deadlock`, `manual`, and phased `bypass` automation) are regression-tested on every commit via `pytest`.

### 3D Warehouse Replay Showcase (`robotization-bench.replay.v1`)

Every week (`0..11`) of a quarterly rollout composes the untouched `v1` shift kernel (`30s`/tick, 11 `Event` kinds, `RawReport`, `Economy`) so any shift or week plays out-of-the-box in Musa's 3D Warehouse Showcase:

```sh
# Export paired v1 shifts + 12-week v2 rollouts (supports --extra-plan <slug>=<plan.json>)
uv run python scripts/export_3d_pack.py --out artifacts/3d-pack --seed 11

# Serve replay manifests and events.jsonl over read-only local CORS HTTP
uv run python scripts/serve_3d.py --dir artifacts/3d-pack --host 127.0.0.1 --port 8765
```

Single-shift `v1` timelines can also be exported directly via the CLI:

```sh
PYTHONPATH=src uv run python -m robotization_bench.cli validate --plan data/plans/manual.json
PYTHONPATH=src uv run python -m robotization_bench.cli pilot --plan data/plans/manual.json --seed 11 --events artifacts/shift-11.jsonl
```

## 5. Repository Layout & Black-Box Boundary

```text
tasks/fulfillment-cell-bench/   Ready-to-run Harbor 0.26.0 task (0700 /srv/bench_daemon + no-network verifier)
src/robotization_bench/         Shift kernel (engine.py), 12-week rollout (quarterly.py), Fraction grading, MCP daemon/proxy
scripts/run_bench.py            Dual-mode v2/v1 benchmark runner + <5s CPU blind-evidence verifier (--verify-evidence)
scripts/prepare_harbor.py       Airgapped Harbor bundle builder enforcing public /app allowlist & seed disjointness
scripts/export_3d_pack.py       Exports paired v1 shifts & 12-week rollouts to artifacts/3d-pack/ for 3D playback
scripts/serve_3d.py             Read-only CORS HTTP server (127.0.0.1:8765) for Musa's 3D Warehouse Showcase
scripts/verda/                  Verda H200 Harbor matrix + Qwen/Qwen3.5-9B LoRA SFT & multi-turn GRPO pipeline
data/world_spec.json            Immutable v1 shift + v2 12-week catalog & public development_seeds ([11, 29, 47])
evidence/                       4-way disjoint seed locks, Harbor trajectories, and CPU-verifiable benchmark bundles
```

## Documentation Map

- [`AGENT.md`](AGENT.md) -- Public task instructions mounted into `/app` for benchmarked agents.
- [`docs/SPEC.md`](docs/SPEC.md) -- Authoritative `v2` 12-week & `v1` shift physics, integer-cent economics, and rational grading formulas.
- [`docs/CONTRACTS.md`](docs/CONTRACTS.md) -- Frozen wire dataclasses, 11 sacred `Event` kinds, `manifest.json` 3D contract, and socket IPC.
- [`docs/HARBOR.md`](docs/HARBOR.md) -- Privilege-separated `/srv/bench_daemon` + `no-network` Harbor `0.26.0` container architecture.
- [`docs/DEMO_PLAYBOOK_10MIN.md`](docs/DEMO_PLAYBOOK_10MIN.md) -- 10-minute live Junction judge walkthrough and side-by-side 3D comparison script.
- [`evidence/README.md`](evidence/README.md) -- 4-way seed disjointness protocol and `< 5s` CPU verification guide (`docs/ru/` holds archived `v1` Russian docs).
