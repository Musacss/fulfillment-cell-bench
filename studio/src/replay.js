// The trace is the sole source of production state. No scheduler or random draw
// runs in this module; v2 weeks use this same v1 shift boundary.
export const REPLAY_FORMAT = 'robotization-bench.replay.v1';
export const EVENT_KINDS = Object.freeze(['arrival','enqueue','start','finish','walk','jam','assist','break','good','escaped','scrap']);
export const COUNTER_KEYS = Object.freeze(['total','good','on_time','escaped','scrap','unfinished','pack_started','pack_finished','auto_finished','trays_used','rework_started','labor_ticks','overtime_ticks']);
const EVENT_KEYS=['tick','kind','order_id','resource','stage','attempt','end_tick'];
const COST_KEYS=['depreciation','service','shifts','overtime','trays','materials','rework','late','unfulfilled','escaped'];
const TERMINAL=new Set(['good','escaped','scrap']);
const OPERATION={1:'prepare',2:'pick',3:'pack',4:'inspect'};
const clone=value=>structuredClone(value);
const integer=value=>Number.isSafeInteger(value);
const object=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
const exactKeys=(value,keys)=>object(value)&&same(Object.keys(value).sort(),[...keys].sort());

export class ReplayError extends Error {
  constructor(message,{source='events.jsonl',line=1,code='INVALID_REPLAY'}={}) {
    super(`${source} line ${line}: ${message}`);
    this.name='ReplayError';this.source=source;this.line=line;this.code=code;
  }
}
function fail(message,line=1,source='events.jsonl',code) {throw new ReplayError(message,{source,line,code});}
function requireValue(condition,message,line=1,source='events.jsonl') {if(!condition)fail(message,line,source);}
function validateManifest(input) {
  const src='manifest.json',check=(ok,msg)=>requireValue(ok,msg,1,src);
  check(object(input),'Expected a replay manifest object');
  check(input.replay_format===REPLAY_FORMAT,`Unsupported replay_format: ${String(input.replay_format)}`);
  const {world,plan,scenario,raw,economy}=input;
  check(object(world)&&world.schema_version===1,'world.schema_version must be 1');
  check(object(world.clock),'Missing world.clock');
  const clock=world.clock;
  for(const key of ['tick_seconds','shift_ticks','overtime_ticks','break_at','break_length','walk_ticks'])
    check(integer(clock[key])&&clock[key]>=0,`world.clock.${key} must be a non-negative integer`);
  check(clock.tick_seconds>0&&clock.shift_ticks>0,'tick_seconds and shift_ticks must be positive');
  check(object(world.capacity)&&object(world.time)&&object(world.workers),'Missing World capacities, times or worker catalog');
  for(const key of ['pick','pack','qc'])check(integer(world.capacity[key])&&world.capacity[key]>=0,`Invalid world.capacity.${key}`);
  check(Array.isArray(world.kinds)&&world.kinds.length>0&&world.kinds.every(k=>['regular','fragile','oversize'].includes(k)),'Unknown order kind in world.kinds');
  check(object(plan)&&plan.schema_version===1,'plan.schema_version must be 1');
  check(typeof plan.robot==='boolean'&&typeof plan.trays==='boolean','plan.robot and plan.trays must be boolean');
  check(['manual','all','bypass'].includes(plan.route)&&(!(!plan.robot&&plan.route!=='manual')),'Invalid plan.route / robot combination');
  check(Array.isArray(plan.workers)&&plan.workers.length>=1&&plan.workers.length<=(world.workers.max??8),'Invalid plan.workers count');
  for(const [i,zones] of plan.workers.entries())check(Array.isArray(zones)&&zones.length>0&&zones.every(s=>integer(s)&&s>=1&&s<=4)&&new Set(zones).size===zones.length,`Invalid zones for worker w${i}`);
  check(object(scenario)&&scenario.schema_version===1&&integer(scenario.seed),'Invalid scenario schema or seed');
  check(Array.isArray(scenario.orders)&&scenario.orders.length>0,'scenario.orders must be non-empty');
  const ids=new Set();let previous=null;
  for(const [i,o] of scenario.orders.entries()) {
    check(exactKeys(o,['id','kind','arrival','due']),`Scenario order #${i} must contain id, kind, arrival, due`);
    check(integer(o.id)&&o.id>=0&&!ids.has(o.id),`Duplicate or invalid order id at #${i}`);
    check(world.kinds.includes(o.kind),`Unknown order kind ${o.kind} at #${i}`);
    check(integer(o.arrival)&&o.arrival>=0&&o.arrival<clock.shift_ticks&&integer(o.due)&&o.due>=o.arrival,`Invalid arrival/due at order ${o.id}`);
    check(!previous||previous.arrival<o.arrival||(previous.arrival===o.arrival&&previous.id<o.id),'Scenario orders must be strictly sorted by (arrival, id)');
    ids.add(o.id);previous=o;
    const manual=world.time.manual?.[o.kind];
    check(Array.isArray(manual)&&manual.length===4&&manual.every(v=>integer(v)&&v>0),`Missing manual durations for ${o.kind}`);
    check(integer(world.time.auto?.[plan.trays?'tray':'bare']?.[o.kind])&&world.time.auto[plan.trays?'tray':'bare'][o.kind]>0,`Missing robot duration for ${o.kind}`);
  }
  check(integer(world.time.jam_service)&&world.time.jam_service>0,'Invalid jam_service duration');
  check(object(raw)&&raw.schema_version===1&&raw.seed===scenario.seed,'Invalid RawReport schema or seed');
  for(const key of COUNTER_KEYS.filter(k=>k!=='overtime_ticks'))check(integer(raw[key])&&raw[key]>=0,`Invalid raw.${key}`);
  check(Array.isArray(raw.overtime_ticks)&&raw.overtime_ticks.length===plan.workers.length&&raw.overtime_ticks.every(v=>integer(v)&&v>=0),'raw.overtime_ticks must contain one non-negative integer per worker');
  check(Array.isArray(raw.events)&&raw.events.length===0,'raw.events must be [] because events.jsonl is authoritative');
  check(object(economy)&&integer(economy.purchase)&&economy.purchase>=0&&integer(economy.total)&&economy.total>=0,'Invalid Economy money fields');
  check(exactKeys(economy.costs,COST_KEYS),'Economy.costs must contain the 10 v1 operating cost items');
  check(Object.values(economy.costs).every(v=>integer(v)&&v>=0)&&Object.values(economy.costs).reduce((a,b)=>a+b,0)===economy.total,'Economy.total differs from sum(costs)');
  check(typeof input.events_file==='string'&&input.events_file.length>0&&!/[\\/\0]/.test(input.events_file)&&!['.','..'].includes(input.events_file),'Invalid events_file name');
  return clone(input);
}

