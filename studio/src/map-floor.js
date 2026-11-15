// Runtime corrections for the authored v02 map. The GLBs remain immutable.
import * as THREE from 'three';
import {MAP_LAYOUT} from './map-layout.js';

const applied=new WeakMap();
const REVISION='map-expanded-floor-2026-11-14';
const HEIGHT={lane:.006,white:.008,label:.008};
export const WALKWAY_ARROW_CENTERS=MAP_LAYOUT.arrowCenters;

function oneMaterial(mesh){return Array.isArray(mesh.material)?mesh.material[0]:mesh.material;}
function positionBounds(mesh){
  mesh.updateWorldMatrix(true,false);
  return new THREE.Box3().setFromObject(mesh);
}

function topCaptionGeometry(source,parent){
  // The exporter batched the label and its outline by amber material. The
  // outline is below .0022 m; the text's upward cap is at .00255 m. Extract
  // only that cap, not coincident front/back lettering or the old outline.
  const geometry=source.geometry,positions=geometry.getAttribute('position');
  const normals=geometry.getAttribute('normal'),index=geometry.index;
  const points=[],normalValues=[],vertex=new THREE.Vector3();
  const normal=new THREE.Vector3(),normalMatrix=new THREE.Matrix3().getNormalMatrix(source.matrixWorld);
  const inverseParent=parent.matrixWorld.clone().invert();
  const count=index?index.count:positions.count;
  for(let i=0;i<count;i+=3){
    const ids=[0,1,2].map(k=>index?index.getX(i+k):i+k);
    const world=ids.map(id=>vertex.fromBufferAttribute(positions,id).applyMatrix4(source.matrixWorld).clone());
    const upward=ids.every(id=>normals&&normal.fromBufferAttribute(normals,id).applyMatrix3(normalMatrix).normalize().y>.98);
    if(!upward||!world.every(p=>p.y>.0025&&p.y<.003))continue;
    for(const point of world){point.applyMatrix4(inverseParent);points.push(point.x,point.y,point.z);normalValues.push(0,1,0);}
  }
  if(!points.length)throw new Error('Не удалось выделить надпись ESCAPED / HOLD из пола v02');
  const result=new THREE.BufferGeometry();
  result.setAttribute('position',new THREE.Float32BufferAttribute(points,3));
  result.setAttribute('normal',new THREE.Float32BufferAttribute(normalValues,3));
  result.computeBoundingBox();
  const bounds=result.boundingBox,size=new THREE.Vector3();bounds.getSize(size);
  const center=new THREE.Vector3();bounds.getCenter(center);
  const scaleX=Math.min(1,1.70/size.x),attribute=result.getAttribute('position');
  for(let i=0;i<attribute.count;i++){
    attribute.setXYZ(i,10+(attribute.getX(i)-center.x)*scaleX,HEIGHT.label,-3.86+(attribute.getZ(i)-center.z));
  }
  attribute.needsUpdate=true;result.computeBoundingBox();result.computeBoundingSphere();
  return result;
}

function zoneCaptionGeometry(source,parent,zone){
  const geometry=source.geometry,p=geometry.getAttribute('position'),n=geometry.getAttribute('normal'),idx=geometry.index;
  const values=[],normals=[],inverse=parent.matrixWorld.clone().invert(),normalMatrix=new THREE.Matrix3().getNormalMatrix(source.matrixWorld);
  const [x0,x1,z0,z1]=zone.source;
  for(let i=0;i<(idx?idx.count:p.count);i+=3){
    const ids=[0,1,2].map(k=>idx?idx.getX(i+k):i+k);
    const points=ids.map(id=>new THREE.Vector3().fromBufferAttribute(p,id).applyMatrix4(source.matrixWorld));
    if(!points.every(v=>v.y>.0025&&v.y<.003&&v.x>x0&&v.x<x1&&v.z>z0&&v.z<z1))continue;
    if(!ids.every(id=>new THREE.Vector3().fromBufferAttribute(n,id).applyMatrix3(normalMatrix).normalize().y>.98))continue;
    for(const point of points){point.applyMatrix4(inverse);values.push(point.x,point.y,point.z);normals.push(0,1,0);}
  }
  if(!values.length)throw new Error('Не найдена подпись зоны '+zone.id);
  const result=new THREE.BufferGeometry();result.setAttribute('position',new THREE.Float32BufferAttribute(values,3));
  result.setAttribute('normal',new THREE.Float32BufferAttribute(normals,3));result.computeBoundingBox();
  const bounds=result.boundingBox,pos=result.getAttribute('position');
  for(let i=0;i<pos.count;i++)pos.setXYZ(i,pos.getX(i)-bounds.min.x+zone.minX+.15,HEIGHT.label,pos.getZ(i)-bounds.max.z-MAP_LAYOUT.zoneFront-.15);
  result.computeBoundingBox();result.computeBoundingSphere();return result;
}

