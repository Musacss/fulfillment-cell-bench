import './styles.css';
import {openRemote,openLocal,DEFAULT_INDEX} from './data.js';
import {createScenePlayer} from './scene.js';
import {environmentLayers} from '../../4_Horses_Environment_v02/visual/environment-layers.js';

const $=id=>document.getElementById(id);
const html=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const euros=value=>new Intl.NumberFormat('en-US',{style:'currency',currency:'EUR'}).format((value??0)/100);
const number=value=>new Intl.NumberFormat('en-US',{maximumFractionDigits:2}).format(value??0);
const duration=seconds=>[Math.floor(seconds/3600),Math.floor(seconds/60)%60,Math.floor(seconds)%60].map(v=>String(v).padStart(2,'0')).join(':');
const strategy={manual:'Manual Baseline',candidate:'Candidate Plan',reference:'Adaptive Reference',local:'Local Run','naive-route-all':'Naive Route-All'};
const workerStates={idle:'Idle',walk:'Walking',prepare:'Prep',pick:'Picking',pack:'Packing',inspect:'QC Inspect',assist:'Robot Assist',break:'Break',not_purchased:'Not Purchased',disabled:'Bypassed / Off',jammed:'Jammed',helper_walking:'Helper En Route',service:'Clearing Jam',finished:'Finished'};
const importantLabels={jam:'Robot Jam',assist:'Jam Assist',rework:'Rework',break:'Break',escaped:'Escaped Defect',scrap:'Scrap'};
const layerLabels={'ENV_FLOOR_AND_GRID':['Floor & CAD Grid','▦'],'ENV_WALLS_AND_DOCKS':['Walls & Docks','▥'],'ENV_WORKSTATIONS_DETAIL':['Workstations','⌑'],'ENV_ROBOT_CELL':['Robot Cell','◇'],'ENV_BREAK_AREA':['Break & KPI','◷'],'ENV_OVERHEAD':['Overhead Trusses','⌁']};
const costsLabels={depreciation:'Depreciation',service:'Robot Service',shifts:'Shift Wages',overtime:'Overtime',trays:'Trays',materials:'Packing Materials',rework:'Rework',late:'Late Penalties',unfulfilled:'Scrap & Unfulfilled',escaped:'Escaped Defects'};
let source=null,current=[],snapshots=[],mode='single',time=0,playing=false,speed=60,activeInspector=0,requestVersion=0,lastPaint=-1,lastInspector=-1,loading=false,disposed=false;
const players=[null,null],playerPromises=[null,null],panelStats=[{},{}];
const layerState=new Map(environmentLayers),preset='overview';
let cameraPreset=preset;
const query=new URLSearchParams(location.search);
const isLocalHost=['127.0.0.1','localhost','[::1]'].includes(location.hostname);
const defaultCatalogUrl=isLocalHost?DEFAULT_INDEX:new URL('./3d-pack/index.json',document.baseURI).href;
$('bridge-url').value=query.get('index')||defaultCatalogUrl;

