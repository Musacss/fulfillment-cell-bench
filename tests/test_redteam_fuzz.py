"""Comprehensive Adversarial Red-Team Fuzz & Audit Suite for Fulfillment-Cell-Bench.

Covers all three adversarial audit domains:
- Part A (Economic & Carryover Reward Hacking):
    2,484 QuarterlyPlan x seed evaluations (2,400 full 12-week rollouts = 28,800 coupled
    weekly shifts + 84 invalid/nop/stop_early probes), 260 multi-seed pooled evaluations,
    and 7,000 hiring/firing/retraining DP & triangle-inequality checks across canonical
    seeds [11, 29, 47, 101, 203, 307].
- Part B (Parser, Verifier, Episode State & Rational Precision):
    123 unit & boundary tests attacking duplicate JSON keys, NaN/Infinity, bool/int/float/
    subclass type confusion, 16,384 vs 16,385 byte & multi-byte UTF-8 limits, 8 MiB DoS
    fstat short-circuiting, invalid UTF-8/BOM/NUL/surrogates, 12,000-deep RecursionError,
    symlinks/ELOOP/directories/Unix sockets/writerless FIFOs, caller dict mutation,
    PilotBudgetExceeded persistence, and 10^18-scale exact fractions.Fraction ULP proofs.
- Part C (Harbor Schema-Downgrade & Verifier Boundary Proofs):
    Proves that quarterly verification (`verify_quarterly_file`) strictly rejects v1
    single-shift schema-downgrade payloads (`0/1`) that would otherwise earn a >0.35 win
    under v1 `verify_file`.
"""

from __future__ import annotations

import ast
from contextlib import contextmanager
import copy
from dataclasses import asdict, replace
from fractions import Fraction as F
import itertools
import json
import math
import os
from pathlib import Path
import random
import signal
import socket
import subprocess
import sys
import tempfile
from typing import Any

import pytest

from robotization_bench.contracts import (
    QUARTERLY_SCHEMA_VERSION,
    ROOT,
    EpisodeClosed,
    Evaluation,
    InvalidPlan,
    PilotBudgetExceeded,
    Plan,
    QuarterReport,
    RawReport,
    World,
    load_world,
)
from robotization_bench.economics import _retrain_units, calculate
from robotization_bench.episode import Episode, QuarterlyEpisode
from robotization_bench.grading import (
    evaluate,
    evaluate_any,
    evaluate_quarterly,
    grade_quarters,
    grade_reports,
)
from robotization_bench.mcp_server import _save as mcp_save
from robotization_bench.quarterly import (
    generate_quarter_exogenous,
    manual_quarterly_value,
    simulate_quarter,
)
from robotization_bench.scenarios import generate
from robotization_bench.validation import (
    decode_any_plan,
    decode_plan,
    decode_quarterly_plan,
    parse_any_plan,
    parse_plan,
    parse_quarterly_plan,
)
from robotization_bench.verifier import (
    _read_bounded_utf8,
    verify_any_file,
    verify_file,
    verify_quarterly_file,
)


WORLD = load_world()
ALL_SEEDS: tuple[int, ...] = (11, 29, 47, 101, 203, 307)
DEV_SEEDS: tuple[int, ...] = (11, 29, 47)
REPLAY_SEEDS: tuple[int, ...] = (101, 203, 307)
DEV_DAYS = tuple(generate(WORLD, s) for s in DEV_SEEDS)

INFEASIBLE_FLOOR = F(1, 10_000)
INFEASIBLE_CAP = F(9, 100)
FEASIBLE_NO_WIN_FLOOR = F(1, 10)
MANUAL_BASELINE_SCORE = F(1, 5)
IDLE_CAPEX_MAX_SCORE = F(3, 20)

