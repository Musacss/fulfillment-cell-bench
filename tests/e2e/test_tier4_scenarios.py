"""Tier 4: Complete end-to-end operator and judge acceptance scenarios (Scenarios #1..#8)."""

from __future__ import annotations

from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import py_compile
import re
import shutil
import subprocess
import time
import tomllib

import pytest

from .conftest import (
    CYRILLIC_RE,
    FORBIDDEN_PUBLIC_FILENAMES,
    REPO_ROOT,
    audit_v1_shift_bundle,
    best_phased_win_plan,
    discover_benchmark_v2_bundle,
    extract_eval_dict,
    extract_index_ids,
    extract_mcp_payload,
    has_cli_flag,
    lazy_attr,
    make_socket_client,
    make_week,
    mcp_proxy_cli_args,
    raw_http_request,
    run_mcp_session,
    run_staged_grade,
    run_staged_oracle,
    running_bench_daemon,
    running_cors_server,
    scan_repo_for_secrets,
    v2_buy_capex_idle,
    v2_manual_quarterly,
    v2_naive_all_unmaintained,
    v2_understaffed_carryover_plan,
    v2_unstaffed_jam_deadlock,
    v2_week11_token,
)


def test_t4_scenario1_holiday_automation_roi_study(world, replay_seeds, tmp_path):
    """Scenario 1: 12-Week Peak Holiday Automation ROI Study (F01..F07, F10)."""
    QuarterlyEpisode = lazy_attr("episode", "QuarterlyEpisode")
    solve = lazy_attr("reference", "solve")
    verify_quarterly_file = lazy_attr("verifier", "verify_quarterly_file")

    state_file = tmp_path / "roi_state.json"
    ep = QuarterlyEpisode(world, max_pilots=24, state_path=state_file)
    obs = ep.observe()
    assert obs["schema_version"] == 2
    assert obs["pilot_budget"]["max"] == 24

    plan = solve(ep)
    pilots_used = sum(1 for e in ep.log if e["action"] == "pilot")
    assert 1 <= pilots_used <= 20 < 24

    receipt = ep.submit(plan)
    assert receipt["terminal"] is True and receipt["plan"] == plan

    sub_path = tmp_path / "submission.json"
    sub_path.write_text(json.dumps(receipt["plan"], indent=2) + "\n", encoding="utf-8")
    assert sub_path.stat().st_size <= 16_384

    manual_path = tmp_path / "manual.json"
    manual_path.write_text(json.dumps(obs["manual"]) + "\n", encoding="utf-8")

    for seed_pool in (world["development_seeds"], replay_seeds):
        ev_ref = verify_quarterly_file(world, sub_path, seed_pool)
        ev_man = verify_quarterly_file(world, manual_path, seed_pool)
        assert ev_man.valid and ev_man.feasible and not ev_man.win
        assert Fraction(ev_man.reward_num, ev_man.reward_den) == Fraction(1, 5)
        assert ev_ref.valid and ev_ref.feasible and ev_ref.win
        assert Fraction(ev_ref.reward_num, ev_ref.reward_den) >= Fraction(7, 20)


