"use strict";
(function (root, factory) {
  const audit = typeof module === "object" && module.exports ? require("./forecast-audit-model.js") : root.RaceAuditModel;
  const api = factory(audit);
  if (typeof module === "object" && module.exports) module.exports = api;
  root.RaceProductData = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (Audit) {
  const sports = ["boat", "keirin", "autorace", "horse"];
  const scopes = ["official", "research", "synthetic"];
  const stages = ["P0", "P1", "UNKNOWN"];
  const sha = value => typeof value === "string" && /^[a-f0-9]{64}$/i.test(value);
  const stamp = value => typeof value === "string" && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(value) && validDay(value.slice(0,10)) && Number.isFinite(Date.parse(value));
  const text = value => typeof value === "string" && value.trim().length > 0;
  function fail(message) { throw new Error(message); }
  function freeze(value) {
    if (value && typeof value === "object") {
      for (const child of Object.values(value)) freeze(child);
      Object.freeze(value);
    }
    return value;
  }
  function clone(raw) {
    let encoded;
    try {
      encoded = typeof raw === "string" ? raw : JSON.stringify(raw, (_key, value) => {
        if (typeof value === "number" && !Number.isFinite(value) || ["function", "symbol", "bigint"].includes(typeof value)) fail("有限のJSONデータが必要です。");
        return value;
      });
      if (typeof encoded !== "string" || encoded.length > 32 * 1024 * 1024) fail("JSONデータが大きすぎます。");
      return JSON.parse(encoded);
    } catch (error) {
      if (/JSON/.test(error.message)) throw error;
      fail("JSONデータの形式が不正です。");
    }
  }
  function canonical(value) {
    if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
    if (value && typeof value === "object") return "{" + Object.keys(value).sort().map(k => JSON.stringify(k) + ":" + canonical(value[k])).join(",") + "}";
    return JSON.stringify(value);
  }
  function validDay(day) {
    return typeof day === "string" && /^\d{4}-\d\d-\d\d$/.test(day) && Number.isFinite(Date.parse(day + "T00:00:00Z")) && new Date(day + "T00:00:00Z").toISOString().slice(0, 10) === day;
  }
  function ticket(value) {
    return Array.isArray(value) && value.length === 3 && value.every(x => Number.isInteger(x) && x > 0 && x <= 99) && new Set(value).size === 3;
  }
  function validateStamps(value, fields) {
    if (!value) return;
    for (const field of fields) if (value[field] != null && !stamp(value[field])) fail("保存時刻の形式が不正です: " + field);
  }
  function marketIsolation(value) {
    if (!value || typeof value !== "object") return;
    for (const [key, child] of Object.entries(value)) {
      if (key !== "odds_independent" && /odds|popularity|market|payout|確定配当|人気/i.test(key)) fail("予想に市場由来の値を混ぜないでください。");
      marketIsolation(child);
    }
  }
  function candidateOrder(p) {
    for (const field of ["candidates", "ordered_candidates"]) {
      const rows = p[field];
      if (rows == null) continue;
      if (!Array.isArray(rows) || !rows.length || rows.length > 941094) fail("保存候補の形式が不正です。");
      const combinations = rows.map(row => Array.isArray(row) ? row : row?.combination);
      if (combinations.some(t => !ticket(t)) || new Set(combinations.map(t => t.join("-"))).size !== combinations.length) fail("保存候補に重複・不正な組合せがあります。");
      if (rows.some(row => !Array.isArray(row) && row.score != null && (typeof row.score !== "number" || !Number.isFinite(row.score) || row.score < 0))) fail("保存候補スコアが不正です。");
      if (canonical(combinations.slice(0, p.ordered_top8.length)) !== canonical(p.ordered_top8)) fail("保存候補順位とTop8が一致しません。");
    }
    if (p.candidates != null && p.ordered_candidates != null) {
      const combos = rows => rows.map(r => Array.isArray(r) ? r : r.combination);
      if (canonical(combos(p.candidates)) !== canonical(combos(p.ordered_candidates))) fail("保存候補順位が一致しません。");
    }
  }
  function refunds(result) {
    if (!result) return;
    if (result.refund_boats != null && (!Array.isArray(result.refund_boats) || result.refund_boats.some(x => !Number.isInteger(x) || x < 1 || x > 99) || new Set(result.refund_boats).size !== result.refund_boats.length)) fail("返還対象の形式が不正です。");
    if (result.refunds != null && (!Array.isArray(result.refunds) || result.refunds.length > 10000)) fail("返還記録の形式が不正です。");
    if (result.refund_combinations != null) {
      const combinations = result.refund_combinations;
      if (!Array.isArray(combinations) || combinations.length > 10000 || combinations.some(t => !ticket(t)) ||
          new Set(combinations.map(t => t.join("-"))).size !== combinations.length) fail("返還組合せの形式が不正です。");
      if (result.refunds != null) {
        const detailed = result.refunds.map(r => r?.combination);
        if (detailed.some(t => !ticket(t)) || canonical(detailed.map(t => t.join("-")).sort()) !==
            canonical(combinations.map(t => t.join("-")).sort())) fail("返還組合せの別名と明細が一致しません。");
      }
    }
    const visit = value => {
      if (!value || typeof value !== "object") return;
      for (const [key, child] of Object.entries(value)) {
        if (/refund.*yen|yen.*refund/i.test(key) && (!Number.isSafeInteger(child) || child < 0)) fail("返還金額が不正です。");
        visit(child);
      }
    };
    visit(result);
  }
  function sourcePinned(row) {
    return row.scope === "official" && sha(row.source_sha256) && text(row.source_provenance);
  }
  // These gates check importer assertions and matching saved pins. The browser
  // cannot authenticate the importer's authority, signature or source rights.
  function eligiblePrediction(row, p) {
    const receipt = p?.external_receipt;
    return !!(sourcePinned(row) && p && text(p.model_id) && stages.slice(0, 2).includes(p.stage) && Audit.eligiblePrediction(row, p) &&
      receipt && text(receipt.authority) && receipt.content_sha256 === p.prediction_sha256 &&
      receipt.source_sha256 === row.source_sha256 && stamp(receipt.server_received_at) &&
      Date.parse(receipt.server_received_at) === Date.parse(p.persisted_at));
  }
  function hasRefund(result) {
    return !!(result?.refund_boats?.length || result?.refunds?.length || result?.refund_combinations?.length || result?.refund_yen > 0 || result?.status === "void");
  }
  function eligibleResult(row) {
    const r = row.result, evidence = r?.evidence;
    return !!(sourcePinned(row) && row.offering_status === "TRIFECTA_OFFERED" &&
      r?.status === "final" && r.official === true && sha(r.source_sha256) && stamp(r.confirmed_at) &&
      stamp(row.cutoff_at) && Date.parse(r.confirmed_at) >= Date.parse(row.cutoff_at) && !hasRefund(r) &&
      evidence && text(evidence.authority) && evidence.content_sha256 === r.source_sha256 &&
      stamp(evidence.observed_at) && Date.parse(evidence.observed_at) === Date.parse(r.confirmed_at));
  }
  function candidates(row) { return [row.prediction, ...(row.comparison_predictions || [])].filter(Boolean); }
  function identity(p) { return canonical([p.stage || "UNKNOWN", p.model_id || null, p.model_version]); }
  function selectPrediction(row, {stage, modelId, version} = {}) {
    if (stage == null && modelId == null && version == null) return row.prediction || null;
    return candidates(row).find(p => (stage == null || p.stage === stage) &&
      (modelId == null || p.model_id === modelId) && (version == null || p.model_version === version)) || null;
  }
  function parse(raw) {
    if (!Audit) fail("監査データ検証モジュールが必要です。");
    const value = clone(raw);
    if (!value || value.schema !== "RACE_AI_FORECAST_AUDIT_V1") fail("未対応のデータ形式です。");
    if (!["AUDIT_ONLY", "REAL_REPORTED", "SYNTHETIC_ONLY"].includes(value.dataset_status) || !Array.isArray(value.records) || value.records.length > 10000) fail("データ種別・レース配列が不正です。");
    if (value.event_date_jst != null && !validDay(value.event_date_jst)) fail("JST開催日が不正です。");
    const seen = new Set();
    value.records = value.records.map(row => {
      if (!row || typeof row !== "object") fail("レースの形式が不正です。");
      if (row.source_sha != null) {
        if (row.source_sha256 != null && row.source_sha256 !== row.source_sha) fail("元データSHAが一致しません。");
        row.source_sha256 = row.source_sha;
      }
      if (row.sport === "horse_local" || row.sport === "horse_jra") {
        row.source_sport = row.sport;
        row.sport = "horse";
      }
      if (seen.has(row.race_id)) fail("同じレースIDの重複があります。");
      seen.add(row.race_id);
      if (row.scope != null && !scopes.includes(row.scope)) fail("データの範囲が不正です。");
      const day = row.event_date_jst || Audit.raceDay(row) || value.event_date_jst || null;
      if (day != null && !validDay(day)) fail("JST開催日が不正です。");
      if (row.event_date_jst != null && !validDay(row.event_date_jst)) fail("JST開催日が不正です。");
      validateStamps(row, ["cutoff_at", "observed_at", "as_of", "updated_at"]);
      if (day && row.cutoff_at && new Date(Date.parse(row.cutoff_at) + 9 * 60 * 60 * 1000).toISOString().slice(0, 10) !== day) fail("JST開催日と締切時刻が一致しません。");
      row.event_date_jst = day;
      const reasons = row.missing_reasons == null ? [] : row.missing_reasons;
      if (!Array.isArray(reasons) || reasons.some(r => !text(r))) fail("欠測理由が不正です。");
      row.missing_reasons = reasons;
      if (value.dataset_status === "SYNTHETIC_ONLY") row.scope = "synthetic";
      else if (value.dataset_status !== "REAL_REPORTED" || row.scope !== "official" || !sha(row.source_sha256) || !text(row.source_provenance)) {
        if (row.scope === "synthetic") fail("合成と実データを混在させないでください。");
        if (row.scope !== "research") reasons.push("OFFICIAL_SCOPE_OR_SOURCE_EVIDENCE_MISSING");
        row.scope = "research";
      }
      if (row.comparison_predictions != null && (!Array.isArray(row.comparison_predictions) || row.comparison_predictions.length > 64)) fail("比較モデル予想の件数が不正です。");
      const variants = candidates(row), identities = new Set();
      for (const p of variants) {
        if (!p || typeof p !== "object" || Array.isArray(p)) fail("予想の形式が不正です。");
        p.stage = p.stage || row.stage || "UNKNOWN";
        if (!stages.includes(p.stage)) fail("予想時点はP0/P1/UNKNOWNが必要です。");
        if (p.model_id != null && (!text(p.model_id) || p.model_id.length > 128)) fail("モデル識別子が不正です。");
        validateStamps(p, ["generated_at", "persisted_at", "cutoff_at", "as_of", "observed_at"]);
        marketIsolation(p);
        candidateOrder(p);
        if (identities.has(identity(p))) fail("同じ時点・モデル・版の重複があります。");
        identities.add(identity(p));
        // Reuse the existing strict odds-free audit admission for each saved
        // variant. Its older model key does not distinguish P0 from P1.
        const check = {...row, prediction:p}; delete check.comparison_predictions;
        Audit.parse({...value, records:[check]});
        if (p.stage === "UNKNOWN") reasons.push("PREDICTION_STAGE_NOT_SAVED");
        if (!p.model_id) reasons.push("MODEL_ID_NOT_SAVED");
        if (!eligiblePrediction(row, p)) reasons.push("EXTERNAL_RECEIPT_PIN_MISSING_OR_MISMATCHED");
      }
      if (!variants.length) {
        const check = {...row}; delete check.comparison_predictions;
        Audit.parse({...value, records:[check]});
        reasons.push(row.no_forecast_reason || "NO_SAVED_PREDICTION");
      }
      if (row.result_revisions != null) {
        row.result_revisions.forEach((r, index) => {
          if (r.revision_no !== index + 1) fail("結果改訂の版は連続している必要があります。");
          validateStamps(r, ["confirmed_at", "observed_at"]);
          refunds(r);
        });
        if (row.result_revisions.length && !row.result) fail("最新の公式結果と改訂履歴が一致しません。");
        if (row.result_revisions.length) {
          const withoutRevision = result => Object.fromEntries(Object.entries(result).filter(([key]) => key !== "revision_no"));
          if (canonical(withoutRevision(row.result_revisions.at(-1))) !== canonical(withoutRevision(row.result))) fail("最新結果の払戻・返還・出典と改訂履歴が一致しません。");
        }
      }
      refunds(row.result);
      validateStamps(row.result, ["confirmed_at", "observed_at"]);
      if (row.result && !eligibleResult(row)) reasons.push(hasRefund(row.result) ? "REFUND_REVIEW_REQUIRED" : "OFFICIAL_RESULT_PIN_MISSING_OR_MISMATCHED");
      row.missing_reasons = [...new Set(reasons)];
      row.evidence_imported_only = true;
      return row;
    });
    value.evidence_imported_only = true;
    value.verification_limitations = "保存された取込元の申告・SHA・時刻の整合性を表示します。ブラウザは署名・権限・独立時刻を認証しません。";
    return freeze(value);
  }
  function newStats() {
    return {ledger:0, officialLedger:0, researchLedger:0, syntheticLedger:0, frozenReported:0, noForecast:0,
      evaluable:0, hits:null, hit8:null, excluded:0, actualPurchases:0, actualStake:0, actualPayout:0,
      actualRefund:0, actualNet:null, evidence_imported_only:true, stage_mixed:false,
      identity_mixed:false, prediction_identities:[]};
  }
  function scored(row, p) {
    return eligiblePrediction(row, p) && row.result.winning_combinations.some(w => p.ordered_top8.some(t => Audit.ticketKey(t) === Audit.ticketKey(w)));
  }
  function accumulate(stats, row, p = row.prediction) {
    stats.ledger++;
    stats[row.scope + "Ledger"]++;
    if (eligiblePrediction(row, p)) stats.frozenReported++; else stats.noForecast++;
    if (eligibleResult(row)) {
      stats.evaluable++;
      stats.hits = (stats.hits || 0) + (scored(row, p) ? 1 : 0);
    } else stats.excluded++;
    const a = row.actual_purchase;
    if (row.scope === "official" && a?.confirmed === true) {
      stats.actualPurchases++; stats.actualStake += a.stake_yen;
      stats.actualPayout += a.payout_yen; stats.actualRefund += a.refund_yen;
    }
  }
  function finish(stats, identities) {
    stats.prediction_identities = [...identities].sort().map(key => {
      const [stage, model_id, model_version] = JSON.parse(key);
      return {stage, model_id, model_version};
    });
    stats.stage_mixed = new Set(stats.prediction_identities.map(p => p.stage)).size > 1;
    stats.identity_mixed = identities.size > 1;
    stats.hit8 = stats.evaluable && identities.size === 1 ? stats.hits / stats.evaluable : null;
    stats.actualNet = stats.actualPurchases ? stats.actualPayout + stats.actualRefund - stats.actualStake : null;
    return stats;
  }
  function summary(records) {
    const overall = newStats(), bySport = Object.fromEntries(sports.map(s => [s, newStats()]));
    const byScope = Object.fromEntries(scopes.map(s => [s, newStats()]));
    const byStage = Object.fromEntries(stages.map(s => [s, newStats()]));
    const identitySets = new Map([overall, ...Object.values(bySport), ...Object.values(byScope), ...Object.values(byStage)].map(s => [s, new Set()]));
    for (const row of records) {
      const stage = row.prediction?.stage || "UNKNOWN";
      for (const target of [overall, bySport[row.sport], byScope[row.scope]]) {
        accumulate(target, row);
        if (row.scope === "official" && row.prediction) identitySets.get(target).add(identity(row.prediction));
      }
      for (const phase of stages) {
        const variants = candidates(row).filter(p => p.stage === phase);
        // Each named stage keeps the full official schedule denominator,
        // including races with no saved forecast at that stage. UNKNOWN remains
        // the explicit unknown/missing-primary view rather than another cohort.
        if (phase === "UNKNOWN" ? stage !== "UNKNOWN" : row.scope !== "official" && !variants.length) continue;
        accumulate(byStage[phase], row, variants[0] || null);
        if (row.scope === "official") for (const p of variants) identitySets.get(byStage[phase]).add(identity(p));
      }
    }
    for (const [stats, identities] of identitySets) finish(stats, identities);
    return {overall, bySport, byScope, byStage};
  }
  function modelGroups(records) {
    const groups = new Map();
    for (const row of records) for (const p of candidates(row)) {
      const key = canonical([row.scope, row.sport, p.stage, p.model_id || null, p.model_version]);
      if (!groups.has(key)) groups.set(key, {key, scope:row.scope, sport:row.sport, stage:p.stage,
        model_id:p.model_id || null, model_version:p.model_version, issued:0, ...newStats(),
        comparison:"保存原本の参考比較（同一未来レース・入力・時刻の並走は別途検証）"});
    }
    for (const group of groups.values()) {
      const cohort = records.filter(r => r.scope === group.scope && r.sport === group.sport);
      for (const row of cohort) {
        const p = candidates(row).find(p => p.stage === group.stage && (p.model_id || null) === group.model_id && p.model_version === group.model_version) || null;
        if (p) group.issued++;
        accumulate(group, row, p);
      }
      finish(group, new Set(group.scope === "official" ? [canonical([group.stage, group.model_id, group.model_version])] : []));
    }
    return [...groups.values()];
  }
  return Object.freeze({parse, summary, selectPrediction, modelGroups, eligiblePrediction, eligibleResult, candidates});
});
