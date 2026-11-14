"""Causal AI mistake diagnostics and 3D HUD callout generator for v2 quarterly rollouts."""

from collections.abc import Mapping
from fractions import Fraction
import json
from typing import Any

from .contracts import (
    QUARTERLY_SCHEMA_VERSION,
    Evaluation,
    InvalidPlan,
    QuarterReport,
    WeekPlan,
    WeekReport,
    World,
)
from .grading import grade_quarters, invalid
from .quarterly import manual_quarterly_value, simulate_quarter
from .validation import parse_quarterly_plan

DIAGNOSTICS_FORMAT_V1 = "robotization-bench.quarter-diagnostics.v1"

_SEVERITY_RANK = {"critical": 3, "major": 2, "minor": 1}
_CAUSE_PRIORITY = {
    "invalid_submission_schema": 100,
    "unstaffed_zone3_jam_deadlock": 95,
    "all_route_wear_blowout": 85,
    "bare_robot_commissioning_spike": 82,
    "skipped_pre_peak_maintenance": 78,
    "holiday_peak_understaffing": 75,
    "unprofitable_low_automation": 70,
    "excess_idle_payroll": 68,
    "backlog_snowball": 55,
}

_LABEL_DISPLAY = {
    "baseline_open": "Baseline Open",
    "baseline_steady": "Baseline Steady",
    "autumn_ramp": "Autumn Ramp",
    "fragile_promo": "Fragile Promo",
    "mid_quarter": "Mid-Quarter",
    "pre_peak_prep": "Pre-Peak Prep",
    "early_holiday": "Early Holiday",
    "singles_day_wave": "Singles' Day",
    "black_friday_peak": "Black Friday",
    "cyber_week_peak": "Cyber Week",
    "post_peak_steady": "Post-Peak",
    "quarter_close": "Quarter Close",
}

_REASON_TEXT = {
    "budget": "CapEx exceeded €18,000 budget ceiling",
    "volume": "completed good-order volume fell below SLA (90% weekly / 95% pooled)",
    "on_time": "pooled on-time delivery fell below 88% SLA",
    "quality": "weekly escaped defects exceeded 1.2% SLA ceiling",
    "cost": "operating cost failed to beat manual baseline",
    "labor": "worker labor ticks failed to beat manual baseline",
    "automation": "automated pack share fell below 30% minimum",
}


def _to_wire(value: Any) -> Any:
    return json.loads(json.dumps(value, allow_nan=False))


def _eur(cents: int) -> float:
    return round(cents / 100.0, 2)


def _fmt_eur_compact(cents: int) -> str:
    euros = round(abs(cents) / 100.0)
    sign = "-" if cents < 0 else ""
    return f"{sign}€{euros:,}"


def _week_tag(week: int, label: str) -> str:
    pretty = _LABEL_DISPLAY.get(label, label.replace("_", " ").title())
    return f"Week {week} ({pretty})"


def _range_tag(weeks: list[int], labels: list[str]) -> str:
    ordered = sorted(set(weeks))
    if len(ordered) == 1:
        w = ordered[0]
        return _week_tag(w, labels[w])
    spans: list[str] = []
    start = prev = ordered[0]
    for w in ordered[1:]:
        if w == prev + 1:
            prev = w
        else:
            spans.append(f"{start}–{prev}" if start != prev else f"{start}")
            start = prev = w
    spans.append(f"{start}–{prev}" if start != prev else f"{start}")
    return "Weeks " + ", ".join(spans)


def _unpack_evaluation(ev: Evaluation | Mapping[str, Any]) -> tuple[bool, bool, bool, int, int, list[str]]:
    if isinstance(ev, Mapping):
        valid = bool(ev["valid"])
        feasible = bool(ev["feasible"])
        win = bool(ev["win"])
        r_num = int(ev["reward_num"])
        r_den = int(ev["reward_den"])
        raw_reasons = ev.get("reasons", ())
    else:
        valid = bool(ev.valid)
        feasible = bool(ev.feasible)
        win = bool(ev.win)
        r_num = int(ev.reward_num)
        r_den = int(ev.reward_den)
        raw_reasons = ev.reasons
    if isinstance(raw_reasons, str):
        reasons = [raw_reasons] if raw_reasons else []
    else:
        reasons = [str(r) for r in raw_reasons]
    return valid, feasible, win, r_num, r_den, reasons