def test_t4_scenario2_commissioning_failure_postmortem(world, tmp_path):
    """Scenario 2: Commissioning & Rigid-Automation Failure Post-Mortem (F02..F06, F14)."""
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    simulate_quarter = lazy_attr("quarterly", "simulate_quarter")
    verify_quarterly_file = lazy_attr("verifier", "verify_quarterly_file")
    evaluate_quarterly = lazy_attr("grading", "evaluate_quarterly")

    seeds = world["development_seeds"]

    # 1. Coupled carryover check on understaffed cell
    r_cong = simulate_quarter(world, parse_quarterly_plan(v2_understaffed_carryover_plan(), world), 11)
    assert any(
        r_cong.weeks[w].carryover_out > 0 and r_cong.weeks[w + 1].carryover_in == r_cong.weeks[w].carryover_out
        for w in range(11)
    )

    # 2. Commissioning + unmaintained route="all" wear escalation vs phased winning plan
    win_plan, ev_win = best_phased_win_plan(world, seeds)
    r_naive = simulate_quarter(world, parse_quarterly_plan(v2_naive_all_unmaintained(), world), 11)
    r_win = simulate_quarter(world, parse_quarterly_plan(win_plan, world), 11)
    assert r_naive.weeks[0].commissioning_active is True
    assert max(w.wear_end for w in r_naive.weeks) > max(w.wear_end for w in r_win.weeks)

    # 3. Exact rational hierarchy across post-mortem failure archetypes
    ev_nop = verify_quarterly_file(world, tmp_path / "missing_nop.json", seeds)
    ev_dead = evaluate_quarterly(world, v2_unstaffed_jam_deadlock(), seeds)
    ev_naive = evaluate_quarterly(world, v2_naive_all_unmaintained(), seeds)
    ev_idle = evaluate_quarterly(world, v2_buy_capex_idle(world), seeds)
    ev_man = evaluate_quarterly(world, v2_manual_quarterly(world), seeds)

    f_nop = Fraction(ev_nop.reward_num, ev_nop.reward_den)
    f_dead = Fraction(ev_dead.reward_num, ev_dead.reward_den)
    f_naive = Fraction(ev_naive.reward_num, ev_naive.reward_den)
    f_idle = Fraction(ev_idle.reward_num, ev_idle.reward_den)
    f_man = Fraction(ev_man.reward_num, ev_man.reward_den)
    f_win = Fraction(ev_win.reward_num, ev_win.reward_den)

    assert f_nop == Fraction(0, 1)
    assert Fraction(1, 10_000) <= f_dead <= Fraction(9, 100)
    assert ev_naive.win is False and f_naive <= Fraction(1, 5)
    assert Fraction(1, 10) < f_idle < f_man == Fraction(1, 5) < f_win


def test_t4_scenario3_musa_3d_showcase_export_cors_playback_and_trace_audit(run_cli, world, tmp_path):
    """Scenario 3: Musa 3D Warehouse Showcase Export & Live CORS Playback (F01, F04, F12..F14)."""
    pack_dir = tmp_path / "pack"
    export_cmd = ["scripts/export_3d_pack.py", "--out", str(pack_dir), "--seed", "11"]
    help_res = run_cli(["scripts/export_3d_pack.py", "--help"], timeout=8.0)
    if help_res.returncode == 0 and has_cli_flag(help_res.stdout + help_res.stderr, "--extra-plan"):
        extra_file = tmp_path / "extra_manual_q.json"
        extra_file.write_text(json.dumps(v2_manual_quarterly(world)), encoding="utf-8")
        export_cmd.extend(["--extra-plan", f"quarterly-extra-seed11={extra_file}"])
    res = run_cli(export_cmd, timeout=25.0)
    assert res.returncode == 0, res.stderr

    core_entries = {
        "v1-manual-seed11",
        "v1-reference-seed11",
        "quarterly-manual-seed11",
        "quarterly-reference-seed11",
    }
    q_names = sorted(
        d.name
        for d in pack_dir.iterdir()
        if d.is_dir() and (d / "quarter_manifest.json").is_file() and (d / "weeks").is_dir()
    )
    assert {"quarterly-manual-seed11", "quarterly-reference-seed11"} <= set(q_names)

    dl_root = tmp_path / "browser_cache"
    with running_cors_server(pack_dir) as (host, port, _):
        s_opt, h_opt, b_opt = raw_http_request(
            host,
            port,
            "OPTIONS",
            "/index.json",
            headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
        )
        assert s_opt == 204 and b_opt == b"" and h_opt.get("access-control-allow-origin") == "*"

        s_idx, h_idx, b_idx = raw_http_request(host, port, "GET", "/index.json")
        assert s_idx == 200 and "no-store" in h_idx.get("cache-control", "").lower()
        idx_doc = json.loads(b_idx.decode("utf-8"))
        idx_ids = extract_index_ids(idx_doc)
        assert len(idx_ids) >= 4 and core_entries <= idx_ids

        bundle_rels = ["v1-manual-seed11", "v1-reference-seed11"]
        for q_name in q_names:
            s_qm, _, b_qm = raw_http_request(host, port, "GET", f"/{q_name}/quarter_manifest.json")
            assert s_qm == 200
            q_dir = dl_root / q_name
            q_dir.mkdir(parents=True, exist_ok=True)
            (q_dir / "quarter_manifest.json").write_bytes(b_qm)
            for w in range(12):
                bundle_rels.append(f"{q_name}/weeks/week-{w:02d}")

        assert len(bundle_rels) >= 26
        for rel in bundle_rels:
            target = dl_root / rel
            target.mkdir(parents=True, exist_ok=True)
            for fname in ("manifest.json", "events.jsonl"):
                st, hdrs, body = raw_http_request(host, port, "GET", f"/{rel}/{fname}")
                assert st == 200 and hdrs.get("access-control-allow-origin") == "*"
                (target / fname).write_bytes(body)
            audit_v1_shift_bundle(target)

    qm_man = json.loads((dl_root / "quarterly-manual-seed11" / "quarter_manifest.json").read_text("utf-8"))
    qm_ref = json.loads((dl_root / "quarterly-reference-seed11" / "quarter_manifest.json").read_text("utf-8"))
    man_cost = qm_man.get("total_cost") or qm_man.get("quarter", {}).get("total_cost")
    ref_cost = qm_ref.get("total_cost") or qm_ref.get("quarter", {}).get("total_cost")
    if man_cost is not None and ref_cost is not None:
        assert ref_cost < man_cost


