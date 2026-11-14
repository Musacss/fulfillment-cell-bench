from dataclasses import replace
from robotization_bench.contracts import Order, Plan, Scenario, load_world
from robotization_bench.engine import simulate


def test_one_order_by_hand_and_inclusive_horizon():
    w = load_world()
    w["prob_bps"]["defect_manual"]["regular"] = 0
    p = Plan(1, False, False, "manual", ((1, 2, 3, 4),))
    scenario = Scenario(1, 11, (Order(7, "regular", 0, 28),))
    w["clock"].update(shift_ticks=20, overtime_ticks=8)
    r = simulate(w, p, scenario, trace=True)
    assert [(e.tick, e.end_tick) for e in r.events if e.kind == "start"] == [(0,3),(3,10),(10,23),(23,28)]
    assert (r.good, r.on_time, r.unfinished, r.labor_ticks, r.overtime_ticks) == (1,1,0,28,(8,))
    w["clock"]["overtime_ticks"] -= 1
    cut = simulate(w, p, scenario)
    assert (cut.good, cut.unfinished, cut.labor_ticks, cut.overtime_ticks) == (0,1,27,(7,))


def test_two_order_single_worker_downstream_first():
    w = load_world()
    w["prob_bps"]["defect_manual"]["regular"] = 0
    p = Plan(1, False, False, "manual", ((1, 2, 3, 4),))
    first = Order(0, "regular", 0, 28)
    r = simulate(w, p, Scenario(1, 11, (first,replace(first,id=1,due=58))), trace=True)
    assert [(e.order_id, e.tick) for e in r.events if e.kind == "good"] == [(0,28),(1,58)]
    assert r.labor_ticks == 58
