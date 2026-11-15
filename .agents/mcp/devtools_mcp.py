"""Developer & Red-Team MCP server for Antigravity agents working on fulfillment-cell-bench."""

import asyncio
from collections import Counter, defaultdict
import copy
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

from robotization_bench.contracts import Plan, QuarterlyPlan, RawReport, Scenario, load_world
from robotization_bench.economics import calculate
from robotization_bench.engine import simulate
from robotization_bench.episode import Episode, QuarterlyEpisode
from robotization_bench.grading import evaluate, evaluate_any, evaluate_quarterly, manual_value
from robotization_bench.quarterly import manual_quarterly_value, simulate_quarter
from robotization_bench.reference import solve
from robotization_bench.scenarios import generate
from robotization_bench.validation import parse_any_plan


def _resolve_seeds(world: dict, seeds_mode: str, custom_seeds: list[int] | None) -> list[int]:
    if seeds_mode == "dev":
        return list(world["development_seeds"])
    if seeds_mode == "replay":
        return json.loads((ROOT / "evidence" / "replay_seeds.json").read_text(encoding="utf-8"))
    if seeds_mode == "custom":
        if (
            not isinstance(custom_seeds, (list, tuple))
            or not custom_seeds
            or any(type(s) is not int or s < 0 for s in custom_seeds)
            or len(set(custom_seeds)) != len(custom_seeds)
        ):
            raise ValueError("custom_seeds must be a non-empty list of distinct non-negative integers")
        return list(custom_seeds)
    raise ValueError("seeds_mode must be 'dev', 'replay', or 'custom' with non-empty custom_seeds")


def _verify_shift_raw_events(world: dict, plan: Plan, day: Scenario, raw: RawReport) -> Counter:
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
            if stage == 3:
                automatic = attempt == 0 and (
                    plan.route == "all" or (plan.route == "bypass" and by_id[i].kind == "regular")
                )
                assert (event.resource == "robot") == automatic
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
    return Counter(e.kind for e in raw.events)


