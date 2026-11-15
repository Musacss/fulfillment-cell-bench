"""12-week coupled quarterly simulator composing untouched v1 shift runs."""

import copy
from dataclasses import replace
import json
from typing import Any

from .contracts import (
    QUARTERLY_SCHEMA_VERSION,
    ROOT,
    SCHEMA_VERSION,
    Order,
    QuarterReport,
    QuarterlyPlan,
    Scenario,
    WeekReport,
    World,
    draw,
    load_world,
)
from .economics import calculate_week
from .engine import simulate
from .scenarios import generate

_GENERATOR_KEYS = (
    "waves",
    "spacing",
    "orders_min",
    "orders_span",
    "jitter_span",
    "regular_bps",
    "fragile_bps",
    "due_offset",
    "due_span",
)
_TERMINAL_KINDS = frozenset(("good", "escaped", "scrap"))
_WEEK_SEED_MODULUS = 2_147_483_647


def manual_quarterly_value(world: World | None = None) -> dict[str, Any]:
    """Return canonical schema_version=2 JSON dict repeating manual.json crew across all weeks."""
    w = load_world() if world is None else world
    num_weeks = w["quarterly"]["weeks"]
    base = json.loads((ROOT / "data/plans/manual.json").read_text())
    return {
        "schema_version": QUARTERLY_SCHEMA_VERSION,
        "weeks": [
            {
                "robot": False,
                "trays": False,
                "route": "manual",
                "maintenance": False,
                "workers": [list(zones) for zones in base["workers"]],
            }
            for _ in range(num_weeks)
        ],
    }


def build_week_world(
    world: World,
    week: int,
    *,
    commissioning: bool,
    wear: int,
    maintenance: bool,
) -> World:
    """Return an isolated v1-compatible World dict for week `week`."""
    q = world["quarterly"]
    profiles = q["week_profiles"]
    if type(week) is not int or not 0 <= week < len(profiles):
        raise ValueError(f"week must be an integer in 0..{len(profiles) - 1}")
    if type(wear) is not int or wear < 0:
        raise ValueError("wear must be a non-negative integer")

    w = copy.deepcopy(world)
    w["schema_version"] = SCHEMA_VERSION

    profile = profiles[week]
    for key in _GENERATOR_KEYS:
        if key in profile:
            w["generator"][key] = profile[key]

    wear_spec = q["wear"]
    max_wear = wear_spec["max_wear"]
    reduced_wear = wear - wear_spec["maintenance_reduction"] if maintenance else wear
    effective_wear = min(max_wear, max(0, reduced_wear))

    comm_spec = q["commissioning"]
    comm_jam_map = comm_spec["jam_bonus_bps"]
    comm_def_map = comm_spec.get("defect_bonus_bps", {})

    for rig in ("bare", "tray"):
        jam_add = (comm_jam_map[rig] if commissioning else 0) + effective_wear * wear_spec["jam_bps_per_wear"]
        def_add = (comm_def_map.get(rig, 0) if commissioning else 0) + effective_wear * wear_spec["defect_bps_per_wear"]
        for kind in w["kinds"]:
            w["prob_bps"]["jam"][rig][kind] = min(10_000, max(0, w["prob_bps"]["jam"][rig][kind] + jam_add))
            w["prob_bps"]["defect_auto"][rig][kind] = min(
                10_000, max(0, w["prob_bps"]["defect_auto"][rig][kind] + def_add)
            )

    if maintenance:
        slowdown = wear_spec.get("maintenance_auto_slowdown_ticks", 0)
        if slowdown:
            for rig in ("bare", "tray"):
                for kind in w["kinds"]:
                    w["time"]["auto"][rig][kind] = max(1, w["time"]["auto"][rig][kind] + slowdown)

    return w


def generate_quarter_exogenous(world: World, seed: int) -> tuple[Scenario, ...]:
    """Generate the 12 exogenous (pre-carryover) weekly Scenario objects for a quarter seed."""
    if type(seed) is not int:
        raise ValueError("quarter seed must be an integer")
    num_weeks = world["quarterly"]["weeks"]
    scenarios: list[Scenario] = []
    for week in range(num_weeks):
        week_seed = draw(seed, week, 0, 0, "quarter_week", _WEEK_SEED_MODULUS)
        week_world = build_week_world(world, week, commissioning=False, wear=0, maintenance=False)
        scenarios.append(generate(week_world, week_seed))
    return tuple(scenarios)


