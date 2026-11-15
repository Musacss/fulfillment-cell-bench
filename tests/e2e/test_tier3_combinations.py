"""Tier 3: Cross-feature pairwise and multi-module interaction tests (18 tests)."""

from __future__ import annotations

import asyncio
from fractions import Fraction
import json
from pathlib import Path
from typing import Any

import pytest

from .conftest import (
    CLI_COUNT_FLAGS,
    CLI_OUTPUT_FLAGS,
    CYRILLIC_RE,
    ECONOMY_COST_KEYS_V1,
    EVENT_KINDS_V1,
    PYTHON_BIN,
    REPO_ROOT,
    audit_v1_shift_bundle,
    best_phased_win_plan,
    discover_benchmark_v2_bundle,
    extract_eval_dict,
    extract_mcp_payload,
    lazy_attr,
    lazy_mod,
    make_socket_client,
    make_week,
    mcp_proxy_cli_args,
    pick_cli_flag,
    raw_http_request,
    run_mcp_session,
    run_staged_grade,
    run_staged_oracle,
    running_bench_daemon,
    running_cors_server,
    send_unix_jsonl,
    v2_buy_capex_idle,
    v2_manual_quarterly,
    v2_naive_all_unmaintained,
    v2_phased_win_candidates,
    v2_understaffed_carryover_plan,
    v2_unstaffed_jam_deadlock,
    v2_week11_token,
)


def _find_v2_plans(obj: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(obj, dict):
        if obj.get("schema_version") == 2 and isinstance(obj.get("weeks"), list) and len(obj["weeks"]) == 12:
            found.append(obj)
        else:
            for val in obj.values():
                found.extend(_find_v2_plans(val))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_find_v2_plans(item))
    elif isinstance(obj, str) and '"schema_version"' in obj and '"weeks"' in obj:
        try:
            found.extend(_find_v2_plans(json.loads(obj)))
        except Exception:
            pass
    return found


def test_t3_f01_f03_f04_wire_to_v1_trace_pipeline(world):
    decode_any_plan = lazy_attr("validation", "decode_any_plan")
    simulate_quarter = lazy_attr("quarterly", "simulate_quarter")

    wire_txt = json.dumps(v2_phased_win_candidates()[0])
    qp = decode_any_plan(wire_txt, world)
    qr = simulate_quarter(world, qp, 11, trace=True)
    assert len(qr.weeks) == 12
    for wr in qr.weeks:
        assert wr.shift_plan.schema_version == 1
        assert wr.scenario.schema_version == 1
        pairs = [(o.arrival, o.id) for o in wr.scenario.orders]
        assert pairs == sorted(pairs)
        r = wr.raw
        assert r.total == r.good + r.escaped + r.scrap + r.unfinished
        assert len(r.events) > 0
        assert all(ev.kind in EVENT_KINDS_V1 for ev in r.events)


def test_t3_f02_f04_f05_wear_carryover_cost_coupling(world):
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    simulate_quarter = lazy_attr("quarterly", "simulate_quarter")

    win_dict, _ = best_phased_win_plan(world, world["development_seeds"])
    r_naive = simulate_quarter(world, parse_quarterly_plan(v2_naive_all_unmaintained(), world), 11, trace=False)
    r_win = simulate_quarter(world, parse_quarterly_plan(win_dict, world), 11, trace=False)

    for qr in (r_naive, r_win):
        assert qr.total_cost == sum(w.week_economy.total for w in qr.weeks)
        for wr in qr.weeks:
            assert set(wr.shift_economy.costs.keys()) == ECONOMY_COST_KEYS_V1

    assert max(w.wear_end for w in r_naive.weeks) >= max(w.wear_end for w in r_win.weeks)
    assert r_win.total_cost < r_naive.total_cost


def test_t3_f03_f05_f06_five_archetype_reward_chain(world, tmp_path):
    verify_quarterly_file = lazy_attr("verifier", "verify_quarterly_file")
    evaluate_any = lazy_attr("grading", "evaluate_any")
    seeds = world["development_seeds"]

    archetypes = {
        "invalid": {"schema_version": 2, "weeks": []},
        "deadlock": v2_unstaffed_jam_deadlock(),
        "idle": v2_buy_capex_idle(world),
        "token": v2_week11_token(world),
        "manual": v2_manual_quarterly(world),
    }
    scores: dict[str, Fraction] = {}
    for name, payload in archetypes.items():
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        ev_f = verify_quarterly_file(world, p, seeds)
        ev_m = evaluate_any(world, payload, seeds)
        assert (ev_f.reward_num, ev_f.reward_den) == (ev_m.reward_num, ev_m.reward_den)
        scores[name] = Fraction(ev_f.reward_num, ev_f.reward_den)

    assert scores["invalid"] == Fraction(0, 1)
    assert Fraction(1, 10_000) <= scores["deadlock"] <= Fraction(9, 100)
    assert Fraction(1, 10) < scores["idle"] < scores["manual"] == Fraction(1, 5)
    assert Fraction(1, 10) < scores["token"] <= scores["manual"]


