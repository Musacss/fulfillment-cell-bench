"""Run the staged oracle and verifier as isolated Python processes, without Docker."""
import json
import subprocess
import sys
from pathlib import Path
from robotization_bench.contracts import ROOT


def test_payload_boundaries_and_end_to_end(tmp_path):
    task=tmp_path/"task"
    seeds=tmp_path/"seeds.json"
    seeds.write_text("[37281939]")
    subprocess.run([sys.executable,str(ROOT/"scripts/prepare_harbor.py"),"--out",str(task),
                    "--seeds-file",str(seeds)],check=True)
    public=task/"environment/public"
    allowed={"data/world_spec.json","data/plans/manual.json","AGENT.md","docs/SPEC.md","docs/CONTRACTS.md"}
    allowed.update(f"data/development/{seed}.json" for seed in (11,29,47))
    allowed.update("src/robotization_bench/"+name+".py" for name in (
        "__init__","contracts","validation","grading","engine","economics","scenarios","mcp_server","episode"))
    assert {p.relative_to(public).as_posix() for p in public.rglob("*") if p.is_file()}==allowed
    plan=tmp_path/"submission.json"
    log=tmp_path/"log.json"
    def isolated(code,*args):
        subprocess.run([sys.executable,"-I","-B","-c",code,*map(str,args)],check=True,cwd=tmp_path)
    isolated("import sys,runpy; from pathlib import Path; sys.path.insert(0,sys.argv[1]); "
             "runpy.run_path(sys.argv[2])['run'](Path(sys.argv[3]),Path(sys.argv[4]))",
             public/"src",task/"solution/oracle.py",plan,log)
    assert json.loads(log.read_text())[-1]["plan"]==json.loads(plan.read_text())
    def grade():
        isolated("import sys,runpy; from pathlib import Path; "
                 "runpy.run_path(sys.argv[1])['grade'](Path(sys.argv[2]),Path(sys.argv[3]))",
                 task/"tests/grade.py",plan,tmp_path/"verdict")
        return json.loads((tmp_path/"verdict/evaluation.json").read_text())["evaluation"]
    first=grade()
    assert first["valid"]
    (public/"src/robotization_bench/grading.py").write_text("raise AssertionError('public evaluator was used')")
    assert grade()==first
    plan.write_text('{"reward": 1, "raw": {}}')
    assert grade()["reward_num"]==0
