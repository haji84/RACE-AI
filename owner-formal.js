/* Count-only visual attestation against the owner-approved 2026-11-12 AES audit.
 * Never changes encrypted originals, forecasts, actual-purchase records, or
 * racing-provider traffic. Every displayed match must come from a loaded view.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.RaceOwnerFormal = api;
})(typeof globalThis !== "undefined" ? globalThis : this, () => {
  "use strict";
  const DAY = "2026-11-12";
  const ANCHOR = "4169db99a1d99bbcf96c8fa1bfb076ed2d2fb1f434fc64cf7e43b38e55f5adda";
  const EVIDENCE = "https://github.com/haji84/RACE-AI/actions/runs/43339230921";
  const EXPECTED = Object.freeze({
    "boat-observed-pairwise-factor-v1": Object.freeze({hits:26, misses:116}),
    "boat-observed-pairwise-start-v1": Object.freeze({hits:25, misses:117})
  });
  const sha = v => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
  const validTime = t => typeof t === "string" && Number.isFinite(Date.parse(t));
  const ms = t => Date.parse(t);
  const tickets = values => Array.isArray(values) && values.length > 0 &&
    values.every(t => Array.isArray(t) && t.length === 3 &&
      t.every(n => Number.isInteger(n) && n >= 1 && n <= 6) && new Set(t).size === 3);
  const key = t => t.join("-");
  function officialSpUrl(value, raceId) {
    const race = /^([0-9]{8})-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])$/.exec(raceId || "");
    if (!race || typeof value !== "string" || value.length > 1024) return false;
    try {
      const url = new URL(value), q = url.searchParams, keys = [...q.keys()];
      return url.protocol === "https:" && url.hostname === "www.boatrace.jp" &&
        !url.username && !url.password && !url.hash &&
        url.pathname === "/owsp/sp/spdata" && keys.length === 4 &&
        new Set(keys).size === 4 && q.get("type") === "raceresult" &&
        q.get("hd") === race[1] && q.get("jcd") === race[2] &&
        String(Number(q.get("rno"))) === String(Number(race[3])) &&
        /^(?:[1-9]|1[0-2])$/.test(q.get("rno"));
    } catch { return false; }
  }
  const sameNumbers = (a,b) => Array.isArray(a) && Array.isArray(b) &&
    a.length === b.length && JSON.stringify([...a].sort()) === JSON.stringify([...b].sort());

  const preds = r => [r.prediction, ...(Array.isArray(r.comparison_predictions) ? r.comparison_predictions : [])].filter(Boolean);
  const invalid = reason => ({applicable:true, verified:false, reason});

  function referenceEvidence(row) {
    const r = row.result || {}, proof = r.cutoff_reference;
    if (!proof || proof.basis !== "RAW_OFFICIAL_SP_SAME_ROSTER_SAVED_BEFORE_BOTH" ||
        proof.formal_eligible !== false || r.formal_eligible === false ||
        r.cutoff_reconciliation != null || row.cutoff_at !== proof.original_cutoff_at ||
        !validTime(proof.original_cutoff_at) || !validTime(proof.result_schedule_cutoff_at) ||
        !sha(r.source_sha256) || !validTime(r.observed_at) ||
        (row.result_observation_rejections || []).length > 0 ||
        (row.saved_observation_cutoff_variants || []).length > 0) return false;
    const before = ms(proof.original_cutoff_at), source = ms(proof.result_schedule_cutoff_at);
    const offset = source - before;
    if (!Number.isFinite(proof.offset_seconds) ||
        Math.abs(offset - 1000 * proof.offset_seconds) > 1 ||
        Math.abs(offset) > 86400000 || ms(r.observed_at) < Math.max(before, source)) return false;
    for (const p of preds(row)) {
      if (!validTime(p.persisted_at) || ms(p.persisted_at) >= Math.min(before, source)) return false;
      for (const field of ["as_of","generated_at","server_saved_at","source_captured_at"]) {
        if (p[field] != null && (!validTime(p[field]) || ms(p[field]) >= Math.min(before, source))) return false;
      }
    }
    const observations = row.result_observations;
    if (!Array.isArray(observations) || !observations.length ||
        observations.some(o => !o || !validTime(o.captured_at) || o.race_id !== row.race_id)) return false;
    const latest = observations.reduce((a,b) => ms(a.captured_at) >= ms(b.captured_at) ? a : b);
    if (latest.captured_at !== r.observed_at || latest.source_sha256 !== r.source_sha256 ||
        latest.closed_at !== proof.result_schedule_cutoff_at ||
        latest.body_identity_verified !== true || latest.status !== "AVAILABLE" ||
        latest.schedule_binding !== "SP_EXPLICIT_RACE_HEADER" ||
        !officialSpUrl(latest.source_url,row.race_id)) return false;
    const data = latest.data;
    if (!data || data.status !== "settled" || data.confirmed !== true ||
        data.finish_confirmed !== true || !tickets(r.winning_combinations) ||
        !Array.isArray(data.payouts)) return false;
    const payouts = data.payouts.filter(x => x && x.bet_type === "trifecta");
    if (payouts.length !== r.winning_combinations.length ||
        payouts.some(x => !tickets([x.combination]) || !Number.isSafeInteger(x.payout_per_100_yen) ||
          x.payout_per_100_yen < 0) ||
        new Set(payouts.map(x => key(x.combination))).size !== payouts.length ||
        payouts.some(x => !r.winning_combinations.some(t => key(t) === key(x.combination)))) return false;
    if (payouts.length === 1 && r.payout_yen_per_100 !== payouts[0].payout_per_100_yen) return false;
    if (payouts.length > 1 && (!Array.isArray(r.payouts) || r.payouts.length !== payouts.length ||
        r.payouts.some(p => !p || !tickets([p.combination]) ||
          !payouts.some(o => key(o.combination) === key(p.combination) &&
            o.payout_per_100_yen === p.payout_per_100_yen)))) return false;
    if (!sameNumbers(r.refund_boats || [],data.refund_boats || []) ||
        (r.refund_boats || []).some(n => !Number.isInteger(n) || n < 1 || n > 6) ||
        new Set(r.refund_boats || []).size !== (r.refund_boats || []).length) return false;
    if (data.refunds != null && r.refunds != null &&
        JSON.stringify(data.refunds) !== JSON.stringify(r.refunds)) return false;
    if (r.winning_combinations.some(t => t.some(n => (r.refund_boats || []).includes(n))))
      return false;
    return true;
  }

  function inspect(rows, performance, forecastSha) {
    if (!Array.isArray(rows) || !rows.length || rows.some(r => r.event_date_jst !== DAY || r.sport !== "boat"))
      return {applicable:false, verified:false};
    if (forecastSha !== ANCHOR || !performance || typeof performance.compare !== "function")
      return invalid("FORECAST_ANCHOR_OR_COMPARER_MISSING");
    if (rows.length !== 142 || new Set(rows.map(r => r.race_id)).size !== 142 ||
        rows.some(r => r.private_cycle_view !== true || r.scope !== "research"))
      return invalid("ORIGINAL_142_RACES_NOT_LOADED");
    const scores = Object.fromEntries(Object.keys(EXPECTED).map(id => [id, {hits:0, misses:0, forecasts:0}]));
    let ordinary = 0, references = 0, shortOffset = 0, longOffset = 0;
    for (const row of rows) {
      const result = row.result || {};
      if (result.status !== "final") return invalid("OFFICIAL_FINAL_MISSING");
      if (result.cutoff_reference != null) {
        if (!referenceEvidence(row)) return invalid("SP_CUTOFF_SOURCE_EVIDENCE_MISMATCH");
        references++;
        if (Math.abs(result.cutoff_reference.offset_seconds) <= 60) shortOffset++;
        else longOffset++;
      } else {
        if (result.formal_eligible === false || result.cutoff_reconciliation)
          return invalid("OTHER_NONFORMAL_RESULT_PRESENT");
        ordinary++;
      }
      const variants = preds(row);
      if (variants.length !== 2 || new Set(variants.map(p => p.model_id)).size !== 2 ||
          variants.some(p => p.stage !== "P0" || !Object.hasOwn(EXPECTED, p.model_id)))
        return invalid("ORIGINAL_TWO_MODEL_P0_MISMATCH");
      for (const p of variants) {
        const outcome = performance.compare(row,p).status;
        if (outcome !== "HIT" && outcome !== "MISS") return invalid("SITE_MODEL_COMPARISON_HOLD");
        scores[p.model_id].forecasts++;
        scores[p.model_id][outcome === "HIT" ? "hits" : "misses"]++;
      }
    }
    if (ordinary !== 132 || references !== 10 || shortOffset !== 9 || longOffset !== 1)
      return invalid("ORIGINAL_REFERENCE_COUNTS_MISMATCH");
    if (Object.entries(EXPECTED).some(([id,expected]) =>
        scores[id].forecasts !== 142 || scores[id].hits !== expected.hits ||
        scores[id].misses !== expected.misses))
      return invalid("MODEL_COUNTS_DIFFER_FROM_INDEPENDENT_AUDIT");
    return Object.freeze({
      applicable:true, verified:true, day:DAY, races:142, predictions:284,
      approvedReferences:10, counts:scores, evidence:EVIDENCE
    });
  }
  return Object.freeze({inspect, referenceEvidence, DAY, ANCHOR, EVIDENCE});
});
