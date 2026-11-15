// Visual assets adapter only. No scheduling, event reduction, random outcomes or economics.
import * as THREE from 'three';

export const OPERATIONAL_PROP_BONES=Object.freeze([
  'prop_closed','prop_shell',
  'prop_flap_front','prop_flap_back','prop_flap_left','prop_flap_right',
  'prop_item','prop_tote','prop_tape',
]);
const OPERATIONAL_PROP_SET=new Set(OPERATIONAL_PROP_BONES);
const DEMO_ONLY_NAME_RE=/(?:^|_)(?:DemoSupport|prop_stand)(?:$|_|\.)/i;
const LEGACY_PROP_CARTON_RE=/^(?:WORKER|ROBOT)_PROP_CARTON$/i;
const LEGACY_DEMO_CARTON_RE=/_DemoCarton(?:$|_|\.)/;
const BENCH_TRAY_CLIPS=new Set(['Prepare','Pick','Pack','RobotPack','Inspect','Jammed','Service','PickUp','PlaceDown','Reach']);
const SINGLE_SHOT_CLIPS=new Set(['PickUp','PlaceDown','Reach']);

export const WORKER_CLIPS=Object.freeze({
  idle:'Idle',walk:'Walk',
  carry_idle:'CarryIdle',carryIdle:'CarryIdle',
  carry_walk:'CarryWalk',carryWalk:'CarryWalk',
  reach:'Reach',
  pickup:'PickUp',pick_up:'PickUp',pickUp:'PickUp',
  placedown:'PlaceDown',place_down:'PlaceDown',placeDown:'PlaceDown',
  prepare:'Prepare',pick:'Pick',pack:'Pack',inspect:'Inspect',assist:'Assist',break:'Break',
});
export const ROBOT_CLIPS=Object.freeze({
  not_purchased:null,disabled:'Offline',idle:'Idle',walk:'Walk',
  carry_idle:'CarryIdle',carryIdle:'CarryIdle',
  carry_walk:'CarryWalk',carryWalk:'CarryWalk',
  reach:'Reach',
  pickup:'PickUp',pick_up:'PickUp',pickUp:'PickUp',
  placedown:'PlaceDown',place_down:'PlaceDown',placeDown:'PlaceDown',
  pack:'RobotPack',jammed:'Jammed',helper_walking:'Jammed',service:'Service',finished:'Idle',
});
export const ORDER_SIZES={regular:[.36,.28,.25],fragile:[.36,.28,.25],oversize:[.48,.34,.32]};
const OVERSIZE=new Set(['Prepare','Pick','Pack','Inspect','RobotPack','Jammed','Service']);
const FROZEN=new Set(['Jammed','Service','Offline']);
const LABELS={
  idle:'Idle',walk:'Walking',
  carry_idle:'Holding Order',carryIdle:'Holding Order',
  carry_walk:'Carrying Order',carryWalk:'Carrying Order',
  reach:'Reaching',
  pickup:'Picking Up',pick_up:'Picking Up',pickUp:'Picking Up',
  placedown:'Placing Down',place_down:'Placing Down',placeDown:'Placing Down',
  prepare:'Preparing',pick:'Picking',pack:'Packing',inspect:'Inspecting',assist:'Assisting Robot',break:'Break',
  not_purchased:'Not Purchased',disabled:'Disabled',jammed:'Jammed',helper_walking:'Helper En Route',service:'Servicing',finished:'Finished',
};
const MANUAL_STAGE_ACTORS=Object.freeze({
  1:Object.freeze([[-11.00,0,-1.00],[-12.68,0,-1.00],[-12.68,0,-2.85],[-11.35,0,-5.00],[-9.80,0,-5.00],[-10.45,0,-6.05],[-11.60,0,-6.05],[-12.75,0,-6.05]]),
  2:Object.freeze([[-5.40,0,-2.05],[-7.00,0,-2.05],[-4.60,0,-4.95],[-6.05,0,-4.95],[-7.50,0,-4.95],[-4.60,0,-7.35],[-6.05,0,-7.35],[-7.50,0,-7.35]]),
  3:Object.freeze([[1.80,0,-2.05],[.20,0,-2.05],[-1.40,0,-2.05],[-2.90,0,-2.05],[1.85,0,-4.95],[.60,0,-4.95],[-.65,0,-4.95],[-2.92,0,-4.95]]),
  4:Object.freeze([[6.00,0,-2.05],[7.60,0,-2.05],[5.96,0,-4.95],[7.09,0,-4.95],[8.21,0,-4.95],[6.61,0,-6.35],[6.61,0,-7.88],[7.56,0,-1.35]]),
});

