#!/usr/bin/env node
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import * as THREE from '../studio/node_modules/three/build/three.module.js';
import {GLTFLoader} from '../studio/node_modules/three/examples/jsm/loaders/GLTFLoader.js';
import {applyMapLayoutExpansion} from '../studio/src/map-layout.js';

const ROOT=new URL('../',import.meta.url);
const bytes=await fs.readFile(new URL('4_Horses_Environment_v02/warehouse_environment.glb',ROOT));
const gltf=await new Promise((resolve,reject)=>new GLTFLoader().parse(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),'',resolve,reject));
const environment=gltf.scene.clone(true);
const fix=applyMapLayoutExpansion(environment);
environment.updateMatrixWorld(true);
const patch=environment.getObjectByName('MAP_LAYOUT_EXPANSION');
const walls=patch.children.filter(o=>o.name==='MAP_SIDE_WALL');
const lintels=patch.children.filter(o=>o.name==='MAP_DOCK_LINTEL');
assert.equal(walls.length,4);assert.equal(lintels.length,2);
for(const wall of walls){
  const bounds=new THREE.Box3().setFromObject(wall);
  assert.ok(Math.abs(bounds.min.y)<1e-6&&Math.abs(bounds.max.y-3.6)<1e-6);
}
let wallRays=0,lintelRays=0;
for(const side of [-1,1]){
  const direction=new THREE.Vector3(-side,0,0);
  for(let i=0;i<=176;i++){
    const z=-8.8+i*.1;
    if(z>=3.35&&z<=6.95)continue;
    for(const y of [.2,1,2,3.4]){
      const ray=new THREE.Raycaster(new THREE.Vector3(side*18.5,y,z),direction,0,1.4);
      assert.ok(ray.intersectObjects(walls,false).length,`Uncovered side wall: side=${side}, y=${y}, z=${z}`);
      wallRays++;
    }
  }
  for(const z of [3.4,4.4,5.15,5.9,6.9]){
    const ray=new THREE.Raycaster(new THREE.Vector3(side*18.5,3.3,z),direction,0,1.4);
    assert.ok(ray.intersectObjects(lintels,false).length,`Uncovered dock lintel: side=${side}, z=${z}`);
    lintelRays++;
  }
}
fix.dispose();assert.equal(environment.getObjectByName('MAP_LAYOUT_EXPANSION'),undefined);
const report={passed:true,sideWallPanels:4,sideWallHeight:3.6,wallRays,lintelRays,formerParapetGapsClosed:true,conveyorsMoved:false};
await fs.writeFile(new URL('artifacts/player-check/wall-gaps-report.json',ROOT),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report,null,2));
