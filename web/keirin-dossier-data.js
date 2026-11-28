/* Read only admitted public facts for a single race and its named starters. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./keirin-note-model.js'));
  else root.RaceKeirinDossierData = factory(root.RaceKeirinNote);
})(typeof window === 'object' ? window : globalThis, function (note) {
  'use strict';
  const {day: validDay, instantMicros: clock, sameClock} = note;
  const importedHistory = /* reviewed rider race facts */ null;

  const schemas = {
    starters: 'RACE_AI_KEIRIN_PUBLIC_STARTERS_V1',
    referenceStarters: 'RACE_AI_KEIRIN_PUBLIC_REFERENCE_STARTERS_V1',
    official: 'RACE_AI_KEIRIN_PUBLIC_DOSSIER_CONTEXT_V1',
    secondary: 'RACE_AI_KEIRIN_PUBLIC_DOSSIER_SECONDARY_V1',
    conditions: 'RACE_AI_KEIRIN_PUBLIC_DOSSIER_CONDITIONS_V1',
    archive: 'RACE_AI_KEIRIN_PUBLIC_RIDER_HISTORY_ARCHIVE_V1',
    rank: 'RACE_AI_KEIRIN_PUBLIC_RANK_DISTRIBUTION_V1',
    details: 'RACE_AI_KEIRIN_PUBLIC_FORECAST_DETAILS_V1',
  };
  const summaryByCode = {
    SELF_POWER: '自分で仕掛ける方針。',
    SELF_POWER_FLEXIBLE: '自分で動き、展開に応じて位置を選ぶ方針。',
    FLEXIBLE: '展開に応じて走り方を選ぶ方針。',
    SOLO: 'ラインを組まずに走る方針。',
    FORWARD: '前方の位置を取りにいく方針。',
    LEADING: '先頭を取る走りを考えている。',
    POSITION_OPEN: '取れた位置から走る方針。',
    FOLLOW: '指定した選手の後ろで走る方針。',
  };
  const countKeys = ['home_count','back_count','escape_count','makuri_count','difference_count','mark_count'];
  const historyScopes = ['OFFICIAL_SP_RESULT_REPLAY', 'PINNED_KDREAMS_ARCHIVE_AND_OFFICIAL_SP_RESULT_REPLAY'];
  const sha256 = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
  const car = value => Number.isInteger(value) && value >= 1 && value <= 9;
  const registration = value => typeof value === 'string' && /^\d{6}$/.test(value) && value !== '000000';
  const safeText = (value, max) => typeof value === 'string' && value.trim().length > 0 &&
    value.length <= max && !/[<>\p{C}]/u.test(value);
  const nameKey = value => value.normalize('NFKC').replace(/\s/gu, '');
  const exact = (value, names) => value && typeof value === 'object' && !Array.isArray(value) &&
    Object.keys(value).length === names.length && names.every(name => Object.hasOwn(value, name));
  const jstDay = value => new Date(Date.parse(value) + 9 * 3600000).toISOString().slice(0, 10);
  const dayFromId = id => `${id.slice(0,4)}-${id.slice(4,6)}-${id.slice(6,8)}`;
  const unique = values => new Set(values).size === values.length;
  const sum = values => values.reduce((total, value) => total + value, 0);
  const identityMatch = (first, second) => second && nameKey(first.name) === nameKey(second.name) &&
    (!first.registration || !second.registration || first.registration === second.registration);

  function requestedRow(packet, kind, day, raceId) {
    if (packet?.schema !== schemas[kind] || packet.day !== day || clock(packet.published_at) === null ||
        !Array.isArray(packet.races) || packet.races.length > 600) return null;
    const rows = packet.races.filter(row => row?.race_id === raceId);
    return rows.length === 1 ? rows[0] : null;
  }

  function namedField(riders, minimum, nullableRegistration) {
    return Array.isArray(riders) && riders.length >= minimum && riders.length <= 9 && riders.every(rider =>
      car(rider?.number) && safeText(rider.name, 100) && nameKey(rider.name) &&
      (registration(rider.registration) || (nullableRegistration && rider.registration === null))) &&
      unique(riders.map(rider => rider.number)) && unique(riders.map(rider => rider.registration).filter(Boolean));
  }

  function referenceRows(packet, day) {
    const published = clock(packet?.published_at), rows = new Map();
    if (packet?.schema !== schemas.referenceStarters || packet.day !== day || published === null ||
        !Array.isArray(packet.races) || packet.races.length > 300) return rows;
    for (const row of packet.races) {
      if (typeof row?.race_id !== 'string' || !/^20\d{8}(?:0[1-9]|1[0-2])$/.test(row.race_id) ||
          dayFromId(row.race_id) !== day || rows.has(row.race_id) || !sha256(row.source_sha256) ||
          !namedField(row.riders, 1, true)) return new Map();
      const observed = clock(row.source_at);
      const url = typeof row.source_url === 'string' &&
        /^https:\/\/keirin\.kdreams\.jp\/[a-z0-9-]+\/racecard\/(\d{2})(20\d{6})(0[1-7])00\/$/.exec(row.source_url);
      if (observed === null || observed > published || !url || url[1] !== row.race_id.slice(8,10)) return new Map();
      const first = dayFromId(url[2]);
      if (!validDay(first) || new Date(Date.parse(first) + (Number(url[3]) - 1) * 86400000).toISOString().slice(0,10) !== day) {
        return new Map();
      }
      rows.set(row.race_id, row);
    }
    return rows;
  }

  function rankedField(packet, row, day, cutoffAt) {
    if (!row || row.scope !== 'PROSPECTIVE_RESEARCH' || row.premise !== 'ALL_FINISH_NO_TIES' ||
        row.calibration_status !== 'UNVALIDATED' || !sha256(row.source_joint_sha256) || !sha256(row.model_sha256) ||
        !namedField(row.riders, 5, true) || (cutoffAt !== null && !sameClock(cutoffAt, row.cutoff_at))) return null;
    const stamps = [row.source_as_of,row.generated_at,row.frozen_at,row.witnessed_at,row.cutoff_at,packet.published_at].map(clock);
    const [source, generated, frozen, witnessed, cutoff, published] = stamps;
    if (stamps.includes(null) || !(source <= generated && generated <= frozen && frozen <= witnessed &&
        witnessed < cutoff && witnessed <= published)) return null;
    const raceDay = jstDay(row.cutoff_at);
    const next = new Date(Date.parse(day) + 86400000).toISOString().slice(0, 10);
    if (raceDay !== day && raceDay !== next) return null;
    const field = row.riders;
    const normalized = values => Math.abs(1 - sum(values)) <= 1e-8;
    if (!field.every(rider => Array.isArray(rider.probabilities) && rider.probabilities.length === field.length &&
        rider.probabilities.every(p => Number.isFinite(p) && p >= 0 && p <= 1) && normalized(rider.probabilities)) ||
        !field.every((_, rank) => normalized(field.map(rider => rider.probabilities[rank])))) return null;
    return row;
  }

  function contextField(packet, row, kind, day, cutoffAt, roster) {
    if (!row || clock(row.cutoff_at) === null || jstDay(row.cutoff_at) !== day ||
        (cutoffAt !== null && !sameClock(cutoffAt, row.cutoff_at)) ||
        !Array.isArray(row.riders) || row.riders.length !== roster.size ||
        !unique(row.riders.map(rider => rider?.number)) || !row.riders.every(rider => registration(rider?.registration) &&
          roster.get(rider.number)?.registration === rider.registration)) return null;
    const official = kind === 'official';
    const sourceAt = official ? row.card_at : row.source_at;
    const observed = clock(sourceAt), cutoff = clock(row.cutoff_at), published = clock(packet.published_at);
    if (observed === null || observed > published) return null;
    if (official) {
      const comment = clock(row.comments_at), updated = clock(row.comments_updated_at);
      if (comment === null || updated === null || !(observed <= comment && updated <= comment &&
          comment < cutoff && comment <= published) || !sha256(row.card_sha256) || !sha256(row.comments_sha256)) return null;
    } else {
      if (!sha256(row.source_sha256) || clock(row.source_cutoff_at) === null || jstDay(row.source_cutoff_at) !== day ||
          !secondaryRaceUrl(row.source_url, row.race_id, day)) return null;
    }
    return { riders: new Map(row.riders.map(rider => [rider.number, rider])), sourceAt, source: kind,
      commentAt: official ? row.comments_at : sourceAt, cutoffAt: row.cutoff_at,
      performance: official ? null : performanceEvidence(row.performance, row.race_id, day, published, roster) };
  }

  function secondaryRaceUrl(url, raceId, day) {
    const match = typeof url === 'string' && url.length <= 2048 &&
      /^https:\/\/keirin\.kdreams\.jp\/[a-z0-9-]+\/racedetail\/(\d{2})(20\d{6})(\d{2})00(\d{2})\/$/.exec(url);
    if (!match || match[1] !== raceId.slice(8,10) || match[4] !== raceId.slice(10) ||
        Number(match[3]) < 1 || Number(match[3]) > 7) return false;
    const start = dayFromId(match[2]);
    return validDay(start) && new Date(Date.parse(start) + (Number(match[3]) - 1) * 86400000).toISOString().slice(0, 10) === day;
  }

  function performanceUrl(url, raceId, day) {
    return typeof url === 'string' &&
      secondaryRaceUrl(url.replace(/\?pageType=(?:yoso|showResult)$/, ''), raceId, day);
  }

  function performanceEvidence(evidence, raceId, day, published, roster) {
    const at = clock(evidence?.source_at);
    if (at === null || at > published || !sha256(evidence.source_sha256) ||
        !performanceUrl(evidence.source_url, raceId, day) || !Array.isArray(evidence.riders) ||
        evidence.riders.length !== roster.size || !unique(evidence.riders.map(row => row?.number)) ||
        !evidence.riders.every(row => registration(row?.registration) &&
          roster.get(row.number)?.registration === row.registration)) return null;
    return {at:evidence.source_at, url:evidence.source_url, riders:new Map(evidence.riders.map(row => [row.number, row]))};
  }

  function archivedField(packet, raceId, day) {
    if (packet?.schema !== 'RACE_AI_KEIRIN_PUBLIC_DOSSIER_RACE_FACTS_V1' ||
        packet.source_scope !== 'PUBLIC_RACECARD_CHECKED_AFTER_CUTOFF' || clock(packet.checked_at) === null ||
        jstDay(packet.checked_at) < day || !Array.isArray(packet.races)) return null;
    const rows = packet.races.filter(row => row?.race_id === raceId);
    const row = rows[0];
    if (rows.length !== 1 || !performanceUrl(row.stats_url, raceId, day) || !sha256(row.stats_sha256) ||
        row.comments_url !== 'https://keirin.netkeiba.com/race/player_comment/?race_id=' + raceId ||
        !namedField(row.riders, 5, true)) return null;
    return { at:packet.checked_at, url:row.stats_url, comments:row.comments_url, riders:row.riders, afterCutoff:true };
  }

  function publishedRate(counts, evidence, deadline) {
    if (!evidence || !Array.isArray(counts) || counts.length !== 4 ||
        !counts.every(value => Number.isInteger(value) && value >= 0 && value <= 600) || sum(counts) === 0) return null;
    return {numerator:sum(counts.slice(0,3)), denominator:sum(counts), sourceAt:evidence.at, sourceUrl:evidence.url,
      afterCutoff:evidence.afterCutoff || (deadline !== null && clock(evidence.at) >= clock(deadline))};
  }

  function statistics(context, number) {
    const stats = context?.riders.get(number)?.stats;
    if (!stats || typeof stats !== 'object') return null;
    const decimal = (key, max) => Number.isFinite(stats[key]) && stats[key] >= 0 && stats[key] <= max ? stats[key] : null;
    const counts = Object.fromEntries(countKeys.map(key => [key, Number.isInteger(stats[key]) ? decimal(key, 200) : null]));
    if (context.source === 'secondary') counts.home_count = null;
    return {...counts, competition_points: decimal('competition_points', 150), win_rate_percent: decimal('win_rate_percent', 100),
      sourceAt: context.sourceAt, source: context.source};
  }

  function comment(context, number) {
    const value = context?.riders.get(number)?.comment;
    if (value?.state !== 'SUMMARIZED' || !Object.hasOwn(summaryByCode, value.code) || value.summary !== summaryByCode[value.code]) return null;
    const targetCar = value.code === 'FOLLOW' ? value.target_car : null;
    if (value.code === 'FOLLOW' && (targetCar === number || !context.riders.has(targetCar))) return null;
    return { summary: value.summary, at: context.commentAt, targetCar };
  }

  function recentResults(rider, day) {
    const rows = rider?.recent_results;
    if (!Array.isArray(rows) || rows.length > 7) return [];
    let before = day;
    const out = [];
    for (const row of rows) {
      if (!validDay(row?.day) || row.day >= before) return [];
      if (exact(row, ['day','rank']) && car(row.rank)) out.push({day:row.day, rank:row.rank});
      else if (exact(row, ['day','counts']) && Array.isArray(row.counts) && row.counts.length === 9 &&
          row.counts.every(value => Number.isInteger(value) && value >= 0 && value <= 40) &&
          sum(row.counts) >= 2 && sum(row.counts) <= 40) out.push({day:row.day, counts:row.counts.slice()});
      else return [];
      before = row.day;
    }
    return out;
  }

  function finishCounts(counts, maximum) {
    return Array.isArray(counts) && counts.length === 9 &&
      counts.every(n => Number.isSafeInteger(n) && n >= 0 && n <= maximum) &&
      sum(counts) > 0 && sum(counts) <= maximum;
  }

  function historyDay(packet, day) {
    if (!exact(packet, ['schema','day','source_sha256','archive_races','verified_races','riders']) ||
        packet.schema !== 'RACE_AI_KEIRIN_PUBLIC_RIDER_HISTORY_DAY_V1' || packet.day !== day || !validDay(day) ||
        !sha256(packet.source_sha256) || !Number.isInteger(packet.archive_races) ||
        !Number.isInteger(packet.verified_races) || !(0 < packet.verified_races &&
        packet.verified_races <= packet.archive_races && packet.archive_races <= 600)) return null;
    const field = packet.riders, verified = packet.verified_races;
    if (!Array.isArray(field) || field.length < 1 || field.length > 9 * verified || !field.every(rider =>
        exact(rider, ['registration','finish_counts']) && registration(rider.registration) &&
        finishCounts(rider.finish_counts, verified)) || !unique(field.map(rider => rider.registration))) return null;
    const finishTotal = sum(field.map(rider => sum(rider.finish_counts)));
    return finishTotal >= verified && finishTotal <= 9 * verified ?
      new Map(field.map(rider => [rider.registration, rider.finish_counts])) : null;
  }

  function historyDays(packets, day) {
    const days = new Map();
    if (!Array.isArray(packets) || packets.length > 7) return days;
    for (const packet of packets) {
      if (!validDay(packet?.day) || packet.day >= day) continue;
      const results = historyDay(packet, packet.day);
      if (results) days.set(packet.day, days.has(packet.day) ? null : results);
    }
    return days;
  }

  function recentFinish(day, counts) {
    return sum(counts) === 1 ? {day, rank:counts.indexOf(1) + 1} : {day, counts:counts.slice()};
  }

  function historyManifest(packet, today) {
    const published = clock(packet?.published_at);
    if (packet?.schema !== 'RACE_AI_KEIRIN_PUBLIC_RIDER_HISTORY_V1' || published === null ||
        jstDay(packet.published_at) > today || !validDay(packet.base_history_end_day) || !sha256(packet.base_sha256) ||
        !Array.isArray(packet.days) || packet.days.length < 1 || packet.days.length > 400 ||
        !Array.isArray(packet.riders) || packet.riders.length > 5000) return null;
    const days = new Map(), riders = new Map(), posted = jstDay(packet.published_at);
    let previous = packet.base_history_end_day, finishes = 0, races = 0;
    for (const row of packet.days) {
      if (!validDay(row?.day) || row.day <= previous || row.day > posted || !sha256(row.sha256) ||
          !Number.isSafeInteger(row.verified_races) || row.verified_races < 1 || row.verified_races > 600 ||
          !Number.isSafeInteger(row.observed_count) || row.observed_count < row.verified_races ||
          row.observed_count > 9 * row.verified_races) return null;
      days.set(row.day, row.sha256);
      previous = row.day;
      races += row.verified_races;
      finishes += row.observed_count;
    }
    let total = 0;
    for (const result of packet.riders) {
      if (!registration(result?.registration) || riders.has(result.registration) || !finishCounts(result.finish_counts, races) ||
          !days.has(result.first_observed_day) || !days.has(result.latest_observed_day) ||
          result.first_observed_day > result.latest_observed_day) return null;
      riders.set(result.registration, result);
      total += sum(result.finish_counts);
    }
    return total === finishes ? {published, baseEndDay:packet.base_history_end_day, days, riders} : null;
  }

  function confirmedHistory(data, manifest, daily) {
    const updates = new Map();
    if (data.archiveEndDay && data.archiveEndDay !== manifest.baseEndDay) return updates;
    for (const rider of data.riders) {
      const result = manifest.riders.get(rider.registration);
      const endDay = result?.latest_observed_day;
      const counts = daily.get(endDay)?.get(rider.registration);
      if (!counts || counts.some((n, i) => n > result.finish_counts[i]) || endDay < rider.history?.endDay) continue;
      const base = rider.historyBase;
      const history = {counts:result.finish_counts.map((n, i) => n + (base?.counts[i] ?? 0)),
        startDay:base?.startDay ?? result.first_observed_day, endDay};
      const recent = [recentFinish(endDay, counts), ...rider.recent.filter(row => row.day !== endDay)]
        .sort((a,b) => b.day.localeCompare(a.day)).slice(0, 7);
      updates.set(rider.number, {history, recent});
    }
    return updates;
  }

  function riderRecent(rider, day, days, registrationId) {
    const known = recentResults(rider, day);
    const exactDays = new Map(known.map(row => [row.day, row]));
    for (const [date, byRegistration] of days) {
      const counts = byRegistration?.get(registrationId);
      if (!counts || exactDays.has(date)) continue;
      exactDays.set(date, recentFinish(date, counts));
    }
    return [...exactDays.values()].sort((a,b) => b.day.localeCompare(a.day)).slice(0, 7);
  }

  function recentForm(rows, day) {
    const start = new Date(Date.parse(day) - 30 * 86400000).toISOString().slice(0, 10);
    const sample = rows.filter(row => row.day >= start);
    if (!sample.length) return null;
    const denominator = sum(sample.map(row => row.rank ? 1 : sum(row.counts)));
    const numerator = sum(sample.map(row => row.rank ? Number(row.rank <= 3) : sum(row.counts.slice(0, 3))));
    return {numerator, denominator, startDay:sample.at(-1).day, endDay:sample[0].day};
  }

  function archiveForDay(packet, day) {
    if (packet?.schema !== schemas.archive || !validDay(packet.start_day) || !validDay(packet.end_day) ||
        packet.start_day > packet.end_day || !Array.isArray(packet.source_sha256s) ||
        packet.source_sha256s.length < 1 || packet.source_sha256s.length > 100 || !packet.source_sha256s.every(sha256) ||
        !Number.isSafeInteger(packet.numeric_finishes) || packet.numeric_finishes < 1 ||
        !Array.isArray(packet.riders) || packet.riders.length > 5000) return null;
    const venueStartDay = packet.venue_start_day ?? packet.start_day;
    const venueEndDay = packet.venue_end_day ?? packet.end_day;
    if (!validDay(venueStartDay) || !validDay(venueEndDay) || venueStartDay < packet.start_day ||
        venueStartDay > venueEndDay || venueEndDay > packet.end_day) return null;
    const first = packet.observations_start_day, last = packet.observations_end_day;
    const observations = validDay(first) && validDay(last) && packet.start_day <= first &&
      first <= last && last <= packet.end_day && last < day ? {startDay:first, endDay:last} : null;
    const riders = new Map();
    let finishes = 0;
    for (const rider of packet.riders) {
      if (!registration(rider?.registration) || riders.has(rider.registration) || !Array.isArray(rider.counts) ||
          rider.counts.length !== 9 || rider.counts.some(n => !Number.isSafeInteger(n) || n < 0) ||
          !rider.venues || typeof rider.venues !== 'object' || Array.isArray(rider.venues)) return null;
      const total = sum(rider.counts);
      if (total < 1 || total > packet.numeric_finishes) return null;
      let venueStarts = 0;
      for (const [code, row] of Object.entries(rider.venues)) {
        if (!/^[1-9]\d$/.test(code) || !Array.isArray(row) || row.length !== 2 ||
            !row.every(Number.isSafeInteger) || row[0] < 0 || row[1] < 1 || row[0] > row[1]) return null;
        venueStarts += row[1];
      }
      if (venueStarts > total) return null;
      finishes += total;
      riders.set(rider.registration, rider);
    }
    if (finishes !== packet.numeric_finishes) return null;
    return {riders, startDay:packet.start_day, endDay:packet.end_day, venueStartDay, venueEndDay, observations,
      totalAvailable:packet.end_day < day, venueAvailable:venueEndDay < day};
  }

  function collectedHistory(archive, days, registrationId, venueCode) {
    const rider = archive?.riders.get(registrationId);
    const hasTotal = rider && archive.totalAvailable;
    const counts = hasTotal ? rider.counts.slice() : Array(9).fill(0);
    let startDay = hasTotal ? archive.startDay : null, endDay = hasTotal ? archive.endDay : null;
    for (const [date, registers] of days) {
      if (hasTotal && date <= archive.endDay) continue;
      const observed = registers?.get(registrationId);
      if (!observed) continue;
      observed.forEach((n, i) => { counts[i] += n; });
      if (startDay === null || date < startDay) startDay = date;
      if (endDay === null || date > endDay) endDay = date;
    }
    const venue = archive?.venueAvailable ? rider?.venues[venueCode] : null;
    const [runs, peers, score] = Array.isArray(rider?.agari) ? rider.agari : [];
    const observed = archive?.observations;
    const agari = observed && [runs, peers, score].every(Number.isSafeInteger) &&
      0 < runs && runs <= sum(rider.counts) && runs <= peers && peers <= 8 * runs && 0 <= score && score <= 2 * peers ?
      {...observed, runs, peers, percentile:1 - score / (2 * peers)} : null;
    const methods = rider?.techniques;
    const techniques = observed && methods && typeof methods === 'object' && !Array.isArray(methods) &&
      Object.entries(methods).every(([key, value]) => ['escape','makuri','difference','mark'].includes(key) &&
        Number.isSafeInteger(value) && value >= 0) && sum(Object.values(methods)) > 0 &&
      sum(Object.values(methods)) <= rider.counts[0] + rider.counts[1] ? {...observed, counts:methods} : null;
    return {history:startDay ? {counts, startDay, endDay} : null, venue:venue ?
      {numerator:venue[0], denominator:venue[1], startDay:archive.venueStartDay, endDay:archive.venueEndDay} : null,
      agari, techniques};
  }

  function semiFinals(packet, context, registrationId, day) {
    const history = packet?.history;
    if (!context || !sha256(packet.calendar_sha256) || !sha256(context.list_sha256) || clock(context.source_at) === null ||
        clock(context.source_at) > clock(packet.published_at) || !registration(registrationId) ||
        !historyScopes.includes(history?.scope) || !validDay(history.start_day) || !validDay(history.end_day) ||
        history.start_day > history.end_day || history.end_day >= day || !Array.isArray(history.source_sha256s) ||
        !history.source_sha256s.length || history.source_sha256s.length > 402 || !history.source_sha256s.every(sha256) ||
        !Array.isArray(packet.riders) || packet.riders.length > 10000) return null;
    const riders = packet.riders.filter(rider => rider?.registration === registrationId);
    const cells = riders.length === 1 ? riders[0].cells : null;
    if (!Array.isArray(cells) || cells.length > 100) return null;
    const exactStage = cells.filter(cell => cell?.round_stage === 'SEMI_FINAL' && cell.meeting_grade === null);
    if (exactStage.length !== 1) return null;
    const {wins, top2, top3, numeric_finishes: starts} = exactStage[0];
    if (![wins,top2,top3,starts,history.condition_matched_finishes,history.numeric_finishes].every(Number.isSafeInteger) ||
        !(0 <= wins && wins <= top2 && top2 <= top3 && top3 <= starts && starts > 0 &&
          starts <= history.condition_matched_finishes && history.condition_matched_finishes <= history.numeric_finishes)) return null;
    return {numerator:top3, denominator:starts, startDay:history.start_day, endDay:history.end_day};
  }

  function savedTactics(packet, row, publishedForecast, cutoffAt, roster) {
    const saved = clock(row?.saved_at), cutoff = clock(cutoffAt);
    if (saved === null || cutoff === null || saved >= cutoff || saved > clock(packet.published_at) ||
        !sameClock(row.saved_at, publishedForecast?.savedAt)) return null;
    const arm = row.b, tickets = publishedForecast.b;
    const triple = ticket => Array.isArray(ticket) && ticket.length === 3 && unique(ticket) && ticket.every(number => roster.has(number));
    if (!Array.isArray(tickets) || tickets.length < 1 || tickets.length > 8 || !tickets.every(triple) ||
        !Array.isArray(arm?.tickets) || JSON.stringify(tickets) !== JSON.stringify(arm.tickets) ||
        !Array.isArray(arm.reasons) || arm.reasons.length < 1 || arm.reasons.length > 4 || !arm.reasons.every(reason => safeText(reason, 240)) ||
        !Array.isArray(arm.scenarios) || arm.scenarios.length !== Math.min(tickets.length, 2)) return null;
    if (!arm.scenarios.every((scenario, index) => JSON.stringify(scenario?.ticket) === JSON.stringify(tickets[index]) &&
        Array.isArray(scenario.orders) && scenario.orders.length === 6 && scenario.orders.every(order => order === null ||
          (Array.isArray(order) && order.length === roster.size && unique(order) && order.every(number => roster.has(number)))) &&
        (scenario.orders[5] === null || JSON.stringify(scenario.orders[5].slice(0, 3)) === JSON.stringify(scenario.ticket)))) return null;
    return {savedAt:row.saved_at, reasons:arm.reasons.slice(), scenarios:arm.scenarios};
  }

  function prepare({raceId, cutoffAt = null, publishedForecast, packets = {}, archived = importedHistory} = {}) {
    const empty = {riders:[], cutoffAt:null, sourceAt:null};
    if (typeof raceId !== 'string' || !/^20\d{8}(?:0[1-9]|1[0-2])$/.test(raceId) ||
        !validDay(dayFromId(raceId)) || !packets || (cutoffAt !== null && clock(cutoffAt) === null)) return empty;
    const day = dayFromId(raceId);
    const find = kind => requestedRow(packets[kind], kind, day, raceId);
    const starter = find('starters');
    const reference = referenceRows(packets.referenceStarters, day).get(raceId);
    const rank = rankedField(packets.rank, find('rank'), day, cutoffAt);
    const archive = archivedField(archived, raceId, day);
    const withStarters = namedField(starter?.riders, 3, false) && clock(starter.source_at) !== null &&
      clock(starter.source_at) <= clock(packets.starters.published_at);
    const field = withStarters ? starter.riders : reference?.riders ?? rank?.riders ?? archive?.riders;
    if (!field) return empty;
    const roster = new Map(field.map(rider => [rider.number, rider]));
    const official = contextField(packets.official, find('official'), 'official', day, cutoffAt, roster);
    const secondary = contextField(packets.secondary, find('secondary'), 'secondary', day, cutoffAt ?? official?.cutoffAt ?? null, roster);
    const observedCutoff = cutoffAt ?? official?.cutoffAt ?? secondary?.cutoffAt ?? null;
    const matchingRank = rank?.riders.length === roster.size && (observedCutoff === null || sameClock(rank.cutoff_at, observedCutoff)) &&
      rank.riders.every(rider => identityMatch(rider, roster.get(rider.number))) ?
      new Map(rank.riders.map(rider => [rider.number, rider])) : null;
    const matchingArchive = archive?.riders.length === roster.size && archive.riders.every(rider => identityMatch(rider, roster.get(rider.number))) ?
      new Map(archive.riders.map(rider => [rider.number, rider])) : null;
    const archivedContext = matchingArchive && {riders:matchingArchive, source:'archive', sourceAt:archive.at};
    const deadline = observedCutoff ?? (matchingRank ? rank.cutoff_at : null);
    const details = find('details'), conditions = find('conditions');
    const tactics = savedTactics(packets.details, details, publishedForecast, deadline, roster);
    const history = historyDays(packets.recentDays, day);
    const archiveHistory = archiveForDay(packets.archive, day);
    const riders = field.slice().sort((a,b) => a.number - b.number).map(rider => {
      const {number, name, registration, style} = rider;
      const prediction = matchingRank?.get(number);
      const old = matchingArchive?.get(number), performance = secondary?.performance;
      const publishedStyle = style ?? old?.style;
      const measured = performance?.riders.get(number);
      const currentRecent = riderRecent(official?.riders.get(number), day, history, registration);
      const recent = currentRecent.length ? currentRecent : recentResults(old, day);
      const collected = collectedHistory(archiveHistory, history, registration, raceId.slice(8, 10));
      return {number, name, registration, style:['逃','追','両'].includes(publishedStyle) ? publishedStyle : null,
        registrationBasis:rider.registration_basis === 'VERIFIED_DIRECTORY_NAME_PREFECTURE' ?
          '公開登録名簿で氏名・府県を照合' : null,
        stats:statistics(official, number) ?? statistics(secondary, number) ?? statistics(archivedContext, number),
        comment:comment(official, number) ?? comment(secondary, number) ??
          (safeText(old?.comment, 240) ? {summary:old.comment, at:archive.at, url:archive.comments} : null),
        recent, form:recentForm(recent, day), history:collected.history,
        historyBase:archiveHistory?.riders.has(registration) ?
          {counts:archiveHistory.riders.get(registration).counts, startDay:archiveHistory.startDay} : null,
        agari:collected.agari, techniques:collected.techniques,
        semi:publishedRate(measured?.semi, performance, deadline) ?? publishedRate(old?.semifinal_counts, archive, deadline) ??
          semiFinals(packets.conditions, conditions, registration, day),
        venue:publishedRate(measured?.venue, performance, deadline) ?? publishedRate(old?.venue_counts, archive, deadline) ?? collected.venue,
        rank:prediction ? {probabilities:prediction.probabilities.slice(), frozenAt:rank.frozen_at,
          witnessedAt:rank.witnessed_at, sourceAsOf:rank.source_as_of, cutoffAt:rank.cutoff_at, modelSha:rank.model_sha256} : null,
        tactics:tactics ? {savedAt:tactics.savedAt, reasons:tactics.reasons.slice(), positions:tactics.scenarios.map(scenario =>
          scenario.orders.map(order => order ? order.indexOf(number) + 1 : null))} : null};
    });
    const rosterSource = !withStarters && reference ? {url:reference.source_url, at:reference.source_at} : null;
    return {riders, cutoffAt:deadline, rosterSource, archiveEndDay:archiveHistory?.endDay,
      sourceAt:withStarters ? starter.source_at : rosterSource?.at ?? rank?.source_as_of ?? archive.at};
  }

  return {prepare, referenceRows, historyManifest, historyDay, confirmedHistory, namedField, identityMatch};
});
