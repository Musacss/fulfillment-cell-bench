"""Tier 2: Boundary value analysis, corner cases, and adversarial exploit probes across F01..F16."""

from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError, asdict, replace
from fractions import Fraction
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import time
import tomllib

import pytest

from .conftest import (
    CLI_OUTPUT_FLAGS,
    CYRILLIC_RE,
    ECONOMY_COST_KEYS_V1,
    MANUAL_WORKERS,
    PYTHON_BIN,
    REPO_ROOT,
    SECRET_PATTERNS,
    audit_v1_shift_bundle,
    best_phased_win_plan,
    extract_eval_dict,
    extract_mcp_payload,
    has_cli_flag,
    lazy_attr,
    lazy_mod,
    make_socket_client,
    make_week,
    mcp_proxy_cli_args,
    pick_cli_flag,
    python_specifier_allows,
    raw_http_request,
    run_mcp_session,
    run_staged_grade,
    running_bench_daemon,
    running_cors_server,
    scan_repo_for_secrets,
    send_unix_jsonl,
    v1_manual_plan,
    v2_buy_capex_idle,
    v2_manual_quarterly,
    v2_naive_all_unmaintained,
    v2_phased_win_candidates,
    v2_understaffed_carryover_plan,
    v2_unstaffed_jam_deadlock,
    v2_week11_token,
)


# ==============================================================================
# F01: Additive v2 Contracts Boundaries — 5 Tests
# ==============================================================================


