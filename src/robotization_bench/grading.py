"""Authoritative evaluation. Reward fractions never pass through floating point."""
import json
from fractions import Fraction as F
from .contracts import ROOT, Evaluation, InvalidPlan, Plan, RawReport, Scenario, World
from .economics import calculate
from .engine import simulate
from .validation import parse_plan


def manual_value():
    return json.loads((ROOT / "data/plans/manual.json").read_text())


def invalid(reason):
    return Evaluation(False, False, False, 0, 1, {}, (reason,))


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
    def minimum(actual, target):
        return F(1) if actual >= target else F(actual, target)
    def maximum(actual, limit):
        return F(1) if actual <= limit else F(limit, actual)
    progress = {
        "budget": maximum(purchase,world["money"]["budget"]),
        "volume": min(minimum(r.good*10000,r.total*thresholds["good_each_day"]) for r in reports),
        "on_time": minimum(totals["on_time"]*10000,orders*thresholds["on_time_pooled"]),
        "quality": min(maximum(r.escaped*10000,r.total*thresholds["escaped_each_day_max"]) for r in reports),
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
        reward = F(9,100)*min(progress.values())
    return Evaluation(True, feasible, win, reward.numerator, reward.denominator, totals, tuple(reasons))


def evaluate(world: World, value, scenarios: tuple[Scenario,...]) -> Evaluation:
    try:
        plan = parse_plan(value, world)
    except InvalidPlan as exc:
        return invalid(str(exc))
    baseline = parse_plan(manual_value(),world)
    return grade_reports(world, plan, [simulate(world,plan,d) for d in scenarios],
                         [simulate(world,baseline,d) for d in scenarios], baseline)