function showError(error){
  console.error(error);$('error-message').textContent=error.message||String(error);$('error-panel').hidden=false;
  $('connection-dot').className='dot error';$('connection-text').textContent='Attention required';
}
function connected(label){$('connection-dot').className='dot connected';$('connection-text').textContent=label;$('error-panel').hidden=true;}
function setPlaying(value){playing=Boolean(value)&&current.length>0&&!loading;$('play').firstChild.textContent=playing?'❚❚ ':'▶ ';$('play').querySelector('span').textContent=playing?'Pause':'Play';$('replay-status').classList.toggle('live',playing);paintStatus();}
function paintStatus(){
  $('replay-status').textContent=loading?'Loading…':!current.length?'Awaiting data':time>=maxDuration()?'Shift complete':playing?'● Playing':'Paused';
}
function maxDuration(){return Math.max(0,...current.map(item=>item.replay.durationSeconds));}
function tickSeconds(){return current[0]?.replay.tickSeconds||30;}
function controlState(enabled){for(const id of ['play','reset','next-event','timeline'])$(id).disabled=!enabled;}
function runDisplayName(run){return run.label&&run.label!==run.strategy?run.label:(strategy[run.strategy]||run.label||run.id);}
function runLabel(run){return `${runDisplayName(run)} · seed ${run.seed}`;}
function options(element,entries,label,selected){
  const previous=selected??element.value;element.replaceChildren(...entries.map(entry=>{const option=document.createElement('option');option.value=entry.id;option.textContent=label(entry);return option;}));
  if(entries.some(e=>e.id===previous))element.value=previous;
  element.disabled=!entries.length;
}
function setWeeks(count=12){
  const select=$('week-select'),previous=select.value||'0';select.replaceChildren(...Array.from({length:count},(_,i)=>{const o=document.createElement('option');o.value=String(i);o.textContent=`week-${String(i).padStart(2,'0')} / Week ${i+1}`;return o;}));
  select.value=Number(previous)<count?previous:'0';
}
function updateModeFields(){
  $('single-fields').hidden=mode!=='single';$('comparison-fields').hidden=mode!=='compare';$('quarter-fields').hidden=mode!=='quarter';
  const pair=source?.index.comparisons.find(p=>p.id===$('comparison-select').value);
  $('week-fields').hidden=mode!=='quarter'&&!(mode==='compare'&&pair?.mode!=='v1');
  document.querySelectorAll('[data-mode]').forEach(button=>button.classList.toggle('selected',button.dataset.mode===mode));
  const compare=mode==='compare';$('panel-right').hidden=!compare;$('scene-grid').classList.toggle('comparison',compare);
  document.querySelector('[data-inspector="1"]').hidden=!compare;
  if(!compare)activeInspector=0;
  updateInspectorTabs();requestAnimationFrame(()=>players.forEach(p=>p?.resize()));
}
function updateInspectorTabs(){document.querySelectorAll('[data-inspector]').forEach(b=>b.classList.toggle('selected',Number(b.dataset.inspector)===activeInspector));}
async function ensurePlayer(index){
  if(players[index])return players[index];
  if(!playerPromises[index]){
    const side=index?'right':'left';
    playerPromises[index]=createScenePlayer($('canvas-'+side),{assetBase:new URL('./scene/',document.baseURI).href,onStats:stats=>{panelStats[index]=stats||{};}}).then(player=>{
      players[index]=player;
      for(const [name,visible] of layerState)player.setLayer(name,visible);
      player.setCameraPreset(cameraPreset);$('loading-'+side).hidden=true;player.resize();return player;
    }).catch(error=>{$('loading-'+side).innerHTML='<strong>Failed to load 3D scene</strong><small>See error message for details</small>';playerPromises[index]=null;throw error;});
  }
  return playerPromises[index];
}
async function chooseReplay(){
  if(!source)return;
  const version=++requestVersion;loading=true;setPlaying(false);controlState(false);paintStatus();
  try{
    const week=Number($('week-select').value||0);
    const entries=mode==='compare'?await source.loadComparison($('comparison-select').value,{week}):[await source.loadRun((mode==='quarter'?$('quarter-select'):$('run-select')).value,{week})];
    if(version!==requestVersion)return;
    const ready=await Promise.all(entries.map((_,i)=>ensurePlayer(i)));
    if(version!==requestVersion)return;
    for(let i=0;i<entries.length;i++)await ready[i].setReplay(entries[i].replay);
    if(version!==requestVersion)return;
    current=entries;time=0;lastPaint=-1;lastInspector=-1;loading=false;
    const first=entries[0];if(first.quarter)setWeeks(first.quarter.weeks.length);
    $('seed-tag').textContent='SEED '+first.run.seed;
    $('workspace-title').textContent=entries.length===2?(first.quarter?`Two Plans · Week ${first.week+1} (${first.weekSummary?.label||'Compare'})`:'Two Plans. One Shift.'):first.quarter?`${runDisplayName(first.run)} · Week ${first.week+1}`:runDisplayName(first.run);
    const plan=first.replay.manifest.plan;
    $('plan-summary').innerHTML=[`${plan.workers.length} workers`,plan.robot?'Robot active':'No robot',plan.trays?'With trays':'No trays',`Route: ${plan.route}`].map(s=>`<span class="plan-chip">${html(s)}</span>`).join('');
    entries.forEach((item,index)=>{const side=index?'right':'left';$('scene-label-'+side).textContent=`${entries.length===2?(index?'B / ':'A / '):''}${runDisplayName(item.run)}`;$('scene-info-'+side).textContent=`SEED ${item.run.seed} · ${item.replay.manifest.plan.workers.length} workers`;});
    $('timeline').max=String(Math.max(...entries.map(i=>i.replay.horizonTicks)));
    $('duration').textContent='Horizon '+duration(maxDuration());
    controlState(true);connected(source.label+' · '+source.index.runs.length+' runs');paint(true);paintStatus();
    window.dispatchEvent(new CustomEvent('replay-ready',{detail:{runs:entries.map(i=>i.replay.runId)}}));
  }catch(error){if(version===requestVersion){loading=false;showError(error);controlState(current.length>0);paintStatus();}}
}
async function acceptSource(next){
  source=next;const runs=next.index.runs.filter(r=>r.mode==='v1'),quarters=next.index.runs.filter(r=>r.mode!=='v1');
  options($('run-select'),runs,runLabel,query.get('run')||runs.find(r=>r.strategy==='reference')?.id);
  options($('quarter-select'),quarters,runLabel,query.get('quarter')||quarters.find(r=>r.strategy==='reference'||r.slug==='qwen_grpo')?.id);
  options($('comparison-select'),next.index.comparisons,p=>`${p.mode==='v1'?'Shift':'Quarter'} · seed ${p.seed} / ${p.left.replace(/^(v1|quarterly)-/,'').replace(/-seed\d+$/,'')} → ${p.right.replace(/^(v1|quarterly)-/,'').replace(/-seed\d+$/,'')}`);
  document.querySelector('[data-mode="quarter"]').hidden=!(next.index.quarterly_available||quarters.length);
  document.querySelector('[data-mode="compare"]').disabled=!next.index.comparisons.length;
  const qMode=query.get('mode');
  if(qMode&&['single','compare','quarter'].includes(qMode))mode=qMode;
  if(!runs.length&&quarters.length)mode='quarter';else if(mode==='quarter'&&!quarters.length||mode==='compare'&&!next.index.comparisons.length)mode='single';
  $('source-kind').textContent=next.label==='Local files'?'LOCAL':'BRIDGE';
  setWeeks();updateModeFields();await chooseReplay();
}
async function connect(){
  setPlaying(false);$('connection-text').textContent='Connecting to bridge…';
  try{await acceptSource(await openRemote($('bridge-url').value));}catch(error){showError(error);}
}

