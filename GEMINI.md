# Fulfillment-Cell-Bench Workspace Rules (`GEMINI.md`)

## 1. Sandbox-Safe Python & Test Execution
- Always run Python, `pytest`, CLI, and scripts via `.venv/bin/python` (backed by `/opt/homebrew/opt/python@3.12/bin/python3.12`) with `PYTHONPATH=src`:
  - `.venv/bin/python -m pytest -q`
  - `.venv/bin/python scripts/run_bench.py`
  - `PYTHONPATH=src .venv/bin/python -m robotization_bench.cli ...`
- Why: `.venv/bin/python` executes cleanly inside Antigravity's standard terminal sandbox with zero approval prompts.
- Keep `pyproject.toml` `requires-python = ">=3.12,<3.13"` and `.python-version` compatible (`3.12`) so external judges on any `uv` release can reproduce results with one command.

## 2. Sacred 3D Showcase Replay Contract (Musa's Boundary)
- Never break or rename `v1` shift replay structures in `src/robotization_bench/contracts.py` or `reporting.export_events`:
  - `Event` fields: `tick`, `kind` (`arrival`, `start`, `finish`, `break`, `jam`, `assist`, `walk`, `enqueue`, `good`, `escaped`, `scrap`), `order_id`, `resource` (`w0..wN`, `robot`, `null`), `stage` (`1..4`), `attempt` (`0..1`), `end_tick`.
  - Wall-clock animation conversion remains `seconds = tick * tick_seconds` (`30s`).
  - Shift-level `RawReport` and `Economy` JSON keys remain backward-compatible.
- Multi-week / quarterly (`12-week`) rollout mechanics MUST compose deterministic shift-level `simulate()` runs so any week/shift exports a standard `v1`-compatible `events.jsonl` + manifest for 3D playback.

## 3. Anti-Whitebox & Anti-Reward-Hacking Isolation (AfterQuery Rubric)
- The Harbor agent container (`environment/`) MUST NEVER receive simulator internals (`engine.py`, `scenarios.py`, `economics.py`, `grading.py`, `reference.py`) or evaluation `seeds.json`. Agents interact strictly through bounded MCP tools (with explicit pilot/query budgets) and public documentation (`AGENT.md`, `SPEC.md`).
- Authoritative grading runs solely in the isolated `verifier` (`tests/`) using exact `fractions.Fraction` arithmetic before emitting Harbor's scalar `reward.txt`.
- Every reward change MUST pass automated exploit hierarchy checks: `invalid == nop == stop_early == 0 < infeasible < feasible_no_win <= manual_baseline < true_win`.

## 4. Language & Swarm Hygiene
- All judge-facing files (`README.md`, `AGENT.md`, `docs/SPEC.md`, `docs/CONTRACTS.md`, `docs/HARBOR.md`, comparison tables) must be in clear English; preserve Russian team/3D handoff docs under `docs/ru/`.
- Never commit API keys, Verda SSH keys, `.venv/`, or unverified evaluation claims.
- Swarm workers must stay within assigned module ownership, run `.venv/bin/python -m pytest -q`, and report exact exit codes and commit hashes on the Swarm Board.
