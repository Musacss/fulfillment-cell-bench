"""Stage an allowlisted Harbor task. The agent build context never contains verifier inputs."""
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ("__init__","contracts","scenarios","validation","economics","engine","grading")
PUBLIC = CORE+("episode","mcp_server")
TRUSTED = CORE+("verifier",)


def copy(file, dest):
    dest.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(file,dest)


def prepare(out: Path, seeds_file: Path):
    w = json.loads((ROOT/"data/world_spec.json").read_text())
    seeds = json.loads(seeds_file.read_text())
    if (type(seeds) is not list or not seeds or any(type(s) is not int for s in seeds)
            or len(set(seeds))!=len(seeds) or set(seeds)&set(w["development_seeds"])):
        raise ValueError("use distinct evaluation seeds, disjoint from public history")
    out.mkdir(parents=True,exist_ok=False)
    template = ROOT/"integration"/"harbor"
    for f in ("task.toml","environment/Dockerfile","environment/requirements.txt","tests/Dockerfile",
              "tests/test.sh","tests/grade.py","solution/solve.sh","solution/oracle.py"):
        copy(template/f,out/f)
    for dest, modules in (("environment/public",PUBLIC),("tests/trusted",TRUSTED)):
        base=out/dest
        for m in modules:
            p=Path("src/robotization_bench")/(m+".py")
            copy(ROOT/p,base/p)
        for f in ("data/plans/manual.json","data/world_spec.json"):
            copy(ROOT/f,base/f)
    for f in ("docs/SPEC.md","docs/CONTRACTS.md","AGENT.md"):
        copy(ROOT/f,out/"environment/public"/f)
    for s in w["development_seeds"]:
        f=Path("data/development")/(str(s)+".json")
        copy(ROOT/f,out/"environment/public"/f)
    copy(ROOT/"AGENT.md",out/"instruction.md")
    copy(ROOT/"src/robotization_bench/reference.py",out/"solution/reference.py")
    (out/"tests/seeds.json").write_text(json.dumps(seeds)+"\n")
    commit=subprocess.run(["git","-C",str(ROOT),"rev-parse","HEAD"],capture_output=True,text=True)
    (out/"tests/provenance.json").write_text(json.dumps({"commit":commit.stdout.strip() or None,
        "world_sha256":hashlib.sha256((ROOT/"data/world_spec.json").read_bytes()).hexdigest(),
        "schema_version":1,"harbor_checked_version":"0.26.0"}))


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out",type=Path,required=True,help="New directory, must not already exist")
    ap.add_argument("--seeds-file",type=Path,required=True)
    args=ap.parse_args()
    prepare(args.out,args.seeds_file)
