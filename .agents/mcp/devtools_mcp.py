"""Developer & Red-Team MCP server for Antigravity Swarm agents working on fulfillment-cell-bench."""

import asyncio
from collections import Counter, defaultdict
from dataclasses import asdict
from fractions import Fraction
import json
from pathlib import Path
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from robotization_bench.contracts import load_world
from robotization_bench.economics import calculate
from robotization_bench.engine import simulate
from robotization_bench.episode import Episode
from robotization_bench.grading import evaluate, manual_value
from robotization_bench.reference import solve
from robotization_bench.scenarios import generate
from robotization_bench.validation import parse_plan


def _resolve_seeds(world: dict, seeds_mode: str, custom_seeds: list[int] | None) -> list[int]:
    if seeds_mode == "dev":
        return list(world["development_seeds"])
    if seeds_mode == "replay":
        return json.loads((ROOT / "evidence" / "replay_seeds.json").read_text())
    if seeds_mode == "custom" and custom_seeds:
        return list(custom_seeds)
    raise ValueError("seeds_mode must be 'dev', 'replay', or 'custom' with non-empty custom_seeds")


def _audit_trace(world: dict, plan_obj: dict, seed: int) -> dict:
    plan = parse_plan(plan_obj, world)
    day = generate(world, seed)
    raw = simulate(world, plan, day, trace=True)
    econ = calculate(world, plan, raw)

    by_id = {o.id: o for o in day.orders}
    state = {}
    limited = {2: "pick", 3: "pack", 4: "qc"}
    occupied = defaultdict(set)
    active = {}
    done = Counter()
    last_tick = -1
    horizon = world["clock"]["shift_ticks"] + world["clock"]["overtime_ticks"]

    for idx, event in enumerate(raw.events):
        tick, kind, i, stage, attempt = event.tick, event.kind, event.order_id, event.stage, event.attempt
        if not (last_tick <= tick <= horizon):
            raise AssertionError(f"Event #{idx}: tick monotonicity/horizon violated ({tick})")
        last_tick = tick
        if kind == "break":
            continue
        if i not in by_id or attempt not in (0, 1):
            raise AssertionError(f"Event #{idx}: invalid order_id/attempt ({event})")
        previous = state.get(i)
        if kind == "arrival":
            assert previous is None and tick == by_id[i].arrival
        elif kind == "enqueue":
            if stage == 1:
                assert previous == ("arrival", 1, 0) and attempt == 0
            elif stage == 3 and attempt == 1:
                assert previous == ("finish", 4, 0)
            else:
                assert previous == ("finish", stage - 1, attempt) and i in occupied[stage]
        elif kind == "start":
            assert tick < horizon and previous == ("enqueue", stage, attempt)
            if stage in limited and (stage, attempt) != (3, 1):
                occupied[stage].remove(i)
            if stage < 4:
                occupied[stage + 1].add(i)
                assert len(occupied[stage + 1]) <= world["capacity"][limited[stage + 1]]
            assert event.resource not in active
            active[event.resource] = (i, stage, attempt)
        elif kind == "finish":
            assert previous == ("start", stage, attempt)
            assert active.pop(event.resource) == (i, stage, attempt)
        elif kind in ("jam", "assist", "walk"):
            assert previous == ("start", stage, attempt)
            continue
        elif kind in ("good", "escaped", "scrap"):
            assert previous == ("finish", 4, attempt)
            done[kind] += 1
            if kind == "good" and tick <= by_id[i].due:
                done["on_time"] += 1
        else:
            raise AssertionError(f"Unknown 3D event kind: {kind}")
        state[i] = (kind, stage, attempt)

    assert raw.total == len(by_id) == raw.good + raw.escaped + raw.scrap + raw.unfinished
    event_counts = Counter(e.kind for e in raw.events)
    return {
        "ok": True,
        "seed": seed,
        "event_count": len(raw.events),
        "event_kinds": dict(event_counts),
        "summary": {
            "total": raw.total,
            "good": raw.good,
            "on_time": raw.on_time,
            "unfinished": raw.unfinished,
            "labor_ticks": raw.labor_ticks,
            "auto_finished": raw.auto_finished,
            "pack_finished": raw.pack_finished,
            "total_cost_cents": econ.total,
            "purchase_cents": econ.purchase,
        },
    }