def _extract_week_highlights(world: World, wr: WeekReport) -> tuple[int, int, list[dict[str, Any]]]:
    """Scan a week's v1 Event trace once to count jams/assists and extract top 3D scrub highlights."""
    clock = world["clock"]
    tick_sec = int(clock["tick_seconds"])
    horizon = int(clock["shift_ticks"]) + int(clock["overtime_ticks"])
    caps = {
        2: int(world["capacity"]["pick"]),
        3: int(world["capacity"]["pack"]),
        4: int(world["capacity"]["qc"]),
    }

    waiting = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    reserved = {2: 0, 3: 0, 4: 0}
    open_jam: tuple[int, int] | None = None
    jam_count = 0
    assist_count = 0

    jam_intervals: list[tuple[int, int, int, bool]] = []
    escaped_events: list[tuple[int, int, str | None]] = []
    scrap_events: list[tuple[int, int, str | None]] = []

    sat_open: dict[int, int] = {}
    sat_intervals: list[tuple[int, int, int]] = []

    events = wr.raw.events
    idx = 0
    n_events = len(events)
    while idx < n_events:
        t = events[idx].tick
        while idx < n_events and events[idx].tick == t:
            ev = events[idx]
            idx += 1
            k = ev.kind
            if k == "jam":
                jam_count += 1
                if ev.order_id is not None:
                    open_jam = (t, ev.order_id)
            elif k == "assist":
                assist_count += 1
            elif k == "enqueue" and ev.stage is not None:
                q_key = 5 if (ev.stage == 3 and ev.attempt == 1) else ev.stage
                waiting[q_key] += 1
            elif k == "start" and ev.stage is not None:
                q_key = 5 if (ev.stage == 3 and ev.attempt == 1) else ev.stage
                waiting[q_key] = max(0, waiting[q_key] - 1)
                if ev.stage < 4:
                    reserved[ev.stage + 1] += 1
            elif k == "finish" and ev.stage is not None:
                if ev.stage < 4:
                    reserved[ev.stage + 1] = max(0, reserved[ev.stage + 1] - 1)
                if ev.resource == "robot" and open_jam is not None:
                    jam_intervals.append((open_jam[0], t, open_jam[1], False))
                    open_jam = None
            elif k == "escaped" and ev.order_id is not None:
                escaped_events.append((t, ev.order_id, ev.resource))
            elif k == "scrap" and ev.order_id is not None:
                scrap_events.append((t, ev.order_id, ev.resource))

        for s in (2, 3, 4):
            is_full = (waiting[s] + reserved[s]) >= caps[s]
            if is_full and s not in sat_open:
                sat_open[s] = t
            elif not is_full and s in sat_open:
                start_t = sat_open.pop(s)
                if t - start_t >= 12:
                    sat_intervals.append((s, start_t, t))

    if open_jam is not None:
        jam_intervals.append((open_jam[0], horizon, open_jam[1], True))
    for s, start_t in sat_open.items():
        if horizon - start_t >= 12:
            sat_intervals.append((s, start_t, horizon))

    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for s_tick, e_tick, oid, deadlocked in jam_intervals:
        dur = max(0, e_tick - s_tick)
        if deadlocked:
            candidates.append(
                (
                    100,
                    dur,
                    {
                        "kind": "jam_deadlock",
                        "start_tick": s_tick,
                        "end_tick": e_tick,
                        "focus_tick": s_tick,
                        "start_seconds": s_tick * tick_sec,
                        "end_seconds": e_tick * tick_sec,
                        "order_id": oid,
                        "resource": "robot",
                        "stage": 3,
                        "severity": "critical",
                        "reason": (
                            f"Robot jammed on order #{oid} at tick {s_tick} with no Zone-3 assist "
                            f"(frozen {dur} ticks until shift end)"
                        ),
                    },
                )
            )

    for esc_tick, oid, res in escaped_events:
        s_tick = max(0, esc_tick - 4)
        e_tick = min(horizon, esc_tick + 2)
        candidates.append(
            (
                90,
                e_tick - s_tick,
                {
                    "kind": "escaped",
                    "start_tick": s_tick,
                    "end_tick": e_tick,
                    "focus_tick": esc_tick,
                    "start_seconds": s_tick * tick_sec,
                    "end_seconds": e_tick * tick_sec,
                    "order_id": oid,
                    "resource": res,
                    "stage": 4,
                    "severity": "critical",
                    "reason": f"Escaped defect on order #{oid} passed QC at tick {esc_tick}",
                },
            )
        )

    normal_jams = sorted(
        [j for j in jam_intervals if not j[3]],
        key=lambda x: (-(x[1] - x[0]), x[0]),
    )[:2]
    for s_tick, e_tick, oid, _ in normal_jams:
        dur = max(0, e_tick - s_tick)
        sev = "critical" if (dur >= 24 or jam_count >= 25) else "warning"
        candidates.append(
            (
                75,
                dur,
                {
                    "kind": "jam",
                    "start_tick": s_tick,
                    "end_tick": e_tick,
                    "focus_tick": s_tick,
                    "start_seconds": s_tick * tick_sec,
                    "end_seconds": e_tick * tick_sec,
                    "order_id": oid,
                    "resource": "robot",
                    "stage": 3,
                    "severity": sev,
                    "reason": f"Robot jam on order #{oid} blocked Stage 3 for {dur} ticks ([{s_tick}, {e_tick}])",
                },
            )
        )

    top_sats = sorted(sat_intervals, key=lambda x: (-(x[2] - x[1]), x[1]))[:2]
    for s_stage, s_tick, e_tick in top_sats:
        dur = e_tick - s_tick
        candidates.append(
            (
                65,
                dur,
                {
                    "kind": "queue_bottleneck",
                    "start_tick": s_tick,
                    "end_tick": e_tick,
                    "focus_tick": s_tick,
                    "start_seconds": s_tick * tick_sec,
                    "end_seconds": e_tick * tick_sec,
                    "order_id": None,
                    "resource": None,
                    "stage": s_stage,
                    "severity": "critical" if dur >= 90 else "warning",
                    "reason": f"Buffer Q{s_stage} full ({caps[s_stage]}/{caps[s_stage]}) for {dur} ticks ([{s_tick}, {e_tick}])",
                },
            )
        )

    for scr_tick, oid, res in scrap_events[:1]:
        s_tick = max(0, scr_tick - 4)
        e_tick = min(horizon, scr_tick + 2)
        candidates.append(
            (
                50,
                e_tick - s_tick,
                {
                    "kind": "scrap",
                    "start_tick": s_tick,
                    "end_tick": e_tick,
                    "focus_tick": scr_tick,
                    "start_seconds": s_tick * tick_sec,
                    "end_seconds": e_tick * tick_sec,
                    "order_id": oid,
                    "resource": res,
                    "stage": 4,
                    "severity": "warning",
                    "reason": f"Repeat-pack defect scrapped order #{oid} at tick {scr_tick}",
                },
            )
        )

    candidates.sort(key=lambda item: (-item[0], -item[1], item[2]["start_tick"]))
    return jam_count, assist_count, [item[2] for item in candidates[:5]]


