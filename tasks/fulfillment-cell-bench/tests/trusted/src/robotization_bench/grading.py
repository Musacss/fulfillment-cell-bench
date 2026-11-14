"""Authoritative evaluation. Reward fractions never pass through floating point."""

from collections.abc import Sequence
from fractions import Fraction as F
import json
from typing import Any

from .contracts import (
    QUARTERLY_SCHEMA_VERSION,
    ROOT,
    Evaluation,
    InvalidPlan,
    Plan,
    QuarterReport,
    QuarterlyPlan,
    RawReport,
    Scenario,
    World,
)
from .economics import calculate
from .engine import simulate
from .scenarios import generate
from .validation import parse_any_plan, parse_plan, parse_quarterly_plan

_INFEASIBLE_FLOOR = F(1, 10_000)


def manual_value():
    return json.loads((ROOT / "data/plans/manual.json").read_text())


def invalid(reason):
    return Evaluation(False, False, False, 0, 1, {}, (reason,))


def _minimum(actual: int, target: int) -> F:
    return F(1) if actual >= target else F(actual, target)


def _maximum(actual: int, limit: int) -> F:
    return F(1) if actual <= limit else F(limit, actual)


def grade_reports(world: World, plan: Plan, reports: list[RawReport], baseline_reports: list[RawReport],
                  baseline_plan: Plan) -> Evaluation:
    if (not reports or [(r.seed, r.total) for r in reports] != [(r.seed, r.total) for r in baseline_reports]
            or len({r.seed for r in reports}) != len(reports)):
        raise ValueError("need matching unique nonempty days")
    for r in (*reports, *baseline_reports):
        if (r.total <= 0 or not 0 <= r.on_time <= r.good or
            r.total != r.good+r.unfinished+r.scrap+r.escaped or min(r.unfinished,r.scrap,r.escaped,r.labor_ticks)<0
            or not 0 <= r.auto_finished <= r.pack_finished <= r.pack_started):
            raise ValueError("inconsistent trusted report")
    econ = [calculate(world, plan, r) for r in reports]
    cost = sum(e.total for e in econ)
    base_cost = sum(calculate(world, baseline_plan, r).total for r in baseline_reports)
    if cost < 0 or base_cost <= 0:
        raise ValueError("invalid world costs")
    totals = {k: sum(getattr(r, k) for r in reports)
              for k in ("good","on_time","escaped","scrap","unfinished","auto_finished","pack_finished","labor_ticks")}
    orders = sum(r.total for r in reports)
    base_labor = sum(r.labor_ticks for r in baseline_reports)
    purchase = econ[0].purchase
    totals.update(orders=orders, total_cost=cost, base_cost=base_cost, base_labor_ticks=base_labor,
                  purchase=purchase)
    thresholds = world["threshold_bps"]
    progress = {
        "budget": _maximum(purchase,world["money"]["budget"]),
        "volume": min(_minimum(r.good*10000,r.total*thresholds["good_each_day"]) for r in reports),
        "on_time": _minimum(totals["on_time"]*10000,orders*thresholds["on_time_pooled"]),
        "quality": min(_maximum(r.escaped*10000,r.total*thresholds["escaped_each_day_max"]) for r in reports),
    }
    reasons = [k for k,v in progress.items() if v<1]
    feasible = not reasons
    share = F(totals["auto_finished"],totals["pack_finished"]) if totals["pack_finished"] else F(0)
    if feasible:
        reasons = [k for k,v in (("cost",cost<base_cost),("labor",totals["labor_ticks"]<base_labor),
                   ("automation",share*10000>=thresholds["auto_pack_pooled_min"])) if not v]
    win = feasible and not reasons
    if win:
        reward = F(1,5) + F(4,5)*F(base_cost-cost,base_cost)
    elif feasible:
        reward = F(1,10) + F(1,10)/(1+max(F(0),F(cost-base_cost, base_cost)))
    else:
        reward = max(_INFEASIBLE_FLOOR, F(9,100)*min(progress.values()))
    return Evaluation(True, feasible, win, reward.numerator, reward.denominator, totals, tuple(reasons))


