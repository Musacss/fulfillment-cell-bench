"""Parse the public JSON plan into an immutable, ordered production plan."""

import json
from typing import Any

from .contracts import (
    QUARTERLY_SCHEMA_VERSION,
    SCHEMA_VERSION,
    InvalidPlan,
    Plan,
    QuarterlyPlan,
    WeekPlan,
    World,
)


_FIELDS = {"schema_version", "robot", "trays", "route", "workers"}
_QUARTERLY_FIELDS = {"schema_version", "weeks"}
_WEEK_FIELDS = {"robot", "trays", "route", "maintenance", "workers"}


def parse_plan(value: object, world: World) -> Plan:
    """Validate a decoded JSON value. Feasibility is decided by the evaluator."""
    if type(value) is not dict or value.keys() != _FIELDS:
        raise InvalidPlan("Expected a plan object with schema_version, robot, trays, route and workers")
    version = value["schema_version"]
    if type(version) is not int or version != SCHEMA_VERSION:
        raise InvalidPlan(f"schema_version must be integer {SCHEMA_VERSION}")
    robot, trays = value["robot"], value["trays"]
    if type(robot) is not bool or type(trays) is not bool:
        raise InvalidPlan("robot and trays must be JSON booleans")
    route = value["route"]
    if type(route) is not str or route not in ("manual", "all", "bypass"):
        raise InvalidPlan("route must be manual, all or bypass")
    if not robot and route != "manual":
        raise InvalidPlan("route must be manual when robot is false")

    workers = value["workers"]
    spec = world["workers"]
    if type(workers) is not list or not spec["min"] <= len(workers) <= spec["max"]:
        raise InvalidPlan(f"workers must be an array of {spec['min']} to {spec['max']} workers")

    normalized = []
    allowed_zones = spec["zones"]
    for index, zones in enumerate(workers):
        if type(zones) is not list or not 1 <= len(zones) <= len(allowed_zones):
            raise InvalidPlan(f"workers[{index}] must be a nonempty list of distinct zones")
        if any(type(zone) is not int or zone not in allowed_zones for zone in zones):
            raise InvalidPlan(f"workers[{index}] zones must be integers from {allowed_zones}")
        if len(set(zones)) != len(zones):
            raise InvalidPlan(f"workers[{index}] contains a duplicate zone")
        normalized.append(tuple(zones))

    return Plan(version, robot, trays, route, tuple(normalized))


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise InvalidPlan("Duplicate JSON object key")
        obj[key] = value
    return obj


def _reject_constant(token: str) -> None:
    raise InvalidPlan(f"Invalid JSON number: {token}")


def decode_plan(text: str, world: World) -> Plan:
    """Parse a complete JSON document, rejecting ambiguous keys and non-JSON constants."""
    if type(text) is not str:
        raise InvalidPlan("Expected JSON text")
    try:
        value = json.loads(text, object_pairs_hook=_unique_keys, parse_constant=_reject_constant)
    except InvalidPlan:
        raise
    except (ValueError, RecursionError) as exc:
        raise InvalidPlan("Malformed JSON document") from exc
    return parse_plan(value, world)


def _decode_json(text: str) -> Any:
    if type(text) is not str:
        raise InvalidPlan("Expected JSON text")
    try:
        return json.loads(text, object_pairs_hook=_unique_keys, parse_constant=_reject_constant)
    except InvalidPlan:
        raise
    except (ValueError, RecursionError) as exc:
        raise InvalidPlan("Malformed JSON document") from exc


