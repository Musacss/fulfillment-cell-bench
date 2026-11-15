"""Verify zero-whitebox Harbor packaging, Dockerfile/C security invariants, and isolated black-box E2E."""

from fractions import Fraction
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import tomllib

import pytest

from robotization_bench.contracts import ROOT, load_world
from robotization_bench.episode import _sanitize_public_world


EXPECTED_PUBLIC_ALLOWLIST = {
    "AGENT.md",
    "opencode.json",
    ".mcp.json",
    "docs/SPEC.md",
    "docs/CONTRACTS.md",
    "data/world_spec.json",
    "data/plans/manual.json",
    "data/development/11.json",
    "data/development/29.json",
    "data/development/47.json",
    "src/robotization_bench/__init__.py",
    "src/robotization_bench/mcp_proxy.py",
}

FORBIDDEN_PUBLIC_FILENAMES = {
    "engine.py",
    "scenarios.py",
    "quarterly.py",
    "economics.py",
    "grading.py",
    "validation.py",
    "contracts.py",
    "episode.py",
    "mcp_server.py",
    "verifier.py",
    "reference.py",
    "seeds.json",
    "state.json",
}


@pytest.fixture
def short_sock_dir():
    with tempfile.TemporaryDirectory(prefix="/tmp/m2p_") as d:
        yield Path(d)


def _wait_sock(sock_path: Path, proc: subprocess.Popen, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            err = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
            raise RuntimeError(f"daemon exited early ({proc.returncode}): {err}")
        if sock_path.exists():
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(0.5)
                    s.connect(str(sock_path))
                return
            except OSError:
                pass
        time.sleep(0.03)
    raise TimeoutError(f"Timed out waiting for {sock_path}")


def test_prepare_harbor_overwrite_and_seed_disjointness(tmp_path):
    task = tmp_path / "task"
    seeds = tmp_path / "seeds.json"
    seeds.write_text("[37281939]\n", encoding="utf-8")

    # 1. Initial creation succeeds
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/prepare_harbor.py"), "--out", str(task), "--seeds-file", str(seeds)],
        check=True,
    )
    marker = task / "stale_marker.txt"
    marker.write_text("stale", encoding="utf-8")

    # 2. Re-running without --overwrite MUST fail cleanly
    failed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/prepare_harbor.py"), "--out", str(task), "--seeds-file", str(seeds)],
        capture_output=True,
        text=True,
    )
    assert failed.returncode != 0

    # 3. Re-running with --overwrite succeeds and removes stale files
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/prepare_harbor.py"),
            "--out",
            str(task),
            "--seeds-file",
            str(seeds),
            "--overwrite",
        ],
        check=True,
    )
    assert not marker.exists()

    # 4. Overlapping development seed (11) MUST fail
    bad_seeds = tmp_path / "bad_seeds.json"
    bad_seeds.write_text("[11, 37281939]\n", encoding="utf-8")
    overlap = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/prepare_harbor.py"),
            "--out",
            str(tmp_path / "bad_task"),
            "--seeds-file",
            str(bad_seeds),
        ],
        capture_output=True,
        text=True,
    )
    assert overlap.returncode != 0


