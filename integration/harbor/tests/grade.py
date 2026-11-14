"""Run inside the clean verifier. Import exclusively from the trusted image."""
from dataclasses import asdict
from pathlib import Path
import hashlib
import json
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/"trusted"/"src"))
from robotization_bench.contracts import load_world
from robotization_bench.scenarios import generate
from robotization_bench.verifier import verify_file


def grade(submission: Path, out: Path):
    w = load_world()
    seed_bytes = (HERE/"seeds.json").read_bytes()
    days = tuple(generate(w,seed) for seed in json.loads(seed_bytes))
    result = verify_file(w,submission,days)
    out.mkdir(parents=True,exist_ok=True)
    (out/"evaluation.json").write_text(json.dumps({"evaluation":asdict(result),
        "seeds_sha256":hashlib.sha256(seed_bytes).hexdigest(),"world":w["world_id"],
        "source":json.loads((HERE/"provenance.json").read_text())},indent=2))
    # Harbor expects a scalar float; the authoritative fraction is kept beside it.
    (out/"reward.txt").write_text(str(result.reward_num/result.reward_den)+"\n")


if __name__=="__main__":
    grade(Path("/logs/artifacts/submission.json"), Path("/logs/verifier"))
