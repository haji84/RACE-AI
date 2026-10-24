/* Independently saved original-timing research. Video remains unused. */
(function(root,factory){'use strict';const api=factory(typeof module==='object'&&module.exports?require('./ui-core.js'):root.RaceUI);if(typeof module==='object'&&module.exports)module.exports=api;root.RaceOriginalExhibition=api;})(typeof globalThis!=='undefined'?globalThis:this,function(UI){
  'use strict';
  const RANKS=['first','second','third','fourth','fifth','sixth'],METRICS=['display_time_s','lap_s','turn_s','straight_s'];
  const COEFFICIENTS={display_time_s:1,lap_s:0.05,turn_s:0.2,straight_s:0.2};
  const PARAMETERS={display_coefficient_per_second:1,lap_coefficient_per_second:0.05,turn_coefficient_per_second:0.2,straight_coefficient_per_second:0.2,log_strength_min:-20,log_strength_max:20,rating_floor:0.01};
  const fail=()=>{throw new Error('オリジナル反映予想の固定入力・取得保存時刻・24実測値・確率を確認できません。');};
  const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v),hash=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
  const exact=(v,keys)=>{if(!object(v)||Object.keys(v).sort().join()!==keys.slice().sort().join())fail();};
  const finite=(v,low=-Infinity,high=Infinity)=>typeof v==='number'&&Number.isFinite(v)&&v>=low&&v<=high;
  const near=(a,b)=>finite(a)&&finite(b)&&Math.abs(a-b)<1e-10;
  const nonce=v=>typeof v==='string'&&/^([1-9][0-9]{0,19})-([1-9][0-9]{0,3})$/.test(v);
  const combinationKey=v=>{if(!Array.isArray(v)||v.length!==3||new Set(v).size!==3||v.some(n=>!Number.isInteger(n)||n<1||n>6))fail();return v.join('-');};

  function clockReader(dateJst,now){
    return function time(value,scheduled=false){
      const match=typeof value==='string'&&/^(\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d)(?:\.(\d{1,6}))?(Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.exec(value);
      if(!match)fail();const stamp=Date.parse(value),local=new Date(match[1]+'Z');
      if(!Number.isFinite(stamp)||!Number.isFinite(local.getTime())||local.toISOString().slice(0,19)!==match[1]||UI.dayJst(new Date(stamp))!==dateJst)fail();
      const micros=BigInt(stamp)*1000n+BigInt((match[2]||'').padEnd(6,'0').slice(3));if(!scheduled&&micros>BigInt(Math.floor(now))*1000n)fail();return micros;
    };
  }
  function distribution(strengths){
    const lanes=[1,2,3,4,5,6],triples=[],marginals=lanes.map(lane=>({lane,...Object.fromEntries(RANKS.map(p=>[p+'_probability',0])),top3_probability:0}));
    function walk(order,remaining,p){
      if(order.length===3)triples.push({combination:order.slice(),probability:p});
      if(!remaining.length){order.forEach((lane,i)=>marginals[lane-1][RANKS[i]+'_probability']+=p);return;}
      const total=remaining.reduce((sum,lane)=>sum+strengths.get(lane),0);
      for(const lane of remaining)walk([...order,lane],remaining.filter(n=>n!==lane),p*strengths.get(lane)/total);
    }
    walk([],lanes,1);for(const row of marginals)row.top3_probability=RANKS.slice(0,3).reduce((sum,p)=>sum+row[p+'_probability'],0);return {triples,marginals};
  }
  function validateDistribution(value,expected){
    if(!Array.isArray(value.triples)||value.triples.length!==120||!Array.isArray(value.marginals)||value.marginals.length!==6)fail();
    const seen=new Set();for(const row of value.triples){exact(row,['combination','probability']);const key=combinationKey(row.combination),want=expected.triples.find(r=>r.combination.join('-')===key);if(!want||seen.has(key)||!near(row.probability,want.probability))fail();seen.add(key);}
    const lanes=new Set();for(const row of value.marginals){exact(row,['lane',...RANKS.map(p=>p+'_probability'),'top3_probability']);const want=expected.marginals.find(r=>r.lane===row.lane);if(!want||lanes.has(row.lane)||[...RANKS,'top3'].some(p=>!near(row[p+'_probability'],want[p+'_probability'])))fail();lanes.add(row.lane);}
  }
  function pinnedContext(raw,{race,dateJst,now,baselineReceipt,programIdentitySha256}){
    exact(raw,['schema_version','request_id','snapshot','cloud_saved_at','cloud_eligible_pre_race','program_identity_sha256']);
    if(!race||raw.schema_version!==1||!nonce(raw.request_id)||raw.cloud_eligible_pre_race!==true||!hash(programIdentitySha256)||raw.program_identity_sha256!==programIdentitySha256||UI.dayJst(new Date(now))!==dateJst)fail();
    const s=raw.snapshot;exact(s,['schema_version','phase','variant','race_id','date_jst','closed_at','as_of','generated_at','program_identity_sha256','b_program_sha256','baseline_link','beforeinfo_link','original_link','boats','feature_status','model','deltas','research_only','validation_status','purchase_decision','purchase_recommendations','snapshot_id']);
    if(s.schema_version!==1||s.phase!=='post_exhibition'||s.variant!=='original-v1'||s.race_id!==race.race_id||s.date_jst!==dateJst||s.program_identity_sha256!==programIdentitySha256||!hash(s.b_program_sha256)||!hash(s.snapshot_id)||s.research_only!==true||s.validation_status!=='UNVALIDATED'||s.purchase_decision!=='skip'||!Array.isArray(s.purchase_recommendations)||s.purchase_recommendations.length)fail();
    const time=clockReader(dateJst,now),cutoff=time(race.closed_at,true),asof=time(s.as_of),generated=time(s.generated_at),saved=time(raw.cloud_saved_at);
    if(time(s.closed_at,true)!==cutoff||asof!==generated||!(generated<=saved&&saved<cutoff))fail();
    const baseline=UI.validatePredictionReceipt(baselineReceipt,{race,dateJst,now}),b=baseline.snapshot,base=b.models.find(m=>m.model_id==='official-program-rating-pl')||b.models.find(m=>m.model_id==='official-program-uniform-pl'),link=s.baseline_link;
    exact(link,['request_id','snapshot_id','receipt_sha256','cloud_saved_at','model_id']);
    if(link.request_id!==baseline.request_id||link.snapshot_id!==b.snapshot_id||!hash(link.receipt_sha256)||time(link.cloud_saved_at)!==time(baseline.cloud_saved_at)||time(baseline.cloud_saved_at)>asof||link.model_id!==base?.model_id||s.b_program_sha256!==b.program_sha256)fail();
    const preview=s.beforeinfo_link;exact(preview,['snapshot_id','receipt_sha256','source_url','source_sha256','captured_at','runner_saved_at','cloud_saved_at']);
    if(!hash(preview.snapshot_id)||!hash(preview.receipt_sha256)||!hash(preview.source_sha256))fail();let url;try{url=new URL(preview.source_url);}catch{fail();}const [,venue,number]=race.race_id.split('-');
    if(url.protocol!=='https:'||url.hostname!=='www.boatrace.jp'||url.port||url.username||url.password||url.hash||url.pathname!=='/owpc/pc/race/beforeinfo'||[...url.searchParams.keys()].sort().join()!=='hd,jcd,rno'||url.searchParams.get('hd')!==dateJst.replaceAll('-','')||url.searchParams.get('jcd')!==venue||!/^\d{1,2}$/.test(url.searchParams.get('rno'))||Number(url.searchParams.get('rno'))!==Number(number))fail();
    if(!(time(preview.captured_at)<=time(preview.runner_saved_at)&&time(preview.runner_saved_at)<=time(preview.cloud_saved_at)&&time(preview.cloud_saved_at)<=asof))fail();
    return {s,b,base,time,asof};
  }
  function validateOriginalLink(link,race,time,asof){
    exact(link,['request_id','snapshot_id','receipt_sha256','runner_saved_at','cloud_saved_at','sources']);
    if(!nonce(link.request_id)||!hash(link.snapshot_id)||!hash(link.receipt_sha256)||!Array.isArray(link.sources)||link.sources.length!==2)fail();
    const runner=time(link.runner_saved_at),saved=time(link.cloud_saved_at);if(!(runner<=saved&&saved<=asof))fail();
    const [day,venue,number]=race.race_id.split('-');
    for(let i=0;i<2;i++){
      const source=link.sources[i],component=i===0?'original':'standard',path=i===0?'txt':'hp_txt',prefix=i===0?'bc_oriten':'bc_j_tkz';
      exact(source,['component','source_url','source_sha256','captured_at','available_at','upstream_published_at']);
      if(source.component!==component||source.source_url!=='https://race.boatcast.jp/'+path+'/'+venue+'/'+prefix+'_'+day+'_'+venue+'_'+number+'.txt'||!hash(source.source_sha256)||source.upstream_published_at!==null)fail();
      const captured=time(source.captured_at);if(time(source.available_at)!==captured||captured>runner)fail();
    }
  }
  function validateFeatures(features){
    exact(features,['display_time','preview_st','weather','original_exhibition','exhibition_video']);
    const expected={display_time:[['AVAILABLE'],true,null],original_exhibition:[['AVAILABLE'],true,null],preview_st:[['OBSERVED_UNUSED','PARTIAL_UNUSED','MISSING'],false,'NOT_USED_BY_ORIGINAL_TIMING_MODEL'],weather:[['SOURCE_TIME_UNVERIFIED_UNUSED'],false,'SOURCE_TIME_HAS_NO_DATE'],exhibition_video:[['MISSING'],false,'NO_VALIDATED_BOAT_FEATURES']};
    for(const [key,[statuses,used,reason]]of Object.entries(expected)){const value=features[key];exact(value,['status','used','reason']);if(!statuses.includes(value.status)||value.used!==used||value.reason!==reason)fail();}
  }
  function validateBoats(rows,base,program){
    if(!Array.isArray(rows)||rows.length!==6||new Set(rows.map(r=>r.lane)).size!==6)fail();
    const baseStrengths=new Map(base.strengths.map(r=>[r.lane,r.strength])),values=new Map();
    for(const row of rows){
      exact(row,['lane','racer_registration_id','display_time_seconds','base_strength','display_delta_seconds','adjusted_strength','original_times','contributions','total_log_strength_delta']);exact(row.original_times,['lap_s','turn_s','straight_s']);
      const person=program.find(p=>p.lane===row.lane);if(!person||person.racer_registration_id!==row.racer_registration_id||!near(row.base_strength,baseStrengths.get(row.lane))||!finite(row.display_time_seconds,0.01,100)||Object.values(row.original_times).some(v=>!finite(v,0.01,999.99)))fail();
      values.set(row.lane,{display_time_s:row.display_time_seconds,...row.original_times});
    }
    const means=Object.fromEntries(METRICS.map(key=>[key,[...values.values()].reduce((sum,v)=>sum+v[key],0)/6])),strengths=new Map();
    for(const row of rows){
      exact(row.contributions,METRICS);let total=0;
      for(const key of METRICS){const contribution=row.contributions[key],delta=means[key]-values.get(row.lane)[key],coefficient=COEFFICIENTS[key];exact(contribution,['delta_seconds','coefficient_per_second','log_strength_contribution']);if(!near(contribution.delta_seconds,delta)||contribution.coefficient_per_second!==coefficient||!near(contribution.log_strength_contribution,coefficient*delta))fail();total+=coefficient*delta;}
      const adjusted=Math.exp(Math.max(-20,Math.min(20,Math.log(row.base_strength)+total)));
      if(!near(row.display_delta_seconds,means.display_time_s-row.display_time_seconds)||!near(row.total_log_strength_delta,total)||!finite(row.adjusted_strength,Math.exp(-20),Math.exp(20))||Math.abs(row.adjusted_strength-adjusted)>1e-10*Math.max(1,adjusted))fail();strengths.set(row.lane,row.adjusted_strength);
    }
    return {strengths,baseStrengths};
  }
  function validateModel(model,strengths){
    exact(model,['model_id','model_version','parameters','triples','marginals','strengths']);if(model.model_id!=='official-display-original-pl'||model.model_version!=='1')fail();exact(model.parameters,Object.keys(PARAMETERS));for(const [key,value]of Object.entries(PARAMETERS))if(model.parameters[key]!==value)fail();
    if(!Array.isArray(model.strengths)||model.strengths.length!==6||new Set(model.strengths.map(r=>r.lane)).size!==6)fail();for(const row of model.strengths){exact(row,['lane','strength']);if(!strengths.has(row.lane)||row.strength!==strengths.get(row.lane))fail();}
    validateDistribution(model,distribution(strengths));
  }
  function validateDeltas(deltas,base,model){
    exact(deltas,['triples','marginals']);if(!Array.isArray(deltas.triples)||deltas.triples.length!==120||!Array.isArray(deltas.marginals)||deltas.marginals.length!==6)fail();
    const check=(v,before,after)=>{exact(v,['baseline_probability','post_probability','delta_probability']);if(!near(v.baseline_probability,before)||!near(v.post_probability,after)||!near(v.delta_probability,after-before))fail();};
    const combinations=new Set();for(const row of deltas.triples){exact(row,['combination','baseline_probability','post_probability','delta_probability']);const key=combinationKey(row.combination),before=base.triples.find(r=>r.combination.join('-')===key),after=model.triples.find(r=>r.combination.join('-')===key);if(!before||!after||combinations.has(key))fail();combinations.add(key);check({baseline_probability:row.baseline_probability,post_probability:row.post_probability,delta_probability:row.delta_probability},before.probability,after.probability);}
    const lanes=new Set();for(const row of deltas.marginals){exact(row,['lane',...RANKS,'top3']);const before=base.marginals.find(r=>r.lane===row.lane),after=model.marginals.find(r=>r.lane===row.lane);if(!before||!after||lanes.has(row.lane))fail();lanes.add(row.lane);for(const rank of [...RANKS,'top3'])check(row[rank],before[rank+'_probability'],after[rank+'_probability']);}
  }
  function validateReceipt(raw,{race,dateJst,now=Date.now(),baselineReceipt,programIdentitySha256}={}){
    const {s,b,base,time,asof}=pinnedContext(raw,{race,dateJst,now,baselineReceipt,programIdentitySha256});
    validateOriginalLink(s.original_link,race,time,asof);validateFeatures(s.feature_status);
    const {strengths,baseStrengths}=validateBoats(s.boats,base,b.program_boats);
    validateDistribution(base,distribution(baseStrengths));validateModel(s.model,strengths);validateDeltas(s.deltas,base,s.model);
    return JSON.parse(JSON.stringify(raw));
  }
  function phaseStatus({baseline='idle',post='idle',original='idle'}={}){
    const label=state=>({idle:'未確認',loading:'確認中',ready:'保存済み',unobtained:'未保存',error:'取得失敗'})[state]||'未確認';
    return '展示前 '+label(baseline)+' · 展示後v1 '+label(post)+' · オリジナル反映v1 '+label(original)+' · 映像特徴量 未使用';
  }
  return {phaseStatus,validateReceipt};
});
