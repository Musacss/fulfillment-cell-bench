"""Oracle-only payload delivered by Harbor; interacts strictly via SocketEpisodeClient."""

import copy
import json
import os
from pathlib import Path
import sys
from typing import Any

HERE = Path(__file__).resolve().parent
SOLUTION_SRC = str(HERE / "src")
if SOLUTION_SRC not in sys.path:
    sys.path.insert(0, SOLUTION_SRC)
if "robotization_bench" in sys.modules:
    pkg_dir = str(HERE / "src" / "robotization_bench")
    pkg_paths = getattr(sys.modules["robotization_bench"], "__path__", None)
    if pkg_paths is not None and pkg_dir not in pkg_paths:
        pkg_paths.insert(0, pkg_dir)

from robotization_bench import reference  # noqa: E402
from robotization_bench.mcp_proxy import SocketEpisodeClient  # noqa: E402


class _CachingEpisodeAdapter:
    """Caches observe() and identical pilot() calls across solver/fallback stages."""

    def __init__(self, client: SocketEpisodeClient) -> None:
        self._client = client
        self._obs: dict[str, Any] | None = None
        self._pilot_cache: dict[tuple[str, int, bool], dict[str, Any]] = {}
        self.used_pilots: int = 0
        self.max_pilots: int | None = None

    def observe(self) -> dict[str, Any]:
        if self._obs is None:
            self._obs = self._client.observe()
            budget = self._obs.get("pilot_budget")
            if isinstance(budget, dict):
                self.used_pilots = int(budget.get("used", 0))
                self.max_pilots = int(budget["max"]) if "max" in budget else None
        out = copy.deepcopy(self._obs)
        if isinstance(out.get("pilot_budget"), dict) and self.max_pilots is not None:
            out["pilot_budget"]["used"] = self.used_pilots
            out["pilot_budget"]["max"] = self.max_pilots
        return out

    def pilot(self, plan: object, seed: int, *, trace: bool = False) -> dict[str, Any]:
        key = (json.dumps(plan, sort_keys=True, ensure_ascii=True), seed, bool(trace))
        if key in self._pilot_cache:
            return copy.deepcopy(self._pilot_cache[key])
        res = self._client.pilot(plan, seed, trace=trace)
        budget = res.get("pilot_budget")
        if isinstance(budget, dict):
            self.used_pilots = int(budget.get("used", self.used_pilots + 1))
            if "max" in budget:
                self.max_pilots = int(budget["max"])
        self._pilot_cache[key] = res
        return copy.deepcopy(res)

    def remaining_pilots(self) -> int:
        if self.max_pilots is None:
            return 999
        return max(0, self.max_pilots - self.used_pilots)


