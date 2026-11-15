import * as THREE from 'three';

// Only the building envelope changes. Process equipment and replay anchors
// retain their authored metre coordinates.
export const MAP_LAYOUT=Object.freeze({
  width:36,depth:18,wallHeight:3.6,dockX:17.85,dockZ:5.15,
  laneHalfLength:17.7,laneWidth:1.5,
  arrowCenters:Object.freeze([-11.8,0,11.8]),
  zoneFront:.65,zoneBack:4.9,
  zones:Object.freeze([
    {id:'01',label:'01 PREP',minX:-12.4,maxX:-8.55,source:[-13.475,-9.725,-4.2,-.7]},
    {id:'02',label:'02 PICK',minX:-8.15,maxX:-3.95,source:[-7.875,-4.525,-5.1,-1.4]},
    {id:'03',label:'03 / PACK (MANUAL + AUTO SLOT)',minX:-3.55,maxX:5.10,source:[-.35,4.95,-4.9,-1.4]},
    {id:'04',label:'04 QC',minX:5.40,maxX:8.775,source:[5.125,8.775,-5.1,-1.4]},
  ]),
});
const applied=new WeakMap();

export function findFloorSlab(environment){
  const direct=environment?.getObjectByName?.('Raised_concrete_slab')
    ||environment?.getObjectByName?.('Raised concrete slab')
    ||environment?.getObjectByName?.('ENV_FLOOR_AND_GRID__Warm_mineral_concrete');
  if(direct?.isMesh)return direct;
  const floor=environment?.getObjectByName?.('ENV_FLOOR_AND_GRID');
  let fallback=null;
  floor?.traverse(o=>{
    if(!o.isMesh||fallback)return;
    const mat=Array.isArray(o.material)?o.material[0]:o.material;
    if(mat?.name==='Warm mineral concrete'||/^Warm mineral concrete\b/i.test(mat?.name||''))fallback=o;
  });
  return fallback;
}

export function isNativeExpandedMap(environment){
  const expansion=environment?.getObjectByName?.('MAP_LAYOUT_EXPANSION');
  if(expansion&&typeof expansion.userData?.nativeExpanded==='boolean')return expansion.userData.nativeExpanded;
  const slab=findFloorSlab(environment);
  const pos=slab?.geometry?.getAttribute?.('position');
  if(!pos||pos.count===0)return false;
  let minX=Infinity,maxX=-Infinity;
  for(let i=0;i<pos.count;i++){const x=pos.getX(i);if(x<minX)minX=x;if(x>maxX)maxX=x;}
  if((maxX-minX)>=35.5)return true;
  if(Math.abs((slab.scale?.x??1)-1)>1e-4){
    slab.updateWorldMatrix(true,false);
    const worldBox=new THREE.Box3().setFromObject(slab);
    if(!worldBox.isEmpty()&&(worldBox.max.x-worldBox.min.x)>=35.5)return true;
  }
  return false;
}

// Static export batches share materials across independent architectural
// parts. Clone their buffers, keeping the frozen source and other players safe.
function remap(mesh,pointMap,keepPart=()=>true){
  const source=mesh.geometry.index?mesh.geometry.toNonIndexed():mesh.geometry;
  const position=source.getAttribute('position'),world=[];
  for(let i=0;i<position.count;i++)world.push(new THREE.Vector3().fromBufferAttribute(position,i).applyMatrix4(mesh.matrixWorld));
  const parent=Array.from({length:position.count},(_,i)=>i),seen=new Map();
  const find=i=>{while(parent[i]!==i){parent[i]=parent[parent[i]];i=parent[i];}return i;};
  const join=(a,b)=>{parent[find(a)]=find(b);};
  for(let i=0;i<world.length;i++){
    const key=world[i].toArray().map(v=>Math.round(v*1e5)).join(',');
    if(seen.has(key))join(i,seen.get(key));else seen.set(key,i);
    if(i%3)join(i,i-i%3);
  }
  const boxes=new Map();
  for(let i=0;i<world.length;i++){const id=find(i);if(!boxes.has(id))boxes.set(id,new THREE.Box3());boxes.get(id).expandByPoint(world[i]);}
  const keep=[];
  for(let i=0;i<world.length;i+=3)if(keepPart(boxes.get(find(i))))keep.push(i,i+1,i+2);
  const result=new THREE.BufferGeometry(),inverse=mesh.matrixWorld.clone().invert();
  for(const [name,attribute] of Object.entries(source.attributes)){
    const values=new Float32Array(keep.length*attribute.itemSize);
    keep.forEach((old,index)=>{for(let k=0;k<attribute.itemSize;k++)values[index*attribute.itemSize+k]=attribute.getComponent(old,k);});
    result.setAttribute(name,new THREE.BufferAttribute(values,attribute.itemSize,attribute.normalized));
  }
  const target=result.getAttribute('position');
  keep.forEach((old,i)=>{const p=pointMap(world[old].clone()).applyMatrix4(inverse);target.setXYZ(i,p.x,p.y,p.z);});
  result.computeBoundingBox();result.computeBoundingSphere();
  if(source!==mesh.geometry)source.dispose();return result;
}

