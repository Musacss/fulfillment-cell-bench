"""Black-box polymorphic reference optimizer using ONLY stdlib, observe(), and pilot()."""

from __future__ import annotations

from collections.abc import Sequence
import copy
from fractions import Fraction as F
import json
from typing import Any

_INFEASIBLE_FLOOR = F(1, 10_000)


def _minimum(actual: int, target: int) -> F:
    if target <= 0:
        return F(1)
    return F(1) if actual >= target else F(actual, target)


def _maximum(actual: int, limit: int) -> F:
    if limit <= 0:
        return F(1) if actual <= 0 else F(0)
    return F(1) if actual <= limit else F(limit, actual)


# ==============================================================================
# v1 Single-Shift Reference Solver (100% unbounded parity + budget-safe)
# ==============================================================================


def candidates():
    """Yield candidate v1 shift plans in canonical order for 100% v1 parity."""
    crews = ("1 2 3 4", "1 2 34 23", "1 2 4 23", "1 2 3 4 2", "1 2 3 4 23", "1 2 3 4 1234")
    for crew in crews:
        workers = [[int(ch) for ch in z] for z in crew.split()]
        for trays in (False, True):
            for route in ("all", "bypass"):
                yield {
                    "schema_version": 1,
                    "robot": True,
                    "trays": trays,
                    "route": route,
                    "workers": workers,
                }


def _v1_candidates():
    """Yield candidate v1 shift plans prioritizing trays=True, route='bypass' under tight pilot caps."""
    crews = ("1 2 3 4", "1 2 34 23", "1 2 4 23", "1 2 3 4 2", "1 2 3 4 23", "1 2 3 4 1234")
    for trays, route in ((True, "bypass"), (True, "all"), (False, "bypass"), (False, "all")):
        for crew in crews:
            workers = [[int(ch) for ch in z] for z in crew.split()]
            yield {
                "schema_version": 1,
                "robot": True,
                "trays": trays,
                "route": route,
                "workers": workers,
            }


def _economy_v1_from_pilot(world: dict[str, Any], plan: dict[str, Any], pilot_out: dict[str, Any]) -> dict[str, int]:
    econ = pilot_out.get("economy")
    if isinstance(econ, dict) and "total" in econ and "purchase" in econ:
        return {"purchase": int(econ["purchase"]), "total": int(econ["total"])}
    raw = pilot_out["raw"]
    prices = world["money"]
    purchase = (int(prices["robot_purchase"]) if plan["robot"] else 0) + (
        int(prices["tray_purchase"]) if plan["trays"] else 0
    )
    days = int(prices["depreciation_days"])
    cents, remainder = divmod(purchase, days)
    depreciation = cents + (1 if 2 * remainder >= days else 0)
    total = (
        depreciation
        + (int(prices["robot_service_day"]) if plan["robot"] else 0)
        + len(plan["workers"]) * int(prices["worker_shift"])
        + sum(int(x) for x in raw["overtime_ticks"]) * int(prices["overtime_per_worker_tick"])
        + int(raw["trays_used"]) * int(prices["tray_per_order"])
        + int(raw["pack_started"]) * int(prices["material_per_pack"])
        + int(raw["rework_started"]) * int(prices["rework_start"])
        + (int(raw["good"]) - int(raw["on_time"])) * int(prices["late_good"])
        + (int(raw["scrap"]) + int(raw["unfinished"])) * int(prices["unfulfilled"])
        + int(raw["escaped"]) * int(prices["escaped"])
    )
    return {"purchase": purchase, "total": total}


def _rank_v1(
    world: dict[str, Any],
    plan: dict[str, Any],
    pilots: Sequence[dict[str, Any]],
    base_pilots: Sequence[dict[str, Any]],
    manual_plan: dict[str, Any],
) -> tuple[F, int]:
    raws = [p["raw"] for p in pilots]
    base_raws = [p["raw"] for p in base_pilots]
    econs = [_economy_v1_from_pilot(world, plan, p) for p in pilots]
    base_econs = [_economy_v1_from_pilot(world, manual_plan, p) for p in base_pilots]

    cost = sum(e["total"] for e in econs)
    base_cost = sum(e["total"] for e in base_econs)
    orders = sum(int(r["total"]) for r in raws)
    labor_ticks = sum(int(r["labor_ticks"]) for r in raws)
    base_labor = sum(int(r["labor_ticks"]) for r in base_raws)
    on_time = sum(int(r["on_time"]) for r in raws)
    auto_finished = sum(int(r["auto_finished"]) for r in raws)
    pack_finished = sum(int(r["pack_finished"]) for r in raws)
    purchase = econs[0]["purchase"]

    thresholds = world["threshold_bps"]
    progress = {
        "budget": _maximum(purchase, int(world["money"]["budget"])),
        "volume": min(_minimum(int(r["good"]) * 10_000, int(r["total"]) * int(thresholds["good_each_day"])) for r in raws),
        "on_time": _minimum(on_time * 10_000, orders * int(thresholds["on_time_pooled"])),
        "quality": min(
            _maximum(int(r["escaped"]) * 10_000, int(r["total"]) * int(thresholds["escaped_each_day_max"]))
            for r in raws
        ),
    }
    feasible = all(v >= 1 for v in progress.values())
    share = F(auto_finished, pack_finished) if pack_finished else F(0)
    win = (
        feasible
        and cost < base_cost
        and labor_ticks < base_labor
        and share * 10_000 >= int(thresholds["auto_pack_pooled_min"])
    )
    if win:
        reward = F(1, 5) + F(4, 5) * F(base_cost - cost, base_cost)
    elif feasible:
        reward = F(1, 10) + F(1, 10) / (1 + max(F(0), F(cost - base_cost, base_cost)))
    else:
        reward = max(_INFEASIBLE_FLOOR, F(9, 100) * min(progress.values()))
    return (reward, -labor_ticks)


