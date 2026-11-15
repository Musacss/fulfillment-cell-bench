#!/usr/bin/env node
// Acceptance checks against the frozen source GLBs, with both comparison instances.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {createHash} from 'node:crypto';
import * as THREE from '../studio/node_modules/three/build/three.module.js';
import {GLTFLoader} from '../studio/node_modules/three/examples/jsm/loaders/GLTFLoader.js';
import {applyMapGeometryFixes} from '../studio/src/map-geometry.js';
import {applyMapLayoutExpansion,MAP_LAYOUT,isNativeExpandedMap} from '../studio/src/map-layout.js';
import {applyMapFloorFixes} from '../studio/src/map-floor.js';

const ROOT=new URL('../',import.meta.url);
const near=(actual,expected,label,tolerance=3e-5)=>assert.ok(Math.abs(actual-expected)<=tolerance,`${label}: ${actual} vs ${expected}`);
const isVisible=o=>{for(let p=o;p;p=p.parent)if(!p.visible)return false;return true;};
const box=o=>new THREE.Box3().setFromObject(o);
const digest=array=>createHash('sha256').update(Buffer.from(array.buffer,array.byteOffset,array.byteLength)).digest('hex');
const geometryDigest=g=>JSON.stringify({index:g.index?digest(g.index.array):null,attributes:Object.fromEntries(Object.entries(g.attributes).map(([n,a])=>[n,digest(a.isInterleavedBufferAttribute?a.data.array:a.array)])),groups:g.groups,drawRange:g.drawRange});
const materialDigest=m=>m?JSON.stringify({name:m.name,color:m.color?.toArray(),roughness:m.roughness,metalness:m.metalness,opacity:m.opacity,transparent:m.transparent,depthTest:m.depthTest,depthWrite:m.depthWrite,polygonOffset:m.polygonOffset,polygonOffsetFactor:m.polygonOffsetFactor,polygonOffsetUnits:m.polygonOffsetUnits}):null;

function graph(root){
  root.updateMatrixWorld(true);const out=[];
  root.traverse(o=>out.push({object:o,parent:o.parent,children:[...o.children],position:o.position.toArray(),quaternion:o.quaternion.toArray(),scale:o.scale.toArray(),world:[...o.matrixWorld.elements],visible:o.visible,castShadow:o.castShadow,receiveShadow:o.receiveShadow,renderOrder:o.renderOrder,geometry:o.geometry,geometryDigest:o.geometry?geometryDigest(o.geometry):null,material:o.material,materialDigest:(Array.isArray(o.material)?o.material:[o.material]).map(materialDigest)}));
  return out;
}
function graphUnchanged(root,states,label){
  root.updateMatrixWorld(true);const nodes=[];root.traverse(o=>nodes.push(o));
  assert.deepEqual(nodes,states.map(s=>s.object),label+' node order');
  for(const s of states){
    const o=s.object;assert.equal(o.parent,s.parent,label+' parent '+o.name);assert.deepEqual(o.children,s.children,label+' children '+o.name);
    assert.deepEqual(o.position.toArray(),s.position,label+' position '+o.name);assert.deepEqual(o.quaternion.toArray(),s.quaternion,label+' rotation '+o.name);assert.deepEqual(o.scale.toArray(),s.scale,label+' scale '+o.name);assert.deepEqual(o.matrixWorld.elements,s.world,label+' world transform '+o.name);
    assert.equal(o.visible,s.visible,label+' visibility '+o.name);assert.equal(o.geometry,s.geometry,label+' geometry identity '+o.name);assert.equal(o.material,s.material,label+' material identity '+o.name);
    assert.equal(o.castShadow,s.castShadow,label+' cast '+o.name);assert.equal(o.receiveShadow,s.receiveShadow,label+' receive '+o.name);assert.equal(o.renderOrder,s.renderOrder,label+' renderOrder '+o.name);
    if(o.geometry)assert.equal(geometryDigest(o.geometry),s.geometryDigest,label+' geometry buffers '+o.name);
    assert.deepEqual((Array.isArray(o.material)?o.material:[o.material]).map(materialDigest),s.materialDigest,label+' material properties '+o.name);
  }
}
const hashes=JSON.parse(await fs.readFile(new URL('studio/asset-hashes.json',ROOT)));
for(const [file,expected] of Object.entries(hashes))assert.equal(digest(await fs.readFile(new URL(file,ROOT))),expected.sha256,'Frozen asset changed: '+file);
async function load(file){const b=await fs.readFile(new URL('4_Horses_Environment_v02/'+file,ROOT));return new GLTFLoader().parseAsync(b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength),'');}
const [sourceEnvironment,sourceLayout]=await Promise.all([load('warehouse_environment.glb'),load('modules/visual_layout.glb')]);
const sourceGraphs=[graph(sourceEnvironment.scene),graph(sourceLayout.scene)];
const binding=JSON.parse(await fs.readFile(new URL('4_Horses_Environment_v02/visual_bindings.json',ROOT)));

