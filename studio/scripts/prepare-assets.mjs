import fs from 'node:fs/promises';
import {createHash} from 'node:crypto';
const repo=new URL('../../',import.meta.url),out=new URL('../public/scene/',import.meta.url);
const hashes=JSON.parse(await fs.readFile(new URL('asset-hashes.json',new URL('../',import.meta.url))));
for(const [name,expected] of Object.entries(hashes)){
  const bytes=await fs.readFile(new URL(name,repo));
  if(createHash('sha256').update(bytes).digest('hex')!==expected.sha256)throw new Error(`Original GLB changed: ${name}`);
}
for(const name of ['warehouse_environment.glb','modules/visual_layout.glb','modules/visual_support.glb','modules/warehouse_worker.glb','modules/humanoid_robot.glb','visual_bindings.json','anchors.json']){
  const dest=new URL(name,out);await fs.mkdir(new URL('./',dest),{recursive:true});
  await fs.copyFile(new URL('4_Horses_Environment_v02/'+name,repo),dest);
}
console.log('Scene v02: 15 original GLB hashes verified; player assets copied.');
