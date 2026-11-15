# Fulfillment-Cell-Bench Specification (`v2` Quarterly & `v1` Shift Kernel)

This document is the authoritative public rulebook for **Fulfillment-Cell-Bench** (loaded directly by `Episode.observe()` and `QuarterlyEpisode.observe()`). Numeric parameters live in `data/world_spec.json` and cannot be mutated by submitted plans.

- **Units**: Time is measured in integer ticks (`tick_seconds = 30`), money in integer euro cents (`EUR 1.00 = 100` cents), and probabilities/thresholds in basis points (`10000` bps = `100%`).
- **Horizons**:
  - **`v2` Quarterly Rollout (`schema_version = 2`, default benchmark mode)**: Simulates `weeks = 12` coupled weeks (`w = 0..11`) per quarter seed by composing 12 sequential calls to the `v1` shift kernel with inter-week backlog carryover, commissioning spikes, cumulative equipment wear, preventive maintenance, irreversible CapEx, and staffing friction.
  - **`v1` Single-Shift Mode (`schema_version = 1`, backward-compatible kernel & 3D replay unit)**: Simulates one shift from tick `0` to `H = shift_ticks + overtime_ticks = 960 + 120 = 1080` (`9` hours). All execution intervals `[t, end)` are half-open.

---

## 1. Deterministic PRNG & Exogenous Demand Generation

Shift-level randomness uses an internal server-side PRNG seeded per week; exact micro-streams are only observable via `pilot()`. Every stochastic outcome is deterministic for a fixed `(seed, order_id, stage, attempt, event_type)` tuple -- never depending on worker identity, routing mode, or neighboring orders.

### 1.1 Shift Exogenous Generator (`scenarios.generate`)
Given `generator` parameters (`waves`, `spacing`, `orders_min`, `orders_span`, `jitter_span`, `regular_bps`, `fragile_bps`, `due_offset`, `due_span`) and integer `seed`:
- For each wave `w` in `0 .. waves - 1`, order count is sampled deterministically in `[orders_min, orders_min + orders_span)`.
- Orders receive sequential `order_id = 0, 1, ...` prior to sorting:
  - `arrival` is sampled deterministically in `[w * spacing, w * spacing + jitter_span)` (`0 <= arrival < shift_ticks`).
  - `due` is sampled deterministically in `[arrival + due_offset, arrival + due_offset + due_span)`.
  - `kind` is `"regular"` at rate `regular_bps / 10000`, `"fragile"` at rate `fragile_bps / 10000`, else `"oversize"`.
- Final `Scenario.orders` is sorted by `(arrival, id)`.

### 1.2 Quarterly Demand Profiles (`quarterly.generate_quarter_exogenous`)
For quarter `seed` and week `w` in `0..11`:
- `week_seed` is derived deterministically per `(seed, w)` from the internal server-side PRNG.
- `world["quarterly"]["week_profiles"][w]` overrides `waves`, `orders_min`, `regular_bps`, `fragile_bps`, and `due_offset` for week `w` (spanning baseline weeks `0..1`, `autumn_ramp` `2`, `fragile_promo` `3`, mid-quarter/prep `4..6`, peak holiday waves `7..9` where non-regular share reaches `38%--42%`, and post-peak/close `10..11`).

---

## 2. Sacred `v1` Discrete-Event Shift Kernel (`engine.simulate`)

### 2.1 Stages, Queues & Reservations
Orders traverse four stages: **1 (Prep)**, **2 (Pick)**, **3 (Pack)**, and **4 (QC)**.
- Input queue `Q1` (stage 1, `attempt=0`) and rework queue `R` (stage 3, `attempt=1`) have unlimited capacity.
- Intermediate buffers have finite capacity: `Q2` (`pick`) = `12`, `Q3` (`pack`, `attempt=0`) = `10`, `Q4` (`qc`) = `8`.
- Starting a job at stage `s < 4` atomically pops the item from its input queue and increments `reserved[s + 1]`; dispatch into stage `s` is blocked whenever `len(Q_{s+1}) + reserved[s + 1] >= capacity[s + 1]`. Finishing stage `s < 4` decrements `reserved[s + 1]` and appends the item to `Q_{s+1}`.

### 2.2 Exact 6-Step Per-Tick Scheduler (`t = 0 .. H`)
At each integer tick `t`:
1. **Complete human jobs (`job.end == t`)** in worker array order `w0, w1, ...`:
   - If `job.mode == "assist"`, the jammed robot transitions from `"assisted"` to `"released"` with `robot.end = t` (no human `finish` event is emitted for an assist).
   - Otherwise, `complete(job, w.name)` emits `finish` and advances or terminates the order.
2. **Process robot (`robot.end == t` and `robot.mode in {"work", "released"}`)**:
   - If `robot.mode == "work"` and the per-order jam outcome triggers at rate `jam_bps[rig][kind] / 10000`, `robot.mode` becomes `"waiting"` and `jam` is emitted (holding the order and its `Q4` reservation).
   - Otherwise, `complete(robot, "robot")` emits `finish`, records `pack_finished += 1` and `auto_finished += 1`, rolls `defect_auto`, and enqueues into `Q4`.