/** Parse without sorting. A complete last JSON record is legal without LF. */
export function parseEvents(text,horizonTicks=Infinity) {
  requireValue(typeof text==='string','Expected JSONL text');
  const lines=text.replace(/^\uFEFF/,'').split(/\r?\n/);
  if(lines.at(-1)==='')lines.pop();
  const events=[];let lastTick=0;
  for(let index=0;index<lines.length;index++) {
    const line=index+1;let event;
    try {event=JSON.parse(lines[index]);} catch(error) {fail(`Invalid or truncated JSONL record (${error.message})`,line);}
    requireValue(exactKeys(event,EVENT_KEYS),'Expected the exact 7 Event keys',line);
    requireValue(integer(event.tick)&&event.tick>=lastTick&&event.tick>=0&&event.tick<=horizonTicks,`Tick ${event.tick} violates monotonicity or horizon [${lastTick}, ${horizonTicks}]`,line);
    requireValue(EVENT_KINDS.includes(event.kind),`Unknown Event.kind: ${String(event.kind)}`,line);
    events.push(Object.freeze({...event,line,eventIndex:index}));lastTick=event.tick;
  }
  requireValue(events.length>0,'Empty event trace for a non-empty scenario');
  return Object.freeze(events);
}

function initialState(manifest,runId) {
  const orders=Object.fromEntries(manifest.scenario.orders.map(o=>[o.id,{...o,status:'not_arrived',queue:null,stage:1,attempt:0,resource:null,tray:false}]));
  const workers=Object.fromEntries(manifest.plan.workers.map((zones,i)=>[`w${i}`,{id:`w${i}`,zones:[...zones],zone:zones[0],previousZone:zones[0],state:'idle',orderId:null,activity:null,lastActivity:null,walk:null,lastWalk:null,lastWorkEnd:0,tookBreak:false}]));
  return {runId,tick:0,tickFloat:0,timeSeconds:0,ended:false,orders,workers,
    queues:{Q1:[],Q2:[],Q3:[],Q4:[],R:[]},reserved:{Q2:0,Q3:0,Q4:0},reservationOwners:{Q2:[],Q3:[],Q4:[]},
    capacity:{Q2:manifest.world.capacity.pick,Q3:manifest.world.capacity.pack,Q4:manifest.world.capacity.qc},
    robot:{id:'robot',state:!manifest.plan.robot?'not_purchased':manifest.plan.route==='manual'?'disabled':'idle',orderId:null,activity:null,lastActivity:null,jamTick:null,helperId:null,assistEndTick:null,assistCompletedTick:null},
    counters:{total:manifest.scenario.orders.length,good:0,on_time:0,escaped:0,scrap:0,unfinished:0,pack_started:0,pack_finished:0,auto_finished:0,trays_used:0,rework_started:0,labor_ticks:0,overtime_ticks:manifest.plan.workers.map(()=>0)},
    outcomes:{good:[],escaped:[],scrap:[]},eventIndex:-1,arrivedCount:0,
    _transitions:{},_laborIntervals:[],_lastEventTick:-1};
}
function expire(state,tick) {
  for(const worker of Object.values(state.workers)) {
    const a=worker.activity;
    if(a&&['assist','break'].includes(a.kind)&&a.endTick<=tick) {
      worker.lastActivity={...a};worker.activity=null;worker.orderId=null;worker.walk=null;worker.state='idle';
      if(a.kind==='assist')state.robot.assistCompletedTick=a.endTick;
    }
  }
}
function actorFree(worker) {return worker.activity===null;}
function transitionMatches(previous,kind,stage,attempt) {return previous?.kind===kind&&previous.stage===stage&&previous.attempt===attempt;}
function expect(condition,event,message) {requireValue(condition,message,event.line);}
function queueName(stage,attempt) {return stage===3&&attempt===1?'R':`Q${stage}`;}
function sameActivity(activity,event) {return activity&&activity.orderId===event.order_id&&activity.stage===event.stage&&activity.attempt===event.attempt;}

