# Data, Wire & 3D Replay Contracts (`v1` + `v2`)

Canonical dataclass definitions reside in `src/robotization_bench/contracts.py`. All wire payloads are UTF-8 JSON serialized via `dataclasses.asdict` (Python `tuple` fields become JSON arrays; `allow_nan=False`). Plan parsers reject duplicate object keys, unknown keys, `NaN`/`Infinity`, and boolean-for-integer type confusion (`type(True) is not int`).

---

## 1. Plan Input Schemas (`validation.py`)

### 1.1 `QuarterlyPlan` & `WeekPlan` (`schema_version = 2`)
- **`QuarterlyPlan`**: `schema_version: int` (`== 2`), `weeks: tuple[WeekPlan, ...]` (`len == 12`).
- **`WeekPlan`**:
  - `robot: bool`, `trays: bool`, `maintenance: bool` (strict JSON booleans).
  - `route: "manual" | "all" | "bypass"`.
  - `workers: tuple[tuple[int, ...], ...]` (`1..8` workers; each worker is `1..4` unique integers from `[1, 2, 3, 4]`; `workers[i][0]` is initial shift zone).
  - Cross-week invariants: `robot` and `trays` are monotonic non-decreasing across `weeks[0..11]`; `not robot` implies `route == "manual"` and `not maintenance`.
  - `WeekPlan.to_shift_plan() -> Plan` projects any week directly to a `v1` `Plan(1, robot, trays, route, workers)`.

### 1.2 `Plan` (`schema_version = 1`)
- Exact keys: `{"schema_version", "robot", "trays", "route", "workers"}` with `schema_version == 1`. Validated by `parse_plan` / `decode_plan` (`parse_any_plan` / `decode_any_plan` dispatch on `schema_version in {1, 2}`).

---

## 2. Sacred `v1` Shift & 3D Replay Contracts (Musa Showcase Boundary)

These structures are frozen for 100% compatibility with Musa's 3D Warehouse Showcase:

### 2.1 `Order` & `Scenario`
- **`Order`**: `id: int` (`>= 0`, unique within shift), `kind: "regular" | "fragile" | "oversize"`, `arrival: int` (`0 <= arrival < shift_ticks`), `due: int` (`due >= arrival`).
- **`Scenario`**: `schema_version: int` (`== 1`), `seed: int`, `orders: tuple[Order, ...]` (non-empty, strictly sorted by `(arrival, id)`).

### 2.2 `Event` (`events.jsonl` — Exact 7 Keys & 11 Kinds)
Every JSONL line exported by `reporting.export_events` contains **all 7 keys** (`null` when inapplicable); wall-clock animation time is **`seconds = tick * tick_seconds` (`tick * 30`)**:

| `kind` | `order_id` | `resource` | `stage` | `attempt` | `end_tick` | Transition Semantics |
|---|---|---|---|---|---|---|
| `arrival` | `int` | `null` | `1` | `0` | `null` | Order enters system at `tick == arrival` (spawn box once). |
| `enqueue` | `int` | `null` | `1..4` | `0..1` | `null` | Enters `Q1..Q4` (`attempt=0`, or `Q4` `0..1`) or rework queue `R` (`stage=3, attempt=1`). |
| `start` | `int` | `"w0".."wN"` \| `"robot"` | `1..4` | `0..1` | `int` (`> tick`) | Pops input queue, reserves downstream slot (`stage < 4`); includes any human `walk`. |
| `walk` | `int` | `"w0".."wN"` | `1..4` | `0..1` | `tick + 2` | Initial travel sub-interval of human `start` or `assist` emitted at same `tick`. |
| `jam` | `int` | `"robot"` | `3` | `0` | `null` | Emitted at planned `robot` cycle end; robot holds `order_id` and `Q4` slot until cleared. |
| `assist` | `int` | `"w0".."wN"` | `3` | `0` | `int` (`> tick`) | Zone-3 worker clears waiting robot (`jam_service = 8` + optional `walk`); no human `finish` event. |
| `break` | `null` | `"w0".."wN"` | `null` | `null` | `tick + 40` | Non-preemptive shift break taken once at `tick >= 440`; no `finish` event. |
| `finish` | `int` | `"w0".."wN"` \| `"robot"` | `1..4` | `0..1` | `null` | Completes `start` (for jammed robot, emitted at `assist.end_tick`). |
| `good` | `int` | `"w0".."wN"` | `4` | `0..1` | `null` | Terminal defect-free completion (`on_time` iff `tick <= due`). |
| `escaped` | `int` | `"w0".."wN"` | `4` | `0..1` | `null` | Terminal undetected defect shipped after stage 4. |
| `scrap` | `int` | `"w0".."wN"` | `4` | `1` | `null` | Terminal detected defect on second pack attempt (`attempt == 1`). |

