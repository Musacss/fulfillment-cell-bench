"""Comprehensive TDD suite for Milestone M3 (@solver-rl-verda): reference.py & scripts/verda/*."""

from __future__ import annotations

import ast
import copy
from fractions import Fraction as F
import json
from pathlib import Path
from typing import Any

import pytest

from robotization_bench.contracts import ROOT, load_world
from robotization_bench.episode import Episode, QuarterlyEpisode
from robotization_bench.grading import evaluate, evaluate_quarterly, manual_value
from robotization_bench.quarterly import manual_quarterly_value
import robotization_bench.reference as reference
from robotization_bench.reference import solve
from robotization_bench.scenarios import generate
from robotization_bench.validation import parse_plan, parse_quarterly_plan

WORKTREE_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_PY = WORKTREE_ROOT / "src" / "robotization_bench" / "reference.py"
REPLAY_SEEDS_JSON = WORKTREE_ROOT / "evidence" / "replay_seeds.json"


class StrictSocketMockClient:
    """Duck-typed black-box proxy exposing ONLY .observe() and .pilot(plan, seed)."""

    __slots__ = ("_backend",)

    def __init__(self, backend: Any) -> None:
        object.__setattr__(self, "_backend", backend)

    def __getattribute__(self, name: str) -> Any:
        if name in ("observe", "pilot"):
            return object.__getattribute__(self, name)
        raise AttributeError(f"Black-box client forbids attribute access: {name!r}")

    def observe(self) -> dict[str, Any]:
        backend = object.__getattribute__(self, "_backend")
        return backend.observe()

    def pilot(self, plan: Any, seed: int) -> dict[str, Any]:
        backend = object.__getattribute__(self, "_backend")
        return backend.pilot(plan, seed)


def _static_route_all_plan(world: dict[str, Any]) -> dict[str, Any]:
    num_weeks = world["quarterly"]["weeks"]
    return {
        "schema_version": 2,
        "weeks": [
            {
                "robot": True,
                "trays": True,
                "route": "all",
                "maintenance": False,
                "workers": [[1], [2], [3], [4]],
            }
            for _ in range(num_weeks)
        ],
    }


# ==============================================================================
# Cycle 1: Deliverable A — Black-Box Polymorphic Reference Optimizer
# ==============================================================================


