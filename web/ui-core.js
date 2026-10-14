/* Shared, dependency-free view model. No network access or persisted race data. */
(function(root,factory){
  if(typeof module==='object'&&module.exports) module.exports=factory();
  else root.RaceUI=factory();
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  const venueNames=['桐生','戸田','江戸川','平和島','多摩川','浜名湖','蒲郡','常滑','津','三国','びわこ','住之江','尼崎','鳴門','丸亀','児島','宮島','徳山','下関','若松','芦屋','福岡','唐津','大村'];
  const pages=['home','races','detail','picks','results','research','settings'];
  const racePattern=/^(\d{8})-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])$/;
  function dayJst(now=new Date()){
    const p=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(now);
    return ['year','month','day'].map(t=>p.find(v=>v.type===t).value).join('-');
  }
  function validDate(value){return typeof value==='string'&&/^\d{4}-\d\d-\d\d$/.test(value)&&Number.isFinite(Date.parse(value+'T00:00:00Z'))&&new Date(value+'T00:00:00Z').toISOString().slice(0,10)===value;}
  function zoned(value){return typeof value==='string'&&/T.*(Z|[+-]\d\d:\d\d)$/.test(value)&&Number.isFinite(Date.parse(value));}
  function noEvent(value){return value?.status==='NO_EVENT'||value?.no_event===true;}
  function scheduleProven(venue,report){
    if(venue?.schedule_verified!==true||!zoned(venue.schedule_observed_at)||dayJst(new Date(venue.schedule_observed_at))!==report.date_jst||Date.parse(venue.schedule_observed_at)>Date.now()+60000)return false;
    return Array.isArray(report.sources)&&report.sources.filter(s=>s.source_url===venue.schedule_source_url&&s.source_sha256===venue.schedule_source_sha256&&s.first_observed_at===venue.schedule_observed_at&&typeof s.source_url==='string'&&s.source_url.startsWith('https://')&&/^[a-f0-9]{64}$/.test(s.source_sha256||'')).length===1;
  }
  function emptyDayProven(report){return report.status==='NO_EVENT'&&report.no_event===true&&Array.isArray(report.active_venues)&&report.active_venues.length===0&&scheduleProven(report,report);}
  function validateReport(raw,options={}){
    if(!raw||typeof raw!=='object'||Array.isArray(raw)) throw new Error('JSONの形式が正しくありません。');
    if(!validDate(raw.date_jst)) throw new Error('対象日が不正です。');
    if(options.automatic&&raw.date_jst!==options.today) throw new Error('対象日が本日ではありません。');
    if(options.automatic&&raw.redistribution_authorized!==true) throw new Error('再配信許可を確認できません。');
    if(!zoned(raw.first_observed_at)) throw new Error('初回確認時刻に時差情報がありません。');
    if(dayJst(new Date(raw.first_observed_at))!==raw.date_jst)throw new Error('取得時刻と対象日が一致していません。');
    if(Date.parse(raw.first_observed_at)>(options.now??Date.now())+60000) throw new Error('取得時刻が未来です。');
    let source;try{source=new URL(raw.source_url);}catch{throw new Error('取得元の証拠情報が不足しています。');}
    if(source.protocol!=='https:'||source.username||source.password||!/^[a-f0-9]{64}$/.test(raw.source_sha256||'')) throw new Error('取得元の証拠情報が不足しています。');
    if(!Array.isArray(raw.venues)||raw.venues.length>24||(!raw.venues.length&&!emptyDayProven(raw))) throw new Error('開催場データが不正です。');
    const codes=new Set();let count=0,complete=0;
    for(const venue of raw.venues){
      if(!venue||!/^(0[1-9]|1\d|2[0-4])$/.test(venue.venue||'')||codes.has(venue.venue)||!Array.isArray(venue.races)||venue.races.length>12||(!venue.races.length&&(!['NO_EVENT','UNOBTAINED','ERROR','PARTIAL'].includes(venue.status)||!scheduleProven(venue,raw)))) throw new Error('開催場・レース一覧に矛盾があります。');
      if(noEvent(venue)&&(!scheduleProven(venue,raw)||venue.races.length))throw new Error('開催なしの証拠情報に矛盾があります。');
      if(!venue.races.length&&(noEvent(venue)?venue.no_event!==true||venue.status!=='NO_EVENT'||venue.schedule_basis!=='NOT_LISTED_IN_COMPLETE_DAY_INDEX':venue.no_event!==false||venue.schedule_basis!=='LISTED_IN_COMPLETE_DAY_INDEX'))throw new Error('開催場の確認根拠が不正です。');
      codes.add(venue.venue);const ids=new Set();
      for(const race of venue.races){
        const match=typeof race.race_id==='string'&&race.race_id.match(racePattern);
        if(!match||match[1]!==raw.date_jst.replaceAll('-','')||match[2]!==venue.venue||ids.has(race.race_id)||!Array.isArray(race.boats)||race.boats.length<1||race.boats.length>6) throw new Error('レース識別子または艇数が不正です。');
        ids.add(race.race_id);const lanes=new Set(),racers=new Set(),motors=new Set();
        for(const boat of race.boats){
          if(!boat||!Number.isInteger(boat.lane)||boat.lane<1||boat.lane>6||lanes.has(boat.lane)||!/^\d{4}$/.test(boat.racer_registration_id||'')||racers.has(boat.racer_registration_id)|| (boat.motor_no!=null&&(!Number.isInteger(boat.motor_no)||boat.motor_no<1||boat.motor_no>999||motors.has(boat.motor_no)))) throw new Error('艇・選手・モーターの記録が不正です。');
          lanes.add(boat.lane);racers.add(boat.racer_registration_id);if(boat.motor_no!=null)motors.add(boat.motor_no);
        }
        count++;if(race.boats.length===6)complete++;
      }
    }
    if(raw.races!==undefined&&raw.races!==count)throw new Error('レース総数に矛盾があります。');
    if(raw.complete_six_boat_races!==undefined&&raw.complete_six_boat_races!==complete)throw new Error('6艇の集計値に矛盾があります。');
    return {...raw,races:count,complete_six_boat_races:complete};
  }
  function venueState(report,code){
    if(!report)return 'unobtained';const venue=report.venues.find(v=>v.venue===code);
    if(venue?.races?.length)return 'ready';
    if(!report.venues.length&&emptyDayProven(report))return 'no-event';
    if(noEvent(venue)&&scheduleProven(venue,report))return 'no-event';
    return venue?.status==='ERROR'?'error':'unobtained';
  }
  function allRaces(report){return (report?.venues||[]).flatMap(v=>v.races.map(r=>({...r,venue:v.venue,venueName:venueNames[Number(v.venue)-1],date_jst:report.date_jst})));}
  function cutoff(race,day){
    let value=race?.closed_at;
    if(typeof value==='string'&&/^\d\d:\d\d(?::\d\d)?$/.test(value))value=day+'T'+value+'+09:00';
    if(!zoned(value)||dayJst(new Date(value))!==day)return null;
    return Date.parse(value);
  }
  function purchaseAvailability(race,day,now=Date.now()){
    if(!race)return {allowed:false,reason:'レースを選択してください。'};
    if(['CANCELLED','POSTPONED','VOID'].includes(race.status)||race.result_available===true)return {allowed:false,reason:'終了・中止・延期のため新規記録を停止しています。'};
    const closes=cutoff(race,day);
    if(closes===null)return {allowed:false,reason:'締切時刻が未取得のため、新規記録を停止しています。'};
    if(now>=closes)return {allowed:false,reason:'締切時刻を過ぎているため、新規記録を停止しています。'};
    return {allowed:true,reason:'締切前・手動記録のみ'};
  }
  function timeLabel(race,day){const c=cutoff(race,day);return c===null?'未取得':new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',hour:'2-digit',minute:'2-digit',hour12:false}).format(c);}
  function filterRaces(report,filter={}){
    const q=(filter.query||'').trim().toLocaleLowerCase('ja');
    const rows=allRaces(report).filter(r=>(!filter.venue||r.venue===filter.venue)&&(!filter.number||Number(r.race_id.slice(-2))===Number(filter.number))&&(!q||[r.venueName,r.race_id,Number(r.race_id.slice(-2))+'R',...r.boats.flatMap(b=>[b.name,b.racer_registration_id])].filter(Boolean).join(' ').toLocaleLowerCase('ja').includes(q)));
    return rows.sort((a,b)=>filter.sort==='time'?(cutoff(a,report.date_jst)??Infinity)-(cutoff(b,report.date_jst)??Infinity)||a.race_id.localeCompare(b.race_id):a.race_id.localeCompare(b.race_id));
  }
  function parseRoute(hash){
    const parts=(hash||'').replace(/^#\/?/,'').split('/');
    return {page:pages.includes(parts[0])?parts[0]:'home',raceId:racePattern.test(parts[1]||'')?parts[1]:null};
  }
  function text(value){return (typeof value==='string'&&value.trim())?value.slice(0,100):typeof value==='number'&&Number.isFinite(value)?String(value):'未取得';}
  const updateKinds=['beforeinfo','odds3t','raceresult'];
  const marketSizes={trifecta:3,trio:3,exacta:2,quinella:2,quinella_place:2,win:1,place:1};
  function validateRaceBundle(raw,{race,dateJst,now=Date.now()}={}){
    const fail=message=>{throw new Error(message||'レース更新データの形式を確認できません。');};
    const hash=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
    const stamp=value=>{if(!zoned(value))fail('取得時刻の形式が不正です。');const n=Date.parse(value);if(n>now+60000||dayJst(new Date(n))!==dateJst)fail('取得時刻と対象日を確認できません。');return n;};
    const measure=(value,low,high)=>value===null||value===undefined||(typeof value==='number'&&Number.isFinite(value)&&value>=low&&value<=high);
    if(!race||!raw||raw.schema_version!==1||raw.race_id!==race.race_id||raw.date_jst!==dateJst||!hash(raw.program_sha256)||!Array.isArray(raw.records)||raw.records.length>3||!raw.latest||typeof raw.latest!=='object'||Array.isArray(raw.latest))fail('対象レース・日付が一致していません。');
    const closing=cutoff(race,dateJst);if(closing===null||!zoned(raw.closed_at)||Date.parse(raw.closed_at)!==closing)fail('レースの締切時刻が一致していません。');
    const published=stamp(raw.published_at),program=new Map(race.boats.map(b=>[b.lane,b])),ids=new Set(),kinds=new Set();
    const canonical=value=>typeof value==='string'?value.normalize('NFKC').replace(/\s/g,''):'';
    for(const wrapper of raw.records){
      const record=wrapper?.record,kind=record?.kind;
      if(!record||record.schema_version!==1||record.race_id!==race.race_id||!updateKinds.includes(kind)||kinds.has(kind)||!hash(record.snapshot_id)||ids.has(record.snapshot_id)||!hash(record.source_sha256)||wrapper.program_sha256!==raw.program_sha256||raw.latest[kind]!==record.snapshot_id||!['AVAILABLE','PARTIAL','PENDING'].includes(record.status))fail();
      ids.add(record.snapshot_id);kinds.add(kind);
      let source;try{source=new URL(record.source_url);}catch{fail('取得元を確認できません。');}
      const [,venue,number]=race.race_id.split('-');
      if(source.protocol!=='https:'||source.hostname!=='www.boatrace.jp'||source.port||source.username||source.password||source.hash||source.pathname!=='/owpc/pc/race/'+kind||source.searchParams.getAll('hd').join()!==dateJst.replaceAll('-','')||source.searchParams.getAll('jcd').join()!==venue||Number(source.searchParams.get('rno'))!==Number(number)||source.searchParams.getAll('rno').length!==1)fail('取得元と対象レースが一致していません。');
      const captured=stamp(record.captured_at),available=stamp(record.available_at),saved=stamp(record.saved_at),cloud=stamp(wrapper.cloud_saved_at);
      if(available!==captured||captured>saved||saved>cloud||cloud>published||record.upstream_published_at!==null)fail('取得・保存時刻の順序が不正です。');
      const data=record.data,verified=record.body_identity_verified===true,final=kind==='odds3t'&&data?.odds_phase==='final';
      const phase=kind==='raceresult'?'official_result':final?'final_market':'pre_race_observation';
      const eligible=verified&&kind!=='raceresult'&&captured<closing&&!final;
      if(record.information_phase!==phase||record.eligible_pre_race!==eligible||record.storage_eligible_pre_race!==(eligible&&saved<closing)||wrapper.cloud_eligible_pre_race!==(eligible&&saved<closing&&cloud<closing))fail('締切前後の区分が不正です。');
      if(verified&&(!zoned(record.closed_at)||Date.parse(record.closed_at)!==closing))fail('出走表と更新情報の締切が一致していません。');
      if(!verified&&(record.status!=='PENDING'||data!==null))fail('未確認の出走データは表示できません。');
      if(data===null)continue;
      if(!data||typeof data!=='object'||Array.isArray(data))fail();
      const rows=kind==='beforeinfo'?data.boats:kind==='raceresult'?data.results:data.racers;
      const emptyDisposition=kind==='raceresult'&&['cancelled','no_contest','postponed'].includes(data.status)&&Array.isArray(rows)&&!rows.length;
      if(!emptyDisposition){
        if(!Array.isArray(rows)||rows.length!==6||new Set(rows.map(b=>b.lane)).size!==6)fail('6艇の選手照合が一致していません。');
        for(const row of rows){const entry=program.get(row.lane);if(!entry)fail('艇番が一致していません。');if(kind==='odds3t'?(canonical(row.name)!==canonical(entry.name)||![null,entry.racer_registration_id].includes(row.racer_registration_id)):row.racer_registration_id!==entry.racer_registration_id)fail('登録番号・選手が出走表と一致していません。');}
      }
      if(kind==='beforeinfo'){
        for(const b of rows)if(!measure(b.display_time,0,100)||!measure(b.preview_st,0,1)||!measure(b.tilt,-10,10)||b.actual_course!=null||['actual_st','finish','payouts','result_course'].some(key=>key in b)||(b.preview_course!=null&&(!Number.isInteger(b.preview_course)||b.preview_course<1||b.preview_course>6)))fail('展示情報に矛盾があります。');
        const w=data.weather||{};for(const [key,low,high]of [['wind_speed_mps',0,100],['wave_height_cm',0,1000],['air_temperature_c',-40,60],['water_temperature_c',-10,60]])if(!measure(w[key],low,high))fail('気象情報の数値が不正です。');
      }
      if(kind==='odds3t'){
        if(!['observed','final'].includes(data.odds_phase)||!Array.isArray(data.odds)||data.odds.length!==120)fail('3連単120通りのオッズを確認できません。');
        const combinations=new Set();let count=0;
        for(const row of data.odds){const combo=row.combination,key=Array.isArray(combo)?combo.join('-'):'';if(!Array.isArray(combo)||combo.length!==3||new Set(combo).size!==3||combo.some(n=>!Number.isInteger(n)||n<1||n>6)||combinations.has(key))fail('買い目の識別子が不正です。');combinations.add(key);if(row.odds!==null){if(typeof row.odds!=='string'||!/^\d+(?:\.\d{1,2})?$/.test(row.odds)||Number(row.odds)<1||Number(row.odds)>1000000||row.availability!=='AVAILABLE')fail('オッズの数値が不正です。');count++;}else if(row.availability!=='PENDING')fail('未取得オッズの区分が不正です。');}
        if(record.status!==(count===120?'AVAILABLE':count?'PARTIAL':'PENDING'))fail('オッズの取得状態に矛盾があります。');
      }
      if(kind==='raceresult'){
        if(!['settled','dead_heat','special','cancelled','no_contest','postponed'].includes(data.status)||typeof data.confirmed!=='boolean'||typeof data.settlement_ready!=='boolean'||(data.finish_confirmed!==undefined&&typeof data.finish_confirmed!=='boolean'))fail('結果の確認状態が不正です。');
        if(!emptyDisposition&&captured<closing)fail('締切前の結果を表示できません。');
        for(const row of rows)if((row.finish!=null&&(!Number.isInteger(row.finish)||row.finish<1||row.finish>6))||!measure(row.actual_st,0,1)||(row.actual_course!=null&&(!Number.isInteger(row.actual_course)||row.actual_course<1||row.actual_course>6)))fail('本番の着順・STが不正です。');
        for(const field of ['payouts','special_payouts','verified_market_types','refund_boats'])if(!Array.isArray(data[field]))fail('結果・払戻の確認情報が不足しています。');
        for(const p of [...data.payouts,...data.special_payouts]){if(!marketSizes[p.bet_type]||!Number.isSafeInteger(p.payout_per_100_yen)||p.payout_per_100_yen<=0)fail('確定払戻の数値が不正です。');if(p.combination&&(!Array.isArray(p.combination)||p.combination.length!==marketSizes[p.bet_type]||new Set(p.combination).size!==p.combination.length||p.combination.some(n=>!Number.isInteger(n)||n<1||n>6)))fail('払戻の買い目が不正です。');}
        if(data.refund_boats.some(n=>!Number.isInteger(n)||n<1||n>6)||new Set(data.refund_boats).size!==data.refund_boats.length)fail('返還艇が不正です。');
      }
    }
    if(Object.keys(raw.latest).length!==raw.records.length||Object.entries(raw.latest).some(([kind,id])=>!updateKinds.includes(kind)||!ids.has(id)))fail('最新の更新情報が一致していません。');
    return raw;
  }
  function raceUpdatePhase(wrapper,closed){
    const r=wrapper.record;if(r.kind==='raceresult')return {label:'公式結果・事後情報',preRace:false};
    if(r.kind==='odds3t'&&r.data?.odds_phase==='final')return {label:'締切時オッズ・事前予想には使用しません',preRace:false};
    if(wrapper.cloud_eligible_pre_race===true)return {label:'締切前に取得・保存',preRace:true};
    return {label:Date.parse(r.captured_at)>=Date.parse(closed)?'締切後に取得・事前予想には使用しません':'締切後に保存・事前予想には使用しません',preRace:false};
  }
  function sortedOdds(record){return (record?.data?.odds||[]).slice().sort((a,b)=>(a.odds===null?Infinity:Number(a.odds))-(b.odds===null?Infinity:Number(b.odds))||a.combination.join('').localeCompare(b.combination.join('')));}
  function confirmedResultView(record){
    const d=record?.kind==='raceresult'&&record.status!=='PENDING'?record.data:null;
    if(!d)return {results:[],payouts:[],specialPayouts:[],refundLabel:'未確定',status:'pending'};
    const verified=kind=>d.verified_market_types?.includes(kind)&&['VERIFIED','VERIFIED_EXPLICIT_SPECIAL_PAYOUT'].includes(d.winning_coverage_status?.[kind]);
    return {results:d.finish_confirmed===true?d.results:[],payouts:(d.payouts||[]).filter(p=>verified(p.bet_type)),specialPayouts:(d.special_payouts||[]).filter(p=>verified(p.bet_type)),status:d.status,
      refundLabel:d.confirmed===true&&d.refund_policy_status==='EXPLICIT_FULL_RACE_REFUND'?'全額返還を確認':d.refund_policy_status==='NO_RETURNED_BOATS'&&Array.isArray(d.refunds)?'返還艇なし（取得時点）':'返還処理は未確定'};
  }
  function validatePredictionReceipt(raw,{race,dateJst,now=Date.now()}={}){
    const fail=message=>{throw new Error(message||'研究予測データの形式を確認できません。');};
    const hash=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
    const time=value=>{if(!zoned(value))fail('予測・保存時刻の形式が不正です。');const n=Date.parse(value);if(n>now+60000||dayJst(new Date(n))!==dateJst)fail('予測・保存時刻と対象日が一致していません。');return n;};
    const probability=value=>typeof value==='number'&&Number.isFinite(value)&&value>0&&value<1;
    const near=(a,b)=>Math.abs(a-b)<1e-8;
    const research=value=>value?.research_only===true&&value.validation_status==='UNVALIDATED'&&value.purchase_decision==='skip'&&Array.isArray(value.purchase_recommendations)&&!value.purchase_recommendations.length;
    const s=raw?.snapshot,closing=race?cutoff(race,dateJst):null;
    if(!race||closing===null||raw?.schema_version!==1||typeof raw.request_id!=='string'||!/^([1-9][0-9]{0,19})-([1-9][0-9]{0,3})$/.test(raw.request_id)||raw.cloud_eligible_pre_race!==true||!s||s.schema_version!==1||s.race_id!==race.race_id||s.date_jst!==dateJst||!hash(s.snapshot_id)||!hash(s.program_sha256)||raw.program_sha256!==s.program_sha256||!research(s))fail('研究用の予測・対象レースを確認できません。');
    if(!zoned(s.closed_at)||Date.parse(s.closed_at)!==closing)fail('予測と出走表の締切時刻が一致していません。');
    const asof=time(s.as_of),generated=time(s.generated_at),cloud=time(raw.cloud_saved_at);
    if(!(asof<=generated&&generated<=cloud&&cloud<closing))fail('締切前に生成・保存された予測ではありません。');
    const source=s.program_source;let url;try{url=new URL(source?.source_url);}catch{fail('番組表の取得元を確認できません。');}
    if(url.protocol!=='https:'||url.hostname!=='www1.mbrace.or.jp'||url.port||url.username||url.password||url.hash||url.search||url.pathname!=='/od2/B/'+dateJst.slice(0,7).replace('-','')+'/b'+dateJst.slice(2).replaceAll('-','')+'.lzh'||source.source_sha256!==s.program_sha256)fail('研究予測と公式番組表の出典が一致していません。');
    const captured=time(source.captured_at);if(captured>asof)fail('予測時点より後の番組表は使用できません。');
    const program=new Map(race.boats.map(b=>[b.lane,b])),boats=s.program_boats;
    if(program.size!==6||!Array.isArray(boats)||boats.length!==6||new Set(boats.map(b=>b.lane)).size!==6)fail('研究予測には照合済みの6艇が必要です。');
    const canonical=value=>typeof value==='string'?value.normalize('NFKC').replace(/\s/g,''):'';
    const ratings=new Map();
    for(const b of boats){const expected=program.get(b.lane),rate=b.national_win_rate;if(!expected||b.racer_registration_id!==expected.racer_registration_id||canonical(b.name)!==canonical(expected.name)||(rate!==null&&(typeof rate!=='number'||!Number.isFinite(rate)||rate<0||rate>10)))fail('予測に使った選手・全国勝率を確認できません。');ratings.set(b.lane,rate);}
    const expectedModels=[...ratings.values()].every(rate=>rate!==null)?2:1;
    if(!Array.isArray(s.models)||s.models.length!==expectedModels)fail('比較モデルの構成が不正です。');
    const modelIds=new Set(),positions=['first','second','third','fourth','fifth','sixth'];
    for(const model of s.models){
      const uniform=model.model_id==='official-program-uniform-pl';
      if(!['official-program-uniform-pl','official-program-rating-pl'].includes(model.model_id)||modelIds.has(model.model_id)||model.model_version!=='1'||model.race_id!==race.race_id||!hash(model.content_sha256)||!research(model)||model.uncertainty?.not_calibrated!==true)fail('未検証の固定比較モデルではありません。');modelIds.add(model.model_id);
      if(!uniform&&expectedModels!==2)fail('全国勝率が不足しているため得点比較は表示できません。');
      if(!zoned(model.race_start_at)||!zoned(model.inputs?.race_start_at)||Date.parse(model.race_start_at)!==closing||Date.parse(model.inputs.race_start_at)!==closing)fail('モデルの締切時刻が一致していません。');
      for(const [field,want]of [['as_of',asof],['generated_at',generated]])if(time(model[field])!==want||time(model.inputs?.[field])!==want)fail('モデルの予測時点が一致していません。');
      if(model.inputs.race_id!==race.race_id||model.inputs.model_id!==model.model_id||model.inputs.model_version!==model.model_version||!Array.isArray(model.inputs.boats)||model.inputs.boats.length!==6||new Set(model.inputs.boats.map(b=>b.lane)).size!==6)fail('モデル入力と対象レースが一致していません。');
      const strengths=new Map();for(const b of model.inputs.boats){const expected=program.get(b.lane),strength=uniform?1:Math.max(ratings.get(b.lane),0.01);if(!expected||b.racer_id!==expected.racer_registration_id||typeof b.strength!=='number'||!Number.isFinite(b.strength)||!near(b.strength,strength)||b.feature_kind!==(uniform?'uniform_baseline':'pre_race_strength')||b.source_ref!=='official-b:'+s.program_sha256||Object.keys(b).some(key=>!['lane','racer_id','strength','available_at','captured_at','generated_at','source_ref','feature_kind'].includes(key)))fail('研究モデルに対象外の特徴量が含まれています。');for(const field of ['available_at','captured_at','generated_at'])if(time(b[field])!==captured)fail('入力情報の取得時点が一致していません。');strengths.set(b.lane,b.strength);}
      if(!Array.isArray(model.strengths)||model.strengths.length!==6||new Set(model.strengths.map(b=>b.lane)).size!==6||model.strengths.some(b=>!near(b.strength,strengths.get(b.lane))))fail('比較用の強さが入力値と一致していません。');
      if(!Array.isArray(model.triples)||model.triples.length!==120)fail('3連単120通りの予測が不足しています。');
      const combinations=new Set(),rankSums=Array.from({length:3},()=>new Map());let mass=0;
      for(const row of model.triples){const combo=row.combination,key=Array.isArray(combo)?combo.join('-'):'';if(!Array.isArray(combo)||combo.length!==3||new Set(combo).size!==3||combo.some(n=>!Number.isInteger(n)||n<1||n>6)||combinations.has(key)||!probability(row.probability))fail('買い目の識別子・確率が不正です。');combinations.add(key);mass+=row.probability;combo.forEach((lane,index)=>rankSums[index].set(lane,(rankSums[index].get(lane)||0)+row.probability));if(uniform&&!near(row.probability,1/120))fail('均等な比較モデルに確率差を付けることはできません。');}
      if(!near(mass,1))fail('120通りの確率合計が100％になっていません。');
      if(!Array.isArray(model.marginals)||model.marginals.length!==6||new Set(model.marginals.map(b=>b.lane)).size!==6)fail('6艇の着順確率が不足しています。');const columns=Array(6).fill(0);
      for(const row of model.marginals){if(!program.has(row.lane))fail('着順確率の艇番が一致していません。');let sum=0,top3=0;positions.forEach((position,index)=>{const p=row[position+'_probability'];if(!probability(p))fail('着順確率の数値が不正です。');sum+=p;columns[index]+=p;if(index<3){top3+=p;if(!near(p,rankSums[index].get(row.lane)))fail('3連単と着順確率が一致していません。');}if(uniform&&!near(p,1/6))fail('均等比較の着順確率が不正です。');});if(!near(sum,1)||!probability(row.top3_probability)||!near(top3,row.top3_probability))fail('着順確率の合計が一致していません。');}
      if(columns.some(sum=>!near(sum,1)))fail('艇全体の着順確率合計が一致していません。');
    }
    if(!modelIds.has('official-program-uniform-pl')||(expectedModels===2&&!modelIds.has('official-program-rating-pl')))fail('必要な比較モデルがありません。');
    return raw;
  }
  function sortedPredictionTriples(model){return (model?.triples||[]).slice().sort((a,b)=>b.probability-a.probability||a.combination.join('').localeCompare(b.combination.join('')));}
  return {venueNames,pages,dayJst,validateReport,venueState,allRaces,filterRaces,cutoff,purchaseAvailability,timeLabel,parseRoute,text,validateRaceBundle,raceUpdatePhase,sortedOdds,confirmedResultView,validatePredictionReceipt,sortedPredictionTriples};
});