def _quarterly_candidates(obs: dict[str, Any]) -> list[dict[str, Any]]:
    q = obs["world"]["quarterly"]
    profiles = q["week_profiles"]
    num_weeks = int(q["weeks"])
    comm_weeks = int(q["commissioning"]["weeks"])

    # Derive elevated-demand / non-regular wave weeks from public week_profiles
    loads = [int(p["waves"]) * int(p["orders_min"]) for p in profiles]
    median_load = sorted(loads)[len(loads) // 2]
    heavy_weeks = {
        idx
        for idx, p in enumerate(profiles)
        if int(p["waves"]) * int(p["orders_min"]) > median_load + 15
        or (10_000 - int(p["regular_bps"])) >= 3000
    }

    configs = [
        ([[1], [2], [2, 3], [4]], [[1], [2], [3], [4], [2, 3]], False),
        ([[1], [2], [2, 3], [4]], [[1], [2], [3], [4], [2, 3]], True),
        ([[1], [2], [3], [4]], [[1], [2], [3], [4], [2, 3]], False),
        ([[1], [2], [2, 3], [3, 4]], [[1], [2], [3], [4], [2, 3]], False),
        ([[1], [2], [2, 3], [4]], [[1], [2], [2, 3], [3, 4], [2, 3]], False),
    ]

    plans: list[dict[str, Any]] = []
    for steady_crew, peak_crew, maint_mid_peak in configs:
        weeks: list[dict[str, Any]] = []
        for idx in range(num_weeks):
            is_heavy = idx in heavy_weeks
            post_comm = idx == comm_weeks
            post_heavy = idx > 0 and (idx - 1) in heavy_weeks
            pre_heavy = (idx + 1) < num_weeks and (idx + 1) in heavy_weeks
            mid_long_peak = (
                maint_mid_peak
                and is_heavy
                and idx >= 2
                and (idx - 1) in heavy_weeks
                and (idx - 2) in heavy_weeks
            )
            do_maint = (
                idx >= comm_weeks
                and idx < num_weeks - 1
                and ((not is_heavy and (post_comm or post_heavy or pre_heavy)) or mid_long_peak)
            )
            crew = peak_crew if is_heavy else steady_crew
            weeks.append(
                {
                    "robot": True,
                    "trays": True,
                    "route": "bypass",
                    "maintenance": do_maint,
                    "workers": [list(z) for z in crew],
                }
            )
        plans.append({"schema_version": 2, "weeks": weeks})
    return plans


def _is_quarterly_feasible(obs: dict[str, Any], reports: list[dict[str, Any]]) -> bool:
    q = obs["world"]["quarterly"]
    thresholds = q["threshold_bps"]
    budget_limit = int(q["money"]["budget"])

    if any(int(r["purchase"]) > budget_limit for r in reports):
        return False
    for r in reports:
        for wr in r["weeks"]:
            raw = wr["raw"]
            if int(raw["good"]) * 10_000 < int(raw["total"]) * int(thresholds["good_each_week"]):
                return False
            if int(raw["escaped"]) * 10_000 > int(raw["total"]) * int(thresholds["escaped_each_week_max"]):
                return False

    orders = sum(int(r["totals"]["orders"]) for r in reports)
    good = sum(int(r["totals"]["good"]) for r in reports)
    on_time = sum(int(r["totals"]["on_time"]) for r in reports)
    auto_fin = sum(int(r["totals"]["auto_finished"]) for r in reports)
    pack_fin = sum(int(r["totals"]["pack_finished"]) for r in reports)

    if good * 10_000 < orders * int(thresholds["good_pooled"]):
        return False
    if on_time * 10_000 < orders * int(thresholds["on_time_pooled"]):
        return False
    if pack_fin == 0 or auto_fin * 10_000 < pack_fin * int(thresholds["auto_pack_pooled_min"]):
        return False
    return True


def _quarterly_rank_key(obs: dict[str, Any], reports: list[dict[str, Any]]) -> tuple[int, int, int]:
    feasible = 1 if _is_quarterly_feasible(obs, reports) else 0
    total_cost = sum(int(r["total_cost"]) for r in reports)
    labor_ticks = sum(int(r["labor_ticks"]) for r in reports)
    return (feasible, -total_cost, -labor_ticks)


def _fallback_quarterly_search(adapter: _CachingEpisodeAdapter, obs: dict[str, Any]) -> dict[str, Any]:
    seeds = list(obs["development_seeds"])
    candidates = _quarterly_candidates(obs)
    if not seeds or adapter.remaining_pilots() <= 0:
        return candidates[0] if candidates else obs["manual"]

    screened: list[tuple[tuple[int, int, int], dict[str, Any], dict[str, Any]]] = []
    for cand in candidates:
        if adapter.remaining_pilots() <= len(seeds) - 1:
            break
        r0 = adapter.pilot(cand, seeds[0])
        screened.append((_quarterly_rank_key(obs, [r0]), cand, r0))

    if not screened:
        return candidates[0]

    screened.sort(key=lambda item: item[0], reverse=True)
    best_plan = screened[0][1]
    best_full_key: tuple[int, int, int] | None = None

    for _, cand, r0 in screened[:3]:
        if adapter.remaining_pilots() < len(seeds) - 1:
            break
        full_reports = [r0] + [adapter.pilot(cand, s) for s in seeds[1:]]
        full_key = _quarterly_rank_key(obs, full_reports)
        if best_full_key is None or full_key > best_full_key:
            best_full_key = full_key
            best_plan = cand

    return best_plan


def run(socket_path: Path | None = None) -> dict[str, Any]:
    client = SocketEpisodeClient(socket_path=socket_path)
    adapter = _CachingEpisodeAdapter(client)
    obs = adapter.observe()
    is_quarterly = obs.get("schema_version") == 2

    plan: dict[str, Any] | None = None
    try:
        candidate = reference.solve(adapter)
        if isinstance(candidate, dict) and (not is_quarterly or candidate.get("schema_version") == 2):
            plan = candidate
    except (KeyError, ValueError, TypeError, RuntimeError):
        if not is_quarterly:
            raise
        plan = None

    if plan is None:
        plan = _fallback_quarterly_search(adapter, obs)

    return client.submit(plan)


if __name__ == "__main__":
    run()
