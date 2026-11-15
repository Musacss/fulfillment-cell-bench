#!/usr/bin/env node
// Independent player acceptance tests. No production events or simulator code are changed.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {createReplay} from '../studio/src/replay.js';
import {actorPosition,benchPosition,breakPosition,planWalkPath,segmentHitsObstacle,DEFAULT_OBSTACLES,queueStackPositions,outcomeStackPositions,buildWorkerPresentationPlan} from '../studio/src/spatial.js';
import {setRobotAndonState} from '../4_Horses_Environment_v02/visual/environment-layers.js';
import {openLocal,openRemote,parseDocument,validateQuarter} from '../studio/src/data.js';

const ROOT=fileURLToPath(new URL('../',import.meta.url));
const pack=path.resolve(ROOT,process.argv[2]||'artifacts/3d-pack');
const fixtureRoot=path.join(ROOT,'artifacts/replay-player-fixtures');
const rawFields=['good','on_time','escaped','scrap','unfinished','pack_started','pack_finished','auto_finished','trays_used','rework_started','labor_ticks','overtime_ticks'];
const numericFields=rawFields.filter(k=>k!=='overtime_ticks');
const terminal=new Set(['good','escaped','scrap']);
const clone=value=>JSON.parse(JSON.stringify(value));
const near=(actual,expected,label)=>assert.ok(Math.abs(actual-expected)<1e-8,`${label}: ${actual} !== ${expected}`);
const readJSON=async file=>JSON.parse(await fs.readFile(file,'utf8'));
const jsonl=events=>events.map(e=>JSON.stringify(e)).join('\n')+'\n';

function command(executable,args,label){
 const result=spawnSync(executable,args,{cwd:ROOT,encoding:'utf8',env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});
 assert.equal(result.status,0,`${label} failed (${result.status}):\n${result.stdout}\n${result.stderr}`);
 return result.stdout;
}
command(path.join(ROOT,'.venv/bin/python'),['scripts/generate_player_fixtures.py'],'isolated engine fixtures');

async function bundle(directory,id=path.basename(directory)){
 const manifest=await readJSON(path.join(directory,'manifest.json'));
 const text=await fs.readFile(path.join(directory,manifest.events_file),'utf8');
 const events=text.trim().split('\n').map(line=>JSON.parse(line));
 return {id,manifest,text,events,player:createReplay(manifest,text,{runId:id})};
}

// This oracle only folds the public trace prefix. It does not call the reducer or
// trust manifest.raw. It checks the moving labour totals as well as final counts.
function prefixOracle(data,tick){
 const {manifest,events}=data;
 const H=manifest.world.clock.shift_ticks+manifest.world.clock.overtime_ticks;
 const t=Math.max(0,Math.min(H,tick));
 const out=Object.fromEntries(numericFields.map(k=>[k,0]));
 out.overtime_ticks=manifest.plan.workers.map(()=>0);
 const queues={Q1:[],Q2:[],Q3:[],Q4:[],R:[]};
 const reserved={Q2:0,Q3:0,Q4:0};
 const byId=new Map(manifest.scenario.orders.map(o=>[o.id,o]));
 for(const e of events){
  if(e.tick>Math.floor(t))break;
  if(e.kind==='enqueue')queues[e.stage===3&&e.attempt===1?'R':'Q'+e.stage].push(e.order_id);
  if(e.kind==='start'){
   const queue=queues[e.stage===3&&e.attempt===1?'R':'Q'+e.stage];
   const index=queue.indexOf(e.order_id);assert.ok(index>=0,'Oracle trace contains a start without queue');queue.splice(index,1);
   if(e.stage<4)reserved['Q'+(e.stage+1)]++;
   if(e.stage===3){out.pack_started++;out.trays_used+=Number(manifest.plan.trays&&e.attempt===0);out.rework_started+=Number(e.attempt===1);}
  }
  if(e.kind==='finish'&&e.stage<4){
   reserved['Q'+(e.stage+1)]--;
   if(e.stage===3){out.pack_finished++;out.auto_finished+=Number(e.resource==='robot');}
  }
  if(terminal.has(e.kind)){out[e.kind]++;if(e.kind==='good'&&e.tick<=byId.get(e.order_id).due)out.on_time++;}
  if(['start','assist'].includes(e.kind)&&/^w\d+$/.test(e.resource)){
   const worked=Math.max(0,Math.min(H,t,e.end_tick)-e.tick);
   out.labor_ticks+=worked;
   const wi=Number(e.resource.slice(1));
   out.overtime_ticks[wi]=Math.max(out.overtime_ticks[wi],Math.max(0,Math.min(H,t,e.end_tick)-manifest.world.clock.shift_ticks));
  }
 }
 if(t>=H)out.unfinished=manifest.scenario.orders.length-out.good-out.escaped-out.scrap;
 return {counters:out,queues,reserved};
}

