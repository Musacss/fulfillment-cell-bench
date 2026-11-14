import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {RoomEnvironment} from 'three/addons/environments/RoomEnvironment.js';
import {
  createActorVisual,createOrderVisualPool,templateClone,hideEnvironmentReplayOrders,sampleWalkPath,
} from '../../4_Horses_Environment_v02/visual/visual-integration.js';
import {
  applyEnvironmentDefaults,setEnvironmentLayer,setRobotAndonState,
} from '../../4_Horses_Environment_v02/visual/environment-layers.js';
import {
  actorPosition,benchPosition,queueStackPositions,outcomeStackPositions,buildWorkerPresentationPlan,
} from './spatial.js';
import {applyMapGeometryFixes} from './map-geometry.js';
import {applyMapFloorFixes} from './map-floor.js';
import {applyMapLayoutExpansion} from './map-layout.js';

const assetCache=new Map();
const PRESETS={
  overview:{eye:[30,26,34],target:[0,.3,0]},
  q1:{eye:[-16,11,8],target:[-8,.6,-2.4]},
  robot:{eye:[10,8,7],target:[3.1,.9,-2.7]},
  qc:{eye:[17,10,8],target:[7.4,.7,-1.2]},
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
        catch(error){throw new Error('Не удалось загрузить 3D-ассет '+file+': '+error.message);}
      }));
      const response=await fetch(base+'visual_bindings.json');
      if(!response.ok)throw new Error('Не найдены привязки visual_bindings.json ('+response.status+')');
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

