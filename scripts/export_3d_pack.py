#!/usr/bin/env python3
"""Export self-validated v1 shift and v2 quarterly 3D replay packs for Musa's Warehouse Showcase."""

import argparse
from collections.abc import Sequence
from dataclasses import asdict
from fractions import Fraction
import importlib
import inspect
import json
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from robotization_bench import (
    contracts,
    economics,
    engine,
    episode,
    grading,
    reference,
    reporting,
    scenarios,
    validation,
)

validate_shift_bundle = reporting.validate_shift_bundle
validate_quarter_pack = reporting.validate_quarter_pack

PACK_INDEX_FORMAT_V1 = "robotization-bench.3d-pack-index.v1"
_PROTECTED_SUBDIRS = ("src", "data", "tests", "integration", "evidence", "docs", "scripts")


def _to_wire(value: Any) -> Any:
    return json.loads(json.dumps(value, allow_nan=False))


def _atomic_write_json(destination: Path, payload: Any) -> None:
    if destination.is_symlink():
        raise ValueError(f"Refusing symlink output file: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", dir=destination.parent, delete=False
    ) as output:
        pending = Path(output.name)
        try:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
            output.close()
            if destination.is_symlink():
                raise ValueError(f"Refusing symlink output file: {destination}")
            pending.replace(destination)
        finally:
            pending.unlink(missing_ok=True)


