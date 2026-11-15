import * as THREE from 'three';

// Only the building envelope changes. Process equipment and replay anchors
// retain their authored metre coordinates.
export const MAP_LAYOUT=Object.freeze({
  width:36,depth:18,dockX:17.85,dockZ:5.15,
  laneHalfLength:17.7,laneWidth:1.5,
  arrowCenters:Object.freeze([-11.8,0,11.8]),
  zoneFront:.65,zoneBack:4.9,
  zones:Object.freeze([
    {id:'01',label:'01 PREP',minX:-12.4,maxX:-8.55,source:[-13.475,-9.725,-4.2,-.7]},
    {id:'02',label:'02 PICK',minX:-8.15,maxX:-3.95,source:[-7.875,-4.525,-5.1,-1.4]},
    {id:'03',label:'03 PACK + ROBOT',minX:-3.55,maxX:5.10,source:[-.35,4.95,-4.9,-1.4]},
    {id:'04',label:'04 QC',minX:5.40,maxX:8.775,source:[5.125,8.775,-5.1,-1.4]},
  ]),
});
const applied=new WeakMap();

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
  const changes=[],geometry=[],ownedGeometry=[],ownedMaterials=[];
  const remember=o=>{changes.push({o,visible:o.visible,position:o.position.clone(),scale:o.scale.clone()});return o;};
  const replace=(mesh,result)=>{geometry.push({mesh,original:mesh.geometry});mesh.geometry=result;ownedGeometry.push(result);};
  const patch=new THREE.Group();patch.name='MAP_LAYOUT_EXPANSION';walls.add(patch);
  const gridPatch=new THREE.Group();gridPatch.name='MAP_EXPANDED_GRID';floor.add(gridPatch);
  const material=name=>{let found;environment.traverse(o=>{if(o.isMesh&&o.material?.name===name)found=o.material;});if(!found)throw new Error('Нет материала '+name);return found;};
  const wallMat=material('FlexSim / Cutaway wall'),darkMat=material('FlexSim / Graphite steel');
  const addBox=(name,w,h,d,x,y,z,mat)=>{
    const g=new THREE.BoxGeometry(w,h,d),o=new THREE.Mesh(g,mat);ownedGeometry.push(g);
    o.name=name;o.position.set(x,y,z);o.castShadow=true;o.receiveShadow=true;patch.add(o);return o;
  };
  for(const [name,ratio] of [['Raised_concrete_slab',36/28],['Lower_reveal',35.92/27.92]]){
    const o=environment.getObjectByName(name);if(!o)throw new Error('Нет плиты '+name);remember(o);o.scale.x*=ratio;
  }
  const rearNames=['Plinth_edge','Porcelain_wall_panels','Safety_ochre','Satin_zinc_steel'];
  for(const suffix of rearNames){
    const mesh=environment.getObjectByName('ENV_WALLS_AND_DOCKS__'+suffix);
    if(mesh)replace(mesh,remap(mesh,p=>{p.x*=36/28;return p;}));
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
    // Full-height rear returns and low front parapets keep a useful cutaway.
    for(const [lo,hi,height] of [[-8.85,-.30,3.6],[-.30,3.35,.32],[6.95,8.85,.32]]){
      addBox('MAP_SIDE_WALL',.13,height,hi-lo,side*17.85,height/2,(lo+hi)/2,wallMat);
      addBox('MAP_SIDE_SKIRTING',.18,.16,hi-lo,side*17.825,.08,(lo+hi)/2,darkMat);
    }
    addBox('MAP_DOCK_LINTEL',.16,.65,3.6,side*17.85,3.275,5.15,wallMat);
  }
  const jack=environment.getObjectByName('PALLET_JACK');
  if(jack){remember(jack);jack.position.set(-16.85,0,2.8);}
  const removedAxis=[];
  for(const o of [...floor.children]){
    if(o.isMesh&&(/Axis_[XY]/.test(o.name)||/CAD_grid_(major|minor)/.test(o.name))){remember(o);o.visible=false;if(/Axis_/.test(o.name))removedAxis.push(o.name);}
  }
  const gridMat={};
  for(const kind of ['minor','major']){
    const m=material('FlexSim / CAD grid '+kind).clone();m.name='Map / Expanded grid '+kind;
    m.polygonOffset=true;m.polygonOffsetFactor=-1;m.polygonOffsetUnits=-1;
    m.depthTest=true;m.depthWrite=true;ownedMaterials.push(m);gridMat[kind]=m;
  }
  const line=(name,width,depth,x,z,major)=>{
    const g=new THREE.PlaneGeometry(width,depth);g.rotateX(-Math.PI/2);g.translate(x,.003,z);ownedGeometry.push(g);
    const o=new THREE.Mesh(g,gridMat[major?'major':'minor']);o.name=name;o.renderOrder=1;
    o.castShadow=false;o.receiveShadow=false;o.userData.map_floor_decal=true;gridPatch.add(o);
  };
  for(let x=-23;x<=23;x++)line('MAP_CAD_GRID_X',x%5===0?.014:.006,28,x,0,x%5===0);
  for(let z=-14;z<=14;z++)line('MAP_CAD_GRID_Z',46,z%5===0?.014:.006,0,z,z%5===0);
  environment.updateMatrixWorld(true);
  const report={width:36,previousWidth:28,depth:18,docks:[[-17.85,0,5.15],[17.85,0,5.15]],
    corridor:{min:[-17.7,.025,4.4],max:[17.7,2.2,5.9],width:1.5},removedAxis,scaleCaptionRemoved:true,
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
