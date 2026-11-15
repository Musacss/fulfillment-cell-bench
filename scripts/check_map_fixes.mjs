#!/usr/bin/env node
// Regressions for the six requested map corrections, against the actual GLBs.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {createHash} from 'node:crypto';
import * as THREE from '../studio/node_modules/three/build/three.module.js';
import {GLTFLoader} from '../studio/node_modules/three/examples/jsm/loaders/GLTFLoader.js';
import {applyMapGeometryFixes,MAP_GEOMETRY_FIXES} from '../studio/src/map-geometry.js';
import {applyMapFloorFixes} from '../studio/src/map-floor.js';
import {MAP_LAYOUT,isNativeExpandedMap} from '../studio/src/map-layout.js';

const ROOT=new URL('../',import.meta.url);
const near=(value,expected,label,tolerance=2e-5)=>assert.ok(Math.abs(value-expected)<=tolerance,`${label}: ${value} vs ${expected}`);
const bounds=object=>new THREE.Box3().setFromObject(object);
const visible=object=>{for(let o=object;o;o=o.parent)if(!o.visible)return false;return true;};
const materials=object=>Array.isArray(object.material)?object.material:[object.material];
const hashes=JSON.parse(await fs.readFile(new URL('studio/asset-hashes.json',ROOT)));
for(const [file,expected] of Object.entries(hashes)){
  const bytes=await fs.readFile(new URL(file,ROOT));
  assert.equal(createHash('sha256').update(bytes).digest('hex'),expected.sha256,`Original asset changed: ${file}`);
}
async function load(file){
  const bytes=await fs.readFile(new URL('4_Horses_Environment_v02/'+file,ROOT));
  return new Promise((resolve,reject)=>new GLTFLoader().parse(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),'',resolve,reject));
}
const [source,sourceLayout]=await Promise.all([load('warehouse_environment.glb'),load('modules/visual_layout.glb')]);
source.scene.updateMatrixWorld(true);sourceLayout.scene.updateMatrixWorld(true);
const prototypeState=[];
for(const root of [source.scene,sourceLayout.scene])root.traverse(object=>{
  if(object.isMesh)prototypeState.push({object,geometry:object.geometry,material:object.material,visible:object.visible,cast:object.castShadow,receive:object.receiveShadow});
});
const binding=JSON.parse(await fs.readFile(new URL('4_Horses_Environment_v02/visual_bindings.json',ROOT)));
const visualNames=binding.stages.flatMap(stage=>[stage.actor_anchor,stage.order_anchor]);
visualNames.push(binding.robot.actor_anchor,binding.robot.order_anchor,binding.robot.helper_anchor);
for(const queue of Object.values(binding.queues))visualNames.push(queue.anchor,...Array.from({length:queue.preview_count},(_,i)=>queue.anchor+'_SLOT_'+String(i).padStart(2,'0')));
visualNames.push(...Object.values(binding.outcomes).map(outcome=>outcome.anchor));
assert.equal(new Set(visualNames).size,61);

function instance(){
  const environment=source.scene.clone(true),layout=sourceLayout.scene.clone(true);
  for(const root of [environment,layout])root.traverse(o=>{if(o.isMesh){o.castShadow=true;o.receiveShadow=true;}});
  environment.updateMatrixWorld(true);layout.updateMatrixWorld(true);
  const nativeExpanded=isNativeExpandedMap(environment);
  const anchors=visualNames.map(name=>{const o=layout.getObjectByName(name);assert.ok(o,name);return {object:o,position:o.getWorldPosition(new THREE.Vector3()).toArray()};});
  environment.traverse(o=>{if(o.userData.kind==='anchor')anchors.push({object:o,position:o.getWorldPosition(new THREE.Vector3()).toArray()});});
  const oldSteel=environment.getObjectByName('PROPS__Satin_zinc_steel')?.geometry??null;
  const oldParent=environment.getObjectByName(MAP_GEOMETRY_FIXES.orphanRobotTop)?.parent??null;
  const originalLane=environment.getObjectByName('WALKWAY_GREEN_5S');
  const laneMaterial=originalLane.material;
  const reworkBenchInitialVisible=environment.getObjectByName('BENCH_REWORK')?.visible??null;
  return {environment,layout,nativeExpanded,anchors,oldSteel,oldParent,originalLane,laneMaterial,reworkBenchInitialVisible};
}
const a=instance(),b=instance();
const geometryA=applyMapGeometryFixes(a.environment,a.layout),floorA=applyMapFloorFixes(a.environment,a.layout);
assert.equal(applyMapGeometryFixes(a.environment,a.layout),geometryA);
assert.equal(applyMapFloorFixes(a.environment,a.layout),floorA);
if(!b.nativeExpanded){
  assert.equal(b.environment.getObjectByName('UTILITY_CABINET').visible,true,'Comparison B must not be modified by A');
  assert.equal(b.environment.getObjectByName(MAP_GEOMETRY_FIXES.orphanRobotTop).parent,b.oldParent);
}
assert.equal(b.originalLane.visible,true,'Comparison B lane must remain unchanged until patched');
const geometryB=applyMapGeometryFixes(b.environment,b.layout),floorB=applyMapFloorFixes(b.environment,b.layout);