def _redteam_suite(world: dict, seeds: list[int]) -> dict:
    days = tuple(generate(world, s) for s in seeds)
    ep = Episode(world, tuple(generate(world, s) for s in world["development_seeds"]))
    ref_plan = solve(ep)

    probes = {
        "null_submit": None,
        "invalid_route": {"schema_version": 1, "robot": False, "trays": False, "route": "all", "workers": [[1, 2, 3, 4]]},
        "over_budget_8_workers": {
            "schema_version": 1,
            "robot": True,
            "trays": True,
            "route": "all",
            "workers": [[1], [2], [3], [4], [1, 2], [2, 3], [3, 4], [1, 2, 3, 4]],
        },
        "single_worker_understaffed": {
            "schema_version": 1,
            "robot": False,
            "trays": False,
            "route": "manual",
            "workers": [[1, 2, 3, 4]],
        },
        "unstaffed_jam_deadlock": {
            "schema_version": 1,
            "robot": True,
            "trays": False,
            "route": "all",
            "workers": [[1], [2], [4]],
        },
        "buy_robot_use_manual_route": {
            "schema_version": 1,
            "robot": True,
            "trays": True,
            "route": "manual",
            "workers": manual_value()["workers"],
        },
        "manual_baseline": manual_value(),
        "reference_solver": ref_plan,
    }
    scored = {}
    for name, candidate in probes.items():
        ev = evaluate(world, candidate, days)
        frac = Fraction(ev.reward_num, ev.reward_den)
        scored[name] = {
            "valid": ev.valid,
            "feasible": ev.feasible,
            "win": ev.win,
            "reward_fraction": f"{ev.reward_num}/{ev.reward_den}",
            "reward_float": round(float(frac), 6),
            "reasons": list(ev.reasons),
        }

    ref_score = Fraction(*map(int, scored["reference_solver"]["reward_fraction"].split("/")))
    manual_score = Fraction(*map(int, scored["manual_baseline"]["reward_fraction"].split("/")))
    exploits_beating_ref = [
        k for k, v in scored.items()
        if k != "reference_solver"
        and Fraction(*map(int, v["reward_fraction"].split("/"))) >= ref_score
    ]
    return {
        "hierarchy_intact": (
            scored["null_submit"]["reward_float"] == 0.0
            and manual_score < ref_score
            and not exploits_beating_ref
        ),
        "exploits_beating_reference": exploits_beating_ref,
        "probes": scored,
    }


TOOLS = [
    Tool(
        name="verify_plan_matrix",
        description="Authoritatively grade a candidate warehouse plan on dev, replay, or custom seeds with exact rational rewards.",
        inputSchema={
            "type": "object",
            "properties": {
                "plan": {"type": "object", "description": "Candidate Plan JSON object."},
                "seeds_mode": {"type": "string", "enum": ["dev", "replay", "custom"], "default": "dev"},
                "custom_seeds": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["plan"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="audit_3d_replay_trace",
        description="Simulate one shift with trace=True and verify all 3D event stream, queue capacity, and worker walk/break/assist invariants.",
        inputSchema={
            "type": "object",
            "properties": {
                "plan": {"type": "object", "description": "Plan JSON object to simulate."},
                "seed": {"type": "integer", "default": 11},
            },
            "required": ["plan"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="redteam_reward_exploits",
        description="Run automated reward-hacking probes (null, stop-early, deadlock, fake-automation, understaffing) against manual and reference baselines.",
        inputSchema={
            "type": "object",
            "properties": {
                "seeds_mode": {"type": "string", "enum": ["dev", "replay"], "default": "dev"},
            },
            "additionalProperties": False,
        },
    ),
]


async def serve() -> None:
    server = Server("fulfillment-bench-devtools", version="0.1.0")

    @server.list_tools()
    async def list_tools():
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        world = load_world()
        if name == "verify_plan_matrix":
            seeds = _resolve_seeds(world, arguments.get("seeds_mode", "dev"), arguments.get("custom_seeds"))
            days = tuple(generate(world, s) for s in seeds)
            ev = evaluate(world, arguments["plan"], days)
            payload = asdict(ev)
            payload["reward_float"] = round(ev.reward_num / ev.reward_den, 6)
            payload["seeds"] = seeds
        elif name == "audit_3d_replay_trace":
            payload = _audit_trace(world, arguments["plan"], arguments.get("seed", 11))
        elif name == "redteam_reward_exploits":
            seeds = _resolve_seeds(world, arguments.get("seeds_mode", "dev"), None)
            payload = _redteam_suite(world, seeds)
        else:
            raise ValueError(f"Unknown tool: {name}")
        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]

    async with stdio_server() as (reader, writer):
        await server.run(reader, writer, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(serve())