function instance(){
  const environment=sourceEnvironment.scene.clone(true),layout=sourceLayout.scene.clone(true);
  for(const root of [environment,layout])root.traverse(o=>{if(o.isMesh){o.castShadow=true;o.receiveShadow=true;}});
  const graphs=[graph(environment),graph(layout)],anchors=[],conveyors=[];
  for(const root of [environment,layout])root.traverse(o=>{
    if(o.userData.kind==='anchor'||/^VIS_(STAGE_[1-4]_(WORK|ORDER)|ROBOT_(WORK|ORDER|ASSIST)|QUEUE_(Q[1-4]|R)(_SLOT_\d+)?|OUTCOME_(GOOD|ESCAPED|SCRAP))$/.test(o.name))anchors.push({object:o,world:[...o.matrixWorld.elements]});
    let conveyor=false;
    for(let p=o;p;p=p.parent)if(/^(CONVEYOR_\d\d|QUEUE_R_ROLLER_SECTION|QC_PORTAL|STOPPER_GATE|INLET_HOOD|OUTLET_HOOD|VIS_QUEUE_Q[234]_(FRAME|INFEED|TRANSFER_TONGUE|LABEL|LABEL_PLATE))$/.test(p.name))conveyor=true;
    if(conveyor)conveyors.push({object:o,parent:o.parent,world:[...o.matrixWorld.elements],geometry:o.geometry,geometryDigest:o.geometry?geometryDigest(o.geometry):null});
  });
  assert.ok(anchors.length>=61,'All operational anchors must be included');
  assert.ok(conveyors.filter(c=>/^ROLLER_\d\d_\d\d$/.test(c.object.name)).length===200);
  return {environment,layout,graphs,anchors,conveyors};
}

// Exact triangle-vs-prism intersections, following a bounding-box broad phase.
// This catches narrow legs/diagonals; object centres alone cannot prove a clear aisle.
function corridorObstacles(environment,layout){
  const region=new THREE.Box3(new THREE.Vector3(-17.7,.025,4.4),new THREE.Vector3(17.7,2.2,5.9));
  const hits=[],triangle=new THREE.Triangle(),points=[triangle.a,triangle.b,triangle.c];let candidateMeshes=0,testedTriangles=0;
  for(const root of [environment,layout])root.traverse(o=>{
    if(!o.isMesh||!isVisible(o))return;
    for(let p=o;p;p=p.parent)if(/^DOCK_\d\d_SECTIONAL_LEAF$/.test(p.name))return;
    if(!box(o).intersectsBox(region))return;
    candidateMeshes++;
    const position=o.geometry.getAttribute('position'),index=o.geometry.index,count=index?index.count:position.count;
    for(let i=0;i<count;i+=3){
      for(let k=0;k<3;k++)points[k].fromBufferAttribute(position,index?index.getX(i+k):i+k).applyMatrix4(o.matrixWorld);
      testedTriangles++;
      if(region.intersectsTriangle(triangle)){hits.push({name:o.name,triangle:i/3,vertices:points.map(p=>p.toArray())});break;}
    }
  });
  return {bounds:{min:region.min.toArray(),max:region.max.toArray()},candidateMeshes,testedTriangles,hits};
}

function checkAnchorsAndConveyors(view){
  for(const root of [view.environment,view.layout])root.updateMatrixWorld(true);
  for(const s of view.anchors)assert.deepEqual(s.object.matrixWorld.elements,s.world,'Operational anchor moved: '+s.object.name);
  for(const s of view.conveyors){
    assert.equal(s.object.parent,s.parent,'Conveyor parent changed: '+s.object.name);
    assert.deepEqual(s.object.matrixWorld.elements,s.world,'Conveyor transform changed: '+s.object.name);
    assert.equal(s.object.geometry,s.geometry,'Conveyor geometry object changed: '+s.object.name);
    if(s.geometry)assert.equal(geometryDigest(s.object.geometry),s.geometryDigest,'Conveyor vertex/index buffer changed: '+s.object.name);
    assert.ok(isVisible(s.object),'Conveyor hidden: '+s.object.name);
  }
}

const a=instance(),b=instance();
const geometryA=applyMapGeometryFixes(a.environment,a.layout),layoutA=applyMapLayoutExpansion(a.environment),floorA=applyMapFloorFixes(a.environment,a.layout);
assert.equal(applyMapLayoutExpansion(a.environment),layoutA,'Expansion must be idempotent');
graphUnchanged(b.environment,b.graphs[0],'Untouched comparison B environment');graphUnchanged(b.layout,b.graphs[1],'Untouched comparison B layout');
const geometryB=applyMapGeometryFixes(b.environment,b.layout),layoutB=applyMapLayoutExpansion(b.environment),floorB=applyMapFloorFixes(b.environment,b.layout);

