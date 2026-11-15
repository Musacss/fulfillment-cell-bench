// Presentation geometry only. These functions never change replay timing or counts.
export const ORDER_SIZES = Object.freeze({regular:[.36,.28,.25],fragile:[.36,.28,.25],oversize:[.48,.34,.32]});
export const BREAK_POINTS = Object.freeze(Array.from({length:8},(_,i)=>[
  7.4+(i%4)*(2.8/3),0,-6.4-Math.floor(i/4)*.65,
]));

const r6=v=>{const n=Math.round(Number(v)*1e6)/1e6;return n===0?0:n;};

export const DEFAULT_VISUAL_BINDINGS = Object.freeze({
  stages:Object.freeze([
    Object.freeze({stage:1,actor_position_gltf_m:Object.freeze([-11,0,-1]),yaw_gltf_rad:Math.PI,table_height_m:.86,parallel_slot_spacing_m:Object.freeze([1.6,1.8]),parallel_slot_columns:2}),
    Object.freeze({stage:2,actor_position_gltf_m:Object.freeze([-5.4,0,-2.05]),yaw_gltf_rad:Math.PI,table_height_m:.86,parallel_slot_spacing_m:Object.freeze([1.6,1.8]),parallel_slot_columns:2}),
    Object.freeze({stage:3,actor_position_gltf_m:Object.freeze([1.8,0,-2.05]),yaw_gltf_rad:Math.PI,table_height_m:.86,parallel_slot_spacing_m:Object.freeze([1.6,1.8]),parallel_slot_columns:2}),
    Object.freeze({stage:4,actor_position_gltf_m:Object.freeze([6.0,0,-2.05]),yaw_gltf_rad:Math.PI,table_height_m:.86,parallel_slot_spacing_m:Object.freeze([1.6,1.8]),parallel_slot_columns:2}),
  ]),
  robot:Object.freeze({
    stage:3,
    position_gltf_m:Object.freeze([3.5,0,-2.05]),
    yaw_gltf_rad:Math.PI,
    order_position_gltf_m:Object.freeze([3.5,.86,-2.39]),
    helper_position_gltf_m:Object.freeze([2.8,0,-1.95]),
    helper_yaw_gltf_rad:Math.atan2(.70,-.44),
  }),
  queues:Object.freeze({
    Q1:Object.freeze({columns:3,spacing:Object.freeze([.56,.42]),preview_count:6,bounded:false,origin_gltf_m:Object.freeze([-11,.15,-3.1])}),
    Q2:Object.freeze({columns:4,spacing:Object.freeze([.56,-.42]),preview_count:12,bounded:true,origin_gltf_m:Object.freeze([-7.3,.86,2.3])}),
    Q3:Object.freeze({columns:5,spacing:Object.freeze([.56,-.42]),preview_count:10,bounded:true,origin_gltf_m:Object.freeze([-.7,.86,2.3])}),
    Q4:Object.freeze({columns:4,spacing:Object.freeze([.56,-.42]),preview_count:8,bounded:true,origin_gltf_m:Object.freeze([5.6,.86,2.3])}),
    R:Object.freeze({columns:3,spacing:Object.freeze([.56,.42]),preview_count:6,bounded:false,origin_gltf_m:Object.freeze([3.8,.86,7.45])}),
  }),
  outcomes:Object.freeze({
    good:Object.freeze({position_gltf_m:Object.freeze([10,.15,-2.2])}),
    escaped:Object.freeze({position_gltf_m:Object.freeze([10,.15,-4.4])}),
    scrap:Object.freeze({position_gltf_m:Object.freeze([7.2,.02,7.0])}),
  }),
});

export const STAGE_SLOTS = Object.freeze({
  1:Object.freeze([
    Object.freeze({bx:-11.00,bz:-1.65,dir:'-Z',staticBench:true,approach:Object.freeze([-11.00,0,-.80])}),
    Object.freeze({bx:-12.68,bz:-1.65,dir:'-Z',approach:Object.freeze([-12.68,0,-.80])}),
    Object.freeze({bx:-12.68,bz:-3.50,dir:'-Z',approach:Object.freeze([-12.68,0,-2.50])}),
    Object.freeze({bx:-11.35,bz:-4.35,dir:'+Z',approach:Object.freeze([-11.35,0,-5.40])}),
    Object.freeze({bx:-9.80,bz:-4.35,dir:'+Z',approach:Object.freeze([-9.80,0,-5.40])}),
    Object.freeze({bx:-10.45,bz:-6.70,dir:'-Z',approach:Object.freeze([-10.45,0,-5.50])}),
    Object.freeze({bx:-11.60,bz:-6.70,dir:'-Z',approach:Object.freeze([-11.60,0,-5.50])}),
    Object.freeze({bx:-12.75,bz:-6.70,dir:'-Z',approach:Object.freeze([-12.75,0,-5.50])}),
  ]),
  2:Object.freeze([
    Object.freeze({bx:-5.40,bz:-2.70,dir:'-Z',staticBench:true,approach:Object.freeze([-5.40,0,-1.45])}),
    Object.freeze({bx:-7.00,bz:-2.70,dir:'-Z',approach:Object.freeze([-7.00,0,-1.45])}),
    Object.freeze({bx:-4.60,bz:-4.30,dir:'+Z',approach:Object.freeze([-4.60,0,-5.40])}),
    Object.freeze({bx:-6.05,bz:-4.30,dir:'+Z',approach:Object.freeze([-6.05,0,-5.40])}),
    Object.freeze({bx:-7.50,bz:-4.30,dir:'+Z',approach:Object.freeze([-7.50,0,-5.40])}),
    Object.freeze({bx:-4.60,bz:-8.00,dir:'-Z',approach:Object.freeze([-4.60,0,-7.10])}),
    Object.freeze({bx:-6.05,bz:-8.00,dir:'-Z',approach:Object.freeze([-6.05,0,-7.10])}),
    Object.freeze({bx:-7.50,bz:-8.00,dir:'-Z',approach:Object.freeze([-7.50,0,-7.10])}),
  ]),
  3:Object.freeze([
    Object.freeze({bx:1.80,bz:-2.70,dir:'-Z',staticBench:true,approach:Object.freeze([1.80,0,-1.45])}),
    Object.freeze({bx:0.20,bz:-2.70,dir:'-Z',approach:Object.freeze([0.20,0,-1.45])}),
    Object.freeze({bx:-1.40,bz:-2.70,dir:'-Z',approach:Object.freeze([-1.40,0,-1.45])}),
    Object.freeze({bx:-2.90,bz:-2.70,dir:'-Z',approach:Object.freeze([-2.90,0,-1.45])}),
    Object.freeze({bx:1.85,bz:-4.30,dir:'+Z',approach:Object.freeze([1.85,0,-5.40])}),
    Object.freeze({bx:0.60,bz:-4.30,dir:'+Z',approach:Object.freeze([0.60,0,-5.40])}),
    Object.freeze({bx:-0.65,bz:-4.30,dir:'+Z',approach:Object.freeze([-0.65,0,-5.40])}),
    Object.freeze({bx:-2.92,bz:-4.30,dir:'+Z',approach:Object.freeze([-2.92,0,-5.40])}),
  ]),
  4:Object.freeze([
    Object.freeze({bx:6.00,bz:-2.70,dir:'-Z',staticBench:true,approach:Object.freeze([6.00,0,-1.45])}),
    Object.freeze({bx:7.60,bz:-2.70,dir:'-Z',approach:Object.freeze([7.15,0,-1.45])}),
    Object.freeze({bx:5.96,bz:-4.30,dir:'+Z',approach:Object.freeze([5.96,0,-5.40])}),
    Object.freeze({bx:7.09,bz:-4.30,dir:'+Z',approach:Object.freeze([7.09,0,-5.40])}),
    Object.freeze({bx:8.21,bz:-4.30,dir:'+Z',approach:Object.freeze([8.21,0,-5.40])}),
    Object.freeze({bx:5.96,bz:-6.35,dir:'-X',approach:Object.freeze([6.90,0,-6.35])}),
    Object.freeze({bx:5.96,bz:-7.88,dir:'-X',approach:Object.freeze([6.90,0,-7.88])}),
    Object.freeze({bx:8.21,bz:-1.35,dir:'+X',approach:Object.freeze([7.15,0,-1.35])}),
  ]),
});

function rect(name,minX,maxX,minZ,maxZ){return {name,minX,maxX,minZ,maxZ};}

export function stageSlotTransform(bindings=DEFAULT_VISUAL_BINDINGS,stage,index=0) {
  const s=Number(stage),table=STAGE_SLOTS[s];
  const entry=(bindings?.stages||DEFAULT_VISUAL_BINDINGS.stages).find(x=>x.stage===s);
  if(!table||!entry)throw new Error('Нет пространственной привязки этапа '+stage);
  if(!Number.isInteger(index)||index<0||index>=table.length)throw new RangeError('Invalid parallel slot '+index);
  const spec=table[index],tableY=entry.table_height_m??.86;
  let bx=spec.bx,bz=spec.bz;
  if(index===0&&Array.isArray(entry.actor_position_gltf_m)&&entry.actor_position_gltf_m.length===3){
    bx=r6(entry.actor_position_gltf_m[0]);
    bz=r6(entry.actor_position_gltf_m[2]-.65);
  }
  let actor,yaw,order,benchRotY,approach,obstacle;
  if(spec.dir==='+Z'){
    actor=[bx,0,r6(bz-.65)];yaw=0;benchRotY=Math.PI;order=[bx,tableY,r6(bz-.31)];
    approach=spec.approach?[...spec.approach]:[bx,0,r6(bz-1.10)];
    obstacle=rect(`PARALLEL_STAGE_${s}_${index}`,r6(bx-.56),r6(bx+.56),r6(bz-.58),r6(bz+.48));
  }else if(spec.dir==='+X'){
    actor=[r6(bx-.65),0,bz];yaw=Math.PI/2;benchRotY=-Math.PI/2;order=[r6(bx-.31),tableY,bz];
    approach=spec.approach?[...spec.approach]:[r6(bx-1.15),0,bz];
    obstacle=rect(`PARALLEL_STAGE_${s}_${index}`,r6(bx-.58),r6(bx+.48),r6(bz-.56),r6(bz+.56));
  }else if(spec.dir==='-X'){
    actor=[r6(bx+.65),0,bz];yaw=-Math.PI/2;benchRotY=Math.PI/2;order=[r6(bx+.31),tableY,bz];
    approach=spec.approach?[...spec.approach]:[r6(bx+1.15),0,bz];
    obstacle=rect(`PARALLEL_STAGE_${s}_${index}`,r6(bx-.48),r6(bx+.58),r6(bz-.56),r6(bz+.56));
  }else{
    actor=[bx,0,r6(bz+.65)];yaw=index===0?(entry.yaw_gltf_rad??Math.PI):Math.PI;benchRotY=0;order=[bx,tableY,r6(bz+.31)];
    approach=spec.approach?[...spec.approach]:[bx,0,r6(bz+1.30)];
    obstacle=rect(`PARALLEL_STAGE_${s}_${index}`,r6(bx-.56),r6(bx+.56),r6(bz-.48),r6(bz+.58));
  }
  return {stage:s,index,actor,yaw,order,bench:[bx,0,bz],benchRotY,approach,obstacle,dir:spec.dir,staticBench:Boolean(spec.staticBench)};
}

export function actorPosition(bindings=DEFAULT_VISUAL_BINDINGS,stage,index=0) {
  return [...stageSlotTransform(bindings,stage,index).actor];
}
export const stageWorkPosition=(stage,index,bindings=DEFAULT_VISUAL_BINDINGS)=>actorPosition(bindings,stage,index);
export function stageOrderPosition(bindings=DEFAULT_VISUAL_BINDINGS,stage,index=0) {
  return [...stageSlotTransform(bindings,stage,index).order];
}
export function benchPosition(bindings=DEFAULT_VISUAL_BINDINGS,stage,index=0) {
  return [...stageSlotTransform(bindings,stage,index).bench];
}
export function parallelBenchTransform(bindings=DEFAULT_VISUAL_BINDINGS,stage,index=0) {
  const slot=stageSlotTransform(bindings,stage,index);
  return {position:[...slot.bench],rotationY:slot.benchRotY};
}
export function breakPosition(index=0) {return [...BREAK_POINTS[((Number(index)%8)+8)%8]];}

export function robotAssistPosition(bindings=DEFAULT_VISUAL_BINDINGS) {
  const p=bindings?.robot?.helper_position_gltf_m;
  return Array.isArray(p)&&p.length===3?[...p]:[2.8,0,-1.95];
}
export function robotAssistYaw(bindings=DEFAULT_VISUAL_BINDINGS) {
  const helper=robotAssistPosition(bindings);
  const target=bindings?.robot?.order_position_gltf_m??[3.5,.86,-2.39];
  const dx=target[0]-helper[0],dz=target[2]-helper[2],len=Math.hypot(dx,dz);
  const computed=Math.atan2(dx,dz);
  const configured=bindings?.robot?.helper_yaw_gltf_rad;
  if(Number.isFinite(configured)&&len>1e-6){
    const dot=(Math.sin(configured)*dx+Math.cos(configured)*dz)/len;
    if(dot>.995)return configured;
  }
  return computed;
}