function checkSnapshot(data,state,tick){
 const {counters,queues,reserved}=prefixOracle(data,tick);
 for(const key of numericFields)near(state.counters[key],counters[key],`${data.id} tick ${tick} ${key}`);
 assert.deepEqual(state.counters.overtime_ticks,counters.overtime_ticks,`${data.id} overtime at ${tick}`);
 assert.deepEqual(state.queues,queues,`${data.id} queue order at ${tick}`);
 assert.deepEqual(state.reserved,reserved,`${data.id} reservations at ${tick}`);
 const waiting=Object.values(state.queues).flat();
 assert.equal(new Set(waiting).size,waiting.length,'An order is waiting in multiple queues');
 for(const [q,k] of [['Q2','pick'],['Q3','pack'],['Q4','qc']]){
  assert.ok(state.queues[q].length+state.reserved[q]<=data.manifest.world.capacity[k],`${q} exceeded capacity`);
  assert.ok(state.reserved[q]>=0,'Negative reservation');
 }
 const orderEntries=Object.entries(state.orders);
 assert.equal(orderEntries.length,data.manifest.scenario.orders.length,'Order table size changed');
 for(const [id,order] of orderEntries){
  if(order.queue)assert.ok(state.queues[order.queue].includes(order.id??Number(id)),'Queue ownership mismatch');
  if(order.resource==='robot')assert.equal(state.robot.orderId,order.id??Number(id),'Robot order ownership mismatch');
 }
 return state;
}

function checkDeterminism(data){
 const {player,events,manifest}=data;
 const H=player.horizonTicks, seconds=player.tickSeconds;
 const times=new Set([0,H,...[200,750,455,990,1080].filter(t=>t<=H)]);
 for(let tick=0;tick<=H;tick++)times.add(tick);
 for(const e of events){
  if(['jam','assist','walk','break'].includes(e.kind)||(e.kind==='enqueue'&&e.attempt===1)){
   for(const base of [e.tick,e.end_tick])if(base!==null&&base!==undefined){
    for(const delta of [-.25,0,.25])if(base+delta>=0&&base+delta<=H)times.add(base+delta);
   }
  }
 }
 const snapshots=new Map();
 const sequential=createReplay(manifest,data.text,{runId:data.id});
 for(const t of [...times].sort((a,b)=>a-b)){
  const state=checkSnapshot(data,sequential.seekTo(t*seconds),t);
  snapshots.set(t,clone(state));
 }
 // Required arbitrary back/forward jumps, then a deterministic scrambled sample.
 const jumpTimes=[200,750,455,990,0,1080].filter(t=>t<=H);
 const scrambled=[...times].filter((_,i)=>i%19===0).sort((a,b)=>((a*79)%113)-((b*79)%113));
 for(const t of [...jumpTimes,...scrambled,H,0,H])assert.deepEqual(player.seekTo(t*seconds),snapshots.get(t),`${data.id} seek determinism at ${t}`);
 const final=player.seekTo(player.durationSeconds);
 for(const key of rawFields)assert.deepEqual(final.counters[key],manifest.raw[key],`${data.id} final ${key}`);
 assert.equal(final.counters.good+final.counters.escaped+final.counters.scrap+final.counters.unfinished,manifest.raw.total,'Final order conservation');
 // Returned snapshots are not a writable live handle into a subsequent seek.
 const mutated=player.seekTo(0);try{mutated.queues.Q1.push(99999);}catch{}
 assert.deepEqual(player.seekTo(0),snapshots.get(0),'Consumer mutation corrupted replay');
 const initial=snapshots.get(0);
 for(const [id,w] of Object.entries(initial.workers))if(!w.activity)assert.equal(w.zone,manifest.plan.workers[Number(id.slice(1))][0]);
 return {run:data.id,seed:manifest.scenario.seed,horizon:H,event_lines:events.length,snapshots:times.size,final_counters:final.counters};
}

function expectError(manifest,text,label,{line=true}={}){
 let error;try{createReplay(clone(manifest),text,{runId:'malformed'});}catch(e){error=e;}
 assert.ok(error,`${label}: malformed input was accepted`);
 assert.ok(typeof error.message==='string'&&error.message.length>8,`${label}: missing explanation`);
 if(line)assert.ok(/line|строк|JSONL/i.test(error.message)||Number.isInteger(error.line),`${label}: error lacks line number: ${error.message}`);
 return {case:label,message:error.message};
}

const actual=[];
for(const seed of [11,29,47])for(const role of ['manual','candidate','reference'])actual.push(await bundle(path.join(pack,`v1-${role}-seed${seed}`)));
const runs=actual.map(checkDeterminism);
const fixtures=[];
for(const name of (await fs.readdir(fixtureRoot)).sort())if(name.startsWith('test-'))fixtures.push(await bundle(path.join(fixtureRoot,name)));
const fixtureResults=fixtures.map(checkDeterminism);
const get=name=>fixtures.find(f=>f.id===name);
const at=(data,tick)=>data.player.seekTo(tick*data.player.tickSeconds);

// Hand-worked 27/28 tick references and half-open walking intervals.
const one=get('test-one-order-h28');
for(const [tick,state] of [[0,'prepare'],[3,'walk'],[4.999,'walk'],[5,'pick'],[10,'walk'],[12,'pack'],[23,'walk'],[25,'inspect']])assert.equal(at(one,tick).workers.w0.state,state,`Manual reference ${tick}`);
assert.equal(at(one,28).counters.good,1);assert.equal(at(get('test-one-order-h27'),27).counters.unfinished,1);
assert.equal(at(get('test-one-order-h27'),27).counters.pack_finished,1);

