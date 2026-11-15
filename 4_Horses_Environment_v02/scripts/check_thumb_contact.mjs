// Verify actual thumb triangles touching the carton side, not just a bone marker.
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
const url=new URL('../dist/assets/three.module.js',import.meta.url).href;
registerHooks({resolve(s,c,next){return s==='three'?{url,shortCircuit:true}:next(s,c);}});
const THREE=await import(url),{GLTFLoader}=await import('../dist/assets/GLTFLoader.js');
function clip(poly,axis,bound,high){
 const result=[];
 for(let i=0;i<poly.length;i++){
  const a=poly[i],b=poly[(i+1)%poly.length],da=a[axis]-bound,db=b[axis]-bound,ina=high?da>=0:da<=0,inb=high?db>=0:db<=0;
  if(ina)result.push(a);if(ina!==inb)result.push(a.clone().lerp(b,da/(da-db)));
 }
 return result;
}
const reports=[];
for(const [character,prefix,file] of [['worker','WORKER','warehouse_worker'],['robot','ROBOT','humanoid_robot']]){
 const bytes=await fs.readFile(new URL('../dist/assets/'+file+'.glb',import.meta.url));
 const gltf=await new Promise((res,rej)=>new GLTFLoader().parse(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),'',res,rej));
 const pieces={L:[],R:[]};
 gltf.scene.traverse(skin=>{
  if(!skin.isSkinnedMesh)return;let owner=skin;while(owner&&!owner.name.startsWith(prefix+'_Body'))owner=owner.parent;if(!owner)return;
  const joints=skin.geometry.attributes.skinIndex,weights=skin.geometry.attributes.skinWeight;
  for(const side of ['L','R']){
   const selected=new Set();for(let i=0;i<joints.count;i++)if(weights.getX(i)>.999&&skin.skeleton.bones[joints.getX(i)].name==='thumb'+side)selected.add(i);
   const index=skin.geometry.index,triangles=[],count=index?.count??joints.count;
   for(let i=0;i<count;i+=3){const ids=[0,1,2].map(j=>index?index.getX(i+j):i+j);if(ids.every(v=>selected.has(v)))triangles.push(ids);}
   if(triangles.length)pieces[side].push({skin,triangles,selected});
  }
 });
 for(const side of ['L','R'])assert.ok(pieces[side].length,'Missing thumb surface '+character+side);
 const mixer=new THREE.AnimationMixer(gltf.scene),box=gltf.scene.getObjectByName('prop_box');let checks=0,maxGap=0,maxPenetration=0,minThumbUp=1;const clips=[];
 for(const name of ['CarryIdle','CarryWalk','PickUp','PlaceDown']){
  mixer.stopAllAction();const animation=gltf.animations.find(c=>c.name===name),action=mixer.clipAction(animation);action.reset().setLoop(THREE.LoopOnce,1);action.clampWhenFinished=true;action.play();let frameCount=0;
  for(let i=0;i<=40;i++){
   const fraction=i/40;if((name==='PickUp'&&fraction<.5)||(name==='PlaceDown'&&fraction>.5))continue;
   action.reset().play();mixer.setTime(animation.duration*fraction);gltf.scene.updateMatrixWorld(true);const center=box.getWorldPosition(new THREE.Vector3());
   for(const [side,sign] of [['L',1],['R',-1]]){
    let distance=Infinity;let surfacePoints=0;
    for(const {skin,triangles,selected} of pieces[side]){
     skin.skeleton.update();const points=new Map();for(const v of selected){const point=new THREE.Vector3();skin.getVertexPosition(v,point).applyMatrix4(skin.matrixWorld);points.set(v,point);}
     for(const ids of triangles){
      let poly=ids.map(i=>points.get(i));
      for(const [axis,lo,hi] of [['y',center.y-.125,center.y+.125],['z',center.z-.14,center.z+.14]]){
       if(poly.length)poly=clip(poly,axis,lo,true);if(poly.length)poly=clip(poly,axis,hi,false);
      }
      for(const p of poly){distance=Math.min(distance,sign*(p.x-center.x)-.18);surfacePoints++;}
     }
    }
    assert.ok(surfacePoints>0,'Thumb misses the carton face');
    assert.ok(Math.abs(distance)<.0015,`${character} ${name} ${side} at ${fraction}: thumb/carton gap ${distance} m`);
    const thumb=gltf.scene.getObjectByName('thumb'+side),up=new THREE.Vector3(0,1,0).transformDirection(thumb.matrixWorld).y;
    assert.ok(up>.75,'Thumb must remain on the upper side of the grip');
    maxGap=Math.max(maxGap,distance);maxPenetration=Math.max(maxPenetration,-distance);minThumbUp=Math.min(minThumbUp,up);checks++;
   }
   frameCount++;
  }
  clips.push({name,frames:frameCount});
 }
 reports.push({character,thumb_surface_checks:checks,max_surface_gap_m:maxGap,max_surface_penetration_m:maxPenetration,min_thumb_up_dot:minThumbUp,clips});
}
console.log(JSON.stringify({passed:true,characters:reports},null,2));
