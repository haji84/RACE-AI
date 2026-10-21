"use strict";
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.RaceAuditModel = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const allowedSports = ["boat", "keirin", "autorace", "horse"];
  const displaySport = {boat:"ボートレース",keirin:"競輪",autorace:"オートレース",horse:"競馬"};
  const pattern = /^[a-f0-9]{64}$/i;
  const isTimestamp = x => typeof x === "string" && /T\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(x) && Number.isFinite(Date.parse(x));
  function ticket(v) {
    return Array.isArray(v) && v.length === 3 && v.every(x => Number.isInteger(x) && x > 0 && x <= 99) && new Set(v).size === 3;
  }
  const ticketKey = v => v.join("-");
  function fail(message) { throw new Error(message); }
  function parse(raw) {
    if (!raw || raw.schema !== "RACE_AI_FORECAST_AUDIT_V1") fail("未対応のデータ形式です。");
    if (!["AUDIT_ONLY","REAL_REPORTED","SYNTHETIC_ONLY"].includes(raw.dataset_status)) fail("データ種別が不正です。");
    if (!Array.isArray(raw.records) || raw.records.length > 10000) fail("レース配列が不正です。");
    const seen = new Set();
    const records = raw.records.map((r, i) => {
      if (!r || typeof r.race_id !== "string" || r.race_id.length > 250 || !r.race_id) fail("レースIDが不正です: "+i);
      if (seen.has(r.race_id)) fail("同じレースIDの重複があります: "+r.race_id);
      seen.add(r.race_id);
      if (!allowedSports.includes(r.sport) || typeof r.venue !== "string" || !r.venue || r.venue.length > 100
          || !Number.isInteger(r.race_no) || r.race_no < 1 || r.race_no > 99) fail("競技・場・レース番号が不正です。");
      if (r.cutoff_at !== null && r.cutoff_at !== undefined && !isTimestamp(r.cutoff_at)) fail("締切時刻が不正です: "+r.race_id);
      if (!["TRIFECTA_OFFERED","NOT_OFFERED","UNKNOWN"].includes(r.offering_status)) fail("券種発売の状態が不正です。");
      if (r.prediction !== null && r.prediction !== undefined) {
        const p=r.prediction;
        if (!Array.isArray(p.ordered_top8) || p.ordered_top8.length < 1 || p.ordered_top8.length > 8 ||
            p.ordered_top8.some(v=>!ticket(v)) ||
            new Set(p.ordered_top8.map(ticketKey)).size !== p.ordered_top8.length) fail("3連単予想が不正です: "+r.race_id);
        if (!isTimestamp(p.generated_at) || !isTimestamp(p.persisted_at) || !isTimestamp(p.cutoff_at)
            || !pattern.test(p.input_sha256||"") || !pattern.test(p.prediction_sha256||"")
            || typeof p.model_version !== "string" || p.model_version.length > 100
            || p.odds_independent !== true) fail("予想時刻・証拠・オッズ分離が不正です: "+r.race_id);
      }
      if (r.result !== null && r.result !== undefined) {
        const result=r.result;
        if (!["final","void","pending","unsupported"].includes(result.status) ||
            !Array.isArray(result.winning_combinations) ||
            result.winning_combinations.some(v=>!ticket(v)) ||
            (result.status === "final" && result.winning_combinations.length === 0) ||
            (result.status !== "final" && result.winning_combinations.length > 0)) fail("確定結果の形式が不正です: "+r.race_id);
        if (result.confirmed_at != null && !isTimestamp(result.confirmed_at)) fail("結果発表時刻が不正です。");
      }
      return r;
    });
    return {dataset_status:raw.dataset_status, event_date_jst:raw.event_date_jst||"不明", provenance_urls:Array.isArray(raw.provenance_urls)?raw.provenance_urls:[], records};
  }
  function eligibleFreeze(r) {
    const p=r.prediction;
    return !!(p && r.cutoff_at && p.odds_independent===true
        && Date.parse(p.generated_at) <= Date.parse(p.persisted_at)
        && Date.parse(p.persisted_at) < Date.parse(p.cutoff_at)
        && Date.parse(p.cutoff_at) === Date.parse(r.cutoff_at)
        && p.external_receipt_verified === true);
  }
  function status(r) {
    if (r.prediction) return eligibleFreeze(r) ? "FROZEN_REPORTED" : "PREDICTION_UNVERIFIED";
    return "NO_FORECAST";
  }
  function score(r) {
    if (r.offering_status !== "TRIFECTA_OFFERED" || !r.result || r.result.status!=="final") return null;
    return eligibleFreeze(r) && r.result.winning_combinations.some(w => r.prediction.ordered_top8.some(t => ticketKey(t)===ticketKey(w)));
  }
  function summary(records) {
    const bySport = Object.fromEntries(allowedSports.map(s=>[s,{ledger:0,frozenReported:0,noForecast:0,evaluable:0,hits:0,excluded:0}]));
    for (const r of records) {
      const g=bySport[r.sport]; g.ledger++;
      if (eligibleFreeze(r)) g.frozenReported++;
      else g.noForecast++;
      const hit=score(r);
      if (hit===null) g.excluded++;
      else {g.evaluable++;if(hit)g.hits++;}
    }
    const overall={ledger:0,frozenReported:0,noForecast:0,evaluable:0,hits:0,excluded:0};
    for(const v of Object.values(bySport))for(const k of Object.keys(overall))overall[k]+=v[k];
    overall.hit8=overall.evaluable ? overall.hits/overall.evaluable : null;
    return {overall,bySport};
  }
  function merge(datasets) {
    if (!Array.isArray(datasets) || datasets.length === 0) fail("読み込み対象がありません。");
    const parsed=datasets.map(parse), types=new Set(parsed.map(d=>d.dataset_status));
    if(types.has("SYNTHETIC_ONLY") && types.size>1) fail("合成と実データを混在させないでください。");
    const records=[], seen=new Set();
    for(const d of parsed)for(const r of d.records){
      if (seen.has(r.race_id)) fail("ファイル間のレースID重複です。自動上書きはしません: "+r.race_id);
      seen.add(r.race_id);records.push(r);
    }
    return {dataset_status:types.has("SYNTHETIC_ONLY")?"SYNTHETIC_ONLY":types.has("REAL_REPORTED")?"REAL_REPORTED":"AUDIT_ONLY",records,sources:parsed.flatMap(x=>x.provenance_urls)};
  }
  return Object.freeze({parse,merge,summary,score,status,eligibleFreeze,ticketKey,displaySport});
});
