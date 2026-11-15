# Fulfillment-Cell-Bench — Public Agent Briefing (`v2` Quarterly Rollout)

You are planning a **12-week (`week = 0..11`) warehouse fulfillment-cell automation rollout**. The cell processes `regular`, `fragile`, and `oversize` orders through four sequential stages:

1. **Zone 1 — Prep** (unbounded input queue `Q1`)
2. **Zone 2 — Pick** (buffer capacity `12`)
3. **Zone 3 — Pack** (buffer capacity `10` for first-pass packs; separate unbounded rework queue for detected defects)
4. **Zone 4 — Quality Control / QC** (buffer capacity `8`)

Your goal is to submit **one validated 12-week `QuarterlyPlan` (`schema_version: 2`)** that satisfies all weekly and pooled service-level agreements (SLAs) within the **EUR 18,000** capital budget while achieving **strictly lower total operating cost** and **strictly lower human labor ticks** than the manual baseline crew, with at least **30% (`3000` bps)** of completed packs handled by automation.

---

## 1. Available Episode Tools & Non-Resettable Budget

Interact with the environment through four MCP tools:

- **`observe({})`**: Returns `schema_version: 2`, the public `world` catalog (`data/world_spec.json`, amounts in integer euro cents, times in `30`-second ticks, probabilities/thresholds in basis points where `10000 = 100%`), full specification text (`rules`), `development_seeds` (`[11, 29, 47]`), exogenous 12-week order summaries (`history`), the `manual` baseline 12-week plan, and `pilot_budget` (`{"used": ..., "max": 24}`).
- **`pilot({"plan": <QuarterlyPlan>, "seed": <int>, "trace": false})`**: Simulates a full 12-week quarter on one public development seed (`11`, `29`, or `47`). Returns total CapEx `purchase`, `total_cost`, `labor_ticks`, pooled `totals`, and per-week `carryover_in`, `carryover_out`, `wear_start`, `wear_end`, `commissioning_active`, `jams`, `assists`, `raw`, and `week_economy`.
  - **Hard rollout budget**: You have **`max_pilots = 24`** valid pilot simulations across the entire episode. Exhausting the budget raises `BudgetExceeded` while leaving the episode open so you can still call `submit`. Restarting the MCP client does **not** reset `pilot_budget`.
- **`submit({"plan": <QuarterlyPlan>})`**: Validates and records your final 12-week plan into `/logs/artifacts/submission.json` via the privileged episode daemon, returns `{"terminal": true, "plan": ...}`, and permanently closes the episode. Submitting an invalid plan records `null` and scores `0`.
- **`stop({})`**: Aborts without a plan (`plan: null`), closes the episode, and scores `0`.

> Do NOT waste episode wall-clock time re-implementing the discrete-event simulator from scratch -- internal PRNG streams live inside the server, container CPU is capped (`2` vCPUs), and each `pilot` call simulates all 12 weeks in `< 0.2s` (`24` pilots available). Test hypotheses directly via `pilot` and call `submit` (terminal) well before the `600s` timeout.

An isolated airgapped verifier re-evaluates `/logs/artifacts/submission.json` from scratch on held-out evaluation seeds.

---

## 2. `QuarterlyPlan` JSON Schema & Hard Validation Rules

Your submitted `plan` must be a JSON object with exact root keys `{"schema_version", "weeks"}`:

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

Validation invariants (any violation raises `InvalidPlan` and scores `0` if submitted):

1. `schema_version` must be integer `2` (never boolean or float). Duplicate JSON keys, extra keys, `NaN`, and `Infinity` are rejected.
2. `weeks` must be an array of **exactly 12** weekly objects (`week = 0..11`), each with exact keys `{"robot", "trays", "route", "maintenance", "workers"}`.
3. `robot`, `trays`, and `maintenance` must be JSON booleans (`true` or `false`).
4. **Irreversible CapEx**: Once `robot` becomes `true` in week `w`, `robot` must remain `true` in all weeks `w..11`. Once `trays` becomes `true` in week `w`, `trays` must remain `true` in all weeks `w..11`.
5. **Equipment dependencies**: When `robot` is `false`, `route` must be `"manual"` and `maintenance` must be `false`.
6. **`route`**: `"manual"` (humans pack all orders), `"bypass"` (robot packs first-attempt `regular` orders; humans pack `fragile`, `oversize`, and all rework), or `"all"` (robot packs first-attempt orders of all three SKU kinds; humans pack rework).
7. **`workers`**: Array of `1..8` workers per week. Each worker is a non-empty array of distinct integer zones from `[1, 2, 3, 4]`. `workers[i][0]` sets `w{i}`'s starting zone each shift; array order sets dispatch priority.