export const BASE_STATIC_OBSTACLES=Object.freeze([
  rect('CONVEYOR',-10.15,10.15,-.60,.60),
  rect('INFEED_PREP_C01',-10.43,-9.00,-1.35,.35),
  rect('OUTFEED_C10_GOOD',8.98,10.02,-1.78,.35),
  rect('SPUR_PICK',-4.49,-4.05,-.89,-.46),
  rect('SPUR_PACK',.77,1.21,-.89,-.46),
  rect('SPUR_ROBOT',3.93,4.23,-2.12,-.37),
  rect('SPUR_QC',6.47,6.91,-.89,-.46),
  rect('PREP',-11.56,-10.44,-2.13,-1.079),
  rect('PREP cassette',-10.40,-9.95,-2.03,-1.35),
  rect('Q1 pallet deck',-11.65,-9.23,-3.75,-2.88),
  rect('PICK',-6.31,-4.49,-3.16,-2.179),
  rect('PICK rear totes',-6.24,-4.56,-3.12,-2.72),
  rect('PACK',.89,2.71,-3.16,-2.179),
  rect('ROBOT table',2.95,4.06,-3.18,-2.13),
  rect('QC table',5.44,6.68,-3.18,-2.129),
  rect('GOOD pallet',9.38,10.62,-2.62,-1.78),
  rect('ESCAPED pallet',9.38,10.62,-4.82,-3.98),
  rect('SUPPLY_TROLLEY',-2.30,-1.30,-4.02,-3.38),
  rect('ROBOT_GUARD_REAR',2.68,4.36,-4.28,-4.18),
  rect('ROBOT_GUARD_RIGHT',4.28,4.36,-4.22,-2.20),
  rect('ROBOT_PLC_CABINET',4.40,5.08,-4.48,-3.96),
  rect('LIGHT_CURTAIN_LEFT',2.41,2.49,-1.59,-1.53),
  rect('LIGHT_CURTAIN_RIGHT',4.28,4.35,-1.59,-1.53),
  rect('RACK_01',-9.75,-7.85,-6.71,-5.99),
  rect('RACK_02',-6.15,-4.25,-6.71,-5.99),
  rect('RACK_03',-2.55,-.65,-6.71,-5.99),
  rect('Paper stock',3.11,4.33,-6.76,-5.94),
  rect('Q2',-7.64,-5.29,2.04,3.40),
  rect('Q2 infeed',-6.81,-6.10,.35,2.10),
  rect('Q3',-1.03,1.88,2.04,2.99),
  rect('Q3 infeed',.07,.77,.35,2.10),
  rect('Q4',5.27,7.62,2.04,2.99),
  rect('Q4 infeed',6.08,6.79,.35,2.10),
  rect('R',3.38,5.34,6.74,7.77),
  rect('BENCH_REWORK',1.00,2.60,5.95,6.75),
  rect('SCRAP_BIN',6.58,7.82,6.48,7.52),
  rect('BENCH_SCRAP',7.95,9.35,5.95,6.75),
  rect('BREAK_BENCH',7.50,9.20,-7.84,-7.37),
  rect('WATER_COOLER',10.05,10.43,-7.96,-7.50),
  rect('PALLET_JACK',-17.20,-16.50,2.05,3.75),
  rect('WEST_INBOUND_RACK_01',-17.01,-16.09,-7.48,-5.42),
  rect('WEST_INBOUND_RACK_02',-17.01,-16.09,-4.88,-2.82),
  rect('INBOUND_PALLET_STACK_01',-17.03,-16.21,-.06,1.16),
  rect('INBOUND_PALLET_STACK_02',-15.93,-15.11,-.06,1.16),
  rect('INBOUND_PALLET_STACK_03',-17.03,-16.21,-1.86,-.64),
  rect('INBOUND_PALLET_STACK_04',-15.93,-15.11,-1.86,-.64),
  rect('NW_TOTE_RETURN_RACK',-13.68,-12.12,-8.34,-7.66),
  rect('NW_CHARGING_CABINET',-11.83,-10.87,-8.34,-7.68),
  rect('SHIPPING_MANIFEST_PODIUM',12.95,13.75,1.54,2.16),
  rect('PALLET_STRETCH_WRAPPER',15.07,16.80,.87,2.43),
  rect('SHIPPING_PALLET_01',13.68,14.92,-1.92,-1.08),
  rect('SHIPPING_PALLET_02',15.63,16.87,-1.92,-1.08),
  rect('SHIPPING_PALLET_03',13.68,14.92,-4.07,-3.23),
  rect('SHIPPING_PALLET_04',15.63,16.87,-4.07,-3.23),
  rect('SHIPPING_PALLET_05',13.68,14.92,-6.22,-5.38),
  rect('SHIPPING_PALLET_06',15.63,16.87,-6.22,-5.38),
  ...[-14,-10,-6,-2,2,6,10,14].map(x=>rect(`COL_${x}`,x-.12,x+.12,-8.85,-8.55)),
]);

export const DEFAULT_OBSTACLES=Object.freeze([
  ...BASE_STATIC_OBSTACLES,
  rect('PICK parallel',-7.56,-6.44,-3.18,-2.129),
  rect('PACK parallel 1',-.36,.76,-3.18,-2.129),
  rect('PACK parallel 2',-1.96,-.84,-3.18,-2.129),
  rect('QC parallel',7.04,8.16,-3.18,-2.129),
]);

export function buildObstacles(bindings=DEFAULT_VISUAL_BINDINGS,maxSlots={1:1,2:2,3:3,4:2}) {
  const baseline={1:1,2:2,3:3,4:2};
  const list=[...DEFAULT_OBSTACLES];
  for(const stage of [1,2,3,4]){
    const count=Math.max(baseline[stage],Math.min(8,Number(maxSlots?.[stage])||1));
    for(let i=baseline[stage];i<count;i++)list.push(stageSlotTransform(bindings,stage,i).obstacle);
  }
  return Object.freeze(list);
}

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
const pointInExpanded=(p,o,m)=>p[0]>o.minX-m&&p[0]<o.maxX+m&&p[2]>o.minZ-m&&p[2]<o.maxZ+m;
const distance=(a,b)=>Math.hypot(a[0]-b[0],a[2]-b[2]);
const same=(a,b)=>distance(a,b)<1e-7;
const polylineLength=pts=>{let s=0;for(let i=1;i<pts.length;i++)s+=distance(pts[i-1],pts[i]);return s;};
const routeCache=new Map();
const maskCache=new WeakMap();

const KNOWN_SLOT_APPROACHES=(()=>{
  const out=[];
  for(const s of [1,2,3,4])for(let i=0;i<8;i++){
    const slot=stageSlotTransform(DEFAULT_VISUAL_BINDINGS,s,i);
    out.push({actor:slot.actor,approach:slot.approach});
  }
  out.push({actor:[2.8,0,-1.95],approach:[2.8,0,-1.15]});
  return out;
})();

function resolveApproach(p,obstacles=DEFAULT_OBSTACLES){
  for(const item of KNOWN_SLOT_APPROACHES)if(Math.hypot(p[0]-item.actor[0],p[2]-item.actor[2])<.025)return [...item.approach];
  if(p[2]<-1.35&&p[2]>-2.25){
    const cand=[p[0],p[1],r6(p[2]+.65)];
    if(!obstacles.some(o=>pointInExpanded(cand,o,.17)||segmentHitsObstacle(p,cand,o,pointInExpanded(p,o,.175)?0:.17)))return cand;
  }
  return [...p];
}

class MinHeap {
  constructor(){this.a=[];}
  push(n){const a=this.a;a.push(n);let i=a.length-1;while(i){const p=(i-1)>>1;if(a[p].f<=n.f)break;a[i]=a[p];i=p;}a[i]=n;}
  pop(){const a=this.a,first=a[0],last=a.pop();if(a.length){let i=0;while(i*2+1<a.length){let j=i*2+1;if(j+1<a.length&&a[j+1].f<a[j].f)j++;if(a[j].f>=last.f)break;a[i]=a[j];i=j;}a[i]=last;}return first;}
  get length(){return this.a.length;}
}

