import {duration, number} from './format.js';

export const strategyLabels = Object.freeze({
  manual: 'Manual Baseline',
  candidate: 'Candidate',
  reference: 'Reference',
  local: 'Local Run',
});

export const workerStates = Object.freeze({
  idle: 'Idle',
  walk: 'Walking',
  carry_idle: 'Holding Order',
  carry_walk: 'Carrying Order',
  pickup: 'Picking Up',
  place_down: 'Placing Down',
  reach: 'Reaching',
  prepare: 'Preparing',
  pick: 'Picking',
  pack: 'Packing',
  inspect: 'Inspecting',
  assist: 'Assisting Robot',
  break: 'Break',
  not_purchased: 'Not Purchased',
  disabled: 'Disabled',
  jammed: 'Jammed',
  helper_walking: 'Helper En Route',
  service: 'Servicing',
  finished: 'Finished',
});

export const importantLabels = Object.freeze({
  jam: 'Jam',
  assist: 'Assist',
  rework: 'Rework',
  break: 'Break',
  escaped: 'Escaped Defect',
  scrap: 'Scrap',
});

export const costLabels = Object.freeze({
  depreciation: 'Depreciation',
  service: 'Robot Service',
  shifts: 'Shift Wages',
  overtime: 'Overtime',
  trays: 'Trays',
  materials: 'Materials',
  rework: 'Rework',
  late: 'Late Penalty',
  unfulfilled: 'Scrap & Unfinished',
  escaped: 'Escaped Defects',
});

export const queueLabels = Object.freeze({
  Q1: 'Inbound',
  Q2: 'To Pick',
  Q3: 'To Pack',
  Q4: 'To QC',
  R: 'Rework',
});

export const stageLabels = Object.freeze({
  1: 'Prep',
  2: 'Pick',
  3: 'Pack',
  4: 'QC',
});

const routeLabels = {
  manual: 'Manual Pack',
  all: 'All via Robot',
  bypass: 'Regular via Robot',
};

const orderStatuses = {
  not_arrived: 'Not Arrived',
  arrived: 'Arrived',
  queue: 'Queued',
  processing: 'In Progress',
  finished_stage: 'Stage Done',
  good: 'Good',
  escaped: 'Escaped Defect',
  scrap: 'Scrapped',
  unfinished: 'Unfinished',
};

const orderKinds = {
  regular: 'Regular',
  fragile: 'Fragile',
  oversize: 'Oversize',
};

const share = (numerator, denominator) => denominator > 0 ? numerator / denominator * 100 : null;
const hours = (ticks, tickSeconds) => Number.isFinite(ticks) ? ticks * tickSeconds / 3600 : null;

/** A read-only view of one replay prefix, with final results in a distinct scope. */
export function makeView(entry, state) {
  if (!entry?.replay || !state) return null;
  const {replay} = entry, {manifest} = replay, {plan, raw, economy} = manifest;
  const counters = state.counters;
  return {
    run: {
      id: entry.run?.id ?? replay.runId,
      label: strategyLabels[entry.run?.strategy] ?? entry.run?.label ?? replay.runId,
      strategy: entry.run?.strategy,
      seed: manifest.scenario.seed,
      mode: entry.quarter ? 'quarterly' : 'v1',
      week: entry.week ?? 0,
    },
    clock: {
      seconds: state.timeSeconds,
      tick: state.tickFloat ?? state.tick,
      tickSeconds: replay.tickSeconds,
      horizonTicks: replay.horizonTicks,
      ended: state.ended,
    },
    current: {
      counters,
      arrived: state.arrivedCount,
      inSystem: state.inSystem,
      notArrived: state.notArrived,
      good: counters.good,
      onTime: counters.on_time,
      escaped: counters.escaped,
      scrap: counters.scrap,
      packsFinished: counters.pack_finished,
      autoFinished: counters.auto_finished,
      laborHours: hours(counters.labor_ticks, replay.tickSeconds),
      autoShare: share(counters.auto_finished, counters.pack_finished),
      onTimeShare: share(counters.on_time, counters.total),
      goodShare: share(counters.good, counters.total),
      queues: state.queues,
      resources: [...Object.values(state.workers), state.robot],
    },
    final: {
      scope: entry.quarter ? 'week' : 'shift',
      raw,
      economy,
      laborHours: hours(raw.labor_ticks, replay.tickSeconds),
      autoShare: share(raw.auto_finished, raw.pack_finished),
      onTimeShare: share(raw.on_time, raw.total),
      goodShare: share(raw.good, raw.total),
    },
    plan: {
      workers: plan.workers.length,
      robot: plan.robot,
      trays: plan.trays,
      route: plan.route,
      routeLabel: routeLabels[plan.route] ?? plan.route,
      zones: plan.workers,
      summary: [
        `${plan.workers.length} workers`,
        plan.robot ? 'Robot' : 'No Robot',
        plan.trays ? 'Trays' : 'No Trays',
        routeLabels[plan.route] ?? plan.route,
      ],
    },
    evaluation: entry.evaluation ?? null,
    evaluationSeeds: entry.evaluationSeeds ?? [],
    quarter: entry.quarter ? {
      totalCostCents: entry.quarter.total_cost,
      purchaseCents: entry.quarter.purchase,
      weekSummary: entry.weekSummary,
      weeksCount: entry.quarter.weeks.length,
    } : null,
  };
}

