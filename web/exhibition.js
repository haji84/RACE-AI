/* Saved post-exhibition research, kept independent of the exhibition-unreflected baseline. */
(function(root,factory){'use strict';const api=factory(typeof module==='object'&&module.exports?require('./ui-core.js'):root.RaceUI);if(typeof module==='object'&&module.exports)module.exports=api;root.RaceExhibition=api;})(typeof globalThis!=='undefined'?globalThis:this,function(UI){
  'use strict';
  const POSITIONS=['first','second','third','fourth','fifth','sixth'],PARAMETERS={display_coefficient_per_second:1,log_strength_min:-20,log_strength_max:20,rating_floor:0.01};
  const fail=()=>{throw new Error('展示後予想の固定された入力・保存時点・確率の再計算を確認できません。');};
  const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v),hash=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
  const exact=(v,keys)=>{if(!object(v)||Object.keys(v).sort().join()!==keys.slice().sort().join())fail();};
  const finite=(v,low=-Infinity,high=Infinity)=>typeof v==='number'&&Number.isFinite(v)&&v>=low&&v<=high;
  const near=(a,b)=>finite(a)&&finite(b)&&Math.abs(a-b)<1e-10;
  const combinationKey=value=>{if(!Array.isArray(value)||value.length!==3||new Set(value).size!==3||value.some(n=>!Number.isInteger(n)||n<1||n>6))fail();return value.join('-');};
  function distribution(strengths){
    const lanes=[1,2,3,4,5,6],marginals=lanes.map(lane=>({lane,...Object.fromEntries(POSITIONS.map(p=>[p+'_probability',0])),top3_probability:0})),triples=[];
    function walk(order,remaining,p){
      if(order.length===3)triples.push({combination:order.slice(),probability:p});
      if(!remaining.length){order.forEach((lane,index)=>marginals[lane-1][POSITIONS[index]+'_probability']+=p);return;}
      const total=remaining.reduce((sum,lane)=>sum+strengths.get(lane),0);
      for(const lane of remaining)walk([...order,lane],remaining.filter(n=>n!==lane),p*strengths.get(lane)/total);
    }
    walk([],lanes,1);for(const row of marginals)row.top3_probability=POSITIONS.slice(0,3).reduce((sum,p)=>sum+row[p+'_probability'],0);
    return {triples,marginals};
  }
  function validateDistribution(model,expected){
    if(!Array.isArray(model.triples)||model.triples.length!==120||!Array.isArray(model.marginals)||model.marginals.length!==6)fail();
    const seen=new Set();for(const row of model.triples){exact(row,['combination','probability']);const key=combinationKey(row.combination);const want=expected.triples.find(r=>r.combination.join('-')===key);if(!want||seen.has(key)||!near(row.probability,want.probability))fail();seen.add(key);}
    const boats=new Set();for(const row of model.marginals){exact(row,['lane',...POSITIONS.map(p=>p+'_probability'),'top3_probability']);const want=expected.marginals.find(r=>r.lane===row.lane);if(!want||boats.has(row.lane)||[...POSITIONS,'top3'].some(p=>!near(row[p+'_probability'],want[p+'_probability'])))fail();boats.add(row.lane);}
  }
  function validateReceipt(raw,{race,dateJst,now=Date.now(),baselineReceipt,programIdentitySha256}={}){
    exact(raw,['schema_version','request_id','snapshot','cloud_saved_at','cloud_eligible_pre_race','program_identity_sha256']);
    if(!race||raw.schema_version!==1||!/^([1-9][0-9]{0,19})-([1-9][0-9]{0,3})$/.test(raw.request_id)||raw.cloud_eligible_pre_race!==true||!hash(programIdentitySha256)||raw.program_identity_sha256!==programIdentitySha256||UI.dayJst(new Date(now))!==dateJst)fail();
    const s=raw.snapshot;exact(s,['schema_version','phase','race_id','date_jst','closed_at','as_of','generated_at','program_identity_sha256','b_program_sha256','baseline_link','beforeinfo_link','boats','feature_status','model','deltas','research_only','validation_status','purchase_decision','purchase_recommendations','snapshot_id']);
    if(s.schema_version!==1||s.phase!=='post_exhibition'||s.race_id!==race.race_id||s.date_jst!==dateJst||s.program_identity_sha256!==programIdentitySha256||!hash(s.b_program_sha256)||!hash(s.snapshot_id)||s.research_only!==true||s.validation_status!=='UNVALIDATED'||s.purchase_decision!=='skip'||!Array.isArray(s.purchase_recommendations)||s.purchase_recommendations.length)fail();
    const time=(value,scheduled=false)=>{if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(value))fail();const stamp=Date.parse(value);if(!Number.isFinite(stamp)||(!scheduled&&stamp>now+60000)||UI.dayJst(new Date(stamp))!==dateJst)fail();return stamp;};
    const cutoff=UI.cutoff(race,dateJst),asof=time(s.as_of),generated=time(s.generated_at),saved=time(raw.cloud_saved_at);
    if(time(s.closed_at,true)!==cutoff||asof!==generated||!(generated<=saved&&saved<cutoff))fail();
    const baseline=UI.validatePredictionReceipt(baselineReceipt,{race,dateJst,now}),b=baseline.snapshot,link=s.baseline_link;
    exact(link,['request_id','snapshot_id','receipt_sha256','cloud_saved_at','model_id']);
    const base=b.models.find(m=>m.model_id==='official-program-rating-pl')||b.models.find(m=>m.model_id==='official-program-uniform-pl');
    if(link.request_id!==baseline.request_id||link.snapshot_id!==b.snapshot_id||!hash(link.receipt_sha256)||time(link.cloud_saved_at)!==time(baseline.cloud_saved_at)||time(baseline.cloud_saved_at)>asof||link.model_id!==base?.model_id||s.b_program_sha256!==b.program_sha256)fail();
    const source=s.beforeinfo_link;exact(source,['snapshot_id','receipt_sha256','source_url','source_sha256','captured_at','runner_saved_at','cloud_saved_at']);
    if(!hash(source.snapshot_id)||!hash(source.receipt_sha256)||!hash(source.source_sha256))fail();let url;try{url=new URL(source.source_url);}catch{fail();}const [,venue,number]=race.race_id.split('-');
    if(url.protocol!=='https:'||url.hostname!=='www.boatrace.jp'||url.port||url.username||url.password||url.hash||url.pathname!=='/owpc/pc/race/beforeinfo'||[...url.searchParams.keys()].sort().join()!=='hd,jcd,rno'||url.searchParams.get('hd')!==dateJst.replaceAll('-','')||url.searchParams.get('jcd')!==venue||!/^\d{1,2}$/.test(url.searchParams.get('rno'))||Number(url.searchParams.get('rno'))!==Number(number))fail();
    const captured=time(source.captured_at),runner=time(source.runner_saved_at),cloud=time(source.cloud_saved_at);if(!(captured<=runner&&runner<=cloud&&cloud<=asof))fail();
    exact(s.feature_status,['display_time','preview_st','weather','original_exhibition','exhibition_video']);
    const features={display_time:[['AVAILABLE'],true,null],preview_st:[['OBSERVED_UNUSED','PARTIAL_UNUSED','MISSING'],false,'NOT_USED_BY_DISPLAY_ONLY_MODEL'],weather:[['SOURCE_TIME_UNVERIFIED_UNUSED'],false,'SOURCE_TIME_HAS_NO_DATE'],original_exhibition:[['MISSING'],false,'ORIGINAL_SOURCE_NOT_INGESTED'],exhibition_video:[['MISSING'],false,'NO_VALIDATED_BOAT_FEATURES']};
    for(const [name,[statuses,used,reason]]of Object.entries(features)){const f=s.feature_status[name];exact(f,['status','used','reason']);if(!statuses.includes(f.status)||f.used!==used||f.reason!==reason)fail();}
    if(!Array.isArray(s.boats)||s.boats.length!==6||new Set(s.boats.map(row=>row.lane)).size!==6)fail();
    const mean=s.boats.reduce((sum,row)=>{if(!finite(row.display_time_seconds,0.01,100))fail();return sum+row.display_time_seconds;},0)/6,strengths=new Map(),baseStrengths=new Map(base.strengths.map(row=>[row.lane,row.strength]));
    for(const row of s.boats){exact(row,['lane','racer_registration_id','display_time_seconds','base_strength','display_delta_seconds','adjusted_strength']);const boat=b.program_boats.find(v=>v.lane===row.lane),strength=baseStrengths.get(row.lane),delta=mean-row.display_time_seconds,adjusted=Math.exp(Math.max(-20,Math.min(20,Math.log(strength)+delta)));
      if(!boat||row.racer_registration_id!==boat.racer_registration_id||!near(row.base_strength,strength)||!near(row.display_delta_seconds,delta)||!finite(row.adjusted_strength,Math.exp(-20),Math.exp(20))||Math.abs(row.adjusted_strength-adjusted)>1e-10*Math.max(1,adjusted))fail();strengths.set(row.lane,row.adjusted_strength);
    }
    const m=s.model;exact(m,['model_id','model_version','parameters','triples','marginals','strengths']);if(m.model_id!=='official-beforeinfo-display-pl'||m.model_version!=='1')fail();exact(m.parameters,Object.keys(PARAMETERS));for(const [key,value]of Object.entries(PARAMETERS))if(m.parameters[key]!==value)fail();
    if(!Array.isArray(m.strengths)||m.strengths.length!==6||new Set(m.strengths.map(r=>r.lane)).size!==6)fail();for(const row of m.strengths){exact(row,['lane','strength']);if(!strengths.has(row.lane)||row.strength!==strengths.get(row.lane))fail();}
    const expected=distribution(strengths),baseExpected=distribution(baseStrengths);validateDistribution(m,expected);validateDistribution(base,baseExpected);
    exact(s.deltas,['triples','marginals']);if(!Array.isArray(s.deltas.triples)||s.deltas.triples.length!==120||!Array.isArray(s.deltas.marginals)||s.deltas.marginals.length!==6)fail();
    const delta=(value,before,after)=>{exact(value,['baseline_probability','post_probability','delta_probability']);if(!near(value.baseline_probability,before)||!near(value.post_probability,after)||!near(value.delta_probability,after-before))fail();};
    const combinations=new Set();for(const row of s.deltas.triples){exact(row,['combination','baseline_probability','post_probability','delta_probability']);const key=combinationKey(row.combination),before=base.triples.find(r=>r.combination.join('-')===key),after=m.triples.find(r=>r.combination.join('-')===key);if(!before||!after||combinations.has(key))fail();combinations.add(key);delta({baseline_probability:row.baseline_probability,post_probability:row.post_probability,delta_probability:row.delta_probability},before.probability,after.probability);}
    const lanes=new Set();for(const row of s.deltas.marginals){exact(row,['lane',...POSITIONS,'top3']);const before=base.marginals.find(r=>r.lane===row.lane),after=m.marginals.find(r=>r.lane===row.lane);if(!before||!after||lanes.has(row.lane))fail();lanes.add(row.lane);for(const p of [...POSITIONS,'top3'])delta(row[p],before[p+'_probability'],after[p+'_probability']);}
    return JSON.parse(JSON.stringify(raw));
  }
  function phaseStatus({baseline='idle',post='idle'}={}){
    const label=state=>({idle:'未確認',loading:'確認中',ready:'保存済み',unobtained:'未保存',error:'取得失敗'})[state]||'未確認';
    return '展示前 '+label(baseline)+' · 展示後v1 '+label(post)+' · 映像・オリジナル展示v1 未取得';
  }
  return {phaseStatus,validateReceipt};
});

