import assert from 'node:assert/strict';
import { replaySnapshot, DEMO } from '../dist/assets/replay.js';

let minClearance=Infinity, holds=0, visibleTransitions=0;
let previous=null;
for(let k=0;k<=10000;k++){
  const time=k*.01,s=replaySnapshot(time);
  const parcels=s.parcels.filter(p=>p.visible).sort((a,b)=>a.x-b.x);
  for(let i=1;i<parcels.length;i++){
    const clearance=parcels[i].x-parcels[i-1].x-.4;
    minClearance=Math.min(minClearance,clearance);
    assert.ok(clearance>=0,`Intersecting cartons at ${time}`);
  }
  for(const p of s.parcels){
    assert.ok(Number.isFinite(p.x));
    if(p.visible)assert.ok(p.x>=DEMO.start-1e-9&&p.x<=DEMO.end+1e-9);
    if(p.held){holds++;assert.ok(Math.abs(p.x-DEMO.stop)<1e-8);assert.ok(p.x+.2<6.51);}
    if(previous){
      const prev=previous.parcels.find(q=>q.id===p.id);
      if(prev.visible&&p.visible)assert.ok(p.x>=prev.x-1e-8,`Backward jump at ${time}`);
      if(prev.visible!==p.visible){
        visibleTransitions++;
        assert.ok(Math.abs(p.x)>DEMO.end-.1,'Replay must recycle under the end hoods');
      }
    }
  }
  previous=s;
}
assert.ok(holds>0);assert.ok(visibleTransitions>0);
console.log(JSON.stringify({passed:true,checked_seconds:100,samples:10001,min_carton_clearance_m:Number(minClearance.toFixed(3)),inspection_dwell_checked:true,recycling_masked_by_hoods:true}));
