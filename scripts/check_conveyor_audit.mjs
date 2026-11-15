#!/usr/bin/env node
// Read-only audit of material-flow events. Never changes source traces or assets.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createReplay,EVENT_KINDS,COUNTER_KEYS} from '../studio/src/replay.js';

const root=fileURLToPath(new URL('../',import.meta.url));
const readJSON=async file=>JSON.parse(await fs.readFile(file,'utf8'));
const queueName=e=>e.stage===3&&e.attempt===1?'R':'Q'+e.stage;

async function audit(directory,id){
  const manifest=await readJSON(path.join(directory,'manifest.json'));
  const body=await fs.readFile(path.join(directory,manifest.events_file),'utf8');
  const replay=createReplay(manifest,body,{runId:id}),events=replay.events;
  const kinds={},queued=new Map(),waits=[],transfers=[];
  const previousByOrder=new Map();
  let maxVisibleR=0,firstVisibleR=null;
  const batchTicks=[...new Set(events.map(e=>e.tick))];
  for(const e of events){
    kinds[e.kind]=(kinds[e.kind]||0)+1;
    if(e.kind==='enqueue'){
      const q=queueName(e),prior=previousByOrder.get(e.order_id);
      queued.set(e.order_id,{queue:q,tick:e.tick});
      if(prior?.kind==='finish'){
        assert.equal(e.tick,prior.tick,'The exported contract requires same-tick transfer');
        transfers.push({fromStage:prior.stage,toQueue:q,deltaTicks:e.tick-prior.tick});
      }
    }
    if(e.kind==='start'){
      const prior=queued.get(e.order_id);
      assert.ok(prior,'start must consume an enqueued order');
      waits.push({orderId:e.order_id,queue:prior.queue,enqueueTick:prior.tick,startTick:e.tick,waitTicks:e.tick-prior.tick});
      queued.delete(e.order_id);
    }
    if(e.order_id!==null&&!['walk','jam','assist'].includes(e.kind))previousByOrder.set(e.order_id,e);
  }
  for(const tick of batchTicks){
    const state=replay.seekTo(tick*replay.tickSeconds);
    if(state.queues.R.length>maxVisibleR)maxVisibleR=state.queues.R.length;
    if(state.queues.R.length&&firstVisibleR===null)firstVisibleR={tick,orderIds:state.queues.R};
  }
  const final=replay.seekTo(replay.durationSeconds);
  for(const key of COUNTER_KEYS)assert.deepEqual(final.counters[key],manifest.raw[key],id+' final '+key);
  const rework=waits.filter(e=>e.queue==='R');
  const reworkEnqueues=events.filter(e=>e.kind==='enqueue'&&queueName(e)==='R');
  const firstRework=rework[0]||null;
  const firstScrap=events.find(e=>e.kind==='scrap');
  if(firstRework){
    const state=replay.seekTo(firstRework.startTick*replay.tickSeconds),order=state.orders[firstRework.orderId];
    assert.equal(order.queue,null);
    assert.equal(order.stage,3);
    assert.equal(order.attempt,1);
    assert.match(order.resource,/^w\d+$/);
  }
  if(firstScrap){
    const state=replay.seekTo(firstScrap.tick*replay.tickSeconds);
    assert.equal(state.orders[firstScrap.order_id].status,'scrap');
    assert.ok(state.outcomes.scrap.includes(firstScrap.order_id));
  }
  const raw=manifest.raw;
  return {
    id,seed:manifest.scenario.seed,route:manifest.plan.route,orders:raw.total,
    tickSeconds:replay.tickSeconds,events:events.length,kinds,
    final:{good:raw.good,escaped:raw.escaped,scrap:raw.scrap,unfinished:raw.unfinished,autoFinished:raw.auto_finished,reworkStarted:raw.rework_started},
    finishToQueueTransfers:transfers.length,allTransfersSameTick:transfers.every(e=>e.deltaTicks===0),
    queueWaits:Object.fromEntries(['Q1','Q2','Q3','Q4','R'].map(q=>{const a=waits.filter(w=>w.queue===q);return [q,{started:a.length,zeroWait:a.filter(w=>w.waitTicks===0).length,positiveWait:a.filter(w=>w.waitTicks>0).length,maxWaitTicks:Math.max(0,...a.map(w=>w.waitTicks))}];})),
    rework:{enqueued:reworkEnqueues.length,started:rework.length,zeroWait:rework.filter(e=>e.waitTicks===0).length,positiveWait:rework.filter(e=>e.waitTicks>0).length,maxVisibleQueued:maxVisibleR,firstVisibleR,firstRework,allWaits:rework},
    firstScrap:firstScrap?{tick:firstScrap.tick,orderId:firstScrap.order_id,attempt:firstScrap.attempt}:null,
  };
}

const index=await readJSON(path.join(root,'artifacts/3d-pack/index.json'));
const real=[];
for(const run of index.runs)real.push(await audit(path.join(root,'artifacts/3d-pack',run.bundle_dir),run.id));
const fixtureRoot=path.join(root,'artifacts/replay-player-fixtures'),controlled=[];
for(const name of (await fs.readdir(fixtureRoot)).sort())controlled.push(await audit(path.join(fixtureRoot,name),name));
const sum=(list,key)=>list.reduce((n,r)=>n+r.final[key],0);
const evidence={
  traceValidationPassed:true,
  scope:'Checks the existing trace contract and its queue/outcome states; does not certify conveyor parcel transport.',
  physicalConveyorTransportImplemented:false,
  parcelsFollowConveyorGeometry:false,
  geometryOrSimulatorModified:false,
  declaredEventKinds:EVENT_KINDS,
  existingRegressionReport:'artifacts/player-check/report.json',
  rendererFindings:{orderPlacement:'Each frame, orders are placed directly at queue slots, fixed work points or outcome stacks.',workerWalk:'Workers interpolate along presentation routes; their order stays at the destination work point.',rollers:'The 200 main rollers rotate in unison from the union of any work start/finish intervals, independent of parcel location.',nominalRollerSurfaceSpeedMetersPerSimulationSecond:.38,rollerRadiusMeters:.025,transferDurationTicks:0,perSegmentOccupancy:false,photoeyeOrStopperLogic:false},
  realSummary:{runs:real.length,orders:real.reduce((n,r)=>n+r.orders,0),good:sum(real,'good'),escaped:sum(real,'escaped'),scrap:sum(real,'scrap'),unfinished:sum(real,'unfinished'),reworkStarted:sum(real,'reworkStarted'),reworkEnqueues:real.reduce((n,r)=>n+r.rework.enqueued,0),reworkZeroWait:real.reduce((n,r)=>n+r.rework.zeroWait,0),reworkPositiveWait:real.reduce((n,r)=>n+r.rework.positiveWait,0),maxVisibleQueuedR:Math.max(...real.map(r=>r.rework.maxVisibleQueued)),finishToQueueTransfers:real.reduce((n,r)=>n+r.finishToQueueTransfers,0)},
  real,controlled,
};
assert.equal(real.length,9);assert.equal(controlled.length,8);
assert.ok(controlled.find(r=>r.id==='test-rework-scrap')?.final.scrap>0);
await fs.writeFile(path.join(root,'artifacts/player-check/conveyor-audit.json'),JSON.stringify(evidence,null,2)+'\n');
console.log(JSON.stringify({traceValidationPassed:true,realSummary:evidence.realSummary,controlledWorlds:controlled.length},null,2));