def test_t3_f04_f06_f07_episode_pilot_verifier_parity(world, tmp_path):
    QuarterlyEpisode = lazy_attr("episode", "QuarterlyEpisode")
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    simulate_quarter = lazy_attr("quarterly", "simulate_quarter")
    verify_quarterly_file = lazy_attr("verifier", "verify_quarterly_file")

    state_file = tmp_path / "state.json"
    ep = QuarterlyEpisode(world, max_pilots=5, state_path=state_file)
    obs = ep.observe()
    manual_q = obs["manual"]
    pilot_out = ep.pilot(manual_q, 11, trace=False)

    direct = simulate_quarter(world, parse_quarterly_plan(manual_q, world), 11, trace=False)
    assert pilot_out["purchase"] == direct.purchase
    assert pilot_out["total_cost"] == direct.total_cost
    assert pilot_out["labor_ticks"] == direct.labor_ticks

    ep_reloaded = QuarterlyEpisode(world, max_pilots=5, state_path=state_file)
    rec = ep_reloaded.submit(manual_q)
    sub_file = tmp_path / "submission.json"
    sub_file.write_text(json.dumps(rec["plan"]), encoding="utf-8")
    ev = verify_quarterly_file(world, sub_file, world["development_seeds"])
    assert Fraction(ev.reward_num, ev.reward_den) == Fraction(1, 5)