def test_t4_scenario4_harbor_blackbox_airgap_50x_restart_flood_oracle_and_grade(
    run_cli, world, short_sock_dir, tmp_path
):
    """Scenario 4: Harbor Black-Box Airgap & 50x Proxy Restart Audit (F06..F10, F14)."""
    task = tmp_path / "harbor_task"
    replay_file = REPO_ROOT / "evidence" / "replay_seeds.json"
    r1 = run_cli(["scripts/prepare_harbor.py", "--out", str(task), "--seeds-file", str(replay_file)])
    assert r1.returncode == 0, r1.stderr

    # Verify --overwrite refreshes existing staged task cleanly
    r2 = run_cli(
        ["scripts/prepare_harbor.py", "--out", str(task), "--seeds-file", str(replay_file), "--overwrite"]
    )
    assert r2.returncode == 0, r2.stderr

    pub = task / "environment" / "public"
    for p in pub.rglob("*"):
        if p.is_file():
            low_name = p.name.lower()
            assert p.name not in FORBIDDEN_PUBLIC_FILENAMES
            assert not (low_name.endswith(".json") and "seeds" in low_name)
            assert low_name != "candidate.json" and not low_name.startswith(".env")

    dockerfile = (task / "environment" / "Dockerfile").read_text(encoding="utf-8")
    assert "/srv/bench_daemon" in dockerfile and "bench-daemon-start" in dockerfile
    cfg = tomllib.loads((task / "task.toml").read_text(encoding="utf-8"))
    assert cfg["verifier"]["environment_mode"] == "separate"
    assert cfg["verifier"]["environment"]["network_mode"] == "no-network"

    daemon_src = task / "environment" / "daemon" / "src"
    manual_q = v2_manual_quarterly(world)

    # Session 1: 3 stdio proxy restarts + 50x socket client flood + stop() -> 0.0
    s1 = short_sock_dir / "s1.sock"
    sub1 = tmp_path / "sub1.json"
    with running_bench_daemon(
        s1,
        state_path=tmp_path / "st1.json",
        sub_path=sub1,
        log_path=tmp_path / "log1.json",
        max_pilots=3,
        python_path=daemon_src,
    ):
        p_args, p_env = mcp_proxy_cli_args(s1, python_path=pub / "src")
        for seed in (11, 29, 47):

            async def _p(session, sd=seed):
                r = await session.call_tool("pilot", {"plan": manual_q, "seed": sd, "trace": False})
                assert not r.isError

            run_mcp_session(p_args, _p, python_path=pub / "src", env_extra=p_env)

        for _ in range(50):
            with pytest.raises(Exception):
                make_socket_client(s1).pilot(manual_q, 11)

        make_socket_client(s1).stop()
        for _ in range(50):
            with pytest.raises(Exception):
                make_socket_client(s1).observe()

    v1_out = tmp_path / "verd1"
    verd1 = run_staged_grade(task, sub1, v1_out)
    ev1 = extract_eval_dict(verd1)
    assert (ev1["reward_num"], ev1["reward_den"]) == (0, 1)
    assert float((v1_out / "reward.txt").read_text(encoding="utf-8").strip()) == 0.0

    # Session 2: Airgapped oracle.py -> grade.py -> win >= 0.35
    s2 = short_sock_dir / "s2.sock"
    sub2 = tmp_path / "sub2.json"
    log2 = tmp_path / "log2.json"
    with running_bench_daemon(
        s2, state_path=tmp_path / "st2.json", sub_path=sub2, log_path=log2, python_path=daemon_src
    ):
        ora_res = run_staged_oracle(task, s2, sub2, log2)
        assert ora_res.returncode == 0, ora_res.stderr

    v2_out = tmp_path / "verd2"
    verd2 = run_staged_grade(task, sub2, v2_out)
    ev2 = extract_eval_dict(verd2)
    assert ev2["valid"] is True and ev2["feasible"] is True and ev2["win"] is True
    assert Fraction(ev2["reward_num"], ev2["reward_den"]) >= Fraction(7, 20)