def evaluate(world: World, value, scenarios: tuple[Scenario,...]) -> Evaluation:
    try:
        plan = parse_plan(value, world)
    except InvalidPlan as exc:
        return invalid(str(exc))
    baseline = parse_plan(manual_value(),world)
    return grade_reports(world, plan, [simulate(world,plan,d) for d in scenarios],
                         [simulate(world,baseline,d) for d in scenarios], baseline)


def grade_quarters(
    world: World,
    plan: QuarterlyPlan,
    quarters: Sequence[QuarterReport],
    baseline_quarters: Sequence[QuarterReport],
) -> Evaluation:
    del plan
    num_weeks = world["quarterly"]["weeks"]
    if (
        not quarters
        or [q.seed for q in quarters] != [bq.seed for bq in baseline_quarters]
        or len({q.seed for q in quarters}) != len(quarters)
    ):
        raise ValueError("need matching unique nonempty quarters")

    for q in (*quarters, *baseline_quarters):
        if (
            q.schema_version != QUARTERLY_SCHEMA_VERSION
            or len(q.weeks) != num_weeks
            or q.purchase < 0
            or q.total_cost != sum(w.week_economy.total for w in q.weeks)
            or q.labor_ticks != sum(w.raw.labor_ticks for w in q.weeks)
        ):
            raise ValueError("inconsistent trusted quarter report")
        for idx, wr in enumerate(q.weeks):
            r = wr.raw
            expected_in = 0 if idx == 0 else q.weeks[idx - 1].carryover_out
            if (
                wr.week != idx
                or wr.carryover_in != expected_in
                or not 0 <= wr.carryover_out <= r.unfinished
                or (idx == num_weeks - 1 and wr.carryover_out != 0)
                or r.total - wr.carryover_in <= 0
                or not 0 <= r.on_time <= r.good
                or r.total != r.good + r.unfinished + r.scrap + r.escaped
                or min(r.unfinished, r.scrap, r.escaped, r.labor_ticks) < 0
                or not 0 <= r.auto_finished <= r.pack_finished <= r.pack_started
            ):
                raise ValueError("inconsistent trusted week report")

    for q, bq in zip(quarters, baseline_quarters):
        for wr, bwr in zip(q.weeks, bq.weeks):
            if wr.raw.total - wr.carryover_in != bwr.raw.total - bwr.carryover_in:
                raise ValueError("mismatched exogenous weekly orders")

    cost = sum(q.total_cost for q in quarters)
    base_cost = sum(bq.total_cost for bq in baseline_quarters)
    if cost < 0 or base_cost <= 0:
        raise ValueError("invalid world costs")

    purchase = quarters[0].purchase
    if any(q.purchase != purchase for q in quarters):
        raise ValueError("inconsistent plan purchase across seeds")

    orders = sum(wr.raw.total - wr.carryover_in for q in quarters for wr in q.weeks)
    base_labor = sum(bq.labor_ticks for bq in baseline_quarters)
    totals = {
        "orders": orders,
        "good": sum(wr.raw.good for q in quarters for wr in q.weeks),
        "on_time": sum(wr.raw.on_time for q in quarters for wr in q.weeks),
        "escaped": sum(wr.raw.escaped for q in quarters for wr in q.weeks),
        "scrap": sum(wr.raw.scrap for q in quarters for wr in q.weeks),
        "unfinished": sum(wr.raw.unfinished - wr.carryover_out for q in quarters for wr in q.weeks),
        "auto_finished": sum(wr.raw.auto_finished for q in quarters for wr in q.weeks),
        "pack_finished": sum(wr.raw.pack_finished for q in quarters for wr in q.weeks),
        "labor_ticks": sum(q.labor_ticks for q in quarters),
        "base_labor_ticks": base_labor,
        "total_cost": cost,
        "base_cost": base_cost,
        "purchase": purchase,
    }
    if totals["orders"] != totals["good"] + totals["escaped"] + totals["scrap"] + totals["unfinished"]:
        raise ValueError("quarterly order conservation failed")

    thresholds = world["quarterly"]["threshold_bps"]
    budget_limit = world["quarterly"]["money"]["budget"]
    vol_each_week = min(
        _minimum(wr.raw.good * 10_000, wr.raw.total * thresholds["good_each_week"])
        for q in quarters
        for wr in q.weeks
    )
    vol_pooled = _minimum(totals["good"] * 10_000, orders * thresholds["good_pooled"])
    progress = {
        "budget": _maximum(purchase, budget_limit),
        "volume": min(vol_each_week, vol_pooled),
        "on_time": _minimum(totals["on_time"] * 10_000, orders * thresholds["on_time_pooled"]),
        "quality": min(
            _maximum(wr.raw.escaped * 10_000, wr.raw.total * thresholds["escaped_each_week_max"])
            for q in quarters
            for wr in q.weeks
        ),
    }
    reasons = [k for k, v in progress.items() if v < 1]
    feasible = not reasons
    auto_min_bps = thresholds["auto_pack_pooled_min"]
    share = F(totals["auto_finished"], totals["pack_finished"]) if totals["pack_finished"] else F(0)
    if feasible:
        reasons = [
            k
            for k, v in (
                ("cost", cost < base_cost),
                ("labor", totals["labor_ticks"] < base_labor),
                ("automation", share * 10_000 >= auto_min_bps),
            )
            if not v
        ]
    win = feasible and not reasons
    if win:
        reward = F(1, 5) + F(4, 5) * F(base_cost - cost, base_cost)
    elif feasible:
        overrun = max(F(0), F(cost - base_cost, base_cost))
        if purchase > 0 and "automation" in reasons:
            auto_prog = (
                _minimum(totals["auto_finished"] * 10_000, totals["pack_finished"] * auto_min_bps)
                if totals["pack_finished"] and auto_min_bps > 0
                else F(0)
            )
            overrun += F(1) - auto_prog
        if purchase > 0 and "labor" in reasons:
            overrun += F(totals["labor_ticks"] - base_labor + 1, max(1, base_labor))
        reward = F(1, 10) + F(1, 10) / (1 + overrun)
    else:
        reward = max(_INFEASIBLE_FLOOR, F(9, 100) * min(progress.values()))

    return Evaluation(True, feasible, win, reward.numerator, reward.denominator, totals, tuple(reasons))


