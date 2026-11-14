#!/usr/bin/env python3
"""Run a reproducible public comparison or verify an operator-provided plan on external seeds."""
import argparse
import hashlib
import json
import platform
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from robotization_bench.contracts import load_world
from robotization_bench.episode import Episode
from robotization_bench.grading import evaluate, manual_value
from robotization_bench.reference import solve
from robotization_bench.reporting import compare
from robotization_bench.scenarios import generate
from robotization_bench.verifier import verify_file


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out",type=Path,default=ROOT/"artifacts"/"local")
    ap.add_argument("--seeds-file",type=Path,help="Operator JSON array of disjoint evaluation seeds")
    ap.add_argument("--plan", type=Path, help="Optional external plan file for independent grading")
    args = ap.parse_args()
    names = ("submission.json","episode.json","comparison.md","results.json")
    outputs = [args.out / name for name in names]
    if any(path.is_symlink() for path in outputs):
        ap.error("refusing symlink output")
    for source in (args.plan,args.seeds_file):
        if source is not None and any(source.resolve() == output.resolve() or
               (output.exists() and source.exists() and output.samefile(source)) for output in outputs):
            ap.error("input file must not be one of the output files; use another --out directory")
    world = load_world()
    dev = tuple(generate(world,s) for s in world["development_seeds"])
    seeds = json.loads(args.seeds_file.read_text()) if args.seeds_file else world["development_seeds"]
    if (type(seeds) is not list or not seeds or any(type(s) is not int for s in seeds) or
        len(set(seeds)) != len(seeds) or args.seeds_file and set(seeds) & set(world["development_seeds"])):
        ap.error("need distinct integer seeds; external seeds must exclude public history")
    days = tuple(generate(world,s) for s in seeds)
    ep = Episode(world,dev)
    plan = ep.submit(solve(ep))["plan"]
    args.out.mkdir(parents=True,exist_ok=True)
    def save(name,value):
        (args.out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n")
    save("submission.json",plan)
    save("episode.json",ep.log)
    results = {"manual":evaluate(world,manual_value(),days),"reference":verify_file(world,args.out/"submission.json",days)}
    if args.plan:
        results["submitted"] = verify_file(world,args.plan,days)
    table = compare(results)
    print(table)
    (args.out/"comparison.md").write_text(table+"\n")
    git = subprocess.run(["git","-C",str(ROOT),"rev-parse","HEAD"],capture_output=True,text=True)
    def digest(file):
        return hashlib.sha256(file.read_bytes()).hexdigest()
    daily = {}
    for name, value in [("manual",manual_value()),("reference",plan)]:
        replay = Episode(world,days)
        daily[name] = [replay.pilot(value,s) for s in seeds]
    save("results.json",{"commit":git.stdout.strip() or None,"world":world["world_id"],"schema_version":1,
                         "world_sha256":digest(ROOT/"data/world_spec.json"), "python":platform.python_version(),
                         "runner":"local-python","model":None,"pilot_limit":None,
                         "pilot_count":sum(e["action"]=="pilot" for e in ep.log),
                         "evaluation_seeds":seeds,"development":not bool(args.seeds_file),
                         "results":{k:asdict(v) for k,v in results.items()}, "days":daily})
    return 0


if __name__=="__main__":
    raise SystemExit(main())