const jam=get('test-jam-h32');
assert.equal(at(jam,12).workers.w0.state,'break');
assert.equal(at(jam,13).robot.state,'jammed');
assert.equal(at(jam,16.999).workers.w0.state,'break');
assert.equal(at(jam,17).workers.w0.state,'walk');
assert.equal(at(jam,17).robot.state,'helper_walking');
assert.equal(at(jam,19).workers.w0.state,'assist');
assert.equal(at(jam,19).robot.state,'service');
for(const tick of [13,17,18.99,19,26.999]){
 const state=at(jam,tick);assert.equal(state.robot.orderId,0);assert.equal(state.orders[0].resource,'robot');assert.equal(state.reserved.Q4,1);assert.equal(state.counters.auto_finished,0);
}
assert.equal(at(jam,27).counters.auto_finished,1);assert.equal(at(jam,27).workers.w0.state,'walk');assert.equal(at(jam,32).counters.good,1);
assert.equal(at(get('test-jam-h22'),22).counters.unfinished,1);assert.equal(at(get('test-jam-h22'),22).counters.auto_finished,0);
assert.equal(at(get('test-jam-h27'),27).counters.unfinished,1);assert.equal(at(get('test-jam-h27'),27).counters.auto_finished,1);
const scrap=get('test-rework-scrap'), escaped=get('test-defect-escaped');
assert.equal(at(scrap,scrap.player.horizonTicks).counters.scrap,1);assert.equal(at(scrap,scrap.player.horizonTicks).counters.trays_used,1);assert.equal(at(scrap,scrap.player.horizonTicks).counters.rework_started,1);
assert.equal(at(escaped,escaped.player.horizonTicks).counters.escaped,1);assert.equal(at(escaped,escaped.player.horizonTicks).counters.rework_started,0);
const disabled=get('test-purchased-disabled');assert.equal(at(disabled,0).robot.state,'disabled');assert.equal(at(disabled,disabled.player.horizonTicks).counters.trays_used,1);
const playbackRates=[1,5,20,60,100];
for(const data of [actual.find(r=>r.id==='v1-candidate-seed29'),jam])for(const speed of playbackRates){
 const replay=createReplay(data.manifest,data.text,{runId:data.id});let time=0,state=replay.seekTo(0);
 // Coarse render steps deliberately skip many trace events. A paused redraw
 // repeats the same instant; neither operation may advance production itself.
 while(time<replay.durationSeconds){
  assert.deepEqual(replay.seekTo(time),state,'Paused redraw changed production');
  time=Math.min(replay.durationSeconds,time+60*speed);state=replay.seekTo(time);
 }
 for(const key of rawFields)assert.deepEqual(state.counters[key],data.manifest.raw[key],`${data.id} final at ${speed}x with dropped frames`);
}

const malformed=[];
const base=one.manifest, events=one.events;
malformed.push(expectError({...base,replay_format:'robotization-bench.replay.v999'},one.text,'unknown replay format',{line:false}));
let changed=clone(events);changed[0].kind='unknown';malformed.push(expectError(base,jsonl(changed),'unknown event kind'));
changed=clone(events);const decreaseIndex=changed.findIndex((e,i)=>i>0&&changed[i-1].tick>0&&e.tick>changed[i-1].tick);changed[decreaseIndex].tick=changed[decreaseIndex-1].tick-1;malformed.push(expectError(base,jsonl(changed),'decreasing event tick'));
changed=clone(events);changed[0].order_id=123456;malformed.push(expectError(base,jsonl(changed),'missing order'));
changed=clone(events);changed.find(e=>e.kind==='start').resource='w999';malformed.push(expectError(base,jsonl(changed),'missing resource'));
changed=clone(events);changed.find(e=>e.kind==='start').stage=4;malformed.push(expectError(base,jsonl(changed),'illegal order transition'));
malformed.push(expectError(base,one.text.trimEnd().slice(0,-8),'truncated JSON object'));
malformed.push(expectError(base,jsonl(events.slice(0,-1)),'missing complete trailing event'));
changed=clone(events);changed.push(clone(events.at(-1)));malformed.push(expectError(base,jsonl(changed),'duplicate terminal outcome'));
changed=clone(events);const walkIndex=changed.findIndex(e=>e.kind==='walk');changed.splice(walkIndex,1);malformed.push(expectError(base,jsonl(changed),'missing required walking subactivity'));

// Data shared by two displays stays immutable and run identity stays separate.
const sharedManifest=clone(actual[0].manifest), sharedText=actual[0].text, before=JSON.stringify(sharedManifest);
const left=createReplay(sharedManifest,sharedText,{runId:'left'}),right=createReplay(sharedManifest,sharedText,{runId:'right'});
left.seekTo(left.durationSeconds);assert.equal(right.seekTo(0).runId,'right');assert.equal(left.seekTo(0).runId,'left');assert.equal(JSON.stringify(sharedManifest),before,'Loader mutated manifest');

