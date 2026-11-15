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

export function applyMapGeometryFixes(environment,layout=null){
  if(applied.has(environment))return applied.get(environment);
  if(!environment?.isObject3D||(layout!==null&&layout!==undefined&&!layout?.isObject3D))throw new Error('Map geometry corrections need a valid environment root');
  environment.updateMatrixWorld(true);layout?.updateMatrixWorld?.(true);
  const visibility=[],geometries=[],relocations=[],addedNodes=[],ownedGeometries=[],ownedMaterials=[];
  const report={cabinet:{hiddenObjects:[],filteredMeshes:[],removedTriangles:0},orphanRobotTop:false,robotWorktop:null,oldReworkBench:false,reworkRollersPreserved:false,groundedTables:{qcUnderframeSynthesized:false,robotUnderframeSynthesized:false,stage1StandaloneSynthesized:false,waterCoolerPlinthSynthesized:false,deduplicatedLayoutTables:[]}};
  const hide=object=>{
    if(!object)return;visibility.push([object,object.visible]);object.visible=false;
  };
  const detach=object=>{
    if(!object?.parent)return;
    relocations.push({object,parent:object.parent,index:object.parent.children.indexOf(object),position:object.position.clone(),quaternion:object.quaternion.clone(),scale:object.scale.clone(),detachedOnly:true});
    object.parent.remove(object);
  };
  const addBoxTo=(parent,name,minX,maxX,minY,maxY,minZ,maxZ,mat)=>{
    const g=new THREE.BoxGeometry(maxX-minX,maxY-minY,maxZ-minZ);
    const m=new THREE.Mesh(g,mat);
    m.name=name;m.position.set((minX+maxX)/2,(minY+maxY)/2,(minZ+maxZ)/2);
    m.castShadow=true;m.receiveShadow=true;
    parent.add(m);ownedGeometries.push(g);addedNodes.push(m);
    return m;
  };
  const isNodeVisible=o=>{for(let p=o;p;p=p.parent)if(!p.visible)return false;return true;};
  const findEnvMaterial=(re,fallbackHex,rough=.42,metal=.55)=>{
    let found=null;
    environment.traverse(o=>{
      if(!o.isMesh||found)return;
      for(const m of Array.isArray(o.material)?o.material:[o.material])if(re.test(m?.name||'')){found=m;break;}
    });
    if(found)return found;
    const created=new THREE.MeshStandardMaterial({color:fallbackHex,roughness:rough,metalness:metal});
    ownedMaterials.push(created);return created;
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
  const actual=layout?.getObjectByName?.('VIS_ROBOT_PACK_TABLE')||null;
  const existingTop=actual?.getObjectByName(MAP_GEOMETRY_FIXES.orphanRobotTop)||layout?.getObjectByName?.(MAP_GEOMETRY_FIXES.orphanRobotTop)||null;
  if(stray){
    const strayBox=new THREE.Box3().setFromObject(stray),strayCenter=strayBox.getCenter(new THREE.Vector3());
    const atLegacyOrigin=Math.abs(strayCenter.x)<.8&&Math.abs(strayCenter.z)<.8;
    if(actual&&!existingTop&&atLegacyOrigin){
      relocations.push({object:stray,parent:stray.parent,index:stray.parent.children.indexOf(stray),position:stray.position.clone(),quaternion:stray.quaternion.clone(),scale:stray.scale.clone()});
      actual.add(stray);stray.position.set(0,0,0);stray.quaternion.identity();stray.scale.set(1,1,1);
      layout.updateMatrixWorld(true);
      const bounds=new THREE.Box3().setFromObject(stray);
      report.orphanRobotTop=true;
      report.robotWorktop={name:stray.name,parent:actual.name,bounds:{min:bounds.min.toArray(),max:bounds.max.toArray()}};
    }else if(atLegacyOrigin){
      detach(stray);
      report.orphanRobotTop=true;
    }
  }
  const finalTop=actual?.getObjectByName(MAP_GEOMETRY_FIXES.orphanRobotTop)||layout?.getObjectByName?.(MAP_GEOMETRY_FIXES.orphanRobotTop)||null;
  if(!report.robotWorktop&&finalTop){
    const bounds=new THREE.Box3().setFromObject(finalTop);
    report.robotWorktop={name:finalTop.name,parent:finalTop.parent?.name??null,bounds:{min:bounds.min.toArray(),max:bounds.max.toArray()}};
  }

  // R has a complete, independently supported roller accumulator. Hide legacy
  // misplaced BENCH_REWORK only when at Z < 0 or colliding with QUEUE_R (X > 2.8),
  // preserving M1's grounded BENCH_REWORK at [1.80, 0, +6.35].
  const oldRework=environment.getObjectByName(MAP_GEOMETRY_FIXES.oldReworkBench);
  const rework=environment.getObjectByName(MAP_GEOMETRY_FIXES.reworkRollers);
  if(oldRework){
    const rb=new THREE.Box3().setFromObject(oldRework),rc=rb.getCenter(new THREE.Vector3());
    if(!rb.isEmpty()&&(rc.z<0||rc.x>2.8)){hide(oldRework);report.oldReworkBench=true;}
  }
  if(rework)report.reworkRollersPreserved=Boolean(rework.visible);

  // Ensure every workstation table & cooler in environment has grounded support
  // (min.y <= 0.005 m) even when warehouse_environment.glb is inspected without
  // visual_layout.glb, while avoiding coplanar duplicate Z-fighting with layout.
  const envHasGroundedIn=(minX,maxX,minZ,maxZ)=>{
    const probe=new THREE.Box3(new THREE.Vector3(minX,.05,minZ),new THREE.Vector3(maxX,.90,maxZ));
    let grounded=false;
    environment.traverse(o=>{
      if(grounded||!o.isMesh||!isNodeVisible(o)||hasAncestor(o,'ENV_FLOOR_AND_GRID'))return;
      const b=new THREE.Box3().setFromObject(o);
      if(b.intersectsBox(probe)&&b.min.y<=.005&&b.max.y>=.35)grounded=true;
    });
    return grounded;
  };
  const envHasWorktopIn=(minX,maxX,minZ,maxZ)=>{
    const probe=new THREE.Box3(new THREE.Vector3(minX,.78,minZ),new THREE.Vector3(maxX,.89,maxZ));
    let hasTop=false;
    environment.traverse(o=>{
      if(hasTop||!o.isMesh||!isNodeVisible(o)||hasAncestor(o,'ENV_FLOOR_AND_GRID'))return;
      const b=new THREE.Box3().setFromObject(o);
      if(b.intersectsBox(probe)&&(b.max.x-b.min.x)>=.75&&(b.max.z-b.min.z)>=.65&&b.max.y>=.84&&b.min.y<=.865)hasTop=true;
    });
    return hasTop;
  };

  const wsDetail=environment.getObjectByName('ENV_WORKSTATIONS_DETAIL')||environment;
  const robotCell=environment.getObjectByName('ENV_ROBOT_CELL')||wsDetail;
  const breakArea=environment.getObjectByName('ENV_BREAK_AREA')||environment;
  const frameMat=findEnvMaterial(/Graphite|Petrol powder coat|Satin zinc/i,'#2f3942',.42,.52);
  const topMat=findEnvMaterial(/Warm white laminate|Porcelain/i,'#eaeeef',.55,.05);

  // 1) Stage 4 QC table: QC_TABLE_TOOLING sits in ENV_WORKSTATIONS_DETAIL at minY=0.782m
  // when legs were exported only to visual_layout.glb. Ground it in environment and
  // deduplicate VIS_STAGE_4_TABLE in layout so ENV_WORKSTATIONS_DETAIL toggles cleanly.
  const nativeQcGrounded=envHasGroundedIn(5.45,6.55,-3.15,-2.25);
  if(!nativeQcGrounded){
    const g=new THREE.Group();g.name='MAP_QC_TABLE_UNDERFRAME';
    wsDetail.add(g);addedNodes.push(g);
    for(const [lx0,lx1] of [[5.5175,5.5625],[6.4375,6.4825]]){
      for(const [lz0,lz1] of [[-3.0825,-3.0375],[-2.3625,-2.3175]])addBoxTo(g,'MAP_QC_TABLE_LEG',lx0,lx1,0,.825,lz0,lz1,frameMat);
    }
    addBoxTo(g,'MAP_QC_TABLE_RAIL',5.52,6.48,.3325,.3675,-3.0375,-3.0025,frameMat);
    if(!envHasWorktopIn(5.45,6.55,-3.18,-2.12))addBoxTo(g,'MAP_QC_TABLE_TOP',5.45,6.55,.825,.86,-3.17,-2.13,topMat);
    report.groundedTables.qcUnderframeSynthesized=true;
  }
  const visStage4Table=layout?.getObjectByName?.('VIS_STAGE_4_TABLE')||null;
  if(visStage4Table){
    visStage4Table.traverse(o=>{if(o.isMesh)hide(o);});
    report.groundedTables.deduplicatedLayoutTables.push('VIS_STAGE_4_TABLE');
  }

  // 2) Stage 1 Prep table: deduplicate if M1 grounded it in environment; synthesize if standalone env lacks layout.
  const nativeS1Grounded=envHasGroundedIn(-11.56,-10.44,-2.13,-1.07)&&envHasWorktopIn(-11.56,-10.44,-2.13,-1.07);
  const visStage1Table=layout?.getObjectByName?.('VIS_STAGE_1_TABLE')||null;
  if(nativeS1Grounded&&visStage1Table){
    visStage1Table.traverse(o=>{if(o.isMesh)hide(o);});
    report.groundedTables.deduplicatedLayoutTables.push('VIS_STAGE_1_TABLE');
  }else if(!nativeS1Grounded&&!visStage1Table){
    const g=new THREE.Group();g.name='MAP_STAGE1_TABLE_UNDERFRAME';
    wsDetail.add(g);addedNodes.push(g);
    for(const [lx0,lx1] of [[-11.4825,-11.4375],[-10.5625,-10.5175]]){
      for(const [lz0,lz1] of [[-2.0325,-1.9875],[-1.3125,-1.2675]])addBoxTo(g,'MAP_STAGE1_TABLE_LEG',lx0,lx1,0,.83,lz0,lz1,frameMat);
    }
    addBoxTo(g,'MAP_STAGE1_TABLE_RAIL',-11.48,-10.52,.3325,.3675,-1.9875,-1.9525,frameMat);
    addBoxTo(g,'MAP_STAGE1_TABLE_TOP',-11.55,-10.45,.825,.86,-2.12,-1.08,topMat);
    report.groundedTables.stage1StandaloneSynthesized=true;
  }

  // 3) Robot Pack table: deduplicate VIS_ROBOT_PACK_TABLE in layout when environment
  // already has grounded ROBOT_PACK_TABLE (zero coplanar Z-fighting & clean ENV_ROBOT_CELL
  // dimming/visibility); otherwise keep VIS_ROBOT_PACK_TABLE and ground ROBOT_TABLE_REINFORCEMENT.
  const nativeRobotPackTable=environment.getObjectByName('ROBOT_PACK_TABLE');
  const nativeRobotGrounded=envHasGroundedIn(2.95,4.05,-3.17,-2.13);
  const nativeRobotTop=envHasWorktopIn(2.95,4.05,-3.17,-2.13);
  if(actual&&nativeRobotPackTable&&nativeRobotGrounded&&nativeRobotTop){
    actual.traverse(o=>{if(o.isMesh)hide(o);});
    report.groundedTables.deduplicatedLayoutTables.push('VIS_ROBOT_PACK_TABLE');
  }else if(actual){
    if(nativeRobotTop){
      const dupProbe=new THREE.Box3(new THREE.Vector3(2.94,.78,-3.18),new THREE.Vector3(4.06,.865,-2.12));
      environment.traverse(o=>{
        if(!o.isMesh||!isNodeVisible(o)||hasAncestor(o,'ENV_FLOOR_AND_GRID'))return;
        const b=new THREE.Box3().setFromObject(o);
        if(b.intersectsBox(dupProbe)&&b.max.y<=.862&&(b.max.x-b.min.x)>=.75&&(b.max.z-b.min.z)>=.65)hide(o);
      });
    }
    const reinf=environment.getObjectByName('ROBOT_TABLE_REINFORCEMENT');
    if(reinf){
      const rb=new THREE.Box3().setFromObject(reinf);
      if(!rb.isEmpty()&&rb.min.y>.005&&rb.min.y<.08){
        const g=new THREE.Group();g.name='MAP_ROBOT_REINFORCEMENT_FEET';
        robotCell.add(g);addedNodes.push(g);
        for(const [lx0,lx1] of [[3.015,3.065],[3.935,3.985]]){
          for(const [lz0,lz1] of [[-3.085,-3.035],[-2.365,-2.315]])addBoxTo(g,'MAP_ROBOT_FOOT',lx0,lx1,0,rb.min.y+.005,lz0,lz1,frameMat);
        }
        report.groundedTables.robotUnderframeSynthesized=true;
      }
    }
  }else if(!nativeRobotGrounded||!nativeRobotTop){
    const g=new THREE.Group();g.name='MAP_ROBOT_TABLE_UNDERFRAME';
    robotCell.add(g);addedNodes.push(g);
    if(!nativeRobotGrounded){
      for(const [lx0,lx1] of [[3.0175,3.0625],[3.9375,3.9825]]){
        for(const [lz0,lz1] of [[-3.0825,-3.0375],[-2.3625,-2.3175]])addBoxTo(g,'MAP_ROBOT_TABLE_LEG',lx0,lx1,0,.83,lz0,lz1,frameMat);
      }
      addBoxTo(g,'MAP_ROBOT_TABLE_RAIL',3.02,3.98,.3325,.3675,-3.0375,-3.0025,frameMat);
    }
    if(!nativeRobotTop)addBoxTo(g,'MAP_ROBOT_TABLE_TOP',2.95,4.05,.825,.86,-3.17,-2.13,topMat);
    report.groundedTables.robotUnderframeSynthesized=true;
  }

  // 4) Legacy WATER_COOLER plinth grounding (in cached 28m GLB, body minY is 0.020m).
  const coolerProbe=new THREE.Box3(new THREE.Vector3(10.04,0,-7.99),new THREE.Vector3(10.44,1.30,-7.50));
  let coolerMinY=Infinity;
  environment.traverse(o=>{
    if(!o.isMesh||!isNodeVisible(o)||hasAncestor(o,'ENV_FLOOR_AND_GRID'))return;
    const b=new THREE.Box3().setFromObject(o);
    if(b.intersectsBox(coolerProbe)&&b.min.y<coolerMinY)coolerMinY=b.min.y;
  });
  if(Number.isFinite(coolerMinY)&&coolerMinY>.005&&coolerMinY<.10){
    addBoxTo(breakArea,'MAP_WATER_COOLER_PLINTH',10.06,10.42,0,coolerMinY+.002,-7.95,-7.61,frameMat);
    report.groundedTables.waterCoolerPlinthSynthesized=true;
  }

  // 5) Grounded 4-leg BENCH_REWORK ([1.80, 0, +6.35]) & BENCH_SCRAP ([8.65, 0, +6.35])
  // Synthesize when absent/hidden in environment, or ground if M1 GLB includes them above y=0.005m.
  const amberRimMat=findEnvMaterial(/Status amber|Safety ochre/i,'#d48817',.48,.12);
  const redRimMat=findEnvMaterial(/Status red|Alert red/i,'#c83e37',.48,.12);
  const ensureStationBench=(nodeName,cx,cz,w,d,rimMat,reportKey)=>{
    const hx=w*.5,hz=d*.5,x0=cx-hx,x1=cx+hx,z0=cz-hz,z1=cz+hz;
    const existing=environment.getObjectByName(nodeName);
    let hasVisibleTop=envHasWorktopIn(x0+.02,x1-.02,z0+.02,z1-.02);
    let hasGrounded=envHasGroundedIn(x0+.02,x1-.02,z0+.02,z1-.02);
    if(existing&&isNodeVisible(existing)){
      const eb=new THREE.Box3().setFromObject(existing),ec=eb.getCenter(new THREE.Vector3());
      if(!eb.isEmpty()&&ec.z>4.5&&Math.abs(ec.x-cx)<.8){
        hasVisibleTop=hasVisibleTop||eb.max.y>=.84;
        hasGrounded=hasGrounded||eb.min.y<=.005;
      }
    }
    if(hasVisibleTop&&hasGrounded)return;
    const g=new THREE.Group();g.name=existing&&isNodeVisible(existing)?`MAP_${nodeName}_UNDERFRAME`:nodeName;
    wsDetail.add(g);addedNodes.push(g);
    if(!hasGrounded){
      const leg=.045,inset=.055;
      for(const [lx0,lx1] of [[x0+inset,x0+inset+leg],[x1-inset-leg,x1-inset]]){
        for(const [lz0,lz1] of [[z0+inset,z0+inset+leg],[z1-inset-leg,z1-inset]]){
          addBoxTo(g,`${nodeName}_LEG`,lx0,lx1,0,.825,lz0,lz1,frameMat);
        }
      }
      addBoxTo(g,`${nodeName}_RAIL_BACK`,x0+inset+leg,x1-inset-leg,.28,.315,z1-inset-leg,z1-inset,frameMat);
      addBoxTo(g,`${nodeName}_RAIL_L`,x0+inset,x0+inset+leg,.28,.315,z0+inset+leg,z1-inset-leg,frameMat);
      addBoxTo(g,`${nodeName}_RAIL_R`,x1-inset-leg,x1-inset,.28,.315,z0+inset+leg,z1-inset-leg,frameMat);
    }
    if(!hasVisibleTop){
      addBoxTo(g,`${nodeName}_TOP`,x0,x1,.825,.860,z0,z1,topMat);
      const rim=.022;
      addBoxTo(g,`${nodeName}_RIM_F`,x0,x1,.826,.859,z0-.004,z0+rim,rimMat);
      addBoxTo(g,`${nodeName}_RIM_B`,x0,x1,.826,.859,z1-rim,z1+.004,rimMat);
      addBoxTo(g,`${nodeName}_RIM_L`,x0-.004,x0+rim,.826,.859,z0,z1,rimMat);
      addBoxTo(g,`${nodeName}_RIM_R`,x1-rim,x1+.004,.826,.859,z0,z1,rimMat);
    }
    report.groundedTables[reportKey]=true;
  };
  ensureStationBench('BENCH_REWORK',1.80,6.35,1.60,.80,amberRimMat,'reworkBenchSynthesized');
  ensureStationBench('BENCH_SCRAP',8.65,6.35,1.40,.80,redRimMat,'scrapBenchSynthesized');

  // 6) Green-Walkway-Only Floor Arrows (03:14:54Z & 03:59:41Z user overrides):
  // hide ALL .glb floor arrows, chevrons, transfer-lane dashes/corridors, and spur
  // arrow guides outside MAP_WALKWAY_ARROW_* (never touching visual_support props).
  const floorFlowPurgeRe=/ARROW|CHEVRON|_DASH(?:\b|\d)|(?:DISPATCH|INBOUND|SCRAP)_TRANSFER_|REWORK_RETURN_|SPUR_GUIDE_|SPUR_TRANSFER_GUIDES/i;
  let floorArrowsHidden=0;
  for(const root of [environment,layout].filter(Boolean)){
    root.traverse(o=>{
      if(/^MAP_WALKWAY_ARROW_/i.test(o.name||'')||/^VIS_(?:Large|Issued)_arrow/i.test(o.name||''))return;
      if(!o.isMesh&&!o.isLine){
        if(/^(?:DISPATCH_TRANSFER_LANE|INBOUND_TRANSFER_LANE|REWORK_RETURN_LANE|SCRAP_TRANSFER_LANE|SPUR_TRANSFER_GUIDES)$/i.test(o.name||'')&&o.visible){
          hide(o);floorArrowsHidden++;
        }
        return;
      }
      if(!o.visible)return;
      let matched=floorFlowPurgeRe.test(o.name||'');
      if(!matched){
        for(let p=o.parent;p;p=p.parent){
          if(p.name==='ENV_FLOOR_AND_GRID')break;
          if(floorFlowPurgeRe.test(p.name||'')){matched=true;break;}
        }
      }
      if(!matched)return;
      const wb=new THREE.Box3().setFromObject(o);
      if(!wb.isEmpty()&&wb.max.y<.08){hide(o);floorArrowsHidden++;}
    });
  }
  report.floorArrowsHidden=floorArrowsHidden;

  // 7) Unobstructed Ceiling Lock (02:42:13Z user requirement): hide all physical
  // ceiling beams, trusses, cable trays, and hanging lamps across all views,
  // while preserving any Three.js Light sources.
  const overheadBlockRe=/OVERHEAD_TRUSS|OVERHEAD_CABLE_TRAY|HIGHBAY|LUMINAIRE|CEILING_BEAM|LIGHTING_RIG|ENV_OVERHEAD|ENV_LIGHTING_RIG/i;
  const hasLight=node=>{let found=false;node?.traverse?.(c=>{if(c.isLight)found=true;});return found;};
  let overheadSuppressedMeshes=0;
  for(const root of [environment,layout].filter(Boolean)){
    root.traverse(o=>{
      if(o.isLight)return;
      if((o.name==='ENV_OVERHEAD'||o.name==='ENV_LIGHTING_RIG')&&!hasLight(o)&&o.visible){
        hide(o);
        return;
      }
      if((o.isMesh||o.isLine||o.isPoints)&&o.visible){
        for(let p=o;p;p=p.parent){
          if(overheadBlockRe.test(p.name||'')){
            hide(o);
            overheadSuppressedMeshes++;
            break;
          }
        }
      }
    });
  }
  report.overheadSuppressedMeshes=overheadSuppressedMeshes;

  environment.updateMatrixWorld(true);layout?.updateMatrixWorld?.(true);
  let disposed=false;
  const correction={report,dispose(){
    if(disposed)return;disposed=true;
    for(let i=addedNodes.length-1;i>=0;i--)addedNodes[i].removeFromParent();
    for(let i=relocations.length-1;i>=0;i--){
      const move=relocations[i];
      move.parent.add(move.object);move.object.position.copy(move.position);move.object.quaternion.copy(move.quaternion);move.object.scale.copy(move.scale);
      const list=move.parent.children;list.splice(list.indexOf(move.object),1);list.splice(move.index,0,move.object);
      move.object.updateMatrixWorld(true);
    }
    for(const [mesh,original,owned] of geometries){mesh.geometry=original;owned.dispose();}
    for(let i=visibility.length-1;i>=0;i--){const [object,visible]=visibility[i];object.visible=visible;}
    for(const g of ownedGeometries)g.dispose();
    for(const m of ownedMaterials)m.dispose();
    environment.updateMatrixWorld(true);layout?.updateMatrixWorld?.(true);
    applied.delete(environment);
  }};
  applied.set(environment,correction);return correction;
}
