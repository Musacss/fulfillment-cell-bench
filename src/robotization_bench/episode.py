"""Public exploration session. No verifier scenarios or scores in this object."""
import json
from dataclasses import asdict
from .contracts import ROOT, EpisodeClosed, InvalidPlan, Scenario, World
from .economics import calculate
from .engine import simulate
from .grading import manual_value
from .validation import parse_plan


def wire(value):
    return json.loads(json.dumps(value, allow_nan=False))


class Episode:
    def __init__(self, world: World, history: tuple[Scenario, ...]):
        self._world = world
        self._days = {d.seed:d for d in history}
        if not history or len(history) != len(self._days):
            raise ValueError("need distinct public days")
        self._closed = False
        self.log = []

    def _action(self, name):
        if self._closed:
            raise EpisodeClosed("episode already closed")
        entry = {"n":len(self.log)+1,"action":name}
        self.log.append(entry)
        return entry

    def observe(self):
        self._action("observe")
        return wire({"world":self._world, "rules":(ROOT/"docs/SPEC.md").read_text(),
                     "history":[asdict(d) for d in self._days.values()], "manual":manual_value()})

    def pilot(self, value, seed: int, *, trace=False):
        entry = self._action("pilot")
        entry["seed"] = seed
        try:
            plan = parse_plan(value,self._world)
            if type(seed) is not int or seed not in self._days:
                raise ValueError("unknown public day")
        except ValueError as exc:
            entry["error"] = str(exc)
            raise
        raw = simulate(self._world,plan,self._days[seed],trace=trace)
        economy = calculate(self._world,plan,raw)
        summary = asdict(raw)
        summary.pop("events")
        entry.update(plan=wire(asdict(plan)), raw=wire(summary), economy=asdict(economy))
        return wire({"raw":asdict(raw),"economy":asdict(economy)})

    def submit(self, value):
        entry = self._action("submit")
        self._closed = True
        try:
            plan = wire(asdict(parse_plan(value,self._world)))
        except InvalidPlan as exc:
            entry["error"] = str(exc)
            plan = None
        entry["plan"] = plan
        return wire({"terminal":True,"plan":plan})

    def stop(self):
        self._action("stop")
        self._closed = True
        return {"terminal":True,"plan":None}
