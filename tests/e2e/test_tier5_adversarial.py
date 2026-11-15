"""Tier 5 white-box adversarial regression suite (< 5.0s total on CPU, zero skips)."""

from __future__ import annotations

import ast
import copy
from dataclasses import asdict, replace
from fractions import Fraction
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
from typing import Any

import pytest

from robotization_bench import economics, grading, mcp_proxy, quarterly, reference, reporting, verifier
from robotization_bench.contracts import InvalidPlan, QuarterlyPlan, WeekPlan, load_world
from robotization_bench.engine import simulate
from robotization_bench.episode import Episode, QuarterlyEpisode
from robotization_bench.scenarios import generate
from robotization_bench.validation import decode_quarterly_plan, parse_plan, parse_quarterly_plan

_CACHED_WORLD: dict[str, Any] | None = None


def _world() -> dict[str, Any]:
    global _CACHED_WORLD
    if _CACHED_WORLD is None:
        _CACHED_WORLD = load_world()
    return _CACHED_WORLD


def _mini_world(world: dict[str, Any]) -> dict[str, Any]:
    mw = copy.deepcopy(world)
    mw["generator"]["waves"] = 1
    mw["generator"]["orders_min"] = 2
    mw["generator"]["orders_span"] = 1
    for prof in mw["quarterly"]["week_profiles"]:
        prof["waves"] = 1
        prof["orders_min"] = 2
        if "orders_span" in prof:
            prof["orders_span"] = 1
    return mw


def test_t5_01_capex_week10_to_11_trusted_bypass_and_manual_burnin_guard() -> None:
    world = _world()
    base = quarterly.manual_quarterly_value(world)
    bad_robot = copy.deepcopy(base)
    for w in range(11):
        bad_robot["weeks"][w].update(robot=True, route="bypass")
    with pytest.raises(InvalidPlan, match=r"weeks\[11\].*robot"):
        parse_quarterly_plan(bad_robot, world)
    bad_trays = copy.deepcopy(base)
    for w in range(12):
        bad_trays["weeks"][w].update(robot=True, trays=(w < 11), route="bypass")
    with pytest.raises(InvalidPlan, match=r"weeks\[11\].*trays"):
        parse_quarterly_plan(bad_trays, world)

    wp_on = WeekPlan(True, False, "bypass", False, ((1,), (2,), (3,), (4,)))
    wp_off = WeekPlan(False, False, "manual", False, ((1,), (2,), (3,), (4,)))
    with pytest.raises(ValueError, match="irreversible CapEx violated"):
        quarterly.simulate_quarter(world, QuarterlyPlan(2, (wp_on,) * 11 + (wp_off,)), 11)
    wp_maint_no_robot = WeekPlan(False, False, "manual", True, ((1,), (2,), (3,), (4,)))
    with pytest.raises(ValueError, match="robot required"):
        quarterly.simulate_quarter(world, QuarterlyPlan(2, (wp_maint_no_robot,) + (wp_off,) * 11), 11)

    delayed = copy.deepcopy(base)
    for w in range(12):
        delayed["weeks"][w]["robot"] = True
        delayed["weeks"][w]["route"] = "manual" if w < 2 else "bypass"
    mw = _mini_world(world)
    qr = quarterly.simulate_quarter(mw, parse_quarterly_plan(delayed, mw), 11)
    assert [wr.commissioning_active for wr in qr.weeks[:5]] == [False, False, True, True, False]


def test_t5_02_carryover_cap_80_truncation_dropped_orders_and_terminal_cents() -> None:
    world = _world()
    plan_dict = quarterly.manual_quarterly_value(world)
    for w in range(12):
        plan_dict["weeks"][w]["workers"] = [[2]]
    qr = quarterly.simulate_quarter(world, parse_quarterly_plan(plan_dict, world), 11)
    hold_rate = world["quarterly"]["money"]["backlog_holding_per_order"]
    unfulfilled_shift = world["money"]["unfulfilled"] * world["quarterly"]["money"]["shifts_per_week"]
    dropped_total = 0
    exo_total = 0
    for idx, wr in enumerate(qr.weeks):
        exo_total += wr.raw.total - wr.carryover_in
        if idx < 11:
            assert wr.carryover_out == min(wr.raw.unfinished, 80) == qr.weeks[idx + 1].carryover_in
            dropped = wr.raw.unfinished - wr.carryover_out
            dropped_total += dropped
            assert wr.week_economy.costs["backlog_holding"] == wr.carryover_out * hold_rate
            assert wr.week_economy.costs["unfulfilled"] == (wr.raw.scrap + dropped) * unfulfilled_shift
        else:
            assert wr.carryover_out == 0
            assert wr.week_economy.costs["backlog_holding"] == 0
            assert wr.week_economy.costs["unfulfilled"] == (wr.raw.scrap + wr.raw.unfinished) * unfulfilled_shift
    assert dropped_total > 0
    assert exo_total == dropped_total + qr.weeks[11].raw.unfinished


