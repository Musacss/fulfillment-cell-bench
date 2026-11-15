#!/usr/bin/env python3
"""Run reproducible v2/v1 benchmark comparisons or verify blind evidence offline."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from fractions import Fraction
import hashlib
import json
import math
import multiprocessing
import os
import platform
from pathlib import Path
import re
import stat
import subprocess
import sys
from tempfile import NamedTemporaryFile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from robotization_bench.contracts import Evaluation, InvalidPlan, QuarterlyPlan, World, load_world
from robotization_bench.episode import Episode, QuarterlyEpisode
from robotization_bench.grading import evaluate, evaluate_quarterly, grade_quarters, invalid, manual_value
from robotization_bench.quarterly import manual_quarterly_value, simulate_quarter
from robotization_bench.reference import solve
from robotization_bench.reporting import compare
from robotization_bench.scenarios import generate
from robotization_bench.validation import decode_quarterly_plan, parse_quarterly_plan
from robotization_bench.verifier import verify_file, verify_quarterly_file

_CYRILLIC_RE = re.compile(r"[\u0400-\u04ff]")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_OUTPUT_NAMES = ("submission.json", "episode.json", "comparison.md", "results.json")
_MAX_METADATA_BYTES = 4 * 1024 * 1024
_MAX_JSON_DEPTH = 128
_SEED_COUNT_KEYS = frozenset(
    {
        "num_seeds",
        "n_seeds",
        "total_seeds",
        "max_seeds",
        "min_seeds",
        "count_seeds",
    }
)
_SEED_COUNT_SUFFIXES = (
    "_num_seeds",
    "_n_seeds",
    "_total_seeds",
    "_max_seeds",
    "_min_seeds",
    "_count_seeds",
)
_RUN_EVAL_RELS = (
    "evaluation.json",
    "verifier/evaluation.json",
    "logs/verifier/evaluation.json",
    "artifacts/evaluation.json",
    "logs/artifacts/evaluation.json",
)
_RUN_REWARD_RELS = (
    "reward.txt",
    "verifier/reward.txt",
    "logs/verifier/reward.txt",
    "artifacts/reward.txt",
    "logs/artifacts/reward.txt",
)

_VERIFY_WORLD_REF: World | None = None
_VERIFY_PLANS_REF: list[QuarterlyPlan] | None = None


def _simulate_verify_pair(pair: tuple[int, int]) -> Any:
    plan_idx, seed = pair
    assert _VERIFY_WORLD_REF is not None and _VERIFY_PLANS_REF is not None
    return simulate_quarter(_VERIFY_WORLD_REF, _VERIFY_PLANS_REF[plan_idx], seed)


class BenchError(RuntimeError):
    """Controlled CLI/input/verification error printed without a traceback."""


def _safe_resolve(path: Path, *, label: str = "path") -> Path:
    if "\x00" in str(path):
        raise BenchError(f"{label} contains forbidden null byte")
    try:
        return path.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise BenchError(f"cannot resolve {label} {path}: {exc}") from exc


def _resolve_contained_path(
    ev_root_resolved: Path,
    raw_path: Path,
    label: str,
    *,
    allow_root: bool = False,
) -> Path:
    if "\x00" in str(raw_path):
        raise BenchError(f"{label} contains forbidden null byte")
    if ".." in raw_path.parts:
        raise BenchError(f"{label} escapes evidence root ('..' traversal forbidden): {raw_path}")
    candidate = raw_path if raw_path.is_absolute() else (ev_root_resolved / raw_path)
    strict_ancestors = set(ev_root_resolved.parents)
    parts = candidate.parts
    if parts:
        accum = Path(parts[0])
        for part in parts[1:]:
            accum = accum / part
            if accum in strict_ancestors:
                continue
            try:
                st = os.lstat(accum)
            except FileNotFoundError:
                continue
            except (OSError, ValueError) as exc:
                raise BenchError(f"cannot inspect {label} {raw_path}: {exc}") from exc
            if stat.S_ISLNK(st.st_mode):
                raise BenchError(f"{label} traverses symlink: {accum}")

    resolved = _safe_resolve(candidate, label=label)
    if allow_root:
        if resolved != ev_root_resolved and ev_root_resolved not in resolved.parents:
            raise BenchError(f"{label} escapes evidence root: {raw_path}")
    else:
        if ev_root_resolved not in resolved.parents:
            raise BenchError(f"{label} escapes evidence root: {raw_path}")
    return resolved


def _validate_positive_int_list(values: Any, *, label: str, allow_empty: bool) -> list[int]:
    if type(values) is not list or (not allow_empty and not values):
        kind = "JSON array" if allow_empty else "non-empty JSON array"
        raise BenchError(f"{label} must be a {kind} of positive integers")
    out: list[int] = []
    for idx, item in enumerate(values):
        if not isinstance(item, int) or isinstance(item, bool) or item <= 0:
            raise BenchError(f"{label}[{idx}] must be a positive integer (booleans/floats/non-positive forbidden)")
        out.append(item)
    return out


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise BenchError(f"duplicate JSON key: {key!r}")
        obj[key] = value
    return obj


def _reject_constant(token: str) -> None:
    raise BenchError(f"non-standard JSON constant not allowed: {token}")


def _loads_strict(text: str, *, context: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=_unique_keys, parse_constant=_reject_constant)
    except BenchError:
        raise
    except (ValueError, RecursionError) as exc:
        raise BenchError(f"{context}: malformed JSON ({exc})") from exc


def _read_regular_bytes(path: Path, *, max_bytes: int = _MAX_METADATA_BYTES, label: str = "file") -> bytes:
    if "\x00" in str(path):
        raise BenchError(f"{label} contains forbidden null byte")
    try:
        if path.is_symlink():
            raise BenchError(f"{label} must not be a symlink: {path}")
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except BenchError:
        raise
    except FileNotFoundError as exc:
        raise BenchError(f"{label} not found: {path}") from exc
    except IsADirectoryError as exc:
        raise BenchError(f"{label} is a directory, expected regular file: {path}") from exc
    except (OSError, ValueError) as exc:
        raise BenchError(f"cannot open {label} {path}: {exc}") from exc
    try:
        meta = os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode):
            raise BenchError(f"{label} must be a regular file: {path}")
        if meta.st_size > max_bytes:
            raise BenchError(f"{label} exceeds {max_bytes} bytes: {path}")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise BenchError(f"{label} exceeds {max_bytes} bytes: {path}")
        return data
    except OSError as exc:
        raise BenchError(f"cannot read {label} {path}: {exc}") from exc
    finally:
        os.close(fd)


def _read_regular_json(path: Path, *, max_bytes: int = _MAX_METADATA_BYTES, label: str = "JSON file") -> Any:
    raw = _read_regular_bytes(path, max_bytes=max_bytes, label=label)
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise BenchError(f"{label} is not valid UTF-8: {path}") from exc
    return _loads_strict(text, context=str(path))


def _validate_seed_list(
    seeds: Any,
    *,
    label: str,
    disjoint_from: dict[str, set[int]],
) -> list[int]:
    if type(seeds) is not list or not seeds:
        raise BenchError(f"{label} must be a non-empty JSON array of positive integers")
    for idx, s in enumerate(seeds):
        if type(s) is not int or isinstance(s, bool) or s <= 0:
            raise BenchError(f"{label}[{idx}] must be a positive integer (booleans/floats forbidden)")
    if len(set(seeds)) != len(seeds):
        raise BenchError(f"{label} must contain unique integers (duplicates found)")
    seed_set = set(seeds)
    for pool_name, pool_values in disjoint_from.items():
        overlap = sorted(seed_set & pool_values)
        if overlap:
            raise BenchError(f"{label} overlaps {pool_name}: {overlap[:5]}")
    return list(seeds)


def _atomic_write_text(target: Path, content: str) -> None:
    try:
        if target.is_symlink() or target.parent.is_symlink():
            raise BenchError(f"refusing symlink output: {target}")
        if target.exists() and target.is_dir():
            raise BenchError(f"output path is a directory: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
    except BenchError:
        raise
    except OSError as exc:
        raise BenchError(f"cannot prepare output directory for {target}: {exc}") from exc

    pending: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            pending = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if target.is_symlink():
            raise BenchError(f"refusing symlink output: {target}")
        pending.replace(target)
    except BenchError:
        raise
    except OSError as exc:
        raise BenchError(f"cannot write output file {target}: {exc}") from exc
    finally:
        if pending is not None:
            try:
                pending.unlink(missing_ok=True)
            except OSError:
                pass


def _eur(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    whole, rem = divmod(abs(cents), 100)
    return f"{sign}{whole}.{rem:02d}"


def _cell(text: str) -> str:
    return " ".join(str(text).splitlines()).replace("|", r"\|")


def _render_english_comparison(evaluations: dict[str, Evaluation]) -> str:
    if not evaluations:
        return "No evaluated plans."
    try:
        upstream = compare(evaluations)
    except Exception:
        upstream = ""
    if upstream and not _CYRILLIC_RE.search(upstream):
        return upstream

    rows = [
        "| Plan | Valid | Feasible | Win | Reward | Fraction | Cost (EUR) | Base Cost (EUR) | CapEx (EUR) | Labor Ticks | Auto Packs | Reasons |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    outcomes = [
        "| Plan | Orders | Good | On-Time | Escaped | Scrap | Unfinished |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for label, ev in evaluations.items():
        name = _cell(label)
        frac_str = f"{ev.reward_num}/{ev.reward_den}"
        reward_str = f"{ev.reward_num / ev.reward_den:.6f}"
        reasons = ", ".join(_cell(r) for r in ev.reasons) if ev.reasons else "-"
        if ev.valid:
            m = ev.metrics
            rows.append(
                "| "
                + " | ".join(
                    [
                        name,
                        "yes",
                        "yes" if ev.feasible else "no",
                        "yes" if ev.win else "no",
                        reward_str,
                        frac_str,
                        _eur(m["total_cost"]),
                        _eur(m["base_cost"]),
                        _eur(m["purchase"]),
                        f"{m['labor_ticks']} / {m['base_labor_ticks']}",
                        f"{m['auto_finished']} / {m['pack_finished']}",
                        reasons,
                    ]
                )
                + " |"
            )
            outcomes.append(
                "| "
                + " | ".join(
                    [
                        name,
                        *(
                            str(m[k])
                            for k in ("orders", "good", "on_time", "escaped", "scrap", "unfinished")
                        ),
                    ]
                )
                + " |"
            )
        else:
            rows.append(
                "| "
                + " | ".join(
                    [
                        name,
                        "no",
                        "no",
                        "no",
                        reward_str,
                        frac_str,
                        "-",
                        "-",
                        "-",
                        "-",
                        "-",
                        reasons,
                    ]
                )
                + " |"
            )
    if len(outcomes) > 2:
        rows.extend(["", *outcomes])
    return "\n".join(rows)


def _detect_mode(requested_mode: str, plan_path: Path | None) -> str:
    if requested_mode in ("v1", "v2"):
        return requested_mode
    if plan_path is not None and not plan_path.is_symlink():
        try:
            raw = _read_regular_bytes(plan_path, max_bytes=65_536, label="plan")
            parsed = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_unique_keys,
                parse_constant=_reject_constant,
            )
            if type(parsed) is dict and type(parsed.get("schema_version")) is int and parsed["schema_version"] == 1:
                return "v1"
        except (BenchError, UnicodeError, ValueError, RecursionError, OSError):
            return "v2"
    return "v2"


def _canonical_quarterly_or_none(world: World, plan_path: Path) -> dict[str, Any] | None:
    try:
        raw = _read_regular_bytes(plan_path, max_bytes=16_384, label="plan")
        plan = decode_quarterly_plan(raw.decode("utf-8"), world)
        return json.loads(json.dumps(asdict(plan), allow_nan=False))
    except (BenchError, UnicodeError, InvalidPlan, ValueError, OSError):
        return None


def _git_head() -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    head = proc.stdout.strip()
    return head if proc.returncode == 0 and head else None


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(_read_regular_bytes(path, label=str(path))).hexdigest()


def _samefile_safe(a: Path, b: Path) -> bool:
    try:
        return a.exists() and b.exists() and a.samefile(b)
    except (OSError, ValueError):
        return False


def _run_benchmark(args: argparse.Namespace) -> int:
    out_dir: Path = args.out
    try:
        if "\x00" in str(out_dir):
            raise BenchError("--out contains forbidden null byte")
        if out_dir.is_symlink():
            raise BenchError(f"refusing symlink output directory: {out_dir}")
        if out_dir.exists() and not out_dir.is_dir():
            raise BenchError(f"--out must be a directory path: {out_dir}")
        outputs = [out_dir / name for name in _OUTPUT_NAMES]
        if any(path.is_symlink() for path in outputs):
            raise BenchError("refusing symlink output")
    except BenchError:
        raise
    except (OSError, ValueError) as exc:
        raise BenchError(f"invalid --out path {out_dir}: {exc}") from exc

    out_resolved = _safe_resolve(out_dir, label="--out")
    outputs_resolved = {_safe_resolve(output, label="output path") for output in outputs}
    for source in (args.plan, args.seeds_file):
        if source is not None:
            src_resolved = _safe_resolve(source, label="input path")
            if (
                src_resolved == out_resolved
                or src_resolved in outputs_resolved
                or any(_samefile_safe(output, source) for output in outputs)
            ):
                raise BenchError("input file must not be one of the output files; use another --out directory")

    world = load_world()
    dev_seeds = list(world["development_seeds"])
    if args.seeds_file is not None:
        raw_seeds = _read_regular_json(args.seeds_file, label="--seeds-file")
        seeds = _validate_seed_list(
            raw_seeds,
            label="--seeds-file",
            disjoint_from={"development_seeds": set(dev_seeds)},
        )
        development = False
    else:
        seeds = dev_seeds
        development = True

    mode = _detect_mode(args.mode, args.plan)

    def save_json(name: str, value: Any) -> None:
        _atomic_write_text(out_dir / name, json.dumps(value, ensure_ascii=False, indent=2) + "\n")

    if mode == "v1":
        dev_days = tuple(generate(world, s) for s in dev_seeds)
        eval_days = tuple(generate(world, s) for s in seeds)
        ep = Episode(world, dev_days)
        plan = ep.submit(solve(ep))["plan"]
        save_json("submission.json", plan)
        save_json("episode.json", ep.log)
        results: dict[str, Evaluation] = {
            "manual": evaluate(world, manual_value(), eval_days),
            "reference": verify_file(world, out_dir / "submission.json", eval_days),
        }
        if args.plan is not None:
            results["submitted"] = verify_file(world, args.plan, eval_days)
        table = _render_english_comparison(results)
        print(table)
        _atomic_write_text(out_dir / "comparison.md", table + "\n")

        daily: dict[str, list[dict[str, Any]]] = {}
        for name, plan_val in [("manual", manual_value()), ("reference", plan)]:
            replay = Episode(world, eval_days)
            daily[name] = [replay.pilot(plan_val, s) for s in seeds]

        save_json(
            "results.json",
            {
                "commit": _git_head(),
                "world": world["world_id"],
                "schema_version": 1,
                "world_sha256": _sha256_file(ROOT / "data/world_spec.json"),
                "python": platform.python_version(),
                "runner": "local-python",
                "model": None,
                "pilot_limit": None,
                "pilot_count": sum(e.get("action") == "pilot" for e in ep.log),
                "seeds": seeds,
                "evaluation_seeds": seeds,
                "development": development,
                "results": {k: asdict(v) for k, v in results.items()},
                "days": daily,
            },
        )
        return 0

    manual_q = manual_quarterly_value(world)
    manual_eval = evaluate_quarterly(world, manual_q, seeds)
    if args.plan is not None:
        submitted_eval = verify_quarterly_file(world, args.plan, seeds)
        canonical_sub = _canonical_quarterly_or_none(world, args.plan) if submitted_eval.valid else None
        save_json("submission.json", canonical_sub)
        save_json("episode.json", [])
        results = {"manual": manual_eval, "submitted": submitted_eval}
        pilot_limit: int | None = None
        pilot_count = 0
    else:
        episode = QuarterlyEpisode(world)
        solved_plan = solve(episode)
        receipt = episode.submit(solved_plan)
        canonical_plan = receipt["plan"]
        save_json("submission.json", canonical_plan)
        save_json("episode.json", episode.log)
        ref_eval = evaluate_quarterly(
            world,
            solved_plan if canonical_plan is None else canonical_plan,
            seeds,
        )
        results = {"manual": manual_eval, "reference": ref_eval}
        pilot_limit = episode.max_pilots
        pilot_count = episode.pilot_used

    table = _render_english_comparison(results)
    print(table)
    _atomic_write_text(out_dir / "comparison.md", table + "\n")
    save_json(
        "results.json",
        {
            "commit": _git_head(),
            "world": world["quarterly"]["world_id"],
            "schema_version": 2,
            "world_sha256": _sha256_file(ROOT / "data/world_spec.json"),
            "python": platform.python_version(),
            "runner": "local-python",
            "model": None,
            "pilot_limit": pilot_limit,
            "pilot_count": pilot_count,
            "seeds": seeds,
            "evaluation_seeds": seeds,
            "development": development,
            "results": {k: asdict(v) for k, v in results.items()},
        },
    )
    return 0


def _raise_walk_error(exc: OSError) -> None:
    raise BenchError(f"cannot traverse evidence directory: {exc}") from exc


def _ensure_no_symlinks_under(root_dir: Path) -> None:
    try:
        if "\x00" in str(root_dir):
            raise BenchError("evidence directory path contains forbidden null byte")
        if root_dir.is_symlink():
            raise BenchError(f"evidence directory must not be a symlink: {root_dir}")
        if not root_dir.exists() or not root_dir.is_dir():
            raise BenchError(f"evidence directory does not exist or is not a directory: {root_dir}")
    except BenchError:
        raise
    except (OSError, ValueError) as exc:
        raise BenchError(f"cannot access evidence directory {root_dir}: {exc}") from exc

    for dirpath, dirnames, filenames in os.walk(root_dir, followlinks=False, onerror=_raise_walk_error):
        base = Path(dirpath)
        for name in (*dirnames, *filenames):
            candidate = base / name
            try:
                if candidate.is_symlink():
                    raise BenchError(f"symlink forbidden inside evidence bundle: {candidate}")
            except BenchError:
                raise
            except (OSError, ValueError) as exc:
                raise BenchError(f"cannot inspect evidence entry {candidate}: {exc}") from exc


def _collect_digest_and_seed_fields(
    obj: Any,
    *,
    source: str,
    digests: list[tuple[str, str]],
    extra_seed_pools: dict[str, set[int]],
    eval_seed_claims: list[tuple[str, list[int]]],
) -> None:
    stack: list[tuple[Any, int]] = [(obj, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > _MAX_JSON_DEPTH:
            raise BenchError(f"{source}: JSON nesting depth exceeds maximum ({_MAX_JSON_DEPTH})")
        if isinstance(current, dict):
            for key, value in current.items():
                if key in ("blind_seeds_sha256", "seeds_sha256"):
                    if type(value) is not str or not _HEX64_RE.match(value.lower()):
                        raise BenchError(f"{source}: invalid {key} hex digest {value!r}")
                    digests.append((f"{source}:{key}", value.lower()))
                elif isinstance(key, str) and (
                    key.lower() in _SEED_COUNT_KEYS or key.lower().endswith(_SEED_COUNT_SUFFIXES)
                ):
                    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                        continue
                    if type(value) is list:
                        validated = _validate_positive_int_list(value, label=f"{source}:{key}", allow_empty=True)
                        extra_seed_pools.setdefault(f"meta:{source}:{key}", set()).update(validated)
                    else:
                        raise BenchError(
                            f"{source}:{key} must be a non-negative integer seed count, got {value!r}"
                        )
                elif isinstance(key, str) and (
                    key.lower().endswith("_seeds")
                    or key in ("rl_train_seeds", "rl_val_seeds", "train_seeds", "val_seeds")
                ):
                    low_key = key.lower()
                    if low_key in ("blind_seeds", "evaluation_seeds", "eval_seeds"):
                        validated = _validate_positive_int_list(value, label=f"{source}:{key}", allow_empty=False)
                        eval_seed_claims.append((f"{source}:{key}", validated))
                    else:
                        validated = _validate_positive_int_list(value, label=f"{source}:{key}", allow_empty=True)
                        extra_seed_pools.setdefault(f"meta:{source}:{key}", set()).update(validated)
                elif isinstance(value, (dict, list)):
                    stack.append((value, depth + 1))
        elif isinstance(current, list):
            for item in current:
                if isinstance(item, (dict, list)):
                    stack.append((item, depth + 1))


def _classify_role_tokens(raw_value: str, *, context: str) -> str | None:
    norm = re.sub(r"[^a-z0-9]+", "_", raw_value.lower()).strip("_")
    if not norm:
        return None
    tokens = set(norm.split("_"))
    matched_specific: list[str] = []

    if (
        "nop" in tokens
        or norm == "no_op"
        or norm.startswith("no_op_")
        or norm.endswith("_no_op")
        or "_no_op_" in norm
    ):
        matched_specific.append("nop")
    if "stop_early" in norm or norm == "stop" or ("stop" in tokens and "early" in tokens):
        matched_specific.append("stop_early")
    if bool(tokens & {"infeasible", "deadlock", "understaffed", "unstaffed"}) or any(
        s in norm for s in ("deadlock", "understaffed", "unstaffed", "infeasible")
    ):
        matched_specific.append("infeasible")
    if "feasible_no_win" in norm or norm == "no_win" or "buy_capex_idle" in norm or "capex_idle" in norm:
        matched_specific.append("feasible_no_win")
    if bool(tokens & {"reference", "oracle"}) or norm in {"reference_optimizer", "solver"}:
        matched_specific.append("reference")
    if "grpo" in tokens or "post_rl" in norm or "post_sft" in norm or "sft_grpo" in norm or norm in {
        "rl",
        "post_trained",
        "trained_open",
    }:
        matched_specific.append("post_rl")
    if (
        "base_rl" in norm
        or "base_open" in norm
        or "pre_rl" in norm
        or norm in {"base", "base_model", "untrained_open"}
        or norm.startswith("base_")
        or norm.endswith("_base")
        or ("base" in tokens and bool(tokens & {"qwen", "qwen2", "qwen3", "llama", "mistral", "open"}))
    ):
        matched_specific.append("base_open")
    if norm in {"manual", "manual_baseline", "baseline_manual"} or (
        norm.startswith("manual_") and not bool(tokens & {"gemini", "gpt", "claude"})
    ):
        matched_specific.append("manual")

    if len(matched_specific) > 1:
        raise BenchError(f"conflicting role tokens in {context} {raw_value!r}: {', '.join(matched_specific)}")
    if len(matched_specific) == 1:
        return matched_specific[0]
    if bool(tokens & {"frontier", "opencode", "gemini", "gpt", "claude"}):
        return "frontier"
    return None


def _classify_run_role(
    run_id: str,
    manifest_entry: dict[str, Any] | None,
    *,
    run_dir_slug: str | None = None,
) -> str:
    id_role = _classify_role_tokens(run_id, context="run_id")
    id_specific = id_role if id_role not in (None, "frontier") else None

    dir_role = _classify_role_tokens(run_dir_slug, context="run_dir") if run_dir_slug else None
    dir_specific = dir_role if dir_role not in (None, "frontier") else None

    if id_specific is not None and dir_specific is not None and id_specific != dir_specific:
        raise BenchError(
            f"conflicting role classification for run {run_id!r}: run_id implies {id_specific!r} but run directory implies {dir_specific!r}"
        )
    slug_specific = id_specific if id_specific is not None else dir_specific

    manifest_specific: str | None = None
    manifest_has_frontier = False
    if manifest_entry is not None:
        for field in ("role", "category", "kind", "tier"):
            if field not in manifest_entry or manifest_entry[field] is None:
                continue
            raw = manifest_entry[field]
            if type(raw) is not str:
                raise BenchError(f"run {run_id!r} manifest field {field!r} must be a string, got {raw!r}")
            if not raw.strip():
                continue
            field_role = _classify_role_tokens(raw.strip(), context=f"manifest.json:{run_id}.{field}")
            if field_role == "frontier":
                manifest_has_frontier = True
            elif field_role is not None:
                if manifest_specific is not None and manifest_specific != field_role:
                    raise BenchError(
                        f"conflicting manifest role metadata for run {run_id!r}: {manifest_specific!r} vs {field_role!r}"
                    )
                manifest_specific = field_role

    if slug_specific is not None and manifest_specific is not None and slug_specific != manifest_specific:
        raise BenchError(
            f"conflicting role classification for run {run_id!r}: run/directory implies {slug_specific!r} but manifest specifies {manifest_specific!r}"
        )
    if slug_specific is not None:
        return slug_specific
    if manifest_specific is not None:
        return manifest_specific
    if id_role == "frontier" or dir_role == "frontier" or manifest_has_frontier:
        return "frontier"
    return "candidate"


def _infer_run_dir_from_artifact(ev_root_resolved: Path, artifact_path: Path) -> Path:
    parent = artifact_path.parent
    if parent != ev_root_resolved and parent.name in ("artifacts", "verifier"):
        if parent.parent != ev_root_resolved and parent.parent.name == "logs":
            return parent.parent.parent
        return parent.parent
    return parent


def _default_submission_for_run_dir(run_dir: Path) -> Path:
    for rel in ("submission.json", "artifacts/submission.json", "logs/artifacts/submission.json"):
        cand = run_dir / rel
        if cand.exists():
            return cand
    return run_dir / "submission.json"


def _resolve_manifest_rel_file(
    ev_root_resolved: Path,
    run_dir: Path,
    rel_value: Any,
    *,
    label: str,
) -> Path:
    if type(rel_value) is not str or not rel_value.strip():
        raise BenchError(f"{label} must be a non-empty relative path string, got {rel_value!r}")
    if "\x00" in rel_value:
        raise BenchError(f"{label} contains forbidden null byte")
    rel_clean = rel_value.strip()
    if Path(rel_clean).is_absolute():
        raise BenchError(f"{label} escapes evidence root (absolute path forbidden): {rel_clean}")
    primary = _resolve_contained_path(ev_root_resolved, ev_root_resolved / rel_clean, label, allow_root=False)
    if not primary.exists() and run_dir != ev_root_resolved:
        alt = _resolve_contained_path(ev_root_resolved, run_dir / rel_clean, label, allow_root=False)
        if alt.exists():
            return alt
    return primary


def _parse_reward_txt(path: Path) -> float:
    raw = _read_regular_bytes(path, max_bytes=4096, label="reward.txt")
    try:
        text = raw.decode("utf-8").strip()
    except UnicodeError as exc:
        raise BenchError(f"invalid UTF-8 in {path}") from exc
    parts = text.split()
    if len(parts) != 1:
        raise BenchError(f"malformed reward.txt (expected single scalar float): {path}")
    try:
        val = float(parts[0])
    except ValueError as exc:
        raise BenchError(f"non-numeric reward.txt in {path}: {parts[0]!r}") from exc
    if not math.isfinite(val):
        raise BenchError(f"non-finite float in {path}: {parts[0]!r}")
    return val


def _verify_claim_dict(
    claim: dict[str, Any],
    actual: Evaluation,
    *,
    source: str,
    require_core_fields: bool,
) -> bool:
    has_reward_claim = False
    if require_core_fields:
        for req in ("feasible", "win", "reward_num", "reward_den"):
            if req not in claim:
                raise BenchError(f"{source}: missing required field {req!r}")

    if "valid" in claim:
        if type(claim["valid"]) is not bool or claim["valid"] != actual.valid:
            raise BenchError(f"{source}: valid mismatch (claimed={claim['valid']!r}, actual={actual.valid!r})")
    if "feasible" in claim:
        if type(claim["feasible"]) is not bool or claim["feasible"] != actual.feasible:
            raise BenchError(
                f"{source}: feasible mismatch (claimed={claim['feasible']!r}, actual={actual.feasible!r})"
            )
    if "win" in claim:
        if type(claim["win"]) is not bool or claim["win"] != actual.win:
            raise BenchError(f"{source}: win mismatch (claimed={claim['win']!r}, actual={actual.win!r})")
    if "reward_num" in claim or "reward_den" in claim:
        if "reward_num" not in claim or "reward_den" not in claim:
            raise BenchError(f"{source}: both reward_num and reward_den must be provided together")
        r_num = claim["reward_num"]
        r_den = claim["reward_den"]
        if (
            type(r_num) is not int
            or isinstance(r_num, bool)
            or type(r_den) is not int
            or isinstance(r_den, bool)
            or r_den <= 0
        ):
            raise BenchError(f"{source}: invalid rational reward ({r_num!r}/{r_den!r})")
        if r_num != actual.reward_num or r_den != actual.reward_den:
            raise BenchError(
                f"{source}: exact reward mismatch (claimed={r_num}/{r_den}, actual={actual.reward_num}/{actual.reward_den})"
            )
        has_reward_claim = True
    if "metrics" in claim and claim["metrics"] is not None:
        if type(claim["metrics"]) is not dict or claim["metrics"] != actual.metrics:
            raise BenchError(f"{source}: metrics mismatch against deterministic recomputation")
    if "reward" in claim and claim["reward"] is not None:
        val = claim["reward"]
        if type(val) not in (int, float) or isinstance(val, bool) or not math.isfinite(float(val)):
            raise BenchError(f"{source}: invalid scalar reward {val!r}")
        expected_f = float(Fraction(actual.reward_num, actual.reward_den))
        if abs(float(val) - expected_f) > 1e-12:
            raise BenchError(f"{source}: scalar reward mismatch (claimed={val}, actual={expected_f})")
        has_reward_claim = True
    return has_reward_claim


def _verify_evidence(evidence_dir: Path) -> int:
    _ensure_no_symlinks_under(evidence_dir)
    ev_root_resolved = _safe_resolve(evidence_dir, label="evidence directory")
    world = load_world()

    direct_blind = ev_root_resolved / "blind_seeds.json"
    blind_matches = [
        _resolve_contained_path(ev_root_resolved, p, "blind_seeds.json")
        for p in sorted(ev_root_resolved.rglob("blind_seeds.json"))
    ]
    if direct_blind.exists():
        if len(blind_matches) > 1:
            raise BenchError(f"multiple blind_seeds.json files found under {evidence_dir}")
        blind_path = _resolve_contained_path(ev_root_resolved, direct_blind, "blind_seeds.json")
    else:
        if not blind_matches:
            raise BenchError(f"missing blind_seeds.json in {evidence_dir}")
        if len(blind_matches) > 1:
            raise BenchError(f"multiple blind_seeds.json files found under {evidence_dir}")
        blind_path = blind_matches[0]

    blind_bytes = _read_regular_bytes(blind_path, label="blind_seeds.json")
    actual_sha256 = hashlib.sha256(blind_bytes).hexdigest()
    try:
        blind_raw = _loads_strict(blind_bytes.decode("utf-8"), context=str(blind_path))
    except UnicodeError as exc:
        raise BenchError(f"blind_seeds.json is not valid UTF-8: {blind_path}") from exc

    manifest_path = ev_root_resolved / "manifest.json"
    manifest_data: dict[str, Any] | None = None
    if manifest_path.exists():
        loaded_manifest = _read_regular_json(manifest_path, label="manifest.json")
        if type(loaded_manifest) is not dict:
            raise BenchError("manifest.json root must be a JSON object")
        manifest_data = loaded_manifest

    discovered_runs: list[dict[str, Any]] = []
    covered_run_dirs: set[Path] = set()
    covered_submissions: set[Path] = set()
    manifest_has_runs = manifest_data is not None and "runs" in manifest_data

    if manifest_has_runs:
        assert manifest_data is not None
        raw_runs = manifest_data["runs"]
        manifest_entries: list[tuple[str, dict[str, Any]]] = []
        if type(raw_runs) is list:
            for idx, entry in enumerate(raw_runs):
                if type(entry) is not dict:
                    raise BenchError(f"manifest.json runs[{idx}] must be an object")
                run_id = entry.get("id") or entry.get("name") or entry.get("slug") or f"run_{idx}"
                if type(run_id) is not str or not run_id.strip():
                    raise BenchError(f"manifest.json runs[{idx}] has invalid id")
                manifest_entries.append((run_id.strip(), entry))
        elif type(raw_runs) is dict:
            for run_id, entry in raw_runs.items():
                if type(entry) is not dict:
                    raise BenchError(f"manifest.json runs[{run_id!r}] must be an object")
                manifest_entries.append((str(run_id), entry))
        else:
            raise BenchError("manifest.json 'runs' must be a list or object")

        for run_id, entry in manifest_entries:
            if "\x00" in run_id:
                raise BenchError(f"run id contains forbidden null byte: {run_id!r}")
            dir_key_present = any(k in entry and entry[k] is not None for k in ("dir", "run_dir", "path"))
            if dir_key_present:
                rel_dir = next(entry[k] for k in ("dir", "run_dir", "path") if k in entry and entry[k] is not None)
                if (
                    type(rel_dir) is not str
                    or not rel_dir.strip()
                    or "\x00" in rel_dir
                    or Path(rel_dir.strip()).is_absolute()
                ):
                    raise BenchError(f"run '{run_id}' has invalid directory field: {rel_dir!r}")
                run_dir = _resolve_contained_path(
                    ev_root_resolved,
                    ev_root_resolved / rel_dir.strip(),
                    f"run '{run_id}' directory",
                    allow_root=True,
                )
            else:
                run_dir = _resolve_contained_path(
                    ev_root_resolved,
                    ev_root_resolved / "runs" / run_id,
                    f"run '{run_id}' directory",
                    allow_root=False,
                )

            sub_field = entry.get("submission", entry.get("submission_path", "__UNSET__"))
            if sub_field is None:
                sub_path = _resolve_contained_path(
                    ev_root_resolved,
                    run_dir / "submission.json",
                    f"run '{run_id}' submission",
                    allow_root=False,
                )
                allow_missing_sub = True
            elif sub_field == "__UNSET__":
                sub_path = _resolve_contained_path(
                    ev_root_resolved,
                    _default_submission_for_run_dir(run_dir),
                    f"run '{run_id}' submission",
                    allow_root=False,
                )
                allow_missing_sub = False
            elif type(sub_field) is str and sub_field.strip():
                sub_path = _resolve_manifest_rel_file(
                    ev_root_resolved,
                    run_dir,
                    sub_field,
                    label=f"run '{run_id}' submission",
                )
                allow_missing_sub = False
            else:
                raise BenchError(f"run '{run_id}' has invalid submission field: {sub_field!r}")

            covered_run_dirs.add(run_dir)
            covered_submissions.add(sub_path)
            discovered_runs.append(
                {
                    "id": run_id,
                    "run_dir": run_dir,
                    "submission_path": sub_path,
                    "allow_missing_sub": allow_missing_sub,
                    "manifest_entry": entry,
                }
            )

        runs_root = ev_root_resolved / "runs"
        if runs_root.is_dir():
            for child in sorted(runs_root.iterdir()):
                if not child.is_dir():
                    continue
                child_resolved = _resolve_contained_path(ev_root_resolved, child, "runs subdirectory")
                if child_resolved not in covered_run_dirs and not any(
                    child_resolved in declared.parents for declared in covered_run_dirs
                ):
                    rel_unlisted = child_resolved.relative_to(ev_root_resolved).as_posix()
                    raise BenchError(f"unlisted run directory on disk not declared in manifest.json: {rel_unlisted}")
    else:
        for sub_raw in sorted(ev_root_resolved.rglob("submission.json")):
            sub_resolved = _resolve_contained_path(ev_root_resolved, sub_raw, "submission.json")
            if sub_resolved in covered_submissions:
                continue
            run_dir = _resolve_contained_path(
                ev_root_resolved,
                _infer_run_dir_from_artifact(ev_root_resolved, sub_resolved),
                "run directory",
                allow_root=True,
            )
            run_id = run_dir.relative_to(ev_root_resolved).as_posix() if run_dir != ev_root_resolved else "root"
            if run_id.startswith("runs/"):
                run_id = run_id[len("runs/") :]
            covered_run_dirs.add(run_dir)
            covered_submissions.add(sub_resolved)
            discovered_runs.append(
                {
                    "id": run_id,
                    "run_dir": run_dir,
                    "submission_path": sub_resolved,
                    "allow_missing_sub": False,
                    "manifest_entry": None,
                }
            )

        runs_root = ev_root_resolved / "runs"
        if runs_root.is_dir():
            for child in sorted(runs_root.iterdir()):
                if not child.is_dir():
                    continue
                child_resolved = _resolve_contained_path(ev_root_resolved, child, "runs subdirectory")
                if child_resolved in covered_run_dirs:
                    continue
                has_verdict = any(
                    (child_resolved / rel).is_file() for rel in (*_RUN_EVAL_RELS, *_RUN_REWARD_RELS)
                )
                if has_verdict:
                    sub_path = _resolve_contained_path(
                        ev_root_resolved,
                        _default_submission_for_run_dir(child_resolved),
                        f"run '{child.name}' submission",
                    )
                    covered_run_dirs.add(child_resolved)
                    covered_submissions.add(sub_path)
                    discovered_runs.append(
                        {
                            "id": child.name,
                            "run_dir": child_resolved,
                            "submission_path": sub_path,
                            "allow_missing_sub": True,
                            "manifest_entry": None,
                        }
                    )

        for verdict_raw in sorted(
            (*ev_root_resolved.rglob("evaluation.json"), *ev_root_resolved.rglob("reward.txt"))
        ):
            verdict_resolved = _resolve_contained_path(ev_root_resolved, verdict_raw, verdict_raw.name)
            inferred_dir = _resolve_contained_path(
                ev_root_resolved,
                _infer_run_dir_from_artifact(ev_root_resolved, verdict_resolved),
                "run directory",
                allow_root=True,
            )
            if inferred_dir in covered_run_dirs:
                continue
            run_id = (
                inferred_dir.relative_to(ev_root_resolved).as_posix()
                if inferred_dir != ev_root_resolved
                else "root"
            )
            if run_id.startswith("runs/"):
                run_id = run_id[len("runs/") :]
            sub_path = _resolve_contained_path(
                ev_root_resolved,
                _default_submission_for_run_dir(inferred_dir),
                f"run '{run_id}' submission",
            )
            covered_run_dirs.add(inferred_dir)
            covered_submissions.add(sub_path)
            discovered_runs.append(
                {
                    "id": run_id,
                    "run_dir": inferred_dir,
                    "submission_path": sub_path,
                    "allow_missing_sub": True,
                    "manifest_entry": None,
                }
            )

    disjoint_pools: dict[str, set[int]] = {"development_seeds": set(world["development_seeds"])}
    repo_replay = ROOT / "evidence" / "replay_seeds.json"
    if repo_replay.is_file() and not repo_replay.is_symlink():
        replay_vals = _validate_positive_int_list(
            _read_regular_json(repo_replay, label="evidence/replay_seeds.json"),
            label="evidence/replay_seeds.json",
            allow_empty=False,
        )
        disjoint_pools["evidence/replay_seeds.json"] = set(replay_vals)

    for seed_file in sorted(ev_root_resolved.rglob("*seeds*.json")):
        seed_resolved = _resolve_contained_path(ev_root_resolved, seed_file, "seed file")
        if seed_resolved == blind_path or seed_resolved in covered_submissions or seed_resolved.name == "submission.json":
            continue
        rel_seed = seed_resolved.relative_to(ev_root_resolved).as_posix()
        parsed_extra = _read_regular_json(seed_resolved, label=rel_seed)
        validated_extra = _validate_positive_int_list(parsed_extra, label=rel_seed, allow_empty=False)
        disjoint_pools.setdefault(f"file:{rel_seed}", set()).update(validated_extra)

    recorded_digests: list[tuple[str, str]] = []
    for sha_candidate in sorted({blind_path.with_suffix(".sha256"), ev_root_resolved / "blind_seeds.sha256"}):
        if sha_candidate.exists():
            sha_resolved = _resolve_contained_path(ev_root_resolved, sha_candidate, "blind_seeds.sha256")
            raw_sha = _read_regular_bytes(sha_resolved, max_bytes=4096, label="blind_seeds.sha256")
            try:
                sha_text = raw_sha.decode("utf-8", errors="strict")
            except UnicodeError as exc:
                raise BenchError(f"blind_seeds.sha256 is not valid UTF-8: {sha_resolved}") from exc
            tokens = sha_text.strip().split()
            if not tokens or not _HEX64_RE.match(tokens[0].lower()):
                raise BenchError(f"malformed SHA-256 file: {sha_resolved}")
            recorded_digests.append((sha_resolved.relative_to(ev_root_resolved).as_posix(), tokens[0].lower()))

    eval_seed_claims: list[tuple[str, list[int]]] = []
    for json_raw in sorted(ev_root_resolved.rglob("*.json")):
        json_resolved = _resolve_contained_path(ev_root_resolved, json_raw, "JSON file")
        if json_resolved == blind_path or json_resolved in covered_submissions or json_resolved.name == "submission.json":
            continue
        rel_label = json_resolved.relative_to(ev_root_resolved).as_posix()
        payload = _read_regular_json(json_resolved, label=rel_label)
        _collect_digest_and_seed_fields(
            payload,
            source=rel_label,
            digests=recorded_digests,
            extra_seed_pools=disjoint_pools,
            eval_seed_claims=eval_seed_claims,
        )

    blind_seeds = _validate_seed_list(
        blind_raw,
        label="blind_seeds.json",
        disjoint_from=disjoint_pools,
    )
    for claim_source, claimed_eval_seeds in eval_seed_claims:
        if claimed_eval_seeds != blind_seeds:
            raise BenchError(f"{claim_source} does not match blind_seeds.json")

    if not recorded_digests:
        raise BenchError("missing blind_seeds.json SHA-256 provenance record (.sha256 or manifest/evaluation digest)")
    for source_label, expected_hex in recorded_digests:
        if expected_hex != actual_sha256:
            raise BenchError(
                f"blind_seeds.json SHA-256 mismatch against {source_label}: expected {expected_hex}, got {actual_sha256}"
            )

    if not discovered_runs:
        raise BenchError(f"no verifiable runs discovered under {evidence_dir}")

    invalid_probe = invalid("invalid probe")
    nop_probe = invalid("missing submission")
    stop_probe = evaluate_quarterly(world, None, blind_seeds)
    baseline_plan = parse_quarterly_plan(manual_quarterly_value(world), world)

    unique_plans: list[QuarterlyPlan] = [baseline_plan]
    unique_plan_index: dict[QuarterlyPlan, int] = {baseline_plan: 0}
    for item in discovered_runs:
        sp = item["submission_path"]
        try:
            st_pre = os.lstat(sp)
        except OSError:
            continue
        if not stat.S_ISLNK(st_pre.st_mode) and stat.S_ISREG(st_pre.st_mode) and st_pre.st_size <= 16_384:
            try:
                raw_b = _read_regular_bytes(sp, max_bytes=16_384, label="predecode")
                dec = decode_quarterly_plan(raw_b.decode("utf-8"), world)
            except Exception:
                continue
            if dec not in unique_plan_index:
                unique_plan_index[dec] = len(unique_plans)
                unique_plans.append(dec)

    quarters_by_plan: dict[QuarterlyPlan, tuple[Any, ...]] = {}
    tasks = [(p_idx, s) for p_idx in range(len(unique_plans)) for s in blind_seeds]
    cpu_workers = min(8, os.cpu_count() or 1, len(tasks))
    used_parallel = False
    if cpu_workers > 1 and len(tasks) >= 8 and "fork" in multiprocessing.get_all_start_methods():
        global _VERIFY_WORLD_REF, _VERIFY_PLANS_REF
        _VERIFY_WORLD_REF = world
        _VERIFY_PLANS_REF = unique_plans
        try:
            ctx = multiprocessing.get_context("fork")
            with ProcessPoolExecutor(max_workers=cpu_workers, mp_context=ctx) as pool:
                sim_results = list(
                    pool.map(_simulate_verify_pair, tasks, chunksize=max(1, len(tasks) // (cpu_workers * 2)))
                )
            n_seeds = len(blind_seeds)
            for p_idx, p_obj in enumerate(unique_plans):
                quarters_by_plan[p_obj] = tuple(sim_results[p_idx * n_seeds : (p_idx + 1) * n_seeds])
            used_parallel = True
        except (OSError, PermissionError, RuntimeError):
            used_parallel = False
        finally:
            _VERIFY_WORLD_REF = None
            _VERIFY_PLANS_REF = None

    if not used_parallel:
        for p_obj in unique_plans:
            quarters_by_plan[p_obj] = tuple(simulate_quarter(world, p_obj, s) for s in blind_seeds)

    baseline_quarters = quarters_by_plan[baseline_plan]
    manual_eval = grade_quarters(world, baseline_plan, baseline_quarters, baseline_quarters)
    manual_reward = Fraction(manual_eval.reward_num, manual_eval.reward_den)
    if not (
        Fraction(0, 1)
        == Fraction(invalid_probe.reward_num, invalid_probe.reward_den)
        == Fraction(nop_probe.reward_num, nop_probe.reward_den)
        == Fraction(stop_probe.reward_num, stop_probe.reward_den)
        < manual_reward
        <= Fraction(1, 5)
        and manual_eval.valid
        and manual_eval.feasible
        and not manual_eval.win
    ):
        raise BenchError("baseline probe hierarchy failed on blind_seeds")

    eval_cache: dict[bytes, Evaluation] = {}
    plan_eval_cache: dict[QuarterlyPlan, Evaluation] = {
        p_obj: (
            manual_eval
            if p_obj == baseline_plan
            else grade_quarters(world, p_obj, quarters_by_plan[p_obj], baseline_quarters)
        )
        for p_obj in unique_plans
    }
    verified_artifacts: set[Path] = set()
    summary_rows: list[tuple[str, str, Evaluation, Fraction]] = []
    role_rewards: dict[str, list[Fraction]] = {}

    for item in discovered_runs:
        run_id = item["id"]
        run_dir = item["run_dir"]
        sub_path = item["submission_path"]
        manifest_entry = item["manifest_entry"]
        rel_run_dir = run_dir.relative_to(ev_root_resolved).as_posix() if run_dir != ev_root_resolved else None
        if rel_run_dir is not None and rel_run_dir.startswith("runs/"):
            rel_run_dir = rel_run_dir[len("runs/") :]
        role = _classify_run_role(run_id, manifest_entry, run_dir_slug=rel_run_dir)

        try:
            st = os.lstat(sub_path)
        except FileNotFoundError:
            st = None
        except (OSError, ValueError) as exc:
            raise BenchError(f"cannot stat submission {sub_path}: {exc}") from exc

        if st is None:
            if not item["allow_missing_sub"] and role not in ("nop", "stop_early"):
                raise BenchError(f"run '{run_id}' missing submission file: {sub_path}")
            actual = invalid("missing submission")
        else:
            if stat.S_ISLNK(st.st_mode):
                raise BenchError(f"{run_id}/submission.json must not be a symlink: {sub_path}")
            if not stat.S_ISREG(st.st_mode):
                raise BenchError(f"{run_id}/submission.json must be a regular file: {sub_path}")
            verified_artifacts.add(sub_path)
            if st.st_size <= 16_384:
                raw_sub = _read_regular_bytes(sub_path, max_bytes=16_384, label=f"{run_id}/submission.json")
                if raw_sub in eval_cache:
                    actual = eval_cache[raw_sub]
                else:
                    try:
                        decoded_plan = decode_quarterly_plan(raw_sub.decode("utf-8"), world)
                    except (UnicodeError, InvalidPlan, ValueError, RecursionError):
                        actual = verify_quarterly_file(world, sub_path, blind_seeds)
                    else:
                        if decoded_plan in plan_eval_cache:
                            actual = plan_eval_cache[decoded_plan]
                        else:
                            cand_quarters = tuple(simulate_quarter(world, decoded_plan, s) for s in blind_seeds)
                            actual = grade_quarters(world, decoded_plan, cand_quarters, baseline_quarters)
                            plan_eval_cache[decoded_plan] = actual
                    eval_cache[raw_sub] = actual
            else:
                actual = verify_quarterly_file(world, sub_path, blind_seeds)

        reward_claims_verified = 0
        if manifest_entry is not None:
            if _verify_claim_dict(
                manifest_entry,
                actual,
                source=f"manifest.json:{run_id}",
                require_core_fields=False,
            ):
                reward_claims_verified += 1

        eval_paths: list[Path] = []
        if manifest_entry is not None:
            for k in ("evaluation", "evaluation_path"):
                if k in manifest_entry and manifest_entry[k] is not None:
                    p = _resolve_manifest_rel_file(
                        ev_root_resolved,
                        run_dir,
                        manifest_entry[k],
                        label=f"run '{run_id}' {k}",
                    )
                    if p not in eval_paths:
                        eval_paths.append(p)
        for rel in _RUN_EVAL_RELS:
            cand = run_dir / rel
            if cand.exists():
                cand_resolved = _resolve_contained_path(
                    ev_root_resolved,
                    cand,
                    f"run '{run_id}' evaluation.json",
                )
                if cand_resolved not in eval_paths:
                    eval_paths.append(cand_resolved)

        for ev_path in eval_paths:
            ev_doc = _read_regular_json(ev_path, label=f"{run_id}/evaluation.json")
            if type(ev_doc) is not dict:
                raise BenchError(f"{ev_path}: evaluation.json must be a JSON object")
            inner = ev_doc.get("evaluation") if isinstance(ev_doc.get("evaluation"), dict) else ev_doc
            assert isinstance(inner, dict)
            _verify_claim_dict(inner, actual, source=str(ev_path), require_core_fields=True)
            verified_artifacts.add(ev_path)
            reward_claims_verified += 1

        reward_paths: list[Path] = []
        if manifest_entry is not None:
            for k in ("reward_file", "reward_path", "reward_txt"):
                if k in manifest_entry and manifest_entry[k] is not None:
                    p = _resolve_manifest_rel_file(
                        ev_root_resolved,
                        run_dir,
                        manifest_entry[k],
                        label=f"run '{run_id}' {k}",
                    )
                    if p not in reward_paths:
                        reward_paths.append(p)
        for rel in _RUN_REWARD_RELS:
            cand = run_dir / rel
            if cand.exists():
                cand_resolved = _resolve_contained_path(
                    ev_root_resolved,
                    cand,
                    f"run '{run_id}' reward.txt",
                )
                if cand_resolved not in reward_paths:
                    reward_paths.append(cand_resolved)

        expected_float = float(Fraction(actual.reward_num, actual.reward_den))
        for rw_path in reward_paths:
            claimed_float = _parse_reward_txt(rw_path)
            if abs(claimed_float - expected_float) > 1e-12:
                raise BenchError(
                    f"{rw_path}: reward.txt float mismatch (claimed={claimed_float}, expected={expected_float})"
                )
            verified_artifacts.add(rw_path)
            reward_claims_verified += 1

        if reward_claims_verified == 0:
            raise BenchError(
                f"run '{run_id}' has no authoritative reward claim (evaluation.json, reward.txt, or manifest reward_num/reward_den/reward)"
            )

        r_frac = Fraction(actual.reward_num, actual.reward_den)
        if not actual.valid:
            if r_frac != Fraction(0, 1) or actual.feasible or actual.win:
                raise BenchError(f"run '{run_id}' violates invalid-plan reward invariant")
        elif not actual.feasible:
            if not (Fraction(0, 1) < r_frac <= Fraction(9, 100)) or actual.win:
                raise BenchError(f"run '{run_id}' violates infeasible reward band (0, 9/100]: {r_frac}")
        elif not actual.win:
            if not (Fraction(1, 10) < r_frac <= Fraction(1, 5)):
                raise BenchError(f"run '{run_id}' violates feasible-no-win band (1/10, 1/5]: {r_frac}")
        else:
            if not (max(manual_reward, Fraction(1, 5)) < r_frac < Fraction(1, 1)):
                raise BenchError(f"run '{run_id}' violates win reward band (1/5, 1): {r_frac}")

        if role in ("nop", "stop_early"):
            if actual.valid or r_frac != Fraction(0, 1):
                raise BenchError(
                    f"exploit hierarchy violation: '{run_id}' ({role}) must have valid=False and reward=0/1, got valid={actual.valid}, reward={r_frac}"
                )
        elif role == "infeasible":
            if not (actual.valid and not actual.feasible and Fraction(0, 1) < r_frac <= Fraction(9, 100)):
                raise BenchError(
                    f"exploit hierarchy violation: '{run_id}' (infeasible) must score in (0, 9/100], got {r_frac}"
                )
        elif role == "feasible_no_win":
            if not (actual.valid and actual.feasible and not actual.win and Fraction(1, 10) < r_frac <= Fraction(1, 5)):
                raise BenchError(
                    f"exploit hierarchy violation: '{run_id}' (feasible_no_win) must score in (1/10, 1/5], got {r_frac}"
                )
        elif role == "manual":
            if not (actual.valid and actual.feasible and not actual.win and r_frac == manual_reward):
                raise BenchError(
                    f"exploit hierarchy violation: '{run_id}' (manual) must equal manual_reward={manual_reward}, got {r_frac}"
                )
        elif role in ("reference", "post_rl"):
            if not (actual.valid and actual.feasible and actual.win and r_frac > max(manual_reward, Fraction(1, 5))):
                raise BenchError(
                    f"exploit hierarchy violation: '{run_id}' ({role}) must win with reward > {max(manual_reward, Fraction(1, 5))}, got win={actual.win}, reward={r_frac}"
                )

        role_rewards.setdefault(role, []).append(r_frac)
        summary_rows.append((run_id, role, actual, r_frac))

    for art_raw in sorted(
        (
            *ev_root_resolved.rglob("submission.json"),
            *ev_root_resolved.rglob("evaluation.json"),
            *ev_root_resolved.rglob("reward.txt"),
        )
    ):
        art_resolved = _resolve_contained_path(ev_root_resolved, art_raw, art_raw.name)
        if art_resolved not in verified_artifacts:
            rel_art = art_resolved.relative_to(ev_root_resolved).as_posix()
            raise BenchError(f"unverified or unlisted run artifact on disk: {rel_art}")

    if "post_rl" in role_rewards and "base_open" in role_rewards:
        mean_post = sum(role_rewards["post_rl"], Fraction(0, 1)) / len(role_rewards["post_rl"])
        mean_base = sum(role_rewards["base_open"], Fraction(0, 1)) / len(role_rewards["base_open"])
        if not (mean_post > mean_base):
            raise BenchError(
                f"RL improvement check failed: mean post_rl ({float(mean_post):.6f}) <= mean base_open ({float(mean_base):.6f})"
            )

    lines = [
        f"Evidence Verification: {evidence_dir}",
        f"- blind_seeds.json SHA-256: {actual_sha256} (VERIFIED across {len(recorded_digests)} record(s))",
        f"- Blind seed count: {len(blind_seeds)} (disjoint from {len(disjoint_pools)} non-eval pool(s))",
        f"- Baseline probes: invalid=0/1, nop=0/1, stop_early=0/1 < manual={manual_reward} ({float(manual_reward):.4f})",
        "",
        "| Run | Role | Valid | Feasible | Win | Fraction | Reward | Parity |",
        "|---|---|---|---|---|---:|---:|---|",
    ]
    for run_id, role, ev, r_frac in summary_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(run_id),
                    role,
                    "yes" if ev.valid else "no",
                    "yes" if ev.feasible else "no",
                    "yes" if ev.win else "no",
                    f"{ev.reward_num}/{ev.reward_den}",
                    f"{float(r_frac):.6f}",
                    "EXACT",
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append(f"VERIFIED {len(summary_rows)} run(s) — HIERARCHY_INTACT: True")
    print("\n".join(lines))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "artifacts" / "local")
    ap.add_argument("--seeds-file", type=Path, help="Operator JSON array of disjoint evaluation seeds")
    ap.add_argument("--plan", type=Path, help="Optional external plan file for independent grading")
    ap.add_argument(
        "--mode",
        choices=("auto", "v1", "v2"),
        default="auto",
        help="Evaluation horizon mode (default: auto — v2 quarterly unless --plan has schema_version=1)",
    )
    ap.add_argument(
        "--verify-evidence",
        type=Path,
        metavar="DIR",
        help="Deterministically re-grade and verify a synced benchmark evidence directory offline",
    )
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        if args.verify_evidence is not None:
            return _verify_evidence(args.verify_evidence)
        return _run_benchmark(args)
    except BenchError as exc:
        print(f"run_bench.py: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