def _check_safe_out_dir(out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    if out_dir.is_symlink():
        raise ValueError(f"Refusing symlink output directory: {out_dir}")
    if out_dir.exists() and not out_dir.is_dir():
        raise ValueError(f"Output path exists and is not a directory: {out_dir}")

    resolved_root = ROOT.resolve()
    resolved_out = out_dir.resolve(strict=False)
    if resolved_out == resolved_root:
        raise ValueError("Refusing repository root as output directory")
    for sub in _PROTECTED_SUBDIRS:
        protected = (ROOT / sub).resolve(strict=False)
        if resolved_out == protected or resolved_out.is_relative_to(protected):
            raise ValueError(f"Refusing protected repository path as output directory: {out_dir}")

    if out_dir.exists():
        for dirpath, dirnames, filenames in os.walk(out_dir, followlinks=False):
            for name in (*dirnames, *filenames):
                entry = Path(dirpath) / name
                if entry.is_symlink():
                    raise ValueError(f"Refusing symlink inside output directory: {entry}")
    return out_dir


def _validate_seeds(seeds: Sequence[int]) -> list[int]:
    seed_list = list(seeds)
    if not seed_list:
        raise ValueError("At least one non-negative integer seed is required")
    for s in seed_list:
        if type(s) is not int or s < 0:
            raise ValueError(f"Seed must be a non-negative integer, got {s!r}")
    if len(set(seed_list)) != len(seed_list):
        raise ValueError(f"Duplicate seeds are not allowed: {seed_list!r}")
    return seed_list


def _solve_v1_reference(world: dict[str, Any], dev_days: tuple[Any, ...]) -> tuple[dict[str, Any], Any]:
    sig = inspect.signature(episode.Episode)
    try:
        ep = episode.Episode(world, dev_days)
        solved = reference.solve(ep)
    except RuntimeError:
        if "max_pilots" in sig.parameters:
            ep = episode.Episode(world, dev_days, max_pilots=64)
            solved = reference.solve(ep)
        else:
            raise
    plan = validation.parse_plan(solved, world)
    return _to_wire(asdict(plan)), plan


def _detect_quarterly(world: dict[str, Any]) -> Any:
    if "quarterly" not in world or not isinstance(world["quarterly"], dict):
        return None
    try:
        quarterly_mod = importlib.import_module("robotization_bench.quarterly")
    except ImportError:
        return None
    if not callable(getattr(quarterly_mod, "simulate_quarter", None)):
        return None
    return quarterly_mod


def _solve_quarterly_reference(
    world: dict[str, Any], quarterly_mod: Any
) -> tuple[dict[str, Any], Any, str]:
    parse_q_fn = getattr(validation, "parse_quarterly_plan")
    dev_seeds = list(world["development_seeds"])

    # 1. Primary path (Post-M3): QuarterlyEpisode + polymorphic reference.solve()
    q_ep_cls = getattr(episode, "QuarterlyEpisode", None)
    if q_ep_cls is not None:
        try:
            ep_q = q_ep_cls(world, dev_seeds)
            solved_q = reference.solve(ep_q)
            if isinstance(solved_q, dict) and solved_q.get("schema_version") == 2:
                parsed_q = parse_q_fn(solved_q, world)
                return _to_wire(solved_q), parsed_q, "reference.solve"
        except Exception:
            pass

    # 2. Graceful fallback (Post-M1 / Pre-M3 when reference.py is still v1-only)
    num_weeks = int(world["quarterly"].get("weeks", 12))
    maint_week = min(7, num_weeks - 1)
    fallback_crews = (
        [[1], [2], [3, 4], [2, 3]],
        [[1], [2], [3], [4], [2, 3]],
        [[1], [2], [3], [3], [4], [2, 3]],
    )
    candidates: list[dict[str, Any]] = []
    for crew in fallback_crews:
        candidates.append(
            {
                "schema_version": 2,
                "weeks": [
                    {
                        "robot": True,
                        "trays": True,
                        "route": "bypass",
                        "maintenance": (w == maint_week),
                        "workers": [list(z) for z in crew],
                    }
                    for w in range(num_weeks)
                ],
            }
        )
    if callable(getattr(quarterly_mod, "manual_quarterly_value", None)):
        candidates.append(quarterly_mod.manual_quarterly_value(world))

    eval_q_fn = getattr(grading, "evaluate_quarterly", None)
    best_dict: dict[str, Any] | None = None
    best_plan: Any = None
    best_key: tuple[bool, bool, Fraction] | None = None
    for cand in candidates:
        try:
            parsed = parse_q_fn(cand, world)
        except Exception:
            continue
        if callable(eval_q_fn):
            ev = eval_q_fn(world, cand, dev_seeds)
            key = (bool(ev.win), bool(ev.feasible), Fraction(ev.reward_num, ev.reward_den))
        else:
            key = (True, True, Fraction(1, 1))
        if best_key is None or key > best_key:
            best_dict, best_plan, best_key = _to_wire(cand), parsed, key

    if best_dict is None or best_plan is None:
        raise ValueError("Unable to construct a valid quarterly reference plan")
    return best_dict, best_plan, "fallback_phased_template"


def export_pack(out_dir: Path, seeds: Sequence[int] = (11,)) -> dict[str, Any]:
    """Export and self-validate all v1 and (if available) v2 quarterly 3D bundles plus index.json."""
    out_dir = _check_safe_out_dir(out_dir)
    seed_list = _validate_seeds(seeds)

    world = contracts.load_world()
    dev_seeds = [int(s) for s in world["development_seeds"]]
    dev_days = tuple(scenarios.generate(world, s) for s in dev_seeds)

    manual_dict = grading.manual_value()
    manual_plan = validation.parse_plan(manual_dict, world)

    cand_text = (ROOT / "data" / "plans" / "candidate.json").read_text(encoding="utf-8")
    cand_plan = validation.decode_plan(cand_text, world)
    cand_dict = _to_wire(asdict(cand_plan))

    ref_dict, ref_plan = _solve_v1_reference(world, dev_days)

    v1_strategies = (
        ("manual", manual_dict, manual_plan),
        ("candidate", cand_dict, cand_plan),
        ("reference", ref_dict, ref_plan),
    )
    v1_evals = {
        strat: _to_wire(asdict(grading.evaluate(world, p_dict, dev_days)))
        for strat, p_dict, _ in v1_strategies
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []

    for seed in seed_list:
        day = scenarios.generate(world, seed)
        for strat, _p_dict, p_obj in v1_strategies:
            raw = engine.simulate(world, p_obj, day, trace=True)
            econ = economics.calculate(world, p_obj, raw)
            run_id = f"v1-{strat}-seed{seed}"
            bundle_dir = out_dir / run_id
            reporting.export_shift_bundle(world, p_obj, day, raw, econ, bundle_dir)
            audit = validate_shift_bundle(bundle_dir)
            runs.append(
                {
                    "id": run_id,
                    "mode": "v1",
                    "strategy": strat,
                    "label": strat,
                    "seed": seed,
                    "bundle_dir": run_id,
                    "manifest": f"{run_id}/manifest.json",
                    "events": f"{run_id}/events.jsonl",
                    "event_count": audit["event_count"],
                    "summary": audit["summary"],
                    "evaluation": v1_evals[strat],
                    "evaluation_seeds": list(dev_seeds),
                }
            )
        comparisons.append(
            {
                "id": f"v1-manual-vs-reference-seed{seed}",
                "mode": "v1",
                "seed": seed,
                "left": f"v1-manual-seed{seed}",
                "right": f"v1-reference-seed{seed}",
            }
        )

    quarterly_mod = _detect_quarterly(world)
    quarterly_available = quarterly_mod is not None
    quarterly_world_id = (
        world["quarterly"].get("world_id") if quarterly_available else None
    )

    if quarterly_available and quarterly_mod is not None:
        parse_q_fn = getattr(validation, "parse_quarterly_plan")
        eval_q_fn = getattr(grading, "evaluate_quarterly", None)

        manual_q_dict = quarterly_mod.manual_quarterly_value(world)
        manual_q_plan = parse_q_fn(manual_q_dict, world)
        ref_q_dict, ref_q_plan, ref_q_source = _solve_quarterly_reference(world, quarterly_mod)

        expected_weeks = int(world["quarterly"].get("weeks", 12))
        q_strategies = (
            ("manual", manual_q_dict, manual_q_plan, "manual_quarterly_value"),
            ("reference", ref_q_dict, ref_q_plan, ref_q_source),
        )
        q_evals: dict[str, Any] = {}
        for strat, q_dict, _q_plan, _src in q_strategies:
            if callable(eval_q_fn):
                ev_q = eval_q_fn(world, q_dict, dev_seeds)
                q_evals[strat] = _to_wire(asdict(ev_q)) if hasattr(ev_q, "__dataclass_fields__") else _to_wire(ev_q)
            else:
                q_evals[strat] = None

        for seed in seed_list:
            for strat, _q_dict, q_plan, solver_src in q_strategies:
                q_report = quarterly_mod.simulate_quarter(world, q_plan, seed, trace=True)
                run_id = f"quarterly-{strat}-seed{seed}"
                pack_subdir = out_dir / run_id
                reporting.export_quarter_pack(
                    world, q_report, q_plan, pack_subdir, evaluation=q_evals[strat]
                )
                q_audit = validate_quarter_pack(pack_subdir, expected_weeks=expected_weeks)
                weeks_index = [
                    {
                        "week": w["week"],
                        "label": w["label"],
                        "bundle_dir": f"{run_id}/{w['bundle_dir']}",
                        "manifest": f"{run_id}/{w['bundle_dir']}/manifest.json",
                        "events": f"{run_id}/{w['bundle_dir']}/events.jsonl",
                        "event_count": w["event_count"],
                    }
                    for w in q_audit["weeks"]
                ]
                runs.append(
                    {
                        "id": run_id,
                        "mode": "quarterly",
                        "strategy": strat,
                        "label": strat,
                        "solver_source": solver_src,
                        "seed": seed,
                        "bundle_dir": run_id,
                        "quarter_manifest": f"{run_id}/quarter_manifest.json",
                        "weeks_count": q_audit["weeks_count"],
                        "summary": q_audit["summary"],
                        "evaluation": q_evals[strat],
                        "evaluation_seeds": list(dev_seeds),
                        "weeks": weeks_index,
                    }
                )
            comparisons.append(
                {
                    "id": f"quarterly-manual-vs-reference-seed{seed}",
                    "mode": "quarterly",
                    "seed": seed,
                    "left": f"quarterly-manual-seed{seed}",
                    "right": f"quarterly-reference-seed{seed}",
                }
            )

    index_payload = {
        "pack_format": PACK_INDEX_FORMAT_V1,
        "replay_format": reporting.REPLAY_FORMAT_V1,
        "world_id": world["world_id"],
        "quarterly_world_id": quarterly_world_id,
        "quarterly_available": quarterly_available,
        "seeds": seed_list,
        "evaluation_seeds": list(dev_seeds),
        "runs": runs,
        "comparisons": comparisons,
    }
    _atomic_write_json(out_dir / "index.json", index_payload)
    return index_payload


def _parse_int_token(token: str) -> int:
    stripped = token.strip()
    if not stripped or stripped.startswith("+"):
        raise ValueError(f"invalid integer seed {token!r}")
    if stripped.startswith("-"):
        if not stripped[1:].isdigit():
            raise ValueError(f"invalid integer seed {token!r}")
        val = int(stripped, 10)
    else:
        if not stripped.isdigit():
            raise ValueError(f"invalid integer seed {token!r}")
        val = int(stripped, 10)
    if val < 0:
        raise ValueError(f"seed must be >= 0, got {val}")
    return val


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT / "artifacts" / "3d-pack",
        help="Destination directory for exported 3D replay pack",
    )
    ap.add_argument(
        "--seed",
        dest="seed_list",
        type=str,
        action="append",
        default=None,
        help="Non-negative integer seed to export (repeatable; defaults to 11)",
    )
    ap.add_argument(
        "--seeds",
        type=str,
        nargs="*",
        default=None,
        help="Space- or comma-separated non-negative integer seeds",
    )
    ap.add_argument(
        "--all-dev-seeds",
        action="store_true",
        help="Export all public development_seeds from world_spec.json",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    collected: list[int] = []
    try:
        if args.seed_list is not None:
            for raw_tok in args.seed_list:
                collected.append(_parse_int_token(raw_tok))
        if args.seeds is not None:
            if not args.seeds and not collected and not args.all_dev_seeds:
                raise ValueError("--seeds requires at least one non-negative integer seed")
            for group in args.seeds:
                parts = [p for p in group.split(",") if p != ""]
                if not parts:
                    raise ValueError(f"invalid --seeds argument {group!r}")
                for part in parts:
                    collected.append(_parse_int_token(part))
        if args.all_dev_seeds:
            world = contracts.load_world()
            for dev_s in world["development_seeds"]:
                if dev_s not in collected:
                    collected.append(int(dev_s))
        if not collected:
            collected = [11]
        seeds = _validate_seeds(collected)
        index = export_pack(args.out, seeds=seeds)
    except (ValueError, OSError) as exc:
        ap.error(str(exc))
        return 2

    print(
        f"Exported and validated {len(index['runs'])} 3D bundle(s) for seeds {index['seeds']} into {args.out}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