def test_t5_03_bipartite_retrain_dp_shrinking_and_expanding_crews() -> None:
    world = _world()
    prev = ((1,), (2,), (3,), (4,), (1,))
    curr = ((3, 4), (1, 2), (2, 3))
    assert economics._retrain_units(prev, curr) == 3
    assert economics._retrain_units(tuple(reversed(prev)), tuple(reversed(curr))) == 3
    raw = quarterly.simulate_quarter(_mini_world(world), parse_quarterly_plan(quarterly.manual_quarterly_value(world), world), 11).weeks[0].raw
    _, week_econ = economics.calculate_week(world, WeekPlan(False, False, "manual", False, curr), prev, raw, carryover_out=0, owned_robot=False, owned_trays=False)
    qm = world["quarterly"]["money"]
    assert week_econ.costs["hiring_retraining"] == 2 * qm["layoff_cost"] + 3 * qm["retrain_cost"]
    assert week_econ.costs["cross_skill"] == 3 * qm["cross_skill_shift_premium"] * qm["shifts_per_week"]
    assert economics._retrain_units(((1, 2), (2,)), ((2, 3), (1, 2, 4), (4,))) == 2


def test_t5_04_grade_quarters_tampered_report_guards_and_overrun_formula() -> None:
    world = _world()
    mw = _mini_world(world)
    base_plan = parse_quarterly_plan(quarterly.manual_quarterly_value(mw), mw)
    q11 = quarterly.simulate_quarter(mw, base_plan, 11)
    q29 = quarterly.simulate_quarter(mw, base_plan, 29)
    bad_w11 = replace(q11.weeks[11], carryover_out=1)
    with pytest.raises(ValueError, match="inconsistent trusted week report"):
        grading.grade_quarters(mw, base_plan, [replace(q11, weeks=q11.weeks[:11] + (bad_w11,))], [q11])
    with pytest.raises(ValueError, match="inconsistent plan purchase across seeds"):
        grading.grade_quarters(mw, base_plan, [q11, replace(q29, purchase=100)], [q11, q29])
    bad_raw = replace(q11.weeks[0].raw, total=q11.weeks[0].raw.total + 1, unfinished=q11.weeks[0].raw.unfinished + 1)
    with pytest.raises(ValueError, match="mismatched exogenous weekly orders"):
        grading.grade_quarters(mw, base_plan, [replace(q11, weeks=(replace(q11.weeks[0], raw=bad_raw),) + q11.weeks[1:])], [q11])

    idle = quarterly.manual_quarterly_value(world)
    for w in range(12):
        idle["weeks"][w]["robot"] = True
    ev = grading.evaluate_quarterly(world, idle, [11])
    assert ev.valid and ev.feasible and not ev.win and {"cost", "labor", "automation"} <= set(ev.reasons)
    assert Fraction(1, 10) < Fraction(ev.reward_num, ev.reward_den) < Fraction(1, 5)


