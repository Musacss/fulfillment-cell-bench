---
name: running-verda-harbor-rl
description: Use when provisioning remote GPU/Docker instances on Verda Cloud, running Harbor + OpenCode frontier agent evaluations, or training compact RL/GRPO models under fixed cloud credit budgets and strict seed/reproducibility constraints
---

# Running Verda Harbor & RL Pipelines

## Overview

Cloud credits and hackathon clocks vanish when multi-GPU VMs sit idle or when remote-only results cannot be verified offline by judges. **Right-size to single-GPU, arm a dead-man shutdown timer immediately, keep 4-way seed splits strictly disjoint, and export offline-verifiable artifacts back to git.**

## Iron Rules

1. **Right-Sized 1× GPU + Mandatory Dead-Man Timer:**
   - Provision **1× `H100 80GB` or `A100 80GB`** Ubuntu VM (~€1.80–€2.80/h, total run < €25 of a €200 budget)—never multi-GPU `2×/4× H100` for 7B–8B LoRA/GRPO. Colocate vLLM (`--gpu-memory-utilization 0.42`) + bf16 LoRA GRPO trainer on the single 80GB GPU.
   - First command on SSH login: `sudo shutdown -h +240 "4h budget guard"` (extend explicitly with `sudo shutdown -c && sudo shutdown -h +180` only while actively running).
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
| "Spin up `2× H100 SXM` for 15h so vLLM and trainer have separate GPUs" | 7B bf16 LoRA + vLLM fits in ~55 GB on 1× 80GB GPU; 2× SXM without a shutdown timer risks burning the entire €200 credit on one idle night. |
| "Train Qwen on `development_seeds` + `replay_seeds.json` to converge faster" | Contaminates evaluation and teaches constant-JSON memorization instead of `pilot`-driven adaptation. |
| "Serving Qwen on Verda during our demo is enough" | Judges re-run evaluation from `README.md` with one command; commit every trajectory, submission JSON, and deterministic offline verifier. |
