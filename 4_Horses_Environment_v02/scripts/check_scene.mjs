import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';

const threeURL=new URL('../dist/assets/three.module.js',import.meta.url).href;
registerHooks({resolve(specifier,context,next){return specifier==='three'?{url:threeURL,shortCircuit:true}:next(specifier,context);}});
const THREE=await import(threeURL);
const config=JSON.parse(await fs.readFile(new URL('../config/environment.json',import.meta.url),'utf8'));
const moduleCount=config.conveyor.centers_x.length;
const {GLTFLoader}=await import('../dist/assets/GLTFLoader.js');
const path=process.argv[2]||fileURLToPath(new URL('../dist/assets/warehouse_environment.glb',import.meta.url));
const bytes=await fs.readFile(path);
const gltf=await new Promise((resolve,reject)=>new GLTFLoader().parse(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),'',resolve,reject));
const roles={},anchors=[],meshes=[];
gltf.scene.updateMatrixWorld(true);
gltf.scene.traverse(o=>{
  const r=o.userData.animation_role;if(r)(roles[r]??=[]).push(o);
  if(o.name.startsWith('MOUNT_')||o.name.startsWith('ANCHOR_'))anchors.push(o);
  if(o.isMesh){meshes.push(o);o.geometry.computeBoundingBox();const p=o.getWorldPosition(new THREE.Vector3());assert.ok(p.toArray().every(Number.isFinite));}
});
assert.equal(roles.parcel.length,5);
assert.equal(roles.roller.length,moduleCount*20);
assert.equal(roles.stopper.length,1);
assert.equal(anchors.filter(o=>o.name.startsWith('MOUNT_')).length,3);
for(let i=1;i<moduleCount;i++){
  const a=gltf.scene.getObjectByName(`ANCHOR_C${String(i).padStart(2,'0')}_OUT`).getWorldPosition(new THREE.Vector3());
  const b=gltf.scene.getObjectByName(`ANCHOR_C${String(i+1).padStart(2,'0')}_IN`).getWorldPosition(new THREE.Vector3());
  assert.ok(a.distanceTo(b)<1e-5);
  assert.ok(Math.abs(a.y-.86)<1e-5);
}
for(const o of roles.parcel){
  const p=o.getWorldPosition(new THREE.Vector3());assert.ok(Math.abs(p.y-.86)<1e-5);
  assert.ok(o.userData.parcel_id);
}
const triangles=meshes.reduce((n,o)=>n+(o.geometry.index?o.geometry.index.count/3:o.geometry.attributes.position.count/3),0);
const bounds=new THREE.Box3().setFromObject(gltf.scene);
if(process.argv[3]){
  const output={units:'meters',coordinate_system:'glTF / Three.js Y-up',anchors:anchors.map(o=>({id:o.name,position_m:o.getWorldPosition(new THREE.Vector3()).toArray(),role:o.userData.role,clearance_xyz_m:o.userData.clearance?[o.userData.clearance[0],o.userData.clearance[2],o.userData.clearance[1]]:undefined}))};
  await fs.writeFile(process.argv[3],JSON.stringify(output,null,2));
}
const size=bounds.getSize(new THREE.Vector3());
assert.ok(Math.abs(size.x-config.room.width)<1e-4);
assert.ok(Math.abs(size.z-config.room.depth)<1e-4);
const benchBounds=new THREE.Box3().setFromObject(gltf.scene.getObjectByName('BENCH_PICK'));
const rackBounds=new THREE.Box3().setFromObject(gltf.scene.getObjectByName('RACK_02'));
const conveyorBounds=new THREE.Box3().setFromObject(gltf.scene.getObjectByName('CONVEYOR_03'));
const frontClearance=conveyorBounds.min.z-benchBounds.max.z;
const rearClearance=benchBounds.min.z-rackBounds.max.z;
assert.ok(frontClearance>=1.7);
assert.ok(rearClearance>=2.8);
console.log(JSON.stringify({passed:true,loader:'Three.js GLTFLoader 0.170.0, independent of GPU',meshes:meshes.length,triangles,anchors:anchors.length,parcels:roles.parcel.length,rollers:roles.roller.length,future_mounts:3,connected_modules:moduleCount,work_surface_m:.86,bounds_m:size.toArray(),bench_to_conveyor_clearance_m:Number(frontClearance.toFixed(3)),bench_to_shelving_clearance_m:Number(rearClearance.toFixed(3))}));
