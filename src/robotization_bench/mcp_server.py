"""Public pilot service over MCP stdio, with one episode per server process."""

import argparse
import asyncio
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool

from .contracts import load_world
from .episode import Episode
from .scenarios import generate


def _tool(name, description, properties, required=()):
    return Tool(name=name, description=description, inputSchema={
        "type": "object", "properties": properties, "required": list(required),
        "additionalProperties": False,
    })


_PLAN = {"description": "The full v1 plan object. See the manual plan in observe for its shape."}
_TOOLS = [
    _tool("observe", "Read the catalog, rules, manual plan, and public development days.", {}),
    _tool("pilot", "Run one development shift. A failed pilot leaves the episode open.", {
        "plan": _PLAN, "seed": {"type": "integer", "description": "A public day from observe."},
        "trace": {"type": "boolean", "default": False, "description": "Include detailed shift events."},
    }, ("plan", "seed")),
    _tool("submit", "Close the episode by submitting one plan. A missing or invalid plan scores zero.",
          {"plan": _PLAN}),
    _tool("stop", "Close the episode without submitting a plan.", {}),
]


def _save(path: Path | None, value) -> None:
    if path is None:
        return
    payload = json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(payload)
            stream.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


async def serve(submission: Path | None, log: Path | None) -> None:
    world = load_world()
    episode = Episode(world, tuple(generate(world, seed) for seed in world["development_seeds"]))
    _save(submission, None)
    _save(log, episode.log)
    server = Server("robotization-bench", version="0.1.0")

    @server.list_tools()
    async def list_tools():
        return _TOOLS

    @server.call_tool()
    async def call_tool(name, arguments):
        try:
            if name == "observe":
                return episode.observe()
            if name == "pilot":
                return episode.pilot(arguments["plan"], arguments["seed"], trace=arguments.get("trace", False))
            if name == "submit":
                receipt = episode.submit(arguments.get("plan"))
            elif name == "stop":
                receipt = episode.stop()
            else:
                raise ValueError(f"Unknown tool: {name}")
            _save(submission, receipt["plan"])
            return receipt
        finally:
            _save(log, episode.log)

    async with stdio_server() as (reader, writer):
        await server.run(reader, writer, server.create_initialization_options())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submission", type=Path, help="Write the final JSON plan (or null) to this path")
    parser.add_argument("--log", type=Path, help="Write the episode log as a JSON array to this path")
    options = parser.parse_args()
    if options.submission and options.log and options.submission.resolve() == options.log.resolve():
        parser.error("--submission and --log need separate paths")
    asyncio.run(serve(options.submission, options.log))


if __name__ == "__main__":
    main()