function collectSkinnedBoneNames(node,out=new Set()){
  node.traverse(child=>{
    if(!child.isSkinnedMesh||!child.skeleton||!child.geometry)return;
    const si=child.geometry.getAttribute('skinIndex'),sw=child.geometry.getAttribute('skinWeight');
    if(!si||!sw)return;
    for(let i=0;i<si.count;i++)for(let c=0;c<4;c++)if(sw.getComponent(i,c)>0){
      const boneName=child.skeleton.bones[si.getComponent(i,c)]?.name;
      if(boneName)out.add(boneName);
    }
  });
  return out;
}

export function isDemoOnlyProp(ob){
  for(let p=ob;p;p=p.parent){
    const ud=p.userData||{};
    if(ud.demo_only===true||ud.handling_prop==='support'||ud.handling_prop==='prop_stand')return true;
    if(DEMO_ONLY_NAME_RE.test(p.name||''))return true;
    if(LEGACY_PROP_CARTON_RE.test(p.name||'')&&ud.operation_prop!==true)return true;
  }
  if(ob.isSkinnedMesh){
    const used=collectSkinnedBoneNames(ob);
    if(used.size>0&&[...used].every(b=>b==='prop_stand'))return true;
  }
  return false;
}

export function isOperationalProp(ob){
  if(!ob||ob.isBone||isDemoOnlyProp(ob))return false;
  for(let p=ob;p;p=p.parent){
    const ud=p.userData||{};
    if(ud.operation_prop===true||OPERATIONAL_PROP_SET.has(ud.handling_prop))return true;
  }
  const used=collectSkinnedBoneNames(ob);
  return [...used].some(b=>OPERATIONAL_PROP_SET.has(b));
}

export function hasOperationalProps(root){
  if(!root?.getObjectByName)return false;
  const hasBones=Boolean(root.getObjectByName('prop_shell')&&root.getObjectByName('prop_flap_front')&&root.getObjectByName('prop_closed'));
  if(!hasBones)return false;
  let hasMesh=false;
  root.traverse(ob=>{if(!hasMesh&&ob.isMesh&&isOperationalProp(ob))hasMesh=true;});
  return hasMesh;
}

export function cloneActorRig(source){
 const clone=source.clone(true),lookup=new Map();
 function pair(a,b){lookup.set(a,b);a.children.forEach((child,i)=>pair(child,b.children[i]));}pair(source,clone);
 source.traverse(ob=>{
  if(!ob.isSkinnedMesh)return;
  const copy=lookup.get(ob),skeleton=ob.skeleton.clone();
  skeleton.bones=ob.skeleton.bones.map(b=>lookup.get(b));
  if(skeleton.bones.some(b=>!b))throw new Error('Skeleton joint is outside the actor root');
  copy.bind(skeleton,ob.bindMatrix);
  copy.frustumCulled=false;
 });
 clone.traverse(ob=>{if(ob.isSkinnedMesh)ob.frustumCulled=false;});
 return clone;
}
export function hideDemonstrationProps(root){
 let hidden=0;
 root.traverse(ob=>{
  if(ob.isBone)return;
  if(isDemoOnlyProp(ob)){ob.visible=false;hidden++;return;}
  if(isOperationalProp(ob))return;
  if(ob.userData?.handling_prop||LEGACY_DEMO_CARTON_RE.test(ob.name||'')){ob.visible=false;hidden++;}
 });
 return hidden;
}
export function hideEnvironmentReplayOrders(root){
 let hidden=0;root.traverse(ob=>{if(ob.userData.animation_role==='parcel'||ob.userData.parcel_id){ob.visible=false;hidden++;}});return hidden;
}
export function templateClone(library,name){
 const source=library.getObjectByName('VIS_'+name);if(!source)throw new Error('Missing visual template VIS_'+name);return source.clone(true);
}

function addWorldDeltaY(bone,dy,invMat3,deltaVec){
 if(!bone?.parent||!dy)return;
 invMat3.setFromMatrix4(bone.parent.matrixWorld).invert();
 deltaVec.set(0,dy,0).applyMatrix3(invMat3);
 bone.position.add(deltaVec);
}

function boneScaleSq(bone){
 if(!bone)return 0;
 const e=bone.matrixWorld.elements;
 return e[0]*e[0]+e[1]*e[1]+e[2]*e[2];
}

