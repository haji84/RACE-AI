/* Pre-generated illustrations; official photos are references, never fetched by visitors. */
'use strict';
(() => {
  const embedded = null;
  const data = typeof module === 'object' && module.exports ? require('./racer-portraits-data.js') : globalThis.RaceRacerPortraitData;
  const people = Array.isArray(data?.people) ? data.people : [];
  const all = Object.freeze(people.filter(p => p.state === 'READY').map(p => {
    const registration = p.registration, asset = p.asset, info = data.assets?.[asset];
    if (!/^\d{4}$/.test(registration) || typeof p.name !== 'string' || !Array.isArray(p.aliases) ||
        !info || !/^assets\/racer-portraits\/(?:boat-\d{4}|sheet-\d{4})\.webp$/.test(asset) ||
        p.source_url !== 'https://www.boatrace.jp/owpc/pc/data/racersearch/profile?toban=' + registration) return null;
    let atlas = null;
    if (p.atlas != null) {
      const {columns, rows, slot} = p.atlas;
      if (![5,6].includes(columns) || rows !== columns || !Number.isInteger(slot) || slot < 0 || slot >= rows * columns) return null;
      atlas = Object.freeze({columns, rows, slot, column:slot % columns, row:Math.floor(slot / columns)});
    } else if (asset !== 'assets/racer-portraits/boat-' + registration + '.webp') return null;
    if (embedded !== null && !embedded[asset]) return null;
    const src = embedded?.[asset] || './' + asset + (atlas ? '?v=' + info.sha256.slice(0,12) : '');
    return Object.freeze({registration, name:p.name, aliases:Object.freeze([...p.aliases]), src, atlas, sourceUrl:p.source_url});
  }).filter(Boolean));
  const byRegistration = new Map(all.map(item => [item.registration, item]));
  const fields = ['registration_no', 'registration_number', 'registration_id', 'racer_registration_id', 'racer_id', 'participant_id'];
  function get(race, person) {
    if (!race || race.sport !== 'boat' || race.scope === 'synthetic' || race.synthetic === true ||
        !person || person.placeholder) return null;
    const ids = fields.filter(key => Object.hasOwn(person, key)).map(key => person[key]);
    if (!ids.length || ids.some(id => typeof id !== 'string' || !/^\d{4}$/.test(id) || id !== ids[0])) return null;
    const item = byRegistration.get(ids[0]);
    if (!item || person.name != null && (typeof person.name !== 'string' ||
        !item.aliases.some(name => name.replace(/\s+/g, '') === person.name.replace(/\s+/g, '')))) return null;
    return item;
  }
  const total = Number.isInteger(data?.total) && data.total > 0 && data.total <= 10000 ? data.total : all.length;
  const unavailable = people.filter(p => p.state === 'SOURCE_UNAVAILABLE').length;
  const coverage = Object.freeze({total, ready:all.length, unavailable, pending:Math.max(0,total-all.length-unavailable), complete:total>0 && all.length===total});
  const api = Object.freeze({all, get, coverage, offline:embedded!==null});
  if (typeof module === 'object' && module.exports) module.exports = api;
  else globalThis.RaceRacerPortraits = api;
})();
