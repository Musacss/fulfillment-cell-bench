import fs from 'node:fs/promises';
import path from 'node:path';
import validator from 'gltf-validator';

const files=process.argv.slice(2);
if(!files.length)throw new Error('Pass one or more GLB paths');
let failed=false;
const reports=[];
for(const file of files){
  const bytes=new Uint8Array(await fs.readFile(file));
  const result=await validator.validateBytes(bytes,{uri:path.basename(file),maxIssues:200});
  const entry={file:path.basename(file),bytes:bytes.length,errors:result.issues.numErrors,warnings:result.issues.numWarnings,infos:result.issues.numInfos,messages:result.issues.messages};
  reports.push(entry);if(entry.errors)failed=true;
}
console.log(JSON.stringify(reports,null,2));
if(failed)process.exitCode=1;
