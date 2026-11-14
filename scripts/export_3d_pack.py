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
import re
import stat
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
_MAX_EXTRA_PLAN_BYTES = 65_536
_EXTRA_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_RESERVED_EXTRA_SLUGS = frozenset(
    {
        "v1-manual",
        "v1-candidate",
        "v1-reference",
        "quarterly-manual",
        "quarterly-reference",
        "index",
    }
)


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
    raw_profiles = world["quarterly"].get("week_profiles")
    if isinstance(raw_profiles, Sequence) and len(raw_profiles) == num_weeks:
        peak_weeks = {
            idx
            for idx, prof in enumerate(raw_profiles)
            if isinstance(prof, dict) and int(prof.get("waves", 0)) >= 12
        }
    else:
        peak_weeks = {w for w in (3, 7, 8, 9) if w < num_weeks}

    normal_lean = [[1], [2], [2, 3], [4]]
    peak_lean = [[1], [2], [3], [4], [2, 3]]
    normal_dual_picker = [[1, 2], [1, 2], [2, 3], [3, 4], [4]]
    peak_dual_picker = [[1, 2], [1, 2], [2, 3], [3, 4], [4], [4]]
    off_peak_biweekly = tuple(w for w in range(2, num_weeks, 2) if w not in peak_weeks)

    candidates: list[dict[str, Any]] = []
    for norm_crew, pk_crew in (
        (normal_lean, peak_lean),
        (normal_dual_picker, peak_dual_picker),
    ):
        for maint_schedule in (off_peak_biweekly, (4, 8), (3, 7)):
            maint_set = {w for w in maint_schedule if w < num_weeks}
            candidates.append(
                {
                    "schema_version": 2,
                    "weeks": [
                        {
                            "robot": True,
                            "trays": True,
                            "route": "bypass",
                            "maintenance": (w in maint_set),
                            "workers": [
                                list(z) for z in (pk_crew if w in peak_weeks else norm_crew)
                            ],
                        }
                        for w in range(num_weeks)
                    ],
                }
            )
    for static_dual in (normal_lean, peak_lean, normal_dual_picker, peak_dual_picker):
        maint_set = {w for w in off_peak_biweekly if w < num_weeks}
        candidates.append(
            {
                "schema_version": 2,
                "weeks": [
                    {
                        "robot": True,
                        "trays": True,
                        "route": "bypass",
                        "maintenance": (w in maint_set),
                        "workers": [list(z) for z in static_dual],
                    }
                    for w in range(num_weeks)
                ],
            }
        )

    maint_week = min(7, num_weeks - 1)
    fallback_crews = (
        [[1], [2], [3, 4], [2, 3]],
        [[1], [2], [3], [4], [2, 3]],
        [[1], [2], [3], [3], [4], [2, 3]],
    )
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
    best_key: tuple[bool, bool, Fraction, int] | None = None
    for cand in candidates:
        try:
            parsed = parse_q_fn(cand, world)
        except Exception:
            continue
        if callable(eval_q_fn):
            ev = eval_q_fn(world, cand, dev_seeds)
            cost_tiebreak = (
                -int(ev.metrics.get("total_cost", 0)) if isinstance(ev.metrics, dict) else 0
            )
            key = (
                bool(ev.win),
                bool(ev.feasible),
                Fraction(ev.reward_num, ev.reward_den),
                cost_tiebreak,
            )
        else:
            key = (True, True, Fraction(1, 1), 0)
        if best_key is None or key > best_key:
            best_dict, best_plan, best_key = _to_wire(cand), parsed, key

    if best_dict is None or best_plan is None:
        raise ValueError("Unable to construct a valid quarterly reference plan")
    return best_dict, best_plan, "fallback_phased_template"


def _parse_extra_plan_spec(raw_spec: str | tuple[str, Path]) -> tuple[str, Path]:
    if isinstance(raw_spec, tuple) and len(raw_spec) == 2:
        slug, path_val = raw_spec
        slug_str = str(slug)
        path_str = str(path_val)
    elif isinstance(raw_spec, str):
        if "=" not in raw_spec:
            raise ValueError(f"Invalid --extra-plan {raw_spec!r}; expected <slug>=<plan_json_path>")
        slug_str, path_str = raw_spec.split("=", 1)
    else:
        raise ValueError(f"Invalid --extra-plan specification: {raw_spec!r}")

    if not slug_str or not path_str:
        raise ValueError(f"Invalid --extra-plan {raw_spec!r}; both <slug> and <path> must be non-empty")
    if (
        ".." in slug_str
        or "/" in slug_str
        or "\\" in slug_str
        or not _EXTRA_SLUG_RE.match(slug_str)
    ):
        raise ValueError(
            f"Invalid --extra-plan slug {slug_str!r}; must match ^[A-Za-z0-9][A-Za-z0-9._-]{{0,63}}$ without '..'"
        )
    slug_low = slug_str.lower()
    if slug_low in _RESERVED_EXTRA_SLUGS or any(
        slug_low.startswith(f"{res}-seed") for res in _RESERVED_EXTRA_SLUGS
    ):
        raise ValueError(f"--extra-plan slug {slug_str!r} collides with a reserved bundle name")
    return slug_str, Path(path_str)