export function applyMapLayoutExpansion(environment){
  if(applied.has(environment))return applied.get(environment);
  environment.updateMatrixWorld(true);
  const floor=environment.getObjectByName('ENV_FLOOR_AND_GRID'),walls=environment.getObjectByName('ENV_WALLS_AND_DOCKS');
  if(!floor||!walls)throw new Error('Не найдены архитектурные слои карты');
  const nativeExpanded=isNativeExpandedMap(environment);
  const changes=[],geometry=[],ownedGeometry=[],ownedMaterials=[];
  const remember=o=>{changes.push({o,visible:o.visible,position:o.position.clone(),scale:o.scale.clone()});return o;};
  const replace=(mesh,result)=>{geometry.push({mesh,original:mesh.geometry});mesh.geometry=result;ownedGeometry.push(result);};
  const patch=new THREE.Group();patch.name='MAP_LAYOUT_EXPANSION';patch.userData.nativeExpanded=nativeExpanded;walls.add(patch);
  const gridPatch=new THREE.Group();gridPatch.name='MAP_EXPANDED_GRID';gridPatch.userData.nativeExpanded=nativeExpanded;floor.add(gridPatch);
  const findMaterial=name=>{
    let found=null;
    environment.traverse(o=>{
      if(!o.isMesh||found)return;
      for(const m of Array.isArray(o.material)?o.material:[o.material]){
        if(m?.name===name||(typeof name==='string'&&m?.name?.toLowerCase().startsWith(name.toLowerCase()))){found=m;break;}
      }
    });
    return found;
  };
  const findGridMaterial=kind=>{
    const re=kind==='major'?/FlexSim\s*\/\s*CAD grid major/i:/FlexSim\s*\/\s*CAD grid minor/i;
    let found=null;
    environment.traverse(o=>{
      if(!o.isMesh||found)return;
      for(const m of Array.isArray(o.material)?o.material:[o.material]){
        if(re.test(m?.name||'')){found=m;break;}
      }
    });
    return found;
  };
  const buildInteriorClippedGrid=()=>{
    const minorSrc=findGridMaterial('minor'),majorSrc=findGridMaterial('major');
    const gridMat={};
    for(const [kind,src,fallbackHex,units] of [['minor',minorSrc,'#c6cfd7',-2],['major',majorSrc,'#aebac5',-3]]){
      const m=src?src.clone():new THREE.MeshStandardMaterial({color:fallbackHex,roughness:.75,metalness:.02});
      m.name='Map / Expanded grid '+kind;
      m.polygonOffset=true;m.polygonOffsetFactor=-2;m.polygonOffsetUnits=units;
      m.depthTest=true;m.depthWrite=false;ownedMaterials.push(m);gridMat[kind]=m;
    }
    const line=(name,width,depth,x,z,major)=>{
      const g=new THREE.PlaneGeometry(width,depth);g.rotateX(-Math.PI/2);g.translate(x,major?.0064:.0063,z);ownedGeometry.push(g);
      const o=new THREE.Mesh(g,gridMat[major?'major':'minor']);o.name=name;o.renderOrder=2;
      o.castShadow=false;o.receiveShadow=false;o.userData.map_floor_decal=true;gridPatch.add(o);
    };
    for(let x=-17;x<=17;x++)line('MAP_CAD_GRID_X',x%5===0?.014:.006,17.70,x,0,x%5===0);
    for(let z=-8;z<=8;z++)line('MAP_CAD_GRID_Z',35.70,z%5===0?.014:.006,0,z,z%5===0);
  };
  const material=name=>{const found=findMaterial(name);if(!found)throw new Error('Нет материала '+name);return found;};
  const addBox=(name,w,h,d,x,y,z,mat)=>{
    const g=new THREE.BoxGeometry(w,h,d),o=new THREE.Mesh(g,mat);ownedGeometry.push(g);
    o.name=name;o.position.set(x,y,z);o.castShadow=true;o.receiveShadow=true;patch.add(o);return o;
  };
  const removedAxis=[];
  if(!nativeExpanded){
    const wallMat=material('FlexSim / Cutaway wall'),darkMat=material('FlexSim / Graphite steel');
    const slab=findFloorSlab(environment);if(!slab)throw new Error('Нет плиты Raised_concrete_slab');
    remember(slab);slab.scale.x*=36/28;
    const reveal=environment.getObjectByName('Lower_reveal')||environment.getObjectByName('Lower reveal');
    if(!reveal)throw new Error('Нет плиты Lower_reveal');
    remember(reveal);reveal.scale.x*=35.92/27.92;
    const rearNames=['Plinth_edge','Porcelain_wall_panels','Safety_ochre','Satin_zinc_steel'];
    for(const suffix of rearNames){
      const mesh=environment.getObjectByName('ENV_WALLS_AND_DOCKS__'+suffix);
      if(mesh)replace(mesh,remap(mesh,p=>{
        p.x*=36/28;
        // Only the upper wall/column vertices extend. The service rail,
        // lower bevels, skirting and column guards retain their dimensions.
        if((suffix==='Porcelain_wall_panels'||suffix==='Satin_zinc_steel')&&p.y>3.4)p.y+=MAP_LAYOUT.wallHeight-3.6;
        return p;
      }));
    }
    const shiftDock=p=>{
      if(Math.abs(p.x)>13.4){p.x+=Math.sign(p.x)*4;p.z+=8.75;}
      else if(p.x<-12.3&&p.z<-4.9){p.x-=4;p.z+=8.5;}
      return p;
    };
    for(const o of [...walls.children]){
      if(!o.isMesh||!o.name.startsWith('ENV_WALLS_AND_DOCKS__FlexSim__'))continue;
      if(o.material?.name==='FlexSim / Cutaway wall'){remember(o);o.visible=false;continue;}
      replace(o,remap(o,shiftDock,b=>!(o.material?.name==='FlexSim / Graphite steel'&&b.max.y<.17&&b.max.z-b.min.z>1)));
    }
    for(const side of [-1,1]){
      const dock=environment.getObjectByName('DOCK_0'+(side<0?'1':'2'));
      if(!dock)throw new Error('Нет дока');remember(dock);dock.position.x=side*MAP_LAYOUT.dockX;dock.position.z=MAP_LAYOUT.dockZ;
      // Continuous side walls close the former low-parapet gaps. Only the
      // sectional dock opening remains; the front facade is the open cutaway.
      for(const [lo,hi,height] of [[-8.85,3.35,MAP_LAYOUT.wallHeight],[6.95,8.85,MAP_LAYOUT.wallHeight]]){
        addBox('MAP_SIDE_WALL',.13,height,hi-lo,side*17.85,height/2,(lo+hi)/2,wallMat);
        addBox('MAP_SIDE_SKIRTING',.18,.16,hi-lo,side*17.825,.08,(lo+hi)/2,darkMat);
      }
      addBox('MAP_DOCK_LINTEL',.16,.65,3.6,side*17.85,3.275,5.15,wallMat);
      if(MAP_LAYOUT.wallHeight>3.6+1e-6){
        addBox('MAP_DOCK_UPPER_WALL',.16,MAP_LAYOUT.wallHeight-3.6,3.6,side*17.85,(MAP_LAYOUT.wallHeight+3.6)/2,5.15,wallMat);
      }
    }
    const jack=environment.getObjectByName('PALLET_JACK');
    if(jack){remember(jack);jack.position.set(-16.85,0,2.8);}
    for(const o of [...floor.children]){
      if(o.isMesh&&(/Axis_[XY]/i.test(o.name)||/CAD_grid_(major|minor)/i.test(o.name))){remember(o);o.visible=false;if(/Axis_/i.test(o.name))removedAxis.push(o.name);}
    }
    buildInteriorClippedGrid();
  }else{
    const worldPos=new THREE.Vector3();
    for(const o of [...walls.children]){
      if(!o.isMesh)continue;
      if(o.name==='ENV_WALLS_AND_DOCKS__FlexSim__Cutaway_wall'||o.name==='ENV_WALLS_AND_DOCKS__FlexSim__Graphite_steel'){
        remember(o);o.visible=false;
      }
    }
    const wallMat=findMaterial('FlexSim / Cutaway wall')||findMaterial('Porcelain wall panels')||new THREE.MeshStandardMaterial({color:'#e6ebef',roughness:.65,metalness:.02});
    const darkMat=findMaterial('FlexSim / Graphite steel')||findMaterial('Graphite rubber and guards')||new THREE.MeshStandardMaterial({color:'#2b3137',roughness:.34,metalness:.55});
    if(!findMaterial('FlexSim / Cutaway wall')&&!findMaterial('Porcelain wall panels'))ownedMaterials.push(wallMat);
    if(!findMaterial('FlexSim / Graphite steel')&&!findMaterial('Graphite rubber and guards'))ownedMaterials.push(darkMat);
    for(const side of [-1,1]){
      const dock=environment.getObjectByName('DOCK_0'+(side<0?'1':'2'));
      if(dock){
        dock.getWorldPosition(worldPos);
        if(Math.hypot(worldPos.x-side*MAP_LAYOUT.dockX,worldPos.z-MAP_LAYOUT.dockZ)>.2){
          remember(dock);dock.position.x=side*MAP_LAYOUT.dockX;dock.position.z=MAP_LAYOUT.dockZ;
        }
        dock.traverse(child=>{
          if(child.isMesh&&/^Dock_overdoor_lintel/i.test(child.name)){remember(child);child.visible=false;}
        });
      }
      for(const [lo,hi,height] of [[-8.85,3.35,MAP_LAYOUT.wallHeight],[6.95,8.85,MAP_LAYOUT.wallHeight]]){
        addBox('MAP_SIDE_WALL',.13,height,hi-lo,side*17.85,height/2,(lo+hi)/2,wallMat);
        addBox('MAP_SIDE_SKIRTING',.18,.16,hi-lo,side*17.825,.08,(lo+hi)/2,darkMat);
      }
      addBox('MAP_DOCK_LINTEL',.16,.65,3.6,side*17.85,3.275,5.15,wallMat);
      if(MAP_LAYOUT.wallHeight>3.6+1e-6){
        addBox('MAP_DOCK_UPPER_WALL',.16,MAP_LAYOUT.wallHeight-3.6,3.6,side*17.85,(MAP_LAYOUT.wallHeight+3.6)/2,5.15,wallMat);
      }
    }
    const jack=environment.getObjectByName('PALLET_JACK');
    if(jack){
      jack.getWorldPosition(worldPos);
      if(worldPos.x>-15.0){remember(jack);jack.position.set(-16.85,0,2.8);}
    }
    const gridBox=new THREE.Box3();
    floor.traverse(o=>{
      if(!o.isMesh||o.parent===gridPatch)return;
      if(/Axis_[XY]/i.test(o.name)){remember(o);o.visible=false;removedAxis.push(o.name);return;}
      const m=Array.isArray(o.material)?o.material[0]:o.material;
      if(/CAD_grid/i.test(o.name)||/CAD grid/i.test(m?.name||''))gridBox.union(new THREE.Box3().setFromObject(o));
    });
    const hasInteriorClippedGrid=!gridBox.isEmpty()
      &&(gridBox.max.x-gridBox.min.x)>=33.5
      &&gridBox.min.x>=-18.05&&gridBox.max.x<=18.05
      &&gridBox.min.z>=-9.05&&gridBox.max.z<=9.05;
    if(!hasInteriorClippedGrid){
      floor.traverse(o=>{
        if(!o.isMesh||o.parent===gridPatch)return;
        const m=Array.isArray(o.material)?o.material[0]:o.material;
        if(/CAD_grid_(major|minor)/i.test(o.name)||/CAD grid/i.test(m?.name||'')){remember(o);o.visible=false;}
      });
      buildInteriorClippedGrid();
    }
  }
  environment.updateMatrixWorld(true);
  const report={nativeExpanded,width:36,previousWidth:nativeExpanded?36:28,depth:18,docks:[[-17.85,0,5.15],[17.85,0,5.15]],
    corridor:{min:[-17.7,.025,4.4],max:[17.7,2.2,5.9],width:1.5},removedAxis,scaleCaptionRemoved:true,
    sideWalls:{height:MAP_LAYOUT.wallHeight,panelsPerSide:2,formerParapetGapsClosed:true,upperDockWallsClosed:MAP_LAYOUT.wallHeight>3.6+1e-6},
    processAnchorsMoved:false,conveyorsChanged:false};
  let disposed=false;
  const result={report,dispose(){
    if(disposed)return;disposed=true;patch.removeFromParent();gridPatch.removeFromParent();
    for(const c of changes){c.o.visible=c.visible;c.o.position.copy(c.position);c.o.scale.copy(c.scale);}
    for(const c of geometry)c.mesh.geometry=c.original;
    for(const g of ownedGeometry)g.dispose();for(const m of ownedMaterials)m.dispose();
    environment.updateMatrixWorld(true);applied.delete(environment);
  }};
  applied.set(environment,result);return result;
}