def test_t3_f07_f08_f10_reference_solver_over_mcp_proxy_stdio_and_socket_daemon(
    world, short_sock_dir, tmp_path
):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    solve = lazy_attr("reference", "solve")
    verify_quarterly_file = lazy_attr("verifier", "verify_quarterly_file")

    sock = short_sock_dir / "t3p.sock"
    state = tmp_path / "state.json"
    sub = tmp_path / "sub.json"
    log = tmp_path / "log.json"

    with running_bench_daemon(sock, state_path=state, sub_path=sub, log_path=log):
        proxy_args, proxy_env = mcp_proxy_cli_args(sock)
        env = {
            "PYTHONPATH": str(REPO_ROOT / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
            **proxy_env,
        }

        async def _solve_over_mcp():
            import os

            merged_env = {**os.environ, **env}
            params = StdioServerParameters(command=str(PYTHON_BIN), args=proxy_args, env=merged_env)
            async with stdio_client(params) as (r_stream, w_stream):
                async with ClientSession(r_stream, w_stream) as session:
                    await session.initialize()

                    loop = asyncio.get_running_loop()

                    class SyncBridge:
                        def observe(self):
                            fut = asyncio.run_coroutine_threadsafe(session.call_tool("observe", {}), loop)
                            return extract_mcp_payload(fut.result(timeout=10.0))

                        def pilot(self, plan, seed: int, *, trace: bool = False):
                            fut = asyncio.run_coroutine_threadsafe(
                                session.call_tool("pilot", {"plan": plan, "seed": seed, "trace": trace}),
                                loop,
                            )
                            return extract_mcp_payload(fut.result(timeout=10.0))

                    plan = await asyncio.to_thread(solve, SyncBridge())
                    sub_r = await session.call_tool("submit", {"plan": plan})
                    assert not sub_r.isError
                    return plan

        plan = asyncio.run(_solve_over_mcp())

    assert sub.is_file()
    log_entries = json.loads(log.read_text(encoding="utf-8"))
    assert sum(1 for e in log_entries if e["action"] == "pilot") <= 20
    ev = verify_quarterly_file(world, sub, world["development_seeds"])
    assert ev.valid is True and ev.win is True
    assert Fraction(ev.reward_num, ev.reward_den) >= Fraction(7, 20)
    assert json.loads(sub.read_text(encoding="utf-8")) == plan


def test_t3_f06_f08_f09_harbor_staged_daemon_budget_cap_and_trusted_grade(
    run_cli, world, short_sock_dir, tmp_path
):
    seeds = tmp_path / "seeds.json"
    seeds.write_text("[474747]\n", encoding="utf-8")
    task = tmp_path / "task"
    res = run_cli(["scripts/prepare_harbor.py", "--out", str(task), "--seeds-file", str(seeds)])
    assert res.returncode == 0, res.stderr

    sock = short_sock_dir / "t3h.sock"
    state = tmp_path / "state.json"
    sub = tmp_path / "sub.json"
    log = tmp_path / "log.json"
    manual_q = v2_manual_quarterly(world)

    with running_bench_daemon(
        sock,
        state_path=state,
        sub_path=sub,
        log_path=log,
        max_pilots=4,
        python_path=task / "environment" / "daemon" / "src",
    ):
        for s in (11, 29, 47, 11):
            c = make_socket_client(sock)
            c.pilot(manual_q, s)
        with pytest.raises(Exception):
            make_socket_client(sock).pilot(manual_q, 29)
        make_socket_client(sock).submit(manual_q)

    verdict = run_staged_grade(task, sub, tmp_path / "verdict")
    ev = extract_eval_dict(verdict)
    assert ev["valid"] is True
    assert (ev["reward_num"], ev["reward_den"]) == (1, 5)


def test_t3_f09_f10_staged_harbor_oracle_airgapped_solve_and_replay_seeds_win(
    run_cli, short_sock_dir, tmp_path
):
    task = tmp_path / "task"
    replay_file = REPO_ROOT / "evidence" / "replay_seeds.json"
    res = run_cli(["scripts/prepare_harbor.py", "--out", str(task), "--seeds-file", str(replay_file)])
    assert res.returncode == 0, res.stderr

    sock = short_sock_dir / "ora.sock"
    state = tmp_path / "state.json"
    sub = tmp_path / "sub.json"
    log = tmp_path / "log.json"

    with running_bench_daemon(
        sock,
        state_path=state,
        sub_path=sub,
        log_path=log,
        python_path=task / "environment" / "daemon" / "src",
    ):
        o_res = run_staged_oracle(task, sock, sub, log)
        assert o_res.returncode == 0, o_res.stderr

    verdict = run_staged_grade(task, sub, tmp_path / "verdict")
    ev = extract_eval_dict(verdict)
    assert ev["valid"] is True and ev["feasible"] is True and ev["win"] is True
    assert Fraction(ev["reward_num"], ev["reward_den"]) >= Fraction(7, 20)


def test_t3_f10_f11_sft_trace_generator_plans_pass_quarterly_validator_and_grader(
    run_cli, world, tmp_path
):
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    evaluate_quarterly = lazy_attr("grading", "evaluate_quarterly")

    script = "scripts/verda/generate_sft_traces.py"
    help_res = run_cli([script, "--help"], timeout=8.0)
    assert help_res.returncode == 0, help_res.stderr
    help_txt = help_res.stdout + help_res.stderr

    out_file = tmp_path / "sft_t3.jsonl"
    cmd = [script]
    out_flag = pick_cli_flag(help_txt, CLI_OUTPUT_FLAGS)
    if out_flag is not None:
        cmd.extend([out_flag, str(out_file)])
    count_flag = pick_cli_flag(help_txt, CLI_COUNT_FLAGS)
    if count_flag is not None:
        cmd.extend([count_flag, "2"])

    res = run_cli(cmd, timeout=20.0)
    assert res.returncode == 0, res.stderr
    records = [json.loads(ln) for ln in out_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    plans = _find_v2_plans(records)
    assert len(plans) >= 1, "Expected valid QuarterlyPlan submissions inside generated SFT JSONL traces"
    for p in plans:
        qp = parse_quarterly_plan(p, world)
        assert len(qp.weeks) == 12
        ev = evaluate_quarterly(world, p, world["development_seeds"])
        assert ev.valid is True


def test_t3_f04_f12_f14_exported_quarterly_3d_pack_audited_by_devtools_mcp(run_cli, tmp_path):
    pack = tmp_path / "pack"
    res = run_cli(["scripts/export_3d_pack.py", "--out", str(pack), "--seed", "11"], timeout=20.0)
    assert res.returncode == 0, res.stderr

    q_ref = pack / "quarterly-reference-seed11"
    for w in range(12):
        audit_v1_shift_bundle(q_ref / "weeks" / f"week-{w:02d}")

    qm = json.loads((q_ref / "quarter_manifest.json").read_text(encoding="utf-8"))
    ref_plan = qm.get("plan")
    if ref_plan is None:
        found = _find_v2_plans(qm)
        assert found
        ref_plan = found[0]

    async def _audit(session):
        return extract_mcp_payload(
            await session.call_tool("audit_3d_replay_trace", {"plan": ref_plan, "seed": 11})
        )

    audit_res = run_mcp_session([str(REPO_ROOT / ".agents" / "mcp" / "devtools_mcp.py")], _audit)
    assert audit_res["ok"] is True


def test_t3_f08_f09_f14_untrusted_mcp_submissions_preserve_hierarchy_in_harbor_grade(
    run_cli, world, short_sock_dir, tmp_path
):
    seeds = tmp_path / "seeds.json"
    seeds.write_text("[474747]\n", encoding="utf-8")
    task = tmp_path / "task"
    res = run_cli(["scripts/prepare_harbor.py", "--out", str(task), "--seeds-file", str(seeds)])
    assert res.returncode == 0, res.stderr

    daemon_src = task / "environment" / "daemon" / "src"

    def _run_case(idx: int, fn) -> Fraction:
        sock = short_sock_dir / f"c{idx}.sock"
        state = tmp_path / f"st{idx}.json"
        sub = tmp_path / f"sub{idx}.json"
        log = tmp_path / f"log{idx}.json"
        with running_bench_daemon(
            sock, state_path=state, sub_path=sub, log_path=log, python_path=daemon_src
        ):
            fn(sock, sub, log)
        verdict = run_staged_grade(task, sub, tmp_path / f"verd{idx}")
        ev = extract_eval_dict(verdict)
        return Fraction(ev["reward_num"], ev["reward_den"])

    def _run_ora(s: Path, sub: Path, log: Path) -> None:
        o_res = run_staged_oracle(task, s, sub, log)
        assert o_res.returncode == 0, o_res.stderr

    r_stop = _run_case(0, lambda s, sub, log: make_socket_client(s).stop())
    r_partial = _run_case(
        1,
        lambda s, sub, log: send_unix_jsonl(
            s, {"action": "submit", "args": {"plan": {"schema_version": 2, "weeks": [make_week()]}}}
        ),
    )
    r_idle = _run_case(2, lambda s, sub, log: make_socket_client(s).submit(v2_buy_capex_idle(world)))
    r_ora = _run_case(3, _run_ora)

    assert Fraction(0, 1) == r_stop == r_partial < r_idle < Fraction(1, 5) < r_ora
    assert r_ora >= Fraction(7, 20)


def test_t3_f04_f12_coupled_quarterly_carryover_preserved_in_3d_week_manifests(world, tmp_path):
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    simulate_quarter = lazy_attr("quarterly", "simulate_quarter")
    export_quarter_pack = lazy_attr("reporting", "export_quarter_pack")

    qp = parse_quarterly_plan(v2_understaffed_carryover_plan(), world)
    qr = simulate_quarter(world, qp, 11, trace=True)
    out = tmp_path / "congested_pack"
    export_quarter_pack(world, qr, qp, out)

    manifests = []
    for w in range(12):
        res = audit_v1_shift_bundle(out / "weeks" / f"week-{w:02d}")
        manifests.append(res["manifest"])

    checked = 0
    cap = world["quarterly"]["carryover_cap"]
    for w in range(11):
        unfinished_w = manifests[w]["raw"]["unfinished"]
        if unfinished_w > 0:
            checked += 1
            carried_next = [
                o for o in manifests[w + 1]["scenario"]["orders"] if o["arrival"] == 0 and o["due"] == 0
            ]
            assert len(carried_next) == min(unfinished_w, cap)
    assert checked > 0


def test_t3_f10_f12_f13_reference_quarterly_pack_served_over_cors_matches_disk(world, tmp_path):
    QuarterlyEpisode = lazy_attr("episode", "QuarterlyEpisode")
    solve = lazy_attr("reference", "solve")
    parse_quarterly_plan = lazy_attr("validation", "parse_quarterly_plan")
    simulate_quarter = lazy_attr("quarterly", "simulate_quarter")
    export_quarter_pack = lazy_attr("reporting", "export_quarter_pack")

    plan_dict = solve(QuarterlyEpisode(world))
    qp = parse_quarterly_plan(plan_dict, world)
    qr = simulate_quarter(world, qp, 11, trace=True)

    served = tmp_path / "served_qpack"
    export_quarter_pack(world, qr, qp, served)

    dl = tmp_path / "downloaded_qpack"
    with running_cors_server(served) as (host, port, _):
        s_opt, h_opt, _ = raw_http_request(host, port, "OPTIONS", "/quarter_manifest.json")
        assert s_opt == 204 and h_opt.get("access-control-allow-origin") == "*"

        for w in range(12):
            rel = f"weeks/week-{w:02d}"
            target_dir = dl / rel
            target_dir.mkdir(parents=True)
            for fname in ("manifest.json", "events.jsonl"):
                st, hdrs, body = raw_http_request(host, port, "GET", f"/{rel}/{fname}")
                assert st == 200 and hdrs.get("access-control-allow-origin") == "*"
                (target_dir / fname).write_bytes(body)
            audit_v1_shift_bundle(target_dir)


def test_t3_f06_f12_f16_run_bench_external_v2_plan_matches_verifier_and_compare(
    run_cli, world, tmp_path
):
    verify_quarterly_file = lazy_attr("verifier", "verify_quarterly_file")

    plan_dict, _ = best_phased_win_plan(world, world["development_seeds"])
    plan_path = tmp_path / "ext_plan.json"
    plan_path.write_text(json.dumps(plan_dict), encoding="utf-8")
    seeds_path = tmp_path / "ext_seeds.json"
    seeds_path.write_text("[9101, 9102]\n", encoding="utf-8")
    out_dir = tmp_path / "bench_ext"

    res = run_cli(
        [
            "scripts/run_bench.py",
            "--plan",
            str(plan_path),
            "--seeds-file",
            str(seeds_path),
            "--out",
            str(out_dir),
        ],
        timeout=25.0,
    )
    assert res.returncode == 0, res.stderr
    direct_ev = verify_quarterly_file(world, plan_path, [9101, 9102])
    bench_ev = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))["results"]["submitted"]
    assert (bench_ev["reward_num"], bench_ev["reward_den"]) == (
        direct_ev.reward_num,
        direct_ev.reward_den,
    )
    comp = (out_dir / "comparison.md").read_text(encoding="utf-8")
    assert not CYRILLIC_RE.search(comp)
    assert f"{direct_ev.reward_num}/{direct_ev.reward_den}" in comp


