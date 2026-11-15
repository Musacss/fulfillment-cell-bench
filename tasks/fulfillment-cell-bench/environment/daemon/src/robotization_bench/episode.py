"""Public exploration session. No verifier scenarios or scores in this object."""

from collections.abc import Sequence
import copy
from dataclasses import asdict
import errno
import json
import os
from pathlib import Path
import stat
from tempfile import NamedTemporaryFile
from typing import Any

from .contracts import (
    QUARTERLY_SCHEMA_VERSION,
    ROOT,
    SCHEMA_VERSION,
    EpisodeClosed,
    InvalidPlan,
    PilotBudgetExceeded,
    Scenario,
    World,
)
from .economics import calculate
from .engine import simulate
from .grading import manual_value
from .validation import _reject_constant, _unique_keys, parse_plan, parse_quarterly_plan

_PUBLIC_WORLD_KEYS = frozenset(
    {
        "schema_version",
        "world_id",
        "clock",
        "capacity",
        "workers",
        "kinds",
        "time",
        "prob_bps",
        "money",
        "threshold_bps",
        "generator",
        "development_seeds",
        "quarterly",
    }
)
_PUBLIC_QUARTERLY_KEYS = frozenset(
    {
        "schema_version",
        "world_id",
        "weeks",
        "max_pilots",
        "carryover_cap",
        "commissioning",
        "wear",
        "money",
        "threshold_bps",
        "week_profiles",
    }
)


_INT64_MIN = -(1 << 63)
_INT64_MAX = (1 << 63) - 1
_MAX_ERROR_LOG_ENTRIES = 64
_MAX_STATE_BYTES = 16_777_216


def wire(value):
    return json.loads(json.dumps(value, allow_nan=False))


def _safe_seed_log(seed: object) -> int | str:
    if type(seed) is int:
        return seed if _INT64_MIN <= seed <= _INT64_MAX else "<oversized-int>"
    if type(seed) is str and len(seed) > 64:
        rendered = repr(seed[:64])
        return rendered[:64] + "..." if len(rendered) > 64 else rendered + "..."
    if type(seed) is bytes and len(seed) > 64:
        rendered = repr(seed[:64])
        return rendered[:64] + "..." if len(rendered) > 64 else rendered + "..."
    try:
        rendered = repr(seed)
    except Exception:
        return f"<unrepresentable {type(seed).__name__}>"
    if len(rendered) > 64:
        return rendered[:64] + "..."
    return rendered


def _safe_error_log(exc: BaseException) -> str:
    msg = str(exc)
    return msg[:256] + "..." if len(msg) > 256 else msg


