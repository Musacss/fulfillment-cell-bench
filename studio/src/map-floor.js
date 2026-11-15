// Runtime corrections for the authored v02 map. The GLBs remain immutable.
import * as THREE from 'three';
import {MAP_LAYOUT,isNativeExpandedMap} from './map-layout.js';

const applied=new WeakMap();
const REVISION='map-expanded-floor-2026-11-14';
const HEIGHT={lane:.006,white:.008,label:.008};
export const WALKWAY_ARROW_CENTERS=MAP_LAYOUT.arrowCenters;

const NON_WALKWAY_FLOOR_FLOW_RE=/ARROW|CHEVRON|_DASH(?:\b|\d)|(?:DISPATCH|INBOUND|SCRAP)_TRANSFER_|REWORK_RETURN_|SPUR_GUIDE_|SPUR_TRANSFER_GUIDES/i;
function isNonWalkwayFloorFlow(meshObj){
  if(/^MAP_WALKWAY_ARROW_/i.test(meshObj.name||''))return false;
  for(let p=meshObj;p;p=p.parent){
    if(p.name==='ENV_FLOOR_AND_GRID')break;
    if(NON_WALKWAY_FLOOR_FLOW_RE.test(p.name||''))return true;
  }
  return NON_WALKWAY_FLOOR_FLOW_RE.test(meshObj.name||'');
}
function stripMergedFloorFlowComponents(meshObj,ownedGeometry){
  const mName=meshObj.name||'';
  if(!/^ENV_FLOOR_AND_GRID__/i.test(mName)||/CAD_grid|Raised_concrete_slab|Lower_reveal|Printed_charcoal|Safety_ochre/i.test(mName))return;
  const orig=meshObj.geometry,pos=orig?.getAttribute('position');
  if(!pos)return;
  const idx=orig.index,triCount=(idx?idx.count:pos.count)/3|0;
  if(triCount<1||triCount>12000)return;
  const parent=new Int32Array(triCount).fill(-1);
  const find=x=>{while(parent[x]>=0)x=parent[x];return x;};
  const unite=(a,b)=>{a=find(a);b=find(b);if(a===b)return;if(parent[a]>parent[b])[a,b]=[b,a];parent[a]+=parent[b];parent[b]=a;};
  const vMap=new Map(),wx=new Float32Array(triCount*3),wz=new Float32Array(triCount*3),v=new THREE.Vector3();
  for(let t=0;t<triCount;t++){
    for(let k=0;k<3;k++){
      const vi=idx?idx.getX(t*3+k):t*3+k;
      v.fromBufferAttribute(pos,vi).applyMatrix4(meshObj.matrixWorld);
      wx[t*3+k]=v.x;wz[t*3+k]=v.z;
      const key=`${Math.round(v.x*2500)}_${Math.round(v.z*2500)}`;
      if(vMap.has(key))unite(t,vMap.get(key));else vMap.set(key,t);
    }
  }
  const comps=new Map();
  for(let t=0;t<triCount;t++){
    const r=find(t);let c=comps.get(r);
    if(!c){c={tris:[],minX:1e9,maxX:-1e9,minZ:1e9,maxZ:-1e9,diag:0};comps.set(r,c);}
    c.tris.push(t);
    for(let k=0;k<3;k++){
      const x=wx[t*3+k],z=wz[t*3+k],nx=wx[t*3+(k+1)%3],nz=wz[t*3+(k+1)%3];
      if(x<c.minX)c.minX=x;if(x>c.maxX)c.maxX=x;if(z<c.minZ)c.minZ=z;if(z>c.maxZ)c.maxZ=z;
      if(Math.abs(nx-x)>.03&&Math.abs(nz-z)>.03&&Math.hypot(nx-x,nz-z)>.14)c.diag++;
    }
  }
  const dropRoots=new Set();
  for(const [r,c] of comps){
    const sx=c.maxX-c.minX,sz=c.maxZ-c.minZ,cx=(c.minX+c.maxX)*.5,cz=(c.minZ+c.maxZ)*.5;
    if(sx>.85||sz>.85)continue;
    const isChevronOrSpur=c.tris.length<=8&&Math.max(sx,sz)>.24&&Math.min(sx,sz)>.18&&c.diag>=2;
    const inEastTransfer=cx>10.68&&cx<12.78&&cz>-5.05&&cz<6.65&&!(cx>=10.68&&cx<=12.55&&cz>=-2.70&&cz<=-.90);
    const inWestInbound=cx>-17.15&&cx<-13.55&&cz>-4.05&&cz<6.65&&Math.min(sx,sz)<.14&&Math.max(sx,sz)>.22&&c.tris.length<=4;
    if(isChevronOrSpur||(inEastTransfer&&Math.min(sx,sz)<.14&&Math.max(sx,sz)>.22&&c.tris.length<=4)||inWestInbound)dropRoots.add(r);
  }
  if(!dropRoots.size)return;
  const keepTris=[];
  for(let t=0;t<triCount;t++)if(!dropRoots.has(find(t)))keepTris.push(t);
  if(!keepTris.length){meshObj.visible=false;return;}
  const g=orig.clone();
  if(idx){
    const nextIdx=new Uint32Array(keepTris.length*3);
    keepTris.forEach((t,i)=>{nextIdx[i*3]=idx.getX(t*3);nextIdx[i*3+1]=idx.getX(t*3+1);nextIdx[i*3+2]=idx.getX(t*3+2);});
    g.setIndex(new THREE.BufferAttribute(nextIdx,1));
  }else{
    for(const [k,a] of Object.entries(orig.attributes)){
      const arr=new Float32Array(keepTris.length*3*a.itemSize);
      keepTris.forEach((t,i)=>{for(let j=0;j<3;j++)for(let s=0;s<a.itemSize;s++)arr[(i*3+j)*a.itemSize+s]=a.getComponent(t*3+j,s);});
      g.setAttribute(k,new THREE.BufferAttribute(arr,a.itemSize,a.normalized));
    }
  }
  g.computeBoundingBox();g.computeBoundingSphere();
  ownedGeometry.add(g);meshObj.geometry=g;
}
function oneMaterial(mesh){return Array.isArray(mesh.material)?mesh.material[0]:mesh.material;}
function positionBounds(mesh){
  mesh.updateWorldMatrix(true,false);
  return new THREE.Box3().setFromObject(mesh);
}