def evaluate_quarterly(world: World, value: Any, seeds: Sequence[int]) -> Evaluation:
    if not seeds or any(type(s) is not int for s in seeds) or len(set(seeds)) != len(seeds):
        raise ValueError("seeds must be a nonempty sequence of unique integers")
    try:
        plan = parse_quarterly_plan(value, world)
    except InvalidPlan as exc:
        return invalid(str(exc))
    from .quarterly import manual_quarterly_value, simulate_quarter

    baseline = parse_quarterly_plan(manual_quarterly_value(world), world)
    return grade_quarters(
        world,
        plan,
        [simulate_quarter(world, plan, s) for s in seeds],
        [simulate_quarter(world, baseline, s) for s in seeds],
    )


def evaluate_any(world: World, value: Any, seeds: Sequence[int]) -> Evaluation:
    if not seeds or any(type(s) is not int for s in seeds) or len(set(seeds)) != len(seeds):
        raise ValueError("seeds must be a nonempty sequence of unique integers")
    try:
        parsed = parse_any_plan(value, world)
    except InvalidPlan as exc:
        return invalid(str(exc))
    if isinstance(parsed, QuarterlyPlan):
        return evaluate_quarterly(world, value, seeds)
    scenarios = tuple(generate(world, s) for s in seeds)
    return evaluate(world, value, scenarios)
