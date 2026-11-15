import './styles.css';
import { openRemote, openLocal } from './data.js';
import { createScenePlayer } from './scene.js';
import { environmentLayers } from './visual/environment-layers.js';
import { duration, euros, html, number, percent } from './ui/format.js';
import {
  costLabels,
  importantLabels,
  inspectEntity,
  makeView,
  queueLabels,
  strategyLabels,
  workerStates,
} from './ui/model.js';

const $ = id => document.getElementById(id);

const LAYER_LABELS = Object.freeze({
  ENV_FLOOR_AND_GRID: ['Floor & Grid', 'GRID'],
  ENV_WALLS_AND_DOCKS: ['Walls & Docks', 'DOCK'],
  ENV_WORKSTATIONS_DETAIL: ['Workstations', 'POST'],
  ENV_ROBOT_CELL: ['Robot Cell', 'CELL'],
  ENV_BREAK_AREA: ['Break Area', 'BRK'],
});

const STAGE_NAMES = Object.freeze({
  S0_INBOUND: 'Inbound Q1',
  S1_PREP: 'Prep',
  S2_PICK: 'Picking',
  S3A_PACK_MANUAL: 'Manual Pack',
  S3B_PACK_ROBOT: 'Robot Pack',
  S3C_ROBOT_ASSIST: 'Robot Assist',
  S4_QC: 'QC',
  S5A_GOOD: 'Good',
  S5B_ESCAPED: 'Escaped',
  S5C_REWORK_R: 'Rework R',
  S5D_SCRAP: 'Scrap',
  S5E_BREAK: 'Break',
});

const REASON_LABELS = Object.freeze({
  cost: 'cost > baseline',
  labor: 'labor > baseline',
  automation: 'auto pack < 30%',
  budget: 'over budget',
});

const ROUTE_SHORT = Object.freeze({
  manual: 'MANUAL',
  bypass: 'BYPASS',
  all: 'ALL → ROBOT',
});

const RUN_LABEL_CLEAN = Object.freeze({
  'Manual Baseline (6 Workers)': 'Manual Baseline',
  'Phased Reference Rollout': 'Reference',
  'Naive AI (Wear Blowout)': 'Naive AI',
  manual: 'Manual Baseline',
  candidate: 'Candidate',
  reference: 'Reference',
});

const query = new URLSearchParams(location.search);

let source = null;
let workshopChain = null;
let mode = query.get('mode') === 'single' ? 'single' : 'compare';
const rawCam = query.get('cam');
let cameraPreset = ['overview', 'blueprint', 'top', 'q1', 'robot', 'qc', 'rework', 'break'].includes(rawCam)
  ? (rawCam === 'top' ? 'blueprint' : rawCam)
  : 'overview';
let selectedWeek = Math.max(0, Math.min(11, Number(query.get('week') ?? 6) || 0));
let current = [];
let snapshots = [];
let time = 0;
let playing = false;
let speed = 15;
let activeInspector = 0;
let activeTab = 'flow';
let selectedEntity = null;
let syncingSelection = false;
let requestVersion = 0;
let loading = false;
let disposed = false;
let lastPaint = -1;
let lastLedgerPaint = -1;
let initialSeekApplied = false;

const players = [null, null];
const playerPromises = [null, null];
const panelStats = [{}, {}];
const layerState = new Map(environmentLayers.filter(([name]) => Object.hasOwn(LAYER_LABELS, name)));

function toast(msg, isError = false) {
  const el = $('status-toast');
  if (!msg) {
    el.style.display = 'none';
    return;
  }
  el.textContent = msg;
  el.className = isError ? 'status-toast err' : 'status-toast';
  el.style.display = 'block';
  if (!isError) {
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => {
      if (!el.classList.contains('err')) el.style.display = 'none';
    }, 2800);
  }
}

function maxDuration() {
  return Math.max(0, ...current.map(item => item.replay.durationSeconds));
}

function maxHorizonTicks() {
  return Math.max(1, ...current.map(item => item.replay.horizonTicks));
}

function tickSeconds() {
  return current[0]?.replay.tickSeconds || 30;
}

function setPlaying(next) {
  playing = Boolean(next) && current.length > 0 && !loading;
  $('btn-play').textContent = playing ? 'PAUSE' : 'PLAY';
}

function runShortName(run) {
  if (!run) return '—';
  const raw = run.label || strategyLabels[run.strategy] || run.id;
  if (RUN_LABEL_CLEAN[raw]) return RUN_LABEL_CLEAN[raw];
  return String(raw).replace(/\s*\([^)]*\)\s*$/, '').trim();
}

function runOptionLabel(run) {
  return `S${run.seed} · ${runShortName(run)}`;
}

function setControlsDisabled(disabled) {
  for (const id of ['btn-reset', 'btn-step-back', 'btn-play', 'btn-step-fwd', 'tick-scrubber', 'btn-next-event']) {
    $(id).disabled = disabled;
  }
}

function syncCameraButtons() {
  document.querySelectorAll('[data-cam]').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.cam === cameraPreset);
  });
}

function setCameraPreset(nextPreset) {
  cameraPreset = nextPreset === 'top' ? 'blueprint' : nextPreset;
  syncCameraButtons();
  players.forEach(p => p?.setCameraPreset(cameraPreset));
  if (activeTab === 'scene') renderSceneStats();
}

function selectSceneEntity(entity, { fromPlayerIndex = null, openSceneTab = false } = {}) {
  if (syncingSelection) return;
  syncingSelection = true;
  try {
    selectedEntity = entity ? { ...entity } : null;
    if (fromPlayerIndex !== null && current[fromPlayerIndex]) {
      activeInspector = fromPlayerIndex;
      updateInspectorSwitch();
    }
    players.forEach((player, idx) => {
      if (!player) return;
      if (fromPlayerIndex === idx) return;
      if (!selectedEntity) {
        player.clearSelection?.();
      } else if (selectedEntity.type === 'order' || idx === activeInspector) {
        player.selectEntity?.(selectedEntity);
      } else {
        player.clearSelection?.();
      }
    });
    if (openSceneTab && selectedEntity) {
      switchTab('scene');
    }
    renderLedger();
  } finally {
    syncingSelection = false;
  }
}

async function loadWorkshopChainOnce() {
  if (workshopChain) return workshopChain;
  try {
    const res = await fetch(new URL('./scene/workshop_chain.json', document.baseURI).href);
    if (res.ok) workshopChain = await res.json();
  } catch {}
  return workshopChain;
}

