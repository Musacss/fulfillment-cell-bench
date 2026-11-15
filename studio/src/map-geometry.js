import * as THREE from 'three';

// Corrections to the authored v02 map, applied to scene instances only. The
// original GLB buffers, logical anchors and animation assets stay unchanged.
export const MAP_GEOMETRY_FIXES = Object.freeze({
  cabinetBounds: Object.freeze({min:[-12.10,-.02,-6.76],max:[-11.30,1.30,-5.99]}),
  orphanRobotTop: 'VIS_Bench_top_robot_chamfer',
  oldReworkBench: 'BENCH_REWORK',
  reworkRollers: 'QUEUE_R_ROLLER_SECTION',
});
const applied = new WeakMap();

function hasAncestor(object,name){
  for(let node=object;node;node=node.parent)if(node.name===name)return true;
  return false;
}
function vertexValue(attribute,index,component){
  return attribute.isInterleavedBufferAttribute
    ? attribute.data.array[index*attribute.data.stride+attribute.offset+component]
    : attribute.array[index*attribute.itemSize+component];
}

/** Remove complete, localized triangles from a static material batch.
 * A compact geometry is required: changing only its index would leave removed
 * vertices in bounding boxes, raycasts and later map diagnostics.
 */
function withoutRegion(mesh,region){
  const original=mesh.geometry;
  const source=original.index?original.toNonIndexed():original;
  const position=source.getAttribute('position'),point=new THREE.Vector3();
  const kept=[],materialIndices=[];let removed=0;
  const materialAt=vertex=>source.groups.find(g=>vertex>=g.start&&vertex<g.start+g.count)?.materialIndex??0;
  for(let first=0;first<position.count;first+=3){
    let contained=true;
    for(let i=0;i<3;i++){
      point.fromBufferAttribute(position,first+i).applyMatrix4(mesh.matrixWorld);
      if(!region.containsPoint(point)){contained=false;break;}
    }
    if(contained){removed++;continue;}
    kept.push(first,first+1,first+2);materialIndices.push(materialAt(first));
  }
  if(!removed){if(source!==original)source.dispose();return null;}
  if(!kept.length){if(source!==original)source.dispose();return {removed,geometry:null};}
  const geometry=new THREE.BufferGeometry();
  for(const [name,attribute] of Object.entries(source.attributes)){
    const sourceValues=attribute.isInterleavedBufferAttribute?attribute.data.array:attribute.array;
    const values=new sourceValues.constructor(kept.length*attribute.itemSize);
    kept.forEach((oldIndex,index)=>{
      for(let component=0;component<attribute.itemSize;component++)
        values[index*attribute.itemSize+component]=vertexValue(attribute,oldIndex,component);
    });
    geometry.setAttribute(name,new THREE.BufferAttribute(values,attribute.itemSize,attribute.normalized));
  }
  if(source.groups.length){
    let first=0,material=materialIndices[0];
    for(let i=1;i<=materialIndices.length;i++)if(i===materialIndices.length||materialIndices[i]!==material){
      geometry.addGroup(first*3,(i-first)*3,material);first=i;material=materialIndices[i];
    }
  }
  geometry.name=original.name+' / cabinet removed';
  geometry.userData={...original.userData,mapGeometryCorrection:'utility-cabinet'};
  geometry.computeBoundingBox();geometry.computeBoundingSphere();
  if(source!==original)source.dispose();
  return {removed,geometry};
}

export function applyMapGeometryFixes(environment,layout){
  if(applied.has(environment))return applied.get(environment);
  if(!environment?.isObject3D||!layout?.isObject3D)throw new Error('Map geometry corrections need the environment and layout roots');
  environment.updateMatrixWorld(true);layout.updateMatrixWorld(true);
  const visibility=[],geometries=[],relocations=[];
  const report={cabinet:{hiddenObjects:[],filteredMeshes:[],removedTriangles:0},orphanRobotTop:false,robotWorktop:null,oldReworkBench:false,reworkRollersPreserved:false};
  const hide=object=>{
    if(!object)return;visibility.push([object,object.visible]);object.visible=false;
  };
  const region=new THREE.Box3(new THREE.Vector3(...MAP_GEOMETRY_FIXES.cabinetBounds.min),new THREE.Vector3(...MAP_GEOMETRY_FIXES.cabinetBounds.max));
  const cabinet=environment.getObjectByName('UTILITY_CABINET');
  if(cabinet){hide(cabinet);report.cabinet.hiddenObjects.push(cabinet.name);}
  environment.traverse(mesh=>{
    if(!mesh.isMesh||!hasAncestor(mesh,'PROPS'))return;
    // Native material batching moved the door, handle and feet out of their
    // cabinet hierarchy, so hiding the empty root alone cannot remove them.
    const bounds=new THREE.Box3().setFromObject(mesh);
    if(!bounds.intersectsBox(region))return;
    const result=withoutRegion(mesh,region);if(!result)return;
    report.cabinet.removedTriangles+=result.removed;
    if(result.geometry){
      geometries.push([mesh,mesh.geometry,result.geometry]);mesh.geometry=result.geometry;
      report.cabinet.filteredMeshes.push({name:mesh.name,removedTriangles:result.removed});
    }else{
      hide(mesh);report.cabinet.hiddenObjects.push(mesh.name);
    }
  });

  // The exporter omitted the newly authored top from the layout collection,
  // then left it at local origin when removing its integration parent. Restore
  // that same piece to its real table, without changing its vertex buffers.
  const stray=environment.getObjectByName(MAP_GEOMETRY_FIXES.orphanRobotTop);
  const actual=layout.getObjectByName('VIS_ROBOT_PACK_TABLE');
  if(stray&&actual){
    relocations.push({object:stray,parent:stray.parent,index:stray.parent.children.indexOf(stray),position:stray.position.clone(),quaternion:stray.quaternion.clone(),scale:stray.scale.clone()});
    actual.add(stray);stray.position.set(0,0,0);stray.quaternion.identity();stray.scale.set(1,1,1);
    layout.updateMatrixWorld(true);
    const bounds=new THREE.Box3().setFromObject(stray);
    report.orphanRobotTop=true;
    report.robotWorktop={name:stray.name,parent:actual.name,bounds:{min:bounds.min.toArray(),max:bounds.max.toArray()}};
  }

  // R has a complete, independently supported roller accumulator. Keeping the
  // old desk under it caused double legs, a white shelf and stock to protrude.
  const oldRework=environment.getObjectByName(MAP_GEOMETRY_FIXES.oldReworkBench);
  const rework=environment.getObjectByName(MAP_GEOMETRY_FIXES.reworkRollers);
  if(oldRework&&rework){hide(oldRework);report.oldReworkBench=true;report.reworkRollersPreserved=rework.visible;}

  let disposed=false;
  const correction={report,dispose(){
    if(disposed)return;disposed=true;
    for(const move of relocations){
      move.parent.add(move.object);move.object.position.copy(move.position);move.object.quaternion.copy(move.quaternion);move.object.scale.copy(move.scale);
      const list=move.parent.children;list.splice(list.indexOf(move.object),1);list.splice(move.index,0,move.object);
      move.object.updateMatrixWorld(true);
    }
    for(const [mesh,original,owned] of geometries){mesh.geometry=original;owned.dispose();}
    for(const [object,visible] of visibility)object.visible=visible;
    applied.delete(environment);
  }};
  applied.set(environment,correction);return correction;
}