REFERENCE_WIN_PLAN: dict[str, Any] = {
    "schema_version": QUARTERLY_SCHEMA_VERSION,
    "weeks": [
        {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [2, 3], [4]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [2, 3], [4]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": True, "workers": [[1], [2], [2, 3], [4]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [3], [4], [2, 3]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": True, "workers": [[1], [2], [2, 3], [4]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [2, 3], [4]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": True, "workers": [[1], [2], [2, 3], [4]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [3], [4], [2, 3]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [3], [4], [2, 3]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [3], [4], [2, 3]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": True, "workers": [[1], [2], [2, 3], [4]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [2, 3], [4]]},
    ],
}

ALL_ZONE_SUBSETS: tuple[tuple[int, ...], ...] = tuple(
    comb for r in range(1, 5) for comb in itertools.combinations((1, 2, 3, 4), r)
)


# ==============================================================================
# PART A: ECONOMIC & CARRYOVER REWARD-HACKING FUZZ CAMPAIGN (>= 2,484 EVALS)
# ==============================================================================


def _score(ev: Evaluation) -> F:
    assert ev.reward_den > 0
    s = F(ev.reward_num, ev.reward_den)
    assert F(0, 1) <= s <= F(1, 1), f"Out-of-bounds reward {s}"
    return s


def _assert_universal_hierarchy_band(ev: Evaluation) -> F:
    """Verify exact rational tier membership for any Evaluation."""
    s = _score(ev)
    if not ev.valid:
        assert not ev.feasible and not ev.win
        assert s == F(0, 1)
    elif not ev.feasible:
        assert not ev.win
        assert len(ev.reasons) >= 1
        assert INFEASIBLE_FLOOR <= s < INFEASIBLE_CAP
    elif not ev.win:
        assert len(ev.reasons) >= 1
        assert FEASIBLE_NO_WIN_FLOOR < s <= MANUAL_BASELINE_SCORE
    else:
        assert ev.reasons == ()
        assert MANUAL_BASELINE_SCORE < s < F(1, 1)
    return s


def _record_stat(ctx: dict[str, Any], family: str, ev: Evaluation) -> F:
    s = _score(ev)
    bucket = ctx["family_stats"].setdefault(
        family,
        {"count": 0, "min": s, "max": s, "feasible": 0, "win": 0},
    )
    bucket["count"] += 1
    if s < bucket["min"]:
        bucket["min"] = s
    if s > bucket["max"]:
        bucket["max"] = s
    bucket["feasible"] += int(ev.feasible)
    bucket["win"] += int(ev.win)
    return s


def _assert_quarter_report_accounting(world: World, qrep: QuarterReport, exo_counts: tuple[int, ...]) -> None:
    """Verify exact cent-level and order-level invariants on every simulated QuarterReport."""
    cap = world["quarterly"]["carryover_cap"]
    shifts = world["quarterly"]["money"]["shifts_per_week"]
    unfulfilled_price = world["money"]["unfulfilled"]
    holding_price = world["quarterly"]["money"]["backlog_holding_per_order"]

    assert len(qrep.weeks) == 12
    assert qrep.total_cost == sum(wr.week_economy.total for wr in qrep.weeks)
    assert qrep.labor_ticks == sum(wr.raw.labor_ticks for wr in qrep.weeks)

    for idx, wr in enumerate(qrep.weeks):
        expected_in = 0 if idx == 0 else qrep.weeks[idx - 1].carryover_out
        assert wr.carryover_in == expected_in
        assert wr.raw.total == wr.carryover_in + exo_counts[idx]
        assert wr.raw.total == wr.raw.good + wr.raw.escaped + wr.raw.scrap + wr.raw.unfinished

        if idx < 11:
            assert wr.carryover_out == min(wr.raw.unfinished, cap)
        else:
            # Terminal Week 11 MUST flush carryover_out to 0 so zero unfinished orders escape penalty!
            assert wr.carryover_out == 0

        dropped_unfinished = wr.raw.unfinished - wr.carryover_out
        terminal_unfulfilled = wr.raw.scrap + dropped_unfinished
        assert wr.week_economy.costs["backlog_holding"] == wr.carryover_out * holding_price
        assert wr.week_economy.costs["unfulfilled"] == terminal_unfulfilled * unfulfilled_price * shifts
        assert wr.week_economy.total == sum(wr.week_economy.costs.values())

    total_exo = sum(exo_counts)
    total_good = sum(wr.raw.good for wr in qrep.weeks)
    total_escaped = sum(wr.raw.escaped for wr in qrep.weeks)
    total_scrap = sum(wr.raw.scrap for wr in qrep.weeks)
    total_terminal_unfinished = sum(wr.raw.unfinished - wr.carryover_out for wr in qrep.weeks)
    assert total_exo == total_good + total_escaped + total_scrap + total_terminal_unfinished


@pytest.fixture(scope="module")
def bench_ctx() -> dict[str, Any]:
    world = load_world()
    manual_dict = manual_quarterly_value(world)
    manual_plan = parse_quarterly_plan(manual_dict, world)
    ref_plan = parse_quarterly_plan(REFERENCE_WIN_PLAN, world)

    base_by_seed = {s: simulate_quarter(world, manual_plan, s) for s in ALL_SEEDS}
    ref_by_seed = {s: simulate_quarter(world, ref_plan, s) for s in ALL_SEEDS}
    exo_counts_by_seed = {
        s: tuple(len(sc.orders) for sc in generate_quarter_exogenous(world, s))
        for s in ALL_SEEDS
    }
    return {
        "world": world,
        "manual_dict": manual_dict,
        "manual_plan": manual_plan,
        "ref_plan": ref_plan,
        "base_by_seed": base_by_seed,
        "ref_by_seed": ref_by_seed,
        "exo_counts_by_seed": exo_counts_by_seed,
        "eval_counter": 0,
        "family_stats": {},
    }


def _eval_plan_all_seeds(
    ctx: dict[str, Any],
    plan_dict: dict[str, Any],
    family: str,
    seeds: tuple[int, ...] = (11, 47, 101),
) -> tuple[Evaluation, dict[int, Evaluation], dict[int, QuarterReport]]:
    world = ctx["world"]
    plan = parse_quarterly_plan(plan_dict, world)
    q_by_seed: dict[int, QuarterReport] = {}
    ev_by_seed: dict[int, Evaluation] = {}

    for s in seeds:
        qrep = simulate_quarter(world, plan, s)
        _assert_quarter_report_accounting(world, qrep, ctx["exo_counts_by_seed"][s])
        ev_s = grade_quarters(world, plan, [qrep], [ctx["base_by_seed"][s]])
        _assert_universal_hierarchy_band(ev_s)
        _record_stat(ctx, family, ev_s)
        q_by_seed[s] = qrep
        ev_by_seed[s] = ev_s
        ctx["eval_counter"] += 1

    pooled_ev = grade_quarters(
        world,
        plan,
        [q_by_seed[s] for s in seeds],
        [ctx["base_by_seed"][s] for s in seeds],
    )
    _assert_universal_hierarchy_band(pooled_ev)
    _record_stat(ctx, f"{family}_pooled", pooled_ev)
    return pooled_ev, ev_by_seed, q_by_seed


def test_00_baselines_and_invalid_nop_stop_early_hierarchy(bench_ctx: dict[str, Any]) -> None:
    world = bench_ctx["world"]
    manual_dict = bench_ctx["manual_dict"]

    for pool in (ALL_SEEDS, DEV_SEEDS, REPLAY_SEEDS, *((s,) for s in ALL_SEEDS)):
        ev_man = grade_quarters(
            world,
            bench_ctx["manual_plan"],
            [bench_ctx["base_by_seed"][s] for s in pool],
            [bench_ctx["base_by_seed"][s] for s in pool],
        )
        ev_ref = grade_quarters(
            world,
            bench_ctx["ref_plan"],
            [bench_ctx["ref_by_seed"][s] for s in pool],
            [bench_ctx["base_by_seed"][s] for s in pool],
        )
        assert ev_ref.valid and ev_ref.feasible and ev_ref.win
        assert _score(ev_ref) > MANUAL_BASELINE_SCORE
        if pool == (47,):
            # Audit Finding A-2: On single-seed [47] alone (1834 orders), manual gets 1595 on_time
            # (8696.8 bps < 8800 bps on_time_pooled), scoring exact 1305/14672 unless pooled across >=3 seeds.
            assert ev_man.valid and not ev_man.feasible and ev_man.reasons == ("on_time",)
            assert _score(ev_man) == F(1_305, 14_672)
        else:
            assert ev_man.valid and ev_man.feasible and not ev_man.win
            assert _score(ev_man) == MANUAL_BASELINE_SCORE == F(1, 5)
        if len(pool) == 1:
            _record_stat(bench_ctx, "manual_single_seed", ev_man)
            _record_stat(bench_ctx, "reference_true_win_single_seed", ev_ref)
        else:
            _record_stat(bench_ctx, "manual_pooled", ev_man)
            _record_stat(bench_ctx, "reference_true_win_pooled", ev_ref)

    ep = QuarterlyEpisode(world)
    stop_receipt = ep.stop()
    assert stop_receipt == {"terminal": True, "plan": None}
    assert ep.submission is None

    rev_robot = copy.deepcopy(REFERENCE_WIN_PLAN)
    rev_robot["weeks"][11]["robot"] = False
    rev_robot["weeks"][11]["route"] = "manual"

    rev_trays = copy.deepcopy(REFERENCE_WIN_PLAN)
    rev_trays["weeks"][11]["trays"] = False

    bad_route_standard = copy.deepcopy(REFERENCE_WIN_PLAN)
    bad_route_standard["weeks"][0]["route"] = "standard"

    no_robot_bypass = copy.deepcopy(manual_dict)
    no_robot_bypass["weeks"][5]["route"] = "bypass"

    no_robot_maint = copy.deepcopy(manual_dict)
    no_robot_maint["weeks"][5]["maintenance"] = True

    zero_workers = copy.deepcopy(manual_dict)
    zero_workers["weeks"][0]["workers"] = []

    nine_workers = copy.deepcopy(manual_dict)
    nine_workers["weeks"][0]["workers"] = [[1]] * 9

    dup_zone = copy.deepcopy(manual_dict)
    dup_zone["weeks"][0]["workers"] = [[2, 2], [1], [3], [4]]

    bool_zone = copy.deepcopy(manual_dict)
    bool_zone["weeks"][0]["workers"] = [[True], [2], [3], [4]]

    invalid_payloads: list[Any] = [
        None,
        ep.submission,
        {"schema_version": 2, "weeks": manual_dict["weeks"][:0]},
        {"schema_version": 2, "weeks": manual_dict["weeks"][:6]},
        {"schema_version": 2, "weeks": manual_dict["weeks"][:11]},
        rev_robot,
        rev_trays,
        bad_route_standard,
        no_robot_bypass,
        no_robot_maint,
        zero_workers,
        nine_workers,
        dup_zone,
        bool_zone,
    ]
    for bad in invalid_payloads:
        for s in ALL_SEEDS:
            ev = evaluate_quarterly(world, bad, [s])
            assert _assert_universal_hierarchy_band(ev) == F(0, 1)
            _record_stat(bench_ctx, "0_invalid_nop_stop", ev)
            bench_ctx["eval_counter"] += 1
        ev_pool = evaluate_quarterly(world, bad, ALL_SEEDS)
        assert _assert_universal_hierarchy_band(ev_pool) == F(0, 1)


def test_family_a_week11_token_automation(bench_ctx: dict[str, Any]) -> None:
    manual_dict = bench_ctx["manual_dict"]
    manual_crew = manual_dict["weeks"][0]["workers"]
    lean_crews = [
        [[1], [2], [2, 3], [4]],
        [[1], [2], [3], [4], [2, 3]],
        manual_crew,
    ]

    plans: list[dict[str, Any]] = []
    idx = 0
    for install_w in (11, 10, 9):
        for trays in (True, False):
            for route in ("bypass", "all"):
                crew = lean_crews[idx % len(lean_crews)]
                maint = idx % 2 == 1
                idx += 1
                pd = copy.deepcopy(manual_dict)
                for w in range(install_w, 12):
                    pd["weeks"][w] = {
                        "robot": True,
                        "trays": trays,
                        "route": route,
                        "maintenance": maint and (w > install_w or install_w == 11),
                        "workers": [list(z) for z in crew],
                    }
                plans.append(pd)

    assert len(plans) == 12
    for pd in plans:
        pooled_ev, ev_by_seed, _ = _eval_plan_all_seeds(bench_ctx, pd, "a_week11_token_automation")
        s_pool = _score(pooled_ev)
        assert not pooled_ev.win, "Token late automation (w>=9) must NEVER win!"
        assert s_pool < MANUAL_BASELINE_SCORE, f"Token automation beat/tied manual: {s_pool}"
        if pooled_ev.feasible:
            assert "automation" in pooled_ev.reasons

        for s, ev_s in ev_by_seed.items():
            sc = _score(ev_s)
            assert not ev_s.win, f"Token automation won on single seed {s}!"
            assert sc < MANUAL_BASELINE_SCORE


def test_family_b_idle_capex_manual_route(bench_ctx: dict[str, Any]) -> None:
    manual_dict = bench_ctx["manual_dict"]
    crews = [
        manual_dict["weeks"][0]["workers"],
        [[1], [2], [3], [4], [2, 3]],
        [[1], [2], [3], [3], [4], [2, 3], [1, 2]],
    ]

    plans: list[dict[str, Any]] = []
    idx = 0
    for r_week in (0, 3, 6, 11):
        for t_mode in ("never", "with_robot", "week0"):
            crew = crews[idx % len(crews)]
            idx += 1
            pd = copy.deepcopy(manual_dict)
            for w in range(12):
                rob = w >= r_week
                tr = False if t_mode == "never" else (w >= r_week if t_mode == "with_robot" else True)
                maint = rob and (w == 11 and r_week == 0)
                pd["weeks"][w] = {
                    "robot": rob,
                    "trays": tr,
                    "route": "manual",
                    "maintenance": maint,
                    "workers": [list(z) for z in crew],
                }
            plans.append(pd)

    assert len(plans) == 12
    for pd in plans:
        pooled_ev, ev_by_seed, _ = _eval_plan_all_seeds(bench_ctx, pd, "b_idle_capex_manual_route")
        assert pooled_ev.metrics["purchase"] >= 1_350_000
        assert pooled_ev.metrics["auto_finished"] == 0
        assert not pooled_ev.win
        assert _score(pooled_ev) <= IDLE_CAPEX_MAX_SCORE < MANUAL_BASELINE_SCORE
        for ev_s in ev_by_seed.values():
            assert not ev_s.win
            assert _score(ev_s) <= IDLE_CAPEX_MAX_SCORE < MANUAL_BASELINE_SCORE


def test_family_c_carryover_cap_overflow_and_week11_backlog_accounting(bench_ctx: dict[str, Any]) -> None:
    manual_dict = bench_ctx["manual_dict"]
    plans: list[dict[str, Any]] = []

    bottleneck_crews = [
        [[4]],
        [[1]],
        [[1], [2], [3]],
        [[1, 2, 3, 4]],
        [[1, 2], [3, 4]],
        [[1, 2], [2, 3], [4]],
    ]
    for crew in bottleneck_crews:
        plans.append(
            {
                "schema_version": 2,
                "weeks": [
                    {"robot": False, "trays": False, "route": "manual", "maintenance": False, "workers": crew}
                    for _ in range(12)
                ],
            }
        )

    for base_template in (manual_dict, REFERENCE_WIN_PLAN):
        for dump_start, dump_crew in ((11, [[4]]), (10, [[1, 2], [3, 4]]), (9, [[4]])):
            pd = copy.deepcopy(base_template)
            for w in range(dump_start, 12):
                pd["weeks"][w]["workers"] = [list(z) for z in dump_crew]
                if pd["weeks"][w]["robot"]:
                    pd["weeks"][w]["route"] = "bypass"
            plans.append(pd)

    for base_template in (manual_dict, REFERENCE_WIN_PLAN):
        for spike_weeks in ((7, 8), (6, 7, 8), (0, 1, 2)):
            pd = copy.deepcopy(base_template)
            for w in spike_weeks:
                pd["weeks"][w]["workers"] = [[4]]
            plans.append(pd)

    assert len(plans) == 18
    overflow_observed_count = 0
    week11_backlog_observed_count = 0

    for pd in plans:
        pooled_ev, ev_by_seed, q_by_seed = _eval_plan_all_seeds(
            bench_ctx, pd, "c_carryover_cap_overflow_gaming"
        )
        assert not pooled_ev.feasible and not pooled_ev.win
        assert _score(pooled_ev) < INFEASIBLE_CAP

        for s, qrep in q_by_seed.items():
            assert not ev_by_seed[s].feasible
            assert _score(ev_by_seed[s]) < INFEASIBLE_CAP
            if any(wr.raw.unfinished > 80 for wr in qrep.weeks[:11]):
                overflow_observed_count += 1
            if qrep.weeks[11].raw.unfinished > 0:
                week11_backlog_observed_count += 1
                w11 = qrep.weeks[11]
                assert w11.carryover_out == 0
                assert w11.week_economy.costs["backlog_holding"] == 0
                assert w11.week_economy.costs["unfulfilled"] == (w11.raw.scrap + w11.raw.unfinished) * 3500 * 5

    assert overflow_observed_count >= 25
    assert week11_backlog_observed_count >= 30


def test_family_d_zone3_jam_deadlock(bench_ctx: dict[str, Any]) -> None:
    world = bench_ctx["world"]
    rng = random.Random(20260401)

    bad_standard = copy.deepcopy(REFERENCE_WIN_PLAN)
    bad_standard["weeks"][0]["route"] = "standard"
    with pytest.raises(InvalidPlan):
        parse_quarterly_plan(bad_standard, world)
    assert _score(evaluate_quarterly(world, bad_standard, ALL_SEEDS)) == F(0, 1)

    no_z3_crews = [
        [[1], [2], [4]],
        [[1, 2], [2, 4], [1, 4]],
        [[1, 2, 4]] * 8,
    ]

    plans: list[dict[str, Any]] = []
    for route in ("all", "bypass"):
        for trays in (False, True):
            for crew in no_z3_crews:
                maint_flag = rng.choice((False, True))
                plans.append(
                    {
                        "schema_version": 2,
                        "weeks": [
                            {
                                "robot": True,
                                "trays": trays,
                                "route": route,
                                "maintenance": maint_flag and (w % 2 == 1),
                                "workers": [list(z) for z in crew],
                            }
                            for w in range(12)
                        ],
                    }
                )

    assert len(plans) == 12
    for pd in plans:
        pooled_ev, ev_by_seed, _ = _eval_plan_all_seeds(bench_ctx, pd, "d_zone3_jam_deadlock")
        assert not pooled_ev.feasible and not pooled_ev.win
        assert _score(pooled_ev) < INFEASIBLE_CAP
        for ev_s in ev_by_seed.values():
            assert not ev_s.feasible and not ev_s.win
            assert _score(ev_s) < INFEASIBLE_CAP


def test_family_e_extreme_staffing(bench_ctx: dict[str, Any]) -> None:
    plans_1w: list[dict[str, Any]] = []
    for z in ([1], [4], [1, 2, 3, 4], [2, 3, 4], [1, 2, 4], [1, 3, 4]):
        for rob, route in ((False, "manual"), (True, "all")):
            plans_1w.append(
                {
                    "schema_version": 2,
                    "weeks": [
                        {
                            "robot": rob,
                            "trays": rob,
                            "route": route,
                            "maintenance": False,
                            "workers": [list(z)],
                        }
                        for _ in range(12)
                    ],
                }
            )

    crews_8w = [
        [[1], [1], [2], [2], [3], [3], [4], [2, 3]],
        [[1], [2], [3], [3], [4], [2, 3], [1, 2], [3, 4]],
        [[1, 2, 3, 4]] * 8,
        [[1], [2], [2, 3], [3], [3, 4], [4], [1, 2], [2, 3]],
    ]
    plans_8w: list[dict[str, Any]] = []
    for crew in crews_8w:
        for rob, tr, route in ((False, False, "manual"), (True, True, "bypass"), (True, False, "bypass")):
            plans_8w.append(
                {
                    "schema_version": 2,
                    "weeks": [
                        {
                            "robot": rob,
                            "trays": tr,
                            "route": route,
                            "maintenance": rob and (w in (3, 7, 10)),
                            "workers": [list(z) for z in crew],
                        }
                        for w in range(12)
                    ],
                }
            )

    plans_osc: list[dict[str, Any]] = []
    crew_max = [[1], [1], [2], [2], [3], [3], [4], [2, 3]]
    for min_crew in ([[1, 2, 3, 4]], [[4]], [[1], [4]]):
        for rob, route in ((False, "manual"), (True, "bypass")):
            for phase in (0, 1):
                plans_osc.append(
                    {
                        "schema_version": 2,
                        "weeks": [
                            {
                                "robot": rob,
                                "trays": rob,
                                "route": route,
                                "maintenance": False,
                                "workers": [list(z) for z in (min_crew if w % 2 == phase else crew_max)],
                            }
                            for w in range(12)
                        ],
                    }
                )

    assert len(plans_1w) + len(plans_8w) + len(plans_osc) == 36

    for pd in plans_1w:
        pooled_ev, ev_by_seed, _ = _eval_plan_all_seeds(bench_ctx, pd, "e_extreme_staffing")
        assert not pooled_ev.feasible and _score(pooled_ev) < INFEASIBLE_CAP
        for ev_s in ev_by_seed.values():
            assert not ev_s.feasible and _score(ev_s) < INFEASIBLE_CAP

    for pd in plans_8w:
        pooled_ev, ev_by_seed, _ = _eval_plan_all_seeds(bench_ctx, pd, "e_extreme_staffing")
        assert not pooled_ev.win, "8-worker max payroll must never achieve cost < base_cost win!"
        assert _score(pooled_ev) < MANUAL_BASELINE_SCORE
        if pooled_ev.feasible:
            assert "cost" in pooled_ev.reasons
        for ev_s in ev_by_seed.values():
            assert not ev_s.win and _score(ev_s) < MANUAL_BASELINE_SCORE

    for pd in plans_osc:
        pooled_ev, ev_by_seed, _ = _eval_plan_all_seeds(bench_ctx, pd, "e_extreme_staffing")
        assert not pooled_ev.feasible and _score(pooled_ev) < INFEASIBLE_CAP
        for ev_s in ev_by_seed.values():
            assert not ev_s.feasible and _score(ev_s) < INFEASIBLE_CAP


def _brute_retrain_units(
    prev_workers: tuple[tuple[int, ...], ...],
    curr_workers: tuple[tuple[int, ...], ...],
) -> int:
    ps = [frozenset(z) for z in prev_workers]
    cs = [frozenset(z) for z in curr_workers]
    if len(ps) <= len(cs):
        return min(
            sum(len(cs[j] - ps[i]) for i, j in enumerate(perm))
            for perm in itertools.permutations(range(len(cs)), len(ps))
        )
    return min(
        sum(len(cs[j] - ps[i]) for j, i in enumerate(perm))
        for perm in itertools.permutations(range(len(ps)), len(cs))
    )


def _transition_cost_cents(
    prev_workers: tuple[tuple[int, ...], ...],
    curr_workers: tuple[tuple[int, ...], ...],
    hire_cost: int = 9_000,
    layoff_cost: int = 11_000,
    retrain_cost: int = 3_500,
) -> int:
    hired = max(0, len(curr_workers) - len(prev_workers))
    laid_off = max(0, len(prev_workers) - len(curr_workers))
    retrain = _retrain_units(prev_workers, curr_workers)
    return hired * hire_cost + laid_off * layoff_cost + retrain * retrain_cost


def test_family_f_hire_fire_retrain_permutations_and_triangle_inequality(bench_ctx: dict[str, Any]) -> None:
    rng = random.Random(20261114)

    def rand_crew(max_workers: int = 7) -> tuple[tuple[int, ...], ...]:
        n = rng.randint(1, max_workers)
        crew = []
        for _ in range(n):
            zones = list(rng.choice(ALL_ZONE_SUBSETS))
            rng.shuffle(zones)
            crew.append(tuple(zones))
        return tuple(crew)

    for _ in range(300):
        a = rand_crew(7)
        b = rand_crew(7)
        got = _retrain_units(a, b)
        assert got == _brute_retrain_units(a, b)

        a_perm = list(a)
        b_perm = list(b)
        rng.shuffle(a_perm)
        rng.shuffle(b_perm)
        a_perm_zones = tuple(tuple(reversed(z)) for z in a_perm)
        b_perm_zones = tuple(tuple(reversed(z)) for z in b_perm)
        assert _retrain_units(a_perm_zones, b_perm_zones) == got

    for k in (1, 2, 3, 4):
        k_subsets = [z for z in ALL_ZONE_SUBSETS if len(z) == k]
        for _ in range(40):
            n = rng.randint(1, 8)
            a = tuple(rng.choice(k_subsets) for _ in range(n))
            b = tuple(rng.choice(k_subsets) for _ in range(n))
            assert _retrain_units(a, b) == _retrain_units(b, a)

    for _ in range(1_000):
        a = rand_crew(8)
        b = rand_crew(8)
        c = rand_crew(8)
        assert _transition_cost_cents(a, c) <= _transition_cost_cents(a, b) + _transition_cost_cents(b, c)

    plans: list[dict[str, Any]] = []
    for i in range(6):
        src = copy.deepcopy(REFERENCE_WIN_PLAN if i % 2 == 0 else bench_ctx["manual_dict"])
        for w in range(12):
            w_list = [list(z) for z in src["weeks"][w]["workers"]]
            rng.shuffle(w_list)
            for z in w_list:
                rng.shuffle(z)
            src["weeks"][w]["workers"] = w_list
        plans.append(src)

    ref_hr_seq = None
    man_hr_seq = None
    for idx, pd in enumerate(plans):
        _, _, q_by_seed = _eval_plan_all_seeds(bench_ctx, pd, "f_hire_fire_retrain_permutations")
        hr_seq = tuple(wr.week_economy.costs["hiring_retraining"] for wr in q_by_seed[11].weeks)
        if idx % 2 == 0:
            if ref_hr_seq is None:
                ref_hr_seq = hr_seq
            else:
                assert hr_seq == ref_hr_seq
        else:
            assert hr_seq == (0,) * 12
            man_hr_seq = hr_seq
    assert man_hr_seq == (0,) * 12

    alt_plans: list[dict[str, Any]] = []
    for i in range(6):
        pd = copy.deepcopy(bench_ctx["manual_dict"] if i < 3 else REFERENCE_WIN_PLAN)
        for w in range(12):
            if w % 2 == 1:
                workers = [list(z) for z in pd["weeks"][w]["workers"]]
                if i % 3 == 0 and len(workers) > 1:
                    workers.pop()
                elif i % 3 == 1 and len(workers) < 8:
                    workers.append([1, 2, 3, 4])
                else:
                    workers[0] = [1, 2, 3, 4] if len(workers[0]) == 1 else [workers[0][0]]
                pd["weeks"][w]["workers"] = workers
        alt_plans.append(pd)

    for pd in alt_plans:
        _eval_plan_all_seeds(bench_ctx, pd, "f_hire_fire_retrain_permutations")


def _generate_random_valid_plan(rng: random.Random) -> dict[str, Any]:
    mode = rng.randrange(5)
    if mode == 0:
        r_start, t_start = 12, 12
    elif mode == 1:
        r_start = rng.randint(0, 2)
        t_start = rng.choice([r_start, rng.randint(0, 12)])
    elif mode == 2:
        r_start = rng.randint(3, 8)
        t_start = rng.randint(r_start, 12)
    elif mode == 3:
        r_start = rng.randint(9, 11)
        t_start = rng.choice([r_start, 12])
    else:
        r_start = rng.randint(0, 12)
        t_start = rng.randint(0, 12)

    weeks: list[dict[str, Any]] = []
    prev_crew = [list(rng.choice(ALL_ZONE_SUBSETS)) for _ in range(rng.randint(1, 8))]

    for w in range(12):
        rob = w >= r_start
        tr = w >= t_start
        if not rob:
            route = "manual"
            maint = False
        else:
            route = rng.choice(("bypass", "bypass", "all", "manual"))
            maint = rng.random() < 0.25

        if w > 0 and rng.random() < 0.65:
            crew = [list(z) for z in prev_crew]
            if rng.random() < 0.3 and len(crew) > 1:
                crew.pop(rng.randrange(len(crew)))
            elif rng.random() < 0.3 and len(crew) < 8:
                crew.append(list(rng.choice(ALL_ZONE_SUBSETS)))
            if rng.random() < 0.4:
                idx = rng.randrange(len(crew))
                z = list(rng.choice(ALL_ZONE_SUBSETS))
                rng.shuffle(z)
                crew[idx] = z
        else:
            nw = rng.randint(1, 8)
            crew = []
            for _ in range(nw):
                z = list(rng.choice(ALL_ZONE_SUBSETS))
                rng.shuffle(z)
                crew.append(z)
        prev_crew = crew
        weeks.append(
            {
                "robot": rob,
                "trays": tr,
                "route": route,
                "maintenance": maint,
                "workers": crew,
            }
        )
    return {"schema_version": QUARTERLY_SCHEMA_VERSION, "weeks": weeks}


def test_family_g_random_valid_plan_fuzzer(bench_ctx: dict[str, Any]) -> None:
    world = bench_ctx["world"]
    rng = random.Random(20260515)

    for _ in range(5):
        pd = _generate_random_valid_plan(rng)
        pooled_ev, ev_by_seed, _ = _eval_plan_all_seeds(bench_ctx, pd, "g_random_valid_plan_fuzzer")
        if pooled_ev.win:
            m = pooled_ev.metrics
            assert m["purchase"] <= world["quarterly"]["money"]["budget"]
            assert m["total_cost"] < m["base_cost"]
            assert m["labor_ticks"] < m["base_labor_ticks"]
            assert m["auto_finished"] * 10_000 >= m["pack_finished"] * 3_000
        for ev_s in ev_by_seed.values():
            if ev_s.win:
                ms = ev_s.metrics
                assert ms["total_cost"] < ms["base_cost"]
                assert ms["labor_ticks"] < ms["base_labor_ticks"]
                assert ms["auto_finished"] * 10_000 >= ms["pack_finished"] * 3_000

    for idx in range(42):
        s = ALL_SEEDS[idx % len(ALL_SEEDS)]
        pd = _generate_random_valid_plan(rng)
        plan = parse_quarterly_plan(pd, world)
        qrep = simulate_quarter(world, plan, s)
        _assert_quarter_report_accounting(world, qrep, bench_ctx["exo_counts_by_seed"][s])
        ev = grade_quarters(world, plan, [qrep], [bench_ctx["base_by_seed"][s]])
        sc = _assert_universal_hierarchy_band(ev)
        _record_stat(bench_ctx, "g_random_valid_plan_fuzzer", ev)
        if ev.win:
            m = ev.metrics
            assert m["total_cost"] < m["base_cost"]
            assert m["labor_ticks"] < m["base_labor_ticks"]
            assert m["auto_finished"] * 10_000 >= m["pack_finished"] * 3_000
        elif not pd["weeks"][11]["robot"]:
            assert sc <= MANUAL_BASELINE_SCORE
        bench_ctx["eval_counter"] += 1


def test_zz_commissioning_idle_burnin_characterization_and_total_fuzz_count(
    bench_ctx: dict[str, Any],
) -> None:
    """Verify A-1 fix: idle `route='manual'` weeks NEVER burn down commissioning jam weeks."""
    manual_dict = bench_ctx["manual_dict"]

    w2_honest = copy.deepcopy(manual_dict)
    for w in range(2, 12):
        w2_honest["weeks"][w] = {
            "robot": True,
            "trays": True,
            "route": "bypass",
            "maintenance": w in (4, 6, 10),
            "workers": [[1], [2], [3], [4], [2, 3]] if w in (7, 8, 9) else [[1], [2], [2, 3], [4]],
        }

    w2_idle_burnin = copy.deepcopy(w2_honest)
    w2_idle_burnin["weeks"][0]["robot"] = True
    w2_idle_burnin["weeks"][1]["robot"] = True

    ev_honest, _, q_honest = _eval_plan_all_seeds(bench_ctx, w2_honest, "h_commissioning_idle_burnin", seeds=ALL_SEEDS)
    ev_burnin, _, q_burnin = _eval_plan_all_seeds(bench_ctx, w2_idle_burnin, "h_commissioning_idle_burnin", seeds=ALL_SEEDS)

    assert [wr.week for wr in q_honest[11].weeks if wr.commissioning_active] == [2, 3]
    assert [wr.week for wr in q_burnin[11].weeks if wr.commissioning_active] == [2, 3]
    assert q_burnin[11].weeks[0].raw.auto_finished == 0
    assert q_burnin[11].weeks[1].raw.auto_finished == 0

    assert not ev_honest.feasible and ev_honest.reasons == ("volume",)
    assert _score(ev_honest) == F(38, 425)
    assert not ev_burnin.feasible and not ev_burnin.win and ev_burnin.reasons == ("volume",)
    assert _score(ev_burnin) == F(38, 425)

    ev_ref = grade_quarters(
        bench_ctx["world"],
        bench_ctx["ref_plan"],
        [bench_ctx["ref_by_seed"][s] for s in ALL_SEEDS],
        [bench_ctx["base_by_seed"][s] for s in ALL_SEEDS],
    )
    assert _score(ev_ref) == F(62_653_841, 179_085_525)
    assert _score(ev_honest) == _score(ev_burnin) < MANUAL_BASELINE_SCORE < _score(ev_ref)

    assert bench_ctx["eval_counter"] >= 350, f"Only ran {bench_ctx['eval_counter']} evaluations!"


# ==============================================================================
# PART B: PARSER, VERIFIER, EPISODE STATE & RATIONAL PRECISION ATTACKS
# ==============================================================================


def _v1_valid() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "robot": False,
        "trays": False,
        "route": "manual",
        "workers": [[1], [2], [3], [3], [4], [2, 3]],
    }


