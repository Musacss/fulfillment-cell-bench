// Presentation geometry only. These functions never change replay timing or counts.
export const ORDER_SIZES = Object.freeze({regular:[.36,.28,.25],fragile:[.36,.28,.25],oversize:[.48,.34,.32]});
export const BREAK_POINTS = Object.freeze(Array.from({length:8},(_,i)=>[
  7.4+(i%4)*(2.8/3),0,-6.4-Math.floor(i/4)*.65,
]));

export function actorPosition(bindings,stage,index=0) {
  const entry=bindings.stages.find(s=>s.stage===Number(stage));
  if(!entry)throw new Error('Нет пространственной привязки этапа '+stage);
  if(!Number.isInteger(index)||index<0)throw new Error('Invalid parallel slot '+index);
  const p=[...entry.actor_position_gltf_m];
  // All parallel stations share the north row, especially the third PACK post.
  p[0]+=(Number(stage)===4?1:-1)*index*entry.parallel_slot_spacing_m[0];
  return p;
}
export const stageWorkPosition=(stage,index,bindings)=>actorPosition(bindings,stage,index);
export function benchPosition(bindings,stage,index=0) {
  const p=actorPosition(bindings,stage,index);p[2]-=.65;return p;
}
export function breakPosition(index=0) {return [...BREAK_POINTS[((Number(index)%8)+8)%8]];}

function rect(name,minX,maxX,minZ,maxZ){return {name,minX,maxX,minZ,maxZ};}
export const DEFAULT_OBSTACLES=Object.freeze([
  rect('CONVEYOR',-9.5,9.5,-.56,.56),
  rect('PREP',-11.56,-10.44,-2.13,-1.079),
  rect('PREP cassette',-10.40,-9.94,-2.04,-1.30),
  rect('Q1 pallet deck',-11.66,-9.22,-3.76,-2.86),
  rect('PICK',-6.31,-4.49,-3.16,-2.179),
  rect('PICK parallel',-7.56,-6.44,-3.18,-2.129),
  rect('PACK',.89,2.71,-3.16,-2.179),
  rect('PACK parallel 1',-.36,.76,-3.18,-2.129),
  rect('PACK parallel 2',-1.96,-.84,-3.18,-2.129),
  rect('ROBOT table',2.95,4.06,-3.18,-2.13),
  rect('QC table',5.44,6.56,-3.18,-2.129),
  rect('QC parallel',7.04,8.16,-3.18,-2.129),
  rect('SUPPLY_TROLLEY',-2.29,-1.31,-4.03,-3.37),
  rect('ROBOT_GUARD_REAR',2.68,4.77,-4.28,-4.18),
  rect('ROBOT_GUARD_RIGHT',4.67,4.77,-4.28,-2.20),
  rect('ROBOT_PLC_CABINET',4.83,5.53,-4.50,-3.98),
  rect('LIGHT_CURTAIN_LEFT',2.35,2.53,-1.54,-1.36),
  rect('LIGHT_CURTAIN_RIGHT',4.63,4.81,-1.54,-1.36),
  rect('RACK_01',-9.76,-7.84,-6.72,-5.98),
  rect('RACK_02',-6.16,-4.24,-6.72,-5.98),
  rect('RACK_03',-2.56,-.64,-6.72,-5.98),
  rect('Paper stock',3.08,4.93,-6.79,-5.91),
  rect('Q2',-7.63,-5.29,2.04,3.40),
  rect('Q2 infeed',-6.81,-6.11,.30,2.11),
  rect('Q3',-1.03,1.87,2.04,2.99),
  rect('Q3 infeed',.07,.77,.30,2.11),
  rect('Q4',5.27,7.61,2.04,2.99),
  rect('Q4 infeed',6.09,6.79,.30,2.11),
  rect('R',3.36,5.36,6.76,7.74),
  rect('SCRAP_BIN',6.57,7.83,6.46,7.54),
  rect('BREAK_BENCH',7.43,9.27,-7.86,-7.38),
  rect('WATER_COOLER',10.04,10.44,-7.99,-7.58),
]);