def test_t2_f01_frozen_dataclass_mutation_blocked():
    contracts = lazy_mod("contracts")
    WeekPlan = lazy_attr("contracts", "WeekPlan")
    QuarterlyPlan = lazy_attr("contracts", "QuarterlyPlan")
    QuarterReport = lazy_attr("contracts", "QuarterReport")

    p1 = contracts.Plan(1, False, False, "manual", ((1,),))
    wp = WeekPlan(False, False, "manual", False, ((1,),))
    qp = QuarterlyPlan(2, (wp,) * 12)
    qr = QuarterReport(2, 11, 0, 0, 0, ())

    for obj, attr, val in (
        (p1, "robot", True),
        (wp, "maintenance", True),
        (qp, "schema_version", 99),
        (qr, "total_cost", 123),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(obj, attr, val)


def test_t2_f01_draw_modulus_one_and_range_bounds():
    draw = lazy_attr("contracts", "draw")
    assert draw(11, 0, 3, 0, "jam", 1) == 0
    vals = [draw(11 + i, i, (i % 4) + 1, i % 2, "jam", 10_000) for i in range(25)]
    assert all(0 <= v < 10_000 for v in vals)
    assert len(set(vals)) > 15
    base = draw(11, 5, 3, 0, "jam", 1_000_000_000)
    assert base != draw(12, 5, 3, 0, "jam", 1_000_000_000)
    assert base != draw(11, 6, 3, 0, "jam", 1_000_000_000)
    assert base != draw(11, 5, 4, 0, "jam", 1_000_000_000)
    assert base != draw(11, 5, 3, 1, "jam", 1_000_000_000)
    assert base != draw(11, 5, 3, 0, "defect", 1_000_000_000)


def test_t2_f01_exception_inheritance_boundaries():
    InvalidPlan = lazy_attr("contracts", "InvalidPlan")
    EpisodeClosed = lazy_attr("contracts", "EpisodeClosed")
    PilotBudgetExceeded = lazy_attr("contracts", "PilotBudgetExceeded")
    assert issubclass(InvalidPlan, ValueError)
    assert not issubclass(InvalidPlan, RuntimeError)
    assert issubclass(EpisodeClosed, RuntimeError)
    assert issubclass(PilotBudgetExceeded, RuntimeError)
    assert EpisodeClosed is not PilotBudgetExceeded


def test_t2_f01_to_shift_plan_strips_v2_fields():
    WeekPlan = lazy_attr("contracts", "WeekPlan")
    wp = WeekPlan(True, False, "all", True, ((1, 2, 3, 4),))
    sp_dict = asdict(wp.to_shift_plan())
    assert set(sp_dict.keys()) == {"schema_version", "robot", "trays", "route", "workers"}
    assert "maintenance" not in sp_dict
    assert sp_dict["schema_version"] == 1


def test_t2_f01_evaluation_reasons_tuple_type():
    invalid = lazy_attr("grading", "invalid")
    ev = invalid("bad plan")
    assert type(ev.reasons) is tuple
    assert ev.reasons == ("bad plan",)
    assert ev.metrics == {}
    assert (ev.valid, ev.feasible, ev.win, ev.reward_num, ev.reward_den) == (False, False, False, 0, 1)


# ==============================================================================
# F02: Quarterly World Catalog Boundaries — 5 Tests
# ==============================================================================


def test_t2_f02_v1_world_constants_byte_exact(world):
    assert world["clock"] == {
        "tick_seconds": 30,
        "shift_ticks": 960,
        "overtime_ticks": 120,
        "break_at": 440,
        "break_length": 40,
        "walk_ticks": 2,
    }
    assert world["capacity"] == {"pick": 12, "pack": 10, "qc": 8}
    assert world["workers"] == {"min": 1, "max": 8, "zones": [1, 2, 3, 4]}
    assert world["money"]["robot_purchase"] == 1_350_000
    assert world["money"]["tray_purchase"] == 180_000
    assert world["money"]["depreciation_days"] == 500


def test_t2_f02_week_profiles_sku_bps_sum_bounds(world):
    assert "quarterly" in world
    for prof in world["quarterly"]["week_profiles"]:
        assert prof["waves"] > 0
        assert prof["orders_min"] > 0
        assert 0 <= prof["regular_bps"] <= 10_000
        assert 0 <= prof["fragile_bps"] <= 10_000
        assert prof["regular_bps"] + prof["fragile_bps"] <= 10_000
        assert prof["due_offset"] > 0


def test_t2_f02_wear_and_commissioning_rate_ordering(world):
    assert "quarterly" in world
    wear = world["quarterly"]["wear"]
    comm = world["quarterly"]["commissioning"]
    assert 0 < wear["per_week_bypass"] < wear["per_week_all"] <= wear["max_wear"]
    assert wear["maintenance_reduction"] > 0
    assert comm["jam_bonus_bps"]["bare"] > comm["jam_bonus_bps"]["tray"] > 0
    assert comm["defect_bonus_bps"]["bare"] > comm["defect_bonus_bps"]["tray"] > 0


def test_t2_f02_quarterly_money_positive_rates(world):
    assert "quarterly" in world
    qm = world["quarterly"]["money"]
    for key in (
        "budget",
        "depreciation_weeks",
        "robot_service_week",
        "maintenance_cost",
        "shifts_per_week",
        "hire_cost",
        "layoff_cost",
        "retrain_cost",
        "cross_skill_shift_premium",
        "backlog_holding_per_order",
    ):
        assert type(qm[key]) is int and qm[key] > 0


def test_t2_f02_quarterly_thresholds_valid_bps(world):
    assert "quarterly" in world
    qt = world["quarterly"]["threshold_bps"]
    for val in qt.values():
        assert type(val) is int and 0 < val <= 10_000
    assert qt["good_each_week"] <= qt["good_pooled"]


# ==============================================================================
# F03: Dual v1/v2 Validation Boundaries & JSON Attacks — 5 Tests
# ==============================================================================


def test_t2_f03_weeks_length_11_12_13_boundary(world):
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    InvalidPlan = lazy_attr("contracts", "InvalidPlan")

    for bad_len in (0, 11, 13):
        with pytest.raises(InvalidPlan):
            parse_quarterly_plan({"schema_version": 2, "weeks": [make_week() for _ in range(bad_len)]}, world)

    ok = parse_quarterly_plan({"schema_version": 2, "weeks": [make_week() for _ in range(12)]}, world)
    assert len(ok.weeks) == 12


def test_t2_f03_capex_depurchase_true_to_false(world):
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    InvalidPlan = lazy_attr("contracts", "InvalidPlan")

    robot_drop = v2_manual_quarterly()
    robot_drop["weeks"][3] = make_week(robot=True, trays=False, route="bypass")
    robot_drop["weeks"][4] = make_week(robot=False, trays=False, route="manual")
    with pytest.raises(InvalidPlan):
        parse_quarterly_plan(robot_drop, world)

    tray_drop = v2_manual_quarterly()
    for w in range(12):
        tray_drop["weeks"][w] = make_week(robot=True, trays=(w == 0), route="bypass")
    with pytest.raises(InvalidPlan):
        parse_quarterly_plan(tray_drop, world)


def test_t2_f03_maintenance_true_with_robot_false(world):
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    InvalidPlan = lazy_attr("contracts", "InvalidPlan")

    bad = v2_manual_quarterly()
    bad["weeks"][5]["maintenance"] = True
    with pytest.raises(InvalidPlan):
        parse_quarterly_plan(bad, world)


def test_t2_f03_non_manual_route_with_robot_false(world):
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    InvalidPlan = lazy_attr("contracts", "InvalidPlan")

    for bad_route in ("bypass", "all"):
        bad = v2_manual_quarterly()
        bad["weeks"][2]["route"] = bad_route
        with pytest.raises(InvalidPlan):
            parse_quarterly_plan(bad, world)


def test_t2_f03_nan_inf_dup_keys_and_bool_as_int(world):
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    decode_quarterly_plan = lazy_attr("validation", "decode_quarterly_plan")
    InvalidPlan = lazy_attr("contracts", "InvalidPlan")

    raw_valid = json.dumps(v2_manual_quarterly())
    dup_root = '{"schema_version": 2, "schema_version": 2, "weeks": []}'
    for bad_txt in (dup_root, '{"schema_version": NaN, "weeks": []}', '{"schema_version": Infinity}'):
        with pytest.raises(InvalidPlan):
            decode_quarterly_plan(bad_txt, world)

    assert decode_quarterly_plan(raw_valid, world).schema_version == 2

    bad_dicts = []
    b1 = v2_manual_quarterly()
    b1["schema_version"] = True
    bad_dicts.append(b1)

    b2 = v2_manual_quarterly()
    b2["weeks"][0]["robot"] = 1
    bad_dicts.append(b2)

    b3 = v2_manual_quarterly()
    b3["weeks"][0]["workers"] = [[True]]
    bad_dicts.append(b3)

    b4 = v2_manual_quarterly()
    b4["weeks"][0]["workers"] = [[2, 2], [1], [3], [4]]
    bad_dicts.append(b4)

    b5 = v2_manual_quarterly()
    b5["weeks"][0]["workers"] = []
    bad_dicts.append(b5)

    b6 = v2_manual_quarterly()
    b6["weeks"][0]["workers"] = [[1]] * 9
    bad_dicts.append(b6)

    for bd in bad_dicts:
        with pytest.raises(InvalidPlan):
            parse_quarterly_plan(bd, world)


def test_t2_f03_any_plan_rejects_malformed_bool_version_dup_keys_and_nan(world):
    parse_any_plan = lazy_attr("validation", "parse_any_plan")
    decode_any_plan = lazy_attr("validation", "decode_any_plan")
    evaluate_any = lazy_attr("grading", "evaluate_any")
    InvalidPlan = lazy_attr("contracts", "InvalidPlan")

    bad_values = [
        None,
        {},
        [],
        "manual",
        42,
        {"schema_version": True, "robot": False, "trays": False, "route": "manual", "workers": MANUAL_WORKERS},
        {"schema_version": True, "weeks": [make_week() for _ in range(12)]},
        {"schema_version": 3, "weeks": [make_week() for _ in range(12)]},
        {"schema_version": 0, "weeks": []},
    ]
    for bad in bad_values:
        with pytest.raises(InvalidPlan):
            parse_any_plan(bad, world)
        ev = evaluate_any(world, bad, world["development_seeds"])
        assert ev.valid is False and (ev.reward_num, ev.reward_den) == (0, 1)

    valid_week_json = json.dumps(make_week())
    weeks_12_json = "[" + ",".join([valid_week_json] * 12) + "]"
    bad_texts = [
        "",
        "null",
        "{}",
        "[]",
        '{"schema_version": 2, "schema_version": 1, "robot": false, "trays": false, "route": "manual", "workers": [[1],[2],[3],[4]]}',
        f'{{"schema_version": 2, "schema_version": 2, "weeks": {weeks_12_json}}}',
        '{"schema_version": NaN, "weeks": []}',
        '{"schema_version": Infinity, "weeks": []}',
        '{"schema_version": -Infinity, "weeks": []}',
        f'{{"schema_version": true, "weeks": {weeks_12_json}}}',
        f'{{"schema_version": 3, "weeks": {weeks_12_json}}}',
    ]
    for raw_txt in bad_texts:
        with pytest.raises(InvalidPlan):
            decode_any_plan(raw_txt, world)


# ==============================================================================
# F04: 12-Week Coupled Simulator Boundaries — 6 Tests
# ==============================================================================


def test_t2_f04_carryover_in_out_sorting_and_cap(world):
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    simulate_quarter = lazy_attr("quarterly", "simulate_quarter")

    cap = world["quarterly"]["carryover_cap"]
    qp = parse_quarterly_plan(v2_understaffed_carryover_plan(), world)
    qr = simulate_quarter(world, qp, 11, trace=False)

    assert qr.weeks[0].carryover_in == 0
    saw_carryover = False
    for w in range(11):
        cur = qr.weeks[w]
        nxt = qr.weeks[w + 1]
        assert cur.carryover_out == min(cur.raw.unfinished, cap)
        assert nxt.carryover_in == cur.carryover_out
        carried = [o for o in nxt.scenario.orders if o.arrival == 0 and o.due == 0]
        assert len(carried) == nxt.carryover_in
        if nxt.carryover_in > 0:
            saw_carryover = True
        assert len({o.id for o in nxt.scenario.orders}) == len(nxt.scenario.orders)
        pairs = [(o.arrival, o.id) for o in nxt.scenario.orders]
        assert pairs == sorted(pairs)
    assert saw_carryover, "Understaffed 1-worker plan must generate positive backlog carryover"


def test_t2_f04_commissioning_two_week_window(world):
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    simulate_quarter = lazy_attr("quarterly", "simulate_quarter")

    plan_dict = {
        "schema_version": 2,
        "weeks": [
            make_week() if w < 2 else make_week(robot=True, trays=True, route="bypass")
            for w in range(12)
        ],
    }
    qp = parse_quarterly_plan(plan_dict, world)
    qr = simulate_quarter(world, qp, 11, trace=False)
    comm_weeks = world["quarterly"]["commissioning"]["weeks"]
    for w, wr in enumerate(qr.weeks):
        expected = 2 <= w < 2 + comm_weeks
        assert wr.commissioning_active is expected, f"Week {w} commissioning_active={wr.commissioning_active}"


def test_t2_f04_wear_escalation_all_vs_bypass_cap(world):
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    simulate_quarter = lazy_attr("quarterly", "simulate_quarter")

    max_wear = world["quarterly"]["wear"]["max_wear"]
    p_all = parse_quarterly_plan(v2_naive_all_unmaintained(), world)
    p_byp = parse_quarterly_plan(
        {
            "schema_version": 2,
            "weeks": [
                make_week(robot=True, trays=True, route="bypass", maintenance=False)
                for _ in range(12)
            ],
        },
        world,
    )
    r_all = simulate_quarter(world, p_all, 11, trace=False)
    r_byp = simulate_quarter(world, p_byp, 11, trace=False)

    for wr in (*r_all.weeks, *r_byp.weeks):
        assert 0 <= wr.wear_start <= max_wear
        assert 0 <= wr.wear_end <= max_wear
    assert max(w.wear_end for w in r_all.weeks) > r_byp.weeks[1].wear_end


def test_t2_f04_maintenance_wear_drop_and_slowdown(world):
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    simulate_quarter = lazy_attr("quarterly", "simulate_quarter")

    weeks = []
    for w in range(12):
        weeks.append(
            make_week(
                robot=True,
                trays=False,
                route="all",
                maintenance=(w == 4),
                workers=[[1], [2], [3, 4], [2, 3], [4]],
            )
        )
    qp = parse_quarterly_plan({"schema_version": 2, "weeks": weeks}, world)
    qr = simulate_quarter(world, qp, 11, trace=False)
    assert qr.weeks[3].wear_end >= 5
    # Maintenance in week 4 reduces wear relative to unmaintained trajectory
    assert qr.weeks[4].wear_start < qr.weeks[3].wear_end or qr.weeks[4].wear_end < qr.weeks[3].wear_end

    # Also verify maintenance_auto_slowdown_ticks inside simulate_quarter at identical wear_start == 0
    slowdown = world["quarterly"]["wear"]["maintenance_auto_slowdown_ticks"]
    assert slowdown >= 1
    p_no_maint = parse_quarterly_plan(
        {
            "schema_version": 2,
            "weeks": [make_week(robot=True, trays=True, route="bypass", maintenance=False) for _ in range(12)],
        },
        world,
    )
    p_wk0_maint = parse_quarterly_plan(
        {
            "schema_version": 2,
            "weeks": [
                make_week(robot=True, trays=True, route="bypass", maintenance=(w == 0)) for w in range(12)
            ],
        },
        world,
    )
    r_no = simulate_quarter(world, p_no_maint, 11, trace=True)
    r_yes = simulate_quarter(world, p_wk0_maint, 11, trace=True)
    assert r_no.weeks[0].wear_start == r_yes.weeks[0].wear_start == 0
    dur_no = next(
        ev.end_tick - ev.tick
        for ev in r_no.weeks[0].raw.events
        if ev.kind == "start" and ev.resource == "robot" and ev.stage == 3
    )
    dur_yes = next(
        ev.end_tick - ev.tick
        for ev in r_yes.weeks[0].raw.events
        if ev.kind == "start" and ev.resource == "robot" and ev.stage == 3
    )
    assert dur_yes - dur_no == slowdown


def test_t2_f04_e10_q3_bypass_nonblocking_and_trays_used_attempt_zero_only(world):
    build_week_world = lazy_attr("quarterly", "build_week_world")
    simulate_quarter = lazy_attr("quarterly", "simulate_quarter")
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    WeekPlan = lazy_attr("contracts", "WeekPlan")
    contracts = lazy_mod("contracts")
    engine = lazy_mod("engine")

    # (a) route="bypass": fragile order at head of Q3 must NOT block robot from starting regular order behind it
    wk_world = copy.deepcopy(build_week_world(world, 0, commissioning=False, wear=0, maintenance=False))
    wk_world["prob_bps"]["jam"]["tray"]["regular"] = 0
    wk_world["prob_bps"]["defect_auto"]["tray"]["regular"] = 0
    wp_no_z3_human = WeekPlan(True, True, "bypass", False, ((1,), (2,), (4,)))
    scen_bypass = contracts.Scenario(
        1,
        101,
        (
            contracts.Order(0, "fragile", 0, 200),
            contracts.Order(1, "regular", 0, 200),
        ),
    )
    raw_byp = engine.simulate(wk_world, wp_no_z3_human.to_shift_plan(), scen_bypass, trace=True)
    assert raw_byp.good == 1 and raw_byp.unfinished == 1
    assert any(e.kind == "start" and e.resource == "robot" and e.order_id == 1 for e in raw_byp.events)

    # (b) trays=True increments trays_used by 1 on attempt=0 (both manual & auto) and 0 on attempt=1 rework
    wk_rework = copy.deepcopy(wk_world)
    wk_rework["prob_bps"]["defect_auto"]["tray"]["regular"] = 10_000
    wk_rework["prob_bps"]["defect_manual"]["fragile"] = 10_000
    wk_rework["prob_bps"]["detect"] = 10_000
    wp_rework = WeekPlan(True, True, "bypass", False, ((1,), (2,), (3,), (4,)))
    raw_rw = engine.simulate(wk_rework, wp_rework.to_shift_plan(), scen_bypass, trace=True)
    assert raw_rw.auto_finished == 1
    assert raw_rw.rework_started == 2
    assert raw_rw.pack_started == 4
    assert raw_rw.trays_used == 2

    qp_trays = parse_quarterly_plan(
        {
            "schema_version": 2,
            "weeks": [make_week(robot=True, trays=True, route="bypass", maintenance=False) for _ in range(12)],
        },
        world,
    )
    qr_trays = simulate_quarter(world, qp_trays, 11, trace=True)
    assert sum(w.raw.rework_started for w in qr_trays.weeks) > 0
    for wr in qr_trays.weeks:
        att0_starts = sum(1 for e in wr.raw.events if e.kind == "start" and e.stage == 3 and e.attempt == 0)
        att1_starts = sum(1 for e in wr.raw.events if e.kind == "start" and e.stage == 3 and e.attempt == 1)
        assert wr.raw.trays_used == att0_starts
        assert wr.raw.rework_started == att1_starts


def test_t2_f04_weekly_raw_report_conservation(world):
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    simulate_quarter = lazy_attr("quarterly", "simulate_quarter")

    for plan_dict in (v2_unstaffed_jam_deadlock(), v2_phased_win_candidates()[0]):
        qp = parse_quarterly_plan(plan_dict, world)
        qr = simulate_quarter(world, qp, 11, trace=False)
        for wr in qr.weeks:
            r = wr.raw
            assert r.total == r.good + r.escaped + r.scrap + r.unfinished
            assert len(r.overtime_ticks) == len(wr.shift_plan.workers)


# ==============================================================================
# F05: Quarterly Integer-Cent Economics Boundaries — 5 Tests
# ==============================================================================


def test_t2_f05_hiring_layoff_retraining_cents(world, dev_scenarios):
    calculate_week = lazy_attr("economics", "calculate_week")
    WeekPlan = lazy_attr("contracts", "WeekPlan")
    engine = lazy_mod("engine")

    qm = world["quarterly"]["money"]
    base_w = ((1,), (2,), (3,), (4,))
    raw4 = engine.simulate(world, WeekPlan(False, False, "manual", False, base_w).to_shift_plan(), dev_scenarios[0])

    # +1 hire
    hire_w = ((1,), (2,), (3,), (4,), (1,))
    raw5 = engine.simulate(world, WeekPlan(False, False, "manual", False, hire_w).to_shift_plan(), dev_scenarios[0])
    _, e_hire = calculate_week(
        world,
        WeekPlan(False, False, "manual", False, hire_w),
        base_w,
        raw5,
        carryover_out=0,
        owned_robot=False,
        owned_trays=False,
    )
    assert e_hire.costs["hiring_retraining"] == qm["hire_cost"]

    # -1 layoff
    _, e_layoff = calculate_week(
        world,
        WeekPlan(False, False, "manual", False, base_w),
        hire_w,
        raw4,
        carryover_out=0,
        owned_robot=False,
        owned_trays=False,
    )
    assert e_layoff.costs["hiring_retraining"] == qm["layoff_cost"]

    # +1 zone skill retrain + cross-skill premium
    retrain_w = ((1, 3), (2,), (3,), (4,))
    raw_ret = engine.simulate(
        world, WeekPlan(False, False, "manual", False, retrain_w).to_shift_plan(), dev_scenarios[0]
    )
    _, e_ret = calculate_week(
        world,
        WeekPlan(False, False, "manual", False, retrain_w),
        base_w,
        raw_ret,
        carryover_out=0,
        owned_robot=False,
        owned_trays=False,
    )
    assert e_ret.costs["hiring_retraining"] == qm["retrain_cost"]
    assert e_ret.costs["cross_skill"] in (
        qm["cross_skill_shift_premium"],
        qm["cross_skill_shift_premium"] * qm["shifts_per_week"],
    )


def test_t2_f05_backlog_holding_vs_w11_unfulfilled(world):
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    simulate_quarter = lazy_attr("quarterly", "simulate_quarter")

    qm = world["quarterly"]["money"]
    qp = parse_quarterly_plan(v2_understaffed_carryover_plan(), world)
    qr = simulate_quarter(world, qp, 11, trace=False)

    for w in range(11):
        wr = qr.weeks[w]
        assert wr.week_economy.costs["backlog_holding"] == wr.carryover_out * qm["backlog_holding_per_order"]
    w11 = qr.weeks[11]
    assert w11.raw.unfinished > 0
    assert w11.week_economy.costs["unfulfilled"] >= w11.raw.unfinished * world["money"]["unfulfilled"]


def test_t2_f05_depreciation_52wk_half_up_integer(world, dev_scenarios):
    calculate_week = lazy_attr("economics", "calculate_week")
    WeekPlan = lazy_attr("contracts", "WeekPlan")
    engine = lazy_mod("engine")

    workers = ((1,), (2,), (3,), (4,))
    wp_manual = WeekPlan(False, False, "manual", False, workers)
    raw = engine.simulate(world, wp_manual.to_shift_plan(), dev_scenarios[0])

    _, econ_none = calculate_week(
        world, wp_manual, workers, raw, carryover_out=0, owned_robot=False, owned_trays=False
    )
    assert econ_none.costs["depreciation"] == 0

    wp_robot = WeekPlan(True, False, "manual", False, workers)
    raw_robot = engine.simulate(world, wp_robot.to_shift_plan(), dev_scenarios[0])
    _, econ_robot = calculate_week(
        world, wp_robot, workers, raw_robot, carryover_out=0, owned_robot=True, owned_trays=False
    )
    dep_weeks = world["quarterly"]["money"]["depreciation_weeks"]
    q, rem = divmod(world["money"]["robot_purchase"], dep_weeks)
    expected = q + (2 * rem >= dep_weeks)
    assert type(econ_robot.costs["depreciation"]) is int
    assert econ_robot.costs["depreciation"] == expected

    wp_both = WeekPlan(True, True, "manual", False, workers)
    raw_both = engine.simulate(world, wp_both.to_shift_plan(), dev_scenarios[0])
    _, econ_both = calculate_week(
        world, wp_both, workers, raw_both, carryover_out=0, owned_robot=True, owned_trays=True
    )
    assert econ_both.costs["depreciation"] > econ_robot.costs["depreciation"]


def test_t2_f05_buy_capex_idle_opex_penalty(world):
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    simulate_quarter = lazy_attr("quarterly", "simulate_quarter")

    p_man = parse_quarterly_plan(v2_manual_quarterly(world), world)
    p_idle = parse_quarterly_plan(v2_buy_capex_idle(world), world)
    r_man = simulate_quarter(world, p_man, 11, trace=False)
    r_idle = simulate_quarter(world, p_idle, 11, trace=False)

    assert r_idle.purchase == world["money"]["robot_purchase"] + world["money"]["tray_purchase"]
    assert all(w.week_economy.costs["depreciation"] > 0 for w in r_idle.weeks)
    assert all(
        w.week_economy.costs["service"] == world["quarterly"]["money"]["robot_service_week"]
        for w in r_idle.weeks
    )
    assert r_idle.total_cost > r_man.total_cost


def test_t2_f05_zero_depreciation_period_raises(world, dev_scenarios):
    economics = lazy_mod("economics")
    calculate_week = lazy_attr("economics", "calculate_week")
    WeekPlan = lazy_attr("contracts", "WeekPlan")
    engine = lazy_mod("engine")

    wp = WeekPlan(True, False, "manual", False, ((1,), (2,), (3,), (4,)))
    sp = wp.to_shift_plan()
    raw = engine.simulate(world, sp, dev_scenarios[0])

    w_bad_v1 = copy.deepcopy(world)
    w_bad_v1["money"]["depreciation_days"] = 0
    with pytest.raises(ValueError):
        economics.calculate(w_bad_v1, sp, raw)

    w_bad_v2 = copy.deepcopy(world)
    w_bad_v2["quarterly"]["money"]["depreciation_weeks"] = 0
    with pytest.raises(ValueError):
        calculate_week(
            w_bad_v2, wp, wp.workers, raw, carryover_out=0, owned_robot=True, owned_trays=False
        )


# ==============================================================================
# F06: Exact Fraction Evaluator & Verifier Boundaries — 5 Tests
# ==============================================================================


def test_t2_f06_jam_deadlock_positive_floor(world, dev_scenarios):
    grading = lazy_mod("grading")
    evaluate_quarterly = lazy_attr("grading", "evaluate_quarterly")

    v1_deadlock = {
        "schema_version": 1,
        "robot": True,
        "trays": False,
        "route": "all",
        "workers": [[1], [2], [4]],
    }
    ev_v1 = grading.evaluate(world, v1_deadlock, dev_scenarios)
    assert ev_v1.valid is True and ev_v1.feasible is False and ev_v1.win is False
    assert Fraction(1, 10_000) <= Fraction(ev_v1.reward_num, ev_v1.reward_den) <= Fraction(9, 100)

    ev_v2 = evaluate_quarterly(world, v2_unstaffed_jam_deadlock(), world["development_seeds"])
    assert ev_v2.valid is True and ev_v2.feasible is False and ev_v2.win is False
    assert Fraction(1, 10_000) <= Fraction(ev_v2.reward_num, ev_v2.reward_den) <= Fraction(9, 100)


def test_t2_f06_idle_capex_and_week11_token_lose(world):
    evaluate_quarterly = lazy_attr("grading", "evaluate_quarterly")
    seeds = world["development_seeds"]

    ev_idle = evaluate_quarterly(world, v2_buy_capex_idle(world), seeds)
    assert ev_idle.valid is True and ev_idle.feasible is True and ev_idle.win is False
    assert "automation" in ev_idle.reasons
    assert Fraction(1, 10) < Fraction(ev_idle.reward_num, ev_idle.reward_den) < Fraction(1, 5)

    ev_w11 = evaluate_quarterly(world, v2_week11_token(world), seeds)
    assert ev_w11.valid is True and ev_w11.feasible is True and ev_w11.win is False
    assert "automation" in ev_w11.reasons
    assert Fraction(1, 10) < Fraction(ev_w11.reward_num, ev_w11.reward_den) <= Fraction(1, 5)


def test_t2_f06_grade_quarters_rejects_seed_or_length_mismatch(world):
    grade_quarters = lazy_attr("grading", "grade_quarters")
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    simulate_quarter = lazy_attr("quarterly", "simulate_quarter")

    qp = parse_quarterly_plan(v2_manual_quarterly(world), world)
    q11 = simulate_quarter(world, qp, 11, trace=False)
    q29 = simulate_quarter(world, qp, 29, trace=False)

    with pytest.raises(ValueError):
        grade_quarters(world, qp, [], [])
    with pytest.raises(ValueError):
        grade_quarters(world, qp, [q11, q29], [q11])
    with pytest.raises(ValueError):
        grade_quarters(world, qp, [q11], [q29])


def test_t2_f06_over_budget_capex_infeasible(world):
    evaluate_quarterly = lazy_attr("grading", "evaluate_quarterly")
    tight_world = copy.deepcopy(world)
    tight_world["money"]["budget"] = 1_000_000
    tight_world["quarterly"]["money"]["budget"] = 1_000_000

    ev = evaluate_quarterly(tight_world, v2_phased_win_candidates()[0], tight_world["development_seeds"])
    assert ev.valid is True and ev.feasible is False and ev.win is False
    assert "budget" in ev.reasons
    assert Fraction(1, 10_000) <= Fraction(ev.reward_num, ev.reward_den) <= Fraction(9, 100)


def test_t2_f06_file_size_16384_vs_16385_bytes(world, tmp_path):
    verify_quarterly_file = lazy_attr("verifier", "verify_quarterly_file")
    compact = json.dumps(v2_manual_quarterly(world), separators=(",", ":")).encode("utf-8")
    assert len(compact) < 16_384

    f_ok = tmp_path / "exact_16384.json"
    f_ok.write_bytes(compact + b" " * (16_384 - len(compact)))
    assert f_ok.stat().st_size == 16_384
    ev_ok = verify_quarterly_file(world, f_ok, world["development_seeds"])
    assert ev_ok.valid is True and (ev_ok.reward_num, ev_ok.reward_den) == (1, 5)

    f_big = tmp_path / "over_16385.json"
    f_big.write_bytes(compact + b" " * (16_385 - len(compact)))
    assert f_big.stat().st_size == 16_385
    ev_big = verify_quarterly_file(world, f_big, world["development_seeds"])
    assert ev_big.valid is False and (ev_big.reward_num, ev_big.reward_den) == (0, 1)


def test_t2_f06_o_nofollow_symlink_fifo_dir_utf8(world, tmp_path):
    verify_quarterly_file = lazy_attr("verifier", "verify_quarterly_file")
    seeds = world["development_seeds"]

    real = tmp_path / "real.json"
    real.write_text(json.dumps(v2_manual_quarterly(world)), encoding="utf-8")
    sym = tmp_path / "sym.json"
    sym.symlink_to(real)

    fifo = tmp_path / "pipe.json"
    os.mkfifo(fifo)

    bad_utf8 = tmp_path / "bad_utf8.json"
    bad_utf8.write_bytes(b"\xff\xfe\xfd")

    sub_dir = tmp_path / "as_dir"
    sub_dir.mkdir()

    t0 = time.monotonic()
    for target in (sym, fifo, sub_dir, tmp_path / "missing.json", bad_utf8):
        ev = verify_quarterly_file(world, target, seeds)
        assert ev.valid is False and (ev.reward_num, ev.reward_den) == (0, 1)
    assert time.monotonic() - t0 < 1.0


# ==============================================================================
# F07: Bounded QuarterlyEpisode Boundaries — 5 Tests
# ==============================================================================


def test_t2_f07_max_pilots_n_minus_1_n_n_plus_1(world):
    QuarterlyEpisode = lazy_attr("episode", "QuarterlyEpisode")
    PilotBudgetExceeded = lazy_attr("contracts", "PilotBudgetExceeded")

    ep = QuarterlyEpisode(world, max_pilots=3)
    manual_q = v2_manual_quarterly(world)
    r1 = ep.pilot(manual_q, 11)
    r2 = ep.pilot(manual_q, 29)
    r3 = ep.pilot(manual_q, 47)
    assert (r1["pilot_budget"]["used"], r2["pilot_budget"]["used"], r3["pilot_budget"]["used"]) == (1, 2, 3)

    with pytest.raises(PilotBudgetExceeded):
        ep.pilot(manual_q, 11)

    rec = ep.submit(manual_q)
    assert rec["terminal"] is True and rec["plan"] == manual_q


def test_t2_f07_submit_invalid_closes_episode(world):
    QuarterlyEpisode = lazy_attr("episode", "QuarterlyEpisode")
    InvalidPlan = lazy_attr("contracts", "InvalidPlan")
    EpisodeClosed = lazy_attr("contracts", "EpisodeClosed")

    ep = QuarterlyEpisode(world)
    try:
        receipt = ep.submit({"bad": 1})
        assert receipt["terminal"] is True and receipt["plan"] is None
    except InvalidPlan:
        pass

    with pytest.raises(EpisodeClosed):
        ep.observe()


def test_t2_f07_episode_closed_after_submit_or_stop(world):
    QuarterlyEpisode = lazy_attr("episode", "QuarterlyEpisode")
    EpisodeClosed = lazy_attr("contracts", "EpisodeClosed")
    manual_q = v2_manual_quarterly(world)

    ep1 = QuarterlyEpisode(world)
    ep1.submit(manual_q)
    for fn in (
        lambda: ep1.observe(),
        lambda: ep1.pilot(manual_q, 11),
        lambda: ep1.submit(manual_q),
        lambda: ep1.stop(),
    ):
        with pytest.raises(EpisodeClosed):
            fn()

    ep2 = QuarterlyEpisode(world)
    ep2.stop()
    for fn in (
        lambda: ep2.observe(),
        lambda: ep2.pilot(manual_q, 11),
        lambda: ep2.submit(manual_q),
        lambda: ep2.stop(),
    ):
        with pytest.raises(EpisodeClosed):
            fn()


def test_t2_f07_bad_pilot_seed_or_plan_stays_open(world):
    QuarterlyEpisode = lazy_attr("episode", "QuarterlyEpisode")
    InvalidPlan = lazy_attr("contracts", "InvalidPlan")
    manual_q = v2_manual_quarterly(world)

    ep = QuarterlyEpisode(world, max_pilots=10)
    with pytest.raises(ValueError):
        ep.pilot(manual_q, 999_999)
    with pytest.raises((ValueError, TypeError)):
        ep.pilot(manual_q, True)
    with pytest.raises(InvalidPlan):
        ep.pilot({"schema_version": 2, "weeks": []}, 11)

    ok_pilot = ep.pilot(manual_q, 11)
    assert ok_pilot["seed"] == 11
    obs_mut = ep.observe()
    obs_mut["world"]["money"]["worker_shift"] = 0
    obs_mut["development_seeds"].clear()
    after_mut = ep.pilot(manual_q, 11)
    assert after_mut["total_cost"] == ok_pilot["total_cost"]
    rec = ep.submit(manual_q)
    assert rec["plan"] == manual_q


def test_t2_f07_state_path_persistence_on_reload(world, tmp_path):
    QuarterlyEpisode = lazy_attr("episode", "QuarterlyEpisode")
    PilotBudgetExceeded = lazy_attr("contracts", "PilotBudgetExceeded")
    EpisodeClosed = lazy_attr("contracts", "EpisodeClosed")

    state_file = tmp_path / "ep_state.json"
    manual_q = v2_manual_quarterly(world)

    ep1 = QuarterlyEpisode(world, max_pilots=2, state_path=state_file)
    ep1.pilot(manual_q, 11)
    ep1.pilot(manual_q, 29)
    assert state_file.is_file()

    ep2 = QuarterlyEpisode(world, max_pilots=2, state_path=state_file)
    obs2 = ep2.observe()
    assert obs2["pilot_budget"]["used"] == 2
    with pytest.raises(PilotBudgetExceeded):
        ep2.pilot(manual_q, 47)
    ep2.submit(manual_q)

    ep3 = QuarterlyEpisode(world, max_pilots=2, state_path=state_file)
    with pytest.raises(EpisodeClosed):
        ep3.observe()


# ==============================================================================
# F08: Socket Daemon & Stateless MCP Proxy Exploits (E05, E06) — 6 Tests
# ==============================================================================


def test_t2_f08_stdio_restart_flood_50x_preserves_pilot_budget(world, short_sock_dir, tmp_path):
    sock = short_sock_dir / "f1.sock"
    state = tmp_path / "state.json"
    sub = tmp_path / "sub.json"
    log = tmp_path / "log.json"
    manual_q = v2_manual_quarterly(world)

    with running_bench_daemon(sock, state_path=state, sub_path=sub, log_path=log, max_pilots=3):
        proxy_args, proxy_env = mcp_proxy_cli_args(sock)

        for idx, seed in enumerate((11, 29, 47), start=1):

            async def _one_pilot(session, s=seed):
                r = await session.call_tool("pilot", {"plan": manual_q, "seed": s, "trace": False})
                assert not r.isError
                return extract_mcp_payload(r)

            res = run_mcp_session(proxy_args, _one_pilot, env_extra=proxy_env)
            assert res["pilot_budget"]["used"] == idx

        async def _fourth_pilot(session):
            return await session.call_tool("pilot", {"plan": manual_q, "seed": 11, "trace": False})

        r4 = run_mcp_session(proxy_args, _fourth_pilot, env_extra=proxy_env)
        assert r4.isError is True

        for _ in range(50):
            c = make_socket_client(sock)
            with pytest.raises(Exception) as exc_info:
                c.pilot(manual_q, 11, trace=False)
            assert "budget" in str(exc_info.value).lower() or "pilot" in str(exc_info.value).lower()

        final_client = make_socket_client(sock)
        rec = final_client.submit(manual_q)
        assert rec["plan"] == manual_q


def test_t2_f08_post_submit_50x_reconnect_blocks_reopen_and_preserves_submission(
    world, short_sock_dir, tmp_path
):
    sock = short_sock_dir / "f2.sock"
    state = tmp_path / "state.json"
    sub = tmp_path / "sub.json"
    log = tmp_path / "log.json"
    manual_q = v2_manual_quarterly(world)

    with running_bench_daemon(sock, state_path=state, sub_path=sub, log_path=log, max_pilots=6):
        c0 = make_socket_client(sock)
        assert c0.submit(manual_q)["plan"] == manual_q

        for _ in range(50):
            c = make_socket_client(sock)
            with pytest.raises(Exception):
                c.observe()
            with pytest.raises(Exception):
                c.stop()

        proxy_args, proxy_env = mcp_proxy_cli_args(sock)

        async def _post_close(session):
            r_obs = await session.call_tool("observe", {})
            r_sub = await session.call_tool("submit", {"plan": manual_q})
            return r_obs.isError, r_sub.isError

        err1, err2 = run_mcp_session(proxy_args, _post_close, env_extra=proxy_env)
        assert err1 is True and err2 is True
        assert json.loads(sub.read_text(encoding="utf-8")) == manual_q


def test_t2_f08_stale_submission_overwritten_with_null_on_stop_and_invalid_submit(short_sock_dir, tmp_path):
    # E06 nop case: observe only (disconnect without stop/submit) must clear pre-existing stale submission
    sock_nop = short_sock_dir / "st_nop.sock"
    state_nop = tmp_path / "state_nop.json"
    sub_nop = tmp_path / "sub_nop.json"
    log_nop = tmp_path / "log_nop.json"
    sub_nop.write_text('{"stale": true}\n', encoding="utf-8")
    with running_bench_daemon(sock_nop, state_path=state_nop, sub_path=sub_nop, log_path=log_nop):
        p_args, p_env = mcp_proxy_cli_args(sock_nop)

        async def _obs_only(session):
            return await session.call_tool("observe", {})

        obs_r = run_mcp_session(p_args, _obs_only, env_extra=p_env)
        assert not obs_r.isError
    assert not sub_nop.exists() or json.loads(sub_nop.read_text(encoding="utf-8")) is None

    cases = (
        ("stop", {}),
        ("submit", {}),
        ("submit", {"plan": {"schema_version": 2, "weeks": []}}),
    )
    for idx, (tool_name, tool_args) in enumerate(cases):
        sock = short_sock_dir / f"st{idx}.sock"
        state = tmp_path / f"state_{idx}.json"
        sub = tmp_path / f"sub_{idx}.json"
        log = tmp_path / f"log_{idx}.json"
        sub.write_text('{"stale": true}\n', encoding="utf-8")

        with running_bench_daemon(sock, state_path=state, sub_path=sub, log_path=log):
            proxy_args, proxy_env = mcp_proxy_cli_args(sock)

            async def _act(session, tn=tool_name, ta=tool_args):
                r1 = await session.call_tool(tn, ta)
                r2 = await session.call_tool("observe", {})
                return r1, r2

            r1, r2 = run_mcp_session(proxy_args, _act, env_extra=proxy_env)
            assert json.loads(sub.read_text(encoding="utf-8")) is None
            if not r1.isError:
                payload = extract_mcp_payload(r1)
                assert payload["terminal"] is True and payload["plan"] is None
            assert r2.isError is True


def test_t2_f08_daemon_malformed_jsonl_unknown_action_and_unlisted_seed(world, short_sock_dir, tmp_path):
    sock = short_sock_dir / "mal.sock"
    state = tmp_path / "state.json"
    sub = tmp_path / "sub.json"
    log = tmp_path / "log.json"
    manual_q = v2_manual_quarterly(world)

    with running_bench_daemon(sock, state_path=state, sub_path=sub, log_path=log):
        for bad_payload in (
            "{bad_json\n",
            "[1, 2, 3]\n",
            {"action": "dump_private_seeds", "args": {}},
            {"action": "pilot", "args": {"plan": manual_q, "seed": -999, "trace": False}},
            {"action": "pilot", "args": {"plan": manual_q, "seed": True, "trace": False}},
        ):
            resp = send_unix_jsonl(sock, bad_payload)
            assert resp["ok"] is False

        ok_obs = send_unix_jsonl(sock, {"action": "observe", "args": {}})
        assert ok_obs["ok"] is True
        ok_stop = send_unix_jsonl(sock, {"action": "stop", "args": {}})
        assert ok_stop["ok"] is True


def test_t2_f08_cli_colliding_paths_and_autostart_launcher_hook(run_cli, short_sock_dir, tmp_path):
    same = tmp_path / "same.json"
    r1 = run_cli(["-m", "robotization_bench.mcp_server", "--submission", str(same), "--log", str(same)])
    assert r1.returncode != 0

    r2 = run_cli(["-m", "robotization_bench.mcp_server", "--state", str(same), "--submission", str(same)])
    assert r2.returncode != 0

    sock = short_sock_dir / "auto.sock"
    pid_file = tmp_path / "daemon.pid"
    state = tmp_path / "state.json"
    sub = tmp_path / "sub.json"
    log = tmp_path / "log.json"
    launcher = short_sock_dir / "start_daemon.sh"
    launcher.write_text(
        "#!/bin/sh\n"
        f'PYTHONPATH="{REPO_ROOT / "src"}" "{PYTHON_BIN}" -m robotization_bench.mcp_server '
        f'--socket "{sock}" --state "{state}" --submission "{sub}" --log "{log}" >/dev/null 2>&1 &\n'
        f'echo $! > "{pid_file}"\n'
        "i=0\n"
        f'while [ ! -S "{sock}" ] && [ "$i" -lt 50 ]; do\n'
        "  sleep 0.05\n"
        "  i=$((i + 1))\n"
        "done\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)

    try:
        client = make_socket_client(sock, autostart_bin=launcher)
        obs = client.observe()
        assert obs["schema_version"] == 2
    finally:
        if pid_file.is_file():
            try:
                os.kill(int(pid_file.read_text(encoding="utf-8").strip()), 15)
            except OSError:
                pass


def test_t2_f08_daemon_process_restart_restores_state_json_without_wiping_submission(
    world, short_sock_dir, tmp_path
):
    sock = short_sock_dir / "res.sock"
    state = tmp_path / "state.json"
    sub = tmp_path / "sub.json"
    log = tmp_path / "log.json"
    manual_q = v2_manual_quarterly(world)

    with running_bench_daemon(sock, state_path=state, sub_path=sub, log_path=log, max_pilots=4):
        c1 = make_socket_client(sock)
        c1.pilot(manual_q, 11)
        c1.submit(manual_q)
        assert json.loads(sub.read_text(encoding="utf-8")) == manual_q

    sock.unlink(missing_ok=True)
    with running_bench_daemon(sock, state_path=state, sub_path=sub, log_path=log, max_pilots=4):
        assert json.loads(sub.read_text(encoding="utf-8")) == manual_q
        c2 = make_socket_client(sock)
        with pytest.raises(Exception):
            c2.observe()


# ==============================================================================
# F09: Harbor Packaging & Isolation Boundaries (E08, E12) — 5 Tests
# ==============================================================================


def test_t2_f09_prepare_harbor_rejects_existing_out_without_overwrite(run_cli, tmp_path):
    seeds = tmp_path / "seeds.json"
    seeds.write_text("[37281939]\n", encoding="utf-8")
    existing = tmp_path / "already_here"
    existing.mkdir()
    (existing / "keep.txt").write_text("do_not_clobber", encoding="utf-8")

    res = run_cli(["scripts/prepare_harbor.py", "--out", str(existing), "--seeds-file", str(seeds)])
    assert res.returncode != 0
    assert (existing / "keep.txt").read_text(encoding="utf-8") == "do_not_clobber"


def test_t2_f09_prepare_harbor_rejects_overlapping_dev_seeds_and_bad_types(run_cli, tmp_path):
    bad_payloads = [
        "[11, 88888]",
        "[29]",
        "[47]",
        "[]",
        "[42, 42]",
        "[true]",
        '["42"]',
        '{"seeds": [42]}',
    ]
    for idx, raw in enumerate(bad_payloads):
        sf = tmp_path / f"bad_{idx}.json"
        sf.write_text(raw, encoding="utf-8")
        out = tmp_path / f"out_{idx}"
        res = run_cli(["scripts/prepare_harbor.py", "--out", str(out), "--seeds-file", str(sf)])
        assert res.returncode != 0
        assert not out.exists()


def test_t2_f09_agent_pythonpath_cannot_import_simulator_or_read_eval_seeds(run_cli, tmp_path):
    secret_seed = 76543219
    seeds = tmp_path / "seeds.json"
    seeds.write_text(f"[{secret_seed}]\n", encoding="utf-8")
    task = tmp_path / "task"
    res = run_cli(["scripts/prepare_harbor.py", "--out", str(task), "--seeds-file", str(seeds)])
    assert res.returncode == 0, res.stderr

    public_dir = task / "environment" / "public"
    forbidden_mods = [
        "engine",
        "quarterly",
        "scenarios",
        "economics",
        "grading",
        "verifier",
        "reference",
        "episode",
        "mcp_server",
    ]
    probe = subprocess.run(
        [
            str(PYTHON_BIN),
            "-I",
            "-B",
            "-c",
            "import importlib, json, sys; sys.path.insert(0, sys.argv[1]); "
            "leaked = [];\n"
            "for m in json.loads(sys.argv[2]):\n"
            "    try:\n"
            "        importlib.import_module('robotization_bench.' + m)\n"
            "        leaked.append(m)\n"
            "    except ImportError:\n"
            "        pass\n"
            "print(json.dumps(leaked))",
            str(public_dir / "src"),
            json.dumps(forbidden_mods),
        ],
        cwd=str(public_dir),
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    assert probe.returncode == 0, probe.stderr
    assert json.loads(probe.stdout.strip()) == []

    for env_file in (task / "environment").rglob("*"):
        if env_file.is_file():
            txt = env_file.read_text(encoding="utf-8", errors="ignore")
            assert str(secret_seed) not in txt


def test_t2_f09_tampering_public_tree_cannot_affect_airgapped_grade_py(run_cli, world, tmp_path):
    seeds = tmp_path / "seeds.json"
    seeds.write_text("[37281939]\n", encoding="utf-8")
    task = tmp_path / "task"
    res = run_cli(["scripts/prepare_harbor.py", "--out", str(task), "--seeds-file", str(seeds)])
    assert res.returncode == 0, res.stderr

    sub = tmp_path / "sub.json"
    sub.write_text(json.dumps(v2_manual_quarterly(world)), encoding="utf-8")
    v1_dir = tmp_path / "v1"
    v2_dir = tmp_path / "v2"
    first = run_staged_grade(task, sub, v1_dir)
    first_ev = extract_eval_dict(first)
    assert first_ev["valid"] is True
    assert (first_ev["reward_num"], first_ev["reward_den"]) == (1, 5)

    pub_pkg = task / "environment" / "public" / "src" / "robotization_bench"
    (pub_pkg / "grading.py").write_text("raise SystemExit(99)\n", encoding="utf-8")
    if (pub_pkg / "mcp_proxy.py").is_file():
        (pub_pkg / "mcp_proxy.py").write_text("raise SystemExit(98)\n", encoding="utf-8")

    second = run_staged_grade(task, sub, v2_dir)
    assert extract_eval_dict(second) == first_ev
    assert (v2_dir / "reward.txt").read_text(encoding="utf-8") == (v1_dir / "reward.txt").read_text(
        encoding="utf-8"
    )


def test_t2_f09_grade_py_scores_zero_on_missing_null_symlink_and_oversized_submission(run_cli, tmp_path):
    secret_seed = 76543219
    seeds = tmp_path / "seeds.json"
    seeds.write_text(f"[{secret_seed}]\n", encoding="utf-8")
    task = tmp_path / "task"
    res = run_cli(["scripts/prepare_harbor.py", "--out", str(task), "--seeds-file", str(seeds)])
    assert res.returncode == 0, res.stderr

    null_sub = tmp_path / "null.json"
    null_sub.write_text("null\n", encoding="utf-8")

    sym_sub = tmp_path / "sym.json"
    sym_sub.symlink_to(task / "tests" / "seeds.json")

    big_sub = tmp_path / "big.json"
    big_sub.write_bytes(b"x" * 16_385)

    fake_sub = tmp_path / "fake.json"
    fake_sub.write_text('{"reward_num": 1, "reward_den": 1}\n', encoding="utf-8")

    for idx, candidate_path in enumerate((tmp_path / "missing.json", null_sub, sym_sub, big_sub, fake_sub)):
        out_v = tmp_path / f"verdict_{idx}"
        verdict = run_staged_grade(task, candidate_path, out_v)
        ev = extract_eval_dict(verdict)
        assert ev["valid"] is False
        assert (ev["reward_num"], ev["reward_den"]) == (0, 1)
        assert float((out_v / "reward.txt").read_text(encoding="utf-8").strip()) == 0.0
        assert str(secret_seed) not in json.dumps(ev["reasons"])


# ==============================================================================
# F10: Reference Optimizer Boundaries — 5 Tests
# ==============================================================================


def test_t2_f10_tight_pilot_budget_1_3_5_never_exceeds_max_pilots(world):
    QuarterlyEpisode = lazy_attr("episode", "QuarterlyEpisode")
    solve = lazy_attr("reference", "solve")
    evaluate_quarterly = lazy_attr("grading", "evaluate_quarterly")

    for k in (1, 3, 5):
        ep = QuarterlyEpisode(world, max_pilots=k)
        plan = solve(ep)
        used = sum(1 for e in ep.log if e["action"] == "pilot" and "error" not in e)
        assert used <= k
        rec = ep.submit(plan)
        assert rec["plan"] == plan
        ev = evaluate_quarterly(world, plan, world["development_seeds"])
        assert ev.valid is True and ev.feasible is True
        assert Fraction(ev.reward_num, ev.reward_den) >= Fraction(1, 5)


def test_t2_f10_zero_pilot_budget_graceful_fallback_to_valid_plan(world):
    QuarterlyEpisode = lazy_attr("episode", "QuarterlyEpisode")
    solve = lazy_attr("reference", "solve")
    evaluate_quarterly = lazy_attr("grading", "evaluate_quarterly")

    try:
        ep = QuarterlyEpisode(world, max_pilots=0)
    except ValueError:
        ep = QuarterlyEpisode(world, max_pilots=1)
        ep.pilot(v2_manual_quarterly(world), world["development_seeds"][0])
    plan = solve(ep)
    rec = ep.submit(plan)
    assert rec["plan"] == plan
    ev = evaluate_quarterly(world, plan, world["development_seeds"])
    assert ev.valid is True and ev.feasible is True
    assert Fraction(ev.reward_num, ev.reward_den) >= Fraction(1, 5)


def test_t2_f10_pure_duck_typed_wrapper_blocks_private_attribute_access(world):
    QuarterlyEpisode = lazy_attr("episode", "QuarterlyEpisode")
    solve = lazy_attr("reference", "solve")
    evaluate_quarterly = lazy_attr("grading", "evaluate_quarterly")

    inner = QuarterlyEpisode(world)

    class OpaqueDuckProxy:
        def observe(self):
            return inner.observe()

        def pilot(self, plan, seed: int, *, trace: bool = False):
            return inner.pilot(plan, seed, trace=trace)

    plan = solve(OpaqueDuckProxy())
    ev = evaluate_quarterly(world, plan, world["development_seeds"])
    assert ev.valid is True and ev.feasible is True and ev.win is True


def test_t2_f10_determinism_and_phased_operational_structure(world):
    QuarterlyEpisode = lazy_attr("episode", "QuarterlyEpisode")
    solve = lazy_attr("reference", "solve")
    evaluate_quarterly = lazy_attr("grading", "evaluate_quarterly")

    p1 = solve(QuarterlyEpisode(world))
    p2 = solve(QuarterlyEpisode(world))
    assert p1 == p2

    robots = [wk["robot"] for wk in p1["weeks"]]
    trays = [wk["trays"] for wk in p1["weeks"]]
    assert robots == sorted(robots)
    assert trays == sorted(trays)
    for wk in p1["weeks"]:
        if wk["robot"]:
            assert any(3 in z for z in wk["workers"]), "Automated week must staff Zone-3 jam coverage"

    ev_ref = evaluate_quarterly(world, p1, world["development_seeds"])
    ev_naive = evaluate_quarterly(world, v2_naive_all_unmaintained(), world["development_seeds"])
    assert Fraction(ev_ref.reward_num, ev_ref.reward_den) > Fraction(
        ev_naive.reward_num, ev_naive.reward_den
    )


def test_t2_f10_adapts_under_tightened_capex_budget_without_hardcoded_plan(world):
    QuarterlyEpisode = lazy_attr("episode", "QuarterlyEpisode")
    solve = lazy_attr("reference", "solve")
    evaluate_quarterly = lazy_attr("grading", "evaluate_quarterly")

    tight_world = copy.deepcopy(world)
    # 1_400_000 fits robot (1_350_000) or manual (0), but NOT robot+trays (1_530_000)
    tight_world["money"]["budget"] = 1_400_000
    tight_world["quarterly"]["money"]["budget"] = 1_400_000

    plan = solve(QuarterlyEpisode(tight_world))
    ev = evaluate_quarterly(tight_world, plan, tight_world["development_seeds"])
    assert ev.valid is True and ev.feasible is True
    assert ev.metrics["purchase"] <= 1_400_000
    assert Fraction(ev.reward_num, ev.reward_den) >= Fraction(1, 5)


# ==============================================================================
# F11: Verda Cloud & RL Scripts Boundaries (E12) — 5 Tests
# ==============================================================================


def _assert_seed_disjointness_rejection(res: subprocess.CompletedProcess[str]) -> None:
    assert res.returncode != 0
    combined = (res.stdout + "\n" + res.stderr).lower()
    for bogus in ("unrecognized arguments", "invalid int", "command not found", "modulenotfounderror"):
        assert bogus not in combined, f"Script failed with CLI/import error rather than seed guard: {combined}"
    assert any(
        kw in combined
        for kw in ("seed", "overlap", "disjoint", "contaminat", "development", "replay", "blind", "forbidden")
    ), f"Expected seed overlap/disjointness error message, got: {combined}"


def test_t2_f11_sft_generator_rejects_overlapping_dev_or_replay_seeds(run_cli, tmp_path):
    script = "scripts/verda/generate_sft_traces.py"
    help_res = run_cli([script, "--help"], timeout=8.0)
    assert help_res.returncode == 0, help_res.stderr
    help_txt = help_res.stdout + help_res.stderr

    bad_seeds_file = tmp_path / "contaminated_seeds.json"
    bad_seeds_file.write_text("[11, 5343194]\n", encoding="utf-8")
    out_file = tmp_path / "bad_out.jsonl"

    base_cmd = [script]
    out_flag = pick_cli_flag(help_txt, CLI_OUTPUT_FLAGS)
    if out_flag is not None:
        base_cmd.extend([out_flag, str(out_file)])

    file_seed_flag = pick_cli_flag(
        help_txt, ("--train-seeds-file", "--seeds-file", "--seed-file", "--seeds-path", "--seeds-json")
    )
    pool_seed_flag = pick_cli_flag(help_txt, ("--train-seeds", "--seeds"))
    int_seed_flag = pick_cli_flag(help_txt, ("--seed",))

    if file_seed_flag is not None:
        res = run_cli([*base_cmd, file_seed_flag, str(bad_seeds_file)], timeout=10.0)
    elif pool_seed_flag is not None:
        res = run_cli([*base_cmd, pool_seed_flag, str(bad_seeds_file)], timeout=10.0)
        if "invalid int" in (res.stdout + res.stderr).lower():
            res = run_cli([*base_cmd, pool_seed_flag, "11"], timeout=10.0)
    elif int_seed_flag is not None:
        res = run_cli([*base_cmd, int_seed_flag, "11"], timeout=10.0)
    else:
        raise AssertionError(f"{script} must expose a seed/seeds-file flag for 4-way disjointness validation")

    _assert_seed_disjointness_rejection(res)


def test_t2_f11_grpo_trainer_rejects_contaminated_train_val_or_blind_seed_pools(run_cli, tmp_path):
    script = "scripts/verda/train_grpo_qwen7b.py"
    help_res = run_cli([script, "--help"], timeout=8.0)
    assert help_res.returncode == 0, help_res.stderr
    help_txt = help_res.stdout + help_res.stderr

    bad_seeds = tmp_path / "bad_train.json"
    bad_seeds.write_text("[29, 301926751]\n", encoding="utf-8")
    base_cmd = [script]
    if has_cli_flag(help_txt, "--dry-run"):
        base_cmd.append("--dry-run")
    if has_cli_flag(help_txt, "--validate-seeds-only"):
        base_cmd.append("--validate-seeds-only")

    file_flag = pick_cli_flag(
        help_txt,
        (
            "--train-seeds-file",
            "--seeds-file",
            "--val-seeds-file",
            "--blind-seeds-file",
            "--seed-file",
            "--seeds-path",
            "--seeds-json",
        ),
    )
    pool_flag = pick_cli_flag(help_txt, ("--train-seeds", "--val-seeds", "--blind-seeds", "--seeds"))

    if file_flag is not None:
        res = run_cli([*base_cmd, file_flag, str(bad_seeds)], timeout=10.0)
    elif pool_flag is not None:
        res = run_cli([*base_cmd, pool_flag, str(bad_seeds)], timeout=10.0)
        if "invalid int" in (res.stdout + res.stderr).lower():
            res = run_cli([*base_cmd, pool_flag, "29"], timeout=10.0)
    else:
        raise AssertionError(f"{script} must accept a seed pool CLI option to enforce pre-GPU 4-way disjointness")

    _assert_seed_disjointness_rejection(res)


def test_t2_f11_run_harbor_matrix_rejects_overlapping_blind_seeds_and_never_calls_ssh(tmp_path):
    script = REPO_ROOT / "scripts" / "verda" / "run_harbor_matrix.sh"
    assert script.is_file()

    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    ssh_marker = tmp_path / "ssh_called.txt"
    harbor_marker = tmp_path / "harbor_called.txt"
    docker_marker = tmp_path / "docker_called.txt"
    for bin_name, marker, code in (
        ("ssh", ssh_marker, 99),
        ("harbor", harbor_marker, 0),
        ("docker", docker_marker, 0),
    ):
        stub = stub_bin / bin_name
        stub.write_text(f'#!/bin/sh\necho called > "{marker}"\nexit {code}\n', encoding="utf-8")
        stub.chmod(0o755)

    bad_blind = tmp_path / "bad_blind.json"
    bad_blind.write_text("[5343194, 9999991]\n", encoding="utf-8")

    env = {
        **os.environ,
        "PATH": f"{stub_bin}:{os.environ.get('PATH', '')}",
        "BLIND_SEEDS_FILE": str(bad_blind),
        "SEEDS_FILE": str(bad_blind),
        "GEMINI_API_KEY": "dummy_test_key",
    }
    help_probe = subprocess.run(
        ["bash", str(script), "--help"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=5.0,
    )
    help_txt = help_probe.stdout + help_probe.stderr
    script_uncommented = "\n".join(ln.split("#", 1)[0] for ln in script.read_text(encoding="utf-8").splitlines())
    cmd = ["bash", str(script)]
    if has_cli_flag(help_txt, "--blind-seeds") or re.search(r"(?<![\w-])--blind-seeds(?![\w-])", script_uncommented):
        cmd.extend(["--blind-seeds", str(bad_blind)])
    elif has_cli_flag(help_txt, "--seeds-file") or re.search(r"(?<![\w-])--seeds-file(?![\w-])", script_uncommented):
        cmd.extend(["--seeds-file", str(bad_blind)])

    res = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    assert not ssh_marker.exists(), "run_harbor_matrix.sh must never invoke ssh"
    assert not harbor_marker.exists(), "run_harbor_matrix.sh must reject overlapping blind seeds BEFORE harbor run"
    _assert_seed_disjointness_rejection(res)


def test_t2_f11_zero_hardcoded_api_keys_ssh_keys_or_secret_echo_across_repo():
    verda_dir = REPO_ROOT / "scripts" / "verda"
    assert verda_dir.is_dir() and len(list(verda_dir.iterdir())) >= 5

    assert scan_repo_for_secrets(REPO_ROOT) == []

    matrix_txt = (verda_dir / "run_harbor_matrix.sh").read_text(encoding="utf-8")
    assert "echo $OPENAI_API_KEY" not in matrix_txt
    assert "echo $GEMINI_API_KEY" not in matrix_txt


def test_t2_f11_sync_evidence_excludes_large_weights_and_enforces_local_cpu_verify():
    p = REPO_ROOT / "scripts" / "verda" / "sync_evidence.sh"
    assert p.is_file()
    txt = p.read_text(encoding="utf-8")
    assert "set -e" in txt
    assert "--verify-evidence" in txt
    assert any(tok in txt for tok in ("safetensors", "checkpoint-", "--exclude", "evidence/"))
    for pat in SECRET_PATTERNS:
        assert not pat.search(txt)


# ==============================================================================
# F12: Sacred 3D Export Pack Boundaries & Golden Traces — 6 Tests
# ==============================================================================


def test_t2_f12_export_events_empty_vs_populated_atomic_overwrite(world, tmp_path):
    validation = lazy_mod("validation")
    scenarios = lazy_mod("scenarios")
    engine = lazy_mod("engine")
    reporting = lazy_mod("reporting")

    plan = validation.parse_plan(v1_manual_plan(), world)
    day = scenarios.generate(world, 11)
    populated = engine.simulate(world, plan, day, trace=True)
    dest = tmp_path / "sub" / "events.jsonl"
    reporting.export_events(populated, dest)
    assert dest.stat().st_size > 0

    empty = replace(populated, events=())
    reporting.export_events(empty, dest)
    assert dest.read_bytes() == b""
    assert list(dest.parent.iterdir()) == [dest]


def test_t2_f12_compare_escapes_pipe_and_multiline_labels_and_handles_empty_metrics():
    Evaluation = lazy_attr("contracts", "Evaluation")
    reporting = lazy_mod("reporting")

    empty_msg = reporting.compare({})
    assert empty_msg and not CYRILLIC_RE.search(empty_msg)

    ev_bad = Evaluation(False, False, False, 0, 1, {}, ("bad|pipe\nreason",))
    out = reporting.compare({"plan|alpha\nv2": ev_bad, "stop|early": ev_bad})
    assert not CYRILLIC_RE.search(out)
    assert r"\|" in out
    assert "0/1" in out


def test_t2_f12_build_shift_manifest_custom_events_file_and_unstaffed_deadlock_shift(world):
    build_shift_manifest = lazy_attr("reporting", "build_shift_manifest")
    Plan = lazy_attr("contracts", "Plan")
    scenarios = lazy_mod("scenarios")
    engine = lazy_mod("engine")
    economics = lazy_mod("economics")

    deadlock_plan = Plan(1, True, False, "all", ((1,), (2,), (4,)))
    day = scenarios.generate(world, 11)
    raw = engine.simulate(world, deadlock_plan, day, trace=True)
    econ = economics.calculate(world, deadlock_plan, raw)

    manifest = build_shift_manifest(world, deadlock_plan, day, raw, econ, events_file="custom_trace.jsonl")
    assert manifest["events_file"] == "custom_trace.jsonl"
    assert manifest["raw"]["events"] == []
    assert manifest["raw"]["good"] == 0
    assert manifest["raw"]["unfinished"] == manifest["raw"]["total"]


def test_t2_f12_golden_manual_horizon_cutoff_27_vs_28_bundle_export(world, tmp_path):
    export_shift_bundle = lazy_attr("reporting", "export_shift_bundle")
    contracts = lazy_mod("contracts")
    engine = lazy_mod("engine")
    economics = lazy_mod("economics")

    plan = contracts.Plan(1, False, False, "manual", ((1, 2, 3, 4),))
    day = contracts.Scenario(1, 99, (contracts.Order(7, "regular", 0, 28),))

    for overtime, exp_good, exp_unfin, exp_labor in ((7, 0, 1, 27), (8, 1, 0, 28)):
        w_mod = copy.deepcopy(world)
        w_mod["clock"].update(shift_ticks=20, overtime_ticks=overtime, break_at=440, break_length=40)
        w_mod["prob_bps"]["defect_manual"]["regular"] = 0
        raw = engine.simulate(w_mod, plan, day, trace=True)
        econ = economics.calculate(w_mod, plan, raw)
        bdir = tmp_path / f"h_{20 + overtime}"
        export_shift_bundle(w_mod, plan, day, raw, econ, bdir)
        audited = audit_v1_shift_bundle(bdir)
        m_raw = audited["manifest"]["raw"]
        assert (m_raw["good"], m_raw["unfinished"], m_raw["labor_ticks"]) == (
            exp_good,
            exp_unfin,
            exp_labor,
        )


def test_t2_f12_golden_jam_break_assist_bundle_has_no_human_assist_finish(world, tmp_path):
    export_shift_bundle = lazy_attr("reporting", "export_shift_bundle")
    contracts = lazy_mod("contracts")
    engine = lazy_mod("engine")
    economics = lazy_mod("economics")

    w_mod = copy.deepcopy(world)
    w_mod["clock"].update(shift_ticks=12, overtime_ticks=20, break_at=12, break_length=5)
    w_mod["prob_bps"]["jam"]["tray"]["regular"] = 10_000
    w_mod["prob_bps"]["defect_auto"]["tray"]["regular"] = 0
    plan = contracts.Plan(1, True, True, "all", ((1, 2, 3, 4),))
    day = contracts.Scenario(1, 42, (contracts.Order(0, "regular", 0, 32),))
    raw = engine.simulate(w_mod, plan, day, trace=True)
    econ = economics.calculate(w_mod, plan, raw)

    bdir = tmp_path / "jam_bundle"
    export_shift_bundle(w_mod, plan, day, raw, econ, bdir)
    audited = audit_v1_shift_bundle(bdir)
    evs = audited["events"]
    assert [e["tick"] for e in evs if e["kind"] == "jam"] == [13]
    assert [(e["tick"], e["end_tick"]) for e in evs if e["kind"] == "break"] == [(12, 17)]
    assert [(e["tick"], e["end_tick"]) for e in evs if e["kind"] == "assist"] == [(17, 27)]
    assert not any(e["kind"] == "finish" and e["resource"] == "w0" and e["stage"] == 3 for e in evs)

    # E09 boundary overtime_ticks=15 (H=27, assist.end_tick == H): robot finishes & enqueues stage 4 at tick 27 without starting QC
    w_h27 = copy.deepcopy(w_mod)
    w_h27["clock"]["overtime_ticks"] = 15
    day_h27 = contracts.Scenario(1, 42, (contracts.Order(0, "regular", 0, 27),))
    raw_27 = engine.simulate(w_h27, plan, day_h27, trace=True)
    econ_27 = economics.calculate(w_h27, plan, raw_27)
    bdir_27 = tmp_path / "jam_bundle_h27"
    export_shift_bundle(w_h27, plan, day_h27, raw_27, econ_27, bdir_27)
    audited_27 = audit_v1_shift_bundle(bdir_27)
    evs_27 = audited_27["events"]
    assert [(e["tick"], e["end_tick"]) for e in evs_27 if e["kind"] == "assist"] == [(17, 27)]
    assert any(
        e["kind"] == "finish" and e["resource"] == "robot" and e["stage"] == 3 and e["tick"] == 27
        for e in evs_27
    )
    assert any(e["kind"] == "enqueue" and e["stage"] == 4 and e["tick"] == 27 for e in evs_27)
    assert not any(e["kind"] == "start" and e["stage"] == 4 for e in evs_27)
    assert (audited_27["manifest"]["raw"]["good"], audited_27["manifest"]["raw"]["unfinished"]) == (0, 1)


def test_t2_f12_export_3d_pack_rejects_unknown_flag_or_file_as_output_dir(run_cli, tmp_path):
    script = REPO_ROOT / "scripts" / "export_3d_pack.py"
    assert script.is_file(), f"Missing {script}"

    blocker = tmp_path / "blocker.txt"
    blocker.write_text("keep", encoding="utf-8")
    r1 = run_cli(["scripts/export_3d_pack.py", "--out", str(blocker)])
    assert r1.returncode != 0
    assert blocker.read_text(encoding="utf-8") == "keep"

    r2 = run_cli(["scripts/export_3d_pack.py", "--out", str(tmp_path / "ok"), "--seed", "not_an_int"])
    assert r2.returncode != 0


# ==============================================================================
# F13: CORS Server Security & Traversal Boundaries — 6 Tests
# ==============================================================================


def test_t2_f13_serve_3d_blocks_raw_dotdot_path_traversal(tmp_path):
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("OUTSIDE_SECRET_" + ("X" * 58), encoding="utf-8")
    secret_len = str(secret_file.stat().st_size)
    served = tmp_path / "pack"
    served.mkdir()
    (served / "index.json").write_text("{}", encoding="utf-8")

    with running_cors_server(served) as (host, port, _):
        for target in ("/../secret.txt", "/weeks/../../../secret.txt"):
            status, _, body = raw_http_request(host, port, "GET", target)
            assert status in (400, 403, 404)
            assert b"OUTSIDE_SECRET" not in body
            h_status, h_hdrs, h_body = raw_http_request(host, port, "HEAD", target)
            assert h_status in (400, 403, 404)
            assert h_body == b""
            assert h_hdrs.get("content-length") != secret_len


def test_t2_f13_serve_3d_blocks_url_encoded_dotdot_traversal(tmp_path):
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("OUTSIDE_SECRET_" + ("Y" * 58), encoding="utf-8")
    secret_len = str(secret_file.stat().st_size)
    served = tmp_path / "pack"
    served.mkdir()
    (served / "index.json").write_text("{}", encoding="utf-8")

    with running_cors_server(served) as (host, port, _):
        for target in (
            "/%2e%2e/secret.txt",
            "/%2E%2E/secret.txt",
            "/weeks/%2e%2e/%2e%2e/secret.txt",
            "/%2e%2e%2fsecret.txt",
        ):
            status, _, body = raw_http_request(host, port, "GET", target)
            assert status in (400, 403, 404)
            assert b"OUTSIDE_SECRET" not in body
            h_status, h_hdrs, h_body = raw_http_request(host, port, "HEAD", target)
            assert h_status in (400, 403, 404)
            assert h_body == b""
            assert h_hdrs.get("content-length") != secret_len


def test_t2_f13_serve_3d_blocks_symlink_escape_outside_served_root(tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text('{"secret": "SYMLINK_LEAK"}', encoding="utf-8")
    served = tmp_path / "pack"
    served.mkdir()
    (served / "leak.json").symlink_to(outside)

    with running_cors_server(served) as (host, port, _):
        status, _, body = raw_http_request(host, port, "GET", "/leak.json")
    assert status in (403, 404)
    assert b"SYMLINK_LEAK" not in body


def test_t2_f13_serve_3d_rejects_post_put_delete_on_readonly_server(tmp_path):
    served = tmp_path / "pack"
    served.mkdir()
    idx = served / "index.json"
    idx.write_text('{"ok": 1}', encoding="utf-8")

    with running_cors_server(served) as (host, port, _):
        for verb, path in (("POST", "/index.json"), ("PUT", "/pwn.json"), ("DELETE", "/index.json")):
            status, _, _ = raw_http_request(host, port, verb, path)
            assert status in (403, 405, 501)
    assert idx.read_text(encoding="utf-8") == '{"ok": 1}'
    assert not (served / "pwn.json").exists()


def test_t2_f13_serve_3d_missing_file_returns_404_with_cors_header(tmp_path):
    served = tmp_path / "pack"
    served.mkdir()
    with running_cors_server(served) as (host, port, _):
        status, hdrs, _ = raw_http_request(host, port, "GET", "/missing_shift/manifest.json")
    assert status == 404
    assert hdrs.get("access-control-allow-origin") == "*"


def test_t2_f13_serve_3d_strips_query_string_and_blocks_backslash_escape(tmp_path):
    (tmp_path / "secret.txt").write_text("OUTSIDE_SECRET", encoding="utf-8")
    served = tmp_path / "pack"
    served.mkdir()
    (served / "index.json").write_text('{"v": 1}', encoding="utf-8")

    with running_cors_server(served) as (host, port, _):
        s_ok, _, b_ok = raw_http_request(host, port, "GET", "/index.json?cacheBust=42")
        s_bad, _, b_bad = raw_http_request(host, port, "GET", "/..%5csecret.txt")
    assert s_ok == 200 and json.loads(b_ok.decode("utf-8")) == {"v": 1}
    assert s_bad in (400, 403, 404) and b"OUTSIDE_SECRET" not in b_bad


# ==============================================================================
# F14: 15-Minute Judge Exploit Probes (E01..E08) — 6 Tests
# ==============================================================================


def test_t2_f14_e01_complete_jam_deadlock_and_zero_good_positive_rational_floor(world):
    evaluate_quarterly = lazy_attr("grading", "evaluate_quarterly")
    seeds = world["development_seeds"]

    starved = {
        "schema_version": 2,
        "weeks": [make_week(robot=False, trays=False, route="manual", workers=[[2]]) for _ in range(12)],
    }
    ev_starved = evaluate_quarterly(world, starved, seeds)
    assert ev_starved.valid is True and ev_starved.feasible is False and ev_starved.win is False
    assert Fraction(ev_starved.reward_num, ev_starved.reward_den) == Fraction(1, 10_000)

    ev_dead = evaluate_quarterly(world, v2_unstaffed_jam_deadlock(), seeds)
    assert ev_dead.valid is True and ev_dead.feasible is False and ev_dead.win is False
    assert Fraction(1, 10_000) <= Fraction(ev_dead.reward_num, ev_dead.reward_den) <= Fraction(9, 100)


def test_t2_f14_e03_e04_fake_automation_buy_capex_idle_and_week11_token_lose_to_manual(
    world, replay_seeds
):
    evaluate_quarterly = lazy_attr("grading", "evaluate_quarterly")
    selloff = v2_manual_quarterly(world)
    selloff["weeks"][0] = make_week(robot=True, trays=False, route="bypass")
    selloff["weeks"][1] = make_week(robot=False, trays=False, route="manual")

    for pool in (world["development_seeds"], replay_seeds):
        ev_sell = evaluate_quarterly(world, selloff, pool)
        assert ev_sell.valid is False and (ev_sell.reward_num, ev_sell.reward_den) == (0, 1)

        ev_idle = evaluate_quarterly(world, v2_buy_capex_idle(world), pool)
        assert ev_idle.valid is True and ev_idle.feasible is True and ev_idle.win is False
        assert "automation" in ev_idle.reasons
        assert Fraction(1, 10) < Fraction(ev_idle.reward_num, ev_idle.reward_den) < Fraction(1, 5)

        ev_tok = evaluate_quarterly(world, v2_week11_token(world), pool)
        assert ev_tok.valid is True and ev_tok.feasible is True and ev_tok.win is False
        assert "automation" in ev_tok.reasons
        assert Fraction(1, 10) < Fraction(ev_tok.reward_num, ev_tok.reward_den) <= Fraction(1, 5)


def test_t2_f14_partial_horizon_0_1_11_13_weeks_and_illegal_week_combos_score_zero(world):
    evaluate_quarterly = lazy_attr("grading", "evaluate_quarterly")
    seeds = world["development_seeds"]

    bad_plans = [
        {"schema_version": 2, "weeks": [make_week() for _ in range(n)]}
        for n in (0, 1, 11, 13)
    ]
    m_no_robot = v2_manual_quarterly(world)
    m_no_robot["weeks"][5]["maintenance"] = True
    bad_plans.append(m_no_robot)

    r_no_robot = v2_manual_quarterly(world)
    r_no_robot["weeks"][3]["route"] = "bypass"
    bad_plans.append(r_no_robot)

    for bp in bad_plans:
        ev = evaluate_quarterly(world, bp, seeds)
        assert (ev.valid, ev.feasible, ev.win, ev.reward_num, ev.reward_den) == (False, False, False, 0, 1)


def test_t2_f14_e07_json_parser_attacks_dup_keys_nan_inf_bool_as_int_and_extra_fields(world, tmp_path):
    verify_quarterly_file = lazy_attr("verifier", "verify_quarterly_file")
    seeds = world["development_seeds"]
    valid_week_json = json.dumps(make_week())
    weeks_12_json = "[" + ",".join([valid_week_json] * 12) + "]"

    bad_week_dup = '{"robot": false, "robot": true, "trays": false, "route": "manual", "maintenance": false, "workers": [[1]]}'
    raw_attacks = [
        f'{{"schema_version": 2, "schema_version": 2, "weeks": {weeks_12_json}}}',
        f'{{"schema_version": 2, "weeks": [{bad_week_dup}, ' + ",".join([valid_week_json] * 11) + "]}",
        '{"schema_version": NaN, "weeks": []}',
        '{"schema_version": Infinity, "weeks": []}',
        '{"schema_version": -Infinity, "weeks": []}',
        f'{{"schema_version": true, "weeks": {weeks_12_json}}}',
        f'{{"schema_version": 2, "reward_num": 1, "weeks": {weeks_12_json}}}',
    ]
    bool_zone = v2_manual_quarterly(world)
    bool_zone["weeks"][0]["workers"] = [[True]]
    raw_attacks.append(json.dumps(bool_zone))

    for idx, payload in enumerate(raw_attacks):
        p = tmp_path / f"attack_{idx}.json"
        p.write_text(payload, encoding="utf-8")
        ev = verify_quarterly_file(world, p, seeds)
        assert ev.valid is False and (ev.reward_num, ev.reward_den) == (0, 1) and ev.metrics == {}


def test_t2_f14_e08_verifier_filesystem_attacks_symlink_fifo_dir_and_16384_byte_bva(world, tmp_path):
    verify_quarterly_file = lazy_attr("verifier", "verify_quarterly_file")
    seeds = world["development_seeds"]

    sym = tmp_path / "sym_replay.json"
    sym.symlink_to(REPO_ROOT / "evidence" / "replay_seeds.json")
    fifo = tmp_path / "fifo_attack.json"
    os.mkfifo(fifo)
    sub_dir = tmp_path / "dir_attack"
    sub_dir.mkdir()

    compact = json.dumps(v2_manual_quarterly(world), separators=(",", ":")).encode("utf-8")
    p_16384 = tmp_path / "bva_16384.json"
    p_16384.write_bytes(compact + b" " * (16_384 - len(compact)))
    p_16385 = tmp_path / "bva_16385.json"
    p_16385.write_bytes(compact + b" " * (16_385 - len(compact)))

    for bad in (sym, fifo, sub_dir, p_16385):
        ev = verify_quarterly_file(world, bad, seeds)
        assert ev.valid is False and (ev.reward_num, ev.reward_den) == (0, 1)

    ev_ok = verify_quarterly_file(world, p_16384, seeds)
    assert ev_ok.valid is True and Fraction(ev_ok.reward_num, ev_ok.reward_den) == Fraction(1, 5)


def test_t2_f14_e02_coupled_carryover_and_unmaintained_all_route_wear_degradation(world):
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    simulate_quarter = lazy_attr("quarterly", "simulate_quarter")
    evaluate_quarterly = lazy_attr("grading", "evaluate_quarterly")

    congested = v2_understaffed_carryover_plan()
    qr = simulate_quarter(world, parse_quarterly_plan(congested, world), 11, trace=True)
    assert any(w.carryover_in > 0 for w in qr.weeks[1:])

    async def _audit(session):
        return extract_mcp_payload(
            await session.call_tool("audit_3d_replay_trace", {"plan": congested, "seed": 11})
        )

    res = run_mcp_session([str(REPO_ROOT / ".agents" / "mcp" / "devtools_mcp.py")], _audit)
    assert res["ok"] is True

    win_plan, ev_win = best_phased_win_plan(world, world["development_seeds"])
    ev_unmaint = evaluate_quarterly(world, v2_naive_all_unmaintained(), world["development_seeds"])
    assert Fraction(ev_unmaint.reward_num, ev_unmaint.reward_den) < Fraction(
        ev_win.reward_num, ev_win.reward_den
    )


# ==============================================================================
# F15: Benchmark Evidence Tamper & Contamination Boundaries — 6 Tests
# ==============================================================================


def _clone_evidence_v2(tmp_path: Path, name: str = "ev_copy") -> Path:
    src = REPO_ROOT / "evidence" / "benchmark-v2"
    assert src.is_dir(), f"Missing {src}"
    dst = tmp_path / name
    shutil.copytree(src, dst)
    return dst


def test_t2_f15_verify_evidence_rejects_tampered_reward_txt(run_cli, tmp_path):
    ev_copy = _clone_evidence_v2(tmp_path, "tamper_rw")
    rw_files = sorted(ev_copy.rglob("reward.txt"))
    assert rw_files, "Expected at least one reward.txt in evidence/benchmark-v2"
    rw_files[0].write_text("0.999999\n", encoding="utf-8")

    res = run_cli(["scripts/run_bench.py", "--verify-evidence", str(ev_copy)])
    assert res.returncode != 0


def test_t2_f15_verify_evidence_rejects_tampered_blind_seeds_sha256(run_cli, tmp_path):
    ev_copy = _clone_evidence_v2(tmp_path, "tamper_seeds")
    bs_path = next(ev_copy.rglob("blind_seeds.json"))
    seeds = json.loads(bs_path.read_text(encoding="utf-8"))
    seeds[0] = seeds[0] + 1
    bs_path.write_text(json.dumps(seeds) + "\n", encoding="utf-8")

    res = run_cli(["scripts/run_bench.py", "--verify-evidence", str(ev_copy)])
    assert res.returncode != 0


def test_t2_f15_verify_evidence_rejects_blind_seeds_overlapping_dev_or_replay(run_cli, tmp_path):
    import hashlib

    for idx, bad_seed in enumerate((11, 5343194)):
        ev_copy = _clone_evidence_v2(tmp_path, f"overlap_{idx}")
        bs_path = next(ev_copy.rglob("blind_seeds.json"))
        old_hex = hashlib.sha256(bs_path.read_bytes()).hexdigest()
        seeds = json.loads(bs_path.read_text(encoding="utf-8"))
        seeds[0] = bad_seed
        bs_path.write_text(json.dumps(seeds) + "\n", encoding="utf-8")
        new_hex = hashlib.sha256(bs_path.read_bytes()).hexdigest()
        for jf in ev_copy.rglob("*.json"):
            if jf != bs_path:
                jf.write_text(jf.read_text(encoding="utf-8").replace(old_hex, new_hex), encoding="utf-8")

        res = run_cli(["scripts/run_bench.py", "--verify-evidence", str(ev_copy)])
        assert res.returncode != 0


def test_t2_f15_verify_evidence_rejects_mutated_submission_plan(run_cli, world, tmp_path):
    ev_copy = _clone_evidence_v2(tmp_path, "tamper_sub")
    subs = [
        p
        for p in sorted(ev_copy.rglob("submission.json"))
        if any(k in p.as_posix().lower() for k in ("oracle", "reference", "post", "grpo"))
    ]
    assert subs, "Expected winning oracle/post-RL submission.json in evidence/benchmark-v2"
    subs[0].write_text(json.dumps(v2_manual_quarterly(world)) + "\n", encoding="utf-8")

    res = run_cli(["scripts/run_bench.py", "--verify-evidence", str(ev_copy)])
    assert res.returncode != 0


def test_t2_f15_verify_evidence_rejects_missing_or_empty_directory(run_cli, tmp_path):
    help_res = run_cli(["scripts/run_bench.py", "--help"])
    assert "--verify-evidence" in (help_res.stdout + help_res.stderr)

    empty_dir = tmp_path / "empty_ev"
    empty_dir.mkdir()
    for target in (tmp_path / "nonexistent_ev", empty_dir):
        res = run_cli(["scripts/run_bench.py", "--verify-evidence", str(target)])
        assert res.returncode != 0
        assert len((res.stderr + res.stdout).strip()) > 0


def test_t2_f15_no_evidence_submission_exceeds_16kb_or_uses_dev_seeds(world):
    b_v2 = REPO_ROOT / "evidence" / "benchmark-v2"
    h_runs = REPO_ROOT / "evidence" / "harbor-runs"
    assert b_v2.is_dir() and h_runs.is_dir()

    for root_dir in (b_v2, h_runs):
        for sub in root_dir.rglob("submission.json"):
            assert not sub.is_symlink()
            st = sub.stat()
            assert stat.S_ISREG(st.st_mode)
            assert st.st_size <= 16_384

    bs = json.loads(next(b_v2.rglob("blind_seeds.json")).read_text(encoding="utf-8"))
    assert set(bs).isdisjoint(set(world["development_seeds"]))


# ==============================================================================
# F16: Packaging, CLI Collision & Repo Hygiene Boundaries — 6 Tests
# ==============================================================================


def test_t2_f16_python_specifier_accepts_all_312x_and_excludes_311_and_313():
    proj = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    spec = proj["project"]["requires-python"]
    for ok_ver in ("3.12.0", "3.12.8", "3.12.13", "3.12.14"):
        assert python_specifier_allows(spec, ok_ver) is True, f"{spec} rejected {ok_ver}"
    for bad_ver in ("3.11.9", "3.13.0", "3.13.1"):
        assert python_specifier_allows(spec, bad_ver) is False, f"{spec} accepted {bad_ver}"


def test_t2_f16_run_bench_rejects_overlapping_duplicate_and_boolean_seeds(run_cli, tmp_path):
    help_res = run_cli(["scripts/run_bench.py", "--help"])
    assert "--verify-evidence" in (help_res.stdout + help_res.stderr)

    for idx, raw in enumerate(("[11, 9001]", "[500, 500]", "[true, 501]", "[]")):
        sf = tmp_path / f"bad_s_{idx}.json"
        sf.write_text(raw, encoding="utf-8")
        res = run_cli(["scripts/run_bench.py", "--seeds-file", str(sf), "--out", str(tmp_path / f"o_{idx}")])
        assert res.returncode != 0
        assert len((res.stderr + res.stdout).strip()) > 0


def test_t2_f16_run_bench_rejects_plan_or_seeds_colliding_with_output_files(run_cli, world, tmp_path):
    help_res = run_cli(["scripts/run_bench.py", "--help"])
    assert "--verify-evidence" in (help_res.stdout + help_res.stderr)

    colliding = tmp_path / "submission.json"
    original = json.dumps(v2_manual_quarterly(world))
    colliding.write_text(original, encoding="utf-8")

    res = run_cli(["scripts/run_bench.py", "--out", str(tmp_path), "--plan", str(colliding)])
    assert res.returncode != 0
    assert colliding.read_text(encoding="utf-8") == original


def test_t2_f16_run_bench_rejects_symlink_in_output_targets(run_cli, tmp_path):
    help_res = run_cli(["scripts/run_bench.py", "--help"])
    assert "--verify-evidence" in (help_res.stdout + help_res.stderr)

    victim = tmp_path / "victim.json"
    victim.write_text("SAFE", encoding="utf-8")
    out = tmp_path / "out_sym"
    out.mkdir()
    (out / "results.json").symlink_to(victim)

    res = run_cli(["scripts/run_bench.py", "--out", str(out)])
    assert res.returncode != 0
    assert victim.read_text(encoding="utf-8") == "SAFE"


def test_t2_f16_run_bench_grades_invalid_external_plan_as_zero_without_crashing(run_cli, tmp_path):
    bad_plan = tmp_path / "bad_plan.json"
    bad_plan.write_text('{"schema_version": 2, "weeks": []}\n', encoding="utf-8")
    out = tmp_path / "out_bad"

    res = run_cli(["scripts/run_bench.py", "--plan", str(bad_plan), "--out", str(out)], timeout=25.0)
    assert res.returncode == 0, res.stderr
    results = json.loads((out / "results.json").read_text(encoding="utf-8"))
    sub_ev = results["results"]["submitted"]
    assert sub_ev["valid"] is False
    assert (sub_ev["reward_num"], sub_ev["reward_den"]) == (0, 1)
    assert not CYRILLIC_RE.search((out / "comparison.md").read_text(encoding="utf-8"))


def test_t2_f16_repository_hygiene_no_tracked_secrets_venv_or_teamwork_metadata():
    ls_res = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    tracked = [ln.strip() for ln in ls_res.stdout.splitlines() if ln.strip()]
    for rel in tracked:
        assert not rel.startswith(".agents/teamwork/"), f"Forbidden teamwork metadata in git: {rel}"
        assert not rel.startswith(".venv/"), f"Forbidden .venv file in git: {rel}"
        assert rel != ".env" and not rel.endswith((".pem", ".key", "id_rsa", "id_ed25519"))

    assert scan_repo_for_secrets(REPO_ROOT) == []
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert not CYRILLIC_RE.search(readme)