def solve_v1(episode: Any, obs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Optimize a v1 single-shift Plan via public observe() and pilot()."""
    if obs is None:
        obs = episode.observe()
    world = obs["world"]
    manual = copy.deepcopy(obs["manual"])
    seeds = [int(s["seed"]) for s in obs["history"]]
    if not seeds:
        return manual

    budget_info = obs.get("pilot_budget")
    max_calls: int | None = None
    if isinstance(budget_info, dict) and budget_info.get("max") is not None:
        used0 = int(budget_info.get("used", 0))
        max_calls = min(20, max(0, int(budget_info["max"]) - 1 - used0))
    else:
        try:
            ep_max = episode.max_pilots
            ep_used = episode.pilot_used
        except AttributeError:
            ep_max = None
            ep_used = 0
        if ep_max is not None:
            max_calls = min(20, max(0, int(ep_max) - 1 - int(ep_used or 0)))

    if max_calls is not None and max_calls <= 0:
        return manual

    calls_made = 0
    exhausted = False

    def try_pilot(plan_val: dict[str, Any], seed_val: int) -> dict[str, Any] | None:
        nonlocal calls_made, exhausted
        if exhausted or (max_calls is not None and calls_made >= max_calls):
            exhausted = True
            return None
        try:
            out = episode.pilot(plan_val, seed_val)
            calls_made += 1
            pb = out.get("pilot_budget") if isinstance(out, dict) else None
            if isinstance(pb, dict) and pb.get("used") is not None and pb.get("max") is not None:
                if int(pb["max"]) - 1 - int(pb["used"]) <= 0:
                    exhausted = True
            return out
        except (RuntimeError, ValueError):
            exhausted = True
            return None

    base_seeds = seeds if (max_calls is None or max_calls >= len(seeds) + 4) else seeds[:1]
    base: list[dict[str, Any]] = []
    for s in base_seeds:
        res = try_pilot(manual, s)
        if res is None:
            break
        base.append(res)
    if not base:
        return manual

    if max_calls is None:
        cand_list = list(candidates())
        confirm_top_k = 6
        stage1_limit = len(cand_list)
    else:
        cand_list = list(_v1_candidates())
        rem = max(0, max_calls - calls_made)
        n_other = len(seeds) - 1 if len(base) == len(seeds) else 0
        if n_other > 0 and rem >= 6 + 3 * n_other:
            confirm_top_k = 3
        elif n_other > 0 and rem >= 4 + 2 * n_other:
            confirm_top_k = 2
        elif n_other > 0 and rem >= 2 + n_other:
            confirm_top_k = 1
        else:
            confirm_top_k = 0
        stage1_limit = max(0, rem - confirm_top_k * n_other)

    screened: list[tuple[tuple[F, int], dict[str, Any], dict[str, Any]]] = []
    for value in cand_list[:stage1_limit]:
        first = try_pilot(value, seeds[0])
        if first is None:
            break
        screened.append((_rank_v1(world, value, [first], base[:1], manual), value, first))

    if not screened:
        return manual

    if len(base) < len(seeds) or confirm_top_k == 0:
        best_single, best_val = _rank_v1(world, manual, base[:1], base[:1], manual), manual
        for key1, val, _ in screened:
            if key1 > best_single:
                best_single, best_val = key1, val
        return copy.deepcopy(best_val)

    best, answer = _rank_v1(world, manual, base, base, manual), manual
    partial_best, partial_answer = _rank_v1(world, manual, base[:1], base[:1], manual), manual
    confirmed_any = False

    for key1, value, first in sorted(screened, key=lambda x: x[0], reverse=True)[:confirm_top_k]:
        if key1 > partial_best:
            partial_best, partial_answer = key1, value
        full_reports = [first]
        completed = True
        for s in seeds[1:]:
            nxt = try_pilot(value, s)
            if nxt is None:
                completed = False
                break
            full_reports.append(nxt)
        if not completed:
            break
        confirmed_any = True
        key = _rank_v1(world, value, full_reports, base, manual)
        if key > best:
            best, answer = key, value

    if not confirmed_any and best == _rank_v1(world, manual, base, base, manual):
        return copy.deepcopy(partial_answer)
    return copy.deepcopy(answer)


# ==============================================================================
# v2 12-Week Coupled Quarterly Reference Optimizer
# ==============================================================================


def _plan_key(plan: dict[str, Any]) -> str:
    return json.dumps(plan, sort_keys=True, separators=(",", ":"))


def _is_valid_quarterly_plan(plan: dict[str, Any], world: dict[str, Any]) -> bool:
    if not isinstance(plan, dict) or plan.get("schema_version") != 2:
        return False
    q = world.get("quarterly")
    if not isinstance(q, dict):
        return False
    weeks = plan.get("weeks")
    num_weeks = int(q["weeks"])
    if not isinstance(weeks, list) or len(weeks) != num_weeks:
        return False

    w_spec = world["workers"]
    min_w, max_w = int(w_spec["min"]), int(w_spec["max"])
    valid_zones = {int(z) for z in w_spec["zones"]}
    owned_robot = False
    owned_trays = False

    for wp in weeks:
        if not isinstance(wp, dict):
            return False
        robot = bool(wp.get("robot"))
        trays = bool(wp.get("trays"))
        route = wp.get("route")
        maint = bool(wp.get("maintenance"))
        workers = wp.get("workers")

        if (owned_robot and not robot) or (owned_trays and not trays):
            return False
        owned_robot = owned_robot or robot
        owned_trays = owned_trays or trays

        if route not in ("manual", "all", "bypass"):
            return False
        if not robot and (route != "manual" or maint):
            return False
        if not isinstance(workers, list) or not (min_w <= len(workers) <= max_w):
            return False
        for zlist in workers:
            if not isinstance(zlist, list) or not zlist or len(set(zlist)) != len(zlist):
                return False
            if any(z not in valid_zones for z in zlist):
                return False

    prices = world["money"]
    purchase = (int(prices["robot_purchase"]) if owned_robot else 0) + (
        int(prices["tray_purchase"]) if owned_trays else 0
    )
    if purchase > int(q["money"]["budget"]):
        return False
    return True


def _normalize_crew(crew: list[list[int]], world: dict[str, Any]) -> list[list[int]]:
    w_spec = world["workers"]
    min_w, max_w = int(w_spec["min"]), int(w_spec["max"])
    valid_zones = {int(z) for z in w_spec["zones"]}
    valid_sorted = sorted(valid_zones)
    cleaned = [list(dict.fromkeys(int(z) for z in zlist if int(z) in valid_zones)) for zlist in crew]
    cleaned = [zlist for zlist in cleaned if zlist]
    while len(cleaned) < min_w:
        cleaned.append([valid_sorted[0]])
    return cleaned[:max_w]


def _build_nested_ladders(world: dict[str, Any]) -> dict[str, list[list[list[int]]]]:
    """Construct nested worker ladders so stepping up/down incurs zero retrain_units."""
    ladder_a_raw = [
        [[1], [2], [2, 3], [4]],
        [[1], [2], [3], [4], [2, 3]],
        [[1], [2], [2], [3], [4], [2, 3]],
        [[1], [2], [2], [3], [3], [4], [2, 3]],
        [[1, 2], [2], [2], [3], [3], [4], [2, 3], [3, 4]],
    ]
    ladder_b_raw = [
        [[1], [2], [2, 3], [3, 4]],
        [[1], [2], [3], [2, 3], [3, 4]],
        [[1], [2], [2], [3], [2, 3], [3, 4]],
        [[1], [2], [2], [3], [3], [2, 3], [3, 4]],
        [[1, 2], [2], [2], [3], [3], [4], [2, 3], [3, 4]],
    ]
    ladder_c_raw = [
        [[1], [2], [4], [2, 3]],
        [[1], [2], [3], [4], [2, 3]],
        [[1], [2], [2], [3], [4], [2, 3]],
        [[1], [2], [2], [3], [3], [4], [2, 3]],
        [[1, 2], [2], [2], [3], [3], [4], [2, 3], [3, 4]],
    ]
    return {
        "a": [_normalize_crew(c, world) for c in ladder_a_raw],
        "b": [_normalize_crew(c, world) for c in ladder_b_raw],
        "c": [_normalize_crew(c, world) for c in ladder_c_raw],
    }


def _analyze_weekly_demand(
    world: dict[str, Any], history: Sequence[dict[str, Any]]
) -> list[dict[str, float]]:
    q = world["quarterly"]
    profiles = q["week_profiles"]
    gen = world["generator"]
    t_man = world["time"]["manual"]
    t_jam = float(world["time"]["jam_service"])
    clock = world["clock"]
    shift_cap = float(max(1, int(clock["shift_ticks"]) - int(clock.get("break_length", 0))))
    orders_span = float(gen.get("orders_span", 5))

    weekly_stats: list[dict[str, float]] = []
    for w_idx, prof in enumerate(profiles):
        waves = float(prof.get("waves", gen["waves"]))
        orders_min = float(prof.get("orders_min", gen["orders_min"]))
        analytical_orders = waves * (orders_min + max(0.0, orders_span - 1.0) / 2.0)

        hist_orders: list[float] = []
        hist_non_reg: list[float] = []
        for h in history:
            h_weeks = h.get("weeks") or []
            if w_idx < len(h_weeks):
                hw = h_weeks[w_idx]
                tot = float(hw.get("total_orders", analytical_orders))
                kc = hw.get("kind_counts") or {}
                nr = float(kc.get("fragile", 0) + kc.get("oversize", 0))
                hist_orders.append(tot)
                hist_non_reg.append(nr / max(1.0, tot))

        max_hist = max(hist_orders) if hist_orders else analytical_orders
        mean_hist = (sum(hist_orders) / len(hist_orders)) if hist_orders else analytical_orders
        expected_orders = 0.45 * analytical_orders + 0.35 * max_hist + 0.20 * mean_hist

        reg_bps = float(prof.get("regular_bps", gen["regular_bps"]))
        frag_bps = float(prof.get("fragile_bps", gen["fragile_bps"]))
        p_reg = max(0.0, min(1.0, reg_bps / 10_000.0))
        p_frag = max(0.0, min(1.0 - p_reg, frag_bps / 10_000.0))
        p_over = max(0.0, 1.0 - p_reg - p_frag)
        if hist_non_reg:
            emp_nr = sum(hist_non_reg) / len(hist_non_reg)
            p_reg = 0.6 * p_reg + 0.4 * (1.0 - emp_nr)
            rem = max(0.0, 1.0 - p_reg)
            base_nr = max(1e-6, p_frag + p_over)
            p_frag = rem * (p_frag / base_nr)
            p_over = rem * (p_over / base_nr)

        l1 = expected_orders * (
            p_reg * t_man["regular"][0] + p_frag * t_man["fragile"][0] + p_over * t_man["oversize"][0]
        )
        l2 = expected_orders * (
            p_reg * t_man["regular"][1] + p_frag * t_man["fragile"][1] + p_over * t_man["oversize"][1]
        )
        l3_bypass_pack = expected_orders * (
            p_frag * t_man["fragile"][2] + p_over * t_man["oversize"][2]
        )
        # Include commissioning/wear jam assist allowance on automated regular share
        jam_assist_ticks = expected_orders * p_reg * 0.08 * t_jam
        l3_bypass = l3_bypass_pack + jam_assist_ticks
        l3_manual = expected_orders * (
            p_reg * t_man["regular"][2] + p_frag * t_man["fragile"][2] + p_over * t_man["oversize"][2]
        )
        l4 = (
            expected_orders
            * (p_reg * t_man["regular"][3] + p_frag * t_man["fragile"][3] + p_over * t_man["oversize"][3])
            * 1.04
        )

        due_offset = float(prof.get("due_offset", gen.get("due_offset", 160)))
        tight_due_factor = max(1.0, 165.0 / max(90.0, due_offset))
        fte_23_bypass = ((l2 + l3_bypass) / shift_cap) * (0.7 + 0.3 * tight_due_factor)
        fte_total_manual = (l1 + l2 + l3_manual + l4) / shift_cap

        weekly_stats.append(
            {
                "week": float(w_idx),
                "orders": expected_orders,
                "p_reg": p_reg,
                "p_non_reg": p_frag + p_over,
                "l1_fte": l1 / shift_cap,
                "l2_fte": l2 / shift_cap,
                "l3_bypass_fte": l3_bypass / shift_cap,
                "l4_fte": l4 / shift_cap,
                "fte_23": fte_23_bypass,
                "fte_manual": fte_total_manual,
            }
        )
    return weekly_stats


def _simulate_maintenance_schedule(
    num_weeks: int,
    routes: Sequence[str],
    weekly_stats: Sequence[dict[str, float]],
    rungs: Sequence[int],
    wear_spec: dict[str, Any],
    *,
    comm_weeks: int,
    wear_trigger: int,
    avoid_surge: bool,
    pre_surge_trigger: int | None,
    comm_maint: bool = True,
) -> list[bool]:
    per_bypass = int(wear_spec.get("per_week_bypass", 1))
    per_all = int(wear_spec.get("per_week_all", 3))
    all_bonus = int(wear_spec.get("fragile_oversize_all_bonus", 1))
    reduction = max(1, int(wear_spec.get("maintenance_reduction", 5)))
    max_wear = int(wear_spec.get("max_wear", 12))

    maint_flags = [False] * num_weeks
    wear = 0
    robot_weeks_seen = 0
    for w in range(num_weeks):
        route = routes[w]
        if route == "manual":
            continue
        in_commissioning = robot_weeks_seen < comm_weeks
        robot_weeks_seen += 1
        is_surge = rungs[w] >= 1
        next_is_surge = (w + 1 < num_weeks) and (rungs[w + 1] >= 1)
        is_last = w == num_weeks - 1

        do_maint = False
        if wear > 0:
            if wear_trigger <= 1:
                do_maint = True
            elif comm_maint and in_commissioning:
                do_maint = True
            elif not is_last:
                surge_cap = wear_trigger + 2
                if wear >= wear_trigger and (not avoid_surge or not is_surge or wear >= surge_cap):
                    do_maint = True
                elif (
                    pre_surge_trigger is not None
                    and not is_surge
                    and next_is_surge
                    and wear >= pre_surge_trigger
                ):
                    do_maint = True
            else:
                if wear >= wear_trigger + 2:
                    do_maint = True

        maint_flags[w] = do_maint
        eff_wear = min(max_wear, max(0, wear - reduction if do_maint else wear))
        if route == "bypass":
            gain = per_bypass
        else:
            elevated = weekly_stats[w]["p_non_reg"] >= 0.30
            gain = per_all + (all_bonus if elevated else 0)
        wear = min(max_wear, eff_wear + gain)

    return maint_flags


def _smooth_rungs_for_churn(
    rungs: list[int], weekly_stats: Sequence[dict[str, float]], world: dict[str, Any]
) -> list[int]:
    q_money = world["quarterly"]["money"]
    shift_week_cost = int(world["money"]["worker_shift"]) * int(q_money["shifts_per_week"])
    churn_roundtrip = int(q_money["hire_cost"]) + int(q_money["layoff_cost"])
    out = list(rungs)
    if churn_roundtrip >= shift_week_cost:
        for w in range(1, len(out) - 1):
            if out[w - 1] > out[w] and out[w + 1] > out[w]:
                out[w] = min(out[w - 1], out[w + 1])
    return out


def _generate_analytical_quarterly_candidates(
    world: dict[str, Any],
    history: Sequence[dict[str, Any]],
    manual_plan: dict[str, Any],
) -> list[dict[str, Any]]:
    q = world["quarterly"]
    num_weeks = int(q["weeks"])
    prices = world["money"]
    budget = int(q["money"]["budget"])
    robot_cost = int(prices["robot_purchase"])
    tray_cost = int(prices["tray_purchase"])
    wear_spec = q["wear"]
    auto_min_bps = int(q["threshold_bps"]["auto_pack_pooled_min"])

    if robot_cost > budget:
        return [copy.deepcopy(manual_plan)]

    has_trays = (robot_cost + tray_cost) <= budget
    weekly_stats = _analyze_weekly_demand(world, history)
    ladders = _build_nested_ladders(world)

    total_expected_orders = sum(s["orders"] for s in weekly_stats)
    pooled_reg_bps = int(
        round(
            10_000.0
            * sum(s["orders"] * s["p_reg"] for s in weekly_stats)
            / max(1.0, total_expected_orders)
        )
    )

    comm_weeks = int(q["commissioning"]["weeks"])

    seen: set[str] = set()
    candidates_out: list[dict[str, Any]] = []

    def _add_candidate(cand_plan: dict[str, Any]) -> None:
        if _is_valid_quarterly_plan(cand_plan, world):
            key = _plan_key(cand_plan)
            if key not in seen:
                seen.add(key)
                candidates_out.append(cand_plan)

    # High-surge-only cross-skilled candidates (skipping single-week promo churn & zero retrain prefix)
    high_surge_weeks = {
        idx for idx, prof in enumerate(q["week_profiles"]) if int(prof.get("waves", 0)) >= 13
    }
    off_43 = _normalize_crew([[1], [2], [4, 3], [2, 3]], world)
    peak_43_nested = _normalize_crew([[1], [2], [4, 3], [2, 3], [2, 3]], world)
    off_34 = _normalize_crew([[1], [2], [3, 4], [2, 3]], world)
    peak_34_nested = _normalize_crew([[1], [2], [3, 4], [2, 3], [2, 3]], world)
    default_route = "all" if pooled_reg_bps < auto_min_bps + 600 else "bypass"
    all_active_maint = set(range(1, num_weeks))
    even_maint = {w for w in range(2, num_weeks, 2)}
    even_non_surge_maint = {w for w in even_maint if w not in high_surge_weeks}
    for off_crew, peak_crew in ((off_43, peak_43_nested), (off_34, peak_34_nested)):
        for mset in (all_active_maint, even_maint, even_non_surge_maint):
            _add_candidate(
                {
                    "schema_version": 2,
                    "weeks": [
                        {
                            "robot": True,
                            "trays": has_trays,
                            "route": default_route,
                            "maintenance": w in mset,
                            "workers": [list(z) for z in (peak_crew if w in high_surge_weeks else off_crew)],
                        }
                        for w in range(num_weeks)
                    ],
                }
            )

    # Parameterized candidate configurations:
    # (ladder, tau1, tau2, tau3, wear_trig, avoid_surge, pre_surge, comm_maint, comm_boost, route_mode)
    configs: list[tuple[str, float, float, float, int, bool, int | None, bool, bool, str]] = []
    if pooled_reg_bps < auto_min_bps + 600:
        configs.append(("a", 1.65, 2.85, 3.65, 2, False, 1, True, False, "hybrid_all"))
    configs.extend(
        [
            ("a", 1.82, 3.08, 3.95, 1, False, 1, True, False, "bypass"),
            ("c", 1.82, 3.08, 3.95, 2, True, 2, False, False, "bypass"),
            ("a", 1.82, 3.08, 3.95, 2, True, 2, False, False, "bypass"),
            ("a", 1.68, 2.95, 3.80, 1, False, 1, True, False, "bypass"),
            ("b", 1.82, 3.05, 3.90, 1, False, 1, True, False, "bypass"),
            ("a", 1.60, 2.75, 3.60, 1, False, 1, True, True, "bypass"),
        ]
    )

    for (
        ladder_key,
        tau1,
        tau2,
        tau3,
        wear_trig,
        avoid_surge,
        pre_surge,
        comm_maint,
        comm_boost,
        route_mode,
    ) in configs:
        ladder = ladders[ladder_key]
        rungs: list[int] = []
        routes: list[str] = []
        for w, st in enumerate(weekly_stats):
            fte = st["fte_23"]
            if st["l4_fte"] >= 0.86:
                fte += 0.25
            if fte >= tau3:
                r = 3
            elif fte >= tau2:
                r = 2
            elif fte >= tau1:
                r = 1
            else:
                r = 0
            if comm_boost and w < comm_weeks and fte >= tau1 - 0.35:
                r = max(r, 1)
            rungs.append(min(r, len(ladder) - 1))

            if route_mode == "hybrid_all" and st["p_non_reg"] <= 0.22:
                routes.append("all")
            else:
                routes.append("bypass")

        rungs = _smooth_rungs_for_churn(rungs, weekly_stats, world)
        maint_flags = _simulate_maintenance_schedule(
            num_weeks,
            routes,
            weekly_stats,
            rungs,
            wear_spec,
            comm_weeks=comm_weeks,
            wear_trigger=wear_trig,
            avoid_surge=avoid_surge,
            pre_surge_trigger=pre_surge,
            comm_maint=comm_maint,
        )

        plan = {
            "schema_version": 2,
            "weeks": [
                {
                    "robot": True,
                    "trays": has_trays,
                    "route": routes[w],
                    "maintenance": maint_flags[w],
                    "workers": [list(z) for z in ladder[rungs[w]]],
                }
                for w in range(num_weeks)
            ],
        }
        _add_candidate(plan)

    if not candidates_out:
        candidates_out.append(copy.deepcopy(manual_plan))
    return candidates_out


def _grade_quarterly_surrogate(
    world: dict[str, Any],
    quarters: Sequence[dict[str, Any]],
    base_quarters: Sequence[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Exact Fraction quarterly evaluation + worst-week SLA margin diagnostics."""
    q_spec = world["quarterly"]
    thresholds = q_spec["threshold_bps"]
    budget_limit = int(q_spec["money"]["budget"])
    good_each_week = int(thresholds["good_each_week"])
    good_pooled = int(thresholds["good_pooled"])
    on_time_pooled = int(thresholds["on_time_pooled"])
    escaped_max = int(thresholds["escaped_each_week_max"])
    auto_min_bps = int(thresholds["auto_pack_pooled_min"])

    purchase = int(quarters[0]["purchase"])
    cost = sum(int(q["total_cost"]) for q in quarters)
    labor_ticks = sum(int(q["labor_ticks"]) for q in quarters)
    orders = sum(int(w["raw"]["total"]) - int(w["carryover_in"]) for q in quarters for w in q["weeks"])
    good = sum(int(w["raw"]["good"]) for q in quarters for w in q["weeks"])
    on_time = sum(int(w["raw"]["on_time"]) for q in quarters for w in q["weeks"])
    auto_finished = sum(int(w["raw"]["auto_finished"]) for q in quarters for w in q["weeks"])
    pack_finished = sum(int(w["raw"]["pack_finished"]) for q in quarters for w in q["weeks"])

    vol_each_week = min(
        _minimum(int(w["raw"]["good"]) * 10_000, int(w["raw"]["total"]) * good_each_week)
        for q in quarters
        for w in q["weeks"]
    )
    vol_pooled = _minimum(good * 10_000, orders * good_pooled)
    progress = {
        "budget": _maximum(purchase, budget_limit),
        "volume": min(vol_each_week, vol_pooled),
        "on_time": _minimum(on_time * 10_000, orders * on_time_pooled),
        "quality": min(
            _maximum(int(w["raw"]["escaped"]) * 10_000, int(w["raw"]["total"]) * escaped_max)
            for q in quarters
            for w in q["weeks"]
        ),
    }
    feasible = all(v >= 1 for v in progress.values())
    share = F(auto_finished, pack_finished) if pack_finished else F(0)
    auto_ok = (share * 10_000) >= auto_min_bps

    min_good_margin_bps = min(
        (int(w["raw"]["good"]) * 10_000) // max(1, int(w["raw"]["total"])) - good_each_week
        for q in quarters
        for w in q["weeks"]
    )
    pooled_good_margin_bps = (good * 10_000) // max(1, orders) - good_pooled
    on_time_margin_bps = (on_time * 10_000) // max(1, orders) - on_time_pooled
    min_escaped_margin_bps = min(
        escaped_max - ((int(w["raw"]["escaped"]) * 10_000 + max(1, int(w["raw"]["total"])) - 1) // max(1, int(w["raw"]["total"])))
        for q in quarters
        for w in q["weeks"]
    )
    carryover_peak = max(int(w["carryover_out"]) for q in quarters for w in q["weeks"])
    max_wear_end = max(int(w["wear_end"]) for q in quarters for w in q["weeks"])

    if base_quarters:
        base_cost = sum(int(bq["total_cost"]) for bq in base_quarters)
        base_labor = sum(int(bq["labor_ticks"]) for bq in base_quarters)
    else:
        # Conservative analytical fallback when pilot_cap < 2 prevents baseline pilot
        shifts = int(q_spec["money"]["shifts_per_week"])
        manual_crew_size = int(world["workers"]["max"])
        base_cost = max(1, len(quarters) * len(quarters[0]["weeks"]) * manual_crew_size * int(world["money"]["worker_shift"]) * shifts)
        base_labor = max(1, labor_ticks + 1)

    win = feasible and cost < base_cost and labor_ticks < base_labor and auto_ok
    if win:
        reward = F(1, 5) + F(4, 5) * F(base_cost - cost, base_cost)
    elif feasible:
        overrun = max(F(0), F(cost - base_cost, base_cost))
        if purchase > 0 and not auto_ok:
            auto_prog = (
                _minimum(auto_finished * 10_000, pack_finished * auto_min_bps)
                if pack_finished and auto_min_bps > 0
                else F(0)
            )
            overrun += F(1) - auto_prog
        if purchase > 0 and not (labor_ticks < base_labor):
            overrun += F(labor_ticks - base_labor + 1, max(1, base_labor))
        reward = F(1, 10) + F(1, 10) / (1 + overrun)
    else:
        reward = max(_INFEASIBLE_FLOOR, F(9, 100) * min(progress.values()))

    robust = (
        win
        and min_good_margin_bps >= 160
        and pooled_good_margin_bps >= 100
        and on_time_margin_bps >= 140
        and min_escaped_margin_bps >= 12
        and carryover_peak <= 6
    )

    return {
        "feasible": feasible,
        "win": win,
        "robust": robust,
        "reward": reward,
        "cost": cost,
        "labor_ticks": labor_ticks,
        "min_good_margin_bps": min_good_margin_bps,
        "min_escaped_margin_bps": min_escaped_margin_bps,
        "on_time_margin_bps": on_time_margin_bps,
        "carryover_peak": carryover_peak,
        "zero_wear_maintained": max_wear_end <= 1,
    }


def _candidate_rank_key(grade_info: dict[str, Any]) -> tuple[int, int, int, F, int, int]:
    return (
        1 if grade_info["robust"] else 0,
        1 if grade_info["win"] else 0,
        1 if grade_info["feasible"] else 0,
        grade_info["reward"],
        min(grade_info["min_good_margin_bps"], 450),
        -grade_info["labor_ticks"],
    )


def _synthesize_empirical_repairs(
    world: dict[str, Any],
    screened_entries: Sequence[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]],
    seen_keys: set[str],
) -> list[dict[str, Any]]:
    """Inspect week-level pilot telemetry to synthesize bottleneck-repair and cost-trim plans."""
    q_spec = world["quarterly"]
    thresholds = q_spec["threshold_bps"]
    good_each = int(thresholds["good_each_week"])
    escaped_max = int(thresholds["escaped_each_week_max"])
    num_weeks = int(q_spec["weeks"])
    ladder = _build_nested_ladders(world)["a"]
    shift_ticks = int(world["clock"]["shift_ticks"])

    repairs: list[dict[str, Any]] = []

    def crew_rung_index(workers: list[list[int]]) -> int:
        n = len(workers)
        for idx, l_crew in enumerate(ladder):
            if len(l_crew) >= n:
                return idx
        return len(ladder) - 1

    # 1. Bottleneck / SLA margin repair on top 2 screened plans
    for _, plan, q_rep in screened_entries[:3]:
        repaired = copy.deepcopy(plan)
        changed = False
        for w_idx, wr in enumerate(q_rep["weeks"]):
            raw = wr["raw"]
            tot = max(1, int(raw["total"]))
            good_bps = (int(raw["good"]) * 10_000) // tot
            esc_bps = (int(raw["escaped"]) * 10_000 + tot - 1) // tot
            overtime_sum = sum(int(x) for x in raw["overtime_ticks"])
            carry_out = int(wr["carryover_out"])
            wear_start = int(wr["wear_start"])

            if good_bps < good_each + 220 or carry_out > 2 or overtime_sum > 240:
                cur_rung = crew_rung_index(repaired["weeks"][w_idx]["workers"])
                if cur_rung + 1 < len(ladder):
                    repaired["weeks"][w_idx]["workers"] = [list(z) for z in ladder[cur_rung + 1]]
                    changed = True
                if int(wr["carryover_in"]) > 2 and w_idx >= 1:
                    prev_rung = crew_rung_index(repaired["weeks"][w_idx - 1]["workers"])
                    if prev_rung + 1 < len(ladder):
                        repaired["weeks"][w_idx - 1]["workers"] = [list(z) for z in ladder[prev_rung + 1]]
                        changed = True

            if esc_bps > escaped_max - 20 or (wear_start >= 3 and (good_bps < good_each + 260 or esc_bps > escaped_max - 35)):
                if repaired["weeks"][w_idx]["route"] == "all":
                    repaired["weeks"][w_idx]["route"] = "bypass"
                    changed = True
                maint_w = max(1, w_idx - 1) if w_idx >= 2 else w_idx
                if maint_w >= 1 and maint_w < num_weeks and repaired["weeks"][maint_w]["robot"]:
                    if not repaired["weeks"][maint_w]["maintenance"]:
                        repaired["weeks"][maint_w]["maintenance"] = True
                        changed = True

        if changed and _is_valid_quarterly_plan(repaired, world):
            k = _plan_key(repaired)
            if k not in seen_keys:
                seen_keys.add(k)
                repairs.append(repaired)

    # 2. Lean cost-trim variant on the best robust winning plan
    for g_info, plan, q_rep in screened_entries:
        if not g_info["robust"]:
            continue
        trimmed = copy.deepcopy(plan)
        slack_candidates: list[tuple[float, int, int]] = []
        for w_idx, wr in enumerate(q_rep["weeks"]):
            if int(q_spec["week_profiles"][w_idx].get("waves", 0)) >= 12:
                continue
            workers = trimmed["weeks"][w_idx]["workers"]
            cur_rung = crew_rung_index(workers)
            if cur_rung <= 0:
                continue
            raw = wr["raw"]
            overtime_sum = sum(int(x) for x in raw["overtime_ticks"])
            if (
                int(wr["carryover_out"]) == 0
                and int(raw["unfinished"]) == 0
                and overtime_sum <= 80
                and int(raw["good"]) * 10_000 >= int(raw["total"]) * (good_each + 450)
            ):
                util = float(raw["labor_ticks"]) / max(1.0, float(len(workers) * shift_ticks))
                if util < 0.80:
                    slack_candidates.append((util, w_idx, cur_rung))

        if slack_candidates:
            slack_candidates.sort(key=lambda item: item[0])
            _, target_w, cur_rung = slack_candidates[0]
            trimmed["weeks"][target_w]["workers"] = [list(z) for z in ladder[cur_rung - 1]]
            if _is_valid_quarterly_plan(trimmed, world):
                k = _plan_key(trimmed)
                if k not in seen_keys:
                    seen_keys.add(k)
                    repairs.append(trimmed)
        break

    return repairs


def solve_quarterly(episode: Any, obs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Optimize a 12-week v2 QuarterlyPlan strictly within <= min(20, max_pilots - 1) pilots."""
    if obs is None:
        obs = episode.observe()

    world = obs["world"]
    q = world["quarterly"]
    manual = copy.deepcopy(obs["manual"])
    history = obs.get("history") or []
    dev_seeds = [int(s) for s in (obs.get("development_seeds") or [h["seed"] for h in history])]

    budget_info = obs.get("pilot_budget") or {}
    used0 = int(budget_info.get("used", 0))
    max_p = int(budget_info.get("max", q.get("max_pilots", 24)))
    pilot_cap = min(20, max(0, max_p - 1 - used0))

    prices = world["money"]
    has_trays = (int(prices["robot_purchase"]) + int(prices["tray_purchase"])) <= int(
        q["money"]["budget"]
    )
    analytical_candidates = _generate_analytical_quarterly_candidates(world, history, manual)
    if pilot_cap <= 0 or not dev_seeds:
        if not has_trays:
            return copy.deepcopy(manual)
        return copy.deepcopy(analytical_candidates[0])

    # Identify hardest development seed from public exogenous summary
    seed_difficulty: dict[int, float] = {s: 0.0 for s in dev_seeds}
    for h in history:
        s = int(h["seed"])
        if s in seed_difficulty:
            kc = h.get("kind_counts") or {}
            non_reg = float(kc.get("fragile", 0) + kc.get("oversize", 0))
            seed_difficulty[s] = float(h.get("total_orders", 0)) + 0.5 * non_reg
    ordered_seeds = sorted(dev_seeds, key=lambda s: seed_difficulty.get(s, 0.0), reverse=True)
    hard_seed = ordered_seeds[0]
    other_seeds = ordered_seeds[1:]

    calls_made = 0
    exhausted = False

    def try_pilot(plan_val: dict[str, Any], seed_val: int) -> dict[str, Any] | None:
        nonlocal calls_made, exhausted
        if exhausted or calls_made >= pilot_cap:
            exhausted = True
            return None
        try:
            res = episode.pilot(plan_val, seed_val)
            calls_made += 1
            pb = res.get("pilot_budget")
            if isinstance(pb, dict) and pb.get("used") is not None and pb.get("max") is not None:
                rem_hw = int(pb["max"]) - 1 - int(pb["used"])
                if rem_hw <= 0:
                    exhausted = True
            return res
        except (RuntimeError, ValueError):
            exhausted = True
            return None

    # Ultra-tight budget mode (1..3 pilots allowed)
    if pilot_cap <= 3:
        best_plan = copy.deepcopy(manual)
        best_key: tuple[int, int, int, F, int, int] | None = None
        for cand in analytical_candidates[:pilot_cap]:
            rep = try_pilot(cand, hard_seed)
            if rep is None:
                break
            g = _grade_quarterly_surrogate(world, [rep], None)
            if g["feasible"]:
                key = _candidate_rank_key(g)
                if best_key is None or key > best_key:
                    best_key = key
                    best_plan = cand
        return copy.deepcopy(best_plan)

    # Allocate pilots across Baseline, Stage 1 Screen, Stage 2 Empirical Repair, Stage 3 Multi-Seed Confirm
    n_seeds = len(ordered_seeds)
    use_full_baseline = pilot_cap >= (n_seeds + 6)
    baseline_seeds = ordered_seeds if use_full_baseline else [hard_seed]

    base_by_seed: dict[int, dict[str, Any]] = {}
    for s in baseline_seeds:
        b_rep = try_pilot(manual, s)
        if b_rep is None:
            break
        base_by_seed[s] = b_rep

    if hard_seed not in base_by_seed:
        if not has_trays:
            return copy.deepcopy(manual)
        return copy.deepcopy(analytical_candidates[0])

    # Reserve pilots for Stage 3 confirmation on other_seeds
    n_other = len(other_seeds) if use_full_baseline else 0
    if pilot_cap >= 16 and n_other > 0:
        confirm_top_k = 3
    elif pilot_cap >= 10 and n_other > 0:
        confirm_top_k = 2
    elif n_other > 0 and (pilot_cap - calls_made) >= (n_other + 2):
        confirm_top_k = 1
    else:
        confirm_top_k = 0

    reserved_confirm = confirm_top_k * n_other
    screen_and_repair_budget = max(1, (pilot_cap - calls_made) - reserved_confirm)
    stage2_reserve = 2 if screen_and_repair_budget >= 6 else (1 if screen_and_repair_budget >= 4 else 0)
    stage1_limit = max(1, screen_and_repair_budget - stage2_reserve)

    seen_keys = {_plan_key(c) for c in analytical_candidates}
    screened: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []

    # Stage 1: Screen diverse analytical candidates on hard_seed
    for cand in analytical_candidates[:stage1_limit]:
        rep = try_pilot(cand, hard_seed)
        if rep is None:
            break
        g1 = _grade_quarterly_surrogate(world, [rep], [base_by_seed[hard_seed]])
        screened.append((g1, cand, rep))

    if not screened:
        return copy.deepcopy(manual)

    screened.sort(key=lambda item: _candidate_rank_key(item[0]), reverse=True)

    # Stage 2: Empirical Bottleneck Repair & Cost Trim on hard_seed
    remaining_for_stage2 = max(0, (pilot_cap - calls_made) - reserved_confirm)
    if remaining_for_stage2 > 0 and confirm_top_k >= 1:
        synthesized = _synthesize_empirical_repairs(world, screened, seen_keys)
        for rep_cand in synthesized[:remaining_for_stage2]:
            rep = try_pilot(rep_cand, hard_seed)
            if rep is None:
                break
            g1 = _grade_quarterly_surrogate(world, [rep], [base_by_seed[hard_seed]])
            screened.append((g1, rep_cand, rep))
        screened.sort(key=lambda item: _candidate_rank_key(item[0]), reverse=True)

    # Stage 3: Multi-Seed Confirmation across all development_seeds
    manual_quarters = [base_by_seed[s] for s in ordered_seeds if s in base_by_seed]
    best_manual_grade = _grade_quarterly_surrogate(world, manual_quarters, manual_quarters)
    best_rank = _candidate_rank_key(best_manual_grade)
    best_answer = copy.deepcopy(manual)
    confirmed_any = False

    if confirm_top_k > 0 and len(manual_quarters) == len(ordered_seeds):
        for _, cand, hard_rep in screened[:confirm_top_k]:
            by_seed: dict[int, dict[str, Any]] = {hard_seed: hard_rep}
            complete = True
            for s in other_seeds:
                nxt = try_pilot(cand, s)
                if nxt is None:
                    complete = False
                    break
                by_seed[s] = nxt
            if not complete:
                break
            confirmed_any = True
            cand_quarters = [by_seed[s] for s in ordered_seeds]
            base_quarters = [base_by_seed[s] for s in ordered_seeds]
            g_full = _grade_quarterly_surrogate(world, cand_quarters, base_quarters)
            r_key = _candidate_rank_key(g_full)
            if r_key > best_rank:
                best_rank = r_key
                best_answer = cand

    if not confirmed_any:
        single_manual_grade = _grade_quarterly_surrogate(
            world, [base_by_seed[hard_seed]], [base_by_seed[hard_seed]]
        )
        single_best_rank = _candidate_rank_key(single_manual_grade)
        for g1, cand, _ in screened:
            r1 = _candidate_rank_key(g1)
            if r1 > single_best_rank:
                single_best_rank = r1
                best_answer = cand

    return copy.deepcopy(best_answer)


def solve(episode: Any) -> dict[str, Any]:
    """Polymorphic black-box reference optimizer supporting both v2 quarterly and v1 shift episodes."""
    obs = episode.observe()
    if obs.get("schema_version") == 2 or obs.get("manual", {}).get("schema_version") == 2:
        return solve_quarterly(episode, obs)
    return solve_v1(episode, obs)