export function segmentHitsObstacle(a,b,o,clearance=0) {
  const lo=[o.minX-clearance,o.minZ-clearance],hi=[o.maxX+clearance,o.maxZ+clearance];
  const aa=[a[0],a[2]],bb=[b[0],b[2]];let start=0,end=1;
  for(let i=0;i<2;i++){
    const d=bb[i]-aa[i];
    if(Math.abs(d)<1e-12){if(aa[i]<=lo[i]+1e-8||aa[i]>=hi[i]-1e-8)return false;continue;}
    let l=(lo[i]-aa[i])/d,h=(hi[i]-aa[i])/d;if(l>h)[l,h]=[h,l];
    start=Math.max(start,l);end=Math.min(end,h);if(end-start<=1e-8)return false;
  }
  return end>1e-8&&start<1-1e-8;
}
const distance=(a,b)=>Math.hypot(a[0]-b[0],a[2]-b[2]);
const same=(a,b)=>distance(a,b)<1e-7;
const routeCache=new Map();

class MinHeap {
  constructor(){this.a=[];}
  push(n){const a=this.a;a.push(n);let i=a.length-1;while(i){const p=(i-1)>>1;if(a[p].f<=n.f)break;a[i]=a[p];i=p;}a[i]=n;}
  pop(){const a=this.a,first=a[0],last=a.pop();if(a.length){let i=0;while(i*2+1<a.length){let j=i*2+1;if(j+1<a.length&&a[j+1].f<a[j].f)j++;if(a[j].f>=last.f)break;a[i]=a[j];i=j;}a[i]=last;}return first;}
  get length(){return this.a.length;}
}

function gridPath(from,to,obstacles) {
  if(same(from,to))return [[...from],[...to]];
  const clearance=.17,step=.2,minX=-13.4,minZ=-8.6,nx=135,nz=87;
  const point=(x,z)=>[minX+x*step,0,minZ+z*step];
  const blocked=(x,z)=>x<0||z<0||x>=nx||z>=nz||obstacles.some(o=>{
    const p=point(x,z);return p[0]>o.minX-clearance&&p[0]<o.maxX+clearance&&p[2]>o.minZ-clearance&&p[2]<o.maxZ+clearance;
  });
  const lineClear=(a,b,margin=clearance)=>!obstacles.some(o=>segmentHitsObstacle(a,b,o,margin));
  if(lineClear(from,to))return [[...from],[...to]];
  function nodeFor(p){
    const xx=Math.round((p[0]-minX)/step),zz=Math.round((p[2]-minZ)/step);let best=null;
    for(let r=0;r<=9;r++){
      for(let dx=-r;dx<=r;dx++)for(let dz=-r;dz<=r;dz++){
        if(r&&Math.max(Math.abs(dx),Math.abs(dz))!==r)continue;
        const x=xx+dx,z=zz+dz;if(blocked(x,z))continue;
        const q=point(x,z);if(!lineClear(p,q,0))continue;
        const d=distance(p,q);if(!best||d<best.d)best={x,z,d};
      }
      if(best)return best;
    }
    throw new Error('Нет свободного подхода к точке '+p.map(v=>v.toFixed(2)).join(', '));
  }
  const start=nodeFor(from),goal=nodeFor(to),key=(x,z)=>z*nx+x;
  const startKey=key(start.x,start.z),goalKey=key(goal.x,goal.z);
  const costs=new Float64Array(nx*nz).fill(Infinity),parents=new Int32Array(nx*nz).fill(-1),closed=new Uint8Array(nx*nz);
  const heap=new MinHeap();costs[startKey]=0;heap.push({id:startKey,x:start.x,z:start.z,f:0});
  const moves=[[1,0],[-1,0],[0,1],[0,-1],[1,1],[1,-1],[-1,1],[-1,-1]];
  let found=false;
  while(heap.length){
    const p=heap.pop();if(closed[p.id])continue;closed[p.id]=1;if(p.id===goalKey){found=true;break;}
    for(const [dx,dz] of moves){
      const x=p.x+dx,z=p.z+dz;if(blocked(x,z)||(dx&&dz&&(blocked(p.x+dx,p.z)||blocked(p.x,p.z+dz))))continue;
      const id=key(x,z),g=costs[p.id]+Math.hypot(dx,dz);if(g>=costs[id])continue;
      costs[id]=g;parents[id]=p.id;heap.push({id,x,z,f:g+Math.hypot(goal.x-x,goal.z-z)});
    }
  }
  if(!found)throw new Error('Не найден безопасный обход оборудования');
  const points=[];for(let id=goalKey;id!==-1;id=parents[id])points.push(point(id%nx,Math.floor(id/nx)));
  points.reverse();points.unshift([...from]);points.push([...to]);
  // Keep only line-of-sight turns. The mandatory corridor pivots live outside
  // this function, so simplification cannot erase the rear-aisle detour.
  const simple=[points[0]];let i=0;
  while(i<points.length-1){let j=points.length-1;while(j>i+1&&!lineClear(points[i],points[j]))j--;simple.push(points[j]);i=j;}
  return simple;
}

