import './styles.css';
import {openRemote,openLocal,DEFAULT_INDEX} from './data.js';
import {createScenePlayer} from './scene.js';
import {environmentLayers} from '../../4_Horses_Environment_v02/visual/environment-layers.js';

const $=id=>document.getElementById(id);
const html=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const euros=value=>new Intl.NumberFormat('ru-RU',{style:'currency',currency:'EUR'}).format((value??0)/100);
const number=value=>new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(value??0);
const duration=seconds=>[Math.floor(seconds/3600),Math.floor(seconds/60)%60,Math.floor(seconds)%60].map(v=>String(v).padStart(2,'0')).join(':');
const strategy={manual:'Ручной план',candidate:'Кандидат',reference:'Контрольная стратегия',local:'Локальный прогон'};
const STAGE_CODES={1:'01 PREP',2:'02 PICK',3:'03 PACK',4:'04 QC'};
const workerStates={idle:'Ожидание',walk:'Переход',prepare:'Подготовка',pick:'Комплектация',pack:'Упаковка',inspect:'Контроль',assist:'Помощь роботу',break:'Перерыв',not_purchased:'Авто-слот: выкл (решение ИИ)',disabled:'Авто-слот: резерв',jammed:'Застревание',helper_walking:'Помощник идёт',service:'Обслуживание',finished:'Завершено'};
const importantLabels={jam:'Застревание',assist:'Помощь',rework:'Переделка',break:'Перерыв',escaped:'Выдан брак',scrap:'Списание'};
const layerLabels={'ENV_FLOOR_AND_GRID':['Пол и CAD-сетка','▦'],'ENV_WALLS_AND_DOCKS':['Стены и доки','▥'],'ENV_WORKSTATIONS_DETAIL':['Оснастка постов','⌑'],'ENV_ROBOT_CELL':['Ячейка робота','◇'],'ENV_BREAK_AREA':['Отдых и KPI','◷']};
const costsLabels={depreciation:'Амортизация',service:'Обслуживание робота',shifts:'Оплата смен',overtime:'Сверхурочные',trays:'Лотки',materials:'Упаковочные материалы',rework:'Переделка',late:'Опоздания',unfulfilled:'Брак и незавершённые',escaped:'Выданный брак'};

let source=null,current=[],snapshots=[],mode='single',time=0,playing=false,speed=15,activeInspector=0,requestVersion=0,lastPaint=-1,lastInspector=-1,loading=false,disposed=false;
const players=[null,null],playerPromises=[null,null],panelStats=[{},{}];
const layerState=new Map(environmentLayers.map(([name,visible])=>[name,name==='ENV_OVERHEAD'?false:visible]));
let cameraPreset='overview';
const query=new URLSearchParams(location.search);
const isLocalHost=['127.0.0.1','localhost','[::1]'].includes(location.hostname);
const defaultCatalogUrl=isLocalHost?DEFAULT_INDEX:new URL('./3d-pack/index.json',document.baseURI).href;
$('bridge-url').value=query.get('index')||defaultCatalogUrl;

const speedSelect=()=>$('speed-select')||$('speed');
const ensureBlueprintButton=()=>{
  const grid=$('camera-presets')||document.querySelector('.camera-grid');
  if(!grid||grid.querySelector('[data-camera="blueprint"]'))return;
  const btn=document.createElement('button');
  btn.type='button';btn.dataset.camera='blueprint';btn.style.gridColumn='span 2';btn.textContent='⊞ Чертёж сверху';
  const first=grid.firstElementChild;
  if(first)first.insertAdjacentElement('afterend',btn);else grid.append(btn);
};
ensureBlueprintButton();
if(speedSelect()){
  const sel=speedSelect();
  if(![...sel.options].some(o=>o.value==='15')){
    const opt=new Option('15×','15',true,true);
    sel.insertBefore(opt,sel.options[2]||null);
  }
  sel.value='15';
}

