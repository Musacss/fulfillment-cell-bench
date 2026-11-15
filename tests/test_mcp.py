import ast
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import tempfile
import time

import pytest

pytest.importorskip("mcp", reason="Install the locked mcp dependency group for protocol tests")
from mcp import ClientSession, StdioServerParameters, stdio_client

from robotization_bench.contracts import ROOT, load_world
from robotization_bench.engine import simulate
from robotization_bench.quarterly import manual_quarterly_value, simulate_quarter
from robotization_bench.scenarios import generate
from robotization_bench.validation import parse_plan, parse_quarterly_plan


@pytest.fixture
def short_sock_dir():
    """Short /tmp directory so AF_UNIX socket paths stay well under macOS 104-byte limit."""
    with tempfile.TemporaryDirectory(prefix="/tmp/m2_") as d:
        yield Path(d)


@asynccontextmanager
async def connected_server(directory: Path, extra_args: tuple[str, ...] = ()):
    command = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "robotization_bench.mcp_server",
            "--submission",
            str(directory / "plan.json"),
            "--log",
            str(directory / "log.json"),
            *extra_args,
        ],
        env={"PYTHONPATH": str(ROOT / "src")},
        cwd=str(directory),
    )
    async with asyncio.timeout(25):
        async with stdio_client(command) as (reader, writer), ClientSession(reader, writer) as session:
            await session.initialize()
            yield session


@asynccontextmanager
async def connected_proxy(socket_path: Path, directory: Path, extra_args: tuple[str, ...] = ()):
    command = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "robotization_bench.mcp_proxy",
            "--socket",
            str(socket_path),
            *extra_args,
        ],
        env={"PYTHONPATH": str(ROOT / "src")},
        cwd=str(directory),
    )
    async with asyncio.timeout(25):
        async with stdio_client(command) as (reader, writer), ClientSession(reader, writer) as session:
            await session.initialize()
            yield session


