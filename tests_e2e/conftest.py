"""Session-scoped read-only fixtures and isolated sandbox helpers for the 4 Horses v02 E2E Suite."""

from __future__ import annotations

import os
import sys

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import time
from typing import Any, Iterator
import urllib.error
import urllib.request

import pytest

TESTS_E2E_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_E2E_DIR.parent
V02_DIR = REPO_ROOT / "4_Horses_Environment_v02"
STUDIO_DIR = REPO_ROOT / "studio"
HELPERS_DIR = TESTS_E2E_DIR / "helpers"

for _p in (str(REPO_ROOT / "src"), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tests_e2e.helpers.chain_validator import validate_workshop_chain  # noqa: E402

REQUIRED_9_V1_RUN_IDS = (
    "v1-manual-seed11",
    "v1-manual-seed29",
    "v1-manual-seed47",
    "v1-candidate-seed11",
    "v1-candidate-seed29",
    "v1-candidate-seed47",
    "v1-reference-seed11",
    "v1-reference-seed29",
    "v1-reference-seed47",
)


def build_e2e_env(repo_root: Path = REPO_ROOT) -> dict[str, str]:
    """Return environment dictionary with host binaries and PYTHONDONTWRITEBYTECODE=1."""
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.setdefault("BLENDER_BIN", "/Applications/Blender.app/Contents/MacOS/Blender")
    env.setdefault(
        "NODE_BIN",
        "/Users/musaka/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node",
    )
    env.setdefault(
        "PNPM_BIN",
        "/Users/musaka/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm",
    )
    env.setdefault("UV_BIN", "/Users/musaka/.local/bin/uv")
    env.setdefault("PYTHON_BIN", str(repo_root / ".venv" / "bin" / "python"))
    env.setdefault("CHROME_BIN", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

    extra_dirs = [
        str(Path(env["NODE_BIN"]).parent),
        str(Path(env["PNPM_BIN"]).parent),
        str(Path(env["UV_BIN"]).parent),
    ]
    cur_path = env.get("PATH", "")
    env["PATH"] = os.pathsep.join([p for p in extra_dirs if p] + ([cur_path] if cur_path else []))

    py_paths = [str(repo_root / "src"), str(repo_root)]
    if env.get("PYTHONPATH"):
        py_paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(py_paths)
    return env


def is_stage3_pack_station(station: dict[str, Any]) -> bool:
    """Contract-aligned Stage-3 matcher: id == 'pack' OR case-insensitive '03' and 'PACK' in label/name."""
    if not isinstance(station, dict):
        return False
    if station.get("id") == "pack":
        return True
    text = f"{station.get('label', '')} {station.get('name', '')}".upper()
    return "03" in text and "PACK" in text


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def v02_dir(repo_root: Path) -> Path:
    return repo_root / "4_Horses_Environment_v02"


@pytest.fixture(scope="session")
def studio_dir(repo_root: Path) -> Path:
    return repo_root / "studio"


@pytest.fixture(scope="session")
def session_tmp_dir() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="4horses_e2e_session_") as tmp:
        yield Path(tmp)


@pytest.fixture(scope="session")
def exported_pack_report(repo_root: Path, session_tmp_dir: Path) -> dict[str, Any]:
    """Export the 3D replay pack once per session into session_tmp_dir / 'pack'."""
    pack_dir = session_tmp_dir / "pack"
    t0 = time.perf_counter()
    try:
        from scripts.export_3d_pack import export_pack

        index = export_pack(pack_dir, seeds=(11, 29, 47))
        runs = index.get("runs", []) if isinstance(index, dict) else []
        v1_ids = [r["id"] for r in runs if not r.get("mode") or r.get("mode") == "v1"]
        quarterly_ids = [r["id"] for r in runs if r.get("mode") == "quarterly"]
        v1_set = set(v1_ids)
        return {
            "ok": True,
            "pack_dir": pack_dir,
            "elapsed_s": round(time.perf_counter() - t0, 4),
            "index": index,
            "total_runs": len(runs),
            "v1_run_ids": v1_ids,
            "quarterly_run_ids": quarterly_ids,
            "all_9_v1_present": all(rid in v1_set for rid in REQUIRED_9_V1_RUN_IDS),
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "pack_dir": pack_dir,
            "elapsed_s": round(time.perf_counter() - t0, 4),
            "index": None,
            "total_runs": 0,
            "v1_run_ids": [],
            "quarterly_run_ids": [],
            "all_9_v1_present": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


@pytest.fixture(scope="session")
def exported_pack_dir(exported_pack_report: dict[str, Any]) -> Path:
    return Path(exported_pack_report["pack_dir"])


def _run_blender_probe_sync(repo_root: Path, v02_dir: Path, session_tmp_dir: Path) -> dict[str, Any]:
    env = build_e2e_env(repo_root)
    blender_bin = Path(env["BLENDER_BIN"])
    blend_path = v02_dir / "warehouse_environment.blend"
    out_json = session_tmp_dir / "blender_probe.json"

    if not blender_bin.exists():
        return {"exists": False, "ok": False, "error": f"BLENDER_BIN not found at {blender_bin}"}
    if not blend_path.exists():
        return {"exists": False, "ok": False, "error": f"Blend file missing at {blend_path}"}

    cmd = [
        str(blender_bin),
        "-b",
        str(blend_path),
        "--factory-startup",
        "--python",
        str(HELPERS_DIR / "blender_probe.py"),
        "--",
        "--out",
        str(out_json),
    ]
    completed = subprocess.run(
        cmd,
        cwd=str(session_tmp_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if not out_json.exists():
        return {
            "exists": True,
            "ok": False,
            "returncode": completed.returncode,
            "error": f"blender_probe produced no JSON (rc={completed.returncode}): {completed.stderr[-800:]}",
        }
    try:
        payload = json.loads(out_json.read_text(encoding="utf-8"))
        payload.setdefault("returncode", completed.returncode)
        return payload
    except Exception as exc:
        return {
            "exists": True,
            "ok": False,
            "returncode": completed.returncode,
            "error": f"Invalid blender_probe JSON: {exc}",
        }


def _run_node_probe_sync(
    repo_root: Path,
    exported_pack_dir: Path,
    session_tmp_dir: Path,
) -> dict[str, Any]:
    env = build_e2e_env(repo_root)
    node_bin = Path(env["NODE_BIN"])
    out_json = session_tmp_dir / "node_probe.json"

    if not node_bin.exists():
        return {"ok": False, "error": f"NODE_BIN not found at {node_bin}"}

    stress_bundle_dir = session_tmp_dir / "stress-seed137"
    if not (stress_bundle_dir / "manifest.json").exists():
        src_dir = str(repo_root / "src")
        if src_dir not in sys.path:
            sys.path.insert(0, src_dir)
        from robotization_bench import contracts, economics, engine, reporting, scenarios, validation

        world = contracts.load_world()
        stress_plan = validation.parse_plan(
            {
                "schema_version": 1,
                "robot": True,
                "trays": True,
                "route": "all",
                "workers": [[1], [2], [3], [4], [2, 3, 4]],
            },
            world,
        )
        stress_day = scenarios.generate(world, 137)
        stress_raw = engine.simulate(world, stress_plan, stress_day, trace=True)
        stress_econ = economics.calculate(world, stress_plan, stress_raw)
        reporting.export_shift_bundle(world, stress_plan, stress_day, stress_raw, stress_econ, stress_bundle_dir)

    cmd = [
        str(node_bin),
        str(HELPERS_DIR / "node_probe.mjs"),
        "--mode",
        "session",
        "--repo",
        str(repo_root),
        "--pack-dir",
        str(exported_pack_dir),
        "--extra-run-dir",
        str(stress_bundle_dir),
        "--out",
        str(out_json),
    ]
    completed = subprocess.run(
        cmd,
        cwd=str(session_tmp_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if not out_json.exists():
        return {
            "ok": False,
            "returncode": completed.returncode,
            "error": f"node_probe produced no JSON (rc={completed.returncode}): {completed.stderr[-800:]}",
        }
    try:
        payload = json.loads(out_json.read_text(encoding="utf-8"))
        payload.setdefault("returncode", completed.returncode)
        return payload
    except Exception as exc:
        return {
            "ok": False,
            "returncode": completed.returncode,
            "error": f"Invalid node_probe JSON: {exc}",
        }


def _run_core_pytest_sync(repo_root: Path, session_tmp_dir: Path) -> dict[str, Any]:
    env = build_e2e_env(repo_root)
    python_bin = env["PYTHON_BIN"]
    if not Path(python_bin).exists():
        python_bin = sys.executable

    core_cache = session_tmp_dir / "core_pytest_cache"
    core_test_files = [
        f
        for f in (
            "tests/test_cli.py",
            "tests/test_clock.py",
            "tests/test_economics.py",
            "tests/test_grading.py",
            "tests/test_invariants.py",
            "tests/test_mcp.py",
            "tests/test_packaging.py",
            "tests/test_scenarios.py",
            "tests/test_validation.py",
        )
        if (repo_root / f).exists()
    ]
    t0 = time.perf_counter()
    completed = subprocess.run(
        [
            python_bin,
            "-B",
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-o",
            f"cache_dir={core_cache}",
            "-q",
            *core_test_files,
        ],
        cwd=str(repo_root),
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    elapsed_s = round(time.perf_counter() - t0, 4)
    out = (completed.stdout or "") + "\n" + (completed.stderr or "")

    def _extract_count(label: str) -> int:
        m = re.search(rf"(\d+)\s+{label}\b", out)
        return int(m.group(1)) if m else 0

    passed = _extract_count("passed")
    failed = _extract_count("failed")
    errors = _extract_count("errors?")
    skipped = _extract_count("skipped")

    diff_proc = subprocess.run(
        ["git", "diff", "--exit-code", "HEAD", "--", "src/robotization_bench", "data/world_spec.json"],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    status_proc = subprocess.run(
        ["git", "status", "--porcelain", "--", "src/robotization_bench", "data/world_spec.json"],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    return {
        "ok": completed.returncode == 0 and passed >= 90 and failed == 0 and errors == 0 and diff_proc.returncode == 0,
        "exitcode": completed.returncode,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
        "elapsed_s": elapsed_s,
        "stdout_tail": out.strip()[-1200:],
        "frozen_core_git_diff_rc": diff_proc.returncode,
        "frozen_core_git_diff": diff_proc.stdout.strip(),
        "frozen_core_git_status": status_proc.stdout.strip(),
    }


@pytest.fixture(scope="session")
def _parallel_session_probes(
    repo_root: Path,
    v02_dir: Path,
    exported_pack_dir: Path,
    session_tmp_dir: Path,
) -> dict[str, dict[str, Any]]:
    """Run read-only Blender, Node, and core pytest session probes concurrently in temp dirs."""
    with ThreadPoolExecutor(max_workers=3) as pool:
        fut_blender = pool.submit(_run_blender_probe_sync, repo_root, v02_dir, session_tmp_dir)
        fut_node = pool.submit(_run_node_probe_sync, repo_root, exported_pack_dir, session_tmp_dir)
        fut_core = pool.submit(_run_core_pytest_sync, repo_root, session_tmp_dir)
        return {
            "blender": fut_blender.result(),
            "node": fut_node.result(),
            "core_pytest": fut_core.result(),
        }


@pytest.fixture(scope="session")
def blender_probe(_parallel_session_probes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Run headless Blender 5.2.3 LTS geometry/BVH/camera probe once per session."""
    return _parallel_session_probes["blender"]


@pytest.fixture(scope="session")
def node_probe(_parallel_session_probes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Run headless Node v24 session probe once per session across all 15 GLBs, studio, and replays."""
    return _parallel_session_probes["node"]


def _load_json_entry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "exists": False,
            "ok": False,
            "path": str(path),
            "bytes": None,
            "sha256": None,
            "data": None,
            "error": f"Missing file: {path}",
        }
    try:
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
        return {
            "exists": True,
            "ok": True,
            "path": str(path),
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "data": data,
            "error": None,
        }
    except Exception as exc:
        return {
            "exists": True,
            "ok": False,
            "path": str(path),
            "bytes": None,
            "sha256": None,
            "data": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


@pytest.fixture(scope="session")
def v02_configs(repo_root: Path, v02_dir: Path, studio_dir: Path) -> dict[str, Any]:
    """Load and parse all v02, studio, and core JSON contracts (never raising on missing files)."""
    spec_paths = {
        "workshop_chain": v02_dir / "workshop_chain.json",
        "environment_config": v02_dir / "environment_config.json",
        "config_environment": v02_dir / "config" / "environment.json",
        "visual_bindings": v02_dir / "visual_bindings.json",
        "config_visual_bindings": v02_dir / "config" / "visual_bindings.json",
        "anchors": v02_dir / "anchors.json",
        "worker_manifest": v02_dir / "worker_manifest.json",
        "robot_manifest": v02_dir / "robot_manifest.json",
        "asset_manifest": v02_dir / "asset_manifest.json",
        "asset_stats_v02": v02_dir / "asset_stats_v02.json",
        "studio_asset_hashes": studio_dir / "asset-hashes.json",
        "v02_package_json": v02_dir / "package.json",
        "studio_package_json": studio_dir / "package.json",
        "world_spec": repo_root / "data" / "world_spec.json",
    }
    files = {k: _load_json_entry(p) for k, p in spec_paths.items()}
    result: dict[str, Any] = {
        "files": files,
        **{k: v["data"] for k, v in files.items()},
    }

    # Helper summary for Stage-3 Pack station label compatibility ('03 / PACK' or '03 / PACK (MANUAL + AUTO SLOT)')
    stage3_matches: dict[str, dict[str, Any] | None] = {}
    for cfg_key in ("environment_config", "config_environment"):
        cfg_data = result.get(cfg_key)
        stations = cfg_data.get("stations", []) if isinstance(cfg_data, dict) else []
        matched = next((s for s in stations if is_stage3_pack_station(s)), None)
        stage3_matches[cfg_key] = matched
    result["stage3_pack_station"] = stage3_matches
    return result


@pytest.fixture(scope="session")
def chain_report(
    v02_configs: dict[str, Any],
    blender_probe: dict[str, Any],
    node_probe: dict[str, Any],
) -> dict[str, Any]:
    """Validate workshop_chain.json against live GLB/Blender scene nodes, bindings, and character clips."""
    chain_entry = v02_configs["files"]["workshop_chain"]
    bindings_entry = v02_configs["files"]["visual_bindings"]
    if not chain_entry["ok"]:
        return {
            "exists": chain_entry["exists"],
            "ok": False,
            "errors": [chain_entry["error"] or "workshop_chain.json missing or invalid"],
            "scene_nodes": [],
            "worker_clips": [],
            "robot_clips": [],
        }
    if not bindings_entry["ok"]:
        return {
            "exists": True,
            "ok": False,
            "errors": [bindings_entry["error"] or "visual_bindings.json missing or invalid"],
            "scene_nodes": [],
            "worker_clips": [],
            "robot_clips": [],
        }

    scene_nodes: set[str] = set()
    for n in blender_probe.get("all_object_names") or []:
        if n:
            scene_nodes.add(n)
    for c in blender_probe.get("all_collection_names") or []:
        if c:
            scene_nodes.add(c)

    gltf_val = node_probe.get("gltfValidation") or {}
    for glb_key in ("warehouse_environment.glb", "modules/visual_layout.glb", "modules/visual_support.glb"):
        info = gltf_val.get(glb_key) or {}
        for n in info.get("rawNodeNames") or []:
            if n:
                scene_nodes.add(n)
        for n in info.get("threeNodeNames") or []:
            if n:
                scene_nodes.add(n)

    worker_clips = set((gltf_val.get("modules/warehouse_worker.glb") or {}).get("clipNames") or [])
    robot_clips = set((gltf_val.get("modules/humanoid_robot.glb") or {}).get("clipNames") or [])

    errors = validate_workshop_chain(
        chain_entry["data"],
        bindings_entry["data"],
        scene_nodes,
        worker_clips,
        robot_clips,
    )
    return {
        "exists": True,
        "ok": len(errors) == 0,
        "errors": errors,
        "scene_nodes": sorted(scene_nodes),
        "worker_clips": sorted(worker_clips),
        "robot_clips": sorted(robot_clips),
    }


@pytest.fixture(scope="session")
def core_pytest_report(_parallel_session_probes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Run core Python benchmark pytest suite + frozen-core git diff/status checks once per session."""
    return _parallel_session_probes["core_pytest"]


@pytest.fixture(scope="session")
def run_custom_glb_probe(repo_root: Path, session_tmp_dir: Path):
    """Callable helper running node_probe.mjs on an arbitrary or mutated GLB in a temp directory."""
    env = build_e2e_env(repo_root)
    node_bin = env["NODE_BIN"]
    counter = 0

    def _runner(
        glb_path: Path | str,
        *,
        mode: str = "probe-custom-glb",
        kind: str = "worker",
    ) -> dict[str, Any]:
        nonlocal counter
        counter += 1
        out_json = session_tmp_dir / f"custom_glb_probe_{counter}.json"
        cmd = [
            node_bin,
            str(HELPERS_DIR / "node_probe.mjs"),
            "--mode",
            mode,
            "--repo",
            str(repo_root),
            "--glb",
            str(glb_path),
            "--kind",
            kind,
            "--out",
            str(out_json),
        ]
        comp = subprocess.run(
            cmd,
            cwd=str(session_tmp_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        if not out_json.exists():
            return {
                "ok": False,
                "returncode": comp.returncode,
                "error": comp.stderr[-600:],
            }
        data = json.loads(out_json.read_text(encoding="utf-8"))
        data.setdefault("returncode", comp.returncode)
        return data

    return _runner


@pytest.fixture(scope="session")
def run_custom_replay_probe(repo_root: Path, session_tmp_dir: Path):
    """Callable helper running node_probe.mjs --mode replay-check against a custom run_dir or http_url."""
    env = build_e2e_env(repo_root)
    node_bin = env["NODE_BIN"]
    counter = 0

    def _runner(
        *,
        run_dir: Path | str | None = None,
        http_url: str | None = None,
    ) -> dict[str, Any]:
        nonlocal counter
        counter += 1
        out_json = session_tmp_dir / f"custom_replay_probe_{counter}.json"
        cmd = [
            node_bin,
            str(HELPERS_DIR / "node_probe.mjs"),
            "--mode",
            "replay-check",
            "--repo",
            str(repo_root),
            "--out",
            str(out_json),
        ]
        if run_dir is not None:
            cmd.extend(["--run-dir", str(run_dir)])
        if http_url is not None:
            cmd.extend(["--http-url", str(http_url)])
        comp = subprocess.run(
            cmd,
            cwd=str(session_tmp_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if not out_json.exists():
            return {
                "ok": False,
                "returncode": comp.returncode,
                "error": comp.stderr[-600:],
            }
        data = json.loads(out_json.read_text(encoding="utf-8"))
        data.setdefault("returncode", comp.returncode)
        return data

    return _runner


@pytest.fixture(scope="session")
def run_v02_npm_test_sandbox(repo_root: Path, v02_dir: Path, session_tmp_dir: Path):
    """Run 4_Horses_Environment_v02/scripts/check_v02.mjs in an isolated temp sandbox (zero repo writes)."""
    env = build_e2e_env(repo_root)
    node_bin = env["NODE_BIN"]
    counter = 0
    cached_default_result: dict[str, Any] | None = None

    def _runner(sandbox_dir: Path | None = None) -> dict[str, Any]:
        nonlocal counter, cached_default_result
        if sandbox_dir is None and cached_default_result is not None:
            return cached_default_result
        counter += 1
        sb = Path(sandbox_dir) if sandbox_dir is not None else (session_tmp_dir / f"v02_sandbox_{counter}")
        sb.mkdir(parents=True, exist_ok=True)

        # Copy package.json and scripts/*.mjs as REAL files so import.meta.url resolves inside sb,
        # ensuring v02_runtime_check.json is written strictly inside sb and NEVER inside the repo!
        shutil.copy2(v02_dir / "package.json", sb / "package.json")
        sb_scripts = sb / "scripts"
        sb_scripts.mkdir(parents=True, exist_ok=True)
        src_scripts = v02_dir / "scripts"
        if src_scripts.exists():
            for item in src_scripts.iterdir():
                if item.is_file():
                    shutil.copy2(item, sb_scripts / item.name)

        for entry in v02_dir.iterdir():
            if entry.name in ("package.json", "scripts", "v02_runtime_check.json"):
                continue
            dest = sb / entry.name
            if not dest.exists() and not dest.is_symlink():
                dest.symlink_to(entry)

        comp = subprocess.run(
            [node_bin, "scripts/check_v02.mjs"],
            cwd=str(sb),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        rc_json_path = sb / "v02_runtime_check.json"
        rc_data = (
            json.loads(rc_json_path.read_text(encoding="utf-8"))
            if rc_json_path.exists()
            else None
        )
        res = {
            "ok": comp.returncode == 0 and rc_data is not None,
            "returncode": comp.returncode,
            "stdout": comp.stdout,
            "stderr": comp.stderr,
            "runtime_check": rc_data,
            "sandbox_dir": str(sb),
        }
        if sandbox_dir is None:
            cached_default_result = res
        return res

    return _runner


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="session")
def ephemeral_serve_3d(repo_root: Path, exported_pack_dir: Path, session_tmp_dir: Path):
    """Context-manager factory launching scripts/serve_3d.py on an ephemeral port against temp pack."""
    env = build_e2e_env(repo_root)
    python_bin = env["PYTHON_BIN"]
    if not Path(python_bin).exists():
        python_bin = sys.executable

    @contextmanager
    def _serve(
        pack_dir: Path | None = None,
        *,
        host: str = "127.0.0.1",
    ) -> Iterator[dict[str, Any]]:
        target_pack = Path(pack_dir) if pack_dir is not None else exported_pack_dir
        port = _pick_free_port()
        cmd = [
            python_bin,
            "-B",
            str(repo_root / "scripts" / "serve_3d.py"),
            "--dir",
            str(target_pack),
            "--host",
            host,
            "--port",
            str(port),
        ]

        proc = subprocess.Popen(
            cmd,
            cwd=str(session_tmp_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        base_url = f"http://{host}:{port}"
        pack_url = f"{base_url}/"
        index_url = f"{base_url}/index.json"
        ready = False
        last_err = None
        deadline = time.perf_counter() + 8.0
        while time.perf_counter() < deadline:
            if proc.poll() is not None:
                break
            try:
                with urllib.request.urlopen(index_url, timeout=0.5) as resp:
                    if resp.status == 200:
                        ready = True
                        break
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last_err = str(exc)
                time.sleep(0.05)

        stderr_tail = ""
        if not ready and proc.poll() is not None and proc.stderr is not None:
            try:
                stderr_tail = proc.stderr.read()[-500:]
            except Exception:
                stderr_tail = ""

        try:
            yield {
                "ready": ready,
                "host": host,
                "port": port,
                "base_url": base_url,
                "pack_url": pack_url,
                "index_url": index_url,
                "returncode": proc.poll(),
                "error": None if ready else (stderr_tail or last_err or "serve_3d failed to become ready"),
            }
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2.0)

    return _serve