async function ensurePlayer(index) {
  if (players[index]) return players[index];
  if (!playerPromises[index]) {
    const side = index ? 'right' : 'left';
    const loadingEl = $('loading-' + side);
    loadingEl.hidden = false;
    loadingEl.textContent = 'LOADING...';

    playerPromises[index] = createScenePlayer($('canvas-' + side), {
      assetBase: new URL('./scene/', document.baseURI).href,
      onStats: stats => {
        panelStats[index] = stats || {};
        if (activeTab === 'scene') renderSceneStats();
      },
      onSelection: entity => {
        selectSceneEntity(entity, { fromPlayerIndex: index, openSceneTab: Boolean(entity) });
      },
    })
      .then(player => {
        players[index] = player;
        for (const [name, visible] of layerState) {
          player.setLayer(name, visible);
        }
        player.setCameraPreset(cameraPreset);
        loadingEl.hidden = true;
        player.resize();
        return player;
      })
      .catch(error => {
        loadingEl.hidden = false;
        loadingEl.textContent = 'ERROR: ' + (error.message || error);
        playerPromises[index] = null;
        throw error;
      });
  }
  return playerPromises[index];
}

function disposeAllPlayers() {
  for (let i = 0; i < players.length; i++) {
    try {
      players[i]?.dispose();
    } catch (e) {
      console.warn(e);
    }
    players[i] = null;
    playerPromises[i] = null;
    panelStats[i] = {};
  }
}

function updateModeUI() {
  const isCompare = mode === 'compare';
  $('btn-mode-single').classList.toggle('active', !isCompare);
  $('btn-mode-compare').classList.toggle('active', isCompare);
  $('single-selectors').hidden = isCompare;
  $('compare-selectors').hidden = !isCompare;
  $('panel-right').hidden = !isCompare;
  $('scene-grid').classList.toggle('comparison', isCompare);
  $('inspector-switch').hidden = !isCompare;
  if (!isCompare) activeInspector = 0;
  updateInspectorSwitch();
  requestAnimationFrame(() => players.forEach(p => p?.resize()));
}

function updateInspectorSwitch() {
  document.querySelectorAll('#inspector-switch button').forEach(btn => {
    btn.classList.toggle('active', Number(btn.dataset.inspector) === activeInspector);
  });
  $('panel-left').classList.toggle('active-panel', activeInspector === 0);
  $('panel-right').classList.toggle('active-panel', activeInspector === 1);
}