def _wait_for_socket(sock_path: Path, proc: subprocess.Popen, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
            raise RuntimeError(f"daemon exited early ({proc.returncode}): {stderr}")
        if sock_path.exists():
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(0.5)
                    s.connect(str(sock_path))
                return
            except OSError:
                pass
        time.sleep(0.03)
    raise TimeoutError(f"Timed out waiting for Unix socket {sock_path}")


@asynccontextmanager
async def running_daemon(
    sock_path: Path,
    *,
    submission: Path,
    log: Path,
    state: Path | None = None,
    mode: str = "quarterly",
    max_pilots: int | None = None,
):
    args = [
        sys.executable,
        "-m",
        "robotization_bench.mcp_server",
        "--mode",
        mode,
        "--socket",
        str(sock_path),
        "--submission",
        str(submission),
        "--log",
        str(log),
    ]
    if state is not None:
        args.extend(["--state", str(state)])
    if max_pilots is not None:
        args.extend(["--max-pilots", str(max_pilots)])
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    proc = subprocess.Popen(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        await asyncio.to_thread(_wait_for_socket, sock_path, proc)
        yield proc
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                await asyncio.to_thread(proc.wait, 5)
            except subprocess.TimeoutExpired:
                proc.kill()
                await asyncio.to_thread(proc.wait, 5)


def test_stdio_v1_public_trial_and_submission(tmp_path):
    async def interact():
        async with connected_server(tmp_path, ("--mode", "v1")) as session:
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


def test_stdio_quarterly_default_mode_and_large_trace(tmp_path):
    async def interact():
        async with connected_server(tmp_path) as session:
            tools = {t.name: t for t in (await session.list_tools()).tools}
            assert set(tools) == {"observe", "pilot", "submit", "stop"}
            assert "type" not in tools["pilot"].inputSchema["properties"]["plan"]
            assert tools["submit"].inputSchema["required"] == []

            observed = (await session.call_tool("observe")).structuredContent
            world = load_world()
            assert observed["schema_version"] == 2
            assert observed["development_seeds"] == world["development_seeds"]
            assert observed["pilot_budget"] == {"used": 0, "max": 24}

            plan = observed["manual"]
            seed = observed["development_seeds"][0]

            bad = await session.call_tool("pilot", {"plan": {"bad": 1}, "seed": seed})
            assert bad.isError
            unknown = await session.call_tool("pilot", {"plan": plan, "seed": -999})
            assert unknown.isError
            assert "unknown public day" in unknown.content[0].text

            traced = await session.call_tool("pilot", {"plan": plan, "seed": seed, "trace": True})
            assert not traced.isError
            payload = traced.structuredContent
            assert payload["schema_version"] == 2
            assert payload["pilot_budget"] == {"used": 1, "max": 24}
            assert len(json.dumps(payload)) > 65_536
            expected = simulate_quarter(world, parse_quarterly_plan(plan, world), seed, trace=False)
            assert payload["total_cost"] == expected.total_cost

            receipt = await session.call_tool("submit", {"plan": plan})
            assert not receipt.isError
            assert receipt.structuredContent == {"terminal": True, "plan": plan}
            assert (await session.call_tool("observe")).isError
            assert json.loads((tmp_path / "plan.json").read_text()) == plan
            assert (stat.S_IMODE((tmp_path / "plan.json").stat().st_mode) & 0o644) == 0o644

    asyncio.run(interact())


@pytest.mark.parametrize("mode_args", [(), ("--mode", "v1")])
@pytest.mark.parametrize(("action", "args"), [("submit", {}), ("submit", {"plan": {"raw": {}}}), ("stop", {})])
def test_stdio_terminal_zero_clears_stale_submission(tmp_path, mode_args, action, args):
    async def interact():
        target = tmp_path / "plan.json"
        target.write_text('{"stale":true}')
        async with connected_server(tmp_path, mode_args) as session:
            assert json.loads(target.read_text()) is None
            receipt = await session.call_tool(action, args)
            assert receipt.structuredContent == {"terminal": True, "plan": None}
            assert (await session.call_tool("observe")).isError
            assert json.loads(target.read_text()) is None

    asyncio.run(interact())


def test_mcp_proxy_ast_zero_simulator_imports():
    proxy_path = ROOT / "src/robotization_bench/mcp_proxy.py"
    assert proxy_path.is_file(), "mcp_proxy.py must exist"
    tree = ast.parse(proxy_path.read_text(encoding="utf-8"), filename=str(proxy_path))
    forbidden = {
        "robotization_bench",
        "contracts",
        "engine",
        "quarterly",
        "scenarios",
        "economics",
        "grading",
        "validation",
        "verifier",
        "reference",
        "episode",
        "mcp_server",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = set(alias.name.split("."))
                assert not (parts & forbidden), f"Forbidden import in mcp_proxy.py: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"Forbidden relative import in mcp_proxy.py: level={node.level} module={node.module}"
            if node.module:
                parts = set(node.module.split("."))
                assert not (parts & forbidden), f"Forbidden from-import in mcp_proxy.py: {node.module}"
            for alias in node.names:
                assert alias.name not in forbidden, f"Forbidden imported symbol in mcp_proxy.py: {alias.name}"


def test_save_rejects_symlinks_and_socket_escapes_unicode_line_separators(tmp_path, short_sock_dir):
    from robotization_bench.mcp_server import _save

    victim = tmp_path / "victim.json"
    victim.write_text('{"keep": true}\n', encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(victim)
    with pytest.raises(ValueError, match="symlink|regular"):
        _save(link, {"clobbered": True})
    assert json.loads(victim.read_text(encoding="utf-8")) == {"keep": True}

    sock_path = short_sock_dir / "u.sock"
    sub = tmp_path / "sub.json"
    log = tmp_path / "log.json"

    async def interact():
        async with running_daemon(sock_path, submission=sub, log=log):
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(10.0)
                s.connect(str(sock_path))
                # Send two sequential requests on a single connection, including \u2028/\u2029 in payload
                req1 = json.dumps(
                    {"action": "pilot", "args": {"plan": "bad\u2028plan\u2029text", "seed": "bad\u2028seed"}},
                    ensure_ascii=True,
                ) + "\n"
                req2 = json.dumps({"action": "observe", "args": {}}, ensure_ascii=True) + "\n"
                s.sendall((req1 + req2).encode("utf-8"))
                buf = b""
                while buf.count(b"\n") < 2:
                    chunk = s.recv(65536)
                    assert chunk
                    buf += chunk
                lines = buf.splitlines()
                assert len(lines) == 2
                # Ensure ASCII-safe wire encoding without raw U+2028 / U+2029
                assert "\u2028".encode("utf-8") not in buf
                assert "\u2029".encode("utf-8") not in buf
                r1 = json.loads(lines[0].decode("utf-8"))
                r2 = json.loads(lines[1].decode("utf-8"))
                assert r1["ok"] is False and r1["error_type"] == "InvalidPlan"
                assert r2["ok"] is True and r2["result"]["schema_version"] == 2

    asyncio.run(interact())


def test_socket_daemon_client_and_proxy_quarterly_and_v1(tmp_path, short_sock_dir):
    from robotization_bench.mcp_proxy import SocketEpisodeClient

    # 1. Quarterly mode over socket + SocketEpisodeClient + mcp_proxy stdio
    q_sock = short_sock_dir / "q.sock"
    q_sub = tmp_path / "q_sub.json"
    q_log = tmp_path / "q_log.json"
    q_state = tmp_path / "q_state.json"

    async def run_quarterly():
        async with running_daemon(q_sock, submission=q_sub, log=q_log, state=q_state, mode="quarterly"):
            assert stat.S_IMODE(q_sock.stat().st_mode) == 0o666
            client = SocketEpisodeClient(q_sock)
            obs = client.observe()
            assert obs["schema_version"] == 2
            manual = obs["manual"]
            seed = obs["development_seeds"][0]

            # Abrupt disconnect should not crash daemon
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as raw_sock:
                raw_sock.connect(str(q_sock))
                raw_sock.sendall(b'{"action": ')

            traced = client.pilot(manual, seed, trace=True)
            assert len(json.dumps(traced)) > 65_536
            assert traced["pilot_budget"]["used"] == 1

            with pytest.raises(RuntimeError, match="InvalidPlan"):
                client.pilot({"bad": 1}, seed)

            async with connected_proxy(q_sock, tmp_path) as session:
                tools = {t.name for t in (await session.list_tools()).tools}
                assert tools == {"observe", "pilot", "submit", "stop"}
                proxy_obs = await session.call_tool("observe")
                assert not proxy_obs.isError
                assert proxy_obs.structuredContent["pilot_budget"]["used"] == 1

                bad_call = await session.call_tool("pilot", {"plan": {"bad": 1}, "seed": seed})
                assert bad_call.isError

                sub_res = await session.call_tool("submit", {"plan": manual})
                assert not sub_res.isError
                assert sub_res.structuredContent == {"terminal": True, "plan": manual}

                after_close = await session.call_tool("observe")
                assert after_close.isError

            assert json.loads(q_sub.read_text(encoding="utf-8")) == manual

    asyncio.run(run_quarterly())

    # 2. v1 mode over socket + mcp_proxy stdio
    v1_sock = short_sock_dir / "v1.sock"
    v1_sub = tmp_path / "v1_sub.json"
    v1_log = tmp_path / "v1_log.json"

    async def run_v1():
        async with running_daemon(v1_sock, submission=v1_sub, log=v1_log, mode="v1"):
            async with connected_proxy(v1_sock, tmp_path) as session:
                obs = (await session.call_tool("observe")).structuredContent
                assert "schema_version" not in obs
                plan, seed = obs["manual"], obs["history"][0]["seed"]
                pilot = await session.call_tool("pilot", {"plan": plan, "seed": seed})
                assert not pilot.isError
                assert pilot.structuredContent["raw"]["good"] > 0
                sub_res = await session.call_tool("submit", {"plan": plan})
                assert sub_res.structuredContent == {"terminal": True, "plan": plan}
            assert json.loads(v1_sub.read_text(encoding="utf-8")) == plan

    asyncio.run(run_v1())


def test_socket_client_autostart_bin(tmp_path, short_sock_dir):
    from robotization_bench.mcp_proxy import SocketEpisodeClient

    sock_path = short_sock_dir / "auto.sock"
    sub_path = tmp_path / "auto_sub.json"
    log_path = tmp_path / "auto_log.json"
    pid_file = tmp_path / "daemon.pid"
    launcher = tmp_path / "mock-bench-daemon-start"
    launcher.write_text(
        f"""#!/bin/sh
set -eu
PYTHONPATH="{ROOT / 'src'}" "{sys.executable}" -m robotization_bench.mcp_server \\
    --mode quarterly \\
    --socket "{sock_path}" \\
    --submission "{sub_path}" \\
    --log "{log_path}" >/dev/null 2>&1 &
echo $! > "{pid_file}"
""",
        encoding="utf-8",
    )
    launcher.chmod(0o755)

    try:
        assert not sock_path.exists()
        client = SocketEpisodeClient(sock_path, autostart_bin=launcher)
        obs = client.observe()
        assert obs["schema_version"] == 2
        res = client.stop()
        assert res == {"terminal": True, "plan": None}
        assert json.loads(sub_path.read_text(encoding="utf-8")) is None
        with pytest.raises(RuntimeError, match="EpisodeClosed"):
            client.observe()
    finally:
        if pid_file.exists():
            pid = int(pid_file.read_text(encoding="utf-8").strip())
            try:
                os.kill(pid, 15)
            except OSError:
                pass


def test_50x_stdio_restart_flood_and_daemon_restart_persistence(tmp_path, short_sock_dir):
    from robotization_bench.mcp_proxy import SocketEpisodeClient

    sock_path = short_sock_dir / "flood.sock"
    state_path = tmp_path / "state.json"
    sub_path = tmp_path / "submission.json"
    log_path = tmp_path / "episode.json"
    manual_q = manual_quarterly_value()

    async def flood():
        # Phase 1: Start daemon with max_pilots=6, run attempts 1..3 (including stdio mcp_proxy restarts)
        async with running_daemon(
            sock_path, submission=sub_path, log=log_path, state=state_path, mode="quarterly", max_pilots=6
        ):
            assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
            for i in range(1, 4):
                async with connected_proxy(sock_path, tmp_path) as session:
                    res = await session.call_tool("pilot", {"plan": manual_q, "seed": 11})
                    assert not res.isError
                    assert res.structuredContent["pilot_budget"] == {"used": i, "max": 6}

        # Phase 2: Restart daemon against same state.json (attempting higher --max-pilots=99 -> must clamp to 6!)
        async with running_daemon(
            sock_path, submission=sub_path, log=log_path, state=state_path, mode="quarterly", max_pilots=99
        ):
            for i in range(4, 51):
                if i in (4, 7, 25, 50):
                    # Exercise full stdio mcp_proxy spawn on key boundary iterations
                    async with connected_proxy(sock_path, tmp_path) as session:
                        res = await session.call_tool("pilot", {"plan": manual_q, "seed": 29})
                        if i <= 6:
                            assert not res.isError
                            assert res.structuredContent["pilot_budget"] == {"used": i, "max": 6}
                        else:
                            assert res.isError
                            assert "BudgetExceeded" in res.content[0].text
                else:
                    # Fresh SocketEpisodeClient per iteration (stateless client restart flood)
                    client = SocketEpisodeClient(sock_path)
                    if i <= 6:
                        out = client.pilot(manual_q, 11)
                        assert out["pilot_budget"] == {"used": i, "max": 6}
                    else:
                        with pytest.raises(RuntimeError, match="BudgetExceeded"):
                            client.pilot(manual_q, 11)

            # Episode must STILL be open after budget exhaustion so submit(manual_q) succeeds!
            async with connected_proxy(sock_path, tmp_path) as session:
                sub_res = await session.call_tool("submit", {"plan": manual_q})
                assert not sub_res.isError
                assert sub_res.structuredContent == {"terminal": True, "plan": manual_q}
            assert json.loads(sub_path.read_text(encoding="utf-8")) == manual_q

        # Phase 3: Restart daemon AFTER submit — must NOT wipe submission.json to null and must stay closed!
        async with running_daemon(
            sock_path, submission=sub_path, log=log_path, state=state_path, mode="quarterly", max_pilots=6
        ):
            assert json.loads(sub_path.read_text(encoding="utf-8")) == manual_q
            assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
            client = SocketEpisodeClient(sock_path)
            with pytest.raises(RuntimeError, match="EpisodeClosed"):
                client.observe()
            with pytest.raises(RuntimeError, match="EpisodeClosed"):
                client.stop()
            assert json.loads(sub_path.read_text(encoding="utf-8")) == manual_q

    asyncio.run(flood())


@pytest.mark.parametrize(("call_fn_name", "call_arg"), [("submit", {"bad": 1}), ("submit", None), ("stop", None)])
def test_socket_invalid_submit_and_stop_persist_null_submission(tmp_path, short_sock_dir, call_fn_name, call_arg):
    from robotization_bench.mcp_proxy import SocketEpisodeClient

    sock_path = short_sock_dir / "term.sock"
    state_path = tmp_path / "state.json"
    sub_path = tmp_path / "submission.json"
    log_path = tmp_path / "episode.json"

    async def run_case():
        async with running_daemon(sock_path, submission=sub_path, log=log_path, state=state_path):
            client = SocketEpisodeClient(sock_path)
            if call_fn_name == "stop":
                res = client.stop()
            elif call_arg is None:
                res = client.submit()
            else:
                res = client.submit(call_arg)
            assert res == {"terminal": True, "plan": None}
            assert json.loads(sub_path.read_text(encoding="utf-8")) is None
            with pytest.raises(RuntimeError, match="EpisodeClosed"):
                client.observe()

    asyncio.run(run_case())


def test_sigkill_stale_socket_recovery_and_cli_validation(tmp_path, short_sock_dir):
    from robotization_bench.mcp_proxy import SocketEpisodeClient

    # 1. Missing socket without autostart_bin raises FileNotFoundError immediately
    missing_client = SocketEpisodeClient(short_sock_dir / "absent.sock", autostart_bin=tmp_path / "no_such_bin")
    with pytest.raises(FileNotFoundError):
        missing_client.observe()

    # 2. Duplicate --submission and --log paths rejected cleanly
    same = tmp_path / "same.json"
    dup = subprocess.run(
        [
            sys.executable,
            "-m",
            "robotization_bench.mcp_server",
            "--submission",
            str(same),
            "--log",
            str(same),
        ],
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
    )
    assert dup.returncode != 0

    # 3. Hard SIGKILL leaves stale socket on disk; restarted daemon unlinks it and preserves state
    sock_path = short_sock_dir / "kill.sock"
    state_path = tmp_path / "kill_state.json"
    sub_path = tmp_path / "kill_sub.json"
    log_path = tmp_path / "kill_log.json"
    manual_q = manual_quarterly_value()

    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    cmd = [
        sys.executable,
        "-m",
        "robotization_bench.mcp_server",
        "--mode",
        "quarterly",
        "--socket",
        str(sock_path),
        "--state",
        str(state_path),
        "--submission",
        str(sub_path),
        "--log",
        str(log_path),
    ]
    proc1 = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        _wait_for_socket(sock_path, proc1)
        c1 = SocketEpisodeClient(sock_path)
        assert c1.pilot(manual_q, 11)["pilot_budget"]["used"] == 1
        proc1.kill()
        proc1.wait(timeout=5)
    finally:
        if proc1.poll() is None:
            proc1.kill()
            proc1.wait(timeout=5)

    assert sock_path.is_socket()

    proc2 = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        _wait_for_socket(sock_path, proc2)
        c2 = SocketEpisodeClient(sock_path)
        assert c2.observe()["pilot_budget"]["used"] == 1
    finally:
        proc2.terminate()
        proc2.wait(timeout=5)


def test_save_rejects_symlinked_parent_dir_preserving_macos_tmp(tmp_path, short_sock_dir):
    from robotization_bench.mcp_server import _save

    victim_dir = tmp_path / "victim_dir"
    victim_dir.mkdir()
    sym_parent = tmp_path / "artifacts"
    sym_parent.symlink_to(victim_dir)

    with pytest.raises(ValueError, match="symlink"):
        _save(sym_parent / "submission.json", {"clobbered": True})
    assert not (victim_dir / "submission.json").exists()

    with pytest.raises(ValueError, match="symlink"):
        _save(sym_parent / "nested" / "submission.json", {"clobbered": True})
    assert not (victim_dir / "nested").exists()

    # macOS /tmp compatibility check (/tmp -> private/tmp system symlink must remain allowed)
    tmp_ok = short_sock_dir / "ok_sub.json"
    _save(tmp_ok, {"ok": True})
    assert json.loads(tmp_ok.read_text(encoding="utf-8")) == {"ok": True}


def test_socket_daemon_catches_deep_json_recursion_error_cleanly(tmp_path, short_sock_dir):
    sock_path = short_sock_dir / "rec.sock"
    sub = tmp_path / "rec_sub.json"
    log = tmp_path / "rec_log.json"

    async def interact_recursion():
        async with running_daemon(sock_path, submission=sub, log=log):
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(10.0)
                s.connect(str(sock_path))
                deep_json = b'{"action":"pilot","args":{"plan":' + (b"[" * 100_000) + (b"]" * 100_000) + b',"seed":11}}\n'
                obs_json = b'{"action":"observe","args":{}}\n'
                s.sendall(deep_json + obs_json)
                buf = b""
                while buf.count(b"\n") < 2:
                    chunk = s.recv(65536)
                    assert chunk, "daemon closed connection instead of returning RecursionError frame"
                    buf += chunk
                lines = buf.splitlines()
                assert len(lines) == 2
                r1 = json.loads(lines[0].decode("utf-8"))
                r2 = json.loads(lines[1].decode("utf-8"))
                assert r1["ok"] is False and r1["error_type"] == "RecursionError"
                assert r2["ok"] is True and r2["result"]["schema_version"] == 2

    asyncio.run(interact_recursion())
