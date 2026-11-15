import fs from 'node:fs/promises';
import {createHash} from 'node:crypto';
const repo=new URL('../../',import.meta.url),out=new URL('../public/scene/',import.meta.url);
const hashes=JSON.parse(await fs.readFile(new URL('asset-hashes.json',new URL('../',import.meta.url))));
for(const [name,expected] of Object.entries(hashes)){
  const bytes=await fs.readFile(new URL(name,repo));
  if(createHash('sha256').update(bytes).digest('hex')!==expected.sha256)throw new Error(`Original GLB changed: ${name}`);
}
const glbRelNames=Object.keys(hashes).map(k=>k.replace(/^4_Horses_Environment_v02\//,''));
for(const name of [...glbRelNames,'visual_bindings.json','anchors.json','workshop_chain.json']){
  const src=new URL('4_Horses_Environment_v02/'+name,repo);
  try{await fs.access(src);}catch{if(name==='workshop_chain.json')continue;throw new Error(`Missing source asset: ${name}`);}
  const dest=new URL(name,out);await fs.mkdir(new URL('./',dest),{recursive:true});
  await fs.copyFile(src,dest);
}
console.log('Scene v02: 15 original GLB hashes verified; player assets copied.');
