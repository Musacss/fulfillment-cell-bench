"""Parse the public JSON plan into an immutable, ordered production plan."""

import json
from typing import Any

from .contracts import SCHEMA_VERSION, InvalidPlan, Plan, World


_FIELDS = {"schema_version", "robot", "trays", "route", "workers"}


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