def test_t4_scenario5_fifteen_minute_afterquery_judge_redteam_exploit_simulation(
    world, replay_seeds, tmp_path
):
    """Scenario 5: 15-Minute AfterQuery Judge Red-Team Exploit Simulation (F03, F06, F08, F09, F14)."""
    verify_quarterly_file = lazy_attr("verifier", "verify_quarterly_file")
    QuarterlyEpisode = lazy_attr("episode", "QuarterlyEpisode")
    solve = lazy_attr("reference", "solve")

    sym = tmp_path / "sym.json"
    sym.symlink_to(REPO_ROOT / "evidence" / "replay_seeds.json")
    fifo = tmp_path / "fifo.json"
    os.mkfifo(fifo)
    oversized = tmp_path / "over.json"
    oversized.write_bytes(b" " * 16_385)
    dup_key = tmp_path / "dup.json"
    dup_key.write_text('{"schema_version": 2, "schema_version": 2, "weeks": []}', encoding="utf-8")
    nan_file = tmp_path / "nan.json"
    nan_file.write_text('{"schema_version": NaN, "weeks": []}', encoding="utf-8")
    bool_int = tmp_path / "bool.json"
    bool_int.write_text('{"schema_version": true, "weeks": []}', encoding="utf-8")
    stop_null = tmp_path / "stop.json"
    stop_null.write_text("null\n", encoding="utf-8")
    partial_11 = tmp_path / "p11.json"
    partial_11.write_text(json.dumps({"schema_version": 2, "weeks": [make_week() for _ in range(11)]}), "utf-8")

    for zero_target in (
        tmp_path / "missing_nop.json",
        stop_null,
        partial_11,
        sym,
        fifo,
        oversized,
        dup_key,
        nan_file,
        bool_int,
    ):
        ev = verify_quarterly_file(world, zero_target, replay_seeds)
        assert ev.valid is False and Fraction(ev.reward_num, ev.reward_den) == Fraction(0, 1)

    def _grade_plan(name: str, obj: dict) -> Fraction:
        f = tmp_path / f"{name}.json"
        f.write_text(json.dumps(obj), encoding="utf-8")
        ev = verify_quarterly_file(world, f, replay_seeds)
        return Fraction(ev.reward_num, ev.reward_den)

    r_dead = _grade_plan("deadlock", v2_unstaffed_jam_deadlock())
    r_under = _grade_plan("under", v2_understaffed_carryover_plan())
    r_idle = _grade_plan("idle", v2_buy_capex_idle(world))
    r_tok = _grade_plan("tok", v2_week11_token(world))
    r_man = _grade_plan("man", v2_manual_quarterly(world))
    ref_plan = solve(QuarterlyEpisode(world))
    r_ref = _grade_plan("ref", ref_plan)

    assert Fraction(1, 10_000) <= r_dead <= Fraction(9, 100)
    assert Fraction(1, 10_000) <= r_under <= Fraction(9, 100)
    assert Fraction(1, 10) < r_idle < r_man == Fraction(1, 5)
    assert Fraction(1, 10) < r_tok <= r_man
    assert r_ref >= Fraction(7, 20)

    async def _devtools(session):
        rt = extract_mcp_payload(await session.call_tool("redteam_reward_exploits", {"seeds_mode": "replay"}))
        au = extract_mcp_payload(await session.call_tool("audit_3d_replay_trace", {"plan": ref_plan, "seed": 11}))
        return rt, au

    rt, au = run_mcp_session([str(REPO_ROOT / ".agents" / "mcp" / "devtools_mcp.py")], _devtools)
    assert rt["hierarchy_intact"] is True and rt["exploits_beating_reference"] == []
    assert au["ok"] is True