---

## 3. Coupled 12-Week Operational Dynamics

Each week runs a representative `1080`-tick shift (`960` regular ticks + `120` overtime ticks at `30s`/tick) scaled across `shifts_per_week = 5` shifts, with state coupled from week `w` to week `w + 1`:

- **Commissioning spike (`commissioning.weeks = 2`)**: During the first **2 active robot weeks** (`robot: true` and `route != "manual"`), jam rates increase by **`+1400` bps** (`bare`) / **`+650` bps** (`tray`) and auto-pack defect rates increase by **`+200` bps** (`bare`) / **`+80` bps** (`tray`). A jammed robot holds its order and `Q4` slot until a worker certified for **Zone `3`** clears it (`jam_service = 8` ticks + walk). Without Zone-3 coverage, a single jam deadlocks the robot for the rest of the shift.
- **Cumulative wear & preventive maintenance (`max_wear = 12`)**:
  - If `maintenance: true`, start-of-week wear drops by **`5`** (`effective_wear = max(0, wear_start - 5)`), costing **EUR 45.00/week** (`4500` cents) and adding **`+1` tick** to automated pack cycle times that week.
  - Each unit of `effective_wear` adds **`+350` bps** to robot jam probability and **`+120` bps** to auto-pack defect probability across all SKUs.
  - End-of-week wear increases by **`+1`** under `route: "bypass"`, or **`+3`** under `route: "all"` (**`+4`** when non-regular SKU share `10000 - regular_bps >= 3000`, such as promo/peak weeks `3, 7, 8, 9`), capped at `12`.
- **Unfinished backlog carryover (`carryover_cap = 80`)**: Orders left unfinished at tick `1080` of week `w` (`0..10`) carry into week `w + 1` at `arrival = 0, due = 0` (up to `80` orders, incurring **EUR 6.00/order** weekly holding fee; any excess above `80` or unfinished at the end of Week `11` incurs the terminal unfulfilled penalty).
- **Staffing & cross-training friction** (Week `0` transitions are measured relative to the 6-worker `manual` baseline crew `[[1],[2],[3],[3],[4],[2,3]]`):
  - Hiring: **EUR 90.00** (`9000` cents) per net worker added; Layoff: **EUR 110.00** (`11000` cents) per net worker removed; Retraining: **EUR 35.00** (`3500` cents) per newly added zone certification on retained workers; Cross-skill premium: **EUR 9.00/shift** (`900` cents * `5` shifts = **EUR 45.00/week**) per worker certified in `>= 2` zones.
- **CapEx & weekly equipment costs**: Robot purchase is **EUR 13,500** (`1350000` cents), trays purchase is **EUR 1,800** (`180000` cents; combined **EUR 15,300** <= **EUR 18,000** budget). Owned equipment incurs weekly straight-line depreciation (`purchase / 52`, half-up to cent) plus **EUR 35.00/week** (`3500` cents) robot service once owned.

---

## 4. Feasibility Gates & Win Conditions

To be **feasible**, your plan must satisfy all four hard constraints across the evaluation seeds:

1. **CapEx budget**: `purchase <= 1,800,000` cents (**EUR 18,000.00**).
2. **Volume**: `good >= 90.00%` (`9000` bps) of total orders (exogenous + carried-in) in **every individual week**, AND pooled `good >= 95.00%` (`9500` bps) of exogenous quarterly orders.
3. **On-time delivery**: Pooled `on_time >= 88.00%` (`8800` bps) of exogenous quarterly orders.
4. **Quality**: `escaped <= 1.20%` (`120` bps) of total orders in **every individual week**.

To achieve a **Win** (`reward > 0.20`), your plan must be **feasible** AND simultaneously beat the `manual` quarterly baseline on all three operational targets:

- `total_cost < base_cost` (lower total 12-week EUR operating cost, including depreciation, service, maintenance, staffing friction, overtime, materials, and SLA penalties),
- `labor_ticks < base_labor_ticks` (fewer active human labor ticks), and
- `auto_finished / pack_finished >= 30.00%` (`3000` bps pooled across all completed pack attempts, including manual rework).