function displayRunName(run){
  if(!run)return 'Локальный прогон';
  if(run.label&&run.label!==run.strategy)return run.label;
  return strategy[run.strategy]||run.label||run.id||'Локальный прогон';
}
function runLabel(run){return `${displayRunName(run)} · seed ${run.seed}`;}
function plannedStageAllocation(plan){
  const counts={1:0,2:0,3:0,4:0};
  for(const zones of plan?.workers||[]){
    const primary=zones?.[0];
    if(counts[primary]!==undefined)counts[primary]++;
  }
  return `01 PREP:${counts[1]} · 02 PICK:${counts[2]} · 03 PACK:${counts[3]} · 04 QC:${counts[4]}`;
}
function liveStageCounts(state){
  const counts={1:0,2:0,3:0,4:0};
  for(const w of Object.values(state?.workers||{})){
    if(counts[w.zone]!==undefined)counts[w.zone]++;
  }
  return counts;
}
function autoSlotLabel(plan,robotState){
  if(!plan?.robot||robotState==='not_purchased')return 'Авто-слот: выкл (решение ИИ)';
  if(plan.route==='manual'||robotState==='disabled')return 'Авто-слот: резерв (ручной маршрут)';
  return 'Авто-слот: активен';
}

function showError(error){
  console.error(error);$('error-message').textContent=error.message||String(error);$('error-panel').hidden=false;
  $('connection-dot').className='dot error';$('connection-text').textContent='Требуется внимание';
}
function connected(label){$('connection-dot').className='dot connected';$('connection-text').textContent=label;$('error-panel').hidden=true;}
function setPlaying(value){playing=Boolean(value)&&current.length>0&&!loading;$('play').firstChild.textContent=playing?'❚❚ ':'▶ ';$('play').querySelector('span').textContent=playing?'Пауза':'Воспроизвести';$('replay-status').classList.toggle('live',playing);paintStatus();}
function paintStatus(){
  $('replay-status').textContent=loading?'Загрузка…':!current.length?'Ожидание данных':time>=maxDuration()?'Смена завершена':playing?'● Воспроизведение':'На паузе';
}
function maxDuration(){return Math.max(0,...current.map(item=>item.replay.durationSeconds));}
function tickSeconds(){return current[0]?.replay.tickSeconds||30;}
function controlState(enabled){for(const id of ['play','reset','next-event','timeline'])$(id).disabled=!enabled;}
function options(element,entries,label,selected){
  const previous=selected??element.value;element.replaceChildren(...entries.map(entry=>{const option=document.createElement('option');option.value=entry.id;option.textContent=label(entry);return option;}));
  if(entries.some(e=>e.id===previous))element.value=previous;
  element.disabled=!entries.length;
}
function setWeeks(count=12){
  const select=$('week-select'),previous=select.value||'0';select.replaceChildren(...Array.from({length:count},(_,i)=>{const o=document.createElement('option');o.value=String(i);o.textContent=`week-${String(i).padStart(2,'0')} / неделя ${i+1}`;return o;}));
  select.value=Number(previous)<count?previous:'0';
}
function setCameraPreset(name){
  cameraPreset=name;
  players.forEach(player=>player?.setCameraPreset(cameraPreset));
  document.querySelectorAll('[data-camera]').forEach(b=>b.classList.toggle('selected',b.dataset.camera===cameraPreset));
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
      for(const [name,visible] of layerState)player.setLayer(name,name==='ENV_OVERHEAD'?false:visible);
      player.setCameraPreset(cameraPreset);$('loading-'+side).hidden=true;player.resize();return player;
    }).catch(error=>{$('loading-'+side).innerHTML='<strong>Не удалось загрузить 3D-сцену</strong><small>Подробности в сообщении об ошибке</small>';playerPromises[index]=null;throw error;});
  }
  return playerPromises[index];
}
function renderPlanSummary(entry){
  if(!entry)return;
  const plan=entry.replay.manifest.plan;
  const chips=[
    `${plan.workers.length} чел. (${plannedStageAllocation(plan)})`,
    autoSlotLabel(plan,plan.robot?(plan.route==='manual'?'disabled':'idle'):'not_purchased'),
    plan.trays?'С лотками':'Без лотков',
    `Маршрут: ${plan.route}`,
  ];
  $('plan-summary').innerHTML=chips.map(s=>`<span class="plan-chip">${html(s)}</span>`).join('');
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
    $('workspace-title').textContent=entries.length===2?'Два плана. Одна смена.':first.quarter?`Квартал · неделя ${first.week+1} · ${displayRunName(first.run)}`:displayRunName(first.run);
    renderPlanSummary(entries[activeInspector]||first);
    entries.forEach((item,index)=>{
      const side=index?'right':'left',plan=item.replay.manifest.plan;
      $('scene-label-'+side).textContent=`${entries.length===2?(index?'B / ':'A / '):''}${displayRunName(item.run)}`;
      $('scene-info-'+side).textContent=`SEED ${item.run.seed} · ${plan.workers.length} чел. · ${plan.robot?'авто-слот ВКЛ':'авто-слот ВЫКЛ'}`;
    });
    $('timeline').max=String(Math.max(...entries.map(i=>i.replay.horizonTicks)));
    $('duration').textContent='Горизонт '+duration(maxDuration());
    controlState(true);connected(source.label+' · '+source.index.runs.length+' прогонов');paint(true);paintStatus();
    window.dispatchEvent(new CustomEvent('replay-ready',{detail:{runs:entries.map(i=>i.replay.runId)}}));
  }catch(error){if(version===requestVersion){loading=false;showError(error);controlState(current.length>0);paintStatus();}}
}
async function acceptSource(next){
  source=next;const runs=next.index.runs.filter(r=>r.mode==='v1'),quarters=next.index.runs.filter(r=>r.mode!=='v1');
  options($('run-select'),runs,runLabel,query.get('run')||runs.find(r=>r.strategy==='reference')?.id);
  options($('quarter-select'),quarters,runLabel);
  options($('comparison-select'),next.index.comparisons,p=>{
    const leftRun=next.index.runs.find(r=>r.id===p.left);
    const rightRun=next.index.runs.find(r=>r.id===p.right);
    const leftLabel=leftRun?displayRunName(leftRun):(leftRun?.label||leftRun?.strategy||p.left);
    const rightLabel=rightRun?displayRunName(rightRun):(rightRun?.label||rightRun?.strategy||p.right);
    return `${p.mode==='v1'?'Смена':'Квартал'} · seed ${p.seed} / ${leftLabel} → ${rightLabel}`;
  });
  document.querySelector('[data-mode="quarter"]').hidden=!(next.index.quarterly_available||quarters.length);
  document.querySelector('[data-mode="compare"]').disabled=!next.index.comparisons.length;
  if(!runs.length&&quarters.length)mode='quarter';else if(mode==='quarter'&&!quarters.length||mode==='compare'&&!next.index.comparisons.length)mode='single';
  $('source-kind').textContent=next.label==='Локальные файлы'?'LOCAL':'BRIDGE';
  setWeeks();updateModeFields();await chooseReplay();
}
async function connect(){
  setPlaying(false);$('connection-text').textContent='Подключение к мосту…';
  try{await acceptSource(await openRemote($('bridge-url').value));}catch(error){showError(error);}
}