function setTime(seconds){time=Math.min(maxDuration(),Math.max(0,Number(seconds)||0));lastPaint=-1;paint(true);if(time>=maxDuration())setPlaying(false);}
function panelBadges(state,index){
  const badges=[];for(const queue of ['Q1','R']){const overflow=Math.max(0,state.queues[queue].length-18);if(overflow)badges.push(`+${overflow} in ${queue}`);}
  if(['jammed','helper_walking','service'].includes(state.robot.state))badges.push(workerStates[state.robot.state]);
  if(state.ended&&state.counters.unfinished)badges.push(`${state.counters.unfinished} unfinished at H`);
  const entry=current[index];
  if(entry?.weekDiagnostics?.status==='critical')badges.push('SLA Alert');
  const node=$('scene-badges-'+(index?'right':'left'));
  const summary=`<span class="canvas-badge summary">Good ${state.counters.good} · Auto ${state.counters.auto_finished}</span>`;
  const markup=summary+badges.map(text=>`<span class="canvas-badge">${html(text)}</span>`).join('');if(node.innerHTML!==markup)node.innerHTML=markup;
}
function paint(force=false){
  if(!current.length)return;
  if(force||time!==lastPaint){
    snapshots=current.map(item=>item.replay.seekTo(Math.min(time,item.replay.durationSeconds)));lastPaint=time;
    const tick=time/tickSeconds();$('clock').textContent=duration(time);$('tick-label').textContent=`Tick ${number(tick)} / ${$('timeline').max}`;$('timeline').value=String(tick);
    snapshots.forEach(panelBadges);
  }
  if(force||lastInspector<0||performance.now()-lastInspector>=160){renderInspector();lastInspector=performance.now();}
}
function renderDiagnostics(entry){
  const diag=entry.diagnostics,wdiag=entry.weekDiagnostics,box=$('diagnostics-summary'),body=$('diagnostics-details');
  if(!diag){box.hidden=true;return;}
  box.hidden=false;
  const ov=diag.overall||{};
  $('diagnostics-badge').textContent=ov.win?'WIN':ov.feasible?'NO WIN':'FAIL';
  const headline=ov.headline_summary||entry.run.diagnostics_headline||'';
  const mistakes=(diag.key_mistakes||[]).slice(0,3);
  const weekNotes=wdiag?.active_mistakes||[];
  const highlights=(wdiag?.highlight_ticks||[]).slice(0,4);
  let out='';
  if(ov.reward_fraction)out+=`<div class="diag-score">Reward: <strong>${html(ov.reward_fraction)}</strong> (${Number(ov.reward_float||0).toFixed(4)})</div>`;
  if(headline)out+=`<p class="diag-headline">${html(headline)}</p>`;
  if(weekNotes.length)out+=`<div class="diag-group"><strong>Week ${entry.week+1} Callouts</strong>${weekNotes.map(m=>`<div class="diag-callout warn">${html(m)}</div>`).join('')}</div>`;
  else if(mistakes.length)out+=`<div class="diag-group"><strong>Quarter Root Causes</strong>${mistakes.map(m=>`<div class="diag-callout ${html(m.severity||'warn')}">${html(m.hud_callout||m.category||'')}</div>`).join('')}</div>`;
  if(highlights.length){
    out+=`<div class="diag-group"><strong>Jump to Highlight Tick</strong><div class="diag-jumps">${highlights.map(h=>{const t=h.focus_tick??h.start_tick??0;return `<button type="button" class="diag-jump" data-seek-tick="${Number(t)}" data-reason="${html(h.reason||h.kind)}">${html(h.kind)} @ t=${Number(t)}</button>`;}).join('')}</div></div>`;
  }
  if(body.innerHTML!==out)body.innerHTML=out;
}
function renderInspector(){
  const entry=current[activeInspector],state=snapshots[activeInspector];if(!entry||!state)return;
  const c=state.counters;
  const cards=[['good',c.good,'Good'],['',c.on_time,'On-Time'],['',state.arrivedCount,'Arrived'],['',state.inSystem,'In System'],['warn',c.escaped,'Escaped'],['warn',c.scrap,'Scrap']];
  $('metrics').innerHTML=cards.map(([cls,value,label])=>`<div class="metric ${cls}"><strong>${number(value)}</strong><span>${label}</span></div>`).join('');
  $('metrics-tick').textContent=number(state.tickFloat??state.tick)+' TICK';
  $('throughput').innerHTML=`Packed: <strong>${c.pack_finished}</strong> / ${c.pack_started} started · auto ${c.auto_finished}<br>Active labor: <strong>${number(c.labor_ticks*entry.replay.tickSeconds/3600)} h</strong> · rework ${c.rework_started}<br>Trays: ${c.trays_used} · pending arrival: ${state.notArrived} · unfinished at H: ${c.unfinished}<br>Overtime per worker: ${c.overtime_ticks.map(number).join(' / ')} ticks`;
  renderDiagnostics(entry);
  $('queue-body').innerHTML=['Q1','Q2','Q3','Q4','R'].map(q=>`<tr><td>${q}</td><td>${state.queues[q].length}</td><td>${state.reserved[q]??'—'}</td><td>${state.capacity?.[q]??'∞'}</td></tr>`).join('');
  const resources=[...Object.values(state.workers),{id:'robot',...state.robot}];
  $('resources').innerHTML=resources.map(w=>`<div class="resource-row"><i class="resource-dot ${w.state==='break'?'break':['jammed','helper_walking','service'].includes(w.state)?'jammed':!['idle','disabled','not_purchased'].includes(w.state)?'busy':''}"></i><strong>${w.id==='robot'?'RBT':html(w.id.toUpperCase())}</strong><span>${html(workerStates[w.state]||w.state)}</span><small>${w.orderId!=null?'#'+w.orderId:w.zone?'Z'+w.zone:''}</small></div>`).join('');
  const economy=entry.replay.manifest.economy;
  $('costs').innerHTML=Object.entries(costsLabels).map(([key,label])=>`<div class="cost-row"><span>${label}</span><strong>${euros(economy.costs[key])}</strong></div>`).join('')+`<div class="cost-row total"><span>Total OpEx</span><strong>${euros(economy.total)}</strong></div>`;
  $('purchase').innerHTML=`<span>Equipment Purchase · CapEx</span><strong>${euros(economy.purchase)}</strong>`;
  const ev=entry.evaluation;
  $('evaluation').innerHTML=ev?`<h3>Evaluation / Seed Suite</h3><div class="seeds">evaluation_seeds: <strong>${entry.evaluationSeeds.length?entry.evaluationSeeds.map(html).join(', '):'not listed'}</strong></div><div class="evaluation-flags">${[['valid','Valid'],['feasible','Feasible'],['win','Win']].map(([key,label])=>`<span class="flag ${ev[key]?'yes':''}">${ev[key]?'✓':'–'} ${label}</span>`).join('')}</div><p>${ev.metrics?`Suite OpEx: ${euros(ev.metrics.total_cost)}<br>Manual Baseline: ${euros(ev.metrics.base_cost)}<br>`:''}Evaluated across the listed seed suite.${ev.reasons?.length?'<br>Reasons: '+ev.reasons.map(html).join(', '):''}</p>`:'<h3>Evaluation</h3><p>Single-shift replay shown above.</p>';
  $('quarter-summary').hidden=!entry.quarter;
  if(entry.quarter){const w=entry.weekSummary,q=entry.quarter;$('quarter-details').innerHTML=[['Quarter / OpEx',euros(q.total_cost)],['Quarter / CapEx',euros(q.purchase)],['Carryover',`${w.carryover_in??0} → ${w.carryover_out??0}`],['Wear',`${w.wear_start??0} → ${w.wear_end??0}`],['Commissioning',w.commissioning_active?'Yes':'No'],['Maintenance',w.maintenance?'Yes':'No']].map(([key,value])=>`<div class="quarter-row"><span>${key}</span><strong>${html(value)}</strong></div>`).join('');}
}

