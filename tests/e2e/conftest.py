"""Shared opaque-box fixtures, lazy v2 loaders, socket/CORS managers, and 3D trace auditors."""

from __future__ import annotations

import ast
import asyncio
from collections import Counter, defaultdict
from collections.abc import Mapping
from contextlib import contextmanager
import copy
from fractions import Fraction
import http.client
import importlib
import inspect
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_BIN = Path(sys.executable)

MANUAL_WORKERS: list[list[int]] = [[1], [2], [3], [3], [4], [2, 3]]

CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")

SECRET_PATTERNS = (
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bsk-proj-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bsk-or-v1-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{24,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{32,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b"),
    re.compile(r"\bhf_[A-Za-z0-9]{28,}\b"),
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----"),
)

EVENT_KEYS_V1 = ("tick", "kind", "order_id", "resource", "stage", "attempt", "end_tick")
EVENT_KINDS_V1 = frozenset(
    {
        "arrival",
        "start",
        "finish",
        "break",
        "jam",
        "assist",
        "walk",
        "enqueue",
        "good",
        "escaped",
        "scrap",
    }
)
ECONOMY_COST_KEYS_V1 = frozenset(
    {
        "depreciation",
        "service",
        "shifts",
        "overtime",
        "trays",
        "materials",
        "rework",
        "late",
        "unfulfilled",
        "escaped",
    }
)

FORBIDDEN_PUBLIC_FILENAMES = frozenset(
    {
        "engine.py",
        "quarterly.py",
        "scenarios.py",
        "economics.py",
        "grading.py",
        "reference.py",
        "verifier.py",
        "episode.py",
        "mcp_server.py",
        "seeds.json",
        "provenance.json",
    }
)


def lazy_mod(name: str) -> Any:
    """Import a robotization_bench module inside a test body for pre-merge collection safety."""
    try:
        return importlib.import_module(f"robotization_bench.{name}")
    except ModuleNotFoundError as exc:
        raise AssertionError(f"Required module robotization_bench.{name} is missing: {exc}") from exc


def lazy_attr(mod_name: str, attr: str) -> Any:
    """Resolve an attribute on a robotization_bench module lazily inside a test body."""
    mod = lazy_mod(mod_name)
    if not hasattr(mod, attr):
        raise AssertionError(f"Required symbol robotization_bench.{mod_name}.{attr} is missing")
    return getattr(mod, attr)


def make_week(
    *,
    robot: bool = False,
    trays: bool = False,
    route: str = "manual",
    maintenance: bool = False,
    workers: list[list[int]] | None = None,
) -> dict[str, Any]:
    return {
        "robot": robot,
        "trays": trays,
        "route": route,
        "maintenance": maintenance,
        "workers": copy.deepcopy(workers if workers is not None else MANUAL_WORKERS),
    }


def v1_manual_plan() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "robot": False,
        "trays": False,
        "route": "manual",
        "workers": copy.deepcopy(MANUAL_WORKERS),
    }


def v2_manual_quarterly(world: dict[str, Any] | None = None) -> dict[str, Any]:
    if world is not None:
        try:
            qmod = importlib.import_module("robotization_bench.quarterly")
            if hasattr(qmod, "manual_quarterly_value"):
                return qmod.manual_quarterly_value(world)
        except Exception:
            pass
    return {"schema_version": 2, "weeks": [make_week() for _ in range(12)]}


def v2_phased_win_candidates() -> list[dict[str, Any]]:
    """Small diverse pool of genuine phased automation plans immune to exact wave-index calibration."""
    crew_4_flex = [[1, 2], [2, 3], [3, 4], [1, 4]]
    crew_5_base = [[1], [2], [3, 4], [2, 3], [4]]
    crew_5_flex = [[1, 2], [2], [3, 4], [2, 3], [1, 4]]
    crew_6_peak = [[1], [2], [3, 4], [2, 3], [3, 4], [1, 2]]

    schedules = [
        (0, (4, 8), crew_5_base, crew_6_peak, {5, 6, 9, 10, 11}),
        (0, (3, 7), crew_5_base, crew_5_flex, {4, 5, 8, 9, 10, 11}),
        (0, (5, 9), crew_4_flex, crew_5_flex, {3, 4, 7, 8, 10, 11}),
        (0, (3, 6, 9), crew_5_base, crew_6_peak, {7, 8, 9, 10, 11}),
        (1, (5, 9), crew_5_base, crew_6_peak, {6, 7, 9, 10, 11}),
        (0, (4, 8), crew_4_flex, crew_5_base, {5, 6, 8, 9, 10, 11}),
    ]
    candidates: list[dict[str, Any]] = []
    for buy_week, maint_weeks, base_crew, peak_crew, peak_set in schedules:
        weeks = []
        for w in range(12):
            if w < buy_week:
                weeks.append(make_week())
            else:
                weeks.append(
                    make_week(
                        robot=True,
                        trays=True,
                        route="bypass",
                        maintenance=(w in maint_weeks),
                        workers=(peak_crew if w in peak_set else base_crew),
                    )
                )
        candidates.append({"schema_version": 2, "weeks": weeks})
    return candidates


def best_phased_win_plan(
    world: dict[str, Any], seeds: list[int] | tuple[int, ...] | None = None
) -> tuple[dict[str, Any], Any]:
    """Evaluate genuine phased candidates (plus reference.solve if available) via public evaluate_quarterly."""
    evaluate_quarterly = lazy_attr("grading", "evaluate_quarterly")
    eval_seeds = list(seeds if seeds is not None else world["development_seeds"])
    pool = v2_phased_win_candidates()
    try:
        q_ep_cls = getattr(importlib.import_module("robotization_bench.episode"), "QuarterlyEpisode", None)
        solve_fn = getattr(importlib.import_module("robotization_bench.reference"), "solve", None)
        if q_ep_cls is not None and solve_fn is not None:
            solved = solve_fn(q_ep_cls(copy.deepcopy(world)))
            if isinstance(solved, dict) and solved.get("schema_version") == 2:
                pool.insert(0, solved)
    except Exception:
        pass

    best_pair: tuple[dict[str, Any], Any] | None = None
    best_key: tuple[bool, bool, Fraction] | None = None
    for cand in pool:
        ev = evaluate_quarterly(world, cand, eval_seeds)
        score = Fraction(ev.reward_num, ev.reward_den) if ev.valid else Fraction(-1, 1)
        key = (bool(ev.win), bool(ev.feasible), score)
        if best_key is None or key > best_key:
            best_key = key
            best_pair = (cand, ev)
    assert best_pair is not None
    return best_pair


def v2_buy_capex_idle(world: dict[str, Any] | None = None) -> dict[str, Any]:
    manual = v2_manual_quarterly(world)
    base_workers = manual["weeks"][0]["workers"]
    return {
        "schema_version": 2,
        "weeks": [
            make_week(robot=True, trays=True, route="manual", maintenance=False, workers=base_workers)
            for _ in range(12)
        ],
    }


def v2_unstaffed_jam_deadlock() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "weeks": [
            make_week(robot=True, trays=False, route="all", maintenance=False, workers=[[1], [2], [4]])
            for _ in range(12)
        ],
    }