function createBadge(text,color='#17344c'){
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

export async function createScenePlayer(canvas,{assetBase='/scene/',onStats=()=>{}}={}){
  const bundle=await loadAssets(assetBase,onStats);bundle.refs++;
  const [environmentGLTF,layoutGLTF,templatesGLTF,workerGLTF,robotGLTF]=bundle.models;
  const bindings=bundle.bindings;
  let renderer;
  try{renderer=new THREE.WebGLRenderer({canvas,antialias:true,alpha:false,powerPreference:'high-performance'});}
  catch(error){bundle.refs--;throw new Error('WebGL недоступен: '+error.message);}
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,1.8));
  renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.AgXToneMapping;renderer.toneMappingExposure=1.05;
  renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
  const scene=new THREE.Scene();scene.background=new THREE.Color('#dce2e8');
  const camera=new THREE.PerspectiveCamera(36,1,.25,220);
  const controls=new OrbitControls(camera,canvas);controls.enableDamping=true;controls.dampingFactor=.10;
  controls.minDistance=2.5;controls.maxDistance=160;controls.maxPolarAngle=Math.PI/2-.025;
  let activePreset='overview',fitFactor=1;
  const fitFor=(aspect,preset=activePreset)=>Math.max(1,(preset==='overview'?1.2:.9)/Math.max(.15,aspect));
  const pmrem=new THREE.PMREMGenerator(renderer),room=new RoomEnvironment();
  const environmentMap=pmrem.fromScene(room,.04);scene.environment=environmentMap.texture;scene.environmentIntensity=.7;
  room.dispose();pmrem.dispose();
  scene.add(new THREE.HemisphereLight('#ffffff','#9caebb',1.4));
  const sun=new THREE.DirectionalLight('#fff8ee',3.2);sun.position.set(-5,18,8);sun.castShadow=true;
  sun.shadow.mapSize.set(2048,2048);sun.shadow.camera.left=-20;sun.shadow.camera.right=20;sun.shadow.camera.top=17;sun.shadow.camera.bottom=-17;sun.shadow.camera.near=.5;sun.shadow.camera.far=55;sun.shadow.normalBias=.025;sun.shadow.bias=-.00015;scene.add(sun);
  const fill=new THREE.DirectionalLight('#dce8ff',1.0);fill.position.set(10,10,-8);scene.add(fill);
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
  layout.updateMatrixWorld(true);
  for(const name of [...bindings.stages.flatMap(s=>[s.actor_anchor,s.order_anchor]),bindings.robot.actor_anchor,bindings.robot.order_anchor,bindings.robot.helper_anchor]){
    if(!layout.getObjectByName(name))throw new Error('В visual_layout отсутствует привязка '+name);
  }
  const dynamic=new THREE.Group();dynamic.name='REPLAY_DYNAMIC';scene.add(dynamic);
  const rollers=[];environment.traverse(o=>{if(/^ROLLER_\d\d_\d\d$/.test(o.name))rollers.push({node:o,base:o.quaternion.clone()});});
  const pool=createOrderVisualPool(templatesGLTF.scene),orderViews=new Map(),workerViews=new Map(),benchViews=[];
  const markers=[],badges=[];
  let robotView=null,replay=null,presentation=null,intervals=[],disposed=false,lastMetrics='',metrics={overflow:{Q1:0,R:0},visibleOrders:0};
  const overflowBadges={};
  for(const queue of ['Q1','R']){
    const badge=createBadge('', '#b56809');const p=bindings.queues[queue].origin_gltf_m;
    badge.sprite.position.set(p[0]+.56,p[1]+1.35,p[2]-.21);badge.sprite.visible=false;dynamic.add(badge.sprite);badges.push(badge);overflowBadges[queue]=badge;
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
    controls.target.fromArray(preset.target);fitFactor=fitFor(camera.aspect);
    camera.position.fromArray(preset.eye).sub(controls.target).multiplyScalar(fitFactor).add(controls.target);controls.update();draw();
  }
  function resetReplayObjects(){
    for(const actor of workerViews.values()){actor.view.dispose();actor.badge.dispose();}workerViews.clear();
    robotView?.dispose();robotView=null;pool.dispose();orderViews.clear();
    for(const o of [...benchViews,...markers])o.removeFromParent();benchViews.length=0;markers.length=0;
    for(const badge of badges.slice(2))badge.dispose();badges.splice(2);
    for(const badge of Object.values(overflowBadges))badge.sprite.visible=false;
  }
  function getOrderView(order){
    const id=order.id;let view=orderViews.get(id);
    if(!view){
      const root=pool.getOrCreate({runId:replay.runId,orderId:id,kind:order.kind});dynamic.add(root);
      root.traverse(o=>{if(o.isMesh){o.castShadow=true;o.receiveShadow=true;}});
      view={root,tray:null};orderViews.set(id,view);
    }
    if(order.tray&&!view.tray){view.tray=templateClone(templatesGLTF.scene,'order_tray');view.tray.position.y=-.012;view.root.add(view.tray);}
    if(view.tray)view.tray.visible=Boolean(order.tray);
    return view;
  }
  function placeOrder(order,position){
    const view=getOrderView(order);view.root.visible=true;view.root.position.fromArray(position);view.root.position.y+=order.tray ? .012 : 0;view.root.rotation.set(0,0,0);return view;
  }

  function setReplay(next){
    if(disposed)throw new Error('Scene player disposed');resetReplayObjects();replay=next;
    if(!next){draw();return;}
    presentation=buildWorkerPresentationPlan(next,bindings);intervals=activeIntervals(next);
    Object.keys(presentation.histories).sort(natural).forEach(id=>{
      const view=createActorVisual(workerGLTF,{actorType:'worker',templates:templatesGLTF.scene});
      dynamic.add(view.root);view.root.traverse(o=>{if(o.isMesh)o.castShadow=true;});
      const badge=createBadge(id.toUpperCase());badge.sprite.scale.set(.55,.12,1);badge.sprite.position.set(0,2.28,0);view.root.add(badge.sprite);
      workerViews.set(id,{view,badge});
    });
    robotView=createActorVisual(robotGLTF,{actorType:'robot',templates:templatesGLTF.scene});dynamic.add(robotView.root);
    robotView.root.traverse(o=>{if(o.isMesh)o.castShadow=true;});
    for(const stage of [1,2,3,4])for(let i=1;i<presentation.maxSlots[stage];i++){
      const bench=templateClone(templatesGLTF.scene,'manual_bench');bench.name='PARALLEL_STAGE_'+stage+'_'+i;
      bench.position.fromArray(benchPosition(bindings,stage,i));bench.traverse(o=>{if(o.isMesh){o.castShadow=true;o.receiveShadow=true;}});dynamic.add(bench);benchViews.push(bench);
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
    const rework=createBadge('R → PACK','#8c4a16');rework.sprite.position.set(-.3,1.7,-2.7);rework.sprite.visible=false;dynamic.add(rework.sprite);badges.push(rework);
    presentation.reworkBadge=rework;
    lastMetrics='';
  }

  function activityPlan(id,worker){
    const a=worker.activity||worker.lastActivity;
    return a?presentation.activities.get(id+':'+a.kind+':'+a.startTick):null;
  }
  function cyclesFor(model,clip,seconds){const duration=model.animations.find(c=>c.name===clip)?.duration||2;return Math.max(1,seconds/duration);}
  function render(state,{playing=false,speed=1,deltaSeconds=0}={}){
    if(disposed)return;if(!state||!replay){draw();return;}
    const tick=state.tickFloat??state.timeSeconds/replay.tickSeconds;
    const positions={};let reworkActive=false;
    for(const [id,worker] of Object.entries(state.workers)){
      const actor=workerViews.get(id);if(!actor)continue;
      const plan=activityPlan(id,worker),slot=presentation.slotAt(id,tick);
      let position=plan?[...plan.to]:actorPosition(bindings,slot.stage,slot.index),yaw=Math.PI,visualState=worker.state;
      let phase=0,cycles=1,kind=state.orders[worker.orderId]?.kind||state.orders[worker.activity?.orderId]?.kind||'regular';
      const traveling=plan&&tick>=plan.startTick&&tick<plan.startTick+plan.travelTicks;
      if(traveling){
        const travelPhase=clamp((tick-plan.startTick)/(plan.travelTicks||1));
        const pose=sampleWalkPath(plan.path,travelPhase);position=pose.position;yaw=pose.yaw;visualState='walk';phase=travelPhase;
        cycles=cyclesFor(workerGLTF,'Walk',plan.travelTicks*replay.tickSeconds);
      }else if(worker.activity){
        const a=worker.activity,start=Math.max(a.startTick,plan?a.startTick+plan.travelTicks:a.startTick);
        phase=clamp((tick-start)/Math.max(.001,a.endTick-start));
        const clip={prepare:'Prepare',pick:'Pick',pack:'Pack',inspect:'Inspect',assist:'Assist',break:'Break'}[visualState]||'Idle';
        cycles=cyclesFor(workerGLTF,clip,(a.endTick-start)*replay.tickSeconds);
      }else{
        visualState='idle';phase=(state.timeSeconds%3.2)/3.2;
      }
      if(!['idle','walk','prepare','pick','pack','inspect','assist','break'].includes(visualState))visualState='idle';
      actor.view.sample({state:visualState,phase,cycles,orderKind:kind,position,yaw});
      // Orders remain assigned to this fixed work point during a walk. This
      // map deliberately does not use the animated actor `position` above.
      positions[id]=plan?actorPosition(bindings,plan.stage,plan.index):actorPosition(bindings,slot.stage,slot.index);
      if(worker.activity?.attempt===1&&worker.activity.kind==='work'&&worker.activity.stage===3){reworkActive=true;presentation.reworkBadge.sprite.position.set(positions[id][0],1.75,-2.7);}
    }
    presentation.reworkBadge.sprite.visible=reworkActive;
    const robot=state.robot,robotOrder=state.orders[robot.orderId],robotActivity=robot.activity;
    const robotPhase=robotActivity?clamp((tick-robotActivity.startTick)/Math.max(.001,robotActivity.endTick-robotActivity.startTick)):0;
    robotView.sample({state:robot.state,phase:robotPhase,cycles:1,orderKind:robotOrder?.kind||'regular',position:bindings.robot.position_gltf_m,yaw:bindings.robot.yaw_gltf_rad});
    setRobotAndonState(environment,robot.state);
    for(const view of orderViews.values())view.root.visible=false;
    const overflow={Q1:0,R:0};
    for(const queue of ['Q1','Q2','Q3','Q4','R']){
      const orders=(state.queues[queue]||[]).map(id=>state.orders[id]);
      const stacked=queueStackPositions(bindings,queue,orders);
      stacked.visibleOrders.forEach((order,i)=>placeOrder(order,stacked.positions[i]));
      if(queue==='Q1'||queue==='R'){
        overflow[queue]=stacked.overflow;const badge=overflowBadges[queue];badge.sprite.visible=stacked.overflow>0;badge.update('+'+stacked.overflow+' в '+queue);
      }else{
        const slots=markers[queue]||[],reservations=state.reserved[queue]||0,q=bindings.queues[queue];
        slots.forEach(({empty,reserved},i)=>{
          const position=[q.origin_gltf_m[0]+i%q.columns*q.spacing[0],q.origin_gltf_m[1],q.origin_gltf_m[2]-Math.floor(i/q.columns)*q.spacing[1]];
          empty.position.fromArray(position);reserved.position.fromArray(position);empty.visible=i>=orders.length+reservations;reserved.visible=i>=orders.length&&i<orders.length+reservations;
        });
      }
    }
    for(const order of Object.values(state.orders)){
      if(!order.resource||order.queue||order.status==='not_arrived')continue;
      if(order.resource==='robot'){
        const anchor=layout.getObjectByName(bindings.robot.order_anchor);placeOrder(order,anchor.getWorldPosition(new THREE.Vector3()).toArray());
      }else if(positions[order.resource]){
        const p=positions[order.resource];placeOrder(order,[p[0],.86,p[2]-.34]);
      }
    }
    const terminalOrders={good:[],escaped:[],scrap:[]};
    for(const event of replay.events){
      if(event.tick>state.tick)break;
      if(terminalOrders[event.kind]){const order=state.orders[event.order_id];if(order?.status===event.kind)terminalOrders[event.kind].push(order);}
    }
    for(const outcome of Object.keys(terminalOrders)){
      const stacked=outcomeStackPositions(bindings,outcome,terminalOrders[outcome]);
      stacked.visibleOrders.forEach((order,i)=>placeOrder(order,stacked.positions[i]));
    }
    const activeTicks=intervals.reduce((sum,[a,b])=>sum+Math.max(0,Math.min(tick,b)-a),0);
    const angle=activeTicks*replay.tickSeconds*.38/.025;
    // The exported cylinder's axle is its local Y axis. Euler-X animation
    // would tip the entire roller upright instead of spinning it in place.
    for(const {node,base} of rollers){node.quaternion.copy(base);node.rotateY(angle);}
    const visibleOrders=[...orderViews.values()].filter(o=>o.root.visible).length;
    metrics={overflow,visibleOrders,renderedOrders:visibleOrders,pooledOrders:pool.size,actors:workerViews.size,parallelBenches:benchViews.length,reworkNorth:reworkActive,ended:Boolean(state.ended)};
    const signature=JSON.stringify(metrics);if(signature!==lastMetrics){lastMetrics=signature;onStats(metrics);}
    draw();
  }
  function setLayer(name,visible){setEnvironmentLayer(environment,name,visible);draw();}
  function dispose(){
    if(disposed)return;resetReplayObjects();disposed=true;
    for(const badge of badges)badge.dispose();controls.dispose();
    environment.traverse(o=>{if(o.userData.andonMaterialsOwned)for(const m of Array.isArray(o.material)?o.material:[o.material])m.dispose();});
    mapFloor.dispose();mapLayout.dispose();mapGeometry.dispose();
    environmentMap.dispose();sun.shadow.map?.dispose();renderer.dispose();
    scene.clear();bundle.refs--;if(bundle.refs===0){disposeSourceAssets(bundle);assetCache.delete(bundle.base);}
  }
  const observer=new ResizeObserver(resize);observer.observe(canvas);
  const originalDispose=dispose;
  setCameraPreset('overview');resize();
  return {setReplay,render,resize,setLayer,setCameraPreset,dispose(){observer.disconnect();originalDispose();},get metrics(){return metrics;},getmetrics(){return metrics;},get camera(){return camera;}};
}