$('diagnostics-details').addEventListener('click',event=>{
  const btn=event.target.closest('[data-seek-tick]');if(!btn||!current.length)return;
  const tick=Number(btn.dataset.seekTick||0);setPlaying(false);setTime(tick*tickSeconds());
  if(btn.dataset.reason)$('event-note').textContent=btn.dataset.reason;
});
$('source-form').addEventListener('submit',event=>{event.preventDefault();connect();});
for(const id of ['local-files','local-folder'])$(id).addEventListener('change',async event=>{try{await acceptSource(await openLocal(event.target.files));}catch(error){showError(error);}finally{event.target.value='';}});
for(const id of ['run-select','comparison-select','quarter-select','week-select'])$(id).addEventListener('change',()=>{updateModeFields();chooseReplay();});
document.querySelectorAll('[data-mode]').forEach(button=>button.addEventListener('click',()=>{if(!source)return;mode=button.dataset.mode;updateModeFields();chooseReplay();}));
document.querySelectorAll('[data-camera]').forEach(button=>button.addEventListener('click',()=>{cameraPreset=button.dataset.camera;players.forEach(player=>player?.setCameraPreset(cameraPreset));document.querySelectorAll('[data-camera]').forEach(b=>b.classList.toggle('selected',b===button));}));
for(const [name,visible] of environmentLayers){
  const row=document.createElement('label');row.className='layer-row';row.innerHTML=`<input type="checkbox" ${visible?'checked':''} data-layer="${name}">${layerLabels[name][0]}<span>${layerLabels[name][1]}</span>`;
  row.querySelector('input').addEventListener('change',event=>{layerState.set(name,event.target.checked);players.forEach(p=>p?.setLayer(name,event.target.checked));$('layer-count').textContent=[...layerState.values()].filter(Boolean).length+' / 6';});$('layers').append(row);
}
$('play').addEventListener('click',()=>{if(time>=maxDuration())setTime(0);setPlaying(!playing);});
$('reset').addEventListener('click',()=>{setPlaying(false);setTime(0);});
$('timeline').addEventListener('input',event=>setTime(Number(event.target.value)*tickSeconds()));
$('speed').addEventListener('change',event=>{speed=Number(event.target.value);});
$('next-event').addEventListener('click',()=>{
  const filter=$('event-filter').value,next=current.flatMap(item=>item.replay.importantEvents.map(event=>({...event,seconds:event.tick*item.replay.tickSeconds}))).filter(event=>event.seconds>time+1e-6&&(filter==='all'||event.kind===filter)).sort((a,b)=>a.seconds-b.seconds)[0];
  setPlaying(false);if(next){setTime(next.seconds);$('event-note').textContent=`${importantLabels[next.kind]} · tick ${next.tick}${next.orderId!=null?' · order #'+next.orderId:''}`;}else{$('event-note').textContent='No further events of this type';}
});
$('error-close').addEventListener('click',()=>$('error-panel').hidden=true);
$('inspector-toggle').addEventListener('click',event=>{const hidden=document.querySelector('.application').classList.toggle('no-inspector');event.currentTarget.setAttribute('aria-expanded',String(!hidden));requestAnimationFrame(()=>players.forEach(p=>p?.resize()));});
document.querySelectorAll('[data-inspector]').forEach(button=>button.addEventListener('click',()=>{activeInspector=Number(button.dataset.inspector);updateInspectorTabs();renderInspector();}));
for(const side of ['left','right'])$('panel-'+side).addEventListener('pointerdown',()=>{if(current.length===2){activeInspector=side==='right'?1:0;updateInspectorTabs();renderInspector();}});
document.addEventListener('keydown',event=>{if(['INPUT','SELECT','TEXTAREA','BUTTON'].includes(event.target.tagName)||!current.length)return;if(event.code==='Space'){event.preventDefault();setPlaying(!playing);}else if(event.key==='ArrowRight')setTime(time+tickSeconds()*(event.ctrlKey?10:1));else if(event.key==='ArrowLeft')setTime(time-tickSeconds()*(event.ctrlKey?10:1));else if(event.key==='Home'){setPlaying(false);setTime(0);}else if(event.key==='End'){setPlaying(false);setTime(maxDuration());}});
let dragDepth=0;document.addEventListener('dragenter',event=>{if(event.dataTransfer.types.includes('Files')){dragDepth++;document.body.classList.add('drop-active');}});document.addEventListener('dragleave',()=>{if(--dragDepth<=0){document.body.classList.remove('drop-active');dragDepth=0;}});document.addEventListener('dragover',event=>event.preventDefault());document.addEventListener('drop',async event=>{event.preventDefault();dragDepth=0;document.body.classList.remove('drop-active');if(event.dataTransfer.files.length){try{await acceptSource(await openLocal(event.dataTransfer.files));}catch(error){showError(error);}}});
window.addEventListener('resize',()=>players.forEach(p=>p?.resize()));
window.addEventListener('beforeunload',()=>{disposed=true;players.forEach(p=>p?.dispose());});
let lastFrame=performance.now();function animate(now){if(disposed)return;const delta=Math.min(.25,(now-lastFrame)/1000);lastFrame=now;if(playing&&!loading){time=Math.min(maxDuration(),time+delta*speed);if(time>=maxDuration())setPlaying(false);}paint();for(let i=0;i<current.length;i++){if(players[i]&&snapshots[i])players[i].render(snapshots[i],{playing,speed,deltaSeconds:delta});}requestAnimationFrame(animate);}requestAnimationFrame(animate);

// A small read-only QA surface: all state is still derived by seekTo, never patched.
window.replayStudio={get source(){return source?.index;},get states(){return snapshots;},get time(){return time;},get mode(){return mode;},seekTo:setTime,pause:()=>setPlaying(false),play:()=>setPlaying(true)};
if(window.innerWidth<1000){document.querySelector('.application').classList.add('no-inspector');$('inspector-toggle').setAttribute('aria-expanded','false');}
setWeeks();ensurePlayer(0).catch(showError);connect();
