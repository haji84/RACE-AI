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
  return {venueNames,pages,dayJst,validateReport,venueState,allRaces,filterRaces,cutoff,purchaseAvailability,timeLabel,parseRoute,text};
});