def test_t4_scenario6_judge_one_command_cli_v2_default_and_v1_legacy_workflow(run_cli, tmp_path):
    """Scenario 6: One-Command Judge CLI Benchmark (v2 Default + v1 Legacy Compat) (F06, F07, F10, F12, F16)."""
    v2_out = tmp_path / "v2_default"
    r_v2 = run_cli(["scripts/run_bench.py", "--out", str(v2_out)], timeout=25.0)
    assert r_v2.returncode == 0, r_v2.stderr
    for fname in ("submission.json", "episode.json", "comparison.md", "results.json"):
        assert (v2_out / fname).is_file()

    res_v2 = json.loads((v2_out / "results.json").read_text(encoding="utf-8"))
    assert res_v2["schema_version"] == 2
    assert res_v2["pilot_count"] <= 24
    assert (res_v2["results"]["manual"]["reward_num"], res_v2["results"]["manual"]["reward_den"]) == (1, 5)
    ref_ev = res_v2["results"]["reference"]
    assert ref_ev["win"] is True and Fraction(ref_ev["reward_num"], ref_ev["reward_den"]) >= Fraction(7, 20)
    assert not CYRILLIC_RE.search((v2_out / "comparison.md").read_text(encoding="utf-8"))

    # Legacy v1 CLI commands
    r_val = run_cli(
        [
            "-m",
            "robotization_bench.cli",
            "validate",
            "--plan",
            str(REPO_ROOT / "data/plans/manual.json"),
        ]
    )
    assert r_val.returncode == 0, r_val.stderr

    ev_out = tmp_path / "v1_events.jsonl"
    r_pil = run_cli(
        [
            "-m",
            "robotization_bench.cli",
            "pilot",
            "--plan",
            str(REPO_ROOT / "data/plans/manual.json"),
            "--seed",
            "11",
            "--events",
            str(ev_out),
        ]
    )
    assert r_pil.returncode == 0, r_pil.stderr
    assert ev_out.stat().st_size > 0

    seeds = tmp_path / "s821.json"
    seeds.write_text("[821]\n", encoding="utf-8")
    v1_out = tmp_path / "v1_legacy"
    r_cmp = run_cli(
        [
            "-m",
            "robotization_bench.cli",
            "compare",
            "--plan",
            str(REPO_ROOT / "data/plans/manual.json"),
            "--seeds-file",
            str(seeds),
            "--out",
            str(v1_out),
        ],
        timeout=20.0,
    )
    assert r_cmp.returncode == 0, r_cmp.stderr
    assert not CYRILLIC_RE.search((v1_out / "comparison.md").read_text(encoding="utf-8"))


def test_t4_scenario7_offline_verda_evidence_verification_and_tamper_defense(
    run_cli, world, replay_seeds, tmp_path
):
    """Scenario 7: Offline Verda Evidence Verification & Tamper Detection (F06, F11, F15, F16)."""
    ev_dir = REPO_ROOT / "evidence" / "benchmark-v2"
    harbor_runs = REPO_ROOT / "evidence" / "harbor-runs"
    assert ev_dir.is_dir() and harbor_runs.is_dir()

    t0 = time.monotonic()
    r_ok = run_cli(["scripts/run_bench.py", "--verify-evidence", str(ev_dir)], timeout=10.0)
    elapsed = time.monotonic() - t0
    assert r_ok.returncode == 0, r_ok.stderr
    assert elapsed < 5.0

    bundle = discover_benchmark_v2_bundle(ev_dir)
    blind_seeds = bundle["blind_seeds"]
    assert set(blind_seeds).isdisjoint(set(world["development_seeds"]))
    assert set(blind_seeds).isdisjoint(set(replay_seeds))
    digest = hashlib.sha256(bundle["blind_seeds_path"].read_bytes()).hexdigest()
    assert digest in json.dumps([d for _, d in bundle["json_docs"]]) or any(
        digest in txt for _, txt in bundle.get("text_docs", [])
    )

    # Tamper 1: reward.txt
    c1 = tmp_path / "c1"
    shutil.copytree(ev_dir, c1)
    next(c1.rglob("reward.txt")).write_text("0.999999\n", encoding="utf-8")
    assert run_cli(["scripts/run_bench.py", "--verify-evidence", str(c1)]).returncode != 0

    # Tamper 2: blind_seeds.json
    c2 = tmp_path / "c2"
    shutil.copytree(ev_dir, c2)
    bs2 = next(c2.rglob("blind_seeds.json"))
    arr2 = json.loads(bs2.read_text(encoding="utf-8"))
    arr2[0] += 7
    bs2.write_text(json.dumps(arr2) + "\n", encoding="utf-8")
    assert run_cli(["scripts/run_bench.py", "--verify-evidence", str(c2)]).returncode != 0

    # Tamper 3: submission.json
    c3 = tmp_path / "c3"
    shutil.copytree(ev_dir, c3)
    subs3 = [
        p
        for p in sorted(c3.rglob("submission.json"))
        if any(k in p.as_posix().lower() for k in ("oracle", "reference", "post", "grpo"))
    ]
    assert subs3
    subs3[0].write_text(json.dumps(v2_manual_quarterly(world)) + "\n", encoding="utf-8")
    assert run_cli(["scripts/run_bench.py", "--verify-evidence", str(c3)]).returncode != 0


