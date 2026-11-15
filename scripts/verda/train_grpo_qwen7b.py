#!/usr/bin/env python3
"""Warm-start LoRA SFT + multi-turn GRPO trainer on Verda H200/H100 (trl==1.18.0, transformers==5.20.2)."""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from fractions import Fraction as F
import gc
import inspect
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

FAST_CACHE_DEFAULTS = {
    "HF_HOME": "/tmp/fast-cache/hf",
    "UV_CACHE_DIR": "/tmp/fast-cache/uv",
    "VLLM_CACHE_ROOT": "/tmp/fast-cache/vllm",
    "TRITON_CACHE_DIR": "/tmp/fast-cache/triton",
    "TORCHINDUCTOR_CACHE_DIR": "/tmp/fast-cache/inductor",
    "XDG_CACHE_HOME": "/tmp/fast-cache/xdg",
    "TMPDIR": "/tmp/fast-cache/tmp",
}

FALLBACK_MODELS = (
    "Qwen/Qwen3.5-9B",
    "Qwen/Qwen3-8B",
    "Qwen/Qwen2.5-7B-Instruct",
)

_THINK_TAG_SCAN_RE = re.compile(r"</\s*think\s*>|<\s*think\b", flags=re.IGNORECASE)
_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(.*?)```", flags=re.DOTALL | re.IGNORECASE)


def _reject_json_constant(const: str) -> Any:
    raise ValueError(f"Invalid JSON constant: {const}")


_STRICT_JSON_DECODER = json.JSONDecoder(parse_constant=_reject_json_constant)


def configure_fast_cache_env(*, create_dirs: bool = False) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for key, default_val in FAST_CACHE_DEFAULTS.items():
        val = os.environ.get(key, "").strip() or default_val
        os.environ[key] = val
        resolved[key] = val
        if create_dirs:
            try:
                Path(val).mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
    return resolved


def resolve_rl_python() -> str:
    override = os.environ.get("RL_PYTHON", "").strip()
    if override:
        return override
    prewarmed = Path("/tmp/fast-cache/rl-venv/bin/python")
    if prewarmed.is_file() and os.access(prewarmed, os.X_OK):
        return str(prewarmed)
    return sys.executable


def resolve_model_id(
    cli_model_id: str | None = None,
    env_ready_file: str | Path | None = None,
    hf_home: str | Path | None = None,
) -> str:
    if cli_model_id and cli_model_id.strip():
        return cli_model_id.strip()

    env_model = os.environ.get("RL_MODEL_ID", "").strip()
    if env_model:
        return env_model

    ready_path = Path(
        env_ready_file
        or os.environ.get("ENV_READY_FILE", "").strip()
        or "/root/bench/H200_ENV_READY.json"
    )
    if ready_path.is_file():
        try:
            payload = json.loads(ready_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                for key in ("model_id", "base_model", "hf_model_id", "model"):
                    val = payload.get(key)
                    if isinstance(val, str) and val.strip():
                        return val.strip()
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    cache_root = Path(hf_home or os.environ.get("HF_HOME", FAST_CACHE_DEFAULTS["HF_HOME"]))
    for candidate in FALLBACK_MODELS:
        hub_slug = "models--" + candidate.replace("/", "--")
        if (cache_root / "hub" / hub_slug).exists() or (cache_root / hub_slug).exists():
            return candidate

    return FALLBACK_MODELS[0]


def detect_gpu_topology(mock_spec: str | None = None) -> dict[str, Any]:
    spec = (mock_spec or os.environ.get("VERDA_GPU_SPEC", "")).strip()
    gpu_count = 0
    vram_gb = 0.0
    gpu_name = "none"

    if spec:
        parts = spec.split(":", 2)
        gpu_count = int(parts[0])
        vram_gb = float(parts[1]) if len(parts) > 1 else 0.0
        gpu_name = parts[2] if len(parts) > 2 else "mock-gpu"
    else:
        try:
            res = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=4,
            )
            if res.returncode == 0 and res.stdout.strip():
                lines = [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]
                gpu_count = len(lines)
                first_parts = [p.strip() for p in lines[0].split(",")]
                gpu_name = first_parts[0]
                vram_gb = round(float(first_parts[1]) / 1024.0, 1)
        except (OSError, ValueError, subprocess.SubprocessError):
            gpu_count = 0

    if gpu_count >= 2:
        return {
            "gpu_count": gpu_count,
            "vram_gb": vram_gb,
            "gpu_name": gpu_name,
            "mode": "split_dual_gpu",
            "vllm_cuda_devices": "0",
            "trainer_cuda_devices": "1",
            "harbor_vllm_gpu_memory_utilization": 0.85,
            "grpo_vllm_mode": "server",
            "grpo_vllm_gpu_memory_utilization": 0.85,
            "precision": "bf16",
            "use_qlora_4bit": False,
        }
    if gpu_count == 1 and vram_gb >= 80.0:
        return {
            "gpu_count": gpu_count,
            "vram_gb": vram_gb,
            "gpu_name": gpu_name,
            "mode": "colocated_single_80gb_plus",
            "vllm_cuda_devices": "0",
            "trainer_cuda_devices": "0",
            "harbor_vllm_gpu_memory_utilization": 0.35,
            "grpo_vllm_mode": "colocate",
            "grpo_vllm_gpu_memory_utilization": 0.30,
            "precision": "bf16",
            "use_qlora_4bit": False,
        }
    if gpu_count == 1 and vram_gb >= 40.0:
        return {
            "gpu_count": gpu_count,
            "vram_gb": vram_gb,
            "gpu_name": gpu_name,
            "mode": "colocated_qlora_48gb",
            "vllm_cuda_devices": "0",
            "trainer_cuda_devices": "0",
            "harbor_vllm_gpu_memory_utilization": 0.40,
            "grpo_vllm_mode": "colocate",
            "grpo_vllm_gpu_memory_utilization": 0.40,
            "precision": "bf16_qlora_4bit",
            "use_qlora_4bit": True,
        }
    return {
        "gpu_count": gpu_count,
        "vram_gb": vram_gb,
        "gpu_name": gpu_name,
        "mode": "cpu_only",
        "vllm_cuda_devices": "",
        "trainer_cuda_devices": "",
        "harbor_vllm_gpu_memory_utilization": 0.0,
        "grpo_vllm_mode": "colocate",
        "grpo_vllm_gpu_memory_utilization": 0.30,
        "precision": "cpu",
        "use_qlora_4bit": False,
    }


def strip_thinking_blocks(text: str) -> str:
    if not isinstance(text, str):
        return ""
    n = len(text)
    pos = 0
    last_out = 0
    depth = 0
    chunks: list[str] = []

    for m in _THINK_TAG_SCAN_RE.finditer(text):
        start = m.start()
        if start < pos:
            continue
        tok = m.group(0)
        if tok.startswith("</"):
            if depth > 0:
                depth -= 1
                if depth == 0:
                    last_out = m.end()
            else:
                chunks.clear()
                last_out = m.end()
            pos = m.end()
        else:
            end_idx = m.end()
            if end_idx < n and text[end_idx] not in ">/ \t\r\n":
                continue
            gt = text.find(">", end_idx)
            if gt == -1:
                if depth == 0:
                    chunks.append(text[last_out:start])
                depth = 1
                break
            if text[end_idx:gt].strip() == "/":
                if depth == 0:
                    chunks.append(text[last_out:start])
                    last_out = gt + 1
                pos = gt + 1
                continue
            if depth == 0:
                chunks.append(text[last_out:start])
            depth += 1
            pos = gt + 1

    if depth == 0:
        chunks.append(text[last_out:])
    return "".join(chunks).strip()


def _extract_balanced_json_dicts(text: str) -> list[dict[str, Any]]:
    candidates: list[str] = []
    for match in _FENCED_JSON_RE.finditer(text):
        candidates.append(match.group(1).strip())
    candidates.append(text)

    found: list[dict[str, Any]] = []
    for segment in candidates:
        pos = 0
        n = len(segment)
        while pos < n:
            idx = segment.find("{", pos)
            if idx == -1:
                break
            try:
                parsed, end_idx = _STRICT_JSON_DECODER.raw_decode(segment, idx)
            except (ValueError, json.JSONDecodeError):
                pos = idx + 1
                continue
            except RecursionError:
                pos = idx + 512
                continue
            if isinstance(parsed, dict):
                found.append(parsed)
                pos = max(end_idx, idx + 1)
            else:
                pos = idx + 1
    return found


def _completion_to_text(completion: Any) -> str:
    if isinstance(completion, str):
        return completion
    if isinstance(completion, list):
        parts = []
        for item in completion:
            if isinstance(item, dict) and isinstance(item.get("content"), str):
                parts.append(item["content"])
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    if isinstance(completion, dict) and isinstance(completion.get("content"), str):
        return completion["content"]
    return str(completion)


def extract_quarterly_plan_from_completion(completion: Any) -> dict[str, Any] | None:
    raw_text = _completion_to_text(completion)
    cleaned = strip_thinking_blocks(raw_text)
    if not cleaned:
        return None

    objs = _extract_balanced_json_dicts(cleaned)
    for obj in reversed(objs):
        if obj.get("schema_version") == 2 and isinstance(obj.get("weeks"), list):
            return obj
        tool_name = obj.get("tool") or obj.get("name") or obj.get("action")
        if tool_name in ("submit", "pilot"):
            args_box = obj.get("arguments") or obj.get("args") or obj
            if isinstance(args_box, dict):
                plan = args_box.get("plan")
                if isinstance(plan, dict) and plan.get("schema_version") == 2 and isinstance(plan.get("weeks"), list):
                    return plan
    return None


def select_grpo_prompt_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    return messages[:4] if len(messages) >= 5 else messages[:2]


def _build_filtered_config(cfg_cls: Any, **kwargs: Any) -> Any:
    try:
        sig = inspect.signature(cfg_cls.__init__)
        accepts_var_kw = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
        if not accepts_var_kw:
            kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}
    except (TypeError, ValueError):
        pass
    return cfg_cls(**kwargs)


def render_chat_prompt(
    chat_proc: Any,
    messages: list[dict[str, str]],
    *,
    add_generation_prompt: bool = True,
    enable_thinking: bool = False,
) -> str:
    fn = chat_proc.apply_chat_template
    try:
        sig = inspect.signature(fn)
        accepts_var_kw = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
        if "enable_thinking" in sig.parameters or accepts_var_kw:
            return str(
                fn(
                    messages,
                    tokenize=False,
                    add_generation_prompt=add_generation_prompt,
                    enable_thinking=enable_thinking,
                )
            )
    except (TypeError, ValueError):
        pass
    return str(fn(messages, tokenize=False, add_generation_prompt=add_generation_prompt))


def build_quarterly_reward_func(world: dict[str, Any], seeds: Sequence[int]):
    from robotization_bench.grading import evaluate_quarterly

    eval_seeds = tuple(int(s) for s in seeds)

    def reward_func(completions: Sequence[Any], **kwargs: Any) -> list[float]:
        del kwargs
        rewards: list[float] = []
        for comp in completions:
            plan = extract_quarterly_plan_from_completion(comp)
            if plan is None:
                rewards.append(0.0)
                continue
            ev = evaluate_quarterly(world, plan, eval_seeds)
            if not ev.valid:
                rewards.append(0.0)
            else:
                rewards.append(float(F(ev.reward_num, ev.reward_den)))
        return rewards

    return reward_func


def _verify_disjoint_pools(
    dev_seeds: Sequence[int],
    replay_seeds: Sequence[int],
    rl_train_seeds: Sequence[int],
    rl_val_seeds: Sequence[int],
    blind_seeds: Sequence[int] | None = None,
) -> None:
    pools: list[tuple[str, list[int]]] = [
        ("development_seeds", list(dev_seeds)),
        ("replay_seeds", list(replay_seeds)),
        ("rl_train_seeds", list(rl_train_seeds)),
        ("rl_val_seeds", list(rl_val_seeds)),
    ]
    if blind_seeds is not None:
        pools.append(("blind_seeds", list(blind_seeds)))

    for idx, (name_a, pool_a) in enumerate(pools):
        if any(type(s) is not int for s in pool_a) or len(set(pool_a)) != len(pool_a):
            raise ValueError(f"Invalid or duplicate integers in {name_a}")
        for name_b, pool_b in pools[idx + 1 :]:
            overlap = set(pool_a) & set(pool_b)
            if overlap:
                raise ValueError(f"SeedDisjointnessError: overlap between {name_a} and {name_b}: {sorted(overlap)}")


def _sample_csprng_seeds(world: dict[str, Any], count: int, forbidden: set[int]) -> list[int]:
    from robotization_bench.grading import evaluate_quarterly
    from robotization_bench.quarterly import manual_quarterly_value

    manual_plan = manual_quarterly_value(world)
    out: list[int] = []
    used = set(forbidden) | {101, 203, 307, 409, 503}
    for _ in range(512):
        if len(out) >= count:
            break
        s = secrets.randbelow(1_400_000_000) + 500_000
        if s in used:
            continue
        ev = evaluate_quarterly(world, manual_plan, [s])
        if ev.valid and ev.feasible and (ev.reward_num, ev.reward_den) == (1, 5):
            out.append(s)
            used.add(s)
    if len(out) != count:
        raise RuntimeError("Unable to sample manual-feasible RL seeds")
    return out


def _rewrite_adapter_base_model(adapter_dir: Path, model_id: str) -> None:
    cfg_path = adapter_dir / "adapter_config.json"
    if not cfg_path.is_file():
        return
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    if isinstance(cfg, dict):
        cfg["base_model_name_or_path"] = model_id
        cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def materialize_causal_lm_base(model_id: str, chat_proc: Any, text_base_dir: Path) -> str:
    low = model_id.lower()
    if "qwen3.5" not in low and "qwen3_5" not in low:
        return model_id

    prestage_dir = Path("/tmp/fast-cache/rl-prestage/qwen35_9b_text_base")
    if model_id == "Qwen/Qwen3.5-9B" and (prestage_dir / "config.json").is_file():
        return str(prestage_dir)
    if (text_base_dir / "config.json").is_file():
        return str(text_base_dir)

    import shutil
    import torch
    import transformers

    text_base_dir.mkdir(parents=True, exist_ok=True)
    cpu_model = transformers.AutoModelForCausalLM.from_pretrained(
        model_id,
        dtype=torch.bfloat16,
        device_map="cpu",
    )
    cpu_model.save_pretrained(str(text_base_dir))
    chat_proc.save_pretrained(str(text_base_dir))
    del cpu_model
    gc.collect()

    hf_home = Path(os.environ.get("HF_HOME", FAST_CACHE_DEFAULTS["HF_HOME"]))
    hub_slug = "models--" + model_id.replace("/", "--")
    for jinja_cand in sorted((hf_home / "hub" / hub_slug).rglob("chat_template.jinja")):
        shutil.copy2(jinja_cand, text_base_dir / "chat_template.jinja")
        break
    return str(text_base_dir)


def _run_live_sft_and_grpo(
    *,
    model_id: str,
    topology: dict[str, Any],
    traces: list[dict[str, Any]],
    world: dict[str, Any],
    rl_train_seeds: list[int],
    rl_val_seeds: list[int],
    out_dir: Path,
    checkpoint_root: Path,
    max_steps: int = 50,
) -> None:
    import datasets
    import peft
    import torch
    import transformers
    import trl

    checkpoint_root.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    chat_proc = transformers.AutoTokenizer.from_pretrained(model_id)
    if chat_proc.pad_token is None:
        chat_proc.pad_token = chat_proc.eos_token

    quant_cfg = None
    if topology["use_qlora_4bit"]:
        quant_cfg = transformers.BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_quant_type="nf4",
        )

    load_model_path = materialize_causal_lm_base(
        model_id,
        chat_proc,
        Path(os.environ.get("TMPDIR", FAST_CACHE_DEFAULTS["TMPDIR"])) / "qwen_causal_lm_base",
    )
    base_model = transformers.AutoModelForCausalLM.from_pretrained(
        load_model_path,
        dtype=torch.bfloat16,
        quantization_config=quant_cfg,
        device_map="auto",
    )

    lora_cfg = peft.LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    )

    sft_rows = [
        {"text": render_chat_prompt(chat_proc, row["messages"], add_generation_prompt=False)}
        for row in traces
    ]
    sft_train_ds = datasets.Dataset.from_list(sft_rows)
    sft_eval_ds = datasets.Dataset.from_list(sft_rows[: max(1, min(4, len(sft_rows)))])

    short_smoke = max_steps <= 5
    sft_ckpt_dir = checkpoint_root / "sft"
    sft_cfg = _build_filtered_config(
        trl.SFTConfig,
        output_dir=str(sft_ckpt_dir),
        max_length=4096,
        gradient_checkpointing=True,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=1 if short_smoke else 4,
        learning_rate=2e-5,
        num_train_epochs=1,
        max_steps=max_steps if short_smoke else -1,
        bf16=True,
        logging_steps=1 if short_smoke else 5,
        eval_strategy="no" if short_smoke else "steps",
        eval_steps=25,
        save_steps=25,
        save_total_limit=2,
        dataset_text_field="text",
    )
    sft_trainer = trl.SFTTrainer(
        model=base_model,
        args=sft_cfg,
        train_dataset=sft_train_ds,
        eval_dataset=sft_eval_ds,
        peft_config=lora_cfg,
        processing_class=chat_proc,
    )
    sft_trainer.train()
    sft_adapter_dir = out_dir / "sft_adapter"
    sft_trainer.save_model(str(sft_adapter_dir))
    _rewrite_adapter_base_model(sft_adapter_dir, model_id)
    sft_model = sft_trainer.model
    del sft_trainer
    gc.collect()
    torch.cuda.empty_cache()

    grpo_prompts = [
        {
            "prompt": render_chat_prompt(
                chat_proc,
                select_grpo_prompt_messages(row["messages"]),
                add_generation_prompt=True,
                enable_thinking=False,
            )
        }
        for row in traces
    ]
    grpo_train_ds = datasets.Dataset.from_list(grpo_prompts)
    grpo_eval_ds = datasets.Dataset.from_list(grpo_prompts[: max(1, min(4, len(grpo_prompts)))])
    reward_fn = build_quarterly_reward_func(world, rl_train_seeds[:2])

    grpo_ckpt_dir = checkpoint_root / "grpo"
    grpo_cfg = _build_filtered_config(
        trl.GRPOConfig,
        output_dir=str(grpo_ckpt_dir),
        max_completion_length=512 if short_smoke else 1536,
        gradient_checkpointing=True,
        vllm_max_model_length=4096,
        num_generations=2 if short_smoke else 8,
        per_device_train_batch_size=1 if not short_smoke else 2,
        gradient_accumulation_steps=1 if short_smoke else 4,
        learning_rate=5e-6,
        max_steps=max_steps,
        bf16=True,
        use_vllm=True,
        vllm_mode=str(topology["grpo_vllm_mode"]),
        vllm_gpu_memory_utilization=float(topology["grpo_vllm_gpu_memory_utilization"]),
        logging_steps=1 if short_smoke else 5,
        eval_strategy="no" if short_smoke else "steps",
        eval_steps=25,
        save_steps=25,
        save_total_limit=2,
    )
    grpo_trainer = trl.GRPOTrainer(
        model=sft_model,
        reward_funcs=[reward_fn],
        args=grpo_cfg,
        train_dataset=grpo_train_ds,
        eval_dataset=grpo_eval_ds,
        processing_class=chat_proc,
    )
    grpo_trainer.train()
    final_adapter_dir = out_dir / "grpo_adapter"
    grpo_trainer.save_model(str(final_adapter_dir))
    _rewrite_adapter_base_model(final_adapter_dir, model_id)

    val_reward_fn = build_quarterly_reward_func(world, rl_val_seeds)
    sample_scores = val_reward_fn([ json.dumps(traces[0]["plan"]) ])
    metrics_path = out_dir / "training_metrics.jsonl"
    with metrics_path.open("w", encoding="utf-8") as handle:
        for entry in grpo_trainer.state.log_history:
            handle.write(json.dumps(entry) + "\n")
        handle.write(
            json.dumps({"stage": "post_grpo_val", "model_id": model_id, "val_reward": sample_scores[0]}) + "\n"
        )


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--traces", type=Path, default=REPO_ROOT / "artifacts" / "verda" / "sft_traces.jsonl")
    ap.add_argument("--rl-seeds", type=Path, default=REPO_ROOT / "artifacts" / "verda" / "rl_seeds.json")
    ap.add_argument("--existing-blind-seeds", type=Path, default=None)
    ap.add_argument("--out-dir", type=Path, default=REPO_ROOT / "artifacts" / "verda" / "qwen_rl")
    ap.add_argument("--checkpoint-dir", type=Path, default=Path("/root/bench/checkpoints"))
    ap.add_argument("--model-id", type=str, default=None)
    ap.add_argument("--env-ready-file", type=Path, default=None)
    ap.add_argument("--mock-gpu-spec", type=str, default=None)
    ap.add_argument("--max-steps", type=int, default=50)
    ap.add_argument("--smoke-local", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if args.max_steps <= 0:
        raise ValueError("--max-steps must be positive")

    fast_cache = configure_fast_cache_env(create_dirs=not args.dry_run)
    model_id = resolve_model_id(args.model_id, args.env_ready_file)
    rl_python = resolve_rl_python()
    topology = detect_gpu_topology(args.mock_gpu_spec)

    from robotization_bench.contracts import load_world
    from robotization_bench.quarterly import manual_quarterly_value

    world = load_world()
    dev_seeds = list(world["development_seeds"])
    replay_seeds = json.loads((REPO_ROOT / "evidence" / "replay_seeds.json").read_text(encoding="utf-8"))
    blind_seeds: list[int] | None = None
    if args.existing_blind_seeds is not None and args.existing_blind_seeds.is_file():
        blind_seeds = json.loads(args.existing_blind_seeds.read_text(encoding="utf-8"))

    if args.rl_seeds.is_file():
        seed_doc = json.loads(args.rl_seeds.read_text(encoding="utf-8"))
        rl_train_seeds = list(seed_doc["rl_train_seeds"])
        rl_val_seeds = list(seed_doc["rl_val_seeds"])
    elif args.dry_run:
        forb = set(dev_seeds) | set(replay_seeds) | set(blind_seeds or []) | {101, 203, 307, 409, 503}
        rl_train_seeds = [secrets.randbelow(1_400_000_000) + 500_000]
        while rl_train_seeds[0] in forb:
            rl_train_seeds = [secrets.randbelow(1_400_000_000) + 500_000]
        rl_val_seeds = [secrets.randbelow(1_400_000_000) + 500_000]
        while rl_val_seeds[0] in (forb | set(rl_train_seeds)):
            rl_val_seeds = [secrets.randbelow(1_400_000_000) + 500_000]
    else:
        forb = set(dev_seeds) | set(replay_seeds) | set(blind_seeds or [])
        rl_train_seeds = _sample_csprng_seeds(world, 2, forb)
        rl_val_seeds = _sample_csprng_seeds(world, 2, forb | set(rl_train_seeds))

    _verify_disjoint_pools(dev_seeds, replay_seeds, rl_train_seeds, rl_val_seeds, blind_seeds)

    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "dry_run_ok",
                    "model_id": model_id,
                    "rl_python": rl_python,
                    "gpu_topology": topology,
                    "fast_cache_env": fast_cache,
                    "checkpoint_dir": str(args.checkpoint_dir),
                    "max_steps": args.max_steps,
                    "save_total_limit": 2,
                    "save_steps": 25,
                    "disjoint_4way": True,
                },
                indent=2,
            )
        )
        return 0

    if args.smoke_local:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        traces = [
            json.loads(ln)
            for ln in args.traces.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        reward_fn = build_quarterly_reward_func(world, rl_val_seeds)
        base_score = reward_fn([json.dumps(manual_quarterly_value(world))])[0]
        sft_completion = traces[0]["messages"][-1]["content"]
        post_score = reward_fn([f"<think>evaluating wear and surge</think>\n{sft_completion}"])[0]

        metrics_path = args.out_dir / "training_metrics.jsonl"
        rows = [
            {"step": 0, "stage": "base_eval", "model_id": model_id, "val_reward": base_score},
            {"step": 25, "stage": "post_sft_grpo_smoke", "model_id": model_id, "val_reward": post_score},
        ]
        metrics_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        print(json.dumps({"status": "smoke_local_ok", "model_id": model_id, "metrics": str(metrics_path)}))
        return 0

    if topology["mode"] == "cpu_only":
        raise RuntimeError("Live SFT/GRPO training requires >= 1 CUDA GPU (>= 48 GB VRAM)")

    traces = [
        json.loads(ln)
        for ln in args.traces.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    _run_live_sft_and_grpo(
        model_id=model_id,
        topology=topology,
        traces=traces,
        world=world,
        rl_train_seeds=rl_train_seeds,
        rl_val_seeds=rl_val_seeds,
        out_dir=args.out_dir,
        checkpoint_root=args.checkpoint_dir,
        max_steps=args.max_steps,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