export function gridPath(from,to,obstacles=DEFAULT_OBSTACLES) {
  if(same(from,to))return [[...from],[...to]];
  const clearance=.17,step=.2,minX=-17.6,minZ=-8.6,nx=177,nz=87;
  const point=(x,z)=>[r6(minX+x*step),0,r6(minZ+z*step)];
  let mask=maskCache.get(obstacles);
  if(!mask){
    mask=new Uint8Array(nx*nz);
    for(let z=0;z<nz;z++)for(let x=0;x<nx;x++){
      const px=minX+x*step,pz=minZ+z*step;
      if(obstacles.some(o=>px>o.minX-clearance&&px<o.maxX+clearance&&pz>o.minZ-clearance&&pz<o.maxZ+clearance))mask[z*nx+x]=1;
    }
    maskCache.set(obstacles,mask);
  }
  const blocked=(x,z)=>x<0||z<0||x>=nx||z>=nz||mask[z*nx+x]===1;
  const segClear=(a,b)=>!obstacles.some(o=>segmentHitsObstacle(a,b,o,(pointInExpanded(a,o,.175)||pointInExpanded(b,o,.175))?0:clearance));
  if(segClear(from,to))return [[...from],[...to]];
  function nodeFor(p){
    const xx=Math.round((p[0]-minX)/step),zz=Math.round((p[2]-minZ)/step);let best=null;
    for(let r=0;r<=14;r++){
      for(let dx=-r;dx<=r;dx++)for(let dz=-r;dz<=r;dz++){
        if(r&&Math.max(Math.abs(dx),Math.abs(dz))!==r)continue;
        const x=xx+dx,z=zz+dz;if(blocked(x,z))continue;
        const q=point(x,z);
        if(obstacles.some(o=>segmentHitsObstacle(p,q,o,pointInExpanded(p,o,.175)?0:clearance)))continue;
        const d=distance(p,q);if(!best||d<best.d)best={x,z,d};
      }
      if(best)return best;
    }
    for(let r=0;r<=14;r++){
      for(let dx=-r;dx<=r;dx++)for(let dz=-r;dz<=r;dz++){
        if(r&&Math.max(Math.abs(dx),Math.abs(dz))!==r)continue;
        const x=xx+dx,z=zz+dz;if(blocked(x,z))continue;
        const q=point(x,z);if(obstacles.some(o=>segmentHitsObstacle(p,q,o,0)))continue;
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
  const simple=[points[0]];let i=0;
  while(i<points.length-1){let j=points.length-1;while(j>i+1&&!segClear(points[i],points[j]))j--;simple.push(points[j]);i=j;}
  return simple;
}

export function planWalkPath(from,to,{obstacles=DEFAULT_OBSTACLES}={}) {
  if(!from?.every(Number.isFinite)||!to?.every(Number.isFinite))throw new Error('Invalid walk endpoints');
  const cacheKey=obstacles===DEFAULT_OBSTACLES?JSON.stringify([from,to]):null;
  if(cacheKey&&routeCache.has(cacheKey))return routeCache.get(cacheKey).map(p=>[...p]);
  if(same(from,to))return [[...from],[...to]];
  const north=p=>p[2]<-.6,aisleZ=-5.4,eastX=11.4,westX=-13.6;
  const clampAisleX=x=>r6(Math.max(westX,Math.min(eastX,x)));
  const a=resolveApproach(from,obstacles),b=resolveApproach(to,obstacles),rawPivots=[[...from],a];
  if(north(from)&&north(to)){
    const sameNorthBay=a[2]<-7.0&&b[2]<-7.0&&Math.abs(a[0]-b[0])<3.5;
    let shortDirect=false;
    if(distance(a,b)<4.5){
      try{
        const directPts=gridPath(a,b,obstacles);
        if(polylineLength(directPts)<4.5)shortDirect=true;
      }catch{shortDirect=false;}
    }
    if(!sameNorthBay&&!shortDirect)rawPivots.push([clampAisleX(a[0]),0,aisleZ],[clampAisleX(b[0]),0,aisleZ]);
  }else if(north(from)!==north(to)){
    const east=distance(a,[eastX,0,a[2]])+distance(b,[eastX,0,b[2]])<=distance(a,[westX,0,a[2]])+distance(b,[westX,0,b[2]]);
    const x=east?eastX:westX;
    if(north(from)){
      const ax=clampAisleX(a[0]);
      if(Math.abs(a[0]-x)>1.2)rawPivots.push([ax,0,aisleZ],[x,0,aisleZ]);
      rawPivots.push([x,0,-1.0],[x,0,1.0]);
    }else{
      const bx=clampAisleX(b[0]);
      rawPivots.push([x,0,1.0],[x,0,-1.0]);
      if(Math.abs(b[0]-x)>1.2)rawPivots.push([x,0,aisleZ],[bx,0,aisleZ]);
    }
  }
  rawPivots.push(b,[...to]);
  const pivots=[];
  for(const p of rawPivots)if(!pivots.length||!same(pivots.at(-1),p))pivots.push(p);
  const points=[];
  for(let i=0;i<pivots.length-1;i++){
    const p=pivots[i],q=pivots[i+1];
    const endpointLeg=(i===0&&!same(from,a))||(i===pivots.length-2&&!same(b,to));
    let segment;
    if(endpointLeg&&!obstacles.some(o=>segmentHitsObstacle(p,q,o,(pointInExpanded(p,o,.175)||pointInExpanded(q,o,.175))?0:.17)))segment=[[...p],[...q]];
    else segment=gridPath(p,q,obstacles);
    for(const item of segment)if(!points.length||!same(points.at(-1),item))points.push(item);
  }
  if(points.length===1)points.push([...to]);
  if(cacheKey){if(routeCache.size>2000)routeCache.clear();routeCache.set(cacheKey,points);}
  return points.map(p=>[...p]);
}
export const planWalkRoute=planWalkPath;

const orderHeight=o=>(ORDER_SIZES[o?.kind]||ORDER_SIZES.regular)[2]+(o?.tray ? .012 : 0);
export function queueStackPositions(bindings,queue,orders,{maxLayers=3}={}) {
  const b=bindings||DEFAULT_VISUAL_BINDINGS;
  const q=b.queues[queue];if(!q)throw new Error('Unknown queue '+queue);
  const items=Array.isArray(orders)?orders:[];
  const bounded=q.bounded,base=bounded?items.length:q.preview_count;
  const visibleOrders=items.slice(0,bounded?items.length:base*maxLayers),positions=[];
  const layers=[];let y=q.origin_gltf_m[1];
  for(let layer=0;layer<Math.ceil(visibleOrders.length/(base||1));layer++){
    const chunk=visibleOrders.slice(layer*base,(layer+1)*base);layers.push(y);y+=Math.max(...chunk.map(orderHeight),0)+.015;
  }
  visibleOrders.forEach((o,i)=>{
    const cell=bounded?i:i%base,layer=bounded?0:Math.floor(i/base);
    positions.push([r6(q.origin_gltf_m[0]+cell%q.columns*q.spacing[0]),r6(layers[layer]??q.origin_gltf_m[1]),r6(q.origin_gltf_m[2]-Math.floor(cell/q.columns)*q.spacing[1])]);
  });
  return {positions,visibleOrders,overflow:items.length-visibleOrders.length};
}

export function outcomeStackPositions(bindings,outcome,orders,{maxVisible=outcome==='scrap'?8:12}={}) {
  const b=bindings||DEFAULT_VISUAL_BINDINGS;
  const q=b.outcomes[outcome];if(!q)throw new Error('Unknown outcome '+outcome);
  const items=Array.isArray(orders)?orders:[];
  const startIdx=Math.max(0,items.length-maxVisible);
  const visibleOrders=items.slice(startIdx);
  const layerStep=.346;
  const positions=visibleOrders.map((o,vIdx)=>{
    const slot=(startIdx+vIdx)%maxVisible;
    const corner=slot%4,layer=Math.floor(slot/4);
    return [
      r6(q.position_gltf_m[0]+(corner%2?.28:-.28)),
      r6(q.position_gltf_m[1]+layer*layerStep),
      r6(q.position_gltf_m[2]+(Math.floor(corner/2)?.20:-.20)),
    ];
  });
  return {positions,visibleOrders,overflow:items.length-visibleOrders.length};
}

export function scrapStationPositions(bindings,orders,{maxVisible=8}={}) {
  const b=bindings||DEFAULT_VISUAL_BINDINGS;
  const bin=b.outcomes?.scrap?.position_gltf_m||[7.2,.02,7.0];
  const items=Array.isArray(orders)?orders:[];
  const startIdx=Math.max(0,items.length-maxVisible);
  const visibleOrders=items.slice(startIdx);
  const benchSlots=[[8.38,.860,6.20],[8.92,.860,6.20],[8.38,.860,6.50],[8.92,.860,6.50]];
  const binOffsets=[[-.28,-.20],[.28,-.20],[-.28,.20],[.28,.20]];
  const positions=visibleOrders.map((o,vIdx)=>{
    const slot=(startIdx+vIdx)%maxVisible;
    if(slot<4){
      const s=benchSlots[slot];
      return [r6(s[0]),r6(s[1]),r6(s[2])];
    }
    const bIdx=slot-4,off=binOffsets[bIdx%4],layer=Math.floor(bIdx/4);
    return [r6(bin[0]+off[0]),r6(.28+layer*.346),r6(bin[2]+off[1])];
  });
  return {positions,visibleOrders,overflow:items.length-visibleOrders.length};
}

export function buildWorkerPresentationPlan(replay,bindings=DEFAULT_VISUAL_BINDINGS) {
  const b=bindings||DEFAULT_VISUAL_BINDINGS;
  const histories={},activities=new Map(),occupied={1:new Map(),2:new Map(),3:new Map(),4:new Map()};
  const zones={},slots={},lastPosition={},maxSlots={1:1,2:1,3:1,4:1},rawActivities=[];
  function assign(id,zone){
    let index=0;while([...occupied[zone].values()].includes(index))index++;
    occupied[zone].set(id,index);maxSlots[zone]=Math.max(maxSlots[zone],index+1);return index;
  }
  replay.manifest.plan.workers.forEach((zonesList,i)=>{
    const id='w'+i,zone=zonesList[0];zones[id]=zone;slots[id]=assign(id,zone);
    lastPosition[id]=actorPosition(b,zone,slots[id]);
    histories[id]=[{tick:-1,stage:zone,index:slots[id],position:[...lastPosition[id]]}];
  });
  const walks=new Map(replay.events.filter(e=>e.kind==='walk').map(e=>[e.resource+':'+e.tick,e]));
  const assistTarget=robotAssistPosition(b);
  const clock=replay.manifest.world.clock,H=clock.shift_ticks+clock.overtime_ticks;
  const workerSchedule=new Map();
  for(const e of replay.events){
    if(/^w\d+$/.test(e.resource||'')&&['start','assist','break'].includes(e.kind)){
      if(!workerSchedule.has(e.resource))workerSchedule.set(e.resource,[]);
      workerSchedule.get(e.resource).push(e);
    }
  }
  const nextBusyAfter=(id,afterTick)=>{
    for(const ev of workerSchedule.get(id)||[])if(ev.tick>=afterTick-1e-6)return ev.tick;
    return Infinity;
  };
  for(const e of replay.events){
    if(!/^w\d+$/.test(e.resource||'')||!['start','assist','break'].includes(e.kind))continue;
    const id=e.resource,zone=e.stage??zones[id],from=[...lastPosition[id]];
    if(e.kind!=='break'&&zone!==zones[id]){
      occupied[zones[id]].delete(id);zones[id]=zone;slots[id]=assign(id,zone);
      histories[id].push({tick:e.tick,stage:zone,index:slots[id],position:actorPosition(b,zone,slots[id])});
    }
    const kind=e.kind==='start'?'work':e.kind;
    const to=e.kind==='break'?breakPosition(Number(id.slice(1))):e.kind==='assist'?[...assistTarget]:actorPosition(b,zone,slots[id]);
    const duration=e.end_tick-e.tick,walk=walks.get(id+':'+e.tick);
    if(e.kind==='break'){
      const travelTicks=distance(from,to)<1e-7?0:Math.min(2.6,duration*.42);
      const returnTo=actorPosition(b,zone,slots[id]);
      const returnTicks=distance(to,returnTo)<1e-7?0:Math.min(2.6,duration*.42);
      rawActivities.push({key:id+':'+kind+':'+e.tick,kind,startTick:e.tick,endTick:e.end_tick,stage:zone,index:slots[id],from,to,travelTicks,returnTo,returnTicks,attempt:e.attempt,orderId:e.order_id});
      lastPosition[id]=[...returnTo];
    }else if(e.kind==='assist'){
      const travelTicks=distance(from,to)<1e-7?0:walk?walk.end_tick-e.tick:Math.min(2.2,duration*.35);
      const returnTo=actorPosition(b,zone,slots[id]);
      const nextTick=nextBusyAfter(id,e.end_tick+1e-4);
      const idleWindow=Math.min(H,nextTick)-e.end_tick;
      const retDist=distance(to,returnTo);
      const minRet=retDist/11.5;
      const returnTicks=(retDist>1e-5&&idleWindow>=Math.max(.35,minRet))?Math.min(2.2,idleWindow,Math.max(.55,retDist/9.5)):0;
      rawActivities.push({key:id+':'+kind+':'+e.tick,kind,startTick:e.tick,endTick:e.end_tick,stage:zone,index:slots[id],from,to,travelTicks,returnTo,returnTicks,attempt:e.attempt,orderId:e.order_id});
      lastPosition[id]=returnTicks>0?[...returnTo]:[...to];
    }else{
      const travelTicks=distance(from,to)<1e-7?0:walk?walk.end_tick-e.tick:Math.min(2.4,duration*.38);
      rawActivities.push({key:id+':'+kind+':'+e.tick,kind,startTick:e.tick,endTick:e.end_tick,stage:zone,index:slots[id],from,to,travelTicks,attempt:e.attempt,orderId:e.order_id});
      lastPosition[id]=[...to];
    }
  }
  const obstacles=buildObstacles(b,maxSlots);
  for(const item of rawActivities){
    const path=item.travelTicks>0?planWalkPath(item.from,item.to,{obstacles}):[[...item.to],[...item.to]];
    if(item.kind==='break'||item.kind==='assist'){
      const returnPath=item.returnTicks>0?planWalkPath(item.to,item.returnTo,{obstacles}):[[...item.returnTo],[...item.returnTo]];
      activities.set(item.key,{kind:item.kind,startTick:item.startTick,endTick:item.endTick,stage:item.stage,index:item.index,from:item.from,to:item.to,path,travelTicks:item.travelTicks,returnTo:item.returnTo,returnTicks:item.returnTicks,returnPath,attempt:item.attempt,orderId:item.orderId});
    }else{
      activities.set(item.key,{kind:item.kind,startTick:item.startTick,endTick:item.endTick,stage:item.stage,index:item.index,from:item.from,to:item.to,path,travelTicks:item.travelTicks,attempt:item.attempt,orderId:item.orderId});
    }
  }
  return {histories,activities,maxSlots,obstacles,slotAt(id,tick){
    const list=histories[id];if(!list)throw new Error('Unknown worker '+id);
    let found=list[0];for(const entry of list){if(entry.tick>tick)break;found=entry;}return found;
  }};
}

export const cleanNum=v=>{const n=Number(v);return !Number.isFinite(n)||n===0?0:n;};
const cleanVec3=p=>[cleanNum(p[0]),cleanNum(p[1]),cleanNum(p[2])];
const dist3=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1],a[2]-b[2]);
const lerpAngle=(a,b,t)=>cleanNum(a+Math.atan2(Math.sin(b-a),Math.cos(b-a))*t);
const smooth01=x=>{const c=Math.min(1,Math.max(0,x));return c*c*(3-2*c);};
const OPERATION_BY_STAGE=Object.freeze({1:'prepare',2:'pick',3:'pack',4:'inspect'});
const QUEUE_VISIBLE_MAX=Object.freeze({Q1:18,Q2:12,Q3:10,Q4:8,R:18});

function compilePolyline(rawPoints,fallbackYaw=0,startYaw=null,endYaw=null){
  const raw=[];
  for(const p of rawPoints){
    const c=cleanVec3(p);
    if(!raw.length||dist3(raw.at(-1),c)>1e-6)raw.push(c);
  }
  const pts=[];
  if(raw.length){
    pts.push(raw[0]);
    const endPt=raw.at(-1);
    for(let i=1;i<raw.length-1;i++){
      if(dist3(pts.at(-1),raw[i])>=.60&&dist3(raw[i],endPt)>=.60)pts.push(raw[i]);
    }
    if(raw.length>1)pts.push(endPt);
  }
  if(!pts.length)pts.push([0,0,0],[0,0,0]);
  else if(pts.length===1)pts.push([...pts[0]]);
  const seg=[],cum=[0],segYaw=[];let total=0;
  for(let i=1;i<pts.length;i++){
    const d=dist3(pts[i-1],pts[i]);seg.push(d);total+=d;cum.push(total);
    const dx=pts[i][0]-pts[i-1][0],dz=pts[i][2]-pts[i-1][2];
    segYaw.push(Math.hypot(dx,dz)>1e-6?cleanNum(Math.atan2(dx,dz)):NaN);
  }
  let lastValid=cleanNum(fallbackYaw);
  for(let i=0;i<segYaw.length;i++){if(Number.isFinite(segYaw[i]))lastValid=segYaw[i];else segYaw[i]=lastValid;}
  for(let i=segYaw.length-2;i>=0;i--){if(!Number.isFinite(segYaw[i]))segYaw[i]=segYaw[i+1];}
  return {
    points:pts,seg,cum,segYaw,
    totalLength:cleanNum(total),
    fallbackYaw:cleanNum(fallbackYaw),
    startYaw:Number.isFinite(startYaw)?cleanNum(startYaw):null,
    endYaw:Number.isFinite(endYaw)?cleanNum(endYaw):null,
  };
}

function sampleCompiledPolyline(poly,u){
  const pts=poly.points;
  if(poly.totalLength<=1e-8)return {position:[...pts.at(-1)],yaw:poly.endYaw??poly.startYaw??poly.fallbackYaw};
  const clamped=Math.min(1,Math.max(0,u)),target=clamped*poly.totalLength;
  let idx=0;
  while(idx<poly.seg.length-1&&poly.cum[idx+1]<target)idx++;
  const len=poly.seg[idx],a=pts[idx],b=pts[idx+1];
  const f=len>1e-9?Math.min(1,Math.max(0,(target-poly.cum[idx])/len)):1;
  const pos=[cleanNum(a[0]+(b[0]-a[0])*f),cleanNum(a[1]+(b[1]-a[1])*f),cleanNum(a[2]+(b[2]-a[2])*f)];
  let yaw=poly.segYaw[idx]??poly.fallbackYaw;
  for(let k=1;k<pts.length-1;k++){
    const sk=poly.cum[k],rk=Math.min(.55,.49*poly.seg[k-1],.49*poly.seg[k]);
    if(rk>1e-5&&Math.abs(target-sk)<rk){
      yaw=lerpAngle(poly.segYaw[k-1],poly.segYaw[k],smooth01((target-(sk-rk))/(2*rk)));
      break;
    }
  }
  const endBlend=Math.min(1.20,.5*poly.totalLength);
  if(poly.startYaw!==null&&endBlend>1e-5&&target<endBlend){
    yaw=lerpAngle(poly.startYaw,yaw,smooth01(target/endBlend));
  }
  if(poly.endYaw!==null&&endBlend>1e-5&&target>poly.totalLength-endBlend){
    yaw=lerpAngle(yaw,poly.endYaw,smooth01((target-(poly.totalLength-endBlend))/endBlend));
  }
  return {position:pos,yaw};
}

function handCarryCoords(pos,yaw,tray=false){
  return [cleanNum(pos[0]+Math.sin(yaw)*.32),cleanNum(.85+(tray?.012:0)),cleanNum(pos[2]+Math.cos(yaw)*.32)];
}

function walkToCarryPoints(walkPts,tray=false){
  const out=[];
  for(let i=0;i<walkPts.length;i++){
    const p=walkPts[i];
    const next=walkPts[Math.min(walkPts.length-1,i+1)],prev=walkPts[Math.max(0,i-1)];
    const dx=next[0]-prev[0],dz=next[2]-prev[2];
    const yaw=Math.hypot(dx,dz)>1e-6?Math.atan2(dx,dz):0;
    out.push(handCarryCoords(p,yaw,tray));
  }
  return out;
}

function mergeIntervals(raw){
  if(!raw.length)return {intervals:[],prefix:[0]};
  const sorted=raw.filter(([a,b])=>b>a+1e-7).sort((u,v)=>u[0]-v[0]||u[1]-v[1]);
  if(!sorted.length)return {intervals:[],prefix:[0]};
  const intervals=[[sorted[0][0],sorted[0][1]]];
  for(let i=1;i<sorted.length;i++){
    const [a,b]=sorted[i],last=intervals.at(-1);
    if(a<=last[1]+1e-6)last[1]=Math.max(last[1],b);
    else intervals.push([a,b]);
  }
  const prefix=[0];
  for(const [a,b] of intervals)prefix.push(prefix.at(-1)+(b-a));
  return {intervals,prefix};
}

function evalActiveIntervals(compiled,t){
  const {intervals,prefix}=compiled;
  if(!intervals.length||t<=intervals[0][0])return {active:false,elapsed:0};
  let lo=0,hi=intervals.length-1,idx=-1;
  while(lo<=hi){
    const mid=(lo+hi)>>1;
    if(intervals[mid][0]<=t){idx=mid;lo=mid+1;}else hi=mid-1;
  }
  if(idx<0)return {active:false,elapsed:0};
  const [a,b]=intervals[idx];
  if(t<b)return {active:true,elapsed:prefix[idx]+(t-a)};
  return {active:false,elapsed:prefix[idx+1]};
}

export function buildFlowPlan(manifest,events,bindings=DEFAULT_VISUAL_BINDINGS,presentation=null){
  const b=bindings||DEFAULT_VISUAL_BINDINGS;
  const clock=manifest.world.clock,H=clock.shift_ticks+clock.overtime_ticks;
  const pres=presentation||buildWorkerPresentationPlan({manifest,events},b);
  const obstacles=pres.obstacles||buildObstacles(b,pres.maxSlots);
  const assistYaw=robotAssistYaw(b);
  const robotPos=[...(b.robot?.position_gltf_m||[3.5,0,-2.05])];
  const robotOrderBase=[...(b.robot?.order_position_gltf_m||[3.5,.86,-2.39])];

  const orderEvents=new Map(),workerEvents=new Map();
  for(const o of manifest.scenario.orders)orderEvents.set(o.id,[]);
  manifest.plan.workers.forEach((_,i)=>workerEvents.set('w'+i,[]));
  for(const e of events){
    if(e.order_id!==null&&orderEvents.has(e.order_id))orderEvents.get(e.order_id).push(e);
    if(e.resource&&workerEvents.has(e.resource)&&['start','assist','break'].includes(e.kind))workerEvents.get(e.resource).push(e);
  }

  const nextStartTickFor=(id,afterIdx)=>{
    const list=orderEvents.get(id)||[];
    for(let i=afterIdx+1;i<list.length;i++)if(list[i].kind==='start')return list[i].tick;
    return Infinity;
  };
  const nextWorkerBusyTick=(wId,afterTick)=>{
    const list=workerEvents.get(wId)||[];
    for(const e of list)if(e.tick>=afterTick)return e.tick;
    return Infinity;
  };

  const orderMeta=Object.fromEntries(manifest.scenario.orders.map(o=>[o.id,{id:o.id,kind:o.kind,tray:false}]));
  const orderAttempt=Object.fromEntries(manifest.scenario.orders.map(o=>[o.id,0]));
  const queues={Q1:[],Q2:[],Q3:[],Q4:[],R:[]};
  const outcomes={good:[],escaped:[],scrap:[]};
  const transits=[];
  const workerPhases={};
  const workerActualPos={};
  const workerActualYaw={};
  const activeReworkSpans=[];
  manifest.plan.workers.forEach((zonesList,i)=>{
    const wId='w'+i;
    workerPhases[wId]=[];
    const initEntry=pres.slotAt(wId,-1);
    const initSlot=stageSlotTransform(b,initEntry.stage,initEntry.index);
    workerActualPos[wId]=[...initSlot.actor];
    workerActualYaw[wId]=initSlot.yaw;
  });
  const robotPhases=[];
  const qcDwellIntervals=[];
  const activeWorkOrders={};
  const allWorkRecords=[];
  const workerBusyUntil={};
  const activeRobotOrder={current:null};
  const queueArrivalEnd={};
  const lastScheduledPos={};

  function visibleLimitForQueue(qName){
    const q=b.queues[qName];
    if(!q)return 18;
    return q.bounded?(QUEUE_VISIBLE_MAX[qName]??q.preview_count):(q.preview_count*3);
  }

  function currentQueuePos(qName,id){
    const list=queues[qName];
    const idx=list.indexOf(id);
    if(idx<0)return [...b.queues[qName].origin_gltf_m];
    const {positions}=queueStackPositions(b,qName,list.map(oid=>orderMeta[oid]));
    if(!positions.length)return [...b.queues[qName].origin_gltf_m];
    const base=positions[Math.min(idx,positions.length-1)];
    return [base[0],cleanNum(base[1]+(orderMeta[id]?.tray?.012:0)),base[2]];
  }

  function currentOutcomePos(kind,id){
    const list=outcomes[kind];
    const {positions,visibleOrders}=kind==='scrap'
      ?scrapStationPositions(b,list.map(oid=>orderMeta[oid]))
      :outcomeStackPositions(b,kind,list.map(oid=>orderMeta[oid]));
    const vIdx=visibleOrders.findIndex(o=>o.id===id);
    const base=vIdx>=0?positions[vIdx]:(positions.at(-1)||[...b.outcomes[kind].position_gltf_m]);
    return [base[0],cleanNum(base[1]),base[2]];
  }

  function addTransit({orderId,t0,t1,points,mode='conveyor',actorId=null,fallbackYaw=0,startYaw=null,endYaw=null,suppressPropCarton=false,hideTray=false,showTray=null,trayAdjusted=true,scrapBadged=false}){
    const rawT0=cleanNum(Math.max(0,t0)),rawT1=cleanNum(t1);
    const start=rawT0,end=cleanNum(Math.min(H,rawT1));
    if(end<=start+1e-6)return null;
    const truncatedAtHorizon=rawT1>H+1e-6;
    const poly=compilePolyline(points,fallbackYaw,startYaw,endYaw);
    const resolvedShowTray=showTray!==null?Boolean(showTray):(!hideTray&&Boolean(orderMeta[orderId]?.tray));
    const item={
      orderId,t0:start,t1:end,rawT0,rawT1,truncatedAtHorizon,poly,mode,actorId,
      suppressPropCarton:Boolean(suppressPropCarton),
      hideTray:!resolvedShowTray,
      showTray:resolvedShowTray,
      trayAdjusted:Boolean(trayAdjusted),
      scrapBadged:Boolean(scrapBadged),
    };
    transits.push(item);
    return item;
  }

  function addWorkerPhase(wId,phase){
    const rawT0=cleanNum(Math.max(0,phase.t0)),rawT1=cleanNum(phase.t1);
    const t0=rawT0,t1=cleanNum(Math.min(H,rawT1));
    if(t1<=t0+1e-6)return;
    workerPhases[wId].push({...phase,t0,t1,rawT0,rawT1,truncatedAtHorizon:rawT1>H+1e-6});
  }

  function addRobotPhase(phase){
    const rawT0=cleanNum(Math.max(0,phase.t0)),rawT1=cleanNum(phase.t1);
    const t0=rawT0,t1=cleanNum(Math.min(H,rawT1));
    if(t1<=t0+1e-6)return;
    robotPhases.push({...phase,t0,t1,rawT0,rawT1,truncatedAtHorizon:rawT1>H+1e-6});
  }

  const orderIdxCursor=new Map(manifest.scenario.orders.map(o=>[o.id,-1]));
  const advanceCursor=(id,ev)=>{
    const list=orderEvents.get(id)||[];
    let c=orderIdxCursor.get(id)??-1;
    while(c+1<list.length&&list[c+1].eventIndex<=ev.eventIndex)c++;
    orderIdxCursor.set(id,c);
    return c;
  };

  for(const ev of events){
    if(ev.kind==='break'){
      const wId=ev.resource,act=pres.activities.get(`${wId}:break:${ev.tick}`);
      if(!act)continue;
      const t0=ev.tick,t1=ev.end_tick;
      const fromPos=workerActualPos[wId]||act.from,fromYaw=workerActualYaw[wId]??Math.PI;
      const outPath=distance(fromPos,act.from)>1e-4?planWalkPath(fromPos,act.to,{obstacles}):act.path;
      const outEnd=t0+(outPath.length>=2&&distance(outPath[0],outPath.at(-1))>1e-6?Math.max(act.travelTicks,Math.min(3.2,polylineLength(outPath)/10.8)):0);
      const retStart=t1-act.returnTicks;
      if(outEnd>t0+1e-6)addWorkerPhase(wId,{t0,t1:outEnd,state:'walk',poly:compilePolyline(outPath,0,fromYaw,0),orderId:null,tray:false});
      if(retStart>outEnd+1e-6)addWorkerPhase(wId,{t0:outEnd,t1:retStart,state:'break',position:[...act.to],yaw:0,orderId:null,tray:false});
      if(act.returnTicks>1e-6){
        const slot=stageSlotTransform(b,act.stage,act.index);
        addWorkerPhase(wId,{t0:retStart,t1,state:'walk',poly:compilePolyline(act.returnPath,slot.yaw,0,slot.yaw),orderId:null,tray:false});
        workerActualPos[wId]=[...slot.actor];workerActualYaw[wId]=slot.yaw;
      }else{
        workerActualPos[wId]=[...act.to];workerActualYaw[wId]=0;
      }
      workerBusyUntil[wId]=Math.max(workerBusyUntil[wId]??0,t1);
      continue;
    }

    if(ev.kind==='assist'){
      const wId=ev.resource,act=pres.activities.get(`${wId}:assist:${ev.tick}`);
      if(!act)continue;
      const t0=ev.tick,t1=ev.end_tick;
      const fromPos=workerActualPos[wId]||act.from,fromYaw=workerActualYaw[wId]??Math.PI;
      const aPath=distance(fromPos,act.from)>1e-4?planWalkPath(fromPos,act.to,{obstacles}):act.path;
      const walkTicks=distance(fromPos,act.to)<1e-6?0:Math.min(Math.max(.35,(t1-t0)*.48),Math.max(act.travelTicks,polylineLength(aPath)/10.8));
      const walkEnd=t0+walkTicks;
      if(walkTicks>1e-6)addWorkerPhase(wId,{t0,t1:walkEnd,state:'walk',poly:compilePolyline(aPath,assistYaw,fromYaw,assistYaw),orderId:ev.order_id,tray:Boolean(orderMeta[ev.order_id]?.tray)});
      addWorkerPhase(wId,{t0:walkEnd,t1,state:'assist',position:[...act.to],yaw:assistYaw,orderId:ev.order_id,tray:Boolean(orderMeta[ev.order_id]?.tray)});
      if(act.returnTicks>1e-6){
        const slot=stageSlotTransform(b,act.stage,act.index);
        addWorkerPhase(wId,{t0:t1,t1:t1+act.returnTicks,state:'walk',poly:compilePolyline(act.returnPath,slot.yaw,assistYaw,slot.yaw),orderId:null,tray:false});
        workerActualPos[wId]=[...slot.actor];workerActualYaw[wId]=slot.yaw;
        workerBusyUntil[wId]=Math.max(workerBusyUntil[wId]??0,t1+act.returnTicks);
      }else{
        workerActualPos[wId]=[...act.to];workerActualYaw[wId]=assistYaw;
        workerBusyUntil[wId]=Math.max(workerBusyUntil[wId]??0,t1);
      }
      if(activeRobotOrder.current&&activeRobotOrder.current.orderId===ev.order_id){
        const ro=activeRobotOrder.current;
        if(walkEnd>ev.tick+1e-6)addRobotPhase({t0:ev.tick,t1:walkEnd,state:'helper_walking',orderId:ro.orderId,tray:ro.tray});
        addRobotPhase({t0:walkEnd,t1,state:'service',orderId:ro.orderId,tray:ro.tray});
        ro.servicedEndTick=t1;
      }
      continue;
    }

    const id=ev.order_id;
    if(id===null||!orderMeta[id])continue;
    const curIdx=advanceCursor(id,ev);
    const meta=orderMeta[id];

    if(ev.kind==='enqueue'){
      const qName=ev.stage===3&&ev.attempt===1?'R':'Q'+ev.stage;
      queues[qName].push(id);
      const qIdxArr=queues[qName].length-1;
      const visLim=visibleLimitForQueue(qName);
      const qPos=currentQueuePos(qName,id);
      const tNext=nextStartTickFor(id,curIdx);

      if(qName==='Q1'){
        if(qIdxArr>=visLim){
          queueArrivalEnd[id]=ev.tick;
          lastScheduledPos[id]=[...qPos];
        }else{
          const fullDockPts=[[-17.35,.15,5.15],[-14.40,.15,5.15],[-14.40,.15,qPos[2]],qPos];
          const shortApronPts=[[-13.40,.15,qPos[2]],qPos];
          const midApronPts=[[-14.40,.15,1.80],[-14.40,.15,qPos[2]],qPos];
          const waitBudget=tNext===Infinity?Infinity:(tNext-ev.tick)+1.85;
          let pts=fullDockPts;
          let totalLen=compilePolyline(pts,0).totalLength;
          let dur=Math.max(1.85,totalLen/10.5);
          if(waitBudget<dur){
            pts=midApronPts;totalLen=compilePolyline(pts,0).totalLength;dur=Math.max(1.05,totalLen/10.5);
            if(waitBudget<dur){
              pts=shortApronPts;totalLen=compilePolyline(pts,0).totalLength;dur=Math.max(.55,totalLen/10.5);
            }
          }
          const rawEnd=ev.tick+dur;
          addTransit({orderId:id,t0:ev.tick,t1:rawEnd,points:pts,mode:'dock_infeed',fallbackYaw:0,showTray:false,trayAdjusted:true});
          queueArrivalEnd[id]=Math.min(H,rawEnd);
          lastScheduledPos[id]=[...qPos];
        }
      }else if(qName==='Q2'){
        const prev=activeWorkOrders[id];
        const s1Slot=prev?.slot||stageSlotTransform(b,1,0);
        const s1Ord=[s1Slot.order[0],.86,s1Slot.order[2]];
        const leadPts=(s1Slot.index>=1||s1Ord[2]<-1.8||s1Ord[0]<-11.5)
          ?[s1Ord,[-10.35,.86,Math.max(-1.65,s1Ord[2]*.45-.65)],[-10.15,.86,-.95],[-9.55,.86,-.25],[-9.00,.86,0]]
          :[s1Ord,[-10.15,.86,-.95],[-9.55,.86,-.25],[-9.00,.86,0]];
        const leadLen=compilePolyline(leadPts,0).totalLength;
        const maxLead=prev?Math.max(.26,(ev.tick-prev.workReadyTick)*.55):.75;
        const leadDur=Math.min(maxLead,Math.max(.32,leadLen/10.8));
        if(prev){prev.leadOutStart=ev.tick-leadDur;}
        addTransit({orderId:id,t0:ev.tick-leadDur,t1:ev.tick,points:leadPts,mode:'conveyor',fallbackYaw:0,showTray:false,trayAdjusted:true});
        const inPts=[[-9.00,.86,0],[-6.46,.86,0],[-6.46,.86,2.06],[qPos[0],.86,2.06],qPos];
        const inLen=compilePolyline(inPts,0).totalLength;
        const dur=Math.max(.65,inLen/10.8);
        const rawEnd=ev.tick+dur;
        addTransit({orderId:id,t0:ev.tick,t1:rawEnd,points:inPts,mode:'conveyor',fallbackYaw:0,showTray:false,trayAdjusted:true});
        queueArrivalEnd[id]=Math.min(H,rawEnd);
        lastScheduledPos[id]=[...qPos];
      }else if(qName==='Q3'){
        const prev=activeWorkOrders[id];
        const s2Slot=prev?.slot||stageSlotTransform(b,2,0);
        const s2Ord=[s2Slot.order[0],.86,s2Slot.order[2]];
        const leadPts=[s2Ord,[-4.27,.86,-.89],[-4.27,.86,0]];
        const leadLen=compilePolyline(leadPts,0).totalLength;
        const maxLead=prev?Math.max(.28,(ev.tick-prev.workReadyTick)*.55):.85;
        const leadDur=Math.min(maxLead,Math.max(.34,leadLen/10.8));
        if(prev){prev.leadOutStart=ev.tick-leadDur;}
        addTransit({orderId:id,t0:ev.tick-leadDur,t1:ev.tick,points:leadPts,mode:'conveyor',fallbackYaw:0,showTray:false,trayAdjusted:true});
        const inPts=[[-4.27,.86,0],[.42,.86,0],[.42,.86,2.06],[qPos[0],.86,2.06],qPos];
        const inLen=compilePolyline(inPts,0).totalLength;
        const dur=Math.max(.75,inLen/10.8);
        const rawEnd=ev.tick+dur;
        addTransit({orderId:id,t0:ev.tick,t1:rawEnd,points:inPts,mode:'conveyor',fallbackYaw:0,showTray:false,trayAdjusted:true});
        queueArrivalEnd[id]=Math.min(H,rawEnd);
        lastScheduledPos[id]=[...qPos];
      }else if(qName==='Q4'){
        const prev=activeWorkOrders[id];
        const isRobot=prev?.isRobot;
        const isRework=Boolean(prev?.isRework);
        const trayY=cleanNum(.86+(meta.tray?.012:0));
        if(isRework){
          const rwOrd=prev.reworkBenchOrderPos||[1.80,trayY,6.35];
          const rwPts=[rwOrd,[.40,trayY,5.55],[.40,trayY,0],[6.44,trayY,0],[6.44,trayY,2.06],[qPos[0],trayY,2.06],qPos];
          const rwLen=compilePolyline(rwPts,Math.PI).totalLength;
          const leadDur=Math.min(.22,Math.max(.15,(ev.tick-prev.workReadyTick)*.20));
          prev.leadOutStart=ev.tick-leadDur;
          const rawEnd=ev.tick-leadDur+Math.max(1.35,rwLen/11.5);
          addTransit({orderId:id,t0:ev.tick-leadDur,t1:rawEnd,points:rwPts,mode:'conveyor',fallbackYaw:Math.PI,showTray:Boolean(meta.tray),trayAdjusted:true});
          queueArrivalEnd[id]=Math.min(H,rawEnd);
          lastScheduledPos[id]=[...qPos];
          const wId=prev.workerId;
          if(wId){
            const nextBusy=nextWorkerBusyTick(wId,ev.tick);
            const idleWindow=Math.min(H,nextBusy)-ev.tick;
            const homeSlot=prev.slot||stageSlotTransform(b,3,0);
            const retPts=planWalkPath(prev.reworkBenchActor||[1.80,0,5.55],homeSlot.actor,{obstacles});
            const retDur=Math.max(1.45,polylineLength(retPts)/10.8);
            if(idleWindow>=retDur+.05){
              addWorkerPhase(wId,{t0:ev.tick,t1:ev.tick+retDur,state:'walk',poly:compilePolyline(retPts,homeSlot.yaw,0,homeSlot.yaw),orderId:null,tray:false});
              workerActualPos[wId]=[...homeSlot.actor];workerActualYaw[wId]=homeSlot.yaw;
              workerBusyUntil[wId]=Math.max(workerBusyUntil[wId]??0,ev.tick+retDur);
            }
          }
        }else{
          if(!isRobot){
            const s3Slot=prev?.slot||stageSlotTransform(b,3,0);
            const s3Ord=[s3Slot.order[0],trayY,s3Slot.order[2]];
            const leadPts=[s3Ord,[.96,trayY,-.89],[.96,trayY,0]];
            const leadLen=compilePolyline(leadPts,0).totalLength;
            const maxLead=prev?Math.max(.28,(ev.tick-prev.workReadyTick)*.55):.85;
            const leadDur=Math.min(maxLead,Math.max(.34,leadLen/10.8));
            if(prev){prev.leadOutStart=ev.tick-leadDur;}
            addTransit({orderId:id,t0:ev.tick-leadDur,t1:ev.tick,points:leadPts,mode:'conveyor',fallbackYaw:0,showTray:Boolean(meta.tray),trayAdjusted:true});
          }
          const inPts=isRobot
            ?[[robotOrderBase[0],trayY,robotOrderBase[2]],[4.08,trayY,-2.12],[4.08,trayY,0],[6.44,trayY,0],[6.44,trayY,2.06],[qPos[0],trayY,2.06],qPos]
            :[[.96,trayY,0],[6.44,trayY,0],[6.44,trayY,2.06],[qPos[0],trayY,2.06],qPos];
          const inLen=compilePolyline(inPts,0).totalLength;
          const dur=Math.max(.70,inLen/10.8);
          const rawEnd=ev.tick+dur;
          addTransit({orderId:id,t0:ev.tick,t1:rawEnd,points:inPts,mode:'conveyor',fallbackYaw:0,showTray:Boolean(meta.tray),trayAdjusted:true});
          queueArrivalEnd[id]=Math.min(H,rawEnd);
          lastScheduledPos[id]=[...qPos];
        }
      }else if(qName==='R'){
        orderAttempt[id]=Math.max(1,ev.attempt||1);
        const prev=activeWorkOrders[id];
        const s4Slot=prev?.slot||stageSlotTransform(b,4,0);
        const trayY=cleanNum(.86+(meta.tray?.012:0));
        const s4Ord=[s4Slot.order[0],trayY,s4Slot.order[2]];
        const fullPts=[s4Ord,[7.40,trayY,-2.39],[10.80,trayY,-1.50],[10.80,trayY,5.65],qPos];
        const totalLen=compilePolyline(fullPts,Math.PI).totalLength;
        const needDur=Math.max(1.30,totalLen/13.2);
        const leadDur=.48;
        const tStart=ev.tick-leadDur,rawEnd=tStart+needDur;
        if(prev){prev.leadOutStart=Math.min(prev.leadOutStart??ev.tick,tStart);}
        addTransit({orderId:id,t0:tStart,t1:rawEnd,points:fullPts,mode:'r_transfer',fallbackYaw:Math.PI,showTray:Boolean(meta.tray),trayAdjusted:true});
        queueArrivalEnd[id]=Math.min(H,rawEnd);
        lastScheduledPos[id]=[...qPos];
      }
    }else if(ev.kind==='start'){
      const qName=ev.stage===3&&ev.attempt===1?'R':'Q'+ev.stage;
      const visLim=visibleLimitForQueue(qName);
      const oldIdxMap=new Map(queues[qName].map((oid,idx)=>[oid,idx]));
      const beforePositions=new Map(queues[qName].map(oid=>[oid,lastScheduledPos[oid]?[...lastScheduledPos[oid]]:currentQueuePos(qName,oid)]));
      const popPos=beforePositions.get(id)||currentQueuePos(qName,id);
      const qIdx=queues[qName].indexOf(id);
      if(qIdx>=0)queues[qName].splice(qIdx,1);

      const hadTrayInQueue=Boolean(meta.tray);
      if(ev.stage===3&&ev.attempt===0&&manifest.plan.trays)meta.tray=true;
      const trayY=cleanNum(.86+(meta.tray?.012:0));

      queues[qName].forEach((remId,newIdx)=>{
        const oldIdx=oldIdxMap.get(remId)??newIdx;
        const newP=currentQueuePos(qName,remId);
        if(newIdx>=visLim){
          lastScheduledPos[remId]=[...newP];
          return;
        }
        if(oldIdx>=visLim&&newIdx<visLim){
          lastScheduledPos[remId]=[...newP];
          queueArrivalEnd[remId]=Math.max(ev.tick,queueArrivalEnd[remId]??ev.tick);
          return;
        }
        const oldP=beforePositions.get(remId);
        if(!oldP||dist3(oldP,newP)<=1e-4){
          lastScheduledPos[remId]=[...newP];
          return;
        }
        const cIdx=orderIdxCursor.get(remId)??-1;
        const remNext=nextStartTickFor(remId,cIdx);
        const cStart=Math.max(ev.tick,queueArrivalEnd[remId]??ev.tick);
        const needCompact=Math.max(.26,dist3(oldP,newP)/9.5);
        const cEnd=Math.min(remNext,cStart+needCompact);
        if(cEnd>=cStart+dist3(oldP,newP)/12.5&&cEnd>cStart+1e-4){
          addTransit({orderId:remId,t0:cStart,t1:cEnd,points:[oldP,newP],mode:'compact',fallbackYaw:0,showTray:Boolean(orderMeta[remId]?.tray),trayAdjusted:true});
          queueArrivalEnd[remId]=Math.min(H,cEnd);
          lastScheduledPos[remId]=[...newP];
        }
      });

      const tArrQ=queueArrivalEnd[id]??ev.tick;
      if(ev.resource==='robot'){
        const t0=Math.max(ev.tick,tArrQ);
        const robOrd=[robotOrderBase[0],trayY,robotOrderBase[2]];
        const outPts=[popPos,[popPos[0],.86,2.06],[.42,.86,2.06],[.42,.86,0],[4.08,.86,0],[4.08,.86,-2.12],robOrd];
        const outDur=Math.max(.55,compilePolyline(outPts,0).totalLength/10.8);
        const tReady=Math.min(ev.end_tick-.35,t0+outDur);
        if(t0>tArrQ+1e-5)addTransit({orderId:id,t0:tArrQ,t1:t0,points:[popPos,popPos],mode:'hold',fallbackYaw:0,showTray:false,trayAdjusted:true});
        addTransit({orderId:id,t0,t1:tReady,points:outPts,mode:'conveyor',fallbackYaw:Math.PI,showTray:false,trayAdjusted:true});
        if(tReady>ev.tick+1e-6)addRobotPhase({t0:ev.tick,t1:tReady,state:'idle',orderId:id,tray:meta.tray});
        addRobotPhase({t0:tReady,t1:ev.end_tick,state:'pack',orderId:id,tray:meta.tray});
        const rec={orderId:id,isRobot:true,startTick:ev.tick,endTick:ev.end_tick,workReadyTick:tReady,tray:meta.tray};
        activeWorkOrders[id]=rec;
        activeRobotOrder.current=rec;
      }else{
        const wId=ev.resource,act=pres.activities.get(`${wId}:work:${ev.tick}`);
        const slot=stageSlotTransform(b,ev.stage,act?act.index:0);
        const fromPos=workerActualPos[wId]||(act?act.from:slot.actor);
        const fromYaw=workerActualYaw[wId]??slot.yaw;
        const isReworkOrder=ev.stage===3&&((ev.attempt??0)>=1||(orderAttempt[id]??0)>=1);
        if((ev.attempt??0)>=1)orderAttempt[id]=Math.max(orderAttempt[id]??0,ev.attempt);
        const ordPos=[slot.order[0],trayY,slot.order[2]];
        const rec={orderId:id,workerId:wId,stage:ev.stage,attempt:ev.attempt,isRework:isReworkOrder,slot,startTick:ev.tick,endTick:ev.end_tick,workReadyTick:ev.tick,leadOutStart:ev.end_tick,tray:meta.tray,act};
        activeWorkOrders[id]=rec;
        allWorkRecords.push(rec);
        const prevBusyEnd=Math.max(workerBusyUntil[wId]??0,workerPhases[wId].length?workerPhases[wId].at(-1).t1:0);
        workerBusyUntil[wId]=Math.max(prevBusyEnd,ev.end_tick);

        if(ev.stage===1){
          const qStand=[-11.00,0,-2.35];
          const wPath1=planWalkPath(fromPos,qStand,{obstacles});
          const wLen1=compilePolyline(wPath1,Math.PI).totalLength;
          const walkDur=wLen1<1e-4?0:Math.max(.26,wLen1/10.5);
          const tPick0=Math.max(ev.tick+walkDur,tArrQ);
          if(walkDur>1e-5)addWorkerPhase(wId,{t0:ev.tick,t1:ev.tick+walkDur,state:'walk',poly:compilePolyline(wPath1,Math.PI,fromYaw,Math.PI),orderId:id,tray:false});
          if(tPick0>ev.tick+walkDur+1e-5)addWorkerPhase(wId,{t0:ev.tick+walkDur,t1:tPick0,state:'idle',position:[...qStand],yaw:Math.PI,orderId:id,tray:false});
          if(tPick0>tArrQ+1e-5)addTransit({orderId:id,t0:tArrQ,t1:tPick0,points:[popPos,popPos],mode:'hold',fallbackYaw:0,showTray:false,trayAdjusted:true});
          const carryWalkPts=planWalkPath(qStand,slot.actor,{obstacles});
          const carryPoly=compilePolyline(carryWalkPts,slot.yaw,Math.PI,slot.yaw);
          const carryOrderPts=walkToCarryPoints(carryWalkPts,false);
          const pickDur=Math.max(.26,dist3(popPos,carryOrderPts[0])/8.5);
          const placeDur=Math.max(.24,dist3(carryOrderPts.at(-1),ordPos)/8.5);
          const carryDur=Math.max(.35,carryPoly.totalLength/10.5);
          const tPick1=tPick0+pickDur,tCarry1=tPick1+carryDur,tPlace1=tCarry1+placeDur;
          addWorkerPhase(wId,{t0:tPick0,t1:tPick1,state:'pickup',position:[...qStand],yaw:Math.PI,orderId:id,tray:false,suppressPropCarton:true});
          addTransit({orderId:id,t0:tPick0,t1:tPick1,points:[popPos,carryOrderPts[0]],mode:'pickup',actorId:wId,fallbackYaw:Math.PI,suppressPropCarton:true,showTray:false,trayAdjusted:true});
          addWorkerPhase(wId,{t0:tPick1,t1:tCarry1,state:'carry_walk',poly:carryPoly,orderId:id,tray:false});
          addTransit({orderId:id,t0:tPick1,t1:tCarry1,points:carryOrderPts,mode:'carry',actorId:wId,fallbackYaw:slot.yaw,startYaw:Math.PI,endYaw:slot.yaw,showTray:false,trayAdjusted:true});
          addWorkerPhase(wId,{t0:tCarry1,t1:tPlace1,state:'place_down',position:[...slot.actor],yaw:slot.yaw,orderId:id,tray:false});
          addTransit({orderId:id,t0:tCarry1,t1:tPlace1,points:[carryOrderPts.at(-1),ordPos],mode:'place_down',actorId:wId,fallbackYaw:slot.yaw,showTray:false,trayAdjusted:true});
          rec.workReadyTick=tPlace1;
          workerActualPos[wId]=[...slot.actor];workerActualYaw[wId]=slot.yaw;
        }else if(isReworkOrder){
          const overlapping=activeReworkSpans.filter(s=>s.t1>ev.tick+1e-5&&s.t0<ev.end_tick-1e-5);
          let benchX=1.80;
          if(overlapping.length){
            benchX=overlapping.some(s=>Math.abs(s.benchX-1.50)<.15)?2.10:1.50;
            for(const s of overlapping)if(Math.abs(s.benchX-1.80)<.05){s.benchX=1.50;benchX=2.10;}
          }
          activeReworkSpans.push({wId,t0:ev.tick,t1:ev.end_tick,benchX});
          const rStand=[3.40,0,5.65];
          const rwActor=[benchX,0,5.55];
          const rwOrdPos=[benchX,trayY,6.35];
          rec.reworkBenchActor=rwActor;
          rec.reworkBenchOrderPos=rwOrdPos;
          const wPath1=planWalkPath(fromPos,rStand,{obstacles});
          const wLen1=compilePolyline(wPath1,0).totalLength;
          const prevPhaseEnd=prevBusyEnd;
          const rawWalkDur=wLen1<1e-4?0:Math.max(.32,wLen1/13.5);
          const targetPick0=ev.end_tick-1.40;
          const tWalk0=wLen1<1e-4?ev.tick:Math.max(prevPhaseEnd,Math.min(ev.tick,targetPick0-rawWalkDur));
          const minSafeWalk=wLen1<1e-4?0:Math.max(.30,wLen1/15.6);
          const tWalk1=wLen1<1e-4?ev.tick:Math.min(Math.max(tWalk0+minSafeWalk,targetPick0),tWalk0+rawWalkDur);
          let effArrQ=tArrQ;
          if(effArrQ>tWalk1&&effArrQ>ev.end_tick-1.35){
            const targetArr=Math.max(ev.tick+.45,Math.min(effArrQ,Math.max(tWalk1,ev.end_tick-1.35)));
            for(let ti=transits.length-1;ti>=0;ti--){
              if(transits[ti].orderId===id&&transits[ti].mode==='r_transfer'&&transits[ti].t1>targetArr){
                transits[ti].t1=cleanNum(targetArr);transits[ti].rawT1=cleanNum(targetArr);
                effArrQ=cleanNum(targetArr);break;
              }
            }
          }
          const tPick0=Math.max(tWalk1,effArrQ);
          if(tWalk1>tWalk0+1e-5)addWorkerPhase(wId,{t0:tWalk0,t1:tWalk1,state:'walk',poly:compilePolyline(wPath1,0,fromYaw,0),orderId:id,tray:meta.tray});
          if(tPick0>tWalk1+1e-5)addWorkerPhase(wId,{t0:tWalk1,t1:tPick0,state:'idle',position:[...rStand],yaw:0,orderId:id,tray:meta.tray});
          if(tPick0>effArrQ+1e-5)addTransit({orderId:id,t0:effArrQ,t1:tPick0,points:[popPos,popPos],mode:'hold',fallbackYaw:0,showTray:Boolean(meta.tray),trayAdjusted:true});
          const carryWalkPts=planWalkPath(rStand,rwActor,{obstacles});
          const carryPoly=compilePolyline(carryWalkPts,0,0,0);
          const carryOrderPts=walkToCarryPoints(carryWalkPts,meta.tray);
          const pickDur=.20,placeDur=.20;
          const carryDur=Math.max(.24,carryPoly.totalLength/11.5);
          const tPick1=tPick0+pickDur,tCarry1=tPick1+carryDur,tPlace1=Math.min(ev.end_tick-.55,tCarry1+placeDur);
          addWorkerPhase(wId,{t0:tPick0,t1:tPick1,state:'pickup',position:[...rStand],yaw:0,orderId:id,tray:meta.tray,reworkBenchOrderPos:rwOrdPos});
          addTransit({orderId:id,t0:tPick0,t1:tPick1,points:[popPos,carryOrderPts[0]],mode:'pickup',actorId:wId,fallbackYaw:0,showTray:false,trayAdjusted:true});
          addWorkerPhase(wId,{t0:tPick1,t1:tCarry1,state:'carry_walk',poly:carryPoly,orderId:id,tray:meta.tray,reworkBenchOrderPos:rwOrdPos});
          addTransit({orderId:id,t0:tPick1,t1:tCarry1,points:carryOrderPts,mode:'carry',actorId:wId,fallbackYaw:0,startYaw:0,endYaw:0,showTray:false,trayAdjusted:true});
          addWorkerPhase(wId,{t0:tCarry1,t1:tPlace1,state:'place_down',position:[...rwActor],yaw:0,orderId:id,tray:meta.tray,reworkBenchOrderPos:rwOrdPos});
          addTransit({orderId:id,t0:tCarry1,t1:tPlace1,points:[carryOrderPts.at(-1),rwOrdPos],mode:'place_down',actorId:wId,fallbackYaw:0,showTray:Boolean(meta.tray),trayAdjusted:true});
          rec.workReadyTick=tPlace1;
          workerActualPos[wId]=[...rwActor];workerActualYaw[wId]=0;
        }else if(ev.stage===4){
          const t0=Math.max(ev.tick,tArrQ);
          if(t0>tArrQ+1e-5)addTransit({orderId:id,t0:tArrQ,t1:t0,points:[popPos,popPos],mode:'hold',fallbackYaw:0,showTray:Boolean(meta.tray),trayAdjusted:true});
          const p1=[popPos,[popPos[0],trayY,2.06],[6.44,trayY,2.06],[6.44,trayY,0],[6.15,trayY,0]];
          const d1=Math.max(.32,compilePolyline(p1,Math.PI).totalLength/10.8);
          const dDwell=Math.max(.38,.36);
          const p3=[[6.15,trayY,0],[6.69,trayY,0],[6.69,trayY,-.89],ordPos];
          const d3=Math.max(.32,compilePolyline(p3,slot.yaw).totalLength/10.8);
          const tP1=t0+d1,tP2=tP1+dDwell,tReady=Math.min(ev.end_tick-.35,tP2+d3);
          addTransit({orderId:id,t0,t1:tP1,points:p1,mode:'conveyor',fallbackYaw:Math.PI,showTray:Boolean(meta.tray),trayAdjusted:true});
          addTransit({orderId:id,t0:tP1,t1:tP2,points:[[6.15,trayY,0],[6.15,trayY,0]],mode:'qc_portal',fallbackYaw:Math.PI,showTray:Boolean(meta.tray),trayAdjusted:true});
          qcDwellIntervals.push([cleanNum(tP1),cleanNum(tP2),id]);
          addTransit({orderId:id,t0:tP2,t1:tReady,points:p3,mode:'conveyor',fallbackYaw:slot.yaw,showTray:Boolean(meta.tray),trayAdjusted:true});
          const wPath=distance(fromPos,slot.actor)>1e-4?planWalkPath(fromPos,slot.actor,{obstacles}):(act?act.path:[[...slot.actor],[...slot.actor]]);
          const walkTicks=distance(fromPos,slot.actor)<1e-4?0:Math.min(Math.max(.35,(ev.end_tick-ev.tick)*.42),Math.max(act?act.travelTicks:0,polylineLength(wPath)/10.8));
          const walkEnd=ev.tick+walkTicks;
          if(walkTicks>1e-5)addWorkerPhase(wId,{t0:ev.tick,t1:walkEnd,state:'walk',poly:compilePolyline(wPath,slot.yaw,fromYaw,slot.yaw),orderId:id,tray:meta.tray});
          if(tReady>walkEnd+1e-5)addWorkerPhase(wId,{t0:walkEnd,t1:tReady,state:'idle',position:[...slot.actor],yaw:slot.yaw,orderId:id,tray:meta.tray});
          rec.workReadyTick=Math.max(walkEnd,tReady);
          workerActualPos[wId]=[...slot.actor];workerActualYaw[wId]=slot.yaw;
        }else{
          const qSpurX=ev.stage===2?-6.46:.42;
          const stSpurX=ev.stage===2?-4.27:.96;
          const preBenchY=hadTrayInQueue?trayY:.86;
          const t0=Math.max(ev.tick,tArrQ);
          if(t0>tArrQ+1e-5)addTransit({orderId:id,t0:tArrQ,t1:t0,points:[popPos,popPos],mode:'hold',fallbackYaw:0,showTray:hadTrayInQueue,trayAdjusted:true});
          const outPts=[popPos,[popPos[0],preBenchY,2.06],[qSpurX,preBenchY,2.06],[qSpurX,preBenchY,0],[stSpurX,preBenchY,0],[stSpurX,preBenchY,-.89],ordPos];
          const outDur=Math.max(.55,compilePolyline(outPts,slot.yaw).totalLength/10.8);
          const tReady=Math.min(ev.end_tick-.4,t0+outDur);
          addTransit({orderId:id,t0,t1:tReady,points:outPts,mode:'conveyor',fallbackYaw:slot.yaw,showTray:hadTrayInQueue,trayAdjusted:true});
          const wPath=distance(fromPos,slot.actor)>1e-4?planWalkPath(fromPos,slot.actor,{obstacles}):(act?act.path:[[...slot.actor],[...slot.actor]]);
          const walkTicks=distance(fromPos,slot.actor)<1e-4?0:Math.min(Math.max(.35,(ev.end_tick-ev.tick)*.42),Math.max(act?act.travelTicks:0,polylineLength(wPath)/10.8));
          const walkEnd=ev.tick+walkTicks;
          if(walkTicks>1e-5)addWorkerPhase(wId,{t0:ev.tick,t1:walkEnd,state:'walk',poly:compilePolyline(wPath,slot.yaw,fromYaw,slot.yaw),orderId:id,tray:meta.tray});
          if(tReady>walkEnd+1e-5)addWorkerPhase(wId,{t0:walkEnd,t1:tReady,state:'idle',position:[...slot.actor],yaw:slot.yaw,orderId:id,tray:meta.tray});
          rec.workReadyTick=Math.max(walkEnd,tReady);
          workerActualPos[wId]=[...slot.actor];workerActualYaw[wId]=slot.yaw;
        }
      }
    }else if(ev.kind==='jam'){
      if(activeRobotOrder.current&&activeRobotOrder.current.orderId===id){
        const ro=activeRobotOrder.current;
        ro.jammedTick=ev.tick;
        let tAssist=H;
        for(const e2 of events)if(e2.kind==='assist'&&e2.order_id===id&&e2.tick>=ev.tick){tAssist=e2.tick;break;}
        if(tAssist>ev.tick+1e-5)addRobotPhase({t0:ev.tick,t1:tAssist,state:'jammed',orderId:id,tray:ro.tray});
      }
    }else if(['good','escaped','scrap'].includes(ev.kind)){
      outcomes[ev.kind].push(id);
      const outPos=currentOutcomePos(ev.kind,id);
      const prev=activeWorkOrders[id];
      const slot=prev?.slot||stageSlotTransform(b,4,0);
      const wId=prev?.workerId||ev.resource;
      const trayY=cleanNum(.86+(meta.tray?.012:0));
      const s4Ord=[slot.order[0],trayY,slot.order[2]];

      if(ev.kind==='good'){
        const beltPts=[s4Ord,[6.69,trayY,-.89],[6.69,trayY,0],[9.00,trayY,0]];
        const chutePts=[[9.00,trayY,0],[9.52,.62,-.85],[9.92,.28,-1.78],outPos];
        const beltDur=Math.max(.42,compilePolyline(beltPts,0).totalLength/10.8);
        const chuteDur=Math.max(.52,compilePolyline(chutePts,0).totalLength/9.5);
        const leadDur=.30;
        const tStart=ev.tick-leadDur,tMid=tStart+beltDur,rawEnd=tMid+chuteDur;
        if(prev){prev.leadOutStart=Math.min(prev.leadOutStart??ev.tick,tStart);}
        addTransit({orderId:id,t0:tStart,t1:tMid,points:beltPts,mode:'good_outfeed',fallbackYaw:0,showTray:Boolean(meta.tray),trayAdjusted:true});
        addTransit({orderId:id,t0:tMid,t1:rawEnd,points:chutePts,mode:'good_outfeed',fallbackYaw:0,showTray:false,trayAdjusted:true});
      }else if(ev.kind==='escaped'){
        const escStand=[8.65,0,-4.40];
        const cWalkPts=planWalkPath(slot.actor,escStand,{obstacles});
        const cWalkPoly=compilePolyline(cWalkPts,Math.PI/2,slot.yaw,Math.PI/2);
        const cOrdPts=walkToCarryPoints(cWalkPts,meta.tray);
        const cDur=Math.max(.48,cWalkPoly.totalLength/10.5);
        const retPts=planWalkPath(escStand,slot.actor,{obstacles});
        const retPoly=compilePolyline(retPts,slot.yaw,Math.PI/2,slot.yaw);
        const retDur=Math.max(.46,retPoly.totalLength/10.5);
        const nextBusy=wId?nextWorkerBusyTick(wId,ev.tick):ev.tick;
        const canReturnAfter=ev.tick+retDur<=Math.min(H,nextBusy);
        const pickDur=Math.max(.22,dist3(s4Ord,cOrdPts[0])/8.5);
        const placeDur=Math.max(.22,dist3(cOrdPts.at(-1),outPos)/8.5);
        const tPlace1=canReturnAfter?ev.tick:(ev.tick-retDur);
        const tCarry1=tPlace1-placeDur,tPick1=tCarry1-cDur;
        const minPick0=prev?prev.workReadyTick+.30:0;
        const tPick0=Math.max(minPick0,tPick1-pickDur);
        if(prev){prev.leadOutStart=Math.min(prev.leadOutStart??ev.tick,tPick0);}
        if(wId){
          addWorkerPhase(wId,{t0:tPick0,t1:tPick1,state:'pickup',position:[...slot.actor],yaw:slot.yaw,orderId:id,tray:meta.tray});
          addWorkerPhase(wId,{t0:tPick1,t1:tCarry1,state:'carry_walk',poly:cWalkPoly,orderId:id,tray:meta.tray});
          addWorkerPhase(wId,{t0:tCarry1,t1:tPlace1,state:'place_down',position:[...escStand],yaw:Math.PI/2,orderId:id,tray:meta.tray,suppressPropCarton:true});
          const rStart=canReturnAfter?ev.tick:tPlace1;
          addWorkerPhase(wId,{t0:rStart,t1:rStart+retDur,state:'walk',poly:retPoly,orderId:null,tray:false});
        }
        addTransit({orderId:id,t0:tPick0,t1:tPick1,points:[s4Ord,cOrdPts[0]],mode:'pickup',actorId:wId,fallbackYaw:slot.yaw,showTray:false,trayAdjusted:true});
        addTransit({orderId:id,t0:tPick1,t1:tCarry1,points:cOrdPts,mode:'carry',actorId:wId,fallbackYaw:Math.PI/2,startYaw:slot.yaw,endYaw:Math.PI/2,showTray:false,trayAdjusted:true});
        addTransit({orderId:id,t0:tCarry1,t1:tPlace1,points:[cOrdPts.at(-1),outPos],mode:'place_down',actorId:wId,fallbackYaw:Math.PI/2,suppressPropCarton:true,showTray:false,trayAdjusted:true});
        if(!canReturnAfter&&ev.tick>tPlace1+1e-5){
          addTransit({orderId:id,t0:tPlace1,t1:ev.tick,points:[outPos,outPos],mode:'hold',fallbackYaw:Math.PI/2,suppressPropCarton:true,showTray:false,trayAdjusted:true});
        }
      }else if(ev.kind==='scrap'){
        const nextBusy=wId?nextWorkerBusyTick(wId,ev.tick):ev.tick;
        const idleGap=Math.min(H,nextBusy)-ev.tick;
        const scrapStand=[8.65,0,5.55];
        const rawCarryPts=[slot.actor,[7.40,0,-1.95],[11.35,0,-1.50],[11.35,0,5.55],scrapStand];
        const cWalkPts=[];
        for(let k=0;k<rawCarryPts.length-1;k++){
          const seg=gridPath(rawCarryPts[k],rawCarryPts[k+1],obstacles);
          for(const pt of seg)if(!cWalkPts.length||!same(cWalkPts.at(-1),pt))cWalkPts.push(pt);
        }
        const cWalkPoly=compilePolyline(cWalkPts,0,slot.yaw,0);
        const retPts=planWalkPath(scrapStand,slot.actor,{obstacles});
        const retPoly=compilePolyline(retPts,slot.yaw,0,slot.yaw);
        const minPick0=prev?prev.workReadyTick+.32:Math.max(0,ev.tick-1.6);
        const maxEnd=Math.min(H,nextBusy);
        const cDur=Math.max(1.25,cWalkPoly.totalLength/11.5);
        const retDur=Math.max(1.20,retPoly.totalLength/11.5);
        const pickDur=.22,placeDur=.24,logDur=.22;
        const totalNeed=pickDur+cDur+placeDur+logDur+retDur;
        if(wId&&idleGap>=.80&&(maxEnd-minPick0)>=totalNeed){
          const cOrdPts=walkToCarryPoints(cWalkPts,meta.tray);
          const idealPick0=Math.max(minPick0,ev.tick-pickDur);
          const tPick0=idealPick0+totalNeed<=maxEnd?idealPick0:Math.max(minPick0,maxEnd-totalNeed);
          const tPick1=tPick0+pickDur,tCarry1=tPick1+cDur,tPlace1=tCarry1+placeDur,tLog1=tPlace1+logDur,tEnd=tLog1+retDur;
          if(prev){prev.leadOutStart=Math.min(prev.leadOutStart??ev.tick,tPick0);}
          addWorkerPhase(wId,{t0:tPick0,t1:tPick1,state:'pickup',position:[...slot.actor],yaw:slot.yaw,orderId:id,tray:meta.tray});
          addWorkerPhase(wId,{t0:tPick1,t1:tCarry1,state:'carry_walk',poly:cWalkPoly,orderId:id,tray:meta.tray});
          addWorkerPhase(wId,{t0:tCarry1,t1:tPlace1,state:'place_down',position:[...scrapStand],yaw:0,orderId:id,tray:meta.tray,suppressPropCarton:true});
          addWorkerPhase(wId,{t0:tPlace1,t1:tLog1,state:'inspect',position:[...scrapStand],yaw:0,orderId:id,tray:false,suppressPropCarton:true});
          addWorkerPhase(wId,{t0:tLog1,t1:tEnd,state:'walk',poly:retPoly,orderId:null,tray:false});
          workerActualPos[wId]=[...slot.actor];
          workerBusyUntil[wId]=Math.max(workerBusyUntil[wId]??0,tEnd);
          addTransit({orderId:id,t0:tPick0,t1:tPick1,points:[s4Ord,cOrdPts[0]],mode:'pickup',actorId:wId,fallbackYaw:slot.yaw,showTray:false,trayAdjusted:true,scrapBadged:true});
          addTransit({orderId:id,t0:tPick1,t1:tCarry1,points:cOrdPts,mode:'carry',actorId:wId,fallbackYaw:0,startYaw:slot.yaw,endYaw:0,showTray:false,trayAdjusted:true,scrapBadged:true});
          addTransit({orderId:id,t0:tCarry1,t1:tPlace1,points:[cOrdPts.at(-1),[8.65,.92,6.35],outPos],mode:'scrap_drop',actorId:wId,fallbackYaw:0,suppressPropCarton:true,showTray:false,trayAdjusted:true,scrapBadged:true});
        }else{
          const glidePts=[s4Ord,[7.40,trayY,-2.39],[11.35,trayY,-1.50],[11.35,.86,6.35],[8.65,.86,6.35],outPos];
          const glideDur=Math.max(1.55,compilePolyline(glidePts,Math.PI).totalLength/10.8);
          const tStart=ev.tick-.28,rawEnd=tStart+glideDur;
          if(prev){prev.leadOutStart=Math.min(prev.leadOutStart??ev.tick,tStart);}
          addTransit({orderId:id,t0:tStart,t1:rawEnd,points:glidePts,mode:'scrap_drop',fallbackYaw:Math.PI,suppressPropCarton:true,showTray:false,trayAdjusted:true,scrapBadged:true});
        }
      }
    }
  }

  for(const rec of allWorkRecords){
    if(rec.isRobot)continue;
    const t0=rec.workReadyTick,t1=Math.min(rec.endTick,rec.leadOutStart??rec.endTick);
    const opState=OPERATION_BY_STAGE[rec.stage];
    const workActor=rec.isRework?(rec.reworkBenchActor||[1.80,0,5.55]):rec.slot.actor;
    const workYaw=rec.isRework?0:rec.slot.yaw;
    const rwOrd=rec.isRework?(rec.reworkBenchOrderPos||[1.80,.86,6.35]):null;
    if(t1>t0+1e-5){
      addWorkerPhase(rec.workerId,{t0,t1,state:opState,position:[...workActor],yaw:workYaw,orderId:rec.orderId,tray:rec.tray,reworkBenchOrderPos:rwOrd});
    }
    if(rec.endTick>t1+1e-5){
      const existing=workerPhases[rec.workerId].some(p=>p.t0<rec.endTick-1e-5&&p.t1>t1+1e-5);
      if(!existing)addWorkerPhase(rec.workerId,{t0:t1,t1:rec.endTick,state:'place_down',position:[...workActor],yaw:workYaw,orderId:rec.orderId,tray:rec.tray,suppressPropCarton:true,reworkBenchOrderPos:rwOrd});
    }
  }

  for(const wId of Object.keys(workerPhases)){
    workerPhases[wId].sort((a,b2)=>a.t0-b2.t0||a.t1-b2.t1);
  }
  robotPhases.sort((a,b2)=>a.t0-b2.t0||a.t1-b2.t1);

  const rawMod=Array.from({length:11},()=>[]);
  const rawR=[];
  for(const tr of transits){
    const pts=tr.poly.points,total=tr.poly.totalLength;
    if(total<=1e-6)continue;
    const spanT=tr.truncatedAtHorizon?Math.max(1e-6,tr.rawT1-tr.rawT0):(tr.t1-tr.t0);
    for(let s=0;s<pts.length-1;s++){
      const pa=pts[s],pb=pts[s+1],segLen=tr.poly.seg[s];
      if(segLen<=1e-6)continue;
      const tauA=tr.t0+(tr.poly.cum[s]/total)*spanT;
      const tauB=tr.t0+(tr.poly.cum[s+1]/total)*spanT;
      if(Math.min(Math.abs(pa[2]),Math.abs(pb[2]))<=.48&&Math.hypot(pb[0]-pa[0],pb[2]-pa[2])>1e-4){
        for(let m=1;m<=10;m++){
          const xmin=-9+1.8*(m-1)-.30,xmax=-9+1.8*m+.30;
          const dx=pb[0]-pa[0];
          if(Math.abs(dx)<1e-9){
            if(pa[0]>=xmin&&pa[0]<=xmax)rawMod[m].push([tauA,Math.min(H,tauB)]);
          }else{
            const l=(xmin-pa[0])/dx,h=(xmax-pa[0])/dx;
            const u0=Math.max(0,Math.min(l,h)),u1=Math.min(1,Math.max(l,h));
            if(u1>u0+1e-7)rawMod[m].push([tauA+u0*(tauB-tauA),Math.min(H,tauA+u1*(tauB-tauA))]);
          }
        }
      }
      if(Math.max(pa[2],pb[2])>=6.5&&(tr.mode==='r_transfer'||tr.mode==='compact'||tr.mode==='pickup')){
        rawR.push([tauA,Math.min(H,tauB)]);
      }
    }
  }

  const moduleIntervals=Array.from({length:11},(_,m)=>m===0?null:mergeIntervals(rawMod[m]));
  const rIntervals=mergeIntervals(rawR);
  const tickBuckets=Array.from({length:H+2},()=>[]);
  for(const tr of transits){
    const lo=Math.max(0,Math.floor(tr.t0)),hi=Math.min(H+1,Math.ceil(tr.t1));
    for(let k=lo;k<=hi;k++)tickBuckets[k].push(tr);
  }

  const moduleSummaries=Object.freeze(Array.from({length:10},(_,i)=>Object.freeze({
    module:i+1,
    name:`CONVEYOR_${String(i+1).padStart(2,'0')}`,
    xRange:Object.freeze([cleanNum(-9+1.8*i),cleanNum(-9+1.8*(i+1))]),
    activeIntervals:moduleIntervals[i+1].intervals.length,
  })));
  const spurSummaries=Object.freeze([
    'INFEED_PREP_C01','SPUR_PICK','Q2','SPUR_PACK','SPUR_ROBOT','Q3','Q4','QC_PORTAL','SPUR_QC','OUTFEED_C10_GOOD','EAST_RETURN_R','SCRAP_ROUTE',
  ]);

  return {
    horizonTicks:H,
    bindings:b,
    presentation:pres,
    transits,
    tickBuckets,
    workerPhases,
    robotPhases,
    moduleIntervals,
    rIntervals,
    qcDwellIntervals,
    robotPos,
    moduleSummaries,
    spurSummaries,
  };
}

function isPhaseActiveAt(p,t,horizonTicks){
  if(t<p.t0)return false;
  if(t<p.t1)return true;
  return t===horizonTicks&&Boolean(p.truncatedAtHorizon)&&Math.abs(p.t1-horizonTicks)<=1e-6;
}

function phaseProgressAt(p,t){
  const denom=p.truncatedAtHorizon?Math.max(1e-6,p.rawT1-p.rawT0):Math.max(1e-6,p.t1-p.t0);
  return cleanNum(Math.min(1,Math.max(0,(t-p.t0)/denom)));
}

function findPhase(list,t,horizonTicks){
  if(!list||!list.length)return null;
  let lo=0,hi=list.length-1,idx=-1;
  while(lo<=hi){
    const mid=(lo+hi)>>1;
    if(list[mid].t0<=t){idx=mid;lo=mid+1;}else hi=mid-1;
  }
  while(idx>=0&&idx<list.length){
    const p=list[idx];
    if(isPhaseActiveAt(p,t,horizonTicks))return p;
    if(p.t0>t)break;
    idx--;
  }
  return null;
}

export function sampleFlow(flowPlan,tickFloat,tickSeconds=30){
  const H=flowPlan.horizonTicks;
  const t=cleanNum(Math.min(H,Math.max(0,tickFloat)));
  const bucketIdx=Math.min(flowPlan.tickBuckets.length-1,Math.max(0,Math.floor(t)));
  const activeTransits=[];
  const seenOrders=new Set();
  for(const tr of flowPlan.tickBuckets[bucketIdx]){
    if(isPhaseActiveAt(tr,t,H)&&!seenOrders.has(tr.orderId)){
      seenOrders.add(tr.orderId);
      const u=phaseProgressAt(tr,t);
      const {position,yaw}=sampleCompiledPolyline(tr.poly,u);
      activeTransits.push({
        orderId:tr.orderId,
        mode:tr.mode,
        actorId:tr.actorId??null,
        phase:u,
        position,
        yaw,
        suppressPropCarton:tr.suppressPropCarton,
        hideTray:tr.hideTray,
        showTray:tr.showTray,
        trayAdjusted:tr.trayAdjusted,
        scrapBadged:Boolean(tr.scrapBadged),
      });
    }
  }
  activeTransits.sort((a,b2)=>a.orderId-b2.orderId);

  const workers={};
  const reworkOrderPos={};
  for(const [wId,phases] of Object.entries(flowPlan.workerPhases)){
    const ph=findPhase(phases,t,H);
    if(ph){
      const u=phaseProgressAt(ph,t);
      const pose=ph.poly?sampleCompiledPolyline(ph.poly,u):{position:cleanVec3(ph.position),yaw:cleanNum(ph.yaw)};
      const rwPos=ph.reworkBenchOrderPos?cleanVec3(ph.reworkBenchOrderPos):null;
      if(rwPos&&ph.orderId!=null)reworkOrderPos[ph.orderId]=rwPos;
      workers[wId]={
        state:ph.state,
        phase:u,
        position:pose.position,
        yaw:pose.yaw,
        orderId:ph.orderId??null,
        tray:Boolean(ph.tray),
        suppressPropCarton:Boolean(ph.suppressPropCarton),
        reworkBenchOrderPos:rwPos,
        pathLengthM:cleanNum(ph.poly?ph.poly.totalLength:0),
      };
    }else{
      const prevList=flowPlan.workerPhases[wId]||[];
      let prevPh=null;
      for(let k=prevList.length-1;k>=0;k--)if(prevList[k].t1<=t+1e-6){prevPh=prevList[k];break;}
      const slotEntry=flowPlan.presentation.slotAt(wId,Math.floor(t));
      const slot=stageSlotTransform(flowPlan.bindings,slotEntry.stage,slotEntry.index);
      let idlePos=cleanVec3(slot.actor),idleYaw=cleanNum(slot.yaw);
      if(prevPh&&prevPh.reworkBenchOrderPos){
        idlePos=prevPh.poly?sampleCompiledPolyline(prevPh.poly,1).position:cleanVec3(prevPh.position);
        idleYaw=0;
      }
      workers[wId]={
        state:'idle',
        phase:0,
        position:idlePos,
        yaw:idleYaw,
        orderId:null,
        tray:false,
        suppressPropCarton:false,
        reworkBenchOrderPos:null,
        pathLengthM:0,
      };
    }
  }

  const rPh=findPhase(flowPlan.robotPhases,t,H);
  const robot=rPh?{
    state:rPh.state,
    phase:phaseProgressAt(rPh,t),
    orderId:rPh.orderId??null,
    tray:Boolean(rPh.tray),
  }:null;

  const omega=tickSeconds*(.38/.025);
  const rollerAnglesRad=[];
  const activeModules=[];
  for(let m=1;m<=10;m++){
    const res=evalActiveIntervals(flowPlan.moduleIntervals[m],t);
    rollerAnglesRad.push(cleanNum(res.elapsed*omega));
    if(res.active)activeModules.push(m);
  }
  const rRes=evalActiveIntervals(flowPlan.rIntervals,t);
  const rRollerAngleRad=cleanNum(rRes.elapsed*omega);

  let portalOrder=null,stopperLiftM=0;
  for(const [a,b2,oid] of flowPlan.qcDwellIntervals){
    if(t>=a&&(t<b2||(t===H&&b2>H+1e-6))){
      portalOrder=oid;
      const u=Math.min(1,Math.max(0,(t-a)/Math.max(1e-6,b2-a)));
      stopperLiftM=cleanNum(.085*Math.sin(Math.PI*u));
      break;
    }
  }

  return {
    transits:activeTransits,
    workers,
    reworkOrderPos,
    robot,
    activeModules,
    rollerAnglesRad,
    rRollerActive:rRes.active,
    rRollerAngleRad,
    qcPortal:{
      engaged:portalOrder!==null,
      orderId:portalOrder,
      stopperLiftM,
    },
  };
}
