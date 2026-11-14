"""Oracle-only payload delivered by Harbor; use exactly the public episode API."""
import importlib.util
import json
from pathlib import Path
from robotization_bench.contracts import load_world
from robotization_bench.episode import Episode
from robotization_bench.scenarios import generate


def run(out: Path, log: Path):
    spec = importlib.util.spec_from_file_location("robotization_bench.reference",Path(__file__).with_name("reference.py"))
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    w = load_world()
    episode = Episode(w,tuple(generate(w,s) for s in w["development_seeds"]))
    plan = episode.submit(reference.solve(episode))["plan"]
    for path,value in ((out,plan),(log,episode.log)):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value)+"\n")


if __name__=="__main__":
    run(Path("/logs/artifacts/submission.json"),Path("/logs/agent/cell-episode.json"))