def _week_penalty_cents(wr: WeekReport) -> int:
    c = wr.week_economy.costs
    return int(c["late"] + c["backlog_holding"] + c["unfulfilled"] + c["escaped"] + c["rework"] + c["overtime"])


def _impact_cents(
    weeks: list[int],
    q_weeks: tuple[WeekReport, ...],
    m_weeks: tuple[WeekReport, ...],
    ref_weeks: tuple[WeekReport, ...] | None,
) -> int:
    excess_vs_manual = sum(max(0, q_weeks[w].week_economy.total - m_weeks[w].week_economy.total) for w in weeks)
    excess_pen_manual = sum(max(0, _week_penalty_cents(q_weeks[w]) - _week_penalty_cents(m_weeks[w])) for w in weeks)
    excess_vs_ref = (
        sum(max(0, q_weeks[w].week_economy.total - ref_weeks[w].week_economy.total) for w in weeks)
        if ref_weeks is not None
        else 0
    )
    raw_pen = sum(_week_penalty_cents(q_weeks[w]) for w in weeks)
    return max(excess_vs_manual, excess_pen_manual, excess_vs_ref, raw_pen)


def _build_headline_summary(
    *,
    feasible: bool,
    win: bool,
    reasons: list[str],
    total_cost_cents: int,
    manual_cost_cents: int,
    ref_cost_cents: int | None,
    key_mistakes: list[dict[str, Any]],
    auto_share_bps: int,
    wear_peak: int,
) -> str:
    delta_man = total_cost_cents - manual_cost_cents
    if win:
        saved = _fmt_eur_compact(manual_cost_cents - total_cost_cents)
        ref_clause = ""
        if ref_cost_cents is not None:
            diff_ref = total_cost_cents - ref_cost_cents
            if abs(diff_ref) < 5_000:
                ref_clause = " matching the phased reference rollout."
            elif diff_ref < 0:
                ref_clause = f" beating the reference plan by {_fmt_eur_compact(-diff_ref)}."
            else:
                ref_clause = f" within {_fmt_eur_compact(diff_ref)} of the reference plan."
        else:
            ref_clause = "."
        return (
            f"Rollout succeeded across all 12 weeks, saving {saved} vs manual baseline with "
            f"{auto_share_bps / 100:.1f}% automated packing and peak wear capped at {wear_peak}/12{ref_clause}"
        )

    reason_labels = [_REASON_TEXT.get(r, r) for r in reasons]
    reason_str = "; ".join(reason_labels) if reason_labels else "suboptimal rollout economics"
    if not feasible:
        lead = key_mistakes[0]["hud_callout"] if key_mistakes else "SLA constraints failed during rollout"
        loss = _fmt_eur_compact(-abs(delta_man)) if delta_man > 0 else _fmt_eur_compact(delta_man)
        return f"Infeasible rollout ({loss} vs manual): {reason_str}. Primary root cause — {lead}."

    # Feasible but did not win
    lead = key_mistakes[0]["hud_callout"] if key_mistakes else reason_str
    if delta_man == 0:
        return f"Feasible manual-equivalent baseline (€0 vs manual), but missed win criteria: {reason_str}. {lead}."
    cost_note = (
        f"cost {_fmt_eur_compact(delta_man)} more than manual"
        if delta_man > 0
        else f"saved {_fmt_eur_compact(-delta_man)} vs manual"
    )
    return f"Feasible rollout ({cost_note}) missed win criteria ({reason_str}). {lead}."