def _load_extra_plan_json(plan_path: Path, slug: str) -> dict[str, Any]:
    if plan_path.is_symlink():
        raise ValueError(f"Refusing symlink --extra-plan file for {slug!r}: {plan_path}")
    open_flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(plan_path, open_flags)
    except OSError as exc:
        raise ValueError(f"Cannot open --extra-plan file for {slug!r} ({plan_path}): {exc}") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ValueError(f"--extra-plan path for {slug!r} is not a regular file: {plan_path}")
        if st.st_size > _MAX_EXTRA_PLAN_BYTES:
            raise ValueError(
                f"--extra-plan file for {slug!r} exceeds {_MAX_EXTRA_PLAN_BYTES}-byte limit ({st.st_size} bytes)"
            )
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, _MAX_EXTRA_PLAN_BYTES + 1 - total)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > _MAX_EXTRA_PLAN_BYTES:
                raise ValueError(
                    f"--extra-plan file for {slug!r} exceeds {_MAX_EXTRA_PLAN_BYTES}-byte limit"
                )
        raw_bytes = b"".join(chunks)
    finally:
        os.close(fd)

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"--extra-plan file for {slug!r} is not valid UTF-8: {exc}") from exc

    obj = reporting._strict_json_loads(text)
    if type(obj) is not dict:
        raise ValueError(f"--extra-plan {slug!r} JSON root must be an object")
    schema_ver = obj.get("schema_version")
    if type(schema_ver) is not int or schema_ver not in (1, 2):
        raise ValueError(
            f"--extra-plan {slug!r} has unsupported schema_version {schema_ver!r}; expected integer 1 or 2"
        )
    return obj


