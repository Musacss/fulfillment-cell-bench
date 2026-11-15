"""Run inside the clean airgapped verifier. Import exclusively from the trusted image."""

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "trusted" / "src"))

from robotization_bench.contracts import load_world  # noqa: E402
from robotization_bench.scenarios import generate  # noqa: E402
from robotization_bench.verifier import verify_file, verify_quarterly_file  # noqa: E402


def _prepare_clean_verdict_dir(out: Path) -> None:
    if out.is_symlink() or out.is_file():
        out.unlink()
    elif out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, mode=0o755, exist_ok=True)
    # Fail-closed baseline before parsing or evaluating any untrusted input.
    (out / "reward.txt").write_text("0.0\n", encoding="utf-8")


def grade(submission: Path, out: Path, *, mode: str | None = None) -> None:
    _prepare_clean_verdict_dir(out)

    provenance = json.loads((HERE / "provenance.json").read_text(encoding="utf-8"))
    if mode is not None:
        raw_mode = mode
    elif "BENCH_MODE" in os.environ:
        raw_mode = os.environ["BENCH_MODE"]
    else:
        raw_mode = "v1" if provenance.get("schema_version") == 1 else "quarterly"

    resolved_mode = raw_mode.strip().lower()
    if resolved_mode not in ("quarterly", "v1"):
        raise ValueError(f"Unsupported BENCH_MODE: {raw_mode!r}")

    w = load_world()
    seed_bytes = (HERE / "seeds.json").read_bytes()
    seeds = json.loads(seed_bytes)

    if resolved_mode == "v1":
        days = tuple(generate(w, int(seed)) for seed in seeds)
        result = verify_file(w, submission, days)
        world_id = w["world_id"]
    else:
        result = verify_quarterly_file(w, submission, seeds)
        world_id = w.get("quarterly", {}).get("world_id", w["world_id"])

    payload = {
        "evaluation": asdict(result),
        "seeds_sha256": hashlib.sha256(seed_bytes).hexdigest(),
        "world": world_id,
        "source": provenance,
    }
    (out / "evaluation.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    # Harbor expects a scalar float; the authoritative fraction is kept beside it in evaluation.json.
    (out / "reward.txt").write_text(f"{result.reward_num / result.reward_den}\n", encoding="utf-8")


if __name__ == "__main__":
    submission_path = Path(os.environ.get("BENCH_SUBMISSION", "/logs/artifacts/submission.json"))
    verifier_dir = Path(os.environ.get("BENCH_VERIFIER_DIR", "/logs/verifier"))
    grade(submission_path, verifier_dir)