function setTime(seconds){time=Math.min(maxDuration(),Math.max(0,Number(seconds)||0));lastPaint=-1;paint(true);if(time>=maxDuration())setPlaying(false);}
function panelBadges(state,index){
  const entry=current[index],plan=entry?.replay.manifest.plan;
  const zc=liveStageCounts(state);
  const badges=[
    autoSlotLabel(plan,state.robot.state),
    `Посты 01:${zc[1]} · 02:${zc[2]} · 03:${zc[3]} · 04:${zc[4]}`,
  ];
  for(const queue of ['Q1','R']){const overflow=Math.max(0,state.queues[queue].length-18);if(overflow)badges.push(`+${overflow} в ${queue}`);}
  if(['jammed','helper_walking','service'].includes(state.robot.state))badges.push(workerStates[state.robot.state]);
  if(state.ended&&state.counters.unfinished)badges.push(`${state.counters.unfinished} незавершённых на H`);
  const node=$('scene-badges-'+(index?'right':'left'));
  const summary=`<span class="canvas-badge summary">Годных ${state.counters.good} · авто ${state.counters.auto_finished}</span>`;
  const markup=summary+badges.map(text=>`<span class="canvas-badge">${html(text)}</span>`).join('');if(node.innerHTML!==markup)node.innerHTML=markup;
}
function paint(force=false){
  if(!current.length)return;
  if(force||time!==lastPaint){
    snapshots=current.map(item=>item.replay.seekTo(Math.min(time,item.replay.durationSeconds)));lastPaint=time;
    const tick=time/tickSeconds();$('clock').textContent=duration(time);$('tick-label').textContent=`Тик ${number(tick)} / ${$('timeline').max}`;$('timeline').value=String(tick);
    snapshots.forEach(panelBadges);
  }
  if(force||lastInspector<0||performance.now()-lastInspector>=160){renderInspector();lastInspector=performance.now();}
}
function renderInspector(){
  const entry=current[activeInspector],state=snapshots[activeInspector];if(!entry||!state)return;
  renderPlanSummary(entry);
  const c=state.counters,plan=entry.replay.manifest.plan,zc=liveStageCounts(state);
  const cards=[['good',c.good,'Годных'],['',c.on_time,'Вовремя'],['',state.arrivedCount,'Поступило'],['',state.inSystem,'В системе'],['warn',c.escaped,'Выдан брак'],['warn',c.scrap,'Списано']];
  $('metrics').innerHTML=cards.map(([cls,value,label])=>`<div class="metric ${cls}"><strong>${number(value)}</strong><span>${label}</span></div>`).join('');
  $('metrics-tick').textContent=number(state.tickFloat??state.tick)+' TICK';
  $('throughput').innerHTML=`Упаковок: <strong>${c.pack_finished}</strong> / ${c.pack_started} начато · авто ${c.auto_finished}<br>Активный труд: <strong>${number(c.labor_ticks*entry.replay.tickSeconds/3600)} ч</strong> · переделок ${c.rework_started}<br>Лотков: ${c.trays_used} · ещё не поступило: ${state.notArrived} · незавершено на H: ${c.unfinished}<br>Сверхурочные по людям: ${c.overtime_ticks.map(number).join(' / ')} тик.`;
  $('queue-body').innerHTML=['Q1','Q2','Q3','Q4','R'].map(q=>`<tr><td>${q}</td><td>${state.queues[q].length}</td><td>${state.reserved[q]??'—'}</td><td>${state.capacity?.[q]??'∞'}</td></tr>`).join('');
  const stageHeader=`<div class="resource-row"><strong>ИИ · ${Object.keys(state.workers).length} ЧЕЛ.</strong><span>01:${zc[1]} · 02:${zc[2]} · 03:${zc[3]} · 04:${zc[4]}</span><small>${html(autoSlotLabel(plan,state.robot.state))}</small></div>`;
  const resources=[...Object.values(state.workers),{id:'robot',...state.robot}];
  $('resources').innerHTML=stageHeader+resources.map(w=>`<div class="resource-row"><i class="resource-dot ${w.state==='break'?'break':['jammed','helper_walking','service'].includes(w.state)?'jammed':!['idle','disabled','not_purchased'].includes(w.state)?'busy':''}"></i><strong>${w.id==='robot'?'RBT':html(w.id.toUpperCase())}</strong><span>${html(w.id==='robot'?autoSlotLabel(plan,w.state)+' · '+(workerStates[w.state]||w.state):(workerStates[w.state]||w.state))}</span><small>${w.orderId!=null?'#'+w.orderId:w.zone?(STAGE_CODES[w.zone]||'Z'+w.zone):''}</small></div>`).join('');
  const economy=entry.replay.manifest.economy;
  $('costs').innerHTML=Object.entries(costsLabels).map(([key,label])=>`<div class="cost-row"><span>${label}</span><strong>${euros(economy.costs[key])}</strong></div>`).join('')+`<div class="cost-row total"><span>Всего OpEx</span><strong>${euros(economy.total)}</strong></div>`;
  $('purchase').innerHTML=`<span>Покупка оборудования · CapEx</span><strong>${euros(economy.purchase)}</strong>`;
  const ev=entry.evaluation;
  $('evaluation').innerHTML=ev?`<h3>Evaluation / набор дней</h3><div class="seeds">evaluation_seeds: <strong>${entry.evaluationSeeds.length?entry.evaluationSeeds.map(html).join(', '):'не указаны в файле'}</strong></div><div class="evaluation-flags">${[['valid','План корректен'],['feasible','Ограничения'],['win','Победа']].map(([key,label])=>`<span class="flag ${ev[key]?'yes':''}">${ev[key]?'✓':'–'} ${label}</span>`).join('')}</div><p>${ev.metrics?`Расходы набора: ${euros(ev.metrics.total_cost)}<br>Базовый план: ${euros(ev.metrics.base_cost)}<br>`:''}Оценка относится к перечисленному набору дней.${ev.reasons?.length?'<br>Причины: '+ev.reasons.map(reason=>html({cost:'расходы',labor:'труд',automation:'доля автоматизации',budget:'бюджет'}[reason]||reason)).join(', '):''}</p>`:'<h3>Evaluation</h3><p>В этом пакете нет оценки набора дней. Итог одной смены показан выше.</p>';
  $('quarter-summary').hidden=!entry.quarter;
  if(entry.quarter){const w=entry.weekSummary,q=entry.quarter;$('quarter-details').innerHTML=[['Квартал / расходы',euros(q.total_cost)],['Квартал / CapEx',euros(q.purchase)],['Перенос заказов',`${w.carryover_in??0} → ${w.carryover_out??0}`],['Износ',`${w.wear_start??0} → ${w.wear_end??0}`],['Ввод в эксплуатацию',w.commissioning_active?'Да':'Нет'],['Обслуживание',w.maintenance?'Да':'Нет']].map(([key,value])=>`<div class="quarter-row"><span>${key}</span><strong>${html(value)}</strong></div>`).join('');}
}

