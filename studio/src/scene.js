import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {RoomEnvironment} from 'three/addons/environments/RoomEnvironment.js';
import {
  createActorVisual,createOrderVisualPool,templateClone,hideEnvironmentReplayOrders,sampleWalkPath,
} from '../../4_Horses_Environment_v02/visual/visual-integration.js';
import {
  applyEnvironmentDefaults,setEnvironmentLayer,setRobotAndonState,suppressOverheadStructures,
} from '../../4_Horses_Environment_v02/visual/environment-layers.js';
import {
  actorPosition,benchPosition,stageSlotTransform,robotAssistYaw,queueStackPositions,outcomeStackPositions,scrapStationPositions,buildWorkerPresentationPlan,
} from './spatial.js';
import {applyMapGeometryFixes} from './map-geometry.js';
import {applyMapFloorFixes} from './map-floor.js';
import {applyMapLayoutExpansion} from './map-layout.js';

const assetCache=new Map();
const PRESETS={
  overview:{eye:[30,26,34],target:[0,.3,0]},
  blueprint:{eye:[0,44,.01],target:[0,0,0]},
  q1:{eye:[-16,11,8],target:[-8,.6,-2.4]},
  robot:{eye:[10,8,7],target:[3.1,.9,-2.7]},
  qc:{eye:[17,10,8],target:[7.4,.7,-1.2]},
  rework:{eye:[5.2,9.5,12.8],target:[5.2,.7,6.3]},
  break:{eye:[14,8,0],target:[8.6,1,-6.6]},
};
const clamp=(x,a=0,b=1)=>Math.max(a,Math.min(b,x));
const numberId=id=>Number(String(id).replace(/^w/,''));
const natural=(a,b)=>numberId(a)-numberId(b);

async function loadAssets(assetBase,onProgress){
  const base=assetBase.endsWith('/')?assetBase:assetBase+'/';
  if(!assetCache.has(base)){
    const promise=(async()=>{
      const loader=new GLTFLoader();
      const files=['warehouse_environment.glb','modules/visual_layout.glb','modules/visual_support.glb','modules/warehouse_worker.glb','modules/humanoid_robot.glb'];
      const models=await Promise.all(files.map(async(file,index)=>{
        try{const gltf=await loader.loadAsync(base+file);onProgress?.({loading:file,loadedAsset:index+1});return gltf;}
        catch(error){throw new Error('Failed to load 3D asset '+file+': '+error.message);}
      }));
      const response=await fetch(base+'visual_bindings.json');
      if(!response.ok)throw new Error('Missing visual_bindings.json ('+response.status+')');
      const bindings=await response.json();
      return {base,models,bindings,refs:0};
    })();
    assetCache.set(base,promise);promise.catch(()=>assetCache.delete(base));
  }
  return assetCache.get(base);
}

function disposeSourceAssets(bundle){
  const geometries=new Set(),materials=new Set(),textures=new Set();
  for(const gltf of bundle.models)gltf.scene.traverse(o=>{
    if(o.geometry)geometries.add(o.geometry);
    for(const m of Array.isArray(o.material)?o.material:o.material?[o.material]:[]){materials.add(m);for(const value of Object.values(m))if(value?.isTexture)textures.add(value);}
  });
  for(const t of textures)t.dispose();for(const m of materials)m.dispose();for(const g of geometries)g.dispose();
}

function createBadge(text,color='#333333'){
  const canvas=document.createElement('canvas');canvas.width=512;canvas.height=112;
  const context=canvas.getContext('2d');
  const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;
  const material=new THREE.SpriteMaterial({map:texture,transparent:true,depthTest:false,depthWrite:false});
  const sprite=new THREE.Sprite(material);sprite.scale.set(1.75,.383,1);sprite.renderOrder=20;
  let previous='';
  function update(value){
    if(previous===value)return;previous=value;context.clearRect(0,0,512,112);
    context.fillStyle=color;context.beginPath();context.roundRect(2,2,508,108,18);context.fill();
    context.strokeStyle='rgba(255,255,255,.42)';context.lineWidth=3;context.stroke();
    context.fillStyle='#fff';context.font='600 41px system-ui, sans-serif';context.textAlign='center';context.textBaseline='middle';context.fillText(value,256,57);texture.needsUpdate=true;
  }
  update(text);
  return {sprite,update,dispose(){texture.dispose();material.dispose();sprite.removeFromParent();}};
}

function activeIntervals(replay){
  const jobs=new Map(),segments=[];
  for(const e of replay.events){
    if(e.kind==='start')jobs.set(e.resource,e.tick);
    if(e.kind==='finish'&&jobs.has(e.resource)){segments.push([jobs.get(e.resource),e.tick]);jobs.delete(e.resource);}
  }
  for(const start of jobs.values())segments.push([start,replay.horizonTicks]);
  segments.sort((a,b)=>a[0]-b[0]);const merged=[];
  for(const s of segments){const last=merged.at(-1);if(last&&s[0]<=last[1])last[1]=Math.max(last[1],s[1]);else merged.push([...s]);}
  return merged;
}