function check(view,expansion,floorFix){
  checkAnchorsAndConveyors(view);
  const corridor=corridorObstacles(view.environment,view.layout);
  assert.deepEqual(corridor.hits,[],'Direct 1.5m dock-to-dock aisle must be clear of equipment/walls');
  const slab=view.environment.getObjectByName('Raised_concrete_slab');assert.ok(slab&&isVisible(slab));
  const slabBox=box(slab);near(slabBox.min.x,-18,'Expanded floor left');near(slabBox.max.x,18,'Expanded floor right');near(slabBox.min.z,-9,'Floor front');near(slabBox.max.z,9,'Floor rear');
  const docks=[];
  for(const [name,x] of [['DOCK_01',-17.85],['DOCK_02',17.85]]){
    const o=view.environment.getObjectByName(name);assert.ok(o&&isVisible(o),name+' visible');
    const p=o.getWorldPosition(new THREE.Vector3());near(p.x,x,name+' horizontal position');near(p.z,5.15,name+' alignment with opposite gate');
    const leaf=box(view.environment.getObjectByName(name+'_SECTIONAL_LEAF'));near((leaf.min.z+leaf.max.z)/2,5.15,name+' leaf centre');
    assert.ok(leaf.min.z<4.4&&leaf.max.z>5.9,'Full lane width must lead into dock opening');docks.push({name,position:p.toArray(),leaf:{min:leaf.min.toArray(),max:leaf.max.toArray()}});
  }
  const nativeExpanded=isNativeExpandedMap(view.environment);
  const halfStroke=nativeExpanded?.0725:.0325;
  const expectedZones=[[ '01',nativeExpanded?-13.35:-12.4,-8.55],['02',-8.15,-3.95],['03',-3.55,5.10],['04',5.40,8.775]],zones=[];
  for(const [id,minX,maxX] of expectedZones){
    const mapLabel=view.environment.getObjectByName('MAP_ZONE_'+id+'_LABEL');
    const floorLabel=view.environment.getObjectByName('FLOOR_ZONE_'+id+'_LABEL');
    const label=(mapLabel&&isVisible(mapLabel))?mapLabel:floorLabel;
    const border=new THREE.Box3();let parts=0;
    const partRe=nativeExpanded?new RegExp('^FLOOR_ZONE_'+id+'_(BORDER|CORNER)(?:\\d+)?$'):new RegExp('^MAP_ZONE_'+id+'_(BORDER|CORNER)$');
    view.environment.traverse(o=>{if(o.isMesh&&isVisible(o)&&partRe.test(o.name)){border.union(box(o));parts++;}});
    assert.equal(parts,12,'Four borders and eight corner strokes per zone '+id);
    near(border.min.x,minX-halfStroke,'Zone '+id+' left',1e-3);near(border.max.x,maxX+halfStroke,'Zone '+id+' right',1e-3);
    near(border.min.z,-4.9-halfStroke,'Zone '+id+' shared back baseline',1e-3);near(border.max.z,-.65+halfStroke,'Zone '+id+' shared front baseline',1e-3);
    assert.ok(label&&isVisible(label),'Zone caption '+id);const caption=box(label);
    assert.ok(caption.min.x>minX&&caption.max.x<maxX&&caption.min.z>-4.9&&caption.max.z<-.65,'Zone '+id+' caption stays within own frame');
    const interior=new THREE.Box3(new THREE.Vector3(minX,-1,-4.9),new THREE.Vector3(maxX,3,-.65));
    zones.push({id,interior,border,caption});
  }
  for(let i=1;i<zones.length;i++)assert.ok(zones[i].border.min.x-zones[i-1].border.max.x>(nativeExpanded?.14:.23),'Neighbouring zone outlines must have clear gaps');
  const deck=box(view.environment.getObjectByName('Q1_PAIRED_PALLET_DECK'));
  assert.ok(zones[0].interior.containsBox(deck),'PREP zone must include the complete inbound paired pallet deck');
  for(let i=0;i<binding.queues.Q1.preview_count;i++){
    const anchor=view.layout.getObjectByName('VIS_QUEUE_Q1_SLOT_'+String(i).padStart(2,'0'));
    const p=anchor.getWorldPosition(new THREE.Vector3());
    const footprint=new THREE.Box3(new THREE.Vector3(p.x-.27,p.y,p.z-.20),new THREE.Vector3(p.x+.27,p.y+.32,p.z+.20));
    assert.ok(zones[0].interior.containsBox(footprint),'Full Q1 tray footprint must fit in PREP: '+i);
  }
  assert.ok(Math.abs(docks[0].position[0])-Math.abs(zones[0].border.min.x)>(nativeExpanded?4.3:5),'Inbound gate must have open apron before PREP');
  const arrows=[];view.environment.traverse(o=>{if(/^MAP_WALKWAY_ARROW_/.test(o.name)&&isVisible(o))arrows.push(o);});
  assert.equal(arrows.length,3);assert.deepEqual(arrows.map(o=>o.userData.center_x),[-11.8,0,11.8]);
  assert.equal(floorFix.report.zebras,0);
  const lane=box(view.environment.getObjectByName('MAP_WALKWAY_GREEN'));near(lane.min.x,-17.7,'Lane left');near(lane.max.x,17.7,'Lane right');near(lane.max.z-lane.min.z,1.5,'Lane width');
  let visibleAxisMeshes=0;
  view.environment.traverse(o=>{if(o.isMesh&&isVisible(o)&&/Axis_[XY]/.test(o.name))visibleAxisMeshes++;});
  assert.equal(visibleAxisMeshes,0,'Axis X/Y must be removed');
  assert.equal(isVisible(view.environment.getObjectByName('ENV_FLOOR_AND_GRID__Paper_labels')),false,'Old scale legend and wayfinding batch must be hidden');
  return {operationalAnchors:view.anchors.length,conveyorNodes:view.conveyors.length,conveyorMeshes:view.conveyors.filter(c=>c.geometry).length,unchangedMainRollers:200,corridor,slab:{min:slabBox.min.toArray(),max:slabBox.max.toArray()},docks,zones:zones.map(z=>({id:z.id,interior:{min:z.interior.min.toArray(),max:z.interior.max.toArray()},border:{min:z.border.min.toArray(),max:z.border.max.toArray()},caption:{min:z.caption.min.toArray(),max:z.caption.max.toArray()}})),q1DeckInsidePrep:true,q1TrayFootprintsInsidePrep:binding.queues.Q1.preview_count,arrows:arrows.map(o=>o.userData.center_x),visibleAxisMeshes,expansion:expansion.report};
}
const checkedA=check(a,layoutA,floorA),checkedB=check(b,layoutB,floorB);
const ownedGeoNames=isNativeExpandedMap(a.environment)?['MAP_WALKWAY_GREEN','MAP_SIDE_WALL']:['MAP_ZONE_01_LABEL','MAP_WALKWAY_GREEN','MAP_CAD_GRID_X','MAP_SIDE_WALL'];
for(const name of ownedGeoNames){
  const aa=a.environment.getObjectByName(name),bb=b.environment.getObjectByName(name);assert.ok(aa&&bb,name);
  assert.notEqual(aa.geometry,bb.geometry,'Comparison instances must own new geometry: '+name);
}
assert.notEqual(a.environment.getObjectByName('MAP_WALKWAY_GREEN').material,b.environment.getObjectByName('MAP_WALKWAY_GREEN').material,'Comparison instances must own decal materials');
for(const root of [sourceEnvironment.scene,sourceLayout.scene])root.updateMatrixWorld(true);
graphUnchanged(sourceEnvironment.scene,sourceGraphs[0],'Cached source environment');graphUnchanged(sourceLayout.scene,sourceGraphs[1],'Cached source layout');