def _audit_task_bundle(task_dir: Path) -> None:
    public = task_dir / "environment/public"
    actual_public = {p.relative_to(public).as_posix() for p in public.rglob("*") if p.is_file()}
    assert actual_public == EXPECTED_PUBLIC_ALLOWLIST

    for p in public.rglob("*"):
        assert p.name not in FORBIDDEN_PUBLIC_FILENAMES

    # Sanitized public world_spec.json check
    public_world = json.loads((public / "data/world_spec.json").read_text(encoding="utf-8"))
    assert public_world == _sanitize_public_world(load_world())

    # MCP discovery files in public/
    opencode_cfg = json.loads((public / "opencode.json").read_text(encoding="utf-8"))
    assert opencode_cfg["mcp"]["cell"] == {
        "type": "local",
        "command": ["python3", "-m", "robotization_bench.mcp_proxy", "--socket", "/run/bench/bench.sock"],
        "enabled": True,
        "environment": {"PYTHONPATH": "/app/src"},
    }
    mcp_cfg = json.loads((public / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp_cfg["mcpServers"]["cell"] == {
        "type": "stdio",
        "command": "python3",
        "args": ["-m", "robotization_bench.mcp_proxy", "--socket", "/run/bench/bench.sock"],
        "env": {"PYTHONPATH": "/app/src"},
    }

    # Verify quarterly module presence in private daemon, trusted verifier, and oracle solution
    assert (task_dir / "environment/daemon/src/robotization_bench/quarterly.py").is_file()
    assert (task_dir / "environment/daemon/src/robotization_bench/mcp_server.py").is_file()
    assert (task_dir / "environment/daemon/data/world_spec.json").is_file()
    assert (task_dir / "environment/daemon/docs/SPEC.md").is_file()

    assert (task_dir / "tests/trusted/src/robotization_bench/quarterly.py").is_file()
    assert (task_dir / "tests/trusted/src/robotization_bench/verifier.py").is_file()
    prov = json.loads((task_dir / "tests/provenance.json").read_text(encoding="utf-8"))
    assert prov["schema_version"] == 2

    assert (task_dir / "solution/src/robotization_bench/quarterly.py").is_file()
    assert (task_dir / "solution/src/robotization_bench/reference.py").is_file()
    assert (task_dir / "solution/src/robotization_bench/mcp_proxy.py").is_file()
    assert os.access(task_dir / "solution/solve.sh", os.X_OK)
    assert os.access(task_dir / "tests/test.sh", os.X_OK)


def test_public_allowlist_forbidlist_and_materialized_task(tmp_path):
    # Audit fresh staged task
    staged = tmp_path / "task"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/prepare_harbor.py"),
            "--out",
            str(staged),
            "--seeds-file",
            str(ROOT / "evidence/replay_seeds.json"),
        ],
        check=True,
    )
    _audit_task_bundle(staged)

    # Audit committed materialized ./tasks/fulfillment-cell-bench/
    materialized = ROOT / "tasks/fulfillment-cell-bench"
    assert materialized.is_dir(), "tasks/fulfillment-cell-bench must be materialized in repository"
    _audit_task_bundle(materialized)
    assert json.loads((materialized / "tests/seeds.json").read_text(encoding="utf-8")) == json.loads(
        (ROOT / "evidence/replay_seeds.json").read_text(encoding="utf-8")
    )

    # Verify .gitignore rules
    gitignore_lines = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    assert ".env" in gitignore_lines
    assert ".env.*" in gitignore_lines
    assert ".worktrees/" in gitignore_lines
    assert "tasks/" not in gitignore_lines
    assert "tasks/fulfillment-cell-bench/" not in gitignore_lines