export async function createScenePlayer(canvas,{assetBase='/scene/',onStats=()=>{},onSelection=null}={}){
  const bundle=await loadAssets(assetBase,onStats);bundle.refs++;
  const [environmentGLTF,layoutGLTF,templatesGLTF,workerGLTF,robotGLTF]=bundle.models;
  const bindings=bundle.bindings;
  let renderer;
  try{renderer=new THREE.WebGLRenderer({canvas,antialias:true,alpha:false,powerPreference:'high-performance'});}
  catch(error){bundle.refs--;throw new Error('WebGL unavailable: '+error.message);}
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,1.8));
  renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.AgXToneMapping;renderer.toneMappingExposure=1.05;
  renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
  const scene=new THREE.Scene();scene.background=new THREE.Color('#dce2e8');
  const camera=new THREE.PerspectiveCamera(36,1,.25,220);
  const controls=new OrbitControls(camera,canvas);controls.enableDamping=true;controls.dampingFactor=.10;
  controls.minDistance=2.5;controls.maxDistance=160;controls.maxPolarAngle=Math.PI/2-.025;
  let activePreset='overview',fitFactor=1;
  const fitFor=(aspect,preset=activePreset)=>Math.max(1,(preset==='blueprint'?1.35:preset==='overview'?1.2:.9)/Math.max(.15,aspect));
  const pmrem=new THREE.PMREMGenerator(renderer),room=new RoomEnvironment();
  const environmentMap=pmrem.fromScene(room,.04);scene.environment=environmentMap.texture;scene.environmentIntensity=.75;
  room.dispose();pmrem.dispose();
  scene.add(new THREE.HemisphereLight('#ffffff','#9caebb',1.48));
  const sun=new THREE.DirectionalLight('#fff8ee',3.25);sun.position.set(-5,18,8);sun.castShadow=true;
  sun.shadow.mapSize.set(2048,2048);sun.shadow.camera.left=-20;sun.shadow.camera.right=20;sun.shadow.camera.top=17;sun.shadow.camera.bottom=-17;sun.shadow.camera.near=.5;sun.shadow.camera.far=55;sun.shadow.normalBias=.025;sun.shadow.bias=-.00015;scene.add(sun);
  const fill=new THREE.DirectionalLight('#dce8ff',1.05);fill.position.set(10,10,-8);scene.add(fill);
  const environment=environmentGLTF.scene.clone(true),layout=layoutGLTF.scene.clone(true);
  scene.add(environment,layout);hideEnvironmentReplayOrders(environment);applyEnvironmentDefaults(environment);
  // The authored layout contains preview slot outlines. Runtime occupancy
  // replaces those marks, so their coincident faces must not remain visible.
  layout.traverse(o=>{if(/^VIS_QUEUE_Q[234]_OUTLINE_/.test(o.name))o.visible=false;});
  for(const root of [environment,layout])root.traverse(o=>{
    if(o.isMesh){o.castShadow=!o.name.startsWith('ENV_FLOOR_AND_GRID');o.receiveShadow=true;}
  });
  // Instance-local map corrections preserve the frozen GLB buffers, anchors,
  // character clips and replay. Apply decal settings after the shadow defaults.
  const mapGeometry=applyMapGeometryFixes(environment,layout);
  const mapLayout=applyMapLayoutExpansion(environment);
  const mapFloor=applyMapFloorFixes(environment,layout);
  const purgeFloorFlowArrows=()=>{
    const re=/ARROW|CHEVRON|_DASH(?:\b|\d)|(?:DISPATCH|INBOUND|SCRAP)_TRANSFER_|REWORK_RETURN_|SPUR_GUIDE_|SPUR_TRANSFER_GUIDES/i;
    for(const root of [environment,layout])root.traverse(o=>{
      if(/^MAP_WALKWAY_ARROW_/i.test(o.name||'')||/^VIS_(?:Large|Issued)_arrow/i.test(o.name||''))return;
      if(/^(?:DISPATCH_TRANSFER_LANE|INBOUND_TRANSFER_LANE|REWORK_RETURN_LANE|SCRAP_TRANSFER_LANE|SPUR_TRANSFER_GUIDES|MAP_FLOW_CHEVRON_)/i.test(o.name||'')){
        o.visible=false;return;
      }
      if((o.isMesh||o.isLine)&&o.visible&&re.test(o.name||'')){
        const b=new THREE.Box3().setFromObject(o);
        if(!b.isEmpty()&&b.max.y<.08)o.visible=false;
      }
    });
  };
  purgeFloorFlowArrows();
  suppressOverheadStructures(environment);
  suppressOverheadStructures(layout);
  layout.updateMatrixWorld(true);
  for(const name of [...bindings.stages.flatMap(s=>[s.actor_anchor,s.order_anchor]),bindings.robot.actor_anchor,bindings.robot.order_anchor,bindings.robot.helper_anchor]){
    if(!layout.getObjectByName(name))throw new Error('Missing anchor in visual_layout: '+name);
  }
  const robotCellOwnedMaterials=[],robotCellColorEntries=[],standbyTint=new THREE.Color('#5a6d80');
  for(const rootNode of [environment.getObjectByName('ENV_ROBOT_CELL'),layout.getObjectByName('VIS_ROBOT_PACK_TABLE')].filter(Boolean)){
    rootNode.traverse(o=>{
      if(!o.isMesh||/^ANDON_/.test(o.name)||o.userData.andonMaterialsOwned)return;
      const cloned=Array.isArray(o.material)?o.material.map(m=>m.clone()):o.material.clone();
      o.material=cloned;
      for(const mat of Array.isArray(cloned)?cloned:[cloned]){
        robotCellOwnedMaterials.push(mat);
        if(mat.color){
          robotCellColorEntries.push({
            mat,
            baseColor:mat.color.clone(),
            baseEmissive:mat.emissive?mat.emissive.clone():null,
            baseEmissiveIntensity:mat.emissiveIntensity??1,
          });
        }
      }
    });
  }
  const dynamic=new THREE.Group();dynamic.name='REPLAY_DYNAMIC';scene.add(dynamic);
  const rollers=[],rRollers=[];
  environment.traverse(o=>{
    if(/^ROLLER_\d\d_\d\d$/.test(o.name))rollers.push({node:o,base:o.quaternion.clone(),module:Number(o.name.slice(7,9))});
    else if(/^R_ACCUMULATION_ROLLER_\d\d$/.test(o.name))rRollers.push({node:o,base:o.quaternion.clone()});
  });
  const stopperGate=environment.getObjectByName('STOPPER_GATE'),stopperBaseY=stopperGate?stopperGate.position.y:0;
  const pool=createOrderVisualPool(templatesGLTF.scene),orderViews=new Map(),workerViews=new Map(),benchViews=[];
  const markers=[],badges=[],tmpCarryVec=new THREE.Vector3(),tmpRobotOrderVec=new THREE.Vector3(),lastWorkerYaw=new Map();
  let robotView=null,replay=null,presentation=null,intervals=[],disposed=false,lastMetrics='',metrics={overflow:{Q1:0,R:0},visibleOrders:0},lastState=null,selectedEntity=null,lastRenderTimeSeconds=null,robotDimKey='';
  const queueBadges=new Map();
  const selectionGeometry=new THREE.EdgesGeometry(new THREE.BoxGeometry(1,1,1));
  const selectionMaterial=new THREE.LineBasicMaterial({color:'#111111',depthTest:false});
  const selection=new THREE.LineSegments(selectionGeometry,selectionMaterial);selection.visible=false;selection.renderOrder=40;dynamic.add(selection);
  function selectEntity(entity){
    const next=entity&&['worker','robot','queue','order'].includes(entity.type)?{type:entity.type,id:entity.type==='order'?Number(entity.id):String(entity.type==='robot'?'robot':entity.id)}:null;
    const changed=JSON.stringify(next)!==JSON.stringify(selectedEntity);selectedEntity=next;
    if(changed)onSelection?.(next?{...next}:null);
    if(lastState)render(lastState);
  }
  const overflowBadges={};
  for(const queue of ['Q1','R']){
    const badge=createBadge('', '#333333');const p=bindings.queues[queue].origin_gltf_m;
    badge.sprite.position.set(p[0]+.56,p[1]+1.35,p[2]-.21);badge.sprite.visible=false;dynamic.add(badge.sprite);badges.push(badge);overflowBadges[queue]=badge;
  }
  const autoSlotBadge=createBadge('AUTO-SLOT: OFF (AI)','#3b4a59');
  autoSlotBadge.sprite.position.set(3.5,2.08,-2.55);autoSlotBadge.sprite.scale.set(2.15,.44,1);autoSlotBadge.sprite.visible=false;
  dynamic.add(autoSlotBadge.sprite);badges.push(autoSlotBadge);
  const persistentBadgeCount=badges.length;

  function applyRobotCellStandby(standby,label='AUTO-SLOT: OFF (AI)'){
    const key=standby?`dim:${label}`:'active';
    if(key===robotDimKey)return;
    robotDimKey=key;
    for(const entry of robotCellColorEntries){
      if(standby){
        entry.mat.color.copy(entry.baseColor).multiplyScalar(.58).lerp(standbyTint,.28);
        if(entry.mat.emissive){entry.mat.emissive.setRGB(0,0,0);entry.mat.emissiveIntensity=0;}
      }else{
        entry.mat.color.copy(entry.baseColor);
        if(entry.mat.emissive&&entry.baseEmissive){entry.mat.emissive.copy(entry.baseEmissive);entry.mat.emissiveIntensity=entry.baseEmissiveIntensity;}
      }
    }
    autoSlotBadge.sprite.visible=Boolean(standby);
    if(standby)autoSlotBadge.update(label);
  }

  function draw(){if(disposed)return;controls.update();renderer.render(scene,camera);}
  function resize(){
    if(disposed)return;const rect=canvas.getBoundingClientRect(),w=Math.max(1,rect.width),h=Math.max(1,rect.height);
    renderer.setSize(w,h,false);camera.aspect=w/h;
    const nextFit=fitFor(camera.aspect);
    // Scale the user's current orbit offset rather than resetting their view.
    // Narrow comparison panels retain the same horizontal factory coverage.
    camera.position.sub(controls.target).multiplyScalar(nextFit/fitFactor).add(controls.target);
    fitFactor=nextFit;camera.updateProjectionMatrix();draw();
  }
  function setCameraPreset(name){
    activePreset=name==='q1/pick'?'q1':name;
    const preset=PRESETS[activePreset];if(!preset)throw new Error('Unknown camera preset '+name);
    suppressOverheadStructures(environment);
    suppressOverheadStructures(layout);
    controls.target.fromArray(preset.target);fitFactor=fitFor(camera.aspect);
    camera.position.fromArray(preset.eye).sub(controls.target).multiplyScalar(fitFactor).add(controls.target);controls.update();draw();
  }
  function resetReplayObjects(){
    lastState=null;lastRenderTimeSeconds=null;lastWorkerYaw.clear();applyRobotCellStandby(false);robotDimKey='';
    if(selectedEntity&&!disposed)onSelection?.(null);selectedEntity=null;selection.visible=false;queueBadges.clear();
    for(const actor of workerViews.values()){actor.view.dispose();actor.badge.dispose();}workerViews.clear();
    robotView?.dispose();robotView=null;pool.dispose();orderViews.clear();
    for(const o of [...benchViews,...markers])o.removeFromParent();benchViews.length=0;markers.length=0;
    delete markers.Q2;delete markers.Q3;delete markers.Q4;
    for(const badge of badges.slice(persistentBadgeCount))badge.dispose();badges.splice(persistentBadgeCount);
    for(const badge of Object.values(overflowBadges))badge.sprite.visible=false;
    autoSlotBadge.sprite.visible=false;
  }
  function getOrderView(order){
    const id=order.id;let view=orderViews.get(id);
    if(!view){
      const root=pool.getOrCreate({runId:replay.runId,orderId:id,kind:order.kind});root.userData.selectionEntity={type:'order',id};dynamic.add(root);
      const cartonNodes=[...root.children];
      root.traverse(o=>{if(o.isMesh){o.castShadow=true;o.receiveShadow=true;}});
      view={root,cartonNodes,tray:null,scrapBadge:null};orderViews.set(id,view);
    }
    if(order.tray&&!view.tray){view.tray=templateClone(templatesGLTF.scene,'order_tray');view.tray.position.y=-.012;view.root.add(view.tray);}
    if(view.tray)view.tray.visible=Boolean(order.tray);
    return view;
  }
  function placeOrder(order,position,{yaw=0,hideCarton=false,hideTray=false,showTray=undefined,preTrayAdjusted=false,scrapMarker=false}={}){
    const view=getOrderView(order);view.root.visible=true;view.root.position.fromArray(position);
    if(!preTrayAdjusted&&order.tray)view.root.position.y+=.012;
    view.root.rotation.set(0,yaw,0);
    for(const c of view.cartonNodes)c.visible=!hideCarton;
    const wantScrap=(order.status==='scrap'||scrapMarker)&&!hideCarton;
    if(wantScrap&&!view.scrapBadge){
      try{
        view.scrapBadge=templateClone(templatesGLTF.scene,'outcome_scrap');
        const boxH=order.kind==='oversize'?.32:.25;
        view.scrapBadge.position.set(0,boxH+.006,0);
        view.root.add(view.scrapBadge);
      }catch{view.scrapBadge=null;}
    }
    if(view.scrapBadge)view.scrapBadge.visible=Boolean(wantScrap);
    if(view.tray){
      const allowTray=Boolean(order.tray)&&!hideTray&&showTray!==false&&view.root.position.y>=.80;
      view.tray.visible=allowTray;
      if(allowTray)view.tray.position.y=Math.max(-.012,.860-view.root.position.y);
    }
    return view;
  }

  function setReplay(next){
    if(disposed)throw new Error('Scene player disposed');resetReplayObjects();replay=next;
    if(!next){draw();return;}
    presentation=buildWorkerPresentationPlan(next,bindings);intervals=activeIntervals(next);
    Object.keys(presentation.histories).sort(natural).forEach(id=>{
      const view=createActorVisual(workerGLTF,{actorType:'worker',templates:templatesGLTF.scene});
      view.root.userData.selectionEntity={type:'worker',id};
      dynamic.add(view.root);view.root.traverse(o=>{if(o.isMesh)o.castShadow=true;});
      const badge=createBadge(id.toUpperCase());badge.sprite.scale.set(.55,.12,1);badge.sprite.position.set(0,2.28,0);view.root.add(badge.sprite);
      workerViews.set(id,{view,badge});
    });
    robotView=createActorVisual(robotGLTF,{actorType:'robot',templates:templatesGLTF.scene});robotView.root.userData.selectionEntity={type:'robot',id:'robot'};dynamic.add(robotView.root);
    robotView.root.traverse(o=>{if(o.isMesh)o.castShadow=true;});
    for(const stage of [1,2,3,4])for(let i=1;i<presentation.maxSlots[stage];i++){
      const slot=stageSlotTransform(bindings,stage,i);
      const bench=templateClone(templatesGLTF.scene,'manual_bench');bench.name='PARALLEL_STAGE_'+stage+'_'+i;
      bench.position.fromArray(slot.bench);bench.rotation.y=slot.benchRotY;
      bench.traverse(o=>{if(o.isMesh){o.castShadow=true;o.receiveShadow=true;}});dynamic.add(bench);benchViews.push(bench);
    }
    for(const queue of ['Q2','Q3','Q4']){
      const capacity=next.manifest.world.capacity?.[{Q2:'pick',Q3:'pack',Q4:'qc'}[queue]]??bindings.queues[queue].preview_count;
      const entries=[];
      for(let i=0;i<capacity;i++){
        const empty=templateClone(templatesGLTF.scene,'empty_slot'),reserved=templateClone(templatesGLTF.scene,'reserved_slot');
        for(const ob of [empty,reserved]){ob.visible=false;dynamic.add(ob);markers.push(ob);}
        entries.push({empty,reserved});
      }
      markers[queue]=entries;
    }
    for(const [id,queue] of Object.entries(bindings.queues)){
      const badge=createBadge(id),p=queue.origin_gltf_m;
      badge.sprite.position.set(p[0],p[1]+1.1,p[2]-.5);badge.sprite.scale.set(1.25,.274,1);badge.sprite.userData.selectionEntity={type:'queue',id};
      dynamic.add(badge.sprite);badges.push(badge);queueBadges.set(id,badge);
    }
    const rework=createBadge('R → PACK','#333333');rework.sprite.position.set(-.3,1.7,-2.7);rework.sprite.visible=false;dynamic.add(rework.sprite);badges.push(rework);
    presentation.reworkBadge=rework;
    lastMetrics='';
  }

  function activityPlan(id,worker){
    const a=worker.activity||worker.lastActivity;
    return a?presentation.activities.get(id+':'+a.kind+':'+a.startTick):null;
  }
  function cyclesFor(model,clip,seconds){const duration=model.animations.find(c=>c.name===clip)?.duration||2;return Math.max(1,seconds/duration);}
  function render(state,{playing=false,speed=1,deltaSeconds=0}={}){
    if(disposed)return;if(!state||!replay){draw();return;}lastState=state;
    const tick=state.tickFloat??state.timeSeconds/replay.tickSeconds;
    const dtSim=lastRenderTimeSeconds===null?Infinity:Math.abs(state.timeSeconds-lastRenderTimeSeconds);
    const assistYaw=robotAssistYaw(bindings);
    const orderSlots={};let reworkActive=false;
    for(const [id,worker] of Object.entries(state.workers)){
      const actor=workerViews.get(id);if(!actor)continue;
      const plan=activityPlan(id,worker),slot=presentation.slotAt(id,tick);
      const activeSlot=plan&&plan.kind==='work'?stageSlotTransform(bindings,plan.stage,plan.index):stageSlotTransform(bindings,slot.stage,slot.index);
      const fw=state.flow?.workers?.[id];
      if(fw?.reworkBenchOrderPos){
        orderSlots[id]={...activeSlot,actor:[...fw.position],yaw:fw.yaw,order:[...fw.reworkBenchOrderPos],bench:[fw.reworkBenchOrderPos[0],0,6.35],benchRotY:Math.PI};
      }else{
        orderSlots[id]=activeSlot;
      }
      let position,yaw,visualState,phase=0,cycles=1,trayOffset=0,suppressPropCarton=false;
      let orderObj=state.orders[worker.orderId]||state.orders[worker.activity?.orderId]||null;
      if(fw){
        position=[...fw.position];yaw=fw.yaw;visualState=fw.state;phase=fw.phase;suppressPropCarton=Boolean(fw.suppressPropCarton);
        if(fw.orderId!=null&&state.orders[fw.orderId])orderObj=state.orders[fw.orderId];
        trayOffset=(fw.tray||orderObj?.tray)?.012:0;
        if(visualState==='walk'||visualState==='carry_walk'){
          cycles=Math.max(1,Math.round((fw.pathLengthM||1.15)/1.15));
        }else if(visualState==='idle'&&!worker.activity&&fw.phase===0){
          phase=(state.timeSeconds%3.2)/3.2;cycles=1;
        }else if(visualState==='break'){
          const span=worker.activity?worker.activity.endTick-worker.activity.startTick:4;
          cycles=cyclesFor(workerGLTF,'Break',Math.max(2,span*replay.tickSeconds));
        }else if(visualState==='assist'){
          yaw=assistYaw;
          const span=worker.activity?worker.activity.endTick-worker.activity.startTick:4;
          cycles=cyclesFor(workerGLTF,'Assist',Math.max(2,span*replay.tickSeconds));
        }else{
          cycles=1;
        }
      }else{
        position=plan?(plan.kind==='break'&&!worker.activity?[...(plan.returnTo??plan.to)]:[...plan.to]):[...activeSlot.actor];
        yaw=(worker.state==='assist'||(plan&&plan.kind==='assist'&&worker.activity))?assistYaw:(plan&&plan.kind==='break'&&worker.activity)?0:activeSlot.yaw;
        visualState=worker.state;
        trayOffset=orderObj?.tray?.012:0;
        const traveling=plan&&tick>=plan.startTick&&tick<plan.startTick+plan.travelTicks;
        if(traveling){
          const travelPhase=clamp((tick-plan.startTick)/(plan.travelTicks||1));
          const pose=sampleWalkPath(plan.path,travelPhase);position=pose.position;yaw=pose.yaw;visualState='walk';phase=travelPhase;
          cycles=cyclesFor(workerGLTF,'Walk',plan.travelTicks*replay.tickSeconds);
        }else if(worker.activity){
          const a=worker.activity,start=Math.max(a.startTick,plan?a.startTick+plan.travelTicks:a.startTick);
          phase=clamp((tick-start)/Math.max(.001,a.endTick-start));
          if(visualState==='break'||visualState==='assist'){
            const clip=visualState==='break'?'Break':'Assist';
            cycles=cyclesFor(workerGLTF,clip,(a.endTick-start)*replay.tickSeconds);
          }else{
            cycles=1;
          }
        }else{
          visualState='idle';phase=(state.timeSeconds%3.2)/3.2;
        }
      }
      if(lastWorkerYaw.has(id)){
        const prevYaw=lastWorkerYaw.get(id);
        if(dtSim===0){
          yaw=prevYaw;
        }else if(dtSim>0&&dtSim<=1.0){
          const dy=Math.atan2(Math.sin(yaw-prevYaw),Math.cos(yaw-prevYaw));
          if(Math.abs(dy)>.22)yaw=prevYaw+Math.sign(dy)*.22;
        }
      }
      lastWorkerYaw.set(id,yaw);
      if(!['idle','walk','carry_idle','carry_walk','reach','pickup','place_down','prepare','pick','pack','inspect','assist','break'].includes(visualState))visualState='idle';
      actor.view.sample({state:visualState,phase,cycles,orderKind:orderObj?.kind||'regular',position,yaw,trayOffset,suppressPropCarton});
      if((worker.activity?.attempt>=1||fw?.reworkBenchOrderPos)&&worker.activity?.kind==='work'&&worker.activity?.stage===3){
        const bPos=orderSlots[id].bench;
        reworkActive=true;presentation.reworkBadge.sprite.position.set(bPos[0],1.75,bPos[2]);
      }
    }
    presentation.reworkBadge.sprite.visible=reworkActive;
    const robot=state.robot,robotOrder=state.orders[robot.orderId],robotActivity=robot.activity;
    const robotStandby=!replay.manifest.plan.robot||robot.state==='not_purchased'||robot.state==='disabled';
    applyRobotCellStandby(robotStandby,!replay.manifest.plan.robot||robot.state==='not_purchased'?'AUTO-SLOT: OFF (AI)':'AUTO-SLOT: STANDBY');
    const fr=state.flow?.robot;
    const robotOrderKind=robotOrder?.kind||'regular';
    let robotVisualState=robotStandby?robot.state:(fr?fr.state:robot.state);
    let robotPhase=fr?fr.phase:(robotActivity?clamp((tick-robotActivity.startTick)/Math.max(.001,robotActivity.endTick-robotActivity.startTick)):0);
    let robotCycles=1;
    if(robotStandby){
      robotPhase=(state.timeSeconds%4.0)/4.0;
    }else if(robotVisualState==='idle'&&!robotActivity){
      robotPhase=(state.timeSeconds%3.6)/3.6;
    }else if(robotVisualState==='jammed'||robotVisualState==='helper_walking'){
      const jamSpan=Math.max(2,((robot.assistEndTick??(tick+4))-(robot.jamTick??tick))*replay.tickSeconds);
      robotCycles=cyclesFor(robotGLTF,robotOrderKind==='oversize'?'Jammed_Oversize':'Jammed',jamSpan);
    }else if(robotVisualState==='service'){
      const svcSpan=Math.max(2,((robot.assistEndTick??(tick+4))-(robot.jamTick??tick))*replay.tickSeconds);
      robotCycles=cyclesFor(robotGLTF,robotOrderKind==='oversize'?'Service_Oversize':'Service',svcSpan);
    }
    const robotTrayOffset=(fr?.tray||robotOrder?.tray)?.012:0;
    robotView.sample({state:robotVisualState,phase:robotPhase,cycles:robotCycles,orderKind:robotOrderKind,position:bindings.robot.position_gltf_m,yaw:bindings.robot.yaw_gltf_rad,trayOffset:robotTrayOffset});
    setRobotAndonState(environment,robotStandby?'off':robot.state);
    for(const view of orderViews.values())view.root.visible=false;
    const inTransitIds=new Set();
    for(const tr of state.flow?.transits||[]){
      const order=state.orders[tr.orderId];
      if(!order||order.status==='not_arrived')continue;
      inTransitIds.add(order.id);
      const carrier=tr.actorId?workerViews.get(tr.actorId):null;
      const activeProp=Boolean(carrier?.view.current?.activeCartonProp&&!tr.suppressPropCarton);
      let pos=tr.position,preTrayAdjusted=tr.trayAdjusted!==false,yaw=tr.yaw;
      if(carrier&&!carrier.view.hasOperationalProps&&(tr.mode==='carry'||tr.mode==='pickup'||tr.mode==='place_down')){
        carrier.view.carryPoint(tmpCarryVec);
        yaw=carrier.view.root.rotation.y+Math.PI;
        if(tr.mode==='carry'){
          pos=[tmpCarryVec.x,tmpCarryVec.y,tmpCarryVec.z];preTrayAdjusted=false;
        }else if(tr.mode==='pickup'){
          const u=tr.phase;
          pos=[pos[0]*(1-u)+tmpCarryVec.x*u,pos[1]*(1-u)+tmpCarryVec.y*u,pos[2]*(1-u)+tmpCarryVec.z*u];
          preTrayAdjusted=true;
        }else{
          const u=tr.phase;
          pos=[tmpCarryVec.x*(1-u)+pos[0]*u,tmpCarryVec.y*(1-u)+pos[1]*u,tmpCarryVec.z*(1-u)+pos[2]*u];
          preTrayAdjusted=true;
        }
      }
      const suppressTray=Boolean(tr.hideTray)||tr.showTray===false;
      placeOrder(order,pos,{yaw,hideCarton:activeProp,hideTray:suppressTray,showTray:tr.showTray,preTrayAdjusted,scrapMarker:Boolean(tr.scrapBadged)});
    }
    const overflow={Q1:0,R:0};
    for(const queue of ['Q1','Q2','Q3','Q4','R']){
      const orders=(state.queues[queue]||[]).map(id=>state.orders[id]);
      const stacked=queueStackPositions(bindings,queue,orders);
      stacked.visibleOrders.forEach((order,i)=>{if(!inTransitIds.has(order.id))placeOrder(order,stacked.positions[i]);});
      if(queue==='Q1'||queue==='R'){
        overflow[queue]=stacked.overflow;const badge=overflowBadges[queue];badge.sprite.visible=stacked.overflow>0;badge.update('+'+stacked.overflow+' in '+queue);
      }else{
        const slots=markers[queue]||[],reservations=state.reserved[queue]||0,q=bindings.queues[queue];
        slots.forEach(({empty,reserved},i)=>{
          const position=[q.origin_gltf_m[0]+i%q.columns*q.spacing[0],q.origin_gltf_m[1],q.origin_gltf_m[2]-Math.floor(i/q.columns)*q.spacing[1]];
          empty.position.fromArray(position);reserved.position.fromArray(position);empty.visible=i>=orders.length+reservations;reserved.visible=i>=orders.length&&i<orders.length+reservations;
        });
      }
    }
    for(const order of Object.values(state.orders)){
      if(!order.resource||order.queue||order.status==='not_arrived'||inTransitIds.has(order.id))continue;
      if(order.resource==='robot'){
        const anchor=layout.getObjectByName(bindings.robot.order_anchor);
        const hideCarton=Boolean(robotView?.current?.activeCartonProp);
        placeOrder(order,anchor.getWorldPosition(tmpRobotOrderVec).toArray(),{yaw:0,hideCarton,hideTray:false});
      }else if(orderSlots[order.resource]){
        const wActor=workerViews.get(order.resource),s=orderSlots[order.resource];
        const rwOrderPos=state.flow?.reworkOrderPos?.[order.id]||s.order;
        const hideCarton=Boolean(wActor?.view.current?.activeCartonProp);
        placeOrder(order,rwOrderPos,{yaw:s.benchRotY,hideCarton,hideTray:false,preTrayAdjusted:Boolean(state.flow?.reworkOrderPos?.[order.id])});
      }
    }
    const terminalOrders={good:[],escaped:[],scrap:[]};
    for(const event of replay.events){
      if(event.tick>state.tick)break;
      if(terminalOrders[event.kind]){const order=state.orders[event.order_id];if(order?.status===event.kind)terminalOrders[event.kind].push(order);}
    }
    for(const outcome of Object.keys(terminalOrders)){
      const stacked=outcome==='scrap'
        ?scrapStationPositions(bindings,terminalOrders.scrap)
        :outcomeStackPositions(bindings,outcome,terminalOrders[outcome]);
      stacked.visibleOrders.forEach((order,i)=>{if(!inTransitIds.has(order.id))placeOrder(order,stacked.positions[i],{scrapMarker:outcome==='scrap'});});
    }
    const rollerAngles=state.flow?.rollerAnglesRad;
    if(rollerAngles){
      for(const {node,base,module} of rollers){node.quaternion.copy(base);node.rotateY(rollerAngles[module-1]||0);}
      const rAngle=state.flow.rRollerAngleRad||0;
      for(const {node,base} of rRollers){node.quaternion.copy(base);node.rotateY(rAngle);}
    }else{
      const activeTicks=intervals.reduce((sum,[a,b])=>sum+Math.max(0,Math.min(tick,b)-a),0);
      const angle=activeTicks*replay.tickSeconds*.38/.025;
      for(const {node,base} of rollers){node.quaternion.copy(base);node.rotateY(angle);}
    }
    if(stopperGate)stopperGate.position.y=stopperBaseY+(state.flow?.qcPortal?.stopperLiftM||0);
    for(const [id,badge] of queueBadges)badge.update(`${id} · ${state.queues[id]?.length??0}`);
    let selectedRoot=null,selectedQueue=null;
    if(selectedEntity?.type==='worker')selectedRoot=workerViews.get(selectedEntity.id)?.view.root;
    if(selectedEntity?.type==='robot'&&state.robot.state!=='not_purchased')selectedRoot=robotView.root;
    if(selectedEntity?.type==='order')selectedRoot=orderViews.get(selectedEntity.id)?.root;
    if(selectedEntity?.type==='queue')selectedQueue=bindings.queues[selectedEntity.id]?.origin_gltf_m;
    selection.visible=!!selectedQueue||!!selectedRoot?.visible;
    if(selectedQueue){selection.position.fromArray(selectedQueue);selection.position.y+=.1;selection.scale.set(2,.15,1.6);}
    else if(selectedRoot?.visible){selection.position.copy(selectedRoot.position);const actor=selectedEntity.type!=='order';selection.position.y+=actor?1:.2;selection.scale.set(actor?1:.6,actor?2:.4,actor?1:.5);}
    const visibleOrders=[...orderViews.values()].filter(o=>o.root.visible).length;
    metrics={overflow,visibleOrders,renderedOrders:visibleOrders,inTransitOrders:inTransitIds.size,activeConveyorModules:state.flow?.activeModules?.length||0,pooledOrders:pool.size,actors:workerViews.size,parallelBenches:benchViews.length,reworkNorth:reworkActive,autoSlotStandby:robotStandby,ended:Boolean(state.ended)};
    const signature=JSON.stringify(metrics);if(signature!==lastMetrics){lastMetrics=signature;onStats(metrics);}
    lastRenderTimeSeconds=state.timeSeconds;
    draw();
  }
  function setLayer(name,visible){
    setEnvironmentLayer(environment,name,visible);
    purgeFloorFlowArrows();
    suppressOverheadStructures(layout);
    draw();
  }
  const raycaster=new THREE.Raycaster(),pointer=new THREE.Vector2();let pointerStart=null;
  const pointerDown=event=>{pointerStart=event.button===0?[event.clientX,event.clientY,event.pointerId]:null;};
  const pointerMove=event=>{if(pointerStart&&event.pointerId===pointerStart[2]&&Math.hypot(event.clientX-pointerStart[0],event.clientY-pointerStart[1])>5)pointerStart=null;};
  const pointerCancel=()=>{pointerStart=null;};
  const pointerUp=event=>{
    const start=pointerStart;pointerStart=null;if(!start||event.button!==0||event.pointerId!==start[2]||Math.hypot(event.clientX-start[0],event.clientY-start[1])>5)return;
    const rect=canvas.getBoundingClientRect();pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);raycaster.setFromCamera(pointer,camera);
    const candidates=[...orderViews.values()].filter(v=>v.root.visible).map(v=>v.root);
    for(const worker of workerViews.values())if(worker.view.root.visible)candidates.push(worker.view.root);
    if(robotView?.root.visible&&lastState?.robot.state!=='not_purchased')candidates.push(robotView.root);
    for(const badge of queueBadges.values())if(badge.sprite.visible)candidates.push(badge.sprite);
    let entity=null;for(const hit of raycaster.intersectObjects(candidates,true)){for(let p=hit.object;p;p=p.parent)if(p.userData.selectionEntity){entity=p.userData.selectionEntity;break;}if(entity)break;}
    selectEntity(entity);
  };
  canvas.addEventListener('pointerdown',pointerDown);canvas.addEventListener('pointermove',pointerMove);canvas.addEventListener('pointerup',pointerUp);canvas.addEventListener('pointercancel',pointerCancel);
  function dispose(){
    if(disposed)return;disposed=true;resetReplayObjects();
    canvas.removeEventListener('pointerdown',pointerDown);canvas.removeEventListener('pointermove',pointerMove);canvas.removeEventListener('pointerup',pointerUp);canvas.removeEventListener('pointercancel',pointerCancel);selectionGeometry.dispose();selectionMaterial.dispose();
    for(const badge of badges)badge.dispose();controls.dispose();
    for(const mat of robotCellOwnedMaterials)mat.dispose();
    environment.traverse(o=>{if(o.userData.andonMaterialsOwned)for(const m of Array.isArray(o.material)?o.material:[o.material])m.dispose();});
    mapFloor.dispose();mapLayout.dispose();mapGeometry.dispose();
    environmentMap.dispose();sun.shadow.map?.dispose();renderer.dispose();
    scene.clear();bundle.refs--;if(bundle.refs===0){disposeSourceAssets(bundle);assetCache.delete(bundle.base);}
  }
  const observer=new ResizeObserver(resize);observer.observe(canvas);
  const originalDispose=dispose;
  setCameraPreset('overview');resize();
  return {setReplay,render,resize,setLayer,setCameraPreset,selectEntity,clearSelection(){selectEntity(null);},selectOrder(id){selectEntity(id==null?null:{type:'order',id});},get selectedEntity(){return selectedEntity?{...selectedEntity}:null;},dispose(){observer.disconnect();originalDispose();},get metrics(){return metrics;},getmetrics(){return metrics;},get camera(){return camera;},get scene(){return scene;}};
}
