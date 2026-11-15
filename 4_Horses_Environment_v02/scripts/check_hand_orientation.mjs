// Regression: the actual thumb and finger geometry must be above/forward at contact.
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
const url=new URL('../dist/assets/three.module.js',import.meta.url).href;
registerHooks({resolve(s,c,next){return s==='three'?{url,shortCircuit:true}:next(s,c);}});
const THREE=await import(url),{GLTFLoader}=await import('../dist/assets/GLTFLoader.js');
const reports=[];
for(const [kind,prefix,file] of [['worker','WORKER','warehouse_worker'],['robot','ROBOT','humanoid_robot']]){
 const data=await fs.readFile(new URL('../dist/assets/'+file+'.glb',import.meta.url));
 const gltf=await new Promise((res,rej)=>new GLTFLoader().parse(data.buffer.slice(data.byteOffset,data.byteOffset+data.byteLength),'',res,rej));
 const mixer=new THREE.AnimationMixer(gltf.scene),samples=[];
 for(const [clipName,fraction] of [['Reach',.5],['PickUp',.35],['PickUp',.70],['CarryIdle',.4],['CarryWalk',.3],['PlaceDown',.35]]){
  mixer.stopAllAction();const clip=gltf.animations.find(c=>c.name===clipName);assert.ok(clip);
  const action=mixer.clipAction(clip);action.reset().setLoop(THREE.LoopOnce,1);action.clampWhenFinished=true;action.play();mixer.setTime(clip.duration*fraction);gltf.scene.updateMatrixWorld(true);
  for(const side of ['L','R']){
   const hand=gltf.scene.getObjectByName('hand'+side),thumb=gltf.scene.getObjectByName('thumb'+side);assert.ok(hand&&thumb);
   const fingerForward=new THREE.Vector3(0,1,0).transformDirection(hand.matrixWorld).z;
   const thumbUp=new THREE.Vector3(0,1,0).transformDirection(thumb.matrixWorld).y;
   assert.ok(thumbUp>(clipName==='Reach'?.97:.75),`${kind} ${clipName} ${side}: thumb points ${thumbUp}, expected upper grip with flex toward carton`);
   assert.ok(fingerForward>.995,`${kind} ${clipName} ${side}: fingers must point forward`);
   const thumbPoints=[],fingerPoints=[];
   gltf.scene.traverse(skin=>{
    if(!skin.isSkinnedMesh)return;
    let owner=skin;while(owner&&!owner.name.startsWith(prefix+'_Body'))owner=owner.parent;if(!owner)return;
    skin.skeleton.update();
    const joints=skin.geometry.attributes.skinIndex,weights=skin.geometry.attributes.skinWeight;
    for(let v=0;v<joints.count;v++){
     if(weights.getX(v)<.999)continue;
     const bone=skin.skeleton.bones[joints.getX(v)];if(!bone?.name.endsWith(side))continue;
     if(bone.name!=='thumb'+side&&!bone.name.startsWith('finger'))continue;
     const point=new THREE.Vector3();skin.getVertexPosition(v,point).applyMatrix4(skin.matrixWorld);
     (bone.name.startsWith('thumb')?thumbPoints:fingerPoints).push(point);
    }
   });
   assert.ok(thumbPoints.length&&fingerPoints.length,'Missing actual digit geometry');
   const averageY=points=>points.reduce((sum,p)=>sum+p.y,0)/points.length;
   const thumbAboveFingers=averageY(thumbPoints)-averageY(fingerPoints);
   assert.ok(thumbAboveFingers>.025,`${kind} ${clipName} ${side}: visible thumb is below fingers (${thumbAboveFingers})`);
   samples.push({clip:clipName,fraction,hand:side,thumb_up_dot:+thumbUp.toFixed(6),fingers_forward_dot:+fingerForward.toFixed(6),thumb_above_fingers_m:+thumbAboveFingers.toFixed(5)});
  }
 }
 const transitions=[];
 for(const clipName of ['Reach','PickUp']){
  mixer.stopAllAction();const clip=gltf.animations.find(c=>c.name===clipName);const action=mixer.clipAction(clip);action.reset().setLoop(THREE.LoopOnce,1);action.clampWhenFinished=true;action.play();
  const previous={};let maxWristStep=0;const earlyThumbDirections=[];
  for(let i=0;i<=96;i++){
   action.reset().play();mixer.setTime(clip.duration*i/96);gltf.scene.updateMatrixWorld(true);
   for(const side of ['L','R']){
    const hand=gltf.scene.getObjectByName('hand'+side),thumb=gltf.scene.getObjectByName('thumb'+side);const q=hand.getWorldQuaternion(new THREE.Quaternion());
    if(previous[side])maxWristStep=Math.max(maxWristStep,q.angleTo(previous[side]));previous[side]=q;
    if(i%8===0&&i<=32)earlyThumbDirections.push({fraction:+(i/96).toFixed(4),hand:side,thumb_up_dot:+new THREE.Vector3(0,1,0).transformDirection(thumb.matrixWorld).y.toFixed(5)});
   }
  }
  assert.ok(maxWristStep<.20,'Abrupt wrist turn: '+kind+' '+clipName);
  transitions.push({clip:clipName,frame_samples:97,max_wrist_step_degrees:maxWristStep*180/Math.PI,early_thumb_directions:earlyThumbDirections});
 }
 reports.push({character:kind,checks:samples.length,samples,transitions});
}
console.log(JSON.stringify({passed:true,characters:reports},null,2));
