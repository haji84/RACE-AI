/* Owner-provided Site view adapter. Original/revised/research records stay separate. */
(function(root,factory){
  if(typeof module==='object'&&module.exports)module.exports=factory(require('./keirin-note-source/staking_flexible.js'));
  else root.RaceKeirinNote=factory(root.KeirinStaking);
})(typeof window==='object'?window:globalThis,function(staking){
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
      tickets(p.tickets,3,cars);tickets(row.two.tickets,2,cars);tickets(row.rollover.tickets,3,cars);
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
  async function decodePacket(packet,cipherSha){
    need(record(packet)&&packet.schema===SCHEMA&&packet.formal_model_admission===false&&packet.production_weight_switch===false&&record(packet.files));
    need(Array.isArray(packet.dates)&&packet.dates.length>0&&packet.dates.every(day)&&new Set(packet.dates).size===packet.dates.length);
    const parsed=new Map(),fileShas=new Map();let total=0;
    for(const [path,entry] of Object.entries(packet.files)){
      need(/^data\/(?:\d{4}-\d{2}-\d{2}\/)?[A-Za-z0-9_.-]+\.json$/.test(path)&&record(entry)&&typeof entry.text==='string'&&hex(entry.sha256));
      const bytes=encoder.encode(entry.text);total+=bytes.length;need(bytes.length<=12*1024*1024&&total<=LIMIT&&bytes.length===entry.bytes);
      need(await digest(bytes)===entry.sha256);
      const dated=/^data\/(\d{4}-\d{2}-\d{2})\//.exec(path);need(!dated||packet.dates.includes(dated[1]));
      const value=JSON.parse(entry.text);parsed.set(path,value);fileShas.set(path,entry.sha256);
    }
    const results=await resultRecords(parsed,fileShas,cipherSha,packet.dates),days=new Map(packet.dates.slice().sort().map(date=>[date,normalize(date,parsed,fileShas,cipherSha,results)]));
    const updates=new Map([...days.keys()].map(date=>[date,resultUpdates(date,parsed)]));
    for(const [date,rows] of days)for(const row of rows){const update=updates.get(date).get(row.id);if(update){row.resultUpdate=update;row.resultHistory=[update];}}
    return {schema:SCHEMA,dates:[...days.keys()],days,resultUpdates:updates,sourceCommit:packet.source_commit,importedAt:packet.imported_at,files:parsed,fileShas,cipherSha,results,formal:false};
  }
  async function openPacket(packet){return decodePacket(packet,null);}
  function rows(data,date){return data.days.get(date)||[];}
  function forecast(row,market='3t',variant='flexible'){
    const places=market==='2t'?2:3;
    if(['A','B','C'].includes(variant)){
      const ref=row.reference[variant]||{};
      return {label:'参考'+variant,tickets:market==='3t'?tickets(ref.ranked_tickets,3,row.cars):[],scenarios:ref.six_phase_scenarios||[],
        allocatable:false,headline:'既存モデルの研究出力',reason:variant==='C'?'独立した連係履歴が不足しているため未生成':'公開印・統計・並びを使用した参考計算',
        createdAt:row.reference.generated_at,binding:row.bindings?.reference||null,confidence:null,risk:'学習済み・校正済みの確率ではありません。',source:ref};
    }
    const base=market==='2t'?row.two:row.original;
    let current=base,label=market==='2t'?'2車単・保存分析':'3連単・原分析';
    if(variant==='flexible'&&row.flexible.markets?.[market]){current={...base,...row.flexible.markets[market],analysis_created_at:row.flexible.analysis_created_at};label=market==='2t'?'2車単・改訂分析':'3連単・改訂分析';}
    if(variant==='rollover'&&market==='3t'&&row.rollover.tickets){current=row.rollover;label='3連単・絞り込み分析';}
    return {label,tickets:tickets(current.tickets,places,row.cars),scenarios:[...(row.original.scenarios||[]),...(current.extra_scenarios||[])],allocatable:true,
      headline:text(current.headline)||text(base.headline)||'予想未取得',reason:text(current.point_reason||current.reason||current.confidence_reason||current.verdict||current.selection_reason),
      confidence:text(current.confidence,40),risk:text(current.risk),createdAt:current.analysis_created_at,
      binding:row.bindings?.[variant==='rollover'&&market==='3t'?'rollover':variant==='flexible'&&row.flexible.markets?.[market]?'flexible':market==='2t'?'two':'original']||null,source:current};
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
  return {openPacket,openCipher,rows,forecast,compare,summarize,allocate,resultUpdates,checkedDiagnostics,safeUrl,digest,clock,utc,day,SCHEMA};
});