function switchTab(tabName) {
  activeTab = tabName;
  document.querySelectorAll('.ledger-tabs .tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });
  document.querySelectorAll('.tab-pane').forEach(pane => {
    pane.classList.toggle('active', pane.id === 'tab-' + tabName);
  });
  renderLedger();
}

function populateSelectorsForSource() {
  if (!source) return;
  const seeds = [...new Set(source.index.runs.map(r => r.seed))].sort((a, b) => a - b);
  const prevSeed = $('sel-seed').value;
  $('sel-seed').replaceChildren(
    Object.assign(document.createElement('option'), { value: 'all', textContent: 'ALL' }),
    ...seeds.map(s => Object.assign(document.createElement('option'), { value: String(s), textContent: String(s) }))
  );
  if (seeds.map(String).includes(prevSeed)) {
    $('sel-seed').value = prevSeed;
  } else if (seeds.includes(11)) {
    $('sel-seed').value = '11';
  } else {
    $('sel-seed').value = 'all';
  }
  refreshFilteredRunSelectors(true);
}

function refreshFilteredRunSelectors(pickDefaults = false) {
  if (!source) return;
  const seedFilter = $('sel-seed').value;
  const runs = source.index.runs.filter(r => seedFilter === 'all' || String(r.seed) === seedFilter);
  const comparisons = source.index.comparisons.filter(p => seedFilter === 'all' || String(p.seed) === seedFilter);

  const fill = (el, items, labelFn, fallbackVal) => {
    const prev = el.value;
    el.replaceChildren(...items.map(item => {
      const opt = document.createElement('option');
      opt.value = item.id;
      opt.textContent = labelFn(item);
      return opt;
    }));
    if (!pickDefaults && items.some(x => x.id === prev)) {
      el.value = prev;
    } else if (fallbackVal && items.some(x => x.id === fallbackVal)) {
      el.value = fallbackVal;
    }
    el.disabled = !items.length;
  };

  const preferredSingle = runs.find(r => /reference/i.test(r.id) || r.strategy === 'reference')?.id || runs[0]?.id;
  fill($('sel-run'), runs, runOptionLabel, preferredSingle);

  const preferredPair =
    comparisons.find(p => /claude|gpt/i.test(p.left + ':' + p.right) && /reference/i.test(p.left + ':' + p.right)) ||
    comparisons.find(p => /candidate/i.test(p.left + ':' + p.right) && /reference/i.test(p.left + ':' + p.right)) ||
    comparisons[0];

  const compSelect = $('sel-comparison');
  const prevComp = compSelect.value;
  compSelect.replaceChildren(
    ...comparisons.map(pair => {
      const l = source.index.runs.find(r => r.id === pair.left);
      const r = source.index.runs.find(r => r.id === pair.right);
      const opt = document.createElement('option');
      opt.value = pair.id;
      opt.textContent = `S${pair.seed}: ${runShortName(l)} ↔ ${runShortName(r)}`;
      return opt;
    }),
    Object.assign(document.createElement('option'), { value: '__custom__', textContent: 'CUSTOM PAIR' })
  );

  if (!pickDefaults && ([...comparisons.map(c => c.id), '__custom__'].includes(prevComp))) {
    compSelect.value = prevComp;
  } else if (preferredPair) {
    compSelect.value = preferredPair.id;
  } else {
    compSelect.value = '__custom__';
  }

  const activePair = comparisons.find(c => c.id === compSelect.value);
  const seedForAB = activePair ? activePair.seed : (runs[0]?.seed ?? null);
  const abRuns = seedForAB != null
    ? source.index.runs.filter(r => r.seed === seedForAB && (!activePair || (r.mode === 'v1') === (activePair.mode === 'v1')))
    : runs;

  fill($('sel-run-a'), abRuns, runOptionLabel, activePair?.left || abRuns[0]?.id);
  fill($('sel-run-b'), abRuns, runOptionLabel, activePair?.right || abRuns[1]?.id || abRuns[0]?.id);

  if (!comparisons.length && abRuns.length < 2 && mode === 'compare') {
    mode = 'single';
    updateModeUI();
  }
}

async function loadActiveReplay() {
  if (!source) return;
  const version = ++requestVersion;
  loading = true;
  setPlaying(false);
  setControlsDisabled(true);
  toast('Loading...');

  try {
    loadWorkshopChainOnce();
    let entries;
    if (mode === 'compare') {
      const compId = $('sel-comparison').value;
      const pair = source.index.comparisons.find(c => c.id === compId);
      if (pair) {
        const week = pair.mode === 'v1' ? 0 : selectedWeek;
        entries = await source.loadComparison(pair, { week });
      } else {
        const idA = $('sel-run-a').value;
        const idB = $('sel-run-b').value;
        const runObjA = source.index.runs.find(r => r.id === idA);
        const week = runObjA?.mode === 'v1' ? 0 : selectedWeek;
        entries = await Promise.all([
          source.loadRun(idA, { week }),
          source.loadRun(idB, { week }),
        ]);
      }
    } else {
      const id = $('sel-run').value;
      const runObj = source.index.runs.find(r => r.id === id);
      const week = runObj?.mode === 'v1' ? 0 : selectedWeek;
      entries = [await source.loadRun(id, { week })];
    }

    if (version !== requestVersion) return;

    const readyPlayers = await Promise.all(entries.map((_, i) => ensurePlayer(i)));
    if (version !== requestVersion) return;

    for (let i = 0; i < entries.length; i++) {
      await readyPlayers[i].setReplay(entries[i].replay);
    }
    if (version !== requestVersion) return;

    current = entries;
    loading = false;

    if (!initialSeekApplied) {
      initialSeekApplied = true;
      const queryTick = query.get('tick');
      if (queryTick !== null && Number.isFinite(Number(queryTick))) {
        time = Math.min(maxDuration(), Math.max(0, Number(queryTick) * tickSeconds()));
      } else {
        time = Math.min(maxDuration(), 240 * tickSeconds());
      }
    } else {
      time = Math.min(maxDuration(), Math.max(0, time));
    }

    if (selectedEntity) {
      selectSceneEntity(selectedEntity);
    }

    lastPaint = -1;
    lastLedgerPaint = -1;
    updateSceneHeaders();
    renderWeekStrip();
    renderScrubberMarkers();
    populateOrderPicker();
    setControlsDisabled(false);
    paint(true);
    toast('');

    window.dispatchEvent(new CustomEvent('replay-ready', { detail: { runs: entries.map(e => e.replay.runId) } }));
  } catch (error) {
    if (version === requestVersion) {
      loading = false;
      console.error(error);
      toast('ERROR: ' + (error.message || String(error)), true);
      setControlsDisabled(current.length === 0);
    }
  }
}

function updateSceneHeaders() {
  current.forEach((entry, idx) => {
    const side = idx ? 'right' : 'left';
    const prefix = current.length === 2 ? (idx ? 'B · ' : 'A · ') : '';
    const plan = entry.replay.manifest.plan;
    $('scene-label-' + side).textContent = prefix + runShortName(entry.run).toUpperCase();
    $('scene-plan-' + side).textContent = [
      `S${entry.run.seed}`,
      entry.quarter ? `W${String(entry.week).padStart(2, '0')}` : 'V1',
      `${plan.workers.length} WRK`,
      plan.robot ? 'ROBOT' : 'NO ROBOT',
      plan.trays ? 'TRAYS' : 'NO TRAYS',
      ROUTE_SHORT[plan.route] || plan.route.toUpperCase(),
    ].join(' · ');
  });

  const horizon = maxHorizonTicks();
  $('tick-scrubber').max = String(horizon);
  const otPct = (960 / horizon) * 100;
  $('ot-marker').style.display = otPct <= 99.5 ? 'block' : 'none';
  if (otPct <= 99.5) $('ot-marker').style.left = `${otPct.toFixed(2)}%`;

  const totalEvents = current.reduce((sum, item) => sum + item.replay.importantEvents.length, 0);
  $('ev-count').textContent = String(totalEvents);
}

function updatePanelBadges(state, idx) {
  const node = $('scene-badges-' + (idx ? 'right' : 'left'));
  if (!node || !state) return;
  const chips = [];
  chips.push(`<span class="canvas-badge summary">GOOD ${state.counters.good} · AUTO ${state.counters.auto_finished} · WIP ${state.inSystem}</span>`);
  for (const q of ['Q1', 'R']) {
    const preview = players[idx]?.queuePreviewCount?.[q] ?? 6;
    const overflow = Math.max(0, (state.queues[q]?.length || 0) - preview);
    if (overflow > 0) {
      chips.push(`<span class="canvas-badge">+${overflow} IN ${q}</span>`);
    }
  }
  if (['jammed', 'helper_walking', 'service'].includes(state.robot.state)) {
    chips.push(`<span class="canvas-badge crit">${html(workerStates[state.robot.state] || state.robot.state).toUpperCase()}</span>`);
  }
  if (state.counters.escaped > 0) {
    chips.push(`<span class="canvas-badge crit">DEFECT: ${state.counters.escaped}</span>`);
  }
  const markup = chips.join('');
  if (node.innerHTML !== markup) node.innerHTML = markup;
}

function setTime(seconds) {
  time = Math.min(maxDuration(), Math.max(0, Number(seconds) || 0));
  lastPaint = -1;
  paint(true);
  if (time >= maxDuration()) setPlaying(false);
}

function paint(force = false) {
  if (!current.length) return;
  if (force || time !== lastPaint) {
    snapshots = current.map(item => item.replay.seekTo(Math.min(time, item.replay.durationSeconds)));
    lastPaint = time;

    const tick = time / tickSeconds();
    const horizon = maxHorizonTicks();
    $('tick-scrubber').value = String(tick);
    $('clock-readout').textContent = `TICK ${String(Math.floor(tick)).padStart(4, '0')} / ${horizon} · ${duration(time)}`;

    snapshots.forEach((st, idx) => updatePanelBadges(st, idx));

    if (force) {
      for (let i = 0; i < current.length; i++) {
        if (players[i] && snapshots[i]) {
          players[i].render(snapshots[i], { playing, speed, deltaSeconds: 0 });
        }
      }
    }
  }

  if (force || lastLedgerPaint < 0 || performance.now() - lastLedgerPaint >= 150) {
    renderLedger();
    lastLedgerPaint = performance.now();
  }
}

function renderLedger() {
  const entry = current[activeInspector] || current[0];
  const state = snapshots[activeInspector] || snapshots[0];
  if (!entry || !state) return;

  const tick = state.tickFloat ?? state.tick;
  $('inspector-meta').textContent = `S${entry.run.seed} · ${entry.quarter ? 'W' + String(entry.week).padStart(2, '0') + ' · ' : ''}TICK ${number(tick)}`;

  if (activeTab === 'flow') {
    renderFlowTab(entry, state);
  } else if (activeTab === 'scene') {
    renderEntityInspector();
    renderWorkshopChain(entry, state);
    renderSceneStats();
  } else if (activeTab === 'econ') {
    renderEconTab();
  } else if (activeTab === 'events') {
    renderEventsTab();
  }
}

function renderFlowTab(entry, state) {
  const view = makeView(entry, state);
  const c = state.counters;
  const otherState = current.length === 2 ? snapshots[1 - activeInspector] : null;
  const deltaStr = (val, otherVal) => {
    if (!otherState || otherVal === undefined) return '';
    const d = val - otherVal;
    const otherTag = activeInspector === 0 ? 'B' : 'A';
    return `<small>vs ${otherTag}: ${d > 0 ? '+' : ''}${number(d)}</small>`;
  };

  const kpis = [
    ['GOOD', c.good, otherState?.counters.good, false],
    ['ON TIME', c.on_time, otherState?.counters.on_time, false],
    ['ARRIVED', state.arrivedCount, otherState?.arrivedCount, false],
    ['WIP', state.inSystem, otherState?.inSystem, false],
    ['DEFECTS', c.escaped, otherState?.counters.escaped, c.escaped > 0],
    ['SCRAP', c.scrap, otherState?.counters.scrap, c.scrap > 0],
  ];

  $('live-metrics-box').innerHTML = `
    <div class="plan-chips-row">
      ${view.plan.summary.map(s => `<span class="plan-chip">${html(s)}</span>`).join('')}
    </div>
    <div class="kpi-grid">
      ${kpis.map(([lbl, val, oVal, crit]) => `
        <div class="kpi-cell ${crit ? 'crit' : ''}">
          <span>${lbl}</span>
          <strong>${number(val)}</strong>
          ${deltaStr(val, oVal)}
        </div>
      `).join('')}
    </div>
    <div class="throughput-box">
      Packed: <b>${c.pack_finished}</b> / ${c.pack_started} · auto: <b>${c.auto_finished}</b> (${percent(c.auto_finished, c.pack_finished)})<br/>
      Labor: <b>${number(view.current.laborHours)} h</b> · rework R: <b>${c.rework_started}</b> · trays: <b>${c.trays_used}</b><br/>
      Pending: <b>${state.notArrived}</b> · unfinished: <b>${c.unfinished}</b><br/>
      Overtime: ${c.overtime_ticks.length ? c.overtime_ticks.map(number).join(' / ') : '0'}
    </div>
  `;

  $('live-queues-box').innerHTML = ['Q1', 'Q2', 'Q3', 'Q4', 'R'].map(q => {
    const waiting = state.queues[q]?.length || 0;
    const reserved = state.reserved[q] || 0;
    const cap = state.capacity?.[q];
    const denom = cap || Math.max(24, waiting + reserved, 1);
    const wPct = Math.min(100, (waiting / denom) * 100);
    const rPct = Math.min(100 - wPct, (reserved / denom) * 100);
    const saturated = cap != null && waiting + reserved >= cap;
    const isSel = selectedEntity?.type === 'queue' && selectedEntity.id === q;
    return `
      <div class="q-row ${saturated ? 'sat' : ''} ${isSel ? 'selected-row' : ''}" data-pick-queue="${q}">
        <div class="q-lbl">
          <span>${q} · ${html(queueLabels[q] || q)}</span>
          <b>${waiting}${reserved ? ` + ${reserved}` : ''} / ${cap ?? '∞'}</b>
        </div>
        <div class="q-bar">
          <div class="q-fill-wait" style="width:${wPct.toFixed(1)}%"></div>
          <div class="q-fill-res" style="width:${rPct.toFixed(1)}%"></div>
        </div>
      </div>
    `;
  }).join('');

  $('live-queues-box').querySelectorAll('[data-pick-queue]').forEach(el => {
    el.addEventListener('click', () => {
      const q = el.dataset.pickQueue;
      selectSceneEntity({ type: 'queue', id: q });
      players[activeInspector]?.selectEntity?.({ type: 'queue', id: q });
    });
  });

  const rows = [
    ...Object.entries(state.workers).map(([id, w]) => ({
      entityType: 'worker',
      entityId: id,
      code: id.toUpperCase(),
      zones: w.zones.join(','),
      zoneNow: w.zone ? 'Z' + w.zone : '—',
      state: w.state,
      orderId: w.orderId,
    })),
    {
      entityType: 'robot',
      entityId: 'robot',
      code: 'RBT',
      zones: 'PACK',
      zoneNow: state.robot.state === 'not_purchased' ? '—' : 'Z3',
      state: state.robot.state,
      orderId: state.robot.orderId,
    },
  ];

  $('live-resources-box').innerHTML = `
    <table class="cad-table">
      <thead>
        <tr>
          <th>ID</th>
          <th>ZONES</th>
          <th>POST</th>
          <th>STATE</th>
          <th>ORDER</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map(r => {
          const crit = ['jammed', 'helper_walking', 'service', 'assist'].includes(r.state);
          const busy = !['idle', 'disabled', 'not_purchased', 'break'].includes(r.state);
          const isSel = selectedEntity?.type === r.entityType && selectedEntity.id === r.entityId;
          return `
            <tr class="clickable-row ${busy ? 'row-work' : ''} ${crit ? 'row-assist' : ''} ${isSel ? 'selected-row' : ''}"
                data-pick-type="${r.entityType}" data-pick-id="${r.entityId}">
              <td>${html(r.code)}</td>
              <td>${html(r.zones)}</td>
              <td>${html(r.zoneNow)}</td>
              <td>${html(workerStates[r.state] || r.state)}</td>
              <td>${r.orderId != null ? '#' + r.orderId : '—'}</td>
            </tr>
          `;
        }).join('')}
      </tbody>
    </table>
  `;

  $('live-resources-box').querySelectorAll('[data-pick-type]').forEach(tr => {
    tr.addEventListener('click', () => {
      const entity = { type: tr.dataset.pickType, id: tr.dataset.pickId };
      selectSceneEntity(entity);
      players[activeInspector]?.selectEntity?.(entity);
    });
  });
}

function populateOrderPicker() {
  const entry = current[activeInspector] || current[0];
  if (!entry) return;
  const orders = entry.replay.manifest.scenario?.orders || [];
  const sel = $('sel-order-pick');
  sel.replaceChildren(
    Object.assign(document.createElement('option'), {
      value: '',
      textContent: `— ORDER (${orders.length}) —`,
    }),
    ...orders.map(o => {
      const opt = document.createElement('option');
      opt.value = String(o.id);
      opt.textContent = `#${o.id} · ${o.kind} · T${o.arrival}→T${o.due}`;
      return opt;
    })
  );
  if (selectedEntity?.type === 'order') {
    sel.value = String(selectedEntity.id);
  }
}

function renderEntityInspector() {
  const box = $('entity-inspector-box');
  if (!selectedEntity) {
    box.innerHTML = `<div class="ord-hint">Select an object in the scene or an order above.</div>`;
    return;
  }

  if (selectedEntity.type === 'order') {
    $('sel-order-pick').value = String(selectedEntity.id);
  }

  const targets = selectedEntity.type === 'order' && current.length === 2
    ? current.map((e, idx) => ({ entry: e, state: snapshots[idx], prefix: idx ? 'B' : 'A' }))
    : [{
        entry: current[activeInspector] || current[0],
        state: snapshots[activeInspector] || snapshots[0],
        prefix: current.length === 2 ? (activeInspector ? 'B' : 'A') : '',
      }];

  const cards = targets.map(({ entry, state, prefix }) => {
    const info = inspectEntity(entry, state, selectedEntity);
    if (!info) return '';
    return `
      <div class="ord-card">
        <div class="oc-head">
          <strong>${html(prefix ? prefix + ' · ' + info.title : info.title)}</strong>
          <span class="oc-status">${html(info.status)}</span>
        </div>
        <table class="cad-table">
          <tbody>
            ${(info.fields || []).map(f => `
              <tr>
                <th>${html(f.label)}</th>
                <td>${html(f.value)}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  }).filter(Boolean);

  box.innerHTML = cards.length ? cards.join('') : `<div class="ord-hint">No data.</div>`;
}

function renderWorkshopChain(entry, state) {
  const box = $('workshop-chain-box');
  if (!box) return;
  const stages = workshopChain?.stages;
  if (!stages?.length) {
    box.innerHTML = `<div class="ord-hint">Loading...</div>`;
    return;
  }
  const workersList = Object.values(state.workers || {});
  const stageStatus = st => {
    const id = st.id;
    if (id === 'S0_INBOUND') return `${state.queues.Q1?.length ?? 0} in Q1`;
    if (id === 'S1_PREP') return `${workersList.filter(w => w.zone === 1 && w.orderId != null).length} active`;
    if (id === 'S2_PICK') return `Q2:${state.queues.Q2?.length ?? 0} · wrk:${workersList.filter(w => w.zone === 2 && w.orderId != null).length}`;
    if (id === 'S3A_PACK_MANUAL') return `Q3:${state.queues.Q3?.length ?? 0} · wrk:${workersList.filter(w => w.zone === 3 && w.orderId != null && w.state !== 'assist').length}`;
    if (id === 'S3B_PACK_ROBOT') return workerStates[state.robot.state] || state.robot.state;
    if (id === 'S3C_ROBOT_ASSIST') return state.robot.helperId ? `Assist (${state.robot.helperId.toUpperCase()})` : 'Nominal';
    if (id === 'S4_QC') return `Q4:${state.queues.Q4?.length ?? 0} · wrk:${workersList.filter(w => w.zone === 4 && w.orderId != null).length}`;
    if (id === 'S5A_GOOD') return `${state.counters.good} good`;
    if (id === 'S5B_ESCAPED') return `${state.counters.escaped} defects`;
    if (id === 'S5C_REWORK_R') return `${state.queues.R?.length ?? 0} in R`;
    if (id === 'S5D_SCRAP') return `${state.counters.scrap} scrap`;
    if (id === 'S5E_BREAK') return `${workersList.filter(w => w.state === 'break').length} on break`;
    return '—';
  };

  box.innerHTML = `
    <table class="cad-table">
      <thead>
        <tr><th>STAGE</th><th>STATUS</th></tr>
      </thead>
      <tbody>
        ${stages.map(st => `
          <tr>
            <td>${html(STAGE_NAMES[st.id] || st.id)}</td>
            <td>${html(stageStatus(st))}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

function buildSceneLayersUI() {
  const box = $('scene-layers-box');
  box.replaceChildren();
  for (const [name, defaultVis] of environmentLayers) {
    if (!Object.hasOwn(LAYER_LABELS, name)) continue;
    const [title, code] = LAYER_LABELS[name];
    const row = document.createElement('label');
    row.className = 'layer-check-row';
    row.innerHTML = `
      <span class="layer-check-left">
        <input type="checkbox" ${layerState.get(name) ?? defaultVis ? 'checked' : ''} data-layer="${name}" />
        <span>${html(title)}</span>
      </span>
      <span class="layer-code">${html(code)}</span>
    `;
    row.querySelector('input').addEventListener('change', e => {
      const checked = e.target.checked;
      layerState.set(name, checked);
      players.forEach(p => p?.setLayer(name, checked));
      $('layer-count-lbl').textContent = `${[...layerState.values()].filter(Boolean).length} / ${layerState.size}`;
    });
    box.append(row);
  }
  $('layer-count-lbl').textContent = `${[...layerState.values()].filter(Boolean).length} / ${layerState.size}`;
}

function renderSceneStats() {
  const st = panelStats[activeInspector] || panelStats[0] || {};
  const rows = [
    ['Camera', cameraPreset.toUpperCase()],
    ['Visible Orders', number(st.visibleOrders ?? 0)],
    ['In Transit', number(st.inTransitOrders ?? 0)],
    ['Active Conveyors', number(st.activeConveyorModules ?? 0)],
    ['Workers', number(st.actors ?? 0)],
    ['Extra Benches', number(st.parallelBenches ?? 0)],
    ['Overflow Q1 / R', `${st.overflow?.Q1 ?? 0} / ${st.overflow?.R ?? 0}`],
  ];
  $('scene-stats-box').innerHTML = `
    <table class="cad-table">
      <tbody>
        ${rows.map(([k, v]) => `<tr><th>${html(k)}</th><td>${html(v)}</td></tr>`).join('')}
      </tbody>
    </table>
  `;
}

function renderEconTab() {
  $('eval-summary-box').innerHTML = current.map((entry, idx) => {
    const tag = current.length === 2 ? (idx ? 'B · ' : 'A · ') : '';
    const ev = entry.evaluation;
    if (!ev) {
      return `
        <div class="eval-card">
          <div class="ec-head">
            <span class="ec-name">${html(tag + runShortName(entry.run))}</span>
            <span class="ec-badge feas">V1</span>
          </div>
          <div class="ec-headline">Single shift.</div>
        </div>
      `;
    }
    const badgeCls = ev.win ? 'win' : ev.feasible ? 'feas' : 'fail';
    const badgeTxt = ev.win ? 'WIN' : ev.feasible ? 'FEASIBLE' : 'FAIL';
    const frac = ev.reward_num != null && ev.reward_den != null ? `REWARD ${ev.reward_num}/${ev.reward_den}` : '';
    const reasons = ev.reasons?.length
      ? 'Missed: ' + ev.reasons.map(r => REASON_LABELS[r] || r).join(', ')
      : 'All win criteria met';
    return `
      <div class="eval-card">
        <div class="ec-head">
          <span class="ec-name">${html(tag + runShortName(entry.run))}</span>
          <span class="ec-badge ${badgeCls}">${badgeTxt}</span>
        </div>
        <div class="ec-reward">
          <span>SEEDS: ${entry.evaluationSeeds.join(', ') || entry.run.seed}</span>
          <span>${html(frac)}</span>
        </div>
        <div class="ec-headline">
          ${ev.metrics ? `Total: <b>${euros(ev.metrics.total_cost)}</b> (base: ${euros(ev.metrics.base_cost)})<br/>` : ''}
          ${html(reasons)}
        </div>
      </div>
    `;
  }).join('');

  const entry = current[activeInspector] || current[0];
  if (entry?.quarter && entry.weekSummary) {
    $('quarter-summary-block').hidden = false;
    const q = entry.quarter;
    const w = entry.weekSummary;
    const qRows = [
      ['Quarter OpEx', euros(q.total_cost)],
      ['Quarter CapEx', euros(q.purchase)],
      ['Week', `W${String(entry.week).padStart(2, '0')}`],
      ['Carryover', `${w.carryover_in ?? 0} → ${w.carryover_out ?? 0}`],
      ['Robot Wear', `${number(w.wear_start ?? 0)} → ${number(w.wear_end ?? 0)}`],
      ['Commissioning', w.commissioning_active ? 'YES' : 'NO'],
      ['Maintenance', w.maintenance ? 'YES' : 'NO'],
    ];
    $('quarter-summary-box').innerHTML = `
      <table class="cad-table">
        <tbody>
          ${qRows.map(([k, v]) => `<tr><th>${html(k)}</th><td>${html(v)}</td></tr>`).join('')}
        </tbody>
      </table>
    `;
  } else {
    $('quarter-summary-block').hidden = true;
  }

  if (current.length === 2) {
    const ecA = current[0].replay.manifest.economy;
    const ecB = current[1].replay.manifest.economy;
    $('econ-breakdown-box').innerHTML = `
      <table class="cad-table">
        <thead>
          <tr>
            <th>ITEM</th>
            <th>A</th>
            <th>B</th>
            <th>B − A</th>
          </tr>
        </thead>
        <tbody>
          ${Object.entries(costLabels).map(([key, label]) => {
            const a = ecA.costs[key] ?? 0;
            const b = ecB.costs[key] ?? 0;
            const diff = b - a;
            return `
              <tr>
                <td>${html(label)}</td>
                <td>${euros(a)}</td>
                <td>${euros(b)}</td>
                <td>${diff > 0 ? '+' : ''}${euros(diff)}</td>
              </tr>
            `;
          }).join('')}
          <tr class="econ-total">
            <td>SHIFT TOTAL</td>
            <td>${euros(ecA.total)}</td>
            <td>${euros(ecB.total)}</td>
            <td>${ecB.total - ecA.total > 0 ? '+' : ''}${euros(ecB.total - ecA.total)}</td>
          </tr>
          <tr>
            <td>PURCHASE</td>
            <td>${euros(ecA.purchase)}</td>
            <td>${euros(ecB.purchase)}</td>
            <td>${ecB.purchase - ecA.purchase > 0 ? '+' : ''}${euros(ecB.purchase - ecA.purchase)}</td>
          </tr>
        </tbody>
      </table>
    `;
  } else {
    const ec = entry.replay.manifest.economy;
    $('econ-breakdown-box').innerHTML = `
      <table class="cad-table">
        <thead>
          <tr><th>ITEM</th><th>COST</th></tr>
        </thead>
        <tbody>
          ${Object.entries(costLabels).map(([key, label]) => `
            <tr><td>${html(label)}</td><td>${euros(ec.costs[key] ?? 0)}</td></tr>
          `).join('')}
          <tr class="econ-total"><td>SHIFT TOTAL</td><td>${euros(ec.total)}</td></tr>
          <tr><td>PURCHASE</td><td>${euros(ec.purchase)}</td></tr>
        </tbody>
      </table>
    `;
  }
}

function collectCombinedEvents(filterKind = 'all') {
  const list = [];
  current.forEach((item, idx) => {
    const tag = current.length === 2 ? (idx ? 'B' : 'A') : '1';
    for (const ev of item.replay.importantEvents) {
      if (filterKind !== 'all' && ev.kind !== filterKind) continue;
      list.push({
        ...ev,
        runTag: tag,
        playerIndex: idx,
        seconds: ev.tick * item.replay.tickSeconds,
      });
    }
  });
  list.sort((a, b) => a.seconds - b.seconds || a.playerIndex - b.playerIndex);
  return list;
}

function renderEventsTab() {
  const filter = $('sel-tab-ev-filter').value || 'all';
  const events = collectCombinedEvents(filter);
  const box = $('events-list-box');
  if (!events.length) {
    box.innerHTML = `<div class="mistake-empty">No events.</div>`;
  } else {
    box.innerHTML = events.slice(0, 120).map((ev, i) => {
      const crit = ['jam', 'escaped', 'scrap'].includes(ev.kind);
      return `
        <div class="mistake-card ${crit ? 'critical' : ''}" data-ev-idx="${i}">
          <div class="mc-top">
            <span>[${ev.runTag}] TICK ${ev.tick} (${duration(ev.seconds)}) · ${(importantLabels[ev.kind] || ev.kind).toUpperCase()}</span>
            <span class="${crit ? 'mc-imp' : ''}">${ev.orderId != null ? '#' + ev.orderId : ev.resource?.toUpperCase() || ''}</span>
          </div>
          <div class="mc-txt">
            ${ev.resource ? `${html(ev.resource.toUpperCase())}` : ''}${ev.resource && ev.orderId != null ? ' · ' : ''}${ev.orderId != null ? `Order #${ev.orderId}` : ''}
          </div>
        </div>
      `;
    }).join('');

    box.querySelectorAll('[data-ev-idx]').forEach(card => {
      card.addEventListener('click', () => {
        const ev = events[Number(card.dataset.evIdx)];
        if (!ev) return;
        setPlaying(false);
        setTime(ev.seconds);
        if (ev.orderId != null) {
          selectSceneEntity({ type: 'order', id: ev.orderId }, { fromPlayerIndex: ev.playerIndex });
          players[ev.playerIndex]?.selectEntity?.({ type: 'order', id: ev.orderId });
        }
      });
    });
  }

  const entry = current[activeInspector] || current[0];
  const mistakes = entry?.diagnostics?.key_mistakes || [];
  if (mistakes.length) {
    $('diag-block').hidden = false;
    $('mistakes-box').innerHTML = mistakes.map((m, idx) => `
      <div class="mistake-card ${m.severity === 'critical' ? 'critical' : ''}" data-mistake-idx="${idx}">
        <div class="mc-top">
          <span>W${String(m.week_range?.[0] ?? 0).padStart(2, '0')}–W${String(m.week_range?.[1] ?? 0).padStart(2, '0')}</span>
          <span class="mc-imp">${m.euro_impact_cents ? euros(m.euro_impact_cents) : ''}</span>
        </div>
        <div class="mc-txt">${html(m.hud_callout || '')}</div>
      </div>
    `).join('');

    $('mistakes-box').querySelectorAll('[data-mistake-idx]').forEach(card => {
      card.addEventListener('click', () => {
        const m = mistakes[Number(card.dataset.mistakeIdx)];
        const targetWeek = m?.weeks?.[0] ?? m?.week_range?.[0];
        if (Number.isInteger(targetWeek) && targetWeek !== selectedWeek) {
          selectedWeek = targetWeek;
          loadActiveReplay();
        }
      });
    });
  } else {
    $('diag-block').hidden = true;
  }
}

function renderWeekStrip() {
  const strip = $('week-strip');
  const hlStrip = $('highlight-chips');
  const primary = current[activeInspector] || current[0];

  if (!primary?.quarter) {
    strip.innerHTML = `<div class="single-shift-pill">V1 · S${primary?.run.seed ?? '—'} · ${maxHorizonTicks()} TICKS (${duration(maxDuration())})</div>`;
  } else {
    const diagWeeks = primary.diagnostics?.timeline_weeks || [];
    strip.innerHTML = primary.quarter.weeks.map((w, idx) => {
      const dw = diagWeeks[idx];
      const crit = dw?.status === 'critical' || (w.carryover_out ?? 0) > 10;
      const costText = dw?.metrics?.week_cost_cents != null
        ? euros(dw.metrics.week_cost_cents)
        : `${w.carryover_in ?? 0}→${w.carryover_out ?? 0}`;
      return `
        <button type="button" class="wk-cell ${idx === selectedWeek ? 'active' : ''} ${crit ? 'critical' : ''}" data-week="${idx}">
          <div class="wk-top">
            <span>W${String(idx).padStart(2, '0')}</span>
            <span>${w.maintenance ? 'MNT' : w.commissioning_active ? 'INIT' : ''}</span>
          </div>
          <div class="wk-bot">${html(costText)}</div>
        </button>
      `;
    }).join('');

    strip.querySelectorAll('[data-week]').forEach(btn => {
      btn.addEventListener('click', () => {
        const wk = Number(btn.dataset.week);
        if (wk === selectedWeek) return;
        selectedWeek = wk;
        loadActiveReplay();
      });
    });
  }

  const keyEvents = collectCombinedEvents('all').filter(e => ['jam', 'escaped', 'scrap', 'rework', 'assist'].includes(e.kind));
  hlStrip.hidden = !keyEvents.length;
  if (keyEvents.length) {
    hlStrip.innerHTML = keyEvents.slice(0, 14).map((ev, idx) => {
      const crit = ['jam', 'escaped', 'scrap'].includes(ev.kind);
      return `<button type="button" class="hl-chip ${crit ? 'critical' : ''}" data-hl="${idx}">[${ev.runTag}] T${ev.tick} ${html(importantLabels[ev.kind] || ev.kind)}${ev.orderId != null ? ' #' + ev.orderId : ''}</button>`;
    }).join('');

    hlStrip.querySelectorAll('[data-hl]').forEach(btn => {
      btn.addEventListener('click', () => {
        const ev = keyEvents[Number(btn.dataset.hl)];
        if (!ev) return;
        setPlaying(false);
        setTime(ev.seconds);
        if (ev.orderId != null) {
          selectSceneEntity({ type: 'order', id: ev.orderId }, { fromPlayerIndex: ev.playerIndex });
          players[ev.playerIndex]?.selectEntity?.({ type: 'order', id: ev.orderId });
        }
      });
    });
  } else {
    hlStrip.innerHTML = '';
  }
}

function renderScrubberMarkers() {
  const wrap = $('scrubber-markers');
  const horizon = maxHorizonTicks();
  const events = collectCombinedEvents('all').filter(e => ['jam', 'escaped', 'scrap', 'rework'].includes(e.kind));
  wrap.innerHTML = events.slice(0, 80).map(ev => {
    const pct = Math.min(99.8, Math.max(0.2, (ev.tick / horizon) * 100));
    const crit = ['jam', 'escaped', 'scrap'].includes(ev.kind);
    return `<i class="scrub-tick ${crit ? 'crit' : ''}" style="left:${pct.toFixed(2)}%"></i>`;
  }).join('');
}

async function openCatalogUrl(url) {
  setPlaying(false);
  toast('Connecting...');
  try {
    source = await openRemote(url);
    populateSelectorsForSource();
    updateModeUI();
    await loadActiveReplay();
  } catch (error) {
    console.error(error);
    toast('ERROR: ' + (error.message || error), true);
  }
}

async function acceptLocalFiles(fileList) {
  setPlaying(false);
  try {
    source = await openLocal(fileList);
    populateSelectorsForSource();
    updateModeUI();
    await loadActiveReplay();
  } catch (error) {
    toast('ERROR: ' + (error.message || error), true);
  }
}

// Wire UI Controls
$('btn-mode-single').addEventListener('click', () => {
  if (mode === 'single') return;
  mode = 'single';
  updateModeUI();
  loadActiveReplay();
});

$('btn-mode-compare').addEventListener('click', () => {
  if (mode === 'compare') return;
  mode = 'compare';
  updateModeUI();
  loadActiveReplay();
});

$('sel-source').addEventListener('change', async e => {
  const val = e.target.value;
  if (val === 'custom') {
    const customUrl = prompt('index.json URL:', 'http://127.0.0.1:8841/index.json');
    if (!customUrl) {
      e.target.value = './pack/index.json';
      return;
    }
    await openCatalogUrl(customUrl);
  } else {
    await openCatalogUrl(val);
  }
});

$('sel-seed').addEventListener('change', () => {
  refreshFilteredRunSelectors(true);
  loadActiveReplay();
});

$('sel-run').addEventListener('change', () => loadActiveReplay());

$('sel-comparison').addEventListener('change', () => {
  const pair = source?.index.comparisons.find(c => c.id === $('sel-comparison').value);
  if (pair) {
    refreshFilteredRunSelectors(false);
    $('sel-run-a').value = pair.left;
    $('sel-run-b').value = pair.right;
  }
  loadActiveReplay();
});

for (const id of ['sel-run-a', 'sel-run-b']) {
  $(id).addEventListener('change', () => {
    const a = $('sel-run-a').value;
    const b = $('sel-run-b').value;
    const match = source?.index.comparisons.find(c => c.left === a && c.right === b);
    $('sel-comparison').value = match ? match.id : '__custom__';
    loadActiveReplay();
  });
}

document.querySelectorAll('[data-cam]').forEach(btn => {
  btn.addEventListener('click', () => {
    const target = btn.dataset.cam;
    setCameraPreset(cameraPreset === target ? 'overview' : target);
  });
});

$('btn-local-files').addEventListener('click', () => $('file-local').click());
$('btn-local-folder').addEventListener('click', () => $('folder-local').click());
for (const id of ['file-local', 'folder-local']) {
  $(id).addEventListener('change', async e => {
    if (e.target.files?.length) await acceptLocalFiles(e.target.files);
    e.target.value = '';
  });
}

$('toggle-right').addEventListener('click', e => {
  const collapsed = $('workspace').classList.toggle('ledger-collapsed');
  e.currentTarget.classList.toggle('active', !collapsed);
  requestAnimationFrame(() => players.forEach(p => p?.resize()));
});

document.querySelectorAll('#inspector-switch button').forEach(btn => {
  btn.addEventListener('click', () => {
    activeInspector = Number(btn.dataset.inspector);
    updateInspectorSwitch();
    populateOrderPicker();
    renderLedger();
  });
});

for (const [idx, side] of [[0, 'left'], [1, 'right']]) {
  $('panel-' + side).addEventListener('pointerdown', () => {
    if (current.length === 2 && activeInspector !== idx) {
      activeInspector = idx;
      updateInspectorSwitch();
      populateOrderPicker();
      renderLedger();
    }
  });
}

document.querySelectorAll('.ledger-tabs .tab-btn').forEach(btn => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

$('sel-order-pick').addEventListener('change', e => {
  const val = e.target.value;
  if (!val) {
    selectSceneEntity(null);
    players.forEach(p => p?.clearSelection?.());
  } else {
    const entity = { type: 'order', id: Number(val) };
    selectSceneEntity(entity);
    players.forEach(p => p?.selectEntity?.(entity));
  }
});

$('btn-clear-sel').addEventListener('click', () => {
  $('sel-order-pick').value = '';
  selectSceneEntity(null);
  players.forEach(p => p?.clearSelection?.());
});

$('sel-tab-ev-filter').addEventListener('change', () => renderEventsTab());

// Transport controls
$('btn-play').addEventListener('click', () => {
  if (time >= maxDuration()) setTime(0);
  setPlaying(!playing);
});
$('btn-reset').addEventListener('click', () => {
  setPlaying(false);
  setTime(0);
});
$('btn-step-back').addEventListener('click', () => {
  setPlaying(false);
  setTime(time - tickSeconds());
});
$('btn-step-fwd').addEventListener('click', () => {
  setPlaying(false);
  setTime(time + tickSeconds());
});
$('sel-speed').addEventListener('change', e => {
  speed = Number(e.target.value) || 15;
});
$('tick-scrubber').addEventListener('input', e => {
  setPlaying(false);
  setTime(Number(e.target.value) * tickSeconds());
});
$('btn-next-event').addEventListener('click', () => {
  const filter = $('sel-event-filter').value;
  const next = collectCombinedEvents(filter).find(ev => ev.seconds > time + 1e-6);
  setPlaying(false);
  if (next) {
    setTime(next.seconds);
    toast(`[${next.runTag}] ${importantLabels[next.kind] || next.kind} · TICK ${next.tick}${next.orderId != null ? ' · #' + next.orderId : ''}`);
    if (next.orderId != null) {
      selectSceneEntity({ type: 'order', id: next.orderId }, { fromPlayerIndex: next.playerIndex });
      players[next.playerIndex]?.selectEntity?.({ type: 'order', id: next.orderId });
    }
  } else {
    toast('No further matching events');
  }
});

// Keyboard shortcuts
document.addEventListener('keydown', event => {
  if (['INPUT', 'SELECT', 'TEXTAREA', 'BUTTON'].includes(event.target.tagName) || !current.length) return;
  if (event.code === 'Space') {
    event.preventDefault();
    if (time >= maxDuration()) setTime(0);
    setPlaying(!playing);
  } else if (event.key === 'ArrowRight') {
    event.preventDefault();
    setPlaying(false);
    setTime(time + tickSeconds() * (event.shiftKey || event.ctrlKey ? 10 : 1));
  } else if (event.key === 'ArrowLeft') {
    event.preventDefault();
    setPlaying(false);
    setTime(time - tickSeconds() * (event.shiftKey || event.ctrlKey ? 10 : 1));
  } else if (event.key === 'Home') {
    event.preventDefault();
    setPlaying(false);
    setTime(0);
  } else if (event.key === 'End') {
    event.preventDefault();
    setPlaying(false);
    setTime(maxDuration());
  }
});

// Drag & Drop local replay files
let dragDepth = 0;
document.addEventListener('dragenter', e => {
  if (e.dataTransfer?.types?.includes('Files')) {
    dragDepth++;
    document.body.classList.add('drop-active');
  }
});
document.addEventListener('dragleave', () => {
  if (--dragDepth <= 0) {
    dragDepth = 0;
    document.body.classList.remove('drop-active');
  }
});
document.addEventListener('dragover', e => e.preventDefault());
document.addEventListener('drop', async e => {
  e.preventDefault();
  dragDepth = 0;
  document.body.classList.remove('drop-active');
  if (e.dataTransfer?.files?.length) {
    await acceptLocalFiles(e.dataTransfer.files);
  }
});

window.addEventListener('resize', () => players.forEach(p => p?.resize()));
window.addEventListener('beforeunload', () => {
  disposed = true;
  disposeAllPlayers();
});

let lastFrame = performance.now();
function animate(now) {
  if (disposed) return;
  const delta = Math.min(0.25, (now - lastFrame) / 1000);
  lastFrame = now;
  if (playing && !loading) {
    time = Math.min(maxDuration(), time + delta * speed);
    if (time >= maxDuration()) setPlaying(false);
  }
  paint();
  for (let i = 0; i < current.length; i++) {
    if (players[i] && snapshots[i]) {
      players[i].render(snapshots[i], { playing, speed, deltaSeconds: delta });
    }
  }
  requestAnimationFrame(animate);
}

// Read-only QA & automation handle
window.replayStudio = {
  get source() { return source?.index; },
  get states() { return snapshots; },
  get time() { return time; },
  get mode() { return mode; },
  get stats() { return panelStats; },
  get replays() { return current.map(i => i.replay); },
  get players() { return players; },
  seekTo: setTime,
  pause: () => setPlaying(false),
  play: () => setPlaying(true),
  setCameraPreset,
  selectEntity: entity => {
    selectSceneEntity(entity, { openSceneTab: true });
    players.forEach(p => p?.selectEntity?.(entity));
  },
};

// Boot
syncCameraButtons();
buildSceneLayersUI();
updateModeUI();
requestAnimationFrame(animate);

const initialUrl = query.get('index') || $('sel-source').value;
openCatalogUrl(initialUrl).then(() => {
  if (!source && !query.get('index') && initialUrl === './3d-pack/index.json') {
    const fallbackUrl = 'http://127.0.0.1:8765/index.json';
    $('sel-source').value = fallbackUrl;
    return openCatalogUrl(fallbackUrl);
  }
});