function normalizeEntity(entity) {
  if (entity && typeof entity === 'object') return {type: entity.type ?? entity.kind, id: entity.id ?? entity.orderId};
  if (typeof entity === 'number') return {type: 'order', id: entity};
  if (entity === 'robot') return {type: 'robot', id: 'robot'};
  if (/^w\d+$/.test(entity)) return {type: 'worker', id: entity};
  if (Object.hasOwn(queueLabels, entity)) return {type: 'queue', id: entity};
  return null;
}

/** Inspector fields contain only state known at this prefix, never future outcomes. */
export function inspectEntity(entry, state, entity) {
  if (!entry?.replay || !state) return null;
  const selection = normalizeEntity(entity);
  if (!selection) return null;
  const {type, id} = selection, tickSeconds = entry.replay.tickSeconds;
  const at = `At ${duration(state.timeSeconds)}`;
  if (type === 'worker') {
    const worker = state.workers[id];
    if (!worker) return null;
    const fields = [
      {label: 'Current Zone', value: stageLabels[worker.zone] ?? '—'},
      {label: 'Assigned Zones', value: worker.zones.map(zone => `${zone} · ${stageLabels[zone]}`).join(', ')},
      {label: 'Order', value: worker.orderId != null ? `#${worker.orderId}` : '—'},
    ];
    if (worker.activity) {
      fields.push({
        label: 'Window',
        value: `${duration(worker.activity.startTick * tickSeconds)} → ${duration(worker.activity.endTick * tickSeconds)}`,
      });
    }
    return {
      title: `Worker ${id.toUpperCase()}`,
      eyebrow: at,
      status: workerStates[worker.state] ?? worker.state,
      fields,
      orders: worker.orderId != null ? [worker.orderId] : [],
    };
  }
  if (type === 'robot') {
    const robot = state.robot;
    const fields = [
      {label: 'Route', value: routeLabels[entry.replay.manifest.plan.route] ?? '—'},
      {label: 'Order', value: robot.orderId != null ? `#${robot.orderId}` : '—'},
      {label: 'Helper', value: robot.helperId?.toUpperCase() ?? '—'},
    ];
    if (robot.jamTick != null) fields.push({label: 'Jam Time', value: duration(robot.jamTick * tickSeconds)});
    if (robot.assistEndTick != null) fields.push({label: 'Assist Until', value: duration(robot.assistEndTick * tickSeconds)});
    return {
      title: 'Packing Robot',
      eyebrow: at,
      status: workerStates[robot.state] ?? robot.state,
      fields,
      orders: robot.orderId != null ? [robot.orderId] : [],
    };
  }
  if (type === 'queue') {
    const orders = state.queues[id];
    if (!orders) return null;
    const capacity = state.capacity[id];
    return {
      title: `${id} · ${queueLabels[id] ?? id}`,
      eyebrow: at,
      status: `${orders.length} queued`,
      fields: [
        {label: 'Waiting', value: number(orders.length)},
        {label: 'Reserved', value: state.reserved[id] != null ? number(state.reserved[id]) : 'N/A'},
        {label: 'Capacity', value: capacity != null ? `${capacity} slots` : 'Unbounded'},
      ],
      orders: [...orders],
    };
  }
  if (type === 'order') {
    const order = state.orders[id];
    if (!order) return null;
    if (order.status === 'not_arrived') {
      return {
        title: `Order #${order.id}`,
        eyebrow: at,
        status: orderStatuses.not_arrived,
        fields: [{label: 'Details', value: 'Available after arrival'}],
      };
    }
    const fields = [
      {label: 'Type', value: orderKinds[order.kind] ?? order.kind},
      {label: 'Arrival', value: duration(order.arrival * tickSeconds)},
      {label: 'Due', value: duration(order.due * tickSeconds)},
      {label: 'Stage', value: stageLabels[order.stage] ?? '—'},
      {label: 'Queue', value: order.queue ? `${order.queue} · ${queueLabels[order.queue]}` : '—'},
      {label: 'Resource', value: order.resource === 'robot' ? 'Robot' : order.resource?.toUpperCase() ?? '—'},
      {label: 'Attempt', value: order.attempt === 1 ? 'Rework' : 'First'},
    ];
    if (order.outcomeTick != null) fields.push({label: 'Completed', value: duration(order.outcomeTick * tickSeconds)});
    return {
      title: `Order #${order.id}`,
      eyebrow: at,
      status: orderStatuses[order.status] ?? order.status,
      fields,
    };
  }
  return null;
}
