from dataclasses import asdict, dataclass, replace
import hashlib
import http.client
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys
import threading
import types
import urllib.request

from robotization_bench.contracts import Economy, Evaluation, InvalidPlan, Order, Plan, ROOT, Scenario, load_world
from robotization_bench.economics import calculate
from robotization_bench.engine import simulate
from robotization_bench.grading import evaluate, manual_value
from robotization_bench.reporting import (
    build_shift_manifest,
    compare,
    export_events,
    export_quarter_pack,
    export_shift_bundle,
    validate_quarter_pack,
    validate_shift_bundle,
)
from robotization_bench.scenarios import generate
from robotization_bench.validation import parse_plan
import pytest


_CYRILLIC_RE = re.compile(r"[\u0400-\u04ff]")


def test_compare_english_tables_reasons_and_no_cyrillic():
    assert compare({}) == "No evaluated plans."

    world = load_world()
    days = tuple(generate(world, seed) for seed in world["development_seeds"])
    manual = evaluate(world, manual_value(), days)
    winner = evaluate(world, json.loads((ROOT / "data/plans/candidate.json").read_text()), days)
    idle_capex = evaluate(
        world,
        {
            "schema_version": 1,
            "robot": True,
            "trays": True,
            "route": "manual",
            "workers": manual_value()["workers"],
        },
        days,
    )
    tight_world = json.loads(json.dumps(world))
    tight_world["money"]["budget"] = 1_000_000
    infeasible = evaluate(
        tight_world,
        {
            "schema_version": 1,
            "robot": True,
            "trays": False,
            "route": "all",
            "workers": [[1, 2, 3, 4]],
        },
        days,
    )
    no_plan = evaluate(world, None, days)
    v2_reasons_dict = {
        **asdict(manual),
        "feasible": False,
        "win": False,
        "reward_num": 1,
        "reward_den": 10_000,
        "reasons": [
            "good_each_week",
            "good_pooled",
            "on_time_pooled",
            "escaped_each_week_max",
            "auto_pack_pooled_min",
            "stop_early",
            "Custom|Reason\nLine2",
        ],
    }

    report = compare(
        {
            "manual": manual,
            "candidate": winner,
            "idle_capex": idle_capex,
            "over_budget": infeasible,
            "plan|pipe\nline": v2_reasons_dict,
            "stopped": no_plan,
        }
    )

    assert not _CYRILLIC_RE.search(report)
    assert "| Plan | Feasible | Win | Reward | CapEx | Operating Cost |" in report
    assert "| Plan | Orders | Good | On-Time | Escaped Defects | Scrap | Unfinished |" in report
    assert "| manual | yes | no | 1/5 (0.200000) | €0.00 |" in report
    assert f"| €0.00 | {manual.metrics['labor_ticks']} / {manual.metrics['base_labor_ticks']} |" in report
    assert "| candidate | yes | yes |" in report
    assert "-€" in report  # idle_capex has higher operating cost than manual -> negative savings
    assert "| over_budget | no | no |" in report
    assert r"| plan\|pipe line | no | no | 1/10000 (0.000100) |" in report
    assert "| stopped | invalid | no | 0/1 (0.000000) | — | — | — | — | — |" in report
    assert f"| manual | {manual.metrics['orders']} | {manual.metrics['good']} |" in report
    assert "| stopped | " not in report.split("| Plan | Orders |")[1]
    assert "- manual: operating cost did not beat manual baseline" in report
    assert "active labor ticks did not beat manual baseline" in report
    assert "automated pack share below minimum threshold" in report
    assert "CapEx purchase exceeds budget ceiling" in report
    assert "weekly good-order completion rate below SLA threshold" in report
    assert "pooled good-order completion rate below SLA threshold" in report
    assert "pooled on-time delivery rate below SLA threshold" in report
    assert "weekly escaped defect rate exceeds SLA maximum" in report
    assert "episode stopped without submitting a plan" in report
    assert r"Custom\|Reason Line2" in report

    # Also verify compare() when ONLY invalid submissions exist (outcomes table omitted)
    invalid_only = compare({"nop": no_plan})
    assert not _CYRILLIC_RE.search(invalid_only)
    assert "| Plan | Orders |" not in invalid_only


def test_compare_preserves_distinct_reward_fractions():
    world = load_world()
    day = generate(world, 11)
    base = evaluate(world, manual_value(), (day,))
    a = replace(base, reward_num=19_999, reward_den=100_000)
    b = replace(base, reward_num=19_998, reward_den=100_001)
    report = compare({"a": a, "b": b})
    assert "19999/100000 (0.199990)" in report
    assert "19998/100001 (0.199978)" in report
    assert not _CYRILLIC_RE.search(report)


def test_export_events_round_trips_trace_and_empty_events(tmp_path):
    world = load_world()
    day = generate(world, world["development_seeds"][0])
    plan = parse_plan(manual_value(), world)
    shift = simulate(world, plan, day, trace=True)
    destination = tmp_path / "exports" / "shift.jsonl"
    export_events(shift, destination)
    raw_lines = destination.read_text(encoding="utf-8").splitlines()
    assert all(": " not in line and ", " not in line for line in raw_lines)
    timeline = [json.loads(line) for line in raw_lines]
    assert timeline == [asdict(event) for event in shift.events]
    assert all(
        set(ev.keys()) == {"tick", "kind", "order_id", "resource", "stage", "attempt", "end_tick"}
        for ev in timeline
    )
    assert timeline[0]["kind"] == "arrival"
    assert timeline[1]["tick"] == timeline[0]["tick"]
    assert timeline[-1]["kind"] in {"good", "scrap", "escaped"}

    export_events(replace(shift, events=()), destination)
    assert destination.read_bytes() == b""