def _strip_private(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_private(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, (list, tuple)):
        return [_strip_private(v) for v in obj]
    return obj


def _sanitize_public_world(world: World) -> World:
    out = {k: _strip_private(v) for k, v in world.items() if k in _PUBLIC_WORLD_KEYS}
    if "quarterly" in out and isinstance(out["quarterly"], dict):
        out["quarterly"] = {
            k: _strip_private(v)
            for k, v in out["quarterly"].items()
            if k in _PUBLIC_QUARTERLY_KEYS
        }
    return wire(out)


def _read_rules(rules_path: Path | None) -> str:
    target = Path(rules_path) if rules_path is not None else (ROOT / "docs/SPEC.md")
    if target.is_file():
        return target.read_text(encoding="utf-8")
    fallback = Path.cwd() / "docs/SPEC.md"
    if fallback.is_file():
        return fallback.read_text(encoding="utf-8")
    return ""


def _load_state(path: Path, expected_mode: str, *, world: World | None = None) -> dict[str, Any] | None:
    if path.is_symlink():
        raise ValueError("state_path must not be a symlink")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    except IsADirectoryError as exc:
        raise ValueError("state_path must be a regular file") from exc
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ValueError("state_path must not be a symlink") from exc
        if exc.errno in (errno.EOPNOTSUPP, errno.ENXIO):
            raise ValueError("state_path must be a regular file") from exc
        raise
    try:
        meta = os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or meta.st_size > _MAX_STATE_BYTES:
            raise ValueError("state_path must be a regular file <= 16 MiB")
        try:
            with os.fdopen(fd, "rb", closefd=False) as stream:
                raw_bytes = stream.read(_MAX_STATE_BYTES + 1)
            if len(raw_bytes) > _MAX_STATE_BYTES:
                raise ValueError("state_path exceeds 16 MiB")
            data = json.loads(
                raw_bytes.decode("utf-8"),
                object_pairs_hook=_unique_keys,
                parse_constant=_reject_constant,
            )
        except (UnicodeError, json.JSONDecodeError, InvalidPlan, RecursionError, ValueError) as exc:
            raise ValueError("corrupt episode state file") from exc
    finally:
        os.close(fd)

    if type(data) is not dict or data.get("mode") != expected_mode:
        raise ValueError(f"episode state mode mismatch: expected {expected_mode}")
    used = data.get("pilot_used", data.get("pilot_count"))
    if type(used) is not int or used < 0:
        raise ValueError("invalid pilot_used in state file")
    saved_max = data.get("max_pilots")
    if saved_max is not None and (type(saved_max) is not int or saved_max <= 0):
        raise ValueError("invalid max_pilots in state file")
    closed = data.get("closed")
    if type(closed) is not bool:
        raise ValueError("invalid closed flag in state file")
    submission = data.get("submission")
    if submission is not None:
        if type(submission) is not dict:
            raise ValueError("invalid submission in state file")
        if world is not None:
            try:
                if expected_mode == "quarterly":
                    parse_quarterly_plan(submission, world)
                else:
                    parse_plan(submission, world)
            except (InvalidPlan, RecursionError, ValueError) as exc:
                raise ValueError("invalid submission in state file") from exc
    saved_log = data.get("log")
    if type(saved_log) is not list or any(type(item) is not dict for item in saved_log):
        raise ValueError("invalid log in state file")
    rejected_calls = data.get("rejected_calls", 0)
    if type(rejected_calls) is not int or rejected_calls < 0:
        raise ValueError("invalid rejected_calls in state file")

    return {
        "pilot_used": used,
        "max_pilots": saved_max,
        "closed": closed,
        "submission": submission,
        "log": saved_log,
        "rejected_calls": rejected_calls,
    }


def _save_state(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    if path.is_symlink():
        raise ValueError("state_path must not be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, allow_nan=False) + "\n").encode("utf-8")
    with NamedTemporaryFile(
        mode="wb",
        dir=path.parent,
        prefix=".state-",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        pending = Path(tmp.name)
        try:
            os.fchmod(tmp.fileno(), 0o600)
            tmp.write(encoded)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp.close()
            os.replace(pending, path)
        finally:
            pending.unlink(missing_ok=True)


class Episode:
    def __init__(
        self,
        world: World,
        history: tuple[Scenario, ...],
        *,
        max_pilots: int | None = None,
        state_path: Path | None = None,
        rules_path: Path | None = None,
    ) -> None:
        self._world = copy.deepcopy(world)
        self._days = {d.seed: d for d in history}
        if not history or len(history) != len(self._days):
            raise ValueError("need distinct public days")
        if max_pilots is not None and (type(max_pilots) is not int or max_pilots <= 0):
            raise ValueError("max_pilots must be a positive integer")
        self._max_pilots = max_pilots
        self._state_path = Path(state_path) if state_path is not None else None
        self._rules_path = Path(rules_path) if rules_path is not None else None
        self._pilot_used = 0
        self._rejected_calls = 0
        self._closed = False
        self._submission: dict[str, Any] | None = None
        self.log: list[dict[str, Any]] = []

        if self._state_path is not None:
            loaded = _load_state(self._state_path, "v1", world=self._world)
            if loaded is not None:
                self._pilot_used = loaded["pilot_used"]
                saved_max = loaded["max_pilots"]
                if saved_max is not None:
                    self._max_pilots = saved_max if self._max_pilots is None else min(self._max_pilots, saved_max)
                self._closed = loaded["closed"]
                self._submission = loaded["submission"]
                self.log = loaded["log"]
                self._rejected_calls = loaded["rejected_calls"]
                if self._max_pilots != saved_max:
                    self._persist()
            else:
                self._persist()

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def pilot_used(self) -> int:
        return self._pilot_used

    @property
    def rejected_calls(self) -> int:
        return self._rejected_calls

    @property
    def max_pilots(self) -> int | None:
        return self._max_pilots

    @property
    def submission(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._submission)

    def _persist(self) -> None:
        _save_state(
            self._state_path,
            {
                "schema_version": SCHEMA_VERSION,
                "mode": "v1",
                "pilot_used": self._pilot_used,
                "pilot_count": self._pilot_used,
                "rejected_calls": self._rejected_calls,
                "max_pilots": self._max_pilots,
                "closed": self._closed,
                "submission": self._submission,
                "log": self.log,
            },
        )

    def _action(self, name: str) -> dict[str, Any]:
        if self._closed:
            raise EpisodeClosed("episode already closed")
        entry: dict[str, Any] = {"n": len(self.log) + 1, "action": name}
        self.log.append(entry)
        return entry

    def _record_pilot_error(self, safe_seed: int | str, error_msg: str) -> None:
        self._rejected_calls += 1
        appended = False
        error_count = sum(1 for e in self.log if e.get("action") == "pilot" and "error" in e)
        if error_count < _MAX_ERROR_LOG_ENTRIES:
            self.log.append(
                {
                    "n": len(self.log) + 1,
                    "action": "pilot",
                    "seed": safe_seed,
                    "error": error_msg,
                }
            )
            appended = True
        try:
            self._persist()
        except BaseException:
            self._rejected_calls -= 1
            if appended:
                self.log.pop()
            raise

    def observe(self) -> dict[str, Any]:
        if self._closed:
            raise EpisodeClosed("episode already closed")
        rules_text = _read_rules(self._rules_path)
        obs_count = sum(1 for e in self.log if e.get("action") == "observe")
        appended = False
        if obs_count < _MAX_ERROR_LOG_ENTRIES:
            self._action("observe")
            appended = True
            try:
                self._persist()
            except BaseException:
                self.log.pop()
                raise
        return wire(
            {
                "world": _sanitize_public_world(self._world),
                "rules": rules_text,
                "history": [asdict(d) for d in self._days.values()],
                "manual": manual_value(),
            }
        )

    def pilot(self, value: object, seed: int, *, trace: bool = False) -> dict[str, Any]:
        if self._closed:
            raise EpisodeClosed("episode already closed")
        safe_seed = _safe_seed_log(seed)
        if self._max_pilots is not None and self._pilot_used >= self._max_pilots:
            msg = f"BudgetExceeded: pilot budget exhausted ({self._pilot_used}/{self._max_pilots})"
            self._record_pilot_error(safe_seed, msg)
            raise PilotBudgetExceeded(msg)

        try:
            if type(trace) is not bool:
                raise ValueError("trace must be a boolean")
            plan = parse_plan(value, self._world)
            if type(seed) is not int or seed not in self._days:
                raise ValueError("unknown public day")
        except ValueError as exc:
            self._record_pilot_error(safe_seed, _safe_error_log(exc))
            raise

        entry = self._action("pilot")
        entry["seed"] = safe_seed
        self._pilot_used += 1
        try:
            self._persist()
        except BaseException:
            self._pilot_used -= 1
            self.log.pop()
            raise
        raw = simulate(self._world, plan, self._days[seed], trace=trace)
        economy = calculate(self._world, plan, raw)
        summary = asdict(raw)
        summary.pop("events")
        entry.update(plan=wire(asdict(plan)), raw=wire(summary), economy=asdict(economy))
        self._persist()
        return wire({"raw": asdict(raw), "economy": asdict(economy)})

    def submit(self, value: object) -> dict[str, Any]:
        entry = self._action("submit")
        self._closed = True
        try:
            plan = wire(asdict(parse_plan(value, self._world)))
        except InvalidPlan as exc:
            entry["error"] = _safe_error_log(exc)
            plan = None
        entry["plan"] = copy.deepcopy(plan)
        self._submission = copy.deepcopy(plan)
        try:
            self._persist()
        except BaseException:
            self._closed = False
            self._submission = None
            self.log.pop()
            raise
        return wire({"terminal": True, "plan": plan})

    def stop(self) -> dict[str, Any]:
        self._action("stop")
        self._closed = True
        self._submission = None
        try:
            self._persist()
        except BaseException:
            self._closed = False
            self.log.pop()
            raise
        return {"terminal": True, "plan": None}


class QuarterlyEpisode:
    def __init__(
        self,
        world: World,
        seeds: Sequence[int] | None = None,
        *,
        max_pilots: int | None = None,
        state_path: Path | None = None,
        rules_path: Path | None = None,
    ) -> None:
        if type(world) is not dict or type(world.get("quarterly")) is not dict:
            raise ValueError("world missing quarterly specification")
        self._world = wire(world)

        raw_seeds = self._world["development_seeds"] if seeds is None else seeds
        if (
            isinstance(raw_seeds, (str, bytes))
            or not isinstance(raw_seeds, Sequence)
            or not raw_seeds
            or any(type(s) is not int for s in raw_seeds)
            or len(set(raw_seeds)) != len(raw_seeds)
        ):
            raise ValueError("need distinct integer development seeds")
        self._seeds = tuple(raw_seeds)
        self._seed_set = frozenset(self._seeds)

        limit = self._world["quarterly"]["max_pilots"] if max_pilots is None else max_pilots
        if type(limit) is not int or limit <= 0:
            raise ValueError("max_pilots must be a positive integer")
        self._max_pilots = limit

        self._state_path = Path(state_path) if state_path is not None else None
        self._rules_path = Path(rules_path) if rules_path is not None else None
        self._pilot_used = 0
        self._rejected_calls = 0
        self._closed = False
        self._submission: dict[str, Any] | None = None
        self.log: list[dict[str, Any]] = []

        from .quarterly import generate_quarter_exogenous

        self._exogenous = {s: generate_quarter_exogenous(self._world, s) for s in self._seeds}

        if self._state_path is not None:
            loaded = _load_state(self._state_path, "quarterly", world=self._world)
            if loaded is not None:
                self._pilot_used = loaded["pilot_used"]
                saved_max = loaded["max_pilots"]
                if saved_max is not None:
                    self._max_pilots = min(self._max_pilots, saved_max)
                self._closed = loaded["closed"]
                self._submission = loaded["submission"]
                self.log = loaded["log"]
                self._rejected_calls = loaded["rejected_calls"]
                if self._max_pilots != saved_max:
                    self._persist()
            else:
                self._persist()

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def pilot_used(self) -> int:
        return self._pilot_used

    @property
    def rejected_calls(self) -> int:
        return self._rejected_calls

    @property
    def max_pilots(self) -> int:
        return self._max_pilots

    @property
    def submission(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._submission)

    def _persist(self) -> None:
        _save_state(
            self._state_path,
            {
                "schema_version": QUARTERLY_SCHEMA_VERSION,
                "mode": "quarterly",
                "pilot_used": self._pilot_used,
                "pilot_count": self._pilot_used,
                "rejected_calls": self._rejected_calls,
                "max_pilots": self._max_pilots,
                "closed": self._closed,
                "submission": self._submission,
                "log": self.log,
            },
        )

    def _action(self, name: str) -> dict[str, Any]:
        if self._closed:
            raise EpisodeClosed("episode already closed")
        entry: dict[str, Any] = {"n": len(self.log) + 1, "action": name}
        self.log.append(entry)
        return entry

    def _record_pilot_error(self, safe_seed: int | str, error_msg: str) -> None:
        self._rejected_calls += 1
        appended = False
        error_count = sum(1 for e in self.log if e.get("action") == "pilot" and "error" in e)
        if error_count < _MAX_ERROR_LOG_ENTRIES:
            self.log.append(
                {
                    "n": len(self.log) + 1,
                    "action": "pilot",
                    "seed": safe_seed,
                    "error": error_msg,
                }
            )
            appended = True
        try:
            self._persist()
        except BaseException:
            self._rejected_calls -= 1
            if appended:
                self.log.pop()
            raise

    def _summarize_seed(self, seed: int) -> dict[str, Any]:
        profiles = self._world["quarterly"]["week_profiles"]
        weeks_summary = []
        total_orders = 0
        quarter_kinds = {"regular": 0, "fragile": 0, "oversize": 0}
        for w_idx, scen in enumerate(self._exogenous[seed]):
            orders = scen.orders
            n_orders = len(orders)
            total_orders += n_orders
            kind_counts = {
                "regular": sum(o.kind == "regular" for o in orders),
                "fragile": sum(o.kind == "fragile" for o in orders),
                "oversize": sum(o.kind == "oversize" for o in orders),
            }
            for k, v in kind_counts.items():
                quarter_kinds[k] += v
            slacks = [o.due - o.arrival for o in orders]
            weeks_summary.append(
                {
                    "week": w_idx,
                    "label": str(profiles[w_idx]["label"]),
                    "week_seed": scen.seed,
                    "total_orders": n_orders,
                    "kind_counts": kind_counts,
                    "first_arrival": min(o.arrival for o in orders),
                    "last_arrival": max(o.arrival for o in orders),
                    "min_due_slack": min(slacks),
                    "max_due_slack": max(slacks),
                    "mean_due_slack_ticks": sum(slacks) // n_orders,
                }
            )
        return {
            "seed": seed,
            "total_orders": total_orders,
            "kind_counts": quarter_kinds,
            "weeks": weeks_summary,
        }

    def observe(self) -> dict[str, Any]:
        if self._closed:
            raise EpisodeClosed("episode already closed")
        rules_text = _read_rules(self._rules_path)
        obs_count = sum(1 for e in self.log if e.get("action") == "observe")
        appended = False
        if obs_count < _MAX_ERROR_LOG_ENTRIES:
            self._action("observe")
            appended = True
            try:
                self._persist()
            except BaseException:
                self.log.pop()
                raise
        from .quarterly import manual_quarterly_value

        return wire(
            {
                "schema_version": QUARTERLY_SCHEMA_VERSION,
                "world": _sanitize_public_world(self._world),
                "rules": rules_text,
                "development_seeds": list(self._seeds),
                "history": [self._summarize_seed(s) for s in self._seeds],
                "manual": manual_quarterly_value(self._world),
                "pilot_budget": {"used": self._pilot_used, "max": self._max_pilots},
            }
        )

    def pilot(self, value: object, seed: int, *, trace: bool = False) -> dict[str, Any]:
        if self._closed:
            raise EpisodeClosed("episode already closed")
        safe_seed = _safe_seed_log(seed)
        if self._pilot_used >= self._max_pilots:
            msg = f"BudgetExceeded: pilot budget exhausted ({self._pilot_used}/{self._max_pilots})"
            self._record_pilot_error(safe_seed, msg)
            raise PilotBudgetExceeded(msg)

        try:
            if type(trace) is not bool:
                raise ValueError("trace must be a boolean")
            plan = parse_quarterly_plan(value, self._world)
            if type(seed) is not int or seed not in self._seed_set:
                raise ValueError("unknown public day: seed must be in development_seeds")
        except ValueError as exc:
            self._record_pilot_error(safe_seed, _safe_error_log(exc))
            raise

        entry = self._action("pilot")
        entry["seed"] = safe_seed
        self._pilot_used += 1
        try:
            self._persist()
        except BaseException:
            self._pilot_used -= 1
            self.log.pop()
            raise

        from .quarterly import simulate_quarter

        quarter = simulate_quarter(self._world, plan, seed, trace=True)
        weeks_wire: list[dict[str, Any]] = []
        weeks_log: list[dict[str, Any]] = []
        total_jams = 0
        total_assists = 0

        for w in quarter.weeks:
            raw_full = asdict(w.raw)
            week_jams = sum(1 for e in w.raw.events if e.kind == "jam")
            week_assists = sum(1 for e in w.raw.events if e.kind == "assist")
            total_jams += week_jams
            total_assists += week_assists

            raw_stripped = dict(raw_full)
            raw_stripped["events"] = []
            raw_caller = raw_full if trace else raw_stripped

            common = {
                "week": w.week,
                "label": w.label,
                "week_seed": w.week_seed,
                "exogenous_orders": len(self._exogenous[seed][w.week].orders),
                "carryover_in": w.carryover_in,
                "carryover_out": w.carryover_out,
                "wear_start": w.wear_start,
                "wear_end": w.wear_end,
                "commissioning_active": w.commissioning_active,
                "jams": week_jams,
                "assists": week_assists,
                "shift_economy": asdict(w.shift_economy),
                "week_economy": asdict(w.week_economy),
            }
            weeks_wire.append({**common, "raw": raw_caller})
            weeks_log.append({**common, "raw": raw_stripped})

        totals = {
            "orders": sum(len(s.orders) for s in self._exogenous[seed]),
            "good": sum(w.raw.good for w in quarter.weeks),
            "on_time": sum(w.raw.on_time for w in quarter.weeks),
            "escaped": sum(w.raw.escaped for w in quarter.weeks),
            "scrap": sum(w.raw.scrap for w in quarter.weeks),
            "unfinished_terminal": sum(w.raw.unfinished - w.carryover_out for w in quarter.weeks),
            "carryover_peak": max(w.carryover_out for w in quarter.weeks),
            "auto_finished": sum(w.raw.auto_finished for w in quarter.weeks),
            "pack_finished": sum(w.raw.pack_finished for w in quarter.weeks),
            "pack_started": sum(w.raw.pack_started for w in quarter.weeks),
            "rework_started": sum(w.raw.rework_started for w in quarter.weeks),
            "trays_used": sum(w.raw.trays_used for w in quarter.weeks),
            "jams": total_jams,
            "assists": total_assists,
        }
        budget_status = {"used": self._pilot_used, "max": self._max_pilots}
        entry.update(
            plan=wire(asdict(plan)),
            pilot_budget=budget_status,
            purchase=quarter.purchase,
            total_cost=quarter.total_cost,
            labor_ticks=quarter.labor_ticks,
            totals=totals,
            weeks=wire(weeks_log),
        )
        self._persist()
        return wire(
            {
                "schema_version": QUARTERLY_SCHEMA_VERSION,
                "seed": seed,
                "pilot_budget": budget_status,
                "purchase": quarter.purchase,
                "total_cost": quarter.total_cost,
                "labor_ticks": quarter.labor_ticks,
                "totals": totals,
                "weeks": weeks_wire,
            }
        )

    def submit(self, value: object) -> dict[str, Any]:
        entry = self._action("submit")
        self._closed = True
        try:
            plan = wire(asdict(parse_quarterly_plan(value, self._world)))
        except InvalidPlan as exc:
            entry["error"] = _safe_error_log(exc)
            plan = None
        entry["plan"] = copy.deepcopy(plan)
        self._submission = copy.deepcopy(plan)
        try:
            self._persist()
        except BaseException:
            self._closed = False
            self._submission = None
            self.log.pop()
            raise
        return wire({"terminal": True, "plan": plan})

    def stop(self) -> dict[str, Any]:
        self._action("stop")
        self._closed = True
        self._submission = None
        try:
            self._persist()
        except BaseException:
            self._closed = False
            self.log.pop()
            raise
        return {"terminal": True, "plan": None}
