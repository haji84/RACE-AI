/* Reused from PR #62: manual accounting is independent of forecast/result evidence. */
(function (root) {
  "use strict";
  const model = {
    validateTicket(lanes, amount, maxNumber = 6) {
      if (!Array.isArray(lanes) || lanes.length !== 3 || lanes.some(n => !Number.isInteger(n) || n < 1 || n > maxNumber) || new Set(lanes).size !== 3)
        return "1〜" + maxNumber + "の異なる番号を3つ選んでください。";
      if (!Number.isSafeInteger(amount) || amount < 100 || amount > 10000000 || amount % 100)
        return "金額は100〜10,000,000円の100円単位で入力してください。";
      return null;
    },
    allocate(budget, count) {
      if (!Number.isSafeInteger(budget) || budget < count * 100 || !Number.isInteger(count) || count < 1 || count > 32) return [];
      const units = Math.floor(budget / 100);
      return Array.from({length: count}, (_, i) => (Math.floor(units / count) + (i < units % count ? 1 : 0)) * 100);
    },
    validateDraft(tickets, budget, limit, maxNumber = 6) {
      if (!Number.isSafeInteger(budget) || budget < 100 || budget > 10000000 || budget % 100) return "予算は100円単位で入力してください。";
      if (!tickets.length) return "買い目候補を追加してください。";
      if (![8, 16, 24, 32].includes(limit) || tickets.length > limit) return "最大買い目数を超えています。候補を削除するか点数設定を変更してください。";
      const invalid = tickets.map(t => model.validateTicket(t.lanes, t.amount, maxNumber)).find(Boolean);
      if (invalid) return invalid;
      if (new Set(tickets.map(t => t.lanes.join("-"))).size !== tickets.length) return "同じ買い目がすでにあります。";
      if (tickets.reduce((sum, t) => sum + t.amount, 0) > budget) return "1レース予算を超えています。";
      return null;
    },
    summarize(records) {
      const spent = records.reduce((sum, r) => sum + r.amount, 0);
      const settled = records.filter(r => r.payout !== null);
      const settledCost = settled.reduce((sum, r) => sum + r.amount, 0);
      const returned = settled.reduce((sum, r) => sum + r.payout, 0);
      const hits = settled.filter(r => r.payout > 0).length;
      return {spent, returned, purchases: records.length, settled: settled.length, hits,
        roi: settledCost ? returned / settledCost * 100 : null,
        hitRate: settled.length ? hits / settled.length * 100 : null};
    },
    outcome(row, {predictionEligible = false, resultEligible = false} = {}) {
      if (row.offering_status === "NOT_OFFERED" || ["void", "unsupported"].includes(row.result?.status)) return "VOID";
      if (!row.prediction) return "NO_FORECAST";
      if (!predictionEligible) return "PREDICTION_UNVERIFIED";
      if (!resultEligible) return "PENDING";
      return row.result.winning_combinations.some(w => row.prediction.ordered_top8.some(t => t.join("-") === w.join("-"))) ? "HIT" : "MISS";
    },
    refundSummary(result) {
      const fields = [["refunds", "返還記録"], ["refund_boats", "返還対象番号"], ["refund_combinations", "返還対象券"], ["refund_yen", "返還額"]];
      const values = fields.flatMap(([key, label]) => {
        const value = result?.[key];
        if (value === undefined || value === null || (Array.isArray(value) && !value.length)) return [];
        const display = key === "refund_yen" ? value.toLocaleString("ja-JP") + "円" : key === "refund_boats" ? value.join("・") : typeof value === "object" ? JSON.stringify(value) : String(value);
        return [label + " " + display];
      });
      return values.join(" / ") || "未取得";
    },
    filterRaces(records, {sport = "all", day = "", allDates = false, period = "day", query = "", venue = "", forecastOnly = false, candidatesOnly = false, candidateRaceIds = [], sort = "venue"} = {}) {
      const needle = query.trim().toLocaleLowerCase("ja-JP");
      let weekStart = "", weekEnd = "";
      if (day && period === "week") { const start = new Date(day + "T00:00:00Z"); start.setUTCDate(start.getUTCDate() - (start.getUTCDay() + 6) % 7); weekStart = start.toISOString().slice(0, 10); start.setUTCDate(start.getUTCDate() + 7); weekEnd = start.toISOString().slice(0, 10); }
      const rows = records.filter(r => (sport === "all" || r.sport === sport) && (allDates || !day || (period === "week" ? r.event_date_jst >= weekStart && r.event_date_jst < weekEnd : r.event_date_jst === day)) &&
        (!venue || r.venue === venue) && (!forecastOnly || !!r.prediction || !!r.comparison_predictions?.length) &&
        (!candidatesOnly || candidateRaceIds.includes(r.race_id)) &&
        (!needle || [r.venue, r.race_no + "R", r.race_id, r.prediction?.model_id, r.prediction?.model_version,
          ...(r.participants || []).flatMap(p => [p.name, p.registration_id, p.racer_registration_id])].filter(Boolean).join(" ").toLocaleLowerCase("ja-JP").includes(needle)));
      const cutoff = r => Number.isFinite(Date.parse(r.cutoff_at)) ? Date.parse(r.cutoff_at) : Infinity;
      return rows.sort((a, b) => (sort === "time" ? cutoff(a) - cutoff(b) : a.venue.localeCompare(b.venue, "ja") || a.race_no - b.race_no) || a.race_id.localeCompare(b.race_id));
    }
  };
  if (typeof module === "object" && module.exports) module.exports = model;
  else root.RaceUI = model;
})(typeof globalThis !== "undefined" ? globalThis : this);