def test_dockerfile_c_launcher_and_task_toml_security_invariants(tmp_path):
    for idx, base in enumerate((ROOT / "integration/harbor", ROOT / "tasks/fulfillment-cell-bench")):
        dockerfile = (base / "environment/Dockerfile").read_text(encoding="utf-8")
        reqs = (base / "environment/requirements.txt").read_text(encoding="utf-8")
        c_path = base / "environment/bench_daemon_start.c"
        c_src = c_path.read_text(encoding="utf-8")
        task_cfg = tomllib.loads((base / "task.toml").read_text(encoding="utf-8"))

        # Multi-stage build & Verda OpenCode 1.19.5 wrapper checks
        assert "AS builder" in dockerfile
        for pkg in ("git", "curl", "ca-certificates", "bash", "coreutils"):
            assert pkg in dockerfile
        assert "COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node" in dockerfile
        assert "COPY --from=node:22-bookworm-slim /usr/local/lib/node_modules /usr/local/lib/node_modules" in dockerfile
        assert "npm install -g opencode-ai@1.19.5" in dockerfile
        assert "GOOGLE_GENERATIVE_AI_API_KEY" in dockerfile
        assert "/usr/local/bin/opencode-bin" in dockerfile
        assert "mcp==1.30.0" in reqs

        # Privilege separation & bench_daemon.pth checks
        assert "/usr/local/lib/python3.12/site-packages/bench_daemon.pth" in dockerfile
        assert "/srv/bench_daemon/src" in dockerfile
        assert "useradd -m -u 1000 -s /bin/bash agent" in dockerfile
        assert "0700" in dockerfile and "/srv/bench_daemon" in dockerfile
        assert "04755" in dockerfile and "/usr/local/bin/bench-daemon-start" in dockerfile
        assert "0777" not in dockerfile
        assert "chown root:root /logs /logs/artifacts /run/bench" in dockerfile
        assert "chmod 0755 /logs /logs/artifacts /run/bench" in dockerfile
        assert "chown -R agent:agent /home/agent /app /logs/agent" in dockerfile
        for ln in dockerfile.splitlines():
            stripped = ln.strip()
            if "chown" in stripped and "agent:agent" in stripped:
                tokens = stripped.replace("\\", " ").split()
                assert "/logs" not in tokens, f"Dockerfile must never chown /logs to agent: {stripped}"
                assert "/logs/artifacts" not in tokens, f"Dockerfile must never chown /logs/artifacts to agent: {stripped}"
        assert "HOME=/home/agent" in dockerfile

        user_lines = [
            ln.strip()
            for ln in dockerfile.splitlines()
            if ln.strip() and not ln.strip().startswith("#") and ln.strip().upper().startswith("USER ")
        ]
        assert user_lines and user_lines[-1] == "USER agent"

        # C launcher security invariants
        first_include_pos = c_src.index("#include")
        assert c_src.index("#define _GNU_SOURCE") < first_include_pos
        assert "argc != 1" in c_src
        assert "argc > 1" not in c_src
        assert "0777" not in c_src
        assert 'ensure_dir("/logs", 0755)' in c_src
        assert 'ensure_dir("/logs/artifacts", 0755)' in c_src
        assert "O_DIRECTORY" in c_src and "O_NOFOLLOW" in c_src
        assert "fchown(" in c_src and "fchmod(" in c_src
        assert "S_ISLNK(" in c_src and "S_ISDIR(" in c_src
        assert "setresgid(0, 0, 0)" in c_src
        assert "setresuid(0, 0, 0)" in c_src
        assert "clearenv()" in c_src
        assert "O_CLOEXEC" in c_src
        assert "flock(" in c_src and "LOCK_EX" in c_src
        assert '"/usr/local/bin/python3"' in c_src
        assert '"-I"' in c_src
        assert '"robotization_bench.mcp_server"' in c_src
        assert '"/srv/bench_daemon/state.json"' in c_src

        if shutil.which("cc"):
            compiled_bin = tmp_path / f"bench-daemon-start-{idx}"
            subprocess.run(
                ["cc", "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror", str(c_path), "-o", str(compiled_bin)],
                check=True,
            )
            bad_argc = subprocess.run([str(compiled_bin), "--unexpected"], capture_output=True, text=True)
            assert bad_argc.returncode == 2

        # task.toml invariants
        assert task_cfg["schema_version"] == "1.4"
        assert task_cfg["verifier"]["environment_mode"] == "separate"
        assert task_cfg["verifier"]["environment"]["network_mode"] == "no-network"
        mcp_srv = task_cfg["environment"]["mcp_servers"][0]
        assert mcp_srv["name"] == "cell"
        assert mcp_srv["transport"] == "stdio"
        assert mcp_srv["command"] == "python3"
        assert mcp_srv["args"] == ["/app/src/robotization_bench/mcp_proxy.py", "--socket", "/run/bench/bench.sock"]


