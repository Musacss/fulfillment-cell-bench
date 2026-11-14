import asyncio
from contextlib import asynccontextmanager
import json
import sys

import pytest

pytest.importorskip("mcp", reason="Install the locked mcp dependency group for protocol tests")
from mcp import ClientSession, StdioServerParameters, stdio_client

from robotization_bench.contracts import ROOT, load_world
from robotization_bench.engine import simulate
from robotization_bench.scenarios import generate
from robotization_bench.validation import parse_plan


@asynccontextmanager
async def connected(directory):
    command = StdioServerParameters(
        command=sys.executable, args=["-m", "robotization_bench.mcp_server",
                                     "--submission", str(directory / "plan.json"),
                                     "--log", str(directory / "log.json")],
        env={"PYTHONPATH": str(ROOT / "src")}, cwd=str(directory),
    )
    async with asyncio.timeout(18):
        async with stdio_client(command) as (reader, writer), ClientSession(reader, writer) as session:
            await session.initialize()
            yield session


def test_stdio_public_trial_and_submission(tmp_path):
    async def interact():
        async with connected(tmp_path) as session:
            assert {tool.name for tool in (await session.list_tools()).tools} == {"observe", "pilot", "submit", "stop"}
            observed = (await session.call_tool("observe")).structuredContent
            world = load_world()
            assert [day["seed"] for day in observed["history"]] == world["development_seeds"]
            plan, seed = observed["manual"], observed["history"][0]["seed"]
            bad = await session.call_tool("pilot", {"plan": dict(plan, raw={}), "seed": seed})
            assert bad.isError
            unknown_day = await session.call_tool("pilot", {"plan": plan, "seed": -999})
            assert unknown_day.isError
            assert "unknown public day" in unknown_day.content[0].text
            pilot = await session.call_tool("pilot", {"plan": plan, "seed": seed})
            assert not pilot.isError
            raw = simulate(world, parse_plan(plan, world), generate(world, seed))
            assert pilot.structuredContent["raw"]["good"] == raw.good
            assert pilot.structuredContent["economy"]["total"] > 0
            receipt = await session.call_tool("submit", {"plan": plan})
            assert receipt.structuredContent == {"terminal": True, "plan": plan}
            assert (await session.call_tool("stop")).isError
            assert json.loads((tmp_path / "plan.json").read_text()) == plan
            entries = json.loads((tmp_path / "log.json").read_text())
            assert [entry["action"] for entry in entries] == ["observe", "pilot", "pilot", "pilot", "submit"]
            assert all("error" in entry for entry in entries[1:3])
    asyncio.run(interact())


@pytest.mark.parametrize(("action", "args"), [("submit", {}), ("submit", {"plan": {"raw": {}}}), ("stop", {})])
def test_stdio_terminal_zero_clears_stale_submission(tmp_path, action, args):
    async def interact():
        target = tmp_path / "plan.json"
        target.write_text('{"stale":true}')
        async with connected(tmp_path) as session:
            assert json.loads(target.read_text()) is None
            receipt = await session.call_tool(action, args)
            assert receipt.structuredContent == {"terminal": True, "plan": None}
            assert (await session.call_tool("observe")).isError
            assert json.loads(target.read_text()) is None
    asyncio.run(interact())