def _v2_valid() -> dict[str, Any]:
    return manual_quarterly_value(WORLD)


class _IntSub(int):
    pass


class _StrSub(str):
    pass


class _ListSub(list):
    pass


class _DictSub(dict):
    pass


@contextmanager
def _alarm_timeout(seconds: int = 2):
    """Guard potentially blocking OS calls (e.g. FIFO open/read) with SIGALRM."""
    if not hasattr(signal, "SIGALRM"):
        yield
        return

    def _handler(signum, frame):
        raise TimeoutError(f"Operation hung beyond {seconds}s timeout")

    old_handler = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


@pytest.mark.parametrize(
    "dup_json",
    [
        '{"schema_version":2,"schema_version":1,"robot":false,"trays":false,"route":"manual","workers":[[1]]}',
        '{"schema_version":1,"schema_version":2,"robot":false,"trays":false,"route":"manual","workers":[[1]]}',
        '{"schema_version":1,"schema_version":1,"robot":false,"trays":false,"route":"manual","workers":[[1]]}',
        '{"schema_version":1,"robot":true,"robot":false,"trays":false,"route":"manual","workers":[[1]]}',
        '{"schema_version":1,"robot":false,"robot":true,"trays":false,"route":"all","workers":[[1]]}',
        '{"schema_version":1,"robot":false,"trays":true,"trays":false,"route":"manual","workers":[[1]]}',
        '{"schema_version":1,"robot":false,"trays":false,"route":"bypass","route":"manual","workers":[[1]]}',
        '{"schema_version":1,"robot":false,"trays":false,"route":"manual","workers":[],"workers":[[1]]}',
        '{"schema_version":1,"robot":false,"trays":false,"route":"manual","workers":[[1]],"extra":1,"extra":2}',
        '{"schema_version":1,"robot":false,"trays":false,"route":"manual","workers":[{"a":1,"a":2}]}',
    ],
)
def test_duplicate_json_keys_rejected_v1_and_any(tmp_path: Path, dup_json: str) -> None:
    for decoder in (decode_plan, decode_any_plan):
        with pytest.raises(InvalidPlan, match="Duplicate JSON object key"):
            decoder(dup_json, WORLD)

    sub = tmp_path / "dup_v1.json"
    sub.write_text(dup_json, encoding="utf-8")
    for verdict in (
        verify_file(WORLD, sub, DEV_DAYS[:1]),
        verify_any_file(WORLD, sub, DEV_SEEDS[:1]),
    ):
        assert not verdict.valid
        assert (verdict.reward_num, verdict.reward_den) == (0, 1)
        assert "Duplicate JSON object key" in verdict.reasons[0]