def _audit_trace(world: dict, plan_obj: dict, seed: int) -> dict:
    parsed = parse_any_plan(plan_obj, world)
    if isinstance(parsed, QuarterlyPlan):
        qrep = simulate_quarter(world, parsed, seed, trace=True)
        agg_kinds: Counter = Counter()
        total_events = 0
        for wr in qrep.weeks:
            counts = _verify_shift_raw_events(world, wr.shift_plan, wr.scenario, wr.raw)
            agg_kinds.update(counts)
            total_events += len(wr.raw.events)
        return {
            "ok": True,
            "mode": "quarterly",
            "seed": seed,
            "weeks_audited": len(qrep.weeks),
            "event_count": total_events,
            "event_kinds": dict(agg_kinds),
            "summary": {
                "total": sum(wr.raw.total - wr.carryover_in for wr in qrep.weeks),
                "good": sum(wr.raw.good for wr in qrep.weeks),
                "on_time": sum(wr.raw.on_time for wr in qrep.weeks),
                "unfinished": sum(wr.raw.unfinished - wr.carryover_out for wr in qrep.weeks),
                "labor_ticks": qrep.labor_ticks,
                "auto_finished": sum(wr.raw.auto_finished for wr in qrep.weeks),
                "pack_finished": sum(wr.raw.pack_finished for wr in qrep.weeks),
                "total_cost_cents": qrep.total_cost,
                "purchase_cents": qrep.purchase,
            },
        }

    day = generate(world, seed)
    raw = simulate(world, parsed, day, trace=True)
    econ = calculate(world, parsed, raw)
    event_counts = _verify_shift_raw_events(world, parsed, day, raw)
    return {
        "ok": True,
        "mode": "v1",
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


def _redteam_suite_v1(world: dict, seeds: list[int]) -> dict:
    days = tuple(generate(world, s) for s in seeds)
    ep = Episode(world, tuple(generate(world, s) for s in world["development_seeds"]))
    ref_plan = solve(ep)

    probes = {
        "null_submit": None,
        "invalid_route": {"schema_version": 1, "robot": False, "trays": False, "route": "all", "workers": [[1, 2, 3, 4]]},
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
        "horizon": "v1",
        "hierarchy_intact": (
            scored["null_submit"]["reward_float"] == 0.0
            and manual_score < ref_score
            and not exploits_beating_ref
        ),
        "exploits_beating_reference": exploits_beating_ref,
        "probes": scored,
    }


def _redteam_suite_quarterly(world: dict, seeds: list[int]) -> dict:
    manual_q = manual_quarterly_value(world)
    ep = QuarterlyEpisode(world)
    ref_plan = solve(ep)

    ep_stop = QuarterlyEpisode(world)
    stop_plan = ep_stop.stop()["plan"]

    partial_11w = {"schema_version": 2, "weeks": copy.deepcopy(manual_q["weeks"][:11])}
    v1_downgrade = {
        "schema_version": 1,
        "robot": True,
        "trays": True,
        "route": "bypass",
        "workers": [[1], [2], [3], [4], [2, 3]],
    }
    unstaffed_jam_deadlock = {
        "schema_version": 2,
        "weeks": [
            {
                "robot": True,
                "trays": True,
                "route": "all",
                "maintenance": False,
                "workers": [[1], [2], [4]],
            }
            for _ in range(12)
        ],
    }
    crate_burnin = copy.deepcopy(manual_q)
    crate_burnin["weeks"][0]["robot"] = True
    crate_burnin["weeks"][1]["robot"] = True
    for w in range(2, 12):
        crate_burnin["weeks"][w] = {
            "robot": True,
            "trays": True,
            "route": "bypass",
            "maintenance": w in (4, 6, 10),
            "workers": [[1], [2], [3], [4], [2, 3]] if w in (7, 8, 9) else [[1], [2], [2, 3], [4]],
        }
    buy_capex_idle = copy.deepcopy(manual_q)
    for w in range(12):
        buy_capex_idle["weeks"][w]["robot"] = True
        buy_capex_idle["weeks"][w]["trays"] = True
        buy_capex_idle["weeks"][w]["route"] = "manual"
    week11_token = copy.deepcopy(manual_q)
    week11_token["weeks"][11] = {
        "robot": True,
        "trays": True,
        "route": "bypass",
        "maintenance": False,
        "workers": [[1], [2], [2, 3], [4]],
    }

    probes = {
        "null_submit": None,
        "stop_early": stop_plan,
        "partial_horizon_11w": partial_11w,
        "v1_schema_downgrade": v1_downgrade,
        "unstaffed_jam_deadlock": unstaffed_jam_deadlock,
        "crate_burnin_evasion": crate_burnin,
        "buy_capex_idle": buy_capex_idle,
        "week11_token_automation": week11_token,
        "manual_baseline": manual_q,
        "reference_solver": ref_plan,
    }
    scored = {}
    fracs: dict[str, Fraction] = {}
    for name, candidate in probes.items():
        ev = evaluate_quarterly(world, candidate, seeds)
        frac = Fraction(ev.reward_num, ev.reward_den)
        fracs[name] = frac
        scored[name] = {
            "valid": ev.valid,
            "feasible": ev.feasible,
            "win": ev.win,
            "reward_fraction": f"{ev.reward_num}/{ev.reward_den}",
            "reward_float": round(float(frac), 6),
            "reasons": list(ev.reasons),
        }

    ref_score = fracs["reference_solver"]
    manual_score = fracs["manual_baseline"]
    exploits_beating_ref = [
        k for k, v in fracs.items()
        if k != "reference_solver" and v >= ref_score
    ]
    hierarchy_ok = (
        fracs["null_submit"] == fracs["stop_early"] == fracs["partial_horizon_11w"] == fracs["v1_schema_downgrade"] == Fraction(0, 1)
        and Fraction(0, 1) < fracs["unstaffed_jam_deadlock"] <= Fraction(9, 100)
        and Fraction(0, 1) < fracs["crate_burnin_evasion"] <= Fraction(9, 100)
        and Fraction(1, 10) < fracs["buy_capex_idle"] < manual_score
        and fracs["week11_token_automation"] < manual_score
        and manual_score == Fraction(1, 5)
        and ref_score >= Fraction(7, 20)
        and not exploits_beating_ref
    )
    return {
        "horizon": "quarterly",
        "hierarchy_intact": hierarchy_ok,
        "exploits_beating_reference": exploits_beating_ref,
        "probes": scored,
    }


TOOLS = [
    Tool(
        name="verify_plan_matrix",
        description="Authoritatively grade a candidate v2 quarterly or v1 shift warehouse plan on dev, replay, or custom seeds with exact rational rewards.",
        inputSchema={
            "type": "object",
            "properties": {
                "plan": {"type": "object", "description": "Candidate QuarterlyPlan (v2) or Plan (v1) JSON object."},
                "seeds_mode": {"type": "string", "enum": ["dev", "replay", "custom"], "default": "dev"},
                "custom_seeds": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["plan"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="audit_3d_replay_trace",
        description="Simulate a v1 shift or v2 12-week quarter with trace=True and verify all 3D event stream, queue capacity, and worker walk/break/assist invariants.",
        inputSchema={
            "type": "object",
            "properties": {
                "plan": {"type": "object", "description": "QuarterlyPlan (v2) or Plan (v1) JSON object to simulate."},
                "seed": {"type": "integer", "default": 11},
            },
            "required": ["plan"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="redteam_reward_exploits",
        description="Run automated quarterly (default) or v1 reward-hacking probes against manual and reference baselines.",
        inputSchema={
            "type": "object",
            "properties": {
                "seeds_mode": {"type": "string", "enum": ["dev", "replay"], "default": "dev"},
                "horizon": {"type": "string", "enum": ["quarterly", "v1"], "default": "quarterly"},
            },
            "additionalProperties": False,
        },
    ),
]


def verify_plan_matrix(
    plan: dict,
    seeds_mode: str = "dev",
    custom_seeds: list[int] | None = None,
) -> dict:
    world = load_world()
    seeds = _resolve_seeds(world, seeds_mode, custom_seeds)
    ev = evaluate_any(world, plan, seeds)
    payload = asdict(ev)
    payload["reward_float"] = round(ev.reward_num / ev.reward_den, 6)
    payload["seeds"] = seeds
    return payload


def audit_3d_replay_trace(plan: dict, seed: int = 11) -> dict:
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    world = load_world()
    return _audit_trace(world, plan, seed)


def redteam_reward_exploits(seeds_mode: str = "dev", horizon: str = "quarterly") -> dict:
    if horizon not in ("quarterly", "v1"):
        raise ValueError("horizon must be 'quarterly' or 'v1'")
    world = load_world()
    seeds = _resolve_seeds(world, seeds_mode, None)
    return _redteam_suite_v1(world, seeds) if horizon == "v1" else _redteam_suite_quarterly(world, seeds)


async def serve() -> None:
    server = Server("fulfillment-bench-devtools", version="0.1.0")

    @server.list_tools()
    async def list_tools():
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict | None):
        arguments = arguments or {}
        if type(arguments) is not dict:
            raise ValueError("arguments must be a JSON object")
        if name == "verify_plan_matrix":
            if "plan" not in arguments:
                raise ValueError("Missing required 'plan' argument")
            payload = verify_plan_matrix(
                arguments["plan"],
                arguments.get("seeds_mode", "dev"),
                arguments.get("custom_seeds"),
            )
        elif name == "audit_3d_replay_trace":
            if "plan" not in arguments:
                raise ValueError("Missing required 'plan' argument")
            payload = audit_3d_replay_trace(arguments["plan"], arguments.get("seed", 11))
        elif name == "redteam_reward_exploits":
            payload = redteam_reward_exploits(
                arguments.get("seeds_mode", "dev"),
                arguments.get("horizon", "quarterly"),
            )
        else:
            raise ValueError(f"Unknown tool: {name}")
        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]

    async with stdio_server() as (reader, writer):
        await server.run(reader, writer, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(serve())
