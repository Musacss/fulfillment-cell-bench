---
name: hardening-rl-environments
description: Use when designing, modifying, packaging, or auditing RL environments, agent benchmarks, MCP episode servers, Harbor containers, or reward functions where coding agents have shell access or reward-hacking incentives
---

# Hardening RL Environments

## Overview

Coding agents (OpenCode, Claude Code, SWE agents) have bash and filesystem access inside benchmark containers. **Violating the letter of isolation or reward bounds is violating the spirit of the benchmark.** If an agent can read simulator source, reset stdio state, or score credit by stopping early, the benchmark measures white-box scripting rather than decision-making.

## Iron Rules

1. **Zero White-Box Simulator Leakage:** Never copy simulator, scenario-generator, or grading code (`engine.py`, `scenarios.py`, `grading.py`, `reference.py`, `seeds.json`) into directories readable by the agent user (`environment/public/`).
   - Isolate the environment backend via a privilege-separated daemon (`root`-owned `0700` directory + Unix socket / localhost HTTP started in container entrypoint before dropping to unprivileged `USER agent`) or separate container.
   - Give `USER agent` only `AGENT.md`, public `SPEC.md`/`CONTRACTS.md`, public history JSONs, and a thin stateless MCP stdio-to-socket client.
2. **Non-Resettable Rollout Budgets:** Enforce hard `max_pilots` / query budgets inside the privileged daemon's persistent state file—never in a child stdio process that the agent can restart to reset counters.
3. **Coupled State Carryover (Multi-Period Rollouts):** When wrapping single-step simulators into multi-week/quarterly horizons, carry state across periods (unfinished backlog, equipment wear/commissioning jam spikes, cumulative CapEx/depreciation, crew hiring/retraining friction) while preserving exact per-period event schemas (`Event` JSONL) for downstream 3D/UI replay.
4. **Exact Rational Reward & Adversarial Hierarchy:** Compute rewards in `fractions.Fraction` (convert to `float` only at final Harbor `reward.txt` serialization). Verify strict inequality across mandatory baselines:
   `0 == invalid == nop == stop_early < infeasible < feasible_no_win <= manual_baseline < reference_win`

## Core Packaging Pattern

```dockerfile
# environment/Dockerfile — privilege-separated black-box MCP inside Harbor
RUN useradd -m -u 1000 agent && mkdir -p /srv/bench_daemon /logs/artifacts \
    && chown root:root /srv/bench_daemon && chmod 0700 /srv/bench_daemon \
    && chown -R agent:agent /app /logs
COPY daemon/ /srv/bench_daemon/
COPY public/ /app/
# Entrypoint starts root-owned daemon on /run/bench.sock (0666), then execs su -s /bin/bash agent
```

## Quick Reference: Mandatory Exploit Probes

| Probe | Expected Score | Catches |
|---|---|---|
| `nop` (no file / no tool call) | `0/1` | Default credit / stale artifact reuse |
| `stop_early` (`stop({})` or partial horizon) | `0/1` | Avoiding late-quarter waves or penalties |
| `buy_capex_idle` (buy robot, run manual route) | `< manual_baseline` | Fake automation credit without throughput share |
| `unstaffed_deadlock` (robot jams, no zone-3 helper) | `< 9/100` (infeasible) | Zero-labor loophole via starved queues |
| `stdio_restart_flood` (respawn MCP client 50×) | `BudgetExceeded` after `max_pilots` | Stateless stdio counter reset |

## Rationalization Table

| Excuse | Reality |
|---|---|
| "`grade.py` runs in a separate container, so copying `engine.py` to `public/` is safe" | OpenCode imports `engine.py` + `scenarios.py` in Python and brute-forces 10,000 plans in 3 seconds, collapsing **The Gap** to zero. |
| "Local stdio `mcp_server.py` resets on restart anyway, so leave `pilot` unlimited" | Unlimited free rollouts turn sequential planning under uncertainty into exhaustive grid search. Persist `pilot_count` behind a privileged socket. |
| "Running 12 independent shifts is faster than carrying over state" | Independent shifts decouple week $t$ decisions from week $t+1$ consequences—static plans remain optimal. |
| "Downstream 3D/UI needs custom quarterly events" | Keep per-shift `Event` streams untouched; emit a period manifest pointing to standard per-shift JSONL traces. |

## Red Flags — STOP and Fix Design

- Copying simulator, RNG `draw()`, or `grading.py` into `/app` or `environment/public/`
- Storing `pilot_count` only in memory inside a user-spawned stdio process
- Using `float` division inside `grading.py` before ranking or win checks
- Claiming reward integrity without testing `nop`, `stop_early`, and `buy_capex_idle`
- Modifying existing shift `Event` fields and breaking 3D/replay consumers