def export_pack(
    out_dir: Path,
    seeds: Sequence[int] = (11,),
    extra_plans: Sequence[str | tuple[str, Path]] = (),
) -> dict[str, Any]:
    """Export and self-validate all v1 and (if available) v2 quarterly 3D bundles plus index.json."""
    out_dir = _check_safe_out_dir(out_dir)
    seed_list = _validate_seeds(seeds)

    world = contracts.load_world()
    quarterly_mod = _detect_quarterly(world)
    quarterly_available = quarterly_mod is not None
    quarterly_world_id = (
        world["quarterly"].get("world_id") if quarterly_available else None
    )

    seen_extra_lower: set[str] = set()
    validated_extra_v1: list[tuple[str, dict[str, Any], Any]] = []
    validated_extra_v2: list[tuple[str, dict[str, Any], Any]] = []
    for raw_spec in extra_plans:
        slug, plan_path = _parse_extra_plan_spec(raw_spec)
        slug_low = slug.lower()
        if slug_low in seen_extra_lower:
            raise ValueError(f"Duplicate --extra-plan slug (case-insensitive): {slug!r}")
        seen_extra_lower.add(slug_low)

        raw_obj = _load_extra_plan_json(plan_path, slug)
        schema_ver = raw_obj["schema_version"]
        if schema_ver == 1:
            parsed_v1 = validation.parse_plan(raw_obj, world)
            validated_extra_v1.append((slug, _to_wire(asdict(parsed_v1)), parsed_v1))
        else:
            if not quarterly_available or quarterly_mod is None:
                raise ValueError(
                    f"--extra-plan {slug!r} requires schema_version=2 quarterly support, "
                    "but robotization_bench.quarterly is not available"
                )
            parse_q_fn = getattr(validation, "parse_quarterly_plan", None)
            if not callable(parse_q_fn):
                raise ValueError("validation.parse_quarterly_plan is not available")
            parsed_v2 = parse_q_fn(raw_obj, world)
            validated_extra_v2.append((slug, _to_wire(raw_obj), parsed_v2))

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
            ev_wire = v1_evals[strat]
            runs.append(
                {
                    "id": run_id,
                    "mode": "v1",
                    "strategy": strat,
                    "plan_name": f"v1-{strat}",
                    "label": strat,
                    "extra_plan": False,
                    "seed": seed,
                    "bundle_dir": run_id,
                    "manifest": f"{run_id}/manifest.json",
                    "events": f"{run_id}/events.jsonl",
                    "event_count": audit["event_count"],
                    "summary": audit["summary"],
                    "feasible": bool(ev_wire["feasible"]),
                    "win": bool(ev_wire["win"]),
                    "reward_num": int(ev_wire["reward_num"]),
                    "reward_den": int(ev_wire["reward_den"]),
                    "total_cost": int(econ.total),
                    "evaluation": ev_wire,
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

        prev_v1_extra_slug: str | None = None
        for slug, extra_dict, extra_plan in validated_extra_v1:
            raw = engine.simulate(world, extra_plan, day, trace=True)
            econ = economics.calculate(world, extra_plan, raw)
            ev_seed = _to_wire(asdict(grading.evaluate(world, extra_dict, (day,))))
            run_id = f"{slug}-seed{seed}"
            bundle_dir = out_dir / run_id
            reporting.export_shift_bundle(world, extra_plan, day, raw, econ, bundle_dir)
            audit = validate_shift_bundle(bundle_dir)
            runs.append(
                {
                    "id": run_id,
                    "mode": "v1",
                    "strategy": slug,
                    "plan_name": slug,
                    "label": slug,
                    "extra_plan": True,
                    "seed": seed,
                    "bundle_dir": run_id,
                    "manifest": f"{run_id}/manifest.json",
                    "events": f"{run_id}/events.jsonl",
                    "event_count": audit["event_count"],
                    "summary": audit["summary"],
                    "feasible": bool(ev_seed["feasible"]),
                    "win": bool(ev_seed["win"]),
                    "reward_num": int(ev_seed["reward_num"]),
                    "reward_den": int(ev_seed["reward_den"]),
                    "total_cost": int(econ.total),
                    "evaluation": ev_seed,
                    "evaluation_seeds": [seed],
                }
            )
            comparisons.append(
                {
                    "id": f"v1-manual-vs-{slug}-seed{seed}",
                    "mode": "v1",
                    "seed": seed,
                    "left": f"v1-manual-seed{seed}",
                    "right": run_id,
                }
            )
            comparisons.append(
                {
                    "id": f"v1-{slug}-vs-reference-seed{seed}",
                    "mode": "v1",
                    "seed": seed,
                    "left": run_id,
                    "right": f"v1-reference-seed{seed}",
                }
            )
            if prev_v1_extra_slug is not None:
                comparisons.append(
                    {
                        "id": f"v1-{prev_v1_extra_slug}-vs-{slug}-seed{seed}",
                        "mode": "v1",
                        "seed": seed,
                        "left": f"{prev_v1_extra_slug}-seed{seed}",
                        "right": run_id,
                    }
                )
            prev_v1_extra_slug = slug

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
                ev_q_wire = q_evals[strat]
                reporting.export_quarter_pack(
                    world, q_report, q_plan, pack_subdir, evaluation=ev_q_wire
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
                        "plan_name": f"quarterly-{strat}",
                        "label": strat,
                        "extra_plan": False,
                        "solver_source": solver_src,
                        "seed": seed,
                        "bundle_dir": run_id,
                        "quarter_manifest": f"{run_id}/quarter_manifest.json",
                        "diagnostics_md": f"{run_id}/diagnostics.md",
                        "weeks_count": q_audit["weeks_count"],
                        "summary": q_audit["summary"],
                        "feasible": bool(ev_q_wire["feasible"]) if isinstance(ev_q_wire, dict) else None,
                        "win": bool(ev_q_wire["win"]) if isinstance(ev_q_wire, dict) else None,
                        "reward_num": int(ev_q_wire["reward_num"]) if isinstance(ev_q_wire, dict) else None,
                        "reward_den": int(ev_q_wire["reward_den"]) if isinstance(ev_q_wire, dict) else None,
                        "total_cost": int(q_audit["summary"]["total_cost"]),
                        "evaluation": ev_q_wire,
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

            prev_v2_extra_slug: str | None = None
            for slug, extra_q_dict, extra_q_plan in validated_extra_v2:
                q_report = quarterly_mod.simulate_quarter(world, extra_q_plan, seed, trace=True)
                if callable(eval_q_fn):
                    ev_q_obj = eval_q_fn(world, extra_q_dict, [seed])
                    ev_q_seed = (
                        _to_wire(asdict(ev_q_obj))
                        if hasattr(ev_q_obj, "__dataclass_fields__")
                        else _to_wire(ev_q_obj)
                    )
                else:
                    ev_q_seed = None
                run_id = f"{slug}-seed{seed}"
                pack_subdir = out_dir / run_id
                reporting.export_quarter_pack(
                    world, q_report, extra_q_plan, pack_subdir, evaluation=ev_q_seed
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
                        "strategy": slug,
                        "plan_name": slug,
                        "label": slug,
                        "extra_plan": True,
                        "seed": seed,
                        "bundle_dir": run_id,
                        "quarter_manifest": f"{run_id}/quarter_manifest.json",
                        "diagnostics_md": f"{run_id}/diagnostics.md",
                        "weeks_count": q_audit["weeks_count"],
                        "summary": q_audit["summary"],
                        "feasible": bool(ev_q_seed["feasible"]) if isinstance(ev_q_seed, dict) else None,
                        "win": bool(ev_q_seed["win"]) if isinstance(ev_q_seed, dict) else None,
                        "reward_num": int(ev_q_seed["reward_num"]) if isinstance(ev_q_seed, dict) else None,
                        "reward_den": int(ev_q_seed["reward_den"]) if isinstance(ev_q_seed, dict) else None,
                        "total_cost": int(q_audit["summary"]["total_cost"]),
                        "evaluation": ev_q_seed,
                        "evaluation_seeds": [seed],
                        "weeks": weeks_index,
                    }
                )
                comparisons.append(
                    {
                        "id": f"quarterly-manual-vs-{slug}-seed{seed}",
                        "mode": "quarterly",
                        "seed": seed,
                        "left": f"quarterly-manual-seed{seed}",
                        "right": run_id,
                    }
                )
                comparisons.append(
                    {
                        "id": f"quarterly-{slug}-vs-reference-seed{seed}",
                        "mode": "quarterly",
                        "seed": seed,
                        "left": run_id,
                        "right": f"quarterly-reference-seed{seed}",
                    }
                )
                if prev_v2_extra_slug is not None:
                    comparisons.append(
                        {
                            "id": f"quarterly-{prev_v2_extra_slug}-vs-{slug}-seed{seed}",
                            "mode": "quarterly",
                            "seed": seed,
                            "left": f"{prev_v2_extra_slug}-seed{seed}",
                            "right": run_id,
                        }
                    )
                prev_v2_extra_slug = slug

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
        rest = stripped[1:]
        if not (rest and rest.isascii() and rest.isdigit()):
            raise ValueError(f"invalid integer seed {token!r}")
        val = int(stripped, 10)
    else:
        if not (stripped.isascii() and stripped.isdigit()):
            raise ValueError(f"invalid integer seed {token!r}")
        val = int(stripped, 10)
    if val < 0:
        raise ValueError(f"seed must be >= 0, got {val}")
    return val


class _OrderedSeedAction(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        ops: list[tuple[str, Any]] = list(getattr(namespace, "seed_ops", None) or [])
        ops.append((self.dest, values))
        setattr(namespace, "seed_ops", ops)


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
        dest="seed_single",
        type=str,
        action=_OrderedSeedAction,
        help="Non-negative integer seed to export (repeatable; defaults to 11)",
    )
    ap.add_argument(
        "--seeds",
        dest="seed_group",
        type=str,
        nargs="*",
        action=_OrderedSeedAction,
        help="Space- or comma-separated non-negative integer seeds",
    )
    ap.add_argument(
        "--all-dev-seeds",
        dest="all_dev_seeds",
        nargs=0,
        action=_OrderedSeedAction,
        help="Export all public development_seeds from world_spec.json",
    )
    ap.add_argument(
        "--extra-plan",
        dest="extra_plans",
        action="append",
        default=[],
        metavar="SLUG=PATH",
        help="Additional v1 or v2 plan JSON to export side-by-side (repeatable: <slug>=<path>)",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    seed_ops: list[tuple[str, Any]] = getattr(args, "seed_ops", None) or []
    collected: list[int] = []
    try:
        for op_kind, op_val in seed_ops:
            if op_kind == "seed_single":
                collected.append(_parse_int_token(op_val))
            elif op_kind == "seed_group":
                if not op_val:
                    raise ValueError("--seeds requires at least one non-negative integer seed")
                for group in op_val:
                    parts = [p for p in group.split(",") if p != ""]
                    if not parts:
                        raise ValueError(f"invalid --seeds argument {group!r}")
                    for part in parts:
                        collected.append(_parse_int_token(part))
            elif op_kind == "all_dev_seeds":
                world = contracts.load_world()
                for dev_s in world["development_seeds"]:
                    dev_int = int(dev_s)
                    if dev_int not in collected:
                        collected.append(dev_int)
        if not collected:
            collected = [11]
        seeds = _validate_seeds(collected)
        index = export_pack(args.out, seeds=seeds, extra_plans=args.extra_plans)
    except (ValueError, OSError, contracts.InvalidPlan) as exc:
        ap.error(str(exc))
        return 2

    print(
        f"Exported and validated {len(index['runs'])} 3D bundle(s) for seeds {index['seeds']} into {args.out}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