def simulate_quarter(
    world: World,
    plan: QuarterlyPlan,
    seed: int,
    *,
    trace: bool = False,
) -> QuarterReport:
    """Simulate 12 coupled weeks via engine.simulate() with carryover, commissioning, and wear."""
    if type(seed) is not int:
        raise ValueError("quarter seed must be an integer")
    q = world["quarterly"]
    num_weeks = q["weeks"]
    if plan.schema_version != QUARTERLY_SCHEMA_VERSION or len(plan.weeks) != num_weeks:
        raise ValueError("invalid trusted quarterly plan")

    carryover_cap = q["carryover_cap"]
    comm_weeks = q["commissioning"]["weeks"]
    wear_spec = q["wear"]
    max_wear = wear_spec["max_wear"]
    profiles = q["week_profiles"]

    exogenous = generate_quarter_exogenous(world, seed)
    base_manual = json.loads((ROOT / "data/plans/manual.json").read_text())
    prev_workers: tuple[tuple[int, ...], ...] = tuple(tuple(z) for z in base_manual["workers"])

    carried_orders: list[Order] = []
    wear = 0
    robot_weeks_seen = 0
    owned_robot = False
    owned_trays = False
    week_reports: list[WeekReport] = []

    for week, wp in enumerate(plan.weeks):
        if (owned_robot and not wp.robot) or (owned_trays and not wp.trays):
            raise ValueError("invalid trusted quarterly plan: irreversible CapEx violated")
        if not wp.robot and (wp.route != "manual" or wp.maintenance):
            raise ValueError("invalid trusted quarterly plan: robot required for route/maintenance")

        owned_robot = owned_robot or wp.robot
        owned_trays = owned_trays or wp.trays

        active_auto = wp.robot and (wp.route != "manual")
        commissioning_active = active_auto and (robot_weeks_seen < comm_weeks)
        if active_auto:
            robot_weeks_seen += 1

        wear_start = wear
        reduced_wear = wear_start - wear_spec["maintenance_reduction"] if wp.maintenance else wear_start
        effective_wear = min(max_wear, max(0, reduced_wear))

        week_world = build_week_world(
            world,
            week,
            commissioning=commissioning_active,
            wear=wear_start,
            maintenance=wp.maintenance,
        )

        exo = exogenous[week]
        week_seed = exo.seed
        carryover_in = len(carried_orders)
        merged_orders = tuple(
            sorted(
                [Order(idx, orig.kind, 0, 0) for idx, orig in enumerate(carried_orders)]
                + [Order(o.id + carryover_in, o.kind, o.arrival, o.due) for o in exo.orders],
                key=lambda o: (o.arrival, o.id),
            )
        )
        week_scenario = Scenario(SCHEMA_VERSION, week_seed, merged_orders)
        shift_plan = wp.to_shift_plan()

        raw_traced = simulate(week_world, shift_plan, week_scenario, trace=True)
        terminal_ids = {e.order_id for e in raw_traced.events if e.kind in _TERMINAL_KINDS}
        unfinished_orders = [o for o in week_scenario.orders if o.id not in terminal_ids]
        if len(unfinished_orders) != raw_traced.unfinished:
            raise RuntimeError("unfinished order extraction mismatch")

        if week < num_weeks - 1:
            carried_orders = unfinished_orders[:carryover_cap]
            carryover_out = len(carried_orders)
        else:
            carried_orders = []
            carryover_out = 0

        if wp.robot and wp.route == "bypass":
            wear_gain = wear_spec["per_week_bypass"]
        elif wp.robot and wp.route == "all":
            elevated_mix = (10_000 - week_world["generator"]["regular_bps"]) >= wear_spec.get(
                "fragile_oversize_threshold_bps", 3000
            )
            wear_gain = wear_spec["per_week_all"] + (
                wear_spec.get("fragile_oversize_all_bonus", 0) if elevated_mix else 0
            )
        else:
            wear_gain = 0
        wear_end = min(max_wear, effective_wear + wear_gain)
        wear = wear_end

        raw_out = raw_traced if trace else replace(raw_traced, events=())
        shift_economy, week_economy = calculate_week(
            world,
            wp,
            prev_workers,
            raw_out,
            carryover_out=carryover_out,
            owned_robot=owned_robot,
            owned_trays=owned_trays,
        )
        prev_workers = wp.workers

        week_reports.append(
            WeekReport(
                week=week,
                label=profiles[week]["label"],
                week_seed=week_seed,
                carryover_in=carryover_in,
                carryover_out=carryover_out,
                wear_start=wear_start,
                wear_end=wear_end,
                commissioning_active=commissioning_active,
                shift_plan=shift_plan,
                scenario=week_scenario,
                raw=raw_out,
                shift_economy=shift_economy,
                week_economy=week_economy,
            )
        )

    prices = world["money"]
    purchase = (prices["robot_purchase"] if owned_robot else 0) + (
        prices["tray_purchase"] if owned_trays else 0
    )
    total_cost = sum(w.week_economy.total for w in week_reports)
    labor_ticks = sum(w.raw.labor_ticks for w in week_reports)
    return QuarterReport(
        schema_version=QUARTERLY_SCHEMA_VERSION,
        seed=seed,
        purchase=purchase,
        total_cost=total_cost,
        labor_ticks=labor_ticks,
        weeks=tuple(week_reports),
    )
