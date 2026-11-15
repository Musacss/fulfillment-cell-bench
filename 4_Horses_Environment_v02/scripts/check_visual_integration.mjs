import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
const url=new URL('../dist/assets/three.module.js',import.meta.url).href;
registerHooks({resolve(s,c,next){return s==='three'?{url,shortCircuit:true}:next(s,c);}});
const THREE=await import(url),{GLTFLoader}=await import('../dist/assets/GLTFLoader.js');
const {createActorVisual,createOrderVisualPool,queueSlotPositions,manualWorkPosition,sampleWalkPath,hideEnvironmentReplayOrders}=await import('../dist/assets/visual-integration.js');
async function load(file){const b=await fs.readFile(new URL('../dist/assets/'+file,import.meta.url));return new Promise((res,rej)=>new GLTFLoader().parse(b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength),'',res,rej));}
const [worker,robot,templates,layout,environment]=await Promise.all(['warehouse_worker.glb','humanoid_robot.glb','visual_support.glb','visual_layout.glb','warehouse_environment.glb'].map(load));
const bindings=JSON.parse(await fs.readFile(new URL('../config/visual_bindings.json',import.meta.url)));
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
for(const state of ['jammed','helper_walking','service','disabled']){
 machine.sample({state,phase:0});const before=signature(machine);machine.sample({state,phase:.91});assert.deepEqual(signature(machine),before,'Blocked robot continued working');
}
machine.sample({state:'jammed',phase:.2});const jam=signature(machine);machine.sample({state:'service',phase:.8});assert.deepEqual(signature(machine),jam,'Service restarted the packaging cycle');
for(const orderKind of ['regular','oversize']){
 machine.sample({state:'pack',phase:1,orderKind});const end=signature(machine);
 machine.sample({state:'jammed',phase:0,orderKind});const stopped=signature(machine);
 assert.ok(end.every((v,i)=>Math.abs(v-stopped[i])<1e-5),'Jam snapped back to another packing pose');
 machine.sample({state:'service',phase:.8,orderKind});assert.deepEqual(signature(machine),stopped,'Servicing moved the frozen order');
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
console.log(JSON.stringify({passed:true,contract_source:'attached v1 document; private core unavailable',new_worker_clips:10,new_robot_clips:7,queues:['Q1','Q2','Q3','Q4','R'],variable_capacity:true,oversize_slots_do_not_overlap:true,work_anchor_matches_order_origin:true,parallel_manual_positions:true,independent_actors:true,same_order_id_across_runs:true,production_demo_props_hidden:true,blocked_robot_frozen:true,jam_matches_packing_end:true,service_does_not_restart_cycle:true,deterministic_pose_seek:true,legacy_demonstration_boxes_identified:true},null,2));