### 2.3 `RawReport` & `Economy`
- **`RawReport`**: `schema_version` (`1`), `seed`, `total`, `good`, `on_time`, `escaped`, `scrap`, `unfinished`, `pack_started`, `pack_finished`, `auto_finished`, `trays_used`, `rework_started`, `labor_ticks`, `overtime_ticks` (`len == len(workers)`), `events` (`[]` when `trace=False` or inside `manifest.json`).
- **`Economy`**: `purchase: int`, `costs: dict[str, int]`, `total: int` (`sum(costs.values())`).
  - `v1` `shift_economy.costs` has exact 10 keys: `depreciation`, `service`, `shifts`, `overtime`, `trays`, `materials`, `rework`, `late`, `unfulfilled`, `escaped`.
  - `v2` `week_economy.costs` has exact 14 keys: adds `maintenance`, `cross_skill`, `hiring_retraining`, and `backlog_holding`.

### 2.4 3D Pack Layout (`artifacts/3d-pack/`)
- **Per-shift / per-week `manifest.json`** (`replay_format: "robotization-bench.replay.v1"`):
  `{"replay_format": "robotization-bench.replay.v1", "world": {...}, "plan": {...}, "scenario": {...}, "raw": {..., "events": []}, "economy": {...}, "events_file": "events.jsonl"}`.
- **Quarterly rollout folder**: `<run-slug>/quarter_manifest.json` + `weeks/week-00..week-11/{manifest.json, events.jsonl}`. Every week is an authentic `v1` replay bundle.
- **Pack catalog**: `artifacts/3d-pack/index.json` (`pack_format: "robotization-bench.3d-pack-index.v1"`), served over read-only CORS HTTP (`127.0.0.1:8765`) by `scripts/serve_3d.py`.

---

## 3. Quarterly Reports, `Evaluation` & Verifier Boundary

- **`WeekReport`**: `week` (`0..11`), `label`, `week_seed`, `carryover_in`, `carryover_out`, `wear_start`, `wear_end`, `commissioning_active`, `shift_plan`, `scenario`, `raw`, `shift_economy`, `week_economy`.
- **`QuarterReport`**: `schema_version` (`2`), `seed`, `purchase`, `total_cost`, `labor_ticks`, `weeks` (`12` `WeekReport` items).
- **`Evaluation`**: `valid: bool`, `feasible: bool`, `win: bool`, `reward_num: int`, `reward_den: int` (`> 0`), `metrics: dict[str, int]` (empty `{}` if `valid=False`; else 13 keys: `orders`, `good`, `on_time`, `escaped`, `scrap`, `unfinished`, `auto_finished`, `pack_finished`, `labor_ticks`, `base_labor_ticks`, `total_cost`, `base_cost`, `purchase`), `reasons: tuple[str, ...]`.
- **Bounded file verifier (`verifier.py`)**: `verify_file`, `verify_quarterly_file`, and `verify_any_file` open submissions with `os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW`, require `stat.S_ISREG` and `st_size <= 16_384` bytes, and return `Evaluation(valid=False, reward_num=0, reward_den=1)` on symlinks, FIFOs, directories, oversized files, invalid UTF-8, or malformed JSON.

---

## 4. MCP Tools & Privilege-Separated Unix Socket Wire Protocol

- **MCP tools** (`mcp_server.py` & `mcp_proxy.py`): `observe({})`, `pilot({"plan": ..., "seed": ..., "trace": false})`, `submit({"plan": ...})`, `stop({})`.
- **Unix socket IPC (`/run/bench/bench.sock`)**: Newline-delimited UTF-8 JSON requests `{"action": "observe"|"pilot"|"submit"|"stop", "args": {...}}` from `SocketEpisodeClient` (`mcp_proxy.py`, zero simulator imports) to the root-owned `mcp_server.py` daemon, returning `{"ok": true, "result": ...}` or `{"ok": false, "error_type": ..., "error": ...}` while persisting `pilot_used`, `max_pilots`, `closed`, and `submission` atomically in `0600` `/srv/bench_daemon/state.json`.
