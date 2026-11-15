import {createReplay} from './replay.js';

export const DEFAULT_INDEX='http://127.0.0.1:8765/index.json';
const INDEX='robotization-bench.3d-pack-index.v1';
const SHIFT='robotization-bench.replay.v1';
const QUARTER='robotization-bench.quarter-pack.v1';
export class DataError extends Error {
  constructor(file,message){super(`${file}: ${message}`);this.name='DataError';}
}
export function parseDocument(text,file='manifest.json'){
  try{return JSON.parse(text.replace(/^\uFEFF/,''));}
  catch(error){
    const offset=Number(/position (\d+)/.exec(error.message)?.[1]||0);
    const line=text.slice(0,offset).split('\n').length;
    throw new DataError(file,`line ${line}: invalid JSON (${error.message})`);
  }
}
const parent=p=>p.slice(0,p.lastIndexOf('/')+1);
const relative=(base,path)=>{
  if(/^[a-z]+:/i.test(base))return new URL(path,base).href;
  const parts=(parent(base)+path).split('/'),out=[];
  for(const part of parts){if(part==='..'){if(!out.length)throw new DataError(path,'path escapes uploaded folder');out.pop();}else if(part&&part!=='.')out.push(part);}
  return out.join('/');
};
function validateIndex(index,file){
  if(index.pack_format!==INDEX)throw new DataError(file,`unknown pack_format: ${index.pack_format}`);
  if(index.replay_format!==SHIFT)throw new DataError(file,`unknown replay_format: ${index.replay_format}`);
  if(!Array.isArray(index.runs)||!Array.isArray(index.comparisons))throw new DataError(file,'expected runs and comparisons arrays');
  const ids=new Set();
  for(const run of index.runs){
    if(!run.id||ids.has(run.id)||!Number.isInteger(run.seed))throw new DataError(file,'invalid or duplicate run.id / seed');
    if(!['v1','quarterly','v2'].includes(run.mode))throw new DataError(file,`unknown mode ${run.mode}`);
    if(run.mode==='v1'&&!run.manifest)throw new DataError(file,`missing manifest for ${run.id}`);
    if(run.mode!=='v1'&&!run.quarter_manifest)throw new DataError(file,`missing quarter_manifest for ${run.id}`);
    ids.add(run.id);
  }
  for(const pair of index.comparisons){
    const left=index.runs.find(r=>r.id===pair.left),right=index.runs.find(r=>r.id===pair.right);
    if(!left||!right||left.seed!==right.seed||left.seed!==pair.seed)throw new DataError(file,`comparison ${pair.id} must reference two runs with matching seed`);
    if((left.mode==='v1')!==(right.mode==='v1'))throw new DataError(file,`incompatible comparison modes in ${pair.id}`);
  }
  return index;
}
export function validateQuarter(quarter,file){
  if(quarter.replay_pack_format!==QUARTER)throw new DataError(file,`unknown replay_pack_format: ${quarter.replay_pack_format}`);
  if(!Array.isArray(quarter.weeks)||!quarter.weeks.length)throw new DataError(file,'missing weeks array');
  if(quarter.weeks.length>12)throw new DataError(file,'expected at most 12 weeks');
  quarter.weeks.forEach((week,i)=>{
    if(week.week!==undefined&&week.week!==i)throw new DataError(file,`invalid sequence at weeks[${i}]`);
  });
  return quarter;
}
const isJsonPath=p=>typeof p==='string'&&/\.json(?:$|[?#])/i.test(p);
export function normalizeDiagnostics(diag,evaluation=null){
  if(!diag||typeof diag!=='object')return null;
  if(diag.overall&&Array.isArray(diag.timeline_weeks))return diag;
  const qs=diag.overall||diag.quarter_summary||{},ev=evaluation||{};
  const hasFrac=Number.isInteger(ev.reward_num)&&Number.isInteger(ev.reward_den)&&ev.reward_den>0;
  const overall=diag.overall||{
    valid:qs.valid??ev.valid??true,
    feasible:Boolean(qs.feasible??ev.feasible),
    win:Boolean(qs.win??ev.win),
    ...(qs.reward_fraction?{reward_fraction:qs.reward_fraction,reward_float:qs.reward_float??0}:hasFrac?{reward_fraction:`${ev.reward_num}/${ev.reward_den}`,reward_float:ev.reward_num/ev.reward_den}:{}),
    failure_reasons:qs.failure_reasons||qs.reasons||ev.reasons||[],
    headline_summary:qs.headline_summary||qs.headline||'',
  };
  const rawWeeks=Array.isArray(diag.timeline_weeks)?diag.timeline_weeks:Array.isArray(diag.weeks)?diag.weeks:[];
  const timeline_weeks=rawWeeks.map((w,idx)=>({
    ...w,
    week:Number.isInteger(w?.week)?w.week:idx,
    active_mistakes:Array.isArray(w?.active_mistakes)?w.active_mistakes:Array.isArray(w?.issues)?w.issues.map(i=>i?.message).filter(Boolean):[],
    highlight_ticks:Array.isArray(w?.highlight_ticks)?w.highlight_ticks:[],
  }));
  const key_mistakes=Array.isArray(diag.key_mistakes)?diag.key_mistakes:[];
  return {...diag,overall,key_mistakes,timeline_weeks};
}

async function openSource(entry,read,label){
  const document=parseDocument(await read(entry),entry);
  let index;
  if(document.pack_format)index=validateIndex(document,entry);
  else if(document.replay_pack_format){
    validateQuarter(document,entry);
    index={pack_format:INDEX,replay_format:SHIFT,quarterly_available:true,evaluation_seeds:document.evaluation_seeds||[],runs:[{id:'local-quarter',mode:'quarterly',strategy:'local',label:'Local Quarter',seed:document.seed,quarter_manifest:entry}],comparisons:[]};
  }else if(document.replay_format){
    if(document.replay_format!==SHIFT)throw new DataError(entry,`unknown replay_format: ${document.replay_format}`);
    index={pack_format:INDEX,replay_format:SHIFT,quarterly_available:false,evaluation_seeds:[],runs:[{id:'local-shift',mode:'v1',label:'Local Shift',strategy:'local',seed:document.scenario?.seed,manifest:entry}],comparisons:[]};
  }else throw new DataError(entry,'unknown document: expected index.json, manifest.json, or quarter_manifest.json');
  const standalone=!document.pack_format;
  const pathFor=p=>standalone&&p===entry?p:relative(entry,p);
  const cache=new Map(),diagCache=new Map();
  async function json(path){return parseDocument(await read(path),path);}
  async function loadRun(run,{week=0}={}){
    if(typeof run==='string')run=index.runs.find(r=>r.id===run);
    if(!run)throw new DataError(label,'run not found');
    const key=run.id+':'+week;
    if(cache.has(key))return cache.get(key);
    let manifestPath,quarter=null,weekSummary=null,diagnostics=null;
    if(run.mode==='v1')manifestPath=pathFor(run.manifest);
    else{
      const quarterPath=pathFor(run.quarter_manifest);
      quarter=validateQuarter(await json(quarterPath),quarterPath);
      if(!Number.isInteger(week)||week<0||week>=quarter.weeks.length)throw new DataError(quarterPath,`missing week ${week}`);
      weekSummary=quarter.weeks[week];
      manifestPath=relative(quarterPath,(weekSummary.bundle_dir||`weeks/week-${String(week).padStart(2,'0')}`)+'/manifest.json');
      const diagPath=isJsonPath(run.diagnostics)?pathFor(run.diagnostics):isJsonPath(quarter.diagnostics_file)?relative(quarterPath,quarter.diagnostics_file):relative(quarterPath,'diagnostics.json');
      if(diagCache.has(diagPath))diagnostics=diagCache.get(diagPath);
      else{
        try{diagnostics=await json(diagPath);diagCache.set(diagPath,diagnostics);}
        catch(err){if(err?.name==='AbortError')throw err;diagCache.set(diagPath,null);}
      }
      if(!diagnostics)diagnostics=quarter.ai_mistakes_overlay||quarter.diagnostics||null;
      diagnostics=normalizeDiagnostics(diagnostics,run.evaluation||quarter?.evaluation||null);
    }
    const manifest=await json(manifestPath);
    if(manifest.replay_format!==SHIFT)throw new DataError(manifestPath,`unknown replay_format: ${manifest.replay_format}`);
    const eventsPath=relative(manifestPath,manifest.events_file||'events.jsonl');
    const replay=createReplay(manifest,await read(eventsPath),{runId:run.id+(quarter?`:week-${week}`:'')});
    const expectedSeed=quarter?(weekSummary.week_seed??manifest.scenario.seed):run.seed;
    if(manifest.scenario.seed!==expectedSeed)throw new DataError(manifestPath,'shift seed does not match catalog');
    const weekList=diagnostics?.timeline_weeks||diagnostics?.weeks||[];
    const weekDiagnostics=weekList.find(w=>w?.week===week)||(weekList[week]?.week===undefined?weekList[week]:null)||null;
    const result={replay,run,quarter,weekSummary,week,diagnostics,weekDiagnostics,evaluation:run.evaluation||quarter?.evaluation||null,evaluationSeeds:run.evaluation_seeds||index.evaluation_seeds||quarter?.evaluation_seeds||[]};
    cache.set(key,result);return result;
  }
  async function loadComparison(pair,{week=0}={}){
    if(typeof pair==='string')pair=index.comparisons.find(p=>p.id===pair);
    if(!pair)throw new DataError(label,'comparison pair not found');
    const both=await Promise.all([loadRun(pair.left,{week}),loadRun(pair.right,{week})]);
    if(both[0].replay.manifest.scenario.seed!==both[1].replay.manifest.scenario.seed)throw new DataError(pair.id,'comparison seed mismatch');
    if(!both[0].quarter&&JSON.stringify(both[0].replay.manifest.scenario.orders)!==JSON.stringify(both[1].replay.manifest.scenario.orders))throw new DataError(pair.id,'comparison order streams differ');
    return both;
  }
  return {index,label,entry,loadRun,loadComparison};
}

export async function openRemote(url=DEFAULT_INDEX,{signal}={}){
  let entry;
  try{entry=new URL(url);if(!['http:','https:'].includes(entry.protocol))throw new Error('protocol');}
  catch{throw new DataError(url,'expected full HTTP(S) URL');}
  async function read(path){
    let response;
    try{response=await fetch(path,{signal});}
    catch(error){if(error.name==='AbortError')throw error;throw new DataError(path,'bridge unreachable. Start scripts/serve_3d.py or open local files.');}
    if(!response.ok)throw new DataError(path,`HTTP ${response.status}`);
    return response.text();
  }
  return openSource(entry.href,read,entry.host);
}
export async function openLocal(files){
  const list=Array.from(files);
  if(!list.length)throw new DataError('Local files','no files selected');
  const map=new Map(list.map(file=>[(file.webkitRelativePath||file.name).replace(/\\/g,'/'),file]));
  const find=name=>[...map.keys()].filter(p=>p.split('/').at(-1)===name).sort((a,b)=>a.length-b.length)[0];
  const entry=find('index.json')||find('quarter_manifest.json')||find('manifest.json');
  if(!entry)throw new DataError('Local files','expected index.json, quarter_manifest.json, or manifest.json with events.jsonl');
  return openSource(entry,async path=>{
    let file=map.get(path);
    if(!file&&map.has(path.split('/').at(-1))&&[...map.keys()].every(p=>!p.includes('/')))file=map.get(path.split('/').at(-1));
    if(!file)throw new DataError(path,'file not selected. Choose the full pack folder or manifest.json with events.jsonl.');
    return file.text();
  },'Local files');
}
