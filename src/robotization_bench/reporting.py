"""Display trusted evaluations and export v1 shift and v2 quarterly 3D replay bundles."""

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass, replace
import importlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from .contracts import (
    SCHEMA_VERSION,
    Economy,
    Evaluation,
    Event,
    Plan,
    RawReport,
    Scenario,
    World,
)
from .economics import calculate
from .validation import parse_plan


REPLAY_FORMAT_V1 = "robotization-bench.replay.v1"
QUARTER_PACK_FORMAT_V1 = "robotization-bench.quarter-pack.v1"

_ECONOMY_COST_KEYS_V1 = frozenset(
    {
        "depreciation",
        "service",
        "shifts",
        "overtime",
        "trays",
        "materials",
        "rework",
        "late",
        "unfulfilled",
        "escaped",
    }
)
_RAW_KEYS_V1 = frozenset(
    {
        "schema_version",
        "seed",
        "total",
        "good",
        "on_time",
        "escaped",
        "scrap",
        "unfinished",
        "pack_started",
        "pack_finished",
        "auto_finished",
        "trays_used",
        "rework_started",
        "labor_ticks",
        "overtime_ticks",
        "events",
    }
)
_RAW_INT_KEYS_V1 = _RAW_KEYS_V1 - {"schema_version", "seed", "overtime_ticks", "events"}
_EVENT_KEYS_V1 = frozenset(
    {"tick", "kind", "order_id", "resource", "stage", "attempt", "end_tick"}
)
_EVENT_KINDS_V1 = frozenset(
    {
        "arrival",
        "enqueue",
        "start",
        "walk",
        "jam",
        "assist",
        "break",
        "finish",
        "good",
        "escaped",
        "scrap",
    }
)


_MISSING = object()

_REASONS: dict[str, str] = {
    # Feasibility failure codes (v1 & v2)
    "budget": "CapEx purchase exceeds budget ceiling",
    "volume": "completed good-order volume below SLA threshold",
    "good_each_day": "daily good-order completion rate below SLA threshold",
    "good_each_week": "weekly good-order completion rate below SLA threshold",
    "volume_each_week": "weekly good-order completion rate below SLA threshold",
    "volume_week": "weekly good-order completion rate below SLA threshold",
    "weekly_volume": "weekly good-order completion rate below SLA threshold",
    "good_pooled": "pooled good-order completion rate below SLA threshold",
    "volume_pooled": "pooled good-order completion rate below SLA threshold",
    "pooled_volume": "pooled good-order completion rate below SLA threshold",
    "on_time": "pooled on-time delivery rate below SLA threshold",
    "on_time_pooled": "pooled on-time delivery rate below SLA threshold",
    "quality": "escaped defect rate exceeds SLA maximum",
    "escaped": "escaped defect rate exceeds SLA maximum",
    "escaped_each_day_max": "daily escaped defect rate exceeds SLA maximum",
    "escaped_each_week_max": "weekly escaped defect rate exceeds SLA maximum",
    # Win-condition failure codes (v1 & v2)
    "cost": "operating cost did not beat manual baseline",
    "labor": "active labor ticks did not beat manual baseline",
    "automation": "automated pack share below minimum threshold",
    "auto_pack_pooled_min": "automated pack share below minimum threshold",
    # Invalid / terminal submission shorthand codes
    "nop": "no plan submitted (no-op)",
    "stop_early": "episode stopped without submitting a plan",
    "invalid_plan": "submitted plan failed schema validation",
    "missing submission": "missing submission file",
    "unreadable submission": "unreadable or symlinked submission file",
    "oversized submission": "submission file exceeds 16384-byte limit",
}


def _field(obj: Any, key: str, default: Any = _MISSING) -> Any:
    if isinstance(obj, Mapping):
        if key in obj:
            return obj[key]
    elif hasattr(obj, key):
        return getattr(obj, key)
    if default is _MISSING:
        raise KeyError(f"Missing required field {key!r} on {type(obj).__name__}")
    return default


def _euros(cents: int) -> str:
    whole, fraction = divmod(abs(cents), 100)
    sign = "-" if cents < 0 else ""
    return f"{sign}€{whole:,}.{fraction:02d}"


def _decimal_reward(num: int, den: int, places: int = 6) -> str:
    if den <= 0:
        raise ValueError("reward_den must be positive")
    sign = "-" if num < 0 else ""
    scale = 10**places
    scaled, rem = divmod(abs(num) * scale, den)
    if 2 * rem >= den:
        scaled += 1
    whole, frac = divmod(scaled, scale)
    return f"{sign}{whole}.{frac:0{places}d}"


def _cell(text: str) -> str:
    return " ".join(str(text).splitlines()).replace("\\", r"\\").replace("|", r"\|")


