"""One deterministic tick scheduler. All orders enter and leave through the same queues."""
from dataclasses import dataclass

from .contracts import Event, Order, Plan, RawReport, Scenario, World, draw


@dataclass
class Item:
    order: Order
    attempt: int = 0
    defect: bool = False


@dataclass
class Job:
    item: Item
    stage: int
    end: int
    mode: str = "work"  # robot may wait for service; assistant shares only its reference


@dataclass
class Worker:
    zones: tuple[int, ...]
    pos: int
    name: str
    job: Job | None = None
    break_end: int = -1
    last: int = 0


def simulate(world: World, plan: Plan, scenario: Scenario, *, trace: bool = False) -> RawReport:
    clock, times, prob = world["clock"], world["time"], world["prob_bps"]
    shift = clock["shift_ticks"]
    horizon = shift + clock["overtime_ticks"]
    queues: dict[int, list[Item]] = {i: [] for i in range(1, 6)}  # 5 = repeat pack
    slots = dict(zip((2, 3, 4), (world["capacity"][k] for k in ("pick", "pack", "qc"))))
    reserved = {i: 0 for i in slots}
    workers = [Worker(z, z[0], f"w{i}") for i, z in enumerate(plan.workers)]
    robot: Job | None = None
    orders = scenario.orders
    if (scenario.schema_version != 1 or not orders or len({o.id for o in orders}) != len(orders)
            or any(o.id < 0 or not 0 <= o.arrival < shift or o.due < o.arrival or o.kind not in world["kinds"] for o in orders)
            or any((a.arrival, a.id) >= (b.arrival, b.id) for a, b in zip(orders, orders[1:]))):
        raise ValueError("invalid trusted scenario")
    index = 0
    good = on_time = escaped = scrap = started = finished = auto = trays = rework = labor = 0
    events: list[Event] = []
    rig = "tray" if plan.trays else "bare"

    def emit(kind, item=None, resource=None, stage=None, end=None):
        if trace:
            events.append(Event(t, kind, item.order.id if item else None, resource, stage,
                                item.attempt if item else None, end))

    def put(item, stage):
        queues[5 if stage == 3 and item.attempt else stage].append(item)
        emit("enqueue", item, stage=stage)

    def hit(item, stage, label, threshold):
        return draw(scenario.seed, item.order.id, stage, item.attempt, label, 10000) < threshold

    def complete(job, resource):
        nonlocal good, on_time, escaped, scrap, finished, auto
        item, s = job.item, job.stage
        emit("finish", item, resource, s)
        if s < 4:
            reserved[s + 1] -= 1
            if s == 3:
                is_auto = resource == "robot"
                finished += 1
                auto += is_auto
                chance = prob["defect_auto"][rig] if is_auto else prob["defect_manual"]
                item.defect = hit(item, 3, "defect", chance[item.order.kind])
            put(item, s + 1)
        elif not item.defect:
            good += 1
            on_time += t <= item.order.due
            emit("good", item, resource, s)
        elif not hit(item, 4, "detect", prob["detect"]):
            escaped += 1
            emit("escaped", item, resource, s)
        elif item.attempt == 1:
            scrap += 1
            emit("scrap", item, resource, s)
        else:
            item.attempt = 1
            put(item, 3)

    def take(s, automatic):
        nonlocal started, trays, rework
        if s < 4 and len(queues[s + 1]) + reserved[s + 1] >= slots[s + 1]:
            return None
        for q in ((5, 3) if s == 3 and not automatic else (s,)):
            for i, item in enumerate(queues[q]):
                if s == 3:
                    routed = (item.attempt == 0 and plan.robot and
                              (plan.route == "all" or plan.route == "bypass" and item.order.kind == "regular"))
                    if routed != automatic:
                        continue
                    started += 1
                    trays += int(plan.trays and item.attempt == 0)
                    rework += int(item.attempt == 1)
                if s < 4:
                    reserved[s + 1] += 1
                return queues[q].pop(i)
        return None

    for t in range(horizon + 1):
        for w in workers:
            job = w.job
            if job is not None and job.end == t:
                w.job = None
                if job.mode == "assist":
                    assert robot is not None and robot.mode == "assisted"
                    robot.mode, robot.end = "released", t
                else:
                    complete(job, w.name)
        if robot is not None and robot.end == t and robot.mode in ("work", "released"):
            if robot.mode == "work" and hit(robot.item, 3, "jam", prob["jam"][rig][robot.item.order.kind]):
                robot.mode = "waiting"
                emit("jam", robot.item, "robot", 3)
            else:
                complete(robot, "robot")
                robot = None
        while index < len(orders) and orders[index].arrival == t:
            item = Item(orders[index])
            emit("arrival", item, stage=1)
            put(item, 1)
            index += 1
        if t == horizon or good + escaped + scrap == len(orders):
            break
        if plan.robot and plan.route != "manual" and robot is None:
            item = take(3, True)
            if item:
                robot = Job(item, 3, t + times["auto"][rig][item.order.kind])
                emit("start", item, "robot", 3, robot.end)
        for w in workers:
            if w.job is not None or t < w.break_end:
                continue
            if w.break_end == -1 and t >= clock["break_at"]:
                w.break_end = t + clock["break_length"]
                emit("break", resource=w.name, end=w.break_end)
                continue
            helping = robot is not None and robot.mode == "waiting" and 3 in w.zones
            if helping:
                s, item, duration = 3, robot.item, times["jam_service"]
                robot.mode = "assisted"
            else:
                for s in (4, 3, 2, 1):
                    if s in w.zones and (item := take(s, False)) is not None:
                        break
                else:
                    continue
                duration = times["manual"][item.order.kind][s - 1]
            travel = clock["walk_ticks"] if w.pos != s else 0
            end = t + travel + duration
            w.pos = s
            w.job = Job(item, s, end, "assist" if helping else "work")
            w.last = min(horizon, end)
            labor += w.last - t
            emit("assist" if helping else "start", item, w.name, s, end)
            if travel:
                emit("walk", item, w.name, s, t + travel)
    unfinished = sum(map(len, queues.values())) + int(robot is not None) + sum(
        w.job is not None and w.job.mode != "assist" for w in workers)
    if index != len(orders) or good + escaped + scrap + unfinished != len(orders):
        raise RuntimeError("order conservation failed")
    return RawReport(1, scenario.seed, len(orders), good, on_time, escaped, scrap, unfinished,
                     started, finished, auto, trays, rework, labor,
                     tuple(max(0, w.last - shift) for w in workers), tuple(events))