// Browser File inputs can be exercised without a browser. Both a flat pair and
// a complete directory tree must resolve the exact exported relative paths.
const browserFile=(relative,text)=>({name:relative.split('/').at(-1),webkitRelativePath:relative.includes('/')?relative:'',text:async()=>text});
const localSingle=await openLocal([browserFile('manifest.json',JSON.stringify(one.manifest)),browserFile('events.jsonl',one.text)]);
const openedSingle=await localSingle.loadRun(localSingle.index.runs[0]);
assert.equal(openedSingle.replay.seekTo(openedSingle.replay.durationSeconds).counters.good,1);
const index=await readJSON(path.join(pack,'index.json'));
const fileRecords=[['pack/index.json',JSON.stringify(index)]];
for(const data of actual)fileRecords.push([`pack/${data.id}/manifest.json`,JSON.stringify(data.manifest)],[`pack/${data.id}/events.jsonl`,data.text]);
const localCatalog=await openLocal(fileRecords.map(([name,text])=>browserFile(name,text)));
assert.equal(localCatalog.index.runs.filter(r=>r.mode==='v1').length,9);
assert.ok(localCatalog.index.runs.length>=9);
const comparison=await localCatalog.loadComparison(localCatalog.index.comparisons[0]);
assert.equal(comparison[0].replay.manifest.scenario.seed,comparison[1].replay.manifest.scenario.seed);
assert.notEqual(comparison[0].replay.runId,comparison[1].replay.runId);
assert.deepEqual(comparison[0].evaluationSeeds,index.evaluation_seeds);

// A labelled synthetic quarter tests the v2 container with twelve unchanged v1
// shift bundles. It is not a claimed result of an unavailable quarterly engine.
const quarter={replay_pack_format:'robotization-bench.quarter-pack.v1',seed:99,evaluation_seeds:[99],carryover:{backlog:0},wear:{current:12},commissioning:{week:2},maintenance:{visits:1},weeks:Array.from({length:12},(_,week)=>({week,week_seed:one.manifest.scenario.seed,bundle_dir:`weeks/week-${String(week).padStart(2,'0')}`}))};
const quarterFiles=[browserFile('quarter/quarter_manifest.json',JSON.stringify(quarter))];
for(const week of quarter.weeks)quarterFiles.push(browserFile(`quarter/${week.bundle_dir}/manifest.json`,JSON.stringify(one.manifest)),browserFile(`quarter/${week.bundle_dir}/events.jsonl`,one.text));
const quarterSource=await openLocal(quarterFiles);
assert.equal(quarterSource.index.quarterly_available,true);
const weekIdentities=new Set();
for(let week=0;week<12;week++){
 const loaded=await quarterSource.loadRun('local-quarter',{week});
 assert.equal(loaded.week,week);assert.equal(loaded.quarter.wear.current,12);assert.equal(loaded.replay.seekTo(loaded.replay.durationSeconds).counters.good,1);weekIdentities.add(loaded.replay.runId);
}
assert.equal(weekIdentities.size,12,'Different weeks must use different run identities');
assert.throws(()=>validateQuarter({...quarter,replay_pack_format:'unknown'},'quarter_manifest.json'),/replay_pack_format/);
assert.throws(()=>parseDocument('{\n "a": }','broken.json'),/строка|line/i);
await assert.rejects(()=>openLocal([browserFile('manifest.json',JSON.stringify(one.manifest))]).then(source=>source.loadRun('local-shift')),/events\.jsonl/);

