"""Stable wire boundary v1. Dataclasses serialize via asdict; tuples become arrays in JSON."""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = 1
World = dict[str, Any]
Kind = Literal["regular", "fragile", "oversize"]
Route = Literal["manual", "all", "bypass"]


class InvalidPlan(ValueError):
    """Bad public submission; never use for an internal failure."""


class EpisodeClosed(RuntimeError):
    pass


def load_world() -> World:
    return json.loads((ROOT / "data/world_spec.json").read_text())


def draw(seed: int, order_id: int, stage: int, attempt: int, event_type: str, modulus: int) -> int:
    """Stable draw: 8 leading digest bytes, unsigned big endian, modulo modulus."""
    key = json.dumps([seed, order_id, stage, attempt, event_type], separators=(",", ":"), ensure_ascii=True)
    return int.from_bytes(hashlib.sha256(key.encode("ascii")).digest()[:8], "big") % modulus


@dataclass(frozen=True)
class Plan:
    schema_version: int
    robot: bool
    trays: bool
    route: Route
    workers: tuple[tuple[int, ...], ...]


@dataclass(frozen=True)
class Order:
    id: int
    kind: Kind
    arrival: int
    due: int


@dataclass(frozen=True)
class Scenario:
    schema_version: int
    seed: int
    orders: tuple[Order, ...]


@dataclass(frozen=True)
class Event:
    tick: int
    kind: str
    order_id: int | None
    resource: str | None
    stage: int | None
    attempt: int | None
    end_tick: int | None


@dataclass(frozen=True)
class RawReport:
    schema_version: int
    seed: int
    total: int
    good: int
    on_time: int
    escaped: int
    scrap: int
    unfinished: int
    pack_started: int
    pack_finished: int
    auto_finished: int
    trays_used: int
    rework_started: int
    labor_ticks: int
    overtime_ticks: tuple[int, ...]
    events: tuple[Event, ...]


@dataclass(frozen=True)
class Economy:
    purchase: int
    costs: dict[str, int]
    total: int


@dataclass(frozen=True)
class Evaluation:
    valid: bool
    feasible: bool
    win: bool
    reward_num: int
    reward_den: int
    metrics: dict[str, int]
    reasons: tuple[str, ...]