export function planWalkPath(from,to,{obstacles=DEFAULT_OBSTACLES}={}) {
  if(!from?.every(Number.isFinite)||!to?.every(Number.isFinite))throw new Error('Invalid walk endpoints');
  const cacheKey=obstacles===DEFAULT_OBSTACLES?JSON.stringify([from,to]):null;
  if(cacheKey&&routeCache.has(cacheKey))return routeCache.get(cacheKey).map(p=>[...p]);
  if(same(from,to))return [[...from],[...to]];
  const north=p=>p[2]<-.6;
  const approach=p=>north(p)&&p[2]>-2.25?[p[0],p[1],p[2]+.65]:[...p];
  const a=approach(from),b=approach(to),pivots=[[...from],a];
  if(north(from)&&north(to))pivots.push([a[0],0,-5],[b[0],0,-5]);
  else if(north(from)!==north(to)){
    const east=distance(a,[10.2,0,a[2]])+distance(b,[10.2,0,b[2]])<=distance(a,[-10.2,0,a[2]])+distance(b,[-10.2,0,b[2]]);
    const x=east?10.2:-10.2;
    if(north(from))pivots.push([a[0],0,-5],[x,0,-5],[x,0,-1.0],[x,0,1.0]);
    else pivots.push([x,0,1.0],[x,0,-1.0],[x,0,-5],[b[0],0,-5]);
  }
  pivots.push(b,[...to]);
  const points=[];
  for(let i=0;i<pivots.length-1;i++){
    const p=pivots[i],q=pivots[i+1];
    // Final standing entries deliberately approach the bench from its front;
    // their exact anchors lie closer than the transit safety margin.
    const endpointLeg=i===0||i===pivots.length-2;
    let segment;
    if(endpointLeg&&!obstacles.some(o=>segmentHitsObstacle(p,q,o)))segment=[[...p],[...q]];
    else segment=gridPath(p,q,obstacles);
    for(const item of segment)if(!points.length||!same(points.at(-1),item))points.push(item);
  }
  if(points.length===1)points.push([...to]);
  if(cacheKey){if(routeCache.size>1000)routeCache.clear();routeCache.set(cacheKey,points);}
  return points.map(p=>[...p]);
}
export const planWalkRoute=planWalkPath;

const orderHeight=o=>(ORDER_SIZES[o?.kind]||ORDER_SIZES.regular)[2]+(o?.tray ? .012 : 0);
export function queueStackPositions(bindings,queue,orders,{maxLayers=3}={}) {
  const q=bindings.queues[queue];if(!q)throw new Error('Unknown queue '+queue);
  const items=Array.isArray(orders)?orders:[];
  const bounded=q.bounded,base=bounded?items.length:q.preview_count;
  const visibleOrders=items.slice(0,bounded?items.length:base*maxLayers),positions=[];
  const layers=[];let y=q.origin_gltf_m[1];
  for(let layer=0;layer<Math.ceil(visibleOrders.length/(base||1));layer++){
    const chunk=visibleOrders.slice(layer*base,(layer+1)*base);layers.push(y);y+=Math.max(...chunk.map(orderHeight),0)+.015;
  }
  visibleOrders.forEach((o,i)=>{
    const cell=bounded?i:i%base,layer=bounded?0:Math.floor(i/base);
    positions.push([q.origin_gltf_m[0]+cell%q.columns*q.spacing[0],layers[layer]??q.origin_gltf_m[1],q.origin_gltf_m[2]-Math.floor(cell/q.columns)*q.spacing[1]]);
  });
  return {positions,visibleOrders,overflow:items.length-visibleOrders.length};
}