const patchedB=[graph(b.environment),graph(b.layout)];
for(const [view,g,l,f] of [[a,geometryA,layoutA,floorA],[b,geometryB,layoutB,floorB]]){
  f.dispose();l.dispose();g.dispose();f.dispose();l.dispose();g.dispose();
  graphUnchanged(view.environment,view.graphs[0],'Disposed environment');graphUnchanged(view.layout,view.graphs[1],'Disposed layout');
  if(view===a){graphUnchanged(b.environment,patchedB[0],'B survives A disposal');graphUnchanged(b.layout,patchedB[1],'B layout survives A disposal');}
}
const report={passed:true,originalGLBsUnchanged:Object.keys(hashes).length,comparisonInstances:2,mapLayout:MAP_LAYOUT,checks:checkedA,secondInstance:checkedB,sourcePrototypeUntouched:true,disposeRestoresOriginals:true};
await fs.writeFile(new URL('artifacts/player-check/map-expansion-report.json',ROOT),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify({passed:true,originalGLBsUnchanged:report.originalGLBsUnchanged,anchors:checkedA.operationalAnchors,conveyorNodesUnchanged:checkedA.conveyorNodes,corridorObstacles:checkedA.corridor.hits.length,report:'artifacts/player-check/map-expansion-report.json'},null,2));