3. **Inject exogenous arrivals (`order.arrival == t`)** in ascending `id` order, emitting `arrival` followed by `enqueue(stage=1)`.
4. **Horizon / early-exit gate**: If `t == H` or `good + escaped + scrap == len(orders)`, the loop terminates immediately. No new `start`, `assist`, or `break` events can begin at `t == H`.
5. **Dispatch free robot** (when `plan.robot and plan.route != "manual" and robot is None`): Scans `Q3` (`attempt == 0`) in FIFO order for the first compatible item (`"all"`: any kind; `"bypass"`: `"regular"` only; non-routed items do not head-of-line block compatible items behind them). If `Q4` has space, reserves `Q4` and emits `start(resource="robot", stage=3, end_tick=t + auto_time)`.
6. **Dispatch free workers** in priority order `w0, w1, ...`:
   - **Break**: If `w.break_end == -1 and t >= break_at` (`440`), worker takes one non-preemptive break `[t, t + 40)` (`emit("break")`; logical zone `w.pos` unchanged).
   - **Jam assist**: Else if `robot.mode == "waiting"` and `3 in w.zones`, worker sets `robot.mode = "assisted"` and starts `assist` at stage `3` for `(walk_ticks if w.pos != 3 else 0) + jam_service` (`8` ticks).
   - **Stage work**: Else scans stages `4 -> 3 (R before Q3) -> 2 -> 1` restricted to `s in w.zones`, taking the first non-auto-routed item whose downstream buffer has space for `(walk_ticks if w.pos != s else 0) + manual_time[kind][s - 1]`.
   - If `travel > 0`, `walk` is emitted on `[t, t + 2)` alongside `start`/`assist`. Active labor accumulates `min(H, end) - t`. Worker overtime is `max(0, last_busy_tick - shift_ticks)`.

### 2.3 Quality, Rework & Order Conservation
- **Trays**: When `trays = true`, every `attempt == 0` pack start (robot or manual) consumes `1` tray (`trays_used += 1`); `attempt == 1` rework consumes `0` trays and is always packed manually.
- **Defects & QC**: Upon finishing stage `3`, `item.defect` is drawn against `defect_auto[rig][kind]` (robot) or `defect_manual[kind]` (human). Upon finishing stage `4`:
  - If `not item.defect`: emits `good` (`on_time += (t <= order.due)`).
  - Else if QC inspection misses the defect (rate `(10000 - detect) / 10000`, where `detect = 9500` bps): undetected defect ships as `escaped`.
  - Else if `attempt == 0`: detected defect enters rework queue `R` (`stage=3, attempt=1`).
  - Else (`attempt == 1`): second detected defect terminates as `scrap`.
- **Conservation**: At horizon `H`, `total == good + escaped + scrap + unfinished` holds identically.

---

## 3. `v2` Coupled 12-Week Mechanics (`quarterly.simulate_quarter`)

Across weeks `w = 0..11` of a `QuarterlyPlan`:
1. **Irreversible ownership**: `owned_robot` and `owned_trays` latch to `True` permanently once purchased; `maintenance` and non-manual `route` require `robot = True`.
2. **Commissioning (`commissioning.weeks = 2`)**: `commissioning_active` is `True` during the first 2 weeks in which `wp.robot` is `True` and `wp.route != "manual"`, adding `+1400`/`+650` bps (`bare`/`tray`) to `jam` and `+200`/`+80` bps (`bare`/`tray`) to `defect_auto`.
3. **Wear & preventive maintenance (`max_wear = 12`)**:
   - `effective_wear = min(12, max(0, wear_start - (5 if wp.maintenance else 0)))`.
   - Week `w` probabilities add `effective_wear * 350` bps to `jam` and `effective_wear * 120` bps to `defect_auto` (clamped to `[0, 10000]`).
   - When `wp.maintenance` is `True`, automated pack durations increase by `+1` tick (`maintenance_auto_slowdown_ticks = 1`).
   - End-of-week wear updates to `wear_end = min(12, effective_wear + wear_gain)` where `wear_gain` is `1` for `route="bypass"`, `3 + (1 if 10000 - regular_bps >= 3000 else 0)` for `route="all"`, and `0` for `"manual"`.
4. **Backlog carryover (`carryover_cap = 80`)**: Week `w` merges carried-over orders from week `w - 1` (re-indexed `0 .. carryover_in - 1` at `arrival = 0, due = 0`) ahead of week `w`'s exogenous orders (shifted by `+carryover_in`), preserving `Scenario` invariants. For `w < 11`, up to `80` unfinished orders carry into `w + 1`; at `w == 11`, `carryover_out = 0` and all remaining unfinished orders incur terminal unfulfilled penalties.

---

## 4. Integer-Cent Economics (`economics.py`)