def test_t4_scenario8_verda_ops_packaging_secret_hygiene_and_bilingual_docs_audit():
    """Scenario 8: Verda Cloud Ops Readiness, Secret Hygiene & Documentation Audit (F09, F11, F12, F15, F16)."""
    proj = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert proj["project"]["requires-python"].replace(" ", "") == ">=3.12,<3.13"
    assert proj["project"]["dependencies"] == []
    assert (REPO_ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.12"

    # Ready-to-run Harbor task & gitignore checks
    assert (REPO_ROOT / "tasks" / "fulfillment-cell-bench" / "task.toml").is_file()
    assert (
        subprocess.run(
            ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", "tasks/fulfillment-cell-bench"],
            capture_output=True,
        ).returncode
        != 0
    )
    assert (
        subprocess.run(
            ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", ".env"],
            capture_output=True,
        ).returncode
        == 0
    )

    # Verda scripts audit
    verda_dir = REPO_ROOT / "scripts" / "verda"
    for sh_name in ("provision_check.sh", "run_harbor_matrix.sh", "sync_evidence.sh"):
        p = verda_dir / sh_name
        assert p.is_file()
        assert subprocess.run(["bash", "-n", str(p)], capture_output=True).returncode == 0
    for py_name in ("generate_sft_traces.py", "train_grpo_qwen7b.py"):
        p = verda_dir / py_name
        assert p.is_file()
        py_compile.compile(str(p), doraise=True)

    prov_txt = (verda_dir / "provision_check.sh").read_text(encoding="utf-8")
    assert any(
        tok in prov_txt
        for tok in ("shutdown -h", "HF_HOME", "/tmp/fast-cache", "H200", "df -h", "save_total_limit")
    )
    grpo_txt = (verda_dir / "train_grpo_qwen7b.py").read_text(encoding="utf-8")
    assert any(
        tok in grpo_txt
        for tok in ("CUDA_VISIBLE_DEVICES", "cuda:0", "gpu_memory_utilization", "vllm", "H200")
    )
    assert re.search(
        r"qwen3\.?5-9b|qwen3-8b|qwen2\.?5-7b|qwen|--model-id|H200_ENV_READY\.json",
        grpo_txt,
        re.IGNORECASE,
    )
    mat_txt = (verda_dir / "run_harbor_matrix.sh").read_text(encoding="utf-8")
    mat_uncommented = "\n".join(ln.split("#", 1)[0] for ln in mat_txt.splitlines())
    assert "gemini/" in mat_uncommented and "openai/" in mat_uncommented
    assert not re.search(r"\bssh\b|verda-junction", mat_uncommented)

    # Docs & secret hygiene
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert not CYRILLIC_RE.search(readme) and 40 <= len(readme.splitlines()) <= 180
    for doc_rel in (
        "AGENT.md",
        "docs/SPEC.md",
        "docs/CONTRACTS.md",
        "docs/HARBOR.md",
        "docs/DEMO_PLAYBOOK_10MIN.md",
    ):
        p = REPO_ROOT / doc_rel
        assert p.is_file() and not CYRILLIC_RE.search(p.read_text(encoding="utf-8"))

    musa_doc = REPO_ROOT / "docs" / "ru" / "3D_HANDOFF_MUSA.md"
    assert musa_doc.is_file() and CYRILLIC_RE.search(musa_doc.read_text(encoding="utf-8"))

    assert scan_repo_for_secrets(REPO_ROOT) == []
