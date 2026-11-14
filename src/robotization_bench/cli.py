"""Validate a plan, replay a public shift, or run the benchmark comparison."""

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

from .contracts import ROOT, InvalidPlan, load_world
from .economics import calculate
from .engine import simulate
from .reporting import export_events
from .scenarios import generate
from .validation import decode_plan


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["compare"]:
        # Let the benchmark runner own its flags, defaults, help, and exit code.
        return subprocess.call([sys.executable, str(ROOT / "scripts/run_bench.py"), *args[1:]])

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Validate a JSON plan and print it")
    pilot = commands.add_parser("pilot", help="Run one public development shift")
    commands.add_parser("compare", help="Compare plans using scripts/run_bench.py")
    for command in (pilot, validate):
        command.add_argument("--plan", type=Path, required=True)
    pilot.add_argument("--seed", type=int, required=True, help="Public development day")
    pilot.add_argument("--events", type=Path, help="Export the timeline to a JSONL file")
    options = parser.parse_args(args)
    world = load_world()
    try:
        plan = decode_plan(options.plan.read_text(encoding="utf-8"), world)
    except (OSError, UnicodeError, InvalidPlan) as exc:
        parser.error(f"{options.plan}: {exc}")
    if options.command == "validate":
        print(json.dumps(asdict(plan)))
        return 0

    if options.seed not in world["development_seeds"]:
        parser.error(f"--seed must be a public development day from {world['development_seeds']}")
    if options.events and options.events.resolve() == options.plan.resolve():
        parser.error("--events must differ from the input plan")
    raw = simulate(world, plan, generate(world, options.seed), trace=options.events is not None)
    if options.events:
        try:
            export_events(raw, options.events)
        except OSError as exc:
            parser.error(f"{options.events}: {exc}")
    print(json.dumps({"raw": asdict(replace(raw, events=())), "economy": asdict(calculate(world, plan, raw))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