def test_blackbox_e2e_daemon_oracle_verifier_and_zero_baselines(tmp_path, short_sock_dir):
    task = tmp_path / "task"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/prepare_harbor.py"),
            "--out",
            str(task),
            "--seeds-file",
            str(ROOT / "evidence/replay_seeds.json"),
        ],
        check=True,
    )

    daemon_src = task / "environment/daemon/src"
    public_src = task / "environment/public/src"
    solution_dir = task / "solution"
    tests_dir = task / "tests"

    def run_grade(submission_path: Path, verdict_dir: Path, *, mode: str | None = None) -> tuple[dict, float]:
        env = {"PATH": os.environ.get("PATH", ""), "BENCH_SUBMISSION": str(submission_path), "BENCH_VERIFIER_DIR": str(verdict_dir)}
        if mode is not None:
            env["BENCH_MODE"] = mode
        subprocess.run([sys.executable, "-I", "-B", str(tests_dir / "grade.py")], check=True, cwd=tmp_path, env=env)
        ev = json.loads((verdict_dir / "evaluation.json").read_text(encoding="utf-8"))["evaluation"]
        reward_txt = float((verdict_dir / "reward.txt").read_text(encoding="utf-8").strip())
        return ev, reward_txt

    # 1. Quarterly E2E: daemon -> unprivileged oracle.py -> airgapped grade.py
    q_sock = short_sock_dir / "q.sock"
    q_state = tmp_path / "q_state.json"
    q_sub = tmp_path / "q_submission.json"
    q_log = tmp_path / "q_episode.json"

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "robotization_bench.mcp_server",
            "--mode",
            "quarterly",
            "--socket",
            str(q_sock),
            "--state",
            str(q_state),
            "--submission",
            str(q_sub),
            "--log",
            str(q_log),
        ],
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(daemon_src)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_sock(q_sock, proc)
        # Run oracle.py with ONLY solution/src + public/src on PYTHONPATH (ZERO daemon access!)
        oracle_env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": f"{solution_dir / 'src'}{os.pathsep}{public_src}",
            "BENCH_SOCKET": str(q_sock),
        }
        subprocess.run([sys.executable, str(solution_dir / "oracle.py")], check=True, env=oracle_env, cwd=tmp_path)
    finally:
        proc.terminate()
        proc.wait(timeout=5)

    ev_q, reward_q = run_grade(q_sub, tmp_path / "verdict_q")
    assert ev_q["valid"] is True
    assert ev_q["feasible"] is True
    assert ev_q["win"] is True
    exact_q = Fraction(ev_q["reward_num"], ev_q["reward_den"])
    assert exact_q > Fraction(35, 100)
    assert reward_q == pytest.approx(float(exact_q), abs=1e-12)

    # Poison public mcp_proxy to verify grade.py never touches environment/public
    (public_src / "robotization_bench/mcp_proxy.py").write_text("raise AssertionError('public imported')\n")
    ev_q2, _ = run_grade(q_sub, tmp_path / "verdict_q2")
    assert ev_q2 == ev_q

    # Restore clean public/src for remaining runs
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/prepare_harbor.py"),
            "--out",
            str(task),
            "--seeds-file",
            str(ROOT / "evidence/replay_seeds.json"),
            "--overwrite",
        ],
        check=True,
    )

    # 2. nop baseline (fresh daemon initialized submission.json -> null, zero agent actions)
    nop_sock = short_sock_dir / "nop.sock"
    nop_sub = tmp_path / "nop_sub.json"
    nop_log = tmp_path / "nop_log.json"
    proc_nop = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "robotization_bench.mcp_server",
            "--mode",
            "quarterly",
            "--socket",
            str(nop_sock),
            "--submission",
            str(nop_sub),
            "--log",
            str(nop_log),
        ],
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(daemon_src)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_sock(nop_sock, proc_nop)
    finally:
        proc_nop.terminate()
        proc_nop.wait(timeout=5)
    ev_nop, reward_nop = run_grade(nop_sub, tmp_path / "verdict_nop")
    assert ev_nop["valid"] is False and ev_nop["reward_num"] == 0 and reward_nop == 0.0

    # 3. stop_early baseline (agent connects via SocketEpisodeClient and calls stop())
    stop_sock = short_sock_dir / "stop.sock"
    stop_sub = tmp_path / "stop_sub.json"
    stop_log = tmp_path / "stop_log.json"
    proc_stop = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "robotization_bench.mcp_server",
            "--mode",
            "quarterly",
            "--socket",
            str(stop_sock),
            "--submission",
            str(stop_sub),
            "--log",
            str(stop_log),
        ],
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(daemon_src)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_sock(stop_sock, proc_stop)
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import os; from robotization_bench.mcp_proxy import SocketEpisodeClient; SocketEpisodeClient().stop()",
            ],
            check=True,
            env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(public_src), "BENCH_SOCKET": str(stop_sock)},
        )
    finally:
        proc_stop.terminate()
        proc_stop.wait(timeout=5)
    ev_stop, reward_stop = run_grade(stop_sub, tmp_path / "verdict_stop")
    assert ev_stop["valid"] is False and ev_stop["reward_num"] == 0 and reward_stop == 0.0

    # 4. v1 mode backward-compatible E2E: daemon (--mode v1) -> oracle.py -> grade.py
    v1_sock = short_sock_dir / "v1.sock"
    v1_sub = tmp_path / "v1_sub.json"
    v1_log = tmp_path / "v1_log.json"
    proc_v1 = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "robotization_bench.mcp_server",
            "--mode",
            "v1",
            "--socket",
            str(v1_sock),
            "--submission",
            str(v1_sub),
            "--log",
            str(v1_log),
        ],
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(daemon_src)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_sock(v1_sock, proc_v1)
        subprocess.run(
            [sys.executable, str(solution_dir / "oracle.py")],
            check=True,
            env={
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": f"{solution_dir / 'src'}{os.pathsep}{public_src}",
                "BENCH_SOCKET": str(v1_sock),
            },
            cwd=tmp_path,
        )
    finally:
        proc_v1.terminate()
        proc_v1.wait(timeout=5)
    ev_v1, reward_v1 = run_grade(v1_sub, tmp_path / "verdict_v1", mode="v1")
    assert ev_v1["valid"] is True and ev_v1["feasible"] is True and ev_v1["win"] is True
    assert reward_v1 > 0.20