function applyBatch(state,batch,manifest,horizon,validate=true) {
  const tick=batch[0].tick,clock=manifest.world.clock;
  expire(state,tick);
  if(validate) {
    for(const w of Object.values(state.workers))if(w.activity?.kind==='work'&&w.activity.endTick<tick)fail(`Missing finish for ${w.id} at tick ${w.activity.endTick}`,batch[0].line);
    const r=state.robot;
    if(r.activity&&r.jamTick===null&&r.activity.endTick<tick)fail(`Missing finish/jam for robot at tick ${r.activity.endTick}`,batch[0].line);
    if(r.activity&&r.assistCompletedTick!==null&&r.assistCompletedTick<tick)fail(`Missing robot finish after assist at tick ${r.assistCompletedTick}`,batch[0].line);
  }
  const starts=[];
  for(const event of batch) {
    const {kind,order_id:id,resource,stage,attempt,end_tick:end}=event;
    const worker=Object.hasOwn(state.workers,resource)?state.workers[resource]:null;
    if(kind==='break') {
      expect(id===null&&stage===null&&attempt===null&&worker&&integer(end)&&end-tick===clock.break_length&&tick>=clock.break_at&&tick<horizon,event,'Invalid break event or interval');
      expect(actorFree(worker)&&!worker.tookBreak,event,`Worker ${resource} is busy or already took a break`);
      worker.activity={kind:'break',startTick:tick,endTick:end,stage:worker.zone,attempt:null,orderId:null,fromZone:worker.zone};
      worker.state='break';worker.tookBreak=true;worker.walk=null;worker.orderId=null;
      state.eventIndex=event.eventIndex;continue;
    }
    expect(integer(id)&&Object.hasOwn(state.orders,id),event,`Unknown or missing order_id ${String(id)}`);
    expect(integer(stage)&&stage>=1&&stage<=4&&integer(attempt)&&[0,1].includes(attempt),event,'Invalid stage or attempt');
    const order=state.orders[id],previous=state._transitions[id];
    if(kind==='arrival') {
      expect(order.status==='not_arrived'&&!previous&&resource===null&&stage===1&&attempt===0&&end===null&&tick===order.arrival,event,'Invalid or duplicate arrival');
      order.status='arrived';state.arrivedCount++;
    } else if(kind==='enqueue') {
      expect(resource===null&&end===null,event,'Enqueue must not have resource or end_tick');
      let allowed=false;
      if(stage===1)allowed=transitionMatches(previous,'arrival',1,0)&&attempt===0;
      else if(stage===3&&attempt===1)allowed=transitionMatches(previous,'finish',4,0);
      else allowed=transitionMatches(previous,'finish',stage-1,attempt);
      expect(allowed&&previous.tick===tick,event,`Illegal enqueue transition for order ${id}`);
      const q=queueName(stage,attempt);
      expect(!Object.values(state.queues).some(ids=>ids.includes(id)),event,`Order ${id} is already in a queue`);
      state.queues[q].push(id);Object.assign(order,{status:'queue',queue:q,stage,attempt,resource:null});
    } else if(kind==='start') {
      expect((resource==='robot'||worker)&&integer(end)&&end>tick&&tick<horizon&&transitionMatches(previous,'enqueue',stage,attempt),event,`Invalid start or order state for ${id}`);
      const q=queueName(stage,attempt),at=state.queues[q].indexOf(id);
      expect(at>=0&&order.status==='queue'&&order.queue===q,event,`Order ${id} is missing from ${q}`);
      const expectedAuto=stage===3&&attempt===0&&manifest.plan.robot&&(manifest.plan.route==='all'||(manifest.plan.route==='bypass'&&order.kind==='regular'));
      expect((resource==='robot')===Boolean(expectedAuto),event,`Routing violation for order ${id} on ${resource}`);
      const fromZone=worker?.zone??3,travel=worker&&fromZone!==stage?clock.walk_ticks:0;
      if(resource==='robot') {
        expect(!state.robot.activity,event,'Robot is already busy');
        expect(end===tick+manifest.world.time.auto[manifest.plan.trays?'tray':'bare'][order.kind],event,'Robot start.end_tick differs from World duration');
      } else {
        expect(actorFree(worker)&&worker.zones.includes(stage),event,`Worker ${resource} is busy or cannot work in stage ${stage}`);
        expect(tick<clock.break_at||worker.tookBreak,event,`Worker ${resource} started work before taking the due break`);
        expect(end===tick+travel+manifest.world.time.manual[order.kind][stage-1],event,'Manual start.end_tick differs from World work/walk duration');
      }
      if(stage<4) {
        const next=`Q${stage+1}`;
        expect(state.queues[next].length+state.reserved[next]<state.capacity[next],event,`${next} waiting + reserved exceeds capacity`);
        expect(!state.reservationOwners[next].includes(id),event,`Duplicate ${next} reservation`);
        state.reservationOwners[next].push(id);state.reserved[next]++;
      }
      state.queues[q].splice(at,1);
      const activity={kind:'work',startTick:tick,endTick:end,stage,attempt,orderId:id,fromZone};
      if(worker) {
        worker.previousZone=fromZone;worker.zone=stage;worker.activity=activity;worker.orderId=id;worker.walk=null;worker.state=OPERATION[stage];
        worker.lastWorkEnd=Math.min(horizon,end);state._laborIntervals.push({worker:resource,startTick:tick,endTick:end});
        starts.push({event,worker,fromZone});
      } else Object.assign(state.robot,{state:'pack',activity,orderId:id,jamTick:null,helperId:null,assistEndTick:null,assistCompletedTick:null});
      Object.assign(order,{status:'processing',queue:null,stage,attempt,resource});
      if(stage===3) {
        state.counters.pack_started++;
        if(manifest.plan.trays&&attempt===0){state.counters.trays_used++;order.tray=true;}
        if(attempt===1)state.counters.rework_started++;
      }
    } else if(kind==='walk') {
      expect(worker&&integer(end)&&end===tick+clock.walk_ticks&&end>tick,event,'Invalid walk resource or end_tick');
      expect(sameActivity(worker.activity,event)&&worker.activity.startTick===tick&&worker.activity.fromZone!==stage&&!worker.walk,event,'Orphan, duplicate or mismatched walk sub-interval');
      expect(end<=worker.activity.endTick,event,'Walk exceeds parent activity');
      worker.walk={fromZone:worker.activity.fromZone,toZone:stage,startTick:tick,endTick:end};worker.lastWalk={...worker.walk};worker.state='walk';
    } else if(kind==='finish') {
      expect((resource==='robot'||worker)&&end===null&&transitionMatches(previous,'start',stage,attempt)&&order.resource===resource,event,`Invalid finish transition for order ${id}`);
      const actor=worker??state.robot;
      expect(sameActivity(actor.activity,event)&&actor.activity.kind==='work',event,`Finish has no matching active operation on ${resource}`);
      if(resource==='robot') {
        expect(state.robot.jamTick===null?tick===actor.activity.endTick:state.robot.assistCompletedTick===tick,event,'Robot finish is mistimed or jam has not been serviced');
        Object.assign(state.robot,{lastActivity:{...actor.activity},state:'idle',activity:null,orderId:null,jamTick:null,helperId:null,assistEndTick:null,assistCompletedTick:null});
      } else {
        expect(tick===actor.activity.endTick,event,`Worker ${resource} finish is not at its end_tick`);
        Object.assign(worker,{lastActivity:{...worker.activity},activity:null,state:'idle',orderId:null,walk:null});
      }
      if(stage<4) {
        const next=`Q${stage+1}`,at=state.reservationOwners[next].indexOf(id);
        expect(at>=0&&state.reserved[next]>0,event,`Missing output reservation in ${next}`);
        state.reservationOwners[next].splice(at,1);state.reserved[next]--;
      }
      if(stage===3){state.counters.pack_finished++;if(resource==='robot')state.counters.auto_finished++;}
      order.status='finished_stage';order.resource=null;
    } else if(kind==='jam') {
      const r=state.robot;
      expect(resource==='robot'&&stage===3&&attempt===0&&end===null&&transitionMatches(previous,'start',3,0)&&sameActivity(r.activity,event)&&r.jamTick===null&&tick===r.activity.endTick,event,'Invalid or duplicate robot jam');
      r.state='jammed';r.jamTick=tick;
    } else if(kind==='assist') {
      const r=state.robot,fromZone=worker?.zone,travel=fromZone!==3?clock.walk_ticks:0;
      expect(worker&&worker.zones.includes(3)&&actorFree(worker)&&stage===3&&attempt===0&&integer(end)&&end>tick&&tick<horizon,event,'Invalid assist worker or interval');
      expect(tick<clock.break_at||worker.tookBreak,event,`Worker ${resource} started assistance before taking the due break`);
      expect(transitionMatches(previous,'start',3,0)&&r.orderId===id&&r.jamTick!==null&&r.helperId===null&&r.activity,event,'Assist does not reference an unassigned jammed robot');
      expect(end===tick+travel+manifest.world.time.jam_service,event,'Assist end_tick differs from World walk/service duration');
      worker.previousZone=fromZone;worker.zone=3;worker.activity={kind:'assist',startTick:tick,endTick:end,stage:3,attempt:0,orderId:id,fromZone};
      worker.orderId=null;worker.walk=null;worker.state='assist';worker.lastWorkEnd=Math.min(horizon,end);
      state._laborIntervals.push({worker:resource,startTick:tick,endTick:end});starts.push({event,worker,fromZone});
      r.helperId=resource;r.assistEndTick=end;r.state=travel?'helper_walking':'service';
    } else if(TERMINAL.has(kind)) {
      expect(worker&&stage===4&&end===null&&transitionMatches(previous,'finish',4,attempt)&&previous.tick===tick&&previous.resource===resource&&(kind!=='scrap'||attempt===1),event,`Invalid or duplicate terminal ${kind}`);
      state.counters[kind]++;state.outcomes[kind].push(id);
      if(kind==='good'&&tick<=order.due)state.counters.on_time++;
      Object.assign(order,{status:kind,queue:null,resource:null,stage:4,attempt,outcomeTick:tick});
    }
    if(!['walk','jam','assist'].includes(kind))state._transitions[id]={kind,stage,attempt,tick,resource,line:event.line};
    state.eventIndex=event.eventIndex;
  }
  if(validate) {
    for(const {event,worker,fromZone} of starts)expect(fromZone===event.stage?worker.walk===null:Boolean(worker.walk),event,`Missing or unexpected walk for ${worker.id} transition ${fromZone}->${event.stage}`);
    for(const [id,last] of Object.entries(state._transitions))if(['arrival','finish'].includes(last.kind))fail(`Truncated tick ${tick}: order ${id} is missing its enqueue/outcome after ${last.kind}`,last.line);
    for(const worker of Object.values(state.workers))if(worker.activity?.kind==='work'&&worker.activity.endTick<=tick)fail(`Missing finish for ${worker.id} at tick ${worker.activity.endTick}`,batch.at(-1).line);
    const r=state.robot;
    if(r.activity&&r.jamTick===null&&r.activity.endTick<=tick)fail(`Missing finish/jam for robot at tick ${r.activity.endTick}`,batch.at(-1).line);
    if(r.activity&&r.assistCompletedTick!==null&&r.assistCompletedTick<=tick)fail(`Missing robot finish after assist at tick ${r.assistCompletedTick}`,batch.at(-1).line);
    for(const q of ['Q2','Q3','Q4'])expect(state.reserved[q]===state.reservationOwners[q].length&&state.queues[q].length+state.reserved[q]<=state.capacity[q],batch.at(-1),`Invalid ${q} waiting/reserved invariant`);
  }
  state._lastEventTick=tick;
}