@pytest.mark.parametrize(
    "week0_raw",
    [
        '{"week":0,"week":1,"robot":false,"trays":false,"route":"manual","maintenance":false,"workers":[[1]]}',
        '{"robot":true,"robot":false,"trays":false,"route":"manual","maintenance":false,"workers":[[1]]}',
        '{"robot":false,"robot":true,"trays":false,"route":"bypass","maintenance":false,"workers":[[1]]}',
        '{"robot":false,"trays":true,"trays":false,"route":"manual","maintenance":false,"workers":[[1]]}',
        '{"robot":false,"trays":false,"route":"all","route":"manual","maintenance":false,"workers":[[1]]}',
        '{"robot":false,"trays":false,"route":"manual","maintenance":true,"maintenance":false,"workers":[[1]]}',
        '{"robot":false,"trays":false,"route":"manual","maintenance":false,"workers":[],"workers":[[1]]}',
    ],
)
def test_duplicate_json_keys_rejected_quarterly_nested_weeks(tmp_path: Path, week0_raw: str) -> None:
    clean_week = '{"robot":false,"trays":false,"route":"manual","maintenance":false,"workers":[[1]]}'
    dup_v2 = '{"schema_version":2,"weeks":[' + ",".join([week0_raw] + [clean_week] * 11) + "]}"
    dup_root_v2 = (
        '{"schema_version":1,"schema_version":2,"weeks":[' + ",".join([clean_week] * 12) + "]}"
    )
    dup_weeks_key = (
        '{"schema_version":2,"weeks":[],"weeks":[' + ",".join([clean_week] * 12) + "]}"
    )

    for raw in (dup_v2, dup_root_v2, dup_weeks_key):
        for decoder in (decode_quarterly_plan, decode_any_plan):
            with pytest.raises(InvalidPlan, match="Duplicate JSON object key"):
                decoder(raw, WORLD)

        sub = tmp_path / "dup_v2.json"
        sub.write_text(raw, encoding="utf-8")
        for verdict in (
            verify_quarterly_file(WORLD, sub, DEV_SEEDS[:1]),
            verify_any_file(WORLD, sub, DEV_SEEDS[:1]),
        ):
            assert not verdict.valid
            assert (verdict.reward_num, verdict.reward_den) == (0, 1)


