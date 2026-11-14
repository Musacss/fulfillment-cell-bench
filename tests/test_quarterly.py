"""Comprehensive TDD verification suite for v2 12-week quarterly simulation, economics, grading, and episodes."""

import copy
from dataclasses import FrozenInstanceError, asdict, replace
from fractions import Fraction as F
import importlib.util
import json
import stat

import pytest

from robotization_bench.contracts import (
    QUARTERLY_SCHEMA_VERSION,
    ROOT,
    SCHEMA_VERSION,
    Economy,
    EpisodeClosed,
    InvalidPlan,
    Order,
    PilotBudgetExceeded,
    Plan,
    QuarterReport,
    QuarterlyPlan,
    RawReport,
    Scenario,
    WeekPlan,
    WeekReport,
    draw,
    load_world,
)
from robotization_bench.economics import calculate, calculate_week
from robotization_bench.episode import Episode, QuarterlyEpisode
from robotization_bench.grading import (
    evaluate,
    evaluate_any,
    evaluate_quarterly,
    grade_quarters,
    manual_value,
)
from robotization_bench.quarterly import (
    build_week_world,
    generate_quarter_exogenous,
    manual_quarterly_value,
    simulate_quarter,
)
from robotization_bench.reference import solve
from robotization_bench.reporting import compare, export_events
from robotization_bench.scenarios import generate
from robotization_bench.validation import (
    decode_any_plan,
    decode_plan,
    decode_quarterly_plan,
    parse_any_plan,
    parse_plan,
    parse_quarterly_plan,
)
from robotization_bench.verifier import verify_any_file, verify_file, verify_quarterly_file


