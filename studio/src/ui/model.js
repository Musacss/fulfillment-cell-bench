const ORDER_STATUS_LABELS = Object.freeze({
  not_arrived: 'Ещё не поступил',
  arrived: 'Поступил',
  queue: 'В очереди',
  processing: 'В работе',
  finished_stage: 'Этап завершён',
  good: 'Годен',
  escaped: 'Выдан брак',
  scrap: 'Списан',
  unfinished: 'Не завершён',
});

export function makeView(entry, state) {
  const { replay } = entry;
  const manifest = replay.manifest;
  const tickSeconds = manifest.world.clock.tick_seconds;
  const c = state.counters;
  const totalOrders = manifest.raw.total;

  return {
    clock: {
      tick: state.tick,
      tickFloat: state.tickFloat ?? state.tick,
      seconds: state.timeSeconds ?? (state.tickFloat ?? state.tick) * tickSeconds,
      tickSeconds,
      horizonTicks: replay.horizonTicks,
      ended: Boolean(state.ended),
    },
    current: {
      good: c.good,
      onTime: c.on_time,
      escaped: c.escaped,
      scrap: c.scrap,
      unfinished: c.unfinished,
      arrived: state.arrivedCount,
      inSystem: state.inSystem,
      notArrived: state.notArrived,
      packStarted: c.pack_started,
      packFinished: c.pack_finished,
      autoFinished: c.auto_finished,
      traysUsed: c.trays_used,
      reworkStarted: c.rework_started,
      laborTicks: c.labor_ticks,
      laborHours: (c.labor_ticks * tickSeconds) / 3600,
      overtimeTicks: [...c.overtime_ticks],
      onTimeShare: totalOrders > 0 ? (c.on_time / totalOrders) * 100 : null,
      autoShare: c.pack_finished > 0 ? (c.auto_finished / c.pack_finished) * 100 : null,
    },
    final: {
      scope: entry.quarter ? 'week' : 'shift',
      raw: structuredClone(manifest.raw),
      economy: structuredClone(manifest.economy),
    },
    quarter: entry.quarter
      ? {
          week: entry.week ?? 0,
          weekCount: Array.isArray(entry.quarter.weeks) ? entry.quarter.weeks.length : 0,
          totalCostCents: entry.quarter.total_cost,
          purchaseCents: entry.quarter.purchase,
          weekSummary: entry.weekSummary ? structuredClone(entry.weekSummary) : {},
        }
      : null,
  };
}

export function inspectEntity(entry, state, target) {
  if (!target || !entry || !state) return null;
  const normalized =
    typeof target === 'string'
      ? target === 'robot'
        ? { type: 'robot', id: 'robot' }
        : null
      : { type: target.type, id: target.id };
  if (!normalized) return null;

  const manifest = entry.replay.manifest;

  if (normalized.type === 'order') {
    const orderId = Number(normalized.id);
    const order = state.orders?.[orderId] ?? state.orders?.[normalized.id];
    if (!order) return null;
    const status = ORDER_STATUS_LABELS[order.status] || String(order.status);
    if (order.status === 'not_arrived') {
      return {
        type: 'order',
        id: order.id,
        title: `Заказ #${order.id}`,
        status,
        fields: [{ label: 'Сведения', value: 'Доступны после поступления' }],
      };
    }
    return {
      type: 'order',
      id: order.id,
      title: `Заказ #${order.id}`,
      status,
      fields: [
        { label: 'Тип', value: String(order.kind) },
        { label: 'Этап', value: String(order.stage) },
        { label: 'Попытка', value: String(order.attempt) },
        { label: 'Очередь', value: order.queue || '—' },
        { label: 'Ресурс', value: order.resource || '—' },
        { label: 'Дедлайн', value: `тик ${order.due}` },
      ],
    };
  }

  if (normalized.type === 'queue') {
    const queueId = String(normalized.id);
    if (!Object.hasOwn(state.queues || {}, queueId)) return null;
    const orders = [...state.queues[queueId]];
    const capByQueue = {
      Q2: manifest.world.capacity.pick,
      Q3: manifest.world.capacity.pack,
      Q4: manifest.world.capacity.qc,
    };
    const cap = state.capacity?.[queueId] ?? capByQueue[queueId] ?? null;
    const reserved = state.reserved?.[queueId] ?? null;
    return {
      type: 'queue',
      id: queueId,
      title: `Очередь ${queueId}`,
      status: orders.length > 0 ? `${orders.length} в очереди` : 'Пусто',
      orders,
      fields: [
        { label: 'Ожидают', value: String(orders.length) },
        { label: 'Бронь', value: reserved !== null ? String(reserved) : '—' },
        { label: 'Вместимость', value: cap !== null ? `${cap} мест` : '∞' },
      ],
    };
  }

  if (normalized.type === 'worker') {
    const workerId = String(normalized.id);
    const worker = state.workers?.[workerId];
    if (!worker) return null;
    return {
      type: 'worker',
      id: workerId,
      title: `Оператор ${workerId.toUpperCase()}`,
      status: String(worker.state),
      fields: [
        { label: 'Состояние', value: String(worker.state) },
        { label: 'Текущая зона', value: `Зона ${worker.zone}` },
        { label: 'Разрешённые зоны', value: worker.zones.join(', ') },
        { label: 'Заказ', value: worker.orderId != null ? `#${worker.orderId}` : '—' },
      ],
    };
  }

  if (normalized.type === 'robot') {
    const robot = state.robot;
    if (!robot) return null;
    return {
      type: 'robot',
      id: 'robot',
      title: 'Упаковочный робот',
      status: String(robot.state),
      fields: [
        { label: 'Состояние', value: String(robot.state) },
        { label: 'Маршрут', value: String(manifest.plan.route) },
        { label: 'Лотки', value: manifest.plan.trays ? 'Да' : 'Нет' },
        { label: 'Заказ', value: robot.orderId != null ? `#${robot.orderId}` : '—' },
      ],
    };
  }

  return null;
}