const originalFetch=globalThis.fetch;const fetchOptions=[];const fetchedUrls=[];
try{
 const responses=new Map(fileRecords.map(([name,text])=>['http://bridge.test/'+name.replace(/^pack\//,''),text]));
 globalThis.fetch=async(url,options)=>{fetchedUrls.push(String(url));fetchOptions.push(options);const text=responses.get(String(url));return {ok:text!==undefined,status:text===undefined?404:200,text:async()=>text};};
 const remote=await openRemote('http://bridge.test/index.json');
 const remoteRun=await remote.loadRun('v1-manual-seed11');
 assert.equal(remoteRun.replay.seekTo(remoteRun.replay.durationSeconds).counters.good,166);
 assert.ok(fetchOptions.length>=3);
 assert.ok(fetchOptions.every(options=>!options.headers&&Object.keys(options).every(k=>k==='signal')),'Bridge requests must not send unsupported custom CORS headers');
}finally{globalThis.fetch=originalFetch;}

// Regression coverage for v2 quarterly diagnostics loading:
// 1) Standalone quarter_manifest.json (diagnostics_version: 1 + diagnostics_file: "diagnostics.md", no diagnostics.json)
//    must synthesize overall.win / feasible / timeline_weeks cleanly and never parse diagnostics.md as JSON.
// 2) External diagnostics.json (robotization-bench.quarter-diagnostics.v1) must take precedence over embedded
//    quarter.diagnostics in both openLocal and openRemote.
const badgeOf=diag=>diag?.overall?.win?'WIN':diag?.overall?.feasible?'NO WIN':'FAIL';
const embeddedSummaryQuarter={
 ...quarter,
 evaluation:{valid:true,feasible:true,win:true,reward_num:7,reward_den:20,reasons:[]},
 diagnostics_file:'diagnostics.md',
 diagnostics:{
  diagnostics_version:1,
  seed:99,
  quarter_summary:{feasible:true,win:true,reasons:[],headline:'Standalone quarter summary [WIN]'},
  weeks:Array.from({length:12},(_,w)=>({week:w,label:`w${w}`,status:w===8?'critical':'ok',issues:w===8?[{category:'sla',severity:'critical',message:'Week 8 SLA pressure'}]:[]})),
 },
};
const standaloneQuarterFiles=[
 browserFile('quarter/quarter_manifest.json',JSON.stringify(embeddedSummaryQuarter)),
 browserFile('quarter/diagnostics.md','# Non-JSON Markdown diagnostics\n'),
 ...quarter.weeks.flatMap(w=>[
  browserFile(`quarter/${w.bundle_dir}/manifest.json`,JSON.stringify(one.manifest)),
  browserFile(`quarter/${w.bundle_dir}/events.jsonl`,one.text),
 ]),
];
const standaloneLocal=await openLocal(standaloneQuarterFiles);
const standaloneWeek8=await standaloneLocal.loadRun('local-quarter',{week:8});
assert.equal(standaloneWeek8.diagnostics?.overall?.win,true,'Standalone quarter_manifest fallback must preserve win=true');
assert.equal(standaloneWeek8.diagnostics?.overall?.feasible,true,'Standalone quarter_manifest fallback must preserve feasible=true');
assert.equal(badgeOf(standaloneWeek8.diagnostics),'WIN');
assert.equal(standaloneWeek8.diagnostics?.overall?.reward_fraction,'7/20');
assert.equal(standaloneWeek8.weekDiagnostics?.status,'critical');
assert.deepEqual(standaloneWeek8.weekDiagnostics?.active_mistakes,['Week 8 SLA pressure']);

const overlayDiagnostics={
 diagnostics_format:'robotization-bench.quarter-diagnostics.v1',
 schema_version:2,
 seed:99,
 overall:{valid:true,feasible:false,win:false,reward_float:0.017836,reward_fraction:'1062/59543',headline_summary:'Overlay infeasible summary'},
 key_mistakes:[{severity:'critical',category:'all_route_wear_blowout',hud_callout:'Wear hit 12/12'}],
 timeline_weeks:Array.from({length:12},(_,w)=>({
  week:w,
  status:w===8?'critical':'ok',
  active_mistakes:w===8?['Overlay week 8 callout']:[],
  highlight_ticks:w===8?[{kind:'jam',start_tick:442,end_tick:488,focus_tick:442,reason:'Jam @ 442'}]:[],
 })),
};
const overlayLocal=await openLocal([...standaloneQuarterFiles,browserFile('quarter/diagnostics.json',JSON.stringify(overlayDiagnostics))]);
const overlayWeek8=await overlayLocal.loadRun('local-quarter',{week:8});
assert.equal(overlayWeek8.diagnostics?.diagnostics_format,'robotization-bench.quarter-diagnostics.v1','External diagnostics.json must not be shadowed by quarter.diagnostics');
assert.equal(badgeOf(overlayWeek8.diagnostics),'FAIL');
assert.equal(overlayWeek8.diagnostics?.key_mistakes?.length,1);
assert.equal(overlayWeek8.weekDiagnostics?.highlight_ticks?.length,1);

const quarterlyTargets=['quarterly-reference-seed11','quarterly-qwen_grpo-seed11','quarterly-manual-seed11','quarterly-qwen_base-seed11','quarterly-naive_ai-seed11'];
const hasQuarterlyPack=quarterlyTargets.every(id=>index.runs.some(r=>r.id===id));
if(hasQuarterlyPack){
 const mdRequests=[];
 try{
  globalThis.fetch=async(url,options)=>{
   const rel=decodeURIComponent(new URL(String(url)).pathname).replace(/^\//,'');
   if(rel.endsWith('.md'))mdRequests.push(rel);
   try{const text=await fs.readFile(path.join(pack,rel),'utf8');return {ok:true,status:200,text:async()=>text};}
   catch{return {ok:false,status:404,text:async()=>''};}
  };
  const remotePack=await openRemote('http://pack.local/index.json');
  for(const winId of ['quarterly-reference-seed11','quarterly-qwen_grpo-seed11']){
   const entry=await remotePack.loadRun(winId,{week:8});
   assert.equal(entry.diagnostics?.diagnostics_format,'robotization-bench.quarter-diagnostics.v1',`${winId} must load diagnostics.json`);
   assert.equal(entry.diagnostics?.overall?.win,true,`${winId} overall.win must be true`);
   assert.equal(badgeOf(entry.diagnostics),'WIN',`${winId} badge must be WIN`);
   assert.ok(typeof entry.diagnostics?.overall?.reward_fraction==='string'&&entry.diagnostics.overall.reward_fraction.length>0,`${winId} reward_fraction missing`);
   assert.ok(entry.weekDiagnostics!==null&&entry.weekDiagnostics.week===8,`${winId} weekDiagnostics missing for week 8`);
  }
  for(const noWinId of ['quarterly-manual-seed11','quarterly-qwen_base-seed11']){
   const entry=await remotePack.loadRun(noWinId,{week:8});
   assert.equal(entry.diagnostics?.diagnostics_format,'robotization-bench.quarter-diagnostics.v1',`${noWinId} must load diagnostics.json`);
   assert.equal(entry.diagnostics?.overall?.win,false,`${noWinId} overall.win must be false`);
   assert.equal(entry.diagnostics?.overall?.feasible,true,`${noWinId} overall.feasible must be true`);
   assert.equal(badgeOf(entry.diagnostics),'NO WIN',`${noWinId} badge must be NO WIN`);
  }
  const naiveEntry=await remotePack.loadRun('quarterly-naive_ai-seed11',{week:8});
  assert.equal(naiveEntry.diagnostics?.diagnostics_format,'robotization-bench.quarter-diagnostics.v1');
  assert.equal(naiveEntry.diagnostics?.overall?.feasible,false,'naive_ai overall.feasible must be false');
  assert.equal(badgeOf(naiveEntry.diagnostics),'FAIL','naive_ai badge must be FAIL');
  assert.ok((naiveEntry.diagnostics?.key_mistakes?.length||0)>0,'naive_ai key_mistakes must be non-empty');
  assert.ok(naiveEntry.weekDiagnostics!==null&&naiveEntry.weekDiagnostics.week===8,'naive_ai weekDiagnostics must resolve week 8');
  assert.ok((naiveEntry.weekDiagnostics?.highlight_ticks?.length||0)>0,'naive_ai week 8 highlight_ticks must be non-empty');
  assert.equal(mdRequests.length,0,'openRemote must never fetch .md diagnostics files as JSON');
 }finally{globalThis.fetch=originalFetch;}

 // Exercise openLocal on real exported quarterly bundles (both with diagnostics.json and standalone fallback).
 const localQuarterRecords=[['pack/index.json',JSON.stringify({
  ...index,
  runs:index.runs.filter(r=>['quarterly-qwen_grpo-seed11','quarterly-naive_ai-seed11'].includes(r.id)),
  comparisons:[],
 })]];
 for(const id of ['quarterly-qwen_grpo-seed11','quarterly-naive_ai-seed11']){
  for(const rel of [`${id}/quarter_manifest.json`,`${id}/diagnostics.json`,`${id}/weeks/week-08/manifest.json`,`${id}/weeks/week-08/events.jsonl`]){
   localQuarterRecords.push([`pack/${rel}`,await fs.readFile(path.join(pack,rel),'utf8')]);
  }
 }
 const localQuarterCatalog=await openLocal(localQuarterRecords.map(([name,text])=>browserFile(name,text)));
 const localWin=await localQuarterCatalog.loadRun('quarterly-qwen_grpo-seed11',{week:8});
 assert.equal(localWin.diagnostics?.overall?.win,true);
 assert.ok((localWin.diagnostics?.overall?.reward_fraction||'').length>0);
 const localFail=await localQuarterCatalog.loadRun('quarterly-naive_ai-seed11',{week:8});
 assert.equal(localFail.diagnostics?.overall?.feasible,false);
 assert.ok((localFail.diagnostics?.key_mistakes?.length||0)>0);
 assert.ok((localFail.weekDiagnostics?.highlight_ticks?.length||0)>0);

 const realStandaloneFiles=[
  browserFile('qwen/quarter_manifest.json',await fs.readFile(path.join(pack,'quarterly-qwen_grpo-seed11/quarter_manifest.json'),'utf8')),
  browserFile('qwen/diagnostics.md',await fs.readFile(path.join(pack,'quarterly-qwen_grpo-seed11/diagnostics.md'),'utf8')),
  ...await Promise.all(Array.from({length:12},async(_,w)=>{
   const wdir=`weeks/week-${String(w).padStart(2,'0')}`;
   return [
    browserFile(`qwen/${wdir}/manifest.json`,await fs.readFile(path.join(pack,'quarterly-qwen_grpo-seed11',wdir,'manifest.json'),'utf8')),
    browserFile(`qwen/${wdir}/events.jsonl`,await fs.readFile(path.join(pack,'quarterly-qwen_grpo-seed11',wdir,'events.jsonl'),'utf8')),
   ];
  })).then(rows=>rows.flat()),
 ];
 const realStandaloneSource=await openLocal(realStandaloneFiles);
 const realStandaloneEntry=await realStandaloneSource.loadRun('local-quarter',{week:6});
 assert.equal(realStandaloneEntry.diagnostics?.overall?.win,true,'Real standalone quarter_manifest fallback must resolve overall.win=true');
 assert.equal(realStandaloneEntry.weekDiagnostics?.status,'critical','Real standalone week 6 status must resolve');
}
const dataLoading={offline_pair:true,offline_catalog:true,same_seed_comparison:true,quarterly_v2_weeks:12,quarterly_fixture_is_synthetic:true,quarterly_diagnostics_overlay:true,quarterly_standalone_fallback:true,plain_fetch_cors:true};

const baseline=await readJSON(path.join(ROOT,'4_Horses_Environment_v02/asset_stats_v02.json'));
const records=Array.isArray(baseline)?baseline:(baseline.assets||baseline.files||baseline.glbs);
assert.ok(Array.isArray(records)&&records.length===15,'Expected original fifteen GLB SHA-256 records');
for(const record of records){
 const file=record.file||record.path;const expected=record.sha256;
 assert.ok(file&&expected,'Missing baseline GLB hash');
 const data=await fs.readFile(path.join(ROOT,'4_Horses_Environment_v02',file));
 assert.equal(crypto.createHash('sha256').update(data).digest('hex'),expected,'Existing GLB changed: '+file);
}

// Spatial policies are deliberately separate from the deterministic production
// reducer: display limits never delete orders or change capacities/counters.
const bindings=await readJSON(path.join(ROOT,'4_Horses_Environment_v02/visual_bindings.json'));
const ORDER_SIZES={regular:[.36,.28,.25],fragile:[.36,.28,.25],oversize:[.48,.34,.32]};
const stackOrders=Array.from({length:19},(_,id)=>({id,kind:['regular','fragile','oversize'][id%3]}));
const q1=queueStackPositions(bindings,'Q1',stackOrders);
assert.equal(q1.visibleOrders.length,18,'Q1 may display at most 18 orders on the paired deck');
assert.equal(q1.overflow,1,'Q1 overflow badge must count the hidden order');
assert.equal(q1.positions.length,18);
function checkStack(result,rectangle,label){
 const bounds=result.positions.map((p,i)=>{
  const order=result.visibleOrders[i],box=ORDER_SIZES[order.kind];
  const size=order.tray?[.54,.40,box[2]+.012]:box;
  const b={min:[p[0]-size[0]/2,p[1],p[2]-size[1]/2],max:[p[0]+size[0]/2,p[1]+size[2],p[2]+size[1]/2]};
  assert.ok(b.min[0]>=rectangle[0]-1e-6&&b.max[0]<=rectangle[1]+1e-6&&b.min[2]>=rectangle[2]-1e-6&&b.max[2]<=rectangle[3]+1e-6,`${label}: a displayed box left its physical support`);
  return b;
 });
 for(let i=0;i<bounds.length;i++)for(let j=i+1;j<bounds.length;j++)assert.ok(![0,1,2].every(axis=>bounds[i].max[axis]>bounds[j].min[axis]+1e-6&&bounds[j].max[axis]>bounds[i].min[axis]+1e-6),`${label}: boxes ${i} and ${j} intersect`);
}
checkStack(q1,[-11.64,-9.24,-3.74,-2.88],'Q1');
for(const [kind,rectangle,count] of [['good',[9.4,10.6,-2.6,-1.8],12],['escaped',[9.4,10.6,-4.8,-4],12],['scrap',[6.6,7.8,6.5,7.5],8]]){
 const result=outcomeStackPositions(bindings,kind,stackOrders);
 assert.equal(result.visibleOrders.length,count);assert.equal(result.overflow,stackOrders.length-count);
 assert.deepEqual(result.visibleOrders,stackOrders.slice(-count),'Outcome stack must show the most recent orders');
 checkStack(result,rectangle,kind);
 const trayOrders=stackOrders.map(order=>({...order,tray:true}));
 const trayResult=outcomeStackPositions(bindings,kind,trayOrders);
 assert.equal(trayResult.visibleOrders.length,count);
 checkStack(trayResult,rectangle,kind+' with full .54 x .40 tray');
}
for(const [index,x] of [[0,1.8],[1,.2],[2,-1.4]]){
 const actor=actorPosition(bindings,3,index),bench=benchPosition(bindings,3,index);
 near(actor[0],x,'Stage3 worker X');near(actor[2],-2.05,'Stage3 worker row');near(bench[0],x,'Stage3 bench X');near(bench[2],-2.7,'Stage3 bench row');
}
const rests=Array.from({length:8},(_,i)=>breakPosition(i));
assert.equal(new Set(rests.map(p=>p.join(','))).size,8,'Break positions must be independent');
for(const p of rests)assert.ok(p[0]>=7.4-1e-6&&p[0]<=10.2+1e-6&&p[2]>=-7.1-1e-6&&p[2]<=-6.4+1e-6,'Break slot outside rest island');
const destinations=[...[1,2,3,4].map(stage=>actorPosition(bindings,stage,0)),[2.8,0,-1.95],...rests,[0,0,4.5],[4.5,0,8.1]];
let routeSegments=0;
for(let i=0;i<destinations.length;i++)for(let j=0;j<destinations.length;j++)if(i!==j){
 const from=destinations[i],to=destinations[j],points=planWalkPath(from,to);
 assert.ok(points.length>=2,'Walk route needs at least two points');assert.deepEqual(points[0],from);assert.deepEqual(points.at(-1),to);
 for(let k=1;k<points.length;k++){
  const a=points[k-1],b=points[k];routeSegments++;
  assert.ok(a.every(Number.isFinite)&&b.every(Number.isFinite),'Non-finite walking route');
  for(const obstacle of DEFAULT_OBSTACLES)assert.ok(!segmentHitsObstacle(a,b,obstacle),`Walking route ${i}->${j} crosses ${obstacle.name||JSON.stringify(obstacle)}`);
  if(a[2]*b[2]<0){const f=-a[2]/(b[2]-a[2]),crossX=a[0]+f*(b[0]-a[0]);assert.ok(Math.abs(crossX)>=10.1,'Walk crossed the middle of the conveyor');}
 }
}
const actualTracePaths=[];
for(const data of actual){
 const presentation=buildWorkerPresentationPlan(data.player,bindings);
 const expectedActivities=data.events.filter(e=>/^w\d+$/.test(e.resource||'')&&['start','assist','break'].includes(e.kind));
 assert.equal(presentation.activities.size,expectedActivities.length,`${data.id}: each recorded worker activity needs one presentation path`);
 let segments=0;
 for(const [key,activity] of presentation.activities){
  const points=activity.path;
  assert.ok(points.length>=2,`${data.id} ${key}: missing activity route`);
  assert.deepEqual(points[0],activity.from,`${data.id} ${key}: route start`);
  assert.deepEqual(points.at(-1),activity.to,`${data.id} ${key}: route destination`);
  if(activity.kind==='work'&&activity.stage===3){
   near(activity.to[2],-2.05,`${data.id} ${key}: primary packaging and rework must stay in the north row`);
   near(activity.to[0],1.8-activity.index*1.6,`${data.id} ${key}: linear PACK slot`);
  }
  for(let k=1;k<points.length;k++){
   const a=points[k-1],b=points[k];segments++;
   assert.ok(a.every(Number.isFinite)&&b.every(Number.isFinite),`${data.id} ${key}: non-finite activity path`);
   for(const obstacle of DEFAULT_OBSTACLES)assert.ok(!segmentHitsObstacle(a,b,obstacle),`${data.id} ${key}: activity path crosses ${obstacle.name}`);
   if(a[2]*b[2]<0){const f=-a[2]/(b[2]-a[2]),crossX=a[0]+f*(b[0]-a[0]);assert.ok(Math.abs(crossX)>=10.1,`${data.id} ${key}: activity crossed the conveyor instead of its end`);}
  }
 }
 actualTracePaths.push({run:data.id,activities:presentation.activities.size,segments,max_slots:presentation.maxSlots});
}
const spatial={q1_visible:18,q1_overflow:1,outcome_visible_limits:{good:12,escaped:12,scrap:8},outcome_full_tray_envelopes_clear:true,stage3_linear_benches:3,break_slots:8,walk_routes:destinations.length*(destinations.length-1),collision_free_segments:routeSegments,actual_trace_activities:actualTracePaths.reduce((n,r)=>n+r.activities,0),actual_trace_path_segments:actualTracePaths.reduce((n,r)=>n+r.segments,0),actual_trace_paths:actualTracePaths};
// Exercise all semantic robot states, including mixed-case input and dark lenses.
// Existing check_v02 below separately checks the actual Three.js GLB materials.
const material=()=>({color:{},emissive:{copy(){return this;}},emissiveIntensity:0,clone(){return material();}});
const lenses=Object.fromEntries(['RED','AMBER','GREEN'].map(channel=>['ANDON_'+channel,{isMesh:true,userData:{},material:material()}]));
const andonScene={getObjectByName:name=>lenses[name]};
for(const [state,active] of [['idle','GREEN'],['PACK','GREEN'],['Jammed','RED'],['Service','AMBER'],['off',null],['NOT_PURCHASED',null],['DiSaBlEd',null],['helper_walking','RED'],['finished','GREEN']]){
 setRobotAndonState(andonScene,state);
 for(const [name,node] of Object.entries(lenses)){
  const expected=name==='ANDON_'+active;
  assert.equal(node.userData.active,expected,`Andon ${state} ${name}`);
  near(node.material.emissiveIntensity,expected?1.6:.02,`Andon emissive ${state} ${name}`);
 }
}
assert.throws(()=>setRobotAndonState(andonScene,'unknown'),/Unsupported Andon state/);
command(process.execPath,['4_Horses_Environment_v02/scripts/check_v02.mjs'],'unchanged v02 adapter/asset checks');
const validationText=command(process.execPath,['4_Horses_Environment_v02/scripts/validate_gltf.mjs',
 '4_Horses_Environment_v02/warehouse_environment.glb','4_Horses_Environment_v02/modules/visual_layout.glb','4_Horses_Environment_v02/modules/visual_support.glb','4_Horses_Environment_v02/modules/warehouse_worker.glb','4_Horses_Environment_v02/modules/humanoid_robot.glb'],'unchanged glTF validator');
const validation=JSON.parse(validationText);assert.ok(validation.every(r=>r.errors===0&&r.warnings===0));
command('git',['diff','--exit-code','HEAD','--','src/robotization_bench','data/world_spec.json'],'unchanged checked-out bridge simulator core, scenario generator and prices');

const report={passed:true,real_runs:runs,controlled_test_worlds:fixtureResults,independent_prefix_oracle:true,backward_forward_seek:true,half_open_intervals:true,playback_rates:playbackRates,pause_and_dropped_frames:true,raw_fields:rawFields,malformed_inputs:malformed,composite_run_identity:true,data_loading:dataLoading,original_glb_hashes:15,core_unchanged_from_bridge:true,spatial,andon_all_valid_states:true,existing_v02_checks:true,gltf_validation:validation};
await fs.mkdir(path.join(ROOT,'artifacts/player-check'),{recursive:true});
await fs.writeFile(path.join(ROOT,'artifacts/player-check/report.json'),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify({passed:true,real_runs:runs.length,controlled_test_worlds:fixtureResults.length,snapshots:runs.reduce((n,r)=>n+r.snapshots,0)+fixtureResults.reduce((n,r)=>n+r.snapshots,0),malformed_cases:malformed.length,GLBs_unchanged:15,existing_v02_checks:true,report:'artifacts/player-check/report.json'},null,2));
