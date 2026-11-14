"""TDD suite for AI Mistake Diagnostics & Multi-Model 3D Showcase Exporter."""

import copy
from dataclasses import asdict
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

from robotization_bench.contracts import ROOT, load_world
from robotization_bench.diagnostics import diagnose_quarter_plan
from robotization_bench.grading import evaluate_quarterly
from robotization_bench.quarterly import manual_quarterly_value, simulate_quarter
from robotization_bench.reporting import validate_quarter_pack, validate_shift_bundle
from robotization_bench.validation import parse_quarterly_plan


PHASED_WIN_PLAN = {
    "schema_version": 2,
    "weeks": [
        {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [2, 3], [4]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [2, 3], [4]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": True, "workers": [[1], [2], [2, 3], [4]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [3], [4], [2, 3]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": True, "workers": [[1], [2], [2, 3], [4]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [2, 3], [4]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": True, "workers": [[1], [2], [2, 3], [4]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [3], [4], [2, 3]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [3], [4], [2, 3]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [3], [4], [2, 3]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": True, "workers": [[1], [2], [2, 3], [4]]},
        {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [2, 3], [4]]},
    ],
}


def _uniform_quarterly(
    *,
    robot: bool,
    trays: bool,
    route: str,
    maintenance: bool,
    workers: list[list[int]],
) -> dict:
    return {
        "schema_version": 2,
        "weeks": [
            {
                "robot": robot,
                "trays": trays,
                "route": route,
                "maintenance": maintenance,
                "workers": [list(z) for z in workers],
            }
            for _ in range(12)
        ],
    }


def _assert_diagnostics_contract(diag: dict, *, expected_valid: bool = True) -> None:
    # Must be strict JSON-serializable (no tuples, NaN/Inf, dataclasses, or Fractions)
    roundtrip = json.loads(json.dumps(diag, allow_nan=False))
    assert roundtrip == diag

    overall = diag["overall"]
    required_overall = {
        "valid",
        "feasible",
        "win",
        "reward_float",
        "reward_fraction",
        "failure_reasons",
        "total_cost_eur",
        "cost_delta_vs_manual_eur",
        "cost_delta_vs_reference_eur",
        "headline_summary",
    }
    assert required_overall.issubset(overall.keys())
    assert overall["valid"] is expected_valid
    assert isinstance(overall["reward_float"], float)
    assert isinstance(overall["reward_fraction"], str) and "/" in overall["reward_fraction"]
    assert isinstance(overall["failure_reasons"], list)
    assert isinstance(overall["headline_summary"], str) and len(overall["headline_summary"]) >= 20

    assert isinstance(diag["key_mistakes"], list)
    for m in diag["key_mistakes"]:
        assert m["severity"] in {"critical", "major", "minor"}
        assert isinstance(m["week_range"], list) and len(m["week_range"]) == 2
        assert 0 <= m["week_range"][0] <= m["week_range"][1] <= 11
        assert isinstance(m["category"], str) and m["category"]
        assert type(m["euro_impact_cents"]) is int and m["euro_impact_cents"] >= 0
        assert isinstance(m["evidence_metrics"], dict)
        assert isinstance(m["hud_callout"], str) and len(m["hud_callout"]) >= 15

    if expected_valid:
        assert len(diag["timeline_weeks"]) == 12
        for idx, tw in enumerate(diag["timeline_weeks"]):
            assert tw["week"] == idx
            assert isinstance(tw["label"], str) and tw["label"]
            assert isinstance(tw["decisions"], dict)
            assert isinstance(tw["metrics"], dict)
            assert tw["status"] in {"ok", "warning", "critical"}
            assert isinstance(tw["active_mistakes"], list)
            assert isinstance(tw["highlight_ticks"], list)