function sampleState(internal,tickFloat,manifest,horizon,tickSeconds) {
  const state=clone(internal);expire(state,tickFloat);
  state.tick=Math.floor(tickFloat);state.tickFloat=tickFloat;state.timeSeconds=tickFloat*tickSeconds;state.ended=tickFloat>=horizon;
  for(const worker of Object.values(state.workers)) {
    const a=worker.activity;
    worker.state=!a?'idle':worker.walk&&tickFloat<worker.walk.endTick?'walk':a.kind==='work'?OPERATION[a.stage]:a.kind;
    worker.unfinished=state.ended&&a!==null&&a.kind!=='break';
  }
  const r=state.robot;
  if(r.activity&&r.jamTick!==null)r.state=r.helperId?(state.workers[r.helperId].walk&&tickFloat<state.workers[r.helperId].walk.endTick?'helper_walking':'service'):'jammed';
  r.stopped=state.ended;
  state.counters.labor_ticks=state._laborIntervals.reduce((sum,a)=>sum+Math.max(0,Math.min(tickFloat,horizon,a.endTick)-a.startTick),0);
  state.counters.overtime_ticks=Object.values(state.workers).map(w=>Math.max(0,Math.min(tickFloat,horizon,w.lastWorkEnd)-manifest.world.clock.shift_ticks));
  if(state.ended) {
    for(const order of Object.values(state.orders))if(!TERMINAL.has(order.status)) {
      order.previousStatus=order.status;order.status='unfinished';state.counters.unfinished++;
    }
  }
  state.inSystem=state.arrivedCount-state.counters.good-state.counters.escaped-state.counters.scrap;
  state.notArrived=state.counters.total-state.arrivedCount;
  delete state._transitions;delete state._laborIntervals;delete state._lastEventTick;
  return state;
}

