"""Generate the exogenous order stream for a day of the synthetic warehouse."""
from .contracts import Kind, Order, Scenario, World, draw


def generate(world: World, seed: int) -> Scenario:
    if type(seed) is not int:
        raise ValueError("scenario seed must be an integer")
    rules = world["generator"]
    orders = []
    fragile_limit = rules["regular_bps"] + rules["fragile_bps"]
    for wave in range(rules["waves"]):
        count = rules["orders_min"] + draw(seed, wave, 0, 0, "wave", rules["orders_span"])
        for _ in range(count):
            order_id = len(orders)
            jitter = draw(seed, order_id, 0, 0, "arrival", rules["jitter_span"])
            arrival = wave * rules["spacing"] + jitter
            due = arrival + rules["due_offset"] + draw(seed, order_id, 0, 0, "due", rules["due_span"])
            kind_draw = draw(seed, order_id, 0, 0, "kind", 10_000)
            kind: Kind
            if kind_draw < rules["regular_bps"]:
                kind = "regular"
            elif kind_draw < fragile_limit:
                kind = "fragile"
            else:
                kind = "oversize"
            orders.append(Order(order_id, kind, arrival, due))
    orders.sort(key=lambda order: (order.arrival, order.id))
    return Scenario(world["schema_version"], seed, tuple(orders))
