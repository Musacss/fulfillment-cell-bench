import json
from dataclasses import asdict, replace

from robotization_bench.contracts import load_world
from robotization_bench.engine import simulate
from robotization_bench.grading import evaluate, manual_value
from robotization_bench.reporting import compare, export_events
from robotization_bench.scenarios import generate
from robotization_bench.validation import parse_plan


def test_compare_real_manual_shift_and_missing_plan():
    world = load_world()
    days = tuple(generate(world, seed) for seed in world["development_seeds"])
    manual = evaluate(world, manual_value(), days)
    no_plan = evaluate(world, None, days)
    report = compare({"ручной": manual, "остановка": no_plan})
    assert manual.feasible
    assert "| ручной | да | нет | 1/5 | 0,00 € |" in report
    assert f"| 0,00 € | {manual.metrics['labor_ticks']} / {manual.metrics['labor_ticks']} |" in report
    assert "активный труд не снизился" in report
    assert "| остановка | невалидная сдача | нет | 0/1 | —" in report
    assert f"| ручной | {manual.metrics['orders']} | {manual.metrics['good']} |" in report


def test_compare_preserves_distinct_reward_fractions():
    world = load_world()
    day = generate(world, 11)
    base = evaluate(world, manual_value(), (day,))
    a = replace(base, reward_num=19_999, reward_den=100_000)
    b = replace(base, reward_num=19_998, reward_den=100_001)
    report = compare({"a": a, "b": b})
    assert "19999/100000" in report and "19998/100001" in report


def test_export_round_trips_trace_including_same_tick_events(tmp_path):
    world = load_world()
    day = generate(world, world["development_seeds"][0])
    plan = parse_plan(manual_value(), world)
    shift = simulate(world, plan, day, trace=True)
    destination = tmp_path / "exports" / "shift.jsonl"
    export_events(shift, destination)
    timeline = [json.loads(line) for line in destination.read_text().splitlines()]
    assert timeline == [asdict(event) for event in shift.events]
    assert timeline[0]["kind"] == "arrival"
    assert timeline[1]["tick"] == timeline[0]["tick"]
    assert timeline[-1]["kind"] in {"good", "scrap", "escaped"}

    export_events(replace(shift, events=()), destination)
    assert destination.read_bytes() == b""