def compare(evaluations: dict[str, Evaluation]) -> str:
    """Render evaluated plans in caller order as English Markdown tables with exact rational rewards."""
    if not evaluations:
        return "No evaluated plans."

    rows = [
        "| Plan | Feasible | Win | Reward | CapEx | Operating Cost | "
        "Savings vs Manual | Labor / Baseline (ticks) | Auto / Total Packs |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    outcomes = [
        "| Plan | Orders | Good | On-Time | Escaped Defects | Scrap | Unfinished |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    notes: list[str] = []
    for label, result in evaluations.items():
        name = _cell(label)
        valid = bool(_field(result, "valid"))
        feasible = bool(_field(result, "feasible"))
        win = bool(_field(result, "win"))
        reward_num = int(_field(result, "reward_num"))
        reward_den = int(_field(result, "reward_den"))
        reward = f"{reward_num}/{reward_den} ({_decimal_reward(reward_num, reward_den)})"
        if valid:
            m = _field(result, "metrics")
            values = [
                name,
                "yes" if feasible else "no",
                "yes" if win else "no",
                reward,
                _euros(int(m["purchase"])),
                _euros(int(m["total_cost"])),
                _euros(int(m["base_cost"]) - int(m["total_cost"])),
                f"{m['labor_ticks']} / {m['base_labor_ticks']}",
                f"{m['auto_finished']} / {m['pack_finished']}",
            ]
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
            values = [name, "invalid", "no", reward, "—", "—", "—", "—", "—"]
        rows.append("| " + " | ".join(values) + " |")
        reasons = _field(result, "reasons", ())
        if isinstance(reasons, str):
            reasons = (reasons,) if reasons else ()
        if reasons:
            details = ", ".join(_REASONS.get(r, _cell(r)) for r in reasons)
            notes.append(f"- {name}: {details}.")
    if len(outcomes) > 2:
        rows.extend(["", *outcomes])
    if notes:
        rows.extend(["", *notes])
    return "\n".join(rows)


def export_events(raw: RawReport, destination: Path) -> None:
    """Write one v1 Event per JSONL line, preserving order within each tick."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    # A reader opening the timeline during an export sees a complete file.
    with NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                            dir=destination.parent, delete=False) as output:
        pending = Path(output.name)
        try:
            for event in raw.events:
                output.write(json.dumps(asdict(event), separators=(",", ":")) + "\n")
            output.close()
            pending.replace(destination)
        finally:
            pending.unlink(missing_ok=True)


def _unique_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"Duplicate JSON object key: {key!r}")
        obj[key] = value
    return obj


def _reject_json_constant(token: str) -> None:
    raise ValueError(f"Invalid JSON constant: {token}")


def _strict_json_loads(text: str) -> Any:
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_json_keys,
            parse_constant=_reject_json_constant,
        )
    except (ValueError, RecursionError) as exc:
        raise ValueError(f"Malformed JSON: {exc}") from exc


def _is_strict_int(value: Any) -> bool:
    return type(value) is int


def _ensure_not_symlink(path: Path) -> None:
    if path.is_symlink():
        raise ValueError(f"Refusing symlink path: {path}")


def _atomic_write_json(destination: Path, payload: Any) -> None:
    _ensure_not_symlink(destination)
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
            _ensure_not_symlink(destination)
            pending.replace(destination)
        finally:
            pending.unlink(missing_ok=True)


def _to_wire(value: Any) -> Any:
    """Convert dataclasses/tuples/dicts into strict JSON-safe dicts/lists (no tuples, no NaN/Inf)."""
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Value is not strict JSON-serializable: {exc}") from exc


def _strip_raw_events(raw: RawReport | Mapping[str, Any]) -> dict[str, Any]:
    """Serialize RawReport to JSON wire dict with events cleared to [] without copying full trace twice."""
    if isinstance(raw, RawReport):
        return _to_wire(replace(raw, events=()))
    if is_dataclass(raw) and not isinstance(raw, type):
        data = asdict(raw)
        data["events"] = []
        return _to_wire(data)
    if isinstance(raw, Mapping):
        data = dict(raw)
        data["events"] = []
        return _to_wire(data)
    raise ValueError(f"Unsupported raw report type: {type(raw).__name__}")


def _coerce_raw_report(raw: RawReport | Mapping[str, Any]) -> RawReport:
    """Return a RawReport instance so untouched export_events() works on both dataclasses and dicts."""
    if isinstance(raw, RawReport):
        return raw
    if not isinstance(raw, Mapping) and not (is_dataclass(raw) and not isinstance(raw, type)):
        raise ValueError(f"Unsupported raw report type: {type(raw).__name__}")
    events_in = _field(raw, "events", ())
    events = tuple(e if isinstance(e, Event) else Event(**e) for e in events_in)
    return RawReport(
        schema_version=int(_field(raw, "schema_version", SCHEMA_VERSION)),
        seed=int(_field(raw, "seed")),
        total=int(_field(raw, "total")),
        good=int(_field(raw, "good")),
        on_time=int(_field(raw, "on_time")),
        escaped=int(_field(raw, "escaped")),
        scrap=int(_field(raw, "scrap")),
        unfinished=int(_field(raw, "unfinished")),
        pack_started=int(_field(raw, "pack_started")),
        pack_finished=int(_field(raw, "pack_finished")),
        auto_finished=int(_field(raw, "auto_finished")),
        trays_used=int(_field(raw, "trays_used")),
        rework_started=int(_field(raw, "rework_started")),
        labor_ticks=int(_field(raw, "labor_ticks")),
        overtime_ticks=tuple(int(x) for x in _field(raw, "overtime_ticks")),
        events=events,
    )


def _validate_events_filename(events_file: Any) -> str:
    if (
        type(events_file) is not str
        or not events_file
        or "\x00" in events_file
        or "/" in events_file
        or "\\" in events_file
        or events_file in {".", ".."}
    ):
        raise ValueError(f"Invalid events_file name: {events_file!r}")
    return events_file


def _validate_world_wire(world_wire: Any) -> dict[str, Any]:
    if type(world_wire) is not dict:
        raise ValueError("Manifest world must be a JSON object")
    if not _is_strict_int(world_wire.get("schema_version")) or world_wire["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"Manifest world.schema_version must be integer {SCHEMA_VERSION}")
    for key in ("clock", "capacity", "workers", "kinds", "time", "prob_bps", "money"):
        if key not in world_wire:
            raise ValueError(f"Manifest world missing required key {key!r}")
    return world_wire


def _validate_scenario_wire(scenario_wire: Any, world_wire: dict[str, Any]) -> dict[str, Any]:
    if type(scenario_wire) is not dict or scenario_wire.keys() != {"schema_version", "seed", "orders"}:
        raise ValueError("Manifest scenario must have exact keys schema_version, seed, orders")
    if not _is_strict_int(scenario_wire["schema_version"]) or scenario_wire["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"Manifest scenario.schema_version must be integer {SCHEMA_VERSION}")
    if not _is_strict_int(scenario_wire["seed"]):
        raise ValueError("Manifest scenario.seed must be an integer")
    orders = scenario_wire["orders"]
    if type(orders) is not list or not orders:
        raise ValueError("Manifest scenario.orders must be a non-empty list")
    shift_ticks = world_wire["clock"]["shift_ticks"]
    kinds = set(world_wire["kinds"])
    seen_ids: set[int] = set()
    prev_key: tuple[int, int] | None = None
    for idx, order in enumerate(orders):
        if type(order) is not dict or order.keys() != {"id", "kind", "arrival", "due"}:
            raise ValueError(f"Scenario order #{idx} must have exact keys id, kind, arrival, due")
        oid, kind, arrival, due = order["id"], order["kind"], order["arrival"], order["due"]
        if (
            not _is_strict_int(oid)
            or oid < 0
            or oid in seen_ids
            or type(kind) is not str
            or kind not in kinds
            or not _is_strict_int(arrival)
            or not (0 <= arrival < shift_ticks)
            or not _is_strict_int(due)
            or due < arrival
        ):
            raise ValueError(f"Scenario order #{idx} violates domain constraints: {order!r}")
        cur_key = (arrival, oid)
        if prev_key is not None and prev_key >= cur_key:
            raise ValueError(f"Scenario orders must be strictly sorted by (arrival, id) at #{idx}")
        seen_ids.add(oid)
        prev_key = cur_key
    return scenario_wire


def _validate_raw_wire(raw_wire: Any, expected_seed: int, num_workers: int) -> dict[str, Any]:
    if type(raw_wire) is not dict or raw_wire.keys() != _RAW_KEYS_V1:
        raise ValueError("Manifest raw must contain exact v1 RawReport keys")
    if not _is_strict_int(raw_wire["schema_version"]) or raw_wire["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"Manifest raw.schema_version must be integer {SCHEMA_VERSION}")
    if not _is_strict_int(raw_wire["seed"]) or raw_wire["seed"] != expected_seed:
        raise ValueError("Manifest raw.seed must match scenario.seed")
    for k in _RAW_INT_KEYS_V1:
        if not _is_strict_int(raw_wire[k]) or raw_wire[k] < 0:
            raise ValueError(f"Manifest raw.{k} must be a non-negative integer")
    overtime = raw_wire["overtime_ticks"]
    if (
        type(overtime) is not list
        or len(overtime) != num_workers
        or any(not _is_strict_int(x) or x < 0 for x in overtime)
    ):
        raise ValueError("Manifest raw.overtime_ticks must be a list of non-negative ints per worker")
    if type(raw_wire["events"]) is not list or raw_wire["events"] != []:
        raise ValueError("Manifest raw.events must be an empty list []")
    return raw_wire


def _validate_economy_wire(economy_wire: Any) -> dict[str, Any]:
    if type(economy_wire) is not dict or economy_wire.keys() != {"purchase", "costs", "total"}:
        raise ValueError("Manifest economy must have exact keys purchase, costs, total")
    purchase = economy_wire["purchase"]
    total = economy_wire["total"]
    costs = economy_wire["costs"]
    if not _is_strict_int(purchase) or purchase < 0:
        raise ValueError("Manifest economy.purchase must be a non-negative integer")
    if not _is_strict_int(total) or total < 0:
        raise ValueError("Manifest economy.total must be a non-negative integer")
    if type(costs) is not dict or costs.keys() != _ECONOMY_COST_KEYS_V1:
        raise ValueError("Manifest economy.costs must have exact 10 v1 cost keys")
    for k, v in costs.items():
        if not _is_strict_int(v) or v < 0:
            raise ValueError(f"Manifest economy.costs[{k!r}] must be a non-negative integer")
    if total != sum(costs.values()):
        raise ValueError(
            f"Manifest economy.total ({total}) != sum(costs.values()) ({sum(costs.values())})"
        )
    return economy_wire


def build_shift_manifest(
    world: World,
    plan: Plan | Mapping[str, Any],
    scenario: Scenario | Mapping[str, Any],
    raw: RawReport | Mapping[str, Any],
    economy: Economy | Mapping[str, Any],
    *,
    events_file: str = "events.jsonl",
) -> dict[str, Any]:
    """Build Musa's exact robotization-bench.replay.v1 manifest with JSON-ready list/dict types."""
    events_name = _validate_events_filename(events_file)
    world_copy = _to_wire(world)
    if type(world_copy) is dict:
        world_copy.pop("quarterly", None)
    world_wire = _validate_world_wire(world_copy)
    plan_wire = _to_wire(plan)
    parsed_plan = parse_plan(plan_wire, world_wire)
    scenario_wire = _validate_scenario_wire(_to_wire(scenario), world_wire)
    raw_wire = _validate_raw_wire(_strip_raw_events(raw), scenario_wire["seed"], len(parsed_plan.workers))
    economy_wire = _validate_economy_wire(_to_wire(economy))
    return {
        "replay_format": REPLAY_FORMAT_V1,
        "world": world_wire,
        "plan": plan_wire,
        "scenario": scenario_wire,
        "raw": raw_wire,
        "economy": economy_wire,
        "events_file": events_name,
    }


def export_shift_bundle(
    world: World,
    plan: Plan | Mapping[str, Any],
    scenario: Scenario | Mapping[str, Any],
    raw: RawReport | Mapping[str, Any],
    economy: Economy | Mapping[str, Any],
    out_dir: Path,
) -> Path:
    """Atomically write a v1 3D shift bundle (events.jsonl + manifest.json) into out_dir."""
    out_dir = Path(out_dir)
    _ensure_not_symlink(out_dir)
    if out_dir.exists() and not out_dir.is_dir():
        raise ValueError(f"Output path exists and is not a directory: {out_dir}")

    raw_report = _coerce_raw_report(raw)
    if raw_report.total > 0 and len(raw_report.events) == 0:
        raise ValueError(
            "Refusing to export 3D shift bundle with empty event trace; run simulate(..., trace=True)"
        )
    manifest = build_shift_manifest(
        world, plan, scenario, raw_report, economy, events_file="events.jsonl"
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    events_path = out_dir / "events.jsonl"
    manifest_path = out_dir / "manifest.json"
    _ensure_not_symlink(events_path)
    _ensure_not_symlink(manifest_path)

    export_events(raw_report, events_path)
    _atomic_write_json(manifest_path, manifest)
    return out_dir


def validate_shift_bundle(bundle_dir: Path) -> dict[str, Any]:
    """Validate an on-disk v1 3D shift bundle against all state-machine, queue, worker, and counter invariants."""
    bundle_dir = Path(bundle_dir)
    _ensure_not_symlink(bundle_dir)
    if not bundle_dir.exists() or not bundle_dir.is_dir():
        raise ValueError(f"Shift bundle directory does not exist: {bundle_dir}")

    manifest_path = bundle_dir / "manifest.json"
    _ensure_not_symlink(manifest_path)
    if not manifest_path.is_file():
        raise ValueError(f"Missing regular manifest.json in {bundle_dir}")

    manifest = _strict_json_loads(manifest_path.read_text(encoding="utf-8"))
    if type(manifest) is not dict or manifest.keys() != {
        "replay_format",
        "world",
        "plan",
        "scenario",
        "raw",
        "economy",
        "events_file",
    }:
        raise ValueError("manifest.json must contain exact 7 v1 replay wrapper keys")
    if manifest["replay_format"] != REPLAY_FORMAT_V1:
        raise ValueError(f"Unsupported replay_format: {manifest['replay_format']!r}")

    events_name = _validate_events_filename(manifest["events_file"])
    events_path = bundle_dir / events_name
    _ensure_not_symlink(events_path)
    if not events_path.is_file():
        raise ValueError(f"Missing regular events file {events_name!r} in {bundle_dir}")

    world = _validate_world_wire(manifest["world"])
    plan = parse_plan(manifest["plan"], world)
    scenario = _validate_scenario_wire(manifest["scenario"], world)
    raw = _validate_raw_wire(manifest["raw"], scenario["seed"], len(plan.workers))
    economy = _validate_economy_wire(manifest["economy"])

    clock = world["clock"]
    shift_ticks = clock["shift_ticks"]
    horizon = shift_ticks + clock["overtime_ticks"]
    break_at = clock["break_at"]
    break_length = clock["break_length"]
    walk_ticks = clock["walk_ticks"]

    by_id = {o["id"]: o for o in scenario["orders"]}
    valid_workers = {f"w{idx}" for idx in range(len(plan.workers))}
    valid_resources = valid_workers | {"robot"}
    limited = {2: "pick", 3: "pack", 4: "qc"}

    raw_lines = events_path.read_text(encoding="utf-8").splitlines()
    if raw["total"] > 0 and not raw_lines:
        raise ValueError("events.jsonl line 1: empty event trace for non-empty scenario")

    state: dict[int, tuple[str, int, int]] = {}
    state_line: dict[int, int] = {}
    last_transition: dict[int, tuple[int, str | None]] = {}
    occupied: dict[int, set[int]] = defaultdict(set)
    active: dict[str, tuple[int, int, int, int]] = {}
    active_line: dict[str, int] = {}
    pending_walk: dict[str, tuple[int, int, int, int, int]] = {}
    robot_jammed = False
    robot_assisted_end: int | None = None
    robot_assist_line: int | None = None
    done: Counter[str] = Counter()
    event_kinds: Counter[str] = Counter()

    worker_zones = {f"w{idx}": zones for idx, zones in enumerate(plan.workers)}
    w_pos = {f"w{idx}": zones[0] for idx, zones in enumerate(plan.workers)}
    w_busy_until = {f"w{idx}": 0 for idx in range(len(plan.workers))}
    w_last_work = {f"w{idx}": 0 for idx in range(len(plan.workers))}
    w_took_break = {f"w{idx}": False for idx in range(len(plan.workers))}
    rig = "tray" if plan.trays else "bare"

    pack_started = 0
    pack_finished = 0
    auto_finished = 0
    trays_used = 0
    rework_started = 0
    labor = 0
    last_tick = 0

    for line_no, line_text in enumerate(raw_lines, start=1):
        try:
            ev = _strict_json_loads(line_text)
        except ValueError as exc:
            raise ValueError(f"events.jsonl line {line_no}: {exc}") from exc
        if type(ev) is not dict or ev.keys() != _EVENT_KEYS_V1:
            raise ValueError(
                f"events.jsonl line {line_no}: expected exact 7 Event keys, got {sorted(ev.keys()) if type(ev) is dict else type(ev).__name__}"
            )

        tick = ev["tick"]
        kind = ev["kind"]
        order_id = ev["order_id"]
        resource = ev["resource"]
        stage = ev["stage"]
        attempt = ev["attempt"]
        end_tick = ev["end_tick"]

        if not _is_strict_int(tick) or not (0 <= tick <= horizon) or tick < last_tick:
            raise ValueError(
                f"events.jsonl line {line_no}: tick {tick!r} violates monotonicity or horizon [last={last_tick}, H={horizon}]"
            )
        last_tick = tick

        if type(kind) is not str or kind not in _EVENT_KINDS_V1:
            raise ValueError(f"events.jsonl line {line_no}: unknown Event.kind {kind!r}")
        event_kinds[kind] += 1

        if pending_walk:
            pw_res, (pw_line, pw_tick, _pw_oid, _pw_stg, _pw_att) = next(iter(pending_walk.items()))
            if kind != "walk" or resource != pw_res:
                raise ValueError(
                    f"events.jsonl line {pw_line}: missing immediate walk event on {pw_res} at tick {pw_tick}"
                )

        if kind == "break":
            if (
                order_id is not None
                or stage is not None
                or attempt is not None
                or resource not in valid_workers
                or not _is_strict_int(end_tick)
                or tick >= horizon
                or tick < break_at
                or end_tick - tick != break_length
                or w_took_break[resource]
                or resource in active
                or tick < w_busy_until[resource]
            ):
                raise ValueError(f"events.jsonl line {line_no}: invalid break event {ev!r}")
            w_took_break[resource] = True
            w_busy_until[resource] = end_tick
            continue

        if not _is_strict_int(order_id) or order_id not in by_id:
            raise ValueError(
                f"events.jsonl line {line_no}: unknown or missing order_id {order_id!r}"
            )
        if not _is_strict_int(stage) or stage not in (1, 2, 3, 4):
            raise ValueError(f"events.jsonl line {line_no}: invalid stage {stage!r}")
        if not _is_strict_int(attempt) or attempt not in (0, 1):
            raise ValueError(f"events.jsonl line {line_no}: invalid attempt {attempt!r}")

        previous = state.get(order_id)

        if kind == "arrival":
            if (
                previous is not None
                or resource is not None
                or stage != 1
                or attempt != 0
                or end_tick is not None
                or tick != by_id[order_id]["arrival"]
            ):
                raise ValueError(f"events.jsonl line {line_no}: invalid arrival event {ev!r}")
            state[order_id] = ("arrival", 1, 0)
            state_line[order_id] = line_no
            last_transition[order_id] = (tick, None)

        elif kind == "enqueue":
            if resource is not None or end_tick is not None:
                raise ValueError(f"events.jsonl line {line_no}: invalid enqueue fields {ev!r}")
            if stage == 1:
                if previous != ("arrival", 1, 0) or attempt != 0:
                    raise ValueError(
                        f"events.jsonl line {line_no}: illegal stage-1 enqueue transition from {previous!r}"
                    )
            elif stage == 3 and attempt == 1:
                if previous != ("finish", 4, 0):
                    raise ValueError(
                        f"events.jsonl line {line_no}: illegal rework enqueue transition from {previous!r}"
                    )
            else:
                if previous != ("finish", stage - 1, attempt) or order_id not in occupied[stage]:
                    raise ValueError(
                        f"events.jsonl line {line_no}: illegal stage-{stage} enqueue transition from {previous!r}"
                    )
            prev_tick = last_transition.get(order_id, (-1, None))[0]
            if tick != prev_tick:
                raise ValueError(
                    f"events.jsonl line {line_no}: enqueue tick {tick} must match preceding transition tick {prev_tick}"
                )
            state[order_id] = ("enqueue", stage, attempt)
            state_line[order_id] = line_no

        elif kind == "start":
            if (
                resource not in valid_resources
                or not _is_strict_int(end_tick)
                or end_tick <= tick
                or tick >= horizon
                or previous != ("enqueue", stage, attempt)
            ):
                raise ValueError(
                    f"events.jsonl line {line_no}: invalid start event {ev!r} from state {previous!r}"
                )
            if stage in limited and (stage, attempt) != (3, 1):
                if order_id not in occupied[stage]:
                    raise ValueError(
                        f"events.jsonl line {line_no}: order {order_id} missing reservation in Q{stage}"
                    )
                occupied[stage].remove(order_id)
            if stage < 4:
                if order_id in occupied[stage + 1]:
                    raise ValueError(
                        f"events.jsonl line {line_no}: duplicate reservation in Q{stage + 1} for order {order_id}"
                    )
                occupied[stage + 1].add(order_id)
                cap_limit = world["capacity"][limited[stage + 1]]
                if len(occupied[stage + 1]) > cap_limit:
                    raise ValueError(
                        f"events.jsonl line {line_no}: queue Q{stage + 1} capacity exceeded ({len(occupied[stage + 1])} > {cap_limit})"
                    )
            if stage == 3:
                expected_auto = (
                    attempt == 0
                    and plan.robot
                    and (
                        plan.route == "all"
                        or (plan.route == "bypass" and by_id[order_id]["kind"] == "regular")
                    )
                )
                if (resource == "robot") != expected_auto:
                    raise ValueError(
                        f"events.jsonl line {line_no}: stage-3 routing violation for order {order_id} on {resource!r}"
                    )
                pack_started += 1
                if plan.trays and attempt == 0:
                    trays_used += 1
                if attempt == 1:
                    rework_started += 1
            elif resource == "robot":
                raise ValueError(
                    f"events.jsonl line {line_no}: robot cannot run stage {stage}"
                )

            if resource in active:
                raise ValueError(
                    f"events.jsonl line {line_no}: resource {resource!r} already busy with {active[resource]!r}"
                )

            order_kind = by_id[order_id]["kind"]
            if resource == "robot":
                expected_end = tick + world["time"]["auto"][rig][order_kind]
                if end_tick != expected_end:
                    raise ValueError(
                        f"events.jsonl line {line_no}: robot start end_tick {end_tick} != expected {expected_end}"
                    )
                robot_jammed = False
                robot_assisted_end = None
                robot_assist_line = None
            else:
                if tick < w_busy_until[resource]:
                    raise ValueError(
                        f"events.jsonl line {line_no}: overlapping interval on worker {resource} (available={w_busy_until[resource]}, tick={tick})"
                    )
                if tick >= break_at and not w_took_break[resource]:
                    raise ValueError(
                        f"events.jsonl line {line_no}: worker {resource} started work at tick {tick} >= break_at ({break_at}) before taking break"
                    )
                if stage not in worker_zones[resource]:
                    raise ValueError(
                        f"events.jsonl line {line_no}: worker {resource} assigned disallowed stage {stage} (zones={worker_zones[resource]})"
                    )
                travel = walk_ticks if w_pos[resource] != stage else 0
                expected_end = tick + travel + world["time"]["manual"][order_kind][stage - 1]
                if end_tick != expected_end:
                    raise ValueError(
                        f"events.jsonl line {line_no}: worker {resource} start end_tick {end_tick} != expected {expected_end}"
                    )
                w_pos[resource] = stage
                w_busy_until[resource] = end_tick
                w_last_work[resource] = min(horizon, end_tick)
                labor += w_last_work[resource] - tick
                if travel > 0:
                    pending_walk[resource] = (line_no, tick, order_id, stage, attempt)

            active[resource] = (order_id, stage, attempt, end_tick)
            active_line[resource] = line_no
            state[order_id] = ("start", stage, attempt)
            state_line[order_id] = line_no

        elif kind == "finish":
            act = active.get(resource)
            if (
                resource not in valid_resources
                or end_tick is not None
                or previous != ("start", stage, attempt)
                or act is None
                or act[:3] != (order_id, stage, attempt)
            ):
                raise ValueError(
                    f"events.jsonl line {line_no}: invalid finish event {ev!r} from state {previous!r}"
                )
            if resource == "robot" and robot_jammed:
                if robot_assisted_end != tick:
                    raise ValueError(
                        f"events.jsonl line {line_no}: jammed robot finished at tick {tick} without completed assist ({robot_assisted_end!r})"
                    )
                robot_jammed = False
                robot_assisted_end = None
                robot_assist_line = None
            else:
                if tick != act[3]:
                    raise ValueError(
                        f"events.jsonl line {line_no}: finish tick {tick} != expected end_tick {act[3]} on {resource!r}"
                    )
            active.pop(resource)
            active_line.pop(resource, None)
            if stage == 3:
                pack_finished += 1
                if resource == "robot":
                    auto_finished += 1
            state[order_id] = ("finish", stage, attempt)
            state_line[order_id] = line_no
            last_transition[order_id] = (tick, resource)

        elif kind == "jam":
            act = active.get("robot")
            if (
                resource != "robot"
                or stage != 3
                or attempt != 0
                or end_tick is not None
                or previous != ("start", 3, 0)
                or act is None
                or act[:3] != (order_id, 3, 0)
                or tick != act[3]
                or robot_jammed
            ):
                raise ValueError(f"events.jsonl line {line_no}: invalid jam event {ev!r}")
            robot_jammed = True

        elif kind == "assist":
            act_robot = active.get("robot")
            if (
                resource not in valid_workers
                or stage != 3
                or attempt != 0
                or not _is_strict_int(end_tick)
                or end_tick <= tick
                or tick >= horizon
                or previous != ("start", 3, 0)
                or act_robot is None
                or act_robot[:3] != (order_id, 3, 0)
                or not robot_jammed
                or robot_assisted_end is not None
                or resource in active
                or tick < w_busy_until[resource]
            ):
                raise ValueError(f"events.jsonl line {line_no}: invalid assist event {ev!r}")
            if tick >= break_at and not w_took_break[resource]:
                raise ValueError(
                    f"events.jsonl line {line_no}: worker {resource} started assist at tick {tick} >= break_at ({break_at}) before taking break"
                )
            if 3 not in worker_zones[resource]:
                raise ValueError(
                    f"events.jsonl line {line_no}: worker {resource} cannot assist at stage 3 (zones={worker_zones[resource]})"
                )
            travel = walk_ticks if w_pos[resource] != 3 else 0
            expected_end = tick + travel + world["time"]["jam_service"]
            if end_tick != expected_end:
                raise ValueError(
                    f"events.jsonl line {line_no}: worker {resource} assist end_tick {end_tick} != expected {expected_end}"
                )
            w_pos[resource] = 3
            w_busy_until[resource] = end_tick
            w_last_work[resource] = min(horizon, end_tick)
            labor += w_last_work[resource] - tick
            robot_assisted_end = end_tick
            robot_assist_line = line_no
            if travel > 0:
                pending_walk[resource] = (line_no, tick, order_id, 3, 0)

        elif kind == "walk":
            if resource not in valid_workers or resource not in pending_walk:
                raise ValueError(
                    f"events.jsonl line {line_no}: walk event {ev!r} must immediately follow parent start/assist"
                )
            pw_line, pw_tick, pw_oid, pw_stg, pw_att = pending_walk.pop(resource)
            if (
                line_no != pw_line + 1
                or tick != pw_tick
                or order_id != pw_oid
                or stage != pw_stg
                or attempt != pw_att
                or not _is_strict_int(end_tick)
                or end_tick != pw_tick + walk_ticks
                or tick >= horizon
            ):
                raise ValueError(
                    f"events.jsonl line {line_no}: invalid walk event {ev!r} for parent line {pw_line}"
                )

        elif kind in ("good", "escaped", "scrap"):
            if (
                resource not in valid_workers
                or stage != 4
                or end_tick is not None
                or previous != ("finish", 4, attempt)
                or (kind == "scrap" and attempt != 1)
                or last_transition.get(order_id) != (tick, resource)
            ):
                raise ValueError(
                    f"events.jsonl line {line_no}: invalid terminal {kind!r} event {ev!r} from state {previous!r}"
                )
            done[kind] += 1
            if kind == "good" and tick <= by_id[order_id]["due"]:
                done["on_time"] += 1
            state[order_id] = (kind, 4, attempt)
            state_line[order_id] = line_no

    if pending_walk:
        pw_res, (pw_line, pw_tick, _pw_oid, _pw_stg, _pw_att) = next(iter(pending_walk.items()))
        raise ValueError(
            f"events.jsonl line {pw_line}: missing required walk event on {pw_res} at tick {pw_tick}"
        )

    for res, (_oid, _stg, _att, exp_end) in active.items():
        if res != "robot":
            if exp_end <= horizon:
                raise ValueError(
                    f"events.jsonl line {active_line[res]}: unfinished worker job on {res} has end_tick {exp_end} <= horizon {horizon}"
                )
        else:
            if not robot_jammed:
                if exp_end <= horizon:
                    raise ValueError(
                        f"events.jsonl line {active_line['robot']}: unfinished unjammed robot job has end_tick {exp_end} <= horizon {horizon}"
                    )
            elif robot_assisted_end is not None and robot_assisted_end <= horizon:
                err_ln = robot_assist_line or active_line["robot"]
                raise ValueError(
                    f"events.jsonl line {err_ln}: assisted jammed robot completed service at tick {robot_assisted_end} <= horizon {horizon} without finish"
                )

    overtime = [max(0, w_last_work[f"w{idx}"] - shift_ticks) for idx in range(len(plan.workers))]

    # Post-loop order conservation, RawReport parity & Economy formula parity
    if state.keys() != by_id.keys():
        missing = sorted(set(by_id.keys()) - set(state.keys()))
        raise ValueError(f"Orders missing arrival events in trace: {missing[:10]}")
    for oid, st_val in state.items():
        if st_val[0] not in {"start", "enqueue", "good", "escaped", "scrap"}:
            raise ValueError(
                f"events.jsonl line {state_line[oid]}: invalid incomplete order state {st_val!r} at end of trace"
            )

    unfinished = sum(v[0] in {"start", "enqueue"} for v in state.values())
    total_orders = len(by_id)
    if done["good"] + done["escaped"] + done["scrap"] + unfinished != total_orders:
        raise ValueError("Order conservation failed across trace")

    expected_raw = {
        "total": total_orders,
        "good": done["good"],
        "on_time": done["on_time"],
        "escaped": done["escaped"],
        "scrap": done["scrap"],
        "unfinished": unfinished,
        "pack_started": pack_started,
        "pack_finished": pack_finished,
        "auto_finished": auto_finished,
        "trays_used": trays_used,
        "rework_started": rework_started,
        "labor_ticks": labor,
        "overtime_ticks": overtime,
    }
    for key, expected_val in expected_raw.items():
        if raw[key] != expected_val:
            raise ValueError(
                f"Manifest raw.{key} ({raw[key]!r}) does not match reconstructed trace value ({expected_val!r})"
            )

    reconstructed_raw = RawReport(
        schema_version=SCHEMA_VERSION,
        seed=scenario["seed"],
        total=total_orders,
        good=done["good"],
        on_time=done["on_time"],
        escaped=done["escaped"],
        scrap=done["scrap"],
        unfinished=unfinished,
        pack_started=pack_started,
        pack_finished=pack_finished,
        auto_finished=auto_finished,
        trays_used=trays_used,
        rework_started=rework_started,
        labor_ticks=labor,
        overtime_ticks=tuple(overtime),
        events=(),
    )
    expected_economy = _to_wire(calculate(world, plan, reconstructed_raw))
    if economy != expected_economy:
        raise ValueError(
            f"Manifest economy {economy!r} does not match calculated shift economy {expected_economy!r}"
        )

    return {
        "ok": True,
        "bundle_dir": str(bundle_dir),
        "seed": scenario["seed"],
        "event_count": len(raw_lines),
        "event_kinds": dict(event_kinds),
        "summary": {
            "total": raw["total"],
            "good": raw["good"],
            "on_time": raw["on_time"],
            "escaped": raw["escaped"],
            "scrap": raw["scrap"],
            "unfinished": raw["unfinished"],
            "labor_ticks": raw["labor_ticks"],
            "purchase": economy["purchase"],
            "total_cost": economy["total"],
        },
    }


_QUARTERLY_GENERATOR_KEYS = (
    "waves",
    "spacing",
    "orders_min",
    "orders_span",
    "jitter_span",
    "regular_bps",
    "fragile_bps",
    "due_offset",
    "due_span",
)


def _build_week_world_fallback(
    world: Mapping[str, Any],
    week_num: int,
    *,
    commissioning: bool,
    wear: int,
    maintenance: bool,
) -> World:
    w = _to_wire(dict(world))
    q = w.pop("quarterly", None)
    if not isinstance(q, Mapping):
        return w
    w["schema_version"] = SCHEMA_VERSION

    profiles = q.get("week_profiles")
    if (
        isinstance(profiles, list)
        and 0 <= week_num < len(profiles)
        and isinstance(profiles[week_num], Mapping)
        and isinstance(w.get("generator"), dict)
    ):
        profile = profiles[week_num]
        for key in _QUARTERLY_GENERATOR_KEYS:
            if key in profile:
                w["generator"][key] = profile[key]

    wear_spec = q.get("wear") if isinstance(q.get("wear"), Mapping) else {}
    comm_spec = q.get("commissioning") if isinstance(q.get("commissioning"), Mapping) else {}
    max_wear = int(wear_spec.get("max_wear", 12))
    maint_reduction = int(wear_spec.get("maintenance_reduction", 5))
    reduced_wear = wear - maint_reduction if maintenance else wear
    effective_wear = min(max_wear, max(0, reduced_wear))

    comm_jam_map = (
        comm_spec.get("jam_bonus_bps")
        if isinstance(comm_spec.get("jam_bonus_bps"), Mapping)
        else {}
    )
    comm_def_map = (
        comm_spec.get("defect_bonus_bps")
        if isinstance(comm_spec.get("defect_bonus_bps"), Mapping)
        else {}
    )
    jam_per_wear = int(wear_spec.get("jam_bps_per_wear", 0))
    def_per_wear = int(wear_spec.get("defect_bps_per_wear", 0))

    prob_bps = w.get("prob_bps")
    kinds = w.get("kinds", ())
    if isinstance(prob_bps, dict):
        for rig in ("bare", "tray"):
            jam_add = (int(comm_jam_map.get(rig, 0)) if commissioning else 0) + (
                effective_wear * jam_per_wear
            )
            def_add = (int(comm_def_map.get(rig, 0)) if commissioning else 0) + (
                effective_wear * def_per_wear
            )
            if isinstance(prob_bps.get("jam", {}).get(rig), dict):
                for kind in kinds:
                    if kind in prob_bps["jam"][rig]:
                        prob_bps["jam"][rig][kind] = min(
                            10_000, max(0, prob_bps["jam"][rig][kind] + jam_add)
                        )
            if isinstance(prob_bps.get("defect_auto", {}).get(rig), dict):
                for kind in kinds:
                    if kind in prob_bps["defect_auto"][rig]:
                        prob_bps["defect_auto"][rig][kind] = min(
                            10_000, max(0, prob_bps["defect_auto"][rig][kind] + def_add)
                        )

    if maintenance:
        default_slowdown = 1 if "wear" not in q else 0
        slowdown = int(wear_spec.get("maintenance_auto_slowdown_ticks", default_slowdown))
        if slowdown and isinstance(w.get("time", {}).get("auto"), dict):
            for rig in ("bare", "tray"):
                if isinstance(w["time"]["auto"].get(rig), dict):
                    for kind in kinds:
                        if kind in w["time"]["auto"][rig]:
                            w["time"]["auto"][rig][kind] = max(
                                1, w["time"]["auto"][rig][kind] + slowdown
                            )
    return w


def _resolve_week_world(world: World, week_report: Any, week_plan: Any, week_num: int) -> World:
    """Resolve effective week World: (1) explicit week_report.world/week_world, (2) lazy quarterly.build_week_world, (3) pure-dict fallback."""
    for attr in ("world", "week_world"):
        explicit = _field(week_report, attr, None)
        if isinstance(explicit, Mapping):
            out = _to_wire(explicit)
            if isinstance(out, dict):
                out.pop("quarterly", None)
            return out
    if isinstance(world, Mapping) and "quarterly" in world:
        commissioning = bool(_field(week_report, "commissioning_active", False))
        wear = int(_field(week_report, "wear_start", 0))
        maintenance = bool(_field(week_plan, "maintenance", False))
        try:
            quarterly_mod = importlib.import_module("robotization_bench.quarterly")
        except ImportError:
            quarterly_mod = None
        build_fn = (
            getattr(quarterly_mod, "build_week_world", None) if quarterly_mod is not None else None
        )
        if callable(build_fn):
            try:
                out = _to_wire(
                    build_fn(
                        world,
                        week_num,
                        commissioning=commissioning,
                        wear=wear,
                        maintenance=maintenance,
                    )
                )
                if isinstance(out, dict):
                    out.pop("quarterly", None)
                return out
            except (TypeError, KeyError, ValueError):
                pass
        return _build_week_world_fallback(
            world,
            week_num,
            commissioning=commissioning,
            wear=wear,
            maintenance=maintenance,
        )
    out = _to_wire(world)
    if isinstance(out, dict):
        out.pop("quarterly", None)
    return out


def _extract_shift_plan_wire(week_report: Any, week_plan: Any) -> dict[str, Any]:
    shift_plan = _field(week_report, "shift_plan", None)
    if shift_plan is not None:
        return _to_wire(shift_plan)
    to_shift = getattr(week_plan, "to_shift_plan", None)
    if callable(to_shift):
        return _to_wire(to_shift())
    return _to_wire(
        {
            "schema_version": SCHEMA_VERSION,
            "robot": bool(_field(week_plan, "robot")),
            "trays": bool(_field(week_plan, "trays")),
            "route": _field(week_plan, "route"),
            "workers": [list(z) for z in _field(week_plan, "workers")],
        }
    )


def export_quarter_pack(
    world: World,
    quarter: Any,
    plan: Any,
    out_dir: Path,
    *,
    evaluation: Evaluation | Mapping[str, Any] | None = None,
) -> Path:
    """Export a 12-week v2 rollout pack where every weeks/week-XX is a valid v1 3D replay bundle."""
    out_dir = Path(out_dir)
    _ensure_not_symlink(out_dir)
    if out_dir.exists() and not out_dir.is_dir():
        raise ValueError(f"Output path exists and is not a directory: {out_dir}")

    weeks_root = out_dir / "weeks"
    quarter_manifest_path = out_dir / "quarter_manifest.json"
    _ensure_not_symlink(weeks_root)
    _ensure_not_symlink(quarter_manifest_path)

    quarter_weeks = list(_field(quarter, "weeks"))
    plan_weeks = list(_field(plan, "weeks"))
    if not quarter_weeks:
        raise ValueError("QuarterReport.weeks must be non-empty")
    if len(plan_weeks) != len(quarter_weeks):
        raise ValueError(
            f"Plan week count ({len(plan_weeks)}) does not match quarter week count ({len(quarter_weeks)})"
        )

    prepared_weeks: list[tuple[str, str, Path, World, dict[str, Any], Any, RawReport, dict[str, Any], dict[str, Any]]] = []
    for idx, (week_report, week_plan) in enumerate(zip(quarter_weeks, plan_weeks, strict=True)):
        week_num = int(_field(week_report, "week", idx))
        if week_num != idx:
            raise ValueError(f"Expected sequential week index {idx}, got {week_num}")
        week_id = f"week-{week_num:02d}"
        rel_dir = f"weeks/{week_id}"
        week_dir = weeks_root / week_id
        _ensure_not_symlink(week_dir)

        week_world = _resolve_week_world(world, week_report, week_plan, week_num)
        shift_plan_wire = _extract_shift_plan_wire(week_report, week_plan)
        scenario = _field(week_report, "scenario")
        raw_report = _coerce_raw_report(_field(week_report, "raw"))
        if raw_report.total > 0 and len(raw_report.events) == 0:
            raise ValueError(
                f"Refusing to export week {week_num} with empty event trace; run simulate_quarter(..., trace=True)"
            )

        shift_economy = _field(
            week_report, "shift_economy", _field(week_report, "economy", None)
        )
        if shift_economy is None:
            shift_plan_dc = parse_plan(shift_plan_wire, week_world)
            shift_economy = calculate(week_world, shift_plan_dc, raw_report)
        shift_economy_wire = _validate_economy_wire(_to_wire(shift_economy))
        week_economy_wire = _to_wire(_field(week_report, "week_economy", shift_economy_wire))

        # Pre-validate manifest before touching disk
        build_shift_manifest(
            week_world, shift_plan_wire, scenario, raw_report, shift_economy_wire, events_file="events.jsonl"
        )

        summary_entry = {
            "week": week_num,
            "week_id": week_id,
            "label": str(_field(week_report, "label", f"week_{week_num}")),
            "week_seed": int(_field(week_report, "week_seed", raw_report.seed)),
            "bundle_dir": rel_dir,
            "manifest_file": f"{rel_dir}/manifest.json",
            "events_file": f"{rel_dir}/events.jsonl",
            "replay_format": REPLAY_FORMAT_V1,
            "carryover_in": int(_field(week_report, "carryover_in", 0)),
            "carryover_out": int(_field(week_report, "carryover_out", 0)),
            "wear_start": int(_field(week_report, "wear_start", 0)),
            "wear_end": int(_field(week_report, "wear_end", 0)),
            "commissioning_active": bool(_field(week_report, "commissioning_active", False)),
            "maintenance": bool(_field(week_plan, "maintenance", False)),
            "shift_plan": shift_plan_wire,
            "raw": _strip_raw_events(raw_report),
            "shift_economy": shift_economy_wire,
            "week_economy": week_economy_wire,
        }
        prepared_weeks.append(
            (
                week_id,
                rel_dir,
                week_dir,
                week_world,
                shift_plan_wire,
                scenario,
                raw_report,
                shift_economy_wire,
                summary_entry,
            )
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    _ensure_not_symlink(weeks_root)
    weeks_root.mkdir(parents=True, exist_ok=True)

    week_summaries: list[dict[str, Any]] = []
    for (
        _week_id,
        _rel_dir,
        week_dir,
        week_world,
        shift_plan_wire,
        scenario,
        raw_report,
        shift_economy_wire,
        summary_entry,
    ) in prepared_weeks:
        export_shift_bundle(
            week_world, shift_plan_wire, scenario, raw_report, shift_economy_wire, week_dir
        )
        week_summaries.append(summary_entry)

    quarter_manifest = {
        "replay_pack_format": QUARTER_PACK_FORMAT_V1,
        "schema_version": int(_field(quarter, "schema_version", 2)),
        "world_id": (
            world.get("quarterly", {}).get("world_id", world.get("world_id"))
            if isinstance(world, Mapping)
            else None
        ),
        "seed": int(_field(quarter, "seed")),
        "purchase": int(_field(quarter, "purchase")),
        "total_cost": int(_field(quarter, "total_cost")),
        "labor_ticks": int(_field(quarter, "labor_ticks")),
        "plan": _to_wire(plan),
        "evaluation": _to_wire(evaluation) if evaluation is not None else None,
        "weeks": week_summaries,
    }
    _atomic_write_json(quarter_manifest_path, quarter_manifest)
    return out_dir


def validate_quarter_pack(
    pack_dir: Path,
    expected_weeks: int | None = None,
) -> dict[str, Any]:
    """Validate an on-disk quarterly 3D pack and verify every week-XX shift bundle."""
    pack_dir = Path(pack_dir)
    _ensure_not_symlink(pack_dir)
    if not pack_dir.exists() or not pack_dir.is_dir():
        raise ValueError(f"Quarter pack directory does not exist: {pack_dir}")

    qm_path = pack_dir / "quarter_manifest.json"
    weeks_root = pack_dir / "weeks"
    _ensure_not_symlink(qm_path)
    _ensure_not_symlink(weeks_root)
    if not qm_path.is_file():
        raise ValueError(f"Missing regular quarter_manifest.json in {pack_dir}")
    if not weeks_root.is_dir():
        raise ValueError(f"Missing weeks/ directory in {pack_dir}")

    for dirpath, dirnames, filenames in os.walk(pack_dir, followlinks=False):
        for name in (*dirnames, *filenames):
            entry = Path(dirpath) / name
            if entry.is_symlink():
                raise ValueError(f"Refusing symlink inside quarter pack: {entry}")

    qm = _strict_json_loads(qm_path.read_text(encoding="utf-8"))
    if type(qm) is not dict:
        raise ValueError("quarter_manifest.json must be a JSON object")
    if qm.get("replay_pack_format") != QUARTER_PACK_FORMAT_V1:
        raise ValueError(f"Unsupported replay_pack_format: {qm.get('replay_pack_format')!r}")
    if not _is_strict_int(qm.get("schema_version")) or qm["schema_version"] != 2:
        raise ValueError("quarter_manifest.schema_version must be integer 2")
    if not _is_strict_int(qm.get("seed")):
        raise ValueError("quarter_manifest.seed must be an integer")
    for int_key in ("purchase", "total_cost", "labor_ticks"):
        if not _is_strict_int(qm.get(int_key)) or qm[int_key] < 0:
            raise ValueError(f"quarter_manifest.{int_key} must be a non-negative integer")

    plan_obj = qm.get("plan")
    weeks_list = qm.get("weeks")
    if (
        type(plan_obj) is not dict
        or plan_obj.keys() != {"schema_version", "weeks"}
        or not _is_strict_int(plan_obj.get("schema_version"))
        or plan_obj["schema_version"] != 2
        or type(plan_obj.get("weeks")) is not list
    ):
        raise ValueError("quarter_manifest.plan must be a schema_version=2 object with a weeks list")
    if type(weeks_list) is not list or not weeks_list:
        raise ValueError("quarter_manifest.weeks must be a non-empty list")
    if len(plan_obj["weeks"]) != len(weeks_list):
        raise ValueError("quarter_manifest plan.weeks length mismatch with weeks summary")
    if expected_weeks is not None and len(weeks_list) != expected_weeks:
        raise ValueError(f"Expected {expected_weeks} weeks, got {len(weeks_list)}")

    actual_week_entries = sorted(p.name for p in weeks_root.iterdir())
    expected_week_entries = [f"week-{i:02d}" for i in range(len(weeks_list))]
    if actual_week_entries != expected_week_entries:
        raise ValueError(
            f"weeks/ directory entries {actual_week_entries!r} do not match expected {expected_week_entries!r}"
        )

    seen_robot = False
    seen_trays = False
    last_prices: dict[str, Any] | None = None
    week_audits: list[dict[str, Any]] = []
    for idx, week_entry in enumerate(weeks_list):
        if type(week_entry) is not dict:
            raise ValueError(f"Week entry #{idx} must be an object")
        expected_id = f"week-{idx:02d}"
        expected_rel = f"weeks/{expected_id}"
        if (
            week_entry.get("week") != idx
            or week_entry.get("week_id") != expected_id
            or week_entry.get("bundle_dir") != expected_rel
            or week_entry.get("manifest_file") != f"{expected_rel}/manifest.json"
            or week_entry.get("events_file") != f"{expected_rel}/events.jsonl"
            or week_entry.get("replay_format") != REPLAY_FORMAT_V1
        ):
            raise ValueError(f"Week entry #{idx} has inconsistent bundle metadata: {week_entry!r}")

        wp = plan_obj["weeks"][idx]
        if type(wp) is not dict or wp.keys() != {"robot", "trays", "route", "maintenance", "workers"}:
            raise ValueError(f"quarter_manifest.plan.weeks[{idx}] has invalid keys")
        if (
            type(wp["robot"]) is not bool
            or type(wp["trays"]) is not bool
            or type(wp["maintenance"]) is not bool
        ):
            raise ValueError(f"quarter_manifest.plan.weeks[{idx}] flags must be booleans")
        if (seen_robot and not wp["robot"]) or (seen_trays and not wp["trays"]):
            raise ValueError(
                f"Week {idx} violates irreversible CapEx monotonicity in quarter_manifest.plan"
            )
        seen_robot = seen_robot or wp["robot"]
        seen_trays = seen_trays or wp["trays"]
        if wp["maintenance"] and not wp["robot"]:
            raise ValueError(f"Week {idx} has maintenance=True without robot=True")
        if wp["route"] != "manual" and not wp["robot"]:
            raise ValueError(f"Week {idx} has route={wp['route']!r} without robot=True")

        expected_shift_plan = {
            "schema_version": SCHEMA_VERSION,
            "robot": wp["robot"],
            "trays": wp["trays"],
            "route": wp["route"],
            "workers": wp["workers"],
        }
        if week_entry.get("shift_plan") != expected_shift_plan:
            raise ValueError(
                f"Week {idx} shift_plan in quarter_manifest mismatches plan.weeks[{idx}]"
            )
        if week_entry.get("maintenance") is not wp["maintenance"]:
            raise ValueError(
                f"Week {idx} maintenance flag in quarter_manifest mismatches plan.weeks[{idx}]"
            )

        we = week_entry.get("week_economy")
        if (
            type(we) is not dict
            or we.keys() != {"purchase", "costs", "total"}
            or not _is_strict_int(we["purchase"])
            or we["purchase"] < 0
            or not _is_strict_int(we["total"])
            or we["total"] < 0
            or type(we["costs"]) is not dict
            or not we["costs"]
            or any(not _is_strict_int(v) or v < 0 for v in we["costs"].values())
            or we["total"] != sum(we["costs"].values())
        ):
            raise ValueError(f"Week {idx} week_economy in quarter_manifest is invalid")

        week_bundle_dir = pack_dir / expected_rel
        shift_audit = validate_shift_bundle(week_bundle_dir)
        shift_manifest = _strict_json_loads((week_bundle_dir / "manifest.json").read_text(encoding="utf-8"))
        last_prices = shift_manifest["world"]["money"]
        if shift_manifest["raw"] != week_entry.get("raw"):
            raise ValueError(f"Week {idx} raw summary in quarter_manifest mismatches shift manifest")
        if shift_manifest["economy"] != week_entry.get("shift_economy"):
            raise ValueError(f"Week {idx} shift_economy in quarter_manifest mismatches shift manifest")
        if shift_manifest["plan"] != week_entry.get("shift_plan"):
            raise ValueError(f"Week {idx} shift_plan in quarter_manifest mismatches shift manifest")
        week_audits.append(
            {
                "week": idx,
                "label": week_entry.get("label", f"week_{idx}"),
                "bundle_dir": expected_rel,
                "event_count": shift_audit["event_count"],
                "summary": shift_audit["summary"],
            }
        )

    expected_labor_ticks = sum(w["raw"]["labor_ticks"] for w in weeks_list)
    if qm["labor_ticks"] != expected_labor_ticks:
        raise ValueError(
            f"quarter_manifest.labor_ticks ({qm['labor_ticks']}) != sum of weekly labor_ticks ({expected_labor_ticks})"
        )
    expected_total_cost = sum(w["week_economy"]["total"] for w in weeks_list)
    if qm["total_cost"] != expected_total_cost:
        raise ValueError(
            f"quarter_manifest.total_cost ({qm['total_cost']}) != sum of weekly week_economy.total ({expected_total_cost})"
        )
    if last_prices is not None:
        expected_purchase = (last_prices["robot_purchase"] if seen_robot else 0) + (
            last_prices["tray_purchase"] if seen_trays else 0
        )
        if qm["purchase"] != expected_purchase:
            raise ValueError(
                f"quarter_manifest.purchase ({qm['purchase']}) != expected CapEx purchase ({expected_purchase})"
            )

    return {
        "ok": True,
        "pack_dir": str(pack_dir),
        "seed": qm["seed"],
        "weeks_count": len(week_audits),
        "summary": {
            "purchase": qm["purchase"],
            "total_cost": qm["total_cost"],
            "labor_ticks": qm["labor_ticks"],
        },
        "weeks": week_audits,
    }