def test_unstaffed_zone3_jam_deadlock_archetype_and_exact_highlight_ticks():
    world = load_world()
    deadlock_plan = _uniform_quarterly(
        robot=True, trays=False, route="all", maintenance=False, workers=[[1], [2], [4]]
    )
    diag = diagnose_quarter_plan(
        world, deadlock_plan, 11, reference_plan_dict=PHASED_WIN_PLAN
    )
    _assert_diagnostics_contract(diag)

    overall = diag["overall"]
    assert overall["feasible"] is False
    assert overall["win"] is False
    assert overall["cost_delta_vs_manual_eur"] > 100_000.0
    assert overall["cost_delta_vs_reference_eur"] > 100_000.0
    assert "volume" in overall["failure_reasons"]

    categories = [m["category"] for m in diag["key_mistakes"]]
    assert categories[0] == "unstaffed_zone3_jam_deadlock"
    assert "excess_idle_payroll" not in categories
    top = diag["key_mistakes"][0]
    assert top["severity"] == "critical"
    assert top["week_range"] == [0, 11]
    assert top["euro_impact_cents"] > 10_000_000
    assert top["evidence_metrics"]["jams"] >= 12
    assert "Zone 3" in top["hud_callout"] or "zone 3" in top["hud_callout"].lower()

    # Cross-check highlight_ticks against real traced simulation events
    qrep = simulate_quarter(world, parse_quarterly_plan(deadlock_plan, world), 11, trace=True)
    horizon = world["clock"]["shift_ticks"] + world["clock"]["overtime_ticks"]
    tick_sec = world["clock"]["tick_seconds"]
    for w_idx, tw in enumerate(diag["timeline_weeks"]):
        assert tw["status"] == "critical"
        assert len(tw["active_mistakes"]) >= 1
        assert len(tw["highlight_ticks"]) >= 1
        jam_events = [e for e in qrep.weeks[w_idx].raw.events if e.kind == "jam"]
        assert len(jam_events) == 1
        hl = tw["highlight_ticks"][0]
        assert hl["kind"] in {"jam_deadlock", "jam"}
        assert hl["start_tick"] == jam_events[0].tick
        assert hl["end_tick"] == horizon
        assert hl["start_seconds"] == hl["start_tick"] * tick_sec
        assert hl["order_id"] == jam_events[0].order_id


def test_route_all_without_maintenance_wear_blowout_and_backlog_snowball():
    world = load_world()
    naive_all = _uniform_quarterly(
        robot=True, trays=True, route="all", maintenance=False, workers=[[1], [2], [3], [4], [2, 3]]
    )
    ev = evaluate_quarterly(world, naive_all, world["development_seeds"])
    diag = diagnose_quarter_plan(
        world, naive_all, 11, reference_plan_dict=PHASED_WIN_PLAN, evaluation=ev
    )
    _assert_diagnostics_contract(diag)

    assert diag["overall"]["feasible"] is False
    assert diag["overall"]["win"] is False
    assert set(diag["overall"]["failure_reasons"]) == {"volume", "on_time", "quality"}

    by_cat = {m["category"]: m for m in diag["key_mistakes"]}
    assert "all_route_wear_blowout" in by_cat
    assert "backlog_snowball" in by_cat

    wear_m = by_cat["all_route_wear_blowout"]
    assert wear_m["severity"] == "critical"
    assert wear_m["evidence_metrics"]["wear_peak"] == 12
    assert wear_m["evidence_metrics"]["jams"] > 400
    assert "route='all'" in wear_m["hud_callout"] or "all" in wear_m["hud_callout"].lower()

    # Black Friday Week 8 must be critical with highlight_ticks grounded in real events
    bf_week = diag["timeline_weeks"][8]
    assert bf_week["label"] == "black_friday_peak"
    assert bf_week["status"] == "critical"
    assert bf_week["metrics"]["wear_end"] == 12
    assert bf_week["metrics"]["jams"] >= 40
    assert len(bf_week["highlight_ticks"]) >= 1

    qrep = simulate_quarter(world, parse_quarterly_plan(naive_all, world), 11, trace=True)
    for w_idx, tw in enumerate(diag["timeline_weeks"]):
        evs = qrep.weeks[w_idx].raw.events
        for hl in tw["highlight_ticks"]:
            assert 0 <= hl["start_tick"] <= hl["end_tick"] <= 1080
            if hl["kind"] in {"jam", "escaped", "scrap"}:
                assert any(
                    e.kind == hl["kind"] and e.order_id == hl["order_id"] and e.tick == hl["focus_tick"]
                    for e in evs
                )


