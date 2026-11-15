"""Check the public event stream, without access to the scheduler's internal queues."""
from collections import Counter, defaultdict
from dataclasses import replace

import pytest

from robotization_bench.contracts import Order, Plan, Scenario, load_world
from robotization_bench.engine import simulate
from robotization_bench.scenarios import generate


def check_trace(world, plan, day, raw):
    by_id = {o.id: o for o in day.orders}
    # For each order the last transition uniquely determines its next legal state.
    state = {}
    limited = {2: "pick", 3: "pack", 4: "qc"}
    occupied = defaultdict(set)  # Same slot is retained from reservation until dequeue.
    active = {}
    done = Counter()
    last_tick = -1
    horizon = world["clock"]["shift_ticks"] + world["clock"]["overtime_ticks"]
    for event in raw.events:
        tick, kind, i, stage, attempt = event.tick, event.kind, event.order_id, event.stage, event.attempt
        assert last_tick <= tick <= horizon
        last_tick = tick
        if kind == "break":
            continue
        assert i in by_id and attempt in (0, 1)
        previous = state.get(i)
        if kind == "arrival":
            assert previous is None and tick == by_id[i].arrival
        elif kind == "enqueue":
            if stage == 1:
                assert previous == ("arrival", 1, 0) and attempt == 0
            elif stage == 3 and attempt == 1:
                assert previous == ("finish", 4, 0)
            else:
                assert previous == ("finish", stage - 1, attempt)
                assert i in occupied[stage]
        elif kind == "start":
            assert tick < horizon and previous == ("enqueue", stage, attempt)
            if stage in limited and (stage, attempt) != (3, 1):
                occupied[stage].remove(i)
            if stage < 4:
                assert i not in occupied[stage + 1]
                occupied[stage + 1].add(i)
                assert len(occupied[stage + 1]) <= world["capacity"][limited[stage + 1]]
            if stage == 3:
                automatic = attempt == 0 and (
                    plan.route == "all" or (plan.route == "bypass" and by_id[i].kind == "regular")
                )
                assert (event.resource == "robot") == automatic
            assert event.resource not in active
            active[event.resource] = (i, stage, attempt)
        elif kind == "finish":
            assert previous == ("start", stage, attempt)
            assert active.pop(event.resource) == (i, stage, attempt)
        elif kind in ("jam", "assist", "walk"):
            assert previous == ("start", stage, attempt)
            if kind in ("jam", "assist"):
                assert active["robot"] == (i, 3, 0)
            continue
        elif kind in ("good", "escaped", "scrap"):
            assert previous == ("finish", 4, attempt)
            done[kind] += 1
            if kind == "good" and tick <= by_id[i].due:
                done["on_time"] += 1
        else:
            pytest.fail(f"unknown transition {event}")
        state[i] = (kind, stage, attempt)

    assert state.keys() == by_id.keys()
    assert all(v[0] in {"start", "enqueue", "good", "escaped", "scrap"} for v in state.values())
    assert raw.unfinished == sum(v[0] in {"start", "enqueue"} for v in state.values())
    assert (raw.good, raw.on_time, raw.escaped, raw.scrap) == tuple(done[k] for k in ("good", "on_time", "escaped", "scrap"))
    assert raw.total == len(by_id) == raw.good + raw.escaped + raw.scrap + raw.unfinished


def check_worker_intervals(world, plan, raw):
    shift = world["clock"]["shift_ticks"]
    horizon = shift + world["clock"]["overtime_ticks"]
    labor = 0
    overtime = []
    for index, zones in enumerate(plan.workers):
        events = [e for e in raw.events if e.resource == f"w{index}"]
        position, available, last_work, took_break = zones[0], 0, 0, False
        for event in events:
            if event.kind not in ("start", "assist", "break"):
                continue
            assert available <= event.tick < event.end_tick
            available = event.end_tick
            if event.kind == "break":
                assert not took_break and event.end_tick - event.tick == world["clock"]["break_length"]
                assert event.tick >= world["clock"]["break_at"]
                took_break = True
                continue
            assert event.tick < world["clock"]["break_at"] or took_break
            assert event.stage in zones
            walks = [w for w in events if w.kind == "walk" and w.tick == event.tick]
            if position != event.stage:
                assert [(w.order_id, w.stage, w.end_tick) for w in walks] == [
                    (event.order_id, event.stage, event.tick + world["clock"]["walk_ticks"])
                ]
            else:
                assert not walks
            position = event.stage
            last_work = min(horizon, event.end_tick)
            labor += last_work - event.tick
        overtime.append(max(0, last_work - shift))
    assert (raw.labor_ticks, raw.overtime_ticks) == (labor, tuple(overtime))


@pytest.mark.parametrize("route", ["all", "bypass", "manual"])
def test_replay_a_congested_mixed_day(route):
    world = load_world()
    world["capacity"].update(pick=2, pack=1, qc=1)
    # Cross coverage lets people compete for the last slot in each buffer.
    plan = Plan(1, route != "manual", True, route, ((1, 2), (1, 2), (3, 4), (4, 3), (2, 3)))
    day = generate(world, 29)
    report = simulate(world, plan, day, trace=True)
    check_trace(world, plan, day, report)
    check_worker_intervals(world, plan, report)
    assert 0 < report.good < report.total
    assert replace(report, events=()) == simulate(world, plan, day)