def test_reference_ast_pure_stdlib_and_blackbox_isolation():
    source = REFERENCE_PY.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(REFERENCE_PY))

    forbidden_calls = {"__import__", "eval", "exec", "compile", "open", "getattr"}
    allowed_episode_attrs = {"observe", "pilot", "max_pilots", "pilot_used"}
    known_seed_constants = {
        11,
        29,
        47,
        5343194,
        301926751,
        437594646,
        653467791,
        853984044,
        1177674159,
        1809728213,
        2055338172,
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("robotization_bench"), (
                    f"Forbidden internal import in reference.py: {alias.name}"
                )
                assert alias.name not in {"importlib", "pathlib", "os", "sys", "subprocess"}, (
                    f"Forbidden module import in reference.py: {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "Relative imports from robotization_bench are forbidden in reference.py"
            mod = node.module or ""
            assert not mod.startswith("robotization_bench"), (
                f"Forbidden internal from-import in reference.py: {mod}"
            )
            assert mod not in {"importlib", "pathlib", "os", "sys", "subprocess"}, (
                f"Forbidden module from-import in reference.py: {mod}"
            )
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden_calls, (
                    f"Forbidden builtin call in reference.py: {node.func.id}"
                )
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "episode":
                assert node.attr in allowed_episode_attrs, (
                    f"Forbidden attribute access episode.{node.attr} in reference.py"
                )
        elif isinstance(node, ast.Dict):
            dict_int_keys = {
                k.value
                for k in node.keys
                if isinstance(k, ast.Constant) and type(k.value) is int
            }
            assert not (dict_int_keys & known_seed_constants), (
                f"Hardcoded seed lookup table detected in reference.py: {dict_int_keys & known_seed_constants}"
            )


def test_solve_quarterly_dev_and_replay_seeds_win_above_035():
    world = load_world()
    replay_seeds = json.loads(REPLAY_SEEDS_JSON.read_text(encoding="utf-8"))

    ep = QuarterlyEpisode(world)
    plan = solve(ep)

    assert ep.pilot_used <= 20
    assert ep.pilot_used < ep.max_pilots
    parsed = parse_quarterly_plan(plan, world)
    assert len(parsed.weeks) == 12

    dev_eval = evaluate_quarterly(world, plan, world["development_seeds"])
    assert dev_eval.valid and dev_eval.feasible and dev_eval.win
    assert F(dev_eval.reward_num, dev_eval.reward_den) >= F(7, 20), (
        f"Dev reward {dev_eval.reward_num}/{dev_eval.reward_den} < 7/20"
    )

    replay_eval = evaluate_quarterly(world, plan, replay_seeds)
    assert replay_eval.valid and replay_eval.feasible and replay_eval.win
    assert F(replay_eval.reward_num, replay_eval.reward_den) >= F(7, 20), (
        f"Replay reward {replay_eval.reward_num}/{replay_eval.reward_den} < 7/20"
    )


def _perturbed_worlds() -> list[tuple[str, dict[str, Any]]]:
    base = load_world()

    # 1. Shifted surge schedule: peaks moved to weeks {1, 2} and {5, 6, 7}
    w_shifted = copy.deepcopy(base)
    orig_profiles = base["quarterly"]["week_profiles"]
    perm = [0, 3, 7, 1, 4, 8, 9, 2, 5, 6, 10, 11]
    w_shifted["quarterly"]["week_profiles"] = [
        {**copy.deepcopy(orig_profiles[src]), "week": idx, "label": f"shifted_{idx}"}
        for idx, src in enumerate(perm)
    ]

    # 2. Boosted wave demand & tighter due_offset on peak weeks
    w_boosted = copy.deepcopy(base)
    for prof in w_boosted["quarterly"]["week_profiles"]:
        if prof["waves"] >= 12:
            prof["waves"] += 1
            prof["due_offset"] = max(140, prof["due_offset"] - 5)

    # 3. Shifted & intensified fragile/oversize promo mix wave
    w_fragile = copy.deepcopy(base)
    p2 = copy.deepcopy(w_fragile["quarterly"]["week_profiles"][2])
    p3 = copy.deepcopy(w_fragile["quarterly"]["week_profiles"][3])
    w_fragile["quarterly"]["week_profiles"][2] = {
        **p3,
        "week": 2,
        "label": "early_fragile_promo",
        "regular_bps": 6100,
        "fragile_bps": 2650,
    }
    w_fragile["quarterly"]["week_profiles"][3] = {
        **p2,
        "week": 3,
        "label": "steady_post_promo",
        "regular_bps": 7900,
        "fragile_bps": 1400,
    }

    # 4. Harsher wear & altered maintenance/wage economics
    w_wear_econ = copy.deepcopy(base)
    w_wear_econ["quarterly"]["wear"]["jam_bps_per_wear"] = 430
    w_wear_econ["quarterly"]["wear"]["defect_bps_per_wear"] = 145
    w_wear_econ["quarterly"]["money"]["maintenance_cost"] = 5200
    w_wear_econ["money"]["worker_shift"] = 15500

    return [
        ("shifted_peaks", w_shifted),
        ("boosted_demand", w_boosted),
        ("elevated_fragile_mix", w_fragile),
        ("harsher_wear_econ", w_wear_econ),
    ]


@pytest.mark.parametrize(("name", "perturbed_world"), _perturbed_worlds(), ids=lambda x: x if isinstance(x, str) else "")
def test_solve_quarterly_generalizes_across_perturbed_worlds_on_holdout_seeds(
    name: str, perturbed_world: dict[str, Any]
):
    dev_seeds = [101, 202]
    holdout_seeds = [5101, 5202, 5303]

    ep = QuarterlyEpisode(perturbed_world, seeds=dev_seeds, max_pilots=14)
    plan = solve(ep)

    assert ep.pilot_used <= 20
    assert ep.pilot_used < ep.max_pilots

    holdout_eval = evaluate_quarterly(perturbed_world, plan, holdout_seeds)
    manual_eval = evaluate_quarterly(perturbed_world, manual_quarterly_value(perturbed_world), holdout_seeds)
    naive_all_eval = evaluate_quarterly(perturbed_world, _static_route_all_plan(perturbed_world), holdout_seeds)

    reward = F(holdout_eval.reward_num, holdout_eval.reward_den)
    manual_reward = F(manual_eval.reward_num, manual_eval.reward_den)
    naive_reward = F(naive_all_eval.reward_num, naive_all_eval.reward_den)

    assert holdout_eval.valid and holdout_eval.feasible and holdout_eval.win, (
        f"Perturbed world {name} failed holdout win: reasons={holdout_eval.reasons}, metrics={holdout_eval.metrics}"
    )
    assert reward >= F(7, 20), f"Perturbed world {name} holdout reward {float(reward):.4f} < 0.35"
    assert reward > manual_reward
    assert reward > naive_reward


@pytest.mark.parametrize("max_pilots", [20, 8, 2, 1])
def test_solve_quarterly_respects_tight_pilot_budgets(max_pilots: int):
    world = load_world()
    ep = QuarterlyEpisode(world, max_pilots=max_pilots)
    plan = solve(ep)

    assert not ep.closed
    assert ep.rejected_calls == 0
    if max_pilots == 1:
        assert ep.pilot_used == 0
    else:
        assert ep.pilot_used < max_pilots
    parsed = parse_quarterly_plan(plan, world)
    assert len(parsed.weeks) == 12


def test_solve_v1_parity_and_bounded_budget_safety():
    world = load_world()
    days = tuple(generate(world, s) for s in world["development_seeds"])

    ep_unbounded = Episode(world, days)
    plan_v1 = solve(ep_unbounded)
    assert ep_unbounded.pilot_used == 39
    ev = evaluate(world, plan_v1, days)
    assert ev.valid and ev.feasible and ev.win
    assert (ev.reward_num, ev.reward_den) == (293219, 704715)

    ep_bounded = Episode(world, days, max_pilots=10)
    plan_bounded = reference.solve_v1(ep_bounded)
    assert not ep_bounded.closed
    assert ep_bounded.pilot_used <= min(20, 10 - 1)
    assert ep_bounded.rejected_calls == 0
    parsed = parse_plan(plan_bounded, world)
    assert parsed.schema_version == 1
    assert evaluate(world, plan_bounded, days).win is True


def test_solve_works_identically_on_strict_duck_typed_socket_client():
    world = load_world()

    ep_direct = QuarterlyEpisode(world, seeds=[11, 29], max_pilots=10)
    plan_direct = reference.solve_quarterly(ep_direct)

    ep_backed = QuarterlyEpisode(world, seeds=[11, 29], max_pilots=10)
    proxy = StrictSocketMockClient(ep_backed)
    plan_proxy = solve(proxy)

    assert plan_proxy == plan_direct
    assert ep_backed.pilot_used == ep_direct.pilot_used

    days = tuple(generate(world, s) for s in world["development_seeds"])
    v1_proxy = StrictSocketMockClient(Episode(world, days))
    v1_plan = solve(v1_proxy)
    ev = evaluate(world, v1_plan, days)
    assert (ev.reward_num, ev.reward_den) == (293219, 704715)



# ==============================================================================
# Cycle 2: Deliverable B — Verda H200 Harbor & RL Scripts (`scripts/verda/*`)
# ==============================================================================

import importlib.util
import os
import stat
import subprocess
import sys

VERDA_DIR = WORKTREE_ROOT / "scripts" / "verda"
PROVISION_SH = VERDA_DIR / "provision_check.sh"
HARBOR_MATRIX_SH = VERDA_DIR / "run_harbor_matrix.sh"
GEN_SFT_PY = VERDA_DIR / "generate_sft_traces.py"
TRAIN_GRPO_PY = VERDA_DIR / "train_grpo_qwen7b.py"
SYNC_EVIDENCE_SH = VERDA_DIR / "sync_evidence.sh"

ALL_VERDA_SCRIPTS = (
    PROVISION_SH,
    HARBOR_MATRIX_SH,
    GEN_SFT_PY,
    TRAIN_GRPO_PY,
    SYNC_EVIDENCE_SH,
)


def _load_script_module(name: str, path: Path):
    assert path.is_file(), f"Missing script: {path}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_verda_cmd(cmd: list[str], *, env_extra: dict[str, str] | None = None, cwd: Path | None = None):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(WORKTREE_ROOT / "src")
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        cmd,
        cwd=str(cwd or WORKTREE_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_verda_scripts_exist_executable_syntax_and_help():
    for script in ALL_VERDA_SCRIPTS:
        assert script.is_file(), f"Missing Verda script: {script}"
        mode = script.stat().st_mode
        assert mode & stat.S_IXUSR, f"Script is not chmod +x executable: {script}"

        if script.suffix == ".sh":
            syntax = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True, timeout=5)
            assert syntax.returncode == 0, f"bash -n failed for {script}: {syntax.stderr}"
            help_res = _run_verda_cmd(["bash", str(script), "--help"])
        else:
            ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
            help_res = _run_verda_cmd([sys.executable, str(script), "--help"])

        assert help_res.returncode == 0, f"--help failed on {script}: {help_res.stderr}"
        assert help_res.stdout.strip(), f"--help produced empty stdout on {script}"


def test_train_grpo_ast_trl_1_18_and_transformers_5_20_signatures():
    assert TRAIN_GRPO_PY.is_file(), f"Missing {TRAIN_GRPO_PY}"
    source = TRAIN_GRPO_PY.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(TRAIN_GRPO_PY))

    # Heavy ML libraries must be lazy-imported inside functions, NEVER at module top-level
    heavy_libs = {"torch", "transformers", "peft", "trl", "datasets", "vllm"}
    for stmt in tree.body:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                root_pkg = alias.name.split(".")[0]
                assert root_pkg not in heavy_libs, f"Top-level ML import forbidden: {alias.name}"
        elif isinstance(stmt, ast.ImportFrom) and stmt.module:
            root_pkg = stmt.module.split(".")[0]
            assert root_pkg not in heavy_libs, f"Top-level ML from-import forbidden: {stmt.module}"

    forbidden_kwargs = {
        "max_prompt_length",
        "max_seq_length",
        "tokenizer",
        "torch_dtype",
        "evaluation_strategy",
    }
    required_kwargs = {
        "processing_class",
        "max_completion_length",
        "max_length",
        "dtype",
        "eval_strategy",
        "vllm_mode",
        "vllm_gpu_memory_utilization",
        "num_generations",
        "save_total_limit",
        "save_steps",
    }

    seen_kwargs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg is not None:
                    assert kw.arg not in forbidden_kwargs, (
                        f"Forbidden TRL/Transformers kwarg {kw.arg!r} found in train_grpo_qwen7b.py"
                    )
                    seen_kwargs.add(kw.arg)

    missing = required_kwargs - seen_kwargs
    assert not missing, f"Missing required TRL/Transformers kwargs in train_grpo_qwen7b.py: {sorted(missing)}"
    assert '["q_proj", "k_proj", "v_proj", "o_proj"]' in source
    assert "all-linear" not in source
    assert "flash-linear-attention" not in source


def test_qwen3_think_block_stripping_and_grpo_reward_parser():
    grpo_mod = _load_script_module("train_grpo_qwen7b", TRAIN_GRPO_PY)
    sft_mod = _load_script_module("generate_sft_traces", GEN_SFT_PY)

    world = load_world()
    manual_plan = manual_quarterly_value(world)

    # 1. Closed <think> containing decoy/invalid JSON followed by fenced real plan
    closed_think_completion = (
        "<think>\n"
        'Let me consider {"fake": 1, "schema_version": 2, "weeks": []} before deciding.\n'
        "</think>\n"
        "```json\n"
        + json.dumps(manual_plan)
        + "\n```"
    )
    stripped = grpo_mod.strip_thinking_blocks(closed_think_completion)
    assert "<think>" not in stripped and "fake" not in stripped
    assert sft_mod.strip_thinking_blocks(closed_think_completion) == stripped

    parsed_plan = grpo_mod.extract_quarterly_plan_from_completion(closed_think_completion)
    assert parsed_plan == manual_plan

    # 2. Tool-call wrapped submission after <think>
    wrapped_completion = (
        "<think>Checking pilot budget...</think>\n"
        + json.dumps({"tool": "submit", "arguments": {"plan": manual_plan}})
    )
    assert grpo_mod.extract_quarterly_plan_from_completion(wrapped_completion) == manual_plan

    # 3. Unclosed <think> (generation truncated inside reasoning block) MUST return None & reward 0.0
    unclosed_think_completion = (
        "<think>\nI am still reasoning and drafted " + json.dumps(manual_plan)
    )
    assert grpo_mod.strip_thinking_blocks(unclosed_think_completion) == ""
    assert grpo_mod.extract_quarterly_plan_from_completion(unclosed_think_completion) is None

    # 4. Exact Fraction-backed GRPO reward function on [closed_valid, unclosed_truncated, invalid_json]
    reward_fn = grpo_mod.build_quarterly_reward_func(world, seeds=[11])
    scores = reward_fn(
        completions=[
            closed_think_completion,
            unclosed_think_completion,
            "<think>done</think>{\"schema_version\": 2, \"weeks\": []}",
        ]
    )
    assert len(scores) == 3
    assert scores[0] == pytest.approx(0.2)
    assert scores[1] == 0.0
    assert scores[2] == 0.0

    # 5. Safe enable_thinking=False chat template helper on both Qwen3 and legacy Qwen2.5 tokenizers
    class Qwen3TokenizerStub:
        def apply_chat_template(self, msgs, tokenize=False, add_generation_prompt=True, enable_thinking=True):
            return f"qwen3:think={enable_thinking}:{len(msgs)}"

    class Qwen25TokenizerStub:
        def apply_chat_template(self, msgs, tokenize=False, add_generation_prompt=True):
            return f"qwen25:{len(msgs)}"

    assert grpo_mod.render_chat_prompt(Qwen3TokenizerStub(), [{"role": "user", "content": "hi"}]) == "qwen3:think=False:1"
    assert grpo_mod.render_chat_prompt(Qwen25TokenizerStub(), [{"role": "user", "content": "hi"}]) == "qwen25:1"


def test_dynamic_model_id_resolution_and_gpu_topology_across_verda_scripts(tmp_path):
    env_ready = tmp_path / "H200_ENV_READY.json"
    hf_home = tmp_path / "hf_cache"
    (hf_home / "hub" / "models--Qwen--Qwen2.5-7B-Instruct").mkdir(parents=True)

    # Case A: H200_ENV_READY.json specifies Qwen/Qwen3.5-9B
    env_ready.write_text(json.dumps({"model_id": "Qwen/Qwen3.5-9B", "ready": True}), encoding="utf-8")
    for sh_script in (PROVISION_SH, HARBOR_MATRIX_SH):
        res = _run_verda_cmd(
            ["bash", str(sh_script), "--dry-run", "--env-ready-file", str(env_ready)],
            env_extra={"RL_MODEL_ID": "", "HF_HOME": str(hf_home)},
        )
        assert res.returncode == 0, res.stderr
        assert "Qwen/Qwen3.5-9B" in res.stdout

    for py_script in (GEN_SFT_PY, TRAIN_GRPO_PY):
        res = _run_verda_cmd(
            [sys.executable, str(py_script), "--dry-run", "--env-ready-file", str(env_ready)],
            env_extra={"RL_MODEL_ID": "", "HF_HOME": str(hf_home)},
        )
        assert res.returncode == 0, res.stderr
        payload = json.loads(res.stdout)
        assert payload["model_id"] == "Qwen/Qwen3.5-9B"

    # Case B: H200_ENV_READY.json specifies Qwen/Qwen3-8B, then overridden by RL_MODEL_ID and --model-id
    env_ready.write_text(json.dumps({"model_id": "Qwen/Qwen3-8B", "ready": True}), encoding="utf-8")
    res_8b = _run_verda_cmd(
        [sys.executable, str(TRAIN_GRPO_PY), "--dry-run", "--env-ready-file", str(env_ready)],
        env_extra={"RL_MODEL_ID": "", "HF_HOME": str(hf_home)},
    )
    assert res_8b.returncode == 0 and json.loads(res_8b.stdout)["model_id"] == "Qwen/Qwen3-8B"

    res_env_override = _run_verda_cmd(
        ["bash", str(PROVISION_SH), "--dry-run", "--env-ready-file", str(env_ready)],
        env_extra={"RL_MODEL_ID": "Qwen/Qwen2.5-7B-Instruct", "HF_HOME": str(hf_home)},
    )
    assert res_env_override.returncode == 0 and "Qwen/Qwen2.5-7B-Instruct" in res_env_override.stdout

    res_cli_override = _run_verda_cmd(
        [
            sys.executable,
            str(TRAIN_GRPO_PY),
            "--dry-run",
            "--env-ready-file",
            str(env_ready),
            "--model-id",
            "Qwen/Qwen3.5-9B",
        ],
        env_extra={"RL_MODEL_ID": "Qwen/Qwen2.5-7B-Instruct", "HF_HOME": str(hf_home)},
    )
    assert res_cli_override.returncode == 0 and json.loads(res_cli_override.stdout)["model_id"] == "Qwen/Qwen3.5-9B"

    # Case C: Missing H200_ENV_READY.json falls back to locally cached model in $HF_HOME/hub
    missing_ready = tmp_path / "missing_ready.json"
    res_cached = _run_verda_cmd(
        [sys.executable, str(GEN_SFT_PY), "--dry-run", "--env-ready-file", str(missing_ready)],
        env_extra={"RL_MODEL_ID": "", "HF_HOME": str(hf_home)},
    )
    assert res_cached.returncode == 0 and json.loads(res_cached.stdout)["model_id"] == "Qwen/Qwen2.5-7B-Instruct"

    # Case D: GPU topology auto-detection (1x 143.8GB H200 colocated, 2x 80GB H100 split, 1x 48GB QLoRA)
    grpo_mod = _load_script_module("train_grpo_qwen7b_gpu", TRAIN_GRPO_PY)
    topo_h200 = grpo_mod.detect_gpu_topology("1:143.8:NVIDIA H200")
    assert topo_h200["mode"] == "colocated_single_80gb_plus"
    assert topo_h200["grpo_vllm_mode"] == "colocate"
    assert topo_h200["harbor_vllm_gpu_memory_utilization"] == pytest.approx(0.35)
    assert topo_h200["grpo_vllm_gpu_memory_utilization"] == pytest.approx(0.30)
    assert topo_h200["use_qlora_4bit"] is False

    topo_2xh100 = grpo_mod.detect_gpu_topology("2:80.0:NVIDIA H100")
    assert topo_2xh100["mode"] == "split_dual_gpu"
    assert topo_2xh100["vllm_cuda_devices"] == "0"
    assert topo_2xh100["trainer_cuda_devices"] == "1"
    assert topo_2xh100["harbor_vllm_gpu_memory_utilization"] == pytest.approx(0.85)

    topo_48gb = grpo_mod.detect_gpu_topology("1:48.0:NVIDIA L40S")
    assert topo_48gb["mode"] == "colocated_qlora_48gb"
    assert topo_48gb["use_qlora_4bit"] is True
    assert topo_48gb["harbor_vllm_gpu_memory_utilization"] == pytest.approx(0.40)

    prov_h200 = _run_verda_cmd(
        ["bash", str(PROVISION_SH), "--dry-run", "--mock-gpu-spec", "1:143.8:NVIDIA H200"]
    )
    assert prov_h200.returncode == 0
    prov_json = json.loads(prov_h200.stdout)
    assert prov_json["gpu_topology"]["mode"] == "colocated_single_80gb_plus"
    assert prov_json["deadman_shutdown"] == "sudo shutdown -h +360"
    for cache_key in (
        "HF_HOME",
        "UV_CACHE_DIR",
        "VLLM_CACHE_ROOT",
        "TRITON_CACHE_DIR",
        "TORCHINDUCTOR_CACHE_DIR",
        "XDG_CACHE_HOME",
        "TMPDIR",
    ):
        assert cache_key in prov_json["fast_cache_env"]


def test_4way_seed_disjointness_and_manual_feasibility_invariant(tmp_path):
    sft_mod = _load_script_module("generate_sft_traces_seeds", GEN_SFT_PY)
    world = load_world()
    dev_seeds = list(world["development_seeds"])
    replay_seeds = json.loads(REPLAY_SEEDS_JSON.read_text(encoding="utf-8"))

    rl_train = sft_mod.sample_feasible_csprng_seeds(
        world, count=3, forbidden=set(dev_seeds) | set(replay_seeds)
    )
    rl_val = sft_mod.sample_feasible_csprng_seeds(
        world, count=2, forbidden=set(dev_seeds) | set(replay_seeds) | set(rl_train)
    )
    blind = sft_mod.sample_feasible_csprng_seeds(
        world,
        count=3,
        forbidden=set(dev_seeds) | set(replay_seeds) | set(rl_train) | set(rl_val),
    )

    sft_mod.verify_4way_seed_disjointness(dev_seeds, replay_seeds, rl_train, rl_val, blind)

    # Every sampled CSPRNG pool must keep manual_quarterly feasible (exact 1/5 baseline invariant)
    for pool in (rl_train, rl_val, blind):
        man_ev = evaluate_quarterly(world, manual_quarterly_value(world), pool)
        assert man_ev.valid and man_ev.feasible and not man_ev.win
        assert (man_ev.reward_num, man_ev.reward_den) == (1, 5)

    # Overlap across any pair MUST raise ValueError and fail CLI non-zero
    with pytest.raises(ValueError, match="overlap"):
        sft_mod.verify_4way_seed_disjointness(dev_seeds, replay_seeds, [dev_seeds[0]], rl_val, blind)
    with pytest.raises(ValueError, match="overlap"):
        sft_mod.verify_4way_seed_disjointness(dev_seeds, replay_seeds, rl_train, [replay_seeds[0]], blind)
    with pytest.raises(ValueError, match="overlap"):
        sft_mod.verify_4way_seed_disjointness(dev_seeds, replay_seeds, rl_train, rl_val, [rl_train[0]])

    bad_blind = tmp_path / "bad_blind.json"
    bad_blind.write_text(json.dumps([replay_seeds[0], 999991]), encoding="utf-8")
    overlap_cli = _run_verda_cmd(
        [sys.executable, str(GEN_SFT_PY), "--dry-run", "--existing-blind-seeds", str(bad_blind)]
    )
    assert overlap_cli.returncode != 0

    bad_rl = tmp_path / "bad_rl.json"
    bad_rl.write_text(json.dumps({"rl_train_seeds": [11], "rl_val_seeds": [777771]}), encoding="utf-8")
    overlap_grpo = _run_verda_cmd(
        [sys.executable, str(TRAIN_GRPO_PY), "--dry-run", "--rl-seeds", str(bad_rl)]
    )
    assert overlap_grpo.returncode != 0

    overlap_harbor = _run_verda_cmd(
        [
            "bash",
            str(HARBOR_MATRIX_SH),
            "--dry-run",
            "--rl-seeds",
            str(bad_rl),
            "--out-dir",
            str(tmp_path / "bad_out"),
        ]
    )
    assert overlap_harbor.returncode != 0


def test_sft_traces_and_grpo_smoke_local_e2e(tmp_path):
    traces_path = tmp_path / "sft_traces.jsonl"
    rl_seeds_path = tmp_path / "rl_seeds.json"
    grpo_out = tmp_path / "grpo_out"

    gen_res = _run_verda_cmd(
        [
            sys.executable,
            str(GEN_SFT_PY),
            "--smoke-local",
            "--train-count",
            "1",
            "--val-count",
            "1",
            "--out",
            str(traces_path),
            "--rl-seeds-out",
            str(rl_seeds_path),
        ]
    )
    assert gen_res.returncode == 0, gen_res.stderr
    assert traces_path.is_file() and rl_seeds_path.is_file()

    lines = [json.loads(line) for line in traces_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) >= 1
    assert lines[0]["win"] is True
    assert F(lines[0]["reward_num"], lines[0]["reward_den"]) > F(1, 5)
    assert any(m["role"] == "assistant" for m in lines[0]["messages"])

    grpo_res = _run_verda_cmd(
        [
            sys.executable,
            str(TRAIN_GRPO_PY),
            "--smoke-local",
            "--traces",
            str(traces_path),
            "--rl-seeds",
            str(rl_seeds_path),
            "--out-dir",
            str(grpo_out),
        ]
    )
    assert grpo_res.returncode == 0, grpo_res.stderr
    metrics_file = grpo_out / "training_metrics.jsonl"
    assert metrics_file.is_file()
    metrics_rows = [json.loads(x) for x in metrics_file.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(metrics_rows) >= 2


def test_harbor_matrix_smoke_local_and_harbor_026_contracts(tmp_path):
    matrix_src = HARBOR_MATRIX_SH.read_text(encoding="utf-8")
    assert "--api-key-name GEMINI_API_KEY" in matrix_src
    assert "gemini/gemini-4-carbon" in matrix_src
    assert "gemini/gemini-3.1-pro-preview" in matrix_src
    assert "artifacts/logs/artifacts/submission.json" in matrix_src
    assert "agent/trajectory.json" in matrix_src
    assert "opencode.db" in matrix_src

    out_dir = tmp_path / "benchmark-v2"
    harbor_runs_dir = tmp_path / "harbor-runs"
    res = _run_verda_cmd(
        [
            "bash",
            str(HARBOR_MATRIX_SH),
            "--smoke-local",
            "--blind-count",
            "2",
            "--out-dir",
            str(out_dir),
            "--harbor-runs-dir",
            str(harbor_runs_dir),
        ]
    )
    assert res.returncode == 0, res.stderr

    blind_file = out_dir / "blind_seeds.json"
    sha_file = out_dir / "blind_seeds.sha256"
    manifest_file = out_dir / "manifest.json"
    assert blind_file.is_file() and sha_file.is_file() and manifest_file.is_file()

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    runs_by_agent = {r["agent"]: r for r in manifest["runs"]}
    assert {"nop", "stop_early", "manual", "oracle"} <= set(runs_by_agent)
    assert runs_by_agent["nop"]["reward_num"] == 0
    assert runs_by_agent["stop_early"]["reward_num"] == 0
    assert (runs_by_agent["manual"]["reward_num"], runs_by_agent["manual"]["reward_den"]) == (1, 5)
    assert runs_by_agent["oracle"]["feasible"] is True
    assert runs_by_agent["oracle"]["win"] is True
    oracle_r = F(runs_by_agent["oracle"]["reward_num"], runs_by_agent["oracle"]["reward_den"])
    assert oracle_r > F(3, 10)

    oracle_eval_path = out_dir / runs_by_agent["oracle"]["evaluation_path"]
    oracle_eval_json = json.loads(oracle_eval_path.read_text(encoding="utf-8"))
    assert "evaluation" in oracle_eval_json and "seeds_sha256" in oracle_eval_json


def test_sync_evidence_scrubs_secrets_and_removes_opencode_sqlite(tmp_path):
    ev_dir = tmp_path / "evidence"
    runs_dir = ev_dir / "harbor-runs" / "trial-01"
    opencode_dir = runs_dir / "agent" / "opencode"
    opencode_dir.mkdir(parents=True)
    fake_gkey = "AI" + "zaSyDummySecretKey1234567890abcdef"
    fake_okey = "sk-" + "proj-DummyOpenAISecret1234567890abcdef"
    fake_pem_hdr = "-----BEGIN " + "OPENSSH PRIVATE KEY-----"
    fake_pem_ftr = "-----END " + "OPENSSH PRIVATE KEY-----"
    (opencode_dir / "opencode.db").write_bytes(b"SQLite format 3\x00" + b"AI" + b"zaSyHiddenInBinary1234567890")
    (runs_dir / "cache.sqlite3").write_bytes(b"SQLite format 3\x00secret")
    (ev_dir / ".env").write_text("GEMINI_API_KEY=" + "AI" + "zaSyDotEnvLeak1234567890abcdef\n", encoding="utf-8")

    traj_path = runs_dir / "agent" / "trajectory.json"
    traj_payload = {
        "agent": "opencode",
        "log": (
            "Auth header: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.secretpayload "
            f"google={fake_gkey} "
            f"openai={fake_okey} "
            f"env: GEMINI_API_KEY={fake_gkey} "
            "ssh_key=/root/.ssh/id_ed25519\n"
            f"{fake_pem_hdr}\n"
            "b3BlbnNzaC1rZXktdjEAAAAABG5vbmU=\n"
            f"{fake_pem_ftr}"
        ),
        "reward": 0.3547,
    }
    traj_path.write_text(json.dumps(traj_payload, indent=2), encoding="utf-8")

    dry = _run_verda_cmd(["bash", str(SYNC_EVIDENCE_SH), "--dry-run", "--dest", str(ev_dir)])
    assert dry.returncode == 0
    assert "opencode.db" in dry.stdout

    smoke = _run_verda_cmd(["bash", str(SYNC_EVIDENCE_SH), "--smoke-local", str(ev_dir)])
    assert smoke.returncode == 0, smoke.stderr

    assert not opencode_dir.exists(), "agent/opencode/ directory must be deleted"
    assert not (runs_dir / "cache.sqlite3").exists(), "*.sqlite* files must be deleted"
    assert not (ev_dir / ".env").exists(), ".env file must be deleted"

    scrubbed_text = traj_path.read_text(encoding="utf-8")
    for leaked in (
        fake_gkey,
        fake_okey,
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        "BEGIN " + "OPENSSH PRIVATE KEY",
        "/root/.ssh/id_ed25519",
    ):
        assert leaked not in scrubbed_text, f"Secret pattern survived scrubbing: {leaked}"

    reloaded = json.loads(scrubbed_text)
    assert reloaded["reward"] == pytest.approx(0.3547)


# ==============================================================================
# Iteration 2 Regression Tests (Fixes 1–5)
# ==============================================================================


def test_solve_v1_bounded_pilot_budgets_and_quarterly_unaffordable_trays_fallback():
    world = load_world()
    days = tuple(generate(world, s) for s in world["development_seeds"])

    # 1. Bounded v1 Episode across mp in (1, 2, 5, 16, 24)
    for mp in (1, 2, 5, 16, 24):
        ep = Episode(world, days, max_pilots=mp)
        plan = solve(ep)
        assert not ep.closed
        assert ep.pilot_used <= min(20, mp - 1), f"mp={mp}: used={ep.pilot_used}"
        assert ep.rejected_calls == 0, f"mp={mp}: rejected={ep.rejected_calls}"
        ev = evaluate(world, plan, days)
        assert ev.valid and ev.feasible
        if mp in (16, 24):
            assert ev.win is True, f"mp={mp} expected win=True, got {ev}"

    # 2. Pre-consumed v1 Episode (15/24 and 23/24 prior calls)
    for pre_used in (15, 23):
        ep_pre = Episode(world, days, max_pilots=24)
        for _ in range(pre_used):
            ep_pre.pilot(manual_value(), days[0].seed)
        assert ep_pre.pilot_used == pre_used
        plan_pre = solve(ep_pre)
        delta = ep_pre.pilot_used - pre_used
        assert delta <= min(20, max(0, 24 - 1 - pre_used))
        assert ep_pre.pilot_used <= 23
        assert ep_pre.rejected_calls == 0
        assert evaluate(world, plan_pre, days).feasible

    # 3. Black-box proxy exposing obs["pilot_budget"]={"used": 0, "max": 24} without Episode attrs
    class BudgetObsV1Proxy:
        __slots__ = ("_ep",)

        def __init__(self, ep: Episode) -> None:
            object.__setattr__(self, "_ep", ep)

        def __getattribute__(self, name: str) -> Any:
            if name in ("observe", "pilot"):
                return object.__getattribute__(self, name)
            raise AttributeError(name)

        def observe(self) -> dict[str, Any]:
            ep = object.__getattribute__(self, "_ep")
            obs = ep.observe()
            obs["pilot_budget"] = {"used": ep.pilot_used, "max": ep.max_pilots}
            return obs

        def pilot(self, plan: Any, seed: int) -> dict[str, Any]:
            ep = object.__getattribute__(self, "_ep")
            return ep.pilot(plan, seed)

    ep_proxy_back = Episode(world, days, max_pilots=24)
    plan_proxy = solve(BudgetObsV1Proxy(ep_proxy_back))
    assert ep_proxy_back.pilot_used <= 20
    assert ep_proxy_back.rejected_calls == 0
    assert evaluate(world, plan_proxy, days).win is True

    # 4. Zero-pilot (max_pilots=1) QuarterlyEpisode when trays are unaffordable (budget=1_400_000)
    w_no_trays = copy.deepcopy(world)
    w_no_trays["quarterly"]["money"]["budget"] = 1_400_000
    ep_q1 = QuarterlyEpisode(w_no_trays, max_pilots=1)
    plan_q1 = solve(ep_q1)
    assert ep_q1.pilot_used == 0
    assert ep_q1.rejected_calls == 0
    assert plan_q1 == manual_quarterly_value(w_no_trays)
    ev_q1 = evaluate_quarterly(w_no_trays, plan_q1, w_no_trays["development_seeds"])
    assert ev_q1.valid and ev_q1.feasible
    assert (ev_q1.reward_num, ev_q1.reward_den) == (1, 5)


def test_harbor_matrix_and_sync_evidence_preserve_sha256_and_manifest_roles(tmp_path):
    import hashlib

    out_dir = tmp_path / "benchmark-v2"
    harbor_runs_dir = tmp_path / "harbor-runs"
    res = _run_verda_cmd(
        [
            "bash",
            str(HARBOR_MATRIX_SH),
            "--smoke-local",
            "--blind-count",
            "2",
            "--out-dir",
            str(out_dir),
            "--harbor-runs-dir",
            str(harbor_runs_dir),
        ]
    )
    assert res.returncode == 0, res.stderr

    blind_file = out_dir / "blind_seeds.json"
    sha_file = out_dir / "blind_seeds.sha256"
    bytes_before = blind_file.read_bytes()
    expected_sha = sha_file.read_text(encoding="utf-8").strip().split()[0]
    assert hashlib.sha256(bytes_before).hexdigest() == expected_sha

    scrub = _run_verda_cmd(["bash", str(SYNC_EVIDENCE_SH), "--smoke-local", str(out_dir)])
    assert scrub.returncode == 0, scrub.stderr

    bytes_after = blind_file.read_bytes()
    assert bytes_after == bytes_before, "sync_evidence.sh mutated clean blind_seeds.json bytes"
    assert hashlib.sha256(bytes_after).hexdigest() == expected_sha

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    runs_by_id = {r["id"]: r for r in manifest["runs"]}
    assert {"nop-01", "stop_early-01", "manual-01", "oracle-01"} <= set(runs_by_id)
    for rid, entry in runs_by_id.items():
        assert entry["run_id"] == rid
        assert entry["dir"] == f"runs/{rid}"
        assert "role" in entry and isinstance(entry["role"], str) and entry["role"]

    assert runs_by_id["nop-01"]["role"] == "nop"
    assert runs_by_id["nop-01"]["submission_path"] is None
    assert runs_by_id["stop_early-01"]["role"] == "stop_early"
    assert runs_by_id["manual-01"]["role"] == "manual"
    assert runs_by_id["oracle-01"]["role"] == "reference"

    matrix_src = HARBOR_MATRIX_SH.read_text(encoding="utf-8")
    assert "--host 0.0.0.0" in matrix_src
    assert "--max-model-len" in matrix_src
    assert "DOCKER_HOST_IP" in matrix_src
    assert "stop_early" in matrix_src


def test_sync_evidence_adversarial_bypasses_and_fail_closed_sqlite_magic(tmp_path):
    ev_dir = tmp_path / "adv_evidence"
    trial_dir = ev_dir / "harbor-runs" / "trial-adv"
    trial_dir.mkdir(parents=True)

    # Clean single-line JSON must remain byte-for-byte untouched
    clean_json = ev_dir / "clean_seeds.json"
    clean_bytes = b"[101, 202, 303]\n"
    clean_json.write_bytes(clean_bytes)

    # SQLite WAL, .db, .env.*, SSH key, and symlink must all be deleted
    (trial_dir / "opencode.db-wal").write_bytes(
        b"SQLite format 3\x00GEMINI_API_KEY=\"secret_in_wal\""
    )
    (trial_dir / "state.db").write_bytes(b"SQLite format 3\x00db_secret")
    (ev_dir / ".env.local").write_text("VERDA_CLIENT_SECRET='dot_env_secret'\n", encoding="utf-8")
    (trial_dir / "id_ed25519").write_text("PRIVATE KEY MATERIAL\n", encoding="utf-8")
    (trial_dir / "dangling_link.json").symlink_to(clean_json)

    traj_path = trial_dir / "trajectory.json"
    traj_payload = {
        "bash": 'export GEMINI_API_KEY="secret_dquote" && VERDA_CLIENT_SECRET=\'secret_squote\'',
        "env": {
            "GEMINI_API_KEY": "secret_dict",
            "VERDA_CLIENT_SECRET": "verda_secret_dict",
        },
        "headers": {
            "authorization": "bearer tok_lower_1234567890",
            "x-upstream": "bearer tok_header_9876543210",
        },
        "usage": {
            "total_tokens": 512,
            "prompt_tokens": 300,
            "max_tokens": 4096,
        },
        "truncated_pem": "-----BEGIN " + "OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAABG5vbmU=",
    }
    traj_path.write_text(json.dumps(traj_payload, indent=2), encoding="utf-8")

    res = _run_verda_cmd(["bash", str(SYNC_EVIDENCE_SH), "--smoke-local", str(ev_dir)])
    assert res.returncode == 0, res.stderr

    assert clean_json.read_bytes() == clean_bytes
    assert not (trial_dir / "opencode.db-wal").exists()
    assert not (trial_dir / "state.db").exists()
    assert not (ev_dir / ".env.local").exists()
    assert not (trial_dir / "id_ed25519").exists()
    assert not (trial_dir / "dangling_link.json").is_symlink()

    scrubbed_raw = traj_path.read_text(encoding="utf-8")
    for secret in (
        "secret_dquote",
        "secret_squote",
        "secret_dict",
        "verda_secret_dict",
        "tok_lower_1234567890",
        "tok_header_9876543210",
        "BEGIN OPENSSH PRIVATE KEY",
        "b3BlbnNzaC1rZXktdjE",
    ):
        assert secret not in scrubbed_raw, f"Adversarial secret leaked: {secret}"

    reloaded = json.loads(scrubbed_raw)
    assert reloaded["env"]["GEMINI_API_KEY"] == "[REDACTED]"
    assert reloaded["usage"] == {"total_tokens": 512, "prompt_tokens": 300, "max_tokens": 4096}

    # Disguised non-.db file with SQLite magic header must fail closed in post-scrub scan
    bad_dir = tmp_path / "disguised_sqlite"
    bad_dir.mkdir(parents=True)
    (bad_dir / "sneaky.bin").write_bytes(b"SQLite format 3\x00hidden_table")
    fail_res = _run_verda_cmd(["bash", str(SYNC_EVIDENCE_SH), "--smoke-local", str(bad_dir)])
    assert fail_res.returncode != 0


def test_think_parser_edge_cases_and_grpo_turn_alignment():
    grpo_mod = _load_script_module("train_grpo_qwen7b_edge", TRAIN_GRPO_PY)
    sft_mod = _load_script_module("generate_sft_traces_edge", GEN_SFT_PY)

    world = load_world()
    manual_plan = manual_quarterly_value(world)
    reward_fn = grpo_mod.build_quarterly_reward_func(world, seeds=[11])

    # 1. Odd quote in prose outside JSON must not invert string tracking (depth == 0)
    odd_quote_comp = '<think>ok</think>24" tray\n' + json.dumps(manual_plan)
    assert grpo_mod.extract_quarterly_plan_from_completion(odd_quote_comp) == manual_plan
    assert reward_fn([odd_quote_comp])[0] == pytest.approx(0.2)

    # 2. Prompt-prefixed <think>\n template (no opening <think> in completion, ends with </think>)
    prefixed_comp = 'draft {"schema_version": 2, "weeks": []}</think>\n' + json.dumps(manual_plan)
    assert grpo_mod.strip_thinking_blocks(prefixed_comp) == json.dumps(manual_plan)
    assert sft_mod.strip_thinking_blocks(prefixed_comp) == json.dumps(manual_plan)
    assert grpo_mod.extract_quarterly_plan_from_completion(prefixed_comp) == manual_plan
    assert reward_fn([prefixed_comp])[0] == pytest.approx(0.2)

    prefixed_only_draft = json.dumps(manual_plan) + "</think>\nStill thinking, no plan."
    assert grpo_mod.extract_quarterly_plan_from_completion(prefixed_only_draft) is None
    assert reward_fn([prefixed_only_draft])[0] == 0.0

    # 3. Nested truncated <think> (outer unclosed) must strip everything from outer <think> -> None (0.0)
    nested_truncated = "<think>outer <think>inner</think> leaked " + json.dumps(manual_plan)
    assert grpo_mod.strip_thinking_blocks(nested_truncated) == ""
    assert sft_mod.strip_thinking_blocks(nested_truncated) == ""
    assert grpo_mod.extract_quarterly_plan_from_completion(nested_truncated) is None
    assert reward_fn([nested_truncated])[0] == 0.0

    # 4. Tool-call extraction accepts both "submit" and "pilot" with "args" or "arguments"
    pilot_tool_comp = json.dumps({"tool": "pilot", "args": {"seed": 11, "plan": manual_plan}})
    assert grpo_mod.extract_quarterly_plan_from_completion(pilot_tool_comp) == manual_plan

    # 5. SFT-to-GRPO prompt turn alignment (messages[:4] when len >= 5 else messages[:2])
    five_msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "obs"},
        {"role": "assistant", "content": "pilot"},
        {"role": "user", "content": "pilot_res"},
        {"role": "assistant", "content": "submit"},
    ]
    assert grpo_mod.select_grpo_prompt_messages(five_msgs) == five_msgs[:4]
    assert grpo_mod.select_grpo_prompt_messages(five_msgs[:3]) == five_msgs[:2]

    # 6. H200 VRAM guards present in AST without forbidden kwargs
    grpo_src = TRAIN_GRPO_PY.read_text(encoding="utf-8")
    assert "gradient_checkpointing=True" in grpo_src
    assert "vllm_max_model_length=4096" in grpo_src
    assert "empty_cache()" in grpo_src