def _load_invariant_helpers():
    spec = importlib.util.spec_from_file_location(
        "test_invariants", ROOT / "tests" / "test_invariants.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.check_trace, module.check_worker_intervals


CHECK_TRACE, CHECK_WORKER_INTERVALS = _load_invariant_helpers()

PHASED_WIN_PLAN = {
    "schema_version": 2,
    "weeks": [
        {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [2, 3], [4]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [2, 3], [4]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [2, 3], [4]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [3], [4], [2, 3]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [2, 3], [4]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": True, "workers": [[1], [2], [2, 3], [4]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [2, 3], [4]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [3], [4], [2, 3]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [3], [4], [2, 3]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [3], [4], [2, 3]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [2, 3], [4]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [2, 3], [4]]},
    ],
}

V1_SHIFT_ECONOMY_KEYS = {
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

V2_WEEK_ECONOMY_KEYS = {
    "depreciation",
    "service",
    "maintenance",
    "shifts",
    "cross_skill",
    "overtime",
    "hiring_retraining",
    "trays",
    "materials",
    "rework",
    "late",
    "backlog_holding",
    "unfulfilled",
    "escaped",
}


def _uniform_quarterly(
    *,
    robot: bool,
    trays: bool,
    route: str,
    maintenance: bool,
    workers: list[list[int]],
) -> dict:
    return {
        "schema_version": 2,
        "weeks": [
            {
                "robot": robot,
                "trays": trays,
                "route": route,
                "maintenance": maintenance,
                "workers": [list(z) for z in workers],
            }
            for _ in range(12)
        ],
    }


def _sample_raw(
    *,
    total: int = 11,
    good: int = 6,
    on_time: int = 4,
    escaped: int = 1,
    scrap: int = 1,
    unfinished: int = 3,
    pack_started: int = 11,
    pack_finished: int = 10,
    auto_finished: int = 0,
    trays_used: int = 9,
    rework_started: int = 2,
    labor_ticks: int = 440,
    overtime_ticks: tuple[int, ...] = (4, 9, 0),
) -> RawReport:
    return RawReport(
        schema_version=1,
        seed=7,
        total=total,
        good=good,
        on_time=on_time,
        escaped=escaped,
        scrap=scrap,
        unfinished=unfinished,
        pack_started=pack_started,
        pack_finished=pack_finished,
        auto_finished=auto_finished,
        trays_used=trays_used,
        rework_started=rework_started,
        labor_ticks=labor_ticks,
        overtime_ticks=overtime_ticks,
        events=(),
    )


# ==============================================================================
# Category A — F01 & F02: Additive v2 Contracts & world_spec.json Non-Regression
# ==============================================================================


def test_v1_world_keys_and_contracts_preserved_intact():
    world = load_world()
    expected_v1_keys = {
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
    assert expected_v1_keys.issubset(world.keys())
    assert world["schema_version"] == 1
    assert world["world_id"] == "cell-v1"
    assert world["development_seeds"] == [11, 29, 47]
    assert SCHEMA_VERSION == 1
    assert QUARTERLY_SCHEMA_VERSION == 2
    assert issubclass(PilotBudgetExceeded, RuntimeError)


def test_quarterly_world_catalog_schema_and_12_week_profiles():
    world = load_world()
    q = world["quarterly"]
    assert q["schema_version"] == 2
    assert q["world_id"] == "cell-quarterly-v2"
    assert q["weeks"] == 12
    assert q["max_pilots"] == 24
    assert q["carryover_cap"] == 80
    assert set(q["commissioning"].keys()) >= {"weeks", "jam_bonus_bps", "defect_bonus_bps"}
    assert set(q["wear"].keys()) >= {
        "per_week_bypass",
        "per_week_all",
        "fragile_oversize_all_bonus",
        "maintenance_reduction",
        "maintenance_auto_slowdown_ticks",
        "jam_bps_per_wear",
        "defect_bps_per_wear",
        "max_wear",
    }
    assert q["money"]["depreciation_weeks"] == 100
    assert q["money"]["shifts_per_week"] == 5
    assert set(q["threshold_bps"].keys()) == {
        "good_each_week",
        "good_pooled",
        "on_time_pooled",
        "escaped_each_week_max",
        "auto_pack_pooled_min",
    }
    profiles = q["week_profiles"]
    assert len(profiles) == 12
    shift_ticks = world["clock"]["shift_ticks"]
    spacing = world["generator"]["spacing"]
    jitter_span = world["generator"]["jitter_span"]
    for idx, prof in enumerate(profiles):
        assert prof["week"] == idx
        assert isinstance(prof["label"], str) and prof["label"]
        assert (prof["waves"] - 1) * spacing + (jitter_span - 1) < shift_ticks
        assert 0 <= prof["regular_bps"] + prof["fragile_bps"] <= 10_000


def test_week_plan_to_shift_plan_and_frozen_dataclasses():
    wp = WeekPlan(
        robot=True,
        trays=True,
        route="bypass",
        maintenance=False,
        workers=((1,), (2, 3), (4,)),
    )
    sp = wp.to_shift_plan()
    assert sp == Plan(1, True, True, "bypass", ((1,), (2, 3), (4,)))
    qp = QuarterlyPlan(2, (wp,) * 12)
    raw = _sample_raw()
    econ = Economy(1_530_000, {"shifts": 100}, 100)
    scen = Scenario(1, 11, (Order(0, "regular", 0, 100),))
    wr = WeekReport(0, "open", 11, 0, 0, 0, 1, True, sp, scen, raw, econ, econ)
    qr = QuarterReport(2, 11, 1_530_000, 100, 440, (wr,))

    for instance, attr in (
        (wp, "robot"),
        (qp, "schema_version"),
        (wr, "week"),
        (qr, "total_cost"),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(instance, attr, 999)

    serialized = json.loads(json.dumps(asdict(qp)))
    assert serialized["schema_version"] == 2
    assert len(serialized["weeks"]) == 12


def test_draw_and_v1_development_streams_bit_identical():
    world = load_world()
    assert draw(11, 0, 1, 0, "arrival", 1000) == draw(11, 0, 1, 0, "arrival", 1000)
    for seed in world["development_seeds"]:
        generated = json.loads(json.dumps(asdict(generate(world, seed))))
        saved = json.loads((ROOT / "data" / "development" / f"{seed}.json").read_text())
        assert generated == saved


def test_manual_quarterly_value_shape_and_immutability():
    world = load_world()
    m1 = manual_quarterly_value(world)
    m2 = manual_quarterly_value()
    assert m1 == m2
    assert m1["schema_version"] == 2
    assert len(m1["weeks"]) == 12
    base_manual = json.loads((ROOT / "data" / "plans" / "manual.json").read_text())
    assert all(
        w == {
            "robot": False,
            "trays": False,
            "route": "manual",
            "maintenance": False,
            "workers": base_manual["workers"],
        }
        for w in m1["weeks"]
    )
    m1["weeks"][0]["workers"][0].append(4)
    assert manual_quarterly_value(world)["weeks"][0]["workers"][0] == [1]


# ==============================================================================
# Category B — F03 & E07: Strict Dual v1/v2 Plan Validation (validation.py)
# ==============================================================================


def test_parse_and_decode_valid_quarterly_plans_including_phased_capex():
    world = load_world()
    phased = manual_quarterly_value(world)
    for w in range(3, 12):
        phased["weeks"][w]["trays"] = True
    for w in range(5, 12):
        phased["weeks"][w]["robot"] = True
        phased["weeks"][w]["route"] = "bypass"
    phased["weeks"][8]["maintenance"] = True

    for candidate in (manual_quarterly_value(world), copy.deepcopy(PHASED_WIN_PLAN), phased):
        parsed = parse_quarterly_plan(candidate, world)
        decoded = decode_quarterly_plan(json.dumps(candidate), world)
        any_parsed = parse_any_plan(candidate, world)
        any_decoded = decode_any_plan(json.dumps(candidate), world)
        assert parsed == decoded == any_parsed == any_decoded
        assert isinstance(parsed, QuarterlyPlan)
        assert parse_quarterly_plan(asdict(parsed), world) == parsed


def test_v1_parse_plan_rejects_v2_and_parse_quarterly_rejects_v1():
    world = load_world()
    v1_plan = manual_value()
    v2_plan = manual_quarterly_value(world)

    with pytest.raises(InvalidPlan):
        parse_plan(v2_plan, world)
    with pytest.raises(InvalidPlan):
        decode_plan(json.dumps(v2_plan), world)
    with pytest.raises(InvalidPlan):
        parse_quarterly_plan(v1_plan, world)
    with pytest.raises(InvalidPlan):
        decode_quarterly_plan(json.dumps(v1_plan), world)

    assert isinstance(parse_any_plan(v1_plan, world), Plan)
    assert isinstance(decode_any_plan(json.dumps(v1_plan), world), Plan)
    assert isinstance(parse_any_plan(v2_plan, world), QuarterlyPlan)
    assert isinstance(decode_any_plan(json.dumps(v2_plan), world), QuarterlyPlan)


@pytest.mark.parametrize("case", ["empty", "one", "eleven", "thirteen", "none", "str", "int"])
def test_quarterly_horizon_length_and_partial_horizon_rejected(case):
    world = load_world()
    base = manual_quarterly_value(world)["weeks"]
    mapping = {
        "empty": [],
        "one": base[:1],
        "eleven": base[:11],
        "thirteen": base + [base[0]],
        "none": None,
        "str": "weeks",
        "int": 12,
    }
    payload = {"schema_version": 2, "weeks": mapping[case]}
    with pytest.raises(InvalidPlan):
        parse_quarterly_plan(payload, world)


def test_irreversible_capex_monotonicity_enforced():
    world = load_world()
    robot_reversal = manual_quarterly_value(world)
    robot_reversal["weeks"][2]["robot"] = True
    with pytest.raises(InvalidPlan, match="robot"):
        parse_quarterly_plan(robot_reversal, world)

    tray_reversal = manual_quarterly_value(world)
    tray_reversal["weeks"][4]["trays"] = True
    with pytest.raises(InvalidPlan, match="trays"):
        parse_quarterly_plan(tray_reversal, world)


def test_week_equipment_route_and_maintenance_coupling_rules():
    world = load_world()
    for bad_route in ("bypass", "all"):
        bad = manual_quarterly_value(world)
        bad["weeks"][0]["route"] = bad_route
        with pytest.raises(InvalidPlan):
            parse_quarterly_plan(bad, world)

    bad_maint = manual_quarterly_value(world)
    bad_maint["weeks"][0]["maintenance"] = True
    with pytest.raises(InvalidPlan, match="maintenance"):
        parse_quarterly_plan(bad_maint, world)

    trays_without_robot = manual_quarterly_value(world)
    for w in range(12):
        trays_without_robot["weeks"][w]["trays"] = True
    parsed_trays = parse_quarterly_plan(trays_without_robot, world)
    assert all(wp.trays and not wp.robot for wp in parsed_trays.weeks)

    idle_robot_maint = _uniform_quarterly(
        robot=True, trays=False, route="manual", maintenance=True, workers=[[1], [2], [3], [4]]
    )
    parsed_idle = parse_quarterly_plan(idle_robot_maint, world)
    assert all(wp.robot and wp.maintenance and wp.route == "manual" for wp in parsed_idle.weeks)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda p: p.update(schema_version=True),
        lambda p: p.update(schema_version=3),
        lambda p: p.update(extra=1),
        lambda p: p["weeks"][0].update(robot=1),
        lambda p: p["weeks"][0].update(trays=0),
        lambda p: p["weeks"][0].update(maintenance="false"),
        lambda p: p["weeks"][0].update(route="turbo"),
        lambda p: p["weeks"][0].update(workers=[]),
        lambda p: p["weeks"][0].update(workers=[[1]] * 9),
        lambda p: p["weeks"][0].update(workers=[[1, True]]),
        lambda p: p["weeks"][0].update(workers=[[1, 1]]),
        lambda p: p["weeks"][0].update(workers=[[5]]),
        lambda p: p["weeks"][0].update(bonus=True),
        lambda p: p["weeks"][0].pop("maintenance"),
    ],
)
def test_strict_type_confusion_duplicate_keys_and_non_finite_json_rejected(mutator):
    world = load_world()
    plan = manual_quarterly_value(world)
    mutator(plan)
    with pytest.raises(InvalidPlan):
        parse_quarterly_plan(plan, world)
    with pytest.raises(InvalidPlan):
        parse_any_plan(plan, world)

    dup_week = (
        '{"schema_version":2,"weeks":['
        + ",".join(
            ['{"robot":false,"robot":true,"trays":false,"route":"manual","maintenance":false,"workers":[[1]]}']
            + ['{"robot":false,"trays":false,"route":"manual","maintenance":false,"workers":[[1]]}'] * 11
        )
        + "]}"
    )
    for raw_bad in (dup_week, "NaN", "Infinity", "-Infinity", "1e999", "1" * 5000):
        with pytest.raises(InvalidPlan):
            decode_quarterly_plan(raw_bad, world)
        with pytest.raises(InvalidPlan):
            decode_any_plan(raw_bad, world)


# ==============================================================================
# Category C — F04 & E02/E09/E10: 12-Week Simulator, Carryover, Wear & 3D Traces
# ==============================================================================


def test_generate_quarter_exogenous_determinism_and_wave_profiles():
    world = load_world()
    exo_a = generate_quarter_exogenous(world, 11)
    exo_b = generate_quarter_exogenous(world, 11)
    exo_other = generate_quarter_exogenous(world, 29)
    assert exo_a == exo_b
    assert exo_a != exo_other
    assert len(exo_a) == 12
    assert len({s.seed for s in exo_a}) == 12
    assert all(s.schema_version == 1 and len(s.orders) > 0 for s in exo_a)
    # Black Friday peak (week 8: 13 waves, min 13) strictly exceeds pre-peak prep (week 5: 10 waves, min 10).
    assert len(exo_a[8].orders) > len(exo_a[5].orders)


def test_backlog_carryover_places_unfinished_at_arrival_zero_and_preserves_scenario_invariants():
    world = load_world()
    understaffed = parse_quarterly_plan(
        _uniform_quarterly(robot=False, trays=False, route="manual", maintenance=False, workers=[[1], [2], [3], [4]]),
        world,
    )
    exo = generate_quarter_exogenous(world, 11)
    report = simulate_quarter(world, understaffed, 11, trace=False)

    w0, w1 = report.weeks[0], report.weeks[1]
    assert w0.carryover_in == 0
    assert w0.carryover_out == min(w0.raw.unfinished, world["quarterly"]["carryover_cap"]) > 0
    assert w1.carryover_in == w0.carryover_out
    assert w1.raw.total == w1.carryover_in + len(exo[1].orders)

    carried = w1.scenario.orders[: w1.carryover_in]
    assert all(o.arrival == 0 and o.due == 0 for o in carried)
    assert [o.id for o in w1.scenario.orders] == sorted({o.id for o in w1.scenario.orders}) or (
        len({o.id for o in w1.scenario.orders}) == len(w1.scenario.orders)
    )
    assert list(w1.scenario.orders) == sorted(w1.scenario.orders, key=lambda o: (o.arrival, o.id))
    assert report.weeks[11].carryover_out == 0


def test_carryover_cap_clips_extreme_deadlock_and_charges_overflow_unfulfilled():
    world = load_world()
    deadlock = parse_quarterly_plan(
        _uniform_quarterly(robot=False, trays=False, route="manual", maintenance=False, workers=[[4]]),
        world,
    )
    report = simulate_quarter(world, deadlock, 11, trace=False)
    cap = world["quarterly"]["carryover_cap"]
    w0 = report.weeks[0]
    assert w0.raw.unfinished > cap
    assert w0.carryover_out == cap
    assert report.weeks[1].carryover_in == cap

    overflow = w0.raw.unfinished - cap
    expected_unfulfilled = (
        (w0.raw.scrap + overflow)
        * world["money"]["unfulfilled"]
        * world["quarterly"]["money"]["shifts_per_week"]
    )
    assert w0.week_economy.costs["unfulfilled"] == expected_unfulfilled
    assert w0.week_economy.costs["backlog_holding"] == cap * world["quarterly"]["money"]["backlog_holding_per_order"]


def test_commissioning_window_elevates_early_robot_jam_and_defect_rates():
    world = load_world()
    delayed = manual_quarterly_value(world)
    for w in range(3, 12):
        delayed["weeks"][w]["robot"] = True
        delayed["weeks"][w]["trays"] = True
        delayed["weeks"][w]["route"] = "bypass"
    report = simulate_quarter(world, parse_quarterly_plan(delayed, world), 11, trace=False)
    active_weeks = [wr.week for wr in report.weeks if wr.commissioning_active]
    assert active_weeks == [3, 4]

    w_base = build_week_world(world, 3, commissioning=False, wear=0, maintenance=False)
    w_comm = build_week_world(world, 3, commissioning=True, wear=0, maintenance=False)
    assert (
        w_comm["prob_bps"]["jam"]["tray"]["regular"]
        == w_base["prob_bps"]["jam"]["tray"]["regular"] + world["quarterly"]["commissioning"]["jam_bonus_bps"]["tray"]
    )
    assert (
        w_comm["prob_bps"]["defect_auto"]["bare"]["regular"]
        == w_base["prob_bps"]["defect_auto"]["bare"]["regular"]
        + world["quarterly"]["commissioning"]["defect_bonus_bps"]["bare"]
    )


def test_cumulative_wear_dynamics_route_all_vs_bypass_and_maintenance_reset():
    world = load_world()
    manual_rep = simulate_quarter(world, parse_quarterly_plan(manual_quarterly_value(world), world), 11)
    assert all(wr.wear_start == 0 and wr.wear_end == 0 for wr in manual_rep.weeks)

    bypass_plan = _uniform_quarterly(
        robot=True, trays=True, route="bypass", maintenance=False, workers=[[1], [2], [3], [4], [2, 3]]
    )
    all_plan = _uniform_quarterly(
        robot=True, trays=True, route="all", maintenance=False, workers=[[1], [2], [3], [4], [2, 3]]
    )
    bypass_rep = simulate_quarter(world, parse_quarterly_plan(bypass_plan, world), 11)
    all_rep = simulate_quarter(world, parse_quarterly_plan(all_plan, world), 11)

    assert bypass_rep.weeks[0].wear_end == 1
    assert all_rep.weeks[0].wear_end == 3
    # Week 3 fragile_promo has non-regular share 3600 bps >= 3000 bps -> +1 fragile/oversize bonus on route="all".
    assert all_rep.weeks[3].wear_end - all_rep.weeks[3].wear_start == 4 or all_rep.weeks[3].wear_end == 12
    assert max(wr.wear_end for wr in all_rep.weeks) == world["quarterly"]["wear"]["max_wear"] == 12

    phased_rep = simulate_quarter(world, parse_quarterly_plan(PHASED_WIN_PLAN, world), 11)
    assert phased_rep.weeks[5].wear_start == 5
    # Week 5 maintenance reduces 5 -> 0 before adding +1 bypass wear -> wear_end == 1.
    assert phased_rep.weeks[5].wear_end == 1

    w_maint = build_week_world(world, 5, commissioning=False, wear=5, maintenance=True)
    w_clean = build_week_world(world, 5, commissioning=False, wear=0, maintenance=False)
    assert w_maint["prob_bps"]["jam"] == w_clean["prob_bps"]["jam"]
    assert w_maint["time"]["auto"]["tray"]["regular"] == w_clean["time"]["auto"]["tray"]["regular"] + 1


def test_trace_true_vs_false_state_equivalence():
    world = load_world()
    plan = parse_quarterly_plan(PHASED_WIN_PLAN, world)
    untraced = simulate_quarter(world, plan, 29, trace=False)
    traced = simulate_quarter(world, plan, 29, trace=True)

    assert (untraced.purchase, untraced.total_cost, untraced.labor_ticks) == (
        traced.purchase,
        traced.total_cost,
        traced.labor_ticks,
    )
    for wu, wt in zip(untraced.weeks, traced.weeks):
        assert wu.raw.events == ()
        assert len(wt.raw.events) > 0
        assert replace(wt, raw=replace(wt.raw, events=())) == wu


def test_all_12_weeks_pass_sacred_3d_check_trace_and_worker_intervals(tmp_path):
    world = load_world()
    congested_all = _uniform_quarterly(
        robot=True, trays=False, route="all", maintenance=False, workers=[[1], [2], [3], [4], [2, 3]]
    )
    for label, plan_dict in (
        ("manual", manual_quarterly_value(world)),
        ("phased", PHASED_WIN_PLAN),
        ("congested_all", congested_all),
    ):
        qplan = parse_quarterly_plan(plan_dict, world)
        qrep = simulate_quarter(world, qplan, 11, trace=True)
        for wr in qrep.weeks:
            CHECK_TRACE(world, wr.shift_plan, wr.scenario, wr.raw)
            CHECK_WORKER_INTERVALS(world, wr.shift_plan, wr.raw)
            assert set(wr.shift_economy.costs.keys()) == V1_SHIFT_ECONOMY_KEYS

        out_jsonl = tmp_path / f"{label}-week07.jsonl"
        export_events(qrep.weeks[7].raw, out_jsonl)
        lines = [json.loads(line) for line in out_jsonl.read_text().splitlines()]
        assert len(lines) == len(qrep.weeks[7].raw.events) > 0
        assert set(lines[0].keys()) == {"tick", "kind", "order_id", "resource", "stage", "attempt", "end_tick"}


# ==============================================================================
# Category D — F05: Quarterly Integer-Cent Economics (economics.py)
# ==============================================================================


def test_v1_calculate_unchanged_and_shift_economy_has_exact_10_v1_keys():
    world = load_world()
    wp = WeekPlan(True, True, "manual", False, ((1, 2), (3,), (4,)))
    raw = _sample_raw()
    v1_direct = calculate(world, wp.to_shift_plan(), raw)
    shift_econ, week_econ = calculate_week(
        world,
        wp,
        ((1, 2), (3,), (4,)),
        raw,
        carryover_out=2,
        owned_robot=True,
        owned_trays=True,
    )
    assert shift_econ == v1_direct
    assert set(shift_econ.costs.keys()) == V1_SHIFT_ECONOMY_KEYS
    assert set(week_econ.costs.keys()) == V2_WEEK_ECONOMY_KEYS


@pytest.mark.parametrize(
    ("robot_price", "tray_price", "dep_weeks", "expected_dep"),
    [
        (1_350_000, 180_000, 100, 15_300),
        (1, 1, 2, 1),
        (2, 1, 2, 2),
        (2, 2, 3, 1),
    ],
)
def test_weekly_depreciation_half_up_rounding_and_irreversible_owned_equipment(
    robot_price, tray_price, dep_weeks, expected_dep
):
    world = load_world()
    assert world["quarterly"]["money"]["depreciation_weeks"] == 100
    world["money"].update(robot_purchase=robot_price, tray_purchase=tray_price)
    world["quarterly"]["money"]["depreciation_weeks"] = dep_weeks

    wp_idle = WeekPlan(False, False, "manual", False, ((1,), (2,), (3,), (4,)))
    raw = _sample_raw(unfinished=0, scrap=0, escaped=0, good=11, on_time=11, overtime_ticks=(0, 0, 0, 0))
    _, week_econ = calculate_week(
        world,
        wp_idle,
        wp_idle.workers,
        raw,
        carryover_out=0,
        owned_robot=True,
        owned_trays=True,
    )
    assert week_econ.purchase == robot_price + tray_price
    assert week_econ.costs["depreciation"] == expected_dep
    assert week_econ.costs["service"] == 3_500

    full_world = load_world()
    qrep = simulate_quarter(full_world, parse_quarterly_plan(PHASED_WIN_PLAN, full_world), 11)
    assert qrep.purchase == 1_530_000
    assert qrep.weeks[0].week_economy.costs["depreciation"] == 15_300


def test_crew_hiring_layoff_retraining_and_cross_skill_premium_in_cents():
    world = load_world()
    raw = _sample_raw(unfinished=0, scrap=0, escaped=0, good=11, on_time=11, overtime_ticks=(0,))
    base_crew = ((1,), (2,), (3,), (3,), (4,), (2, 3))

    # Reordering existing crew incurs zero hiring/layoff/retraining friction.
    wp_reordered = WeekPlan(False, False, "manual", False, tuple(reversed(base_crew)))
    _, econ_reordered = calculate_week(
        world, wp_reordered, base_crew, raw, carryover_out=0, owned_robot=False, owned_trays=False
    )
    assert econ_reordered.costs["hiring_retraining"] == 0
    assert econ_reordered.costs["cross_skill"] == 1 * 900 * 5

    # Laying off one middle worker (3,) charges layoff_cost (11_000¢) only, zero bogus retraining!
    wp_layoff = WeekPlan(False, False, "manual", False, ((1,), (2,), (3,), (4,), (2, 3)))
    _, econ_layoff = calculate_week(
        world, wp_layoff, base_crew, raw, carryover_out=0, owned_robot=False, owned_trays=False
    )
    assert econ_layoff.costs["hiring_retraining"] == 11_000

    # Pure retraining of an existing worker (+2 new zones) without headcount change.
    wp_retrain_only = WeekPlan(False, False, "manual", False, ((1,), (2, 3, 4)))
    _, econ_retrain = calculate_week(
        world,
        wp_retrain_only,
        ((1,), (2,)),
        raw,
        carryover_out=0,
        owned_robot=False,
        owned_trays=False,
    )
    assert econ_retrain.costs["hiring_retraining"] == 2 * 3_500
    assert econ_retrain.costs["cross_skill"] == 1 * 900 * 5

    # Hiring one worker + optimal DP matching: {2}->{4} (1 zone) + new hire {2,3,4} = 9_000 + 3_500 = 12_500¢;
    # and when both non-(1,) slots are (2,3,4), {2}->{2,3,4} requires 2 zones = 9_000 + 2*3_500 = 16_000¢.
    wp_hire_opt = WeekPlan(False, False, "manual", False, ((1,), (2, 3, 4), (4,)))
    _, econ_opt = calculate_week(
        world, wp_hire_opt, ((1,), (2,)), raw, carryover_out=0, owned_robot=False, owned_trays=False
    )
    assert econ_opt.costs["hiring_retraining"] == 1 * 9_000 + 1 * 3_500

    wp_hire_two_zones = WeekPlan(False, False, "manual", False, ((1,), (2, 3, 4), (2, 3, 4)))
    _, econ_hr = calculate_week(
        world,
        wp_hire_two_zones,
        ((1,), (2,)),
        raw,
        carryover_out=0,
        owned_robot=False,
        owned_trays=False,
    )
    assert econ_hr.costs["hiring_retraining"] == 1 * 9_000 + 2 * 3_500
    assert econ_hr.costs["cross_skill"] == 2 * 900 * 5


def test_intra_quarter_backlog_holding_vs_terminal_unfulfilled_accounting():
    world = load_world()
    wp = WeekPlan(False, False, "manual", False, ((1,), (2,), (3,), (4,)))
    raw = _sample_raw(scrap=1, unfinished=3, overtime_ticks=(0, 0, 0, 0))

    # Intra-quarter week: all 3 unfinished orders carried over -> holding 3*600=1800¢, unfulfilled only on 1 scrap.
    _, intra = calculate_week(
        world, wp, wp.workers, raw, carryover_out=3, owned_robot=False, owned_trays=False
    )
    assert intra.costs["backlog_holding"] == 1_800
    assert intra.costs["unfulfilled"] == 1 * 3_500 * 5

    # Terminal Week 11: carryover_out == 0 -> holding 0¢, full terminal unfulfilled on 1 scrap + 3 unfinished.
    _, terminal = calculate_week(
        world, wp, wp.workers, raw, carryover_out=0, owned_robot=False, owned_trays=False
    )
    assert terminal.costs["backlog_holding"] == 0
    assert terminal.costs["unfulfilled"] == 4 * 3_500 * 5


def test_shift_scaling_5_shifts_per_week_consistency():
    world = load_world()
    wp = WeekPlan(True, True, "bypass", True, ((1, 2), (3,), (4,)))
    raw = _sample_raw(scrap=1, unfinished=2)
    shift_econ, week_econ = calculate_week(
        world, wp, wp.workers, raw, carryover_out=2, owned_robot=True, owned_trays=True
    )
    assert week_econ.costs["shifts"] == shift_econ.costs["shifts"] * 5
    assert week_econ.costs["overtime"] == shift_econ.costs["overtime"] * 5
    assert week_econ.costs["trays"] == shift_econ.costs["trays"] * 5
    assert week_econ.costs["materials"] == shift_econ.costs["materials"] * 5
    assert week_econ.costs["rework"] == shift_econ.costs["rework"] * 5
    assert week_econ.costs["late"] == shift_econ.costs["late"] * 5
    assert week_econ.costs["escaped"] == shift_econ.costs["escaped"] * 5
    assert week_econ.costs["maintenance"] == 4_500
    assert week_econ.total == sum(week_econ.costs.values())
    assert all(type(v) is int for v in week_econ.costs.values())


# ==============================================================================
# Category E — F06 & E01/E03/E04/E08: Exact Fraction Grading & Verifier
# ==============================================================================


def test_v1_infeasible_deadlock_positive_floor_in_evaluate():
    world = load_world()
    days = tuple(generate(world, s) for s in world["development_seeds"])
    deadlock_v1 = {"schema_version": 1, "robot": True, "trays": False, "route": "all", "workers": [[1], [2], [4]]}
    verdict = evaluate(world, deadlock_v1, days)
    assert verdict.valid and not verdict.feasible and not verdict.win
    assert F(0) < F(verdict.reward_num, verdict.reward_den) <= F(9, 100)

    zero_good_v1 = {"schema_version": 1, "robot": False, "trays": False, "route": "manual", "workers": [[4]]}
    zero_verdict = evaluate(world, zero_good_v1, days)
    assert zero_verdict.valid and not zero_verdict.feasible and zero_verdict.metrics["good"] == 0
    assert F(zero_verdict.reward_num, zero_verdict.reward_den) == F(1, 10_000)


def test_quarterly_manual_baseline_exact_one_fifth_across_dev_and_replay_seeds():
    world = load_world()
    manual_q = manual_quarterly_value(world)
    replay_seeds = json.loads((ROOT / "evidence" / "replay_seeds.json").read_text())

    for pool in (world["development_seeds"], replay_seeds):
        res = evaluate_quarterly(world, manual_q, pool)
        assert res.valid and res.feasible and not res.win
        assert (res.reward_num, res.reward_den) == (1, 5)
        assert set(res.reasons) == {"cost", "labor", "automation"}


def test_quarterly_strict_reward_hierarchy_all_mandatory_probes_dev_and_replay():
    world = load_world()
    replay_seeds = json.loads((ROOT / "evidence" / "replay_seeds.json").read_text())
    manual_q = manual_quarterly_value(world)

    unstaffed_deadlock = _uniform_quarterly(
        robot=True, trays=False, route="all", maintenance=False, workers=[[1], [2], [4]]
    )
    naive_all = _uniform_quarterly(
        robot=True, trays=True, route="all", maintenance=False, workers=[[1], [2], [3], [4], [2, 3]]
    )
    static_5w_nomaint = _uniform_quarterly(
        robot=True, trays=True, route="bypass", maintenance=False, workers=[[1], [2], [3], [4], [2, 3]]
    )
    buy_capex_idle = _uniform_quarterly(
        robot=True,
        trays=True,
        route="manual",
        maintenance=False,
        workers=manual_q["weeks"][0]["workers"],
    )
    late_week11_token = copy.deepcopy(manual_q)
    late_week11_token["weeks"][11] = {
        "robot": True,
        "trays": True,
        "route": "bypass",
        "maintenance": False,
        "workers": [[1], [2], [2, 3], [4]],
    }

    for seeds in (world["development_seeds"], replay_seeds):
        r_nop = evaluate_quarterly(world, None, seeds)
        r_partial = evaluate_quarterly(world, {"schema_version": 2, "weeks": manual_q["weeks"][:11]}, seeds)
        r_deadlock = evaluate_quarterly(world, unstaffed_deadlock, seeds)
        r_naive_all = evaluate_quarterly(world, naive_all, seeds)
        r_static_nomaint = evaluate_quarterly(world, static_5w_nomaint, seeds)
        r_capex_idle = evaluate_quarterly(world, buy_capex_idle, seeds)
        r_token_w11 = evaluate_quarterly(world, late_week11_token, seeds)
        r_manual = evaluate_quarterly(world, manual_q, seeds)
        r_win = evaluate_quarterly(world, PHASED_WIN_PLAN, seeds)

        assert not r_nop.valid and F(r_nop.reward_num, r_nop.reward_den) == F(0)
        assert not r_partial.valid and F(r_partial.reward_num, r_partial.reward_den) == F(0)
        assert r_deadlock.valid and not r_deadlock.feasible
        assert r_naive_all.valid and not r_naive_all.feasible
        assert r_static_nomaint.valid and not r_static_nomaint.feasible
        assert r_capex_idle.valid and r_capex_idle.feasible and not r_capex_idle.win
        assert r_token_w11.valid and r_token_w11.feasible and not r_token_w11.win
        assert "automation" in r_token_w11.reasons
        assert r_manual.valid and r_manual.feasible and not r_manual.win
        assert r_win.valid and r_win.feasible and r_win.win and r_win.reasons == ()

        s_deadlock = F(r_deadlock.reward_num, r_deadlock.reward_den)
        s_naive = F(r_naive_all.reward_num, r_naive_all.reward_den)
        s_static = F(r_static_nomaint.reward_num, r_static_nomaint.reward_den)
        s_idle = F(r_capex_idle.reward_num, r_capex_idle.reward_den)
        s_token = F(r_token_w11.reward_num, r_token_w11.reward_den)
        s_manual = F(r_manual.reward_num, r_manual.reward_den)
        s_win = F(r_win.reward_num, r_win.reward_den)

        assert F(0) < s_deadlock < s_naive < s_static <= F(9, 100)
        assert F(1, 10) < s_idle < s_manual == F(1, 5)
        assert F(1, 10) < s_token < s_manual == F(1, 5)
        assert s_win >= F(35, 100)

        rendered = compare({"manual": r_manual, "phased": r_win})
        assert f"{r_win.reward_num}/{r_win.reward_den}" in rendered


def test_evaluate_any_polymorphic_v1_and_v2_dispatch():
    world = load_world()
    seeds = world["development_seeds"]
    days = tuple(generate(world, s) for s in seeds)
    assert evaluate_any(world, manual_value(), seeds) == evaluate(world, manual_value(), days)
    assert evaluate_any(world, PHASED_WIN_PLAN, seeds) == evaluate_quarterly(world, PHASED_WIN_PLAN, seeds)
    bad = evaluate_any(world, {"schema_version": 99}, seeds)
    assert not bad.valid and (bad.reward_num, bad.reward_den) == (0, 1)


def test_grade_quarters_rejects_mismatched_seeds_or_nonpositive_base_cost():
    world = load_world()
    qplan = parse_quarterly_plan(manual_quarterly_value(world), world)
    q11 = simulate_quarter(world, qplan, 11)
    q29 = simulate_quarter(world, qplan, 29)

    with pytest.raises(ValueError, match="quarters"):
        grade_quarters(world, qplan, [], [])
    with pytest.raises(ValueError, match="quarters"):
        grade_quarters(world, qplan, [q11], [q29])
    with pytest.raises(ValueError, match="quarters"):
        grade_quarters(world, qplan, [q11, q11], [q11, q11])

    zero_weeks = tuple(
        replace(w, week_economy=Economy(0, {k: 0 for k in w.week_economy.costs}, 0))
        for w in q11.weeks
    )
    q_zero = replace(q11, total_cost=0, weeks=zero_weeks)
    with pytest.raises(ValueError, match="costs"):
        grade_quarters(world, qplan, [q_zero], [q_zero])


def test_verify_quarterly_file_and_verify_any_file_security_guards(tmp_path):
    world = load_world()
    seeds = world["development_seeds"]
    days = tuple(generate(world, s) for s in seeds)

    missing = tmp_path / "missing.json"
    assert not verify_quarterly_file(world, missing, seeds).valid
    assert not verify_any_file(world, missing, seeds).valid
    assert not verify_quarterly_file(world, tmp_path, seeds).valid

    v2_path = tmp_path / "v2.json"
    v2_path.write_text(json.dumps(PHASED_WIN_PLAN))
    res_q = verify_quarterly_file(world, v2_path, seeds)
    res_any_v2 = verify_any_file(world, v2_path, seeds)
    assert res_q.win and res_q == res_any_v2

    v1_path = tmp_path / "v1.json"
    v1_path.write_text(json.dumps(manual_value()))
    assert not verify_quarterly_file(world, v1_path, seeds).valid
    assert verify_any_file(world, v1_path, seeds) == verify_file(world, v1_path, days)

    link = tmp_path / "symlink.json"
    link.symlink_to(v2_path)
    assert not verify_quarterly_file(world, link, seeds).valid
    assert not verify_any_file(world, link, seeds).valid

    bad_path = tmp_path / "bad.json"
    for payload in (
        b"x" * 16_385,
        b"\xff",
        b"null",
        b'{"schema_version":2,"schema_version":2,"weeks":[]}',
        b"NaN",
    ):
        bad_path.write_bytes(payload)
        verdict = verify_quarterly_file(world, bad_path, seeds)
        assert not verdict.valid and (verdict.reward_num, verdict.reward_den) == (0, 1)


# ==============================================================================
# Category F — F07 & E05/E06/E09/E10: QuarterlyEpisode, Episode & Persistence
# ==============================================================================


def test_quarterly_episode_observe_sanitizes_world_and_exposes_12_week_history():
    world = load_world()
    world["_private_secret"] = "leak"
    world["evaluation_seeds"] = [999_999]
    world["quarterly"]["_solver_hint"] = "do_not_expose"

    ep = QuarterlyEpisode(world)
    obs = ep.observe()
    assert obs["schema_version"] == 2
    assert obs["pilot_budget"] == {"used": 0, "max": 24}
    assert obs["development_seeds"] == [11, 29, 47]
    assert "_private_secret" not in obs["world"]
    assert "evaluation_seeds" not in obs["world"]
    assert "_solver_hint" not in obs["world"]["quarterly"]
    assert len(json.dumps(obs)) < 65_536

    obs["world"]["quarterly"]["max_pilots"] = 9999
    assert ep.observe()["world"]["quarterly"]["max_pilots"] == 24

    assert [item["seed"] for item in obs["history"]] == [11, 29, 47]
    for item in obs["history"]:
        assert len(item["weeks"]) == 12
        assert item["total_orders"] == sum(w["total_orders"] for w in item["weeks"])
        for w in item["weeks"]:
            assert sum(w["kind_counts"].values()) == w["total_orders"]
            assert type(w["mean_due_slack_ticks"]) is int


def test_quarterly_episode_pilot_valid_rollout_jams_telemetry_and_trace_toggle():
    world = load_world()
    ep = QuarterlyEpisode(world)
    jam_plan = _uniform_quarterly(
        robot=True, trays=False, route="all", maintenance=False, workers=[[1], [2], [3], [4], [2, 3]]
    )

    untraced = ep.pilot(jam_plan, 11, trace=False)
    traced = ep.pilot(jam_plan, 11, trace=True)

    assert untraced["pilot_budget"] == {"used": 1, "max": 24}
    assert traced["pilot_budget"] == {"used": 2, "max": 24}
    assert untraced["total_cost"] == traced["total_cost"]
    assert untraced["totals"]["jams"] == traced["totals"]["jams"] > 0

    for wu, wt in zip(untraced["weeks"], traced["weeks"]):
        assert wu["raw"]["events"] == []
        assert len(wt["raw"]["events"]) > 0
        assert wu["jams"] == wt["jams"] == sum(1 for e in wt["raw"]["events"] if e["kind"] == "jam")
        assert wu["assists"] == wt["assists"] == sum(1 for e in wt["raw"]["events"] if e["kind"] == "assist")

    for entry in ep.log:
        if entry["action"] == "pilot":
            assert all(w["raw"]["events"] == [] for w in entry["weeks"])


def test_quarterly_episode_invalid_pilot_and_unknown_seed_keep_episode_open():
    world = load_world()
    ep = QuarterlyEpisode(world, seeds=[1, 11])
    manual_q = manual_quarterly_value(world)

    with pytest.raises(InvalidPlan):
        ep.pilot({"schema_version": 2, "weeks": []}, 11)
    with pytest.raises(ValueError, match="unknown public day"):
        ep.pilot(manual_q, -999)
    # True == 1 in Python, so seed=True MUST still be rejected as non-int!
    with pytest.raises(ValueError, match="unknown public day"):
        ep.pilot(manual_q, True)

    assert not ep.closed
    assert ep.pilot_used == 0
    assert len(ep.log) == 3 and all("error" in e for e in ep.log)

    ok = ep.pilot(manual_q, 11)
    assert ok["pilot_budget"]["used"] == 1
    assert ep.pilot_used == 1


def test_quarterly_episode_max_pilots_budget_exhaustion_leaves_episode_open_for_submit():
    world = load_world()
    ep = QuarterlyEpisode(world, max_pilots=3)
    manual_q = manual_quarterly_value(world)

    for expected_used in (1, 2, 3):
        out = ep.pilot(manual_q, 11)
        assert out["pilot_budget"] == {"used": expected_used, "max": 3}

    with pytest.raises(PilotBudgetExceeded, match=r"BudgetExceeded: pilot budget exhausted \(3/3\)"):
        ep.pilot(manual_q, 11)
    assert not ep.closed

    receipt = ep.submit(PHASED_WIN_PLAN)
    assert receipt == {"terminal": True, "plan": PHASED_WIN_PLAN}
    assert ep.closed
    assert ep.submission == PHASED_WIN_PLAN


@pytest.mark.parametrize(
    ("method", "arg"),
    [
        ("submit", None),
        ("submit", {"bad": 1}),
        ("submit", {"schema_version": 2, "weeks": []}),
        ("stop", None),
    ],
)
def test_quarterly_episode_submit_invalid_and_stop_return_null_plan_and_close(method, arg):
    world = load_world()
    ep = QuarterlyEpisode(world)
    receipt = ep.stop() if method == "stop" else ep.submit(arg)
    assert receipt == {"terminal": True, "plan": None}
    assert ep.closed
    assert ep.submission is None
    if method == "submit":
        assert "error" in ep.log[-1]

    for after_fn in (
        lambda: ep.observe(),
        lambda: ep.pilot(manual_quarterly_value(world), 11),
        lambda: ep.submit(PHASED_WIN_PLAN),
        lambda: ep.stop(),
    ):
        with pytest.raises(EpisodeClosed):
            after_fn()


def test_quarterly_episode_50_restart_state_path_persistence_flood(tmp_path):
    world = load_world()
    state_file = tmp_path / "daemon" / "state.json"
    manual_q = manual_quarterly_value(world)

    for i in range(1, 51):
        ep = QuarterlyEpisode(world, max_pilots=24, state_path=state_file)
        if i <= 24:
            res = ep.pilot(manual_q, 11)
            assert res["pilot_budget"] == {"used": i, "max": 24}
        else:
            with pytest.raises(PilotBudgetExceeded):
                ep.pilot(manual_q, 11)
            assert not ep.closed

    mode_bits = stat.S_IMODE(state_file.stat().st_mode)
    assert mode_bits == 0o600

    # 51st restart attempting to inflate max_pilots=999 must stay clamped at 24.
    ep51 = QuarterlyEpisode(world, max_pilots=999, state_path=state_file)
    assert ep51.max_pilots == 24
    with pytest.raises(PilotBudgetExceeded):
        ep51.pilot(manual_q, 11)
    assert ep51.submit(PHASED_WIN_PLAN) == {"terminal": True, "plan": PHASED_WIN_PLAN}

    # 52nd restart stays closed with persisted submission.
    ep52 = QuarterlyEpisode(world, max_pilots=24, state_path=state_file)
    assert ep52.closed
    assert ep52.submission == PHASED_WIN_PLAN
    with pytest.raises(EpisodeClosed):
        ep52.observe()


def test_state_path_rejects_symlink_and_mode_mismatch(tmp_path):
    world = load_world()
    real_state = tmp_path / "real_state.json"
    QuarterlyEpisode(world, state_path=real_state)

    symlink_state = tmp_path / "link_state.json"
    symlink_state.symlink_to(real_state)
    with pytest.raises(ValueError, match="symlink"):
        QuarterlyEpisode(world, state_path=symlink_state)

    dangling_link = tmp_path / "dangling.json"
    dangling_link.symlink_to(tmp_path / "nonexistent.json")
    with pytest.raises(ValueError, match="symlink"):
        QuarterlyEpisode(world, state_path=dangling_link)

    days = tuple(generate(world, s) for s in world["development_seeds"])
    with pytest.raises(ValueError, match="mode"):
        Episode(world, days, state_path=real_state)

    v1_state = tmp_path / "v1_state.json"
    Episode(world, days, state_path=v1_state)
    with pytest.raises(ValueError, match="mode"):
        QuarterlyEpisode(world, state_path=v1_state)


def test_v1_episode_unlimited_by_default_and_optional_max_pilots_and_state_path(tmp_path):
    world = load_world()
    days = tuple(generate(world, s) for s in world["development_seeds"])

    ep_unlimited = Episode(world, days)
    assert ep_unlimited.max_pilots is None
    winner = solve(ep_unlimited)
    assert ep_unlimited.pilot_used == 39
    assert ep_unlimited.submit(winner)["plan"] == winner

    state_file = tmp_path / "v1_bounded.json"
    ep_bounded = Episode(world, days, max_pilots=2, state_path=state_file)
    ep_bounded.pilot(manual_value(), 11)
    ep_reloaded = Episode(world, days, state_path=state_file)
    assert ep_reloaded.max_pilots == 2
    assert ep_reloaded.pilot_used == 1
    ep_reloaded.pilot(manual_value(), 29)
    with pytest.raises(PilotBudgetExceeded):
        ep_reloaded.pilot(manual_value(), 47)


@pytest.mark.parametrize(
    ("kwargs", "missing_quarterly"),
    [
        ({"seeds": []}, False),
        ({"seeds": [11, 11]}, False),
        ({"seeds": [True]}, False),
        ({"seeds": "11"}, False),
        ({"max_pilots": 0}, False),
        ({"max_pilots": -3}, False),
        ({"max_pilots": True}, False),
        ({}, True),
    ],
)
def test_quarterly_episode_validates_constructor_arguments(kwargs, missing_quarterly):
    world = load_world()
    if missing_quarterly:
        world.pop("quarterly", None)
    with pytest.raises(ValueError):
        QuarterlyEpisode(world, **kwargs)


def test_devtools_redteam_and_v1_regression_smoke():
    world = load_world()
    days = tuple(generate(world, s) for s in world["development_seeds"])
    manual_eval = evaluate(world, manual_value(), days)
    assert manual_eval.feasible and not manual_eval.win and (manual_eval.reward_num, manual_eval.reward_den) == (1, 5)

    ref_plan = solve(Episode(world, days))
    ref_eval = evaluate(world, ref_plan, days)
    assert ref_eval.win and F(ref_eval.reward_num, ref_eval.reward_den) > F(1, 5)
