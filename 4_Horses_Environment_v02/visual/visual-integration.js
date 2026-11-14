// Visual assets adapter only. No scheduling, event reduction, random outcomes or economics.
import * as THREE from 'three';

export const WORKER_CLIPS={idle:'Idle',walk:'Walk',prepare:'Prepare',pick:'Pick',pack:'Pack',inspect:'Inspect',assist:'Assist',break:'Break'};
export const ROBOT_CLIPS={not_purchased:null,disabled:'Offline',idle:'Idle',pack:'RobotPack',jammed:'Jammed',helper_walking:'Jammed',service:'Service',finished:'Idle'};
export const ORDER_SIZES={regular:[.36,.28,.25],fragile:[.36,.28,.25],oversize:[.48,.34,.32]};
const OVERSIZE=new Set(['Prepare','Pick','Pack','Inspect','RobotPack','Jammed','Service']);
const FROZEN=new Set(['Jammed','Service','Offline']);
const LABELS={idle:'Ожидание',walk:'Переход к назначенной работе',prepare:'Подготовка тары',pick:'Комплектация',pack:'Упаковка',inspect:'Контроль',assist:'Помощь роботу',break:'Перерыв',not_purchased:'Робот не приобретён',disabled:'Куплен, выключен маршрутом',jammed:'Застрял — нужен работник',helper_walking:'Помощник идёт',service:'Устранение застревания',finished:'Операция завершена'};

export function cloneActorRig(source){
 const clone=source.clone(true),lookup=new Map();
 function pair(a,b){lookup.set(a,b);a.children.forEach((child,i)=>pair(child,b.children[i]));}pair(source,clone);
 source.traverse(ob=>{if(!ob.isSkinnedMesh)return;const copy=lookup.get(ob),skeleton=ob.skeleton.clone();skeleton.bones=ob.skeleton.bones.map(b=>lookup.get(b));if(skeleton.bones.some(b=>!b))throw new Error('Skeleton joint is outside the actor root');copy.bind(skeleton,ob.bindMatrix);});
 return clone;
}
export function hideDemonstrationProps(root){
 let hidden=0;root.traverse(ob=>{if(ob.userData.handling_prop||/_Demo(Carton|Support)/.test(ob.name)){ob.visible=false;hidden++;}});return hidden;
}
export function hideEnvironmentReplayOrders(root){
 let hidden=0;root.traverse(ob=>{if(ob.userData.animation_role==='parcel'||ob.userData.parcel_id){ob.visible=false;hidden++;}});return hidden;
}
export function templateClone(library,name){
 const source=library.getObjectByName('VIS_'+name);if(!source)throw new Error('Missing visual template VIS_'+name);return source.clone(true);
}

export function createActorVisual(gltf,{actorType,templates=null,demoProps=false}={}){
 if(!['worker','robot'].includes(actorType))throw new Error('actorType must be worker or robot');
 const root=cloneActorRig(gltf.scene),clips=new Map(gltf.animations.map(c=>[c.name,c])),mixer=new THREE.AnimationMixer(root);
 const states=actorType==='worker'?WORKER_CLIPS:ROBOT_CLIPS;
 if(!demoProps)hideDemonstrationProps(root);
 const marker=new THREE.Group();marker.name='VIS_ActorStatus';marker.position.set(0,2.04,0);root.add(marker);
 const markers={};if(templates){for(const key of ['jammed','service','break','offline']){const ob=templateClone(templates,'status_'+key);ob.visible=false;marker.add(ob);markers[key]=ob;}}
 let current=null;
 function sample({state,phase=0,orderKind='regular',cycles=1,position=null,yaw=null}={}){
  if(!(state in states))throw new Error('Unsupported '+actorType+' visual state '+state);
  if(!(orderKind in ORDER_SIZES))throw new Error('Unsupported order kind '+orderKind);
  if(!Number.isFinite(phase)||!Number.isFinite(cycles)||cycles<0)throw new Error('Visual phase and cycles must be finite');
  root.visible=state!=='not_purchased';if(position)root.position.fromArray(position);if(yaw!==null)root.rotation.y=yaw;
  let name=states[state];if(orderKind==='oversize'&&OVERSIZE.has(name))name+='_Oversize';
  let time=0;mixer.stopAllAction();
  if(name){
   const clip=clips.get(name);if(!clip)throw new Error('Missing animation '+name);
   const action=mixer.clipAction(clip);action.reset().setLoop(THREE.LoopOnce,1);action.clampWhenFinished=true;action.play();
   const normalized=THREE.MathUtils.clamp(phase,0,1),frozen=FROZEN.has(name.replace('_Oversize',''));
   time=frozen?0:clip.duration*(normalized===1?1:(normalized*cycles)%1);mixer.setTime(time);
  }
  for(const m of Object.values(markers))m.visible=false;
  const status=['jammed','helper_walking'].includes(state)?'jammed':state==='service'?'service':state==='break'?'break':state==='disabled'?'offline':null;
  if(status&&markers[status])markers[status].visible=true;
  root.userData.visual_status=LABELS[state];root.userData.visual_state=state;root.updateMatrixWorld(true);
  const orderRelationship=actorType==='robot'&&['pack','jammed','helper_walking','service'].includes(state)?'robot-retains-order':state==='assist'?'helper-reference-only':'external';
  current=Object.freeze({state,clip:name,visualSeconds:time,status:LABELS[state],assignsOwnership:false,orderRelationship,productionRulesApplied:false});return current;
 }
 return {root,mixer,sample,get current(){return current;},orderPoint(kind='regular'){
  if(!(kind in ORDER_SIZES))throw new Error('Unknown order kind '+kind);root.updateMatrixWorld(true);return new THREE.Vector3(0,.86,.34).applyMatrix4(root.matrixWorld);
 },dispose(){mixer.stopAllAction();mixer.uncacheRoot(root);root.removeFromParent();}};
}