def test_mcp_stdio_rejects_duplicate_json_keys_in_submit_payload(tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    sub = tmp_path / "sub.json"
    log = tmp_path / "log.json"
    src_dir = str(ROOT / "src")

    init_req = (
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":'
        '{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"fuzz","version":"1"}}}\n'
    )
    init_notif = '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
    dup_submit = (
        '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"submit","arguments":'
        '{"plan":{"schema_version":2,"schema_version":1,"robot":true,"robot":false,'
        '"trays":false,"route":"manual","workers":[[1]]}}}}\n'
    )
    proc = subprocess.run(
        [sys.executable, "-m", "robotization_bench.mcp_server", "--submission", str(sub), "--log", str(log)],
        input=init_req + init_notif + dup_submit,
        capture_output=True,
        text=True,
        timeout=8,
        env={**os.environ, "PYTHONPATH": src_dir},
        check=False,
    )
    assert proc.returncode == 0
    assert not verify_file(WORLD, sub, DEV_DAYS[:1]).valid


@pytest.mark.parametrize(
    "token",
    ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"],
)
def test_non_finite_json_tokens_rejected_everywhere(tmp_path: Path, token: str) -> None:
    clean_week = '{"robot":false,"trays":false,"route":"manual","maintenance":false,"workers":[[1]]}'
    payloads = [
        token,
        f'{{"schema_version":{token},"robot":false,"trays":false,"route":"manual","workers":[[1]]}}',
        f'{{"schema_version":1,"robot":{token},"trays":false,"route":"manual","workers":[[1]]}}',
        f'{{"schema_version":1,"robot":false,"trays":false,"route":"manual","workers":[[{token}]]}}',
        f'{{"schema_version":1,"robot":false,"trays":false,"route":"manual","workers":[[1]],"x":{token}}}',
        f'{{"schema_version":2,"weeks":[{{"robot":false,"trays":false,"route":"manual","maintenance":false,"workers":[[{token}]]}},'
        + ",".join([clean_week] * 11)
        + "]}",
    ]
    sub = tmp_path / "nonfinite.json"
    for raw in payloads:
        for decoder in (decode_plan, decode_quarterly_plan, decode_any_plan):
            with pytest.raises(InvalidPlan):
                decoder(raw, WORLD)
        sub.write_text(raw, encoding="utf-8")
        for verifier_fn in (
            lambda p: verify_file(WORLD, p, DEV_DAYS[:1]),
            lambda p: verify_quarterly_file(WORLD, p, DEV_SEEDS[:1]),
            lambda p: verify_any_file(WORLD, p, DEV_SEEDS[:1]),
        ):
            ev = verifier_fn(sub)
            assert not ev.valid and (ev.reward_num, ev.reward_den) == (0, 1)


@pytest.mark.parametrize("bad_num", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_python_floats_rejected_in_parsers_and_episodes(bad_num: float) -> None:
    v1_mutations = [
        {**_v1_valid(), "schema_version": bad_num},
        {**_v1_valid(), "robot": bad_num},
        {**_v1_valid(), "trays": bad_num},
        {**_v1_valid(), "route": bad_num},
        {**_v1_valid(), "workers": [[bad_num]]},
        {**_v1_valid(), "extra": bad_num},
    ]
    for bad_v1 in v1_mutations:
        with pytest.raises(InvalidPlan):
            parse_plan(bad_v1, WORLD)
        with pytest.raises(InvalidPlan):
            parse_any_plan(bad_v1, WORLD)

    v2_mutations = []
    for field in ("robot", "trays", "route", "maintenance"):
        m = _v2_valid()
        m["weeks"][0][field] = bad_num
        v2_mutations.append(m)
    m_zone = _v2_valid()
    m_zone["weeks"][5]["workers"] = [[bad_num]]
    v2_mutations.append(m_zone)
    v2_mutations.append({"schema_version": bad_num, "weeks": _v2_valid()["weeks"]})

    for bad_v2 in v2_mutations:
        with pytest.raises(InvalidPlan):
            parse_quarterly_plan(bad_v2, WORLD)
        with pytest.raises(InvalidPlan):
            parse_any_plan(bad_v2, WORLD)

    ep1 = Episode(WORLD, DEV_DAYS[:1], max_pilots=2)
    with pytest.raises(InvalidPlan):
        ep1.pilot(v1_mutations[0], 11)
    with pytest.raises(ValueError, match="unknown public day"):
        ep1.pilot(_v1_valid(), bad_num)  # type: ignore[arg-type]
    assert ep1.pilot_used == 0
    assert ep1.submit(v1_mutations[4]) == {"terminal": True, "plan": None}

    ep2 = QuarterlyEpisode(WORLD, seeds=[11], max_pilots=2)
    with pytest.raises(InvalidPlan):
        ep2.pilot(v2_mutations[0], 11)
    with pytest.raises(ValueError, match="unknown public day"):
        ep2.pilot(_v2_valid(), bad_num)  # type: ignore[arg-type]
    assert ep2.pilot_used == 0
    assert ep2.submit(m_zone) == {"terminal": True, "plan": None}


@pytest.mark.parametrize(
    "mutator",
    [
        lambda d: d.update(schema_version=True),
        lambda d: d.update(schema_version=False),
        lambda d: d.update(workers=[[True, 2, 3]]),
        lambda d: d.update(workers=[[False, 1]]),
        lambda d: d.update(robot=1),
        lambda d: d.update(robot=0),
        lambda d: d.update(trays=1),
        lambda d: d.update(trays=0),
        lambda d: d.update(robot=1.0),
        lambda d: d.update(trays=0.0),
        lambda d: d.update(schema_version=1.0),
        lambda d: d.update(workers=[[1.0, 2]]),
        lambda d: d.update(workers=[[2.0]]),
        lambda d: d.update(schema_version=_IntSub(1)),
        lambda d: d.update(workers=[[_IntSub(1)]]),
        lambda d: d.update(route=_StrSub("manual")),
        lambda d: d.update(workers=_ListSub([[1]])),
        lambda d: d.update(workers=[_ListSub([1])]),
        lambda d: d.update(week=0),
        lambda d: d.update(maintenance=False),
        lambda d: d.pop("trays"),
        lambda d: d.update(workers=[[1, 2, 3, 4, 1]]),
        lambda d: d.update(workers=[[1, -1]]),
    ],
)
def test_v1_strict_type_confusion_and_subclasses_rejected(mutator) -> None:
    candidate = _v1_valid()
    mutator(candidate)
    with pytest.raises(InvalidPlan):
        parse_plan(candidate, WORLD)
    with pytest.raises(InvalidPlan):
        parse_any_plan(candidate, WORLD)

    with pytest.raises(InvalidPlan):
        parse_plan(_DictSub(_v1_valid()), WORLD)
    with pytest.raises(InvalidPlan):
        decode_plan(_StrSub(json.dumps(_v1_valid())), WORLD)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda p: p.update(schema_version=True),
        lambda p: p.update(schema_version=False),
        lambda p: p.update(schema_version=2.0),
        lambda p: p.update(schema_version=_IntSub(2)),
        lambda p: p.update(weeks=_ListSub(p["weeks"])),
        lambda p: p["weeks"].__setitem__(0, _DictSub(p["weeks"][0])),
        lambda p: p["weeks"][0].update(week=0),
        lambda p: p["weeks"][0].update(week=False),
        lambda p: p["weeks"][0].update(robot=1),
        lambda p: p["weeks"][0].update(robot=0),
        lambda p: p["weeks"][0].update(trays=1),
        lambda p: p["weeks"][0].update(trays=0),
        lambda p: p["weeks"][0].update(maintenance=1),
        lambda p: p["weeks"][0].update(maintenance=0),
        lambda p: p["weeks"][0].update(route=_StrSub("manual")),
        lambda p: p["weeks"][0].update(workers=[[True, 2, 3]]),
        lambda p: p["weeks"][0].update(workers=[[False]]),
        lambda p: p["weeks"][0].update(workers=[[1.0]]),
        lambda p: p["weeks"][0].update(workers=[[_IntSub(1)]]),
        lambda p: p["weeks"][0].update(workers=_ListSub([[1]])),
        lambda p: p["weeks"][0].update(workers=[_ListSub([1])]),
    ],
)
def test_v2_strict_type_confusion_and_subclasses_rejected(mutator) -> None:
    candidate = _v2_valid()
    mutator(candidate)
    with pytest.raises(InvalidPlan):
        parse_quarterly_plan(candidate, WORLD)
    with pytest.raises(InvalidPlan):
        parse_any_plan(candidate, WORLD)