function reworkPaintGeometry(source){
  // Keep the separate R outline/caption from the shared blue export batch.
  const original=source.geometry,g=original.index?original.toNonIndexed():original,position=g.getAttribute('position'),keep=[];
  const normals=g.getAttribute('normal');
  for(let i=0;i<position.count;i+=3)if([0,1,2].every(k=>new THREE.Vector3().fromBufferAttribute(position,i+k).applyMatrix4(source.matrixWorld).z>6.3&&normals.getY(i+k)>.98))keep.push(i,i+1,i+2);
  const result=new THREE.BufferGeometry();
  for(const [name,a] of Object.entries(g.attributes)){
    const values=new Float32Array(keep.length*a.itemSize);
    keep.forEach((old,i)=>{for(let k=0;k<a.itemSize;k++)values[i*a.itemSize+k]=a.getComponent(old,k);});
    result.setAttribute(name,new THREE.BufferAttribute(values,a.itemSize,a.normalized));
  }
  result.computeBoundingBox();result.computeBoundingSphere();if(g!==original)g.dispose();return result;
}

export function applyMapFloorFixes(environment,layout){
  if(applied.has(environment))return applied.get(environment);
  environment.updateMatrixWorld(true);
  const floor=environment.getObjectByName('ENV_FLOOR_AND_GRID');
  if(!floor)throw new Error('Отсутствует слой ENV_FLOOR_AND_GRID');
  const original=[];floor.traverse(o=>{if(o.isMesh)original.push(o);});
  const byMaterial=name=>original.find(o=>oneMaterial(o)?.name===name);
  const lane=original.find(o=>o.name==='WALKWAY_GREEN_5S');
  const oldWhite=byMaterial('Paper labels'),oldArrows=byMaterial('Warm white laminate'),oldAmber=byMaterial('Status amber'),oldBlue=byMaterial('Petrol powder coat');
  if(!lane||!oldWhite||!oldArrows||!oldAmber||!oldBlue)throw new Error('В исходной карте v02 не найдены дорожка или её разметка');

  const changed=[],ownedMaterials=new Set(),ownedGeometry=new Set();
  const patch=new THREE.Group();patch.name='MAP_FLOOR_FIXES';patch.userData.map_revision=REVISION;
  const reports={revision:REVISION,removedLaneBuckets:[lane.name,oldWhite.name,oldArrows.name],floorDecalsStabilized:0};
  function cloneDecalMaterial(source,name,level=2){
    const material=source.clone();material.name=name;
    material.polygonOffset=true;material.polygonOffsetFactor=-1;material.polygonOffsetUnits=-level;
    material.depthTest=true;material.depthWrite=true;
    ownedMaterials.add(material);return material;
  }

  // Stabilize every floor decal, not the floor slab or the rest of the factory.
  // Shadow-map precision cannot resolve the original sub-millimetre paint
  // films, so paint/grid must neither cast nor receive shadow maps.
  for(const mesh of original){
    changed.push({mesh,visible:mesh.visible,castShadow:mesh.castShadow,receiveShadow:mesh.receiveShadow,renderOrder:mesh.renderOrder,material:mesh.material});
    mesh.castShadow=false;
    if(mesh===lane||mesh===oldWhite||mesh===oldArrows||mesh===oldAmber||mesh===oldBlue){mesh.visible=false;continue;}
    const bounds=positionBounds(mesh);
    if(bounds.max.y<.04&&bounds.min.y>-.04){
      const grid=/CAD_grid/.test(mesh.name),level=grid?1:2;
      mesh.material=Array.isArray(mesh.material)?mesh.material.map((m,i)=>cloneDecalMaterial(m,`${m.name} / map decal ${i}`,level)):cloneDecalMaterial(mesh.material,`${mesh.material.name} / map decal`,level);
      mesh.receiveShadow=false;mesh.renderOrder=grid?1:2;mesh.userData.map_floor_decal=true;reports.floorDecalsStabilized++;
    }
  }

  const green=cloneDecalMaterial(oneMaterial(lane),'Map / Pedestrian lane',3);
  const white=cloneDecalMaterial(oneMaterial(oldWhite),'Map / Lane white',4);
  const arrowWhite=cloneDecalMaterial(oneMaterial(oldArrows),'Map / Three lane arrows',4);
  const amber=cloneDecalMaterial(oneMaterial(oldAmber),'Map / Hold zone',3);
  const amberText=cloneDecalMaterial(oneMaterial(oldAmber),'Map / Hold caption',4);
  const blue=cloneDecalMaterial(oneMaterial(oldBlue),'Map / Aligned workstation zones',3);
  function mesh(name,geometry,material,order=3){
    const object=new THREE.Mesh(geometry,material);object.name=name;
    object.castShadow=false;object.receiveShadow=false;object.renderOrder=order;
    object.userData.map_floor_decal=true;patch.add(object);ownedGeometry.add(geometry);return object;
  }
  function plane(name,width,depth,x,z,y,material,order=3){
    const geometry=new THREE.PlaneGeometry(width,depth);geometry.rotateX(-Math.PI/2);
    geometry.translate(x,y,z);return mesh(name,geometry,material,order);
  }

  const laneLength=MAP_LAYOUT.laneHalfLength*2;
  plane('MAP_WALKWAY_GREEN',laneLength,1.5,0,5.15,HEIGHT.lane,green);
  for(const z of [4.42,5.88])plane('MAP_WALKWAY_BORDER',laneLength,.045,0,z,HEIGHT.white,white,4);
  for(const x of [-MAP_LAYOUT.laneHalfLength,MAP_LAYOUT.laneHalfLength])plane('MAP_WALKWAY_END',.045,1.5,x,5.15,HEIGHT.white,white,4);
  for(const x of WALKWAY_ARROW_CENTERS){
    const shape=new THREE.Shape();
    const outline=[[-.48,-.06],[.08,-.06],[.08,-.24],[.48,0],[.08,.24],[.08,.06],[-.48,.06]];
    outline.forEach(([px,py],i)=>i?shape.lineTo(px,py):shape.moveTo(px,py));shape.closePath();
    const geometry=new THREE.ShapeGeometry(shape);geometry.rotateX(-Math.PI/2);geometry.translate(x,HEIGHT.white,5.15);
    const arrow=mesh(`MAP_WALKWAY_ARROW_${x===0?'CENTER':x<0?'START':'END'}`,geometry,arrowWhite,4);
    arrow.userData.center_x=x;arrow.userData.direction='+X';
  }

  for(const zone of MAP_LAYOUT.zones){
    const width=zone.maxX-zone.minX,cx=(zone.minX+zone.maxX)/2,front=-MAP_LAYOUT.zoneFront,back=-MAP_LAYOUT.zoneBack;
    for(const z of [front,back])plane('MAP_ZONE_'+zone.id+'_BORDER',width,.036,cx,z,HEIGHT.lane,blue);
    for(const x of [zone.minX,zone.maxX])plane('MAP_ZONE_'+zone.id+'_BORDER',.036,front-back,x,(front+back)/2,HEIGHT.lane,blue);
    for(const x of [zone.minX,zone.maxX])for(const z of [front,back]){
      plane('MAP_ZONE_'+zone.id+'_CORNER',.25,.065,x+(x===zone.minX?.125:-.125),z,HEIGHT.white,blue,4);
      plane('MAP_ZONE_'+zone.id+'_CORNER',.065,.25,x,z+(z===back?.125:-.125),HEIGHT.white,blue,4);
    }
    mesh('MAP_ZONE_'+zone.id+'_LABEL',zoneCaptionGeometry(oldBlue,floor,zone),blue,4);
  }
  const r=mesh('MAP_REWORK_ZONE_PAINT',reworkPaintGeometry(oldBlue),blue,3);
  r.position.copy(oldBlue.position);r.quaternion.copy(oldBlue.quaternion);r.scale.copy(oldBlue.scale);
  // Match the stable paint level used by the new zones.
  const rp=r.geometry.getAttribute('position');for(let i=0;i<rp.count;i++)rp.setY(i,rp.getY(i)>.0025?HEIGHT.label:HEIGHT.lane);
  const rn=r.geometry.getAttribute('normal');for(let i=0;i<rn.count;i++)rn.setXYZ(i,0,1,0);
  r.geometry.computeBoundingBox();r.geometry.computeBoundingSphere();

  // HOLD is a distinct floor zone, with a real gap to QC. The pallet/outcome
  // anchor stays at x=10, z=-4.4; only its painted frame and caption change.
  const hold={cx:10,cz:-4.4,width:2,depth:1.35,line:.036};
  for(const z of [hold.cz-hold.depth/2,hold.cz+hold.depth/2])plane('MAP_HOLD_ZONE_BORDER',hold.width,hold.line,hold.cx,z,HEIGHT.lane,amber);
  for(const x of [hold.cx-hold.width/2,hold.cx+hold.width/2])plane('MAP_HOLD_ZONE_BORDER',hold.line,hold.depth,x,hold.cz,HEIGHT.lane,amber);
  for(const sx of [-1,1])for(const sz of [-1,1]){
    plane('MAP_HOLD_ZONE_CORNER',.25,.065,hold.cx+sx*(hold.width/2-.125),hold.cz+sz*hold.depth/2,HEIGHT.white,amber,4);
    plane('MAP_HOLD_ZONE_CORNER',.065,.25,hold.cx+sx*hold.width/2,hold.cz+sz*(hold.depth/2-.125),HEIGHT.white,amber,4);
  }
  const label=mesh('MAP_ESCAPED_HOLD_LABEL',topCaptionGeometry(oldAmber,floor),amberText,4);
  floor.add(patch);environment.updateMatrixWorld(true);
  const labelBounds=positionBounds(label);
  const qcRight=MAP_LAYOUT.zones.at(-1).maxX+.0325;
  Object.assign(reports,{
    laneBounds:{min:[-MAP_LAYOUT.laneHalfLength,HEIGHT.lane,4.4],max:[MAP_LAYOUT.laneHalfLength,HEIGHT.lane,5.9]},
    arrows:WALKWAY_ARROW_CENTERS.map(x=>({center:[x,HEIGHT.white,5.15],direction:'+X'})),
    arrowSpacing:11.8,endMargins:[5.9,5.9],zebras:0,wayfindingLabels:0,
    zones:MAP_LAYOUT.zones.map(({id,label,minX,maxX})=>({id,label,minX,maxX,minZ:-MAP_LAYOUT.zoneBack,maxZ:-MAP_LAYOUT.zoneFront})),
    holdZone:{minX:9,maxX:11,minZ:-5.075,maxZ:-3.725,outerMinX:8.9675,qcRightEdge:qcRight,gapToQc:8.9675-qcRight},
    holdCaptionBounds:{min:labelBounds.min.toArray(),max:labelBounds.max.toArray()},
    paintDepthTest:true,paintDepthWrite:true,paintShadows:false,
  });
  let disposed=false;
  const result={report:reports,dispose(){
    if(disposed)return;disposed=true;patch.removeFromParent();
    for(const state of changed){
      Object.assign(state.mesh,{visible:state.visible,castShadow:state.castShadow,receiveShadow:state.receiveShadow,renderOrder:state.renderOrder,material:state.material});
      delete state.mesh.userData.map_floor_decal;
    }
    for(const geometry of ownedGeometry)geometry.dispose();
    for(const material of ownedMaterials)material.dispose();
    applied.delete(environment);
  }};
  applied.set(environment,result);return result;
}
