#!/usr/bin/env python3
"""Export multi-model v2 quarterly 3D replay packs + causal AI mistake diagnostics for Musa's HUD."""

import argparse
from collections.abc import Sequence
from dataclasses import asdict
from fractions import Fraction
import json
import os
from pathlib import Path
import re
import sys
from tempfile import NamedTemporaryFile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from robotization_bench import (
    contracts,
    diagnostics,
    episode,
    grading,
    quarterly,
    reference,
    reporting,
    validation,
)

PACK_INDEX_FORMAT_V1 = "robotization-bench.3d-pack-index.v1"
GUIDE_FILENAME = "AI_MISTAKES_OVERLAY_RU.md"
_PROTECTED_SUBDIRS = ("src", "data", "tests", "integration", "evidence", "docs", "scripts")
_RESERVED_SLUGS = frozenset({"manual", "reference"})
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_TRAINED_TOKENS = (
    "trained",
    "grpo",
    "rl",
    "sft",
    "finetune",
    "fine-tune",
    "fine_tune",
    "distill",
    "lora",
    "posttrain",
)
_MAX_SUBMISSION_BYTES = 262_144


def _to_wire(value: Any) -> Any:
    return json.loads(json.dumps(value, allow_nan=False))


def _atomic_write_text(destination: Path, text: str) -> None:
    if destination.is_symlink():
        raise ValueError(f"Refusing symlink output file: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
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


def _atomic_write_json(destination: Path, payload: Any) -> None:
    text = json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    _atomic_write_text(destination, text)


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


def _classify_role(slug: str, label: str) -> str:
    combined = f"{slug} {label}".lower()
    tokens = set(re.split(r"[^a-z0-9]+", combined))
    for tok in _TRAINED_TOKENS:
        if tok in tokens or (len(tok) >= 4 and tok in combined):
            return "trained"
    return "frontier"


def _read_submission_file(path: Path, world: dict[str, Any]) -> tuple[dict[str, Any], contracts.QuarterlyPlan]:
    if path.is_symlink():
        raise ValueError(f"Refusing symlink submission file: {path}")
    if not path.exists() or not path.is_file():
        raise ValueError(f"Submission file does not exist: {path}")
    size = path.stat().st_size
    if size > _MAX_SUBMISSION_BYTES:
        raise ValueError(f"Submission file exceeds {_MAX_SUBMISSION_BYTES} bytes: {path}")
    text = path.read_text(encoding="utf-8")
    try:
        parsed = validation.decode_quarterly_plan(text, world)
    except contracts.InvalidPlan as exc:
        raise ValueError(f"Invalid quarterly plan in {path}: {exc}") from exc
    return _to_wire(asdict(parsed)), parsed


def _parse_submission_specs(
    specs: Sequence[str], world: dict[str, Any]
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    parsed_list: list[dict[str, Any]] = []
    for raw_spec in specs:
        parts = raw_spec.split("=", 2)
        if len(parts) != 3:
            raise ValueError(
                f"Invalid --submission {raw_spec!r}: expected <slug>=<label>=<path_to_submission.json>"
            )
        slug, label, raw_path = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if not _SLUG_RE.match(slug):
            raise ValueError(
                f"Invalid submission slug {slug!r}: must match {_SLUG_RE.pattern}"
            )
        if slug in _RESERVED_SLUGS:
            raise ValueError(
                f"Submission slug {slug!r} is reserved (manual and reference are auto-included)"
            )
        if slug in seen:
            raise ValueError(f"Duplicate submission slug: {slug!r}")
        if not label:
            raise ValueError(f"Empty label in --submission {raw_spec!r}")
        if not raw_path:
            raise ValueError(f"Empty file path in --submission {raw_spec!r}")

        plan_dict, plan_obj = _read_submission_file(Path(raw_path), world)
        seen.add(slug)
        parsed_list.append(
            {
                "slug": slug,
                "label": label,
                "role": _classify_role(slug, label),
                "source": str(raw_path),
                "plan_dict": plan_dict,
                "plan_obj": plan_obj,
            }
        )
    return parsed_list


def _solve_quarterly_reference(
    world: dict[str, Any],
) -> tuple[dict[str, Any], contracts.QuarterlyPlan, str]:
    dev_seeds = [int(s) for s in world["development_seeds"]]

    # 1. Try polymorphic reference.solve(QuarterlyEpisode(...)) if available
    q_ep_cls = getattr(episode, "QuarterlyEpisode", None)
    if q_ep_cls is not None:
        try:
            ep_q = q_ep_cls(world, dev_seeds)
            solved_q = reference.solve(ep_q)
            if isinstance(solved_q, dict) and solved_q.get("schema_version") == 2:
                parsed_q = validation.parse_quarterly_plan(solved_q, world)
                ev_q = grading.evaluate_quarterly(world, solved_q, dev_seeds)
                if ev_q.win:
                    return _to_wire(asdict(parsed_q)), parsed_q, "reference.solve"
        except Exception:
            pass

    # 2. Phased candidate search over public development_seeds
    profiles = world["quarterly"]["week_profiles"]
    num_weeks = int(world["quarterly"]["weeks"])
    surge_weeks = {
        w
        for w, prof in enumerate(profiles)
        if int(prof.get("waves", 10)) >= 12 or (10_000 - int(prof.get("regular_bps", 7800))) >= 3000
    }
    maint_schedules = (
        {2, 4, 6, 10},
        {2, 5, 6, 10},
        {3, 6, 9},
        {2, 6, 10},
    )
    crew_pairs = (
        ([[1], [2], [2, 3], [4]], [[1], [2], [3], [4], [2, 3]]),
        ([[1], [2], [3, 4], [2, 3]], [[1], [2], [3], [4], [2, 3]]),
        ([[1], [2], [3], [4], [2, 3]], [[1], [2], [3], [4], [2, 3]]),
    )

    best_dict: dict[str, Any] | None = None
    best_plan: contracts.QuarterlyPlan | None = None
    best_key: tuple[bool, bool, Fraction, int] | None = None

    for off_crew, peak_crew in crew_pairs:
        for maint_set in maint_schedules:
            cand = {
                "schema_version": 2,
                "weeks": [
                    {
                        "robot": True,
                        "trays": True,
                        "route": "bypass",
                        "maintenance": (w in maint_set and w not in surge_weeks),
                        "workers": [list(z) for z in (peak_crew if w in surge_weeks else off_crew)],
                    }
                    for w in range(num_weeks)
                ],
            }
            parsed = validation.parse_quarterly_plan(cand, world)
            ev = grading.evaluate_quarterly(world, cand, dev_seeds)
            key = (
                bool(ev.win),
                bool(ev.feasible),
                Fraction(ev.reward_num, ev.reward_den),
                -int(ev.metrics.get("labor_ticks", 0)),
            )
            if best_key is None or key > best_key:
                best_dict, best_plan, best_key = _to_wire(asdict(parsed)), parsed, key

    if best_dict is None or best_plan is None:
        raise ValueError("Unable to construct quarterly reference plan")
    return best_dict, best_plan, "phased_reference_template"


def _load_guide_markdown() -> str:
    repo_guide = ROOT / "docs" / "ru" / GUIDE_FILENAME
    if repo_guide.is_file() and not repo_guide.is_symlink():
        return repo_guide.read_text(encoding="utf-8")
    raise FileNotFoundError(f"Missing canonical HUD guide at {repo_guide}")


def _load_existing_index(index_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[int]]:
    if not index_path.exists():
        return [], [], []
    if index_path.is_symlink() or not index_path.is_file():
        raise ValueError(f"Refusing invalid existing index.json at {index_path}")
    data = json.loads(index_path.read_text(encoding="utf-8"))
    if type(data) is not dict or data.get("pack_format") != PACK_INDEX_FORMAT_V1:
        return [], [], []
    runs = list(data.get("runs", [])) if isinstance(data.get("runs"), list) else []
    comps = list(data.get("comparisons", [])) if isinstance(data.get("comparisons"), list) else []
    seeds = [s for s in data.get("seeds", []) if type(s) is int and s >= 0]
    return runs, comps, seeds


def export_ai_mistakes_pack(
    out_dir: Path,
    *,
    seeds: Sequence[int] = (11,),
    submission_specs: Sequence[str] = (),
) -> dict[str, Any]:
    """Export self-validated quarterly 3D bundles, diagnostics.json, index.json, and HUD guide."""
    out_dir = _check_safe_out_dir(out_dir)
    seed_list = _validate_seeds(seeds)

    world = contracts.load_world()
    if "quarterly" not in world or not isinstance(world["quarterly"], dict):
        raise ValueError("world_spec.json is missing quarterly v2 configuration")

    dev_seeds = [int(s) for s in world["development_seeds"]]
    expected_weeks = int(world["quarterly"]["weeks"])

    custom_subs = _parse_submission_specs(submission_specs, world)

    manual_dict = quarterly.manual_quarterly_value(world)
    manual_plan = validation.parse_quarterly_plan(manual_dict, world)
    ref_dict, ref_plan, ref_source = _solve_quarterly_reference(world)

    entries: list[dict[str, Any]] = [
        {
            "slug": "manual",
            "label": "Manual Baseline (6 Workers)",
            "role": "baseline",
            "source": "manual_quarterly_value",
            "plan_dict": _to_wire(asdict(manual_plan)),
            "plan_obj": manual_plan,
        },
        {
            "slug": "reference",
            "label": "Phased Reference Rollout",
            "role": "reference",
            "source": ref_source,
            "plan_dict": ref_dict,
            "plan_obj": ref_plan,
        },
        *custom_subs,
    ]

    evals_dc: dict[str, contracts.Evaluation] = {}
    evals_wire: dict[str, dict[str, Any]] = {}
    for entry in entries:
        ev = grading.evaluate_quarterly(world, entry["plan_dict"], dev_seeds)
        evals_dc[entry["slug"]] = ev
        evals_wire[entry["slug"]] = _to_wire(asdict(ev))

    guide_text = _load_guide_markdown()
    out_dir.mkdir(parents=True, exist_ok=True)
    prev_runs, prev_comps, prev_seeds = _load_existing_index(out_dir / "index.json")

    new_runs: list[dict[str, Any]] = []
    new_comps: list[dict[str, Any]] = []

    frontier_entries = [e for e in custom_subs if e["role"] == "frontier"]
    trained_entries = [e for e in custom_subs if e["role"] == "trained"]

    for seed in seed_list:
        for entry in entries:
            slug = entry["slug"]
            plan_obj = entry["plan_obj"]
            plan_dict = entry["plan_dict"]
            run_id = f"quarterly-{slug}-seed{seed}"
            pack_subdir = out_dir / run_id

            q_report = quarterly.simulate_quarter(world, plan_obj, seed, trace=True)
            reporting.export_quarter_pack(
                world,
                q_report,
                plan_obj,
                pack_subdir,
                evaluation=evals_wire[slug],
            )

            diag_payload = diagnostics.diagnose_quarter_plan(
                world,
                plan_dict,
                seed,
                reference_plan_dict=ref_dict,
                evaluation=evals_dc[slug],
            )
            _atomic_write_json(pack_subdir / "diagnostics.json", diag_payload)

            q_audit = reporting.validate_quarter_pack(pack_subdir, expected_weeks=expected_weeks)
            status_by_week = {
                tw["week"]: tw["status"] for tw in diag_payload.get("timeline_weeks", [])
            }
            weeks_index = [
                {
                    "week": w["week"],
                    "label": w["label"],
                    "bundle_dir": f"{run_id}/{w['bundle_dir']}",
                    "manifest": f"{run_id}/{w['bundle_dir']}/manifest.json",
                    "events": f"{run_id}/{w['bundle_dir']}/events.jsonl",
                    "event_count": w["event_count"],
                    "status": status_by_week.get(w["week"], "ok"),
                }
                for w in q_audit["weeks"]
            ]
            new_runs.append(
                {
                    "id": run_id,
                    "mode": "quarterly",
                    "strategy": slug,
                    "slug": slug,
                    "role": entry["role"],
                    "label": entry["label"],
                    "solver_source": entry["source"],
                    "seed": seed,
                    "bundle_dir": run_id,
                    "quarter_manifest": f"{run_id}/quarter_manifest.json",
                    "diagnostics": f"{run_id}/diagnostics.json",
                    "diagnostics_headline": diag_payload["overall"]["headline_summary"],
                    "weeks_count": q_audit["weeks_count"],
                    "summary": q_audit["summary"],
                    "evaluation": evals_wire[slug],
                    "evaluation_seeds": list(dev_seeds),
                    "weeks": weeks_index,
                }
            )

        # Pair baseline vs reference
        new_comps.append(
            {
                "id": f"quarterly-manual-vs-reference-seed{seed}",
                "mode": "quarterly",
                "kind": "baseline_vs_reference",
                "seed": seed,
                "left": f"quarterly-manual-seed{seed}",
                "right": f"quarterly-reference-seed{seed}",
            }
        )
        # Pair each frontier / trained submission vs reference
        for sub in custom_subs:
            new_comps.append(
                {
                    "id": f"quarterly-{sub['slug']}-vs-reference-seed{seed}",
                    "mode": "quarterly",
                    "kind": f"{sub['role']}_vs_reference",
                    "seed": seed,
                    "left": f"quarterly-{sub['slug']}-seed{seed}",
                    "right": f"quarterly-reference-seed{seed}",
                }
            )
        # Pair frontier vs trained models directly
        for f_sub in frontier_entries:
            for t_sub in trained_entries:
                new_comps.append(
                    {
                        "id": f"quarterly-{f_sub['slug']}-vs-{t_sub['slug']}-seed{seed}",
                        "mode": "quarterly",
                        "kind": "frontier_vs_trained",
                        "seed": seed,
                        "left": f"quarterly-{f_sub['slug']}-seed{seed}",
                        "right": f"quarterly-{t_sub['slug']}-seed{seed}",
                    }
                )

    new_run_ids = {r["id"] for r in new_runs}
    merged_runs = [r for r in prev_runs if r.get("id") not in new_run_ids] + new_runs

    new_comp_ids = {c["id"] for c in new_comps}
    merged_comps = [c for c in prev_comps if c.get("id") not in new_comp_ids] + new_comps

    merged_seeds = list(seed_list)
    for ps in prev_seeds:
        if ps not in merged_seeds:
            merged_seeds.append(ps)

    _atomic_write_text(out_dir / GUIDE_FILENAME, guide_text)

    index_payload = {
        "pack_format": PACK_INDEX_FORMAT_V1,
        "replay_format": reporting.REPLAY_FORMAT_V1,
        "diagnostics_format": diagnostics.DIAGNOSTICS_FORMAT_V1,
        "guide": GUIDE_FILENAME,
        "world_id": world["world_id"],
        "quarterly_world_id": world["quarterly"].get("world_id"),
        "quarterly_available": True,
        "seeds": merged_seeds,
        "evaluation_seeds": list(dev_seeds),
        "runs": merged_runs,
        "comparisons": merged_comps,
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
        default=ROOT / "artifacts" / "3d-ai-mistakes",
        help="Destination directory for exported multi-model 3D pack + diagnostics",
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
        help="Space- or comma-separated non-negative integer seeds (e.g. --seeds 11 29 47)",
    )
    ap.add_argument(
        "--all-dev-seeds",
        dest="all_dev_seeds",
        nargs=0,
        action=_OrderedSeedAction,
        help="Export all public development_seeds from world_spec.json",
    )
    ap.add_argument(
        "--submission",
        dest="submissions",
        action="append",
        default=[],
        metavar="SLUG=LABEL=PATH",
        help="AI submission JSON to export alongside manual & reference (repeatable; defaults to docs/ru/examples/*.json)",
    )
    ap.add_argument(
        "--no-default-examples",
        action="store_true",
        help="Do not auto-include bundled docs/ru/examples/*.json runs when --submission is omitted",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    submission_specs = list(args.submissions)
    if not submission_specs and not args.no_default_examples:
        examples_dir = ROOT / "docs" / "ru" / "examples"
        default_catalog = (
            ("claude_fable52", "Claude Fable 5.2 (Frontier)", "claude_fable52_frontier.json"),
            ("claude_opus55", "Claude Opus 5.5 (Frontier)", "claude_opus55_frontier.json"),
            ("gemini31_pro", "Gemini 3.1 Pro (Frontier)", "gemini31_pro_frontier.json"),
            ("qwen_grpo", "Qwen 3.5-9B GRPO (Trained)", "qwen35_grpo_win.json"),
            ("qwen_base", "Qwen 3.5-9B Base (Untrained)", "qwen35_base_untrained.json"),
            ("naive_ai", "Naive AI (Wear Blowout)", "naive_ai_wear_fail.json"),
        )
        for slug, label, fname in default_catalog:
            candidate = examples_dir / fname
            if candidate.is_file():
                submission_specs.append(f"{slug}={label}={candidate}")

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
        index = export_ai_mistakes_pack(
            args.out, seeds=seeds, submission_specs=submission_specs
        )
    except (ValueError, OSError) as exc:
        ap.error(str(exc))
        return 2

    print(
        f"Exported and validated {len(index['runs'])} 3D quarterly bundle(s) with AI diagnostics "
        f"for seeds {seeds} into {args.out}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
