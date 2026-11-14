from dataclasses import asdict, dataclass, replace
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
import runpy
import socket
import struct
import subprocess
import sys
import threading
import time
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
    # Confirm reporting.py has zero top-level dependency on robotization_bench.quarterly in a clean process
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, robotization_bench.reporting; assert 'robotization_bench.quarterly' not in sys.modules",
        ],
        check=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"},
        timeout=15,
    )

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
    monkeypatch.setitem(sys.modules, "robotization_bench.quarterly", None)
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
    expected_q = (
        "quarterly" in load_world()
        and importlib.util.find_spec("robotization_bench.quarterly") is not None
    )
    assert index["quarterly_available"] is expected_q

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

        if expected_q:
            for q_strat in ("manual", "reference"):
                q_rid = f"quarterly-{q_strat}-seed{seed}"
                assert q_rid in runs_by_id
                assert validate_quarter_pack(pack_dir / q_rid, expected_weeks=12)["ok"] is True
            assert runs_by_id[f"quarterly-reference-seed{seed}"]["evaluation"]["win"] is True

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
        fixed_weeks = []
        tot_c = 0
        tot_l = 0
        for idx, (wp, wr) in enumerate(zip(q_plan.weeks, q_rep.weeks)):
            sp = wp.to_shift_plan()
            eff_w = _make_week_world(
                w, idx, commissioning=(wp.robot and idx < 2), wear=wr.wear_start, maintenance=wp.maintenance
            )
            raw_w = simulate(eff_w, sp, wr.scenario, trace=trace)
            se = calculate(eff_w, sp, raw_w)
            we_costs = dict(wr.week_economy.costs)
            we_costs.update(
                depreciation=se.costs["depreciation"] * 5,
                service=3500 if wp.robot else 0,
                maintenance=4500 if wp.maintenance else 0,
                shifts=se.costs["shifts"] * 5,
                overtime=se.costs["overtime"],
                trays=se.costs["trays"],
                materials=se.costs["materials"],
                rework=se.costs["rework"],
                late=se.costs["late"],
                escaped=se.costs["escaped"],
            )
            we = Economy(purchase=se.purchase, costs=we_costs, total=sum(we_costs.values()))
            tot_c += we.total
            tot_l += raw_w.labor_ticks
            fixed_weeks.append(
                replace(wr, shift_plan=sp, raw=raw_w, shift_economy=se, week_economy=we)
            )
        has_r = any(wp.robot for wp in q_plan.weeks)
        has_t = any(wp.trays for wp in q_plan.weeks)
        pur = (w["money"]["robot_purchase"] if has_r else 0) + (w["money"]["tray_purchase"] if has_t else 0)
        return _DuckQuarterReport(2, seed, pur, tot_c, tot_l, tuple(fixed_weeks))

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
    with monkeypatch.context() as mp:
        mp.delattr(episode_mod, "QuarterlyEpisode", raising=False)
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

    handoff_bytes = handoff_path.read_bytes()
    assert len(handoff_bytes) > 64_169
    suffix_bytes = handoff_bytes[-64_169:]
    assert len(suffix_bytes) == 64_169
    assert (
        hashlib.sha256(suffix_bytes).hexdigest()
        == "3ea0716cfb4218f1e06d3ba8f1bed655dda420aa9735725132c9ae82013bbf49"
    )
    original_text = suffix_bytes.decode("utf-8")
    assert len(original_text.splitlines()) == 466

    if (ROOT / ".git").exists():
        has_commit = subprocess.run(
            ["git", "-C", str(ROOT), "cat-file", "-e", "368bf27^{commit}"],
            capture_output=True,
            timeout=10,
        )
        if has_commit.returncode == 0:
            git_proc = subprocess.run(
                ["git", "-C", str(ROOT), "show", "368bf27:docs/PROMPT_3D_INTEGRATION_RU.md"],
                capture_output=True,
                check=True,
                timeout=10,
            )
            assert git_proc.stdout == suffix_bytes

    handoff_text = handoff_bytes.decode("utf-8")
    assert handoff_text.endswith(original_text)
    guide_prefix = handoff_bytes[:-64_169].decode("utf-8")
    assert "\n---\n" in guide_prefix
    for required_snippet in (
        "scripts/export_3d_pack.py",
        "scripts/serve_3d.py",
        "--extra-plan",
        "frontier-gemini-4-carbon",
        "post-rl-qwen2.5-7b",
        "http://127.0.0.1:8765/index.json",
        "v1-manual-seed11",
        "v1-candidate-seed11",
        "v1-reference-seed11",
        "quarterly-manual-seed11",
        "quarterly-reference-seed11",
        "quarter_manifest.json",
        "diagnostics",
        "diagnostics.md",
        "weeks/week-00",
        "week-11",
    ):
        assert required_snippet in guide_prefix, f"Missing {required_snippet!r} in Russian guide header"


def _count_unescaped_gfm_pipes(line: str) -> int:
    return len(re.findall(r"(?<!\\)(?:\\\\)*\|", line))


def test_compare_escapes_backslash_pipes_and_handles_string_reasons():
    world = load_world()
    day = generate(world, 11)
    base_eval = evaluate(world, manual_value(), (day,))

    report = compare(
        {
            r"backslash_pipe_plan\|inject": replace(
                base_eval,
                reasons=(r"reason_with_backslash\|pipe",),
            ),
            "str_reason_case": {
                "valid": False,
                "feasible": False,
                "win": False,
                "reward_num": 0,
                "reward_den": 1,
                "metrics": {},
                "reasons": "nop",
            },
            "empty_str_reason_case": {
                "valid": False,
                "feasible": False,
                "win": False,
                "reward_num": 0,
                "reward_den": 1,
                "metrics": {},
                "reasons": "",
            },
        }
    )

    sections = report.split("\n\n")
    table1_lines = sections[0].splitlines()
    table2_lines = sections[1].splitlines()
    for row in table1_lines:
        assert _count_unescaped_gfm_pipes(row) == 10, f"Broken GFM pipe count in Table 1 row: {row!r}"
    for row in table2_lines:
        assert _count_unescaped_gfm_pipes(row) == 8, f"Broken GFM pipe count in Table 2 row: {row!r}"

    assert r"backslash_pipe_plan\\\|inject" in report
    assert r"reason_with_backslash\\\|pipe" in report
    assert "- str_reason_case: no plan submitted (no-op)." in report
    assert "n, o, p" not in report
    assert "- empty_str_reason_case:" not in report