function cabinetTriangleCount(environment){
  const region=new THREE.Box3(new THREE.Vector3(...MAP_GEOMETRY_FIXES.cabinetBounds.min),new THREE.Vector3(...MAP_GEOMETRY_FIXES.cabinetBounds.max));
  let triangles=0;const point=new THREE.Vector3();
  environment.traverse(mesh=>{
    if(!mesh.isMesh||!visible(mesh))return;
    let props=false;for(let p=mesh;p;p=p.parent)if(p.name==='PROPS')props=true;
    if(!props)return;
    const position=mesh.geometry.getAttribute('position'),index=mesh.geometry.index,count=index?index.count:position.count;
    for(let i=0;i<count;i+=3){
      if([0,1,2].every(k=>region.containsPoint(point.fromBufferAttribute(position,index?index.getX(i+k):i+k).applyMatrix4(mesh.matrixWorld))))triangles++;
    }
  });return triangles;
}

function checkInstance(view,geometryFix,floorFix){
  const {environment,layout,nativeExpanded}=view;environment.updateMatrixWorld(true);layout.updateMatrixWorld(true);
  assert.equal(cabinetTriangleCount(environment),0,'No visible cabinet body, door, feet or handle may remain');
  if(!nativeExpanded)assert.ok(geometryFix.report.cabinet.removedTriangles>1000);
  assert.equal(environment.getObjectByName(MAP_GEOMETRY_FIXES.orphanRobotTop),undefined,'No robot table fragment may remain at conveyor origin');
  let topBox;
  if(nativeExpanded){
    const nativeRobotTable=environment.getObjectByName('ROBOT_PACK_TABLE');
    assert.ok(nativeRobotTable&&visible(nativeRobotTable),'Native ROBOT_PACK_TABLE must be visible and grounded');
    topBox=bounds(nativeRobotTable);
    near(topBox.min.y,0,'Native robot table grounded',5e-3);
    near(topBox.max.y,.86,'Robot tabletop height',3e-3);
    near(topBox.min.x,2.95,'Robot tabletop left',5e-3);near(topBox.max.x,4.05,'Robot tabletop right',5e-3);
    near(topBox.min.z,-3.17,'Robot tabletop rear',5e-3);near(topBox.max.z,-2.13,'Robot tabletop front',5e-3);
  }else{
    const top=layout.getObjectByName(MAP_GEOMETRY_FIXES.orphanRobotTop);
    assert.equal(top.parent.name,'VIS_ROBOT_PACK_TABLE');assert.ok(visible(top));
    topBox=bounds(top);near(topBox.max.y,.86,'Robot tabletop height');
    near(topBox.min.x,2.95,'Robot tabletop left');near(topBox.max.x,4.05,'Robot tabletop right');
    near(topBox.min.z,-3.17,'Robot tabletop rear');near(topBox.max.z,-2.13,'Robot tabletop front');
  }
  const order=layout.getObjectByName('VIS_ROBOT_ORDER').getWorldPosition(new THREE.Vector3());
  assert.ok(topBox.min.x<=order.x-.27&&topBox.max.x>=order.x+.27&&topBox.min.z<=order.z-.2&&topBox.max.z>=order.z+.2,'Robot tray has complete top support');
  const ray=new THREE.Raycaster(new THREE.Vector3(.045,1.2,.1),new THREE.Vector3(0,-1,0),0,.5);
  const hits=ray.intersectObject(environment,true).filter(hit=>visible(hit.object));
  assert.ok(hits.some(hit=>hit.object.name==='ROLLER_06_01'),'Main rollers stay unobstructed at the old orphan-table location');
  assert.ok(hits.every(hit=>hit.object.name!=='VIS_Bench_top_robot_chamfer'));
  const benchRework=environment.getObjectByName('BENCH_REWORK');
  if(nativeExpanded){
    assert.ok(benchRework&&visible(benchRework),'Native BENCH_REWORK in north rework bay must remain visible');
    const brBox=bounds(benchRework);
    assert.ok(brBox.min.z>4.5&&brBox.min.y<=.005,'Native BENCH_REWORK grounded in north rework bay');
  }else{
    assert.equal(benchRework.visible,false);
  }
  const rework=environment.getObjectByName('QUEUE_R_ROLLER_SECTION');assert.ok(visible(rework));
  const rBox=bounds(rework);near(rBox.max.y,.86,'Rework tangent height',2e-3);assert.ok(rBox.min.y<1e-4,'Rework has its own floor supports');
  let rollers=0;environment.traverse(o=>{if(/^ROLLER_\d\d_\d\d$/.test(o.name))rollers++;});assert.equal(rollers,200);
  for(const anchor of view.anchors)assert.deepEqual(anchor.object.getWorldPosition(new THREE.Vector3()).toArray(),anchor.position,'Anchor moved: '+anchor.object.name);

  const patch=environment.getObjectByName('MAP_FLOOR_FIXES');assert.ok(patch);
  const arrows=patch.children.filter(o=>o.name.startsWith('MAP_WALKWAY_ARROW_'));
  assert.equal(arrows.length,3);assert.deepEqual(arrows.map(o=>o.userData.center_x),[...MAP_LAYOUT.arrowCenters]);
  assert.deepEqual(floorFix.report.endMargins,[5.9,5.9]);assert.equal(floorFix.report.arrowSpacing,11.8);
  assert.equal(floorFix.report.zebras,0);assert.equal(floorFix.report.wayfindingLabels,0);
  for(const name of floorFix.report.removedLaneBuckets)assert.equal(environment.getObjectByName(name).visible,false,'Old paint batch remains visible');
  assert.equal(environment.getObjectByName('WALKWAY_GREEN_5S').visible,false);
  for(const mesh of patch.children){
    assert.equal(mesh.castShadow,false);assert.equal(mesh.receiveShadow,false);
    for(const material of materials(mesh)){
      assert.equal(material.depthTest,true);assert.equal(material.depthWrite,true);assert.equal(material.polygonOffset,true);
      assert.ok(material.polygonOffsetUnits<0);
      assert.notEqual(material,view.laneMaterial);
    }
    const p=mesh.geometry.getAttribute('position'),n=mesh.geometry.getAttribute('normal');
    for(let i=0;i<p.count;i++){assert.ok(p.getY(i)>=.0059&&p.getY(i)<=.0081);assert.ok(n.getY(i)>.999,'New paint must face upward');}
  }
  const lane=environment.getObjectByName('MAP_WALKWAY_GREEN');near(bounds(lane).min.y,.006,'Stable lane elevation');
  for(const o of environment.getObjectByName('ENV_FLOOR_AND_GRID').children){
    if(o.userData.map_floor_decal){assert.equal(o.castShadow,false);assert.equal(o.receiveShadow,false);}
  }
  const label=bounds(environment.getObjectByName('MAP_ESCAPED_HOLD_LABEL')),zone=floorFix.report.holdZone;
  assert.ok(label.min.x>zone.minX&&label.max.x<zone.maxX&&label.min.z>zone.minZ&&label.max.z<zone.maxZ,'HOLD caption must fit inside its frame');
  assert.ok(zone.outerMinX>zone.qcRightEdge+.15&&zone.outerMinX>8.775,'HOLD must have a visible gap from the blue QC zone');
  return {anchors:view.anchors.length,mainRollers:rollers,cabinetVisibleTriangles:0,robotTopBounds:{min:topBox.min.toArray(),max:topBox.max.toArray()},reworkSupport:true,arrows:arrows.map(o=>o.userData.center_x),holdGap:zone.gapToQc};
}
const checkedA=checkInstance(a,geometryA,floorA),checkedB=checkInstance(b,geometryB,floorB);
if(!a.nativeExpanded){
  assert.notEqual(a.environment.getObjectByName('PROPS__Satin_zinc_steel').geometry,b.environment.getObjectByName('PROPS__Satin_zinc_steel').geometry,'Cabinet batch copies must be independent');
}
assert.notEqual(a.environment.getObjectByName('MAP_WALKWAY_GREEN').material,b.environment.getObjectByName('MAP_WALKWAY_GREEN').material,'Comparison paint must own per-instance materials');
for(const state of prototypeState){
  assert.equal(state.object.geometry,state.geometry);assert.equal(state.object.material,state.material);assert.equal(state.object.visible,state.visible);
  assert.equal(state.object.castShadow,state.cast);assert.equal(state.object.receiveShadow,state.receive);
}
for(const [view,geometryFix,floorFix] of [[a,geometryA,floorA],[b,geometryB,floorB]]){
  floorFix.dispose();geometryFix.dispose();floorFix.dispose();geometryFix.dispose();
  if(!view.nativeExpanded){
    assert.equal(view.environment.getObjectByName('PROPS__Satin_zinc_steel').geometry,view.oldSteel);
    assert.equal(view.environment.getObjectByName(MAP_GEOMETRY_FIXES.orphanRobotTop).parent,view.oldParent);
  }
  if(view.reworkBenchInitialVisible!==null)assert.equal(view.environment.getObjectByName('BENCH_REWORK').visible,view.reworkBenchInitialVisible);
  assert.equal(view.originalLane.visible,true);assert.equal(view.originalLane.material,view.laneMaterial);
  assert.equal(view.environment.getObjectByName('MAP_FLOOR_FIXES'),undefined);
}
const report={passed:true,originalGLBsUnchanged:Object.keys(hashes).length,comparisonInstances:2,checks:checkedA,secondInstance:checkedB,geometry:geometryA.report,floor:floorA.report,sourcePrototypeUntouched:true,disposeRestoresOriginals:true};
const output=new URL('artifacts/player-check/map-fixes-report.json',ROOT);await fs.mkdir(new URL('./',output),{recursive:true});await fs.writeFile(output,JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify({passed:true,originalGLBsUnchanged:report.originalGLBsUnchanged,anchors:checkedA.anchors,mainRollers:checkedA.mainRollers,arrows:checkedA.arrows,holdGap:checkedA.holdGap,report:'artifacts/player-check/map-fixes-report.json'},null,2));