def test_t5_05_verifier_whitebox_boundaries_and_seed_type_guards(tmp_path: Path) -> None:
    world = _world()
    valid_obj = quarterly.manual_quarterly_value(world)
    compact = json.dumps(valid_obj, separators=(",", ":"))
    p_exact = tmp_path / "exact_16384.json"
    p_exact.write_bytes(compact.encode() + b" " * (16_384 - len(compact)))
    assert verifier.verify_quarterly_file(world, p_exact, [11]).valid is True

    p_over = tmp_path / "over_16385.json"
    p_over.write_bytes(compact.encode() + b" " * (16_385 - len(compact)))
    ev_over = verifier.verify_quarterly_file(world, p_over, [11])
    assert not ev_over.valid and (ev_over.reward_num, ev_over.reward_den) == (0, 1) and "16384" in ev_over.reasons[0]

    sym = tmp_path / "sym.json"
    sym.symlink_to(p_exact)
    ev_sym = verifier.verify_quarterly_file(world, sym, [11])
    assert not ev_sym.valid and (ev_sym.reward_num, ev_sym.reward_den) == (0, 1)

    for fn in (verifier.verify_quarterly_file, verifier.verify_any_file):
        for bad_seeds in ("11", b"11", [], [True], [11, 11]):
            with pytest.raises(ValueError):
                fn(world, p_exact, bad_seeds)  # type: ignore[arg-type]

    p_dup = tmp_path / "dup.json"
    w_rest = ",".join(json.dumps(w) for w in valid_obj["weeks"][1:])
    w0 = valid_obj["weeks"][0]
    p_dup.write_text(
        f'{{"schema_version":2,"weeks":[{{"robot":false,"robot":true,"trays":false,"route":"manual","maintenance":false,"workers":{json.dumps(w0["workers"])}}},{w_rest}]}}',
        encoding="utf-8",
    )
    ev_dup = verifier.verify_quarterly_file(world, p_dup, [11])
    assert not ev_dup.valid and "Duplicate" in ev_dup.reasons[0]

    p_inf = tmp_path / "inf.json"
    p_inf.write_text('{"schema_version": -Infinity, "weeks": []}', encoding="utf-8")
    ev_inf = verifier.verify_quarterly_file(world, p_inf, [11])
    assert not ev_inf.valid and "-Infinity" in ev_inf.reasons[0]

    huge = "9" * 110
    p_huge = tmp_path / "huge.json"
    p_huge.write_text(f'{{"schema_version": {huge}, "weeks": []}}', encoding="utf-8")
    ev_huge = verifier.verify_quarterly_file(world, p_huge, [11])
    assert not ev_huge.valid and huge not in ev_huge.reasons[0]


def test_t5_06_harbor_grade_py_verdict_symlink_defense_and_stale_reward_purge(tmp_path: Path, repo_root: Path) -> None:
    grade_path = repo_root / "tasks/fulfillment-cell-bench/tests/grade.py"
    spec = importlib.util.spec_from_file_location("harbor_grade_t5", grade_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "reward.txt").write_text("0.999999\n", encoding="utf-8")
    verdict = tmp_path / "verdict"
    verdict.symlink_to(victim)
    mod.grade(repo_root / "data/plans/manual.json", verdict, mode="quarterly")
    assert not verdict.is_symlink() and verdict.is_dir()
    assert float((verdict / "reward.txt").read_text(encoding="utf-8").strip()) == 0.0
    ev_doc = json.loads((verdict / "evaluation.json").read_text(encoding="utf-8"))
    assert ev_doc["evaluation"]["valid"] is False
    assert (victim / "reward.txt").read_text(encoding="utf-8") == "0.999999\n"


def test_t5_07_run_judge_harbor_cli_safety_and_stubbed_controls_dry_run(tmp_path: Path, repo_root: Path) -> None:
    script = str(repo_root / "scripts/run_judge_harbor.sh")
    miss_out = tmp_path / "missing_harbor_out"
    env_no_harbor = {**os.environ, "HARBOR_BIN": "/nonexistent/harbor_bin_t5", "PYTHON_BIN": sys.executable}
    cli_batch = subprocess.run(
        [
            "bash",
            "-c",
            'set -u; s="$1"; r="$2"; m="$3"; '
            'bash -n "$s" || exit 10; '
            'bash "$s" --help >/dev/null 2>&1 || exit 11; '
            'bash "$s" --bogus-flag >/dev/null 2>&1; [[ $? -eq 2 ]] || exit 12; '
            'bash "$s" -m >/dev/null 2>&1; [[ $? -eq 2 ]] || exit 13; '
            'bash "$s" -o "$r" >/dev/null 2>&1; [[ $? -eq 2 ]] || exit 14; '
            'bash "$s" -o / >/dev/null 2>&1; [[ $? -eq 2 ]] || exit 15; '
            'bash "$s" -o "$m" >/dev/null 2>&1; [[ $? -eq 1 ]] || exit 16',
            "_",
            script,
            str(repo_root),
            str(miss_out),
        ],
        env=env_no_harbor,
        capture_output=True,
        check=False,
    )
    assert cli_batch.returncode == 0 and not miss_out.exists()

    log_path = tmp_path / "calls.jsonl"
    stub = tmp_path / "harbor_stub.sh"
    stub.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\np=''; a=''; o=''\n"
        "while [[ $# -gt 0 ]]; do case \"$1\" in -p) p=\"$2\"; shift 2 ;; -a) a=\"$2\"; shift 2 ;; -o) o=\"$2\"; shift 2 ;; *) shift ;; esac; done\n"
        "stop=false; [[ -f \"$p/solution/solve.sh\" ]] && grep -q 'SocketEpisodeClient().stop()' \"$p/solution/solve.sh\" && stop=true\n"
        "seeds=$(tr -d '\\n ' < \"$p/tests/seeds.json\")\n"
        f"printf '{{\"agent\":\"%s\",\"out\":\"%s\",\"stop\":%s,\"seeds\":%s}}\\n' \"$a\" \"$(basename \"$o\")\" \"$stop\" \"$seeds\" >> {str(log_path)!r}\n"
        "mkdir -p \"$o/trial_0/verifier\"\n"
        "if [[ \"$(basename \"$o\")\" == 'oracle' ]]; then echo '0.412500' > \"$o/trial_0/verifier/reward.txt\"; else echo '0.0' > \"$o/trial_0/verifier/reward.txt\"; fi\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    out_dir = tmp_path / "judge_out"
    res = subprocess.run(
        ["bash", script, "--controls-only", "-o", str(out_dir)],
        env={**os.environ, "HARBOR_BIN": str(stub), "PYTHON_BIN": sys.executable},
        capture_output=True, text=True, check=False,
    )
    assert res.returncode == 0 and "=== Judge Harbor Evaluation Summary ===" in res.stdout
    calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert [(c["out"], c["agent"], c["stop"]) for c in calls] == [("oracle", "oracle", False), ("nop", "nop", False), ("stop_early", "oracle", True)]
    blind_seeds = json.loads((repo_root / "evidence/benchmark-v2/blind_seeds.json").read_text(encoding="utf-8"))
    assert all(c["seeds"] == blind_seeds for c in calls)