def v2_week11_token(world: dict[str, Any] | None = None) -> dict[str, Any]:
    manual = v2_manual_quarterly(world)
    weeks = copy.deepcopy(manual["weeks"][:11])
    w11_workers = copy.deepcopy(manual["weeks"][11]["workers"])
    weeks.append(make_week(robot=True, trays=True, route="bypass", maintenance=False, workers=w11_workers))
    return {"schema_version": 2, "weeks": weeks}


def v2_naive_all_unmaintained() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "weeks": [
            make_week(robot=True, trays=False, route="all", maintenance=False, workers=[[1], [2], [4], [3, 4]])
            for _ in range(12)
        ],
    }


def v2_understaffed_carryover_plan() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "weeks": [
            make_week(robot=False, trays=False, route="manual", maintenance=False, workers=[[1, 2, 3, 4]])
            for _ in range(12)
        ],
    }


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def python_bin() -> Path:
    return PYTHON_BIN


@pytest.fixture
def world() -> dict[str, Any]:
    load_world = lazy_attr("contracts", "load_world")
    return load_world()


@pytest.fixture
def dev_scenarios(world: dict[str, Any]) -> tuple[Any, ...]:
    generate = lazy_attr("scenarios", "generate")
    return tuple(generate(world, s) for s in world["development_seeds"])


@pytest.fixture
def replay_seeds() -> list[int]:
    return json.loads((REPO_ROOT / "evidence" / "replay_seeds.json").read_text(encoding="utf-8"))


@pytest.fixture
def short_sock_dir():
    """macOS AF_UNIX sun_path <= 104 bytes: always allocate sockets under /tmp/fcb_*."""
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="fcb_") as raw:
        yield Path(raw)


