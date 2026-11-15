"""Stateless MCP stdio proxy and Unix-socket client with zero simulator imports."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool

_DEFAULT_SOCKET = "/run/bench/bench.sock"
_DEFAULT_AUTOSTART = Path("/usr/local/bin/bench-daemon-start")
_MAX_RESPONSE_BYTES = 32 * 1024 * 1024


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


_PLAN = {"description": "The full plan object matching observe().manual (schema_version 2 quarterly or 1 shift)."}
_TOOLS = [
    _tool("observe", "Read the catalog, rules, manual plan, and public development seeds.", {}),
    _tool(
        "pilot",
        "Run one development simulation on a public seed. A failed pilot leaves the episode open.",
        {
            "plan": _PLAN,
            "seed": {"type": "integer", "description": "A public development seed from observe."},
            "trace": {"type": "boolean", "default": False, "description": "Include detailed shift events."},
        },
        ("plan", "seed"),
    ),
    _tool(
        "submit",
        "Close the episode permanently by submitting one final plan. A missing or invalid plan scores zero.",
        {"plan": _PLAN},
    ),
    _tool("stop", "Close the episode without submitting a plan.", {}),
]


class EpisodeRemoteError(RuntimeError):
    """Raised when the privileged episode daemon returns ok=False."""

    def __init__(self, error_type: str, error: str) -> None:
        self.error_type = error_type
        self.error = error
        super().__init__(f"{error_type}: {error}")


class SocketEpisodeClient:
    """Thin synchronous client speaking JSON-lines to the privileged AF_UNIX daemon."""

    def __init__(
        self,
        socket_path: Path | str | None = None,
        autostart_bin: Path | str = _DEFAULT_AUTOSTART,
        timeout: float = 30.0,
    ) -> None:
        resolved = os.environ.get("BENCH_SOCKET", _DEFAULT_SOCKET) if socket_path is None else socket_path
        self.socket_path = Path(resolved)
        self.autostart_bin = Path(autostart_bin)
        self.timeout = float(timeout)

    def _connect_once(self) -> socket.socket:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(self.timeout)
            sock.connect(str(self.socket_path))
            return sock
        except BaseException:
            sock.close()
            raise

    def _connect(self) -> socket.socket:
        try:
            return self._connect_once()
        except (FileNotFoundError, ConnectionRefusedError) as initial_err:
            if not (self.autostart_bin.is_file() and os.access(self.autostart_bin, os.X_OK)):
                raise
            subprocess.run([str(self.autostart_bin)], timeout=10.0, check=True)
            deadline = time.monotonic() + 5.0
            last_err: BaseException = initial_err
            while time.monotonic() < deadline:
                try:
                    return self._connect_once()
                except (FileNotFoundError, ConnectionRefusedError) as err:
                    last_err = err
                    time.sleep(0.025)
            raise last_err

    def _request(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        frame = (json.dumps({"action": action, "args": args}, ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")
        sock = self._connect()
        try:
            sock.sendall(frame)
            buf = bytearray()
            while True:
                nl = buf.find(b"\n")
                if nl != -1:
                    raw_line = bytes(buf[:nl])
                    break
                if len(buf) >= _MAX_RESPONSE_BYTES:
                    raise RuntimeError("daemon response exceeded 32 MiB")
                chunk = sock.recv(65536)
                if not chunk:
                    raise RuntimeError("unexpected EOF from episode daemon")
                buf.extend(chunk)
        finally:
            sock.close()

        resp = json.loads(raw_line.decode("utf-8"))
        if type(resp) is not dict:
            raise RuntimeError("malformed daemon response")
        if not resp.get("ok"):
            err_type = str(resp.get("error_type") or "Error")
            err_msg = str(resp.get("error") or "unknown error")
            raise EpisodeRemoteError(err_type, err_msg)
        result = resp.get("result")
        if type(result) is not dict:
            raise RuntimeError("malformed daemon result payload")
        return result

    def observe(self) -> dict[str, Any]:
        return self._request("observe", {})

    def pilot(self, plan: object, seed: int, *, trace: bool = False) -> dict[str, Any]:
        return self._request("pilot", {"plan": plan, "seed": seed, "trace": trace})

    def submit(self, plan: object = None) -> dict[str, Any]:
        args = {"plan": plan} if plan is not None else {}
        return self._request("submit", args)

    def stop(self) -> dict[str, Any]:
        return self._request("stop", {})


async def serve(
    socket_path: Path | str | None = None,
    autostart_bin: Path | str = _DEFAULT_AUTOSTART,
) -> None:
    client = SocketEpisodeClient(socket_path=socket_path, autostart_bin=autostart_bin)
    server = Server("robotization-bench", version="0.1.0")

    @server.list_tools()
    async def list_tools():
        return _TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None):
        args = {} if arguments is None else arguments
        if type(args) is not dict:
            raise TypeError("arguments must be a JSON object")
        if name == "observe":
            return await asyncio.to_thread(client.observe)
        if name == "pilot":
            if "plan" not in args or "seed" not in args:
                raise KeyError("pilot requires 'plan' and 'seed'")
            return await asyncio.to_thread(
                client.pilot,
                args["plan"],
                args["seed"],
                trace=args.get("trace", False),
            )
        if name == "submit":
            if "plan" in args:
                return await asyncio.to_thread(client.submit, args["plan"])
            return await asyncio.to_thread(client.submit)
        if name == "stop":
            return await asyncio.to_thread(client.stop)
        raise ValueError(f"Unknown tool: {name}")

    async with stdio_server() as (reader, writer):
        await server.run(reader, writer, server.create_initialization_options())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--socket",
        type=Path,
        default=None,
        help="Unix domain socket path (defaults to BENCH_SOCKET or /run/bench/bench.sock)",
    )
    parser.add_argument(
        "--autostart-bin",
        type=Path,
        default=_DEFAULT_AUTOSTART,
        help="Optional setuid launcher executed once if the daemon socket is absent",
    )
    options = parser.parse_args()
    asyncio.run(serve(socket_path=options.socket, autostart_bin=options.autostart_bin))


if __name__ == "__main__":
    main()
