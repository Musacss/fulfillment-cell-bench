"""Shift costs in euro cents, from a validated plan and a trusted simulation."""

from .contracts import Economy, Plan, RawReport, World


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
