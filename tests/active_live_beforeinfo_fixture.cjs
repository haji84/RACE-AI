'use strict';
// These source pages and races are invented; no retained source or key is read.
const fs=require('node:fs'),path=require('node:path'),{execFileSync}=require('node:child_process');
const root=path.resolve(__dirname,'..');
function activeFixture(lanes=[1,2,3,4,5],{partial=false,savedLanes=lanes}={}){
 const script=`import json,sys,race_ai
from pathlib import Path
race_ai.__path__.append(str(Path('pr64-reference/race_ai').resolve()))
from tests.test_active_live_beforeinfo import active_view,observation,AT
lanes=json.loads(sys.argv[1]);view,program=active_view(tuple(lanes))
raw,context=observation(program,missing=(lanes[0],) if sys.argv[2]=='partial' else ())
print(json.dumps(dict(context=context,checked_at=AT.isoformat())))`;
 const parsed=JSON.parse(execFileSync(process.env.RACE_AI_TEST_PYTHON||'python3',
  ['-c',script,JSON.stringify(lanes),partial?'partial':'complete'],{cwd:root,encoding:'utf8'}));
 const data=JSON.parse(fs.readFileSync(path.join(root,'web/data/example-synthetic-forecast-audit.json'),'utf8'));
 data.records=data.records.filter(r=>r.sport==='boat');const row=data.records[0];
 Object.assign(row,{race_id:'20300401-12-12',race_no:12,event_date_jst:'2030-04-01',cutoff_at:parsed.context.cutoff_at,
  participants:savedLanes.map(number=>({number,registration_no:String(4000+number),name:'選手 '+number,active:true})),
  live_boat_observation:{schema:'RACE_AI_LIVE_BOAT_OBSERVATION_V1',forecast_inputs_used:false,
   checked_at:parsed.checked_at,state:partial?'AWAITING_EXHIBITION':'READY',context:parsed.context}});
 delete row.weather;delete row.weather_preview;delete row.boat_observation_context;
 const tickets=[];for(const a of savedLanes)for(const b of savedLanes)for(const c of savedLanes)if(a!==b&&a!==c&&b!==c)tickets.push([a,b,c]);
 row.prediction.ordered_top8=tickets.slice(0,8);row.prediction.rationale='架空の保存根拠：取得済みの出走者を比較しました。';
 row.prediction.cutoff_at=row.cutoff_at;
 return data;
}
module.exports={activeFixture};
