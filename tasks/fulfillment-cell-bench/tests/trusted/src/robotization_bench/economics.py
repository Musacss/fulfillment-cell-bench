"""Shift and weekly costs in euro cents, from validated plans and trusted simulations."""

from collections import Counter
from functools import lru_cache

from .contracts import Economy, Plan, RawReport, WeekPlan, World


def calculate(world: World, plan: Plan, raw: RawReport) -> Economy:
    prices = world["money"]
    purchase = (prices["robot_purchase"] if plan.robot else 0) + (
        prices["tray_purchase"] if plan.trays else 0
    )

    days = prices["depreciation_days"]
    if days <= 0:
        raise ValueError("depreciation_days must be positive")
    cents, remainder = divmod(purchase, days)
    depreciation = cents + (2 * remainder >= days)

    costs = {
        "depreciation": depreciation,
        "service": prices["robot_service_day"] if plan.robot else 0,
        "shifts": len(plan.workers) * prices["worker_shift"],
        "overtime": sum(raw.overtime_ticks) * prices["overtime_per_worker_tick"],
        "trays": raw.trays_used * prices["tray_per_order"],
        "materials": raw.pack_started * prices["material_per_pack"],
        "rework": raw.rework_started * prices["rework_start"],
        "late": (raw.good - raw.on_time) * prices["late_good"],
        "unfulfilled": (raw.scrap + raw.unfinished) * prices["unfulfilled"],
        "escaped": raw.escaped * prices["escaped"],
    }
    return Economy(purchase=purchase, costs=costs, total=sum(costs.values()))


def _retrain_units(
    prev_workers: tuple[tuple[int, ...], ...],
    curr_workers: tuple[tuple[int, ...], ...],
) -> int:
    """Minimum newly trained zones across retained workers (permutation-invariant)."""
    prev_counts = Counter(frozenset(z) for z in prev_workers)
    curr_counts = Counter(frozenset(z) for z in curr_workers)
    common = prev_counts & curr_counts
    rem_prev = list((prev_counts - common).elements())
    rem_curr = list((curr_counts - common).elements())
    if not rem_prev or not rem_curr:
        return 0
    if len(rem_prev) <= len(rem_curr):

        @lru_cache(maxsize=None)
        def dp_prev(i: int, mask: int) -> int:
            if i == len(rem_prev):
                return 0
            p = rem_prev[i]
            return min(
                len(rem_curr[j] - p) + dp_prev(i + 1, mask | (1 << j))
                for j in range(len(rem_curr))
                if not (mask & (1 << j))
            )

        return dp_prev(0, 0)

    @lru_cache(maxsize=None)
    def dp_curr(j: int, mask: int) -> int:
        if j == len(rem_curr):
            return 0
        c = rem_curr[j]
        return min(
            len(c - rem_prev[i]) + dp_curr(j + 1, mask | (1 << i))
            for i in range(len(rem_prev))
            if not (mask & (1 << i))
        )

    return dp_curr(0, 0)


def calculate_week(
    world: World,
    week_plan: WeekPlan,
    prev_workers: tuple[tuple[int, ...], ...],
    raw: RawReport,
    *,
    carryover_out: int,
    owned_robot: bool,
    owned_trays: bool,
) -> tuple[Economy, Economy]:
    """Return (shift_economy_v1, week_economy_v2) in integer euro cents."""
    shift_economy = calculate(world, week_plan.to_shift_plan(), raw)
    prices = world["money"]
    q_money = world["quarterly"]["money"]

    shifts = q_money["shifts_per_week"]
    if shifts <= 0:
        raise ValueError("shifts_per_week must be positive")
    if carryover_out < 0 or carryover_out > raw.unfinished:
        raise ValueError("carryover_out must be within 0..raw.unfinished")

    has_robot = owned_robot or week_plan.robot
    has_trays = owned_trays or week_plan.trays
    purchase = (prices["robot_purchase"] if has_robot else 0) + (
        prices["tray_purchase"] if has_trays else 0
    )

    dep_weeks = q_money["depreciation_weeks"]
    if dep_weeks <= 0:
        raise ValueError("depreciation_weeks must be positive")
    cents, remainder = divmod(purchase, dep_weeks)
    depreciation = cents + (2 * remainder >= dep_weeks)

    hired = max(0, len(week_plan.workers) - len(prev_workers))
    laid_off = max(0, len(prev_workers) - len(week_plan.workers))
    retrain_units = _retrain_units(prev_workers, week_plan.workers)
    hiring_retraining = (
        hired * q_money["hire_cost"]
        + laid_off * q_money["layoff_cost"]
        + retrain_units * q_money["retrain_cost"]
    )

    cross_skilled = sum(1 for zones in week_plan.workers if len(zones) > 1)
    terminal_unfulfilled = raw.scrap + (raw.unfinished - carryover_out)

    week_costs = {
        "depreciation": depreciation,
        "service": q_money["robot_service_week"] if has_robot else 0,
        "maintenance": q_money["maintenance_cost"] if week_plan.maintenance else 0,
        "shifts": len(week_plan.workers) * prices["worker_shift"] * shifts,
        "cross_skill": cross_skilled * q_money["cross_skill_shift_premium"] * shifts,
        "overtime": sum(raw.overtime_ticks) * prices["overtime_per_worker_tick"] * shifts,
        "hiring_retraining": hiring_retraining,
        "trays": raw.trays_used * prices["tray_per_order"] * shifts,
        "materials": raw.pack_started * prices["material_per_pack"] * shifts,
        "rework": raw.rework_started * prices["rework_start"] * shifts,
        "late": (raw.good - raw.on_time) * prices["late_good"] * shifts,
        "backlog_holding": carryover_out * q_money["backlog_holding_per_order"],
        "unfulfilled": terminal_unfulfilled * prices["unfulfilled"] * shifts,
        "escaped": raw.escaped * prices["escaped"] * shifts,
    }
    week_economy = Economy(purchase=purchase, costs=week_costs, total=sum(week_costs.values()))
    return shift_economy, week_economy