@pytest.fixture
def run_cli():
    def _run(
        args: list[str],
        *,
        timeout: float = 15.0,
        env_extra: dict[str, str] | None = None,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "PYTHONPATH": str(REPO_ROOT / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [str(PYTHON_BIN), *args],
            cwd=str(cwd or REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    return _run


def make_socket_client(sock_path: Path, autostart_bin: Path | None = None) -> Any:
    cls = lazy_attr("mcp_proxy", "SocketEpisodeClient")
    sig = inspect.signature(cls)
    target_bin = autostart_bin if autostart_bin is not None else Path("/nonexistent_bench_autostart")
    if "autostart_bin" in sig.parameters:
        return cls(sock_path, autostart_bin=target_bin)
    if len(sig.parameters) >= 2:
        return cls(sock_path, target_bin)
    return cls(sock_path)


@contextmanager
def running_bench_daemon(
    sock_path: Path,
    *,
    state_path: Path,
    sub_path: Path,
    log_path: Path,
    mode: str = "quarterly",
    max_pilots: int | None = None,
    python_path: Path | None = None,
):
    assert len(str(sock_path).encode("utf-8")) < 100, f"AF_UNIX path too long: {sock_path}"
    cmd = [
        str(PYTHON_BIN),
        "-m",
        "robotization_bench.mcp_server",
        "--mode",
        mode,
        "--socket",
        str(sock_path),
        "--state",
        str(state_path),
        "--submission",
        str(sub_path),
        "--log",
        str(log_path),
    ]
    if max_pilots is not None:
        cmd.extend(["--max-pilots", str(max_pilots)])
    env = {
        **os.environ,
        "PYTHONPATH": str(python_path or (REPO_ROOT / "src")),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 4.0
        while not sock_path.exists():
            if proc.poll() is not None:
                err = proc.stderr.read() if proc.stderr else ""
                raise AssertionError(f"mcp_server exited early ({proc.returncode}): {err.strip()}")
            if time.monotonic() > deadline:
                raise TimeoutError(f"Timed out waiting for Unix socket {sock_path}")
            time.sleep(0.02)
        for _ in range(10):
            if proc.poll() is not None:
                err = proc.stderr.read() if proc.stderr else ""
                raise AssertionError(f"mcp_server exited early ({proc.returncode}): {err.strip()}")
            if sock_path.is_socket():
                break
            time.sleep(0.025)
        time.sleep(0.025)
        yield proc
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2.0)


def send_unix_jsonl(sock_path: Path, payload: str | dict[str, Any]) -> dict[str, Any]:
    raw = (json.dumps(payload) + "\n") if isinstance(payload, dict) else payload
    buf = b""
    for attempt in range(11):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(4.0)
                client.connect(str(sock_path))
                client.sendall(raw.encode("utf-8"))
                buf = b""
                while not buf.endswith(b"\n"):
                    chunk = client.recv(65_536)
                    if not chunk:
                        break
                    buf += chunk
            break
        except (ConnectionRefusedError, FileNotFoundError):
            if attempt == 10:
                raise
            time.sleep(0.025)
    return json.loads(buf.decode("utf-8"))


def extract_mcp_payload(call_result: Any) -> Any:
    if getattr(call_result, "structuredContent", None) is not None:
        return call_result.structuredContent
    return json.loads(call_result.content[0].text)


def run_mcp_session(
    args: list[str],
    ops_fn,
    *,
    python_path: Path | None = None,
    env_extra: dict[str, str] | None = None,
) -> Any:
    """Connect to an MCP stdio server, run async ops_fn(session), and return its result."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {
        **os.environ,
        "PYTHONPATH": str(python_path or (REPO_ROOT / "src")),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if env_extra:
        env.update(env_extra)

    async def _runner():
        params = StdioServerParameters(command=str(PYTHON_BIN), args=args, env=env)
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                return await ops_fn(session)

    return asyncio.run(_runner())


CLI_OUTPUT_FLAGS = (
    "--output-dir",
    "--out-dir",
    "--output-file",
    "--output-path",
    "--output",
    "--out-file",
    "--out",
)
CLI_COUNT_FLAGS = (
    "--num-episodes",
    "--n-episodes",
    "--episodes",
    "--num-traces",
    "--traces",
    "--samples",
    "--rollouts",
    "--count",
    "--limit",
    "-n",
)


def has_cli_flag(help_txt: str, flag: str) -> bool:
    """Match CLI flags using strict token boundaries so '--out' never matches '--output' or '-n' in prose."""
    return bool(re.search(rf"(?<![\w-]){re.escape(flag)}(?:[\s,=\]|]|$)", help_txt))


def pick_cli_flag(help_txt: str, candidates: tuple[str, ...]) -> str | None:
    for flag in candidates:
        if has_cli_flag(help_txt, flag):
            return flag
    return None


def extract_eval_dict(payload: Any) -> dict[str, Any]:
    """Normalize nested {'evaluation': {...}} or flat asdict(Evaluation) JSON payloads."""
    if isinstance(payload, Mapping) and isinstance(payload.get("evaluation"), Mapping):
        return dict(payload["evaluation"])
    assert isinstance(payload, Mapping), f"Expected evaluation mapping, got {type(payload)}"
    return dict(payload)


def extract_index_ids(idx_doc: Any) -> set[str]:
    """Extract bundle IDs/slugs from artifacts/3d-pack/index.json across dict/list layouts."""
    ids: set[str] = set()
    if isinstance(idx_doc, Mapping):
        for key, val in idx_doc.items():
            if isinstance(val, Mapping) and ("path" in val or "format" in val or "weeks" in val or "kind" in val):
                ids.add(str(key))
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str):
                        ids.add(item.strip("/"))
                    elif isinstance(item, Mapping):
                        for f in ("id", "slug", "name", "dir", "path"):
                            if isinstance(item.get(f), str):
                                ids.add(Path(item[f].strip("/")).name)
        if not ids:
            raw_s = json.dumps(idx_doc)
            for slug in (
                "v1-manual-seed11",
                "v1-reference-seed11",
                "quarterly-manual-seed11",
                "quarterly-reference-seed11",
            ):
                if slug in raw_s:
                    ids.add(slug)
    elif isinstance(idx_doc, list):
        for item in idx_doc:
            if isinstance(item, str):
                ids.add(item.strip("/"))
            elif isinstance(item, Mapping):
                for f in ("id", "slug", "name", "dir", "path"):
                    if isinstance(item.get(f), str):
                        ids.add(Path(item[f].strip("/")).name)
    return ids


def scan_repo_for_secrets(repo_root: Path = REPO_ROOT) -> list[str]:
    """Scan all git-tracked files (excluding tests/e2e/) plus tasks/ and evidence/ for leaked secrets."""
    binary_exts = frozenset(
        {
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".webp",
            ".ico",
            ".pdf",
            ".zip",
            ".tar",
            ".gz",
            ".safetensors",
            ".pt",
            ".pth",
            ".bin",
            ".pyc",
            ".so",
            ".dylib",
            ".woff",
            ".woff2",
            ".ttf",
        }
    )
    candidates: set[Path] = set()
    ls_res = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files"],
        capture_output=True,
        text=True,
        check=False,
    )
    if ls_res.returncode == 0:
        for rel in ls_res.stdout.splitlines():
            rel_s = rel.strip()
            if rel_s and not rel_s.startswith("tests/e2e/"):
                candidates.add(repo_root / rel_s)

    for extra_sub in ("tasks", "evidence"):
        extra_dir = repo_root / extra_sub
        if extra_dir.exists():
            for p in extra_dir.rglob("*"):
                if p.is_file() and not p.is_symlink():
                    candidates.add(p)

    hits: list[str] = []
    for fpath in sorted(candidates):
        if not fpath.is_file() or fpath.is_symlink() or fpath.suffix.lower() in binary_exts:
            continue
        try:
            if fpath.stat().st_size > 5_000_000:
                continue
            raw_bytes = fpath.read_bytes()
            if b"\x00" in raw_bytes[:4096]:
                continue
            txt = raw_bytes.decode("utf-8", errors="ignore")
        except OSError:
            continue
        for pat in SECRET_PATTERNS:
            if pat.search(txt):
                rel_label = fpath.relative_to(repo_root).as_posix() if fpath.is_relative_to(repo_root) else str(fpath)
                hits.append(f"{rel_label}: {pat.pattern}")
    return hits


def _source_registers_cli_flag(source: str, flag: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return bool(re.search(rf"""add_argument\([^)]*['"]{re.escape(flag)}['"]""", source))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn_name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if fn_name in ("add_argument", "option"):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and arg.value == flag:
                        return True
    return False


def mcp_proxy_cli_args(sock_path: Path, python_path: Path | None = None) -> tuple[list[str], dict[str, str]]:
    """Build CLI args and env for python -m robotization_bench.mcp_proxy across CLI/env conventions."""
    src_root = python_path or (REPO_ROOT / "src")
    proxy_file = src_root / "robotization_bench" / "mcp_proxy.py"
    assert proxy_file.is_file(), f"Missing {proxy_file}"
    source = proxy_file.read_text(encoding="utf-8")
    args = ["-m", "robotization_bench.mcp_proxy"]
    if _source_registers_cli_flag(source, "--socket"):
        args.extend(["--socket", str(sock_path)])
    env_extra = {
        "BENCH_SOCKET": str(sock_path),
        "BENCH_AUTOSTART": "/nonexistent_bench_autostart",
    }
    return args, env_extra


def run_staged_oracle(
    task_dir: Path,
    sock_path: Path,
    sub_path: Path,
    log_path: Path,
) -> subprocess.CompletedProcess[str]:
    """Run staged solution/oracle.py in isolated Python (-I -B) with public/src and solution/ on sys.path."""
    public_src = task_dir / "environment" / "public" / "src"
    oracle_py = task_dir / "solution" / "oracle.py"
    code = (
        "import ast, inspect, os, runpy, sys\n"
        "from pathlib import Path\n"
        "public_src, oracle_py, sock_s, sub_s, log_s = sys.argv[1:6]\n"
        "sys.path.insert(0, str(Path(oracle_py).parent))\n"
        "sys.path.insert(0, public_src)\n"
        "os.environ['BENCH_SOCKET'] = sock_s\n"
        "os.environ['BENCH_SUBMISSION'] = sub_s\n"
        "os.environ['BENCH_LOG'] = log_s\n"
        "os.environ['BENCH_AUTOSTART'] = '/nonexistent_bench_autostart'\n"
        "sys.argv = [oracle_py]\n"
        "tree = ast.parse(Path(oracle_py).read_text(encoding='utf-8'))\n"
        "has_run = any(isinstance(n, ast.FunctionDef) and n.name == 'run' for n in tree.body)\n"
        "ran = False\n"
        "if has_run:\n"
        "    ns = runpy.run_path(oracle_py)\n"
        "    run_fn = ns.get('run')\n"
        "    if callable(run_fn):\n"
        "        sig = inspect.signature(run_fn)\n"
        "        name_map = {\n"
        "            'sock': Path(sock_s),\n"
        "            'socket': Path(sock_s),\n"
        "            'socket_path': Path(sock_s),\n"
        "            'sock_path': Path(sock_s),\n"
        "            'sub': Path(sub_s),\n"
        "            'out': Path(sub_s),\n"
        "            'submission': Path(sub_s),\n"
        "            'submission_path': Path(sub_s),\n"
        "            'out_path': Path(sub_s),\n"
        "            'log': Path(log_s),\n"
        "            'log_path': Path(log_s),\n"
        "            'autostart': Path('/nonexistent_bench_autostart'),\n"
        "            'autostart_bin': Path('/nonexistent_bench_autostart'),\n"
        "        }\n"
        "        pos_args = []\n"
        "        kw_args = {}\n"
        "        can_bind = True\n"
        "        skipped_pos_only = False\n"
        "        for p in sig.parameters.values():\n"
        "            if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):\n"
        "                continue\n"
        "            if p.name in name_map:\n"
        "                if p.kind == inspect.Parameter.POSITIONAL_ONLY:\n"
        "                    if skipped_pos_only:\n"
        "                        can_bind = False\n"
        "                        break\n"
        "                    pos_args.append(name_map[p.name])\n"
        "                else:\n"
        "                    kw_args[p.name] = name_map[p.name]\n"
        "            elif p.default is inspect.Parameter.empty:\n"
        "                can_bind = False\n"
        "                break\n"
        "            elif p.kind == inspect.Parameter.POSITIONAL_ONLY:\n"
        "                skipped_pos_only = True\n"
        "        if can_bind:\n"
        "            run_fn(*pos_args, **kw_args)\n"
        "            ran = True\n"
        "if not ran:\n"
        "    runpy.run_path(oracle_py, run_name='__main__')\n"
    )
    return subprocess.run(
        [
            str(PYTHON_BIN),
            "-I",
            "-B",
            "-c",
            code,
            str(public_src),
            str(oracle_py),
            str(sock_path),
            str(sub_path),
            str(log_path),
        ],
        cwd=str(sub_path.parent),
        capture_output=True,
        text=True,
        timeout=15.0,
    )


def run_staged_grade(task_dir: Path, sub_path: Path, verdict_dir: Path) -> dict[str, Any]:
    """Run staged tests/grade.py in isolated Python (-I -B) and return parsed evaluation.json."""
    grade_py = task_dir / "tests" / "grade.py"
    seeds_py = task_dir / "tests" / "seeds.json"
    verdict_dir.mkdir(parents=True, exist_ok=True)
    code = (
        "import ast, builtins, inspect, os, pathlib, runpy, sys\n"
        "from pathlib import Path\n"
        "grade_py, sub_s, seeds_s, out_s = sys.argv[1:5]\n"
        "sys.path.insert(0, str(Path(grade_py).parent))\n"
        "os.environ['BENCH_SUBMISSION'] = sub_s\n"
        "os.environ['BENCH_SEEDS'] = seeds_s\n"
        "os.environ['BENCH_VERIFIER_DIR'] = out_s\n"
        "os.environ['HARBOR_VERIFIER_DIR'] = out_s\n"
        "sys.argv = [grade_py]\n"
        "_REMAP = (\n"
        "    ('/logs/artifacts/submission.json', sub_s),\n"
        "    ('/logs/artifacts', str(Path(sub_s).parent)),\n"
        "    ('/logs/verifier', out_s),\n"
        "    ('/tests/seeds.json', seeds_s),\n"
        "    ('/tests', str(Path(seeds_s).parent)),\n"
        ")\n"
        "def _remap_str(val):\n"
        "    if isinstance(val, str):\n"
        "        for prefix, repl in _REMAP:\n"
        "            if val == prefix or val.startswith(prefix + '/'):\n"
        "                return repl + val[len(prefix):]\n"
        "    return val\n"
        "def _remap_pathlike(p):\n"
        "    if isinstance(p, str):\n"
        "        return _remap_str(p)\n"
        "    if isinstance(p, os.PathLike):\n"
        "        s = os.fspath(p)\n"
        "        if isinstance(s, str):\n"
        "            rs = _remap_str(s)\n"
        "            if rs != s:\n"
        "                return Path(rs)\n"
        "    return p\n"
        "_orig_open = builtins.open\n"
        "def _patched_open(file, *a, **kw):\n"
        "    return _orig_open(_remap_pathlike(file), *a, **kw)\n"
        "builtins.open = _patched_open\n"
        "_orig_os_open = os.open\n"
        "def _patched_os_open(path, flags, *a, **kw):\n"
        "    return _orig_os_open(_remap_pathlike(path), flags, *a, **kw)\n"
        "os.open = _patched_os_open\n"
        "if pathlib.PurePath.__init__ is not object.__init__:\n"
        "    _orig_pp_init = pathlib.PurePath.__init__\n"
        "    def _patched_pp_init(self, *args):\n"
        "        _orig_pp_init(self, *(_remap_pathlike(a) for a in args))\n"
        "    pathlib.PurePath.__init__ = _patched_pp_init\n"
        "else:\n"
        "    _orig_pp_new = pathlib.PurePath.__new__\n"
        "    def _patched_pp_new(cls, *args, **kwargs):\n"
        "        return _orig_pp_new(cls, *(_remap_pathlike(a) for a in args), **kwargs)\n"
        "    pathlib.PurePath.__new__ = staticmethod(_patched_pp_new)\n"
        "tree = ast.parse(Path(grade_py).read_text(encoding='utf-8'))\n"
        "has_grade = any(isinstance(n, ast.FunctionDef) and n.name == 'grade' for n in tree.body)\n"
        "ran = False\n"
        "if has_grade:\n"
        "    ns = runpy.run_path(grade_py)\n"
        "    grade_fn = ns.get('grade')\n"
        "    if callable(grade_fn):\n"
        "        sig = inspect.signature(grade_fn)\n"
        "        name_map = {\n"
        "            'sub': Path(sub_s),\n"
        "            'submission': Path(sub_s),\n"
        "            'submission_path': Path(sub_s),\n"
        "            'plan_path': Path(sub_s),\n"
        "            'path': Path(sub_s),\n"
        "            'seeds': Path(seeds_s),\n"
        "            'seeds_path': Path(seeds_s),\n"
        "            'seeds_file': Path(seeds_s),\n"
        "            'out': Path(out_s),\n"
        "            'out_dir': Path(out_s),\n"
        "            'output_dir': Path(out_s),\n"
        "            'verdict_dir': Path(out_s),\n"
        "            'verifier_dir': Path(out_s),\n"
        "        }\n"
        "        pos_args = []\n"
        "        kw_args = {}\n"
        "        can_bind = True\n"
        "        for p in sig.parameters.values():\n"
        "            if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):\n"
        "                continue\n"
        "            if p.name in name_map:\n"
        "                if p.kind == inspect.Parameter.POSITIONAL_ONLY:\n"
        "                    pos_args.append(name_map[p.name])\n"
        "                else:\n"
        "                    kw_args[p.name] = name_map[p.name]\n"
        "            elif p.default is inspect.Parameter.empty:\n"
        "                can_bind = False\n"
        "                break\n"
        "        if can_bind:\n"
        "            grade_fn(*pos_args, **kw_args)\n"
        "            ran = True\n"
        "        else:\n"
        "            req = [p for p in sig.parameters.values() if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)]\n"
        "            if len(req) == 2:\n"
        "                grade_fn(Path(sub_s), Path(out_s))\n"
        "                ran = True\n"
        "            elif len(req) == 3:\n"
        "                grade_fn(Path(sub_s), Path(seeds_s), Path(out_s))\n"
        "                ran = True\n"
        "if not ran:\n"
        "    runpy.run_path(grade_py, run_name='__main__')\n"
    )
    res = subprocess.run(
        [
            str(PYTHON_BIN),
            "-I",
            "-B",
            "-c",
            code,
            str(grade_py),
            str(sub_path),
            str(seeds_py),
            str(verdict_dir),
        ],
        cwd=str(verdict_dir.parent),
        capture_output=True,
        text=True,
        timeout=15.0,
    )
    assert res.returncode == 0, f"grade.py failed ({res.returncode}): {res.stderr}"
    return json.loads((verdict_dir / "evaluation.json").read_text(encoding="utf-8"))


def audit_v1_shift_bundle(bundle_dir: Path) -> dict[str, Any]:
    """Opaque-box validator for Musa's v1 3D shift bundle (manifest.json + events.jsonl)."""
    manifest_path = bundle_dir / "manifest.json"
    assert manifest_path.is_file(), f"Missing {manifest_path}"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest.get("replay_format") == "robotization-bench.replay.v1"
    events_filename = manifest.get("events_file")
    assert isinstance(events_filename, str) and events_filename
    events_path = bundle_dir / events_filename
    assert events_path.is_file(), f"Missing {events_path}"

    raw = manifest["raw"]
    assert raw["events"] == []
    w = manifest["world"]
    plan = manifest["plan"]
    scenario = manifest["scenario"]
    econ = manifest["economy"]

    assert w["clock"]["tick_seconds"] == 30
    assert scenario["schema_version"] == 1
    orders = scenario["orders"]
    assert len(orders) > 0
    order_pairs = [(o["arrival"], o["id"]) for o in orders]
    assert order_pairs == sorted(order_pairs), "Scenario orders must be strictly sorted by (arrival, id)"
    assert len({o["id"] for o in orders}) == len(orders)
    assert all(o["id"] >= 0 and o["due"] >= o["arrival"] >= 0 for o in orders)

    assert set(econ["costs"].keys()) == ECONOMY_COST_KEYS_V1
    assert econ["total"] == sum(econ["costs"].values())

    raw_text = events_path.read_text(encoding="utf-8")
    lines = [ln for ln in raw_text.splitlines() if ln]
    events: list[dict[str, Any]] = []
    for ln in lines:
        ev = json.loads(ln)
        assert ln == json.dumps(ev, separators=(",", ":")), "events.jsonl must be compact JSONL"
        assert tuple(ev.keys()) == EVENT_KEYS_V1
        assert ev["kind"] in EVENT_KINDS_V1
        events.append(ev)

    by_id = {o["id"]: o for o in orders}
    state: dict[int, tuple[str, int | None, int | None]] = {}
    limited = {2: "pick", 3: "pack", 4: "qc"}
    occupied: dict[int, set[int]] = defaultdict(set)
    active: dict[str, tuple[int, int | None, int | None]] = {}
    done: Counter[str] = Counter()
    last_tick = -1
    shift_ticks = w["clock"]["shift_ticks"]
    horizon = shift_ticks + w["clock"]["overtime_ticks"]

    for ev in events:
        tick, kind, oid, stage, attempt = (
            ev["tick"],
            ev["kind"],
            ev["order_id"],
            ev["stage"],
            ev["attempt"],
        )
        assert 0 <= tick <= horizon and last_tick <= tick
        last_tick = tick
        if kind == "break":
            continue
        assert oid in by_id and attempt in (0, 1)
        prev = state.get(oid)
        if kind == "arrival":
            assert prev is None and tick == by_id[oid]["arrival"]
        elif kind == "enqueue":
            if stage == 1:
                assert prev == ("arrival", 1, 0) and attempt == 0
            elif stage == 3 and attempt == 1:
                assert prev == ("finish", 4, 0)
            else:
                assert prev == ("finish", stage - 1, attempt)
                assert oid in occupied[stage]
        elif kind == "start":
            assert tick < horizon and prev == ("enqueue", stage, attempt)
            if stage in limited and (stage, attempt) != (3, 1):
                occupied[stage].remove(oid)
            if stage < 4:
                assert oid not in occupied[stage + 1]
                occupied[stage + 1].add(oid)
                assert len(occupied[stage + 1]) <= w["capacity"][limited[stage + 1]]
            if stage == 3:
                auto = attempt == 0 and (
                    plan["route"] == "all"
                    or (plan["route"] == "bypass" and by_id[oid]["kind"] == "regular")
                )
                assert (ev["resource"] == "robot") == auto
            assert ev["resource"] not in active
            active[ev["resource"]] = (oid, stage, attempt)
        elif kind == "finish":
            assert prev == ("start", stage, attempt)
            assert active.pop(ev["resource"]) == (oid, stage, attempt)
        elif kind in ("jam", "assist", "walk"):
            assert prev == ("start", stage, attempt)
            if kind in ("jam", "assist"):
                assert active["robot"] == (oid, 3, 0)
            continue
        elif kind in ("good", "escaped", "scrap"):
            assert prev == ("finish", 4, attempt)
            done[kind] += 1
            if kind == "good" and tick <= by_id[oid]["due"]:
                done["on_time"] += 1
        state[oid] = (kind, stage, attempt)

    assert state.keys() == by_id.keys()
    assert raw["unfinished"] == sum(v[0] in {"start", "enqueue"} for v in state.values())
    assert (raw["good"], raw["on_time"], raw["escaped"], raw["scrap"]) == (
        done["good"],
        done["on_time"],
        done["escaped"],
        done["scrap"],
    )
    assert raw["total"] == len(by_id) == raw["good"] + raw["escaped"] + raw["scrap"] + raw["unfinished"]

    labor = 0
    overtime: list[int] = []
    for idx, zones in enumerate(plan["workers"]):
        w_events = [e for e in events if e["resource"] == f"w{idx}"]
        position, available, last_work, took_break = zones[0], 0, 0, False
        for ev in w_events:
            if ev["kind"] not in ("start", "assist", "break"):
                continue
            assert available <= ev["tick"] < ev["end_tick"]
            available = ev["end_tick"]
            if ev["kind"] == "break":
                assert not took_break and ev["end_tick"] - ev["tick"] == w["clock"]["break_length"]
                assert ev["tick"] >= w["clock"]["break_at"]
                took_break = True
                continue
            assert ev["tick"] < w["clock"]["break_at"] or took_break
            assert ev["stage"] in zones
            walks = [wk for wk in w_events if wk["kind"] == "walk" and wk["tick"] == ev["tick"]]
            if position != ev["stage"]:
                assert [(wk["order_id"], wk["stage"], wk["end_tick"]) for wk in walks] == [
                    (ev["order_id"], ev["stage"], ev["tick"] + w["clock"]["walk_ticks"])
                ]
            else:
                assert not walks
            position = ev["stage"]
            last_work = min(horizon, ev["end_tick"])
            labor += last_work - ev["tick"]
        overtime.append(max(0, last_work - shift_ticks))

    assert raw["labor_ticks"] == labor
    assert list(raw["overtime_ticks"]) == overtime
    return {"manifest": manifest, "events": events}


def raw_http_request(
    host: str,
    port: int,
    method: str,
    target: str,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection(host, port, timeout=3.0)
    try:
        conn.putrequest(method, target, skip_accept_encoding=True)
        for k, v in (headers or {}).items():
            conn.putheader(k, v)
        conn.endheaders()
        resp = conn.getresponse()
        body = resp.read()
        hdrs = {k.lower(): v for k, v in resp.getheaders()}
        return resp.status, hdrs, body
    finally:
        conn.close()


@contextmanager
def running_cors_server(serve_dir: Path):
    script = REPO_ROOT / "scripts" / "serve_3d.py"
    assert script.is_file(), f"Missing {script}"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO_ROOT / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    proc = subprocess.Popen(
        [str(PYTHON_BIN), str(script), "--dir", str(serve_dir), "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 3.5
        ready = False
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                err = proc.stderr.read() if proc.stderr else ""
                raise AssertionError(f"serve_3d.py exited early ({proc.returncode}): {err.strip()}")
            try:
                status, _, _ = raw_http_request("127.0.0.1", port, "GET", "/index.json")
                if status in (200, 204, 400, 403, 404):
                    ready = True
                    break
            except OSError:
                pass
            time.sleep(0.025)
        assert ready, f"serve_3d.py failed readiness check on 127.0.0.1:{port}"
        yield ("127.0.0.1", port, proc)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2.0)


def python_specifier_allows(spec_str: str, version_str: str) -> bool:
    try:
        from packaging.specifiers import SpecifierSet

        return SpecifierSet(spec_str).contains(version_str)
    except Exception:
        ver = tuple(int(x) for x in version_str.split("."))
        for clause in spec_str.split(","):
            c = clause.strip()
            for op in (">=", "<=", "==", "!=", ">", "<"):
                if c.startswith(op):
                    rhs_parts = [int(x) for x in c[len(op) :].strip().split(".")]
                    lhs = ver[: len(rhs_parts)] if op in ("==", "!=") else ver
                    rhs = tuple(rhs_parts + [0] * max(0, len(lhs) - len(rhs_parts)))
                    ok = {
                        ">=": lhs >= rhs,
                        "<=": lhs <= rhs,
                        "==": lhs == rhs,
                        "!=": lhs != rhs,
                        ">": lhs > rhs,
                        "<": lhs < rhs,
                    }[op]
                    if not ok:
                        return False
                    break
        return True


def _classify_single_segment(seg: str) -> str | None:
    low = seg.lower()
    if re.fullmatch(r"(?:trial|run|attempt|seed|ep|episode|idx)[_-]?\d+|\d+", low):
        return None
    if "stop_early" in low or "stop-early" in low:
        return "stop_early"
    if re.search(r"(^|[/_.-])nop([/_.-]|$)", low):
        return "nop"
    if re.search(r"(^|[/_.-])(oracle|reference)([/_.-]|$)", low):
        return "oracle"
    is_explicit_base = bool(
        re.search(
            r"(base[_-]?[789]b|[789]b[_-]?base|pre[_-]?rl|qwen.*base|base.*qwen|"
            r"qwen.*zero[_-]?shot|zero[_-]?shot.*(?:qwen|[789]b)|(?:^|[/_.-])base(?:[/_.-]|\d|$))",
            low,
        )
    )
    is_post_rl = bool(
        re.search(
            r"(post[_-]?rl|postrl|sft[_-]?grpo|[789]b[_-]?rl|rl[_-]?[789]b|(?:^|[/_.-])grpo(?:[/_.-]|$)|"
            r"(?:qwen|[789]b).*(?:post|grpo|rl|lora|sft|ft|trained|tuned)|"
            r"(?:post|grpo|lora|sft|trained|tuned).*(?:qwen|[789]b))",
            low,
        )
    )
    if is_post_rl and not is_explicit_base:
        return "post_rl_7b"
    if is_explicit_base or re.search(
        r"((?:qwen|[789]b).*instruct|qwen3\.?5[_-]?9b|qwen3[_-]?8b|qwen2\.?5[_-]?7b|qwen[_-]?[789]b|qwen)",
        low,
    ):
        return "base_7b"
    if re.search(
        r"(gemini|gpt|openai|claude|anthropic|(?<![a-z0-9])o[134](?![a-z0-9])|sonnet|opus|deepseek|frontier|opencode)",
        low,
    ):
        return "frontier"
    return None


def _classify_evidence_role(label: str) -> str | None:
    ignore = {"artifacts", "verifier", "submission.json", "reward.txt", "evaluation.json"}
    parts = [p for p in Path(label).parts if p.lower() not in ignore]
    for seg in reversed(parts):
        role = _classify_single_segment(seg)
        if role is not None:
            return role
    return _classify_single_segment(label)


def discover_benchmark_v2_bundle(bundle_dir: Path | None = None) -> dict[str, Any]:
    """Discover blind_seeds.json, training_metrics.jsonl, and categorized run artifacts under evidence/benchmark-v2."""
    bdir = bundle_dir or (REPO_ROOT / "evidence" / "benchmark-v2")
    if bundle_dir is None and not bdir.is_dir():
        pytest.skip(f"External Verda benchmark-v2 bundle not synced ({bdir}); code-only deployment scope")
    assert bdir.is_dir(), f"Missing evidence bundle directory: {bdir}"

    blind_candidates = [bdir / "blind_seeds.json", *bdir.rglob("blind_seeds.json")]
    blind_files = [p for p in blind_candidates if p.is_file()]
    assert blind_files, f"Missing blind_seeds.json in {bdir}"
    blind_seeds_path = blind_files[0]
    blind_seeds = json.loads(blind_seeds_path.read_text(encoding="utf-8"))

    metrics_candidates = [bdir / "training_metrics.jsonl", *bdir.rglob("training_metrics.jsonl")]
    metrics_files = [p for p in metrics_candidates if p.is_file()]

    json_docs: list[tuple[Path, Any]] = []
    for jf in sorted(bdir.rglob("*.json")):
        if jf.name == "blind_seeds.json":
            continue
        try:
            json_docs.append((jf, json.loads(jf.read_text(encoding="utf-8"))))
        except Exception:
            continue

    text_docs: list[tuple[Path, str]] = []
    for tf in sorted(bdir.rglob("*")):
        if tf.is_file() and (tf.suffix.lower() in (".sha256", ".txt", ".md") or "sha256" in tf.name.lower()):
            try:
                text_docs.append((tf, tf.read_text(encoding="utf-8", errors="ignore")))
            except Exception:
                continue

    runs_by_role: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_dirs: set[Path] = set()

    for sub in sorted(bdir.rglob("submission.json")):
        root_trial = sub.parent.parent if sub.parent.name == "artifacts" else sub.parent
        if root_trial in seen_dirs:
            continue
        seen_dirs.add(root_trial)
        rel = root_trial.relative_to(bdir).as_posix() if root_trial != bdir else sub.relative_to(bdir).as_posix()
        role = _classify_evidence_role(rel)
        ev_file = next(
            (
                cand
                for cand in (
                    root_trial / "verifier" / "evaluation.json",
                    root_trial / "evaluation.json",
                    sub.parent / "evaluation.json",
                )
                if cand.is_file()
            ),
            None,
        )
        rw_file = next(
            (
                cand
                for cand in (
                    root_trial / "verifier" / "reward.txt",
                    root_trial / "reward.txt",
                    sub.parent / "reward.txt",
                )
                if cand.is_file()
            ),
            None,
        )
        rec = {
            "label": rel,
            "submission_path": sub,
            "evaluation_path": ev_file,
            "reward_path": rw_file,
        }
        if role:
            runs_by_role[role].append(rec)

    for rw in sorted(bdir.rglob("reward.txt")):
        root_trial = rw.parent.parent if rw.parent.name == "verifier" else rw.parent
        if root_trial in seen_dirs:
            continue
        seen_dirs.add(root_trial)
        sub_file = next(
            (
                cand
                for cand in (
                    root_trial / "artifacts" / "submission.json",
                    root_trial / "submission.json",
                    rw.parent / "submission.json",
                )
                if cand.is_file()
            ),
            None,
        )
        ev_file = next(
            (
                cand
                for cand in (
                    rw.with_name("evaluation.json"),
                    root_trial / "verifier" / "evaluation.json",
                    root_trial / "evaluation.json",
                )
                if cand.is_file()
            ),
            None,
        )
        rel = root_trial.relative_to(bdir).as_posix() if root_trial != bdir else rw.relative_to(bdir).as_posix()
        role = _classify_evidence_role(rel)
        rec = {
            "label": rel,
            "submission_path": sub_file,
            "evaluation_path": ev_file,
            "reward_path": rw,
        }
        if role:
            runs_by_role[role].append(rec)

    return {
        "bundle_dir": bdir,
        "blind_seeds_path": blind_seeds_path,
        "blind_seeds": blind_seeds,
        "training_metrics_path": metrics_files[0] if metrics_files else None,
        "json_docs": json_docs,
        "text_docs": text_docs,
        "runs_by_role": runs_by_role,
    }