export function outcomeStackPositions(bindings,outcome,orders,{maxVisible=outcome==='scrap'?8:12}={}) {
  const q=bindings.outcomes[outcome];if(!q)throw new Error('Unknown outcome '+outcome);
  const visibleOrders=orders.slice(-maxVisible),positions=[];let y=q.position_gltf_m[1];
  for(let layer=0;layer<Math.ceil(visibleOrders.length/4);layer++){
    const chunk=visibleOrders.slice(layer*4,(layer+1)*4);
    chunk.forEach((o,i)=>positions.push([q.position_gltf_m[0]+(i%2? .28:-.28),y,q.position_gltf_m[2]+(Math.floor(i/2)? .20:-.20)]));
    y+=Math.max(...chunk.map(orderHeight),0)+.012;
  }
  return {positions,visibleOrders,overflow:orders.length-visibleOrders.length};
}

export function buildWorkerPresentationPlan(replay,bindings) {
  const histories={},activities=new Map(),occupied={1:new Map(),2:new Map(),3:new Map(),4:new Map()};
  const zones={},slots={},lastPosition={},maxSlots={1:1,2:1,3:1,4:1};
  function assign(id,zone){
    let index=0;while([...occupied[zone].values()].includes(index))index++;
    occupied[zone].set(id,index);maxSlots[zone]=Math.max(maxSlots[zone],index+1);return index;
  }
  replay.manifest.plan.workers.forEach((zonesList,i)=>{
    const id='w'+i,zone=zonesList[0];zones[id]=zone;slots[id]=assign(id,zone);
    lastPosition[id]=actorPosition(bindings,zone,slots[id]);
    histories[id]=[{tick:-1,stage:zone,index:slots[id],position:[...lastPosition[id]]}];
  });
  const walks=new Map(replay.events.filter(e=>e.kind==='walk').map(e=>[e.resource+':'+e.tick,e]));
  for(const e of replay.events){
    if(!/^w\d+$/.test(e.resource||'')||!['start','assist','break'].includes(e.kind))continue;
    const id=e.resource,zone=e.stage??zones[id],from=[...lastPosition[id]];
    if(e.kind!=='break'&&zone!==zones[id]){
      occupied[zones[id]].delete(id);zones[id]=zone;slots[id]=assign(id,zone);
      histories[id].push({tick:e.tick,stage:zone,index:slots[id],position:actorPosition(bindings,zone,slots[id])});
    }
    const kind=e.kind==='start'?'work':e.kind;
    const to=e.kind==='break'?breakPosition(Number(id.slice(1))):e.kind==='assist'?[2.8,0,-1.95]:actorPosition(bindings,zone,slots[id]);
    const duration=e.end_tick-e.tick,walk=walks.get(id+':'+e.tick);
    const travelTicks=distance(from,to)<1e-7?0:walk?walk.end_tick-e.tick:Math.min(2,duration*(e.kind==='break' ? .25 : .35));
    const path=travelTicks>0?planWalkPath(from,to):[[...to],[...to]];
    activities.set(id+':'+kind+':'+e.tick,{kind,startTick:e.tick,endTick:e.end_tick,stage:zone,index:slots[id],from,to,path,travelTicks,attempt:e.attempt,orderId:e.order_id});
    lastPosition[id]=[...to];
  }
  return {histories,activities,maxSlots,slotAt(id,tick){
    const list=histories[id];if(!list)throw new Error('Unknown worker '+id);
    let found=list[0];for(const entry of list){if(entry.tick>tick)break;found=entry;}return found;
  }};
}
