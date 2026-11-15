"""Tier 1: Isolated happy-path feature coverage across F01..F16 (>= 5 tests per feature)."""

from __future__ import annotations

import ast
from collections.abc import Mapping
import copy
from dataclasses import asdict, fields, is_dataclass, replace
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import tomllib

import pytest

from .conftest import (
    CLI_COUNT_FLAGS,
    CLI_OUTPUT_FLAGS,
    CYRILLIC_RE,
    ECONOMY_COST_KEYS_V1,
    EVENT_KEYS_V1,
    EVENT_KINDS_V1,
    FORBIDDEN_PUBLIC_FILENAMES,
    MANUAL_WORKERS,
    PYTHON_BIN,
    REPO_ROOT,
    SECRET_PATTERNS,
    audit_v1_shift_bundle,
    best_phased_win_plan,
    discover_benchmark_v2_bundle,
    extract_eval_dict,
    extract_index_ids,
    extract_mcp_payload,
    has_cli_flag,
    lazy_attr,
    lazy_mod,
    make_socket_client,
    make_week,
    mcp_proxy_cli_args,
    pick_cli_flag,
    raw_http_request,
    run_mcp_session,
    run_staged_grade,
    run_staged_oracle,
    running_bench_daemon,
    running_cors_server,
    scan_repo_for_secrets,
    send_unix_jsonl,
    v1_manual_plan,
    v2_manual_quarterly,
    v2_phased_win_candidates,
)


# ==============================================================================
# F01: Additive v2 Contracts (contracts.py) — 5 Tests
# ==============================================================================


def test_t1_f01_v1_contracts_and_draw_intact():
    contracts = lazy_mod("contracts")
    assert contracts.SCHEMA_VERSION == 1
    v1_types = (
        contracts.Plan,
        contracts.Order,
        contracts.Scenario,
        contracts.Event,
        contracts.RawReport,
        contracts.Economy,
        contracts.Evaluation,
    )
    for cls in v1_types:
        assert is_dataclass(cls)
        assert cls.__dataclass_params__.frozen is True

    expected = (
        int.from_bytes(hashlib.sha256(b'[11,0,3,0,"jam"]').digest()[:8], "big") % 10_000
    )
    assert contracts.draw(11, 0, 3, 0, "jam", 10_000) == expected


def test_t1_f01_v2_schema_const_and_budget_exc():
    q_ver = lazy_attr("contracts", "QUARTERLY_SCHEMA_VERSION")
    budget_exc = lazy_attr("contracts", "PilotBudgetExceeded")
    assert type(q_ver) is int and q_ver == 2
    assert issubclass(budget_exc, RuntimeError)
    inst = budget_exc("BudgetExceeded: pilot budget exhausted (24/24)")
    assert "24" in str(inst)


def test_t1_f01_week_plan_to_shift_plan():
    Plan = lazy_attr("contracts", "Plan")
    WeekPlan = lazy_attr("contracts", "WeekPlan")
    wp = WeekPlan(
        robot=True,
        trays=True,
        route="bypass",
        maintenance=True,
        workers=((1,), (2, 3), (3, 4)),
    )
    assert wp.__dataclass_params__.frozen is True
    sp = wp.to_shift_plan()
    assert sp == Plan(1, True, True, "bypass", ((1,), (2, 3), (3, 4)))


def test_t1_f01_quarterly_plan_dataclass():
    WeekPlan = lazy_attr("contracts", "WeekPlan")
    QuarterlyPlan = lazy_attr("contracts", "QuarterlyPlan")
    weeks = tuple(
        WeekPlan(False, False, "manual", False, ((1,), (2,), (3,), (4,)))
        for _ in range(12)
    )
    qp = QuarterlyPlan(schema_version=2, weeks=weeks)
    assert qp.__dataclass_params__.frozen is True
    assert qp.schema_version == 2
    assert len(qp.weeks) == 12
    serialized = json.loads(json.dumps(asdict(qp)))
    assert serialized["schema_version"] == 2
    assert len(serialized["weeks"]) == 12


def test_t1_f01_week_and_quarter_report_fields():
    contracts = lazy_mod("contracts")
    WeekReport = lazy_attr("contracts", "WeekReport")
    QuarterReport = lazy_attr("contracts", "QuarterReport")

    expected_week_fields = (
        "week",
        "label",
        "week_seed",
        "carryover_in",
        "carryover_out",
        "wear_start",
        "wear_end",
        "commissioning_active",
        "shift_plan",
        "scenario",
        "raw",
        "shift_economy",
        "week_economy",
    )
    expected_quarter_fields = (
        "schema_version",
        "seed",
        "purchase",
        "total_cost",
        "labor_ticks",
        "weeks",
    )
    assert tuple(f.name for f in fields(WeekReport)) == expected_week_fields
    assert tuple(f.name for f in fields(QuarterReport)) == expected_quarter_fields

    sp = contracts.Plan(1, False, False, "manual", ((1, 2, 3, 4),))
    sc = contracts.Scenario(1, 11, (contracts.Order(0, "regular", 0, 100),))
    raw = contracts.RawReport(1, 11, 1, 1, 1, 0, 0, 0, 1, 1, 0, 0, 0, 22, (0,), ())
    econ = contracts.Economy(0, {k: 0 for k in ECONOMY_COST_KEYS_V1}, 0)
    wr = WeekReport(0, "w0", 1100, 0, 0, 0, 0, False, sp, sc, raw, econ, econ)
    qr = QuarterReport(2, 11, 0, 0, 22, (wr,))
    assert asdict(qr)["weeks"][0]["label"] == "w0"


# ==============================================================================
# F02: Quarterly World Catalog (data/world_spec.json) — 5 Tests
# ==============================================================================


def test_t1_f02_v1_top_level_world_keys_intact(world):
    required_v1 = {
        "schema_version",
        "world_id",
        "clock",
        "capacity",
        "workers",
        "kinds",
        "time",
        "prob_bps",
        "money",
        "threshold_bps",
        "generator",
        "development_seeds",
    }
    assert required_v1.issubset(world.keys())
    assert world["schema_version"] == 1
    assert world["world_id"] == "cell-v1"
    assert world["development_seeds"] == [11, 29, 47]


def test_t1_f02_quarterly_top_level_metadata(world):
    assert "quarterly" in world, "Missing top-level 'quarterly' block in data/world_spec.json"
    q = world["quarterly"]
    assert q["schema_version"] == 2
    assert q["world_id"] == "cell-quarterly-v2"
    assert q["weeks"] == 12
    assert q["max_pilots"] == 24
    assert type(q["carryover_cap"]) is int and q["carryover_cap"] > 0


def test_t1_f02_commissioning_and_wear_catalog(world):
    assert "quarterly" in world
    comm = world["quarterly"]["commissioning"]
    wear = world["quarterly"]["wear"]
    assert comm["weeks"] == 2
    assert set(comm["jam_bonus_bps"].keys()) == {"bare", "tray"}
    assert set(comm["defect_bonus_bps"].keys()) == {"bare", "tray"}
    for key in (
        "per_week_bypass",
        "per_week_all",
        "fragile_oversize_all_bonus",
        "maintenance_reduction",
        "maintenance_auto_slowdown_ticks",
        "jam_bps_per_wear",
        "defect_bps_per_wear",
        "max_wear",
    ):
        assert key in wear and type(wear[key]) is int


