"""Stage an allowlisted Harbor task with privilege-separated black-box MCP isolation."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from robotization_bench.episode import _sanitize_public_world  # noqa: E402

CORE = ("__init__", "contracts", "scenarios", "validation", "economics", "engine", "quarterly", "grading")
PUBLIC = ("__init__", "mcp_proxy")
DAEMON = CORE + ("episode", "mcp_server")
TRUSTED = CORE + ("verifier",)
SOLUTION = CORE + ("mcp_proxy", "reference")

OPENCODE_CONFIG = {
    "$schema": "https://opencode.ai/config.json",
    "mcp": {
        "cell": {
            "type": "local",
            "command": ["python3", "-m", "robotization_bench.mcp_proxy", "--socket", "/run/bench/bench.sock"],
            "enabled": True,
            "environment": {"PYTHONPATH": "/app/src"},
        }
    },
}

MCP_JSON_CONFIG = {
    "mcpServers": {
        "cell": {
            "type": "stdio",
            "command": "python3",
            "args": ["-m", "robotization_bench.mcp_proxy", "--socket", "/run/bench/bench.sock"],
            "env": {"PYTHONPATH": "/app/src"},
        }
    }
}


def copy_file(src: Path, dest: Path, *, mode: int | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    if mode is not None:
        dest.chmod(mode)


def write_json(dest: Path, value: object, *, indent: int | None = 2) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=indent, ensure_ascii=True, allow_nan=False) + "\n"
    dest.write_text(text, encoding="utf-8")


def prepare(
    out: Path,
    seeds_file: Path,
    *,
    overwrite: bool = False,
    min_seeds: int | None = None,
    allow_short_seeds: bool = False,
) -> None:
    w = json.loads((ROOT / "data/world_spec.json").read_text(encoding="utf-8"))
    seeds = json.loads(seeds_file.read_text(encoding="utf-8"))
    canonical_out = (ROOT / "tasks" / "fulfillment-cell-bench").resolve()
    required_min = (
        1
        if allow_short_seeds
        else (min_seeds if min_seeds is not None else (3 if out.resolve() == canonical_out else 1))
    )
    if (
        type(seeds) is not list
        or len(seeds) < required_min
        or any(type(s) is not int for s in seeds)
        or len(set(seeds)) != len(seeds)
        or set(seeds) & set(w["development_seeds"])
    ):
        raise ValueError(
            f"use >= {required_min} distinct integer evaluation seeds, disjoint from public history"
        )

    if out.exists() or out.is_symlink():
        if not overwrite:
            raise FileExistsError(f"Output directory already exists: {out} (pass --overwrite to replace)")
        if out.is_symlink() or out.is_file():
            out.unlink()
        else:
            shutil.rmtree(out)

    out.mkdir(parents=True, exist_ok=False)
    template = ROOT / "integration" / "harbor"

    # 1. Task root & container build files
    copy_file(template / "task.toml", out / "task.toml")
    copy_file(ROOT / "AGENT.md", out / "instruction.md")
    copy_file(template / "environment/Dockerfile", out / "environment/Dockerfile")
    copy_file(template / "environment/requirements.txt", out / "environment/requirements.txt")
    copy_file(template / "environment/bench_daemon_start.c", out / "environment/bench_daemon_start.c")
    copy_file(template / "tests/Dockerfile", out / "tests/Dockerfile")
    copy_file(template / "tests/test.sh", out / "tests/test.sh", mode=0o755)
    copy_file(template / "tests/grade.py", out / "tests/grade.py")
    copy_file(template / "solution/solve.sh", out / "solution/solve.sh", mode=0o755)
    copy_file(template / "solution/oracle.py", out / "solution/oracle.py")

    # 2. Public agent workspace (/app) — strict allowlist, zero simulator/seed leakage
    public_dir = out / "environment/public"
    for mod in PUBLIC:
        rel = Path("src/robotization_bench") / f"{mod}.py"
        copy_file(ROOT / rel, public_dir / rel)
    sanitized_w = _sanitize_public_world(w)
    if sanitized_w == w:
        copy_file(ROOT / "data/world_spec.json", public_dir / "data/world_spec.json")
    else:
        write_json(public_dir / "data/world_spec.json", sanitized_w)
    copy_file(ROOT / "data/plans/manual.json", public_dir / "data/plans/manual.json")
    for seed in w["development_seeds"]:
        rel_dev = Path("data/development") / f"{seed}.json"
        copy_file(ROOT / rel_dev, public_dir / rel_dev)
    for doc in ("AGENT.md", "docs/SPEC.md", "docs/CONTRACTS.md"):
        copy_file(ROOT / doc, public_dir / doc)
    write_json(public_dir / "opencode.json", OPENCODE_CONFIG)
    write_json(public_dir / ".mcp.json", MCP_JSON_CONFIG)

    # 3. Private root-only daemon directory (/srv/bench_daemon, chmod 0700 in image)
    daemon_dir = out / "environment/daemon"
    for mod in DAEMON:
        rel = Path("src/robotization_bench") / f"{mod}.py"
        copy_file(ROOT / rel, daemon_dir / rel)
    for data_file in ("data/world_spec.json", "data/plans/manual.json", "docs/SPEC.md"):
        copy_file(ROOT / data_file, daemon_dir / data_file)

    # 4. Oracle-only solution directory (/solution, mounted by Harbor ONLY on --agent oracle)
    sol_dir = out / "solution"
    for mod in SOLUTION:
        rel = Path("src/robotization_bench") / f"{mod}.py"
        copy_file(ROOT / rel, sol_dir / rel)
    copy_file(ROOT / "src/robotization_bench/reference.py", sol_dir / "reference.py")
    for data_file in ("data/world_spec.json", "data/plans/manual.json", "docs/SPEC.md"):
        copy_file(ROOT / data_file, sol_dir / data_file)

    # 5. Isolated airgapped verifier directory (/tests)
    trusted_dir = out / "tests/trusted"
    for mod in TRUSTED:
        rel = Path("src/robotization_bench") / f"{mod}.py"
        copy_file(ROOT / rel, trusted_dir / rel)
    for data_file in ("data/world_spec.json", "data/plans/manual.json"):
        copy_file(ROOT / data_file, trusted_dir / data_file)

    write_json(out / "tests/seeds.json", seeds, indent=None)
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True)
    provenance = {
        "commit": commit.stdout.strip() or None,
        "world_sha256": hashlib.sha256((ROOT / "data/world_spec.json").read_bytes()).hexdigest(),
        "schema_version": 2,
        "harbor_checked_version": "0.26.0",
    }
    write_json(out / "tests/provenance.json", provenance)


def check_materialized(out: Path, seeds_file: Path) -> None:
    if not out.is_dir():
        raise FileNotFoundError(f"Materialized Harbor task directory not found: {out}")
    with tempfile.TemporaryDirectory(prefix="harbor_check_") as tmp:
        fresh = Path(tmp) / "task"
        prepare(fresh, seeds_file, overwrite=True, min_seeds=3)
        actual_files = {
            p.relative_to(out).as_posix()
            for p in out.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and not p.name.endswith((".pyc", ".pyo"))
        }
        expected_files = {p.relative_to(fresh).as_posix() for p in fresh.rglob("*") if p.is_file()}
        if actual_files != expected_files:
            missing = sorted(expected_files - actual_files)
            extra = sorted(actual_files - expected_files)
            raise ValueError(f"Harbor task file-set drift in {out}: missing={missing}, extra={extra}")
        for rel in sorted(expected_files):
            a_path = out / rel
            e_path = fresh / rel
            if rel == "tests/provenance.json":
                a_doc = json.loads(a_path.read_text(encoding="utf-8"))
                e_doc = json.loads(e_path.read_text(encoding="utf-8"))
                for key in ("world_sha256", "schema_version", "harbor_checked_version"):
                    if a_doc.get(key) != e_doc.get(key):
                        raise ValueError(f"Harbor provenance drift on {key}: {a_doc.get(key)!r} != {e_doc.get(key)!r}")
                continue
            if a_path.read_bytes() != e_path.read_bytes():
                raise ValueError(f"Harbor task content drift in {rel}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=None, help="Target Harbor task directory")
    ap.add_argument("--seeds-file", "--seeds", dest="seeds_file", type=Path, default=None)
    ap.add_argument("--overwrite", action="store_true", help="Replace existing output directory if present")
    ap.add_argument("--min-seeds", type=int, default=None, help="Minimum distinct evaluation seeds required")
    ap.add_argument("--allow-short-seeds", action="store_true", help="Allow <3 seeds even on canonical task dir")
    ap.add_argument("--check", action="store_true", help="Verify materialized Harbor task matches fresh build")
    args = ap.parse_args()
    if args.check:
        target_out = args.out if args.out is not None else (ROOT / "tasks" / "fulfillment-cell-bench")
        target_seeds = args.seeds_file if args.seeds_file is not None else (ROOT / "evidence" / "replay_seeds.json")
        check_materialized(target_out, target_seeds)
        print(f"OK: {target_out} matches fresh Harbor bundle")
        return
    if args.out is None or args.seeds_file is None:
        ap.error("the following arguments are required: --out, --seeds-file")
    prepare(
        args.out,
        args.seeds_file,
        overwrite=args.overwrite,
        min_seeds=args.min_seeds,
        allow_short_seeds=args.allow_short_seeds,
    )


if __name__ == "__main__":
    main()