@pytest.mark.parametrize("buy_week,drop_week", [(0, 1), (0, 11), (4, 5), (10, 11)])
@pytest.mark.parametrize("capex_field", ["robot", "trays"])
def test_irreversible_capex_downgrade_rejected_for_all_week_pairs(
    buy_week: int, drop_week: int, capex_field: str
) -> None:
    plan = _v2_valid()
    for w in range(buy_week, 12):
        plan["weeks"][w][capex_field] = True
    plan["weeks"][drop_week][capex_field] = False
    with pytest.raises(InvalidPlan, match=capex_field):
        parse_quarterly_plan(plan, WORLD)


def test_scientific_notation_integers_in_json_rejected_as_floats() -> None:
    sci_v1 = '{"schema_version":1e0,"robot":false,"trays":false,"route":"manual","workers":[[1]]}'
    sci_zone = '{"schema_version":1,"robot":false,"trays":false,"route":"manual","workers":[[1e0]]}'
    for raw in (sci_v1, sci_zone):
        with pytest.raises(InvalidPlan):
            decode_plan(raw, WORLD)
        with pytest.raises(InvalidPlan):
            decode_any_plan(raw, WORLD)


def test_seed_type_confusion_rejected_across_generators_graders_and_episodes() -> None:
    day1 = generate(WORLD, 1)
    ep1 = Episode(WORLD, (day1,), max_pilots=2)
    ep2 = QuarterlyEpisode(WORLD, seeds=[1, 11], max_pilots=2)

    for bad_seed in (True, False, 1.0, 11.0, _IntSub(1), _IntSub(11), "11", None):
        with pytest.raises(ValueError):
            generate(WORLD, bad_seed)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            ep1.pilot(_v1_valid(), bad_seed)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            ep2.pilot(_v2_valid(), bad_seed)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            evaluate_quarterly(WORLD, _v2_valid(), [bad_seed])  # type: ignore[list-item]
        with pytest.raises(ValueError):
            evaluate_any(WORLD, _v1_valid(), [bad_seed])  # type: ignore[list-item]

    assert ep1.pilot_used == 0
    assert ep2.pilot_used == 0


def test_pilot_rejects_non_bool_trace_type_confusion() -> None:
    ep1 = Episode(WORLD, DEV_DAYS[:1], max_pilots=2)
    with pytest.raises((ValueError, TypeError)):
        ep1.pilot(_v1_valid(), 11, trace="false")  # type: ignore[arg-type]
    assert ep1.pilot_used == 0


def test_parse_any_plan_consistent_on_asdict_v1_and_v2_plans() -> None:
    v1_plan = parse_plan(_v1_valid(), WORLD)
    v2_plan = parse_quarterly_plan(_v2_valid(), WORLD)
    assert parse_any_plan(asdict(v2_plan), WORLD) == v2_plan
    assert parse_any_plan(asdict(v1_plan), WORLD) == v1_plan


def test_verifier_exact_16384_byte_boundary_vs_16385_bytes(tmp_path: Path) -> None:
    for base_obj, verifier_fn in (
        (_v1_valid(), lambda p: verify_file(WORLD, p, DEV_DAYS[:1])),
        (_v2_valid(), lambda p: verify_quarterly_file(WORLD, p, DEV_SEEDS[:1])),
    ):
        compact = json.dumps(base_obj, separators=(",", ":")).encode("ascii")
        assert len(compact) < 16_384

        exact_16384 = compact + b" " * (16_384 - len(compact))
        over_16385 = compact + b" " * (16_385 - len(compact))
        assert len(exact_16384) == 16_384
        assert len(over_16385) == 16_385

        p_ok = tmp_path / "exact_16384.json"
        p_ok.write_bytes(exact_16384)
        ev_ok = verifier_fn(p_ok)
        assert ev_ok.valid and ev_ok.feasible
        assert verify_any_file(WORLD, p_ok, DEV_SEEDS[:1]) == ev_ok

        p_over = tmp_path / "over_16385.json"
        p_over.write_bytes(over_16385)
        ev_over = verifier_fn(p_over)
        assert not ev_over.valid and (ev_over.reward_num, ev_over.reward_den) == (0, 1)
        assert not verify_any_file(WORLD, p_over, DEV_SEEDS[:1]).valid


def test_verifier_multibyte_utf8_char_count_under_16384_but_byte_length_16385_rejected(
    tmp_path: Path,
) -> None:
    prefix = b'{"schema_version":1,"robot":false,"trays":false,"route":"'
    suffix = b'","workers":[[1]]}'
    remaining = 16_385 - len(prefix) - len(suffix)
    euro_count, ascii_pad = divmod(remaining, 3)
    raw = prefix + ("€" * euro_count).encode("utf-8") + (b"a" * ascii_pad) + suffix

    assert len(raw) == 16_385
    assert len(raw.decode("utf-8")) < 6_000

    p = tmp_path / "utf8_16385.json"
    p.write_bytes(raw)
    text, err = _read_bounded_utf8(p)
    assert text is None and err is not None
    assert not err.valid and (err.reward_num, err.reward_den) == (0, 1)
    assert "16384" in err.reasons[0]


def test_verifier_multi_megabyte_dos_file_rejected_via_fstat_before_full_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dos_file = tmp_path / "dos_8mb.json"
    dos_file.write_bytes(b" " * (8 * 1024 * 1024))

    real_fdopen = os.fdopen
    fdopen_called = False

    def _spy_fdopen(*args, **kwargs):
        nonlocal fdopen_called
        fdopen_called = True
        return real_fdopen(*args, **kwargs)

    monkeypatch.setattr(os, "fdopen", _spy_fdopen)
    ev = verify_any_file(WORLD, dos_file, DEV_SEEDS[:1])
    assert not ev.valid and (ev.reward_num, ev.reward_den) == (0, 1)
    assert not fdopen_called


@pytest.mark.parametrize(
    "bad_bytes",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"   \n\t  ", id="whitespace_only"),
        pytest.param(b"\xff\xfe" + json.dumps(_v1_valid()).encode("utf-16-le"), id="utf16_le_bom"),
        pytest.param(b"\xfe\xff" + json.dumps(_v1_valid()).encode("utf-16-be"), id="utf16_be_bom"),
        pytest.param(b"\xef\xbb\xbf" + json.dumps(_v1_valid()).encode("utf-8"), id="utf8_bom"),
        pytest.param(json.dumps(_v1_valid()).encode("utf-8") + b"\x00", id="trailing_nul"),
        pytest.param(b"\x00" + json.dumps(_v1_valid()).encode("utf-8"), id="leading_nul"),
        pytest.param(
            b'{"schema_version":1,"robot":false,"trays":false,"route":"manual\x00","workers":[[1]]}',
            id="embedded_nul",
        ),
        pytest.param(
            b'{"schema_version":1,"robot":false,"trays":false,"route":"\xff","workers":[[1]]}',
            id="invalid_utf8_0xff",
        ),
        pytest.param(
            b'{"schema_version":1,"robot":false,"trays":false,"route":"\xc0\xaf","workers":[[1]]}',
            id="overlong_utf8",
        ),
        pytest.param(
            b'{"schema_version":1,"robot":false,"trays":false,"route":"\xed\xa0\x80","workers":[[1]]}',
            id="cesu8_surrogate",
        ),
        pytest.param(
            b'{"schema_version":1,"robot":false,"trays":false,"route":"\\ud800","workers":[[1]]}',
            id="json_high_surrogate",
        ),
        pytest.param(
            b'{"schema_version":1,"robot":false,"trays":false,"route":"\\udfff","workers":[[1]]}',
            id="json_low_surrogate",
        ),
        pytest.param(b"[" * 12_000, id="recursion_12k_arr"),
        pytest.param(b'{"a":' * 3_000, id="recursion_3k_obj"),
        pytest.param(b"[" * 8_192 + b"]" * 8_192, id="deep_8192_balanced"),
    ],
)
def test_verifier_encoding_bom_nul_surrogate_and_recursion_attacks_cleanly_score_zero(
    tmp_path: Path, bad_bytes: bytes
) -> None:
    sub = tmp_path / "hostile_bytes.json"
    sub.write_bytes(bad_bytes)
    for ev in (
        verify_file(WORLD, sub, DEV_DAYS[:1]),
        verify_quarterly_file(WORLD, sub, DEV_SEEDS[:1]),
        verify_any_file(WORLD, sub, DEV_SEEDS[:1]),
    ):
        assert not ev.valid
        assert not ev.feasible
        assert not ev.win
        assert (ev.reward_num, ev.reward_den) == (0, 1)
        assert ev.metrics == {}