def test_bare_robot_commissioning_spike_and_skipped_maintenance_archetypes():
    world = load_world()

    # 1. Bare robot without trays -> commissioning jam/defect spike in Weeks 0-1 + wear climb
    bare_plan = _uniform_quarterly(
        robot=True, trays=False, route="bypass", maintenance=False, workers=[[1], [2], [3], [4], [2, 3]]
    )
    diag_bare = diagnose_quarter_plan(world, bare_plan, 11, reference_plan_dict=PHASED_WIN_PLAN)
    _assert_diagnostics_contract(diag_bare)
    bare_cats = {m["category"]: m for m in diag_bare["key_mistakes"]}
    assert "bare_robot_commissioning_spike" in bare_cats
    comm_m = bare_cats["bare_robot_commissioning_spike"]
    assert comm_m["week_range"][0] == 0
    assert comm_m["evidence_metrics"]["jams"] >= 60
    assert "tray" in comm_m["hud_callout"].lower() or "bare" in comm_m["hud_callout"].lower()

    # 2. Trays enabled with bypass, but zero maintenance before/during holiday peak
    skip_maint = _uniform_quarterly(
        robot=True, trays=True, route="bypass", maintenance=False, workers=[[1], [2], [3], [4], [2, 3]]
    )
    diag_skip = diagnose_quarter_plan(world, skip_maint, 11, reference_plan_dict=PHASED_WIN_PLAN)
    _assert_diagnostics_contract(diag_skip)
    skip_cats = {m["category"]: m for m in diag_skip["key_mistakes"]}
    assert "skipped_pre_peak_maintenance" in skip_cats
    assert skip_cats["skipped_pre_peak_maintenance"]["evidence_metrics"]["wear_peak"] == 12


