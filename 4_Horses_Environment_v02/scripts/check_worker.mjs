// Check actual exported skinning and clips with the same Three.js loader as the viewer.
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
const threeURL=new URL('../dist/assets/three.module.js',import.meta.url).href;
registerHooks({resolve(specifier,context,next){return specifier==='three'?{url:threeURL,shortCircuit:true}:next(specifier,context);}});
const THREE=await import(threeURL);
const { GLTFLoader }=await import('../dist/assets/GLTFLoader.js');
const bytes=await fs.readFile(new URL('../dist/assets/warehouse_worker.glb',import.meta.url));
const gltf=await new Promise((resolve,reject)=>new GLTFLoader().parse(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),'',resolve,reject));
const skins=[];gltf.scene.traverse(o=>{if(o.isSkinnedMesh)skins.push(o);});
assert.equal(skins.length,14);
assert.deepEqual(gltf.animations.map(c=>c.name),['Idle','Walk','CarryIdle','Reach','PickUp','PlaceDown','CarryWalk','Prepare','Pick','Pack','Inspect','Assist','Break','Prepare_Oversize','Pick_Oversize','Pack_Oversize','Inspect_Oversize']);
for(const side of ['L','R'])assert.ok(gltf.scene.getObjectByName('ATTACH_WORKER_HAND_'+side));
const mixer=new THREE.AnimationMixer(gltf.scene),p=new THREE.Vector3();
let samples=0;
const results=[];
for(const clip of gltf.animations){
  mixer.stopAllAction();const action=mixer.clipAction(clip);action.play();
  const envelope=new THREE.Box3();
  for(let sample=0;sample<=24;sample++){
    mixer.setTime(clip.duration*sample/24);gltf.scene.updateMatrixWorld(true);
    for(const skin of skins){
      skin.skeleton.update();
      for(let i=0;i<skin.geometry.attributes.position.count;i++){
        skin.getVertexPosition(i,p).applyMatrix4(skin.matrixWorld);
        assert.ok(p.toArray().every(Number.isFinite),'Non-finite skinned vertex');
        assert.ok(Math.abs(p.x)<1 && Math.abs(p.z)<1 && p.y>-.07 && p.y<2.05,'Unbounded deformation '+clip.name+': '+p.toArray());
        envelope.expandByPoint(p);samples++;
      }
    }
  }
  results.push({name:clip.name,duration_s:clip.duration,envelope_m:envelope.getSize(new THREE.Vector3()).toArray().map(n=>+n.toFixed(4)),min_y_m:+envelope.min.y.toFixed(4)});
}
console.log(JSON.stringify({passed:true,loader:'Three.js GLTFLoader 0.170.0',skinned_primitives:skins.length,bones:skins[0].skeleton.bones.length,vertex_pose_samples:samples,clips:results},null,2));