# ==============================================================================
# Iteration 3 Regression Tests (m3_challenger_r2_2 Surgical Fixes)
# ==============================================================================


def test_sync_evidence_r3_token_header_keys_github_pats_and_step3_fail_closed(tmp_path):
    import hashlib

    ev_dir = tmp_path / "r3_evidence"
    bench_dir = ev_dir / "benchmark-v2"
    trial_dir = ev_dir / "harbor-runs" / "trial-r3"
    bench_dir.mkdir(parents=True)
    trial_dir.mkdir(parents=True)

    # Byte-exact blind_seeds.json + blind_seeds.sha256 must stay untouched
    blind_bytes = b"[\n  104729,\n  224737,\n  350377\n]\n"
    blind_path = bench_dir / "blind_seeds.json"
    blind_sha_path = bench_dir / "blind_seeds.sha256"
    blind_path.write_bytes(blind_bytes)
    expected_sha = hashlib.sha256(blind_bytes).hexdigest()
    blind_sha_path.write_text(f"{expected_sha}  blind_seeds.json\n", encoding="utf-8")

    traj_path = trial_dir / "trajectory.json"
    fake_ghp_1 = "ghp_" + "FAKEGITHUBPAT1234567890ABCDEF123456"
    fake_fg_pat = "github_pat_" + "11ABCDEFG0123456789_abcdefghijklmnopqrstuv"
    fake_ghp_2 = "ghp_" + "JSONLFAKEPAT1234567890ABCDEF123456"
    traj_payload = {
        "env": {
            "GEMINI_API_KEY": "gemini_secret_0",
            "VERDA_TOKEN": "verda_tok_secret_1",
            "GITHUB_TOKEN": "gh_env_secret_2",
            "OPENAI_TOKEN": "openai_tok_secret_3",
        },
        "extra_headers": {
            "x-goog-api-key": "secret4_goog_header",
            "x-api-key": "secret5_x_api_key",
            "GITHUB_TOKEN": "secret6_gh_env_dict",
        },
        "git_clone": f"git clone https://{fake_ghp_1}@github.com/org/repo.git",
        "fine_grained_pat": f"token={fake_fg_pat}",
        "usage": {
            "prompt_tokens": 512,
            "completion_tokens": 256,
            "total_tokens": 768,
            "max_tokens": 4096,
            "input_tokens": 300,
            "output_tokens": 212,
            "cached_tokens": 64,
            "reasoning_tokens": 128,
        },
    }
    traj_path.write_text(json.dumps(traj_payload, indent=2), encoding="utf-8")

    events_jsonl = trial_dir / "events.jsonl"
    events_jsonl.write_text(
        json.dumps(
            {
                "headers": {"X-Goog-Api-Key": "jsonl_goog_secret", "X-API-Key": "jsonl_xapi_secret"},
                "pat": fake_ghp_2,
                "metrics": {"prompt_tokens": 100, "reasoning_tokens": 25},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    res = _run_verda_cmd(["bash", str(SYNC_EVIDENCE_SH), "--smoke-local", str(ev_dir)])
    assert res.returncode == 0, res.stderr

    # Clean blind_seeds.json preserved byte-for-byte
    assert blind_path.read_bytes() == blind_bytes
    assert hashlib.sha256(blind_path.read_bytes()).hexdigest() == expected_sha

    scrubbed_traj_text = traj_path.read_text(encoding="utf-8")
    scrubbed_jsonl_text = events_jsonl.read_text(encoding="utf-8")
    combined_text = scrubbed_traj_text + "\n" + scrubbed_jsonl_text
    for leaked in (
        "gemini_secret_0",
        "verda_tok_secret_1",
        "gh_env_secret_2",
        "openai_tok_secret_3",
        "secret4_goog_header",
        "secret5_x_api_key",
        "secret6_gh_env_dict",
        fake_ghp_1,
        fake_fg_pat,
        "jsonl_goog_secret",
        "jsonl_xapi_secret",
        fake_ghp_2,
    ):
        assert leaked not in combined_text, f"Secret survived sync_evidence.sh: {leaked}"

    reloaded_traj = json.loads(scrubbed_traj_text)
    assert reloaded_traj["env"] == {
        "GEMINI_API_KEY": "[REDACTED]",
        "VERDA_TOKEN": "[REDACTED]",
        "GITHUB_TOKEN": "[REDACTED]",
        "OPENAI_TOKEN": "[REDACTED]",
    }
    assert reloaded_traj["extra_headers"] == {
        "x-goog-api-key": "[REDACTED]",
        "x-api-key": "[REDACTED]",
        "GITHUB_TOKEN": "[REDACTED]",
    }
    expected_usage = {
        "prompt_tokens": 512,
        "completion_tokens": 256,
        "total_tokens": 768,
        "max_tokens": 4096,
        "input_tokens": 300,
        "output_tokens": 212,
        "cached_tokens": 64,
        "reasoning_tokens": 128,
    }
    assert reloaded_traj["usage"] == expected_usage
    assert all(type(v) is int for v in reloaded_traj["usage"].values())

    reloaded_ev = json.loads(scrubbed_jsonl_text.strip())
    assert reloaded_ev["headers"] == {"X-Goog-Api-Key": "[REDACTED]", "X-API-Key": "[REDACTED]"}
    assert reloaded_ev["metrics"] == {"prompt_tokens": 100, "reasoning_tokens": 25}

    # Step 3 fail-closed check when an unredacted sensitive JSON dict key survives Step 2 (via invalid UTF-8 byte)
    bad_key_dir = tmp_path / "fail_closed_json_key"
    bad_key_dir.mkdir(parents=True)
    (bad_key_dir / "corrupt.json").write_bytes(
        b"\xff" + json.dumps({"nested": {"VERDA_TOKEN": "unredacted_surviving_token"}}).encode("utf-8")
    )
    fail_key_res = _run_verda_cmd(["bash", str(SYNC_EVIDENCE_SH), "--smoke-local", str(bad_key_dir)])
    assert fail_key_res.returncode != 0
    assert "FAIL-CLOSED SECRET AUDIT VIOLATIONS" in fail_key_res.stderr

    bad_hdr_dir = tmp_path / "fail_closed_jsonl_hdr"
    bad_hdr_dir.mkdir(parents=True)
    (bad_hdr_dir / "corrupt.jsonl").write_bytes(
        b"\xff" + (json.dumps({"headers": {"x-goog-api-key": "unredacted_hdr"}}) + "\n").encode("utf-8")
    )
    fail_hdr_res = _run_verda_cmd(["bash", str(SYNC_EVIDENCE_SH), "--smoke-local", str(bad_hdr_dir)])
    assert fail_hdr_res.returncode != 0
    assert "FAIL-CLOSED SECRET AUDIT VIOLATIONS" in fail_hdr_res.stderr

    # Step 3 fail-closed check when an unredacted ghp_... PAT survives Step 2
    bad_pat_dir = tmp_path / "fail_closed_ghp_pat"
    bad_pat_dir.mkdir(parents=True)
    (bad_pat_dir / "corrupt.log").write_bytes(
        b"\xffgit clone https://" + b"ghp_" + b"SURVIVINGPAT1234567890ABCDEF123456@github.com/org/repo.git\n"
    )
    fail_pat_res = _run_verda_cmd(["bash", str(SYNC_EVIDENCE_SH), "--smoke-local", str(bad_pat_dir)])
    assert fail_pat_res.returncode != 0
    assert "FAIL-CLOSED SECRET AUDIT VIOLATIONS" in fail_pat_res.stderr


def test_strip_thinking_blocks_linear_time_100kb_and_nested_boundaries():
    import time

    grpo_mod = _load_script_module("train_grpo_qwen7b_r3_perf", TRAIN_GRPO_PY)
    sft_mod = _load_script_module("generate_sft_traces_r3_perf", GEN_SFT_PY)

    world = load_world()
    manual_plan = manual_quarterly_value(world)
    oracle_plan = solve(QuarterlyEpisode(world))

    # 1. 102.4 KB deeply nested <think> blocks must finish in < 25 ms in BOTH modules
    deep_nested = ("<think>a" * 6400) + ("</think>" * 6400)
    assert len(deep_nested) == 102_400

    t0 = time.perf_counter()
    grpo_deep_out = grpo_mod.strip_thinking_blocks(deep_nested)
    grpo_deep_ms = (time.perf_counter() - t0) * 1000.0

    t1 = time.perf_counter()
    sft_deep_out = sft_mod.strip_thinking_blocks(deep_nested)
    sft_deep_ms = (time.perf_counter() - t1) * 1000.0

    assert grpo_deep_out == ""
    assert sft_deep_out == ""
    assert grpo_deep_ms < 25.0, f"train_grpo_qwen7b strip_thinking_blocks took {grpo_deep_ms:.2f} ms (>= 25 ms)"
    assert sft_deep_ms < 25.0, f"generate_sft_traces strip_thinking_blocks took {sft_deep_ms:.2f} ms (>= 25 ms)"

    # 2. 102.2 KB unclosed '<think ' without '>' must finish in < 25 ms in BOTH modules
    unclosed_no_gt = "<think " * 14600
    assert len(unclosed_no_gt) == 102_200

    t2 = time.perf_counter()
    grpo_unclosed_out = grpo_mod.strip_thinking_blocks(unclosed_no_gt)
    grpo_unclosed_ms = (time.perf_counter() - t2) * 1000.0

    t3 = time.perf_counter()
    sft_unclosed_out = sft_mod.strip_thinking_blocks(unclosed_no_gt)
    sft_unclosed_ms = (time.perf_counter() - t3) * 1000.0

    assert grpo_unclosed_out == ""
    assert sft_unclosed_out == ""
    assert grpo_unclosed_ms < 25.0, (
        f"train_grpo_qwen7b unclosed strip_thinking_blocks took {grpo_unclosed_ms:.2f} ms (>= 25 ms)"
    )
    assert sft_unclosed_ms < 25.0, (
        f"generate_sft_traces unclosed strip_thinking_blocks took {sft_unclosed_ms:.2f} ms (>= 25 ms)"
    )

    # 3. Outer unclosed nested <think> must strip trailing plan -> "" / None
    nested_leak = "<think>outer <think>inner</think> leak " + json.dumps(manual_plan)
    assert grpo_mod.strip_thinking_blocks(nested_leak) == ""
    assert sft_mod.strip_thinking_blocks(nested_leak) == ""
    assert grpo_mod.extract_quarterly_plan_from_completion(nested_leak) is None

    # 4. Prompt-prefixed </think> with submit tool call extracts oracle_plan
    prefixed_oracle = "reasoning...\n</think>\n" + json.dumps(
        {"name": "submit", "arguments": {"plan": oracle_plan}}
    )
    assert grpo_mod.extract_quarterly_plan_from_completion(prefixed_oracle) == oracle_plan

    # 5. Non-<think> tag prefixes (e.g. <thinking_about>, <think-step>) are not stripped
    assert grpo_mod.strip_thinking_blocks("<thinking_about>keep</thinking_about>") == (
        "<thinking_about>keep</thinking_about>"
    )
    assert sft_mod.strip_thinking_blocks("<think-step>keep") == "<think-step>keep"


def test_extract_quarterly_plan_raw_decode_prose_braces_and_dual_world_seed_sampling():
    grpo_mod = _load_script_module("train_grpo_qwen7b_r3_json", TRAIN_GRPO_PY)
    sft_mod = _load_script_module("generate_sft_traces_r3_seeds", GEN_SFT_PY)

    world = load_world()
    manual_plan = manual_quarterly_value(world)
    reward_fn = grpo_mod.build_quarterly_reward_func(world, seeds=[11])

    # 1. Prose brace + quote ('Note {24" tray}:\n' + manual_plan) must extract manual_plan and score 0.2
    prose_brace_comp = 'Note {24" tray}:\n' + json.dumps(manual_plan)
    assert grpo_mod.extract_quarterly_plan_from_completion(prose_brace_comp) == manual_plan
    assert reward_fn([prose_brace_comp])[0] == pytest.approx(0.2)

    # 2. Pathological nested malformed JSON prefix must not raise RecursionError
    deep_malformed = ('{"a":' * 1500) + "\n" + json.dumps(manual_plan)
    assert grpo_mod.extract_quarterly_plan_from_completion(deep_malformed) == manual_plan

    # 3. Fallback RL seed sampling must verify manual_quarterly feasibility on extra_worlds (base_world) too
    strict_base = copy.deepcopy(world)
    strict_base["quarterly"]["threshold_bps"]["good_pooled"] = 10_001  # impossible manual feasibility
    relaxed_perturbed = copy.deepcopy(world)
    with pytest.raises(RuntimeError):
        sft_mod.sample_feasible_csprng_seeds(
            relaxed_perturbed,
            count=1,
            forbidden={11, 29, 47},
            max_attempts=4,
            extra_worlds=[strict_base],
        )