def test_grade_py_rejects_v1_schema_downgrade_unless_explicit_bench_mode_v1(tmp_path):
    v1_exploit_plan = {
        "schema_version": 1,
        "robot": True,
        "trays": True,
        "route": "bypass",
        "workers": [[1], [2], [3], [4], [2, 3]],
    }
    sub_v1 = tmp_path / "exploit_v1_submission.json"
    sub_v1.write_text(json.dumps(v1_exploit_plan) + "\n", encoding="utf-8")

    staged = tmp_path / "staged_task"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/prepare_harbor.py"),
            "--out",
            str(staged),
            "--seeds-file",
            str(ROOT / "evidence/replay_seeds.json"),
        ],
        check=True,
    )

    for label, task_dir in (("staged", staged), ("materialized", ROOT / "tasks/fulfillment-cell-bench")):
        grade_py = task_dir / "tests/grade.py"

        # 1. Default grade.py (no BENCH_MODE env var) MUST reject schema_version=1 as InvalidPlan (0/1 = 0.0)
        out_default = tmp_path / f"{label}_default"
        subprocess.run(
            [sys.executable, "-I", "-B", str(grade_py)],
            check=True,
            cwd=tmp_path,
            env={
                "PATH": os.environ.get("PATH", ""),
                "BENCH_SUBMISSION": str(sub_v1),
                "BENCH_VERIFIER_DIR": str(out_default),
            },
        )
        ev_def = json.loads((out_default / "evaluation.json").read_text(encoding="utf-8"))["evaluation"]
        rew_def = float((out_default / "reward.txt").read_text(encoding="utf-8").strip())
        assert ev_def["valid"] is False
        assert ev_def["feasible"] is False
        assert ev_def["win"] is False
        assert ev_def["reward_num"] == 0 and ev_def["reward_den"] == 1
        assert rew_def == 0.0

        grade_src = grade_py.read_text(encoding="utf-8")
        assert "_detect_v1_submission" not in grade_src

        # 2. Explicit BENCH_MODE=v1 grades valid v1 plan via verify_file (win=True)
        out_v1 = tmp_path / f"{label}_v1"
        subprocess.run(
            [sys.executable, "-I", "-B", str(grade_py)],
            check=True,
            cwd=tmp_path,
            env={
                "PATH": os.environ.get("PATH", ""),
                "BENCH_SUBMISSION": str(sub_v1),
                "BENCH_VERIFIER_DIR": str(out_v1),
                "BENCH_MODE": "v1",
            },
        )
        ev_v1 = json.loads((out_v1 / "evaluation.json").read_text(encoding="utf-8"))["evaluation"]
        rew_v1 = float((out_v1 / "reward.txt").read_text(encoding="utf-8").strip())
        assert ev_v1["valid"] is True and ev_v1["feasible"] is True and ev_v1["win"] is True
        assert rew_v1 > 0.20

        # 3. Unknown BENCH_MODE is rejected cleanly with non-zero exit code
        out_bad = tmp_path / f"{label}_bad_mode"
        bad_run = subprocess.run(
            [sys.executable, "-I", "-B", str(grade_py)],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={
                "PATH": os.environ.get("PATH", ""),
                "BENCH_SUBMISSION": str(sub_v1),
                "BENCH_VERIFIER_DIR": str(out_bad),
                "BENCH_MODE": "auto",
            },
        )
        assert bad_run.returncode != 0