/** Validate once, then deterministically reconstruct any prefix from checkpoints. */
export function createReplay(input,eventsText,{runId='local'}={}) {
  const manifest=validateManifest(input),clock=manifest.world.clock;
  const horizonTicks=clock.shift_ticks+clock.overtime_ticks,tickSeconds=clock.tick_seconds;
  const events=parseEvents(eventsText,horizonTicks),batches=[];
  for(const event of events) {
    if(batches.at(-1)?.[0].tick===event.tick)batches.at(-1).push(event);else batches.push([event]);
  }
  const initial=initialState(manifest,String(runId)),checkpoints=[{tick:-1,batchIndex:0,state:clone(initial)}];
  let current=initial;
  for(let i=0;i<batches.length;i++) {
    applyBatch(current,batches[i],manifest,horizonTicks);
    if(batches[i][0].tick-checkpoints.at(-1).tick>=60)checkpoints.push({tick:batches[i][0].tick,batchIndex:i+1,state:clone(current)});
  }
  const eofLine=events.at(-1).line+1;
  expire(current,horizonTicks);
  for(const worker of Object.values(current.workers))if(worker.activity?.kind==='work'&&worker.activity.endTick<=horizonTicks)fail(`Truncated trace: missing finish for ${worker.id} at tick ${worker.activity.endTick}`,eofLine);
  const r=current.robot;
  if(r.activity&&((r.jamTick===null&&r.activity.endTick<=horizonTicks)||(r.assistCompletedTick!==null&&r.assistCompletedTick<=horizonTicks)))fail('Truncated trace: missing robot finish/jam before horizon',eofLine);
  requireValue(current.arrivedCount===manifest.scenario.orders.length,'Truncated trace: orders are missing arrival events',eofLine);
  const final=sampleState(current,horizonTicks,manifest,horizonTicks,tickSeconds);
  for(const key of COUNTER_KEYS)requireValue(same(final.counters[key],manifest.raw[key]),`Trace does not match manifest.raw.${key}: reconstructed ${JSON.stringify(final.counters[key])}, expected ${JSON.stringify(manifest.raw[key])}`,eofLine);
  const importantEvents=events.filter(e=>['jam','assist','break','escaped','scrap'].includes(e.kind)||(e.kind==='enqueue'&&e.stage===3&&e.attempt===1)).map(e=>Object.freeze({tick:e.tick,kind:e.kind==='enqueue'?'rework':e.kind,eventIndex:e.eventIndex,orderId:e.order_id,line:e.line}));
  return Object.freeze({manifest,events,runId:String(runId),tickSeconds,horizonTicks,durationSeconds:horizonTicks*tickSeconds,importantEvents:Object.freeze(importantEvents),
    seekTo(seconds) {
      requireValue(typeof seconds==='number'&&Number.isFinite(seconds),'seekTo requires a finite time in seconds',1,'player');
      const tickFloat=Math.min(horizonTicks,Math.max(0,seconds/tickSeconds)),target=Math.floor(tickFloat);
      let checkpoint=checkpoints[0];for(const candidate of checkpoints){if(candidate.tick<=target)checkpoint=candidate;else break;}
      const state=clone(checkpoint.state);
      for(let i=checkpoint.batchIndex;i<batches.length&&batches[i][0].tick<=target;i++)applyBatch(state,batches[i],manifest,horizonTicks,false);
      return sampleState(state,tickFloat,manifest,horizonTicks,tickSeconds);
    }
  });
}