export function queueSlotPositions(bindings,queue,count){
 const q=bindings.queues[queue];if(!q)throw new Error('Unknown visual queue '+queue);if(!Number.isInteger(count)||count<0)throw new Error('Pass an explicit World capacity or visible count');
 const origin=q.origin_gltf_m;
 return Array.from({length:count},(_,i)=>[origin[0]+i%q.columns*q.spacing[0],origin[1],origin[2]-Math.floor(i/q.columns)*q.spacing[1]]);
}
export function manualWorkPosition(bindings,stage,index=0){
 const entry=bindings.stages.find(s=>s.stage===stage);if(!entry)throw new Error('Unknown work stage '+stage);if(!Number.isInteger(index)||index<0)throw new Error('Invalid worker slot');
 const p=[...entry.actor_position_gltf_m],direction=stage===4?1:-1;
 p[0]+=direction*(index%entry.parallel_slot_columns)*entry.parallel_slot_spacing_m[0];p[2]-=Math.floor(index/entry.parallel_slot_columns)*entry.parallel_slot_spacing_m[1];return p;
}
export function sampleWalkPath(points,phase){
 if(!Array.isArray(points)||points.length<2||!Number.isFinite(phase))throw new Error('A walk needs at least two visual path points and a finite phase');
 const vectors=points.map(p=>new THREE.Vector3().fromArray(p)),lengths=vectors.slice(1).map((p,i)=>p.distanceTo(vectors[i]));let remaining=THREE.MathUtils.clamp(phase,0,1)*lengths.reduce((a,b)=>a+b,0);
 for(let i=0;i<lengths.length;i++){
  if(remaining<=lengths[i]||i===lengths.length-1){const direction=vectors[i+1].clone().sub(vectors[i]);return {position:vectors[i].clone().lerp(vectors[i+1],lengths[i]?remaining/lengths[i]:0).toArray(),yaw:Math.atan2(direction.x,direction.z)};}remaining-=lengths[i];
 }
}
export function createOrderVisualPool(library){
 const objects=new Map();
 function key(runId,orderId){return JSON.stringify([runId,orderId]);}
 return {get size(){return objects.size;},getOrCreate({runId,orderId,kind}){
  if(runId===undefined||orderId===undefined)throw new Error('A visual order needs runId and orderId');if(!(kind in ORDER_SIZES))throw new Error('Unknown order kind '+kind);
  const id=key(runId,orderId);if(objects.has(id)){const ob=objects.get(id);if(ob.userData.order_kind!==kind)throw new Error('Order kind changed for '+id);return ob;}
  const ob=templateClone(library,'order_'+kind);ob.name='ORDER_'+id;Object.assign(ob.userData,{run_id:runId,order_id:orderId,order_kind:kind});objects.set(id,ob);return ob;
 },removeRun(runId){for(const [id,ob] of objects){if(ob.userData.run_id===runId){ob.removeFromParent();objects.delete(id);}}},dispose(){for(const ob of objects.values())ob.removeFromParent();objects.clear();}};
}
