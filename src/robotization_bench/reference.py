"""A small, inspectable search using only observe and official public pilots."""
from fractions import Fraction
from .contracts import RawReport
from .grading import grade_reports
from .validation import parse_plan


def candidates():
    # Upstream specialist first; downstream packer/QC, optional flex or second picker.
    crews = ("1 2 3 4","1 2 34 23","1 2 4 23","1 2 3 4 2","1 2 3 4 23","1 2 3 4 1234")
    for crew in crews:
        workers = [list(map(int,z)) for z in crew.split()]
        for trays in (False, True):
            for route in ("all", "bypass"):
                yield dict(schema_version=1,robot=True,trays=trays,route=route,workers=workers)


def solve(episode):
    obs = episode.observe()
    w, manual = obs["world"], obs["manual"]
    seeds = [s["seed"] for s in obs["history"]]
    def pilot(plan,seed):
        return RawReport(**episode.pilot(plan,seed)["raw"])
    base = [pilot(manual,seed) for seed in seeds]
    bp = parse_plan(manual,w)
    def rank(value, reports):
        e = grade_reports(w,parse_plan(value,w),reports,base[:len(reports)],bp)
        return (Fraction(e.reward_num,e.reward_den), -e.metrics["labor_ticks"])
    # Screen on one public shift; retry the top six on every other public day.
    screened = []
    for value in candidates():
        first = pilot(value,seeds[0])
        screened.append((rank(value,[first]),value,first))
    best, answer = rank(manual,base), manual
    for _,value,first in sorted(screened,key=lambda x:x[0],reverse=True)[:6]:
        key = rank(value,[first]+[pilot(value,s) for s in seeds[1:]])
        if key > best:
            best, answer = key, value
    return answer
