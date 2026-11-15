// Portable v02 runtime verification: actual GLBs, production adapter and geometry.
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import validator from 'gltf-validator';
import {environmentLayers,applyEnvironmentDefaults,setEnvironmentLayer,setRobotAndonState} from '../visual/environment-layers.js';
import {createActorVisual,createOrderVisualPool,queueSlotPositions,manualWorkPosition,sampleWalkPath,hideEnvironmentReplayOrders} from '../visual/visual-integration.js';
const root=new URL('../',import.meta.url);
async function load(file,base=root){const b=await fs.readFile(new URL(file,base));return new Promise((res,rej)=>new GLTFLoader().parse(b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength),'',res,rej));}
const [worker,robot,templates,layout,environment]=await Promise.all(['modules/warehouse_worker.glb','modules/humanoid_robot.glb','modules/visual_support.glb','modules/visual_layout.glb','warehouse_environment.glb'].map(f=>load(f)));
const bindings=JSON.parse(await fs.readFile(new URL('visual_bindings.json',root)));
const vec=new THREE.Vector3();
const near=(a,b,label,tolerance=2e-5)=>assert.ok(Math.abs(a-b)<=tolerance,`${label}: ${a} vs ${b}`);
const bounds=o=>new THREE.Box3().setFromObject(o,true);
for(const stage of bindings.stages){assert.ok(layout.scene.getObjectByName(stage.actor_anchor));assert.ok(layout.scene.getObjectByName(stage.order_anchor));}
for(const q of Object.values(bindings.queues))assert.ok(layout.scene.getObjectByName(q.anchor));
for(const q of Object.values(bindings.queues)){
 assert.ok(Math.abs(q.spacing[0])>=.48+.04,'Oversize orders overlap horizontally');
 assert.ok(Math.abs(q.spacing[1])>=.34+.04,'Oversize orders overlap between rows');
}
assert.equal(queueSlotPositions(bindings,'Q2',17).length,17,'Preview slot count became a capacity');
assert.equal(queueSlotPositions(bindings,'R',101).length,101,'Rework queue was capped');
assert.notDeepEqual(manualWorkPosition(bindings,3,0),manualWorkPosition(bindings,3,1),'Parallel manual workers share a work point');
assert.deepEqual(sampleWalkPath([[0,0,0],[2,0,0],[2,0,2]],.5).position,[2,0,0]);
const pool=createOrderVisualPool(templates.scene),first=pool.getOrCreate({runId:'A',orderId:7,kind:'fragile'});
assert.equal(pool.getOrCreate({runId:'A',orderId:7,kind:'fragile'}),first);assert.notEqual(pool.getOrCreate({runId:'B',orderId:7,kind:'fragile'}),first);
pool.removeRun('A');assert.equal(pool.size,1);pool.dispose();assert.equal(pool.size,0);
for(const kind of ['regular','fragile','oversize'])assert.ok(templates.scene.getObjectByName('VIS_order_'+kind));
const standard=new THREE.Box3().setFromObject(templates.scene.getObjectByName('VIS_order_regular')).getSize(new THREE.Vector3()),large=new THREE.Box3().setFromObject(templates.scene.getObjectByName('VIS_order_oversize')).getSize(new THREE.Vector3());assert.ok(large.x>standard.x&&large.y>standard.y&&large.z>standard.z);
const human=createActorVisual(worker,{actorType:'worker',templates:templates.scene}),machine=createActorVisual(robot,{actorType:'robot',templates:templates.scene});
const station=bindings.stages[0];human.sample({state:'pack',position:station.actor_position_gltf_m,yaw:station.yaw_gltf_rad});
const expectedAnchor=layout.scene.getObjectByName(station.order_anchor).getWorldPosition(new THREE.Vector3());
assert.ok(human.orderPoint().distanceTo(expectedAnchor)<1e-5,'Order template origin does not match the work anchor');
human.root.position.set(0,0,0);human.root.rotation.y=0;
const signature=actor=>{actor.root.updateMatrixWorld(true);const values=[];actor.root.traverse(o=>{if(o.isBone)values.push(...o.matrixWorld.elements);});return values;};
for(const [state,clip] of [['prepare','Prepare'],['pick','Pick'],['pack','Pack'],['inspect','Inspect'],['assist','Assist'],['break','Break'],['walk','Walk']]){
 assert.equal(human.sample({state,phase:.37}).clip,clip);let demoVisible=false;human.root.traverse(o=>{if(o.userData.handling_prop&&o.visible)demoVisible=true;});assert.equal(demoVisible,false,'Demonstration prop became a production order');
}
assert.equal(human.sample({state:'pack',orderKind:'oversize',phase:.3}).clip,'Pack_Oversize');
const frozenMachine=createActorVisual(robot,{actorType:'robot',templates:templates.scene,animateRecovery:false});
for(const state of ['jammed','helper_walking','service','disabled']){
 frozenMachine.sample({state,phase:0});const before=signature(frozenMachine);frozenMachine.sample({state,phase:.91});assert.deepEqual(signature(frozenMachine),before,'Frozen recovery robot moved');
}
frozenMachine.dispose();
const propVisibility=actor=>['prop_shell','prop_flap_front','prop_flap_back','prop_flap_left','prop_flap_right','prop_tape'].map(n=>{const b=actor.root.getObjectByName(n);return b?b.scale.lengthSq()>1e-4:false;});
for(const orderKind of ['regular','oversize']){
 const jamClip=orderKind==='oversize'?'Jammed_Oversize':'Jammed';
 const svcClip=orderKind==='oversize'?'Service_Oversize':'Service';
 const jamSample=machine.sample({state:'jammed',phase:.2,orderKind});
 assert.equal(jamSample.clip,jamClip);assert.equal(jamSample.activeCartonProp,true);
 const jamVis=propVisibility(machine);
 assert.equal(machine.sample({state:'helper_walking',phase:.6,orderKind}).clip,jamClip);
 assert.deepEqual(propVisibility(machine),jamVis,'Helper walk altered jammed prop visibility');
 const svcSample=machine.sample({state:'service',phase:.8,orderKind});
 assert.equal(svcSample.clip,svcClip);assert.equal(svcSample.activeCartonProp,true);
}
assert.equal(machine.sample({state:'service'}).assignsOwnership,false,'Presentation adapter assigned an order');
assert.equal(machine.current.orderRelationship,'robot-retains-order');
assert.equal(human.sample({state:'assist'}).orderRelationship,'helper-reference-only');
machine.sample({state:'not_purchased'});assert.equal(machine.root.visible,false);machine.sample({state:'disabled'});assert.equal(machine.root.visible,true);
const second=createActorVisual(worker,{actorType:'worker'});second.sample({state:'break',phase:.2});const untouched=signature(second);human.sample({state:'pack',phase:.5});assert.deepEqual(signature(second),untouched,'Workers share pose bones');
const expected=human.sample({state:'inspect',phase:.7});const pose=signature(human);human.sample({state:'inspect',phase:.1});human.sample({state:'inspect',phase:.7});assert.deepEqual(signature(human),pose,'Pose depends on seek direction');
assert.throws(()=>human.sample({state:'unknown'}),/Unsupported/);
assert.throws(()=>pool.getOrCreate({runId:'a',orderId:0,kind:'future'}),/Unknown/);
assert.ok(hideEnvironmentReplayOrders(environment.scene)>0,'Old demonstration boxes were not identified');
human.dispose();second.dispose();machine.dispose();

