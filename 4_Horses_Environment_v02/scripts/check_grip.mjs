// Test the delivered GLBs: palm contact, opposing normals and a fixed box grip.
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
const url=new URL('../dist/assets/three.module.js',import.meta.url).href;
registerHooks({resolve(s,c,next){return s==='three'?{url,shortCircuit:true}:next(s,c);}});
const THREE=await import(url),{GLTFLoader}=await import('../dist/assets/GLTFLoader.js');
const output=[];
for(const [kind,prefix,file] of [['worker','WORKER','warehouse_worker'],['robot','ROBOT','humanoid_robot']]){
 const bytes=await fs.readFile(new URL('../dist/assets/'+file+'.glb',import.meta.url));
 const gltf=await new Promise((res,rej)=>new GLTFLoader().parse(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),'',res,rej));
 const mixer=new THREE.AnimationMixer(gltf.scene),box=gltf.scene.getObjectByName('prop_box');assert.ok(box);
 let maxError=0,minDot=1,checks=0,maxPenetration=0,bodyVertexChecks=0;const report=[];
 for(const name of ['CarryIdle','CarryWalk','PickUp','PlaceDown']){
  const clip=gltf.animations.find(c=>c.name===name);assert.ok(clip);mixer.stopAllAction();const action=mixer.clipAction(clip);action.reset().setLoop(THREE.LoopOnce,1);action.clampWhenFinished=true;action.play();
  const frames=[];
  for(let i=0;i<=40;i++){
   const fraction=i/40;if((name==='PickUp'&&fraction<.50)||(name==='PlaceDown'&&fraction>.50))continue;
   action.reset().play();mixer.setTime(clip.duration*fraction);gltf.scene.updateMatrixWorld(true);
   const center=box.getWorldPosition(new THREE.Vector3());assert.ok(center.y>.98&&center.y<1.14,'Unexpected carton height');
   for(const [side,sign] of [['L',1],['R',-1]]){
    const a=gltf.scene.getObjectByName('ATTACH_'+prefix+'_HAND_'+side);assert.ok(a);
    const desired=center.clone().add(new THREE.Vector3(sign*.18,.025,0));
    const p=a.getWorldPosition(new THREE.Vector3()),distance=p.distanceTo(desired);maxError=Math.max(maxError,distance);assert.ok(distance<.002,'Palm lost carton contact: '+kind+' '+name+' '+fraction+' '+distance);
    const normal=new THREE.Vector3(1,0,0).transformDirection(a.matrixWorld),dot=normal.dot(new THREE.Vector3(-sign,0,0));minDot=Math.min(minDot,dot);assert.ok(dot>.995,'Palm faces away from carton');checks++;
   }
   // Check the visible hand surface against the carton, allowing a small cloth tolerance.
   gltf.scene.traverse(skin=>{if(!skin.isSkinnedMesh)return;let owner=skin;while(owner&&!owner.name.startsWith(prefix+'_Body'))owner=owner.parent;if(!owner)return;skin.skeleton.update();
    for(let v=0;v<skin.geometry.attributes.position.count;v++){
     const p=new THREE.Vector3();skin.getVertexPosition(v,p).applyMatrix4(skin.matrixWorld);const q=p.clone().sub(center);bodyVertexChecks++;
     if(Math.abs(q.x)<.18&&Math.abs(q.y)<.125&&Math.abs(q.z)<.14){const penetration=Math.min(.18-Math.abs(q.x),.125-Math.abs(q.y),.14-Math.abs(q.z));maxPenetration=Math.max(maxPenetration,penetration);}
    }});
   frames.push(+center.y.toFixed(4));
  }
  report.push({clip:name,samples:frames.length,carton_height_range_m:[Math.min(...frames),Math.max(...frames)]});
 }
 assert.ok(bodyVertexChecks>0,'Missing actual body surfaces');
 assert.ok(maxPenetration<.012,'Visible hand intersects carton: '+kind+' '+maxPenetration);
 output.push({character:kind,contact_checks:checks,body_vertex_checks:bodyVertexChecks,max_contact_error_m:maxError,min_inward_palm_normal_dot:minDot,max_carton_surface_penetration_m:maxPenetration,clips:report});
}
console.log(JSON.stringify({passed:true,characters:output},null,2));
