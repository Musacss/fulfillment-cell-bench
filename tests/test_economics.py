import pytest

from robotization_bench.contracts import Plan, RawReport, load_world
from robotization_bench.economics import calculate


@pytest.fixture
def idle_robot():
    # Purchased robot on the manual route. All three workers earn a full shift.
    plan = Plan(1, True, True, "manual", ((1, 2), (3,), (4,)))
    raw = RawReport(
        schema_version=1, seed=7, total=11, good=6, on_time=4, escaped=1,
        scrap=1, unfinished=3, pack_started=11, pack_finished=10,
        auto_finished=0, trays_used=9, rework_started=2, labor_ticks=440,
        overtime_ticks=(4, 9, 0), events=(),
    )
    return plan, raw


def test_mixed_shift_bill(idle_robot):
    bill = calculate(load_world(), *idle_robot)
    assert bill.purchase == 1_530_000
    assert bill.costs == {
        "depreciation": 3060, "service": 700, "shifts": 45_600, "overtime": 325,
        "trays": 54, "materials": 132, "rework": 140, "late": 640,
        "unfulfilled": 14_000, "escaped": 6500,
    }
    assert bill.total == 71_151


@pytest.mark.parametrize(("robot_price", "tray_price", "days", "expected"), [
    (1, 1, 2, 1),  # Round once on the combined purchase.
    (2, 1, 2, 2),  # Half a cent rounds up.
    (2, 2, 3, 1),  # Less than half a cent rounds down.
])
def test_depreciation_rounding(idle_robot, robot_price, tray_price, days, expected):
    world = load_world()
    world["money"].update(robot_purchase=robot_price, tray_purchase=tray_price,
                          depreciation_days=days)
    assert calculate(world, *idle_robot).costs["depreciation"] == expected


@pytest.mark.parametrize("days", [0, -1])
def test_invalid_depreciation_horizon(idle_robot, days):
    world = load_world()
    world["money"]["depreciation_days"] = days
    with pytest.raises(ValueError, match="depreciation_days"):
        calculate(world, *idle_robot)


def test_worker_with_no_work_is_paid_and_backlog_costs_money():
    plan = Plan(1, False, False, "manual", ((4,),))
    raw = RawReport(schema_version=1, seed=7, total=3, good=0, on_time=0,
                    escaped=0, scrap=0, unfinished=3, pack_started=0,
                    pack_finished=0, auto_finished=0, trays_used=0,
                    rework_started=0, labor_ticks=0, overtime_ticks=(0,), events=())
    bill = calculate(load_world(), plan, raw)
    assert bill.purchase == 0
    assert bill.total == 25_700  # One shift (€152) and three missing orders (€105).
