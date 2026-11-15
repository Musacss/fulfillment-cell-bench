#!/usr/bin/env python3
"""Standalone non-mutating CLI runner for the 4 Horses Environment v02 4-Tier E2E Suite."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

TESTS_E2E_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_E2E_DIR.parent

TIER_FILES = {
    "1": "test_tier1_features.py",
    "2": "test_tier2_boundaries.py",
    "3": "test_tier3_interactions.py",
    "4": "test_tier4_scenarios.py",
}


def build_env() -> dict[str, str]:
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
    env.setdefault("PYTHON_BIN", str(REPO_ROOT / ".venv" / "bin" / "python"))
    env.setdefault("CHROME_BIN", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

    extra_dirs = [
        str(Path(env["NODE_BIN"]).parent),
        str(Path(env["PNPM_BIN"]).parent),
        str(Path(env["UV_BIN"]).parent),
    ]
    current_path = env.get("PATH", "")
    path_parts = [p for p in extra_dirs if p] + ([current_path] if current_path else [])
    env["PATH"] = os.pathsep.join(path_parts)

    py_paths = [str(REPO_ROOT / "src"), str(REPO_ROOT)]
    if env.get("PYTHONPATH"):
        py_paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(py_paths)
    return env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the 4 Horses Environment v02 opaque-box E2E test suite (Tiers 1-4).",
    )
    parser.add_argument(
        "--tier",
        choices=("1", "2", "3", "4"),
        default=None,
        help="Run a specific E2E tier (1, 2, 3, or 4); omit to run all 4 tiers.",
    )
    args, extra_pytest_args = parser.parse_known_args(argv)

    env = build_env()
    python_bin = env["PYTHON_BIN"]
    if not Path(python_bin).exists():
        python_bin = sys.executable

    has_explicit_target = any(
        not a.startswith("-") and (".py" in a or Path(a).exists())
        for a in extra_pytest_args
    )
    if args.tier is not None:
        targets = [str(TESTS_E2E_DIR / TIER_FILES[args.tier])]
    elif has_explicit_target:
        targets = []
    else:
        existing_tiers = [
            str(TESTS_E2E_DIR / TIER_FILES[k])
            for k in ("1", "2", "3", "4")
            if (TESTS_E2E_DIR / TIER_FILES[k]).exists()
        ]
        targets = existing_tiers if existing_tiers else [str(TESTS_E2E_DIR)]

    with tempfile.TemporaryDirectory(prefix="4horses_e2e_pytest_cache_") as cache_dir:
        cmd = [
            python_bin,
            "-B",
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-o",
            f"cache_dir={cache_dir}",
            *targets,
            *extra_pytest_args,
        ]
        completed = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, check=False)
        return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
