---
name: running-verda-harbor-rl
description: Use when provisioning remote GPU/Docker instances on Verda Cloud, running Harbor + OpenCode frontier agent evaluations, or training compact RL/GRPO models under fixed cloud credit budgets and strict seed/reproducibility constraints
---

# Running Verda Harbor & RL Pipelines

## Overview

Cloud credits and hackathon clocks vanish when multi-GPU VMs sit idle or when remote-only results cannot be verified offline by judges. **Right-size to single-GPU, arm a dead-man shutdown timer immediately, keep 4-way seed splits strictly disjoint, and export offline-verifiable artifacts back to git.**

## Iron Rules

1. **GPU Allocation (`1×` or `2× H100 80GB`) + Mandatory Dead-Man Timer:**
   - **`2× H100 80GB` (~€4/h, preferred when available):** Pin `CUDA_VISIBLE_DEVICES=0` to dedicated `vLLM` rollout serving (`--gpu-memory-utilization 0.85`) and `CUDA_VISIBLE_DEVICES=1` to dedicated bf16 LoRA SFT / multi-turn GRPO policy training (zero memory contention, 2–3× faster rollouts; also supports `14B` models if desired). Fallback on `1× 80GB` is colocating vLLM (`0.42`) + trainer.
   - First command on SSH login: `sudo shutdown -h +360 "6h budget guard"` (extend explicitly with `sudo shutdown -c && sudo shutdown -h +240` while actively running so an forgotten VM after submission never drains remaining credits).
2. **Strict 4-Way Disjoint Seed Split:**
   - **Public Dev (`development_seeds`):** Visible inside `observe`/`pilot` only.
   - **Smoke Replay (`replay_seeds.json`):** Docker/Harbor plumbing check (`oracle`, `nop`, `stop_early`)—never used for RL training or final claims.
   - **RL Train / RL Val:** Fresh CSPRNG integer pools with domain randomization (perturbed `world_spec` demand/cost/jam regimes) so the model learns `observe -> pilot -> diagnose -> submit` tool-use rather than memorizing one static plan JSON.
   - **Blind Evaluation (`blind_seeds.json`):** Fresh CSPRNG seeds generated once *after* code, reference solver, and RL checkpoint are frozen; SHA-256 logged before running `oracle`, `nop`, `stop_early`, 3× Frontier OpenCode runs, 3× Base-7B runs, and 3× Post-RL-7B runs.
3. **Ephemeral Secrets & Container Airgap:**
   - Pass frontier API keys via ephemeral shell env vars only—never bake into Dockerfiles, `task.toml`, git, or `/logs`; record boolean key-presence metadata only.
   - Keep Harbor `environment_mode = "separate"` and verifier `network_mode = "no-network"`; never mount host repo or `tests/seeds.json` into the agent container.
4. **Offline Judge Reproducibility Bundle (Critical for Grading):**
   - Judges do not SSH into your Verda VM. Sync back and commit deterministic `evidence/benchmark-v2/`:
     - All submitted `submission.json` files, sanitized Harbor episode logs, `blind_seeds.json` + SHA-256, `training_metrics.jsonl` (pre-RL vs post-RL reward curve), LoRA adapter config/weights link, and one-command local verifier (`uv run python scripts/run_bench.py --verify-evidence evidence/benchmark-v2`) that deterministically recomputes every table row in < 5 seconds on CPU.

## Quick Reference: Execution Pipeline

| Stage | Command / Artifact | Gate |
|---|---|---|
| 1. Boot Guard | `sudo shutdown -h +240` + `docker info` + `uv --version` | Timer active, Docker live |
| 2. Harbor Gate | `harbor run --agent nop`, `stop_early`, `oracle` on `replay_seeds.json` | `0.0 == nop == stop_early < oracle` |
| 3. Frontier 3× | 3× OpenCode runs on `blind_seeds.json` | 3 trajectories + failure mode taxonomy |
| 4. 7B GRPO | Warm-start LoRA SFT (valid tool traces) → multi-turn GRPO on exact `Fraction` reward | Base-7B < Post-RL-7B on held-out RL-val & `blind_seeds.json` |
| 5. Sync Back | `rsync` `evidence/benchmark-v2/` → local CPU re-grade | `scripts/run_bench.py` matches Harbor `reward.txt` bit-for-bit |

## Rationalization Table

| Excuse | Reality |
|---|---|
| "Leave the GPU VM running without a `shutdown -h` guard" | An unguarded multi-GPU node left alive after submission drains remaining credits; always arm `shutdown -h +360` on boot. |
| "Train Qwen on `development_seeds` + `replay_seeds.json` to converge faster" | Contaminates evaluation and teaches constant-JSON memorization instead of `pilot`-driven adaptation. |
| "Serving Qwen on Verda during our demo is enough" | Judges re-run evaluation from `README.md` with one command; commit every trajectory, submission JSON, and deterministic offline verifier. |
