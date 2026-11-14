import json
from dataclasses import asdict

import pytest

from robotization_bench.contracts import ROOT, InvalidPlan, load_world
from robotization_bench.validation import decode_plan, parse_plan

WORLD = load_world()


def manual():
    return {"schema_version": 1, "robot": False, "trays": False, "route": "manual", "workers": [[1]]}


@pytest.mark.parametrize("name", ["manual", "candidate"])
def test_catalog_plans_keep_worker_and_zone_order(name):
    text = (ROOT / "data/plans" / f"{name}.json").read_text()
    plan = decode_plan(text, WORLD)
    assert json.loads(json.dumps(asdict(plan))) == json.loads(text)


@pytest.mark.parametrize("overrides", [
    {"schema_version": True}, {"schema_version": 1.0}, {"schema_version": 2}, {"robot": 0},
    {"trays": "true"}, {"route": "bypass"}, {"route": "all"}, {"route": ["manual"]},
    {"route": "other"}, {"workers": []}, {"workers": [[1]] * 9}, {"workers": [{}]},
    {"workers": [[]]}, {"workers": [[1, 1]]}, {"workers": [[1, True]]}, {"workers": [[1.0]]},
    {"workers": [[5]]}, {"workers": [[0]]}, {"workers": [[[3]]]}, {"workers": [[None]]},
    {"raw": {}}, {"reward_num": 1},
])
def test_bad_field_rejected_through_both_entry_points(overrides):
    value = manual() | overrides
    with pytest.raises(InvalidPlan):
        parse_plan(value, WORLD)
    with pytest.raises(InvalidPlan):
        decode_plan(json.dumps(value), WORLD)


@pytest.mark.parametrize("value", [None, [], "plan", {}, {(): True}, 1])
def test_root_must_be_complete_object(value):
    with pytest.raises(InvalidPlan):
        parse_plan(value, WORLD)


@pytest.mark.parametrize("bad_text", [
    '{"schema_version": 1, "robot": true, "robot": false, "trays": false, "route": "manual", "workers": [[1]]}',
    'NaN', 'Infinity', '-Infinity', '1e999', '{} {}', '1' * 5000, '[' * 2000 + ']' * 2000,
])
def test_malformed_and_ambiguous_text_raises_domain_error(bad_text):
    with pytest.raises(InvalidPlan):
        decode_plan(bad_text, WORLD)


def test_feasibility_and_worker_identity_stay_out_of_parser():
    world = load_world()
    world["money"]["budget"] = 0
    source = manual() | {"workers": [[3, 1]] * 8, "robot": True, "trays": True}
    idle_robot = parse_plan(source, world)
    source["workers"][0].reverse()
    assert idle_robot.workers == ((3, 1),) * 8
    assert idle_robot.route == "manual"
    assert parse_plan(manual() | {"trays": True}, world).trays
