# 10-Minute Judge Demo Playbook — Fulfillment-Cell-Bench

Target audience: **Junction 2026 — AfterQuery "Break the Agent"** judges.
Total runtime: **10 minutes** (zero remote SSH required during live judging; every blind benchmark claim verifies locally on CPU in under 5 seconds).

---

## Pre-Flight Checklist (Before Entering the Judging Room)

1. Confirm clean checkout and local Python 3.12 environment:
   ```sh
   uv run python --version
   git status --short
   ```
2. Export the `v1` + `v2` 12-week 3D replay bundle (`artifacts/3d-pack/`) including Manual, Reference, Frontier (`gemini/gemini-4-carbon`), and Post-RL (`Qwen/Qwen3.5-9B`) trajectories:
   ```sh
   uv run python scripts/export_3d_pack.py --out artifacts/3d-pack --seed 11
   ```
3. Start the read-only local CORS replay bridge on `http://127.0.0.1:8765` in Terminal Tab 2:
   ```sh
   uv run python scripts/serve_3d.py --dir artifacts/3d-pack --host 127.0.0.1 --port 8765
   ```
4. Open Musa's 3D Warehouse Showcase pointed at `http://127.0.0.1:8765/index.json` and pre-load Week 0 (`baseline_open`), Week 3 (`fragile_promo`), and Week 8 (`black_friday_peak`).

---

## Minute 0:00–1:30 — The Warehouse ROI Trap & Task Framing

- **Core thesis**: Warehouse automation deployments routinely fail ROI targets because operators over-commit Week-0 CapEx, push fragile and oversize SKUs through rigid automated packing (`route="all"`), neglect commissioning jam spikes without Zone-3 flex staff, skip preventive maintenance before peak waves, and let unfinished backlog cascade across weeks.
- **What the agent faces**: Inside `tasks/fulfillment-cell-bench`, an OpenCode coding agent receives only public rules (`AGENT.md`, `docs/SPEC.md`, `docs/CONTRACTS.md`), three historical development seeds (`11`, `29`, `47`), and four MCP tools (`observe`, `pilot`, `submit`, `stop`) backed by a root-isolated Unix socket (`/run/bench/bench.sock`) with a non-resettable **24-pilot** budget (`/srv/bench_daemon/state.json`) and an **EUR 18,000** CapEx ceiling.
- Show `/app` vs `/srv/bench_daemon` privilege separation in `docs/HARBOR.md`: `USER agent` (`uid=1000`) has zero access to `engine.py`, `quarterly.py`, `grading.py`, or blind evaluation seeds.

---

## Minute 1:30–4:00 — Live One-Command Reproduction & `< 5s` Blind Evidence Audit

Run the local quarterly benchmark and deterministic blind-evidence verifier live in Terminal Tab 1:

```sh
# 1. Re-verify every blind benchmark submission, SHA-256 seed lock, and reward.txt in < 5s on CPU
uv run python scripts/run_bench.py --verify-evidence evidence/benchmark-v2

# 2. Run a live 12-week quarterly comparison (Manual baseline vs Reference Optimizer)
uv run python scripts/run_bench.py --out artifacts/demo-live
```

Point out three concrete details in the terminal output:
1. **SHA-256 & 4-way seed disjointness**: `blind_seeds.json` matches its recorded SHA-256 digest and is strictly disjoint from `development_seeds` (`[11, 29, 47]`), `evidence/replay_seeds.json`, and CSPRNG RL train/validation pools.
2. **Exact rational grading**: `grading.py` computes every metric and feasibility ratio in `fractions.Fraction` (`reward_num / reward_den`), emitting floating-point only at Harbor's final `/logs/verifier/reward.txt` boundary.
3. **One-command Harbor reproducibility** (for judges with Docker + API key):
   ```sh
   harbor run -p ./tasks/fulfillment-cell-bench -a opencode -m gemini/gemini-4-carbon
   harbor run -p ./tasks/fulfillment-cell-bench -a opencode -m gemini/gemini-3.1-pro-preview
   ```

---

## Minute 4:00–6:00 — Adversarial Reward Integrity & Exploit Hierarchy

Demonstrate why agents cannot game the benchmark in 15 minutes of shell access:

```sh
uv run --group mcp python -m pytest -q
```

Walk through the strict rational hierarchy enforced by the `no-network` verifier:

```text
0/1 == invalid == nop == stop_early
  < infeasible        in (0, 9/100]       (incl. 1/10000 floor on jam deadlock)
  < feasible_no_win   in (1/10, 1/5]      (e.g. buy_capex_idle / Week-11 token robot)
 <= manual_baseline   == 1/5 (0.200000)
  < automation_win    in (1/5, 1)         (cost < base, labor < base, auto_share >= 30%)
```

Highlight three defeated exploits:
- **`stdio_restart_flood`**: Respawning `mcp_proxy.py` 50 times hits the same root-owned `/srv/bench_daemon/state.json` counter and raises `PilotBudgetExceeded` at pilot 25.
- **Late-quarter token purchase**: Buying a robot in Week 11 only fails the pooled `auto_pack_pooled_min = 3000` bps (`30%`) automation gate and incurs commissioning jam penalties.
- **`buy_capex_idle`**: Buying robot + trays while keeping `route="manual"` adds weekly depreciation and service costs without reducing labor, scoring strictly below `1/5`.

---

## Minute 6:00–8:30 — Side-by-Side 3D Warehouse Playback (Why Frontier Fails vs Post-RL Wins)

Switch to Musa's 3D Warehouse Showcase (`http://127.0.0.1:8765`):

1. **Frontier failure mode (`gemini/gemini-4-carbon`, Week 0–3 & Week 8)**:
   - Show jam indicators (`kind: "jam"`) and `Q3` pack buffer saturation (`10/10` slots) when naive `route="all"` pushes `fragile` and `oversize` waves through the robot during commissioning (`+1400`/`+650` bps jam bonus) and high cumulative wear (`+350` bps jam per wear point) without dedicated Zone-3 assist coverage (`assist`).
   - Show Week 8 (`black_friday_peak`) unfinished orders carrying over into Week 9 at `arrival=0, due=0`, compounding late penalties and overtime ticks (`960..1080`).
2. **Post-RL (`Qwen/Qwen3.5-9B` SFT + GRPO) & Reference Optimizer win**:
   - Trained on Verda Cloud (`NVIDIA H200`) over randomized worlds via LoRA SFT + multi-turn GRPO using bounded `observe -> pilot -> diagnose -> submit` trajectories.
   - Routes `regular` orders automatically via `route="bypass"` with `trays=True`, staffs a cross-skilled `[2, 3]` flex worker to clear jams in `8` ticks (`jam_service`), schedules preventive `maintenance=True` (`-5` wear) ahead of holiday peaks, and scales peak-week crew cleanly—clearing all weekly/pooled SLAs while cutting both total EUR operating cost and human labor ticks below Manual (`reward > 0.35`).

---

## Minute 8:30–10:00 — Q&A Fast-Path Reference

- **Inspect raw Harbor trajectories & container logs**: `evidence/harbor-runs/` and `evidence/benchmark-v2/runs/`.
- **Inspect sacred `v1` 3D contract**: `docs/CONTRACTS.md` (`robotization-bench.replay.v1`, 11 event kinds, `30s` tick) — every week `0..11` of a `v2` quarterly rollout is a pure `engine.simulate()` shift trace.
- **Grade any judge-supplied plan on custom blind seeds**:
  ```sh
  uv run python scripts/run_bench.py --plan /path/to/plan.json --seeds-file /path/to/judge_seeds.json --out artifacts/judge-check
  ```