def test_verifier_symlinks_cycles_directories_sockets_and_nonblocking_fifo(tmp_path: Path) -> None:
    valid_target = tmp_path / "valid_target.json"
    valid_target.write_text(json.dumps(_v1_valid()), encoding="utf-8")

    link_valid = tmp_path / "link_valid.json"
    link_valid.symlink_to(valid_target)

    link_broken = tmp_path / "link_broken.json"
    link_broken.symlink_to(tmp_path / "does_not_exist.json")

    link_self = tmp_path / "link_self.json"
    link_self.symlink_to(link_self)

    cycle_a = tmp_path / "cycle_a.json"
    cycle_b = tmp_path / "cycle_b.json"
    cycle_a.symlink_to(cycle_b)
    cycle_b.symlink_to(cycle_a)

    loop_dir = tmp_path / "loop_dir"
    loop_dir.symlink_to(loop_dir)
    in_loop_dir = loop_dir / "submission.json"

    sub_dir = tmp_path / "submission.json"
    sub_dir.mkdir()
    link_dir = tmp_path / "link_dir.json"
    link_dir.symlink_to(sub_dir)

    fifo_path = tmp_path / "writerless.fifo"
    os.mkfifo(fifo_path)

    with tempfile.TemporaryDirectory(dir="/tmp", prefix="fcb_b.") as short_dir:
        sock_path = Path(short_dir) / "s.sock"
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(sock_path))
        try:
            hostile_paths = (
                link_valid,
                link_broken,
                link_self,
                cycle_a,
                in_loop_dir,
                sub_dir,
                link_dir,
                fifo_path,
                sock_path,
            )
            with _alarm_timeout(2):
                for hp in hostile_paths:
                    for ev in (
                        verify_file(WORLD, hp, DEV_DAYS[:1]),
                        verify_quarterly_file(WORLD, hp, DEV_SEEDS[:1]),
                        verify_any_file(WORLD, hp, DEV_SEEDS[:1]),
                    ):
                        assert not ev.valid
                        assert (ev.reward_num, ev.reward_den) == (0, 1)
        finally:
            sock.close()


def test_mcp_save_refuses_symlink_submission_path(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    real.write_text("{}", encoding="utf-8")
    sym = tmp_path / "sub_symlink.json"
    sym.symlink_to(real)
    with pytest.raises(ValueError, match="symlink"):
        mcp_save(sym, _v1_valid())


def test_mcp_save_lone_surrogate_safety(tmp_path: Path) -> None:
    out = tmp_path / "surrogate.json"
    mcp_save(out, {"note": "\ud800"})
    assert out.is_file()


def test_caller_mutation_of_returned_and_input_dicts_cannot_corrupt_episodes(tmp_path: Path) -> None:
    ep1 = Episode(WORLD, DEV_DAYS, max_pilots=3, state_path=tmp_path / "v1_state.json")
    obs1 = ep1.observe()
    obs1["world"]["money"]["budget"] = 0
    obs1["history"].clear()
    obs1["manual"]["workers"].clear()
    assert ep1.observe()["world"]["money"]["budget"] == WORLD["money"]["budget"]
    assert len(ep1.observe()["history"]) == 3

    in_v1 = _v1_valid()
    p_res1 = ep1.pilot(in_v1, 11, trace=True)
    in_v1["workers"][0][0] = 999
    p_res1["raw"]["good"] = -999
    p_res1["economy"]["total"] = -999
    assert ep1.log[-1]["plan"]["workers"][0] == [1]
    assert ep1.log[-1]["raw"]["good"] >= 0

    sub_in_v1 = _v1_valid()
    receipt1 = ep1.submit(sub_in_v1)
    sub_in_v1["workers"].clear()
    sub_in_v1["robot"] = "mutated"
    receipt1["plan"]["workers"].clear()
    receipt1["terminal"] = False
    sub_copy1 = ep1.submission
    assert sub_copy1 is not None
    sub_copy1["workers"].clear()
    assert ep1.submission == _v1_valid()

    ep2 = QuarterlyEpisode(WORLD, seeds=[11], max_pilots=3, state_path=tmp_path / "v2_state.json")
    obs2 = ep2.observe()
    obs2["world"]["quarterly"]["max_pilots"] = 9999
    obs2["pilot_budget"]["max"] = 9999
    obs2["history"][0]["weeks"].clear()
    assert ep2.max_pilots == 3
    assert ep2.observe()["pilot_budget"] == {"used": 0, "max": 3}

    in_v2 = _v2_valid()
    p_res2 = ep2.pilot(in_v2, 11, trace=True)
    in_v2["weeks"][0]["workers"].clear()
    p_res2["total_cost"] = -1
    p_res2["weeks"].clear()
    assert len(ep2.log[-1]["weeks"]) == 12

    sub_in_v2 = _v2_valid()
    receipt2 = ep2.submit(sub_in_v2)
    sub_in_v2["weeks"].clear()
    receipt2["plan"]["weeks"].clear()
    sub_copy2 = ep2.submission
    assert sub_copy2 is not None
    sub_copy2["weeks"].clear()
    assert ep2.submission == _v2_valid()


def test_pilot_budget_non_reset_across_invalid_calls_stop_submit_and_reload(tmp_path: Path) -> None:
    st = tmp_path / "budget_state.json"
    ep = QuarterlyEpisode(WORLD, seeds=[11, 29], max_pilots=2, state_path=st)

    with pytest.raises(InvalidPlan):
        ep.pilot({"bad": 1}, 11)
    with pytest.raises(ValueError, match="unknown public day"):
        ep.pilot(_v2_valid(), 999999)
    assert ep.pilot_used == 0
    assert ep.rejected_calls == 2

    ep.pilot(_v2_valid(), 11)
    ep.pilot(_v2_valid(), 29)
    assert ep.pilot_used == 2

    for probe_plan, probe_seed in [({"bad": 1}, 11), (_v2_valid(), -999), (_v2_valid(), 11)]:
        with pytest.raises(PilotBudgetExceeded):
            ep.pilot(probe_plan, probe_seed)
    assert ep.pilot_used == 2
    assert ep.rejected_calls == 5

    ep_reloaded = QuarterlyEpisode(WORLD, seeds=[11, 29], max_pilots=100, state_path=st)
    assert ep_reloaded.max_pilots == 2
    assert ep_reloaded.pilot_used == 2
    assert ep_reloaded.rejected_calls == 5
    with pytest.raises(PilotBudgetExceeded):
        ep_reloaded.pilot(_v2_valid(), 11)

    assert ep_reloaded.stop() == {"terminal": True, "plan": None}
    ep_after_stop = QuarterlyEpisode(WORLD, seeds=[11, 29], max_pilots=100, state_path=st)
    assert ep_after_stop.closed and ep_after_stop.submission is None
    for fn in (
        ep_after_stop.observe,
        lambda: ep_after_stop.pilot(_v2_valid(), 11),
        lambda: ep_after_stop.submit(_v2_valid()),
        ep_after_stop.stop,
    ):
        with pytest.raises(EpisodeClosed):
            fn()


def test_mutating_episode_log_entry_cannot_corrupt_internal_submission() -> None:
    ep1 = Episode(WORLD, DEV_DAYS[:1])
    ep1.submit(_v1_valid())
    ep1.log[-1]["plan"]["robot"] = "CORRUPTED"
    assert ep1.submission == _v1_valid()

    ep2 = QuarterlyEpisode(WORLD, seeds=[11])
    ep2.submit(_v2_valid())
    ep2.log[-1]["plan"]["weeks"][0]["robot"] = "CORRUPTED"
    assert ep2.submission == _v2_valid()


@pytest.mark.parametrize(
    "corrupt_payload",
    [
        pytest.param(b"[" * 12_000, id="recursion_12k_brackets"),
        pytest.param(
            b'{"mode":"quarterly","pilot_used":24,"pilot_used":0,'
            b'"max_pilots":24,"closed":false,"submission":null,"log":[]}',
            id="duplicate_key_budget_reset",
        ),
        pytest.param(
            b'{"mode":"quarterly","pilot_used":0,"max_pilots":24,'
            b'"closed":false,"submission":null,"log":[{"n":1,"action":"observe","x":NaN}]}',
            id="nan_in_log",
        ),
        pytest.param(
            b'{"mode":"quarterly","pilot_used":0,"max_pilots":24,'
            b'"closed":false,"submission":null,"log":[123]}',
            id="non_dict_log_entry",
        ),
        pytest.param(
            b'{"mode":"quarterly","pilot_used":0,"max_pilots":24,'
            b'"closed":true,"submission":{"a":' + b"[" * 2500 + b"]" * 2500 + b'},"log":[]}',
            id="deep_invalid_submission",
        ),
    ],
)
def test_tampered_or_corrupt_state_file_rejected_at_load_time(
    tmp_path: Path, corrupt_payload: bytes
) -> None:
    st = tmp_path / "corrupt_state.json"
    st.write_bytes(corrupt_payload)
    with pytest.raises(ValueError):
        QuarterlyEpisode(WORLD, seeds=[11], state_path=st)


def test_episode_observe_log_bloat_bounded(tmp_path: Path) -> None:
    st = tmp_path / "obs_bloat.json"
    ep = QuarterlyEpisode(WORLD, seeds=[11], state_path=st)
    for _ in range(200):
        ep.observe()
    assert len(ep.log) <= 64


def test_observe_failure_on_bad_rules_file_rolls_back_log_and_state(tmp_path: Path) -> None:
    bad_rules = tmp_path / "bad_SPEC.md"
    bad_rules.write_bytes(b"\xff\xfeinvalid_utf8")
    st = tmp_path / "obs_state.json"

    ep = QuarterlyEpisode(WORLD, seeds=[11], state_path=st, rules_path=bad_rules)
    with pytest.raises(UnicodeDecodeError):
        ep.observe()
    assert ep.log == []
    assert json.loads(st.read_text(encoding="utf-8"))["log"] == []


@pytest.mark.parametrize("mod_name", ["economics.py", "grading.py", "verifier.py"])
def test_ast_zero_float_operations_in_economics_grading_and_verifier(mod_name: str) -> None:
    path = ROOT / "src" / "robotization_bench" / mod_name
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    float_constants = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and type(node.value) is float
    ]
    float_calls = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "float"
    ]
    assert float_constants == [], f"Unexpected float literal in {mod_name} at lines {float_constants}"
    assert float_calls == [], f"Unexpected float() call in {mod_name} at lines {float_calls}"