@pytest.mark.parametrize("horizon,good,finished,labor", [(13, 0, 0, 10), (22, 0, 0, 15), (27, 0, 1, 20), (32, 1, 1, 25)])
def test_jam_holds_order_and_slot_through_break_and_assistance(horizon, good, finished, labor):
    world = load_world()
    world["clock"].update(shift_ticks=12, overtime_ticks=horizon - 12, break_at=12, break_length=5)
    world["prob_bps"]["jam"]["tray"]["regular"] = 10_000
    world["prob_bps"]["defect_auto"]["tray"]["regular"] = 0
    plan = Plan(1, True, True, "all", ((1, 2, 3, 4),))
    day = Scenario(1, 42, (Order(0, "regular", 0, 32),))
    raw = simulate(world, plan, day, trace=True)
    # Human: [0,10) prep + pick, [12,17) break, [17,27) walk + help, [27,32) walk + QC.
    # The robot owns the single order from tick 10 through its release at 27.
    assert (raw.good, raw.on_time, raw.unfinished, raw.auto_finished, raw.labor_ticks) == (good, good, 1 - good, finished, labor)
    assert [e.tick for e in raw.events if e.kind == "jam"] == [13]
    assert [(e.tick, e.end_tick) for e in raw.events if e.kind == "assist"] == ([(17, 27)] if horizon > 17 else [])
    check_trace(world, plan, day, raw)
    check_worker_intervals(world, plan, raw)


@pytest.mark.parametrize("detect,expected", [(10_000, "scrap"), (0, "escaped")])
def test_flawed_packaging_has_one_outcome_and_at_most_one_manual_retry(detect, expected):
    world = load_world()
    probabilities = world["prob_bps"]
    probabilities["defect_auto"]["tray"]["oversize"] = 10_000
    probabilities["defect_manual"]["oversize"] = 10_000
    probabilities["jam"]["tray"]["oversize"] = 0
    probabilities["detect"] = detect
    plan = Plan(1, True, True, "all", ((1,), (2,), (3,), (4,)))
    day = Scenario(1, 47, (Order(13, "oversize", 0, 100),))
    raw = simulate(world, plan, day, trace=True)
    check_trace(world, plan, day, raw)
    starts = [(e.resource, e.attempt) for e in raw.events if e.kind == "start" and e.stage == 3]
    assert starts == ([("robot", 0), ("w2", 1)] if expected == "scrap" else [("robot", 0)])
    assert raw.pack_started == raw.pack_finished == len(starts)
    assert raw.trays_used == raw.auto_finished == 1
    assert raw.rework_started == len(starts) - 1
    assert getattr(raw, expected) == 1 and raw.good == raw.unfinished == 0


def test_unstaffed_jam_keeps_pending_orders_until_horizon():
    world = load_world()
    world["clock"].update(shift_ticks=60, overtime_ticks=10)
    world["capacity"]["qc"] = 1
    world["prob_bps"]["jam"]["tray"]["regular"] = 10_000
    plan = Plan(1, True, True, "all", ((1,), (2,), (4,)))
    day = Scenario(1, 11, (Order(0, "regular", 0, 40), Order(1, "regular", 0, 45)))
    raw = simulate(world, plan, day, trace=True)
    check_trace(world, plan, day, raw)
    assert (raw.total, raw.unfinished, raw.pack_started, raw.pack_finished) == (2, 2, 1, 0)
    assert [e.order_id for e in raw.events if e.kind == "jam"] == [0]
    assert not any(e.kind == "assist" for e in raw.events)


def test_quarterly_active_automation_commissioning_and_shift_trace_invariants():
    from robotization_bench.quarterly import manual_quarterly_value, simulate_quarter
    from robotization_bench.validation import parse_quarterly_plan

    world = load_world()
    raw_plan = manual_quarterly_value(world)
    # Weeks 0..1 buy robot but route manually; commissioning must start only at Week 2 when route != "manual".
    raw_plan["weeks"][0]["robot"] = True
    raw_plan["weeks"][1]["robot"] = True
    for w in range(2, 12):
        raw_plan["weeks"][w] = {
            "robot": True,
            "trays": True,
            "route": "bypass",
            "maintenance": w in (4, 6, 10),
            "workers": [[1], [2], [3], [4], [2, 3]],
        }
    qplan = parse_quarterly_plan(raw_plan, world)
    qrep = simulate_quarter(world, qplan, 11, trace=True)
    assert [wr.week for wr in qrep.weeks if wr.commissioning_active] == [2, 3]
    for wr in qrep.weeks:
        check_trace(world, wr.shift_plan, wr.scenario, wr.raw)
        check_worker_intervals(world, wr.shift_plan, wr.raw)
