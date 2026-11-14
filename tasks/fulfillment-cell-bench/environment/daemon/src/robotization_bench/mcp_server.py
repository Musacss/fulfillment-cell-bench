"""Public pilot service over MCP stdio or persistent AF_UNIX JSON-lines daemon."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import signal
import stat
from tempfile import NamedTemporaryFile
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool

from .contracts import EpisodeClosed, InvalidPlan, PilotBudgetExceeded, load_world
from .episode import Episode, QuarterlyEpisode
from .scenarios import generate

_SOCKET_STREAM_LIMIT = 16 * 1024 * 1024
_SYSTEM_SYMLINK_DIRS = frozenset({Path("/tmp"), Path("/var")})


def _tool(name: str, description: str, properties: dict[str, Any], required: tuple[str, ...] = ()) -> Tool:
    return Tool(
        name=name,
        description=description,
        inputSchema={
            "type": "object",
            "properties": properties,
            "required": list(required),
            "additionalProperties": False,
        },
    )


_PLAN = {"description": "The full v1 plan object. See the manual plan in observe for its shape."}
_TOOLS = [
    _tool("observe", "Read the catalog, rules, manual plan, and public development days.", {}),
    _tool(
        "pilot",
        "Run one development shift. A failed pilot leaves the episode open.",
        {
            "plan": _PLAN,
            "seed": {"type": "integer", "description": "A public day from observe."},
            "trace": {"type": "boolean", "default": False, "description": "Include detailed shift events."},
        },
        ("plan", "seed"),
    ),
    _tool(
        "submit",
        "Close the episode by submitting one plan. A missing or invalid plan scores zero.",
        {"plan": _PLAN},
    ),
    _tool("stop", "Close the episode without submitting a plan.", {}),
]


def _save(path: Path | None, value: Any) -> None:
    if path is None:
        return
    abs_path = Path(os.path.abspath(path))
    parent = abs_path.parent
    for anc in (parent, *parent.parents):
        if anc in _SYSTEM_SYMLINK_DIRS:
            continue
        try:
            anc_st = os.lstat(anc)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(anc_st.st_mode):
            raise ValueError(f"{anc} must not be a symlink")
        if not stat.S_ISDIR(anc_st.st_mode):
            raise ValueError(f"{anc} must be a directory")

    try:
        st = os.lstat(abs_path)
    except FileNotFoundError:
        st = None
    if st is not None:
        if stat.S_ISLNK(st.st_mode):
            raise ValueError(f"{path} must not be a symlink")
        if not stat.S_ISREG(st.st_mode):
            raise ValueError(f"{path} must be a regular file")

    encoded = (json.dumps(value, ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")
    parent.mkdir(parents=True, exist_ok=True)
    parent_st = os.lstat(parent)
    if stat.S_ISLNK(parent_st.st_mode) and parent not in _SYSTEM_SYMLINK_DIRS:
        raise ValueError(f"{parent} must not be a symlink")
    if not stat.S_ISLNK(parent_st.st_mode) and not stat.S_ISDIR(parent_st.st_mode):
        raise ValueError(f"{parent} must be a directory")
    with NamedTemporaryFile(
        mode="wb",
        dir=parent,
        prefix=".mcp-",
        suffix=".tmp",
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
        try:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
            os.replace(temporary, abs_path)
        finally:
            temporary.unlink(missing_ok=True)


def _build_episode(
    mode: str,
    *,
    max_pilots: int | None = None,
    state: Path | None = None,
    rules: Path | None = None,
) -> Episode | QuarterlyEpisode:
    world = load_world()
    if mode == "quarterly":
        return QuarterlyEpisode(world, max_pilots=max_pilots, state_path=state, rules_path=rules)
    if mode == "v1":
        days = tuple(generate(world, seed) for seed in world["development_seeds"])
        return Episode(world, days, max_pilots=max_pilots, state_path=state, rules_path=rules)
    raise ValueError(f"Unsupported mode: {mode}")


def _execute_action(
    episode: Episode | QuarterlyEpisode,
    name: str,
    arguments: dict[str, Any] | None,
    submission: Path | None,
    log: Path | None,
) -> dict[str, Any]:
    args = {} if arguments is None else arguments
    if type(args) is not dict:
        raise TypeError("arguments must be a JSON object")
    try:
        if name == "observe":
            return episode.observe()
        if name == "pilot":
            if "plan" not in args or "seed" not in args:
                raise KeyError("pilot requires 'plan' and 'seed'")
            trace = args.get("trace", False)
            if type(trace) is not bool:
                raise TypeError("trace must be a boolean")
            return episode.pilot(args["plan"], args["seed"], trace=trace)
        if name == "submit":
            receipt = episode.submit(args.get("plan"))
        elif name == "stop":
            receipt = episode.stop()
        else:
            raise ValueError(f"Unknown tool: {name}")
        _save(submission, receipt["plan"])
        return receipt
    finally:
        _save(log, episode.log)


def _prepare_socket_path(socket_path: Path) -> None:
    try:
        st = os.lstat(socket_path)
    except FileNotFoundError:
        st = None
    if st is not None:
        if stat.S_ISLNK(st.st_mode):
            raise ValueError("socket path must not be a symlink")
        if stat.S_ISSOCK(st.st_mode):
            socket_path.unlink()
        else:
            raise ValueError("socket path already exists and is not a socket")
    socket_path.parent.mkdir(parents=True, exist_ok=True)


async def serve(
    submission: Path | None,
    log: Path | None,
    *,
    mode: str = "quarterly",
    socket_path: Path | None = None,
    state: Path | None = None,
    max_pilots: int | None = None,
    rules: Path | None = None,
) -> None:
    episode = _build_episode(mode, max_pilots=max_pilots, state=state, rules=rules)
    _save(submission, episode.submission)
    _save(log, episode.log)
    lock = asyncio.Lock()

    if socket_path is not None:
        _prepare_socket_path(socket_path)

        async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while True:
                    try:
                        raw_line = await reader.readline()
                    except (asyncio.LimitOverrunError, ValueError) as exc:
                        err_frame = {"ok": False, "error_type": type(exc).__name__, "error": str(exc)}
                        writer.write((json.dumps(err_frame, ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8"))
                        await writer.drain()
                        break
                    if not raw_line:
                        break
                    if not raw_line.strip():
                        continue
                    try:
                        req = json.loads(raw_line.decode("utf-8"))
                        if type(req) is not dict:
                            raise TypeError("request must be a JSON object")
                        action = req.get("action")
                        if type(action) is not str:
                            raise ValueError("request 'action' must be a string")
                        raw_args = req.get("args", {})
                        if raw_args is None:
                            raw_args = {}
                        if type(raw_args) is not dict:
                            raise TypeError("request 'args' must be a JSON object")
                        async with lock:
                            data = _execute_action(episode, action, raw_args, submission, log)
                        resp: dict[str, Any] = {"ok": True, "result": data}
                    except (
                        EpisodeClosed,
                        PilotBudgetExceeded,
                        InvalidPlan,
                        ValueError,
                        KeyError,
                        TypeError,
                        UnicodeDecodeError,
                        RecursionError,
                    ) as exc:
                        resp = {"ok": False, "error_type": type(exc).__name__, "error": str(exc)}
                    payload = (json.dumps(resp, ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")
                    writer.write(payload)
                    await writer.drain()
            except (ConnectionResetError, BrokenPipeError, EOFError):
                pass
            finally:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except (NotImplementedError, RuntimeError):
                pass

        unix_srv = await asyncio.start_unix_server(
            handle_client,
            path=str(socket_path),
            limit=_SOCKET_STREAM_LIMIT,
        )
        os.chmod(socket_path, 0o666)
        try:
            async with unix_srv:
                await stop_event.wait()
        finally:
            try:
                if socket_path.is_socket():
                    socket_path.unlink(missing_ok=True)
            except OSError:
                pass
        return

    server = Server("robotization-bench", version="0.1.0")

    @server.list_tools()
    async def list_tools():
        return _TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None):
        async with lock:
            return _execute_action(episode, name, arguments, submission, log)

    async with stdio_server() as (reader, writer):
        await server.run(reader, writer, server.create_initialization_options())


def _canonical_target(path: Path) -> Path:
    return path.parent.resolve() / path.name


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("quarterly", "v1"),
        default="quarterly",
        help="Episode horizon mode (default: quarterly)",
    )
    parser.add_argument("--socket", type=Path, default=None, help="Serve persistent JSON-lines protocol on AF_UNIX socket")
    parser.add_argument("--state", type=Path, default=None, help="Persist non-resettable episode state JSON here (0600)")
    parser.add_argument("--submission", type=Path, default=None, help="Write the final JSON plan (or null) to this path")
    parser.add_argument("--log", type=Path, default=None, help="Write the episode log as a JSON array to this path")
    parser.add_argument("--max-pilots", type=int, default=None, help="Override maximum allowed pilot rollouts")
    parser.add_argument("--rules", type=Path, default=None, help="Optional path to SPEC.md")
    options = parser.parse_args()

    configured = [
        p for p in (options.submission, options.log, options.state, options.socket) if p is not None
    ]
    resolved = [_canonical_target(p) for p in configured]
    if len(resolved) != len(set(resolved)):
        parser.error("--submission, --log, --state, and --socket must be distinct paths")

    asyncio.run(
        serve(
            options.submission,
            options.log,
            mode=options.mode,
            socket_path=options.socket,
            state=options.state,
            max_pilots=options.max_pilots,
            rules=options.rules,
        )
    )


if __name__ == "__main__":
    main()