def diagnose_quarter_plan(
    world: World,
    plan_dict: dict[str, Any],
    seed: int,
    *,
    reference_plan_dict: dict[str, Any] | None = None,
    evaluation: Evaluation | None = None,
) -> dict[str, Any]:
    """Simulate a v2 12-week plan with trace=True and emit causal AI mistake diagnostics for 3D HUD & README."""
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    if type(world) is not dict or type(world.get("quarterly")) is not dict:
        raise ValueError("world missing quarterly specification")

    q_world_id = world["quarterly"].get("world_id", world.get("world_id"))
    try:
        plan = parse_quarterly_plan(plan_dict, world)
    except InvalidPlan as exc:
        ev_bad = evaluation if evaluation is not None else invalid(str(exc))
        _, _, _, r_num, r_den, reasons = _unpack_evaluation(ev_bad)
        if not reasons:
            reasons = [str(exc)]
        msg = reasons[0]
        return _to_wire(
            {
                "diagnostics_format": DIAGNOSTICS_FORMAT_V1,
                "schema_version": QUARTERLY_SCHEMA_VERSION,
                "world_id": q_world_id,
                "seed": seed,
                "overall": {
                    "valid": False,
                    "feasible": False,
                    "win": False,
                    "reward_float": round(float(Fraction(r_num, r_den)), 6),
                    "reward_fraction": f"{r_num}/{r_den}",
                    "failure_reasons": reasons,
                    "total_cost_eur": None,
                    "cost_delta_vs_manual_eur": None,
                    "cost_delta_vs_reference_eur": None,
                    "headline_summary": f"Submission rejected before simulation: {msg}.",
                },
                "key_mistakes": [
                    {
                        "severity": "critical",
                        "week_range": [0, 0],
                        "weeks": [0],
                        "category": "invalid_submission_schema",
                        "euro_impact_cents": 0,
                        "evidence_metrics": {"valid": False},
                        "hud_callout": f"Invalid submission schema: {msg}",
                    }
                ],
                "timeline_weeks": [],
            }
        )

    quarter = simulate_quarter(world, plan, seed, trace=True)
    manual_plan = parse_quarterly_plan(manual_quarterly_value(world), world)
    manual_quarter = (
        quarter
        if plan == manual_plan
        else simulate_quarter(world, manual_plan, seed, trace=False)
    )

    ref_quarter: QuarterReport | None = None
    if reference_plan_dict is not None:
        ref_plan = parse_quarterly_plan(reference_plan_dict, world)
        if ref_plan == plan:
            ref_quarter = quarter
        elif ref_plan == manual_plan:
            ref_quarter = manual_quarter
        else:
            ref_quarter = simulate_quarter(world, ref_plan, seed, trace=False)

    ev_resolved = (
        evaluation
        if evaluation is not None
        else grade_quarters(world, plan, [quarter], [manual_quarter])
    )
    valid, feasible, win, r_num, r_den, reasons = _unpack_evaluation(ev_resolved)

    q_spec = world["quarterly"]
    thresholds = q_spec["threshold_bps"]
    max_wear = int(q_spec["wear"]["max_wear"])
    profiles = q_spec["week_profiles"]
    num_weeks = len(quarter.weeks)

    q_weeks = quarter.weeks
    m_weeks = manual_quarter.weeks
    ref_weeks = ref_quarter.weeks if ref_quarter is not None else None
    p_weeks: tuple[WeekPlan, ...] = plan.weeks
    labels = [wr.label for wr in q_weeks]

    jams: list[int] = []
    assists: list[int] = []
    lates: list[int] = []
    has_z3: list[bool] = []
    week_highlights: list[list[dict[str, Any]]] = []
    week_mistakes_map: list[list[str]] = [[] for _ in range(num_weeks)]
    week_mistake_sev: list[int] = [0 for _ in range(num_weeks)]

    for w_idx, (wr, wp) in enumerate(zip(q_weeks, p_weeks, strict=True)):
        j_cnt, a_cnt, hl_list = _extract_week_highlights(world, wr)
        jams.append(j_cnt)
        assists.append(a_cnt)
        lates.append(wr.raw.good - wr.raw.on_time)
        has_z3.append(any(3 in z for z in wp.workers))
        week_highlights.append(hl_list)

    mistakes: list[dict[str, Any]] = []

    def add_mistake(
        *,
        category: str,
        severity: str,
        weeks: list[int],
        impact_cents: int,
        evidence: dict[str, Any],
        callout: str,
        per_week_callout: dict[int, str],
    ) -> None:
        mistakes.append(
            {
                "severity": severity,
                "week_range": [min(weeks), max(weeks)],
                "weeks": sorted(weeks),
                "category": category,
                "euro_impact_cents": int(max(0, impact_cents)),
                "evidence_metrics": evidence,
                "hud_callout": callout,
            }
        )
        sev_num = _SEVERITY_RANK[severity]
        for w_i, note in per_week_callout.items():
            week_mistakes_map[w_i].append(note)
            if sev_num > week_mistake_sev[w_i]:
                week_mistake_sev[w_i] = sev_num

    # 1. Unstaffed Zone 3 jam / rework deadlock
    deadlock_weeks = [
        w
        for w in range(num_weeks)
        if p_weeks[w].robot
        and p_weeks[w].route != "manual"
        and not has_z3[w]
        and (jams[w] > assists[w] or q_weeks[w].raw.unfinished >= 15 or p_weeks[w].route == "all")
    ]
    if deadlock_weeks:
        imp = _impact_cents(deadlock_weeks, q_weeks, m_weeks, ref_weeks)
        unfin_sum = sum(q_weeks[w].raw.unfinished for w in deadlock_weeks)
        jam_sum = sum(jams[w] for w in deadlock_weeks)
        carry_peak = max(q_weeks[w].carryover_out for w in deadlock_weeks)
        pw = {
            w: (
                f"{_week_tag(w, labels[w])}: Robot active with 0 Zone-3 workers -> "
                f"unassisted jam froze Stage 3 ({q_weeks[w].raw.unfinished} unfinished)"
            )
            for w in deadlock_weeks
        }
        add_mistake(
            category="unstaffed_zone3_jam_deadlock",
            severity="critical",
            weeks=deadlock_weeks,
            impact_cents=imp,
            evidence={
                "jams": jam_sum,
                "assists": sum(assists[w] for w in deadlock_weeks),
                "wear_peak": max(q_weeks[w].wear_end for w in deadlock_weeks),
                "carryover_peak": carry_peak,
                "unfinished": unfin_sum,
                "escaped": sum(q_weeks[w].raw.escaped for w in deadlock_weeks),
                "late": sum(lates[w] for w in deadlock_weeks),
            },
            callout=(
                f"{_range_tag(deadlock_weeks, labels)}: No worker assigned to Zone 3 while robot ran "
                f"route={p_weeks[deadlock_weeks[0]].route!r} -> first jam froze Stage 3 "
                f"({unfin_sum} unfinished, {_fmt_eur_compact(-imp)})"
            ),
            per_week_callout=pw,
        )

    # 2. Naive route='all' wear blowout & fragile/oversize jam storm
    all_blowout_weeks = [
        w
        for w in range(num_weeks)
        if p_weeks[w].robot
        and p_weeks[w].route == "all"
        and has_z3[w]
        and (q_weeks[w].wear_end >= 6 or jams[w] >= 25 or lates[w] >= 35)
    ]
    if all_blowout_weeks:
        all_route_weeks = [w for w in range(num_weeks) if p_weeks[w].robot and p_weeks[w].route == "all" and has_z3[w]]
        imp = _impact_cents(all_route_weeks, q_weeks, m_weeks, ref_weeks)
        worst_w = max(
            all_blowout_weeks,
            key=lambda w: (q_weeks[w].wear_end, jams[w], lates[w], q_weeks[w].carryover_out),
        )
        worst_imp = _impact_cents([worst_w], q_weeks, m_weeks, ref_weeks)
        maint_used = sum(1 for w in all_route_weeks if p_weeks[w].maintenance)
        maint_note = " & no maintenance" if maint_used == 0 else ""
        sev = "critical" if (not feasible or max(q_weeks[w].wear_end for w in all_route_weeks) >= 9) else "major"
        pw = {
            w: (
                f"{_week_tag(w, labels[w])}: Wear {q_weeks[w].wear_end}/{max_wear} with route='all'{maint_note} -> "
                f"{jams[w]} jams, {lates[w]} late orders"
            )
            for w in all_blowout_weeks
        }
        add_mistake(
            category="all_route_wear_blowout",
            severity=sev,
            weeks=all_route_weeks,
            impact_cents=imp,
            evidence={
                "jams": sum(jams[w] for w in all_route_weeks),
                "wear_peak": max(q_weeks[w].wear_end for w in all_route_weeks),
                "carryover_peak": max(q_weeks[w].carryover_out for w in all_route_weeks),
                "escaped": sum(q_weeks[w].raw.escaped for w in all_route_weeks),
                "late": sum(lates[w] for w in all_route_weeks),
            },
            callout=(
                f"{_week_tag(worst_w, labels[worst_w])}: Wear hit {q_weeks[worst_w].wear_end}/{max_wear} "
                f"with route='all'{maint_note} -> {jams[worst_w]} jams, {lates[worst_w]} late orders "
                f"({_fmt_eur_compact(-worst_imp)}; quarter: {sum(jams[w] for w in all_route_weeks)} jams)"
            ),
            per_week_callout=pw,
        )

    # 3. Bare robot without trays commissioning / jam spike
    bare_weeks = [
        w
        for w in range(num_weeks)
        if p_weeks[w].robot
        and not p_weeks[w].trays
        and p_weeks[w].route != "manual"
        and has_z3[w]
    ]
    bare_comm_weeks = [w for w in bare_weeks if q_weeks[w].commissioning_active]
    if bare_weeks and (bare_comm_weeks or sum(jams[w] for w in bare_weeks) >= 120):
        focus_weeks = bare_comm_weeks if bare_comm_weeks else bare_weeks
        imp = _impact_cents(bare_weeks, q_weeks, m_weeks, ref_weeks)
        comm_jams = sum(jams[w] for w in focus_weeks)
        comm_late = sum(lates[w] for w in focus_weeks)
        sev = "critical" if not feasible else "major"
        pw = {
            w: (
                f"{_week_tag(w, labels[w])}: Bare robot (trays=false"
                f"{', commissioning' if q_weeks[w].commissioning_active else ''}) -> "
                f"{jams[w]} jams, {lates[w]} late orders"
            )
            for w in bare_weeks
            if q_weeks[w].commissioning_active or jams[w] >= 25
        }
        add_mistake(
            category="bare_robot_commissioning_spike",
            severity=sev,
            weeks=focus_weeks,
            impact_cents=imp,
            evidence={
                "jams": comm_jams,
                "quarter_jams": sum(jams[w] for w in bare_weeks),
                "wear_peak": max(q_weeks[w].wear_end for w in bare_weeks),
                "carryover_peak": max(q_weeks[w].carryover_out for w in bare_weeks),
                "escaped": sum(q_weeks[w].raw.escaped for w in bare_weeks),
                "late": comm_late,
            },
            callout=(
                f"{_range_tag(focus_weeks, labels)}: Deployed bare robot without trays=true during commissioning -> "
                f"{comm_jams} jams & {comm_late} late orders in ramp-up ({_fmt_eur_compact(-imp)} quarter impact)"
            ),
            per_week_callout=pw,
        )

    # 4. Skipped preventive maintenance before/during holiday peak
    high_wear_nomaint = [
        w
        for w in range(num_weeks)
        if p_weeks[w].robot
        and p_weeks[w].route != "manual"
        and not p_weeks[w].maintenance
        and has_z3[w]
        and (q_weeks[w].wear_start >= 5 or q_weeks[w].wear_end >= 6)
        and p_weeks[w].route != "all"
    ]
    if high_wear_nomaint:
        imp = _impact_cents(high_wear_nomaint, q_weeks, m_weeks, ref_weeks)
        worst_w = max(
            high_wear_nomaint,
            key=lambda w: (q_weeks[w].wear_end, q_weeks[w].raw.escaped, jams[w], lates[w]),
        )
        sev = "critical" if (not feasible or max(q_weeks[w].wear_end for w in high_wear_nomaint) >= 9) else "major"
        pw = {
            w: (
                f"{_week_tag(w, labels[w])}: Skipped maintenance at wear {q_weeks[w].wear_end}/{max_wear} -> "
                f"{jams[w]} jams, {q_weeks[w].raw.escaped} escaped defects, {lates[w]} late"
            )
            for w in high_wear_nomaint
        }
        add_mistake(
            category="skipped_pre_peak_maintenance",
            severity=sev,
            weeks=high_wear_nomaint,
            impact_cents=imp,
            evidence={
                "jams": sum(jams[w] for w in high_wear_nomaint),
                "wear_peak": max(q_weeks[w].wear_end for w in high_wear_nomaint),
                "carryover_peak": max(q_weeks[w].carryover_out for w in high_wear_nomaint),
                "escaped": sum(q_weeks[w].raw.escaped for w in high_wear_nomaint),
                "late": sum(lates[w] for w in high_wear_nomaint),
            },
            callout=(
                f"{_range_tag(high_wear_nomaint, labels)}: Skipped pre-peak maintenance let wear climb to "
                f"{max(q_weeks[w].wear_end for w in high_wear_nomaint)}/{max_wear} -> "
                f"{sum(jams[w] for w in high_wear_nomaint)} jams & "
                f"{sum(q_weeks[w].raw.escaped for w in high_wear_nomaint)} escaped defects ({_fmt_eur_compact(-imp)})"
            ),
            per_week_callout=pw,
        )

    # 5. Holiday / promo peak understaffing
    peak_indices = [
        w
        for w, prof in enumerate(profiles)
        if int(prof.get("waves", 10)) >= 12 or (10_000 - int(prof.get("regular_bps", 7800))) >= 3000
    ]
    understaffed_peaks = [
        w
        for w in peak_indices
        if (has_z3[w] or not p_weeks[w].robot)
        and (
            (p_weeks[w].robot and p_weeks[w].route == "bypass" and len(p_weeks[w].workers) <= 4)
            or (not p_weeks[w].robot and len(p_weeks[w].workers) <= 5)
            or (p_weeks[w].robot and len(p_weeks[w].workers) <= 3)
        )
        and (lates[w] >= 30 or q_weeks[w].raw.unfinished >= 5)
    ]
    if understaffed_peaks:
        imp = _impact_cents(understaffed_peaks, q_weeks, m_weeks, ref_weeks)
        worst_w = max(understaffed_peaks, key=lambda w: (q_weeks[w].carryover_out, lates[w]))
        sev = "critical" if (not feasible or max(q_weeks[w].carryover_out for w in understaffed_peaks) >= 20) else "major"
        pw = {
            w: (
                f"{_week_tag(w, labels[w])}: Only {len(p_weeks[w].workers)} workers on promo/peak wave -> "
                f"{lates[w]} late orders, {q_weeks[w].carryover_out} carried over"
            )
            for w in understaffed_peaks
        }
        add_mistake(
            category="holiday_peak_understaffing",
            severity=sev,
            weeks=understaffed_peaks,
            impact_cents=imp,
            evidence={
                "jams": sum(jams[w] for w in understaffed_peaks),
                "wear_peak": max(q_weeks[w].wear_end for w in understaffed_peaks),
                "carryover_peak": max(q_weeks[w].carryover_out for w in understaffed_peaks),
                "escaped": sum(q_weeks[w].raw.escaped for w in understaffed_peaks),
                "late": sum(lates[w] for w in understaffed_peaks),
                "min_peak_workers": min(len(p_weeks[w].workers) for w in understaffed_peaks),
            },
            callout=(
                f"{_range_tag(understaffed_peaks, labels)}: Kept {len(p_weeks[worst_w].workers)}-worker off-peak crew "
                f"through surge waves -> {sum(lates[w] for w in understaffed_peaks)} late orders & "
                f"peak carryover {max(q_weeks[w].carryover_out for w in understaffed_peaks)} ({_fmt_eur_compact(-imp)})"
            ),
            per_week_callout=pw,
        )

    # 6. Compounding multi-week backlog snowball
    snowball_weeks = [
        w
        for w in range(num_weeks)
        if q_weeks[w].carryover_in >= 10 or q_weeks[w].carryover_out >= 10
    ]
    if snowball_weeks and max(q_weeks[w].carryover_out for w in range(num_weeks)) >= 15:
        imp = sum(
            q_weeks[w].week_economy.costs["backlog_holding"]
            + q_weeks[w].week_economy.costs["unfulfilled"]
            + max(0, q_weeks[w].week_economy.costs["late"] - m_weeks[w].week_economy.costs["late"])
            for w in snowball_weeks
        )
        carry_peak = max(q_weeks[w].carryover_out for w in snowball_weeks)
        sev = "critical" if carry_peak >= 30 else "major"
        pw = {
            w: (
                f"{_week_tag(w, labels[w])}: Backlog snowball ({q_weeks[w].carryover_in} carried in -> "
                f"{q_weeks[w].carryover_out} carried out, {lates[w]} late)"
            )
            for w in snowball_weeks
        }
        add_mistake(
            category="backlog_snowball",
            severity=sev,
            weeks=snowball_weeks,
            impact_cents=imp,
            evidence={
                "jams": sum(jams[w] for w in snowball_weeks),
                "wear_peak": max(q_weeks[w].wear_end for w in snowball_weeks),
                "carryover_peak": carry_peak,
                "escaped": sum(q_weeks[w].raw.escaped for w in snowball_weeks),
                "late": sum(lates[w] for w in snowball_weeks),
            },
            callout=(
                f"{_range_tag(snowball_weeks, labels)}: Unfinished orders snowballed across weeks "
                f"(carryover peaked at {carry_peak}/{q_spec['carryover_cap']}) -> "
                f"automatic arrival=0/due=0 late penalties ({_fmt_eur_compact(-imp)})"
            ),
            per_week_callout=pw,
        )

    # 7. Excess idle payroll / overstaffing alongside automation
    def _fixed_and_payroll(wr: WeekReport) -> int:
        c = wr.week_economy.costs
        return int(c["shifts"] + c["cross_skill"] + c["hiring_retraining"] + c["depreciation"] + c["service"])

    overstaffed_weeks = [
        w
        for w in range(num_weeks)
        if (
            (p_weeks[w].robot and p_weeks[w].route != "manual" and len(p_weeks[w].workers) >= 6)
            or len(p_weeks[w].workers) >= 7
        )
        and _fixed_and_payroll(q_weeks[w]) > _fixed_and_payroll(m_weeks[w])
    ]
    if overstaffed_weeks:
        imp = sum(
            max(0, _fixed_and_payroll(q_weeks[w]) - _fixed_and_payroll(m_weeks[w]))
            for w in overstaffed_weeks
        )
        max_w_cnt = max(len(p_weeks[w].workers) for w in overstaffed_weeks)
        pw = {
            w: (
                f"{_week_tag(w, labels[w])}: {len(p_weeks[w].workers)}-worker payroll + CapEx exceeded manual "
                f"by {_fmt_eur_compact(_fixed_and_payroll(q_weeks[w]) - _fixed_and_payroll(m_weeks[w]))}"
            )
            for w in overstaffed_weeks
        }
        add_mistake(
            category="excess_idle_payroll",
            severity="major" if not win else "minor",
            weeks=overstaffed_weeks,
            impact_cents=imp,
            evidence={
                "jams": sum(jams[w] for w in overstaffed_weeks),
                "wear_peak": max(q_weeks[w].wear_end for w in overstaffed_weeks),
                "carryover_peak": max(q_weeks[w].carryover_out for w in overstaffed_weeks),
                "escaped": sum(q_weeks[w].raw.escaped for w in overstaffed_weeks),
                "late": sum(lates[w] for w in overstaffed_weeks),
                "max_workers": max_w_cnt,
            },
            callout=(
                f"{_range_tag(overstaffed_weeks, labels)}: Kept {max_w_cnt} workers alongside robot CapEx -> "
                f"idle shift payroll wiped out automation savings ({_fmt_eur_compact(-imp)} vs manual)"
            ),
            per_week_callout=pw,
        )

    # 8. Unprofitable low / idle automation (manual baseline, idle CapEx, or delayed token robot)
    total_auto = sum(wr.raw.auto_finished for wr in q_weeks)
    total_pack = sum(wr.raw.pack_finished for wr in q_weeks)
    auto_share_bps = (total_auto * 10_000) // total_pack if total_pack > 0 else 0
    auto_min_bps = int(thresholds["auto_pack_pooled_min"])
    idle_capex_weeks = [w for w in range(num_weeks) if p_weeks[w].robot and p_weeks[w].route == "manual"]
    low_auto_weeks = [w for w in range(num_weeks) if p_weeks[w].route == "manual"]
    if (auto_share_bps < auto_min_bps or "automation" in reasons or idle_capex_weeks) and low_auto_weeks:
        imp_vs_ref = (
            max(0, quarter.total_cost - ref_quarter.total_cost)
            if ref_quarter is not None
            else max(0, quarter.total_cost - manual_quarter.total_cost)
        )
        imp = max(imp_vs_ref, max(0, quarter.total_cost - manual_quarter.total_cost))
        if idle_capex_weeks:
            desc = (
                f"{_range_tag(idle_capex_weeks, labels)}: Purchased robot CapEx but kept route='manual' -> "
                f"0 automated packs while paying depreciation & service ({_fmt_eur_compact(-imp)})"
            )
            pw = {
                w: f"{_week_tag(w, labels[w])}: Robot owned but idle on route='manual'"
                for w in idle_capex_weeks
            }
            target_weeks = idle_capex_weeks
        else:
            loss_label = (
                f"{_fmt_eur_compact(-imp)} vs phased reference"
                if ref_quarter is not None and imp > 0
                else "missed 30% automation target"
            )
            desc = (
                f"{_range_tag(low_auto_weeks, labels)}: Automated pack share only {auto_share_bps / 100:.1f}% "
                f"(target >= {auto_min_bps / 100:.0f}%) -> unautomated 6-worker shifts & peak late orders ({loss_label})"
            )
            pw = {
                w: f"{_week_tag(w, labels[w])}: Unautomated manual packing ({lates[w]} late orders)"
                for w in low_auto_weeks
                if lates[w] > 0 or w in {0, 8}
            }
            target_weeks = low_auto_weeks

        add_mistake(
            category="unprofitable_low_automation",
            severity="major",
            weeks=target_weeks,
            impact_cents=imp,
            evidence={
                "jams": sum(jams[w] for w in target_weeks),
                "wear_peak": max(q_weeks[w].wear_end for w in target_weeks),
                "carryover_peak": max(q_weeks[w].carryover_out for w in target_weeks),
                "escaped": sum(q_weeks[w].raw.escaped for w in target_weeks),
                "late": sum(lates[w] for w in target_weeks),
                "auto_pack_share_bps": auto_share_bps,
            },
            callout=desc,
            per_week_callout=pw,
        )

    mistakes.sort(
        key=lambda m: (
            -_SEVERITY_RANK[m["severity"]],
            -_CAUSE_PRIORITY.get(m["category"], 50),
            -m["euro_impact_cents"],
        )
    )

    timeline_weeks: list[dict[str, Any]] = []
    for w_idx, (wr, wp, mr) in enumerate(zip(q_weeks, p_weeks, m_weeks, strict=True)):
        r = wr.raw
        good_sla_bad = r.good * 10_000 < r.total * int(thresholds["good_each_week"])
        esc_sla_bad = r.escaped * 10_000 > r.total * int(thresholds["escaped_each_week_max"])
        deadlock_now = jams[w_idx] > assists[w_idx]
        late_share_high = lates[w_idx] * 10_000 > r.total * (10_000 - int(thresholds["on_time_pooled"]))

        if (
            good_sla_bad
            or esc_sla_bad
            or deadlock_now
            or wr.carryover_out >= 20
            or wr.wear_end >= 10
        ):
            status = "critical"
        elif (
            wr.carryover_out > 0
            or wr.wear_end >= 6
            or late_share_high
            or week_mistake_sev[w_idx] >= 2
        ):
            status = "warning"
        else:
            status = "ok"

        timeline_weeks.append(
            {
                "week": w_idx,
                "label": wr.label,
                "decisions": {
                    "robot": wp.robot,
                    "trays": wp.trays,
                    "route": wp.route,
                    "maintenance": wp.maintenance,
                    "workers": [list(z) for z in wp.workers],
                    "worker_count": len(wp.workers),
                    "has_zone3_worker": has_z3[w_idx],
                },
                "metrics": {
                    "orders_total": r.total,
                    "exogenous_orders": r.total - wr.carryover_in,
                    "carryover_in": wr.carryover_in,
                    "carryover_out": wr.carryover_out,
                    "good": r.good,
                    "on_time": r.on_time,
                    "late": lates[w_idx],
                    "escaped": r.escaped,
                    "scrap": r.scrap,
                    "unfinished": r.unfinished,
                    "jams": jams[w_idx],
                    "assists": assists[w_idx],
                    "rework_started": r.rework_started,
                    "auto_finished": r.auto_finished,
                    "pack_finished": r.pack_finished,
                    "wear_start": wr.wear_start,
                    "wear_end": wr.wear_end,
                    "commissioning_active": wr.commissioning_active,
                    "labor_ticks": r.labor_ticks,
                    "overtime_ticks_total": sum(r.overtime_ticks),
                    "week_cost_cents": wr.week_economy.total,
                    "week_cost_eur": _eur(wr.week_economy.total),
                    "manual_week_cost_eur": _eur(mr.week_economy.total),
                    "cost_delta_vs_manual_eur": _eur(wr.week_economy.total - mr.week_economy.total),
                },
                "status": status,
                "active_mistakes": week_mistakes_map[w_idx],
                "highlight_ticks": week_highlights[w_idx],
            }
        )

    wear_peak_all = max(wr.wear_end for wr in q_weeks)
    headline = _build_headline_summary(
        feasible=feasible,
        win=win,
        reasons=reasons,
        total_cost_cents=quarter.total_cost,
        manual_cost_cents=manual_quarter.total_cost,
        ref_cost_cents=ref_quarter.total_cost if ref_quarter is not None else None,
        key_mistakes=mistakes,
        auto_share_bps=auto_share_bps,
        wear_peak=wear_peak_all,
    )

    payload = {
        "diagnostics_format": DIAGNOSTICS_FORMAT_V1,
        "schema_version": QUARTERLY_SCHEMA_VERSION,
        "world_id": q_world_id,
        "seed": seed,
        "overall": {
            "valid": valid,
            "feasible": feasible,
            "win": win,
            "reward_float": round(float(Fraction(r_num, r_den)), 6),
            "reward_fraction": f"{r_num}/{r_den}",
            "failure_reasons": reasons,
            "total_cost_cents": quarter.total_cost,
            "total_cost_eur": _eur(quarter.total_cost),
            "cost_delta_vs_manual_cents": quarter.total_cost - manual_quarter.total_cost,
            "cost_delta_vs_manual_eur": _eur(quarter.total_cost - manual_quarter.total_cost),
            "cost_delta_vs_reference_cents": (
                quarter.total_cost - ref_quarter.total_cost if ref_quarter is not None else None
            ),
            "cost_delta_vs_reference_eur": (
                _eur(quarter.total_cost - ref_quarter.total_cost) if ref_quarter is not None else None
            ),
            "purchase_eur": _eur(quarter.purchase),
            "labor_ticks": quarter.labor_ticks,
            "base_labor_ticks": manual_quarter.labor_ticks,
            "auto_pack_share_bps": auto_share_bps,
            "headline_summary": headline,
        },
        "key_mistakes": mistakes,
        "timeline_weeks": timeline_weeks,
    }
    return _to_wire(payload)
