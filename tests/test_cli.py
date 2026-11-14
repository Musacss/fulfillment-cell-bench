import json
import os
import subprocess
import sys

from robotization_bench.contracts import ROOT


def command(cwd, *args):
    return subprocess.run(
        [sys.executable, "-m", "robotization_bench.cli", *map(str, args)], cwd=cwd,
        env=os.environ | {"PYTHONPATH": str(ROOT / "src")}, capture_output=True, text=True, timeout=90,
    )


def test_validate_and_pilot_with_export(tmp_path):
    manual = ROOT / "data" / "plans" / "manual.json"
    validated = command(tmp_path, "validate", "--plan", manual)
    assert validated.returncode == 0, validated.stderr
    assert json.loads(validated.stdout) == json.loads(manual.read_text())
    trace = tmp_path / "out" / "timeline.jsonl"
    pilot = command(tmp_path, "pilot", "--plan", manual, "--seed", 11, "--events", trace)
    assert pilot.returncode == 0, pilot.stderr
    payload = json.loads(pilot.stdout)
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    assert sum(event["kind"] == "arrival" for event in events) == payload["raw"]["total"] > 0
    assert sum(event["kind"] == "good" for event in events) == payload["raw"]["good"]
    assert payload["economy"]["total"] == sum(payload["economy"]["costs"].values())


def test_bad_file_unknown_day_and_conflicting_output(tmp_path):
    broken = tmp_path / "input.json"
    broken.write_bytes(b"\xff")
    failed = command(tmp_path, "validate", "--plan", broken)
    assert failed.returncode != 0 and "Traceback" not in failed.stderr
    manual = ROOT / "data" / "plans" / "manual.json"
    original = manual.read_bytes()
    broken.write_bytes(original)
    failed = command(tmp_path, "pilot", "--plan", broken, "--seed", 11, "--events", broken)
    assert failed.returncode != 0 and broken.read_bytes() == original
    trace = tmp_path / "trace.jsonl"
    failed = command(tmp_path, "pilot", "--plan", broken, "--seed", 999, "--events", trace)
    assert failed.returncode != 0 and "public development day" in failed.stderr and not trace.exists()


def test_compare_forwards_operator_flags(tmp_path):
    seeds = tmp_path / "seeds.json"
    seeds.write_text("[821]")
    out = tmp_path / "results"
    invocation = command(tmp_path, "compare", "--plan", ROOT / "data" / "plans" / "manual.json",
                         "--seeds-file", seeds, "--out", out)
    assert invocation.returncode == 0, invocation.stderr
    results = json.loads((out / "results.json").read_text())
    assert not results["development"] and results["evaluation_seeds"] == [821]
    assert results["results"]["submitted"] == results["results"]["manual"]
    bad = command(tmp_path, "compare", "--unknown-option")
    assert bad.returncode != 0
