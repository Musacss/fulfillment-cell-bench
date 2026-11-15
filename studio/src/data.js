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
    throw new DataError(file,`строка ${line}: неверный JSON (${error.message})`);
  }
}
const parent=p=>p.slice(0,p.lastIndexOf('/')+1);
const relative=(base,path)=>{
  if(/^[a-z]+:/i.test(base))return new URL(path,base).href;
  const parts=(parent(base)+path).split('/'),out=[];
  for(const part of parts){if(part==='..'){if(!out.length)throw new DataError(path,'путь выходит за загруженную папку');out.pop();}else if(part&&part!=='.')out.push(part);}
  return out.join('/');
};
function validateIndex(index,file){
  if(index.pack_format!==INDEX)throw new DataError(file,`неизвестный pack_format: ${index.pack_format}`);
  if(index.replay_format!==SHIFT)throw new DataError(file,`неизвестный replay_format: ${index.replay_format}`);
  if(!Array.isArray(index.runs)||!Array.isArray(index.comparisons))throw new DataError(file,'ожидаются runs и comparisons');
  const ids=new Set();
  for(const run of index.runs){
    if(!run.id||ids.has(run.id)||!Number.isInteger(run.seed))throw new DataError(file,'неверный или повторяющийся run.id / seed');
    if(!['v1','quarterly','v2'].includes(run.mode))throw new DataError(file,`неизвестный режим ${run.mode}`);
    if(run.mode==='v1'&&!run.manifest)throw new DataError(file,`у ${run.id} нет manifest`);
    if(run.mode!=='v1'&&!run.quarter_manifest)throw new DataError(file,`у ${run.id} нет quarter_manifest`);
    ids.add(run.id);
  }
  for(const pair of index.comparisons){
    const left=index.runs.find(r=>r.id===pair.left),right=index.runs.find(r=>r.id===pair.right);
    if(!left||!right||left.seed!==right.seed||left.seed!==pair.seed)throw new DataError(file,`сравнение ${pair.id} должно ссылаться на два прогона одного seed`);
    if((left.mode==='v1')!==(right.mode==='v1'))throw new DataError(file,`несовместимые режимы сравнения ${pair.id}`);
  }
  return index;
}
export function validateQuarter(quarter,file){
  if(quarter.replay_pack_format!==QUARTER)throw new DataError(file,`неизвестный replay_pack_format: ${quarter.replay_pack_format}`);
  if(!Array.isArray(quarter.weeks)||!quarter.weeks.length)throw new DataError(file,'нет списка weeks');
  if(quarter.weeks.length>12)throw new DataError(file,'ожидается не более 12 недель');
  quarter.weeks.forEach((week,i)=>{
    if(week.week!==undefined&&week.week!==i)throw new DataError(file,`неверная последовательность weeks[${i}]`);
  });
  return quarter;
}

