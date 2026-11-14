import json
from dataclasses import asdict

import pytest

from robotization_bench.contracts import ROOT, load_world
from robotization_bench.scenarios import generate


def test_first_wave_v1_known_values():
    scenario = generate(load_world(), 11)
    wave = [(o.arrival, o.id, o.kind, o.due) for o in scenario.orders if o.arrival < 65]
    assert wave == [
        (0, 1, "regular", 162), (0, 3, "fragile", 173), (0, 5, "regular", 171),
        (0, 6, "oversize", 178), (0, 9, "regular", 153), (1, 2, "regular", 186),
        (1, 7, "oversize", 163), (2, 0, "regular", 174), (2, 8, "regular", 178),
        (5, 4, "regular", 176), (5, 11, "fragile", 167), (5, 12, "regular", 177),
        (8, 10, "oversize", 168),
    ]


@pytest.mark.parametrize("seed", load_world()["development_seeds"])
def test_development_artifact_matches_generated_stream(seed):
    world = load_world()
    result = generate(world, seed)
    saved = json.loads((ROOT / "data" / "development" / f"{seed}.json").read_text())
    assert saved == json.loads(json.dumps(asdict(result)))
    assert sorted(o.id for o in result.orders) == list(range(len(result.orders)))
    assert list(result.orders) == sorted(result.orders, key=lambda o: (o.arrival, o.id))
    assert all(0 <= o.arrival < world["clock"]["shift_ticks"] and o.due >= o.arrival for o in result.orders)


def test_kind_distribution_does_not_shift_arrivals_or_deadlines():
    world = load_world()
    before = generate(world, 29)
    world["generator"].update(regular_bps=0, fragile_bps=10_000)
    after = generate(world, 29)
    assert all(o.kind == "fragile" for o in after.orders)
    assert [(o.id, o.arrival, o.due) for o in before.orders] == [(o.id, o.arrival, o.due) for o in after.orders]