def test_validate_shift_bundle_rejects_walk_before_parent_start_or_assist(tmp_path):
    # m10a: walk swapped before parent assist on same tick (tick=17, line 13 vs line 14)
    w_jam = load_world()
    w_jam["clock"].update(shift_ticks=12, overtime_ticks=20, break_at=12, break_length=5)
    w_jam["prob_bps"]["jam"]["tray"]["regular"] = 10_000
    w_jam["prob_bps"]["defect_auto"]["tray"]["regular"] = 0
    p_jam = Plan(1, True, True, "all", ((1, 2, 3, 4),))
    s_jam = Scenario(1, 42, (Order(0, "regular", 0, 32),))
    r_jam = simulate(w_jam, p_jam, s_jam, trace=True)
    b_jam = export_shift_bundle(w_jam, p_jam, s_jam, r_jam, calculate(w_jam, p_jam, r_jam), tmp_path / "m10_assist")
    evs_jam = [json.loads(x) for x in (b_jam / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assist_idx = next(i for i, e in enumerate(evs_jam) if e["kind"] == "assist")
    assert evs_jam[assist_idx + 1]["kind"] == "walk"
    evs_jam[assist_idx], evs_jam[assist_idx + 1] = evs_jam[assist_idx + 1], evs_jam[assist_idx]
    (b_jam / "events.jsonl").write_text(
        "\n".join(json.dumps(e, separators=(",", ":")) for e in evs_jam) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=f"line {assist_idx + 1}"):
        validate_shift_bundle(b_jam)

    # m10b: walk swapped before parent human start on same tick (stage 2 transition 1->2)
    w_man = load_world()
    w_man["clock"].update(shift_ticks=40, overtime_ticks=10, break_at=440, break_length=40)
    w_man["prob_bps"]["defect_manual"]["regular"] = 0
    p_man = Plan(1, False, False, "manual", ((1, 2, 3, 4),))
    s_man = Scenario(1, 7, (Order(0, "regular", 0, 28),))
    r_man = simulate(w_man, p_man, s_man, trace=True)
    b_man = export_shift_bundle(w_man, p_man, s_man, r_man, calculate(w_man, p_man, r_man), tmp_path / "m10_start")
    evs_man = [json.loads(x) for x in (b_man / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    walk_idx = next(i for i, e in enumerate(evs_man) if e["kind"] == "walk")
    assert evs_man[walk_idx - 1]["kind"] == "start"
    evs_man[walk_idx - 1], evs_man[walk_idx] = evs_man[walk_idx], evs_man[walk_idx - 1]
    (b_man / "events.jsonl").write_text(
        "\n".join(json.dumps(e, separators=(",", ":")) for e in evs_man) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=f"line {walk_idx}"):
        validate_shift_bundle(b_man)


def test_validate_shift_bundle_enforces_deterministic_end_tick_finish_jam_and_horizon_clipping(tmp_path):
    # m30: fabricated finish + good at tick == H (27) when start.end_tick == 28 > H
    w30 = load_world()
    w30["clock"].update(shift_ticks=20, overtime_ticks=7, break_at=440, break_length=40)
    w30["prob_bps"]["defect_manual"]["regular"] = 0
    p30 = Plan(1, False, False, "manual", ((1, 2, 3, 4),))
    s30 = Scenario(1, 7, (Order(0, "regular", 0, 28),))
    r30 = simulate(w30, p30, s30, trace=True)
    b30 = export_shift_bundle(w30, p30, s30, r30, calculate(w30, p30, r30), tmp_path / "m30")
    fake_r30 = replace(r30, good=1, on_time=1, unfinished=0, events=())
    m30 = json.loads((b30 / "manifest.json").read_text(encoding="utf-8"))
    m30["raw"].update(good=1, on_time=1, unfinished=0)
    m30["economy"] = json.loads(json.dumps(asdict(calculate(w30, p30, fake_r30))))
    (b30 / "manifest.json").write_text(json.dumps(m30) + "\n", encoding="utf-8")
    evs30 = [json.loads(x) for x in (b30 / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    fab_line = len(evs30) + 1
    evs30.append({"tick": 27, "kind": "finish", "order_id": 0, "resource": "w0", "stage": 4, "attempt": 0, "end_tick": None})
    evs30.append({"tick": 27, "kind": "good", "order_id": 0, "resource": "w0", "stage": 4, "attempt": 0, "end_tick": None})
    (b30 / "events.jsonl").write_text(
        "\n".join(json.dumps(e, separators=(",", ":")) for e in evs30) + "\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match=f"line {fab_line}"):
        validate_shift_bundle(b30)

    # m31: premature human finish at tick=1 when start=[0,3)
    w31 = load_world()
    w31["clock"].update(shift_ticks=40, overtime_ticks=10, break_at=440, break_length=40)
    w31["prob_bps"]["defect_manual"]["regular"] = 0
    r31 = simulate(w31, p30, s30, trace=True)
    b31 = export_shift_bundle(w31, p30, s30, r31, calculate(w31, p30, r31), tmp_path / "m31")
    evs31 = [json.loads(x) for x in (b31 / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    evs31[3]["tick"] = 1  # finish(stage=1) moved from tick 3 to tick 1
    evs31[4]["tick"] = 1  # enqueue(stage=2) moved to tick 1
    (b31 / "events.jsonl").write_text(
        "\n".join(json.dumps(e, separators=(",", ":")) for e in evs31) + "\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="line 4"):
        validate_shift_bundle(b31)

    # m32: premature robot jam at tick=11 when robot start=[10,13)
    w32 = load_world()
    w32["clock"].update(shift_ticks=12, overtime_ticks=20, break_at=12, break_length=5)
    w32["prob_bps"]["jam"]["tray"]["regular"] = 10_000
    w32["prob_bps"]["defect_auto"]["tray"]["regular"] = 0
    p32 = Plan(1, True, True, "all", ((1, 2, 3, 4),))
    s32 = Scenario(1, 42, (Order(0, "regular", 0, 32),))
    r32 = simulate(w32, p32, s32, trace=True)
    b32 = export_shift_bundle(w32, p32, s32, r32, calculate(w32, p32, r32), tmp_path / "m32")
    evs32 = [json.loads(x) for x in (b32 / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    jam_idx = next(i for i, e in enumerate(evs32) if e["kind"] == "jam")
    # Place jam before break (which starts at tick=12) so monotonicity holds while jam.tick=11 != 13
    jam_ev = dict(evs32.pop(jam_idx), tick=11)
    brk_idx = next(i for i, e in enumerate(evs32) if e["kind"] == "break")
    evs32.insert(brk_idx, jam_ev)
    (b32 / "events.jsonl").write_text(
        "\n".join(json.dumps(e, separators=(",", ":")) for e in evs32) + "\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match=f"line {brk_idx + 1}"):
        validate_shift_bundle(b32)

    # m33: bogus robot start.end_tick = tick + 999 while world.time.auto.tray.regular == 3
    b33 = export_shift_bundle(w32, p32, s32, r32, calculate(w32, p32, r32), tmp_path / "m33")
    evs33 = [json.loads(x) for x in (b33 / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    r_start_idx = next(i for i, e in enumerate(evs33) if e["kind"] == "start" and e["resource"] == "robot")
    evs33[r_start_idx]["end_tick"] = evs33[r_start_idx]["tick"] + 999
    (b33 / "events.jsonl").write_text(
        "\n".join(json.dumps(e, separators=(",", ":")) for e in evs33) + "\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match=f"line {r_start_idx + 1}"):
        validate_shift_bundle(b33)

    # m34: dangling human start [0,3) without finish when horizon == 50
    b34 = export_shift_bundle(w31, p30, s30, r31, calculate(w31, p30, r31), tmp_path / "m34")
    evs34 = [json.loads(x) for x in (b34 / "events.jsonl").read_text(encoding="utf-8").splitlines()][:3]
    fake_r34 = replace(
        r31, good=0, on_time=0, unfinished=1, pack_started=0, pack_finished=0, labor_ticks=3, overtime_ticks=(0,), events=()
    )
    m34 = json.loads((b34 / "manifest.json").read_text(encoding="utf-8"))
    m34["raw"] = {**json.loads(json.dumps(asdict(fake_r34))), "events": []}
    m34["economy"] = json.loads(json.dumps(asdict(calculate(w31, p30, fake_r34))))
    (b34 / "manifest.json").write_text(json.dumps(m34) + "\n", encoding="utf-8")
    (b34 / "events.jsonl").write_text(
        "\n".join(json.dumps(e, separators=(",", ":")) for e in evs34) + "\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="line 3"):
        validate_shift_bundle(b34)

    # m35: dangling jammed robot after assist.end_tick == H == 27 (trailing robot finish+enqueue deleted)
    w35 = load_world()
    w35["clock"].update(shift_ticks=12, overtime_ticks=15, break_at=12, break_length=5)
    w35["prob_bps"]["jam"]["tray"]["regular"] = 10_000
    w35["prob_bps"]["defect_auto"]["tray"]["regular"] = 0
    r35 = simulate(w35, p32, s32, trace=True)
    b35 = export_shift_bundle(w35, p32, s32, r35, calculate(w35, p32, r35), tmp_path / "m35")
    evs35 = [json.loads(x) for x in (b35 / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert evs35[-2]["kind"] == "finish" and evs35[-2]["resource"] == "robot"
    evs35 = evs35[:-2]
    fake_r35 = replace(r35, pack_finished=0, auto_finished=0, events=())
    m35 = json.loads((b35 / "manifest.json").read_text(encoding="utf-8"))
    m35["raw"] = {**json.loads(json.dumps(asdict(fake_r35))), "events": []}
    m35["economy"] = json.loads(json.dumps(asdict(calculate(w35, p32, fake_r35))))
    (b35 / "manifest.json").write_text(json.dumps(m35) + "\n", encoding="utf-8")
    (b35 / "events.jsonl").write_text(
        "\n".join(json.dumps(e, separators=(",", ":")) for e in evs35) + "\n", encoding="utf-8"
    )
    with pytest.raises(ValueError):
        validate_shift_bundle(b35)


def test_validate_shift_bundle_enforces_transition_coupling_and_economy_formula_parity(tmp_path):
    w = load_world()
    w["clock"].update(shift_ticks=60, overtime_ticks=10, break_at=440, break_length=40)
    w["prob_bps"]["defect_auto"]["tray"]["regular"] = 0
    w["prob_bps"]["jam"]["tray"]["regular"] = 0
    p = Plan(1, True, True, "all", ((1,), (2,), (3,), (4,)))
    s = Scenario(1, 7, (Order(0, "regular", 0, 50),))
    r = simulate(w, p, s, trace=True)
    econ = calculate(w, p, r)

    # m36: Stage-4 terminal good attributed to wrong worker resource ("w0" instead of "w3")
    b36 = export_shift_bundle(w, p, s, r, econ, tmp_path / "m36")
    evs36 = [json.loads(x) for x in (b36 / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    good_idx = next(i for i, e in enumerate(evs36) if e["kind"] == "good")
    evs36[good_idx]["resource"] = "w0"
    (b36 / "events.jsonl").write_text(
        "\n".join(json.dumps(e, separators=(",", ":")) for e in evs36) + "\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match=f"line {good_idx + 1}"):
        validate_shift_bundle(b36)

    # m37: Delayed enqueue after finish (phantom multi-tick limbo between finish and enqueue)
    w37 = load_world()
    w37["clock"].update(shift_ticks=80, overtime_ticks=10, break_at=440, break_length=40)
    w37["prob_bps"]["defect_manual"]["regular"] = 0
    p37 = Plan(1, False, False, "manual", ((1,), (2, 3, 4)))
    s37 = Scenario(1, 7, (Order(0, "regular", 0, 70), Order(1, "regular", 20, 80)))
    r37 = simulate(w37, p37, s37, trace=True)
    b37 = export_shift_bundle(w37, p37, s37, r37, calculate(w37, p37, r37), tmp_path / "m37")
    evs37 = [json.loads(x) for x in (b37 / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    # Order 0 finishes stage 1 at tick 3; delay enqueue(stage=2) from tick 3 to tick 4 while start(stage=2) is shifted too?
    # Simpler: Order 1 arrives at tick=20; delay its stage-1 enqueue from tick=20 to tick=21 before w0 starts it!
    # Wait: w0 is idle at tick 20 so w0 starts order 1 at tick 20. Let's make w0 busy at tick 4 when order 1 arrives at tick 1!
    s37b = Scenario(1, 7, (Order(0, "regular", 0, 70), Order(1, "regular", 1, 70)))
    r37b = simulate(w37, p37, s37b, trace=True)
    b37b = export_shift_bundle(w37, p37, s37b, r37b, calculate(w37, p37, r37b), tmp_path / "m37b")
    evs37b = [json.loads(x) for x in (b37b / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    enq1_idx = next(
        i for i, e in enumerate(evs37b) if e["kind"] == "enqueue" and e["order_id"] == 1 and e["stage"] == 1
    )
    # Order 1 arrives at tick 1 while w0 is busy until tick 3, so tick=2 preserves monotonicity!
    evs37b[enq1_idx]["tick"] = 2
    (b37b / "events.jsonl").write_text(
        "\n".join(json.dumps(e, separators=(",", ":")) for e in evs37b) + "\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match=f"line {enq1_idx + 1}"):
        validate_shift_bundle(b37b)

    # m38: Zeroed Economy costs and purchase on robot=True, trays=True bundle
    b38 = export_shift_bundle(w, p, s, r, econ, tmp_path / "m38")
    m38 = json.loads((b38 / "manifest.json").read_text(encoding="utf-8"))
    m38["economy"] = {
        "purchase": 0,
        "costs": {k: 0 for k in m38["economy"]["costs"]},
        "total": 0,
    }
    (b38 / "manifest.json").write_text(json.dumps(m38) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="economy"):
        validate_shift_bundle(b38)


@dataclass(frozen=True)
class _StrictProjectWeekPlan:
    robot: bool
    trays: bool
    route: str
    maintenance: bool
    workers: tuple[tuple[int, ...], ...]

    def to_shift_plan(self) -> Plan:
        return Plan(1, self.robot, self.trays, self.route, self.workers)


@dataclass(frozen=True)
class _StrictProjectQuarterlyPlan:
    schema_version: int
    weeks: tuple[_StrictProjectWeekPlan, ...]


@dataclass(frozen=True)
class _StrictProjectWeekReport:
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


@dataclass(frozen=True)
class _StrictProjectQuarterReport:
    schema_version: int
    seed: int
    purchase: int
    total_cost: int
    labor_ticks: int
    weeks: tuple[_StrictProjectWeekReport, ...]


def test_export_quarter_pack_strict_project_md_week_report_without_quarterly_module(tmp_path, monkeypatch):
    # Verify strict 13-field WeekReport contract (NO .world or .week_world attribute)
    assert len(_StrictProjectWeekReport.__dataclass_fields__) == 13
    assert "world" not in _StrictProjectWeekReport.__dataclass_fields__
    assert "week_world" not in _StrictProjectWeekReport.__dataclass_fields__

    monkeypatch.setitem(sys.modules, "robotization_bench.quarterly", None)

    world = load_world()
    world["quarterly"] = {
        "schema_version": 2,
        "world_id": "cell-quarterly-v2",
        "weeks": 12,
        "max_pilots": 24,
        "carryover_cap": 80,
        "commissioning": {
            "weeks": 2,
            "jam_bonus_bps": {"bare": 1400, "tray": 650},
            "defect_bonus_bps": {"bare": 200, "tray": 80},
        },
        "wear": {
            "per_week_bypass": 1,
            "per_week_all": 3,
            "fragile_oversize_all_bonus": 1,
            "maintenance_reduction": 5,
            "maintenance_auto_slowdown_ticks": 1,
            "jam_bps_per_wear": 350,
            "defect_bps_per_wear": 120,
            "max_wear": 12,
        },
        "money": {
            "budget": 1800000,
            "depreciation_weeks": 52,
            "robot_service_week": 3500,
            "maintenance_cost": 4500,
            "shifts_per_week": 5,
            "hire_cost": 9000,
            "layoff_cost": 11000,
            "retrain_cost": 3500,
            "cross_skill_shift_premium": 900,
            "backlog_holding_per_order": 600,
        },
        "threshold_bps": {
            "good_each_week": 9000,
            "good_pooled": 9500,
            "on_time_pooled": 8800,
            "escaped_each_week_max": 120,
            "auto_pack_pooled_min": 3000,
        },
        "week_profiles": [
            {
                "week": w,
                "label": f"profile_{w:02d}",
                "waves": 10 + (w % 3),
                "orders_min": 11,
                "regular_bps": 7600,
                "fragile_bps": 1600,
                "due_offset": 160,
            }
            for w in range(12)
        ],
    }

    q = world["quarterly"]
    wear = 0
    plan_weeks = []
    report_weeks = []
    total_cost = 0
    total_labor = 0

    for w in range(12):
        maint = w in (6, 9)
        wp = _StrictProjectWeekPlan(
            robot=True,
            trays=True,
            route="bypass",
            maintenance=maint,
            workers=((1,), (2,), (3, 4), (2, 3)),
        )
        sp = wp.to_shift_plan()
        commissioning = w < 2
        wear_start = wear
        reduced_wear = wear_start - q["wear"]["maintenance_reduction"] if maint else wear_start
        eff_wear = min(q["wear"]["max_wear"], max(0, reduced_wear))

        eff_w = json.loads(json.dumps(world))
        eff_w.pop("quarterly", None)
        for k, v in q["week_profiles"][w].items():
            if k in eff_w["generator"]:
                eff_w["generator"][k] = v
        for rig in ("bare", "tray"):
            jam_add = (q["commissioning"]["jam_bonus_bps"][rig] if commissioning else 0) + eff_wear * q["wear"]["jam_bps_per_wear"]
            def_add = (q["commissioning"]["defect_bonus_bps"][rig] if commissioning else 0) + eff_wear * q["wear"]["defect_bps_per_wear"]
            for kind in eff_w["kinds"]:
                eff_w["prob_bps"]["jam"][rig][kind] = min(10_000, max(0, eff_w["prob_bps"]["jam"][rig][kind] + jam_add))
                eff_w["prob_bps"]["defect_auto"][rig][kind] = min(10_000, max(0, eff_w["prob_bps"]["defect_auto"][rig][kind] + def_add))
        if maint:
            for rig in ("bare", "tray"):
                for kind in eff_w["kinds"]:
                    eff_w["time"]["auto"][rig][kind] += q["wear"]["maintenance_auto_slowdown_ticks"]

        scen = Scenario(
            1,
            1100 + w,
            tuple(Order(idx, "regular", 5 * idx, 180 + 5 * idx) for idx in range(6)),
        )
        raw = simulate(eff_w, sp, scen, trace=True)
        shift_econ = calculate(eff_w, sp, raw)
        week_costs = {
            "depreciation": 29_423,
            "service": 3_500,
            "maintenance": 4_500 if maint else 0,
            "shifts": shift_econ.costs["shifts"] * 5,
            "cross_skill": 9_000,
            "overtime": shift_econ.costs["overtime"] * 5,
            "hiring_retraining": 0,
            "trays": shift_econ.costs["trays"] * 5,
            "materials": shift_econ.costs["materials"] * 5,
            "rework": shift_econ.costs["rework"] * 5,
            "late": shift_econ.costs["late"] * 5,
            "backlog_holding": 0,
            "unfulfilled": 0,
            "escaped": shift_econ.costs["escaped"] * 5,
        }
        week_econ = Economy(purchase=1_530_000, costs=week_costs, total=sum(week_costs.values()))
        wear_end = min(q["wear"]["max_wear"], eff_wear + q["wear"]["per_week_bypass"])
        wear = wear_end

        total_cost += week_econ.total
        total_labor += raw.labor_ticks
        plan_weeks.append(wp)
        report_weeks.append(
            _StrictProjectWeekReport(
                week=w,
                label=q["week_profiles"][w]["label"],
                week_seed=scen.seed,
                carryover_in=0,
                carryover_out=0,
                wear_start=wear_start,
                wear_end=wear_end,
                commissioning_active=commissioning,
                shift_plan=sp,
                scenario=scen,
                raw=raw,
                shift_economy=shift_econ,
                week_economy=week_econ,
            )
        )

    strict_plan = _StrictProjectQuarterlyPlan(2, tuple(plan_weeks))
    strict_quarter = _StrictProjectQuarterReport(
        2, 11, 1_530_000, total_cost, total_labor, tuple(report_weeks)
    )

    out_dir = tmp_path / "strict_quarter_pack"
    export_quarter_pack(world, strict_quarter, strict_plan, out_dir)
    audit = validate_quarter_pack(out_dir, expected_weeks=12)
    assert audit["ok"] is True

    for w in range(12):
        wm = json.loads((out_dir / f"weeks/week-{w:02d}/manifest.json").read_text(encoding="utf-8"))
        assert "quarterly" not in wm["world"]
        expected_reg_auto = world["time"]["auto"]["tray"]["regular"] + (1 if w in (6, 9) else 0)
        assert wm["world"]["time"]["auto"]["tray"]["regular"] == expected_reg_auto


def test_validate_quarter_pack_reconciles_totals_plan_monotonicity_and_orphan_entries(tmp_path):
    base_world = load_world()
    q_plan, q_report = _build_duck_quarter_fixture(
        base_world, seed=11, automated=True, attach_explicit_week_world=True
    )
    clean_dir = tmp_path / "clean_qpack"
    export_quarter_pack(base_world, q_report, q_plan, clean_dir)
    assert validate_quarter_pack(clean_dir, expected_weeks=12)["ok"] is True

    def clone_pack(tag: str) -> Path:
        dst = tmp_path / f"mut_{tag}"
        (dst / "weeks").mkdir(parents=True)
        (dst / "quarter_manifest.json").write_bytes((clean_dir / "quarter_manifest.json").read_bytes())
        if (clean_dir / "diagnostics.md").is_file():
            (dst / "diagnostics.md").write_bytes((clean_dir / "diagnostics.md").read_bytes())
        for w in range(12):
            src_w = clean_dir / "weeks" / f"week-{w:02d}"
            dst_w = dst / "weeks" / f"week-{w:02d}"
            dst_w.mkdir()
            (dst_w / "manifest.json").write_bytes((src_w / "manifest.json").read_bytes())
            (dst_w / "events.jsonl").write_bytes((src_w / "events.jsonl").read_bytes())
        return dst

    # qm01: labor_ticks + 1
    d1 = clone_pack("qm01_labor")
    qm1 = json.loads((d1 / "quarter_manifest.json").read_text(encoding="utf-8"))
    qm1["labor_ticks"] += 1
    (d1 / "quarter_manifest.json").write_text(json.dumps(qm1) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="labor_ticks"):
        validate_quarter_pack(d1, expected_weeks=12)

    # qm02: total_cost + 1
    d2 = clone_pack("qm02_cost")
    qm2 = json.loads((d2 / "quarter_manifest.json").read_text(encoding="utf-8"))
    qm2["total_cost"] += 1
    (d2 / "quarter_manifest.json").write_text(json.dumps(qm2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="total_cost"):
        validate_quarter_pack(d2, expected_weeks=12)

    # qm_purchase: purchase + 1
    d_pur = clone_pack("qm_purchase")
    qm_pur = json.loads((d_pur / "quarter_manifest.json").read_text(encoding="utf-8"))
    qm_pur["purchase"] += 1
    (d_pur / "quarter_manifest.json").write_text(json.dumps(qm_pur) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="purchase"):
        validate_quarter_pack(d_pur, expected_weeks=12)

    # qm03: plan.weeks[5] contradicts shift_plan / breaks irreversible CapEx
    d3 = clone_pack("qm03_plan_mismatch")
    qm3 = json.loads((d3 / "quarter_manifest.json").read_text(encoding="utf-8"))
    qm3["plan"]["weeks"][5] = {
        "robot": False,
        "trays": False,
        "route": "manual",
        "maintenance": False,
        "workers": qm3["plan"]["weeks"][5]["workers"],
    }
    (d3 / "quarter_manifest.json").write_text(json.dumps(qm3) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        validate_quarter_pack(d3, expected_weeks=12)

    # qm05a & qm05b: orphan weeks/week-12/ directory and stray file inside weeks/
    d5a = clone_pack("qm05_orphan_dir")
    (d5a / "weeks" / "week-12").mkdir()
    with pytest.raises(ValueError):
        validate_quarter_pack(d5a, expected_weeks=12)

    d5b = clone_pack("qm05_stray_file")
    (d5b / "weeks" / "stray.txt").write_text("orphan\n", encoding="utf-8")
    with pytest.raises(ValueError):
        validate_quarter_pack(d5b, expected_weeks=12)


def test_export_3d_pack_cli_rejects_non_ascii_seeds_and_preserves_flag_order(tmp_path):
    script_path = ROOT / "scripts" / "export_3d_pack.py"

    # Non-ASCII Unicode digits (Devanagari ११ and Latin-1 superscript ²) MUST fail with exit code 2 and no traceback
    for bad_seed in ("११", "²", "-१"):
        res = subprocess.run(
            [sys.executable, str(script_path), "--out", str(tmp_path / f"bad_{ord(bad_seed[-1])}"), "--seed", bad_seed],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert res.returncode == 2, f"Expected exit code 2 for --seed {bad_seed!r}, got {res.returncode}"
        assert "Traceback" not in res.stderr

    # Mixed --seeds / --seed / --all-dev-seeds MUST preserve exact CLI appearance order
    mod_ns = runpy.run_path(str(script_path))
    main_fn = mod_ns["main"]

    ordered_out = tmp_path / "ordered_pack"
    rc = main_fn(["--out", str(ordered_out), "--seeds", "29,47", "--seed", "0", "--seed", "11"])
    assert rc == 0
    idx = json.loads((ordered_out / "index.json").read_text(encoding="utf-8"))
    assert idx["seeds"] == [29, 47, 0, 11]

    ordered_dev_out = tmp_path / "ordered_dev_pack"
    rc_dev = main_fn(["--out", str(ordered_dev_out), "--seed", "99", "--all-dev-seeds", "--seed", "5"])
    assert rc_dev == 0
    idx_dev = json.loads((ordered_dev_out / "index.json").read_text(encoding="utf-8"))
    assert idx_dev["seeds"] == [99, 11, 29, 47, 5]


def _raw_tcp_exchange(host: str, port: int, payload: bytes, *, timeout: float = 5.0) -> bytes:
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(payload)
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(65_536)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)


def _parse_raw_http_response(raw_bytes: bytes) -> tuple[str, dict[str, str], bytes]:
    assert b"\r\n\r\n" in raw_bytes, f"Missing HTTP header terminator in {raw_bytes[:200]!r}"
    head, body = raw_bytes.split(b"\r\n\r\n", 1)
    lines = head.decode("iso-8859-1").split("\r\n")
    status_line = lines[0]
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip()] = v.strip()
    return status_line, headers, body


def test_serve_3d_hardens_latin1_range_malformed_ipv6_options_origin_large_post_and_http09(tmp_path, capsys):
    serve_script = ROOT / "scripts" / "serve_3d.py"
    pack_dir = tmp_path / "hardened_pack"
    pack_dir.mkdir()
    index_bytes = b'{"secret_payload": "DO_NOT_LEAK_HEADERLESS"}\n'
    (pack_dir / "index.json").write_bytes(index_bytes)

    serve_mod = runpy.run_path(str(serve_script))
    server = serve_mod["create_server"](pack_dir, host="127.0.0.1", port=0, quiet=True)
    host, port = server.server_address[:2]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # 1. Latin-1 superscripts in Range header -> 416 + Content-Range + CORS + no-store + 0 tracebacks
        for raw_range in (b"bytes=\xb2-", b"bytes=0-\xb3", b"bytes=-\xb9"):
            req = (
                b"GET /index.json HTTP/1.1\r\nHost: 127.0.0.1\r\nRange: "
                + raw_range
                + b"\r\nConnection: close\r\n\r\n"
            )
            resp = _raw_tcp_exchange(host, port, req)
            status_line, hdrs, _ = _parse_raw_http_response(resp)
            assert status_line.startswith("HTTP/1.1 416"), status_line
            _assert_common_cors_headers(hdrs)
            assert {k.lower(): v for k, v in hdrs.items()}.get("content-range") == f"bytes */{len(index_bytes)}"

        # 2. Malformed IPv6 urlsplit & invalid origin-form OPTIONS (missing leading '/') -> 400 + CORS + no-store
        for bad_req in (
            b"GET http://[::1/index.json HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n",
            b"OPTIONS http://[::1/index.json HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n",
            b"OPTIONS index.json HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n",
        ):
            resp = _raw_tcp_exchange(host, port, bad_req)
            status_line, hdrs, _ = _parse_raw_http_response(resp)
            assert status_line.startswith("HTTP/1.1 400"), f"Got {status_line!r} for {bad_req!r}"
            _assert_common_cors_headers(hdrs)

        # Valid OPTIONS * still returns 204
        opt_star = _raw_tcp_exchange(
            host, port, b"OPTIONS * HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
        )
        st_star, hdr_star, _ = _parse_raw_http_response(opt_star)
        assert st_star.startswith("HTTP/1.1 204")
        _assert_common_cors_headers(hdr_star)

        # 3. Large POST body (100 KB and 1 MiB raw TCP + 20x 512 KB http.client) -> clean 405 + EOF (no RST)
        for body_size, conn_hdr in ((102_400, b"Connection: close\r\n"), (102_400, b""), (1_048_576, b"Connection: close\r\n")):
            post_body = b"x" * body_size
            post_req = (
                b"POST /index.json HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                + f"Content-Length: {body_size}\r\n".encode("ascii")
                + conn_hdr
                + b"\r\n"
                + post_body
            )
            post_resp = _raw_tcp_exchange(host, port, post_req)
            st_post, hdr_post, _ = _parse_raw_http_response(post_resp)
            assert st_post.startswith("HTTP/1.1 405"), st_post
            _assert_common_cors_headers(hdr_post)
            assert {k.lower(): v for k, v in hdr_post.items()}.get("allow") == "GET, HEAD, OPTIONS"

        payload_512k = b"z" * 524_288
        for _ in range(20):
            st_hc, hdr_hc, _ = _http_request(
                host,
                port,
                "POST",
                "/index.json",
                headers={"Content-Type": "application/octet-stream"},
                body=payload_512k,
            )
            assert st_hc == 405
            _assert_common_cors_headers(hdr_hc)

        # Raw TCP GET without Connection: close also receives HTTP/1.1 + CORS + clean EOF
        get_no_close = _raw_tcp_exchange(
            host, port, b"GET /index.json HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
        )
        st_nc, hdr_nc, body_nc = _parse_raw_http_response(get_no_close)
        assert st_nc.startswith("HTTP/1.1 200")
        _assert_common_cors_headers(hdr_nc)
        assert body_nc == index_bytes

        # 4. HTTP/0.9 2-token GET and 1-token garbage -> HTTP/1.1 400 + CORS + no-store + zero payload leak
        for raw_09 in (b"GET /index.json\r\n\r\n", b"GARBAGE_NOT_HTTP\r\n\r\n"):
            resp_09 = _raw_tcp_exchange(host, port, raw_09)
            st_09, hdr_09, body_09 = _parse_raw_http_response(resp_09)
            assert st_09.startswith("HTTP/1.1 400"), st_09
            _assert_common_cors_headers(hdr_09)
            assert b"DO_NOT_LEAK_HEADERLESS" not in body_09
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "ValueError" not in captured.err


def test_serve_3d_bounded_digits_single_crlf_http09_blank_line_disconnect_and_monotonic_drain(tmp_path):
    serve_script = ROOT / "scripts" / "serve_3d.py"
    pack_dir = tmp_path / "iter3_pack"
    pack_dir.mkdir()
    index_bytes = b'{"ok":true,"secret":"NO_LEAK_09"}\n'
    (pack_dir / "index.json").write_bytes(index_bytes)

    serve_mod = runpy.run_path(str(serve_script))
    handler_cls = serve_mod["PackRequestHandler"]
    assert getattr(handler_cls, "timeout", None) == 5.0

    with subprocess.Popen(
        [
            sys.executable,
            str(serve_script),
            "--dir",
            str(pack_dir),
            "--host",
            "127.0.0.1",
            "--port",
            "0",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as proc:
        try:
            assert proc.stdout is not None
            banner = proc.stdout.readline().decode("utf-8").strip()
            host, port_s = banner.split("http://", 1)[1].rstrip("/").split(":")
            port = int(port_s)

            # 1. >4300-digit ASCII integers in Range & Content-Length -> zero ValueError, valid HTTP + CORS
            huge_nines = b"9" * 5000
            huge_zeros = b"0" * 5000
            for raw_range, expected_status in (
                (b"bytes=" + huge_nines + b"-", "HTTP/1.1 416"),
                (b"bytes=0-" + huge_nines, "HTTP/1.1 206"),
                (b"bytes=-" + huge_nines, "HTTP/1.1 206"),
                (b"bytes=-" + huge_zeros, "HTTP/1.1 416"),
                (b"bytes=" + huge_zeros + b"-", "HTTP/1.1 206"),
            ):
                resp = _raw_tcp_exchange(
                    host,
                    port,
                    b"GET /index.json HTTP/1.1\r\nHost: 127.0.0.1\r\nRange: " + raw_range + b"\r\n\r\n",
                )
                st_line, hdrs, _ = _parse_raw_http_response(resp)
                assert st_line.startswith(expected_status), f"{raw_range[:24]!r} -> {st_line!r}"
                _assert_common_cors_headers(hdrs)

            resp_cl = _raw_tcp_exchange(
                host,
                port,
                b"POST /index.json HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: " + huge_nines + b"\r\n\r\n",
            )
            st_cl, hdr_cl, _ = _parse_raw_http_response(resp_cl)
            assert st_cl.startswith("HTTP/1.1 405")
            _assert_common_cors_headers(hdr_cl)

            # 2. Single-CRLF HTTP/0.9 (without 2nd CRLF or half-close!) & blank request lines -> < 0.25s 400 + CORS
            for fast_bad in (
                b"GET /index.json\r\n",
                b"GARBAGE\r\n",
                b"\r\n\r\n",
                b"   \r\n\r\n",
            ):
                t0 = time.monotonic()
                resp_bad = _raw_tcp_exchange(host, port, fast_bad, timeout=1.0)
                dt = time.monotonic() - t0
                assert dt < 0.25, f"{fast_bad!r} took {dt:.3f}s"
                st_bad, hdr_bad, body_bad = _parse_raw_http_response(resp_bad)
                assert st_bad.startswith("HTTP/1.1 400"), f"{fast_bad!r} -> {st_bad!r}"
                _assert_common_cors_headers(hdr_bad)
                assert {k.lower(): v for k, v in hdr_bad.items()}.get("connection") == "close"
                assert b"NO_LEAK_09" not in body_bad

            # 3. 200 KB oversized URI -> clean 414 + CORS + no-store + clean EOF (zero ConnectionResetError)
            uri_200k = b"GET /" + (b"a" * 200_000) + b" HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
            resp_414 = _raw_tcp_exchange(host, port, uri_200k, timeout=3.0)
            st_414, hdr_414, _ = _parse_raw_http_response(resp_414)
            assert st_414.startswith("HTTP/1.1 414"), st_414
            _assert_common_cors_headers(hdr_414)

            # 4. Abrupt client FIN and SO_LINGER(1, 0) RST mid-POST -> zero tracebacks on stderr
            with socket.create_connection((host, port), timeout=2.0) as s_fin:
                s_fin.sendall(
                    b"POST /index.json HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 100000\r\n\r\n"
                    + b"x" * 1024
                )
            with socket.create_connection((host, port), timeout=2.0) as s_rst:
                s_rst.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                s_rst.sendall(
                    b"POST /index.json HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 100000\r\n\r\n"
                    + b"y" * 1024
                )

            # 5. Monotonic wall-clock cap on trickle POST (1 byte every 0.2s) & instant skip on >2MiB lie
            t_lie = time.monotonic()
            resp_lie = _raw_tcp_exchange(
                host,
                port,
                b"POST /index.json HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 10737418240\r\n\r\n",
                timeout=2.0,
            )
            dt_lie = time.monotonic() - t_lie
            assert dt_lie < 0.25, f"10 GiB Content-Length lie took {dt_lie:.3f}s"
            st_lie, hdr_lie, _ = _parse_raw_http_response(resp_lie)
            assert st_lie.startswith("HTTP/1.1 405")
            _assert_common_cors_headers(hdr_lie)

            t_trickle = time.monotonic()
            with socket.create_connection((host, port), timeout=2.0) as s_tr:
                s_tr.sendall(
                    b"POST /index.json HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 100000\r\n\r\n"
                )
                for _ in range(4):
                    time.sleep(0.2)
                    try:
                        s_tr.sendall(b"z")
                    except OSError:
                        break
                chunks = []
                while True:
                    try:
                        ch = s_tr.recv(4096)
                    except OSError:
                        break
                    if not ch:
                        break
                    chunks.append(ch)
            dt_trickle = time.monotonic() - t_trickle
            assert dt_trickle < 0.95, f"Trickle POST exceeded monotonic 0.5s deadline ({dt_trickle:.3f}s)"
            st_tr, hdr_tr, _ = _parse_raw_http_response(b"".join(chunks))
            assert st_tr.startswith("HTTP/1.1 405")
            _assert_common_cors_headers(hdr_tr)

            time.sleep(0.15)
            proc.terminate()
            proc.wait(timeout=5)
            assert proc.stderr is not None
            stderr_text = proc.stderr.read().decode("utf-8", errors="replace")
            assert "Traceback (most recent call last):" not in stderr_text, stderr_text
            assert "ValueError" not in stderr_text, stderr_text
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)


def test_compare_coerces_dict_string_metrics_blocking_pipe_injection():
    valid_numeric_strings = {
        "valid": True,
        "feasible": True,
        "win": True,
        "reward_num": 2,
        "reward_den": 5,
        "metrics": {
            "purchase": "1530000",
            "total_cost": "80000",
            "base_cost": "100000",
            "labor_ticks": "3000",
            "base_labor_ticks": "4000",
            "auto_finished": "120",
            "pack_finished": "200",
            "orders": "200",
            "good": "200",
            "on_time": "198",
            "escaped": "0",
            "scrap": "0",
            "unfinished": "0",
        },
        "reasons": (),
    }
    rendered = compare({"str_digits_ok": valid_numeric_strings})
    t1, t2 = rendered.split("\n\n")[:2]
    for line in t1.splitlines():
        assert _count_unescaped_gfm_pipes(line) == 10
    for line in t2.splitlines():
        assert _count_unescaped_gfm_pipes(line) == 8

    for bad_field in ("labor_ticks", "auto_finished", "orders", "unfinished"):
        injected = json.loads(json.dumps(valid_numeric_strings))
        injected["metrics"][bad_field] = "250 | INJECTED_COL"
        with pytest.raises(ValueError):
            compare({"injected": injected})


def test_quarter_diagnostics_all_five_categories_markdown_and_validator(tmp_path):
    import robotization_bench.reporting as reporting_mod

    assert hasattr(reporting_mod, "build_quarter_diagnostics")
    assert hasattr(reporting_mod, "render_quarter_diagnostics_md")
    build_diag = reporting_mod.build_quarter_diagnostics
    render_diag_md = reporting_mod.render_quarter_diagnostics_md

    expected_categories = {
        "commissioning_jam_unassisted",
        "route_all_unmaintained_wear",
        "hiring_retraining_friction",
        "sla_overtime_breach",
        "backlog_carryover_surge",
    }

    world = load_world()
    world["quarterly"] = {
        "schema_version": 2,
        "world_id": "cell-quarterly-v2",
        "weeks": 12,
        "carryover_cap": 80,
        "threshold_bps": {
            "good_each_week": 9000,
            "good_pooled": 9500,
            "on_time_pooled": 8800,
            "escaped_each_week_max": 120,
            "auto_pack_pooled_min": 3000,
        },
    }

    # Build a 12-week rollout exhibiting all 5 genuine operational failure categories:
    # - Week 0: robot=True, route="all", commissioning_active=True, NO Zone-3 worker -> jam deadlock + unfulfilled
    # - Week 1: crew changed + hiring_retraining > 0, carryover_in > 0
    # - Weeks 2..4: route="all", maintenance=False, rising wear (6 -> 9 on week 4)
    # - Week 5: carryover_out == 80 (carryover_cap) + overtime_ticks + escaped defect
    plan_weeks = []
    report_weeks = []
    total_cost = 0
    total_labor = 0

    for w in range(12):
        if w == 0:
            workers = ((1,), (2,), (4,))  # 0 Zone-3 workers!
            route = "all"
            maint = False
        elif w == 1:
            workers = ((1, 2), (2, 3), (3, 4), (4,))  # crew churn vs week 0
            route = "bypass"
            maint = False
        elif w in (2, 3, 4):
            workers = ((1, 2), (2, 3), (3, 4), (4,))
            route = "all"
            maint = False
        else:
            workers = ((1, 2), (2, 3), (3, 4), (4,))
            route = "bypass"
            maint = w == 7

        wp = _DuckWeekPlan(robot=True, trays=False, route=route, maintenance=maint, workers=workers)
        sp = wp.to_shift_plan()
        commissioning = w < 2
        wear_start = 6 if w == 4 else (3 if w == 3 else (0 if w < 3 else 4))
        wear_end = 9 if w == 4 else (6 if w == 3 else (3 if w == 2 else 2))

        eff_w = _make_week_world(world, w, commissioning=commissioning, wear=wear_start, maintenance=maint)
        if w == 0:
            eff_w["prob_bps"]["jam"]["bare"]["regular"] = 10_000  # guaranteed commissioning jam without Zone 3
        elif w == 5:
            eff_w["prob_bps"]["defect_auto"]["bare"]["regular"] = 10_000
            eff_w["prob_bps"]["detect"] = 0  # guaranteed escaped defect

        carry_in = 3 if w == 1 else (10 if w == 5 else 0)
        orders = [Order(cid, "regular", 0, 0) for cid in range(carry_in)]
        if w == 5:
            # Overload shift to force overtime and carryover_out == 80 (carryover_cap)
            orders.extend(Order(100 + idx, "oversize", 900 + (idx % 50), 955) for idx in range(95))
        else:
            orders.extend(Order(100 + idx, "regular", 5 * idx, 220 + 5 * idx) for idx in range(6))

        scen = Scenario(1, 5000 + w, tuple(sorted(orders, key=lambda o: (o.arrival, o.id))))
        raw = simulate(eff_w, sp, scen, trace=True)
        shift_econ = calculate(eff_w, sp, raw)
        carry_out = min(80, raw.unfinished) if w < 11 else 0
        hiring_cost = 29_000 if w == 1 else 0
        v2_costs = {
            "depreciation": shift_econ.costs["depreciation"] * 5,
            "service": 3_500,
            "maintenance": 4_500 if maint else 0,
            "shifts": shift_econ.costs["shifts"] * 5,
            "cross_skill": 1_800,
            "overtime": shift_econ.costs["overtime"] * 5,
            "hiring_retraining": hiring_cost,
            "trays": 0,
            "materials": shift_econ.costs["materials"] * 5,
            "rework": shift_econ.costs["rework"] * 5,
            "late": shift_econ.costs["late"] * 5,
            "backlog_holding": carry_out * 600,
            "unfulfilled": shift_econ.costs["unfulfilled"] * 5 if w == 11 else 0,
            "escaped": shift_econ.costs["escaped"] * 5,
        }
        week_econ = Economy(purchase=1_350_000, costs=v2_costs, total=sum(v2_costs.values()))
        total_cost += week_econ.total
        total_labor += raw.labor_ticks
        plan_weeks.append(wp)
        report_weeks.append(
            _DuckWeekReport(
                week=w,
                label=f"wk_{w:02d}",
                week_seed=scen.seed,
                carryover_in=carry_in,
                carryover_out=carry_out,
                wear_start=wear_start,
                wear_end=wear_end,
                commissioning_active=commissioning,
                shift_plan=sp,
                scenario=scen,
                raw=raw,
                shift_economy=shift_econ,
                week_economy=week_econ,
                week_world=eff_w,
            )
        )

    q_plan = _DuckQuarterlyPlan(2, tuple(plan_weeks))
    q_report = _DuckQuarterReport(2, 11, 1_350_000, total_cost, total_labor, tuple(report_weeks))
    eval_stub = Evaluation(False, False, False, 0, 1, {}, ("good_each_week", "escaped_each_week_max"))

    diag = build_diag(world, q_report, q_plan, evaluation=eval_stub)
    assert diag["diagnostics_version"] == 1
    assert diag["seed"] == 11
    assert diag["total_weeks"] == 12
    assert set(diag["counts_by_category"].keys()) == expected_categories
    for cat in expected_categories:
        assert diag["counts_by_category"][cat] >= 1, f"Expected category {cat} > 0, got {diag['counts_by_category']}"
    assert diag["total_issues"] == sum(diag["counts_by_category"].values())
    assert diag["total_issues"] == diag["critical_issues"] + diag["warning_issues"]
    assert diag["critical_issues"] >= 3
    assert 0 in diag["critical_weeks"] and 4 in diag["critical_weeks"]
    assert not _CYRILLIC_RE.search(json.dumps(diag, ensure_ascii=False))

    md = render_diag_md(diag)
    assert md.strip() != ""
    assert not _CYRILLIC_RE.search(md)
    assert "commissioning_jam_unassisted" in md or "Commissioning" in md

    pack_dir = tmp_path / "diag_qpack"
    export_quarter_pack(world, q_report, q_plan, pack_dir, evaluation=eval_stub)
    assert (pack_dir / "diagnostics.md").is_file()
    qm = json.loads((pack_dir / "quarter_manifest.json").read_text(encoding="utf-8"))
    assert qm["diagnostics_file"] == "diagnostics.md"
    assert qm["diagnostics"] == diag
    assert validate_quarter_pack(pack_dir, expected_weeks=12)["ok"] is True

    # Sacred v1 check: per-week manifest.json still has exact 7 keys!
    for w in range(12):
        wm = json.loads((pack_dir / f"weeks/week-{w:02d}/manifest.json").read_text(encoding="utf-8"))
        assert set(wm.keys()) == {"replay_format", "world", "plan", "scenario", "raw", "economy", "events_file"}

    # Validator rejects missing diagnostics.md, Cyrillic diagnostics.md, stray root file, tampered counts
    def clone_diag_pack(name: str) -> Path:
        dst = tmp_path / f"diag_mut_{name}"
        (dst / "weeks").mkdir(parents=True)
        (dst / "quarter_manifest.json").write_bytes((pack_dir / "quarter_manifest.json").read_bytes())
        (dst / "diagnostics.md").write_bytes((pack_dir / "diagnostics.md").read_bytes())
        for w in range(12):
            src_w = pack_dir / "weeks" / f"week-{w:02d}"
            dst_w = dst / "weeks" / f"week-{w:02d}"
            dst_w.mkdir()
            (dst_w / "manifest.json").write_bytes((src_w / "manifest.json").read_bytes())
            (dst_w / "events.jsonl").write_bytes((src_w / "events.jsonl").read_bytes())
        return dst

    p_missing = clone_diag_pack("missing_md")
    (p_missing / "diagnostics.md").unlink()
    with pytest.raises(ValueError):
        validate_quarter_pack(p_missing, expected_weeks=12)

    p_empty = clone_diag_pack("empty_md")
    (p_empty / "diagnostics.md").write_text("   \n", encoding="utf-8")
    with pytest.raises(ValueError):
        validate_quarter_pack(p_empty, expected_weeks=12)

    p_cyr = clone_diag_pack("cyrillic_md")
    (p_cyr / "diagnostics.md").write_text("# Ошибка\n", encoding="utf-8")
    with pytest.raises(ValueError):
        validate_quarter_pack(p_cyr, expected_weeks=12)

    p_stray = clone_diag_pack("stray_root")
    (p_stray / "unexpected.txt").write_text("stray\n", encoding="utf-8")
    with pytest.raises(ValueError):
        validate_quarter_pack(p_stray, expected_weeks=12)

    p_tampered = clone_diag_pack("tampered_counts")
    qm_bad = json.loads((p_tampered / "quarter_manifest.json").read_text(encoding="utf-8"))
    qm_bad["diagnostics"]["total_issues"] += 1
    (p_tampered / "quarter_manifest.json").write_text(json.dumps(qm_bad) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        validate_quarter_pack(p_tampered, expected_weeks=12)


def test_export_3d_pack_extra_plan_v1_and_v2_and_strict_validation(tmp_path, monkeypatch):
    script_path = ROOT / "scripts" / "export_3d_pack.py"

    # 1. Valid v1 --extra-plan via subprocess CLI
    v1_plan_file = tmp_path / "extra_v1.json"
    v1_plan_file.write_text((ROOT / "data/plans/candidate.json").read_text(encoding="utf-8"), encoding="utf-8")
    out_v1 = tmp_path / "pack_extra_v1"
    proc_v1 = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--out",
            str(out_v1),
            "--seed",
            "11",
            "--extra-plan",
            f"custom-v1-model={v1_plan_file}",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc_v1.returncode == 0, proc_v1.stderr
    idx_v1 = json.loads((out_v1 / "index.json").read_text(encoding="utf-8"))
    extra_v1_run = next(r for r in idx_v1["runs"] if r["id"] == "custom-v1-model-seed11")
    assert extra_v1_run["mode"] == "v1"
    assert extra_v1_run["plan_name"] == "custom-v1-model"
    assert extra_v1_run["extra_plan"] is True
    assert extra_v1_run["feasible"] is True
    assert extra_v1_run["win"] is True
    assert extra_v1_run["reward_den"] > 0
    assert extra_v1_run["total_cost"] > 0
    assert validate_shift_bundle(out_v1 / "custom-v1-model-seed11")["ok"] is True
    assert any("custom-v1-model-seed11" in (c["left"], c["right"]) for c in idx_v1["comparisons"])

    # 2. Strict CLI validation errors -> exit code 2 & zero tracebacks
    sym_plan = tmp_path / "sym_plan.json"
    sym_plan.symlink_to(v1_plan_file)
    big_plan = tmp_path / "oversized_plan.json"
    big_plan.write_text('{"schema_version": 1, "pad": "' + ("x" * 70_000) + '"}\n', encoding="utf-8")
    dup_key_plan = tmp_path / "dup_key.json"
    dup_key_plan.write_text(
        '{"schema_version": 1, "schema_version": 1, "robot": false, "trays": false, "route": "manual", "workers": [[1,2,3,4]]}\n',
        encoding="utf-8",
    )
    nan_plan = tmp_path / "nan_plan.json"
    nan_plan.write_text('{"schema_version": NaN}\n', encoding="utf-8")
    bad_ver_plan = tmp_path / "bad_ver.json"
    bad_ver_plan.write_text('{"schema_version": 99}\n', encoding="utf-8")
    invalid_v1_plan = tmp_path / "invalid_v1.json"
    invalid_v1_plan.write_text(
        '{"schema_version": 1, "robot": false, "trays": false, "route": "all", "workers": [[1,2,3,4]]}\n',
        encoding="utf-8",
    )

    bad_invocations = [
        ["--extra-plan", "missing_equals"],
        ["--extra-plan", f"={v1_plan_file}"],
        ["--extra-plan", "empty_path="],
        ["--extra-plan", f"../traversal={v1_plan_file}"],
        ["--extra-plan", f"bad..dots={v1_plan_file}"],
        ["--extra-plan", f"slash/slug={v1_plan_file}"],
        ["--extra-plan", f"-leading-dash={v1_plan_file}"],
        ["--extra-plan", f"v1-manual={v1_plan_file}"],
        ["--extra-plan", f"Quarterly-Reference={v1_plan_file}"],
        ["--extra-plan", f"Post-RL-7B={v1_plan_file}", "--extra-plan", f"post-rl-7b={v1_plan_file}"],
        ["--extra-plan", f"sym={sym_plan}"],
        ["--extra-plan", f"dir={tmp_path}"],
        ["--extra-plan", f"big={big_plan}"],
        ["--extra-plan", f"dup={dup_key_plan}"],
        ["--extra-plan", f"nan={nan_plan}"],
        ["--extra-plan", f"ver={bad_ver_plan}"],
        ["--extra-plan", f"inv={invalid_v1_plan}"],
    ]
    for extra_flags in bad_invocations:
        res_bad = subprocess.run(
            [sys.executable, str(script_path), "--out", str(tmp_path / "never_ok"), "--seed", "11", *extra_flags],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert res_bad.returncode == 2, f"Expected rc=2 for {extra_flags}, got {res_bad.returncode}"
        assert "Traceback" not in res_bad.stderr, f"Unexpected traceback for {extra_flags}: {res_bad.stderr}"

    # 3. Repeatable v2 --extra-plan (Frontier + Post-RL) & quarterly-unavailable guard
    mod_ns = runpy.run_path(str(script_path))
    main_fn = mod_ns["main"]

    v2_frontier_file = tmp_path / "frontier_gemini.json"
    v2_post_rl_file = tmp_path / "post_rl_qwen.json"
    v2_frontier_payload = {
        "schema_version": 2,
        "weeks": [
            {
                "robot": True,
                "trays": False,
                "route": "all",
                "maintenance": False,
                "workers": [[1], [2], [3], [4]],
            }
            for _ in range(12)
        ],
    }
    v2_post_rl_payload = {
        "schema_version": 2,
        "weeks": [
            {
                "robot": True,
                "trays": True,
                "route": "bypass",
                "maintenance": (w in (4, 8)),
                "workers": [[1, 2], [1, 2], [2, 3], [3, 4], [4]],
            }
            for w in range(12)
        ],
    }
    v2_frontier_file.write_text(json.dumps(v2_frontier_payload) + "\n", encoding="utf-8")
    v2_post_rl_file.write_text(json.dumps(v2_post_rl_payload) + "\n", encoding="utf-8")

    # 3a. When quarterly is NOT available, schema_version=2 extra plan exits 2 cleanly
    import robotization_bench.contracts as contracts_mod

    base_world = load_world()
    world_no_q = json.loads(json.dumps(base_world))
    world_no_q.pop("quarterly", None)
    with monkeypatch.context() as mp:
        mp.setattr(contracts_mod, "load_world", lambda: json.loads(json.dumps(world_no_q)))
        mp.setitem(sys.modules, "robotization_bench.quarterly", None)
        with pytest.raises(SystemExit) as exc_no_q:
            main_fn(
                [
                    "--out",
                    str(tmp_path / "no_q_out"),
                    "--seed",
                    "11",
                    "--extra-plan",
                    f"frontier-gemini-4-carbon={v2_frontier_file}",
                ]
            )
        assert exc_no_q.value.code == 2

    # 3b. When quarterly IS available, both Frontier and Post-RL v2 extra plans export + validate + index!
    world_q = json.loads(json.dumps(base_world))
    world_q["quarterly"] = {"schema_version": 2, "world_id": "cell-quarterly-v2", "weeks": 12}
    import robotization_bench.episode as episode_mod
    import robotization_bench.grading as grading_mod
    import robotization_bench.validation as validation_mod

    def fake_parse_q(val, _w):
        if type(val) is not dict or val.get("schema_version") != 2 or len(val.get("weeks", ())) != 12:
            raise InvalidPlan("bad quarterly plan")
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

    def fake_manual_q(_w=None):
        return {
            "schema_version": 2,
            "weeks": [
                {"robot": False, "trays": False, "route": "manual", "maintenance": False, "workers": [[1], [2], [3], [3], [4], [2, 3]]}
                for _ in range(12)
            ],
        }

    def fake_sim_q(w, q_plan, seed, *, trace=False):
        automated = any(wp.robot for wp in q_plan.weeks)
        _, q_rep = _build_duck_quarter_fixture(
            w, seed=seed, automated=automated, attach_explicit_week_world=False, trace=trace
        )
        # Ensure week_report shift_plan & maintenance match q_plan.weeks exactly!
        fixed_weeks = []
        tot_c = 0
        tot_l = 0
        for idx, (wp, wr) in enumerate(zip(q_plan.weeks, q_rep.weeks)):
            sp = wp.to_shift_plan()
            eff_w = _make_week_world(w, idx, commissioning=(wp.robot and idx < 2), wear=wr.wear_start, maintenance=wp.maintenance)
            raw_w = simulate(eff_w, sp, wr.scenario, trace=trace)
            se = calculate(eff_w, sp, raw_w)
            we_costs = dict(wr.week_economy.costs)
            we_costs.update(
                depreciation=se.costs["depreciation"] * 5,
                service=3500 if wp.robot else 0,
                maintenance=4500 if wp.maintenance else 0,
                shifts=se.costs["shifts"] * 5,
                overtime=se.costs["overtime"],
                trays=se.costs["trays"],
                materials=se.costs["materials"],
                rework=se.costs["rework"],
                late=se.costs["late"],
                escaped=se.costs["escaped"],
            )
            we = Economy(purchase=se.purchase, costs=we_costs, total=sum(we_costs.values()))
            tot_c += we.total
            tot_l += raw_w.labor_ticks
            fixed_weeks.append(
                replace(wr, shift_plan=sp, raw=raw_w, shift_economy=se, week_economy=we)
            )
        has_r = any(wp.robot for wp in q_plan.weeks)
        has_t = any(wp.trays for wp in q_plan.weeks)
        pur = (w["money"]["robot_purchase"] if has_r else 0) + (w["money"]["tray_purchase"] if has_t else 0)
        return _DuckQuarterReport(2, seed, pur, tot_c, tot_l, tuple(fixed_weeks))

    def fake_eval_q(_w, val, _seeds):
        # Require >= 2 Zone-1 pickers + trays + bypass to win (verifies upgraded pre-M3 fallback_crews too!)
        wks = val["weeks"]
        dual_picker = all(sum(1 in z for z in wk["workers"]) >= 2 for wk in wks)
        bypass_trays = all(wk["robot"] and wk["trays"] and wk["route"] == "bypass" for wk in wks)
        is_win = dual_picker and bypass_trays
        is_auto = any(wk["robot"] for wk in wks)
        return Evaluation(
            valid=True,
            feasible=dual_picker or not is_auto,
            win=is_win,
            reward_num=2 if is_win else (1 if not is_auto else 1),
            reward_den=5 if (is_win or not is_auto) else 20,
            metrics={
                "orders": 200,
                "good": 200 if (dual_picker or not is_auto) else 150,
                "on_time": 198,
                "escaped": 0,
                "scrap": 0,
                "unfinished": 0,
                "purchase": 1_530_000 if is_win else (1_350_000 if is_auto else 0),
                "total_cost": 75_000 if is_win else 100_000,
                "base_cost": 100_000,
                "labor_ticks": 2800 if is_win else 4000,
                "base_labor_ticks": 4000,
                "auto_finished": 140 if is_auto else 0,
                "pack_finished": 200,
            },
            reasons=() if is_win else (("good_each_week",) if is_auto else ("cost",)),
        )

    fake_q_mod = types.ModuleType("robotization_bench.quarterly")
    fake_q_mod.manual_quarterly_value = fake_manual_q
    fake_q_mod.build_week_world = _make_week_world
    fake_q_mod.simulate_quarter = fake_sim_q

    monkeypatch.setattr(contracts_mod, "load_world", lambda: json.loads(json.dumps(world_q)))
    monkeypatch.setitem(sys.modules, "robotization_bench.quarterly", fake_q_mod)
    monkeypatch.setattr(validation_mod, "parse_quarterly_plan", fake_parse_q, raising=False)
    monkeypatch.setattr(grading_mod, "evaluate_quarterly", fake_eval_q, raising=False)
    monkeypatch.delattr(episode_mod, "QuarterlyEpisode", raising=False)

    out_v2 = tmp_path / "pack_extra_v2"
    rc_v2 = main_fn(
        [
            "--out",
            str(out_v2),
            "--seed",
            "11",
            "--extra-plan",
            f"frontier-gemini-4-carbon={v2_frontier_file}",
            "--extra-plan",
            f"post-rl-Qwen2.5-7B={v2_post_rl_file}",
        ]
    )
    assert rc_v2 == 0
    idx_v2 = json.loads((out_v2 / "index.json").read_text(encoding="utf-8"))
    runs_v2 = {r["id"]: r for r in idx_v2["runs"]}

    # Pre-M3 fallback reference achieved win=True with dual-picker crew!
    assert runs_v2["quarterly-reference-seed11"]["evaluation"]["win"] is True
    assert runs_v2["quarterly-manual-seed11"]["diagnostics_md"] == "quarterly-manual-seed11/diagnostics.md"
    assert runs_v2["quarterly-reference-seed11"]["diagnostics_md"] == "quarterly-reference-seed11/diagnostics.md"

    for slug, exp_win in (("frontier-gemini-4-carbon", False), ("post-rl-Qwen2.5-7B", True)):
        rid = f"{slug}-seed11"
        assert rid in runs_v2
        r_entry = runs_v2[rid]
        assert r_entry["mode"] == "quarterly"
        assert r_entry["plan_name"] == slug
        assert r_entry["extra_plan"] is True
        assert r_entry["diagnostics_md"] == f"{rid}/diagnostics.md"
        assert r_entry["win"] is exp_win
        assert (out_v2 / rid / "diagnostics.md").is_file()
        assert validate_quarter_pack(out_v2 / rid, expected_weeks=12)["ok"] is True
        assert any(rid in (c["left"], c["right"]) for c in idx_v2["comparisons"])
