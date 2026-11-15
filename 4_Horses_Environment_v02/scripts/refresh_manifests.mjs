// Read shipped GLBs and refresh metadata; never mutate assets or bindings.
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
const root=new URL('../',import.meta.url);
const readJSON=async file=>JSON.parse(await fs.readFile(new URL(file,root),'utf8'));
const writeJSON=async(file,value)=>fs.writeFile(new URL(file,root),JSON.stringify(value,null,2)+'\n');
const clean=v=>Math.abs(v)<1e-7?0:+v.toFixed(8);
const record=b=>({min:b.min.toArray().map(clean),max:b.max.toArray().map(clean),size:b.getSize(new THREE.Vector3()).toArray().map(clean)});
const nativeBounds=b=>record(new THREE.Box3(new THREE.Vector3(b.min.x,-b.max.z,b.min.y),new THREE.Vector3(b.max.x,-b.min.z,b.max.y)));
function triangles(p,j){const n=j.accessors[p.indices??p.attributes.POSITION].count,m=p.mode??4;return m===4?n/3:m===5||m===6?Math.max(0,n-2):0;}
function demonstration(o){for(let p=o;p;p=p.parent)if(p.userData.handling_prop||/_Demo(Carton|Support)/.test(p.name))return true;return false;}
function objectBounds(scene,character=false){scene.updateMatrixWorld(true);const b=new THREE.Box3();scene.traverse(o=>{if(o.isMesh&&(!character||!demonstration(o)))b.union(new THREE.Box3().setFromObject(o,true));});assert.ok(!b.isEmpty());return b;}
async function readModel(file){
 const bytes=await fs.readFile(new URL(file,root));assert.equal(bytes.toString('utf8',0,4),'glTF');
 const json=JSON.parse(bytes.subarray(20,20+bytes.readUInt32LE(12)).toString('utf8'));
 const model=await new Promise((resolve,reject)=>new GLTFLoader().parse(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),'',resolve,reject));
 const accessors=new Set((json.meshes??[]).flatMap(m=>m.primitives.map(p=>p.attributes.POSITION)));
 let instanceTriangles=0,instances=0;model.scene.traverse(o=>{if(o.isMesh){instances++;instanceTriangles+=(o.geometry.index?.count??o.geometry.attributes.position.count)/3;}});
 const box=objectBounds(model.scene);
 return {file,json,model,box,stats:{file,bytes:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex'),nodes:json.nodes?.length??0,mesh_definitions:json.meshes?.length??0,mesh_primitives:(json.meshes??[]).reduce((s,m)=>s+m.primitives.length,0),mesh_instances:instances,geometry_vertices:[...accessors].reduce((s,i)=>s+json.accessors[i].count,0),mesh_definition_triangles:(json.meshes??[]).reduce((s,m)=>s+m.primitives.reduce((a,p)=>a+triangles(p,json),0),0),scene_instance_triangles:instanceTriangles,materials:json.materials?.length??0,textures:json.textures?.length??0,images:json.images?.length??0,skins:json.skins?.length??0,bones:[...new Set((json.skins??[]).flatMap(s=>s.joints))].length,animation_clips:(json.animations??[]).map(a=>a.name),bounds_gltf_y_up_m:record(box),bounds_blender_z_up_m:nativeBounds(box)}};
}
const modules=(await fs.readdir(new URL('modules/',root))).filter(f=>f.endsWith('.glb')).sort();
const models=await Promise.all(['warehouse_environment.glb',...modules.map(f=>'modules/'+f)].map(readModel));assert.equal(models.length,15);
const byFile=new Map(models.map(m=>[m.file,m]));
const oldRoot=await readJSON('asset_manifest.json'),oldConfig=await readJSON('config/asset_manifest.json');
const entries=new Map(oldConfig.map(e=>[e.id,{...e}]));for(const e of oldRoot)entries.set(e.id,{...(entries.get(e.id)??{}),...e});
const manifest=[];
for(const file of modules){
 const id=file.replace(/\.glb$/,''),a=byFile.get('modules/'+file),e=entries.get(id)??{id,file:'modules/'+file,origin:'root-local'},character=['warehouse_worker','humanoid_robot'].includes(id),b=nativeBounds(character?objectBounds(a.model.scene,true):a.box);
 Object.assign(e,{file:'modules/'+file,bounds_min_m:b.min,bounds_max_m:b.max,actual_envelope_m:b.size,bounds_coordinate_system:'Blender Z-up'});
 if('editable_parts' in e||!character&&!['visual_support','visual_layout'].includes(id))e.editable_parts=(a.json.nodes?.length??0)-(a.json.scenes?.[a.json.scene??0]?.nodes?.length??0);
 if(character)Object.assign(e,{rigged:true,bones:a.stats.bones,clips:a.stats.animation_clips});
 if(id==='carton_open')e.purpose='Separate catalog asset; no carton embedded in active environment work areas';
 manifest.push(e);
}
await writeJSON('asset_manifest.json',manifest);await writeJSON('config/asset_manifest.json',manifest);
const w=byFile.get('modules/warehouse_worker.glb'),bodyNode=w.json.nodes.find(n=>n.name==='WORKER_Body'),helmetNode=w.json.nodes.find(n=>n.name==='WORKER_Helmet');assert.ok(bodyNode&&helmetNode);
const body=w.json.meshes[bodyNode.mesh],helmet=w.json.meshes[helmetNode.mesh];
const bodyTriangles=body.primitives.reduce((s,p)=>s+triangles(p,w.json),0),helmetTriangles=helmet.primitives.reduce((s,p)=>s+triangles(p,w.json),0);assert.equal(bodyTriangles,3480);assert.equal(helmetTriangles,256);
const workerMaterials=new Set([...body.primitives,...helmet.primitives].map(p=>p.material));assert.equal(workerMaterials.size,12);
const workerNative=nativeBounds(objectBounds(w.model.scene,true)),worker=await readJSON('worker_manifest.json');
Object.assign(worker,{version:'2.0.0',height_rest_m:+workerNative.max[2].toFixed(6),triangles:bodyTriangles+helmetTriangles,authored_vertices:1976+130,materials:workerMaterials.size,bounds_blender_rest_m:workerNative,clothing:['blue long sleeve work shirt','bright yellow reflective safety vest','silver reflective bands','dark gray cargo trousers','protective gloves','safety boots','yellow safety helmet weighted to existing head bone']});assert.ok(Math.abs(worker.height_rest_m-1.944)<1e-6);
// Native authored counts: unchanged1976-vertex body plus130-vertex closed helmet.
// Exported render vertices are measured separately from POSITION accessors.
await writeJSON('worker_manifest.json',worker);await writeJSON('config/characters/warehouse_worker.json',worker);
const environment=byFile.get('warehouse_environment.glb').model.scene,anchors=await readJSON('anchors.json');let refreshed=0;
for(const a of anchors.anchors){const n=environment.getObjectByName(a.id);assert.ok(n,'Missing environment anchor '+a.id);a.position_m=n.getWorldPosition(new THREE.Vector3()).toArray().map(clean);if(n.userData.role)a.role=n.userData.role;if(n.userData.clearance){const c=n.userData.clearance;a.clearance_xyz_m=[c[0],c[2],c[1]];}refreshed++;}
await writeJSON('anchors.json',anchors);await writeJSON('config/anchors.exported.json',anchors);
await writeJSON('asset_stats_v02.json',{format:'four-horses.asset-stats.v02',units:'meters',measurement_source:'Actual shipped GLBs parsed by Three.js GLTFLoader0.170.0; geometry_vertices count exported POSITION accessors, not native authoring vertices',files:models.map(m=>m.stats),totals:{glb_files:models.length,bytes:models.reduce((s,m)=>s+m.stats.bytes,0),textures:models.reduce((s,m)=>s+m.stats.textures,0),images:models.reduce((s,m)=>s+m.stats.images,0)},worker_authored_geometry:{body_triangles:bodyTriangles,helmet_triangles:helmetTriangles,body_authored_vertices:1976,helmet_authored_vertices:130,total_authored_vertices:2106,materials:workerMaterials.size},refreshed_environment_anchors:refreshed});
console.log(JSON.stringify({refreshed_manifests:2,module_assets:manifest.length,glb_files:models.length,worker_triangles:worker.triangles,worker_authored_vertices:worker.authored_vertices,worker_materials:worker.materials,worker_height_m:worker.height_rest_m,environment_anchors:refreshed,environment_bytes:models[0].stats.bytes},null,2));