def test_t1_f02_quarterly_money_and_thresholds(world):
    assert "quarterly" in world
    qmoney = world["quarterly"]["money"]
    qthresh = world["quarterly"]["threshold_bps"]
    for mkey in (
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
        assert mkey in qmoney and type(qmoney[mkey]) is int
    assert set(qthresh.keys()) == {
        "good_each_week",
        "good_pooled",
        "on_time_pooled",
        "escaped_each_week_max",
        "auto_pack_pooled_min",
    }


def test_t1_f02_week_profiles_twelve_weeks(world):
    assert "quarterly" in world
    profiles = world["quarterly"]["week_profiles"]
    assert isinstance(profiles, list) and len(profiles) == 12
    assert [p["week"] for p in profiles] == list(range(12))
    req_keys = {"week", "label", "waves", "orders_min", "regular_bps", "fragile_bps", "due_offset"}
    for prof in profiles:
        assert req_keys.issubset(prof.keys())
        assert isinstance(prof["label"], str) and prof["label"]


# ==============================================================================
# F03: Dual v1/v2 Strict Plan Validation (validation.py) — 5 Tests
# ==============================================================================


def test_t1_f03_v1_parse_and_decode_plan_compat(world):
    validation = lazy_mod("validation")
    InvalidPlan = lazy_attr("contracts", "InvalidPlan")
    v1_dict = v1_manual_plan()
    parsed = validation.parse_plan(v1_dict, world)
    decoded = validation.decode_plan(json.dumps(v1_dict), world)
    assert parsed == decoded
    assert parsed.schema_version == 1

    with pytest.raises(InvalidPlan):
        validation.parse_plan(v2_manual_quarterly(), world)


def test_t1_f03_parse_quarterly_manual_plan(world):
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    QuarterlyPlan = lazy_attr("contracts", "QuarterlyPlan")
    qp = parse_quarterly_plan(v2_manual_quarterly(), world)
    assert isinstance(qp, QuarterlyPlan)
    assert qp.schema_version == 2
    assert len(qp.weeks) == 12
    assert all(isinstance(w.workers, tuple) and not w.robot and w.route == "manual" for w in qp.weeks)


def test_t1_f03_decode_quarterly_phased_plan(world):
    decode_quarterly_plan = lazy_attr("validation", "decode_quarterly_plan")
    phased = v2_phased_win_candidates()[0]
    qp = decode_quarterly_plan(json.dumps(phased), world)
    assert qp.schema_version == 2
    assert len(qp.weeks) == 12
    assert any(w.maintenance and w.robot for w in qp.weeks)


def test_t1_f03_parse_any_plan_polymorphic(world):
    parse_any_plan = lazy_attr("validation", "parse_any_plan")
    Plan = lazy_attr("contracts", "Plan")
    QuarterlyPlan = lazy_attr("contracts", "QuarterlyPlan")

    p1 = parse_any_plan(v1_manual_plan(), world)
    p2 = parse_any_plan(v2_manual_quarterly(), world)
    assert isinstance(p1, Plan) and p1.schema_version == 1
    assert isinstance(p2, QuarterlyPlan) and p2.schema_version == 2


def test_t1_f03_decode_any_plan_polymorphic(world):
    decode_any_plan = lazy_attr("validation", "decode_any_plan")
    Plan = lazy_attr("contracts", "Plan")
    QuarterlyPlan = lazy_attr("contracts", "QuarterlyPlan")

    p1 = decode_any_plan(json.dumps(v1_manual_plan()), world)
    p2 = decode_any_plan(json.dumps(v2_phased_win_candidates()[0]), world)
    assert isinstance(p1, Plan) and p1.schema_version == 1
    assert isinstance(p2, QuarterlyPlan) and p2.schema_version == 2


# ==============================================================================
# F04: 12-Week Coupled Quarterly Simulator (quarterly.py) — 5 Tests
# ==============================================================================


def test_t1_f04_manual_quarterly_value_valid(world):
    manual_quarterly_value = lazy_attr("quarterly", "manual_quarterly_value")
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    val = manual_quarterly_value(world)
    qp = parse_quarterly_plan(val, world)
    assert qp.schema_version == 2
    assert len(qp.weeks) == 12
    assert all(not w.robot and not w.trays and w.route == "manual" and not w.maintenance for w in qp.weeks)


def test_t1_f04_generate_quarter_exogenous_12(world):
    gen_q = lazy_attr("quarterly", "generate_quarter_exogenous")
    s1 = gen_q(world, 11)
    s2 = gen_q(world, 11)
    assert s1 == s2
    assert isinstance(s1, tuple) and len(s1) == 12
    for sc in s1:
        assert sc.schema_version == 1
        assert len(sc.orders) > 0
        pairs = [(o.arrival, o.id) for o in sc.orders]
        assert pairs == sorted(pairs)


def test_t1_f04_build_week_world_modifiers(world):
    build_week_world = lazy_attr("quarterly", "build_week_world")
    snapshot = copy.deepcopy(world)
    mod_w = build_week_world(world, 0, commissioning=True, wear=4, maintenance=True)
    assert world == snapshot, "build_week_world must not mutate caller world dict"
    assert mod_w["prob_bps"]["jam"]["bare"]["regular"] > world["prob_bps"]["jam"]["bare"]["regular"]
    assert mod_w["prob_bps"]["defect_auto"]["bare"]["regular"] > world["prob_bps"]["defect_auto"]["bare"]["regular"]
    slowdown = world["quarterly"]["wear"]["maintenance_auto_slowdown_ticks"]
    assert mod_w["time"]["auto"]["tray"]["regular"] == world["time"]["auto"]["tray"]["regular"] + slowdown


def test_t1_f04_simulate_quarter_manual_determinism(world):
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    manual_quarterly_value = lazy_attr("quarterly", "manual_quarterly_value")
    simulate_quarter = lazy_attr("quarterly", "simulate_quarter")

    qp = parse_quarterly_plan(manual_quarterly_value(world), world)
    r1 = simulate_quarter(world, qp, 11, trace=False)
    r2 = simulate_quarter(world, qp, 11, trace=False)
    assert r1 == r2
    assert r1.schema_version == 2 and r1.seed == 11
    assert len(r1.weeks) == 12
    assert all(w.raw.events == () for w in r1.weeks)


def test_t1_f04_simulate_quarter_trace_v1_events(world):
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    simulate_quarter = lazy_attr("quarterly", "simulate_quarter")
    qp = parse_quarterly_plan(v2_phased_win_candidates()[0], world)
    qr = simulate_quarter(world, qp, 11, trace=True)
    horizon = world["clock"]["shift_ticks"] + world["clock"]["overtime_ticks"]
    for wr in qr.weeks:
        assert len(wr.raw.events) > 0
        for ev in wr.raw.events:
            assert 0 <= ev.tick <= horizon
            assert ev.kind in EVENT_KINDS_V1


# ==============================================================================
# F05: Quarterly Integer-Cent Economics (economics.py) — 5 Tests
# ==============================================================================


def test_t1_f05_v1_calculate_backward_compat(world, dev_scenarios):
    economics = lazy_mod("economics")
    validation = lazy_mod("validation")
    engine = lazy_mod("engine")

    p_manual = validation.parse_plan(v1_manual_plan(), world)
    raw = engine.simulate(world, p_manual, dev_scenarios[0])
    econ = economics.calculate(world, p_manual, raw)
    assert econ.purchase == 0
    assert set(econ.costs.keys()) == ECONOMY_COST_KEYS_V1
    assert econ.total == sum(econ.costs.values())


def test_t1_f05_calculate_week_manual_zero_friction(world, dev_scenarios):
    calculate_week = lazy_attr("economics", "calculate_week")
    WeekPlan = lazy_attr("contracts", "WeekPlan")
    engine = lazy_mod("engine")

    workers = tuple(tuple(z) for z in MANUAL_WORKERS)
    wp = WeekPlan(False, False, "manual", False, workers)
    raw = engine.simulate(world, wp.to_shift_plan(), dev_scenarios[0])
    shift_econ, week_econ = calculate_week(
        world,
        wp,
        workers,
        raw,
        carryover_out=0,
        owned_robot=False,
        owned_trays=False,
    )
    assert set(shift_econ.costs.keys()) == ECONOMY_COST_KEYS_V1
    assert week_econ.purchase == 0
    assert week_econ.costs["depreciation"] == 0
    assert week_econ.costs["service"] == 0
    assert week_econ.costs["maintenance"] == 0
    assert week_econ.costs["hiring_retraining"] == 0
    assert week_econ.total == sum(week_econ.costs.values())


def test_t1_f05_calculate_week_owned_automation_costs(world, dev_scenarios):
    calculate_week = lazy_attr("economics", "calculate_week")
    WeekPlan = lazy_attr("contracts", "WeekPlan")
    engine = lazy_mod("engine")

    qmoney = world["quarterly"]["money"]
    purchase = world["money"]["robot_purchase"] + world["money"]["tray_purchase"]
    dep_weeks = qmoney["depreciation_weeks"]
    q, rem = divmod(purchase, dep_weeks)
    expected_dep = q + (2 * rem >= dep_weeks)

    workers = ((1,), (2,), (3, 4), (2, 3), (4,))
    wp = WeekPlan(True, True, "bypass", True, workers)
    raw = engine.simulate(world, wp.to_shift_plan(), dev_scenarios[0])
    _, week_econ = calculate_week(
        world,
        wp,
        workers,
        raw,
        carryover_out=0,
        owned_robot=True,
        owned_trays=True,
    )
    assert all(type(v) is int for v in week_econ.costs.values())
    assert week_econ.costs["depreciation"] == expected_dep
    assert week_econ.costs["service"] == qmoney["robot_service_week"]
    assert week_econ.costs["maintenance"] == qmoney["maintenance_cost"]
    assert week_econ.total == sum(week_econ.costs.values())


def test_t1_f05_quarter_report_cost_aggregation(world):
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    simulate_quarter = lazy_attr("quarterly", "simulate_quarter")
    qp = parse_quarterly_plan(v2_phased_win_candidates()[0], world)
    qr = simulate_quarter(world, qp, 11, trace=False)
    expected_capex = world["money"]["robot_purchase"] + world["money"]["tray_purchase"]
    assert qr.purchase == expected_capex
    assert qr.total_cost == sum(w.week_economy.total for w in qr.weeks)
    assert qr.labor_ticks >= sum(w.raw.labor_ticks for w in qr.weeks)


def test_t1_f05_shift_economy_manifest_compat(world):
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    simulate_quarter = lazy_attr("quarterly", "simulate_quarter")
    qp = parse_quarterly_plan(v2_phased_win_candidates()[0], world)
    qr = simulate_quarter(world, qp, 11, trace=False)
    for wr in qr.weeks:
        assert set(wr.shift_economy.costs.keys()) == ECONOMY_COST_KEYS_V1
        assert wr.shift_economy.total == sum(wr.shift_economy.costs.values())


# ==============================================================================
# F06: Exact Fraction Evaluator & Verifier (grading.py, verifier.py) — 5 Tests
# ==============================================================================


def test_t1_f06_v1_evaluate_and_verify_file_compat(world, dev_scenarios):
    grading = lazy_mod("grading")
    verifier = lazy_mod("verifier")
    manual_path = REPO_ROOT / "data" / "plans" / "manual.json"
    ev1 = grading.evaluate(world, grading.manual_value(), dev_scenarios)
    ev2 = verifier.verify_file(world, manual_path, dev_scenarios)
    assert ev1 == ev2
    assert ev1.valid is True and ev1.feasible is True and ev1.win is False
    assert (ev1.reward_num, ev1.reward_den) == (1, 5)


def test_t1_f06_evaluate_quarterly_manual_one_fifth(world):
    evaluate_quarterly = lazy_attr("grading", "evaluate_quarterly")
    manual_quarterly_value = lazy_attr("quarterly", "manual_quarterly_value")
    ev = evaluate_quarterly(world, manual_quarterly_value(world), world["development_seeds"])
    assert ev.valid is True and ev.feasible is True and ev.win is False
    assert Fraction(ev.reward_num, ev.reward_den) == Fraction(1, 5)


def test_t1_f06_evaluate_quarterly_phased_win(world):
    _, ev = best_phased_win_plan(world, world["development_seeds"])
    assert ev.valid is True and ev.feasible is True and ev.win is True
    assert Fraction(ev.reward_num, ev.reward_den) >= Fraction(7, 20)


def test_t1_f06_evaluate_any_v1_and_v2_dispatch(world):
    evaluate_any = lazy_attr("grading", "evaluate_any")
    manual_quarterly_value = lazy_attr("quarterly", "manual_quarterly_value")
    ev1 = evaluate_any(world, v1_manual_plan(), world["development_seeds"])
    ev2 = evaluate_any(world, manual_quarterly_value(world), world["development_seeds"])
    assert ev1.valid and Fraction(ev1.reward_num, ev1.reward_den) == Fraction(1, 5)
    assert ev2.valid and Fraction(ev2.reward_num, ev2.reward_den) == Fraction(1, 5)


def test_t1_f06_verify_quarterly_file_valid(world, tmp_path):
    verify_quarterly_file = lazy_attr("verifier", "verify_quarterly_file")
    evaluate_quarterly = lazy_attr("grading", "evaluate_quarterly")
    manual_q = v2_manual_quarterly(world)
    sub = tmp_path / "submission.json"
    sub.write_text(json.dumps(manual_q, indent=2) + "\n", encoding="utf-8")
    ev_file = verify_quarterly_file(world, sub, world["development_seeds"])
    ev_mem = evaluate_quarterly(world, manual_q, world["development_seeds"])
    assert ev_file == ev_mem
    assert Fraction(ev_file.reward_num, ev_file.reward_den) == Fraction(1, 5)


def test_t1_f06_grade_quarters_matches_evaluate_quarterly(world):
    grade_quarters = lazy_attr("grading", "grade_quarters")
    evaluate_quarterly = lazy_attr("grading", "evaluate_quarterly")
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    simulate_quarter = lazy_attr("quarterly", "simulate_quarter")

    seeds = world["development_seeds"]
    base_qp = parse_quarterly_plan(v2_manual_quarterly(world), world)
    baseline_list = [simulate_quarter(world, base_qp, s, trace=False) for s in seeds]

    cand_dict, expected_ev = best_phased_win_plan(world, seeds)
    cand_qp = parse_quarterly_plan(cand_dict, world)
    cand_list = [simulate_quarter(world, cand_qp, s, trace=False) for s in seeds]

    ev_from_list = grade_quarters(world, cand_qp, cand_list, baseline_list)
    ev_from_tuple = grade_quarters(world, cand_qp, tuple(cand_list), tuple(baseline_list))
    assert ev_from_list == expected_ev
    assert ev_from_tuple == expected_ev
    assert ev_from_list == evaluate_quarterly(world, cand_dict, seeds)


# ==============================================================================
# F07: Bounded QuarterlyEpisode (episode.py) — 5 Tests
# ==============================================================================


def test_t1_f07_v1_episode_lifecycle_compat(world, dev_scenarios):
    Episode = lazy_attr("episode", "Episode")
    ep = Episode(world, dev_scenarios)
    obs = ep.observe()
    assert set(obs.keys()) >= {"world", "rules", "history", "manual"}
    p_res = ep.pilot(obs["manual"], 11, trace=False)
    assert p_res["raw"]["good"] > 0 and p_res["economy"]["total"] > 0
    s_res = ep.submit(obs["manual"])
    assert s_res == {"terminal": True, "plan": obs["manual"]}


def test_t1_f07_quarterly_episode_observe_schema(world):
    QuarterlyEpisode = lazy_attr("episode", "QuarterlyEpisode")
    ep = QuarterlyEpisode(world)
    obs = ep.observe()
    assert obs["schema_version"] == 2
    assert "world" in obs and isinstance(obs["world"], Mapping)
    assert "rules" in obs and isinstance(obs["rules"], str) and len(obs["rules"].strip()) > 0
    assert obs["development_seeds"] == [11, 29, 47]
    assert obs["pilot_budget"] == {"used": 0, "max": world["quarterly"]["max_pilots"]}
    assert isinstance(obs["history"], list) and len(obs["history"]) == 3
    assert obs["manual"]["schema_version"] == 2


def test_t1_f07_quarterly_episode_pilot_execution(world):
    QuarterlyEpisode = lazy_attr("episode", "QuarterlyEpisode")
    ep = QuarterlyEpisode(world)
    obs = ep.observe()
    res = ep.pilot(obs["manual"], 11, trace=False)
    assert res["schema_version"] == 2
    assert res["seed"] == 11
    assert res["pilot_budget"]["used"] == 1
    assert len(res["weeks"]) == 12
    assert res["total_cost"] > 0


def test_t1_f07_quarterly_episode_submit_valid(world):
    QuarterlyEpisode = lazy_attr("episode", "QuarterlyEpisode")
    EpisodeClosed = lazy_attr("contracts", "EpisodeClosed")
    ep = QuarterlyEpisode(world)
    manual_q = v2_manual_quarterly(world)
    receipt = ep.submit(manual_q)
    assert receipt["terminal"] is True
    assert receipt["plan"] == manual_q
    with pytest.raises(EpisodeClosed):
        ep.observe()


def test_t1_f07_quarterly_episode_stop_terminal(world):
    QuarterlyEpisode = lazy_attr("episode", "QuarterlyEpisode")
    EpisodeClosed = lazy_attr("contracts", "EpisodeClosed")
    ep = QuarterlyEpisode(world)
    receipt = ep.stop()
    assert receipt == {"terminal": True, "plan": None}
    with pytest.raises(EpisodeClosed):
        ep.observe()


# ==============================================================================
# F08: Socket Daemon & Stateless MCP Proxy (mcp_server.py, mcp_proxy.py) — 6 Tests
# ==============================================================================


def test_t1_f08_mcp_tool_schema_contract_preserved(tmp_path):
    sub = tmp_path / "sub.json"
    log = tmp_path / "log.json"

    async def _check(session):
        listed = await session.list_tools()
        return listed.tools

    tools = run_mcp_session(
        ["-m", "robotization_bench.mcp_server", "--submission", str(sub), "--log", str(log)],
        _check,
    )
    by_name = {t.name: t for t in tools}
    assert set(by_name.keys()) == {"observe", "pilot", "submit", "stop"}
    assert by_name["pilot"].inputSchema["required"] == ["plan", "seed"]
    assert by_name["submit"].inputSchema.get("required", []) == []
    for t in tools:
        assert t.inputSchema.get("additionalProperties") is False


def test_t1_f08_mcp_stdio_default_quarterly_lifecycle(tmp_path):
    sub = tmp_path / "sub.json"
    log = tmp_path / "log.json"

    async def _ops(session):
        obs_r = await session.call_tool("observe", {})
        assert not obs_r.isError
        obs = extract_mcp_payload(obs_r)
        pil_r = await session.call_tool("pilot", {"plan": obs["manual"], "seed": 11, "trace": False})
        assert not pil_r.isError
        pil = extract_mcp_payload(pil_r)
        sub_r = await session.call_tool("submit", {"plan": obs["manual"]})
        assert not sub_r.isError
        return obs, pil, extract_mcp_payload(sub_r)

    obs, pil, receipt = run_mcp_session(
        [
            "-m",
            "robotization_bench.mcp_server",
            "--submission",
            str(sub),
            "--log",
            str(log),
            "--max-pilots",
            "6",
        ],
        _ops,
    )
    assert obs["schema_version"] == 2
    assert obs["pilot_budget"] == {"used": 0, "max": 6}
    assert pil["pilot_budget"]["used"] == 1 and len(pil["weeks"]) == 12
    assert receipt == {"terminal": True, "plan": obs["manual"]}
    assert json.loads(sub.read_text(encoding="utf-8")) == obs["manual"]


def test_t1_f08_mcp_stdio_v1_mode_backward_compat(tmp_path):
    sub = tmp_path / "sub.json"
    log = tmp_path / "log.json"

    async def _ops(session):
        obs = extract_mcp_payload(await session.call_tool("observe", {}))
        pil = extract_mcp_payload(await session.call_tool("pilot", {"plan": obs["manual"], "seed": 11}))
        rec = extract_mcp_payload(await session.call_tool("submit", {"plan": obs["manual"]}))
        return obs, pil, rec

    obs, pil, rec = run_mcp_session(
        [
            "-m",
            "robotization_bench.mcp_server",
            "--mode",
            "v1",
            "--submission",
            str(sub),
            "--log",
            str(log),
        ],
        _ops,
    )
    assert obs["manual"]["schema_version"] == 1
    assert pil["raw"]["good"] > 0 and pil["economy"]["total"] > 0
    assert rec["terminal"] is True and rec["plan"]["schema_version"] == 1


def test_t1_f08_daemon_unix_socket_jsonl_protocol(short_sock_dir, tmp_path):
    sock = short_sock_dir / "b.sock"
    state = tmp_path / "state.json"
    sub = tmp_path / "sub.json"
    log = tmp_path / "log.json"

    with running_bench_daemon(sock, state_path=state, sub_path=sub, log_path=log, max_pilots=8):
        r_obs = send_unix_jsonl(sock, {"action": "observe", "args": {}})
        assert r_obs["ok"] is True
        obs = r_obs["result"]
        assert obs["schema_version"] == 2

        r_pil = send_unix_jsonl(
            sock,
            {"action": "pilot", "args": {"plan": obs["manual"], "seed": 11, "trace": False}},
        )
        assert r_pil["ok"] is True
        assert r_pil["result"]["pilot_budget"]["used"] == 1
        assert state.is_file()

        r_sub = send_unix_jsonl(sock, {"action": "submit", "args": {"plan": obs["manual"]}})
        assert r_sub["ok"] is True
        assert json.loads(sub.read_text(encoding="utf-8")) == obs["manual"]


def test_t1_f08_socket_episode_client_and_mcp_proxy_stdio(short_sock_dir, tmp_path):
    sock = short_sock_dir / "p.sock"
    state = tmp_path / "state.json"
    sub = tmp_path / "sub.json"
    log = tmp_path / "log.json"

    with running_bench_daemon(sock, state_path=state, sub_path=sub, log_path=log, max_pilots=6):
        client = make_socket_client(sock)
        obs = client.observe()
        assert obs["pilot_budget"] == {"used": 0, "max": 6}
        p1 = client.pilot(obs["manual"], 11, trace=False)
        assert p1["pilot_budget"]["used"] == 1

        proxy_args, proxy_env = mcp_proxy_cli_args(sock)

        async def _proxy_ops(session):
            p2 = extract_mcp_payload(
                await session.call_tool("pilot", {"plan": obs["manual"], "seed": 29, "trace": False})
            )
            rec = extract_mcp_payload(await session.call_tool("submit", {"plan": obs["manual"]}))
            return p2, rec

        p2, rec = run_mcp_session(proxy_args, _proxy_ops, env_extra=proxy_env)
        assert p2["pilot_budget"]["used"] == 2
        assert rec == {"terminal": True, "plan": obs["manual"]}
        assert json.loads(sub.read_text(encoding="utf-8")) == obs["manual"]


def test_t1_f08_mcp_proxy_zero_simulator_imports():
    proxy_file = REPO_ROOT / "src" / "robotization_bench" / "mcp_proxy.py"
    assert proxy_file.is_file(), f"Missing {proxy_file}"
    tree = ast.parse(proxy_file.read_text(encoding="utf-8"))
    forbidden_mods = {
        "contracts",
        "engine",
        "quarterly",
        "scenarios",
        "economics",
        "grading",
        "validation",
        "episode",
        "reference",
        "verifier",
        "reporting",
        "mcp_server",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = set(alias.name.split("."))
                assert parts.isdisjoint(forbidden_mods), f"Forbidden import {alias.name} in mcp_proxy.py"
        elif isinstance(node, ast.ImportFrom):
            mod_parts = set((node.module or "").split("."))
            name_parts = {a.name for a in node.names}
            assert mod_parts.isdisjoint(forbidden_mods), f"Forbidden from-import {node.module} in mcp_proxy.py"
            assert name_parts.isdisjoint(forbidden_mods), f"Forbidden imported symbol {name_parts} in mcp_proxy.py"

    probe = subprocess.run(
        [
            str(PYTHON_BIN),
            "-I",
            "-B",
            "-c",
            "import json, sys; sys.path.insert(0, sys.argv[1]); import robotization_bench.mcp_proxy; "
            "print(json.dumps(sorted(m for m in sys.modules if m.startswith('robotization_bench.'))))",
            str(REPO_ROOT / "src"),
        ],
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    assert probe.returncode == 0, probe.stderr
    assert json.loads(probe.stdout.strip()) == ["robotization_bench.mcp_proxy"]


# ==============================================================================
# F09: Zero-Whitebox Harbor Packaging & Ready-to-Run Task — 7 Tests
# ==============================================================================


def _assert_public_allowlist(public_dir: Path) -> None:
    assert public_dir.is_dir(), f"Missing public directory {public_dir}"
    pkg_dir = public_dir / "src" / "robotization_bench"
    py_names = {p.name for p in pkg_dir.glob("*.py")}
    assert py_names == {"__init__.py", "mcp_proxy.py"}, f"Leaked modules in public/src: {py_names}"

    all_files = [p for p in public_dir.rglob("*") if p.is_file()]
    for fpath in all_files:
        low_name = fpath.name.lower()
        assert fpath.name not in FORBIDDEN_PUBLIC_FILENAMES, f"Forbidden file in public/: {fpath}"
        assert not ("seeds" in low_name and fpath.suffix.lower() == ".json"), (
            f"Leaked seeds JSON inside public/: {fpath}"
        )
        assert fpath.name not in ("candidate.json", ".env") and not fpath.name.startswith(".env."), (
            f"Forbidden plan/secret file in public/: {fpath}"
        )
        if fpath.suffix == ".py":
            assert fpath.parent == pkg_dir, f"Unexpected Python source in public/: {fpath}"

    rel_paths = {p.relative_to(public_dir).as_posix() for p in all_files}
    required = {
        "AGENT.md",
        "docs/SPEC.md",
        "docs/CONTRACTS.md",
        "data/development/11.json",
        "data/development/29.json",
        "data/development/47.json",
    }
    assert required.issubset(rel_paths), f"Missing core public files: {required - rel_paths}"


def _assert_dockerfile_privilege_hardening(dockerfile_path: Path) -> None:
    assert dockerfile_path.is_file(), f"Missing Dockerfile: {dockerfile_path}"
    raw_text = dockerfile_path.read_text(encoding="utf-8")
    # Strip shell/Dockerfile comments and join line continuations so RUN blocks parse cleanly
    stripped_lines = [ln.split("#", 1)[0].rstrip() for ln in raw_text.splitlines()]
    uncommented = re.sub(r"\\\n\s*", " ", "\n".join(stripped_lines))
    assert re.search(
        r"(?:chmod\s+(?:-[A-Za-z]+\s+)*0?700\s+[^\n]*/srv/bench_daemon|"
        r"(?:mkdir|install)\b[^\n]*(?:-m|--mode)[=\s]+0?700[^\n]*/srv/bench_daemon)",
        uncommented,
    ), "Dockerfile must set 0700 permissions on /srv/bench_daemon"
    assert re.search(
        r"(?:chmod\s+(?:-[A-Za-z]+\s+)*(?:0?4755|4711|u\+s)\s+[^\n]*bench-daemon-start|"
        r"install\b[^\n]*(?:-m|--mode)[=\s]+0?4755[^\n]*bench-daemon-start)",
        uncommented,
    ), "Dockerfile must set setuid (04755 / u+s) on bench-daemon-start"
    user_lines = [
        ln.strip().split()[1]
        for ln in stripped_lines
        if ln.strip().upper().startswith("USER ") and len(ln.strip().split()) >= 2
    ]
    assert user_lines and user_lines[-1] in ("agent", "1000", "agent:agent", "1000:1000")
    assert re.search(r"HOME\s*=?\s*['\"]?/home/agent['\"]?", uncommented), "Expected ENV HOME=/home/agent"
    assert re.search(r"\bcurl\b", uncommented), "Expected curl installed for Harbor OpenCode readiness"


def test_t1_f09_prepare_harbor_public_allowlist_zero_whitebox_leakage(run_cli, tmp_path):
    seeds = tmp_path / "seeds.json"
    seeds.write_text("[37281939, 91827364]\n", encoding="utf-8")
    out = tmp_path / "task"
    res = run_cli(["scripts/prepare_harbor.py", "--out", str(out), "--seeds-file", str(seeds)])
    assert res.returncode == 0, res.stderr
    _assert_public_allowlist(out / "environment" / "public")


def test_t1_f09_prepare_harbor_daemon_and_trusted_trees_staged_without_cross_leak(run_cli, tmp_path):
    seeds = tmp_path / "seeds.json"
    seeds.write_text("[37281939, 91827364]\n", encoding="utf-8")
    out = tmp_path / "task"
    res = run_cli(["scripts/prepare_harbor.py", "--out", str(out), "--seeds-file", str(seeds)])
    assert res.returncode == 0, res.stderr

    daemon_pkg = out / "environment" / "daemon" / "src" / "robotization_bench"
    assert daemon_pkg.is_dir(), "Missing environment/daemon/src/robotization_bench"
    required_daemon = {
        "mcp_server.py",
        "episode.py",
        "quarterly.py",
        "engine.py",
        "scenarios.py",
        "economics.py",
        "grading.py",
        "contracts.py",
        "validation.py",
    }
    assert required_daemon.issubset({p.name for p in daemon_pkg.glob("*.py")})
    daemon_all = {p.name for p in (out / "environment" / "daemon").rglob("*") if p.is_file()}
    assert "seeds.json" not in daemon_all
    assert "reference.py" not in daemon_all

    trusted_pkg = out / "tests" / "trusted" / "src" / "robotization_bench"
    assert {"quarterly.py", "verifier.py"}.issubset({p.name for p in trusted_pkg.glob("*.py")})
    assert json.loads((out / "tests" / "seeds.json").read_text(encoding="utf-8")) == [37281939, 91827364]
    assert (out / "solution" / "reference.py").is_file()


def test_t1_f09_prepare_harbor_overwrite_refreshes_existing_directory(run_cli, tmp_path):
    s1 = tmp_path / "s1.json"
    s2 = tmp_path / "s2.json"
    s1.write_text("[37281939]\n", encoding="utf-8")
    s2.write_text("[91827364]\n", encoding="utf-8")
    out = tmp_path / "task"

    r1 = run_cli(["scripts/prepare_harbor.py", "--out", str(out), "--seeds-file", str(s1)])
    assert r1.returncode == 0, r1.stderr
    marker = out / "stale_marker.txt"
    marker.write_text("stale", encoding="utf-8")

    r_no_flag = run_cli(["scripts/prepare_harbor.py", "--out", str(out), "--seeds-file", str(s2)])
    assert r_no_flag.returncode != 0

    r_overwrite = run_cli(
        ["scripts/prepare_harbor.py", "--out", str(out), "--seeds-file", str(s2), "--overwrite"]
    )
    assert r_overwrite.returncode == 0, r_overwrite.stderr
    assert json.loads((out / "tests" / "seeds.json").read_text(encoding="utf-8")) == [91827364]
    assert not marker.exists()


def test_t1_f09_dockerfile_privilege_separation_0700_setuid_and_user_agent(run_cli, tmp_path):
    seeds = tmp_path / "seeds.json"
    seeds.write_text("[37281939]\n", encoding="utf-8")
    out = tmp_path / "task"
    res = run_cli(["scripts/prepare_harbor.py", "--out", str(out), "--seeds-file", str(seeds)])
    assert res.returncode == 0, res.stderr
    _assert_dockerfile_privilege_hardening(out / "environment" / "Dockerfile")


def test_t1_f09_task_toml_airgap_and_mcp_proxy_config(run_cli, tmp_path):
    seeds = tmp_path / "seeds.json"
    seeds.write_text("[37281939]\n", encoding="utf-8")
    out = tmp_path / "task"
    res = run_cli(["scripts/prepare_harbor.py", "--out", str(out), "--seeds-file", str(seeds)])
    assert res.returncode == 0, res.stderr

    cfg = tomllib.loads((out / "task.toml").read_text(encoding="utf-8"))
    assert cfg["verifier"]["environment_mode"] == "separate"
    assert cfg["verifier"]["environment"]["network_mode"] == "no-network"
    mcp_srv = cfg["environment"]["mcp_servers"][0]
    assert mcp_srv["name"] == "cell"
    assert mcp_srv["transport"] == "stdio"
    assert any("mcp_proxy" in str(arg) for arg in mcp_srv["args"])
    test_sh = (out / "tests" / "test.sh").read_text(encoding="utf-8")
    assert "python" in test_sh and "-I" in test_sh and "grade.py" in test_sh


def test_t1_f09_staged_oracle_and_grade_py_socket_roundtrip(run_cli, short_sock_dir, tmp_path):
    seeds = tmp_path / "seeds.json"
    seeds.write_text("[474747]\n", encoding="utf-8")
    task = tmp_path / "task"
    res = run_cli(["scripts/prepare_harbor.py", "--out", str(task), "--seeds-file", str(seeds)])
    assert res.returncode == 0, res.stderr

    sock = short_sock_dir / "h.sock"
    state = tmp_path / "state.json"
    sub = tmp_path / "submission.json"
    log = tmp_path / "log.json"
    verdict = tmp_path / "verdict"

    with running_bench_daemon(
        sock,
        state_path=state,
        sub_path=sub,
        log_path=log,
        python_path=task / "environment" / "daemon" / "src",
    ):
        o_res = run_staged_oracle(task, sock, sub, log)
        assert o_res.returncode == 0, o_res.stderr

    assert sub.is_file()
    sub_obj = json.loads(sub.read_text(encoding="utf-8"))
    assert sub_obj["schema_version"] == 2

    payload = run_staged_grade(task, sub, verdict)
    ev = extract_eval_dict(payload)
    assert ev["valid"] is True and ev["feasible"] is True and ev["win"] is True
    frac = Fraction(ev["reward_num"], ev["reward_den"])
    assert frac >= Fraction(7, 20)
    reward_float = float((verdict / "reward.txt").read_text(encoding="utf-8").strip())
    assert reward_float == pytest.approx(float(frac))


def test_t1_f09_materialized_tasks_fulfillment_cell_bench_and_gitignore_hygiene():
    task_dir = REPO_ROOT / "tasks" / "fulfillment-cell-bench"
    assert task_dir.is_dir(), f"Missing ready-to-run materialized Harbor task at {task_dir}"
    for rel in (
        "instruction.md",
        "task.toml",
        "environment/Dockerfile",
        "environment/public",
        "environment/daemon",
        "solution",
        "tests",
    ):
        assert (task_dir / rel).exists(), f"Missing {rel} inside tasks/fulfillment-cell-bench"

    _assert_public_allowlist(task_dir / "environment" / "public")
    _assert_dockerfile_privilege_hardening(task_dir / "environment" / "Dockerfile")

    chk_task = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", "tasks/fulfillment-cell-bench"],
        capture_output=True,
    )
    assert chk_task.returncode != 0, "tasks/fulfillment-cell-bench MUST NOT be gitignored"

    chk_env = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", ".env"],
        capture_output=True,
    )
    assert chk_env.returncode == 0, ".env MUST be gitignored"


# ==============================================================================
# F10: Budget-Aware Phased Reference Optimizer (reference.py) — 5 Tests
# ==============================================================================


def test_t1_f10_solve_quarterly_episode_wins_within_20_pilots_on_dev_seeds(world):
    QuarterlyEpisode = lazy_attr("episode", "QuarterlyEpisode")
    solve = lazy_attr("reference", "solve")
    evaluate_quarterly = lazy_attr("grading", "evaluate_quarterly")

    ep = QuarterlyEpisode(world)
    plan = solve(ep)
    assert plan["schema_version"] == 2 and len(plan["weeks"]) == 12
    pilots_used = sum(1 for e in ep.log if e["action"] == "pilot")
    assert 1 <= pilots_used <= 20
    receipt = ep.submit(plan)
    assert receipt["plan"] == plan

    ev = evaluate_quarterly(world, plan, world["development_seeds"])
    assert ev.valid is True and ev.feasible is True and ev.win is True
    assert Fraction(ev.reward_num, ev.reward_den) >= Fraction(7, 20)


def test_t1_f10_solve_quarterly_generalizes_to_disjoint_replay_seeds(world, replay_seeds):
    QuarterlyEpisode = lazy_attr("episode", "QuarterlyEpisode")
    solve = lazy_attr("reference", "solve")
    evaluate_quarterly = lazy_attr("grading", "evaluate_quarterly")

    ep = QuarterlyEpisode(world)
    plan = solve(ep)
    ev = evaluate_quarterly(world, plan, replay_seeds)
    assert ev.valid is True and ev.feasible is True and ev.win is True
    assert Fraction(ev.reward_num, ev.reward_den) >= Fraction(7, 20)


def test_t1_f10_solve_v1_episode_backward_compatibility(world, dev_scenarios):
    Episode = lazy_attr("episode", "Episode")
    solve = lazy_attr("reference", "solve")
    evaluate = lazy_attr("grading", "evaluate")

    ep = Episode(world, dev_scenarios)
    plan = solve(ep)
    assert plan["schema_version"] == 1
    ev = evaluate(world, plan, dev_scenarios)
    assert ev.valid is True and ev.feasible is True and ev.win is True
    assert Fraction(ev.reward_num, ev.reward_den) > Fraction(1, 5)


def test_t1_f10_solve_duck_typed_over_socket_episode_client(world, short_sock_dir, tmp_path):
    solve = lazy_attr("reference", "solve")
    evaluate_quarterly = lazy_attr("grading", "evaluate_quarterly")

    sock = short_sock_dir / "ref.sock"
    state = tmp_path / "state.json"
    sub = tmp_path / "sub.json"
    log = tmp_path / "log.json"

    with running_bench_daemon(sock, state_path=state, sub_path=sub, log_path=log):
        client = make_socket_client(sock)
        plan = solve(client)
        rec = client.submit(plan)
        assert rec["plan"] == plan

    log_entries = json.loads(log.read_text(encoding="utf-8"))
    assert sum(1 for e in log_entries if e["action"] == "pilot") <= 20
    ev = evaluate_quarterly(world, plan, world["development_seeds"])
    assert ev.win is True


def test_t1_f10_reference_zero_simulator_and_grading_imports():
    ref_file = REPO_ROOT / "src" / "robotization_bench" / "reference.py"
    assert ref_file.is_file()
    tree = ast.parse(ref_file.read_text(encoding="utf-8"))
    forbidden = {"engine", "scenarios", "quarterly", "economics", "grading", "verifier"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert set(alias.name.split(".")).isdisjoint(forbidden)
        elif isinstance(node, ast.ImportFrom):
            assert set((node.module or "").split(".")).isdisjoint(forbidden)
            assert {a.name for a in node.names}.isdisjoint(forbidden)


# ==============================================================================
# F11: Verda Cloud & Qwen2.5-7B SFT/GRPO Scripts (scripts/verda/**) — 6 Tests
# ==============================================================================


def test_t1_f11_verda_five_scripts_exist_and_pass_syntax_compilation():
    import py_compile

    verda_dir = REPO_ROOT / "scripts" / "verda"
    sh_names = ("provision_check.sh", "run_harbor_matrix.sh", "sync_evidence.sh")
    py_names = ("generate_sft_traces.py", "train_grpo_qwen7b.py")
    for name in (*sh_names, *py_names):
        p = verda_dir / name
        assert p.is_file() and p.stat().st_size > 0, f"Missing or empty Verda script: {p}"

    for sh_name in sh_names:
        chk = subprocess.run(["bash", "-n", str(verda_dir / sh_name)], capture_output=True, text=True)
        assert chk.returncode == 0, chk.stderr

    for py_name in py_names:
        py_compile.compile(str(verda_dir / py_name), doraise=True)


def test_t1_f11_python_verda_scripts_support_cpu_cli_help_without_gpu_packages(run_cli):
    for script in ("scripts/verda/generate_sft_traces.py", "scripts/verda/train_grpo_qwen7b.py"):
        res = run_cli([script, "--help"], timeout=8.0)
        assert res.returncode == 0, f"{script} --help failed: {res.stderr}"
        assert "usage" in (res.stdout + res.stderr).lower()


def test_t1_f11_provision_check_enforces_deadman_shutdown_and_ops_guards():
    p = REPO_ROOT / "scripts" / "verda" / "provision_check.sh"
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "set -e" in text
    assert any(
        tok in text for tok in ("shutdown -h", "HF_HOME", "/tmp/fast-cache", "H200", "df -h", "save_total_limit")
    )
    assert "nvidia-smi" in text
    assert "docker" in text
    assert any(tok in text for tok in ("uv", "rl-venv", "python"))


def test_t1_f11_run_harbor_matrix_dynamic_frontier_model_selection_without_live_ssh():
    p = REPO_ROOT / "scripts" / "verda" / "run_harbor_matrix.sh"
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    uncommented = "\n".join(ln.split("#", 1)[0] for ln in text.splitlines())
    assert "FRONTIER_MODEL" in uncommented
    assert "GEMINI_API_KEY" in uncommented or "GOOGLE_GENERATIVE_AI_API_KEY" in uncommented
    assert "OPENAI_API_KEY" in uncommented
    assert "gemini/" in uncommented, "Expected gemini/ provider prefix on non-comment lines for Harbor 0.26.0"
    assert any(
        m in uncommented
        for m in (
            "gemini/gemini-4-carbon",
            "gemini/gemini-3.1-pro-preview",
            "gemini/gemini-3.8-flash",
            "gemini/gemini-2.5-pro",
        )
    ), "Expected default Gemini frontier model selector in run_harbor_matrix.sh"
    assert "openai/" in uncommented, "Expected openai/ provider prefix on non-comment lines"
    assert "verda-junction" not in uncommented
    assert not re.search(r"(?<![\w-])ssh\s+", uncommented)


def test_t1_f11_train_grpo_qwen7b_2xh100_pinning_checkpoint_limit_and_fraction_reward():
    p = REPO_ROOT / "scripts" / "verda" / "train_grpo_qwen7b.py"
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    low = text.lower()
    assert any(
        tok in low
        for tok in ("qwen3.5-9b", "qwen3-8b", "qwen2.5-7b", "qwen", "--model-id", "model_id", "h200_env_ready.json")
    )
    assert any(
        tok in low
        for tok in ("gpu_memory_utilization", "cuda:0", "h200", "cuda_visible_devices", "vllm", "bf16")
    )
    assert "save_total_limit" in text
    assert any(tok in text for tok in ("Fraction", "evaluate_quarterly", "grade_quarters"))


def test_t1_f11_generate_sft_traces_local_cpu_smoke_produces_disjoint_traces(
    run_cli, world, replay_seeds, tmp_path
):
    script = "scripts/verda/generate_sft_traces.py"
    help_res = run_cli([script, "--help"], timeout=8.0)
    assert help_res.returncode == 0, help_res.stderr
    help_txt = help_res.stdout + help_res.stderr

    out_file = tmp_path / "sft_smoke.jsonl"
    cmd = [script]
    out_flag = pick_cli_flag(help_txt, CLI_OUTPUT_FLAGS)
    assert out_flag is not None, f"Expected output CLI flag in {script} --help"
    cmd.extend([out_flag, str(out_file)])

    count_flag = pick_cli_flag(help_txt, CLI_COUNT_FLAGS)
    if count_flag is not None:
        cmd.extend([count_flag, "1"])

    res = run_cli(cmd, timeout=15.0)
    assert res.returncode == 0, f"generate_sft_traces.py failed: {res.stderr}"
    assert out_file.is_file() and out_file.stat().st_size > 0
    lines = [json.loads(ln) for ln in out_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) >= 1
    forbidden_seeds = set(world["development_seeds"]) | set(replay_seeds)
    for rec in lines:
        if "seed" in rec and isinstance(rec["seed"], int):
            assert rec["seed"] not in forbidden_seeds


# ==============================================================================
# F12: Sacred 3D Export Pack & Musa Handoff — 6 Tests
# ==============================================================================


def test_t1_f12_export_events_v1_compact_jsonl_exact_seven_keys(world, tmp_path):
    validation = lazy_mod("validation")
    scenarios = lazy_mod("scenarios")
    engine = lazy_mod("engine")
    reporting = lazy_mod("reporting")

    cand_raw = json.loads((REPO_ROOT / "data" / "plans" / "candidate.json").read_text(encoding="utf-8"))
    plan = validation.parse_plan(cand_raw, world)
    day = scenarios.generate(world, 11)
    raw = engine.simulate(world, plan, day, trace=True)
    dest = tmp_path / "events.jsonl"
    reporting.export_events(raw, dest)

    lines = dest.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(raw.events) > 0
    for ln, ev_dc in zip(lines, raw.events, strict=True):
        parsed = json.loads(ln)
        assert ln == json.dumps(parsed, separators=(",", ":"))
        assert tuple(parsed.keys()) == EVENT_KEYS_V1
        assert parsed["kind"] in EVENT_KINDS_V1
        assert parsed == asdict(ev_dc)


def test_t1_f12_compare_outputs_english_markdown_and_exact_fractions(world, dev_scenarios):
    grading = lazy_mod("grading")
    reporting = lazy_mod("reporting")

    ev_manual = grading.evaluate(world, grading.manual_value(), dev_scenarios)
    cand_raw = json.loads((REPO_ROOT / "data" / "plans" / "candidate.json").read_text(encoding="utf-8"))
    ev_cand = grading.evaluate(world, cand_raw, dev_scenarios)
    ev_inv = grading.invalid("missing submission")
    ev_tight = replace(ev_manual, reward_num=19_999, reward_den=100_000)

    out = reporting.compare(
        {
            "manual": ev_manual,
            "candidate": ev_cand,
            "tight_frac": ev_tight,
            "invalid_case": ev_inv,
        }
    )
    assert not CYRILLIC_RE.search(out), f"Cyrillic found in reporting.compare(): {out}"
    assert out.index("manual") < out.index("candidate") < out.index("tight_frac") < out.index("invalid_case")
    for frac_str in ("1/5", "19999/100000", "0/1"):
        assert frac_str in out
    assert "missing submission" in out


def test_t1_f12_build_shift_manifest_strips_inline_events_and_matches_musa_v1(world):
    build_shift_manifest = lazy_attr("reporting", "build_shift_manifest")
    validation = lazy_mod("validation")
    scenarios = lazy_mod("scenarios")
    engine = lazy_mod("engine")
    economics = lazy_mod("economics")

    cand_raw = json.loads((REPO_ROOT / "data" / "plans" / "candidate.json").read_text(encoding="utf-8"))
    plan = validation.parse_plan(cand_raw, world)
    day = scenarios.generate(world, 11)
    raw = engine.simulate(world, plan, day, trace=True)
    econ = economics.calculate(world, plan, raw)

    manifest = build_shift_manifest(world, plan, day, raw, econ)
    assert manifest["replay_format"] == "robotization-bench.replay.v1"
    assert manifest["events_file"] == "events.jsonl"
    assert manifest["raw"]["events"] == []
    assert len(raw.events) > 0
    assert set(manifest["economy"]["costs"].keys()) == ECONOMY_COST_KEYS_V1


def test_t1_f12_export_shift_bundle_writes_valid_manifest_and_events_jsonl(world, tmp_path):
    export_shift_bundle = lazy_attr("reporting", "export_shift_bundle")
    validation = lazy_mod("validation")
    scenarios = lazy_mod("scenarios")
    engine = lazy_mod("engine")
    economics = lazy_mod("economics")

    cand_raw = json.loads((REPO_ROOT / "data" / "plans" / "candidate.json").read_text(encoding="utf-8"))
    plan = validation.parse_plan(cand_raw, world)
    day = scenarios.generate(world, 11)
    raw = engine.simulate(world, plan, day, trace=True)
    econ = economics.calculate(world, plan, raw)

    out_dir = tmp_path / "shift_bundle"
    res = export_shift_bundle(world, plan, day, raw, econ, out_dir)
    assert isinstance(res, Path) and res.exists()
    audit_v1_shift_bundle(out_dir)


def test_t1_f12_export_quarter_pack_writes_twelve_v1_compatible_weeks(world, tmp_path):
    export_quarter_pack = lazy_attr("reporting", "export_quarter_pack")
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    simulate_quarter = lazy_attr("quarterly", "simulate_quarter")
    evaluate_quarterly = lazy_attr("grading", "evaluate_quarterly")

    manual_q = v2_manual_quarterly(world)
    qp = parse_quarterly_plan(manual_q, world)
    qr = simulate_quarter(world, qp, 11, trace=True)
    ev = evaluate_quarterly(world, manual_q, [11])

    out_dir = tmp_path / "qpack"
    export_quarter_pack(world, qr, qp, out_dir, evaluation=ev)
    qm = json.loads((out_dir / "quarter_manifest.json").read_text(encoding="utf-8"))
    assert (qm.get("seed") if "seed" in qm else qm.get("quarter", {}).get("seed")) == 11
    if "diagnostics" in qm:
        assert isinstance(qm["diagnostics"], (list, dict, str))
    if (out_dir / "diagnostics.md").is_file():
        assert not CYRILLIC_RE.search((out_dir / "diagnostics.md").read_text(encoding="utf-8"))
    for w in range(12):
        wk_dir = out_dir / "weeks" / f"week-{w:02d}"
        assert wk_dir.is_dir()
        audit_v1_shift_bundle(wk_dir)


def test_t1_f12_export_3d_pack_cli_and_musa_handoff_doc(run_cli, tmp_path):
    out_dir = tmp_path / "pack3d"
    res = run_cli(["scripts/export_3d_pack.py", "--out", str(out_dir), "--seed", "11"], timeout=20.0)
    assert res.returncode == 0, res.stderr
    assert (out_dir / "index.json").is_file()
    idx_doc = json.loads((out_dir / "index.json").read_text(encoding="utf-8"))
    core_ids = {
        "v1-manual-seed11",
        "v1-reference-seed11",
        "quarterly-manual-seed11",
        "quarterly-reference-seed11",
    }
    found_ids = extract_index_ids(idx_doc)
    assert len(found_ids) >= 4 and core_ids.issubset(found_ids)

    for v1_name in ("v1-manual-seed11", "v1-reference-seed11"):
        audit_v1_shift_bundle(out_dir / v1_name)
    for sub_d in sorted(out_dir.iterdir()):
        if sub_d.is_dir() and (sub_d / "weeks").is_dir():
            for w in range(12):
                audit_v1_shift_bundle(sub_d / "weeks" / f"week-{w:02d}")

    handoff_doc = REPO_ROOT / "docs" / "ru" / "3D_HANDOFF_MUSA.md"
    assert handoff_doc.is_file()
    doc_text = handoff_doc.read_text(encoding="utf-8")
    assert CYRILLIC_RE.search(doc_text)
    assert "robotization-bench.replay.v1" in doc_text
    assert "serve_3d.py" in doc_text


# ==============================================================================
# F13: Local Read-Only CORS Server (scripts/serve_3d.py) — 6 Tests
# ==============================================================================


def test_t1_f13_serve_3d_get_json_returns_200_cors_no_store_and_json_mime(tmp_path):
    payload = {"replay_format": "robotization-bench.replay.v1"}
    (tmp_path / "index.json").write_text(json.dumps(payload), encoding="utf-8")
    with running_cors_server(tmp_path) as (host, port, _):
        status, hdrs, body = raw_http_request(host, port, "GET", "/index.json")
    assert status == 200
    assert hdrs.get("access-control-allow-origin") == "*"
    assert "no-store" in hdrs.get("cache-control", "").lower()
    assert hdrs.get("content-type", "").lower().startswith("application/json")
    assert json.loads(body.decode("utf-8")) == payload


def test_t1_f13_serve_3d_get_jsonl_returns_exact_lines_and_ndjson_or_text_mime(world, tmp_path):
    validation = lazy_mod("validation")
    scenarios = lazy_mod("scenarios")
    engine = lazy_mod("engine")
    reporting = lazy_mod("reporting")

    plan = validation.parse_plan(v1_manual_plan(), world)
    raw = engine.simulate(world, plan, scenarios.generate(world, 11), trace=True)
    events_file = tmp_path / "shift" / "events.jsonl"
    reporting.export_events(raw, events_file)

    with running_cors_server(tmp_path) as (host, port, _):
        status, hdrs, body = raw_http_request(host, port, "GET", "/shift/events.jsonl")
    assert status == 200
    assert hdrs.get("access-control-allow-origin") == "*"
    assert "no-store" in hdrs.get("cache-control", "").lower()
    ctype = hdrs.get("content-type", "").lower()
    assert any(
        ctype.startswith(p)
        for p in ("application/x-ndjson", "application/jsonlines", "application/jsonl", "text/plain")
    )
    assert body == events_file.read_bytes()


def test_t1_f13_serve_3d_options_preflight_returns_204_with_cors_headers(tmp_path):
    (tmp_path / "index.json").write_text("{}", encoding="utf-8")
    with running_cors_server(tmp_path) as (host, port, _):
        status, hdrs, body = raw_http_request(
            host,
            port,
            "OPTIONS",
            "/index.json",
            headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
        )
    assert status == 204
    assert body == b""
    assert hdrs.get("access-control-allow-origin") == "*"
    allow_methods = hdrs.get("access-control-allow-methods", "").upper()
    for verb in ("GET", "HEAD", "OPTIONS"):
        assert verb in allow_methods


def test_t1_f13_serve_3d_head_returns_200_headers_and_empty_body(tmp_path):
    target = tmp_path / "index.json"
    target.write_text('{"ok": true}\n', encoding="utf-8")
    with running_cors_server(tmp_path) as (host, port, _):
        status, hdrs, body = raw_http_request(host, port, "HEAD", "/index.json")
    assert status == 200
    assert body == b""
    assert hdrs.get("access-control-allow-origin") == "*"
    assert "no-store" in hdrs.get("cache-control", "").lower()
    assert int(hdrs["content-length"]) == target.stat().st_size


def test_t1_f13_serve_3d_serves_nested_quarterly_week_bundles(tmp_path):
    wk_dir = tmp_path / "quarterly-reference-seed11" / "weeks" / "week-05"
    wk_dir.mkdir(parents=True)
    m_bytes = b'{"replay_format":"robotization-bench.replay.v1"}\n'
    e_bytes = b'{"tick":0,"kind":"arrival","order_id":0,"resource":null,"stage":1,"attempt":0,"end_tick":null}\n'
    (wk_dir / "manifest.json").write_bytes(m_bytes)
    (wk_dir / "events.jsonl").write_bytes(e_bytes)

    with running_cors_server(tmp_path) as (host, port, _):
        s1, h1, b1 = raw_http_request(host, port, "GET", "/quarterly-reference-seed11/weeks/week-05/manifest.json")
        s2, h2, b2 = raw_http_request(host, port, "GET", "/quarterly-reference-seed11/weeks/week-05/events.jsonl")
    assert s1 == 200 and h1.get("access-control-allow-origin") == "*" and b1 == m_bytes
    assert "no-store" in h1.get("cache-control", "").lower()
    assert s2 == 200 and h2.get("access-control-allow-origin") == "*" and b2 == e_bytes
    assert "no-store" in h2.get("cache-control", "").lower()


def test_t1_f13_serve_3d_ephemeral_port_clean_sigterm_shutdown(tmp_path):
    (tmp_path / "index.json").write_text("{}", encoding="utf-8")
    with running_cors_server(tmp_path) as (host, port, proc):
        status, _, _ = raw_http_request(host, port, "GET", "/index.json")
        assert status == 200
        t0 = time.monotonic()
        proc.terminate()
        proc.wait(timeout=3.0)
        elapsed = time.monotonic() - t0
    assert elapsed <= 3.0
    assert proc.returncode is not None


# ==============================================================================
# F14: 15-Minute Judge Exploit Hierarchy & Devtools MCP — 5 Tests
# ==============================================================================


def test_t1_f14_quarterly_exact_fraction_reward_hierarchy_ordering(world, tmp_path):
    from .conftest import v2_buy_capex_idle, v2_unstaffed_jam_deadlock, v2_week11_token

    verify_quarterly_file = lazy_attr("verifier", "verify_quarterly_file")
    seeds = world["development_seeds"]

    def _grade_obj(name: str, obj, write: bool = True) -> Fraction:
        p = tmp_path / f"{name}.json"
        if write:
            p.write_text(json.dumps(obj), encoding="utf-8")
        ev = verify_quarterly_file(world, p, seeds)
        return Fraction(ev.reward_num, ev.reward_den)

    r_nop = _grade_obj("nop", None, write=False)
    r_stop = _grade_obj("stop", None, write=True)
    r_partial = _grade_obj("partial", {"schema_version": 2, "weeks": [make_week() for _ in range(11)]})
    r_deadlock = _grade_obj("deadlock", v2_unstaffed_jam_deadlock())
    r_idle = _grade_obj("idle", v2_buy_capex_idle(world))
    r_w11 = _grade_obj("w11", v2_week11_token(world))
    r_manual = _grade_obj("manual", v2_manual_quarterly(world))
    win_plan, _ = best_phased_win_plan(world, seeds)
    r_win = _grade_obj("win", win_plan)

    assert Fraction(0, 1) == r_nop == r_stop == r_partial
    assert Fraction(1, 10_000) <= r_deadlock <= Fraction(9, 100)
    assert Fraction(1, 10) < r_idle < Fraction(1, 5)
    assert Fraction(1, 10) < r_w11 <= Fraction(1, 5)
    ev_w11 = verify_quarterly_file(world, tmp_path / "w11.json", seeds)
    assert ev_w11.win is False and "automation" in ev_w11.reasons
    assert r_manual == Fraction(1, 5)
    assert Fraction(7, 20) <= r_win < Fraction(1, 1)


def test_t1_f14_devtools_mcp_verify_plan_matrix_v2_and_v1(world):
    win_plan, _ = best_phased_win_plan(world, world["development_seeds"])
    manual_q = v2_manual_quarterly(world)

    async def _ops(session):
        r_m2 = extract_mcp_payload(
            await session.call_tool("verify_plan_matrix", {"plan": manual_q, "seeds_mode": "dev"})
        )
        r_w2 = extract_mcp_payload(
            await session.call_tool("verify_plan_matrix", {"plan": win_plan, "seeds_mode": "replay"})
        )
        r_m1 = extract_mcp_payload(
            await session.call_tool(
                "verify_plan_matrix", {"plan": v1_manual_plan(), "seeds_mode": "custom", "custom_seeds": [11]}
            )
        )
        return r_m2, r_w2, r_m1

    r_m2, r_w2, r_m1 = run_mcp_session([str(REPO_ROOT / ".agents" / "mcp" / "devtools_mcp.py")], _ops)
    assert r_m2["valid"] is True and (r_m2["reward_num"], r_m2["reward_den"]) == (1, 5)
    assert r_w2["valid"] is True and r_w2["win"] is True
    assert Fraction(r_w2["reward_num"], r_w2["reward_den"]) >= Fraction(7, 20)
    assert r_m1["valid"] is True and (r_m1["reward_num"], r_m1["reward_den"]) == (1, 5)


def test_t1_f14_devtools_mcp_audit_3d_replay_trace_v1_and_v2_quarter(world):
    v1_sub = json.loads((REPO_ROOT / "evidence" / "frozen-v1" / "submission.json").read_text(encoding="utf-8"))
    win_plan, _ = best_phased_win_plan(world, world["development_seeds"])

    async def _ops(session):
        a1 = extract_mcp_payload(
            await session.call_tool("audit_3d_replay_trace", {"plan": v1_sub, "seed": 11})
        )
        a2 = extract_mcp_payload(
            await session.call_tool("audit_3d_replay_trace", {"plan": win_plan, "seed": 11})
        )
        return a1, a2

    a1, a2 = run_mcp_session([str(REPO_ROOT / ".agents" / "mcp" / "devtools_mcp.py")], _ops)
    assert a1["ok"] is True and a1["event_count"] == 2388
    assert a2["ok"] is True


def test_t1_f14_devtools_mcp_redteam_reward_exploits_dev_and_replay():
    async def _ops(session):
        d = extract_mcp_payload(await session.call_tool("redteam_reward_exploits", {"seeds_mode": "dev"}))
        r = extract_mcp_payload(await session.call_tool("redteam_reward_exploits", {"seeds_mode": "replay"}))
        return d, r

    d, r = run_mcp_session([str(REPO_ROOT / ".agents" / "mcp" / "devtools_mcp.py")], _ops)
    for res in (d, r):
        assert res["hierarchy_intact"] is True
        assert res["exploits_beating_reference"] == []
        probes = res["probes"]
        deadlock_frac = Fraction(*map(int, probes["unstaffed_jam_deadlock"]["reward_fraction"].split("/")))
        manual_frac = Fraction(*map(int, probes["manual_baseline"]["reward_fraction"].split("/")))
        ref_frac = Fraction(*map(int, probes["reference_solver"]["reward_fraction"].split("/")))
        assert Fraction(0, 1) < deadlock_frac <= Fraction(9, 100)
        assert manual_frac == Fraction(1, 5)
        assert ref_frac >= Fraction(7, 20)


def _audit_3d_pack_root(pack_dir: Path) -> None:
    assert (pack_dir / "index.json").is_file()
    idx_doc = json.loads((pack_dir / "index.json").read_text(encoding="utf-8"))
    core_ids = {
        "v1-manual-seed11",
        "v1-reference-seed11",
        "quarterly-manual-seed11",
        "quarterly-reference-seed11",
    }
    found_ids = extract_index_ids(idx_doc)
    assert len(found_ids) >= 4 and core_ids.issubset(found_ids)
    for v1_name in ("v1-manual-seed11", "v1-reference-seed11"):
        audit_v1_shift_bundle(pack_dir / v1_name)
    for q_name in ("quarterly-manual-seed11", "quarterly-reference-seed11"):
        assert (pack_dir / q_name / "weeks").is_dir()
    for sub_d in sorted(pack_dir.iterdir()):
        if sub_d.is_dir() and (sub_d / "weeks").is_dir():
            for w in range(12):
                audit_v1_shift_bundle(sub_d / "weeks" / f"week-{w:02d}")


def test_t1_f14_artifacts_3d_pack_presence_and_replay_trace_integrity(run_cli, tmp_path):
    repo_pack = REPO_ROOT / "artifacts" / "3d-pack"
    if repo_pack.is_dir():
        _audit_3d_pack_root(repo_pack)
    else:
        gen_pack = tmp_path / "3d-pack"
        res = run_cli(["scripts/export_3d_pack.py", "--out", str(gen_pack), "--seed", "11"], timeout=25.0)
        assert res.returncode == 0, f"export_3d_pack.py failed: {res.stderr}"
        _audit_3d_pack_root(gen_pack)


# ==============================================================================
# F15: Live Verda Harbor, harbor-runs & 7B SFT/GRPO Evidence — 6 Tests
# ==============================================================================


def _score_evidence_record(
    world: dict, rec: dict, seeds: list[int], *, allow_missing_sub: bool = False
) -> Fraction:
    verify_quarterly_file = lazy_attr("verifier", "verify_quarterly_file")
    sub_path = rec.get("submission_path")
    if sub_path is not None and sub_path.is_file():
        ev = verify_quarterly_file(world, sub_path, seeds)
        score = Fraction(ev.reward_num, ev.reward_den)
        if rec.get("reward_path") is not None and rec["reward_path"].is_file():
            rw_val = float(rec["reward_path"].read_text(encoding="utf-8").strip())
            assert rw_val == pytest.approx(float(score))
        return score
    if not allow_missing_sub:
        raise AssertionError(
            f"Non-control evidence record {rec.get('label')} MUST include a real submission.json for verify_quarterly_file"
        )
    if rec.get("evaluation_path") is not None and rec["evaluation_path"].is_file():
        ev_doc = json.loads(rec["evaluation_path"].read_text(encoding="utf-8"))
        ev_obj = extract_eval_dict(ev_doc)
        return Fraction(ev_obj["reward_num"], ev_obj["reward_den"])
    if rec.get("reward_path") is not None and rec["reward_path"].is_file():
        rw_val = float(rec["reward_path"].read_text(encoding="utf-8").strip())
        assert rw_val == 0.0, f"Missing submission.json control record had non-zero reward.txt: {rw_val}"
        return Fraction(0, 1)
    raise AssertionError(f"Record {rec} lacks submission.json, evaluation.json, and reward.txt")


def test_t1_f15_blind_seeds_disjoint_and_sha256_provenance_recorded(world, replay_seeds):
    bundle = discover_benchmark_v2_bundle()
    blind_seeds = bundle["blind_seeds"]
    assert isinstance(blind_seeds, list) and len(blind_seeds) > 0
    assert all(type(s) is int and s > 0 for s in blind_seeds)
    assert len(set(blind_seeds)) == len(blind_seeds)
    assert set(blind_seeds).isdisjoint(set(world["development_seeds"]))
    assert set(blind_seeds).isdisjoint(set(replay_seeds))

    digest = hashlib.sha256(bundle["blind_seeds_path"].read_bytes()).hexdigest()
    joined_docs = (
        json.dumps([doc for _, doc in bundle["json_docs"]])
        + "\n"
        + "\n".join(txt for _, txt in bundle["text_docs"])
    )
    assert digest in joined_docs, "blind_seeds.json SHA-256 must be recorded in benchmark-v2 metadata"


def test_t1_f15_control_gates_nop_zero_stop_early_zero_and_oracle_above_035(world):
    bundle = discover_benchmark_v2_bundle()
    seeds = bundle["blind_seeds"]
    roles = bundle["runs_by_role"]
    assert roles["nop"], "Missing nop control run in evidence/benchmark-v2"
    assert roles["stop_early"], "Missing stop_early control run in evidence/benchmark-v2"
    assert roles["oracle"], "Missing oracle/reference run in evidence/benchmark-v2"

    assert _score_evidence_record(world, roles["nop"][0], seeds, allow_missing_sub=True) == Fraction(0, 1)
    assert _score_evidence_record(world, roles["stop_early"][0], seeds, allow_missing_sub=True) == Fraction(0, 1)
    assert _score_evidence_record(world, roles["oracle"][0], seeds) > Fraction(35, 100)


def test_t1_f15_qwen7b_post_rl_beats_base_7b_across_blind_runs(world):
    bundle = discover_benchmark_v2_bundle()
    seeds = bundle["blind_seeds"]
    base_runs = bundle["runs_by_role"]["base_7b"]
    post_runs = bundle["runs_by_role"]["post_rl_7b"]
    assert len(base_runs) >= 3, f"Expected >= 3 base_7b runs, found {len(base_runs)}"
    assert len(post_runs) >= 3, f"Expected >= 3 post_rl_7b runs, found {len(post_runs)}"

    base_scores = [_score_evidence_record(world, r, seeds) for r in base_runs]
    post_scores = [_score_evidence_record(world, r, seeds) for r in post_runs]
    assert sum(base_scores) / len(base_scores) < sum(post_scores) / len(post_scores)
    assert max(post_scores) > max(base_scores)


def test_t1_f15_frontier_opencode_scores_below_reference_across_three_blind_runs(world):
    bundle = discover_benchmark_v2_bundle()
    seeds = bundle["blind_seeds"]
    frontier_runs = bundle["runs_by_role"]["frontier"]
    oracle_runs = bundle["runs_by_role"]["oracle"]
    assert len(frontier_runs) >= 3, f"Expected >= 3 frontier runs, found {len(frontier_runs)}"
    assert oracle_runs

    oracle_score = max(_score_evidence_record(world, r, seeds) for r in oracle_runs)
    frontier_scores = [_score_evidence_record(world, r, seeds) for r in frontier_runs]
    assert all(fs < oracle_score for fs in frontier_scores)


def test_t1_f15_training_metrics_jsonl_and_lora_grpo_metadata_valid():
    bundle = discover_benchmark_v2_bundle()
    m_path = bundle["training_metrics_path"]
    assert m_path is not None and m_path.is_file(), "Missing training_metrics.jsonl in evidence/benchmark-v2"
    rows = [
        json.loads(ln, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
        for ln in m_path.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    assert len(rows) >= 2
    joined = (
        json.dumps([doc for _, doc in bundle["json_docs"]]).lower()
        + "\n"
        + "\n".join(txt.lower() for _, txt in bundle["text_docs"])
        + "\n"
        + json.dumps(rows).lower()
    )
    assert any(tok in joined for tok in ("qwen3.5-9b", "qwen3-8b", "qwen2.5-7b", "qwen", "7b", "8b", "9b"))


def test_t1_f15_harbor_runs_evidence_and_zero_leaked_secrets():
    assert scan_repo_for_secrets(REPO_ROOT) == []
    b_v2 = REPO_ROOT / "evidence" / "benchmark-v2"
    h_runs = REPO_ROOT / "evidence" / "harbor-runs"
    if not (b_v2.is_dir() and h_runs.is_dir()):
        pytest.skip("External Verda benchmark-v2 / harbor-runs not synced; code-only deployment scope")

    harbor_files = [p for p in h_runs.rglob("*") if p.is_file()]
    assert len(harbor_files) > 0, "evidence/harbor-runs/ must contain synced Harbor run artifacts"
    assert any(
        p.name in ("reward.txt", "evaluation.json", "submission.json", "result.json", "config.json")
        for p in harbor_files
    )

    for root_dir in (b_v2, h_runs):
        for fpath in root_dir.rglob("*"):
            if fpath.is_file():
                txt = fpath.read_text(encoding="utf-8", errors="ignore")
                for pat in SECRET_PATTERNS:
                    assert not pat.search(txt), f"Secret pattern {pat.pattern} matched in {fpath}"
    assert scan_repo_for_secrets(REPO_ROOT) == []


# ==============================================================================
# F16: Craft, Python >=3.12,<3.13, run_bench --verify-evidence & Docs — 6 Tests
# ==============================================================================


def test_t1_f16_pyproject_toml_and_python_version_pin_312_range():
    proj = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert proj["project"]["requires-python"].replace(" ", "") == ">=3.12,<3.13"
    assert proj["project"]["dependencies"] == []
    assert proj["tool"]["pytest"]["ini_options"]["pythonpath"] == ["src"]
    py_ver = (REPO_ROOT / ".python-version").read_text(encoding="utf-8").strip()
    assert py_ver == "3.12"


def test_t1_f16_run_bench_default_executes_v2_quarterly_and_writes_four_artifacts(run_cli, tmp_path):
    out_dir = tmp_path / "bench_v2"
    res = run_cli(["scripts/run_bench.py", "--out", str(out_dir)], timeout=25.0)
    assert res.returncode == 0, res.stderr
    for fname in ("submission.json", "episode.json", "comparison.md", "results.json"):
        assert (out_dir / fname).is_file()

    sub = json.loads((out_dir / "submission.json").read_text(encoding="utf-8"))
    assert sub["schema_version"] == 2 and len(sub["weeks"]) == 12

    results = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
    assert results["schema_version"] == 2
    assert results["pilot_count"] <= 24
    m_ev = results["results"]["manual"]
    r_ev = results["results"]["reference"]
    assert (m_ev["reward_num"], m_ev["reward_den"]) == (1, 5) and m_ev["win"] is False
    assert r_ev["win"] is True
    assert Fraction(r_ev["reward_num"], r_ev["reward_den"]) >= Fraction(7, 20)

    comp = (out_dir / "comparison.md").read_text(encoding="utf-8")
    assert not CYRILLIC_RE.search(comp)
    assert not CYRILLIC_RE.search(res.stdout)


def test_t1_f16_run_bench_auto_v1_compat_with_legacy_manual_plan(run_cli, tmp_path):
    seeds = tmp_path / "seeds.json"
    seeds.write_text("[821]\n", encoding="utf-8")
    out_dir = tmp_path / "bench_v1"
    res = run_cli(
        [
            "-m",
            "robotization_bench.cli",
            "compare",
            "--plan",
            str(REPO_ROOT / "data" / "plans" / "manual.json"),
            "--seeds-file",
            str(seeds),
            "--out",
            str(out_dir),
        ],
        timeout=20.0,
    )
    assert res.returncode == 0, res.stderr
    results = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
    assert results["evaluation_seeds"] == [821]
    assert results["results"]["submitted"] == results["results"]["manual"]
    comp = (out_dir / "comparison.md").read_text(encoding="utf-8")
    assert not CYRILLIC_RE.search(comp)


def test_t1_f16_run_bench_verify_evidence_succeeds_under_five_seconds(run_cli):
    ev_dir = REPO_ROOT / "evidence" / "benchmark-v2"
    if not ev_dir.is_dir():
        pytest.skip("External Verda benchmark-v2 not synced; code-only deployment scope")
    t0 = time.monotonic()
    res = run_cli(
        ["scripts/run_bench.py", "--verify-evidence", str(ev_dir)],
        timeout=10.0,
    )
    elapsed = time.monotonic() - t0
    assert res.returncode == 0, res.stderr
    assert elapsed < 5.0
    assert not CYRILLIC_RE.search(res.stdout)


def test_t1_f16_readme_concise_anti_slop_and_judge_docs_english():
    readme_path = REPO_ROOT / "README.md"
    readme = readme_path.read_text(encoding="utf-8")
    lines = readme.splitlines()
    assert not CYRILLIC_RE.search(readme), "Top-level README.md must be in clear English"
    assert 40 <= len(lines) <= 180, f"README.md must be 40..180 lines (got {len(lines)})"
    assert "run_bench.py" in readme
    assert "tasks/fulfillment-cell-bench" in readme
    assert "evidence/harbor-runs" in readme

    doc_anchors = {
        "AGENT.md": ("schema_version", "submission.json"),
        "docs/SPEC.md": ("1/5", "quarterly"),
        "docs/CONTRACTS.md": ("QuarterlyPlan", "Event"),
        "docs/HARBOR.md": ("no-network", "/srv/bench_daemon"),
        "evidence/README.md": ("seed",),
    }
    for rel, anchors in doc_anchors.items():
        p = REPO_ROOT / rel
        assert p.is_file(), f"Missing judge-facing doc {rel}"
        txt = p.read_text(encoding="utf-8")
        assert len(txt) >= 100
        assert not CYRILLIC_RE.search(txt), f"Cyrillic found in {rel}"
        for anchor in anchors:
            assert anchor.lower() in txt.lower(), f"Missing '{anchor}' in {rel}"


def test_t1_f16_russian_docs_preserved_under_docs_ru_archive():
    ru_dir = REPO_ROOT / "docs" / "ru"
    assert ru_dir.is_dir()
    assert (ru_dir / "3D_HANDOFF_MUSA.md").is_file()
    md_files = list(ru_dir.glob("*.md"))
    assert len(md_files) >= 2
    assert any(CYRILLIC_RE.search(p.read_text(encoding="utf-8")) for p in md_files)
    for top_md in (REPO_ROOT / "docs").glob("*.md"):
        assert not CYRILLIC_RE.search(top_md.read_text(encoding="utf-8"))