def test_t5_08_sacred_v1_frozen_golden_parity_and_harbor_seed_coherence(repo_root: Path) -> None:
    world = _world()
    v1_plan = parse_plan(json.loads((repo_root / "evidence/frozen-v1/submission.json").read_text(encoding="utf-8")), world)
    raw = simulate(world, v1_plan, generate(world, 11), trace=True)
    assert len(raw.events) == 2388
    assert raw.total == raw.good + raw.escaped + raw.scrap + raw.unfinished
    harbor_seeds = json.loads((repo_root / "tasks/fulfillment-cell-bench/tests/seeds.json").read_text(encoding="utf-8"))
    replay_seeds = json.loads((repo_root / "evidence/replay_seeds.json").read_text(encoding="utf-8"))
    blind_seeds = json.loads((repo_root / "evidence/benchmark-v2/blind_seeds.json").read_text(encoding="utf-8"))
    assert harbor_seeds == replay_seeds and set(replay_seeds).isdisjoint(blind_seeds)


def test_t5_09_validate_quarter_pack_tamper_and_diagnostics_json_checks(tmp_path: Path) -> None:
    mw = _mini_world(_world())
    plan_dict = quarterly.manual_quarterly_value(mw)
    plan = parse_quarterly_plan(plan_dict, mw)
    qr = quarterly.simulate_quarter(mw, plan, 11, trace=True)
    base_dir = tmp_path / "base_pack"
    reporting.export_quarter_pack(mw, qr, plan, base_dir)
    diag = {"diagnostics_format": "robotization-bench.quarter-diagnostics.v1", **reporting.build_quarter_diagnostics(mw, qr, plan)}
    (base_dir / "diagnostics.json").write_text(json.dumps(diag, indent=2) + "\n", encoding="utf-8")
    res_q = reporting.validate_quarter_pack(base_dir, expected_weeks=12)
    assert res_q["ok"] is True and res_q["seed"] == 11

    def clone_pack(name: str) -> Path:
        dst = tmp_path / name
        shutil.copytree(base_dir, dst)
        return dst

    c1 = clone_pack("bad_fmt")
    (c1 / "diagnostics.json").write_text('{"diagnostics_format": "wrong.v0"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="diagnostics_format"):
        reporting.validate_quarter_pack(c1, expected_weeks=12)

    c2 = clone_pack("missing_fmt")
    (c2 / "diagnostics.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="diagnostics_format"):
        reporting.validate_quarter_pack(c2, expected_weeks=12)

    c3 = clone_pack("non_dict")
    (c3 / "diagnostics.json").write_text("[1, 2]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        reporting.validate_quarter_pack(c3, expected_weeks=12)

    c4 = clone_pack("nan_diag")
    (c4 / "diagnostics.json").write_text('{"diagnostics_format": "robotization-bench.quarter-diagnostics.v1", "x": NaN}\n', encoding="utf-8")
    with pytest.raises(ValueError):
        reporting.validate_quarter_pack(c4, expected_weeks=12)

    c5 = clone_pack("rogue")
    (c5 / "rogue.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        reporting.validate_quarter_pack(c5, expected_weeks=12)

    c6 = clone_pack("cost_tamper")
    qm = json.loads((c6 / "quarter_manifest.json").read_text(encoding="utf-8"))
    qm["total_cost"] += 100
    (c6 / "quarter_manifest.json").write_text(json.dumps(qm) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        reporting.validate_quarter_pack(c6, expected_weeks=12)


def test_t5_10_validate_shift_bundle_rejects_replay_format_truncation_and_symlinks(tmp_path: Path) -> None:
    mw = _mini_world(_world())
    plan = parse_plan({"schema_version": 1, "robot": False, "trays": False, "route": "manual", "workers": [[1], [2], [3], [4]]}, mw)
    scen = generate(mw, 11)
    raw = simulate(mw, plan, scen, trace=True)
    econ = economics.calculate(mw, plan, raw)
    bdir = tmp_path / "shift_base"
    reporting.export_shift_bundle(mw, plan, scen, raw, econ, bdir)
    assert reporting.validate_shift_bundle(bdir)["ok"] is True

    for idx, mut in enumerate(("fmt", "trunc", "good", "escape", "symlink")):
        dst = tmp_path / f"shift_{idx}"
        shutil.copytree(bdir, dst)
        m = json.loads((dst / "manifest.json").read_text(encoding="utf-8"))
        if mut == "fmt":
            m["replay_format"] = "robotization-bench.replay.v0"
            (dst / "manifest.json").write_text(json.dumps(m) + "\n", encoding="utf-8")
        elif mut == "trunc":
            lines = (dst / "events.jsonl").read_text(encoding="utf-8").splitlines()
            (dst / "events.jsonl").write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
        elif mut == "good":
            m["raw"]["good"] += 1
            (dst / "manifest.json").write_text(json.dumps(m) + "\n", encoding="utf-8")
        elif mut == "escape":
            m["events_file"] = "../outside.jsonl"
            (dst / "manifest.json").write_text(json.dumps(m) + "\n", encoding="utf-8")
        else:
            real_ev = tmp_path / "real_events.jsonl"
            shutil.move(dst / "events.jsonl", real_ev)
            (dst / "events.jsonl").symlink_to(real_ev)
        with pytest.raises(ValueError):
            reporting.validate_shift_bundle(dst)


def test_t5_11_serve_3d_blocks_encoded_traversal_null_bytes_write_verbs_and_preflight_cors(tmp_path: Path, repo_root: Path) -> None:
    spec = importlib.util.spec_from_file_location("serve_3d_t5", repo_root / "scripts/serve_3d.py")
    assert spec and spec.loader
    serve_3d = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(serve_3d)

    serve_root = tmp_path / "artifacts"
    serve_root.mkdir()
    (serve_root / "index.json").write_text('{"packs": []}\n', encoding="utf-8")
    (tmp_path / "README.md").write_text("TOP_SECRET_OUTSIDE_ROOT", encoding="utf-8")
    srv = serve_3d.create_server(serve_root, "127.0.0.1", 0, quiet=True)
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    t.start()
    host, port = srv.server_address[:2]
    try:
        def req(method: str, target: str) -> tuple[int, dict[str, str], str]:
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request(method, target)
            r = conn.getresponse()
            body = r.read().decode("utf-8", errors="replace")
            hdrs = {k.lower(): v for k, v in r.getheaders()}
            conn.close()
            return r.status, hdrs, body

        st, hdrs, _ = req("OPTIONS", "/index.json")
        assert st == 204 and hdrs.get("access-control-allow-origin") == "*" and "no-store" in hdrs.get("cache-control", "")
        assert req("OPTIONS", "/%2e%2e/README.md")[0] == 403
        st_ok, _, body_ok = req("GET", "/index.json?cachebust=1")
        assert st_ok == 200 and json.loads(body_ok) == {"packs": []}
        for bad in ("/%2e%2e/README.md", "/..%2fREADME.md", "/index.json%00.json", "//index.json", "/..%5cREADME.md"):
            st_b, hdr_b, body_b = req("GET", bad)
            assert st_b == 403 and hdr_b.get("access-control-allow-origin") == "*" and "TOP_SECRET_OUTSIDE_ROOT" not in body_b
        for verb in ("POST", "PUT", "DELETE"):
            assert req(verb, "/index.json")[0] == 405
    finally:
        srv.shutdown()
        srv.server_close()


def test_t5_12_mcp_proxy_zero_whitebox_ast_and_isolated_sys_modules(repo_root: Path) -> None:
    tree = ast.parse((repo_root / "src/robotization_bench/mcp_proxy.py").read_text(encoding="utf-8"))
    forbidden = {"engine", "economics", "grading", "scenarios", "quarterly", "reference", "episode", "contracts", "validation", "reporting", "diagnostics"}
    imported = {
        part
        for node in ast.walk(tree)
        for name in (
            [alias.name for alias in node.names]
            if isinstance(node, ast.Import)
            else ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
        )
        for part in name.split(".")
    }
    assert imported.isdisjoint(forbidden)
    proc = subprocess.run(
        [sys.executable, "-I", "-B", "-c", "import sys, json; sys.path.insert(0, 'src'); import robotization_bench.mcp_proxy; print(json.dumps(sorted(k for k in sys.modules if k.startswith('robotization_bench'))))"],
        cwd=repo_root, capture_output=True, text=True, check=True,
    )
    assert json.loads(proc.stdout) == ["robotization_bench", "robotization_bench.mcp_proxy"]


def test_t5_13_devtools_mcp_rejects_invalid_horizon_negative_or_bool_seeds_and_audits_v1(repo_root: Path) -> None:
    spec = importlib.util.spec_from_file_location("devtools_mcp_t5", repo_root / ".agents/mcp/devtools_mcp.py")
    assert spec and spec.loader
    devtools = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(devtools)
    frozen_v1 = json.loads((repo_root / "evidence/frozen-v1/submission.json").read_text(encoding="utf-8"))
    assert devtools.redteam_reward_exploits("dev", "v1")["hierarchy_intact"] is True
    assert devtools.audit_3d_replay_trace(frozen_v1, seed=11)["event_count"] == 2388
    bad_mat = devtools.verify_plan_matrix({"bad": 1}, "dev")
    assert bad_mat["valid"] is False and (bad_mat["reward_num"], bad_mat["reward_den"]) == (0, 1)
    for call in (
        lambda: devtools.redteam_reward_exploits("dev", "invalid_horizon"),
        lambda: devtools.audit_3d_replay_trace(frozen_v1, seed=-5),
        lambda: devtools.audit_3d_replay_trace(frozen_v1, seed=True),
        lambda: devtools.verify_plan_matrix(frozen_v1, "custom", []),
        lambda: devtools.verify_plan_matrix(frozen_v1, "custom", [-1]),
        lambda: devtools.verify_plan_matrix(frozen_v1, "custom", [True]),
        lambda: devtools.verify_plan_matrix(frozen_v1, "custom", [11, 11]),
    ):
        with pytest.raises(ValueError):
            call()


def test_t5_14_episode_state_budget_ratchet_monotonic_and_tamper_rejected(tmp_path: Path) -> None:
    mw = _mini_world(_world())
    st_path = tmp_path / "state.json"
    ep1 = QuarterlyEpisode(mw, seeds=[11], max_pilots=5, state_path=st_path)
    ep1.pilot(quarterly.manual_quarterly_value(mw), 11)
    ep_inflate = QuarterlyEpisode(mw, seeds=[11], max_pilots=12, state_path=st_path)
    assert (ep_inflate.max_pilots, ep_inflate.pilot_used) == (5, 1)
    QuarterlyEpisode(mw, seeds=[11], max_pilots=2, state_path=st_path)
    ep_reopen = QuarterlyEpisode(mw, seeds=[11], max_pilots=10, state_path=st_path)
    assert (ep_reopen.max_pilots, ep_reopen.pilot_used) == (2, 1)

    with pytest.raises(ValueError):
        Episode(mw, (generate(mw, 11),), max_pilots=5, state_path=st_path)
    sym_st = tmp_path / "sym_state.json"
    sym_st.symlink_to(st_path)
    with pytest.raises(ValueError):
        QuarterlyEpisode(mw, seeds=[11], max_pilots=5, state_path=sym_st)

    raw_state = json.loads(st_path.read_text(encoding="utf-8"))
    nan_st = tmp_path / "nan_state.json"
    nan_st.write_text('{"schema_version": 2, "mode": "quarterly", "pilot_used": NaN, "max_pilots": 5, "closed": false, "submission": null, "log": []}\n', encoding="utf-8")
    with pytest.raises(ValueError):
        QuarterlyEpisode(mw, seeds=[11], max_pilots=5, state_path=nan_st)
    bool_st = tmp_path / "bool_state.json"
    raw_state["pilot_used"] = True
    bool_st.write_text(json.dumps(raw_state) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        QuarterlyEpisode(mw, seeds=[11], max_pilots=5, state_path=bool_st)


def test_t5_15_quarterly_observe_deepcopy_and_private_world_key_sanitization() -> None:
    w = copy.deepcopy(_world())
    w["_secret_eval_seeds"] = [999]
    w["quarterly"]["_hidden_bonus"] = 42
    ep = QuarterlyEpisode(w, seeds=[11, 29], max_pilots=4)
    obs1 = ep.observe()
    assert "_secret_eval_seeds" not in obs1["world"] and "_hidden_bonus" not in obs1["world"]["quarterly"]
    orig_orders_min = obs1["world"]["generator"]["orders_min"]
    orig_w0_orders = obs1["world"]["quarterly"]["week_profiles"][0]["orders_min"]
    obs1["world"]["generator"]["orders_min"] = 999999
    obs1["world"]["quarterly"]["week_profiles"][0]["orders_min"] = 888888
    obs1["development_seeds"].clear()
    obs1["history"].clear()
    obs1["manual"]["weeks"].clear()
    obs1["pilot_budget"]["max"] = 9999
    obs2 = ep.observe()
    assert obs2["world"]["generator"]["orders_min"] == orig_orders_min
    assert obs2["world"]["quarterly"]["week_profiles"][0]["orders_min"] == orig_w0_orders
    assert obs2["development_seeds"] == [11, 29] and len(obs2["history"]) == 2
    assert len(obs2["manual"]["weeks"]) == 12 and obs2["pilot_budget"] == {"used": 0, "max": 4}


def test_t5_16_reference_solver_blackbox_purity_and_single_seed_tight_cap(repo_root: Path) -> None:
    tree = ast.parse((repo_root / "src/robotization_bench/reference.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(not a.name.startswith("robotization_bench") for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and not (node.module or "").startswith("robotization_bench")
    world = _world()
    ep = QuarterlyEpisode(world, seeds=[11], max_pilots=3)
    plan = reference.solve(ep)
    parse_quarterly_plan(plan, world)
    assert ep.pilot_used <= 2 and not ep.closed and ep.rejected_calls == 0
    sub_res = ep.submit(plan)
    assert sub_res["terminal"] is True and sub_res["plan"] is not None


def test_t5_17_socket_daemon_ratchet_and_client_malformed_frame_defenses(
    short_sock_dir: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _world()
    sock_path = short_sock_dir / "d.sock"
    state_path = short_sock_dir / "st.json"
    proc = subprocess.Popen(
        [sys.executable, "-m", "robotization_bench.mcp_server", "--socket", str(sock_path), "--state", str(state_path), "--max-pilots", "2"],
        env={**os.environ, "PYTHONPATH": str(repo_root / "src")},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(250):
            if sock_path.exists():
                break
            threading.Event().wait(0.02)
        c1 = mcp_proxy.SocketEpisodeClient(sock_path)
        with pytest.raises(mcp_proxy.EpisodeRemoteError) as e_bad:
            c1.pilot({"bad": 1}, 11)
        assert e_bad.value.error_type in ("InvalidPlan", "ValueError")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as raw_s:
            raw_s.settimeout(5.0)
            raw_s.connect(str(sock_path))
            try:
                raw_s.sendall(b'{"action":"observe","pad":"' + b"x" * 280_000 + b'"}\n')
            except BrokenPipeError:
                pass
            err_line = raw_s.recv(4096)
        assert json.loads(err_line.decode("utf-8"))["ok"] is False

        c2 = mcp_proxy.SocketEpisodeClient(sock_path)
        assert c2.observe()["pilot_budget"] == {"used": 0, "max": 2}
        man = quarterly.manual_quarterly_value(world)
        c2.pilot(man, 11)
        c2.pilot(man, 29)
        with pytest.raises(mcp_proxy.EpisodeRemoteError) as e_cap:
            c2.pilot(man, 47)
        assert e_cap.value.error_type == "PilotBudgetExceeded"
        sub_c2 = c2.submit(man)
        assert sub_c2["terminal"] is True and sub_c2["plan"] is not None

        c3 = mcp_proxy.SocketEpisodeClient(sock_path)
        for fn in (lambda: c3.observe(), lambda: c3.pilot(man, 11), lambda: c3.submit(man), lambda: c3.stop()):
            with pytest.raises(mcp_proxy.EpisodeRemoteError) as e_cl:
                fn()
            assert e_cl.value.error_type == "EpisodeClosed"
    finally:
        proc.terminate()
        proc.wait(timeout=5)

    bad_sock = short_sock_dir / "bad.sock"
    frames = [b"", b"not-json\n", b"[1, 2]\n", b'{"ok": true, "result": [1]}\n', b'{"ok": true, "result": {"p": "' + b"z" * 128]
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(bad_sock))
    srv.listen(5)

    def _serve_bad() -> None:
        for payload in frames:
            conn, _ = srv.accept()
            with conn:
                conn.recv(1024)
                if payload:
                    conn.sendall(payload)
        srv.close()

    threading.Thread(target=_serve_bad, daemon=True).start()
    cli = mcp_proxy.SocketEpisodeClient(bad_sock)
    for idx in range(5):
        if idx == 4:
            monkeypatch.setattr(mcp_proxy, "_MAX_RESPONSE_BYTES", 64)
        with pytest.raises((RuntimeError, ValueError)):
            cli.observe()


def test_t5_18_verify_evidence_whitebox_tamper_matrix(tmp_path: Path, repo_root: Path) -> None:
    spec = importlib.util.spec_from_file_location("run_bench_t5", repo_root / "scripts/run_bench.py")
    assert spec and spec.loader
    rb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rb)

    world = _world()
    seed = 777_777
    win_sub = next((repo_root / "evidence/benchmark-v2/runs").rglob("oracle/**/submission.json"))
    win_plan = json.loads(win_sub.read_text(encoding="utf-8"))
    ev_win = grading.evaluate_quarterly(world, win_plan, [seed])
    assert ev_win.win is True

    base_ev = tmp_path / "ev_base"
    (base_ev / "runs/oracle").mkdir(parents=True)
    (base_ev / "runs/nop").mkdir(parents=True)
    blind_bytes = b"[777777]\n"
    (base_ev / "blind_seeds.json").write_bytes(blind_bytes)
    (base_ev / "blind_seeds.sha256").write_text(f"{hashlib.sha256(blind_bytes).hexdigest()}  blind_seeds.json\n", encoding="utf-8")
    (base_ev / "runs/oracle/submission.json").write_text(json.dumps(win_plan) + "\n", encoding="utf-8")
    (base_ev / "runs/oracle/evaluation.json").write_text(json.dumps({"evaluation": asdict(ev_win)}) + "\n", encoding="utf-8")
    (base_ev / "runs/oracle/reward.txt").write_text(f"{ev_win.reward_num / ev_win.reward_den}\n", encoding="utf-8")
    (base_ev / "runs/nop/reward.txt").write_text("0.0\n", encoding="utf-8")
    (base_ev / "manifest.json").write_text(
        json.dumps({"runs": {"oracle": {"role": "reference"}, "nop": {"role": "nop", "submission": None}}}) + "\n",
        encoding="utf-8",
    )
    assert rb._verify_evidence(base_ev) == 0

    for idx, mut in enumerate(("sha", "reward", "unlisted", "symlink", "role")):
        dst = tmp_path / f"ev_{idx}"
        shutil.copytree(base_ev, dst)
        if mut == "sha":
            (dst / "blind_seeds.json").write_text("[777778]\n", encoding="utf-8")
        elif mut == "reward":
            shutil.rmtree(dst / "runs/oracle")
            (dst / "manifest.json").write_text('{"runs": {"nop": {"role": "nop", "submission": null}}}\n', encoding="utf-8")
            (dst / "runs/nop/reward.txt").write_text("0.500000\n", encoding="utf-8")
        elif mut == "unlisted":
            (dst / "runs/rogue_trial").mkdir()
        elif mut == "symlink":
            (dst / "runs/oracle/link.txt").symlink_to(dst / "blind_seeds.json")
        else:
            shutil.rmtree(dst / "runs/oracle")
            (dst / "manifest.json").write_text('{"runs": {"nop": {"role": "manual", "submission": null}}}\n', encoding="utf-8")
        with pytest.raises(rb.BenchError):
            rb._verify_evidence(dst)