async function openSource(entry,read,label){
  const document=parseDocument(await read(entry),entry);
  let index;
  if(document.pack_format)index=validateIndex(document,entry);
  else if(document.replay_pack_format){
    validateQuarter(document,entry);
    index={pack_format:INDEX,replay_format:SHIFT,quarterly_available:true,evaluation_seeds:document.evaluation_seeds||[],runs:[{id:'local-quarter',mode:'quarterly',strategy:'local',label:'Локальный квартал',seed:document.seed,quarter_manifest:entry}],comparisons:[]};
  }else if(document.replay_format){
    if(document.replay_format!==SHIFT)throw new DataError(entry,`неизвестный replay_format: ${document.replay_format}`);
    index={pack_format:INDEX,replay_format:SHIFT,quarterly_available:false,evaluation_seeds:[],runs:[{id:'local-shift',mode:'v1',label:'Локальная смена',strategy:'local',seed:document.scenario?.seed,manifest:entry}],comparisons:[]};
  }else throw new DataError(entry,'неизвестный документ: нужен index.json, manifest.json или quarter_manifest.json');
  const standalone=!document.pack_format;
  const pathFor=p=>standalone&&p===entry?p:relative(entry,p);
  const cache=new Map();
  async function json(path){return parseDocument(await read(path),path);}
  async function loadRun(run,{week=0}={}){
    if(typeof run==='string')run=index.runs.find(r=>r.id===run);
    if(!run)throw new DataError(label,'прогон не найден');
    const key=run.id+':'+week;
    if(cache.has(key))return cache.get(key);
    let manifestPath,quarter=null,weekSummary=null;
    if(run.mode==='v1')manifestPath=pathFor(run.manifest);
    else{
      const quarterPath=pathFor(run.quarter_manifest);
      quarter=validateQuarter(await json(quarterPath),quarterPath);
      if(!Number.isInteger(week)||week<0||week>=quarter.weeks.length)throw new DataError(quarterPath,`нет недели ${week}`);
      weekSummary=quarter.weeks[week];
      manifestPath=relative(quarterPath,(weekSummary.bundle_dir||`weeks/week-${String(week).padStart(2,'0')}`)+'/manifest.json');
    }
    const manifest=await json(manifestPath);
    if(manifest.replay_format!==SHIFT)throw new DataError(manifestPath,`неизвестный replay_format: ${manifest.replay_format}`);
    const eventsPath=relative(manifestPath,manifest.events_file||'events.jsonl');
    const replay=createReplay(manifest,await read(eventsPath),{runId:run.id+(quarter?`:week-${week}`:'')});
    const expectedSeed=quarter?(weekSummary.week_seed??manifest.scenario.seed):run.seed;
    if(manifest.scenario.seed!==expectedSeed)throw new DataError(manifestPath,'seed смены не совпадает с каталогом');
    const result={replay,run,quarter,weekSummary,week,evaluation:run.evaluation||quarter?.evaluation||null,evaluationSeeds:run.evaluation_seeds||index.evaluation_seeds||quarter?.evaluation_seeds||[]};
    cache.set(key,result);return result;
  }
  async function loadComparison(pair,{week=0}={}){
    if(typeof pair==='string')pair=index.comparisons.find(p=>p.id===pair);
    if(!pair)throw new DataError(label,'пара сравнения не найдена');
    const both=await Promise.all([loadRun(pair.left,{week}),loadRun(pair.right,{week})]);
    if(both[0].replay.manifest.scenario.seed!==both[1].replay.manifest.scenario.seed)throw new DataError(pair.id,'seed сравнения не совпадает');
    if(!both[0].quarter&&JSON.stringify(both[0].replay.manifest.scenario.orders)!==JSON.stringify(both[1].replay.manifest.scenario.orders))throw new DataError(pair.id,'потоки заказов сравнения различаются');
    return both;
  }
  return {index,label,entry,loadRun,loadComparison};
}

export async function openRemote(url=DEFAULT_INDEX,{signal}={}){
  let entry;
  try{entry=new URL(url);if(!['http:','https:'].includes(entry.protocol))throw new Error('protocol');}
  catch{throw new DataError(url,'нужен полный HTTP(S) URL файла');}
  async function read(path){
    let response;
    try{response=await fetch(path,{signal});}
    catch(error){if(error.name==='AbortError')throw error;throw new DataError(path,'мост недоступен. Запустите scripts/serve_3d.py или откройте локальные файлы.');}
    if(!response.ok)throw new DataError(path,`HTTP ${response.status}`);
    return response.text();
  }
  return openSource(entry.href,read,entry.host);
}
export async function openLocal(files){
  const list=Array.from(files);
  if(!list.length)throw new DataError('Локальные файлы','ничего не выбрано');
  const map=new Map(list.map(file=>[(file.webkitRelativePath||file.name).replace(/\\/g,'/'),file]));
  const find=name=>[...map.keys()].filter(p=>p.split('/').at(-1)===name).sort((a,b)=>a.length-b.length)[0];
  const entry=find('index.json')||find('quarter_manifest.json')||find('manifest.json');
  if(!entry)throw new DataError('Локальные файлы','нужен index.json, quarter_manifest.json или manifest.json вместе с events.jsonl');
  return openSource(entry,async path=>{
    let file=map.get(path);
    if(!file&&map.has(path.split('/').at(-1))&&[...map.keys()].every(p=>!p.includes('/')))file=map.get(path.split('/').at(-1));
    if(!file)throw new DataError(path,'файл не выбран. Выберите всю папку пакета или manifest.json вместе с events.jsonl.');
    return file.text();
  },'Локальные файлы');
}
