import json
from dataclasses import replace
from fractions import Fraction as F

import pytest

from robotization_bench.contracts import EpisodeClosed, InvalidPlan, Order, Plan, RawReport, Scenario, load_world
from robotization_bench.episode import Episode
from robotization_bench.grading import grade_reports, evaluate, manual_value
from robotization_bench.verifier import verify_file


def perfect(seed):
    return RawReport(1,seed,100,100,100,0,0,0,100,100,100,0,0,100,(0,),())


@pytest.mark.parametrize("bad,reason,progress",[
    ({"good":93,"unfinished":7,"on_time":93},"volume",F(93,94)),
    ({"good":98,"escaped":2,"on_time":98},"quality",F(1,2)),
    ({"on_time":79},"on_time",F(179,180))])
def test_worst_day_and_pooled_deadline(bad,reason,progress):
    p = Plan(1,True,True,"all",((3,),))
    base = [perfect(0),perfect(1)]
    r = grade_reports(load_world(),p,[base[0],replace(base[1],**bad)],base,p)
    assert not r.feasible and r.reasons == (reason,)
    assert F(r.reward_num,r.reward_den) == F(9,100)*progress


def test_budget_and_reward_has_no_savings_ceiling():
    w = load_world()
    p = Plan(1, True, True, "all", ((3,),))
    r = perfect(0)
    w["money"]["budget"]=1
    over = grade_reports(w,p,[r],[r],p)
    assert over.reasons == ("budget",) and over.reward_num/over.reward_den < .1
    w = load_world()
    for k in w["money"]:
        if k not in ("depreciation_days","budget"):
            w["money"][k] = 0
    w["money"].update(worker_shift=100,overtime_per_worker_tick=1)
    # Against 400 cents, spending 200 and 140 must earn different ranks.
    b = replace(r, labor_ticks=200, overtime_ticks=(300,))
    for overtime, expected in [(100,F(3,5)),(40,F(18,25))]:
        score=grade_reports(w,p,[replace(r,overtime_ticks=(overtime,))],[b],p)
        assert score.win and F(score.reward_num,score.reward_den)==expected
    w["money"].update(worker_shift=0,overtime_per_worker_tick=0)
    with pytest.raises(ValueError):
        grade_reports(w,p,[r],[r],p)


def test_stop_empty_submit_noop_and_forged_artifacts(tmp_path):
    w = load_world()
    days=(Scenario(1,1,(Order(0,"regular",0,100),)),)
    for method in ("stop","submit"):
        ep=Episode(w,days)
        receipt = ep.stop() if method=="stop" else ep.submit({"reward":1})
        assert not evaluate(w,receipt["plan"],days).valid
        with pytest.raises(EpisodeClosed):
            ep.submit(manual_value())
    no_work = evaluate(w,dict(manual_value(),workers=[[2]]),days)
    assert no_work.valid and not no_work.feasible and no_work.metrics["unfinished"]==1
    path = tmp_path/"submission.json"
    assert not verify_file(w,path,days).valid
    path.write_text(json.dumps(manual_value()))
    assert verify_file(w,path,days).valid
    (tmp_path/"link").symlink_to(path)
    assert not verify_file(w,tmp_path/"link",days).valid
    for payload in (b'{"reward": 1}',b'x'*16385,b'\xff',b'null'):
        path.write_bytes(payload)
        assert not verify_file(w,path,days).valid


def test_unused_robot_never_counts_as_automation():
    w=load_world()
    day=Scenario(1,2,(Order(0,"regular",0,100),))
    s=evaluate(w, dict(manual_value(),robot=True), (day,))
    assert s.feasible and not s.win and s.metrics["auto_finished"]==0 and "automation" in s.reasons


def test_quarterly_negative_budget_and_threshold_guards():
    from robotization_bench.grading import evaluate_quarterly
    from robotization_bench.quarterly import manual_quarterly_value

    w = load_world()
    q_manual = manual_quarterly_value(w)
    w["quarterly"]["money"]["budget"] = 0
    with pytest.raises(ValueError):
        evaluate_quarterly(w, q_manual, [11])
    w2 = load_world()
    w2["quarterly"]["threshold_bps"]["escaped_each_week_max"] = -1
    with pytest.raises(ValueError):
        evaluate_quarterly(w2, q_manual, [11])
