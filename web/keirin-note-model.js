/* Owner-provided Site view adapter. Original/revised/research records stay separate. */
(function(root,factory){
  if(typeof module==='object'&&module.exports)module.exports=factory(require('./keirin-note-source/staking_flexible.js'),require('./confidence.js'),require('./keirin-joint-forecast.js'));
  else root.RaceKeirinNote=factory(root.KeirinStaking,root.RaceKeirinConfidence,root.RaceKeirinJointForecast);
})(typeof window==='object'?window:globalThis,function(staking,confidence,joint){
  'use strict';
  const SCHEMA='RACE_AI_KEIRIN_NOTE_VIEW_V1',OUTER='RACE_AI_SAVED_WEB_VIEW_V1';
  const LIMIT=64*1024*1024,encoder=new TextEncoder();
  const record=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
  const exact=(value,keys)=>record(value)&&Object.keys(value).sort().join(',')===keys.slice().sort().join(',');
  const fail=()=>{throw new Error('KEIRIN_NOTE_INVALID');};
  const need=v=>{if(!v)fail();};
  const hex=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
  const day=v=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(v)&&Number.isFinite(Date.parse(v+'T00:00:00Z'))&&new Date(v+'T00:00:00Z').toISOString().slice(0,10)===v;
  const text=(v,max=2000)=>typeof v==='string'&&v.length<=max?v:'';
  const rid=v=>typeof v==='string'&&/^20\d{10}$/.test(v);
  const sameKeys=(v,keys)=>record(v)&&Object.keys(v).sort().join(',')===keys.split(',').sort().join(',');
  const utc=v=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}T\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(v)&&clock(v.slice(0,10),v)!==null;
  const canonical=v=>JSON.stringify(v&&typeof v==='object'?Array.isArray(v)?v.map(x=>JSON.parse(canonical(x))):Object.fromEntries(Object.keys(v).sort().map(k=>[k,JSON.parse(canonical(v[k]))])):v);
  const RESULT_SCHEMA='RACE_AI_KEIRIN_NOTE_RESEARCH_RESULTS_V1',CONSENSUS_SCHEMA='RACE_AI_KEIRIN_INDEPENDENT_SECONDARY_RESULT_MATCH_V1';
  const MATCHED='SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL';
  const RESULT_STATES=new Set([MATCHED,'HOLD_SECONDARY_RESULT_DISAGREEMENT','HOLD_NO_PUBLISHED_CUTOFF_HINT','HOLD_PROVIDER_DENIED_OR_RATE_LIMITED_STOP','HOLD_RESULT_SOURCE_UNAVAILABLE','HOLD_RESULT_SOURCE_UNVERIFIED','HOLD_RESULT_DAY_MISMATCH','HOLD_RESULT_RACE_MISMATCH','HOLD_SPECIAL_REFUND_OR_TIE_REQUIRES_OFFICIAL','HOLD_CONFLICTING_SOURCE_RESULT','PENDING_RESULT_NOT_PUBLISHED','PENDING_RESULT_NOT_FINAL']);
  const NATIONWIDE_SCHEMA='RACE_AI_KEIRIN_NATIONWIDE_FORECAST_VIEW_V1';
  const NATIONAL_STATES=new Set('WAITING_SOURCE_CAPTURE UNSUPPORTED_CLASS_OR_ROUND PUBLISHED_RESULT_NO_PRE_CUTOFF_ORIGINAL FROZEN_ORIGINAL_PRESERVED SOURCE_CAPTURE_BUDGET_PENDING CUTOFF_MARGIN_INSUFFICIENT BASELINE_SOURCE_UNVERIFIED PROVIDER_STOPPED SOURCE_UNAVAILABLE A_B_ARCHIVED_AWAITING_INDEPENDENT_READBACK A_B_AUTHENTICATED_PRE_CUTOFF ORIGIN_PROOF_PENDING FROZEN_ARCHIVE_UNVERIFIED RACE_DISAPPEARED_FROM_CURRENT_LIST'.split(' '));
  const CONDITION_STATES=new Set('HISTORY_NOT_COLLECTED HISTORY_SOURCE_UNAVAILABLE HISTORY_UNVERIFIED INSUFFICIENT_CAPTURE_MARGIN CONDITIONED_ARCHIVED_AWAITING_READBACK CONDITIONED_AUTHENTICATED_PRE_CUTOFF CONDITIONED_ORIGIN_PROOF_PENDING CONDITIONED_ARCHIVE_UNVERIFIED NO_CONDITIONED_ORIGINAL'.split(' '));
  const apiCrypto=()=>globalThis.crypto?.subtle?globalThis.crypto:require('node:crypto').webcrypto;
  const digest=async v=>Array.from(new Uint8Array(await apiCrypto().subtle.digest('SHA-256',typeof v==='string'?encoder.encode(v):v)),n=>n.toString(16).padStart(2,'0')).join('');
  function safeUrl(value){
    try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password&&(!u.port||u.port==='443')&&['keirin.kdreams.jp','keirin.netkeiba.com','keirin.jp','www.keirin.jp','winticket.jp','www.winticket.jp','www.jma.go.jp','www.sponichi.co.jp','keirin.sponichi.co.jp'].includes(u.hostname)?u.href:null;}catch{return null;}
  }
  function mapRows(value){
    const a=Array.isArray(value)?value:record(value)&&Array.isArray(value.races)?value.races:[];
    const result=new Map();for(const row of a){need(record(row));const id=row.race_id||row.input?.race_id||row.output?.race_id;need(rid(id)&&!result.has(id)&&[row.race_id,row.input?.race_id,row.output?.race_id].every(value=>value===undefined||value===id));result.set(id,row);}return result;
  }
  function clock(date,value){
    if(typeof value!=='string'||!value)return null;
    const stamp=/^\d\d:\d\d$/.test(value)?date+'T'+value+':00+09:00':value;
    const parts=/^(\d{4}-\d{2}-\d{2})T(\d\d):(\d\d)(?::(\d\d))?(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.exec(stamp);
    if(!parts||!day(parts[1])||Number(parts[2])>23||Number(parts[3])>59||Number(parts[4]||0)>59)return null;
    const n=Date.parse(stamp);return Number.isFinite(n)?stamp:null;
  }
  function instantMicros(value){
    if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}T\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)$/.test(value)||!clock(value.slice(0,10),value))return null;
    const fraction=/\.(\d{1,6})(?:Z|[+-]\d\d:\d\d)$/.exec(value)?.[1]||'';
    return BigInt(Date.parse(value))*1000n+BigInt(fraction.padEnd(6,'0').slice(3));
  }
  function sameClock(left,right){const value=instantMicros(left);return value!==null&&value===instantMicros(right);}
  function tickets(value,places,cars){
    if(value==null)return [];
    need(Array.isArray(value)&&value.length<=504);
    const seen=new Set();return value.map(item=>{
      const t=Array.isArray(item)?{combo:item.join('-'),role:'参考'}:item;
      need(record(t)&&typeof t.combo==='string'&&new RegExp('^[1-9](?:-[1-9]){'+(places-1)+'}$').test(t.combo));
      const numbers=t.combo.split('-').map(Number);
      need(new Set(numbers).size===places&&!seen.has(t.combo)&&(!cars.size||numbers.every(n=>cars.has(n))));seen.add(t.combo);
      return {...t,combo:t.combo,role:text(t.role,30)||'参考'};
    });
  }
  function binding(files,shas,cipherSha,date,name,legacy=false){
    const path=files.has('data/'+date+'/'+name)?'data/'+date+'/'+name:legacy&&files.has('data/'+name)?'data/'+name:null;
    return path?{cipherSha,fileSha256:shas.get(path),path}:null;
  }
  function inputSpans(text){
    // Hash the stored Python JSON bytes: parsing and stringifying would change
    // 80.0 into 80 and invalidate authentic originals. Walk JSON structure so
    // strings containing "input" cannot masquerade as an input member.
    need(typeof text==='string');let at=0;const spans=new Map();
    const space=()=>{while(/\s/.test(text[at]||'')&&at<text.length)at++;};
    function string(){const begin=at;need(text[at++]==='"');while(at<text.length){const c=text[at++];if(c==='"')return JSON.parse(text.slice(begin,at));if(c==='\\')at++;}fail();}
    function value(path,depth){
      need(depth<=32);space();const begin=at,c=text[at];
      if(c==='{'){
        at++;space();const keys=new Set();
        if(text[at]!=='}')for(;;){space();const key=string();need(!keys.has(key));keys.add(key);space();need(text[at++]===':');value([...path,key],depth+1);space();if(text[at]!==',')break;at++;}
        need(text[at++]==='}');
      }else if(c==='['){
        at++;space();let index=0;if(text[at]!==']')for(;;){value([...path,index++],depth+1);space();if(text[at]!==',')break;at++;}need(text[at++]==']');
      }else if(c==='"')string();
      else{while(at<text.length&&!/[\s,}\]]/.test(text[at]))at++;need(at>begin);}
      if(path.length===3&&path[0]==='races'&&Number.isInteger(path[1])&&path[2]==='input')spans.set(path[1],text.slice(begin,at));
    }
    value([],0);space();need(at===text.length);return spans;
  }
  async function jointSupplements(date,files,shas,rows,rawFiles){
    const path='data/'+date+'/',doc=files.get(path+'joint_forecasts.json');
    if(doc==null)return;
    const inputs=files.get(path+'comparison_inputs.json'),sourceSha=shas.get(path+'comparison_inputs.json');
    need(joint&&exact(doc,['schema','races'])&&doc.schema==='RACE_AI_KEIRIN_JOINT_FORECASTS_V1'&&Array.isArray(doc.races)&&doc.races.length<=300);
    need(exact(inputs,['schema','races'])&&inputs.schema==='RACE_AI_KEIRIN_COMPARISON_INPUTS_V1'&&Array.isArray(inputs.races)&&inputs.races.length<=300&&hex(sourceSha));
    const sources=mapRows(inputs),byId=new Map(rows.map(row=>[row.id,row])),seen=new Set();
    const spans=inputSpans(rawFiles[path+'comparison_inputs.json'].text),hashes=new Map();
    for(const [index,source] of inputs.races.entries()){const raw=spans.get(index);need(typeof raw==='string');hashes.set(source.race_id,await digest(raw));}
    const name=value=>typeof value==='string'?value.replace(/\s/g,''):'';
    for(const forecast of doc.races){
      need(rid(forecast?.race_id)&&forecast.race_id.startsWith(date.replaceAll('-',''))&&!seen.has(forecast.race_id));seen.add(forecast.race_id);
      const row=byId.get(forecast.race_id),source=sources.get(forecast.race_id);
      need(row&&source&&forecast.input_sha256===hashes.get(row.id)&&forecast.source_as_of===source.source_as_of&&forecast.cutoff_at===source.cutoff_at);
      need(sameClock(row.cutoff,source.cutoff_at)&&utc(source.source_as_of)&&utc(source.forecast_generated_at));
      need(forecast.input_sha256&&source.input?.race_id===row.id&&Array.isArray(source.roster)&&source.roster.length===row.riders.length&&Array.isArray(source.input.riders));
      const people=new Map();for(const p of source.roster){need(record(p)&&Number.isInteger(p.car)&&!people.has(p.car)&&name(p.name));people.set(p.car,p);}
      need(source.input.riders.length===row.riders.length&&new Set(source.input.riders.map(p=>p.car)).size===row.riders.length&&source.input.riders.every(p=>row.cars.has(p.car)));
      for(const p of row.riders){
        const expected=people.get(p.number);need(expected&&name(expected.name)===name(p.name));
        const known=value=>typeof value==='string'&&/^[0-9]{6}$/.test(value);
        need(!known(p.registration)||!known(expected.registration)||p.registration===expected.registration);
      }
      const context={race_id:row.id,cars:[...row.cars],source_packet_sha256:sourceSha,source_forecast_generated_at:source.forecast_generated_at,cutoff_at:source.cutoff_at,source_as_of:source.source_as_of};
      joint.validateForecast(forecast,context);
      for(const p of forecast.riders){const expected=people.get(p.car);need(expected&&name(expected.name)===name(p.name)&&(expected.registration??null)===(p.registration??null));}
      row.jointForecast=forecast;row.jointForecastBindings=context;row.jointForecastHistory=[];
      row.comparisonRiders=source.input.riders.map(p=>({...p,name:people.get(p.car).name}));
    }
  }
  function normalize(date,files,shas,cipherSha,results){
    const read=name=>files.get('data/'+date+'/'+name);
    const roster=mapRows(read('races.json')??files.get('data/races.json'));
    const originals=mapRows(read('forecasts.json')??files.get('data/forecasts.json'));
    const two=mapRows(read('two_car_forecasts.json'));
    const flexible=mapRows(read('flexible_forecasts.json'));
    const refs=mapRows(read('reference_AB.json'));
    const quotes=mapRows(read('odds_snapshot_flexible.json'));
    const settled=mapRows(read('settlement.json'));
    const rollover=mapRows(read('three_car_rollover_forecasts.json'));
    for(const name of ['races.json','forecasts.json','two_car_forecasts.json','flexible_forecasts.json','reference_AB.json','odds_snapshot_flexible.json','settlement.json','three_car_rollover_forecasts.json']){
      if(files.has('data/'+date+'/'+name))need([...mapRows(read(name)).keys()].every(id=>id.startsWith(date.replaceAll('-',''))));
    }
    const ids=new Set([...roster.keys(),...originals.keys(),...two.keys(),...refs.keys()].filter(id=>id.startsWith(date.replaceAll('-',''))));
    const out=[];
    for(const id of ids){
      const r=roster.get(id)||{},p=originals.get(id)||{},riders=r.riders||[];
      need(Array.isArray(riders)&&riders.length<=9);
      const cars=new Set();const people=riders.map(raw=>{need(record(raw));const number=raw.number??raw.car;need(Number.isInteger(number)&&number>=1&&number<=9&&!cars.has(number));cars.add(number);return {...raw,number,name:text(raw.name,120)||'氏名未取得',score:raw.score??raw.points};});
      const row={id,date,venue:text(r.venue||p.venue,100)||'会場名未取得',number:r.race_no??r.no??p.no??Number(id.slice(-2)),title:text(r.race_title||r.title,200),
        cutoff:clock(date,r.deadline_time||r.cutoff||p.deadline_jst),start:clock(date,r.start_time||r.start||p.start_jst),
        sourceUrl:safeUrl(r.source_url),raw:r,riders:people,cars,lines:Array.isArray(r.lines)?r.lines:[],original:p,
        two:two.get(id)||{},flexible:flexible.get(id)||{},referenceEnvelope:refs.get(id)||{},reference:refs.get(id)?.output||refs.get(id)||{},quote:quotes.get(id)||{},
        settlement:settled.get(id)||null,rollover:rollover.get(id)||{},environment:read('environment.json')||null,
        bindings:Object.fromEntries([['original','forecasts.json',true],['two','two_car_forecasts.json'],['flexible','flexible_forecasts.json'],['reference','reference_AB.json'],['rollover','three_car_rollover_forecasts.json']].map(([key,name,legacy])=>[key,binding(files,shas,cipherSha,date,name,legacy)])),
        referenceHistory:[],resultHistory:[],resultUpdate:null,researchResultHistory:[...(results.get(id)||[])],latestResearchResult:(results.get(id)||[]).at(-1)||null};
      tickets(p.tickets,3,cars);tickets(row.two.tickets,2,cars);tickets(row.two.rollover?.tickets,2,cars);tickets(row.rollover.tickets,3,cars);
      for(const market of ['3t','2t'])tickets(row.flexible.markets?.[market]?.tickets,market==='2t'?2:3,cars);
      for(const model of ['A','B'])tickets(row.reference[model]?.ranked_tickets,3,cars);
      for(const saved of row.researchResultHistory)need(saved.observation.winning_triple===null||!cars.size||saved.observation.winning_triple.every(n=>cars.has(n)));
      need(Number.isInteger(row.number)&&row.number>=1&&row.number<=12);
      out.push(row);
    }
    return out.sort((a,b)=>(Date.parse(a.cutoff)||Infinity)-(Date.parse(b.cutoff)||Infinity)||a.id.localeCompare(b.id));
  }
  function resultUrl(provider,value,id){
    need(typeof value==='string'&&value.length<2048);
    const u=new URL(value);need(u.protocol==='https:'&&!u.username&&!u.password&&!u.hash&&!u.port&&value.startsWith('https://'+u.hostname+'/'));
    if(provider==='netkeirin')need(u.hostname==='keirin.netkeiba.com'&&u.pathname==='/race/result/'&&u.search==='?race_id='+id);
    else{
      need(provider==='Kdreams'&&u.hostname==='keirin.kdreams.jp'&&['','?pageType=result'].includes(u.search));
      const m=/^\/[a-z0-9-]+\/racedetail\/([0-9]{2})(20[0-9]{6})([0-9]{2})00([0-9]{2})\/$/.exec(u.pathname);
      need(m&&m[1]===id.slice(8,10)&&m[4]===id.slice(10)&&Number(m[3])>=1&&Number(m[3])<=8);
      const begin=m[2].slice(0,4)+'-'+m[2].slice(4,6)+'-'+m[2].slice(6);need(day(begin));
      need(new Date(Date.parse(begin+'T00:00:00Z')+(Number(m[3])-1)*86400000).toISOString().slice(0,10).replaceAll('-','')===id.slice(0,8));
    }
  }
  async function resultRecords(files,shas,cipherSha,dates){
    const results=new Map();
    for(const [path,value] of files){
      if(!path.endsWith('/research_results.json'))continue;
      const d=path.split('/')[1];need(dates.includes(d)&&sameKeys(value,'schema,day_jst,observations')&&value.schema===RESULT_SCHEMA&&value.day_jst===d&&Array.isArray(value.observations)&&value.observations.length<=10000);
      for(const o of value.observations){
        need(sameKeys(o,'schema,race_id,state,winning_triple,payout_per_100yen,provider_receipts,official_primary_result_authenticated,actual_organizer_cutoff_authenticated,qualifies_for_formal_settlement,captured_at,observation_sha256,previous_observation_sha256')&&o.schema===CONSENSUS_SCHEMA&&rid(o.race_id)&&o.race_id.startsWith(d.replaceAll('-',''))&&RESULT_STATES.has(o.state)&&utc(o.captured_at)&&hex(o.observation_sha256)&&(o.previous_observation_sha256===null||hex(o.previous_observation_sha256))&&o.previous_observation_sha256!==o.observation_sha256);
        need(o.official_primary_result_authenticated===false&&o.actual_organizer_cutoff_authenticated===false&&o.qualifies_for_formal_settlement===false&&Array.isArray(o.provider_receipts)&&o.provider_receipts.length<=2);
        const providers=new Set();for(const receipt of o.provider_receipts){need(sameKeys(receipt,'provider,source_bytes_sha256,observed_at,source_url')&&!providers.has(receipt.provider)&&hex(receipt.source_bytes_sha256)&&utc(receipt.observed_at)&&Date.parse(receipt.observed_at)<=Date.parse(o.captured_at));resultUrl(receipt.provider,receipt.source_url,o.race_id);providers.add(receipt.provider);}
        if(o.state===MATCHED)need(providers.size===2&&Array.isArray(o.winning_triple)&&o.winning_triple.length===3&&new Set(o.winning_triple).size===3&&o.winning_triple.every(n=>Number.isInteger(n)&&n>=1&&n<=9)&&Number.isSafeInteger(o.payout_per_100yen)&&o.payout_per_100yen>=100&&o.payout_per_100yen<=1000000000);
        else need(o.winning_triple===null&&o.payout_per_100yen===null);
        const fact={...o,provider_receipts:o.provider_receipts.map(({provider,source_url})=>({provider,source_url})).sort((a,b)=>(a.provider<b.provider?-1:a.provider>b.provider?1:0)||(a.source_url<b.source_url?-1:a.source_url>b.source_url?1:0))};
        for(const key of ['captured_at','observation_sha256','previous_observation_sha256'])delete fact[key];
        need(await digest(canonical(fact))===o.observation_sha256);
        const prior=results.get(o.race_id)||[],last=prior.at(-1)?.observation;
        if(last)need(o.previous_observation_sha256===last.observation_sha256&&Date.parse(o.captured_at)>=Date.parse(last.captured_at));
        prior.push({observation:o,binding:{cipherSha,fileSha256:shas.get(path),path}});results.set(o.race_id,prior);
      }
    }
    return results;
  }
  function resultUpdates(date,files){
    const value=files.get('data/'+date+'/result_updates.json'),updates=new Map();
    if(value==null)return updates;
    need(exact(value,['schema','observed_at','races'])&&value.schema==='RACE_AI_KEIRIN_RESULT_UPDATES_V1'&&clock(date,value.observed_at)&&Array.isArray(value.races)&&value.races.length<=300);
    for(const row of value.races){
      need(exact(row,['race_id','revision','observed_at','authority','order_status','payout_status','winning_triples','payouts_100yen','source_comparison','diagnostics','arms'])&&rid(row.race_id)&&row.race_id.startsWith(date.replaceAll('-',''))&&!updates.has(row.race_id)&&hex(row.revision)&&clock(date,row.observed_at)&&Date.parse(row.observed_at)<=Date.parse(value.observed_at));
      need(['official','secondary'].includes(row.authority)&&['confirmed','pending','conflict'].includes(row.order_status)&&['confirmed','pending','held'].includes(row.payout_status));
      need(Array.isArray(row.winning_triples)&&row.winning_triples.length<=20&&new Set(row.winning_triples).size===row.winning_triples.length);
      for(const combo of row.winning_triples)need(typeof combo==='string'&&/^[1-9]-[1-9]-[1-9]$/.test(combo)&&new Set(combo.split('-')).size===3);
      need((row.order_status==='confirmed')===(row.winning_triples.length>0)&&record(row.payouts_100yen));
      const money=row.authority==='official'&&row.order_status==='confirmed'&&row.payout_status==='confirmed';
      if(row.payout_status==='confirmed')need(money);
      if(money){
        need(Object.keys(row.payouts_100yen).sort().join(',')===row.winning_triples.slice().sort().join(','));
        Object.values(row.payouts_100yen).forEach(yen=>need(Number.isSafeInteger(yen)&&yen>=100&&yen<=1000000000));
      }else need(Object.keys(row.payouts_100yen).length===0);
      need(Array.isArray(row.source_comparison)&&row.source_comparison.length<=5&&new Set(row.source_comparison.map(s=>s?.source_id)).size===row.source_comparison.length);
      row.source_comparison.forEach(s=>need(exact(s,['source_id','state'])&&['keirin_jp','kdreams','netkeirin','official_pdf','official_json'].includes(s.source_id)&&['matched','different','unavailable','unverified'].includes(s.state)));
      checkedDiagnostics(row.diagnostics,date);need(exact(row.arms,['A','B','C','adjusted_A','adjusted_B']));
      const arms={};
      for(const [name,value] of Object.entries(row.arms)){
        need(exact(value,['state','points','stake_yen','return_yen'])&&['hit','miss','pending','void','unverifiable'].includes(value.state));
        const arm={...value};
        need(arm.points===null||Number.isSafeInteger(arm.points)&&arm.points>=1&&arm.points<=504);
        for(const field of ['stake_yen','return_yen'])need(arm[field]===null||Number.isSafeInteger(arm[field])&&arm[field]>=0&&arm[field]<=504000000000);
        if(!money||['pending','unverifiable'].includes(arm.state))need(arm.stake_yen===null&&arm.return_yen===null);
        if(row.authority!=='official'||row.order_status!=='confirmed')need(!['hit','miss','void'].includes(arm.state));
        arms[name]=arm;
      }
      updates.set(row.race_id,{...row,arms});
    }
    return updates;
  }
  function checkedDiagnostics(rows,date){
    const routes={OFFICIAL_CALENDAR:['keirin.jp','/sp/raceschedule','GET'],CALENDAR_SCRIPT:['keirin.jp','/sp/static/js/SJ0201.js','GET'],FORM_SCRIPT:['keirin.jp','/sp/static/js/commonSubmit.js','GET'],OFFICIAL_RACE_LIST:['keirin.jp','/sp/racelist','POST'],RACE_LIST_VIEW_SCRIPT:['keirin.jp','/sp/static/js/SJ0301_v.js','GET'],RACE_LIST_CONTROLLER_SCRIPT:['keirin.jp','/sp/static/js/SJ0301_c.js','GET'],OFFICIAL_FINAL_RESULT:['keirin.jp','/sp/race','POST'],OFFICIAL_PAYOUT_UNIT:['www.hofukeirin.jp','/ticket/','GET'],OFFICIAL_JSON_CALENDAR:['keirin.jp','/pc/json','GET'],OFFICIAL_JSON_DAY_LIST:['keirin.jp','/pc/json','GET'],OFFICIAL_JSON_RESULT_SUMMARY:['keirin.jp','/pc/json','GET'],OFFICIAL_JSON_HEADER:['keirin.jp','/pc/json','GET'],OFFICIAL_JSON_DETAIL:['keirin.jp','/pc/json','GET']};
    const reasons=['SOURCE_ACCEPTED','TRANSPORT_FAILED','HTTP_DENIED','HTTP_ERROR','REDIRECT_REFUSED','SOURCE_BYTES_INVALID','CHALLENGE_MARKUP','CAPTURE_CLOCK_INVALID','SOURCE_VALIDATION_FAILED','UNIT_TEXT_MISSING','UNIT_VERIFIED','RESULT_VALIDATED','RESULT_NOT_PUBLISHED','PROVIDER_STOP_PERSISTENCE_FAILED'];
    need(Array.isArray(rows)&&rows.length<=32);
    for(const row of rows){
      need(record(row)&&Object.keys(row).sort().join(',')==='http_status,method,observed_at,purpose,reason,schema,source_host,source_path,stage'&&row.schema==='RACE_AI_KEIRIN_RESULT_DIAGNOSTIC_V1');
      const route=routes[row.purpose];need(route&&row.source_host===route[0]&&row.source_path===route[1]&&row.method===route[2]);
      need(['REQUEST','HTTP_RESPONSE','CONTENT_CHECK','PARSE_RESULT','VERIFY_UNIT','PERSIST_STOP'].includes(row.stage)&&reasons.includes(row.reason)&&clock(date,row.observed_at));
      need(row.http_status===null||Number.isInteger(row.http_status)&&row.http_status>=100&&row.http_status<=599);
    }
  }
  function frozenForecasts(date,files){
    const doc=files.get('data/'+date+'/frozen_forecasts.json');if(doc==null)return new Map();
    need(exact(doc,['schema','races'])&&doc.schema==='RACE_AI_KEIRIN_FROZEN_FORECASTS_V1'&&Array.isArray(doc.races)&&doc.races.length>0&&doc.races.length<=300);
    return checkedFrozenRows(date,doc.races,true);
  }
  function checkedFrozenRows(date,rows,conditionedRequired){
    const out=new Map();
    const baseKeys='schema race_id generated_at published_cutoff_at source_facts_sha256 source_as_of A B C official_cutoff_independently_authenticated official_result_observed all_six_phase_orders_are_hypotheses_not_video_truth branch_weights_are_not_calibrated_probabilities formal_model_promoted old_PR71_four_models_required real_money_wager_placed prediction_sha256'.split(' ');
    const shadowKeys='schema race_id generated_at published_cutoff_at baseline_source_sha256 baseline_prediction_sha256 condition_supplement_sha256 A_research B_research rider_assessments verified_source_receipt_count medical_recovery_or_crash_causality_inferred comments_quoted_in_private_supplement_only historical_originals_mutated is_official_calibrated_or_production_forecast C_optional_unrelated sha256'.split(' ');
    const phases=['INITIAL','BELL','FINAL_HOME','FINAL_BACK','FOURTH_CORNER','GOAL'],number=(v,lo,hi)=>Number.isFinite(v)&&v>=lo&&v<=hi;
    for(const row of rows){
      const rowKeys=['race_id','revision','baseline_cipher_sha256','conditioned_cipher_sha256','baseline_sealed_at','conditioned_sealed_at','facts','baseline','conditioned'];
      need((exact(row,rowKeys)||exact(row,[...rowKeys,'confidence_assessment']))&&rid(row.race_id)&&row.race_id.startsWith(date.replaceAll('-',''))&&!out.has(row.race_id));
      for(const key of ['revision','baseline_cipher_sha256'])need(hex(row[key]));
      const base=row.baseline,adjusted=row.conditioned,facts=row.facts;
      need(exact(base,baseKeys)&&base.schema==='RACE_AI_KEIRIN_AUTOMATIC_MARKS_AND_SIX_PHASE_V1'&&base.race_id===row.race_id&&hex(base.prediction_sha256)&&hex(base.source_facts_sha256));
      if(adjusted===null)need(!conditionedRequired&&row.conditioned_cipher_sha256===null&&row.conditioned_sealed_at===null);
      else{
        need(exact(adjusted,shadowKeys)&&adjusted.schema==='RACE_AI_KEIRIN_CONDITIONED_AB_SHADOW_V1'&&adjusted.race_id===row.race_id&&hex(row.conditioned_cipher_sha256));
        need(hex(adjusted.sha256)&&hex(adjusted.condition_supplement_sha256)&&adjusted.baseline_prediction_sha256===base.prediction_sha256&&adjusted.baseline_source_sha256===base.source_facts_sha256&&adjusted.generated_at===base.generated_at&&adjusted.published_cutoff_at===base.published_cutoff_at);
      }
      for(const value of [base.generated_at,base.published_cutoff_at,base.source_as_of,row.baseline_sealed_at,...(adjusted?[row.conditioned_sealed_at]:[])])need(clock(date,value));
      need(Date.parse(base.source_as_of)<=Date.parse(base.generated_at));
      for(const key of ['baseline_sealed_at',...(adjusted?['conditioned_sealed_at']:[])])need(Date.parse(base.generated_at)<=Date.parse(row[key])&&Date.parse(base.published_cutoff_at)-Date.parse(row[key])>=65000);
      need(exact(base.C,['state'])&&base.C.state==='HOLD_NO_INDEPENDENT_HISTORICAL_FOLLOW_LABELS');
      for(const key of ['official_cutoff_independently_authenticated','official_result_observed','formal_model_promoted','old_PR71_four_models_required','real_money_wager_placed'])need(base[key]===false);
      need(base.all_six_phase_orders_are_hypotheses_not_video_truth===true&&base.branch_weights_are_not_calibrated_probabilities===true);
      if(adjusted){
        for(const key of ['medical_recovery_or_crash_causality_inferred','historical_originals_mutated','is_official_calibrated_or_production_forecast'])need(adjusted[key]===false);
        need(adjusted.comments_quoted_in_private_supplement_only===true&&adjusted.C_optional_unrelated===true&&Number.isInteger(adjusted.verified_source_receipt_count)&&adjusted.verified_source_receipt_count>=1&&adjusted.verified_source_receipt_count<=400);
      }
      need(exact(facts,['competition','line_groups','riders'])&&['CHALLENGE','A1_A2','S','GIRLS','OTHER'].includes(facts.competition)&&Array.isArray(facts.riders)&&facts.riders.length>=5&&facts.riders.length<=9);
      const cars=new Set();
      for(const r of facts.riders){
        need(exact(r,['car','athlete_id','mark_rank','competition_points','recent_form_score','h_count','b_count','style'])&&Number.isInteger(r.car)&&r.car>=1&&r.car<=9&&!cars.has(r.car));cars.add(r.car);
        need(r.athlete_id===null||typeof r.athlete_id==='string'&&/^\d{4,8}$/.test(r.athlete_id));
        need(r.mark_rank==='UNMARKED'||Number.isInteger(r.mark_rank)&&r.mark_rank>=1&&r.mark_rank<=facts.riders.length);
        need(number(r.competition_points,0,150)&&number(r.recent_form_score,0,1)&&['h_count','b_count'].every(k=>Number.isInteger(r[k])&&r[k]>=0&&r[k]<=99)&&['NIGE','MAKURI','SASHI','MARK','ALLROUND','UNKNOWN'].includes(r.style));
      }
      need(Array.isArray(facts.line_groups)&&facts.line_groups.length>0&&facts.line_groups.length<=cars.size&&facts.line_groups.every(g=>Array.isArray(g)&&g.length>0&&g.every(c=>Number.isInteger(c)&&cars.has(c))));
      const members=facts.line_groups.flat();need(members.length===cars.size&&new Set(members).size===cars.size&&(facts.competition!=='GIRLS'||facts.line_groups.every(g=>g.length===1)));
      need(exact(base.A,['model','ranked_tickets','based_on_published_marks_not_shared_PR71'])&&base.A.model==='marks-ordinal-plus-observed-rider-strength-v1'&&base.A.based_on_published_marks_not_shared_PR71===true&&exact(base.B,['model','ranked_tickets','six_phase_scenarios','round_objective_source'])&&base.B.model==='line-tactical-six-phase-untrained-v1'&&['SOURCE_EVIDENCED','UNKNOWN_NOT_IMPUTED'].includes(base.B.round_objective_source));
      const scenarios=base.B.six_phase_scenarios,ids=new Set();need(Array.isArray(scenarios)&&scenarios.length>=2&&scenarios.length<=20);
      for(const scenario of scenarios){
        need(exact(scenario,['scenario_id','six_phases','projected_3ren_tan','relative_research_weight'])&&typeof scenario.scenario_id==='string'&&/^L[1-9]_V[0-3]$/.test(scenario.scenario_id)&&!ids.has(scenario.scenario_id)&&number(scenario.relative_research_weight,0,1));ids.add(scenario.scenario_id);
        need(Array.isArray(scenario.six_phases)&&scenario.six_phases.length===6);
        scenario.six_phases.forEach((s,i)=>{need(exact(s,['phase','projected_order','projected_top3','hypothesis_actions','actual_rider_position_video_verified'])&&s.phase===phases[i]&&s.actual_rider_position_video_verified===false&&Array.isArray(s.projected_order)&&s.projected_order.length===cars.size&&new Set(s.projected_order).size===cars.size&&s.projected_order.every(c=>Number.isInteger(c)&&cars.has(c))&&JSON.stringify(s.projected_top3)===JSON.stringify(s.projected_order.slice(0,3))&&Array.isArray(s.hypothesis_actions)&&s.hypothesis_actions.length>0&&s.hypothesis_actions.length<=8&&s.hypothesis_actions.every(a=>typeof a==='string'&&/^[A-Z][A-Z0-9_]{0,79}$/.test(a)));});
        need(JSON.stringify(scenario.projected_3ren_tan)===JSON.stringify(scenario.six_phases[5].projected_top3));
      }
      need(Math.abs(scenarios.reduce((sum,s)=>sum+s.relative_research_weight,0)-1)<=1e-6);
      for(const name of ['A','B']){const value=base[name].ranked_tickets;need(Array.isArray(value)&&value.length>=1&&value.length<=12&&value.every(t=>Array.isArray(t)&&t.length===3&&t.every(Number.isInteger)));tickets(value,3,cars);}
      if(adjusted){
      for(const [name,label] of [['A','baseline-plus-documented-form-v1'],['B','six-phase-plus-documented-form-v1']]){
        const arm=adjusted[name+'_research'],keys=['model','ranked_tickets','baseline_ranked_tickets','changed_from_original'];if(name==='B')keys.push('branch_condition_factors','branch_factor_is_uncalibrated');
        need(exact(arm,keys)&&arm.model===label&&JSON.stringify(arm.baseline_ranked_tickets)===JSON.stringify(base[name].ranked_tickets)&&typeof arm.changed_from_original==='boolean'&&arm.changed_from_original===(JSON.stringify(arm.ranked_tickets)!==JSON.stringify(base[name].ranked_tickets)));
        for(const value of [base[name].ranked_tickets,arm.ranked_tickets]){need(Array.isArray(value)&&value.length>=1&&value.length<=12&&value.every(t=>Array.isArray(t)&&t.length===3&&t.every(Number.isInteger)));tickets(value,3,cars);}
      }
      const factors=adjusted.B_research.branch_condition_factors;
      need(adjusted.B_research.branch_factor_is_uncalibrated===true&&Array.isArray(factors)&&factors.length===ids.size&&new Set(factors.map(f=>f?.scenario_id)).size===ids.size&&factors.every(f=>exact(f,['scenario_id','relative_weight_after'])&&ids.has(f.scenario_id)&&number(f.relative_weight_after,0,1))&&Math.abs(factors.reduce((sum,f)=>sum+f.relative_weight_after,0)-1)<=1e-6);
      need(Array.isArray(adjusted.rider_assessments)&&adjusted.rider_assessments.length===cars.size);const assessed=new Set(),trends=['IMPROVING','DECLINING','NO_CLEAR_CHANGE','INSUFFICIENT_DATA'];
      for(const a of adjusted.rider_assessments){
        need(exact(a,'car trend recent_result_change post_fall_change post_fall_trend fall_on_record documented_absence_days return_after_absence_results comments_count score_adjustment effect_on_tactics'.split(' '))&&Number.isInteger(a.car)&&cars.has(a.car)&&!assessed.has(a.car));assessed.add(a.car);
        need(trends.includes(a.trend)&&trends.includes(a.post_fall_trend)&&typeof a.fall_on_record==='boolean'&&number(a.score_adjustment,-.08,.08)&&['UNKNOWN_NO_ADJUSTMENT','OBSERVED_RESULTS_UPWEIGHT_RESEARCH','OBSERVED_RESULTS_DOWNWEIGHT_RESEARCH'].includes(a.effect_on_tactics));
        for(const key of ['recent_result_change','post_fall_change'])need(a[key]===null||number(a[key],-1,1));
        for(const key of ['documented_absence_days','return_after_absence_results','comments_count'])need(a[key]===null||Number.isInteger(a[key])&&a[key]>=0&&a[key]<=36525);
      }
      }
      out.set(row.race_id,row);
    }
    return out;
  }
  function nationwideDay(date,files){
    const doc=files.get('data/'+date+'/nationwide_forecasts.json');if(doc==null)return null;
    need(exact(doc,['schema','day_jst','revision','observed_at','registry_available','inventory_complete','missing_venues','disappeared_race_ids','races'])&&doc.schema===NATIONWIDE_SCHEMA&&doc.day_jst===date&&hex(doc.revision)&&typeof doc.observed_at==='string'&&doc.observed_at.includes('T')&&clock(date,doc.observed_at));
    need(typeof doc.registry_available==='boolean'&&typeof doc.inventory_complete==='boolean'&&Array.isArray(doc.races)&&doc.races.length<=600&&Array.isArray(doc.missing_venues)&&doc.missing_venues.length<=43&&new Set(doc.missing_venues).size===doc.missing_venues.length&&doc.missing_venues.every(v=>Number.isInteger(v)&&v>=0&&v<=99));
    const ids=new Set();
    for(const row of doc.races){
      need(exact(row,['race_id','venue_code','race_no','cutoff_at','state','condition_state','original_identity','original'])&&rid(row.race_id)&&row.race_id.startsWith(date.replaceAll('-',''))&&!ids.has(row.race_id));ids.add(row.race_id);
      need(Number.isInteger(row.venue_code)&&row.venue_code===Number(row.race_id.slice(8,10))&&Number.isInteger(row.race_no)&&row.race_no>=1&&row.race_no<=12&&row.race_no===Number(row.race_id.slice(-2))&&NATIONAL_STATES.has(row.state)&&CONDITION_STATES.has(row.condition_state));
      need(row.cutoff_at===null||typeof row.cutoff_at==='string'&&row.cutoff_at.includes('T')&&clock(date,row.cutoff_at)&&new Date(Date.parse(row.cutoff_at)+9*3600000).toISOString().slice(0,10)===date);
      if(row.original===null){const identity=row.original_identity;
        if(identity===null)need(row.state!=='A_B_AUTHENTICATED_PRE_CUTOFF'&&row.condition_state!=='CONDITIONED_AUTHENTICATED_PRE_CUTOFF');
        else need(exact(identity,['baseline','conditioned'])&&hex(identity.baseline)&&(identity.conditioned===null||hex(identity.conditioned))&&(row.condition_state!=='CONDITIONED_AUTHENTICATED_PRE_CUTOFF'||identity.conditioned!==null));
        continue;}
      checkedFrozenRows(date,[row.original],false);const original=row.original,identity=row.original_identity,adjusted=original.conditioned!==null;
      need(exact(identity,['baseline','conditioned'])&&hex(identity.baseline)&&(identity.conditioned===null||hex(identity.conditioned))&&original.race_id===row.race_id&&original.baseline.published_cutoff_at===row.cutoff_at&&Date.parse(original.baseline_sealed_at)<=Date.parse(doc.observed_at));
      need((identity.conditioned!==null)===adjusted&&(row.condition_state==='CONDITIONED_AUTHENTICATED_PRE_CUTOFF')===adjusted&&(!adjusted||Date.parse(original.conditioned_sealed_at)<=Date.parse(doc.observed_at)));
    }
    need(Array.isArray(doc.disappeared_race_ids)&&new Set(doc.disappeared_race_ids).size===doc.disappeared_race_ids.length&&doc.disappeared_race_ids.every(id=>ids.has(id)));
    need(!doc.inventory_complete||doc.registry_available&&!doc.missing_venues.length&&!doc.disappeared_race_ids.length);
    need(doc.registry_available||!doc.races.length&&!doc.missing_venues.length&&!doc.disappeared_race_ids.length);
    return doc;
  }
  function combineFrozen(prior,fresh){
    if(!prior)return fresh||null;if(!fresh)return prior;
    for(const name of ['race_id','baseline_cipher_sha256','baseline_sealed_at','facts','baseline'])need(canonical(prior[name])===canonical(fresh[name]));
    need(Object.hasOwn(prior,'confidence_assessment')===Object.hasOwn(fresh,'confidence_assessment'));
    if(Object.hasOwn(prior,'confidence_assessment'))need(canonical(prior.confidence_assessment)===canonical(fresh.confidence_assessment));
    if(prior.conditioned&&fresh.conditioned)for(const name of ['conditioned','conditioned_cipher_sha256','conditioned_sealed_at'])need(canonical(prior[name])===canonical(fresh[name]));
    return fresh.conditioned||!prior.conditioned?fresh:prior;
  }
  function mergeNationwide(prior,fresh){
    if(!prior)return fresh;need(prior.day_jst===fresh.day_jst);
    const old=new Map(prior.races.map(row=>[row.race_id,row]));
    for(const row of fresh.races){const previous=old.get(row.race_id);combineFrozen(previous?.original,row.original);
      if(previous?.original_identity&&row.original_identity)need(previous.original_identity.baseline===row.original_identity.baseline&&(previous.original_identity.conditioned===null||row.original_identity.conditioned===null||previous.original_identity.conditioned===row.original_identity.conditioned));}
    if(Date.parse(fresh.observed_at)<Date.parse(prior.observed_at))return prior;
    const ids=new Set(fresh.races.map(row=>row.race_id));need(prior.races.every(row=>ids.has(row.race_id)));
    return {...fresh,races:fresh.races.map(row=>{const previous=old.get(row.race_id),original=combineFrozen(previous?.original,row.original);let identity=row.original_identity||previous?.original_identity||null;
      if(identity&&previous?.original_identity?.conditioned&&!identity.conditioned)identity={...identity,conditioned:previous.original_identity.conditioned};
      return {...row,cutoff_at:original?.baseline.published_cutoff_at||row.cutoff_at,original,original_identity:identity};})};
  }
  function nationwideSemantic(doc){
    const semantic=Object.fromEntries(Object.entries(doc).filter(([key])=>key!=='observed_at'));
    semantic.races=doc.races.map(row=>Object.fromEntries(Object.entries(row).filter(([key])=>key!=='original')));
    return semantic;
  }
  function attachNationwide(days,nationwide){
    for(const [date,doc] of nationwide){
      const byId=new Map((days.get(date)||[]).map(row=>[row.id,row]));
      for(const item of doc.races){
        let row=byId.get(item.race_id);
        if(!row){const facts=item.original?.facts,riders=(facts?.riders||[]).map(r=>({number:r.car,name:'氏名未取得',score:r.competition_points}));
          row={id:item.race_id,date,venue:'開催コード '+String(item.venue_code).padStart(2,'0'),number:item.race_no,title:'',cutoff:item.cutoff_at,start:null,sourceUrl:null,raw:{},riders,cars:new Set(riders.map(r=>r.number)),lines:facts?.line_groups||[],original:{},two:{},flexible:{},reference:{},referenceEnvelope:{},quote:{},settlement:null,rollover:{},environment:null,bindings:{},referenceHistory:[],resultHistory:[],resultUpdate:null,researchResultHistory:[],latestResearchResult:null,nationwideOnly:true};
        }
        const original=combineFrozen(row.frozenForecast,item.original);
        byId.set(item.race_id,{...row,nationwideStatus:item,...(original?{frozenForecast:original}:{}),...(row.nationwideOnly?{cutoff:item.cutoff_at}: {})});
      }
      days.set(date,[...byId.values()].sort((a,b)=>(Date.parse(a.cutoff)||Infinity)-(Date.parse(b.cutoff)||Infinity)||a.id.localeCompare(b.id)));
    }
    return days;
  }
  async function decodePacket(packet,cipherSha){
    need(record(packet)&&packet.schema===SCHEMA&&packet.formal_model_admission===false&&packet.production_weight_switch===false&&record(packet.files));
    need(Array.isArray(packet.dates)&&packet.dates.length>0&&packet.dates.every(day)&&new Set(packet.dates).size===packet.dates.length);
    const parsed=new Map(),fileShas=new Map();let total=0;
    for(const [path,entry] of Object.entries(packet.files)){
      need(/^data\/(?:\d{4}-\d{2}-\d{2}\/)?[A-Za-z0-9_.-]+\.json$/.test(path)&&record(entry)&&typeof entry.text==='string'&&hex(entry.sha256));
      const bytes=encoder.encode(entry.text),fileLimit=/^data\/\d{4}-\d{2}-\d{2}\/nationwide_forecasts\.json$/.test(path)?32*1024*1024:12*1024*1024;
      total+=bytes.length;need(bytes.length<=fileLimit&&total<=LIMIT&&bytes.length===entry.bytes);
      need(await digest(bytes)===entry.sha256);
      const dated=/^data\/(\d{4}-\d{2}-\d{2})\//.exec(path);need(!dated||packet.dates.includes(dated[1]));
      const value=JSON.parse(entry.text);parsed.set(path,value);fileShas.set(path,entry.sha256);
    }
    const results=await resultRecords(parsed,fileShas,cipherSha,packet.dates),days=new Map(packet.dates.slice().sort().map(date=>[date,normalize(date,parsed,fileShas,cipherSha,results)]));
    for(const [date,rows] of days)await jointSupplements(date,parsed,fileShas,rows,packet.files);
    const updates=new Map([...days.keys()].map(date=>[date,resultUpdates(date,parsed)]));
    const frozen=new Map([...days.keys()].map(date=>[date,frozenForecasts(date,parsed)]));
    const nationwide=new Map([...days.keys()].flatMap(date=>{const doc=nationwideDay(date,parsed);return doc?[[date,doc]]:[];}));
    await validateConfidence(days,frozen,nationwide);
    attachNationwide(days,nationwide);
    for(const [date,rows] of days)for(const row of rows){const update=updates.get(date).get(row.id);if(update){row.resultUpdate=update;row.resultHistory=[update];}const original=frozen.get(date).get(row.id);if(original)row.frozenForecast=combineFrozen(row.frozenForecast,original);const history=results.get(row.id)||[];if(history.length){row.researchResultHistory=[...history];row.latestResearchResult=history.at(-1);}}
    return {schema:SCHEMA,dates:[...days.keys()],days,resultUpdates:updates,frozenForecasts:frozen,nationwide,sourceCommit:packet.source_commit,importedAt:packet.imported_at,files:parsed,fileShas,cipherSha,results,formal:false};
  }
  async function openPacket(packet){return decodePacket(packet,null);}
  async function validateConfidence(days,frozen,nationwide){
    const originals=new Set();
    for(const rows of frozen.values())for(const original of rows.values())originals.add(original);
    for(const doc of nationwide.values())for(const row of doc.races)if(row.original)originals.add(row.original);
    for(const original of originals)if(Object.hasOwn(original,'confidence_assessment')){
      need(confidence);await confidence.validateBaseline(original.confidence_assessment,original.baseline,{source:original.facts,sealedAt:original.baseline_sealed_at});
    }
    for(const rows of days.values())for(const row of rows){
      if(Object.hasOwn(row.referenceEnvelope,'confidence_assessment')){
        need(confidence);await confidence.validateBaseline(row.referenceEnvelope.confidence_assessment,row.reference,{source:row.referenceEnvelope.input,raceId:row.id});
      }
      const selected=[[row.original,'3t','normal'],[row.two,'2t','normal'],[row.rollover,'3t','rollover'],[row.two.rollover,'2t','rollover'],...['3t','2t'].map(market=>[row.flexible.markets?.[market],market,'normal'])];
      for(const [raw,market,strategy] of selected)if(raw&&Object.hasOwn(raw,'confidence_assessment')){
        need(confidence);await confidence.validateAuthored(raw,{raceId:row.id,market,strategy});
      }
    }
  }
  function rows(data,date){return data.days.get(date)||[];}
  function historyRows(data,{period='day',day:selectedDay='',from='',to=''}={}){
    if(!data||!Array.isArray(data.dates))return [];
    let dates;
    if(period==='day')dates=day(selectedDay)?data.dates.filter(d=>d===selectedDay):[];
    else if(period==='range')dates=day(from)&&day(to)&&from<=to?data.dates.filter(d=>from<=d&&d<=to):[];
    else if(period==='all')dates=data.dates.slice();
    else return [];
    return dates.sort().reverse().flatMap(date=>rows(data,date));
  }
  const searchText=value=>String(value??'').normalize('NFKC').toLocaleLowerCase('ja');
  function matchesHistory(row,{query='',venue='',raceNumber=''}={}){
    if(venue&&row.venue!==venue||raceNumber!==''&&row.number!==Number(raceNumber))return false;
    const text=searchText([row.venue,row.title,row.id,row.date,row.original?.headline,
      ...(row.riders||[]).map(r=>r.name)].join(' '));
    const parts=searchText(query).replace(/(\d{1,2})r\b/g,' $1r ').trim().split(/\s+/).filter(Boolean);
    return parts.every(term=>{
      const race=/^(\d{1,2})r$/.exec(term);
      if(race)return Number(race[1])>=1&&Number(race[1])<=12&&row.number===Number(race[1]);
      const date=/^(?:(\d{4})[-/])?(\d{1,2})[-/](\d{1,2})$/.exec(term);
      if(date)return (!date[1]||row.date.slice(0,4)===date[1])&&
        Number(row.date.slice(5,7))===Number(date[2])&&Number(row.date.slice(8,10))===Number(date[3]);
      return text.includes(term);
    });
  }
  function historyPage(list,page,size=20){
    const length=Number.isInteger(size)&&size>0&&size<=100?size:20;
    const pages=Math.max(1,Math.ceil(list.length/length));
    page=Math.min(pages,Math.max(1,Number.isInteger(page)?page:1));
    const start=(page-1)*length,items=list.slice(start,start+length);
    return {items,page,pages,total:list.length,first:items.length?start+1:0,last:start+items.length};
  }
  function frozenArm(row,name){
    const frozen=row.frozenForecast;if(!frozen||!['A','B','adjusted_A','adjusted_B'].includes(name))return null;
    const adjusted=name.startsWith('adjusted_'),role=adjusted?name.slice(9):name;if(adjusted&&!frozen.conditioned)return null;
    const arm=adjusted?frozen.conditioned[role+'_research']:frozen.baseline[role];
    const factors=new Map((frozen.conditioned?.B_research.branch_condition_factors||[]).map(f=>[f.scenario_id,f.relative_weight_after]));
    const assessment=!adjusted&&Object.hasOwn(frozen,'confidence_assessment')?confidence.selected(frozen.confidence_assessment,role):{confidence:null,confidenceAssessment:null,confidenceBundle:null};
    return {name,role,adjusted,source:arm,...assessment,tickets:tickets(arm.ranked_tickets,3,new Set(frozen.facts.riders.map(r=>r.car))),
      scenarios:role==='B'?frozen.baseline.B.six_phase_scenarios.map(s=>({...s,relative_research_weight:adjusted?factors.get(s.scenario_id):s.relative_research_weight})):[],
      assessments:adjusted?frozen.conditioned.rider_assessments:[],facts:frozen.facts,generatedAt:frozen.baseline.generated_at,
      sourceAsOf:frozen.baseline.source_as_of,sealedAt:adjusted?frozen.conditioned_sealed_at:frozen.baseline_sealed_at,cutoffAt:frozen.baseline.published_cutoff_at};
  }
  function forecast(row,market='3t',variant='flexible'){
    const places=market==='2t'?2:3;
    if(['A','B','C'].includes(variant)){
      const ref=row.reference[variant]||{};
      const assessment=market==='3t'&&['A','B'].includes(variant)&&Object.hasOwn(row.referenceEnvelope||{},'confidence_assessment')?confidence.selected(row.referenceEnvelope.confidence_assessment,variant):{confidence:null,confidenceAssessment:null,confidenceBundle:null};
      return {label:'参考'+variant,tickets:market==='3t'?tickets(ref.ranked_tickets,3,row.cars):[],scenarios:ref.six_phase_scenarios||[],
        allocatable:false,headline:'既存モデルの研究出力',reason:variant==='C'?'独立した連係履歴が不足しているため未生成':'公開印・統計・並びを使用した参考計算',
        createdAt:row.reference.generated_at,binding:row.bindings?.reference||null,...assessment,risk:'学習済み・校正済みの確率ではありません。',source:ref};
    }
    const base=market==='2t'?row.two:row.original;
    let current=base,assessmentSource=base,label=market==='2t'?'2車単・通常予想':'3連単・通常予想';
    if(variant==='flexible'&&row.flexible.markets?.[market]){assessmentSource=row.flexible.markets[market];current={...base,...assessmentSource,analysis_created_at:assessmentSource.analysis_created_at||row.flexible.analysis_created_at};label=market==='2t'?'2車単・改訂予想':'3連単・改訂予想';}
    if(variant==='rollover'){
      if(market==='3t'&&row.rollover.tickets){current=row.rollover;assessmentSource=current;label='3連単・転がし予想';}
      else if(market==='2t'&&base.rollover?.eligible){assessmentSource=base.rollover;current={...base,...base.rollover,risk:base.rollover.excluded_risk||base.rollover.risk||base.risk};label='2車単・転がし予想';}
      else{assessmentSource={};current={...base,tickets:[],confidence:null,reason:base.rollover?.reason||'このレースは転がし候補に選んでいません。',headline:'転がし候補は見送り'};label='転がし・見送り';}
    }
    const assessment=Object.hasOwn(assessmentSource,'confidence_assessment')?confidence.selected(assessmentSource.confidence_assessment,'selected'):{confidence:text(current.confidence,40),confidenceAssessment:null,confidenceBundle:null};
    return {label,tickets:tickets(current.tickets,places,row.cars),scenarios:[...(current.scenarios||row.original.scenarios||[]),...(current.extra_scenarios||[])],allocatable:true,
      headline:text(current.headline)||text(base.headline)||'予想未取得',reason:text(current.point_reason||current.reason||current.confidence_reason||current.verdict||current.selection_reason),
      ...assessment,risk:text(current.risk),createdAt:current.analysis_created_at,
      binding:row.bindings?.[variant==='rollover'&&market==='3t'?'rollover':variant==='flexible'&&row.flexible.markets?.[market]?'flexible':market==='2t'?'two':'original']||null,source:current};
  }
  function displayedPredictions(row,market='3t',variant='flexible'){
    const saved=(row.nationwideOnly||market==='3t'&&variant!=='rollover')?['A','B','adjusted_A','adjusted_B'].map(name=>frozenArm(row,name)).filter(Boolean):[];
    return row.nationwideOnly?saved:[forecast(row,market,variant),...saved];
  }
  function compare(row,market='3t',variant='A',version=null){
    need(['3t','2t'].includes(market)&&['original','flexible','rollover','A','B','C'].includes(variant));
    const context=version?{...row,reference:version.reference,referenceEnvelope:version.envelope,bindings:{...row.bindings,reference:version.binding}}:row;
    const prediction=forecast(context,market,variant),saved=row.latestResearchResult,observation=saved?.observation;
    const generated=clock(row.date,prediction.createdAt),cutoff=clock(row.date,row.cutoff);
    const score={raceId:row.id,market,variant,status:'RESEARCH_UNKNOWN',ticketCount:prediction.tickets.length,hitAt1:null,hitAtAll:null,stakeYen:prediction.tickets.length*100,payoutYen:null,netYen:null,
      generatedAt:generated,cutoff,predictionBinding:prediction.binding,resultBinding:saved?.binding||null,resultObservationSha256:observation?.observation_sha256||null,
      timingStatus:!generated?'GENERATED_AT_MISSING':!cutoff?'CUTOFF_UNVERIFIED':Date.parse(generated)>=Date.parse(cutoff)?'GENERATED_AFTER_OR_AT_CUTOFF':'RECORDED_PRE_CUTOFF_NOT_FORMAL',formal:false,scope:'CONDITIONAL_RESEARCH_ONLY'};
    const history=row.researchResultHistory||[];
    if(observation&&(!history.length||history[0].observation.previous_observation_sha256!==null||history.at(-1).observation.observation_sha256!==observation.observation_sha256||!history.every((entry,n)=>n===0||entry.observation.previous_observation_sha256===history[n-1].observation.observation_sha256)))return {...score,reason:'RESULT_HISTORY_INCOMPLETE'};
    if(!prediction.tickets.length||!prediction.binding||observation?.state!==MATCHED||observation.race_id!==row.id||!row.cars.size||!observation.winning_triple.every(n=>row.cars.has(n)))return score;
    const combo=observation.winning_triple.slice(0,market==='2t'?2:3).join('-');score.hitAt1=prediction.tickets[0].combo===combo;score.hitAtAll=prediction.tickets.some(t=>t.combo===combo);score.status=score.hitAtAll?'RESEARCH_HIT':'RESEARCH_MISS';
    if(market==='3t'){score.payoutYen=score.hitAtAll?observation.payout_per_100yen:0;score.netYen=score.payoutYen-score.stakeYen;}
    return score;
  }
  function summarize(values,market='3t'){
    need(Array.isArray(values));const unique=new Map(values.map(row=>[row.id,row]));need(unique.size===values.length);
    const pairs=values.map(row=>({A:compare(row,market,'A'),B:compare(row,market,'B')}));
    const arm=(name,subset=pairs)=>{const scores=subset.map(p=>p[name]),known=scores.filter(s=>s.status!=='RESEARCH_UNKNOWN');return {evaluableRaces:known.length,unknownRaces:scores.length-known.length,hitRaces:known.filter(s=>s.hitAtAll).length,ticketCounts:[...new Set(known.map(s=>s.ticketCount))].sort((a,b)=>a-b),stakeYen:known.reduce((n,s)=>n+s.stakeYen,0),payoutYen:known.every(s=>s.payoutYen!==null)?known.reduce((n,s)=>n+s.payoutYen,0):null};};
    const paired=pairs.filter(p=>p.A.status!=='RESEARCH_UNKNOWN'&&p.B.status!=='RESEARCH_UNKNOWN');
    return {raceCount:values.length,pairedRaceCount:paired.length,A:arm('A'),B:arm('B'),paired:{A:arm('A',paired),B:arm('B',paired)},formal:false,improvementProven:false};
  }
  function allocate(prediction,budget,excluded=new Set()){
    need([2000,2500,3000].includes(budget));
    const chosen=prediction.tickets.filter(t=>!excluded.has(t.combo));
    const available=prediction.allocatable&&chosen.length>0&&chosen.length*100<=budget&&chosen.every(t=>['本線','押さえ','波乱'].includes(t.role));
    if(!available)return {available:false,total:0,chosen,amounts:prediction.tickets.map(()=>0)};
    const paid=staking.allocate(chosen,budget),byCombo=new Map(chosen.map((t,i)=>[t.combo,paid[i]]));
    return {available:true,total:budget,chosen,amounts:prediction.tickets.map(t=>byCombo.get(t.combo)||0)};
  }
  function b64(value,max=LIMIT*2){
    need(typeof value==='string'&&value.length>0&&value.length<=max&&value.length%4===0&&!/[^A-Za-z0-9+/=]/.test(value));
    const binary=atob(value);need(btoa(binary)===value);return Uint8Array.from(binary,c=>c.charCodeAt(0));
  }
  async function openCipher(bytes,{cipherSha,key}){
    need(bytes instanceof Uint8Array&&bytes.length<=90*1024*1024&&hex(cipherSha)&&await digest(bytes)===cipherSha);
    const envelope=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
    need(record(envelope)&&Object.keys(envelope).sort().join(',')==='ciphertext,header,nonce');
    const h=envelope.header;need(record(h)&&Object.keys(h).sort().join(',')==='schema,source_content_sha256'&&h.schema===OUTER&&hex(h.source_content_sha256));
    need(typeof key==='string'&&/^[A-Za-z0-9_-]{43}$/.test(key));
    const rawKey=b64(key.replaceAll('-','+').replaceAll('_','/')+'=',44),nonce=b64(envelope.nonce,16),encrypted=b64(envelope.ciphertext);
    need(rawKey.length===32&&nonce.length===12&&encrypted.length>=16);
    const imported=await apiCrypto().subtle.importKey('raw',rawKey,{name:'AES-GCM'},false,['decrypt']);
    const aad=encoder.encode(JSON.stringify({schema:h.schema,source_content_sha256:h.source_content_sha256}));
    const plain=new Uint8Array(await apiCrypto().subtle.decrypt({name:'AES-GCM',iv:nonce,additionalData:aad,tagLength:128},imported,encrypted));
    need(plain.length<=LIMIT&&await digest(plain)===h.source_content_sha256);
    return decodePacket(JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(plain)),cipherSha);
  }
  return {openPacket,openCipher,rows,historyRows,matchesHistory,historyPage,forecast,frozenArm,displayedPredictions,compare,summarize,allocate,resultUpdates,checkedDiagnostics,combineFrozen,mergeNationwide,nationwideSemantic,attachNationwide,safeUrl,digest,clock,instantMicros,sameClock,utc,day,SCHEMA};
});
