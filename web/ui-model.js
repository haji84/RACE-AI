/* Session-only manual accounting. No predictions or provider data are derived here. */
(function(root) {
  "use strict";
  const model = {
    validateTicket(lanes, amount) {
      if (!Array.isArray(lanes) || lanes.length !== 3 || lanes.some(n => !Number.isInteger(n) || n < 1 || n > 6) || new Set(lanes).size !== 3) return '1〜6の異なる艇を3つ選んでください。';
      if (!Number.isSafeInteger(amount) || amount < 100 || amount % 100 !== 0) return '金額は100円単位で入力してください。';
      return null;
    },
    allocate(budget, count) {
      if (!Number.isSafeInteger(budget) || budget < 0 || !Number.isInteger(count) || count < 1 || count > 32) return [];
      const units = Math.floor(budget / 100);
      return Array.from({length:count}, (_, i) => (Math.floor(units / count) + (i < units % count ? 1 : 0)) * 100);
    },
    summarize(records) {
      const spent = records.reduce((sum, r) => sum + r.amount, 0);
      const settled = records.filter(r => r.payout !== null);
      const settledCost = settled.reduce((sum, r) => sum + r.amount, 0);
      const returned = settled.reduce((sum, r) => sum + r.payout, 0);
      const hits = settled.filter(r => r.payout > 0).length;
      return {spent, returned, purchases:records.length, settled:settled.length, hits, roi:settledCost ? returned / settledCost * 100 : null, hitRate:settled.length ? hits / settled.length * 100 : null};
    }
  };
  if (typeof module === 'object' && module.exports) module.exports = model;
  else root.RaceUI = model;
})(typeof globalThis !== 'undefined' ? globalThis : this);