def test_build_shift_manifest_matches_368bf27_and_wire_types():
    world = load_world()
    cand_json = json.loads((ROOT / "data/plans/candidate.json").read_text(encoding="utf-8"))
    day_json = json.loads((ROOT / "data/development/11.json").read_text(encoding="utf-8"))
    plan = parse_plan(cand_json, world)
    day = generate(world, 11)
    raw = simulate(world, plan, day, trace=True)
    econ = calculate(world, plan, raw)
    orig_event_count = len(raw.events)
    assert orig_event_count > 0

    manifest = build_shift_manifest(world, plan, day, raw, econ)
    assert set(manifest.keys()) == {
        "replay_format",
        "world",
        "plan",
        "scenario",
        "raw",
        "economy",
        "events_file",
    }
    assert manifest["replay_format"] == "robotization-bench.replay.v1"
    assert manifest["events_file"] == "events.jsonl"
    assert type(manifest["plan"]["workers"]) is list
    assert all(type(z) is list for z in manifest["plan"]["workers"])
    assert parse_plan(manifest["plan"], manifest["world"]) == plan
    assert manifest["plan"] == cand_json
    assert manifest["scenario"] == day_json
    assert manifest["raw"]["events"] == []
    assert type(manifest["raw"]["events"]) is list
    assert type(manifest["raw"]["overtime_ticks"]) is list
    assert len(raw.events) == orig_event_count
    assert set(manifest["economy"]["costs"].keys()) == {
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
    assert manifest["economy"]["total"] == sum(manifest["economy"]["costs"].values())

    # Deep-copy isolation check
    orig_shift_ticks = world["clock"]["shift_ticks"]
    manifest["world"]["clock"]["shift_ticks"] = 999_999
    assert world["clock"]["shift_ticks"] == orig_shift_ticks

    # Validation failures on bad schema_version, bad economy, NaN, and bad events_file
    with pytest.raises(ValueError):
        build_shift_manifest(world, {**cand_json, "schema_version": 2}, day, raw, econ)
    with pytest.raises(ValueError):
        build_shift_manifest(world, plan, {**day_json, "schema_version": 2}, raw, econ)
    with pytest.raises(ValueError):
        bad_econ = {"purchase": econ.purchase, "costs": dict(econ.costs), "total": econ.total + 1}
        build_shift_manifest(world, plan, day, raw, bad_econ)
    with pytest.raises(ValueError):
        missing_key_costs = {k: v for k, v in econ.costs.items() if k != "escaped"}
        build_shift_manifest(
            world,
            plan,
            day,
            raw,
            {"purchase": econ.purchase, "costs": missing_key_costs, "total": sum(missing_key_costs.values())},
        )
    with pytest.raises(ValueError):
        nan_world = json.loads(json.dumps(world))
        nan_world["extra_nan"] = float("nan")
        build_shift_manifest(nan_world, plan, day, raw, econ)
    with pytest.raises(ValueError):
        build_shift_manifest(world, plan, day, raw, econ, events_file="../escape.jsonl")


def test_export_shift_bundle_atomic_write_and_guards(tmp_path):
    world = load_world()
    plan = parse_plan(manual_value(), world)
    day = generate(world, 11)
    raw = simulate(world, plan, day, trace=True)
    econ = calculate(world, plan, raw)

    out_dir = tmp_path / "shift_bundle"
    returned = export_shift_bundle(world, plan, day, raw, econ, out_dir)
    assert returned == out_dir
    assert (out_dir / "manifest.json").is_file()
    assert (out_dir / "events.jsonl").is_file()
    assert len((out_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()) == len(raw.events)

    # Also supports dict inputs cleanly
    dict_dir = tmp_path / "dict_bundle"
    export_shift_bundle(
        world,
        manual_value(),
        json.loads(json.dumps(asdict(day))),
        json.loads(json.dumps(asdict(raw))),
        json.loads(json.dumps(asdict(econ))),
        dict_dir,
    )
    assert validate_shift_bundle(dict_dir)["ok"] is True

    # Guard against trace=False (non-empty orders with empty events)
    untraced = simulate(world, plan, day, trace=False)
    untraced_dir = tmp_path / "untraced_bundle"
    with pytest.raises(ValueError, match="trace"):
        export_shift_bundle(world, plan, day, untraced, econ, untraced_dir)
    assert not (untraced_dir / "manifest.json").exists()

    # Symlink guards on out_dir, manifest.json, and events.jsonl
    victim_dir = tmp_path / "victim_dir"
    victim_dir.mkdir()
    symlink_out = tmp_path / "symlink_out"
    symlink_out.symlink_to(victim_dir)
    with pytest.raises(ValueError, match="symlink"):
        export_shift_bundle(world, plan, day, raw, econ, symlink_out)
    assert list(victim_dir.iterdir()) == []

    victim_file = tmp_path / "victim.txt"
    victim_file.write_text("SACRED_CONTENT", encoding="utf-8")

    guarded_m = tmp_path / "guarded_manifest"
    guarded_m.mkdir()
    (guarded_m / "manifest.json").symlink_to(victim_file)
    with pytest.raises(ValueError, match="symlink"):
        export_shift_bundle(world, plan, day, raw, econ, guarded_m)
    assert victim_file.read_text(encoding="utf-8") == "SACRED_CONTENT"

    guarded_e = tmp_path / "guarded_events"
    guarded_e.mkdir()
    (guarded_e / "events.jsonl").symlink_to(victim_file)
    with pytest.raises(ValueError, match="symlink"):
        export_shift_bundle(world, plan, day, raw, econ, guarded_e)
    assert victim_file.read_text(encoding="utf-8") == "SACRED_CONTENT"


def test_validate_shift_bundle_golden_traces_and_legitimate_bad_plans(tmp_path):
    # 1. Golden Trace 1 (368bf27 §16.1): single regular order at H=28 vs H=27, plus two orders at 28 & 58
    for overtime, expected_good, expected_labor in ((8, 1, 28), (7, 0, 27)):
        w1 = load_world()
        w1["clock"].update(shift_ticks=20, overtime_ticks=overtime, break_at=440, break_length=40)
        w1["prob_bps"]["defect_manual"]["regular"] = 0
        p1 = Plan(1, False, False, "manual", ((1, 2, 3, 4),))
        s1 = Scenario(1, 7, (Order(7, "regular", 0, 28),))
        r1 = simulate(w1, p1, s1, trace=True)
        assert (r1.good, r1.unfinished, r1.labor_ticks) == (expected_good, 1 - expected_good, expected_labor)
        e1 = calculate(w1, p1, r1)
        b1 = export_shift_bundle(w1, p1, s1, r1, e1, tmp_path / f"golden1_h{20 + overtime}")
        res1 = validate_shift_bundle(b1)
        assert res1["ok"] is True

    w1_pair = load_world()
    w1_pair["clock"].update(shift_ticks=60, overtime_ticks=0, break_at=440, break_length=40)
    w1_pair["prob_bps"]["defect_manual"]["regular"] = 0
    p1_pair = Plan(1, False, False, "manual", ((1, 2, 3, 4),))
    s1_pair = Scenario(1, 7, (Order(0, "regular", 0, 60), Order(1, "regular", 0, 60)))
    r1_pair = simulate(w1_pair, p1_pair, s1_pair, trace=True)
    assert [ev.tick for ev in r1_pair.events if ev.kind == "good"] == [28, 58]
    assert validate_shift_bundle(
        export_shift_bundle(w1_pair, p1_pair, s1_pair, r1_pair, calculate(w1_pair, p1_pair, r1_pair), tmp_path / "golden1_pair")
    )["ok"] is True

    # 2. Golden Trace 2 (368bf27 §16.2): jam at 13, break [12,17), assist [17,27) with walk [17,19), good at 32
    for horizon, exp_good, exp_labor in ((13, 0, 10), (22, 0, 15), (27, 0, 20), (32, 1, 25)):
        w2 = load_world()
        w2["clock"].update(shift_ticks=12, overtime_ticks=horizon - 12, break_at=12, break_length=5)
        w2["prob_bps"]["jam"]["tray"]["regular"] = 10_000
        w2["prob_bps"]["defect_auto"]["tray"]["regular"] = 0
        p2 = Plan(1, True, True, "all", ((1, 2, 3, 4),))
        s2 = Scenario(1, 42, (Order(0, "regular", 0, 32),))
        r2 = simulate(w2, p2, s2, trace=True)
        assert (r2.good, r2.labor_ticks) == (exp_good, exp_labor)
        b2 = export_shift_bundle(w2, p2, s2, r2, calculate(w2, p2, r2), tmp_path / f"golden2_h{horizon}")
        assert validate_shift_bundle(b2)["ok"] is True

    # 3. Rework (scrap & escaped) in separate R queue + congested bypass non-FIFO skip
    for detect_bps, tag in ((10_000, "scrap"), (0, "escaped")):
        w3 = load_world()
        w3["capacity"]["pack"] = 1
        w3["prob_bps"]["defect_auto"]["tray"]["oversize"] = 10_000
        w3["prob_bps"]["defect_manual"]["oversize"] = 10_000
        w3["prob_bps"]["jam"]["tray"]["oversize"] = 0
        w3["prob_bps"]["detect"] = detect_bps
        p3 = Plan(1, True, True, "all", ((1,), (2,), (3,), (4,)))
        s3 = Scenario(1, 47, (Order(13, "oversize", 0, 100),))
        r3 = simulate(w3, p3, s3, trace=True)
        b3 = export_shift_bundle(w3, p3, s3, r3, calculate(w3, p3, r3), tmp_path / f"rework_{tag}")
        assert validate_shift_bundle(b3)["ok"] is True

    w_bypass = load_world()
    w_bypass["capacity"].update(pick=2, pack=2, qc=2)
    p_bypass = Plan(1, True, True, "bypass", ((1, 2), (3, 4), (2, 3)))
    d_bypass = generate(w_bypass, 29)
    r_bypass = simulate(w_bypass, p_bypass, d_bypass, trace=True)
    b_bypass = export_shift_bundle(
        w_bypass, p_bypass, d_bypass, r_bypass, calculate(w_bypass, p_bypass, r_bypass), tmp_path / "congested_bypass"
    )
    assert validate_shift_bundle(b_bypass)["ok"] is True

    # 4. Legitimate bad plan: unstaffed_jam_deadlock (events stop early before H, permanent jam, unfinished > 0)
    w_dead = load_world()
    p_dead = Plan(1, True, False, "all", ((1,), (2,), (4,)))
    d_dead = generate(w_dead, 11)
    r_dead = simulate(w_dead, p_dead, d_dead, trace=True)
    assert r_dead.unfinished > 0 and r_dead.pack_finished < r_dead.pack_started
    assert r_dead.events[-1].tick < w_dead["clock"]["shift_ticks"] + w_dead["clock"]["overtime_ticks"]
    b_dead = export_shift_bundle(
        w_dead, p_dead, d_dead, r_dead, calculate(w_dead, p_dead, r_dead), tmp_path / "unstaffed_jam_deadlock"
    )
    res_dead = validate_shift_bundle(b_dead)
    assert res_dead["ok"] is True
    assert res_dead["summary"]["unfinished"] == r_dead.unfinished

    # Also test 100% immediate jam (good == 0, unfinished == total)
    w_dead0 = load_world()
    w_dead0["prob_bps"]["jam"]["bare"]["regular"] = 10_000
    s_dead0 = Scenario(1, 11, (Order(0, "regular", 0, 40), Order(1, "regular", 0, 45)))
    r_dead0 = simulate(w_dead0, p_dead, s_dead0, trace=True)
    assert r_dead0.good == 0 and r_dead0.unfinished == 2
    b_dead0 = export_shift_bundle(
        w_dead0, p_dead, s_dead0, r_dead0, calculate(w_dead0, p_dead, r_dead0), tmp_path / "unstaffed_jam_zero_good"
    )
    assert validate_shift_bundle(b_dead0)["ok"] is True


def test_validate_shift_bundle_reports_line_numbers_on_corrupted_traces(tmp_path):
    world = load_world()
    world["clock"].update(shift_ticks=40, overtime_ticks=10, break_at=440, break_length=40)
    world["prob_bps"]["defect_manual"]["regular"] = 0
    plan = Plan(1, False, False, "manual", ((1, 2, 3, 4),))
    day = Scenario(1, 7, (Order(7, "regular", 0, 28),))
    raw = simulate(world, plan, day, trace=True)
    econ = calculate(world, plan, raw)

    base_dir = tmp_path / "clean"
    export_shift_bundle(world, plan, day, raw, econ, base_dir)
    base_manifest = json.loads((base_dir / "manifest.json").read_text(encoding="utf-8"))
    base_lines = [json.loads(line) for line in (base_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]

    def make_case(name: str, manifest_mod=None, lines_mod=None) -> Path:
        case_dir = tmp_path / f"corrupt_{name}"
        case_dir.mkdir()
        m = json.loads(json.dumps(base_manifest))
        if manifest_mod is not None:
            manifest_mod(m)
        lines = json.loads(json.dumps(base_lines))
        if lines_mod is not None:
            lines_mod(lines)
        (case_dir / "manifest.json").write_text(json.dumps(m) + "\n", encoding="utf-8")
        (case_dir / "events.jsonl").write_text(
            "\n".join(json.dumps(ev, separators=(",", ":")) for ev in lines) + "\n",
            encoding="utf-8",
        )
        return case_dir

    # JSONL corruptions that MUST report the exact 1-based line number
    line_cases = [
        ("unknown_kind", 2, lambda ls: ls[1].update(kind="teleport")),
        ("decreasing_tick", 5, lambda ls: ls[4].update(tick=ls[3]["tick"] - 1)),
        ("extra_key", 3, lambda ls: ls[2].update(extra_field=123)),
        ("missing_key", 3, lambda ls: ls[2].pop("end_tick")),
        ("unknown_order", 1, lambda ls: ls[0].update(order_id=999)),
        ("unknown_resource", 3, lambda ls: ls[2].update(resource="w99")),
        ("broken_sequence", 2, lambda ls: ls[1].update(kind="finish", resource="w0", end_tick=None)),
        ("attempt_two", 2, lambda ls: ls[1].update(attempt=2)),
        (
            "start_at_horizon",
            len(base_lines) + 1,
            lambda ls: ls.append(
                {"tick": 50, "kind": "start", "order_id": 7, "resource": "w0", "stage": 1, "attempt": 0, "end_tick": 53}
            ),
        ),
        (
            "duplicate_terminal",
            len(base_lines) + 1,
            lambda ls: ls.append(
                {"tick": 28, "kind": "scrap", "order_id": 7, "resource": "w0", "stage": 4, "attempt": 1, "end_tick": None}
            ),
        ),
        (
            "orphan_walk",
            4,
            lambda ls: ls.insert(
                3,
                {"tick": 1, "kind": "walk", "order_id": 7, "resource": "w0", "stage": 2, "attempt": 0, "end_tick": 3},
            ),
        ),
    ]
    for name, expected_line, mutator in line_cases:
        corrupt_dir = make_case(name, lines_mod=mutator)
        with pytest.raises(ValueError) as exc_info:
            validate_shift_bundle(corrupt_dir)
        assert f"line {expected_line}" in str(exc_info.value).lower(), (
            f"Case {name} did not report line {expected_line}: {exc_info.value}"
        )

    # Queue Q4 capacity overflow reports line number of offending stage-3 start
    q4_overflow = make_case(
        "q4_overflow",
        manifest_mod=lambda m: m["world"]["capacity"].update(qc=0),
    )
    # Find 1-based line of stage=3 start
    stage3_start_line = next(
        idx for idx, ev in enumerate(base_lines, start=1) if ev["kind"] == "start" and ev["stage"] == 3
    )
    with pytest.raises(ValueError) as q4_exc:
        validate_shift_bundle(q4_overflow)
    assert f"line {stage3_start_line}" in str(q4_exc.value).lower()

    # Manifest-level corruptions (unsupported replay_format, bad schema_version, tampered raw/economy)
    for name, m_mut in (
        ("bad_format", lambda m: m.update(replay_format="robotization-bench.replay.v99")),
        ("bad_plan_ver", lambda m: m["plan"].update(schema_version=2)),
        ("tampered_raw_good", lambda m: m["raw"].update(good=99)),
        ("tampered_econ_total", lambda m: m["economy"].update(total=m["economy"]["total"] + 10)),
    ):
        with pytest.raises(ValueError):
            validate_shift_bundle(make_case(name, manifest_mod=m_mut))


@dataclass(frozen=True)
class _DuckWeekPlan:
    robot: bool
    trays: bool
    route: str
    maintenance: bool
    workers: tuple[tuple[int, ...], ...]

    def to_shift_plan(self) -> Plan:
        return Plan(1, self.robot, self.trays, self.route, self.workers)


@dataclass(frozen=True)
class _DuckQuarterlyPlan:
    schema_version: int
    weeks: tuple[_DuckWeekPlan, ...]


@dataclass(frozen=True)
class _DuckWeekReport:
    week: int
    label: str
    week_seed: int
    carryover_in: int
    carryover_out: int
    wear_start: int
    wear_end: int
    commissioning_active: bool
    shift_plan: Plan
    scenario: Scenario
    raw: object
    shift_economy: Economy
    week_economy: Economy
    week_world: dict | None = None


@dataclass(frozen=True)
class _DuckQuarterReport:
    schema_version: int
    seed: int
    purchase: int
    total_cost: int
    labor_ticks: int
    weeks: tuple[_DuckWeekReport, ...]


def _make_week_world(base_world: dict, week: int, *, commissioning: bool, wear: int, maintenance: bool) -> dict:
    ww = json.loads(json.dumps(base_world))
    ww.pop("quarterly", None)
    if maintenance:
        for rig in ("bare", "tray"):
            for k in ww["time"]["auto"][rig]:
                ww["time"]["auto"][rig][k] += 1
    if commissioning or wear > 0:
        bonus = (650 if commissioning else 0) + wear * 50
        for k in ww["prob_bps"]["jam"]["tray"]:
            ww["prob_bps"]["jam"]["tray"][k] = min(9_900, ww["prob_bps"]["jam"]["tray"][k] + bonus)
    return ww


def _build_duck_quarter_fixture(
    base_world: dict,
    seed: int = 11,
    *,
    automated: bool = True,
    attach_explicit_week_world: bool = False,
    trace: bool = True,
) -> tuple[_DuckQuarterlyPlan, _DuckQuarterReport]:
    q_weeks_plan = []
    q_weeks_report = []
    total_cost = 0
    total_labor = 0

    for w in range(12):
        maint = bool(automated and w == 7)
        wp = _DuckWeekPlan(
            robot=automated,
            trays=automated,
            route="bypass" if automated else "manual",
            maintenance=maint,
            workers=((1,), (2,), (3, 4), (2, 3)) if automated else ((1,), (2,), (3,), (3,), (4,), (2, 3)),
        )
        sp = wp.to_shift_plan()
        commissioning = bool(automated and w < 2)
        wear_start = (w % 4) if automated else 0
        wear_end = max(0, wear_start - 3) if maint else (wear_start + (1 if automated else 0))
        eff_world = _make_week_world(
            base_world, w, commissioning=commissioning, wear=wear_start, maintenance=maint
        )

        # Include carried-over orders at arrival=0, due=0 on weeks > 0 + regular arrivals
        carry_in = 2 if w > 0 else 0
        orders = []
        for cid in range(carry_in):
            orders.append(Order(cid, "regular", 0, 0))
        orders.extend(
            [
                Order(10 + 3 * idx, "regular", 10 * idx, 180 + 10 * idx)
                for idx in range(4)
            ]
        )
        orders.append(Order(99, "fragile", 45, 240))
        scen = Scenario(1, seed * 100 + w, tuple(orders))
        raw = simulate(eff_world, sp, scen, trace=trace)
        shift_econ = calculate(eff_world, sp, raw)

        # 14-key v2 week_economy distinct from 10-key v1 shift_economy
        v2_costs = {
            "depreciation": shift_econ.costs["depreciation"] * 5,
            "service": 3500 if automated else 0,
            "maintenance": 4500 if maint else 0,
            "shifts": shift_econ.costs["shifts"] * 5,
            "cross_skill": 1800,
            "overtime": shift_econ.costs["overtime"],
            "hiring_retraining": 9000 if w == 0 and automated else 0,
            "trays": shift_econ.costs["trays"],
            "materials": shift_econ.costs["materials"],
            "rework": shift_econ.costs["rework"],
            "late": shift_econ.costs["late"],
            "backlog_holding": raw.unfinished * 600,
            "unfulfilled": shift_econ.costs["unfulfilled"] if w == 11 else 0,
            "escaped": shift_econ.costs["escaped"],
        }
        week_econ = Economy(
            purchase=shift_econ.purchase if w == 0 else 0,
            costs=v2_costs,
            total=sum(v2_costs.values()),
        )
        total_cost += week_econ.total
        total_labor += raw.labor_ticks

        q_weeks_plan.append(wp)
        q_weeks_report.append(
            _DuckWeekReport(
                week=w,
                label=f"week_{w:02d}",
                week_seed=scen.seed,
                carryover_in=carry_in,
                carryover_out=raw.unfinished,
                wear_start=wear_start,
                wear_end=wear_end,
                commissioning_active=commissioning,
                shift_plan=sp,
                scenario=scen,
                raw=raw,
                shift_economy=shift_econ,
                week_economy=week_econ,
                week_world=eff_world if attach_explicit_week_world else None,
            )
        )

    purchase = 1_530_000 if automated else 0
    q_plan = _DuckQuarterlyPlan(2, tuple(q_weeks_plan))
    q_report = _DuckQuarterReport(2, seed, purchase, total_cost, total_labor, tuple(q_weeks_report))
    return q_plan, q_report


def test_export_quarter_pack_duck_typed_12_weeks_and_world_tiers(tmp_path, monkeypatch):
    # Confirm reporting.py has zero top-level dependency on robotization_bench.quarterly
    assert "robotization_bench.quarterly" not in sys.modules

    base_world = load_world()
    days = tuple(generate(base_world, s) for s in base_world["development_seeds"])
    eval_obj = evaluate(base_world, json.loads((ROOT / "data/plans/candidate.json").read_text()), days)

    # Tier 1: Explicit week_report.week_world on frozen dataclasses
    q_plan_dc, q_report_dc = _build_duck_quarter_fixture(
        base_world, seed=11, automated=True, attach_explicit_week_world=True
    )
    out_dc = tmp_path / "quarter_dc"
    res_path = export_quarter_pack(base_world, q_report_dc, q_plan_dc, out_dc, evaluation=eval_obj)
    assert res_path == out_dc
    qm = json.loads((out_dc / "quarter_manifest.json").read_text(encoding="utf-8"))
    assert qm["replay_pack_format"] == "robotization-bench.quarter-pack.v1"
    assert qm["schema_version"] == 2
    assert qm["seed"] == 11
    assert qm["purchase"] == q_report_dc.purchase
    assert qm["total_cost"] == q_report_dc.total_cost
    assert qm["labor_ticks"] == q_report_dc.labor_ticks
    assert qm["evaluation"]["win"] is True
    assert len(qm["weeks"]) == 12

    # Week 7 had maintenance=True -> auto regular tray time incremented by +1 tick in week_world
    w07_manifest = json.loads((out_dc / "weeks/week-07/manifest.json").read_text(encoding="utf-8"))
    assert (
        w07_manifest["world"]["time"]["auto"]["tray"]["regular"]
        == base_world["time"]["auto"]["tray"]["regular"] + 1
    )
    assert w07_manifest["plan"]["schema_version"] == 1
    assert len(w07_manifest["economy"]["costs"]) == 10
    assert len(qm["weeks"][7]["week_economy"]["costs"]) == 14

    q_audit = validate_quarter_pack(out_dc, expected_weeks=12)
    assert q_audit["ok"] is True
    assert q_audit["weeks_count"] == 12
    for w in range(12):
        assert validate_shift_bundle(out_dc / "weeks" / f"week-{w:02d}")["ok"] is True

    # Tier 2: Lazy robotization_bench.quarterly.build_week_world resolution + plain JSON dicts
    world_with_q = json.loads(json.dumps(base_world))
    world_with_q["quarterly"] = {"schema_version": 2, "world_id": "cell-quarterly-v2", "weeks": 12}
    q_plan_lazy, q_report_lazy = _build_duck_quarter_fixture(
        base_world, seed=29, automated=True, attach_explicit_week_world=False
    )
    calls = []

    def fake_build_week_world(w, week_num, *, commissioning, wear, maintenance):
        calls.append((week_num, commissioning, wear, maintenance))
        return _make_week_world(w, week_num, commissioning=commissioning, wear=wear, maintenance=maintenance)

    fake_q_mod = types.ModuleType("robotization_bench.quarterly")
    fake_q_mod.build_week_world = fake_build_week_world
    monkeypatch.setitem(sys.modules, "robotization_bench.quarterly", fake_q_mod)

    q_plan_dict = json.loads(json.dumps(asdict(q_plan_lazy)))
    q_report_dict = json.loads(json.dumps(asdict(q_report_lazy)))
    for w_entry in q_report_dict["weeks"]:
        w_entry.pop("week_world", None)
        w_entry.pop("shift_plan", None)  # Verify fallback to week_plan extraction too!

    out_dict = tmp_path / "quarter_dict_lazy"
    export_quarter_pack(world_with_q, q_report_dict, q_plan_dict, out_dict)
    assert len(calls) == 12
    assert validate_quarter_pack(out_dict, expected_weeks=12)["ok"] is True
    qm_lazy = json.loads((out_dict / "quarter_manifest.json").read_text(encoding="utf-8"))
    assert qm_lazy["world_id"] == "cell-quarterly-v2"

    # Tier 3: Fallback to base world when quarterly module is not installed
    monkeypatch.delitem(sys.modules, "robotization_bench.quarterly", raising=False)
    q_plan_manual, q_report_manual = _build_duck_quarter_fixture(
        base_world, seed=47, automated=False, attach_explicit_week_world=False
    )
    out_base = tmp_path / "quarter_base_fallback"
    export_quarter_pack(base_world, q_report_manual, q_plan_manual, out_base)
    assert validate_quarter_pack(out_base, expected_weeks=12)["ok"] is True

    # Negative guards: mismatched week counts, non-sequential week index, trace=False, symlinks
    with pytest.raises(ValueError, match="week count"):
        bad_plan = _DuckQuarterlyPlan(2, q_plan_dc.weeks[:-1])
        export_quarter_pack(base_world, q_report_dc, bad_plan, tmp_path / "bad_len")

    with pytest.raises(ValueError, match="sequential"):
        bad_weeks = list(q_report_dc.weeks)
        bad_weeks[3] = replace(bad_weeks[3], week=9)
        export_quarter_pack(base_world, replace(q_report_dc, weeks=tuple(bad_weeks)), q_plan_dc, tmp_path / "bad_seq")

    untraced_plan, untraced_report = _build_duck_quarter_fixture(
        base_world, seed=11, automated=False, attach_explicit_week_world=True, trace=False
    )
    with pytest.raises(ValueError, match="trace"):
        export_quarter_pack(base_world, untraced_report, untraced_plan, tmp_path / "bad_untraced")

    victim = tmp_path / "quarter_victim.txt"
    victim.write_text("KEEP_ME", encoding="utf-8")
    sym_pack = tmp_path / "sym_quarter"
    (sym_pack / "weeks").mkdir(parents=True)
    (sym_pack / "quarter_manifest.json").symlink_to(victim)
    with pytest.raises(ValueError, match="symlink"):
        export_quarter_pack(base_world, q_report_dc, q_plan_dc, sym_pack)
    assert victim.read_text(encoding="utf-8") == "KEEP_ME"


def test_export_3d_pack_cli_v1_custom_seed_and_dynamic_quarterly(tmp_path, monkeypatch):
    script_path = ROOT / "scripts" / "export_3d_pack.py"
    assert script_path.is_file(), f"Missing {script_path}"

    # 1. Subprocess CLI run on default seed 11 + custom non-negative seed 999
    pack_dir = tmp_path / "pack_s11"
    proc = subprocess.run(
        [sys.executable, str(script_path), "--out", str(pack_dir), "--seed", "11", "--seed", "999"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    index = json.loads((pack_dir / "index.json").read_text(encoding="utf-8"))
    assert index["pack_format"] == "robotization-bench.3d-pack-index.v1"
    assert index["replay_format"] == "robotization-bench.replay.v1"
    assert index["seeds"] == [11, 999]
    assert index["evaluation_seeds"] == [11, 29, 47]
    assert index["quarterly_available"] is False

    runs_by_id = {r["id"]: r for r in index["runs"]}
    for seed in (11, 999):
        for strat, expected_workers in (("manual", 6), ("candidate", 5), ("reference", 4)):
            rid = f"v1-{strat}-seed{seed}"
            assert rid in runs_by_id
            run_entry = runs_by_id[rid]
            assert run_entry["evaluation_seeds"] == [11, 29, 47]
            assert "evaluation" in run_entry
            if strat == "reference":
                assert run_entry["evaluation"]["win"] is True
            b_dir = pack_dir / run_entry["bundle_dir"]
            assert validate_shift_bundle(b_dir)["ok"] is True
            m = json.loads((b_dir / "manifest.json").read_text(encoding="utf-8"))
            assert len(m["plan"]["workers"]) == expected_workers

        # Identical scenario across all 3 v1 bundles on the same seed (368bf27:108, 450)
        s_man = json.loads((pack_dir / f"v1-manual-seed{seed}/manifest.json").read_text())["scenario"]
        s_cand = json.loads((pack_dir / f"v1-candidate-seed{seed}/manifest.json").read_text())["scenario"]
        s_ref = json.loads((pack_dir / f"v1-reference-seed{seed}/manifest.json").read_text())["scenario"]
        assert s_man == s_cand == s_ref

    # 2. Clean CLI error handling (no Traceback) on negative, duplicate, non-int seeds & symlink --out
    sym_out = tmp_path / "sym_out"
    sym_out.symlink_to(tmp_path / "real_target")
    for bad_args in (
        ["--out", str(tmp_path / "bad1"), "--seed", "-1"],
        ["--out", str(tmp_path / "bad2"), "--seed", "abc"],
        ["--out", str(tmp_path / "bad3"), "--seeds", "11", "11"],
        ["--out", str(tmp_path / "bad4"), "--seeds", "11,bad"],
        ["--out", str(sym_out), "--seed", "11"],
    ):
        failed = subprocess.run(
            [sys.executable, str(script_path), *bad_args],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert failed.returncode != 0
        assert "Traceback" not in failed.stderr

    # 3. runpy.run_path loadability + boolean seed rejection + dynamic quarterly (both pre-M3 & post-M3)
    mod_ns = runpy.run_path(str(script_path))
    export_pack_fn = mod_ns["export_pack"]
    main_fn = mod_ns["main"]

    with pytest.raises(ValueError):
        export_pack_fn(tmp_path / "bool_seed", seeds=[True])

    base_world = load_world()
    world_q = json.loads(json.dumps(base_world))
    world_q["quarterly"] = {"schema_version": 2, "world_id": "cell-quarterly-v2", "weeks": 12}

    import robotization_bench.contracts as contracts_mod
    import robotization_bench.episode as episode_mod
    import robotization_bench.grading as grading_mod
    import robotization_bench.reference as reference_mod
    import robotization_bench.validation as validation_mod

    monkeypatch.setattr(contracts_mod, "load_world", lambda: json.loads(json.dumps(world_q)))

    def fake_parse_quarterly_plan(val, w):
        if type(val) is not dict or val.get("schema_version") != 2 or len(val.get("weeks", ())) != 12:
            raise InvalidPlan("expected schema_version 2 with 12 weeks")
        return _DuckQuarterlyPlan(
            2,
            tuple(
                _DuckWeekPlan(
                    bool(wk["robot"]),
                    bool(wk["trays"]),
                    wk["route"],
                    bool(wk["maintenance"]),
                    tuple(tuple(z) for z in wk["workers"]),
                )
                for wk in val["weeks"]
            ),
        )

    def fake_manual_quarterly_value(_w=None):
        return {
            "schema_version": 2,
            "weeks": [
                {
                    "robot": False,
                    "trays": False,
                    "route": "manual",
                    "maintenance": False,
                    "workers": [[1], [2], [3], [3], [4], [2, 3]],
                }
                for _ in range(12)
            ],
        }

    def fake_simulate_quarter(w, q_plan, seed, *, trace=False):
        automated = any(wp.robot for wp in q_plan.weeks)
        _, q_rep = _build_duck_quarter_fixture(
            w, seed=seed, automated=automated, attach_explicit_week_world=False, trace=trace
        )
        return q_rep

    def fake_evaluate_quarterly(_w, val, _seeds):
        is_auto = any(wk.get("robot") for wk in val["weeks"])
        return Evaluation(
            valid=True,
            feasible=True,
            win=is_auto,
            reward_num=2 if is_auto else 1,
            reward_den=5,
            metrics={"orders": 200, "good": 200, "on_time": 198, "escaped": 0, "scrap": 0, "unfinished": 0,
                     "purchase": 1530000 if is_auto else 0, "total_cost": 80000 if is_auto else 100000,
                     "base_cost": 100000, "labor_ticks": 3000 if is_auto else 4000, "base_labor_ticks": 4000,
                     "auto_finished": 120 if is_auto else 0, "pack_finished": 200},
            reasons=() if is_auto else ("cost", "labor", "automation"),
        )

    fake_q = types.ModuleType("robotization_bench.quarterly")
    fake_q.manual_quarterly_value = fake_manual_quarterly_value
    fake_q.build_week_world = _make_week_world
    fake_q.simulate_quarter = fake_simulate_quarter
    monkeypatch.setitem(sys.modules, "robotization_bench.quarterly", fake_q)
    monkeypatch.setattr(validation_mod, "parse_quarterly_plan", fake_parse_quarterly_plan, raising=False)
    monkeypatch.setattr(grading_mod, "evaluate_quarterly", fake_evaluate_quarterly, raising=False)

    # 3a. Pre-M3 path (QuarterlyEpisode absent -> graceful phased template fallback)
    pack_pre_m3 = tmp_path / "pack_q_pre_m3"
    rc_pre = main_fn(["--out", str(pack_pre_m3), "--seed", "11"])
    assert rc_pre == 0
    idx_pre = json.loads((pack_pre_m3 / "index.json").read_text(encoding="utf-8"))
    assert idx_pre["quarterly_available"] is True
    assert validate_quarter_pack(pack_pre_m3 / "quarterly-manual-seed11", expected_weeks=12)["ok"] is True
    assert validate_quarter_pack(pack_pre_m3 / "quarterly-reference-seed11", expected_weeks=12)["ok"] is True

    # 3b. Post-M3 path (QuarterlyEpisode + polymorphic reference.solve returning schema_version == 2)
    class FakeQuarterlyEpisode:
        def __init__(self, w, seeds):
            self.w = w
            self.seeds = list(seeds)

        def observe(self):
            return {"schema_version": 2, "world": self.w, "development_seeds": self.seeds}

    orig_solve = reference_mod.solve

    def fake_poly_solve(ep):
        if isinstance(ep, FakeQuarterlyEpisode):
            return {
                "schema_version": 2,
                "weeks": [
                    {
                        "robot": True,
                        "trays": True,
                        "route": "bypass",
                        "maintenance": (w == 7),
                        "workers": [[1], [2], [3, 4], [2, 3]],
                    }
                    for w in range(12)
                ],
            }
        return orig_solve(ep)

    monkeypatch.setattr(episode_mod, "QuarterlyEpisode", FakeQuarterlyEpisode, raising=False)
    monkeypatch.setattr(reference_mod, "solve", fake_poly_solve)

    pack_post_m3 = tmp_path / "pack_q_post_m3"
    rc_post = main_fn(["--out", str(pack_post_m3), "--seeds", "11"])
    assert rc_post == 0
    idx_post = json.loads((pack_post_m3 / "index.json").read_text(encoding="utf-8"))
    q_ref_entry = next(r for r in idx_post["runs"] if r["id"] == "quarterly-reference-seed11")
    assert q_ref_entry["evaluation"]["win"] is True
    assert q_ref_entry["evaluation_seeds"] == [11, 29, 47]
    assert validate_quarter_pack(pack_post_m3 / "quarterly-reference-seed11", expected_weeks=12)["ok"] is True


def _assert_common_cors_headers(headers) -> None:
    lower = {k.lower(): v for k, v in headers.items()}
    assert lower.get("access-control-allow-origin") == "*"
    assert lower.get("access-control-allow-methods") == "GET, HEAD, OPTIONS"
    assert lower.get("access-control-allow-headers") == "Content-Type, Range"
    assert lower.get("cache-control") == "no-store"
    assert lower.get("x-content-type-options") == "nosniff"


def _http_request(host: str, port: int, method: str, target: str, *, headers=None, body=None):
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.request(method, target, body=body, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, dict(resp.getheaders()), data
    finally:
        conn.close()


def test_serve_3d_cors_headers_mime_head_options_range_405_and_once(tmp_path):
    serve_script = ROOT / "scripts" / "serve_3d.py"
    export_script = ROOT / "scripts" / "export_3d_pack.py"
    assert serve_script.is_file(), f"Missing {serve_script}"

    pack_dir = tmp_path / "served_pack"
    export_mod = runpy.run_path(str(export_script))
    export_mod["export_pack"](pack_dir, seeds=[11])
    (pack_dir / "NOTES.md").write_text("# Demo Notes\n", encoding="utf-8")

    serve_mod = runpy.run_path(str(serve_script))
    create_server = serve_mod["create_server"]

    server = create_server(pack_dir, host="127.0.0.1", port=0, quiet=True)
    host, port = server.server_address[:2]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # 1. OPTIONS preflight -> 204 No Content, empty body, full CORS headers
        st_opt, hdr_opt, body_opt = _http_request(host, port, "OPTIONS", "/v1-manual-seed11/events.jsonl")
        assert st_opt == 204
        assert body_opt == b""
        _assert_common_cors_headers(hdr_opt)

        # 2. GET JSON, JSONL, and Markdown with exact MIME types & query-string stripping
        st_idx, hdr_idx, body_idx = _http_request(host, port, "GET", "/index.json?cachebust=1")
        assert st_idx == 200
        _assert_common_cors_headers(hdr_idx)
        assert {k.lower(): v for k, v in hdr_idx.items()}["content-type"] == "application/json; charset=utf-8"
        assert body_idx == (pack_dir / "index.json").read_bytes()

        st_ev, hdr_ev, body_ev = _http_request(host, port, "GET", "/v1-reference-seed11/events.jsonl")
        assert st_ev == 200
        _assert_common_cors_headers(hdr_ev)
        assert {k.lower(): v for k, v in hdr_ev.items()}["content-type"] == "application/x-ndjson; charset=utf-8"
        assert body_ev == (pack_dir / "v1-reference-seed11/events.jsonl").read_bytes()

        st_md, hdr_md, body_md = _http_request(host, port, "GET", "/NOTES.md")
        assert st_md == 200
        _assert_common_cors_headers(hdr_md)
        assert {k.lower(): v for k, v in hdr_md.items()}["content-type"] == "text/markdown; charset=utf-8"
        assert body_md == b"# Demo Notes\n"

        # 3. HEAD -> 200, empty body, Content-Length matches GET bytes
        st_head, hdr_head, body_head = _http_request(host, port, "HEAD", "/index.json")
        assert st_head == 200
        assert body_head == b""
        _assert_common_cors_headers(hdr_head)
        assert int({k.lower(): v for k, v in hdr_head.items()}["content-length"]) == len(body_idx)

        # 4. Range requests -> 206 Partial Content & 416 Range Not Satisfiable
        st_rng, hdr_rng, body_rng = _http_request(
            host, port, "GET", "/index.json", headers={"Range": "bytes=0-31"}
        )
        assert st_rng == 206
        _assert_common_cors_headers(hdr_rng)
        assert body_rng == body_idx[:32]
        assert (
            {k.lower(): v for k, v in hdr_rng.items()}["content-range"]
            == f"bytes 0-31/{len(body_idx)}"
        )

        st_416, hdr_416, _ = _http_request(
            host, port, "GET", "/index.json", headers={"Range": "bytes=99999999-"}
        )
        assert st_416 == 416
        _assert_common_cors_headers(hdr_416)

        # 5. Disallowed methods -> 405 Method Not Allowed + Allow + CORS headers
        for bad_method in ("POST", "PUT", "DELETE", "PATCH"):
            st_405, hdr_405, _ = _http_request(
                host,
                port,
                bad_method,
                "/index.json",
                headers={"Content-Type": "application/json"},
                body=b'{"mutate":true}',
            )
            assert st_405 == 405
            _assert_common_cors_headers(hdr_405)
            assert {k.lower(): v for k, v in hdr_405.items()}.get("allow") == "GET, HEAD, OPTIONS"

        # 6. Missing clean path -> 404 with CORS headers
        st_404, hdr_404, _ = _http_request(host, port, "GET", "/does_not_exist.json")
        assert st_404 == 404
        _assert_common_cors_headers(hdr_404)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    # 7. Subprocess CLI --port 0 --once serves one request and exits 0 within 5s
    with subprocess.Popen(
        [sys.executable, str(serve_script), "--dir", str(pack_dir), "--host", "127.0.0.1", "--port", "0", "--once"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as proc:
        try:
            assert proc.stdout is not None
            startup_line = proc.stdout.readline().strip()
            m_url = re.search(r"http://127\.0\.0\.1:(\d+)/", startup_line)
            assert m_url is not None, f"Unexpected startup line: {startup_line!r}"
            once_port = int(m_url.group(1))
            with urllib.request.urlopen(f"http://127.0.0.1:{once_port}/index.json", timeout=5) as resp:
                assert resp.status == 200
                fetched = json.loads(resp.read().decode("utf-8"))
                assert fetched["pack_format"] == "robotization-bench.3d-pack-index.v1"
            rc = proc.wait(timeout=5)
            assert rc == 0
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)


def test_serve_3d_blocks_traversal_symlinks_and_directory_listing(tmp_path):
    serve_script = ROOT / "scripts" / "serve_3d.py"
    assert serve_script.is_file(), f"Missing {serve_script}"

    pack_dir = tmp_path / "sec_pack"
    (pack_dir / "v1-manual-seed11").mkdir(parents=True)
    (pack_dir / "index.json").write_text('{"ok": true}\n', encoding="utf-8")
    (pack_dir / "v1-manual-seed11" / "manifest.json").write_text('{"ok": true}\n', encoding="utf-8")

    secret_file = tmp_path / "outside_secret.json"
    secret_file.write_text('{"secret": "TOP_SECRET_LEAK"}\n', encoding="utf-8")
    secret_dir = tmp_path / "outside_dir"
    secret_dir.mkdir()
    (secret_dir / "nested.json").write_text('{"secret": "NESTED_SECRET_LEAK"}\n', encoding="utf-8")

    # Plant leaf symlink and intermediate directory symlink inside pack_dir
    (pack_dir / "leaf_symlink.json").symlink_to(secret_file)
    (pack_dir / "dir_symlink").symlink_to(secret_dir)

    serve_mod = runpy.run_path(str(serve_script))
    server = serve_mod["create_server"](pack_dir, host="127.0.0.1", port=0, quiet=True)
    host, port = server.server_address[:2]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        attack_targets = (
            "/../outside_secret.json",
            "/%2e%2e/outside_secret.json",
            "/%2e%2e/%2e%2e/GEMINI.md",
            "/v1-manual-seed11/../../outside_secret.json",
            "/v1-manual-seed11/..%2f..%2foutside_secret.json",
            r"/v1-manual-seed11\..\..\outside_secret.json",
            "/v1-manual-seed11%5c..%5coutside_secret.json",
            "/index.json%00.txt",
            "/./index.json",
            "/",
            "/v1-manual-seed11/",
            "/v1-manual-seed11",
            "//index.json",
            "/%2findex.json",
            "/leaf_symlink.json",
            "/dir_symlink/nested.json",
        )
        for target in attack_targets:
            status, hdrs, body = _http_request(host, port, "GET", target)
            assert status in (400, 403), f"Target {target!r} unexpectedly returned {status}"
            _assert_common_cors_headers(hdrs)
            assert b"TOP_SECRET_LEAK" not in body
            assert b"NESTED_SECRET_LEAK" not in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    # Also verify create_server and CLI refuse a symlinked root --dir
    sym_root = tmp_path / "sym_pack_root"
    sym_root.symlink_to(pack_dir)
    with pytest.raises(ValueError, match="symlink"):
        serve_mod["create_server"](sym_root, host="127.0.0.1", port=0, quiet=True)

    bad_cli = subprocess.run(
        [sys.executable, str(serve_script), "--dir", str(sym_root), "--port", "0", "--once"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert bad_cli.returncode != 0
    assert "Traceback" not in bad_cli.stderr


def test_musa_handoff_doc_recovers_368bf27_verbatim_and_documents_bridge():
    handoff_path = ROOT / "docs" / "ru" / "3D_HANDOFF_MUSA.md"
    assert handoff_path.is_file(), f"Missing {handoff_path}"

    git_proc = subprocess.run(
        ["git", "-C", str(ROOT), "show", "368bf27:docs/PROMPT_3D_INTEGRATION_RU.md"],
        capture_output=True,
        check=True,
        timeout=10,
    )
    raw_bytes = git_proc.stdout
    assert len(raw_bytes) == 64_169
    assert (
        hashlib.sha256(raw_bytes).hexdigest()
        == "3ea0716cfb4218f1e06d3ba8f1bed655dda420aa9735725132c9ae82013bbf49"
    )
    original_text = raw_bytes.decode("utf-8")
    assert len(original_text.splitlines()) == 466

    handoff_text = handoff_path.read_text(encoding="utf-8")
    assert original_text in handoff_text
    assert "\n---\n" in handoff_text

    guide_prefix = handoff_text.split(original_text, 1)[0]
    for required_snippet in (
        "scripts/export_3d_pack.py",
        "scripts/serve_3d.py",
        "http://127.0.0.1:8765/index.json",
        "v1-manual-seed11",
        "v1-candidate-seed11",
        "v1-reference-seed11",
        "quarterly-manual-seed11",
        "quarterly-reference-seed11",
        "quarter_manifest.json",
        "weeks/week-00",
        "week-11",
    ):
        assert required_snippet in guide_prefix, f"Missing {required_snippet!r} in Russian guide header"
