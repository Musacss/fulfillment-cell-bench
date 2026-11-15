#!/usr/bin/env python3
"""Generate labelled player regression fixtures from the unchanged simulation core.

These worlds deliberately force rare visual states. They are test data, not public
seed results and are never placed in the production 3d-pack index.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from robotization_bench.contracts import Order, Plan, Scenario, load_world
from robotization_bench.economics import calculate
from robotization_bench.engine import simulate
from robotization_bench.reporting import export_shift_bundle, validate_shift_bundle


def generate_fixtures(out: Path) -> list[str]:
    names = []

    def save(name, world, plan, scenario):
        raw = simulate(world, plan, scenario, trace=True)
        target = out / name
        export_shift_bundle(world, plan, scenario, raw, calculate(world, plan, raw), target)
        validate_shift_bundle(target)
        names.append(name)

    for horizon in (27, 28):
        world = load_world()
        world["clock"].update(shift_ticks=20, overtime_ticks=horizon - 20)
        world["prob_bps"]["defect_manual"]["regular"] = 0
        save(f"test-one-order-h{horizon}", world,
             Plan(1, False, False, "manual", ((1, 2, 3, 4),)),
             Scenario(1, 11, (Order(7, "regular", 0, 28),)))

    for horizon in (22, 27, 32):
        world = load_world()
        world["clock"].update(shift_ticks=12, overtime_ticks=horizon - 12,
                              break_at=12, break_length=5)
        world["prob_bps"]["jam"]["tray"]["regular"] = 10_000
        world["prob_bps"]["defect_auto"]["tray"]["regular"] = 0
        save(f"test-jam-h{horizon}", world,
             Plan(1, True, True, "all", ((1, 2, 3, 4),)),
             Scenario(1, 42, (Order(0, "regular", 0, 32),)))

    for detection, name in ((10_000, "test-rework-scrap"), (0, "test-defect-escaped")):
        world = load_world()
        world["prob_bps"]["defect_auto"]["tray"]["oversize"] = 10_000
        world["prob_bps"]["defect_manual"]["oversize"] = 10_000
        world["prob_bps"]["jam"]["tray"]["oversize"] = 0
        world["prob_bps"]["detect"] = detection
        save(name, world,
             Plan(1, True, True, "all", ((1,), (2,), (3,), (4,))),
             Scenario(1, 47, (Order(13, "oversize", 0, 100),)))

    # A bought robot in manual routing must stay disabled. Trays still apply to
    # the first manual packaging attempt, with no extra tray on a later attempt.
    world = load_world()
    world["prob_bps"]["defect_manual"]["regular"] = 0
    save("test-purchased-disabled", world,
         Plan(1, True, True, "manual", ((1, 2, 3, 4),)),
         Scenario(1, 11, (Order(0, "regular", 0, 40),)))
    return names


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/replay-player-fixtures")
    args = parser.parse_args()
    print("Generated labelled test fixtures: " + ", ".join(generate_fixtures(args.out)))