def test_holiday_understaffing_idle_payroll_manual_and_winning_phased_plan():
    world = load_world()

    # 1. Holiday peak understaffing (4 workers kept static through promo/Black Friday waves)
    understaff_peak = {
        "schema_version": 2,
        "weeks": [
            {
                "robot": True,
                "trays": True,
                "route": "bypass",
                "maintenance": (w in {2, 4, 6, 10}),
                "workers": [[1], [2], [2, 3], [4]],
            }
            for w in range(12)
        ],
    }
    diag_under = diagnose_quarter_plan(world, understaff_peak, 11, reference_plan_dict=PHASED_WIN_PLAN)
    _assert_diagnostics_contract(diag_under)
    under_cats = {m["category"] for m in diag_under["key_mistakes"]}
    assert "holiday_peak_understaffing" in under_cats
    assert "backlog_snowball" in under_cats

    # 2. Excess idle payroll (7 workers kept all quarter -> feasible, fails cost win condition)
    idle_payroll = {
        "schema_version": 2,
        "weeks": [
            {
                "robot": True,
                "trays": True,
                "route": "bypass",
                "maintenance": (w in {2, 4, 6, 10}),
                "workers": [[1], [2], [3], [3], [4], [2, 3], [1, 2]],
            }
            for w in range(12)
        ],
    }
    diag_payroll = diagnose_quarter_plan(world, idle_payroll, 11, reference_plan_dict=PHASED_WIN_PLAN)
    _assert_diagnostics_contract(diag_payroll)
    assert diag_payroll["overall"]["feasible"] is True
    assert diag_payroll["overall"]["win"] is False
    assert diag_payroll["overall"]["cost_delta_vs_manual_eur"] > 5_000.0
    assert any(m["category"] == "excess_idle_payroll" for m in diag_payroll["key_mistakes"])

    # 3. Manual baseline -> feasible, not win, zero cost delta vs manual, unprofitable_low_automation
    manual_q = manual_quarterly_value(world)
    diag_manual = diagnose_quarter_plan(world, manual_q, 11, reference_plan_dict=PHASED_WIN_PLAN)
    _assert_diagnostics_contract(diag_manual)
    assert diag_manual["overall"]["feasible"] is True
    assert diag_manual["overall"]["win"] is False
    assert diag_manual["overall"]["reward_fraction"] == "1/5"
    assert diag_manual["overall"]["cost_delta_vs_manual_eur"] == 0.0
    assert diag_manual["overall"]["cost_delta_vs_reference_eur"] > 5_000.0
    assert any(m["category"] == "unprofitable_low_automation" for m in diag_manual["key_mistakes"])

    # 4. Profitable phased winning plan -> win=True, negative cost delta vs manual, no critical/major mistakes
    ev_win = evaluate_quarterly(world, PHASED_WIN_PLAN, world["development_seeds"])
    diag_win = diagnose_quarter_plan(
        world, PHASED_WIN_PLAN, 11, reference_plan_dict=PHASED_WIN_PLAN, evaluation=ev_win
    )
    _assert_diagnostics_contract(diag_win)
    assert diag_win["overall"]["valid"] is True
    assert diag_win["overall"]["feasible"] is True
    assert diag_win["overall"]["win"] is True
    assert diag_win["overall"]["failure_reasons"] == []
    assert diag_win["overall"]["cost_delta_vs_manual_eur"] < -5_000.0
    assert diag_win["overall"]["cost_delta_vs_reference_eur"] == 0.0
    assert all(m["severity"] == "minor" for m in diag_win["key_mistakes"])
    assert all(tw["status"] != "critical" for tw in diag_win["timeline_weeks"])

    # 5. Idle CapEx (robot bought, kept on route='manual') + dict evaluation + strict input guards
    idle_capex = _uniform_quarterly(
        robot=True,
        trays=True,
        route="manual",
        maintenance=False,
        workers=manual_q["weeks"][0]["workers"],
    )
    ev_idle_dict = json.loads(
        json.dumps(asdict(evaluate_quarterly(world, idle_capex, world["development_seeds"])))
    )
    diag_idle = diagnose_quarter_plan(
        world, idle_capex, 11, reference_plan_dict=PHASED_WIN_PLAN, evaluation=ev_idle_dict
    )
    _assert_diagnostics_contract(diag_idle)
    assert any(m["category"] == "unprofitable_low_automation" for m in diag_idle["key_mistakes"])
    assert "route='manual'" in diag_idle["key_mistakes"][0]["hud_callout"]

    # 6. Invalid plan handled gracefully without crashing + non-int seed / missing quarterly guards
    diag_bad = diagnose_quarter_plan(world, {"schema_version": 2, "weeks": []}, 11)
    _assert_diagnostics_contract(diag_bad, expected_valid=False)
    assert diag_bad["overall"]["reward_fraction"] == "0/1"
    assert diag_bad["overall"]["reward_float"] == 0.0
    assert diag_bad["key_mistakes"][0]["severity"] == "critical"

    with pytest.raises(ValueError, match="seed"):
        diagnose_quarter_plan(world, PHASED_WIN_PLAN, True)
    with pytest.raises(ValueError, match="seed"):
        diagnose_quarter_plan(world, PHASED_WIN_PLAN, -1)
    world_no_q = {k: v for k, v in world.items() if k != "quarterly"}
    with pytest.raises(ValueError, match="quarterly"):
        diagnose_quarter_plan(world_no_q, PHASED_WIN_PLAN, 11)