function topCaptionGeometry(source,parent){
  // Extract only the upward-facing top cap of ESCAPED / HOLD (works for both
  // legacy batched Status amber at .00255 m and native OUTCOME_FLOOR_ESCAPED_LABEL at .0067 m).
  const geometry=source.geometry,positions=geometry.getAttribute('position');
  const normals=geometry.getAttribute('normal'),index=geometry.index;
  const points=[],normalValues=[],vertex=new THREE.Vector3();
  const normal=new THREE.Vector3(),normalMatrix=new THREE.Matrix3().getNormalMatrix(source.matrixWorld);
  const inverseParent=parent.matrixWorld.clone().invert();
  const count=index?index.count:positions.count;
  const restrictHoldRegion=!/ESCAPED_LABEL/i.test(source.name||'');
  let capMaxY=-Infinity;
  const candidates=[];
  for(let i=0;i<count;i+=3){
    const ids=[0,1,2].map(k=>index?index.getX(i+k):i+k);
    const world=ids.map(id=>vertex.fromBufferAttribute(positions,id).applyMatrix4(source.matrixWorld).clone());
    const upward=ids.every(id=>normals&&normal.fromBufferAttribute(normals,id).applyMatrix3(normalMatrix).normalize().y>.98);
    if(!upward)continue;
    if(restrictHoldRegion&&!world.every(p=>p.x>8.4&&p.x<11.6&&p.z>-5.3&&p.z<-3.4&&p.y>.0024&&p.y<.0085))continue;
    const triMinY=Math.min(world[0].y,world[1].y,world[2].y);
    if(triMinY>capMaxY)capMaxY=triMinY;
    candidates.push(world);
  }
  const minCapY=capMaxY-.00018;
  for(const world of candidates){
    if(!world.every(p=>p.y>=minCapY))continue;
    for(const point of world){point.applyMatrix4(inverseParent);points.push(point.x,point.y,point.z);normalValues.push(0,1,0);}
  }
  if(!points.length)throw new Error('Failed to extract ESCAPED / HOLD floor caption');
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
  if(!values.length)throw new Error('Missing zone caption '+zone.id);
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

const GLYPH_SEGMENTS=Object.freeze({
  '0':[[0,0,1,0],[1,0,1,1],[1,1,0,1],[0,1,0,0]],
  '1':[[.5,0,.5,1],[.2,.8,.5,1],[.2,0,.8,0]],
  '2':[[0,1,1,1],[1,1,1,.5],[1,.5,0,.5],[0,.5,0,0],[0,0,1,0]],
  '3':[[0,1,1,1],[1,1,1,0],[0,.5,.9,.5],[0,0,1,0]],
  '4':[[0,1,0,.5],[0,.5,1,.5],[.85,1,.85,0]],
  'A':[[0,0,0,.75],[0,.75,.5,1],[.5,1,1,.75],[1,.75,1,0],[0,.42,1,.42]],
  'C':[[1,.88,.8,1],[.8,1,.2,1],[.2,1,0,.8],[0,.8,0,.2],[0,.2,.2,0],[.2,0,.8,0],[.8,0,1,.12]],
  'K':[[0,0,0,1],[1,1,.1,.5],[.1,.5,1,0]],
  'L':[[0,1,0,0],[0,0,1,0]],
  'M':[[0,0,0,1],[0,1,.5,.45],[.5,.45,1,1],[1,1,1,0]],
  'N':[[0,0,0,1],[0,1,1,0],[1,0,1,1]],
  'O':[[.15,0,.85,0],[.85,0,1,.2],[1,.2,1,.8],[1,.8,.85,1],[.85,1,.15,1],[.15,1,0,.8],[0,.8,0,.2],[0,.2,.15,0]],
  'P':[[0,0,0,1],[0,1,.85,1],[.85,1,1,.82],[1,.82,1,.60],[1,.60,.85,.46],[.85,.46,0,.46]],
  'S':[[1,.88,.8,1],[.8,1,.15,1],[.15,1,0,.8],[0,.8,0,.56],[0,.56,1,.44],[1,.44,1,.2],[1,.2,.85,0],[.85,0,0,.1]],
  'T':[[0,1,1,1],[.5,1,.5,0]],
  'U':[[0,1,0,.18],[0,.18,.2,0],[.2,0,.8,0],[.8,0,1,.18],[1,.18,1,1]],
  '/':[[.1,0,.9,1]],
  '(':[[.75,1,.35,.7],[.35,.7,.35,.3],[.35,.3,.75,0]],
  ')':[[.25,1,.65,.7],[.65,.7,.65,.3],[.65,.3,.25,0]],
  '+':[[.5,.15,.5,.85],[.12,.5,.88,.5]],
  '-':[[.15,.5,.85,.5]],
});

function buildVectorFloorTextGeometry(text,xLeft,zBottom,capHeight=.19,stroke=.026,y=.0078){
  const points=[],normals=[],charW=capHeight*.62,stepX=charW+capHeight*.24,half=stroke*.5;
  const addQuad=(x0,z0,x1,z1)=>{
    const dx=x1-x0,dz=z1-z0,len=Math.hypot(dx,dz);
    if(len<1e-5)return;
    const ex=(dx/len)*half*.35,ez=(dz/len)*half*.35;
    const sx0=x0-ex,sz0=z0-ez,sx1=x1+ex,sz1=z1+ez;
    const nx=(-dz/len)*half,nz=(dx/len)*half;
    const ax=sx0+nx,az=sz0+nz,bx=sx0-nx,bz=sz0-nz,cx=sx1-nx,cz=sz1-nz,dxp=sx1+nx,dzp=sz1+nz;
    points.push(ax,y,az,cx,y,cz,bx,y,bz,ax,y,az,dxp,y,dzp,cx,y,cz);
    for(let i=0;i<6;i++)normals.push(0,1,0);
  };
  const upper=String(text).toUpperCase();
  for(let idx=0;idx<upper.length;idx++){
    const ch=upper[idx];
    if(ch===' ')continue;
    const segs=GLYPH_SEGMENTS[ch];
    if(!segs)continue;
    const ox=xLeft+idx*stepX;
    for(const [u0,v0,u1,v1] of segs){
      addQuad(ox+u0*charW,zBottom-v0*capHeight,ox+u1*charW,zBottom-v1*capHeight);
    }
  }
  const g=new THREE.BufferGeometry();
  g.setAttribute('position',new THREE.Float32BufferAttribute(points,3));
  g.setAttribute('normal',new THREE.Float32BufferAttribute(normals,3));
  g.computeBoundingBox();g.computeBoundingSphere();
  return g;
}

function buildFlowChevronGeometry(cx,cz,angleRad,y=.0074,arm=.24,stroke=.10){
  const shape=new THREE.Shape();
  const hw=stroke*.5,tip=arm*.72,tail=-arm*.58,wing=arm*.78;
  const pts=[[tail,-wing],[tail+stroke,-wing],[tip+hw,0],[tail+stroke,wing],[tail,wing],[tip-hw,0]];
  pts.forEach(([px,py],i)=>i?shape.lineTo(px,py):shape.moveTo(px,py));
  shape.closePath();
  const g=new THREE.ShapeGeometry(shape);
  g.rotateX(-Math.PI/2);
  if(Math.abs(angleRad)>1e-6)g.rotateY(angleRad);
  g.translate(cx,y,cz);
  const p=g.getAttribute('position'),n=g.getAttribute('normal');
  for(let i=0;i<p.count;i++){p.setY(i,y);if(n)n.setXYZ(i,0,1,0);}
  g.computeBoundingBox();g.computeBoundingSphere();
  return g;
}

export function applyMapFloorFixes(environment,layout){
  if(applied.has(environment))return applied.get(environment);
  environment.updateMatrixWorld(true);
  const floor=environment.getObjectByName('ENV_FLOOR_AND_GRID');
  if(!floor)throw new Error('Missing ENV_FLOOR_AND_GRID layer');
  if(isNativeExpandedMap(environment)){
    const changed=[],ownedMaterials=new Set(),ownedGeometry=new Set();
    const patch=new THREE.Group();patch.name='MAP_FLOOR_FIXES';
    patch.userData.map_revision=REVISION;patch.userData.nativeFloorPreserved=true;
    const lane=floor.getObjectByName('WALKWAY_GREEN_5S');
    const oldWhite=floor.getObjectByName('ENV_FLOOR_AND_GRID__Paper_labels');
    const oldArrows=floor.getObjectByName('ENV_FLOOR_AND_GRID__Warm_white_laminate');
    const nativeHoldLabel=floor.getObjectByName('OUTCOME_FLOOR_ESCAPED_LABEL');
    const hiddenSet=new Set([lane,oldWhite,oldArrows,nativeHoldLabel].filter(Boolean));
    const reports={revision:REVISION,nativeFloorPreserved:true,removedLaneBuckets:[lane,oldWhite,oldArrows].filter(Boolean).map(o=>o.name),floorDecalsStabilized:0};
    const nativeDecalTier=(meshObj,mat,bounds)=>{
      const name=mat?.name||'',mName=meshObj.name||'';
      if(/CAD grid|Expanded grid/i.test(name)||/CAD_grid|MAP_CAD_GRID/i.test(mName)){
        const major=/major/i.test(name)||/major/i.test(mName);
        return {order:2,factor:-2,units:major?-5:-4};
      }
      if(/_FILL\b/i.test(mName)||/Zone fill/i.test(name)||bounds.max.y<.0015)return {order:1,factor:-1,units:-3};
      if(/_(?:CORNER|LABEL|CHEVRON)/i.test(mName)||/Paper labels|Warm white laminate|Printed charcoal/i.test(name)||bounds.max.y>=.0048){
        return {order:4,factor:-4,units:-10};
      }
      return {order:3,factor:-3,units:-6};
    };
    const cloneNativeDecal=(src,suffix,tier)=>{
      if(!src)return src;
      const m=src.clone();m.name=`${src.name||'Floor decal'} / ${suffix}`;
      m.polygonOffset=true;m.polygonOffsetFactor=tier.factor;m.polygonOffsetUnits=tier.units;
      m.depthTest=true;m.depthWrite=false;ownedMaterials.add(m);return m;
    };
    let hasNativeZoneFills=false,hasNativeAutoSlotFill=false;
    floor.traverse(meshObj=>{
      if(!meshObj.isMesh)return;
      if(/^FLOOR_ZONE_01_FILL$/i.test(meshObj.name))hasNativeZoneFills=true;
      if(/AUTO_SLOT.*FILL|Safety_ochre|Printed_charcoal/i.test(meshObj.name))hasNativeAutoSlotFill=true;
      changed.push({mesh:meshObj,visible:meshObj.visible,position:meshObj.position.clone(),castShadow:meshObj.castShadow,receiveShadow:meshObj.receiveShadow,renderOrder:meshObj.renderOrder,material:meshObj.material,geometry:meshObj.geometry,hadDecalFlag:Object.hasOwn(meshObj.userData,'map_floor_decal'),decalFlag:meshObj.userData.map_floor_decal});
      if(hiddenSet.has(meshObj)){meshObj.castShadow=false;meshObj.visible=false;return;}
      const bounds=positionBounds(meshObj);
      if(bounds.max.y<.08&&isNonWalkwayFloorFlow(meshObj)){
        meshObj.castShadow=false;meshObj.visible=false;return;
      }
      if(bounds.max.y<.08)stripMergedFloorFlowComponents(meshObj,ownedGeometry);
      if(!meshObj.visible)return;
      if(bounds.min.y<=-.04||bounds.max.y>=.04)return;
      const tier=nativeDecalTier(meshObj,oneMaterial(meshObj),bounds);
      meshObj.castShadow=false;meshObj.receiveShadow=false;meshObj.renderOrder=tier.order;
      meshObj.material=Array.isArray(meshObj.material)
        ? meshObj.material.map((m,i)=>cloneNativeDecal(m,`native decal ${i}`,tier))
        : cloneNativeDecal(meshObj.material,'native decal',tier);
      meshObj.userData.map_floor_decal=true;
      reports.floorDecalsStabilized++;
    });
    const makeDecalMat=(src,fallbackColor,name,units,factor=-1,rough=.68)=>{
      const m=src?src.clone():new THREE.MeshStandardMaterial({color:fallbackColor,roughness:rough,metalness:.02});
      m.name=name;m.polygonOffset=true;m.polygonOffsetFactor=factor;m.polygonOffsetUnits=units;
      m.depthTest=true;m.depthWrite=true;ownedMaterials.add(m);return m;
    };
    const addPatchMesh=(name,geom,mat,order=3)=>{
      const o=new THREE.Mesh(geom,mat);o.name=name;o.castShadow=false;o.receiveShadow=false;o.renderOrder=order;
      o.userData.map_floor_decal=true;patch.add(o);ownedGeometry.add(geom);return o;
    };
    const addPatchPlane=(name,width,depth,x,z,y,mat,order=3)=>{
      const g=new THREE.PlaneGeometry(width,depth);g.rotateX(-Math.PI/2);g.translate(x,y,z);
      return addPatchMesh(name,g,mat,order);
    };
    if(!hasNativeZoneFills){
      const fillDefs=[
        ['MAP_ZONE_01_FILL',-13.35,-8.55,-4.90,-.65,'#d3dde5'],
        ['MAP_ZONE_02_FILL',-8.15,-3.95,-4.90,-.65,'#d0e1e5'],
        ['MAP_ZONE_03_FILL',-3.55,5.10,-4.90,-.65,'#cfe1de'],
        ['MAP_ZONE_04_FILL',5.40,8.775,-4.90,-.65,'#d4d9e6'],
        ['MAP_OUTCOME_GOOD_FILL',10.70,12.50,-2.65,-.95,'#d1e3d6'],
        ['MAP_OUTCOME_HOLD_FILL',9.00,11.00,-5.075,-3.725,'#e8dfc8'],
        ['MAP_ZONE_R_FILL',1.90,4.50,6.45,8.15,'#e6dcc7'],
        ['MAP_OUTCOME_SCRAP_FILL',7.10,8.90,6.45,8.15,'#e5d2d3'],
      ];
      for(const [fName,x0,x1,z0,z1,hex] of fillDefs){
        const fm=makeDecalMat(null,hex,'Map / '+fName,-2,-1,.82);
        addPatchPlane(fName,x1-x0,z1-z0,(x0+x1)/2,(z0+z1)/2,.0060,fm,1);
      }
    }
    if(!hasNativeAutoSlotFill){
      const autoPadMat=makeDecalMat(null,'#c4d9d6','Map / Auto-slot pad',-3,-1,.80);
      addPatchPlane('MAP_ZONE_03_AUTO_SLOT_FILL',1.90,2.35,3.50,-3.18,.0061,autoPadMat,1);
    }
    const z01Border=floor.getObjectByName('FLOOR_ZONE_01_BORDER');
    const z01Box=z01Border?positionBounds(z01Border):null;
    const z01Span=z01Box?z01Box.max.z-z01Box.min.z:0;
    const z01Thick=z01Span>1.0?z01Span-4.25:z01Span;
    if(!z01Box||z01Thick<.065){
      const boldBlue=makeDecalMat(z01Border?oneMaterial(z01Border):null,'#2f5d7c','Map / Bold zone border',-6,-3,.58);
      for(const z of MAP_LAYOUT.zones){
        const x0=z.id==='01'?-13.35:z.minX,x1=z.maxX,w=x1-x0,cx=(x0+x1)/2,zf=-MAP_LAYOUT.zoneFront,zb=-MAP_LAYOUT.zoneBack;
        for(const bz of [zf,zb])addPatchPlane(`MAP_ZONE_${z.id}_BORDER_BOLD`,w+.085,.085,cx,bz,.0068,boldBlue,3);
        for(const bx of [x0,x1])addPatchPlane(`MAP_ZONE_${z.id}_BORDER_BOLD`,.085,zf-zb+.085,bx,(zf+zb)/2,.0068,boldBlue,3);
      }
    }
    const z03Label=floor.getObjectByName('FLOOR_ZONE_03_LABEL');
    const z03Box=z03Label?positionBounds(z03Label):null;
    if(!z03Box||(z03Box.max.x-z03Box.min.x)<2.6){
      if(z03Label)z03Label.visible=false;
      const z03Mat=makeDecalMat(z03Label?oneMaterial(z03Label):null,'#2b5876','Map / Zone 03 auto-slot caption',-10,-4,.55);
      addPatchMesh('MAP_ZONE_03_LABEL',buildVectorFloorTextGeometry(MAP_LAYOUT.zones[2].label,-3.38,-.82,.19,.026,.0078),z03Mat,4);
    }
    const green=makeDecalMat(lane?oneMaterial(lane):null,'#2b7a52','Map / Pedestrian lane',-12,-5,.62);
    const white=makeDecalMat(oldWhite?oneMaterial(oldWhite):null,'#f2f4f7','Map / Lane white',-14,-6,.55);
    const arrowWhite=makeDecalMat(oldArrows?oneMaterial(oldArrows):null,'#f6f7f8','Map / Three lane arrows',-14,-6,.55);
    const amberSrc=nativeHoldLabel?oneMaterial(nativeHoldLabel):oneMaterial(floor.getObjectByName('OUTCOME_FLOOR_ESCAPED_BORDER')||{});
    const amberText=makeDecalMat(amberSrc,'#d48817','Map / Hold caption',-12,-5,.55);
    const laneLength=MAP_LAYOUT.laneHalfLength*2;
    addPatchPlane('MAP_WALKWAY_GREEN',laneLength,1.5,0,5.15,HEIGHT.lane,green,5);
    for(const z of [4.42,5.88])addPatchPlane('MAP_WALKWAY_BORDER',laneLength,.045,0,z,HEIGHT.white,white,6);
    for(const x of [-MAP_LAYOUT.laneHalfLength,MAP_LAYOUT.laneHalfLength])addPatchPlane('MAP_WALKWAY_END',.045,1.5,x,5.15,HEIGHT.white,white,6);
    for(const x of WALKWAY_ARROW_CENTERS){
      const shape=new THREE.Shape();
      const outline=[[-.48,-.06],[.08,-.06],[.08,-.24],[.48,0],[.08,.24],[.08,.06],[-.48,.06]];
      outline.forEach(([px,py],i)=>i?shape.lineTo(px,py):shape.moveTo(px,py));shape.closePath();
      const geom=new THREE.ShapeGeometry(shape);geom.rotateX(-Math.PI/2);geom.translate(x,HEIGHT.white,5.15);
      const arrow=addPatchMesh(`MAP_WALKWAY_ARROW_${x===0?'CENTER':x<0?'START':'END'}`,geom,arrowWhite,6);
      arrow.userData.center_x=x;arrow.userData.direction='+X';
    }
    let holdCaptionBounds=null;
    if(nativeHoldLabel){
      const holdLabel=addPatchMesh('MAP_ESCAPED_HOLD_LABEL',topCaptionGeometry(nativeHoldLabel,floor),amberText,6);
      floor.add(patch);environment.updateMatrixWorld(true);
      const hb=positionBounds(holdLabel);
      holdCaptionBounds={min:hb.min.toArray(),max:hb.max.toArray()};
    }else{
      floor.add(patch);environment.updateMatrixWorld(true);
    }
    const qcRight=MAP_LAYOUT.zones.at(-1).maxX+.0325;
    const nativeZones=MAP_LAYOUT.zones.map(({id,label,minX,maxX})=>({
      id,label,minX:id==='01'?-13.35:minX,maxX,minZ:-MAP_LAYOUT.zoneBack,maxZ:-MAP_LAYOUT.zoneFront,
    }));
    Object.assign(reports,{
      laneBounds:{min:[-MAP_LAYOUT.laneHalfLength,HEIGHT.lane,4.4],max:[MAP_LAYOUT.laneHalfLength,HEIGHT.lane,5.9]},
      arrows:WALKWAY_ARROW_CENTERS.map(x=>({center:[x,HEIGHT.white,5.15],direction:'+X'})),
      arrowSpacing:11.8,endMargins:[5.9,5.9],zebras:0,wayfindingLabels:0,
      zones:nativeZones,
      holdZone:{minX:9,maxX:11,minZ:-5.075,maxZ:-3.725,outerMinX:8.9675,qcRightEdge:qcRight,gapToQc:8.9675-qcRight},
      ...(holdCaptionBounds?{holdCaptionBounds}:{}),
      paintDepthTest:true,paintDepthWrite:true,paintShadows:false,
    });
    let disposed=false;
    const result={report:reports,dispose(){
      if(disposed)return;disposed=true;patch.removeFromParent();
      for(const state of changed){
        Object.assign(state.mesh,{visible:state.visible,castShadow:state.castShadow,receiveShadow:state.receiveShadow,renderOrder:state.renderOrder,material:state.material,geometry:state.geometry});
        state.mesh.position.copy(state.position);
        state.mesh.updateWorldMatrix(true,false);
        if(state.hadDecalFlag)state.mesh.userData.map_floor_decal=state.decalFlag;
        else delete state.mesh.userData.map_floor_decal;
      }
      for(const geom of ownedGeometry)geom.dispose();
      for(const material of ownedMaterials)material.dispose();
      applied.delete(environment);
    }};
    applied.set(environment,result);return result;
  }
  const original=[];floor.traverse(o=>{if(o.isMesh)original.push(o);});
  const byMaterial=name=>original.find(o=>oneMaterial(o)?.name===name);
  const lane=original.find(o=>o.name==='WALKWAY_GREEN_5S');
  const oldWhite=byMaterial('Paper labels'),oldArrows=byMaterial('Warm white laminate'),oldAmber=byMaterial('Status amber'),oldBlue=byMaterial('Petrol powder coat');
  if(!lane||!oldWhite||!oldArrows||!oldAmber||!oldBlue)throw new Error('Missing walkway or floor markings in map');

  const changed=[],ownedMaterials=new Set(),ownedGeometry=new Set();
  const patch=new THREE.Group();patch.name='MAP_FLOOR_FIXES';patch.userData.map_revision=REVISION;
  const reports={revision:REVISION,removedLaneBuckets:[lane.name,oldWhite.name,oldArrows.name],floorDecalsStabilized:0};
  function cloneDecalMaterial(source,name,level=2,depthWrite=true){
    const material=source?source.clone():new THREE.MeshStandardMaterial({color:'#cfd9e2',roughness:.8,metalness:.02});
    material.name=name;
    material.polygonOffset=true;material.polygonOffsetFactor=-Math.max(1,Math.min(6,Math.ceil(level/2)));material.polygonOffsetUnits=-level;
    material.depthTest=true;material.depthWrite=depthWrite;
    ownedMaterials.add(material);return material;
  }

  // Stabilize every floor decal, not the floor slab or the rest of the factory.
  // Shadow-map precision cannot resolve the original sub-millimetre paint
  // films, so paint/grid must neither cast nor receive shadow maps.
  for(const mesh of original){
    changed.push({mesh,visible:mesh.visible,position:mesh.position.clone(),castShadow:mesh.castShadow,receiveShadow:mesh.receiveShadow,renderOrder:mesh.renderOrder,material:mesh.material,hadDecalFlag:Object.hasOwn(mesh.userData,'map_floor_decal'),decalFlag:mesh.userData.map_floor_decal});
    mesh.castShadow=false;
    if(mesh===lane||mesh===oldWhite||mesh===oldArrows||mesh===oldAmber||mesh===oldBlue){mesh.visible=false;continue;}
    const bounds=positionBounds(mesh);
    if(bounds.max.y<.08&&isNonWalkwayFloorFlow(mesh)){mesh.visible=false;continue;}
    if(bounds.max.y<.04&&bounds.min.y>-.04){
      const grid=/CAD_grid|MAP_CAD_GRID/i.test(mesh.name),major=/major/i.test(mesh.name),level=grid?(major?5:4):6;
      mesh.material=Array.isArray(mesh.material)?mesh.material.map((m,i)=>cloneDecalMaterial(m,`${m.name} / map decal ${i}`,level,false)):cloneDecalMaterial(mesh.material,`${mesh.material.name} / map decal`,level,false);
      mesh.receiveShadow=false;mesh.renderOrder=grid?2:3;mesh.userData.map_floor_decal=true;reports.floorDecalsStabilized++;
    }
  }

  const green=cloneDecalMaterial(oneMaterial(lane),'Map / Pedestrian lane',12,true);
  const white=cloneDecalMaterial(oneMaterial(oldWhite),'Map / Lane white',14,true);
  const arrowWhite=cloneDecalMaterial(oneMaterial(oldArrows),'Map / Three lane arrows',14,true);
  const amber=cloneDecalMaterial(oneMaterial(oldAmber),'Map / Hold zone',6,true);
  const amberText=cloneDecalMaterial(oneMaterial(oldAmber),'Map / Hold caption',10,true);
  const blue=cloneDecalMaterial(oneMaterial(oldBlue),'Map / Aligned workstation zones',6,true);
  function mesh(name,geometry,material,order=3){
    const object=new THREE.Mesh(geometry,material);object.name=name;
    object.castShadow=false;object.receiveShadow=false;object.renderOrder=order;
    object.userData.map_floor_decal=true;patch.add(object);ownedGeometry.add(geometry);return object;
  }
  function plane(name,width,depth,x,z,y,material,order=3){
    const geometry=new THREE.PlaneGeometry(width,depth);geometry.rotateX(-Math.PI/2);
    geometry.translate(x,y,z);return mesh(name,geometry,material,order);
  }

  const legacyFills=[
    ['MAP_ZONE_01_FILL',-12.40,-8.55,-4.90,-.65,'#d3dde5'],
    ['MAP_ZONE_02_FILL',-8.15,-3.95,-4.90,-.65,'#d0e1e5'],
    ['MAP_ZONE_03_FILL',-3.55,5.10,-4.90,-.65,'#cfe1de'],
    ['MAP_ZONE_04_FILL',5.40,8.775,-4.90,-.65,'#d4d9e6'],
    ['MAP_ZONE_03_AUTO_SLOT_FILL',2.55,4.45,-4.30,-2.00,'#c4d9d6'],
    ['MAP_OUTCOME_HOLD_FILL',9.00,11.00,-5.075,-3.725,'#e8dfc8'],
  ];
  for(const [fName,x0,x1,z0,z1,hex] of legacyFills){
    const fm=new THREE.MeshStandardMaterial({color:hex,roughness:.82,metalness:.02,polygonOffset:true,polygonOffsetFactor:-1,polygonOffsetUnits:-2,depthTest:true,depthWrite:true});
    fm.name='Map / '+fName;ownedMaterials.add(fm);
    plane(fName,x1-x0,z1-z0,(x0+x1)/2,(z0+z1)/2,.0060,fm,1);
  }

  const laneLength=MAP_LAYOUT.laneHalfLength*2;
  plane('MAP_WALKWAY_GREEN',laneLength,1.5,0,5.15,HEIGHT.lane,green,5);
  for(const z of [4.42,5.88])plane('MAP_WALKWAY_BORDER',laneLength,.045,0,z,HEIGHT.white,white,6);
  for(const x of [-MAP_LAYOUT.laneHalfLength,MAP_LAYOUT.laneHalfLength])plane('MAP_WALKWAY_END',.045,1.5,x,5.15,HEIGHT.white,white,6);
  for(const x of WALKWAY_ARROW_CENTERS){
    const shape=new THREE.Shape();
    const outline=[[-.48,-.06],[.08,-.06],[.08,-.24],[.48,0],[.08,.24],[.08,.06],[-.48,.06]];
    outline.forEach(([px,py],i)=>i?shape.lineTo(px,py):shape.moveTo(px,py));shape.closePath();
    const geometry=new THREE.ShapeGeometry(shape);geometry.rotateX(-Math.PI/2);geometry.translate(x,HEIGHT.white,5.15);
    const arrow=mesh(`MAP_WALKWAY_ARROW_${x===0?'CENTER':x<0?'START':'END'}`,geometry,arrowWhite,6);
    arrow.userData.center_x=x;arrow.userData.direction='+X';
  }

  for(const zone of MAP_LAYOUT.zones){
    const width=zone.maxX-zone.minX,cx=(zone.minX+zone.maxX)/2,front=-MAP_LAYOUT.zoneFront,back=-MAP_LAYOUT.zoneBack;
    for(const z of [front,back])plane('MAP_ZONE_'+zone.id+'_BORDER',width,.085,cx,z,.0068,blue,3);
    for(const x of [zone.minX,zone.maxX])plane('MAP_ZONE_'+zone.id+'_BORDER',.085,front-back,x,(front+back)/2,.0068,blue,3);
    for(const x of [zone.minX,zone.maxX])for(const z of [front,back]){
      plane('MAP_ZONE_'+zone.id+'_CORNER',.28,.095,x+(x===zone.minX?.14:-.14),z,HEIGHT.white,blue,4);
      plane('MAP_ZONE_'+zone.id+'_CORNER',.095,.28,x,z+(z===back?.14:-.14),HEIGHT.white,blue,4);
    }
    const labelGeom=zone.id==='03'
      ? buildVectorFloorTextGeometry(zone.label,zone.minX+.18,front-.18,.19,.026,.0078)
      : zoneCaptionGeometry(oldBlue,floor,zone);
    mesh('MAP_ZONE_'+zone.id+'_LABEL',labelGeom,blue,4);
  }
  const r=mesh('MAP_REWORK_ZONE_PAINT',reworkPaintGeometry(oldBlue),blue,3);
  r.position.copy(oldBlue.position);r.quaternion.copy(oldBlue.quaternion);r.scale.copy(oldBlue.scale);
  // Match the stable paint level used by the new zones.
  const rp=r.geometry.getAttribute('position');for(let i=0;i<rp.count;i++)rp.setY(i,rp.getY(i)>.0025?HEIGHT.label:HEIGHT.lane);
  const rn=r.geometry.getAttribute('normal');for(let i=0;i<rn.count;i++)rn.setXYZ(i,0,1,0);
  r.geometry.computeBoundingBox();r.geometry.computeBoundingSphere();

  // HOLD is a distinct floor zone, with a real gap to QC. The pallet/outcome
  // anchor stays at x=10, z=-4.4; only its painted frame and caption change.
  const hold={cx:10,cz:-4.4,width:1.96,depth:1.35,line:.085};
  for(const z of [hold.cz-hold.depth/2,hold.cz+hold.depth/2])plane('MAP_HOLD_ZONE_BORDER',hold.width,hold.line,hold.cx,z,.0068,amber,3);
  for(const x of [hold.cx-hold.width/2,hold.cx+hold.width/2])plane('MAP_HOLD_ZONE_BORDER',hold.line,hold.depth,x,hold.cz,.0068,amber,3);
  for(const sx of [-1,1])for(const sz of [-1,1]){
    plane('MAP_HOLD_ZONE_CORNER',.26,.095,hold.cx+sx*(hold.width/2-.13),hold.cz+sz*hold.depth/2,HEIGHT.white,amber,4);
    plane('MAP_HOLD_ZONE_CORNER',.095,.26,hold.cx+sx*hold.width/2,hold.cz+sz*(hold.depth/2-.13),HEIGHT.white,amber,4);
  }
  const label=mesh('MAP_ESCAPED_HOLD_LABEL',topCaptionGeometry(oldAmber,floor),amberText,6);
  floor.add(patch);environment.updateMatrixWorld(true);
  const labelBounds=positionBounds(label);
  const qcRight=MAP_LAYOUT.zones.at(-1).maxX+.0425;
  Object.assign(reports,{
    laneBounds:{min:[-MAP_LAYOUT.laneHalfLength,HEIGHT.lane,4.4],max:[MAP_LAYOUT.laneHalfLength,HEIGHT.lane,5.9]},
    arrows:WALKWAY_ARROW_CENTERS.map(x=>({center:[x,HEIGHT.white,5.15],direction:'+X'})),
    arrowSpacing:11.8,endMargins:[5.9,5.9],zebras:0,wayfindingLabels:0,
    zones:MAP_LAYOUT.zones.map(({id,label,minX,maxX})=>({id,label,minX,maxX,minZ:-MAP_LAYOUT.zoneBack,maxZ:-MAP_LAYOUT.zoneFront})),
    holdZone:{minX:9.02,maxX:10.98,minZ:-5.075,maxZ:-3.725,outerMinX:8.9775,qcRightEdge:qcRight,gapToQc:8.9775-qcRight},
    holdCaptionBounds:{min:labelBounds.min.toArray(),max:labelBounds.max.toArray()},
    paintDepthTest:true,paintDepthWrite:true,paintShadows:false,
  });
  let disposed=false;
  const result={report:reports,dispose(){
    if(disposed)return;disposed=true;patch.removeFromParent();
    for(const state of changed){
      Object.assign(state.mesh,{visible:state.visible,castShadow:state.castShadow,receiveShadow:state.receiveShadow,renderOrder:state.renderOrder,material:state.material});
      state.mesh.position.copy(state.position);
      state.mesh.updateWorldMatrix(true,false);
      if(state.hadDecalFlag)state.mesh.userData.map_floor_decal=state.decalFlag;
      else delete state.mesh.userData.map_floor_decal;
    }
    for(const geometry of ownedGeometry)geometry.dispose();
    for(const material of ownedMaterials)material.dispose();
    applied.delete(environment);
  }};
  applied.set(environment,result);return result;
}