def _parse_week_workers(workers: object, world: World, prefix: str) -> tuple[tuple[int, ...], ...]:
    spec = world["workers"]
    if type(workers) not in (list, tuple) or not spec["min"] <= len(workers) <= spec["max"]:
        raise InvalidPlan(f"{prefix} must be an array of {spec['min']} to {spec['max']} workers")
    normalized = []
    allowed_zones = spec["zones"]
    for index, zones in enumerate(workers):
        if type(zones) not in (list, tuple) or not 1 <= len(zones) <= len(allowed_zones):
            raise InvalidPlan(f"{prefix}[{index}] must be a nonempty list of distinct zones")
        if any(type(zone) is not int or zone not in allowed_zones for zone in zones):
            raise InvalidPlan(f"{prefix}[{index}] zones must be integers from {allowed_zones}")
        if len(set(zones)) != len(zones):
            raise InvalidPlan(f"{prefix}[{index}] contains a duplicate zone")
        normalized.append(tuple(zones))
    return tuple(normalized)


def parse_quarterly_plan(value: object, world: World) -> QuarterlyPlan:
    """Validate a decoded v2 12-week quarterly plan."""
    if type(value) is not dict or value.keys() != _QUARTERLY_FIELDS:
        raise InvalidPlan("Expected a quarterly plan object with schema_version and weeks")
    version = value["schema_version"]
    if type(version) is not int or version != QUARTERLY_SCHEMA_VERSION:
        raise InvalidPlan(f"schema_version must be integer {QUARTERLY_SCHEMA_VERSION}")

    expected_weeks = world.get("quarterly", {}).get("weeks", 12)
    if type(expected_weeks) is not int or expected_weeks <= 0:
        raise ValueError("quarterly.weeks must be a positive integer")

    raw_weeks = value["weeks"]
    if type(raw_weeks) not in (list, tuple) or len(raw_weeks) != expected_weeks:
        raise InvalidPlan(f"weeks must be an array of {expected_weeks} weekly plans")

    owned_robot = False
    owned_trays = False
    parsed_weeks: list[WeekPlan] = []
    for idx, entry in enumerate(raw_weeks):
        if type(entry) is not dict or entry.keys() != _WEEK_FIELDS:
            raise InvalidPlan(f"weeks[{idx}] must have robot, trays, route, maintenance and workers")
        robot, trays, maintenance = entry["robot"], entry["trays"], entry["maintenance"]
        if type(robot) is not bool or type(trays) is not bool or type(maintenance) is not bool:
            raise InvalidPlan(f"weeks[{idx}] robot, trays and maintenance must be JSON booleans")
        route = entry["route"]
        if type(route) is not str or route not in ("manual", "all", "bypass"):
            raise InvalidPlan(f"weeks[{idx}] route must be manual, all or bypass")
        if not robot and route != "manual":
            raise InvalidPlan(f"weeks[{idx}] route must be manual when robot is false")
        if maintenance and not robot:
            raise InvalidPlan(f"weeks[{idx}] maintenance requires robot to be true")
        if owned_robot and not robot:
            raise InvalidPlan(f"weeks[{idx}] robot cannot be false after purchase")
        if owned_trays and not trays:
            raise InvalidPlan(f"weeks[{idx}] trays cannot be false after purchase")
        owned_robot = owned_robot or robot
        owned_trays = owned_trays or trays
        workers = _parse_week_workers(entry["workers"], world, f"weeks[{idx}].workers")
        parsed_weeks.append(WeekPlan(robot, trays, route, maintenance, workers))

    return QuarterlyPlan(version, tuple(parsed_weeks))


def decode_quarterly_plan(text: str, world: World) -> QuarterlyPlan:
    return parse_quarterly_plan(_decode_json(text), world)


def parse_any_plan(value: object, world: World) -> Plan | QuarterlyPlan:
    if type(value) is not dict or "schema_version" not in value:
        raise InvalidPlan("Expected a plan object with schema_version")
    version = value["schema_version"]
    if type(version) is not int:
        raise InvalidPlan("schema_version must be an integer")
    if version == SCHEMA_VERSION:
        return parse_plan(value, world)
    if version == QUARTERLY_SCHEMA_VERSION:
        return parse_quarterly_plan(value, world)
    raise InvalidPlan(f"Unsupported schema_version: {version}")


def decode_any_plan(text: str, world: World) -> Plan | QuarterlyPlan:
    return parse_any_plan(_decode_json(text), world)
