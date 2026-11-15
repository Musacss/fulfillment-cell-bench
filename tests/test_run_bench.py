"""TDD test suite for dual-mode scripts/run_bench.py and offline --verify-evidence."""

from dataclasses import asdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import pytest

from robotization_bench.contracts import ROOT, load_world
from robotization_bench.episode import QuarterlyEpisode
from robotization_bench.grading import evaluate_quarterly, invalid
from robotization_bench.quarterly import manual_quarterly_value
from robotization_bench.verifier import verify_quarterly_file

CYRILLIC_RE = re.compile(r"[\u0400-\u04ff]")

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

BUY_CAPEX_IDLE_PLAN = {
    "schema_version": 2,
    "weeks": [
        {
            "robot": True,
            "trays": True,
            "route": "manual",
            "maintenance": False,
            "workers": [[1], [2], [3], [3], [4], [2, 3]],
        }
        for _ in range(12)
    ],
}

INFEASIBLE_UNDERSTAFFED_PLAN = {
    "schema_version": 2,
    "weeks": [
        {
            "robot": False,
            "trays": False,
            "route": "manual",
            "maintenance": False,
            "workers": [[1, 2, 3, 4]],
        }
        for _ in range(12)
    ],
}


def load_run_bench_module():
    script_path = ROOT / "scripts" / "run_bench.py"
    spec = importlib.util.spec_from_file_location("run_bench_mod", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_cli(*args: object) -> subprocess.CompletedProcess[str]:
    env = os.environ | {"PYTHONPATH": str(ROOT / "src")}
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_bench.py"), *map(str, args)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _write_run_bundle(
    run_dir: Path,
    plan_obj: object,
    *,
    write_submission: bool,
    seeds: list[int],
    seeds_sha256: str,
    world: dict,
    nested_verifier: bool = False,
) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    sub_path = run_dir / "submission.json"
    if write_submission:
        sub_path.write_text(json.dumps(plan_obj, indent=2) + "\n", encoding="utf-8")
        ev = verify_quarterly_file(world, sub_path, seeds)
    else:
        ev = invalid("missing submission")

    ver_dir = (run_dir / "verifier") if nested_verifier else run_dir
    ver_dir.mkdir(parents=True, exist_ok=True)
    (ver_dir / "evaluation.json").write_text(
        json.dumps(
            {
                "evaluation": asdict(ev),
                "seeds_sha256": seeds_sha256,
                "world": world["quarterly"]["world_id"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (ver_dir / "reward.txt").write_text(f"{ev.reward_num / ev.reward_den}\n", encoding="utf-8")
    return asdict(ev)


def _build_synthetic_evidence(base_dir: Path, seeds: list[int] | None = None) -> Path:
    world = load_world()
    ev_dir = base_dir / "benchmark-v2"
    ev_dir.mkdir(parents=True, exist_ok=True)
    blind_seeds = [700_101] if seeds is None else seeds
    seed_bytes = (json.dumps(blind_seeds) + "\n").encode("utf-8")
    (ev_dir / "blind_seeds.json").write_bytes(seed_bytes)
    seeds_sha = hashlib.sha256(seed_bytes).hexdigest()
    (ev_dir / "blind_seeds.sha256").write_text(f"{seeds_sha}  blind_seeds.json\n", encoding="utf-8")

    manual_q = manual_quarterly_value(world)
    specs = [
        ("nop", "nop", None, False),
        ("stop_early", "stop_early", None, True),
        ("infeasible", "infeasible", INFEASIBLE_UNDERSTAFFED_PLAN, True),
        ("feasible_no_win", "feasible_no_win", BUY_CAPEX_IDLE_PLAN, True),
        ("manual", "manual", manual_q, True),
        ("frontier-gemini-4-carbon", "frontier", BUY_CAPEX_IDLE_PLAN, True),
        ("base-rl-qwen3.5-9b", "base_open", manual_q, True),
        ("base_rl_qwen3-8b", None, manual_q, True),
        ("qwen2.5-7b-base", "base_rl", manual_q, True),
        ("post-rl-qwen3.5-9b", "post_rl", PHASED_WIN_PLAN, True),
        ("grpo-qwen3-8b", None, PHASED_WIN_PLAN, True),
        ("reference", "reference", PHASED_WIN_PLAN, True),
    ]
    manifest_runs = []
    for run_id, role, plan_obj, write_sub in specs:
        rdir = ev_dir / "runs" / run_id
        ev_dict = _write_run_bundle(
            rdir,
            plan_obj,
            write_submission=write_sub,
            seeds=blind_seeds,
            seeds_sha256=seeds_sha,
            world=world,
        )
        entry = {
            "id": run_id,
            "dir": f"runs/{run_id}",
            "submission": f"runs/{run_id}/submission.json" if write_sub else None,
            "valid": ev_dict["valid"],
            "feasible": ev_dict["feasible"],
            "win": ev_dict["win"],
            "reward_num": ev_dict["reward_num"],
            "reward_den": ev_dict["reward_den"],
        }
        if role is not None:
            entry["role"] = role
        manifest_runs.append(entry)

    (ev_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "blind_seeds_sha256": seeds_sha,
                "runs": manifest_runs,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return ev_dir


def test_v2_plan_winning_manual_and_invalid_exit_zero_without_cyrillic(tmp_path: Path):
    win_path = tmp_path / "win_plan.json"
    win_path.write_text(json.dumps(PHASED_WIN_PLAN), encoding="utf-8")
    out_win = tmp_path / "out_win"
    proc = run_cli("--plan", win_path, "--out", out_win)
    assert proc.returncode == 0, proc.stderr
    assert not CYRILLIC_RE.search(proc.stdout)
    comp_text = (out_win / "comparison.md").read_text(encoding="utf-8")
    assert not CYRILLIC_RE.search(comp_text)
    res_win = json.loads((out_win / "results.json").read_text(encoding="utf-8"))
    assert res_win["schema_version"] == 2
    assert res_win["development"] is True
    assert res_win["seeds"] == [11, 29, 47]
    assert res_win["results"]["manual"]["reward_num"] == 1
    assert res_win["results"]["manual"]["reward_den"] == 5
    assert res_win["results"]["submitted"]["win"] is True
    assert res_win["results"]["submitted"]["reward_num"] / res_win["results"]["submitted"]["reward_den"] > 0.2
    assert json.loads((out_win / "submission.json").read_text(encoding="utf-8")) == PHASED_WIN_PLAN
    assert json.loads((out_win / "episode.json").read_text(encoding="utf-8")) == []

    manual_q_path = tmp_path / "manual_q.json"
    manual_q_path.write_text(json.dumps(manual_quarterly_value()), encoding="utf-8")
    out_man = tmp_path / "out_man"
    proc_man = run_cli("--plan", manual_q_path, "--out", out_man)
    assert proc_man.returncode == 0, proc_man.stderr
    res_man = json.loads((out_man / "results.json").read_text(encoding="utf-8"))
    assert res_man["results"]["submitted"] == res_man["results"]["manual"]

    bad_q_path = tmp_path / "empty_weeks.json"
    bad_q_path.write_text('{"schema_version": 2, "weeks": []}\n', encoding="utf-8")
    out_bad = tmp_path / "out_bad"
    proc_bad = run_cli("--plan", bad_q_path, "--out", out_bad)
    assert proc_bad.returncode == 0, proc_bad.stderr
    assert "Traceback" not in proc_bad.stderr
    assert not CYRILLIC_RE.search((out_bad / "comparison.md").read_text(encoding="utf-8"))
    res_bad = json.loads((out_bad / "results.json").read_text(encoding="utf-8"))
    assert res_bad["schema_version"] == 2
    assert res_bad["results"]["submitted"]["valid"] is False
    assert res_bad["results"]["submitted"]["reward_num"] == 0
    assert res_bad["results"]["submitted"]["reward_den"] == 1
    assert json.loads((out_bad / "submission.json").read_text(encoding="utf-8")) is None


def test_v1_plan_preserved_in_auto_and_explicit_v1_modes(tmp_path: Path):
    manual_v1 = ROOT / "data" / "plans" / "manual.json"
    seeds_file = tmp_path / "ext_seeds.json"
    seeds_file.write_text("[821]\n", encoding="utf-8")

    for mode_args, tag in [((), "auto"), (("--mode", "v1"), "v1")]:
        out_dir = tmp_path / f"out_{tag}"
        proc = run_cli(*mode_args, "--plan", manual_v1, "--seeds-file", seeds_file, "--out", out_dir)
        assert proc.returncode == 0, proc.stderr
        assert not CYRILLIC_RE.search(proc.stdout)
        assert not CYRILLIC_RE.search((out_dir / "comparison.md").read_text(encoding="utf-8"))
        payload = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
        assert payload["schema_version"] == 1
        assert payload["development"] is False
        assert payload["evaluation_seeds"] == [821]
        assert payload["results"]["submitted"] == payload["results"]["manual"]


def test_v2_default_without_plan_invokes_real_quarterly_episode_and_solve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    mod = load_run_bench_module()
    seen_episodes: list[QuarterlyEpisode] = []

    def real_episode_quarterly_solver(episode):
        assert isinstance(episode, QuarterlyEpisode)
        seen_episodes.append(episode)
        obs = episode.observe()
        assert obs["schema_version"] == 2
        pilot_res = episode.pilot(PHASED_WIN_PLAN, obs["development_seeds"][0])
        assert pilot_res["schema_version"] == 2
        assert pilot_res["pilot_budget"]["used"] == 1
        return PHASED_WIN_PLAN

    monkeypatch.setattr(mod, "solve", real_episode_quarterly_solver)
    out_dir = tmp_path / "v2_default"
    rc = mod.main(["--out", str(out_dir)])
    assert rc == 0
    assert len(seen_episodes) == 1
    assert json.loads((out_dir / "submission.json").read_text(encoding="utf-8")) == PHASED_WIN_PLAN
    ep_log = json.loads((out_dir / "episode.json").read_text(encoding="utf-8"))
    assert [entry["action"] for entry in ep_log] == ["observe", "pilot", "submit"]
    comp = (out_dir / "comparison.md").read_text(encoding="utf-8")
    assert not CYRILLIC_RE.search(comp)
    res = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
    assert res["schema_version"] == 2
    assert res["development"] is True
    assert res["seeds"] == [11, 29, 47]
    assert res["results"]["reference"]["win"] is True
    assert res["results"]["manual"]["reward_num"] == 1 and res["results"]["manual"]["reward_den"] == 5


@pytest.mark.parametrize(
    "seeds_text",
    [
        "[11, 9001]",
        "[true]",
        "[501, 501]",
        "[]",
        "[0]",
        "[-7]",
        "NaN",
    ],
)
def test_seed_guards_reject_invalid_or_overlapping_seeds(tmp_path: Path, seeds_text: str):
    seeds_file = tmp_path / "bad_seeds.json"
    seeds_file.write_text(seeds_text, encoding="utf-8")
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(PHASED_WIN_PLAN), encoding="utf-8")
    proc = run_cli("--plan", plan_file, "--seeds-file", seeds_file, "--out", tmp_path / "out")
    assert proc.returncode != 0
    assert "Traceback" not in proc.stderr
    assert "Traceback" not in proc.stdout


def test_symlink_and_path_collision_guards(tmp_path: Path):
    victim = tmp_path / "victim.json"
    victim_bytes = json.dumps(PHASED_WIN_PLAN).encode("utf-8")
    victim.write_bytes(victim_bytes)

    out_sym = tmp_path / "out_sym"
    out_sym.mkdir()
    (out_sym / "submission.json").symlink_to(victim)
    proc_sym = run_cli("--plan", victim, "--out", out_sym)
    assert proc_sym.returncode != 0
    assert "Traceback" not in proc_sym.stderr
    assert victim.read_bytes() == victim_bytes

    out_collide = tmp_path / "out_collide"
    out_collide.mkdir()
    colliding_plan = out_collide / "submission.json"
    colliding_plan.write_bytes(victim_bytes)
    proc_col = run_cli("--plan", colliding_plan, "--out", out_collide)
    assert proc_col.returncode != 0
    assert "Traceback" not in proc_col.stderr
    assert colliding_plan.read_bytes() == victim_bytes


def test_verify_evidence_accepts_full_benchmark_v2_under_5_seconds(tmp_path: Path):
    ev_dir = _build_synthetic_evidence(tmp_path)
    t0 = time.monotonic()
    proc = run_cli("--verify-evidence", ev_dir)
    elapsed = time.monotonic() - t0
    assert proc.returncode == 0, proc.stderr
    assert elapsed < 5.0
    assert "Traceback" not in proc.stderr
    assert not CYRILLIC_RE.search(proc.stdout)
    assert "post-rl-qwen3.5-9b" in proc.stdout and "grpo-qwen3-8b" in proc.stdout and "reference" in proc.stdout


def test_verify_evidence_accepts_minimal_folder_scan_layout(tmp_path: Path):
    world = load_world()
    ev_dir = tmp_path / "minimal-evidence"
    ev_dir.mkdir()
    blind_seeds = [800_201]
    seed_bytes = (json.dumps(blind_seeds) + "\n").encode("utf-8")
    (ev_dir / "blind_seeds.json").write_bytes(seed_bytes)
    seeds_sha = hashlib.sha256(seed_bytes).hexdigest()
    (ev_dir / "manifest.json").write_text(
        json.dumps({"blind_seeds_sha256": seeds_sha}, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_run_bundle(
        ev_dir / "runs" / "reference",
        PHASED_WIN_PLAN,
        write_submission=True,
        seeds=blind_seeds,
        seeds_sha256=seeds_sha,
        world=world,
        nested_verifier=True,
    )
    t0 = time.monotonic()
    proc = run_cli("--verify-evidence", ev_dir)
    elapsed = time.monotonic() - t0
    assert proc.returncode == 0, proc.stderr
    assert elapsed < 5.0
    assert "reference" in proc.stdout


@pytest.mark.parametrize(
    "tamper_kind",
    [
        "seeds_sha256_mismatch",
        "overlap_dev_seeds",
        "overlap_replay_seeds",
        "tampered_reward_txt",
        "nan_reward_txt",
        "tampered_evaluation_json",
        "tampered_submission_json",
        "hierarchy_nop_wins",
        "hierarchy_reference_manual",
        "hierarchy_post_rl_qwen35_manual",
        "hierarchy_grpo_qwen3_8b_manual",
    ],
)
def test_verify_evidence_rejects_tampering_without_traceback(tmp_path: Path, tamper_kind: str):
    world = load_world()
    if tamper_kind == "overlap_dev_seeds":
        ev_dir = _build_synthetic_evidence(tmp_path, seeds=[11])
    elif tamper_kind == "overlap_replay_seeds":
        replay_seed = json.loads((ROOT / "evidence" / "replay_seeds.json").read_text(encoding="utf-8"))[0]
        ev_dir = _build_synthetic_evidence(tmp_path, seeds=[replay_seed])
    else:
        ev_dir = _build_synthetic_evidence(tmp_path, seeds=[900_301])

    seed_bytes = (ev_dir / "blind_seeds.json").read_bytes()
    seeds_sha = hashlib.sha256(seed_bytes).hexdigest()

    if tamper_kind == "seeds_sha256_mismatch":
        (ev_dir / "blind_seeds.json").write_text("[900302]\n", encoding="utf-8")
    elif tamper_kind == "tampered_reward_txt":
        (ev_dir / "runs" / "reference" / "reward.txt").write_text("0.999999\n", encoding="utf-8")
    elif tamper_kind == "nan_reward_txt":
        (ev_dir / "runs" / "reference" / "reward.txt").write_text("NaN\n", encoding="utf-8")
    elif tamper_kind == "tampered_evaluation_json":
        ev_path = ev_dir / "runs" / "reference" / "evaluation.json"
        payload = json.loads(ev_path.read_text(encoding="utf-8"))
        payload["evaluation"]["reward_num"] += 1
        ev_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    elif tamper_kind == "tampered_submission_json":
        (ev_dir / "runs" / "reference" / "submission.json").write_text(
            json.dumps(manual_quarterly_value(world), indent=2) + "\n",
            encoding="utf-8",
        )
    elif tamper_kind == "hierarchy_nop_wins":
        ev_dict = _write_run_bundle(
            ev_dir / "runs" / "nop",
            PHASED_WIN_PLAN,
            write_submission=True,
            seeds=[900_301],
            seeds_sha256=seeds_sha,
            world=world,
        )
        manifest = json.loads((ev_dir / "manifest.json").read_text(encoding="utf-8"))
        for r in manifest["runs"]:
            if r["id"] == "nop":
                r.update(
                    submission="runs/nop/submission.json",
                    valid=ev_dict["valid"],
                    feasible=ev_dict["feasible"],
                    win=ev_dict["win"],
                    reward_num=ev_dict["reward_num"],
                    reward_den=ev_dict["reward_den"],
                )
        (ev_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    elif tamper_kind in (
        "hierarchy_reference_manual",
        "hierarchy_post_rl_qwen35_manual",
        "hierarchy_grpo_qwen3_8b_manual",
    ):
        target_map = {
            "hierarchy_reference_manual": "reference",
            "hierarchy_post_rl_qwen35_manual": "post-rl-qwen3.5-9b",
            "hierarchy_grpo_qwen3_8b_manual": "grpo-qwen3-8b",
        }
        target_id = target_map[tamper_kind]
        ev_dict = _write_run_bundle(
            ev_dir / "runs" / target_id,
            manual_quarterly_value(world),
            write_submission=True,
            seeds=[900_301],
            seeds_sha256=seeds_sha,
            world=world,
        )
        manifest = json.loads((ev_dir / "manifest.json").read_text(encoding="utf-8"))
        for r in manifest["runs"]:
            if r["id"] == target_id:
                r.update(
                    valid=ev_dict["valid"],
                    feasible=ev_dict["feasible"],
                    win=ev_dict["win"],
                    reward_num=ev_dict["reward_num"],
                    reward_den=ev_dict["reward_den"],
                )
        (ev_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    proc = run_cli("--verify-evidence", ev_dir)
    assert proc.returncode != 0
    assert "unrecognized arguments" not in proc.stderr
    assert "Traceback" not in proc.stderr
    assert "Traceback" not in proc.stdout


@pytest.mark.parametrize(
    "case_kind",
    [
        "clobber_replay_seeds",
        "clobber_train_seeds",
        "bad_seed_file_bool",
        "bad_seed_file_zero",
        "bad_seed_file_neg",
        "bad_seed_file_empty",
        "bad_seed_file_obj",
        "bad_seed_meta_bool",
        "bad_seed_meta_zero",
        "bad_seed_meta_neg",
        "bad_seed_meta_str",
    ],
)
def test_verify_evidence_rejects_seed_pool_clobbering_and_malformed_seed_lists(tmp_path: Path, case_kind: str):
    if case_kind == "clobber_replay_seeds":
        replay_seed = json.loads((ROOT / "evidence" / "replay_seeds.json").read_text(encoding="utf-8"))[0]
        ev_dir = _build_synthetic_evidence(tmp_path, seeds=[replay_seed])
        (ev_dir / "dummy_sub").mkdir()
        (ev_dir / "dummy_sub" / "replay_seeds.json").write_text("[999999]\n", encoding="utf-8")
    elif case_kind == "clobber_train_seeds":
        ev_dir = _build_synthetic_evidence(tmp_path, seeds=[710_001])
        (ev_dir / "a").mkdir()
        (ev_dir / "b").mkdir()
        (ev_dir / "a" / "train_seeds.json").write_text("[710001]\n", encoding="utf-8")
        (ev_dir / "b" / "train_seeds.json").write_text("[999999]\n", encoding="utf-8")
    elif case_kind.startswith("bad_seed_file_"):
        file_map = {
            "bad_seed_file_bool": "[true, 810001]\n",
            "bad_seed_file_zero": "[0, 810001]\n",
            "bad_seed_file_neg": "[-5, 810001]\n",
            "bad_seed_file_empty": "[]\n",
            "bad_seed_file_obj": "{}\n",
        }
        ev_dir = _build_synthetic_evidence(tmp_path, seeds=[720_001])
        (ev_dir / "extra_train_seeds.json").write_text(file_map[case_kind], encoding="utf-8")
    else:
        meta_map = {
            "bad_seed_meta_bool": [True, 810_001],
            "bad_seed_meta_zero": [0, 810_001],
            "bad_seed_meta_neg": [-3, 810_001],
            "bad_seed_meta_str": "not-a-list",
        }
        ev_dir = _build_synthetic_evidence(tmp_path, seeds=[730_001])
        manifest_path = ev_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["rl_train_seeds"] = meta_map[case_kind]
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    proc = run_cli("--verify-evidence", ev_dir)
    assert proc.returncode != 0, f"expected failure for {case_kind}"
    assert "Traceback" not in proc.stderr and "Traceback" not in proc.stdout


def test_verify_evidence_accepts_oversized_70kb_invalid_submission_matching_zero_reward(tmp_path: Path):
    world = load_world()
    seeds = [740_101]
    ev_dir = _build_synthetic_evidence(tmp_path, seeds=seeds)
    seeds_sha = hashlib.sha256((ev_dir / "blind_seeds.json").read_bytes()).hexdigest()

    bad_dir = ev_dir / "runs" / "bad_oversized_agent"
    bad_dir.mkdir(parents=True, exist_ok=True)
    oversized_payload = '{"schema_version": 2, "padding": "' + ("x" * 70_000) + '"}\n'
    assert len(oversized_payload.encode("utf-8")) > 65_536
    sub_path = bad_dir / "submission.json"
    sub_path.write_text(oversized_payload, encoding="utf-8")

    actual_ev = verify_quarterly_file(world, sub_path, seeds)
    assert actual_ev.valid is False and actual_ev.reward_num == 0 and actual_ev.reward_den == 1

    (bad_dir / "evaluation.json").write_text(
        json.dumps(
            {
                "evaluation": asdict(actual_ev),
                "seeds_sha256": seeds_sha,
                "world": world["quarterly"]["world_id"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (bad_dir / "reward.txt").write_text("0.0\n", encoding="utf-8")

    manifest_path = ev_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["runs"].append(
        {
            "id": "bad_oversized_agent",
            "role": "frontier",
            "dir": "runs/bad_oversized_agent",
            "submission": "runs/bad_oversized_agent/submission.json",
            "valid": False,
            "feasible": False,
            "win": False,
            "reward_num": 0,
            "reward_den": 1,
        }
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    proc = run_cli("--verify-evidence", ev_dir)
    assert proc.returncode == 0, proc.stderr
    assert "Traceback" not in proc.stderr
    assert "bad_oversized_agent" in proc.stdout


@pytest.mark.parametrize(
    ("field", "bad_rel"),
    [
        ("evaluation", "../outside_eval.json"),
        ("reward_file", "../outside_reward.txt"),
        ("evaluation", "../sym_outside_dir/eval.json"),
    ],
)
def test_verify_evidence_rejects_manifest_path_traversal_and_symlink_parent_escape(
    tmp_path: Path, field: str, bad_rel: str
):
    ev_dir = _build_synthetic_evidence(tmp_path / "bundle", seeds=[750_101])
    parent_dir = ev_dir.parent
    ref_eval_bytes = (ev_dir / "runs" / "reference" / "evaluation.json").read_bytes()
    ref_reward_bytes = (ev_dir / "runs" / "reference" / "reward.txt").read_bytes()

    (parent_dir / "outside_eval.json").write_bytes(ref_eval_bytes)
    (parent_dir / "outside_reward.txt").write_bytes(ref_reward_bytes)

    real_ext_dir = tmp_path / "real_ext_dir"
    real_ext_dir.mkdir()
    (real_ext_dir / "eval.json").write_bytes(ref_eval_bytes)
    (parent_dir / "sym_outside_dir").symlink_to(real_ext_dir)

    manifest_path = ev_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for r in manifest["runs"]:
        if r["id"] == "reference":
            r[field] = bad_rel
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    proc = run_cli("--verify-evidence", ev_dir)
    assert proc.returncode != 0, f"expected path containment rejection for {field}={bad_rel!r}"
    assert "Traceback" not in proc.stderr and "Traceback" not in proc.stdout


def test_verify_evidence_rejects_manifest_valid_only_without_authoritative_reward_claim(tmp_path: Path):
    ev_dir = tmp_path / "unclaimed-bundle"
    ev_dir.mkdir()
    seed_bytes = b"[760101]\n"
    (ev_dir / "blind_seeds.json").write_bytes(seed_bytes)
    seeds_sha = hashlib.sha256(seed_bytes).hexdigest()
    (ev_dir / "blind_seeds.sha256").write_text(f"{seeds_sha}  blind_seeds.json\n", encoding="utf-8")

    run_dir = ev_dir / "runs" / "frontier_forged"
    run_dir.mkdir(parents=True)
    (run_dir / "submission.json").write_text(json.dumps(BUY_CAPEX_IDLE_PLAN, indent=2) + "\n", encoding="utf-8")
    (ev_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "blind_seeds_sha256": seeds_sha,
                "runs": [
                    {
                        "id": "frontier_forged",
                        "submission": "runs/frontier_forged/submission.json",
                        "valid": True,
                        "claimed_score": 0.9999,
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    proc = run_cli("--verify-evidence", ev_dir)
    assert proc.returncode != 0
    assert "Traceback" not in proc.stderr and "Traceback" not in proc.stdout


@pytest.mark.parametrize(
    "layout_case",
    ["unlisted_disk_run_with_manifest", "logs_verifier_nop_tamper", "harbor_logs_clean"],
)
def test_verify_evidence_rejects_unlisted_disk_run_and_scans_logs_verifier(tmp_path: Path, layout_case: str):
    world = load_world()
    if layout_case == "unlisted_disk_run_with_manifest":
        seeds_a = [770_101]
        ev_a = _build_synthetic_evidence(tmp_path / "case_unlisted", seeds=seeds_a)
        seeds_sha_a = hashlib.sha256((ev_a / "blind_seeds.json").read_bytes()).hexdigest()
        _write_run_bundle(
            ev_a / "runs" / "sneaky",
            BUY_CAPEX_IDLE_PLAN,
            write_submission=True,
            seeds=seeds_a,
            seeds_sha256=seeds_sha_a,
            world=world,
        )
        proc = run_cli("--verify-evidence", ev_a)
        assert proc.returncode != 0
        assert "Traceback" not in proc.stderr and "Traceback" not in proc.stdout
        return

    seed_bytes_b = b"[770201]\n"
    seeds_sha_b = hashlib.sha256(seed_bytes_b).hexdigest()
    if layout_case == "logs_verifier_nop_tamper":
        ev_b = tmp_path / "case_logs_verifier_tamper"
        ev_b.mkdir()
        (ev_b / "blind_seeds.json").write_bytes(seed_bytes_b)
        (ev_b / "blind_seeds.sha256").write_text(f"{seeds_sha_b}  blind_seeds.json\n", encoding="utf-8")
        _write_run_bundle(
            ev_b / "runs" / "reference",
            PHASED_WIN_PLAN,
            write_submission=True,
            seeds=[770_201],
            seeds_sha256=seeds_sha_b,
            world=world,
        )
        nop_ver = ev_b / "runs" / "nop" / "logs" / "verifier"
        nop_ver.mkdir(parents=True)
        (nop_ver / "reward.txt").write_text("0.99\n", encoding="utf-8")
        proc = run_cli("--verify-evidence", ev_b)
        assert proc.returncode != 0
        assert "Traceback" not in proc.stderr and "Traceback" not in proc.stdout
        return

    ev_c = tmp_path / "case_harbor_logs_clean"
    ev_c.mkdir()
    (ev_c / "blind_seeds.json").write_bytes(seed_bytes_b)
    (ev_c / "blind_seeds.sha256").write_text(f"{seeds_sha_b}  blind_seeds.json\n", encoding="utf-8")
    oracle_sub = ev_c / "runs" / "oracle" / "logs" / "artifacts" / "submission.json"
    oracle_sub.parent.mkdir(parents=True)
    oracle_sub.write_text(json.dumps(PHASED_WIN_PLAN, indent=2) + "\n", encoding="utf-8")
    oracle_ev = verify_quarterly_file(world, oracle_sub, [770_201])
    oracle_ver = ev_c / "runs" / "oracle" / "logs" / "verifier"
    oracle_ver.mkdir(parents=True)
    (oracle_ver / "evaluation.json").write_text(
        json.dumps({"evaluation": asdict(oracle_ev), "seeds_sha256": seeds_sha_b}, indent=2) + "\n",
        encoding="utf-8",
    )
    (oracle_ver / "reward.txt").write_text(f"{oracle_ev.reward_num / oracle_ev.reward_den}\n", encoding="utf-8")
    (ev_c / "runs" / "nop" / "logs" / "verifier").mkdir(parents=True)
    (ev_c / "runs" / "nop" / "logs" / "verifier" / "reward.txt").write_text("0.0\n", encoding="utf-8")
    proc_clean = run_cli("--verify-evidence", ev_c)
    assert proc_clean.returncode == 0, proc_clean.stderr


@pytest.mark.parametrize(
    ("run_id", "manifest_fields", "plan_fn"),
    [
        ("post_rl_qwen3.5-9b", {"kind": "opencode"}, lambda w: manual_quarterly_value(w)),
        ("nop", {"role": "frontier"}, lambda w: manual_quarterly_value(w)),
        ("unstaffed_jam_deadlock", {}, lambda _w: PHASED_WIN_PLAN),
        ("buy_capex_idle", {}, lambda _w: PHASED_WIN_PLAN),
    ],
)
def test_verify_evidence_role_classification_resists_override_and_enforces_exploit_slugs(
    tmp_path: Path,
    run_id: str,
    manifest_fields: dict,
    plan_fn,
):
    world = load_world()
    seeds = [780_101]
    ev_dir = tmp_path / f"role_{run_id}"
    ev_dir.mkdir()
    seed_bytes = (json.dumps(seeds) + "\n").encode("utf-8")
    (ev_dir / "blind_seeds.json").write_bytes(seed_bytes)
    seeds_sha = hashlib.sha256(seed_bytes).hexdigest()
    (ev_dir / "blind_seeds.sha256").write_text(f"{seeds_sha}  blind_seeds.json\n", encoding="utf-8")

    plan_obj = plan_fn(world)
    ev_dict = _write_run_bundle(
        ev_dir / "runs" / run_id,
        plan_obj,
        write_submission=True,
        seeds=seeds,
        seeds_sha256=seeds_sha,
        world=world,
    )
    entry = {
        "id": run_id,
        "dir": f"runs/{run_id}",
        "submission": f"runs/{run_id}/submission.json",
        "valid": ev_dict["valid"],
        "feasible": ev_dict["feasible"],
        "win": ev_dict["win"],
        "reward_num": ev_dict["reward_num"],
        "reward_den": ev_dict["reward_den"],
        **manifest_fields,
    }
    (ev_dir / "manifest.json").write_text(
        json.dumps({"schema_version": 2, "blind_seeds_sha256": seeds_sha, "runs": [entry]}, indent=2) + "\n",
        encoding="utf-8",
    )

    proc = run_cli("--verify-evidence", ev_dir)
    assert proc.returncode != 0, f"expected hierarchy failure for {run_id!r} with {manifest_fields!r}"
    assert "Traceback" not in proc.stderr and "Traceback" not in proc.stdout


@pytest.mark.parametrize(
    "crash_case",
    ["invalid_utf8_sha256", "deep_1500_json", "symlink_loop_plan", "devnull_out_dir"],
)
def test_cli_eliminates_raw_tracebacks_on_invalid_utf8_sha_deep_json_symlink_loop_and_devnull_out(
    tmp_path: Path, crash_case: str
):
    if crash_case == "invalid_utf8_sha256":
        ev_sha = _build_synthetic_evidence(tmp_path / "bad_sha", seeds=[790_101])
        (ev_sha / "blind_seeds.sha256").write_bytes(b"\xff\xfe\xfd\n")
        proc = run_cli("--verify-evidence", ev_sha)
    elif crash_case == "deep_1500_json":
        ev_deep = _build_synthetic_evidence(tmp_path / "deep_json", seeds=[790_201])
        (ev_deep / "nested.json").write_text("[" * 1500 + "]" * 1500, encoding="utf-8")
        proc = run_cli("--verify-evidence", ev_deep)
    elif crash_case == "symlink_loop_plan":
        loop_plan = tmp_path / "loop.json"
        loop_plan.symlink_to("loop.json")
        proc = run_cli("--plan", loop_plan, "--out", tmp_path / "out_loop")
    else:
        valid_plan = tmp_path / "valid_plan.json"
        valid_plan.write_text(json.dumps(PHASED_WIN_PLAN), encoding="utf-8")
        proc = run_cli("--plan", valid_plan, "--out", "/dev/null/sub")

    assert proc.returncode != 0
    assert "Traceback" not in proc.stderr and "Traceback" not in proc.stdout
    assert "RecursionError" not in proc.stderr


@pytest.mark.parametrize(
    "artifact_case",
    [
        "folder_scan_forged_logs_artifacts_reward",
        "folder_scan_forged_logs_artifacts_eval",
        "folder_scan_forged_artifacts_reward",
        "manifest_without_runs_forged_logs_artifacts_reward",
        "manifest_with_runs_forged_logs_artifacts_reward",
        "unlisted_nested_extra_reward",
        "folder_scan_matching_logs_artifacts_reward",
    ],
)
def test_verify_evidence_detects_forged_verdicts_in_artifacts_and_unlisted_locations(
    tmp_path: Path, artifact_case: str
):
    world = load_world()
    seeds = [790_002]
    ev_dir = tmp_path / artifact_case
    ev_dir.mkdir()
    seed_bytes = (json.dumps(seeds) + "\n").encode("utf-8")
    (ev_dir / "blind_seeds.json").write_bytes(seed_bytes)
    seeds_sha = hashlib.sha256(seed_bytes).hexdigest()
    (ev_dir / "blind_seeds.sha256").write_text(f"{seeds_sha}  blind_seeds.json\n", encoding="utf-8")

    if artifact_case == "folder_scan_forged_artifacts_reward":
        sub_rel = Path("runs/oracle/artifacts/submission.json")
        ver_dir = ev_dir / "runs" / "oracle" / "verifier"
    else:
        sub_rel = Path("runs/oracle/logs/artifacts/submission.json")
        ver_dir = ev_dir / "runs" / "oracle" / "logs" / "verifier"

    sub_path = ev_dir / sub_rel
    sub_path.parent.mkdir(parents=True, exist_ok=True)
    sub_path.write_text(json.dumps(PHASED_WIN_PLAN, indent=2) + "\n", encoding="utf-8")
    oracle_ev = verify_quarterly_file(world, sub_path, seeds)

    ver_dir.mkdir(parents=True, exist_ok=True)
    (ver_dir / "evaluation.json").write_text(
        json.dumps({"evaluation": asdict(oracle_ev), "seeds_sha256": seeds_sha}, indent=2) + "\n",
        encoding="utf-8",
    )
    exact_reward_str = f"{oracle_ev.reward_num / oracle_ev.reward_den}\n"
    (ver_dir / "reward.txt").write_text(exact_reward_str, encoding="utf-8")

    if artifact_case == "folder_scan_forged_logs_artifacts_reward":
        (sub_path.parent / "reward.txt").write_text("0.9999\n", encoding="utf-8")
    elif artifact_case == "folder_scan_forged_logs_artifacts_eval":
        forged_ev = asdict(oracle_ev) | {"reward_num": 999, "reward_den": 1000}
        (sub_path.parent / "evaluation.json").write_text(
            json.dumps({"evaluation": forged_ev}, indent=2) + "\n",
            encoding="utf-8",
        )
    elif artifact_case == "folder_scan_forged_artifacts_reward":
        (sub_path.parent / "reward.txt").write_text("0.9999\n", encoding="utf-8")
    elif artifact_case == "manifest_without_runs_forged_logs_artifacts_reward":
        (ev_dir / "manifest.json").write_text(
            json.dumps({"schema_version": 2, "blind_seeds_sha256": seeds_sha}, indent=2) + "\n",
            encoding="utf-8",
        )
        (sub_path.parent / "reward.txt").write_text("0.9999\n", encoding="utf-8")
    elif artifact_case == "manifest_with_runs_forged_logs_artifacts_reward":
        (ev_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "blind_seeds_sha256": seeds_sha,
                    "runs": [
                        {
                            "id": "oracle",
                            "dir": "runs/oracle",
                            "submission": sub_rel.as_posix(),
                            "evaluation": "runs/oracle/logs/verifier/evaluation.json",
                            "reward_file": "runs/oracle/logs/verifier/reward.txt",
                        }
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (sub_path.parent / "reward.txt").write_text("0.9999\n", encoding="utf-8")
    elif artifact_case == "unlisted_nested_extra_reward":
        extra_dir = ev_dir / "runs" / "oracle" / "logs" / "extra"
        extra_dir.mkdir(parents=True, exist_ok=True)
        (extra_dir / "reward.txt").write_text("0.9999\n", encoding="utf-8")
    else:
        (sub_path.parent / "reward.txt").write_text(exact_reward_str, encoding="utf-8")

    proc = run_cli("--verify-evidence", ev_dir)
    if artifact_case == "folder_scan_matching_logs_artifacts_reward":
        assert proc.returncode == 0, proc.stderr
    else:
        assert proc.returncode != 0, f"expected forged artifact rejection for {artifact_case}"
        assert "Traceback" not in proc.stderr and "Traceback" not in proc.stdout


@pytest.mark.parametrize(
    ("run_id", "manifest_fields", "plan_fn", "include_base", "expect_pass"),
    [
        ("post_rl_qwen3.5-9b", {"role": "feasible_no_win"}, lambda _w: BUY_CAPEX_IDLE_PLAN, True, False),
        ("manual", {"role": "feasible_no_win"}, lambda _w: BUY_CAPEX_IDLE_PLAN, False, False),
        ("reference", {"category": "infeasible"}, lambda _w: INFEASIBLE_UNDERSTAFFED_PLAN, False, False),
        ("base_qwen3.5-9b", {"kind": "grpo"}, lambda _w: PHASED_WIN_PLAN, False, False),
        ("run_01", {"role": "post_rl", "category": "feasible_no_win"}, lambda _w: BUY_CAPEX_IDLE_PLAN, False, False),
        (
            "run_01",
            {
                "role": "feasible_no_win",
                "dir": "runs/post_rl_qwen3.5-9b",
                "submission": "runs/post_rl_qwen3.5-9b/submission.json",
            },
            lambda _w: BUY_CAPEX_IDLE_PLAN,
            True,
            False,
        ),
        ("feasible_no_win_post_rl_qwen3.5-9b", {}, lambda _w: BUY_CAPEX_IDLE_PLAN, False, False),
        ("post_rl_qwen3.5-9b", {"kind": "opencode"}, lambda _w: PHASED_WIN_PLAN, False, True),
        ("run_01", {"role": "post_rl"}, lambda _w: PHASED_WIN_PLAN, False, True),
    ],
)
def test_verify_evidence_rejects_conflicting_role_metadata_between_run_id_and_manifest(
    tmp_path: Path,
    run_id: str,
    manifest_fields: dict,
    plan_fn,
    include_base: bool,
    expect_pass: bool,
):
    world = load_world()
    seeds = [795_101]
    ev_dir = tmp_path / "role_conflict_bundle"
    ev_dir.mkdir()
    seed_bytes = (json.dumps(seeds) + "\n").encode("utf-8")
    (ev_dir / "blind_seeds.json").write_bytes(seed_bytes)
    seeds_sha = hashlib.sha256(seed_bytes).hexdigest()
    (ev_dir / "blind_seeds.sha256").write_text(f"{seeds_sha}  blind_seeds.json\n", encoding="utf-8")

    runs_list = []
    if include_base:
        base_ev = _write_run_bundle(
            ev_dir / "runs" / "base_qwen3.5-9b",
            manual_quarterly_value(world),
            write_submission=True,
            seeds=seeds,
            seeds_sha256=seeds_sha,
            world=world,
        )
        runs_list.append(
            {
                "id": "base_qwen3.5-9b",
                "dir": "runs/base_qwen3.5-9b",
                "submission": "runs/base_qwen3.5-9b/submission.json",
                "valid": base_ev["valid"],
                "feasible": base_ev["feasible"],
                "win": base_ev["win"],
                "reward_num": base_ev["reward_num"],
                "reward_den": base_ev["reward_den"],
            }
        )

    target_rel_dir = manifest_fields.get("dir", f"runs/{run_id}")
    ev_dict = _write_run_bundle(
        ev_dir / target_rel_dir,
        plan_fn(world),
        write_submission=True,
        seeds=seeds,
        seeds_sha256=seeds_sha,
        world=world,
    )
    runs_list.append(
        {
            "id": run_id,
            "dir": target_rel_dir,
            "submission": f"{target_rel_dir}/submission.json",
            "valid": ev_dict["valid"],
            "feasible": ev_dict["feasible"],
            "win": ev_dict["win"],
            "reward_num": ev_dict["reward_num"],
            "reward_den": ev_dict["reward_den"],
            **manifest_fields,
        }
    )
    (ev_dir / "manifest.json").write_text(
        json.dumps({"schema_version": 2, "blind_seeds_sha256": seeds_sha, "runs": runs_list}, indent=2) + "\n",
        encoding="utf-8",
    )

    proc = run_cli("--verify-evidence", ev_dir)
    if expect_pass:
        assert proc.returncode == 0, proc.stderr
    else:
        assert proc.returncode != 0, f"expected conflict rejection for {run_id!r} + {manifest_fields!r}"
        assert "Traceback" not in proc.stderr and "Traceback" not in proc.stdout


def test_verify_evidence_allows_scalar_seed_count_keys_while_enforcing_seed_arrays(tmp_path: Path):
    ev_dir = _build_synthetic_evidence(tmp_path / "valid_counts", seeds=[801_101])
    (ev_dir / "training_summary.json").write_text(
        json.dumps(
            {
                "model": "Qwen/Qwen3.5-9B",
                "num_seeds": 8,
                "n_seeds": 8,
                "total_seeds": 72,
                "min_seeds": 3,
                "max_seeds": 16,
                "count_seeds": 8,
                "eval_num_seeds": 8,
                "train_n_seeds": 64,
                "steps": 150,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    proc_ok = run_cli("--verify-evidence", ev_dir)
    assert proc_ok.returncode == 0, proc_ok.stderr

    for idx, bad_meta in enumerate(
        [
            {"train_seeds": 8},
            {"eval_seeds": [0]},
            {"num_seeds": -1},
            {"num_seeds": True},
        ]
    ):
        bad_dir = _build_synthetic_evidence(tmp_path / f"bad_meta_{idx}", seeds=[801_201 + idx])
        (bad_dir / "training_summary.json").write_text(json.dumps(bad_meta) + "\n", encoding="utf-8")
        proc_bad = run_cli("--verify-evidence", bad_dir)
        assert proc_bad.returncode != 0, f"expected rejection for {bad_meta!r}"
        assert "Traceback" not in proc_bad.stderr and "Traceback" not in proc_bad.stdout


def test_verify_evidence_8_seeds_14_runs_7_distinct_plans_completes_under_5_seconds(tmp_path: Path):
    from robotization_bench.grading import grade_quarters
    from robotization_bench.quarterly import simulate_quarter
    from robotization_bench.validation import parse_quarterly_plan

    world = load_world()
    blind_seeds = [810_101, 810_102, 810_103, 810_104, 810_105, 810_106, 810_107, 810_108]
    ev_dir = tmp_path / "m5-8seed-bundle"
    ev_dir.mkdir()
    seed_bytes = (json.dumps(blind_seeds) + "\n").encode("utf-8")
    (ev_dir / "blind_seeds.json").write_bytes(seed_bytes)
    seeds_sha = hashlib.sha256(seed_bytes).hexdigest()
    (ev_dir / "blind_seeds.sha256").write_text(f"{seeds_sha}  blind_seeds.json\n", encoding="utf-8")

    manual_q = manual_quarterly_value(world)
    phased_win_alt = {
        "schema_version": 2,
        "weeks": [
            *PHASED_WIN_PLAN["weeks"][:11],
            {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [3], [4], [2, 3]]},
        ],
    }
    phased_win_alt2 = {
        "schema_version": 2,
        "weeks": [
            {"robot": True, "trays": True, "route": "bypass", "maintenance": False, "workers": [[1], [2], [3, 2], [4]]},
            *PHASED_WIN_PLAN["weeks"][1:],
        ],
    }
    capex_idle_delayed = {
        "schema_version": 2,
        "weeks": [
            manual_q["weeks"][0],
            *BUY_CAPEX_IDLE_PLAN["weeks"][1:],
        ],
    }
    overstaffed_manual = {
        "schema_version": 2,
        "weeks": [
            {
                "robot": False,
                "trays": False,
                "route": "manual",
                "maintenance": False,
                "workers": [[1], [2], [3], [3], [4], [2, 3], [1, 4]],
            }
            for _ in range(12)
        ],
    }

    distinct_plans = [
        manual_q,
        PHASED_WIN_PLAN,
        phased_win_alt,
        phased_win_alt2,
        BUY_CAPEX_IDLE_PLAN,
        capex_idle_delayed,
        INFEASIBLE_UNDERSTAFFED_PLAN,
        overstaffed_manual,
    ]
    parsed_distinct = {parse_quarterly_plan(p, world) for p in distinct_plans}
    assert len(parsed_distinct) == 8

    base_parsed = parse_quarterly_plan(manual_q, world)
    base_quarters = tuple(simulate_quarter(world, base_parsed, s) for s in blind_seeds)
    precomputed_evals: dict[int, dict] = {}
    for idx, p_obj in enumerate(distinct_plans):
        parsed = parse_quarterly_plan(p_obj, world)
        q_reps = base_quarters if parsed == base_parsed else tuple(simulate_quarter(world, parsed, s) for s in blind_seeds)
        ev = grade_quarters(world, parsed, q_reps, base_quarters)
        if idx in (0, 1):
            probe_sub = tmp_path / f"parity_{idx}.json"
            probe_sub.write_text(json.dumps(p_obj), encoding="utf-8")
            assert ev == verify_quarterly_file(world, probe_sub, blind_seeds)
        precomputed_evals[idx] = asdict(ev)

    run_specs = [
        ("nop", "nop", None, False),
        ("stop_early", "stop_early", None, True),
        ("infeasible", "infeasible", (6, INFEASIBLE_UNDERSTAFFED_PLAN), True),
        ("feasible_no_win", "feasible_no_win", (4, BUY_CAPEX_IDLE_PLAN), True),
        ("manual", "manual", (0, manual_q), True),
        ("oracle", "reference", (1, PHASED_WIN_PLAN), True),
        ("gemini-4-carbon_run1", "frontier", (4, BUY_CAPEX_IDLE_PLAN), True),
        ("gemini-4-carbon_run2", "frontier", (5, capex_idle_delayed), True),
        ("gemini-4-carbon_run3", "frontier", None, False),
        ("gemini-3.1-pro-preview_run1", "frontier", (7, overstaffed_manual), True),
        ("base_qwen3.5-9b_run1", "base_open", (0, manual_q), True),
        ("base_qwen3.5-9b_run2", "base_open", (7, overstaffed_manual), True),
        ("post_rl_qwen3.5-9b_run1", "post_rl", (2, phased_win_alt), True),
        ("post_rl_qwen3.5-9b_run2", "post_rl", (3, phased_win_alt2), True),
    ]
    assert len(run_specs) == 14

    manifest_runs = []
    for run_id, role, plan_pair, write_sub in run_specs:
        rdir = ev_dir / "runs" / run_id
        rdir.mkdir(parents=True, exist_ok=True)
        if write_sub:
            if plan_pair is None:
                (rdir / "submission.json").write_text("null\n", encoding="utf-8")
                ev_dict = asdict(invalid("Expected a quarterly plan object with schema_version and weeks"))
            else:
                plan_idx, plan_obj = plan_pair
                (rdir / "submission.json").write_text(json.dumps(plan_obj, indent=2) + "\n", encoding="utf-8")
                ev_dict = precomputed_evals[plan_idx]
        else:
            ev_dict = asdict(invalid("missing submission"))

        (rdir / "evaluation.json").write_text(
            json.dumps({"evaluation": ev_dict, "seeds_sha256": seeds_sha}, indent=2) + "\n",
            encoding="utf-8",
        )
        (rdir / "reward.txt").write_text(f"{ev_dict['reward_num'] / ev_dict['reward_den']}\n", encoding="utf-8")
        manifest_runs.append(
            {
                "id": run_id,
                "role": role,
                "dir": f"runs/{run_id}",
                "submission": f"runs/{run_id}/submission.json" if write_sub else None,
                "valid": ev_dict["valid"],
                "feasible": ev_dict["feasible"],
                "win": ev_dict["win"],
                "reward_num": ev_dict["reward_num"],
                "reward_den": ev_dict["reward_den"],
            }
        )

    (ev_dir / "manifest.json").write_text(
        json.dumps({"schema_version": 2, "blind_seeds_sha256": seeds_sha, "runs": manifest_runs}, indent=2) + "\n",
        encoding="utf-8",
    )
    (ev_dir / "training_summary.json").write_text(
        json.dumps({"model": "Qwen/Qwen3.5-9B", "num_seeds": 8, "steps": 150}) + "\n",
        encoding="utf-8",
    )

    t0 = time.monotonic()
    proc = run_cli("--verify-evidence", ev_dir)
    elapsed = time.monotonic() - t0
    assert proc.returncode == 0, proc.stderr
    assert elapsed < 5.0, f"8-seed 14-run bundle took {elapsed:.3f}s (exceeds < 5.0s budget)"
    assert "VERIFIED 14 run(s) — HIERARCHY_INTACT: True" in proc.stdout


@pytest.mark.parametrize(
    ("field", "null_val"),
    [
        ("evaluation", "runs/reference/eval\u0000.json"),
        ("reward_file", "runs/reference/reward\u0000.txt"),
        ("submission", "runs/reference/sub\u0000.json"),
        ("dir", "runs/ref\u0000erence"),
    ],
)
def test_verify_evidence_rejects_null_byte_in_manifest_paths_without_traceback(
    tmp_path: Path, field: str, null_val: str
):
    ev_dir = _build_synthetic_evidence(tmp_path / "null_byte_bundle", seeds=[700_101])
    manifest_path = ev_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for r in manifest["runs"]:
        if r["id"] == "reference":
            r[field] = null_val
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    proc = run_cli("--verify-evidence", ev_dir)
    assert proc.returncode != 0
    assert "Traceback" not in proc.stderr and "Traceback" not in proc.stdout
    assert "run_bench.py: error:" in proc.stderr


