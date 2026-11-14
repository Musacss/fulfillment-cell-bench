#!/usr/bin/env python3
"""Generate multi-turn SFT trajectories on domain-randomized worlds with 4-way disjoint CSPRNG seeds."""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
import copy
from fractions import Fraction as F
import json
import os
from pathlib import Path
import re
import secrets
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

FAST_CACHE_DEFAULTS = {
    "HF_HOME": "/tmp/fast-cache/hf",
    "UV_CACHE_DIR": "/tmp/fast-cache/uv",
    "VLLM_CACHE_ROOT": "/tmp/fast-cache/vllm",
    "TRITON_CACHE_DIR": "/tmp/fast-cache/triton",
    "TORCHINDUCTOR_CACHE_DIR": "/tmp/fast-cache/inductor",
    "XDG_CACHE_HOME": "/tmp/fast-cache/xdg",
    "TMPDIR": "/tmp/fast-cache/tmp",
}

FALLBACK_MODELS = (
    "Qwen/Qwen3.5-9B",
    "Qwen/Qwen3-8B",
    "Qwen/Qwen2.5-7B-Instruct",
)

_THINK_TAG_SCAN_RE = re.compile(r"</\s*think\s*>|<\s*think\b", flags=re.IGNORECASE)


def configure_fast_cache_env(*, create_dirs: bool = False) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for key, default_val in FAST_CACHE_DEFAULTS.items():
        val = os.environ.get(key, "").strip() or default_val
        os.environ[key] = val
        resolved[key] = val
        if create_dirs:
            try:
                Path(val).mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
    return resolved