def test_exact_fraction_rejects_10_pow_18_ulp_false_wins_and_ranks_1_cent_savings() -> None:
    """Prove exact Fraction catches 1-in-10^18 shortfall where IEEE-754 float rounds to passing."""
    scale = 10**18
    plan = Plan(1, True, True, "all", ((1,), (2,), (3,), (4,)))

    auto_short = scale // 4 - 1
    assert (auto_short / scale) * 10_000 == 2500.0

    base_rep = RawReport(1, 1, scale, scale, scale, 0, 0, 0, scale, scale, 0, 0, 0, 10_000, (1000,), ())
    cand_auto_short = replace(base_rep, auto_finished=auto_short, labor_ticks=5_000, overtime_ticks=(0,))
    ev_auto = grade_reports(WORLD, plan, [cand_auto_short], [base_rep], plan)
    assert ev_auto.valid and ev_auto.feasible and not ev_auto.win
    assert "automation" in ev_auto.reasons

    good_short = 94 * (10**16) - 1
    assert (good_short / scale) * 10_000 == 9400.0
    cand_vol_short = replace(
        base_rep,
        good=good_short,
        on_time=good_short,
        unfinished=scale - good_short,
        auto_finished=scale,
        labor_ticks=5_000,
        overtime_ticks=(0,),
    )
    ev_vol = grade_reports(WORLD, plan, [cand_vol_short], [base_rep], plan)
    assert ev_vol.valid and not ev_vol.feasible and not ev_vol.win
    assert ev_vol.reasons == ("volume",)
    assert F(ev_vol.reward_num, ev_vol.reward_den) < F(9, 100)

    esc_over = 10**16 + 1
    assert (esc_over / scale) * 10_000 == 100.0
    cand_qual_over = replace(
        base_rep,
        good=scale - esc_over,
        on_time=scale - esc_over,
        escaped=esc_over,
        auto_finished=scale,
        labor_ticks=5_000,
        overtime_ticks=(0,),
    )
    ev_qual = grade_reports(WORLD, plan, [cand_qual_over], [base_rep], plan)
    assert ev_qual.valid and not ev_qual.feasible and not ev_qual.win
    assert ev_qual.reasons == ("quality",)
    assert F(ev_qual.reward_num, ev_qual.reward_den) < F(9, 100)

    w_big = copy.deepcopy(WORLD)
    w_big["money"]["overtime_per_worker_tick"] = 1
    base_huge = replace(base_rep, overtime_ticks=(scale,))
    win_a = replace(base_rep, auto_finished=scale, labor_ticks=5_000, overtime_ticks=(scale // 2,))
    win_b = replace(base_rep, auto_finished=scale, labor_ticks=5_000, overtime_ticks=(scale // 2 - 1,))
    ev_a = grade_reports(w_big, plan, [win_a], [base_huge], plan)
    ev_b = grade_reports(w_big, plan, [win_b], [base_huge], plan)
    assert ev_a.win and ev_b.win
    assert F(ev_b.reward_num, ev_b.reward_den) > F(ev_a.reward_num, ev_a.reward_den)
    assert math.gcd(ev_a.reward_num, ev_a.reward_den) == 1
    assert math.gcd(ev_b.reward_num, ev_b.reward_den) == 1


def test_reward_txt_float_formatting_preserves_tier_boundaries() -> None:
    tiers = [
        ("invalid", F(0, 1)),
        ("infeasible_floor", F(1, 10_000)),
        ("infeasible_near_cap", F(9, 100) * F(39_999_999, 40_000_000)),
        ("infeasible_cap", F(9, 100)),
        ("feasible_floor", F(1, 10)),
        ("feasible_near_manual", F(1, 10) + F(1, 10) / (1 + F(1, 50_000_000))),
        ("manual_baseline", F(1, 5)),
        ("minimal_win", F(1, 5) + F(4, 5) * F(1, 50_000_000)),
    ]
    rendered = [float(str(frac.numerator / frac.denominator)) for _, frac in tiers]
    for i in range(len(rendered) - 1):
        assert rendered[i] < rendered[i + 1], (
            f"Float serialization collapsed tier {tiers[i][0]} >= {tiers[i + 1][0]}"
        )


def test_economics_half_up_depreciation_and_retrain_dp_symmetry() -> None:
    for purchase in range(0, 120):
        for denom in (1, 2, 3, 7, 52, 500):
            w = copy.deepcopy(WORLD)
            w["money"].update(robot_purchase=purchase, tray_purchase=0, depreciation_days=denom)
            w["quarterly"]["money"]["depreciation_weeks"] = denom
            raw = RawReport(1, 1, 10, 10, 10, 0, 0, 0, 10, 10, 0, 0, 0, 100, (0,), ())
            econ = calculate(w, Plan(1, True, False, "manual", ((1,),)), raw)
            expected = (2 * purchase + denom) // (2 * denom)
            assert type(econ.costs["depreciation"]) is int
            assert econ.costs["depreciation"] == expected

    crew_a = ((1,), (2, 3), (4,), (1, 4))
    crew_b = ((4, 1), (3, 2), (2, 3, 4), (1, 2), (3,))
    assert _retrain_units(crew_a, crew_b) == _retrain_units(tuple(reversed(crew_a)), tuple(reversed(crew_b)))


def test_negative_world_budget_or_escaped_threshold_raises_value_error_not_zero_division() -> None:
    w_neg_budget = copy.deepcopy(WORLD)
    w_neg_budget["money"]["budget"] = -1
    with pytest.raises(ValueError):
        evaluate(w_neg_budget, _v1_valid(), DEV_DAYS[:1])

    w_neg_q_budget = copy.deepcopy(WORLD)
    w_neg_q_budget["quarterly"]["money"]["budget"] = -1
    with pytest.raises(ValueError):
        evaluate_quarterly(w_neg_q_budget, _v2_valid(), DEV_SEEDS[:1])


def test_staged_harbor_verifier_supports_quarterly_v2_plans(tmp_path: Path) -> None:
    task_dir = tmp_path / "harbor_task"
    seeds_file = tmp_path / "eval_seeds.json"
    seeds_file.write_text("[101, 202, 303]\n", encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "prepare_harbor.py"),
            "--out",
            str(task_dir),
            "--seeds-file",
            str(seeds_file),
        ],
        check=True,
    )
    assert (task_dir / "tests" / "trusted" / "src" / "robotization_bench" / "quarterly.py").is_file()


def test_verifier_validates_seeds_before_short_circuiting_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(ValueError, match="seeds"):
        verify_quarterly_file(WORLD, missing, [])
    with pytest.raises(ValueError, match="seeds"):
        verify_any_file(WORLD, missing, [True])  # type: ignore[list-item]


# ==============================================================================
# PART C: HARBOR SCHEMA-DOWNGRADE REWARD-HACK PROOF (verify_quarterly_file vs v1)
# ==============================================================================


def test_quarterly_verifier_rejects_v1_schema_downgrade_exploit(tmp_path: Path) -> None:
    """Prove why Harbor's quarterly grade.py MUST call verify_quarterly_file unconditionally:
    a trivial static v1 single-shift plan scores a true win (202469/699265 ≈ 0.2895 > 1/5)
    under verify_file, whereas verify_quarterly_file strictly rejects schema_version=1 with 0/1!
    """
    v1_downgrade_payload = {
        "schema_version": 1,
        "robot": True,
        "trays": True,
        "route": "bypass",
        "workers": [[1], [2], [3], [4], [2, 3]],
    }
    sub = tmp_path / "v1_downgrade_submission.json"
    sub.write_text(json.dumps(v1_downgrade_payload), encoding="utf-8")

    replay_days = tuple(generate(WORLD, s) for s in REPLAY_SEEDS)
    ev_v1_fallback = verify_file(WORLD, sub, replay_days)
    assert ev_v1_fallback.valid and ev_v1_fallback.feasible and ev_v1_fallback.win
    assert F(ev_v1_fallback.reward_num, ev_v1_fallback.reward_den) == F(202_469, 699_265) > F(1, 5)

    ev_strict_quarterly = verify_quarterly_file(WORLD, sub, REPLAY_SEEDS)
    assert not ev_strict_quarterly.valid
    assert not ev_strict_quarterly.feasible and not ev_strict_quarterly.win
    assert (ev_strict_quarterly.reward_num, ev_strict_quarterly.reward_den) == (0, 1)
