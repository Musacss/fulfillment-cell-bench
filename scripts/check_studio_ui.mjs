#!/usr/bin/env node
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {createReplay} from '../studio/src/replay.js';
import {euros, number, duration, percent, html} from '../studio/src/ui/format.js';
import {makeView, inspectEntity} from '../studio/src/ui/model.js';

const directory = new URL('../artifacts/3d-pack/v1-reference-seed11/', import.meta.url);
const manifest = JSON.parse(await fs.readFile(new URL('manifest.json', directory), 'utf8'));
const replay = createReplay(manifest, await fs.readFile(new URL('events.jsonl', directory), 'utf8'));
const entry = {replay, run: {id: 'v1-reference-seed11', strategy: 'reference'}, evaluationSeeds: [11, 29, 47]};
const start = replay.worldAt(0), middle = replay.worldAt(250.5), end = replay.worldAt(replay.horizonTicks);
const early = makeView(entry, start), partial = makeView(entry, middle), final = makeView(entry, end);

assert.equal(euros(undefined), '—');
assert.equal(euros(null), '—');
assert.notEqual(euros(0), '—');
assert.equal(euros(1530000), new Intl.NumberFormat('ru-RU', {style: 'currency', currency: 'EUR'}).format(15300));
assert.equal(number(NaN), '—');
assert.equal(duration(32400), '09:00:00');
assert.equal(duration(null), '—');
assert.equal(percent(0, 0), '—');
assert.equal(percent(1, 4), new Intl.NumberFormat('ru-RU', {style: 'percent', maximumFractionDigits: 1}).format(.25));
assert.equal(html('<b title="x">&\''), '&lt;b title=&quot;x&quot;&gt;&amp;&#39;');

assert.equal(early.current.good, 0, 'Start must not leak final good count');
assert.equal(early.current.laborHours, 0);
assert.equal(early.final.raw.good, manifest.raw.good, 'Final result stays in its explicit final scope');
assert.equal(partial.final.economy.total, manifest.economy.total);
assert.equal(partial.current.good, middle.counters.good);
assert.ok(partial.current.good < partial.final.raw.good, 'A real prefix differs from its final result');
assert.equal(partial.current.laborHours, middle.counters.labor_ticks * replay.tickSeconds / 3600);
assert.equal(partial.current.onTimeShare, middle.counters.on_time / manifest.raw.total * 100);
assert.equal(partial.current.autoShare, middle.counters.auto_finished / middle.counters.pack_finished * 100);
assert.equal(final.current.good, final.final.raw.good);
assert.equal(final.current.autoFinished, final.final.raw.auto_finished);
assert.equal(final.clock.tickSeconds, manifest.world.clock.tick_seconds);
assert.equal(final.clock.seconds, replay.horizonTicks * replay.tickSeconds);
assert.equal(early.current.autoShare, null, 'No completed packs means no observable percentage');
assert.equal(final.quarter, null, 'Shift result must not invent quarter results');

const future = Object.values(start.orders).find(order => order.status === 'not_arrived');
assert.ok(future);
const futureInspector = inspectEntity(entry, start, {type: 'order', id: future.id});
assert.equal(futureInspector.status, 'Ещё не поступил');
assert.deepEqual(futureInspector.fields, [{label: 'Сведения', value: 'Доступны после поступления'}]);
const queue = inspectEntity(entry, middle, {type: 'queue', id: 'Q3'});
assert.deepEqual(queue.orders, middle.queues.Q3);
assert.notEqual(queue.orders, middle.queues.Q3, 'Inspector does not expose queue array for mutation');
assert.equal(queue.fields.find(field => field.label === 'Вместимость').value, `${manifest.world.capacity.pack} мест`);
assert.ok(inspectEntity(entry, middle, {type: 'worker', id: 'w0'}).fields.some(field => field.label === 'Разрешённые зоны'));
assert.equal(inspectEntity(entry, middle, {type: 'worker', id: 'missing'}), null);
assert.equal(inspectEntity(entry, middle, 'robot').title, 'Упаковочный робот');

const quarter = makeView({...entry, quarter: {weeks: [{}, {}], total_cost: 100, purchase: 200}, week: 1, weekSummary: {}}, middle);
assert.equal(quarter.final.scope, 'week');
assert.equal(quarter.final.economy.total, manifest.economy.total, 'Week economy stays separate from quarter totals');
assert.equal(quarter.quarter.totalCostCents, 100);
assert.equal(quarter.quarter.weekSummary.carryover_out, undefined, 'Missing quarter data stays missing');
console.log('Studio UI: real replay prefix/final, units, denominators, inspectors and quarter scopes verified.');