def resolve_model_id(
    cli_model_id: str | None = None,
    env_ready_file: str | Path | None = None,
    hf_home: str | Path | None = None,
) -> str:
    if cli_model_id and cli_model_id.strip():
        return cli_model_id.strip()

    env_model = os.environ.get("RL_MODEL_ID", "").strip()
    if env_model:
        return env_model

    ready_path = Path(
        env_ready_file
        or os.environ.get("ENV_READY_FILE", "").strip()
        or "/root/bench/H200_ENV_READY.json"
    )
    if ready_path.is_file():
        try:
            payload = json.loads(ready_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                for key in ("model_id", "base_model", "hf_model_id", "model"):
                    val = payload.get(key)
                    if isinstance(val, str) and val.strip():
                        return val.strip()
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    cache_root = Path(hf_home or os.environ.get("HF_HOME", FAST_CACHE_DEFAULTS["HF_HOME"]))
    for candidate in FALLBACK_MODELS:
        hub_slug = "models--" + candidate.replace("/", "--")
        if (cache_root / "hub" / hub_slug).exists() or (cache_root / hub_slug).exists():
            return candidate

    return FALLBACK_MODELS[0]


def strip_thinking_blocks(text: str) -> str:
    if not isinstance(text, str):
        return ""
    n = len(text)
    pos = 0
    last_out = 0
    depth = 0
    chunks: list[str] = []

    for m in _THINK_TAG_SCAN_RE.finditer(text):
        start = m.start()
        if start < pos:
            continue
        tok = m.group(0)
        if tok.startswith("</"):
            if depth > 0:
                depth -= 1
                if depth == 0:
                    last_out = m.end()
            else:
                chunks.clear()
                last_out = m.end()
            pos = m.end()
        else:
            end_idx = m.end()
            if end_idx < n and text[end_idx] not in ">/ \t\r\n":
                continue
            gt = text.find(">", end_idx)
            if gt == -1:
                if depth == 0:
                    chunks.append(text[last_out:start])
                depth = 1
                break
            if text[end_idx:gt].strip() == "/":
                if depth == 0:
                    chunks.append(text[last_out:start])
                    last_out = gt + 1
                pos = gt + 1
                continue
            if depth == 0:
                chunks.append(text[last_out:start])
            depth += 1
            pos = gt + 1

    if depth == 0:
        chunks.append(text[last_out:])
    return "".join(chunks).strip()


def _validate_seed_pool(name: str, seeds: Iterable[int]) -> list[int]:
    out = list(seeds)
    if any(type(s) is not int for s in out):
        raise ValueError(f"SeedDisjointnessError: {name} must contain strict integers only")
    if len(set(out)) != len(out):
        raise ValueError(f"SeedDisjointnessError: duplicate seeds within {name}")
    return out


def verify_4way_seed_disjointness(
    dev_seeds: Sequence[int],
    replay_seeds: Sequence[int],
    rl_train_seeds: Sequence[int],
    rl_val_seeds: Sequence[int],
    blind_seeds: Sequence[int] | None = None,
) -> None:
    named_pools: list[tuple[str, list[int]]] = [
        ("development_seeds", _validate_seed_pool("development_seeds", dev_seeds)),
        ("replay_seeds", _validate_seed_pool("replay_seeds", replay_seeds)),
        ("rl_train_seeds", _validate_seed_pool("rl_train_seeds", rl_train_seeds)),
        ("rl_val_seeds", _validate_seed_pool("rl_val_seeds", rl_val_seeds)),
    ]
    if blind_seeds is not None:
        named_pools.append(("blind_seeds", _validate_seed_pool("blind_seeds", blind_seeds)))

    for idx in range(len(named_pools)):
        name_a, pool_a = named_pools[idx]
        set_a = set(pool_a)
        for jdx in range(idx + 1, len(named_pools)):
            name_b, pool_b = named_pools[jdx]
            overlap = set_a & set(pool_b)
            if overlap:
                raise ValueError(
                    f"SeedDisjointnessError: overlap between {name_a} and {name_b}: {sorted(overlap)}"
                )


def _fast_disjoint_csprng_seeds(count: int, forbidden: set[int]) -> list[int]:
    chosen: list[int] = []
    taken = set(forbidden)
    while len(chosen) < count:
        cand = secrets.randbelow(1_900_000_000) + 10_000
        if cand not in taken:
            chosen.append(cand)
            taken.add(cand)
    return chosen


def sample_feasible_csprng_seeds(
    world: dict[str, Any],
    *,
    count: int,
    forbidden: set[int],
    max_attempts: int = 512,
    extra_worlds: Sequence[dict[str, Any]] = (),
    extra_world_pools: Sequence[Sequence[int]] = (),
) -> list[int]:
    from robotization_bench.grading import evaluate_quarterly
    from robotization_bench.quarterly import manual_quarterly_value

    if count <= 0:
        raise ValueError("count must be positive")
    manual_plan = manual_quarterly_value(world)
    extra_checks = [(ew, manual_quarterly_value(ew)) for ew in extra_worlds]
    chosen: list[int] = []
    taken = set(forbidden)
    attempts = 0

    while len(chosen) < count and attempts < max_attempts:
        attempts += 1
        cand = secrets.randbelow(1_900_000_000) + 10_000
        if cand in taken:
            continue
        ev = evaluate_quarterly(world, manual_plan, [cand])
        if not (ev.valid and ev.feasible and (ev.reward_num, ev.reward_den) == (1, 5)):
            continue
        ok_extra = True
        for idx_ew, (ew, ew_manual) in enumerate(extra_checks):
            ev_ew = evaluate_quarterly(ew, ew_manual, [cand])
            if not (ev_ew.valid and ev_ew.feasible and (ev_ew.reward_num, ev_ew.reward_den) == (1, 5)):
                ok_extra = False
                break
            if idx_ew < len(extra_world_pools) and extra_world_pools[idx_ew]:
                pooled_ew = evaluate_quarterly(
                    ew, ew_manual, [*extra_world_pools[idx_ew], *chosen, cand]
                )
                if not (
                    pooled_ew.valid
                    and pooled_ew.feasible
                    and (pooled_ew.reward_num, pooled_ew.reward_den) == (1, 5)
                ):
                    ok_extra = False
                    break
        if ok_extra:
            chosen.append(cand)
            taken.add(cand)

    if len(chosen) != count:
        raise RuntimeError(f"Failed to rejection-sample {count} manual-feasible CSPRNG seeds")

    pooled_ev = evaluate_quarterly(world, manual_plan, chosen)
    if not (pooled_ev.valid and pooled_ev.feasible and (pooled_ev.reward_num, pooled_ev.reward_den) == (1, 5)):
        raise RuntimeError("Sampled CSPRNG pool failed pooled manual_quarterly feasibility check")
    return chosen


def perturb_world_for_rl(base_world: dict[str, Any], variant_idx: int) -> dict[str, Any]:
    w = copy.deepcopy(base_world)
    profiles = w["quarterly"]["week_profiles"]
    n_weeks = len(profiles)

    shift = variant_idx % 3
    if shift == 1:
        perm = [0, 2, 3, 1, 4, 6, 7, 8, 9, 5, 10, 11]
        w["quarterly"]["week_profiles"] = [
            {**copy.deepcopy(profiles[src]), "week": idx, "label": f"rl_rot1_{idx}"}
            for idx, src in enumerate(perm[:n_weeks])
        ]
    elif shift == 2:
        for prof in w["quarterly"]["week_profiles"]:
            if prof["waves"] >= 12:
                prof["regular_bps"] = max(5600, prof["regular_bps"] - 200)
                prof["fragile_bps"] = min(2900, prof["fragile_bps"] + 150)
        w["quarterly"]["wear"]["jam_bps_per_wear"] = int(w["quarterly"]["wear"]["jam_bps_per_wear"]) + 25
    return w


def build_sft_trajectory_record(
    world: dict[str, Any],
    eval_seeds: Sequence[int],
    dev_seeds: Sequence[int],
    model_id: str,
    variant_idx: int,
    *,
    max_pilots: int = 16,
) -> dict[str, Any] | None:
    from robotization_bench.episode import QuarterlyEpisode
    from robotization_bench.grading import evaluate_quarterly
    from robotization_bench.reference import solve

    ep = QuarterlyEpisode(world, seeds=dev_seeds, max_pilots=max_pilots)
    winning_plan = solve(ep)
    ev = evaluate_quarterly(world, winning_plan, eval_seeds)
    if not (ev.valid and ev.feasible and ev.win):
        return None

    pilot_entries = [e for e in ep.log if e.get("action") == "pilot" and "plan" in e]
    sample_pilot = pilot_entries[-1] if pilot_entries else {}
    assistant_submit = strip_thinking_blocks(
        json.dumps({"tool": "submit", "arguments": {"plan": winning_plan}}, separators=(",", ":"))
    )

    messages = [
        {
            "role": "system",
            "content": (
                "You are an operations research agent optimizing a 12-week warehouse fulfillment cell "
                "rollout via bounded MCP tools (observe, pilot, submit). Output valid JSON without unclosed <think> tags."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "schema_version": 2,
                    "development_seeds": list(dev_seeds),
                    "quarterly": {
                        "weeks": world["quarterly"]["weeks"],
                        "max_pilots": ep.max_pilots,
                        "money": world["quarterly"]["money"],
                        "wear": world["quarterly"]["wear"],
                        "threshold_bps": world["quarterly"]["threshold_bps"],
                        "week_profiles": world["quarterly"]["week_profiles"],
                    },
                },
                separators=(",", ":"),
            ),
        },
        {
            "role": "assistant",
            "content": json.dumps(
                {
                    "tool": "pilot",
                    "arguments": {"seed": dev_seeds[0], "plan": winning_plan},
                },
                separators=(",", ":"),
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "pilot_result": {
                        "seed": dev_seeds[0],
                        "total_cost": sample_pilot.get("total_cost"),
                        "labor_ticks": sample_pilot.get("labor_ticks"),
                        "totals": sample_pilot.get("totals"),
                    }
                },
                separators=(",", ":"),
            ),
        },
        {
            "role": "assistant",
            "content": assistant_submit,
        },
    ]

    return {
        "schema_version": 2,
        "model_id": model_id,
        "variant_idx": variant_idx,
        "dev_seeds": list(dev_seeds),
        "eval_seeds": list(eval_seeds),
        "pilots_used": ep.pilot_used,
        "feasible": ev.feasible,
        "win": ev.win,
        "reward_num": ev.reward_num,
        "reward_den": ev.reward_den,
        "reward_float": float(F(ev.reward_num, ev.reward_den)),
        "plan": winning_plan,
        "messages": messages,
    }


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "artifacts" / "verda" / "sft_traces.jsonl")
    ap.add_argument("--rl-seeds-out", type=Path, default=REPO_ROOT / "artifacts" / "verda" / "rl_seeds.json")
    ap.add_argument("--existing-blind-seeds", type=Path, default=None)
    ap.add_argument("--train-count", type=int, default=16)
    ap.add_argument("--val-count", type=int, default=4)
    ap.add_argument("--model-id", type=str, default=None)
    ap.add_argument("--env-ready-file", type=Path, default=None)
    ap.add_argument("--smoke-local", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    fast_cache = configure_fast_cache_env(create_dirs=not args.dry_run)
    model_id = resolve_model_id(args.model_id, args.env_ready_file)

    from robotization_bench.contracts import load_world

    base_world = load_world()
    dev_seeds = list(base_world["development_seeds"])
    replay_seeds = json.loads((REPO_ROOT / "evidence" / "replay_seeds.json").read_text(encoding="utf-8"))

    existing_blind: list[int] | None = None
    if args.existing_blind_seeds is not None and args.existing_blind_seeds.is_file():
        existing_blind = json.loads(args.existing_blind_seeds.read_text(encoding="utf-8"))

    forbidden = set(dev_seeds) | set(replay_seeds) | set(existing_blind or [])
    train_n = 1 if args.dry_run else (min(args.train_count, 2) if args.smoke_local else args.train_count)
    val_n = 1 if args.dry_run else (min(args.val_count, 2) if args.smoke_local else args.val_count)

    if args.dry_run:
        rl_train_seeds = _fast_disjoint_csprng_seeds(max(1, train_n), forbidden)
        rl_val_seeds = _fast_disjoint_csprng_seeds(max(1, val_n), forbidden | set(rl_train_seeds))
        verify_4way_seed_disjointness(dev_seeds, replay_seeds, rl_train_seeds, rl_val_seeds, existing_blind)
        print(
            json.dumps(
                {
                    "status": "dry_run_ok",
                    "model_id": model_id,
                    "fast_cache_env": fast_cache,
                    "rl_train_seeds": rl_train_seeds,
                    "rl_val_seeds": rl_val_seeds,
                    "disjoint_4way": True,
                },
                indent=2,
            )
        )
        return 0

    rl_train_seeds = sample_feasible_csprng_seeds(base_world, count=max(1, train_n), forbidden=forbidden)
    rl_val_seeds = sample_feasible_csprng_seeds(
        base_world, count=max(1, val_n), forbidden=forbidden | set(rl_train_seeds)
    )
    verify_4way_seed_disjointness(dev_seeds, replay_seeds, rl_train_seeds, rl_val_seeds, existing_blind)

    traces: list[dict[str, Any]] = []
    target_traces = max(1, train_n)
    pilot_budget_per_ep = 8 if args.smoke_local else 16
    used_all = set(forbidden) | set(rl_train_seeds) | set(rl_val_seeds)
    candidate_eval_seeds = list(rl_train_seeds)
    attempt = 0

    while len(traces) < target_traces and attempt < target_traces * 5:
        idx = attempt
        attempt += 1
        perturbed = perturb_world_for_rl(base_world, idx)
        if candidate_eval_seeds:
            eval_seed = candidate_eval_seeds.pop(0)
        else:
            eval_seed = sample_feasible_csprng_seeds(
                perturbed,
                count=1,
                forbidden=used_all,
                extra_worlds=[base_world],
                extra_world_pools=[rl_train_seeds],
            )[0]
            rl_train_seeds.append(eval_seed)
            used_all.add(eval_seed)
        episode_dev = sample_feasible_csprng_seeds(
            perturbed,
            count=1 if args.smoke_local else 2,
            forbidden=used_all | {eval_seed},
        )
        used_all.update(episode_dev)
        rec = build_sft_trajectory_record(
            perturbed,
            [eval_seed],
            episode_dev,
            model_id,
            idx,
            max_pilots=pilot_budget_per_ep,
        )
        if rec is not None:
            traces.append(rec)

    if not traces:
        raise RuntimeError("Zero winning SFT trajectories generated")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.rl_seeds_out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(json.dumps(t) for t in traces) + "\n", encoding="utf-8")
    args.rl_seeds_out.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "model_id": model_id,
                "rl_train_seeds": rl_train_seeds,
                "rl_val_seeds": rl_val_seeds,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "model_id": model_id,
                "traces_written": len(traces),
                "out": str(args.out),
                "rl_seeds_out": str(args.rl_seeds_out),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
