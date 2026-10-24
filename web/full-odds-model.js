"use strict";
/* Full trifecta odds viewer: a separate READ-ONLY consumer of a vetted feed.
 * This file never scores races, selects picks, fetches upstream bookmakers,
 * authorizes collection rights, or changes any frozen forecast.
 */
(function(root,factory){
  const api=factory();
  if(typeof module==="object"&&module.exports)module.exports=api;
  root.RaceFullOdds=api;
})(typeof globalThis!=="undefined"?globalThis:this,function(){
  const SPORTS={boat:[6,6],keirin:[3,9],autorace:[3,8],horse:[3,18]};
  const TIMESTAMP=/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/;
  function bad(s){throw new Error(s);}
  function time(value){return typeof value==="string"&&TIMESTAMP.test(value)&&Number.isFinite(Date.parse(value))?Date.parse(value):null;}
  function key(ticket){return ticket.join("-");}
  function allTickets(participants){
    const out=[];
    for(const a of participants)for(const b of participants)for(const c of participants)
      if(a!==b&&b!==c&&a!==c)out.push([a,b,c]);
    return out;
  }
  function parse(raw){
    if(!raw||raw.schema!=="RACE_AI_FULL_TRIFECTA_ODDS_V1")bad("未対応の全オッズデータ形式");
    if(!["SYNTHETIC_ONLY","PROVIDER_REPORTED_UNVERIFIED"].includes(raw.source_status))
      bad("出典区分が不正");
    if(!Object.hasOwn(SPORTS,raw.sport)||typeof raw.race_id!=="string"||
      !/^[A-Za-z0-9:_-]{5,160}$/.test(raw.race_id))bad("レースID・競技が不正");
    if(typeof raw.venue!=="string"||!raw.venue||raw.venue.length>120||
       !Number.isInteger(raw.race_no)||raw.race_no<1||raw.race_no>99)
      bad("会場またはレース番号が不正");
    if(!/^\d{4}-\d\d-\d\d$/.test(raw.event_date_jst))bad("日付が不正");
    const cutoff=time(raw.cutoff_at),published=time(raw.source_published_at),received=time(raw.ingested_at);
    if(cutoff===null||received===null||
       (raw.source_published_at!==null && (published===null||published>received)))
      bad("オッズ提供・受信時刻が未検証");
    if(!Array.isArray(raw.participants)||new Set(raw.participants).size!==raw.participants.length||
       raw.participants.some(x=>!Number.isInteger(x)||x<1||x>99)||
       raw.participants.length<SPORTS[raw.sport][0]||raw.participants.length>SPORTS[raw.sport][1])
      bad("出走者数・番号が不正");
    const parts=new Intl.DateTimeFormat("en-CA",{
      timeZone:"Asia/Tokyo",year:"numeric",month:"2-digit",day:"2-digit"
    }).formatToParts(new Date(cutoff));
    const part=key=>parts.find(x=>x.type===key)?.value;
    const cutoffDay=part("year")+"-"+part("month")+"-"+part("day");
    if(raw.event_date_jst!==cutoffDay)bad("開催日と締切の不一致");
    if(!["OPEN_REPORTED","CLOSED_REPORTED","UNKNOWN"].includes(raw.sales_status))
      bad("発売状態が不正");
    if(typeof raw.source_url!=="string"||raw.source_url.length>700)bad("出典URLが不正");
    try {
      const source=new URL(raw.source_url);
      if(source.protocol!=="https:"||!source.hostname||source.username||source.password)
        bad("出典URLが不正");
    }catch{bad("出典URLが不正");}
    if(!Array.isArray(raw.odds)||raw.odds.length!==raw.participants.length*(raw.participants.length-1)*(raw.participants.length-2))
      bad("全3連単の組合せが揃っていない");
    const full=new Set(allTickets(raw.participants).map(key)),seen=new Set();
    const rows=raw.odds.map(item=>{
      if(!item||!Array.isArray(item.ticket)||item.ticket.length!==3||
         item.ticket.some(x=>!Number.isInteger(x))||new Set(item.ticket).size!==3||
         !full.has(key(item.ticket))||seen.has(key(item.ticket)))bad("3連単の重複・不正な組合せ");
      seen.add(key(item.ticket));
      if(!["QUOTED","UNAVAILABLE"].includes(item.status)||
         (item.status==="QUOTED"&&
           (typeof item.decimal_odds!=="number"||!Number.isFinite(item.decimal_odds)||item.decimal_odds<1||item.decimal_odds>10000000))||
         (item.status==="UNAVAILABLE"&&item.decimal_odds!==null))
        bad("オッズ値または未取得状態が不正");
      return {ticket:[...item.ticket],decimal_odds:item.decimal_odds,status:item.status};
    });
    if(seen.size!==full.size)bad("有効組合せが欠落");
    return {
      schema:raw.schema,source_status:raw.source_status,race_id:raw.race_id,
      sport:raw.sport,venue:raw.venue,race_no:raw.race_no,
      event_date_jst:raw.event_date_jst,cutoff_at:raw.cutoff_at,
      source_published_at:raw.source_published_at,ingested_at:raw.ingested_at,
      source_url:raw.source_url,sales_status:raw.sales_status,
      participants:[...raw.participants],odds:rows
    };
  }
  function freshness(feed,now=Date.now()){
    if(!feed)return {label:"未取得",stale:true};
    const receivedAge=(now-time(feed.ingested_at))/1000;
    const sourceAge=feed.source_published_at===null?null:
      (now-time(feed.source_published_at))/1000;
    if(!Number.isFinite(receivedAge)||receivedAge<0||
       (sourceAge!==null&&(!Number.isFinite(sourceAge)||sourceAge<0)))
      return {label:"時刻検証不可",stale:true};
    if(now>=time(feed.cutoff_at))return {label:"締切後の参考値（最終確定オッズとは限りません）",stale:true};
    if(sourceAge===null)return {label:"提供元のオッズ更新時刻未確認（受信："+Math.floor(receivedAge)+"秒前）",stale:true};
    if(sourceAge>120)return {label:"提供元の更新遅延：約"+Math.ceil(sourceAge/60)+"分前のオッズ",stale:true};
    if(receivedAge>120)return {label:"RACE-AI配信遅延：約"+Math.ceil(receivedAge/60)+"分前の受信値",stale:true};
    return {label:"受信："+Math.floor(receivedAge)+"秒前 / 提供元："+Math.floor(sourceAge)+"秒前（最新保証なし）",stale:false};
  }
  function initialRowLimit(feed){return feed?.sport==="boat"?120:80;}
  function readDifference(previous,current){
    if(!previous||previous.race_id!==current.race_id)return {kind:"FIRST_READ",changedQuotes:0};
    const old=new Map(previous.odds.map(x=>[key(x.ticket),x.status+":"+x.decimal_odds]));
    let changedQuotes=0;
    for(const x of current.odds)if(old.get(key(x.ticket))!==x.status+":"+x.decimal_odds)changedQuotes++;
    const kind=changedQuotes?"QUOTE_CHANGED":
      previous.source_published_at!==current.source_published_at?"SOURCE_TIME_CHANGED":
      previous.ingested_at!==current.ingested_at?"D1_RECEIPT_CHANGED":"UNCHANGED";
    return {kind,changedQuotes};
  }
  function safariAcceptance(events){
    let consecutiveTimedReads=0,previous=null;
    for(const event of events){
      if(!event?.ok||event.manual_file_mode){consecutiveTimedReads=0;previous=null;continue;}
      const delta=event.gap_seconds;
      if(event.trigger==="timer"){
        consecutiveTimedReads=(previous&&typeof delta==="number"&&
          delta>=55&&delta<=90)?consecutiveTimedReads+1:0;
      }else if(event.trigger!=="initial"){
        consecutiveTimedReads=0;
      }
      previous=event;
    }
    return {confirmedIntervals:consecutiveTimedReads,
      passed:consecutiveTimedReads>=3};
  }
  function select(feed,{first="all",query="",order="ticket"}={}){
    if(!feed)return [];
    const q=String(query).trim().replace(/\s+/g,"");
    if(q&&!/^\d{1,2}(?:-\d{0,2}){0,2}-?$/.test(q))return [];
    const out=feed.odds.filter(x=>(first==="all"||x.ticket[0]===Number(first))&&
      (!q||key(x.ticket).startsWith(q)));
    if(order==="low"||order==="high")out.sort((a,b)=>{
      const av=a.status==="QUOTED"?a.decimal_odds:NaN,bv=b.status==="QUOTED"?b.decimal_odds:NaN;
      if(Number.isNaN(av))return Number.isNaN(bv)?key(a.ticket).localeCompare(key(b.ticket)):1;
      if(Number.isNaN(bv))return -1;
      return (order==="low"?av-bv:bv-av)||key(a.ticket).localeCompare(key(b.ticket));
    });
    else out.sort((a,b)=>a.ticket[0]-b.ticket[0]||a.ticket[1]-b.ticket[1]||a.ticket[2]-b.ticket[2]);
    return out;
  }
  return Object.freeze({parse,select,allTickets,freshness,key,initialRowLimit,readDifference,safariAcceptance});
});
