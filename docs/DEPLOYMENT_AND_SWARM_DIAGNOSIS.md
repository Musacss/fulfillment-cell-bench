# Forensic Diagnosis: Swarm Fragmentation, PR Conflicts & Live Code Deployment

## 1. Executive Summary

Prior swarm milestones reported individual tasks as "done and merged" while the canonical repository (`Musacss/fulfillment-cell-bench:main`) and live web showcase remained un-integrated. Forensic inspection of git object graphs, worktrees, GitHub Pull Requests, and remote targets identified four concrete root causes and resolved each via conflict-free Pull Requests and verified live static deployment.

---

## 2. Root Causes Identified

### 2.1 GitHub Pull Request #5 Merge Conflict (`CONFLICTING` / `DIRTY`)
- **Observed Symptom**: Pull Request [#5](https://github.com/Musacss/fulfillment-cell-bench/pull/5) (`ilyas/dev` -> `main`) failed GitHub mergeability checks with `"mergeable": "CONFLICTING"` and `"mergeStateStatus": "DIRTY"` across five files:
  - `CONFLICT (add/add): src/robotization_bench/quarterly.py`
  - `CONFLICT (content): src/robotization_bench/episode.py`
  - `CONFLICT (content): src/robotization_bench/grading.py`
  - `CONFLICT (content): src/robotization_bench/validation.py`
  - `CONFLICT (content): src/robotization_bench/verifier.py`
  - *(plus `src/robotization_bench/reference.py` after PR #6 merged `bridge-3d` `4f10906` into `main` `9c6c3fb`)*
- **Exact Git Root Cause**: Earlier commit `c4ffbc8` (`parents=[9c070a4]`) copied an early `3f344a3` snapshot of the 12-week `v2` simulator onto `bridge-3d` as a **single-parent non-merge commit** instead of a two-parent `git merge` from `ilyas/dev`, and PRs #3 (`8a58141`) and #4 (`10d0ee8`) merged `bridge-3d` into `main`. Because `ilyas/dev` was never recorded as a second parent of `c4ffbc8`, `git merge-base main ilyas/dev` remained at the pre-`v2` ancestor `9400595`. When `5431c91` hardened `quarterly.py`, `episode.py`, `grading.py`, `validation.py`, and `verifier.py` on `ilyas/dev`, Git's 3-way merge treated both branches as independently adding/editing those five files.

### 2.2 Four-Way Local Worktree & Branch Isolation
Work products lived across four separate refs that had never been unified onto `main`:
1. **`ilyas/dev` (`5431c91` / `625a821`)**: Hardened `v2` 12-week simulator, `fractions.Fraction` grading, privilege-separated Harbor `0.26.0` bundle (`tasks/fulfillment-cell-bench/`), red-team fuzz tests, and Verda RL/Harbor scripts.
2. **`.worktrees/e2e-suite` (`swarm/e2e-suite` at `f0ce5d5`)**: 204-test 4-tier opaque-box E2E suite (`tests/e2e/`) committed inside an isolated git worktree (`git worktree list`) and never merged into `ilyas/dev` or `main`.
3. **`origin/bridge-3d` (`4f10906`, merged via PR #6 `9c6c3fb`)**: Real multi-model Harbor rollout examples (`docs/ru/examples/*.json`) and default catalog support in `scripts/export_ai_mistakes_3d.py`.
4. **`origin/codex/replay-studio` (`d346831`)**: Three.js + Vite 3D Replay Studio (`studio/`), 15 SHA-256 verified GLB assets (`4_Horses_Environment_v02/`), and Node QA checks (`scripts/check_*.mjs`) sitting on an unmerged remote branch with no open PR to `main`.

### 2.3 Two-Repository GitHub Pages Split & Permissions Boundary
- `Musacss/fulfillment-cell-bench` had `"has_pages": false` and zero `.github/workflows/` pipelines.
- `https://musacss.github.io/4-horses-replay-studio/` is served from a separate repository (`Musacss/4-horses-replay-studio`) where the active `gh` account (`FreezeGu`) has read/PR permission (`push: false`) while holding full `push: true` access on `Musacss/fulfillment-cell-bench` and `admin: true` on `FreezeGu/*`.

### 2.4 Code-Only Scope Boundary for Remote GPU Nodes
- Inspection of `verda-junction:/root/bench` showed only `H200_ENV_READY.json` (with pre-staged LoRA weights under `/root/prestage-checkpoints/qwen35-9b-grpo/final_adapter`). Per explicit user scope (`"you only deploy the code"`), Verda scripts are verified via local unit, CLI seed-disjointness, and `--dry-run` checks without running heavy external GPU matrices or fabricating `evidence/benchmark-v2/` metrics.

---

## 3. Resolution & Verification Summary

1. **PR #5 Conflict Resolution & Merge (`727eb82`)**:
   - Merged `swarm/e2e-suite` (`f0ce5d5`), `origin/main` (`9c6c3fb`), and `origin/bridge-3d` (`4f10906`) into `ilyas/dev`, resolving all 3-way conflicts in favor of the hardened `v2` modules while preserving all `docs/ru/examples/*.json` plans and `export_ai_mistakes_3d.py` defaults.
   - Verified GitHub reported `"mergeable": "MERGEABLE"` and `"mergeStateStatus": "CLEAN"` on PR #5 and merged cleanly into `Musacss/fulfillment-cell-bench:main` (`727eb82`).
2. **PRs [#7](https://github.com/Musacss/fulfillment-cell-bench/pull/7), [#8](https://github.com/Musacss/fulfillment-cell-bench/pull/8), and [#9](https://github.com/Musacss/fulfillment-cell-bench/pull/9) Studio, CI & Diagnostics Integration (`47578f5`, `f7ba322`, and `fix/studio-diagnostics-hud` -> `main`)**:
   - Merged `origin/codex/replay-studio` (`d346831`), preserving all 15 frozen GLB SHA-256 hashes and sacred `v1` 7-key `Event` replay parsing (`studio/src/replay.js`).
   - Wired English Studio UI labels, auto-detected relative `./3d-pack/index.json` on HTTPS hosts, and prioritized external `diagnostics.json` (`robotization-bench.quarter-diagnostics.v1`) loading with `diagnostics_version: 1` fallback normalization in `studio/src/data.js` and `studio/src/app.js` (`WIN` / `NO WIN` / `FAIL` badge, `reward_fraction`, `key_mistakes` / `hud_callout`, `active_mistakes`, `SLA Alert` badge, and interactive `highlight_ticks` seek buttons), backed by regression assertions in `scripts/check_replay_player.mjs`.
   - Added `.github/workflows/deploy-studio-pages.yml` checking `.build_type == "workflow"` so CI builds and uploads the Pages artifact cleanly on every `main` push and runs `actions/deploy-pages@v4` whenever GitHub Actions Pages is enabled.
3. **Live Static 3D Showcase Deployment**:
   - Exported the 33-run `v1` + 12-week `v2` + multi-model AI-mistakes pack (`artifacts/3d-pack/`, `quarterly_available: true`, 48 comparisons) and built `studio/dist/`.
   - Deployed via Pull Requests [#1](https://github.com/FreezeGu/4-horses-replay-studio/pull/1) (`981a8f7`) and [#2](https://github.com/FreezeGu/4-horses-replay-studio/pull/2) (`fix/pages-diagnostics-hud` -> `main`) to `https://freezegu.github.io/4-horses-replay-studio/` (`3d-pack/index.json`), updated conflict-free upstream Pull Request [#1](https://github.com/Musacss/4-horses-replay-studio/pull/1) (`MERGEABLE` / `CLEAN`), and verified CORS playback on `https://musacss.github.io/4-horses-replay-studio/?index=https://freezegu.github.io/4-horses-replay-studio/3d-pack/index.json` plus local servers (`127.0.0.1:8765` and `127.0.0.1:5173`).