def test_export_ai_mistakes_3d_cli_end_to_end_and_quarter_pack_validation(tmp_path):
    script_path = ROOT / "scripts" / "export_ai_mistakes_3d.py"
    assert script_path.is_file(), f"Missing {script_path}"

    frontier_plan = _uniform_quarterly(
        robot=True, trays=True, route="all", maintenance=False, workers=[[1], [2], [3], [4], [2, 3]]
    )
    trained_plan = copy.deepcopy(PHASED_WIN_PLAN)

    frontier_file = tmp_path / "gpt54_frontier.json"
    trained_file = tmp_path / "qwen_grpo_trained.json"
    frontier_file.write_text(json.dumps(frontier_plan, indent=2), encoding="utf-8")
    trained_file.write_text(json.dumps(trained_plan, indent=2), encoding="utf-8")

    out_dir = tmp_path / "ai_showcase_pack"
    proc = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--out",
            str(out_dir),
            "--seeds",
            "11",
            "29",
            "--submission",
            f"gpt54=GPT-5.4 (Frontier)={frontier_file}",
            "--submission",
            f"qwen_grpo=Qwen-7B GRPO (Trained)={trained_file}",
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert proc.returncode == 0, proc.stderr

    index_path = out_dir / "index.json"
    assert index_path.is_file()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index["pack_format"] == "robotization-bench.3d-pack-index.v1"
    assert index["replay_format"] == "robotization-bench.replay.v1"
    assert index["seeds"] == [11, 29]
    assert index["evaluation_seeds"] == [11, 29, 47]

    # Expect 4 strategies (manual, reference, gpt54, qwen_grpo) x 2 seeds = 8 runs
    runs_by_id = {r["id"]: r for r in index["runs"]}
    assert len(runs_by_id) == 8
    for seed in (11, 29):
        for slug in ("manual", "reference", "gpt54", "qwen_grpo"):
            rid = f"quarterly-{slug}-seed{seed}"
            assert rid in runs_by_id
            run = runs_by_id[rid]
            pack_subdir = out_dir / run["bundle_dir"]
            audit = validate_quarter_pack(pack_subdir, expected_weeks=12)
            assert audit["ok"] is True
            for w in range(12):
                assert validate_shift_bundle(pack_subdir / "weeks" / f"week-{w:02d}")["ok"] is True

            assert run["diagnostics"] == f"{rid}/diagnostics.json"
            diag_path = out_dir / run["diagnostics"]
            assert diag_path.is_file()
            diag = json.loads(diag_path.read_text(encoding="utf-8"))
            _assert_diagnostics_contract(diag)

        assert runs_by_id[f"quarterly-reference-seed{seed}"]["evaluation"]["win"] is True
        assert runs_by_id[f"quarterly-qwen_grpo-seed{seed}"]["evaluation"]["win"] is True
        assert runs_by_id[f"quarterly-gpt54-seed{seed}"]["evaluation"]["feasible"] is False

    # Verify comparisons include manual vs reference, frontier vs reference, and frontier vs trained
    comp_pairs = {(c["seed"], c["left"], c["right"]) for c in index["comparisons"]}
    for seed in (11, 29):
        assert (seed, f"quarterly-manual-seed{seed}", f"quarterly-reference-seed{seed}") in comp_pairs
        assert (seed, f"quarterly-gpt54-seed{seed}", f"quarterly-reference-seed{seed}") in comp_pairs
        assert (seed, f"quarterly-gpt54-seed{seed}", f"quarterly-qwen_grpo-seed{seed}") in comp_pairs

    # Verify HUD overlay guide exists in --out AND docs/ru/AI_MISTAKES_OVERLAY_RU.md with identical content
    out_guide = out_dir / "AI_MISTAKES_OVERLAY_RU.md"
    repo_guide = ROOT / "docs" / "ru" / "AI_MISTAKES_OVERLAY_RU.md"
    assert out_guide.is_file()
    assert repo_guide.is_file()
    assert out_guide.read_text(encoding="utf-8") == repo_guide.read_text(encoding="utf-8")
    guide_text = out_guide.read_text(encoding="utf-8")
    assert "diagnostics.json" in guide_text
    assert "highlight_ticks" in guide_text
    assert "hud_callout" in guide_text

    # Negative CLI checks: clean error message (no Python Traceback) on bad flags/files/symlinks
    bad_json = tmp_path / "bad.json"
    bad_json.write_text('{"schema_version": 2, "weeks": []}', encoding="utf-8")
    sym_out = tmp_path / "sym_out"
    sym_out.symlink_to(tmp_path / "real_target")
    for bad_args in (
        ["--out", str(tmp_path / "e1"), "--submission", "missing_equals"],
        ["--out", str(tmp_path / "e2"), "--submission", f"manual=Override={frontier_file}"],
        ["--out", str(tmp_path / "e3"), "--submission", f"badslug=Bad={bad_json}"],
        ["--out", str(tmp_path / "e4"), "--submission", f"nope=Missing={tmp_path / 'nope.json'}"],
        [
            "--out",
            str(tmp_path / "e5"),
            "--submission",
            f"dup=One={frontier_file}",
            "--submission",
            f"dup=Two={trained_file}",
        ],
        ["--out", str(ROOT / "src" / "forbidden_out"), "--seeds", "11"],
        ["--out", str(sym_out), "--seeds", "11"],
    ):
        failed = subprocess.run(
            [sys.executable, str(script_path), *bad_args],
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert failed.returncode != 0
        assert "Traceback" not in failed.stderr


def test_merge_with_export_3d_pack_and_serve_3d_cors(tmp_path):
    base_exporter = ROOT / "scripts" / "export_3d_pack.py"
    ai_exporter = ROOT / "scripts" / "export_ai_mistakes_3d.py"
    serve_script = ROOT / "scripts" / "serve_3d.py"

    shared_dir = tmp_path / "merged_pack"
    p1 = subprocess.run(
        [sys.executable, str(base_exporter), "--out", str(shared_dir), "--seed", "11"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert p1.returncode == 0, p1.stderr

    frontier_file = tmp_path / "claude_deadlock.json"
    frontier_file.write_text(
        json.dumps(
            _uniform_quarterly(
                robot=True, trays=False, route="all", maintenance=False, workers=[[1], [2], [4]]
            )
        ),
        encoding="utf-8",
    )
    p2 = subprocess.run(
        [
            sys.executable,
            str(ai_exporter),
            "--out",
            str(shared_dir),
            "--seeds",
            "11",
            "--submission",
            f"claude=Claude Opus (Frontier)={frontier_file}",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert p2.returncode == 0, p2.stderr

    merged = json.loads((shared_dir / "index.json").read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in merged["runs"]}
    # v1 bundles preserved alongside upgraded quarterly + custom AI bundles
    assert "v1-manual-seed11" in by_id
    assert "v1-reference-seed11" in by_id
    assert by_id["quarterly-claude-seed11"]["diagnostics"] == "quarterly-claude-seed11/diagnostics.json"
    assert by_id["quarterly-reference-seed11"]["diagnostics"] == "quarterly-reference-seed11/diagnostics.json"

    # Serve diagnostics.json and AI_MISTAKES_OVERLAY_RU.md via scripts/serve_3d.py --once
    for rel_url, expected_ct in (
        ("/quarterly-claude-seed11/diagnostics.json", "application/json"),
        ("/AI_MISTAKES_OVERLAY_RU.md", "text/markdown"),
    ):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        srv = subprocess.Popen(
            [
                sys.executable,
                str(serve_script),
                "--dir",
                str(shared_dir),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--once",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            body = None
            headers = None
            for _ in range(30):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}{rel_url}", timeout=2) as resp:
                        assert resp.status == 200
                        headers = {k.lower(): v for k, v in resp.headers.items()}
                        body = resp.read().decode("utf-8")
                        break
                except OSError:
                    time.sleep(0.05)
            assert body is not None and headers is not None
            assert headers.get("access-control-allow-origin") == "*"
            assert expected_ct in headers.get("content-type", "")
        finally:
            srv.wait(timeout=5)


def test_sacred_v1_files_untouched():
    from robotization_bench import contracts

    event_fields = [f.name for f in contracts.Event.__dataclass_fields__.values()]
    assert event_fields == [
        "tick",
        "kind",
        "order_id",
        "resource",
        "stage",
        "attempt",
        "end_tick",
    ]
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "diff",
            "9400595",
            "--",
            "src/robotization_bench/engine.py",
            "src/robotization_bench/scenarios.py",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.stdout == ""