// Immutable integration coordinates, exact support heights and bottom-centered templates.
for(const [name,q] of Object.entries(bindings.queues)){
 const actual=layout.scene.getObjectByName(q.anchor).getWorldPosition(new THREE.Vector3()).toArray();
 actual.forEach((v,i)=>near(v,q.origin_gltf_m[i],name+' origin'));
 for(let i=0;i<q.preview_count;i++){
  const anchor=layout.scene.getObjectByName(q.anchor+'_SLOT_'+String(i).padStart(2,'0'));
  assert.ok(anchor,'Missing slot '+name+'/'+i);
  const expected=queueSlotPositions(bindings,name,q.preview_count)[i];
  anchor.getWorldPosition(vec).toArray().forEach((v,k)=>near(v,expected[k],name+' slot'+i));
 }
}
for(const stage of bindings.stages){
 const a=layout.scene.getObjectByName(stage.order_anchor).getWorldPosition(new THREE.Vector3());near(a.y,.86,'Stage'+stage.stage+' order height');
}
for(const [key,q] of Object.entries(bindings.outcomes)){
 layout.scene.getObjectByName(q.anchor).getWorldPosition(vec).toArray().forEach((v,i)=>near(v,q.position_gltf_m[i],key+' outcome'));
}
const helper=layout.scene.getObjectByName('VIS_ROBOT_ASSIST').getWorldPosition(new THREE.Vector3());
helper.toArray().forEach((v,i)=>near(v,[2.8,0,-1.95][i],'Robot helper'));
const pivots={};
for(const id of ['order_regular','order_fragile','order_oversize','order_tray','reserved_slot','empty_slot']){
 const ob=templates.scene.getObjectByName('VIS_'+id);assert.ok(ob,id);
 const b=bounds(ob);near(b.min.y,0,id+' bottom pivot');
 near((b.min.x+b.max.x)/2,0,id+' x center',.005);
 near((b.min.z+b.max.z)/2,0,id+' z center',.005);
 pivots[id]={min:b.min.toArray(),max:b.max.toArray()};
}
const trayBox=bounds(templates.scene.getObjectByName('VIS_order_tray'));
near(trayBox.max.x-trayBox.min.x,.54,'Tray width');near(trayBox.max.z-trayBox.min.z,.40,'Tray depth');
assert.equal(bindings.templates.length,14,'Template count');
for(const id of bindings.templates)assert.ok(templates.scene.getObjectByName(id),'Missing '+id);
const bufferResults=[];
for(const name of ['Q2','Q3','Q4']){
 const q=bindings.queues[name],g=layout.scene.getObjectByName('VIS_QUEUE_'+name+'_FRAME');assert.ok(g,'Missing flow rack '+name);
 const top=layout.scene.getObjectByName('VIS_QUEUE_'+name+'_TOP');near(bounds(top).max.y,.86,name+' roller height');
 const rollers=[];g.traverse(o=>{if(o.isMesh&&(/_ROLLER_/.test(o.name)||o.name==='VIS_QUEUE_'+name+'_TOP'))rollers.push(o);});assert.ok(rollers.length>=10,name+' roller rows');
 const rollerEnvelope=new THREE.Box3();for(const ob of rollers)rollerEnvelope.union(bounds(ob));
 const guides=[];g.traverse(o=>{if(o.isMesh&&o.name.includes('_GUIDE'))guides.push(bounds(o));});
 for(const [i,pos] of queueSlotPositions(bindings,name,q.preview_count).entries()){
  const minX=pos[0]-.27,maxX=pos[0]+.27,minZ=pos[2]-.20,maxZ=pos[2]+.20;
  assert.ok(rollerEnvelope.min.x<=minX+2e-5&&rollerEnvelope.max.x>=maxX-2e-5&&rollerEnvelope.min.z<=minZ+2e-5&&rollerEnvelope.max.z>=maxZ-2e-5,name+' tray lacks full support at '+i);
  for(const guide of guides){
   const overlapX=Math.min(maxX,guide.max.x)-Math.max(minX,guide.min.x),overlapZ=Math.min(maxZ,guide.max.z)-Math.max(minZ,guide.min.z);
   assert.ok(overlapX<.0001||overlapZ<.0001,name+' guide intrudes into tray '+i);
  }
 }
 const label=layout.scene.getObjectByName('VIS_QUEUE_'+name+'_LABEL');assert.ok(bounds(label).max.y<.84,name+' label on active surface');
 const infeed=layout.scene.getObjectByName('VIS_QUEUE_'+name+'_INFEED');assert.ok(infeed,name+' transition');
 bufferResults.push({queue:name,slots:q.preview_count,roller_rows:rollers.length,support_height_m:bounds(top).max.y,full_tray_support:true,guide_clearance:true});
}
// Transfer openings in the main conveyor must clear both the guard and sensors.
environment.scene.updateMatrixWorld(true);
const envMeshes=[];environment.scene.traverse(o=>{if(o.isMesh)envMeshes.push(o);});
for(const cx of [-6.46,.42,6.44])for(const dx of [-.25,0,.25])for(const h of [.90,.95]){
 const ray=new THREE.Raycaster(new THREE.Vector3(cx+dx,h,.24),new THREE.Vector3(0,0,1),0,.24);
 const hits=ray.intersectObjects(envMeshes,false);
 assert.equal(hits.length,0,'Conveyor guard/sensor blocks transfer at '+[cx+dx,h]+': '+hits.map(h=>h.object.name).join(','));
}
for(let i=1;i<=10;i++){
 assert.ok(environment.scene.getObjectByName('CONVEYOR_'+String(i).padStart(2,'0')),'Missing conveyor'+i);
 for(let j=1;j<=20;j++)assert.ok(environment.scene.getObjectByName('ROLLER_'+String(i).padStart(2,'0')+'_'+String(j).padStart(2,'0')),'Missing dynamic roller'+i+'/'+j);
}
for(const name of ['QC_PORTAL','STOPPER_GATE','PACK_PAPER_ROLL','SCRAP_BIN','ENV_FLOOR_AND_GRID','ENV_OVERHEAD','ENV_WALLS_AND_DOCKS','ENV_WORKSTATIONS_DETAIL','ENV_ROBOT_CELL','ENV_BREAK_AREA'])assert.ok(environment.scene.getObjectByName(name),'Missing movable/layer '+name);
// Layer defaults and Andon changes must remain local to one environment instance.
const layerScene=environment.scene.clone(true),otherLayerScene=environment.scene.clone(true);
const materialsOf=ob=>Array.isArray(ob.material)?ob.material:[ob.material];
const materialSnapshot=ob=>materialsOf(ob).map(m=>({uuid:m.uuid,color:m.color.toArray(),emissive:m.emissive.toArray(),emissiveIntensity:m.emissiveIntensity}));
const dockRedNames=['DOCK_01_SIGNAL_RED','DOCK_02_SIGNAL_RED'];
for(const name of dockRedNames)assert.ok(layerScene.getObjectByName(name),'Missing dock signal '+name);
const dockSnapshots=dockRedNames.map(name=>materialSnapshot(layerScene.getObjectByName(name)));
const otherAndonSnapshots=['RED','AMBER','GREEN'].map(channel=>materialSnapshot(otherLayerScene.getObjectByName('ANDON_'+channel)));
applyEnvironmentDefaults(layerScene);
for(const [name,visible] of environmentLayers)assert.equal(layerScene.getObjectByName(name).visible,visible,'Layer default '+name);
assert.equal(layerScene.getObjectByName('ENV_OVERHEAD').visible,false,'Overhead must start hidden');
setEnvironmentLayer(layerScene,'ENV_OVERHEAD',true);assert.equal(layerScene.getObjectByName('ENV_OVERHEAD').visible,true);
setEnvironmentLayer(layerScene,'ENV_OVERHEAD',false);
for(const [state,active] of [['Idle','GREEN'],['Pack','GREEN'],['Jammed','RED'],['Service','AMBER']]){
 setRobotAndonState(layerScene,state);
 for(const channel of ['RED','AMBER','GREEN']){
  const ob=layerScene.getObjectByName('ANDON_'+channel);assert.equal(ob.userData.active,channel===active,'Andon active '+state);
  for(const m of materialsOf(ob))near(m.emissiveIntensity,channel===active?1.6:.02,'Andon intensity');
  assert.notEqual(materialsOf(ob)[0],materialsOf(otherLayerScene.getObjectByName('ANDON_'+channel))[0],'Andon materials shared between environment clones');
 }
 assert.deepEqual(dockRedNames.map(name=>materialSnapshot(layerScene.getObjectByName(name))),dockSnapshots,'Andon changed dock red signal');
 assert.deepEqual(['RED','AMBER','GREEN'].map(channel=>materialSnapshot(otherLayerScene.getObjectByName('ANDON_'+channel))),otherAndonSnapshots,'Andon state changed another environment clone');
}
assert.throws(()=>setEnvironmentLayer(layerScene,'UNREQUESTED_LAYER',false),/Unknown/);
assert.throws(()=>setRobotAndonState(layerScene,'unknown'),/Unsupported/);
const forbidden=[];environment.scene.traverse(o=>{if(/^(Dispatch carton|Inbound tote|CARTON_OPEN)/.test(o.name))forbidden.push(o.name);});assert.deepEqual(forbidden,[],'Embedded orders remain on production furniture');
const expectedWorker=['Idle','Walk','CarryIdle','Reach','PickUp','PlaceDown','CarryWalk','Prepare','Pick','Pack','Inspect','Assist','Break','Prepare_Oversize','Pick_Oversize','Pack_Oversize','Inspect_Oversize'];
const expectedRobot=['Idle','Walk','CarryIdle','Reach','PickUp','PlaceDown','CarryWalk','RobotPack','Jammed','Service','Offline','RobotPack_Oversize','Jammed_Oversize','Service_Oversize'];
assert.deepEqual(worker.animations.map(c=>c.name),expectedWorker,'Worker clips changed');assert.deepEqual(robot.animations.map(c=>c.name),expectedRobot,'Robot clips changed');
assert.ok(worker.scene.getObjectByName('WORKER_Helmet'),'Missing safety helmet');
const characterResults=[];
for(const [label,model,bones] of [['worker',worker,35],['robot',robot,41]]){
 const skins=[];model.scene.traverse(o=>{if(o.isSkinnedMesh)skins.push(o);});assert.ok(skins.length>0);
 assert.equal(skins[0].skeleton.bones.length,bones,label+' bone count');
 for(const side of ['L','R'])assert.ok(model.scene.getObjectByName('ATTACH_'+label.toUpperCase()+'_HAND_'+side),'Missing grip attachment');
 const mixer=new THREE.AnimationMixer(model.scene),p=new THREE.Vector3();let samples=0;
 for(const clip of model.animations){
  mixer.stopAllAction();const action=mixer.clipAction(clip);action.setLoop(THREE.LoopOnce,1);action.clampWhenFinished=true;action.play();
  for(const phase of [0,.5,1]){
   mixer.setTime(clip.duration*phase);model.scene.updateMatrixWorld(true);
   for(const skin of skins){skin.skeleton.update();for(let i=0;i<skin.geometry.attributes.position.count;i++){
    skin.getVertexPosition(i,p).applyMatrix4(skin.matrixWorld);assert.ok(p.toArray().every(Number.isFinite),'Invalid skinned vertex');
    assert.ok(Math.abs(p.x)<1&&Math.abs(p.z)<1&&p.y>-.07&&p.y<2.05,'Unbounded '+label+' deformation '+clip.name+':'+p.toArray());samples++;
   }}
  }
 }
 mixer.stopAllAction();characterResults.push({character:label,bones,clips:model.animations.length,skinned_primitives:skins.length,vertex_pose_samples:samples});
}
const glbFiles=['warehouse_environment.glb',...(await fs.readdir(new URL('modules/',root))).filter(f=>f.endsWith('.glb')).map(f=>'modules/'+f)];
const validation=[];
for(const file of glbFiles){const bytes=new Uint8Array(await fs.readFile(new URL(file,root))),r=await validator.validateBytes(bytes,{uri:file,maxIssues:100});validation.push({file,bytes:bytes.length,errors:r.issues.numErrors,warnings:r.issues.numWarnings,messages:r.issues.messages});}
assert.ok(validation.every(r=>r.errors===0),'Invalid glTF: '+JSON.stringify(validation.filter(r=>r.errors)));
const envBytes=validation.find(x=>x.file==='warehouse_environment.glb').bytes;assert.ok(envBytes<12*1024*1024,'Environment exceeds12MiB');
const report={passed:true,loader:'Three.js0.170.0',adapter_original_checks:true,anchors_preserved:true,templates:14,bottom_center_pivots:pivots,buffers:bufferResults,transfer_ports_clear:true,layer_defaults:true,overhead_default_hidden:true,andon_states:['Idle','Pack','Jammed','Service'],andon_materials_isolated:true,dock_signals_unchanged:true,dynamic_rollers:200,characters:characterResults,gltf:validation,environment_bytes:envBytes};
await fs.writeFile(new URL('v02_runtime_check.json',root),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report,null,2));
