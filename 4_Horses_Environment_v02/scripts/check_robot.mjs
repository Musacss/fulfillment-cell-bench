// Verify the exported robot, its rigid skinning and the human-sized skeleton.
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
const threeURL=new URL('../dist/assets/three.module.js',import.meta.url).href;
registerHooks({resolve(specifier,context,next){return specifier==='three'?{url:threeURL,shortCircuit:true}:next(specifier,context);}});
const THREE=await import(threeURL);
const { GLTFLoader }=await import('../dist/assets/GLTFLoader.js');
async function readModel(file){
  const bytes=await fs.readFile(new URL('../dist/assets/'+file,import.meta.url));
  return new Promise((resolve,reject)=>new GLTFLoader().parse(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),'',resolve,reject));
}
const gltf=await readModel('humanoid_robot.glb'),human=await readModel('warehouse_worker.glb');
const skins=[];gltf.scene.traverse(o=>{if(o.isSkinnedMesh)skins.push(o);});
assert.equal(skins.length,10);assert.equal(skins[0].skeleton.bones.length,32);
assert.deepEqual(gltf.animations.map(c=>c.name),['Idle','Walk','CarryIdle','Reach','PickUp','PlaceDown','CarryWalk','RobotPack','Jammed','Service','Offline','RobotPack_Oversize','Jammed_Oversize','Service_Oversize']);
for(const side of ['L','R'])assert.ok(gltf.scene.getObjectByName('ATTACH_ROBOT_HAND_'+side));
gltf.scene.updateMatrixWorld(true);human.scene.updateMatrixWorld(true);
const jointComparison=[];
for(const bone of skins[0].skeleton.bones.filter(b=>!b.name.startsWith('finger')&&!b.name.startsWith('thumb')&&!b.name.startsWith('prop_'))){
  const reference=human.scene.getObjectByName(bone.name);assert.ok(reference,'Missing human reference joint '+bone.name);
  const distance=bone.getWorldPosition(new THREE.Vector3()).distanceTo(reference.getWorldPosition(new THREE.Vector3()));
  assert.ok(distance<.00002,'Different human joint location: '+bone.name);jointComparison.push({joint:bone.name,distance_m:distance});
}
for(const skin of skins){
  const weights=skin.geometry.attributes.skinWeight;
  for(let i=0;i<weights.count;i++){
    const w=[weights.getX(i),weights.getY(i),weights.getZ(i),weights.getW(i)];
    assert.equal(w.filter(v=>v>1e-6).length,1,'Armor blended across joints');assert.ok(Math.abs(w.reduce((a,b)=>a+b,0)-1)<1e-5);
  }
}
const mixer=new THREE.AnimationMixer(gltf.scene),p=new THREE.Vector3(),clips=[];let samples=0;
for(const clip of gltf.animations){
  mixer.stopAllAction();mixer.clipAction(clip).play();const bounds=new THREE.Box3();
  for(let sample=0;sample<=24;sample++){
    mixer.setTime(clip.duration*sample/24);gltf.scene.updateMatrixWorld(true);
    for(const skin of skins){skin.skeleton.update();for(let i=0;i<skin.geometry.attributes.position.count;i++){
      skin.getVertexPosition(i,p).applyMatrix4(skin.matrixWorld);
      assert.ok(p.toArray().every(Number.isFinite),'Non-finite skinned point');
      assert.ok(Math.abs(p.x)<1 && Math.abs(p.z)<1 && p.y>-.07 && p.y<2.05,'Unbounded robot deformation '+clip.name+': '+p.toArray());
      bounds.expandByPoint(p);samples++;
    }}
  }
  clips.push({name:clip.name,duration_s:clip.duration,envelope_m:bounds.getSize(new THREE.Vector3()).toArray().map(v=>+v.toFixed(4)),min_y_m:+bounds.min.y.toFixed(4)});
}
console.log(JSON.stringify({passed:true,loader:'Three.js GLTFLoader 0.170.0',skinned_primitives:skins.length,bones:32,rigid_skinning:true,human_joint_comparison:jointComparison,vertex_pose_samples:samples,clips},null,2));
