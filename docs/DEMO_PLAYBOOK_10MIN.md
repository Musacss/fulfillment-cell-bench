# 10-Minute Judge Demo Playbook -- Fulfillment-Cell-Bench

Target audience: **Junction 2026 -- AfterQuery "Break the Agent"** judges.
Total runtime: **10 minutes** (zero remote SSH required during live judging; every blind benchmark claim verifies locally on CPU in under 5 seconds).

---

## Pre-Flight Checklist (Before Entering the Judging Room)

1. Confirm clean checkout and local Python 3.12 environment:
   ```sh
   uv run python --version
   git status --short
   ```
2. Export the `v1` + `v2` 12-week 3D replay bundle (`artifacts/3d-pack/`) and AI mistake HUD diagnostics (`artifacts/3d-ai-mistakes/`):
   ```sh
   uv run python scripts/export_3d_pack.py --out artifacts/3d-pack --seed 11
   uv run python scripts/export_ai_mistakes_3d.py --out artifacts/3d-ai-mistakes --seeds 11 29 47
   ```
3. Start the read-only local CORS replay bridge on `http://127.0.0.1:8765` in Terminal Tab 2 (or `bash studio/start.sh` on the 3D Studio branch for `http://127.0.0.1:5173`):
   ```sh
   uv run python scripts/serve_3d.py --dir artifacts/3d-ai-mistakes --host 127.0.0.1 --port 8765
   ```
4. Open Musa's 3D Warehouse Showcase pointed at `http://127.0.0.1:8765/index.json` and pre-load Week 0 (`baseline_open`), Week 3 (`fragile_promo`), and Week 8 (`black_friday_peak`).

---

## Minute 0:00-1:30 -- The Warehouse ROI Trap & Airgapped Sandbox

- **Operational problem**: Warehouse automation rollouts fail ROI gates when operators buy CapEx upfront without coordinating SKU routing (`bypass` vs `all`), commissioning jam coverage (Zone-3 human assist), preventive maintenance (`-5` wear before holiday surge), and week-to-week crew sizing.
- **What the agent sees**: Inside `tasks/fulfillment-cell-bench`, an unprivileged agent (`USER agent`, `uid=1000`) receives public rules (`AGENT.md`, `docs/SPEC.md`, `docs/CONTRACTS.md`), `data/world_spec.json`, three public development seeds (`11, 29, 47`), and four MCP tools (`observe`, `pilot`, `submit`, `stop`) connected over `/run/bench/bench.sock` to a root-owned daemon (`/srv/bench_daemon`, mode `0700`) enforcing a non-resettable **24-pilot** budget (`state.json`, `0600`).
- **Live snoop attempts caught in Harbor logs**:
  - `Claude Opus 5.5` ran `find / -name "quarterly.py" 2>/dev/null` searching for simulator source code (`Permission denied` on `0700 /srv/bench_daemon`).
  - `Claude Fable 5.2` ran `ls -la /logs /logs/verifier /logs/artifacts` (`root:root 0755`) and `pip install numba` to compile a custom `@njit` simulator bypassing the 24-pilot budget.
  - `Gemini 4 Carbon` probed `ls -ld /logs/artifacts` and launched 44-worker multiprocessing searches on 2 container vCPUs before timing out over-analyzing $2^{11}$ maintenance bitmasks.

---

## Minute 1:30-4:00 -- Live `< 5s` Blind Evidence Audit & One-Command Run

Run the deterministic blind-evidence verifier and local benchmark live in Terminal Tab 1:

```sh
# 1. Re-verify all 22 blind runs, SHA-256 seed lock, and reward.txt parity in < 5s on CPU
uv run python scripts/run_bench.py --verify-evidence evidence/benchmark-v2

# 2. Run a live 12-week quarterly comparison (Manual baseline vs Reference Optimizer)
uv run python scripts/run_bench.py --out artifacts/demo-live
```