def test_t3_f06_f15_f16_verify_evidence_matches_direct_verifier_across_all_blind_runs(run_cli, world):
    verify_quarterly_file = lazy_attr("verifier", "verify_quarterly_file")
    bundle = discover_benchmark_v2_bundle()
    blind_seeds = bundle["blind_seeds"]

    res = run_cli(["scripts/run_bench.py", "--verify-evidence", str(bundle["bundle_dir"])], timeout=10.0)
    assert res.returncode == 0, res.stderr

    checked_subs = 0
    checked_rewards = 0
    for sub in bundle["bundle_dir"].rglob("submission.json"):
        ev = verify_quarterly_file(world, sub, blind_seeds)
        checked_subs += 1
        root_trial = sub.parent.parent if sub.parent.name == "artifacts" else sub.parent
        for rw_cand in (
            root_trial / "verifier" / "reward.txt",
            root_trial / "reward.txt",
            sub.with_name("reward.txt"),
        ):
            if rw_cand.is_file():
                rw_val = float(rw_cand.read_text(encoding="utf-8").strip())
                assert rw_val == pytest.approx(ev.reward_num / ev.reward_den)
                checked_rewards += 1
                break
    assert checked_subs >= 6
    assert checked_rewards >= 1


def test_t3_f11_f15_four_way_seed_disjointness_across_world_replay_verda_and_blind(
    world, replay_seeds
):
    bundle = discover_benchmark_v2_bundle()
    dev_set = set(world["development_seeds"])
    rep_set = set(replay_seeds)
    blind_set = set(bundle["blind_seeds"])

    assert dev_set.isdisjoint(rep_set)
    assert dev_set.isdisjoint(blind_set)
    assert rep_set.isdisjoint(blind_set)

    for script_name in ("generate_sft_traces.py", "train_grpo_qwen7b.py", "run_harbor_matrix.sh"):
        p = REPO_ROOT / "scripts" / "verda" / script_name
        assert p.is_file()
        txt = p.read_text(encoding="utf-8")
        assert "development_seeds" in txt or "replay_seeds" in txt or "disjoint" in txt.lower()