$('source-form').addEventListener('submit',event=>{event.preventDefault();connect();});
for(const id of ['local-files','local-folder'])$(id).addEventListener('change',async event=>{try{await acceptSource(await openLocal(event.target.files));}catch(error){showError(error);}finally{event.target.value='';}});
for(const id of ['run-select','comparison-select','quarter-select','week-select'])$(id).addEventListener('change',()=>{updateModeFields();chooseReplay();});
document.querySelectorAll('[data-mode]').forEach(button=>button.addEventListener('click',()=>{if(!source)return;mode=button.dataset.mode;updateModeFields();chooseReplay();}));
document.querySelectorAll('[data-camera]').forEach(button=>button.addEventListener('click',()=>setCameraPreset(button.dataset.camera)));
const visibleLayerEntries=environmentLayers.filter(([name])=>name!=='ENV_OVERHEAD'&&layerLabels[name]);
const refreshLayerCount=()=>{
  const activeCount=visibleLayerEntries.filter(([name])=>layerState.get(name)).length;
  $('layer-count').textContent=`${activeCount} / ${visibleLayerEntries.length}`;
};
for(const [name,visible] of visibleLayerEntries){
  const row=document.createElement('label');row.className='layer-row';row.innerHTML=`<input type="checkbox" ${visible?'checked':''} data-layer="${name}">${layerLabels[name][0]}<span>${layerLabels[name][1]}</span>`;
  row.querySelector('input').addEventListener('change',event=>{layerState.set(name,event.target.checked);players.forEach(p=>p?.setLayer(name,event.target.checked));refreshLayerCount();});$('layers').append(row);
}
refreshLayerCount();
$('play').addEventListener('click',()=>{if(time>=maxDuration())setTime(0);setPlaying(!playing);});
$('reset').addEventListener('click',()=>{setPlaying(false);setTime(0);});
$('timeline').addEventListener('input',event=>setTime(Number(event.target.value)*tickSeconds()));
speedSelect()?.addEventListener('change',event=>{speed=Number(event.target.value)||15;});
$('event-filter').addEventListener('change',event=>{
  const v=event.target.value;
  if((v==='rework'||v==='scrap')&&cameraPreset!=='blueprint'&&cameraPreset!=='rework')setCameraPreset('rework');
});
$('next-event').addEventListener('click',()=>{
  const filter=$('event-filter').value,next=current.flatMap(item=>item.replay.importantEvents.map(event=>({...event,seconds:event.tick*item.replay.tickSeconds}))).filter(event=>event.seconds>time+1e-6&&(filter==='all'||event.kind===filter)).sort((a,b)=>a.seconds-b.seconds)[0];
  setPlaying(false);if(next){
    if((next.kind==='rework'||next.kind==='scrap')&&cameraPreset!=='blueprint'&&cameraPreset!=='rework')setCameraPreset('rework');
    setTime(next.seconds);$('event-note').textContent=`${importantLabels[next.kind]} · тик ${next.tick}${next.orderId!=null?' · заказ #'+next.orderId:''}`;
  }else{$('event-note').textContent='Следующих событий этого типа нет';}
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
window.replayStudio={get source(){return source?.index;},get states(){return snapshots;},get time(){return time;},get speed(){return speed;},get mode(){return mode;},get cameraPreset(){return cameraPreset;},get stats(){return panelStats;},get players(){return players;},seekTo:setTime,pause:()=>setPlaying(false),play:()=>setPlaying(true),setCameraPreset};
if(window.innerWidth<1000){document.querySelector('.application').classList.add('no-inspector');$('inspector-toggle').setAttribute('aria-expanded','false');}
setWeeks();ensurePlayer(0).catch(showError);connect();
