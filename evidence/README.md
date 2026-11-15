# Reproducibility Evidence & 4-Way Disjoint Seed Protocol

This directory stores deterministic evaluation artifacts, seed provenance locks, sanitized Harbor container trajectories, and compact open-model RL (`Qwen/Qwen3.5-9B` LoRA SFT + multi-turn GRPO) outputs so any judge can verify every reported score locally on CPU in under 5 seconds—without SSH access, GPUs, or paid API keys.

---

## 1. Strict 4-Way Seed Disjointness

To prevent data contamination, prompt memorization, and test-set overfitting, **Fulfillment-Cell-Bench** partitions integer seeds into four strictly disjoint pools:

1. **Public Development Seeds (`data/world_spec.json` -> `development_seeds: [11, 29, 47]`)**:
   - Visible inside `observe({})` and playable via `pilot(...)` within the non-resettable `max_pilots = 24` episode budget.
2. **Public Plumbing & Smoke-Gate Seeds (`evidence/replay_seeds.json`)**:
   - `8` fixed post-`v1` CSPRNG seeds (`[5343194, 301926751, 437594646, 653467791, 853984044, 1177674159, 1809728213, 2055338172]`) used strictly for local regression and Docker/Harbor plumbing gates (`nop == 0`, `stop_early == 0`, `oracle > 0.35`). Never used for RL training or headline blind claims.
3. **Domain-Randomized RL Train & Validation Pools (Verda Cloud CSPRNG)**:
   - Fresh CSPRNG seeds paired with randomized `world_spec` cost, demand-wave, commissioning, and wear regimes used to train `Qwen/Qwen3.5-9B` via LoRA SFT + multi-turn GRPO (`scripts/verda/generate_sft_traces.py`, `scripts/verda/train_grpo_qwen7b.py`), forcing genuine `observe -> pilot -> diagnose -> submit` adaptation rather than static JSON memorization.
4. **Post-Freeze Blind Evaluation Seeds (`evidence/benchmark-v2/blind_seeds.json` + `.sha256`)**:
   - Generated once via CSPRNG *after* simulator code, `reference.py`, Harbor Dockerfiles, and RL LoRA checkpoints are frozen. Evaluated across `nop`, `stop_early`, `manual`, `oracle`/`reference`, `3x` `gemini/gemini-4-carbon` (OpenCode), `gemini/gemini-3.1-pro-preview` (OpenCode), `3x` Base `Qwen/Qwen3.5-9B`, and `3x` Post-RL `Qwen/Qwen3.5-9B`.

---

## 2. Directory Layout

- **`evidence/replay_seeds.json`**: Public 8-seed smoke-test array (disjoint from `development_seeds` and `blind_seeds.json`).
- **`evidence/frozen-v1/`**: Archived historical `v1` single-shift replay evidence (`submission.json`, `episode.json`, `results.json`, `comparison.md`) preserved read-only for backward auditability.
- **`evidence/harbor-runs/`**: Sanitized Harbor `0.26.0` Docker execution summaries and episode tool logs (zero API keys or secrets; boolean credential-presence flags only).
- **`evidence/benchmark-v2/`**: Synced blind-seed benchmark bundle (`blind_seeds.json`, `blind_seeds.sha256`, `manifest.json`, `training_metrics.jsonl`, LoRA adapter metadata, and `runs/<run-id>/{submission.json,evaluation.json,reward.txt}`).

---

## 3. One-Command Offline CPU Verification (`< 5s`)

Verify SHA-256 seed integrity, 4-way seed disjointness, bit-for-bit `reward_num / reward_den` + `reward.txt` parity, RL improvement (`Post-RL > Base`), and the full adversarial exploit hierarchy on CPU:

```sh
# Verify blind v2 benchmark bundle (runs in < 5 seconds on local CPU)
uv run python scripts/run_bench.py --verify-evidence evidence/benchmark-v2

# Re-run v1 historical 8-seed replay check
uv run python scripts/run_bench.py --mode v1 --plan evidence/frozen-v1/submission.json --seeds-file evidence/replay_seeds.json --out artifacts/replay-v1
```