export function robotAssistPose(bindings,layout=null){
 const helperAnchor=layout?.getObjectByName?.(bindings?.robot?.helper_anchor||'VIS_ROBOT_ASSIST');
 const orderAnchor=layout?.getObjectByName?.(bindings?.robot?.order_anchor||'VIS_ROBOT_ORDER');
 const position=helperAnchor?helperAnchor.getWorldPosition(new THREE.Vector3()).toArray():[...(bindings?.robot?.helper_position_gltf_m||[2.8,0,-1.95])];
 const target=orderAnchor?orderAnchor.getWorldPosition(new THREE.Vector3()).toArray():[...(bindings?.robot?.order_position_gltf_m||[3.5,.86,-2.39])];
 const dx=target[0]-position[0],dz=target[2]-position[2],len=Math.hypot(dx,dz)||1;
 const computedYaw=Math.atan2(dx,dz);
 const rawYaw=bindings?.robot?.helper_yaw_gltf_rad;
 const validRaw=Number.isFinite(rawYaw)&&((Math.sin(rawYaw)*dx+Math.cos(rawYaw)*dz)/len>.995);
 return {position,target,yaw:validRaw?rawYaw:computedYaw};
}

export function createActorVisual(gltf,{actorType,templates=null,demoProps=false,animateRecovery=null}={}){
 if(!['worker','robot'].includes(actorType))throw new Error('actorType must be worker or robot');
 const root=cloneActorRig(gltf.scene),clips=new Map(gltf.animations.map(c=>[c.name,c])),mixer=new THREE.AnimationMixer(root);
 const states=actorType==='worker'?WORKER_CLIPS:ROBOT_CLIPS;
 if(!demoProps)hideDemonstrationProps(root);
 const operationalProps=hasOperationalProps(root);
 const freezeRecovery=animateRecovery===null?!operationalProps:!animateRecovery;
 const restPositions=new Map(),restQuaternions=new Map(),restScales=new Map();
 root.traverse(b=>{if(b.isBone){restPositions.set(b,b.position.clone());restQuaternions.set(b,b.quaternion.clone());restScales.set(b,b.scale.clone());}});
 const chestBone=root.getObjectByName('chest');
 const propBoxBone=root.getObjectByName('prop_box');
 const cartonBones=['prop_closed','prop_shell'].map(n=>root.getObjectByName(n)).filter(Boolean);
 const extraRootPropBones=['prop_item','prop_tote'].map(n=>root.getObjectByName(n)).filter(Boolean);
 const kindUpper=actorType.toUpperCase();
 const handSockets=['L','R'].map(s=>root.getObjectByName(`ATTACH_${kindUpper}_HAND_${s}`)||root.getObjectByName(`FBF_ATTACH_${kindUpper}_HAND_${s}`)).filter(Boolean);
 const invMat3=new THREE.Matrix3(),deltaVec=new THREE.Vector3(),tmpA=new THREE.Vector3(),tmpB=new THREE.Vector3();
 const marker=new THREE.Group();marker.name='VIS_ActorStatus';marker.position.set(0,2.04,0);root.add(marker);
 const markers={};if(templates){for(const key of ['jammed','service','break','offline']){const ob=templateClone(templates,'status_'+key);ob.visible=false;marker.add(ob);markers[key]=ob;}}
 let current=null;
 function sample({state,phase=0,orderKind='regular',cycles=1,position=null,yaw=null,trayOffset=0,suppressPropCarton=false}={}){
  if(!(state in states))throw new Error('Unsupported '+actorType+' visual state '+state);
  if(!(orderKind in ORDER_SIZES))throw new Error('Unsupported order kind '+orderKind);
  if(!Number.isFinite(phase)||!Number.isFinite(cycles)||cycles<0||!Number.isFinite(trayOffset))throw new Error('Visual phase and cycles must be finite');
  root.visible=state!=='not_purchased';if(position)root.position.fromArray(position);if(yaw!==null)root.rotation.y=yaw;
  for(const [bone,pos] of restPositions)bone.position.copy(pos);
  for(const [bone,quat] of restQuaternions)bone.quaternion.copy(quat);
  for(const [bone,sc] of restScales)bone.scale.copy(sc);
  let name=states[state];const baseName=name;
  if(orderKind==='oversize'&&OVERSIZE.has(name))name+='_Oversize';
  let time=0;mixer.stopAllAction();
  if(name){
   const clip=clips.get(name);if(!clip)throw new Error('Missing animation '+name);
   const action=mixer.clipAction(clip);action.reset().setLoop(THREE.LoopOnce,1);action.clampWhenFinished=true;action.play();
   const normalized=THREE.MathUtils.clamp(phase,0,1),frozen=freezeRecovery&&FROZEN.has(baseName);
   const safeDur=Math.max(0,clip.duration-1e-5);
   time=frozen?0:SINGLE_SHOT_CLIPS.has(baseName)?safeDur*normalized:safeDur*(normalized===1?1:(normalized*cycles)%1);
   mixer.setTime(time);
  }
  if(suppressPropCarton){for(const b of cartonBones)b.scale.set(0,0,0);for(const b of extraRootPropBones)b.scale.set(0,0,0);}
  for(const m of Object.values(markers))m.visible=false;
  const status=['jammed','helper_walking'].includes(state)?'jammed':state==='service'?'service':state==='break'?'break':state==='disabled'?'offline':null;
  if(status&&markers[status])markers[status].visible=true;
  root.userData.visual_status=LABELS[state];root.userData.visual_state=state;root.updateMatrixWorld(true);
  const activeCartonProp=Boolean(root.visible&&name&&operationalProps&&cartonBones.some(b=>boneScaleSq(b)>1e-4));
  if(trayOffset!==0&&activeCartonProp&&BENCH_TRAY_CLIPS.has(baseName)){
   if(propBoxBone&&cartonBones.some(b=>b.parent===propBoxBone))addWorldDeltaY(propBoxBone,trayOffset,invMat3,deltaVec);
   for(const b of cartonBones)if(b.parent!==propBoxBone)addWorldDeltaY(b,trayOffset,invMat3,deltaVec);
   for(const b of extraRootPropBones)if(boneScaleSq(b)>1e-4)addWorldDeltaY(b,trayOffset,invMat3,deltaVec);
   if(chestBone)addWorldDeltaY(chestBone,trayOffset,invMat3,deltaVec);
   root.updateMatrixWorld(true);
  }
  const orderRelationship=actorType==='robot'&&['pack','jammed','helper_walking','service'].includes(state)?'robot-retains-order':state==='assist'?'helper-reference-only':'external';
  current=Object.freeze({state,clip:name,visualSeconds:time,status:LABELS[state],assignsOwnership:false,orderRelationship,productionRulesApplied:false,activeCartonProp,trayOffset});return current;
 }
 function handMidpoint(target=new THREE.Vector3()){
  root.updateMatrixWorld(true);
  if(handSockets.length>=2){
   handSockets[0].getWorldPosition(tmpA);handSockets[1].getWorldPosition(tmpB);
   return target.copy(tmpA).add(tmpB).multiplyScalar(.5);
  }
  if(handSockets.length===1)return handSockets[0].getWorldPosition(target);
  return target.set(0,.96,.30).applyMatrix4(root.matrixWorld);
 }
 function carryPoint(target=new THREE.Vector3()){
  handMidpoint(target);
  const yaw=root.rotation.y;
  target.x+=Math.sin(yaw)*.08;target.y-=.11;target.z+=Math.cos(yaw)*.08;
  return target;
 }
 return {root,mixer,sample,hasOperationalProps:operationalProps,handMidpoint,carryPoint,get current(){return current;},orderPoint(kind='regular',{tray=false}={}){
  if(!(kind in ORDER_SIZES))throw new Error('Unknown order kind '+kind);root.updateMatrixWorld(true);return new THREE.Vector3(0,.86+(tray?.012:0),.34).applyMatrix4(root.matrixWorld);
 },dispose(){mixer.stopAllAction();mixer.uncacheRoot(root);root.traverse(o=>{if(o.isSkinnedMesh)o.skeleton?.dispose?.();});root.removeFromParent();}};
}

export function queueSlotPositions(bindings,queue,count){
 const q=bindings.queues[queue];if(!q)throw new Error('Unknown visual queue '+queue);if(!Number.isInteger(count)||count<0)throw new Error('Pass an explicit World capacity or visible count');
 const origin=q.origin_gltf_m;
 return Array.from({length:count},(_,i)=>[origin[0]+i%q.columns*q.spacing[0],origin[1],origin[2]-Math.floor(i/q.columns)*q.spacing[1]]);
}
export function manualWorkPosition(bindings,stage,index=0){
 const s=Number(stage),entry=bindings?.stages?.find?.(it=>it.stage===s);
 if(!entry||!MANUAL_STAGE_ACTORS[s])throw new Error('Unknown work stage '+stage);
 if(!Number.isInteger(index)||index<0||index>=MANUAL_STAGE_ACTORS[s].length)throw new Error('Invalid worker slot');
 if(index===0)return [...entry.actor_position_gltf_m];
 return [...MANUAL_STAGE_ACTORS[s][index]];
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