### 4.1 `v1` Single-Shift `Economy` (`calculate`)
- `purchase = (1,350,000 if robot else 0) + (180,000 if trays else 0)`.
- Daily depreciation uses half-up integer division: `q, r = divmod(purchase, 500); depreciation = q + (2 * r >= 500)`.
- `costs` (10 keys): `depreciation`, `service` (`700` if `robot`), `shifts` (`len(workers) * 15200`), `overtime` (`sum(overtime_ticks) * 25`), `trays` (`trays_used * 6`), `materials` (`pack_started * 12`), `rework` (`rework_started * 70`), `late` (`(good - on_time) * 320`), `unfulfilled` (`(scrap + unfinished) * 3500`), `escaped` (`escaped * 6500`). `total = sum(costs.values())`.

### 4.2 `v2` Weekly & Quarterly `Economy` (`calculate_week`)
With `shifts = shifts_per_week = 5` and `prev_workers` initialized at `w = 0` to `manual.json`'s crew `[[1],[2],[3],[3],[4],[2,3]]`:
- Weekly depreciation: `q, r = divmod(purchase, 52); depreciation = q + (2 * r >= 52)`.
- Staffing friction: `hired = max(0, len(curr) - len(prev))`, `laid_off = max(0, len(prev) - len(curr))`, plus minimum newly added zone certifications `retrain_units` across retained workers (permutation-invariant bipartite matching): `hiring_retraining = 9000 * hired + 11000 * laid_off + 3500 * retrain_units`.
- `week_economy.costs` (14 keys): `depreciation`, `service` (`3500` if `owned_robot`), `maintenance` (`4500` if `maintenance`), `shifts` (`len(workers) * 15200 * 5`), `cross_skill` (`count(len(z) > 1) * 900 * 5`), `overtime` (`sum(overtime_ticks) * 25 * 5`), `hiring_retraining`, `trays` (`trays_used * 6 * 5`), `materials` (`pack_started * 12 * 5`), `rework` (`rework_started * 70 * 5`), `late` (`(good - on_time) * 320 * 5`), `backlog_holding` (`carryover_out * 600`), `unfulfilled` (`(scrap + (unfinished - carryover_out)) * 3500 * 5`), `escaped` (`escaped * 6500 * 5`).
- Quarter `total_cost` sums `week_economy.total` over `w = 0..11`; `purchase` reflects cumulative quarter-end equipment ownership.

---

## 5. Exact Rational Grading & Exploit Hierarchy (`grading.py`)

All grading uses exact `fractions.Fraction` (`F`) arithmetic against the manual baseline (`manual_value()` in `v1`; `manual_quarterly_value()` in `v2`) over identical evaluation seeds. Let `C = total_cost`, `B = base_cost`, `L = labor_ticks`, `L_b = base_labor_ticks`, `P = purchase`, and `S_auto = F(auto_finished, pack_finished)` (`0` if `pack_finished == 0`).

1. **Feasibility progress ratios (`progress` in `[0, 1]`)**:
   - `budget = min(1, F(budget_limit, P))` (`1` when `P <= 1,800,000`).
   - `volume`: in `v1`, `min_d min(1, F(good_d * 10000, total_d * 9400))`; in `v2`, `min(min_w min(1, F(good_w * 10000, total_w * 9000)), min(1, F(good_sum * 10000, orders * 9500)))`.
   - `on_time`: `min(1, F(on_time_sum * 10000, orders * threshold_on_time))` (`9000` bps in `v1`; `8800` bps in `v2`).
   - `quality`: `min_p min(1, F(total_p * threshold_escaped_max, escaped_p * 10000))` (`100` bps in `v1`; `120` bps in `v2`).
   - `feasible = all(v == 1 for v in progress.values())`.
2. **Win gate**:
   - `win = feasible and (C < B) and (L < L_b) and (S_auto * 10000 >= auto_pack_pooled_min)` (`2500` bps in `v1`; `3000` bps in `v2`).
3. **Piecewise rational reward**:
   - **Invalid / missing / `nop` / `stop_early`**: `F(0, 1)` (`valid = False`).
   - **Infeasible (`valid = True, feasible = False`)**: `max(F(1, 10000), F(9, 100) * min(progress.values()))` in `(0, 9/100]`.
   - **Feasible no-win (`valid = True, feasible = True, win = False`)**:
     - `overrun = max(F(0), F(C - B, B))` (plus, in `v2` when `P > 0`, `1 - auto_prog` if `"automation"` failed and `F(L - L_b + 1, max(1, L_b))` if `"labor"` failed).
     - `reward = F(1, 10) + F(1, 10) / (1 + overrun)` in `(1/10, 1/5]` (manual baseline scores `1/5` = `0.200000`).
   - **Automation win (`valid = True, feasible = True, win = True`)**:
     - `reward = F(1, 5) + F(4, 5) * F(B - C, B)` in `(1/5, 1)`.

This enforces the strict anti-reward-hacking hierarchy:
`0/1 == invalid == nop == stop_early < infeasible <= 9/100 < feasible_no_win <= manual (1/5) < automation_win < 1`.
