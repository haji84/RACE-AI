/* Pre-generated illustrations; official photos are references, never fetched by visitors. */
'use strict';
(() => {
  const embedded = null;
  const all = Object.freeze([
    ['3415', '松井繁'], ['3897', '白井英治'], ['3941', '池田浩二'],
    ['4238', '毒島誠'], ['4320', '峰竜太'], ['4444', '桐生順平']
  ].map(([registration, name]) => Object.freeze({
    registration, name,
    src: embedded?.[registration] || './assets/racer-portraits/boat-' + registration + '.webp',
    sourceUrl: 'https://www.boatrace.jp/owpc/pc/data/racersearch/profile?toban=' + registration
  })));
  const byRegistration = new Map(all.map(item => [item.registration, item]));
  const fields = ['registration_no', 'registration_number', 'registration_id', 'racer_registration_id', 'racer_id', 'participant_id'];
  function get(race, person) {
    if (!race || race.sport !== 'boat' || race.scope === 'synthetic' || race.synthetic === true ||
        !person || person.placeholder) return null;
    const ids = fields.filter(key => Object.hasOwn(person, key)).map(key => person[key]);
    if (!ids.length || ids.some(id => typeof id !== 'string' || !/^\d{4}$/.test(id) || id !== ids[0])) return null;
    const item = byRegistration.get(ids[0]);
    if (!item || person.name != null && (typeof person.name !== 'string' ||
        person.name.replace(/\s+/g, '') !== item.name)) return null;
    return item;
  }
  const api = Object.freeze({all, get});
  if (typeof module === 'object' && module.exports) module.exports = api;
  else globalThis.RaceRacerPortraits = api;
})();
