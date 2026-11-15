# Fulfillment-Cell-Bench

Most real-world warehouse robot rollouts lose money in their first quarter -- not because the robot arm is slow on a standard box, but because teams overspend on hardware early, feed fragile or oversize items into an uncalibrated machine, forget that human workers still have to walk over and clear jams, skip maintenance before Black Friday, and let Friday's unfinished orders roll into Monday already late.

**Fulfillment-Cell-Bench** turns that 12-week warehouse rollout into a black-box reinforcement learning environment built for **Junction 2026 (AfterQuery)**. AI agents cannot read the simulator code or see the test seeds: they get **24 practice test runs ("pilots")** to experiment, then submit one 12-week plan that is graded on unseen quarters.

**Live 3D Warehouse Replay Studio (No Install Needed):** [Open Live 3D Showcase](https://freezegu.github.io/4-horses-replay-studio/) (GitHub Pages mirror: [`musacss.github.io/fulfillment-cell-bench`](https://musacss.github.io/fulfillment-cell-bench/))

| Full 4-Zone Cell (`Prep -> Pick -> Pack -> QC`) | Zone 3 Packing Robot, Safety Cage & QC |
| :---: | :---: |
| ![3D Warehouse Overview](docs/assets/warehouse_overview.jpg) | ![Zone 3 Robotic Pack and QC](docs/assets/zone3_robot_pack.jpg) |

## 1. How the Warehouse & the `24` Practice Runs ("Pilots") Work

Orders (`regular`, `fragile`, and `oversize` boxes) flow through **4 zones in a line**: **Zone 1 Prep -> Zone 2 Pick -> Zone 3 Pack -> Zone 4 Quality Control** (`30 seconds` per simulation tick, `5` shifts per week). Inside `./tasks/fulfillment-cell-bench`, the agent submits a JSON plan covering all **12 weeks** (`weeks[0..11]`):

```json
{
  "schema_version": 2,
  "weeks": [
    {
      "robot": true,
      "trays": true,
      "route": "bypass",
      "maintenance": false,
      "workers": [[1], [2], [4, 3], [2, 3]]
    }
  ]
}
```

For each week (`0..11`), the AI controls four practical levers:
- **Buy equipment (`EUR 18,000` CapEx budget)**: Buy the Zone-3 **Packing Robot** (`EUR 13,500` + `EUR 35/week` service) and optional **Stabilization Trays** (`EUR 1,800`, which steady boxes and cut standard-box jam rates from `16%` down to `2.8%`). Hardware purchases are permanent -- you cannot return a robot in Week 9 after peak season.
- **Pick box routing (`route`)**: `"manual"` (humans pack everything), `"bypass"` (robot packs standard boxes while humans handle fragile, oversize, and rework), or `"all"` (robot tries to pack every box type).
- **Schedule maintenance (`maintenance`)**: Pay `EUR 45` to clean `-5` points of mechanical wear (`0..12`), trading a slight `1`-tick robot slowdown that week to prevent huge jam and defect spikes later.
- **Staff the floor (`workers`)**: Staff `1..8` workers per week and assign which zones (`1..4`) each worker is trained for. Changing headcount week-to-week costs `EUR 90` per hire and `EUR 110` per layoff, and multi-zone workers cost `EUR 45/week` extra. A jammed robot freezes until a **Zone-3 trained human** walks over and clears it (`4 minutes`).
- **What is a "Pilot" (`24` budget)?** Before locking in its final plan (`submit`), an agent can call `pilot(plan, seed)` up to **24 times** on `3` public historical quarters (`seeds 11, 29, 47`). Each `pilot` is a full 12-week **practice test run** in the digital twin so the agent can test staffing and routing ideas -- without brute-forcing thousands of random guesses.

## 2. How Scoring Works (And Why Shortcuts Fail)

Final plans are graded in a separate `no-network` verifier container on **unseen holdout quarters** using exact `fractions.Fraction` math (no float rounding loopholes):

- **Manual Baseline (`0.2000` = `1/5`)**: Running the warehouse with `6` human workers and no robot is feasible and scores `0.2000`.
- **To Earn a Real Win (`> 0.2000`)**, a plan must pass **4 service rules** on the unseen seeds (`<= EUR 18,000` equipment spend, `>= 90%` completed orders every single week and `>= 95%` overall, `>= 88%` on-time delivery, and `<= 1.2%` defective boxes escaping QC in every week) **and** beat Manual on **total Euro cost**, **human labor hours**, and **automate at least `30%` of packing**.
- **Anti-exploit ladder**:
  - `0.0000` (`0/1`): Doing nothing (`nop`), quitting early (`stop`), invalid JSON, or trying to "un-buy" a robot mid-quarter.
  - `(0.0000, 0.0900]`: Breaking any customer-service or quality rule (e.g., firing the crew or letting jams deadlock Zone 3).
  - `(0.1000, 0.2000]`: Feasible plans that lose money or fake automation (e.g., buying a robot in Week 11 just to check a box, or buying a robot and leaving `route="manual"`).
  - `(0.2000, 1.0000)`: True profitable automation -- higher savings vs. Manual earn a higher score.

## 3. Results on 8 Unseen Test Quarters (`evidence/benchmark-v2/` & `evidence/harbor-runs/`)

Tested via `harbor==0.26.0` + OpenCode (`10-minute` limit per trial) on `8` unseen test quarters (`blind_seeds.json`, `SHA-256: a32a879f...`), kept completely separate from the `3` public practice seeds and all `586` RL training seeds:

| Model / Strategy | Runs | Average Score (Best) | Mean 12-Wk Cost | Practice Runs Used (`/24`) | What Happened on the Warehouse Floor |
|---|---:|---:|---:|---:|---|
| **`Reference Solver` (`oracle`)** | `1` | **`0.3609`** (`0.3609`) | `EUR 47,564` | `20` | **Beats every AI trial**: `bypass` + trays, `4` off-peak workers, `5` in peak Weeks `7-9` |
| **`Qwen/Qwen3.5-9B (Trained RL)`** | `3` | **`0.3556`** (`0.3556`) | `EUR 47,953` | `2` | **3/3 wins (#1 AI model on average)**: learned warehouse physics in RL; needs only `2` check runs |
| `Claude Fable 5.2` | `3` | `0.3543` (`0.3603`) | `EUR 48,052` | `9-17` | 3/3 wins, but hires & fires extra staff for a single 1-week promo (`Week 3`) |
| `Claude Opus 5.5` | `3` | `0.3390` (`0.3503`) | `EUR 49,189` | `14-16` | 3/3 wins, but over-hires (`6` peak workers) and runs maintenance `11/12` weeks |
| `Gemini 3.1 Pro` | `3` | `0.2824` (`0.2867`) | `EUR 53,403` | `7-8` | 3/3 wins, but keeps `5` workers all 12 weeks -- wasting `EUR 5,450` in quiet weeks |
| `Manual Baseline` (`6` humans) | `1` | `0.2000` (`0.2000`) | `EUR 59,536` | `0` | All-human baseline (`0%` robot packing, `win = false`) |
| `Qwen/Qwen3.5-9B (Base Untrained)` | `3` | `0.0000` (`0.0000`) | -- | `2` | **0/3 wins**: invents a fake `Zone 5`, runs out of tokens, or hires `8` costly workers |
| `Gemini 4 Carbon` | `3` | `0.0000` (`0.0000`) | -- | `3-5` | Finds a winning plan by min 8, then times out testing `2,048` maintenance combos |
| `Do-Nothing` / `Stop-Early` | `2` | `0.0000` (`0.0000`) | -- | `0` | Verified zero-score floor |

### Why Our Trained `9B` Model Used Only `2` Practice Runs (vs. `7-17` for Frontier Models)

- **Frontier models walk into the warehouse cold**, so they spend `7-17` practice runs (`pilots`) learning basic warehouse lessons by trial and error -- discovering that `3` workers starve the line, `route="all"` jams on fragile promos, or `6` workers cost too much. `Gemini 4` even finds a good plan in its practice runs, then burns the rest of its clock trying to brute-force every maintenance combination in Python and forgets to call `submit()`!
- **Our `Qwen/Qwen3.5-9B` model learned warehouse intuition during RL training** (`50` LoRA SFT steps + `80` GRPO steps on `1x NVIDIA H200` across `96` randomized warehouses). Before training, `Base Qwen 3.5-9B` scored **`0.0000`** (`0%` wins). After RL, it already knows to pair the robot with trays on `"bypass"` and clean wear before Black Friday -- so at test time it runs just **2 quick sanity-check pilots** (`2/24`) on the practice seeds and immediately submits a plan (`0.3556`) that **beats the 3-run average of every frontier model tested**.

## 4. Caught Red-Handed: When Frontier Models Tried to Cheat

Because coding agents inside Harbor have a Linux terminal, **every frontier model family tried to snoop around the container** before solving the task fairly:

- **`Claude Opus 5.5`** ran `find / -name "quarterly.py" 2>/dev/null` trying to read our simulator source code.
- **`Claude Fable 5.2`** ran `ls -la /logs /logs/verifier /logs/artifacts` to peek at the grader folder, and ran `pip install numba` to brute-force a local copy of the simulator.
- **`Gemini 4 Carbon`** probed `ls -ld /logs/artifacts` and spawned a `44`-process Python brute-force pool inside a `2`-CPU container.

```text
$ docker run --rm <harbor-env-image> sh -c 'id; ls /srv/bench_daemon; touch /logs/artifacts/submission.json'
uid=1000(agent) gid=1000(agent) groups=1000(agent)
ls: cannot open directory '/srv/bench_daemon': Permission denied
touch: cannot touch '/logs/artifacts/submission.json': Permission denied
```

**How we blocked every cheat**: The agent runs as unprivileged `uid=1000` with zero simulator files in `/app`. The real simulator and `24`-pilot counter (`state.json`) live inside a root-only directory (`/srv/bench_daemon`, mode `0700`) behind a Unix socket (`/run/bench/bench.sock`) started by a setuid C wrapper (`bench-daemon-start`), and final grading runs in a separate `no-network` container.

## 5. Quick Start: Verify Our Results & Run the Judge Evaluation

Requires Python `>=3.12,<3.13` and [`uv`](https://docs.astral.sh/uv/) (plus Docker and `harbor==0.26.0` for live container runs). `scripts/run_judge_harbor.sh` automatically stages our 8 unseen test seeds (`evidence/benchmark-v2/blind_seeds.json`) into a temp task copy so one command reproduces the table above right after `git clone`:

```sh
# 1. Instant < 5s offline check: re-simulates all 22 blind runs on your CPU and verifies exact scores
uv run python scripts/run_bench.py --verify-evidence evidence/benchmark-v2

# 2. Run the local 12-week simulator (Manual vs Reference) and the full test suite
uv run python scripts/run_bench.py
uv run --group mcp python -m pytest -q

# 3. One-command live Harbor judge suite: runs Reference (oracle) + Do-Nothing + Stop-Early + 3 agent runs
bash scripts/run_judge_harbor.sh -m anthropic/claude-fable-5-2

# 4. Or run individual Harbor commands directly (pass --seeds-file to stage blind_seeds.json or custom judge seeds)
uv run python scripts/prepare_harbor.py --out /tmp/fcb-blind --seeds-file evidence/benchmark-v2/blind_seeds.json
harbor run -p ./tasks/fulfillment-cell-bench -a oracle
harbor run -p ./tasks/fulfillment-cell-bench -a nop
harbor run -p ./tasks/fulfillment-cell-bench -a opencode -m anthropic/claude-opus-5-5 -k 3 -n 3
```

## 6. Watch Any Model Inside the 3D Warehouse Simulation

Every week (`0..11`) exports tick-by-tick `30s` floor events (`events.jsonl`) plus plain-English mistake callouts (`diagnostics.json`) for the 3D Warehouse Studio:

```sh
# 1a. Export all built-in runs (Manual, Reference, Claude, Gemini, Qwen Base & Trained) in one command:
uv run python scripts/export_ai_mistakes_3d.py --out artifacts/3d-ai-mistakes

# 1b. Or plug in ANY Harbor run's submission.json to watch its exact jams, queues, and mistakes in 3D:
uv run python scripts/export_ai_mistakes_3d.py \
  --out artifacts/3d-ai-mistakes \
  --seeds 11 29 47 \
  --submission my_agent="My Custom Agent"=evidence/benchmark-v2/runs/opencode_claude-opus-5-5/trial-01/submission.json

# 2. Start the local replay server (Terminal A) and open the 3D Replay Studio in your browser (Terminal B):
uv run python scripts/serve_3d.py --dir artifacts/3d-ai-mistakes --host 127.0.0.1 --port 8765
bash studio/start.sh   # opens http://127.0.0.1:5173 -- scrub weeks, compare 2 models, or jump to jams
```

## 7. Key Folders & Docs

- `tasks/fulfillment-cell-bench/` -- Ready-to-run Harbor `0.26.0` task (`0700` socket daemon + isolated offline grader).
- `evidence/benchmark-v2/` & `evidence/harbor-runs/` -- All `22` blind runs, seed hashes, RL curves, and sanitized Harbor logs.
- `src/robotization_bench/` & `studio/` -- Python warehouse simulator, `Fraction` grader, and Three.js 3D Replay Studio.
- `docs/` -- [`AGENT.md`](AGENT.md), [`docs/SPEC.md`](docs/SPEC.md), [`docs/CONTRACTS.md`](docs/CONTRACTS.md), [`docs/HARBOR.md`](docs/HARBOR.md), [`docs/DEMO_PLAYBOOK_10MIN.md`](docs/DEMO_PLAYBOOK_10MIN.md).