def test_t3_f07_f12_f16_public_docs_contracts_match_live_observe_and_manifest_keys(world):
    QuarterlyEpisode = lazy_attr("episode", "QuarterlyEpisode")
    build_shift_manifest = lazy_attr("reporting", "build_shift_manifest")
    validation = lazy_mod("validation")
    scenarios = lazy_mod("scenarios")
    engine = lazy_mod("engine")
    economics = lazy_mod("economics")

    obs = QuarterlyEpisode(world).observe()
    spec_text = (REPO_ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
    assert obs["rules"] == spec_text
    assert not CYRILLIC_RE.search(obs["rules"])

    contracts_doc = (REPO_ROOT / "docs" / "CONTRACTS.md").read_text(encoding="utf-8")
    for field_name in ("schema_version", "weeks", "maintenance", "pilot_budget"):
        assert field_name in contracts_doc

    p1 = validation.parse_plan(
        json.loads((REPO_ROOT / "data" / "plans" / "manual.json").read_text(encoding="utf-8")), world
    )
    d1 = scenarios.generate(world, 11)
    r1 = engine.simulate(world, p1, d1, trace=False)
    m1 = build_shift_manifest(world, p1, d1, r1, economics.calculate(world, p1, r1))
    assert m1["replay_format"] == "robotization-bench.replay.v1"


def test_t3_f09_f16_materialized_harbor_task_matches_fresh_prepare_harbor_docs_and_oracle(
    run_cli, tmp_path
):
    mat_dir = REPO_ROOT / "tasks" / "fulfillment-cell-bench"
    assert mat_dir.is_dir(), f"Missing {mat_dir}"

    inst_text = (mat_dir / "instruction.md").read_text(encoding="utf-8")
    agent_text = (REPO_ROOT / "AGENT.md").read_text(encoding="utf-8")
    assert not CYRILLIC_RE.search(inst_text)
    assert inst_text == agent_text

    for doc_name in ("SPEC.md", "CONTRACTS.md"):
        pub_doc = mat_dir / "environment" / "public" / "docs" / doc_name
        assert pub_doc.is_file(), f"Missing {pub_doc}"
        pub_doc_txt = pub_doc.read_text(encoding="utf-8")
        assert not CYRILLIC_RE.search(pub_doc_txt)
        assert pub_doc_txt == (REPO_ROOT / "docs" / doc_name).read_text(encoding="utf-8")

    pub_world = mat_dir / "environment" / "public" / "data" / "world_spec.json"
    if pub_world.is_file():
        assert pub_world.read_text(encoding="utf-8") == (REPO_ROOT / "data" / "world_spec.json").read_text(
            encoding="utf-8"
        )

    fresh_dir = tmp_path / "fresh_task"
    seeds = tmp_path / "s.json"
    seeds.write_text("[37281939]\n", encoding="utf-8")
    res = run_cli(["scripts/prepare_harbor.py", "--out", str(fresh_dir), "--seeds-file", str(seeds)])
    assert res.returncode == 0, res.stderr
    assert (mat_dir / "solution" / "oracle.py").read_text(encoding="utf-8") == (
        fresh_dir / "solution" / "oracle.py"
    ).read_text(encoding="utf-8")


def test_t3_f11_f15_f16_readme_harbor_runs_and_matrix_script_contract_coherence():
    readme_path = REPO_ROOT / "README.md"
    matrix_path = REPO_ROOT / "scripts" / "verda" / "run_harbor_matrix.sh"
    harbor_runs = REPO_ROOT / "evidence" / "harbor-runs"
    task_dir = REPO_ROOT / "tasks" / "fulfillment-cell-bench"

    assert readme_path.is_file()
    assert matrix_path.is_file(), f"Missing {matrix_path}"
    assert task_dir.is_dir()

    readme = readme_path.read_text(encoding="utf-8")
    matrix = matrix_path.read_text(encoding="utf-8")
    matrix_uncommented = "\n".join(ln.split("#", 1)[0] for ln in matrix.splitlines())
    assert 40 <= len(readme.splitlines()) <= 180
    assert "tasks/fulfillment-cell-bench" in readme
    assert "evidence/harbor-runs" in readme
    assert "gemini/" in matrix_uncommented and "openai/" in matrix_uncommented
    if harbor_runs.is_dir():
        assert any(p.is_file() for p in harbor_runs.rglob("*"))
