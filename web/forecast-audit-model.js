"use strict";
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.RaceAuditModel = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const allowedSports = ["boat", "keirin", "autorace", "horse"];
  const displaySport = {boat:"ボート",keirin:"競輪",autorace:"オート",horse:"競馬"};
  const digestPattern = /^[a-f0-9]{64}$/i;
  const isTimestamp = x => typeof x === "string" && /T\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(x) && Number.isFinite(Date.parse(x));
  const ticket = v => Array.isArray(v) && v.length === 3 && v.every(x => Number.isInteger(x) && x > 0 && x <= 99) && new Set(v).size === 3;
  const ticketKey = v => v.join("-");
  function fail(message) {throw new Error(message);}
  function raceDay(r) {
    const fromId = typeof r.race_id === "string" ? r.race_id.match(/\d{4}-\d{2}-\d{2}/)?.[0] : null;
    const day = r.event_date_jst || fromId;
    return day && /^\d{4}-\d\d-\d\d$/.test(day) && !Number.isNaN(Date.parse(day+"T00:00:00Z")) ? day : null;
  }
  function jstToday(now=new Date()) {
    const parts=new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Tokyo",year:"numeric",month:"2-digit",day:"2-digit"}).formatToParts(now);
    const field=type=>parts.find(p=>p.type===type).value;
    return field("year")+"-"+field("month")+"-"+field("day");
  }
  function monday(day) {
    const d=new Date(day+"T00:00:00Z");
    if(!Number.isFinite(d.getTime()))fail("日付の形式が不正です。");
    d.setUTCDate(d.getUTCDate()-((d.getUTCDay()+6)%7));
    return d.toISOString().slice(0,10);
  }
  function inPeriod(row,period,anchor=jstToday()) {
    const day=raceDay(row);
    if(!day)return period==="all";
    if(period==="all")return true;
    if(period==="today")return day===anchor;
    if(period==="week"){const start=monday(anchor);const end=new Date(start+"T00:00:00Z");end.setUTCDate(end.getUTCDate()+7);return day>=start&&day<end.toISOString().slice(0,10);}
    return period===day;
  }
  function parse(raw) {
    if(!raw || raw.schema!=="RACE_AI_FORECAST_AUDIT_V1")fail("未対応のデータ形式です。");
    if(!["AUDIT_ONLY","REAL_REPORTED","SYNTHETIC_ONLY"].includes(raw.dataset_status))fail("データ種別が不正です。");
    if(!Array.isArray(raw.records)||raw.records.length>10000)fail("レース配列が不正です。");
    const seen=new Set();
    const records=raw.records.map((r,i)=>{
      if(!r||typeof r.race_id!=="string"||r.race_id.length>250||!r.race_id)fail("レースIDが不正です: "+i);
      if(seen.has(r.race_id))fail("同じレースIDの重複があります: "+r.race_id);
      seen.add(r.race_id);
      if(!allowedSports.includes(r.sport)||typeof r.venue!=="string"||!r.venue||r.venue.length>100||
         !Number.isInteger(r.race_no)||r.race_no<1||r.race_no>99)fail("競技・会場・レース番号が不正です。");
      if(r.event_date_jst!=null&&raceDay(r)!==r.event_date_jst)fail("JST開催日が不正です。");
      if(r.cutoff_at!=null&&!isTimestamp(r.cutoff_at))fail("締切時刻が不正です: "+r.race_id);
      if(!["TRIFECTA_OFFERED","NOT_OFFERED","UNKNOWN"].includes(r.offering_status))fail("券種発売の状態が不正です。");
      if(r.prediction!=null) {
        const p=r.prediction;
        if(!Array.isArray(p.ordered_top8)||!p.ordered_top8.length||p.ordered_top8.length>8||
           p.ordered_top8.some(v=>!ticket(v))||new Set(p.ordered_top8.map(ticketKey)).size!==p.ordered_top8.length)
          fail("3連単予想が不正です: "+r.race_id);
        if(!isTimestamp(p.generated_at)||!isTimestamp(p.persisted_at)||!isTimestamp(p.cutoff_at)||
           !digestPattern.test(p.input_sha256||"")||!digestPattern.test(p.prediction_sha256||"")||
           typeof p.model_version!=="string"||!p.model_version||p.model_version.length>100||
           p.odds_independent!==true)fail("予想時刻・証拠・オッズ分離が不正です: "+r.race_id);
        if(Object.keys(p).some(k=>k!=="odds_independent"&&/odds|popularity|market|確定配当|人気/i.test(k)))fail("予想へ市場由来の値を混ぜないでください。");
      }
      const checkResult=(v)=>{
        if(!v||!["final","void","pending","unsupported"].includes(v.status)||
           !Array.isArray(v.winning_combinations)||v.winning_combinations.some(x=>!ticket(x))||
           (v.status==="final"&&v.winning_combinations.length===0)||
           (v.status!=="final"&&v.winning_combinations.length>0))fail("確定結果の形式が不正です: "+r.race_id);
        if(v.confirmed_at!=null&&!isTimestamp(v.confirmed_at))fail("結果発表時刻が不正です。");
        if(v.payout_yen_per_100!=null&&(!Number.isSafeInteger(v.payout_yen_per_100)||v.payout_yen_per_100<0))fail("公式払戻が不正です。");
      };
      if(r.result!=null)checkResult(r.result);
      if(r.result_revisions!=null){
        if(!Array.isArray(r.result_revisions)||r.result_revisions.length>100)fail("結果改訂履歴が不正です。");
        let last=0;
        for(const rev of r.result_revisions){
          checkResult(rev);
          if(!Number.isInteger(rev.revision_no)||rev.revision_no<=last)fail("結果改訂の版が不正です。");
          last=rev.revision_no;
        }
        if(r.result_revisions.length&&r.result!=null){
          const latest=r.result_revisions.at(-1);
          if(latest.status!==r.result.status||
             JSON.stringify(latest.winning_combinations)!==JSON.stringify(r.result.winning_combinations))
            fail("最新の公式結果と改訂履歴が一致しません。");
        }
      }
      if(r.actual_purchase!=null){
        const a=r.actual_purchase;
        if(a.confirmed!==true||["stake_yen","payout_yen","refund_yen"].some(k=>!Number.isSafeInteger(a[k])||a[k]<0))
          fail("実購入記録が不正です。");
      }
      return r;
    });
    return {dataset_status:raw.dataset_status,event_date_jst:raw.event_date_jst||"不明",provenance_urls:Array.isArray(raw.provenance_urls)?raw.provenance_urls:[],records};
  }
  function eligibleFreeze(r){
    const p=r.prediction;
    return !!(p&&r.cutoff_at&&p.odds_independent===true&&
      Date.parse(p.generated_at)<=Date.parse(p.persisted_at)&&
      Date.parse(p.persisted_at)<Date.parse(p.cutoff_at)&&
      Date.parse(p.cutoff_at)===Date.parse(r.cutoff_at)&&
      p.external_receipt_verified===true);
  }
  function status(r){
    if(r.prediction)return eligibleFreeze(r)?"FROZEN_REPORTED":"PREDICTION_UNVERIFIED";
    return "NO_FORECAST";
  }
  function score(r){
    if(r.offering_status!=="TRIFECTA_OFFERED"||!r.result||r.result.status!=="final")return null;
    return !!(eligibleFreeze(r)&&r.result.winning_combinations.some(w=>r.prediction.ordered_top8.some(t=>ticketKey(t)===ticketKey(w))));
  }
  function outcome(r){
    if(r.offering_status==="NOT_OFFERED")return "NOT_OFFERED";
    if(r.result?.status==="void"||r.result?.status==="unsupported")return "VOID";
    const hit=score(r);
    if(hit===null)return r.prediction?"PENDING":r.result?"PENDING":"NO_FORECAST";
    if(!r.prediction)return "NO_FORECAST";
    if(!eligibleFreeze(r))return "PREDICTION_UNVERIFIED";
    return hit?"HIT":"MISS";
  }
  function summary(records){
    const init=()=>({ledger:0,frozenReported:0,noForecast:0,evaluable:0,hits:0,excluded:0,actualStake:0,actualPayout:0,actualRefund:0,actualPurchases:0});
    const bySport=Object.fromEntries(allowedSports.map(s=>[s,init()]));
    for(const r of records){
      const g=bySport[r.sport];g.ledger++;
      if(eligibleFreeze(r))g.frozenReported++;else g.noForecast++;
      const hit=score(r);
      if(hit===null)g.excluded++;else {g.evaluable++;if(hit)g.hits++;}
      if(r.actual_purchase?.confirmed===true){
        g.actualPurchases++;g.actualStake+=r.actual_purchase.stake_yen;
        g.actualPayout+=r.actual_purchase.payout_yen;g.actualRefund+=r.actual_purchase.refund_yen;
      }
    }
    const overall=init();
    for(const v of Object.values(bySport))for(const k of Object.keys(overall))overall[k]+=v[k];
    overall.hit8=overall.evaluable?overall.hits/overall.evaluable:null;
    overall.actualNet=overall.actualPurchases?overall.actualPayout+overall.actualRefund-overall.actualStake:null;
    return {overall,bySport};
  }
  function models(records){
    const groups=new Map();
    for(const r of records){
      if(!r.prediction)continue;
      const p=r.prediction;
      const key=r.sport+"|"+(p.model_id||p.model_version)+"|"+p.model_version;
      if(!groups.has(key))groups.set(key,{key,sport:r.sport,model_id:p.model_id||p.model_version,model_version:p.model_version,records:[]});
      groups.get(key).records.push(r);
    }
    return [...groups.values()].map(g=>{
      const s=summary(g.records).overall;
      return {...g,ledger:s.ledger,evaluable:s.evaluable,hits:s.hits,frozen:s.frozenReported,
        hit8:s.hit8,cohort_ids:g.records.map(r=>r.race_id).sort(),comparison:"参考・対象母数相違の可能性"};
    });
  }
  function modelComparison(records){
    const groups=models(records);
    for(const g of groups){
      const peers=groups.filter(m=>m!==g&&m.sport===g.sport);
      g.comparison=peers.length&&peers.some(p=>p.cohort_ids.join("|")===g.cohort_ids.join("|"))?
        "同一レース集合（入力時点は別途照合）":"参考値（同一未来レースの並走未証明）";
    }
    return groups;
  }
  function filtered(records,{sport="all",period="all",day=jstToday(),state="all",query=""}={}){
    const needle=query.trim().toLowerCase();
    return records.filter(r=>(sport==="all"||r.sport===sport)&&inPeriod(r,period,day)&&
      (state==="all"||outcome(r)===state)&&
      (!needle||(r.venue+" "+r.race_no+"R "+r.race_id+" "+(r.prediction?.model_version||"")).toLowerCase().includes(needle)));
  }
  function sortRaces(rows,order="latest",referenceRows=rows){
    const modelsByVersion=new Map(modelComparison(referenceRows).map(g=>[g.key,g]));
    const modelRank=r=>{
      if(!r.prediction)return -1;
      const key=r.sport+"|"+(r.prediction.model_id||r.prediction.model_version)+"|"+r.prediction.model_version;
      return modelsByVersion.get(key)?.hit8??-1;
    };
    const time=r=>Date.parse(r.result?.confirmed_at||r.cutoff_at||"")||0;
    const payout=r=>Number.isSafeInteger(r.result?.payout_yen_per_100)&&r.result?.status==="final"?r.result.payout_yen_per_100:-1;
    return [...rows].sort((a,b)=>{
      const by=order==="payout"?payout(b)-payout(a):
        order==="modelRate"?modelRank(b)-modelRank(a):time(b)-time(a);
      return by||a.race_id.localeCompare(b.race_id);
    });
  }
  function merge(datasets){
    if(!Array.isArray(datasets)||!datasets.length)fail("読み込み対象がありません。");
    const parsed=datasets.map(parse),types=new Set(parsed.map(d=>d.dataset_status));
    if(types.has("SYNTHETIC_ONLY")&&types.size>1)fail("合成と実データを混在させないでください。");
    const records=[],seen=new Set();
    for(const d of parsed)for(const r of d.records){
      if(seen.has(r.race_id))fail("ファイル間のレースID重複です。自動上書きはしません: "+r.race_id);
      seen.add(r.race_id);records.push(r);
    }
    return {dataset_status:types.has("SYNTHETIC_ONLY")?"SYNTHETIC_ONLY":types.has("REAL_REPORTED")?"REAL_REPORTED":"AUDIT_ONLY",
      records,sources:parsed.flatMap(x=>x.provenance_urls)};
  }
  return Object.freeze({parse,merge,summary,score,status,outcome,eligibleFreeze,ticketKey,displaySport,
    jstToday,raceDay,monday,inPeriod,filtered,sortRaces,models,modelComparison});
});