Point out three audit guarantees in the terminal output:
1. **4-way seed disjointness & pre-blind SHA-256 freeze**: `blind_seeds.json` (`8` CSPRNG seeds `>= 200M`) was sampled strictly after freezing `reference.py` and the H200 LoRA checkpoints, disjoint from `development_seeds`, `evidence/replay_seeds.json`, and all `586` RL train/validation seeds.
2. **Exact rational grading**: `grading.py` computes every SLA and cost ratio in `fractions.Fraction` (`reward_num / reward_den`), converting to float only at Harbor's `/logs/verifier/reward.txt` boundary inside a separate `no-network` container (`O_NOFOLLOW`, `<= 16,384` bytes).
3. **One-command Harbor reproduction**:
   ```sh
   harbor run -p ./tasks/fulfillment-cell-bench -a opencode -m anthropic/claude-fable-5-2
   harbor run -p ./tasks/fulfillment-cell-bench -a opencode -m anthropic/claude-opus-5-5
   harbor run -p ./tasks/fulfillment-cell-bench -a opencode -m gemini/gemini-3.1-pro-preview
   ```

---

## Minute 4:00-6:00 -- Adversarial Reward Hierarchy & Compact 9B RL Win

Walk through the strict rational hierarchy and the blind 8-seed scoreboard:

```text
0/1 == invalid == nop == stop_early == Base Qwen3.5-9B == Gemini 4 Carbon (timeout)
  < infeasible        in (0, 9/100]       (1/10000 rational floor on total jam deadlock)
  < feasible_no_win   in (1/10, 1/5]      (idle CapEx, Week-11 token robot, 8-worker cost blowout)
 <= manual_baseline   == 1/5 (0.2000)
  < Gemini 3.1 Pro    (~0.2824 mean)      < Claude Opus 5.5 (~0.3390 mean)
  < Claude Fable 5.2  (~0.3543 mean)      < Qwen3.5-9B SFT+GRPO (0.3556) < Reference (0.3609)
```

Highlight the `Qwen/Qwen3.5-9B` pre/post-RL delta:
- **Base `Qwen/Qwen3.5-9B` (`0.0000` blind; `0%` wins even at `8,192` tokens)**: Over-staffs 8 dual-skilled workers (`+42%` cost blowout -> `0.1703`), cuts crew during Black Friday under `route="all"` (`44%` on-time -> `0.0453`), or hallucinates `Zone 5` in OpenCode.
- **Post-RL `Qwen/Qwen3.5-9B` (`0.3556` across all 3 blind trials)**: Trained via LoRA SFT (`50` steps) + GRPO (`80` steps) on disjoint domain-randomized worlds on a single Verda `NVIDIA H200`, beating the 3-trial mean of every frontier model while leaving positive headroom below `Reference` (`0.3609`).

---

## Minute 6:00-8:30 -- Side-by-Side 3D Warehouse Playback & HUD Mistake Overlay

Switch to Musa's 3D Warehouse Twin (`http://127.0.0.1:8765/index.json` + `diagnostics.json`):

1. **Frontier operational mistakes (visible tick-by-tick at `30s/tick`)**:
   - **`Gemini 3.1 Pro`**: Static 5-worker crew across all 12 weeks bleeds off-peak shift payroll (`w00-w02`, `w04-w06`, `w10-w11`).
   - **`Claude Opus 5.5`**: Over-staffs 6 workers across `w07-w09` (`+EUR 11.4k` payroll + hire/layoff churn) and runs `maintenance=True` in 11/12 weeks (`+1`-tick robot slowdown during peak waves).
   - **`Claude Fable 5.2`**: Redundant multi-worker cross-skill premiums (`[3,2]` + `[4,3]`) and single-week promo hire/layoff churn.
2. **Porting any judge-supplied plan live into 3D**:
   ```sh
   uv run python scripts/export_ai_mistakes_3d.py \
     --out artifacts/3d-ai-mistakes \
     --seed 11 \
     --submission judge_plan="Judge Custom Plan"=path/to/submission.json
   ```
   Refresh the 3D viewer and jump straight to `highlight_ticks` in `diagnostics.json` (`jam`, `assist`, `escaped`, `overtime`).

---

## Minute 8:30-10:00 -- Q&A Fast-Path Reference

- **Committed Harbor trajectories & blind runs**: `evidence/harbor-runs/` and `evidence/benchmark-v2/runs/`.
- **Sacred `v1` 3D replay contract**: `docs/CONTRACTS.md` (`robotization-bench.replay.v1`, 11 event kinds, `30s` tick).
- **Full test & exploit suite**: `uv run --group mcp python -m pytest -q`.