def test_oracle_uses_v2_reference_directly_once_m3_merges(tmp_path, short_sock_dir):
    task = tmp_path / "task"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/prepare_harbor.py"),
            "--out",
            str(task),
            "--seeds-file",
            str(ROOT / "evidence/replay_seeds.json"),
        ],
        check=True,
    )
    # Simulate post-M3 reference.py returning a schema_version=2 plan directly after 1 pilot
    (task / "solution/src/robotization_bench/reference.py").write_text(
        """
def solve(episode):
    obs = episode.observe()
    manual = obs["manual"]
    episode.pilot(manual, obs["development_seeds"][0])
    return manual
""",
        encoding="utf-8",
    )

    sock = short_sock_dir / "m3.sock"
    sub = tmp_path / "m3_sub.json"
    log = tmp_path / "m3_log.json"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "robotization_bench.mcp_server",
            "--mode",
            "quarterly",
            "--socket",
            str(sock),
            "--submission",
            str(sub),
            "--log",
            str(log),
        ],
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(task / "environment/daemon/src")},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_sock(sock, proc)
        subprocess.run(
            [str(task / "solution/solve.sh")],
            check=True,
            env={
                "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}",
                "PYTHONPATH": f"{task / 'solution/src'}{os.pathsep}{task / 'environment/public/src'}",
                "BENCH_SOCKET": str(sock),
            },
            cwd=tmp_path,
        )
    finally:
        proc.terminate()
        proc.wait(timeout=5)

    entries = json.loads(log.read_text(encoding="utf-8"))
    assert [e["action"] for e in entries] == ["observe", "pilot", "submit"]
    assert json.loads(sub.read_text(encoding="utf-8"))["schema_version"] == 2
