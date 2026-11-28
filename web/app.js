if (typeof window === 'object' && typeof location === 'object') window.RaceNoteInitialFragment = location.hash;
/* The public hash boots a read-only view in its own document. */
(() => {
  "use strict";
  const byId = id => globalThis.document?.getElementById(id);
  const panel = byId("page-keirin-public");
  if (!panel) return;

  const hash = "#keirin-public";
  const isPublic = location.hash === hash;
  window.addEventListener("hashchange", event => {
    if (isPublic === (location.hash === hash)) return;
    event.stopImmediatePropagation();
    location.reload();
  });
  if (!isPublic) return;

  document.body.classList.add("keirin-public-page");
  panel.hidden = false;
  document.querySelector(".skip-link")?.addEventListener("click", event => {
    event.preventDefault();
    byId("keirin-public-title").focus();
  });

  const dayInput = byId("keirin-public-day");
  const status = byId("keirin-public-status");
  const updated = byId("keirin-public-updated");
  const races = byId("keirin-public-races");
  const base = "https://raw.githubusercontent.com/haji84/RACE-AI/state/keirin-public-forecasts/";
  const resultsBase = "https://raw.githubusercontent.com/haji84/RACE-AI/state/keirin-public-results/";
  const scoreboard = element("section", "keirin-public-summary");
  scoreboard.id = "keirin-public-scoreboard";
  scoreboard.setAttribute("aria-label", "結果照合とモデル別的中率");
  scoreboard.hidden = true;
  races.before(scoreboard);
  const jstToday = globalThis.RaceAuditModel.jstToday;
  const jstDateTime = new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23"
  });
  // Venue codes from the official KEIRIN.JP venue list (keirin.jp/sp/jyolist).
  const venues = {
    11: "函館", 12: "青森", 13: "いわき平", 21: "弥彦", 22: "前橋", 23: "取手", 24: "宇都宮",
    25: "大宮", 26: "西武園", 27: "京王閣", 28: "立川", 31: "松戸", 32: "千葉", 34: "川崎",
    35: "平塚", 36: "小田原", 37: "伊東温泉", 38: "静岡", 42: "名古屋", 43: "岐阜",
    44: "大垣", 45: "豊橋", 46: "富山", 47: "松阪", 48: "四日市", 51: "福井", 53: "奈良",
    54: "向日町", 55: "和歌山", 56: "岸和田", 61: "玉野", 62: "広島", 63: "防府",
    71: "高松", 73: "小松島", 74: "高知", 75: "松山", 81: "小倉", 83: "久留米",
    84: "武雄", 85: "佐世保", 86: "別府", 87: "熊本"
  };
  let currentRequest, resultRequest, activeDay;

  function validDay(day) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return false;
    const date = new Date(day + "T00:00:00Z");
    return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === day;
  }

  function validClock(value) {
    return typeof value === "string" && value.length <= 40 &&
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
      validDay(value.slice(0, 10)) && Number.isFinite(Date.parse(value));
  }

  function validCars(cars, minimum) {
    return Array.isArray(cars) && cars.length >= minimum && cars.length <= 9 &&
      cars.every((car, i) => Number.isInteger(car) && car >= 1 && car <= 9 && (i === 0 || car > cars[i - 1]));
  }

  function validTickets(tickets, limit = 8) {
    return Array.isArray(tickets) && tickets.length >= 1 && tickets.length <= limit &&
      tickets.every(ticket => Array.isArray(ticket) && ticket.length === 3 &&
        ticket.every(car => Number.isInteger(car) && car >= 1 && car <= 9) && new Set(ticket).size === 3) &&
      new Set(tickets.map(ticket => ticket.join("-"))).size === tickets.length;
  }

  function validPacket(snapshot, day, schema) {
    return snapshot?.schema === schema && snapshot.day === day && validClock(snapshot.published_at) &&
      Array.isArray(snapshot.races) && snapshot.races.length <= 300;
  }

  function validRaceId(id, datePrefix, seen) {
    if (typeof id !== "string" || !/^\d{10}(?:0[1-9]|1[0-2])$/.test(id) || !id.startsWith(datePrefix) || seen.has(id)) return false;
    seen.add(id);
    return true;
  }

  function validSnapshot(snapshot, day) {
    if (!validPacket(snapshot, day, "RACE_AI_KEIRIN_PUBLIC_FORECASTS_V1")) return false;
    const seen = new Set(), datePrefix = day.replaceAll("-", "");
    return snapshot.races.every(row => {
      if (!validRaceId(row?.race_id, datePrefix, seen) ||
          !Array.isArray(row.a) || !Array.isArray(row.b) || (row.cutoff_at !== null && !validClock(row.cutoff_at))) return false;
      if (row.status === "pending") return row.saved_at === null && row.a.length === 0 && row.b.length === 0;
      return row.status === "saved" && validClock(row.saved_at) && row.cutoff_at !== null &&
        Date.parse(row.saved_at) < Date.parse(row.cutoff_at) &&
        Date.parse(row.saved_at) <= Date.parse(snapshot.published_at) &&
        validTickets(row.a) && validTickets(row.b);
    });
  }

  function publicCandidates(snapshot, day, research) {
    const schema = research ? "RACE_AI_KEIRIN_PUBLIC_RESULT_UNREAD_AB_V1" : "RACE_AI_KEIRIN_PUBLIC_REFERENCE_FORECASTS_V1";
    const records = new Map(), seen = new Set(), datePrefix = day.replaceAll("-", "");
    if (!validPacket(snapshot, day, schema)) return records;
    for (const row of snapshot.races) {
      if (!validRaceId(row?.race_id, datePrefix, seen) || !validClock(row.cutoff_at) ||
          jstToday(new Date(row.cutoff_at)) !== day || !Array.isArray(row.a) || !Array.isArray(row.b)) return new Map();
      const created = research ? row.generated_at : row.saved_at;
      if (!validClock(created) || Date.parse(created) > Date.parse(snapshot.published_at)) return new Map();
      const inTime = Date.parse(created) < Date.parse(row.cutoff_at);
      if (research) {
        const cars = row.starter_cars;
        if (!validCars(cars, 5)) return new Map();
        const arms = [row.a, row.b].filter(tickets => tickets.length);
        if (!arms.length || !arms.every(tickets => validTickets(tickets)) ||
            !arms.flat(2).every(car => cars.includes(car))) return new Map();
      } else if (!inTime || !validTickets(row.a) || !validTickets(row.b)) {
        return new Map();
      }
      const status = research ? (inTime ? "research" : "late-research") : "reference";
      records.set(row.race_id, { race_id: row.race_id, a: row.a, b: row.b, status,
        cutoff_at: row.cutoff_at, saved_at: created, published_at: snapshot.published_at,
        starter_cars: row.starter_cars });
    }
    return records;
  }

  const hasFields = (value, fields) => !!value && typeof value === "object" && !Array.isArray(value) &&
    Object.keys(value).length === fields.length && fields.every(field => Object.hasOwn(value, field));
  const instant = value => globalThis.RaceKeirinNote?.instantMicros(value) ?? null;
  const dtModelSha = "5e022092a35c0258954090c6f3d0f8fa14f03f22511b28d6aa9183f5a38c381c";

  function dtShortlists(packet, day) {
    const fields = ["schema", "day", "model_id", "model_sha256", "policy", "input_commit", "published_at", "races"];
    const races = new Map(), seen = new Set(), prefix = day.replaceAll("-", "");
    if (!hasFields(packet, fields) || !validPacket(packet, day, "RACE_AI_KEIRIN_PUBLIC_DT_R1_V1") ||
        packet.model_id !== "chatgpt-dt-r1" || packet.policy !== "dt-r1-public-ranked-mass-v1" ||
        packet.model_sha256 !== dtModelSha ||
        typeof packet.input_commit !== "string" || !/^[a-f0-9]{40}$/.test(packet.input_commit)) return races;
    const published = instant(packet.published_at);
    if (published === null) return races;
    for (const row of packet.races) {
      if (!hasFields(row, ["race_id", "cutoff_at", "selected_at", "source_at", "starter_cars", "tickets", "reason"]) ||
          !validRaceId(row.race_id, prefix, seen) || !validCars(row.starter_cars, 3) ||
          !validTickets(row.tickets, 12) || !row.tickets.flat().every(car => row.starter_cars.includes(car)) ||
          !["COVERAGE_REACHED", "ODDS_CAP", "MAX_POINTS"].includes(row.reason)) return new Map();
      const [cutoff, selected, source] = [row.cutoff_at, row.selected_at, row.source_at].map(instant);
      if (cutoff === null || selected === null || source === null || jstToday(new Date(row.cutoff_at)) !== day ||
          source >= cutoff || source > selected || selected > published) return new Map();
      const timing = selected >= cutoff ? "締切後の再計算" : published >= cutoff ? "締切後掲載" : "締切前掲載";
      races.set(row.race_id, { ...row, timing, published_at: packet.published_at });
    }
    return races;
  }

  function boundResultSource(source, raceId, observed) {
    if (!hasFields(source, ["source_id", "url", "checked_at"]) || instant(source.checked_at) === null ||
        instant(source.checked_at) > observed || typeof source.url !== "string" || source.url.length >= 2048) return false;
    const safe = globalThis.RaceKeirinNote?.safeUrl(source.url);
    if (!safe) return false;
    const url = new URL(safe);
    if (url.hash || url.port) return false;
    if (source.source_id === "netkeirin") {
      return url.hostname === "keirin.netkeiba.com" && url.pathname === "/race/result/" &&
        url.search === "?race_id=" + raceId;
    }
    if (source.source_id !== "kdreams" || url.hostname !== "keirin.kdreams.jp" ||
        !["", "?pageType=result"].includes(url.search)) return false;
    const match = /^\/[a-z0-9-]+\/racedetail\/(\d{2})(20\d{6})(\d{2})00(\d{2})\/$/.exec(url.pathname);
    if (!match || match[1] !== raceId.slice(8, 10) || match[4] !== raceId.slice(10) || Number(match[3]) < 1) return false;
    const start = match[2].replace(/^(\d{4})(\d{2})(\d{2})$/, "$1-$2-$3");
    if (!validDay(start)) return false;
    const raceDay = new Date(Date.parse(start + "T00:00:00Z") + (Number(match[3]) - 1) * 86400000);
    return raceDay.toISOString().slice(0, 10).replaceAll("-", "") === raceId.slice(0, 8);
  }

  function publishedResultRows(packet, day) {
    const races = new Map(), seen = new Set(), prefix = day.replaceAll("-", "");
    if (packet === undefined) return races;
    if (!hasFields(packet, ["schema", "date", "checked_at", "races"]) || packet.schema !== "KEIRIN_PUBLISHED_RESULTS_V1" ||
        packet.date !== day || !Array.isArray(packet.races) || packet.races.length > 300) return null;
    const checked = instant(packet.checked_at);
    if (checked === null) return null;
    for (const row of packet.races) {
      if (!validRaceId(row?.race_id, prefix, seen)) return null;
      if (row.state === "pending" || row.state === "held") {
        const reasons = row.state === "held" ? ["special_result", "source_disagreement"] : ["result_unpublished", "source_unavailable"];
        if (!hasFields(row, ["race_id", "state", "reason"]) || !reasons.includes(row.reason)) return null;
      } else {
        const result = row.comparison;
        if (row.state !== "matched" || !hasFields(row, ["race_id", "state", "comparison"]) ||
            !hasFields(result, ["race_id", "observed_at", "authority", "comparison_scope", "winning_3t", "winning_2t", "payouts_100yen", "sources"]) ||
            result.race_id !== row.race_id || result.authority !== "cross_source_reference" ||
            result.comparison_scope !== "POST_CUTOFF_REFERENCE" || !validTickets([result.winning_3t], 1) ||
            !Array.isArray(result.winning_2t) || result.winning_2t.length !== 2 ||
            !result.winning_2t.every((car, i) => car === result.winning_3t[i]) ||
            !hasFields(result.payouts_100yen, ["2t", "3t"]) ||
            !Object.values(result.payouts_100yen).every(yen => Number.isSafeInteger(yen) && yen >= 100 && yen <= 1e9)) return null;
        const observed = instant(result.observed_at);
        if (observed === null || observed > checked || !Array.isArray(result.sources) || result.sources.length !== 2 ||
            !result.sources.every(source => boundResultSource(source, row.race_id, observed)) ||
            result.sources[0].source_id === result.sources[1].source_id) return null;
      }
      races.set(row.race_id, row);
    }
    return races;
  }

  function resultReceipt(day, roster, packet, results) {
    if (!packet || !results || !hasFields(roster, ["schema", "date", "generated_at", "forecast_asset_sha256", "races"]) ||
        roster.schema !== "KEIRIN_PUBLIC_RESULT_ROSTER_V1" || roster.date !== day ||
        instant(roster.generated_at) === null || !/^[a-f0-9]{64}$/.test(roster.forecast_asset_sha256) ||
        !Array.isArray(roster.races) || roster.races.length > 300) return null;
    const outcomes = new Map(), seen = new Set(), prefix = day.replaceAll("-", "");
    for (const row of roster.races) {
      if (!validRaceId(row?.race_id, prefix, seen)) return null;
      const entry = results.get(row.race_id), cutoff = instant(row.published_cutoff_at);
      if (!entry || row.date !== day || cutoff === null || jstToday(new Date(row.published_cutoff_at)) !== day) continue;
      if (entry.state !== "matched") {
        outcomes.set(row.race_id, entry);
        continue;
      }
      const result = entry.comparison;
      const cars = Array.isArray(row.observed_riders) ? row.observed_riders.map(rider => rider?.number).sort((a, b) => a - b) : [];
      const kd = result.sources.find(source => source.source_id === "kdreams");
      if (!validCars(cars, 3) || !result.winning_3t.every(car => cars.includes(car)) ||
          (kd.url !== row.source_url && kd.url !== row.source_url + "?pageType=result") ||
          result.sources.some(source => instant(source.checked_at) < cutoff)) continue;
      outcomes.set(row.race_id, { ...result, cutoff, cars: new Set(cars) });
    }
    return { checkedAt: packet.checked_at, outcomes };
  }

  const confidenceBands = [[.90, "VERY_HIGH", "激アツ🔥"], [.80, "HIGH", "高"], [.60, "MEDIUM", "中"], [0, "LOW", "低"]];
  const probability = value => Number.isFinite(value) && value >= 0 && value <= 1;
  const percent = value => (100 * value).toFixed(1) + "%";
  const confidenceKey = (lane, arm, points) => [lane, arm, points].join("/");

  function confidenceRows(packet, day) {
    const entries = new Map();
    if (packet?.schema !== "RACE_AI_KEIRIN_PUBLIC_SHORTLIST_CONFIDENCE_V1" || packet.day !== day ||
        !validClock(packet.assessed_at) || !/^[a-f0-9]{40}$/.test(packet.archive_commit) ||
        !Array.isArray(packet.rows) || packet.rows.length > 48) return entries;
    const dayAt = Date.parse(day + "T00:00:00Z");
    const relative = offset => new Date(dayAt - offset * 86400000).toISOString().slice(0, 10);
    if (JSON.stringify(packet.training_window) !== JSON.stringify([relative(10), relative(4)]) ||
        JSON.stringify(packet.validation_window) !== JSON.stringify([relative(3), relative(1)])) return entries;
    const counts = (row, maxDays) => row && Number.isInteger(row.n) && row.n >= 0 && row.n <= 300 * maxDays &&
      Number.isInteger(row.hits) && row.hits >= 0 && row.hits <= row.n &&
      Number.isInteger(row.days) && row.days >= (row.n ? 1 : 0) && row.days <= Math.min(row.n, maxDays);
    for (const row of packet.rows) {
      if (!["official", "reference", "racecard"].includes(row?.lane) || !["A", "B"].includes(row.arm) ||
          !Number.isInteger(row.points) || row.points < 1 || row.points > 8 || !counts(row.fit, 7) ||
          !counts(row.validation, 3)) return new Map();
      const key = confidenceKey(row.lane, row.arm, row.points);
      if (entries.has(key)) return new Map();
      if (row.ci95 !== null && (!Array.isArray(row.ci95) || row.ci95.length !== 2 ||
          !row.ci95.every(probability) || row.ci95[0] > row.ci95[1])) return new Map();
      if (row.state === "GRADED") {
        const rate = row.probability;
        if (!probability(rate) || rate !== row.fit.hits / row.fit.n || row.fit.n < 20 || row.fit.days < 3 ||
            row.validation.n < 30 || row.validation.days < 3 || !row.ci95) return new Map();
        const [threshold, grade, label] = confidenceBands.find(([value]) => rate >= value);
        const observed = row.validation.hits / row.validation.n;
        if (row.grade !== grade || observed < threshold || Math.abs(observed - rate) > .10 ||
            rate < row.ci95[0] || rate > row.ci95[1] ||
            (threshold >= .8 && row.ci95[0] < threshold)) return new Map();
        entries.set(key, { ...row, label, window: packet.validation_window });
      } else {
        if (typeof row.state !== "string" || !/^HOLD_CALIBRATION_[A-Z_]{1,45}$/.test(row.state) ||
            row.probability !== null || row.grade !== null) return new Map();
        entries.set(key, row);
      }
    }
    return entries;
  }

  async function replayConfidenceRows(packet, day, research) {
    const entries = new Map();
    const digest = globalThis.RaceKeirinConfidence?.digest;
    if (!digest || packet?.schema !== "RACE_AI_KEIRIN_PUBLIC_RACECARD_REPLAY_V1" ||
        packet.scope !== "RETROSPECTIVE_REPLAY" || packet.day !== day || !validClock(packet.assessed_at) ||
        !validClock(packet.forecast_published_at) || Date.parse(packet.forecast_published_at) > Date.parse(packet.assessed_at) ||
        jstToday(new Date(packet.assessed_at)) !== day || !/^[a-f0-9]{40}$/.test(packet.forecast_commit) ||
        !/^[a-f0-9]{64}$/.test(packet.tree_sha256) || !/^[a-f0-9]{64}$/.test(packet.archive_sha256) ||
        !Array.isArray(packet.races) || packet.races.length > 300 ||
        !Array.isArray(packet.bins) || packet.bins.length > 4 ||
        !Array.isArray(packet.replay_window) || packet.replay_window.length !== 2) return entries;
    const [start, end] = packet.replay_window;
    if (typeof start !== "string" || typeof end !== "string" ||
        !validDay(start) || !validDay(end) || start > end || end >= day) return entries;
    const windowDays = 1 + (Date.parse(end) - Date.parse(start)) / 86400000;
    const intervals = [[0, .15], [.15, .25], [.25, .35], [.35, .60]];
    const bands = new Map();
    for (const band of packet.bins) {
      const index = intervals.findIndex(([lo, hi]) => band?.lower === lo && band?.upper === hi);
      if (index < 0 || bands.has(index) || !Number.isInteger(band.n) || band.n < 30 ||
          !Number.isInteger(band.days) || band.days < 3 || band.days > Math.min(windowDays, band.n) ||
          band.n > 300 * band.days || !Number.isInteger(band.hits) || band.hits <= 0 || band.hits > band.n ||
          !probability(band.mean_probability) || band.mean_probability < band.lower || band.mean_probability >= band.upper ||
          Math.abs(band.mean_probability - band.hits / band.n) > .10 ||
          !Array.isArray(band.ci95) || band.ci95.length !== 2 || !band.ci95.every(probability) ||
          band.ci95[0] > band.mean_probability || band.ci95[1] < band.mean_probability) return entries;
      bands.set(index, band);
    }
    const seen = new Set(), prefix = day.replaceAll("-", ""), assessed = Date.parse(packet.assessed_at);
    for (const row of packet.races) {
      if (!validRaceId(row?.race_id, prefix, seen) || row.points !== 8 ||
          !probability(row.probability) || !/^[a-f0-9]{64}$/.test(row.ticket_sha256)) return new Map();
      const band = bands.get(intervals.findIndex(([lo, hi]) => row.probability >= lo && row.probability < hi));
      const original = research.get(row.race_id);
      if (!band || original?.status !== "research" || original.starter_cars.length !== 7 || original.b.length ||
          Date.parse(original.published_at) < Date.parse(packet.forecast_published_at) ||
          original.a.length !== row.points || assessed < Date.parse(original.saved_at) ||
          assessed >= Date.parse(original.cutoff_at) || (await digest(original.a).catch(() => null)) !== row.ticket_sha256) continue;
      entries.set(row.race_id, { probability: row.probability, band });
    }
    return entries;
  }

  function element(tag, className, label) {
    const result = document.createElement(tag);
    if (className) result.className = className;
    if (label !== undefined) result.textContent = label;
    return result;
  }

  function clock(value, day, seconds = true) {
    const date = new Date(value);
    const full = jstDateTime.format(date);
    const label = day === jstToday(date) ? (seconds ? full.slice(-8) : full.slice(-8, -3)) : full;
    const result = element("time", "", label);
    result.dateTime = value;
    return result;
  }

  function confidenceText(points, rating) {
    if (!rating) return points + "点 · 同じ方式・点数の照合実績を収集中";
    const { fit, validation } = rating;
    if (rating.state === "GRADED") {
      return "信頼度 " + rating.label + " · 的中確率 " + percent(rating.probability) + " · " + points +
        "点。検証 " + validation.hits + " / " + validation.n + "件的中（" +
        rating.window.map(day => day.slice(5).replace("-", "/")).join("〜") + "）";
    }
    const actual = validation.n ? validation.hits + " / " + validation.n + "件（" +
      percent(validation.hits / validation.n) + "）" : "0件";
    const reasons = {
      HOLD_CALIBRATION_ERROR: "検証期間での差が大きい",
      HOLD_CALIBRATION_FIT_INSUFFICIENT: "校正用の件数が不足",
      HOLD_CALIBRATION_INSUFFICIENT: "別期間の検証件数が不足",
      HOLD_CALIBRATION_OUT_OF_TIME_MISSING: "別期間の照合記録が不足",
      HOLD_CALIBRATION_MODEL_PROVENANCE: "予想方式の版を照合中",
    };
    const fitText = fit.n ? " · 校正用 " + fit.hits + " / " + fit.n + "件" : "";
    return points + "点 · 検証実績 " + actual + fitText + "。" +
      (reasons[rating.state] || "信頼度の認定基準に未達");
  }

  function rankedTickets(label, tickets) {
    const list = element("ol");
    list.setAttribute("aria-label", label + "の三連単（予想順）");
    list.append(...tickets.map(ticket => element("li", "", ticket.join("–"))));
    return list;
  }

  function ticketList(arm, tickets, rating, replay) {
    const group = element("div", "keirin-public-model");
    group.append(element("h3", "", arm));
    if (!tickets.length) {
      group.append(element("p", "", "保留"));
      return group;
    }
    const result = element("span", "keirin-public-badge");
    result.dataset.forecastArm = arm;
    result.hidden = true;
    group.append(result);
    if (replay && rating?.state !== "GRADED") {
      const { band } = replay;
      group.append(element("p", "keirin-public-clocks", "過去再現の推定的中率 " + percent(replay.probability) +
        " · " + tickets.length + "点。同じ推定帯の過去再現 " + band.hits + " / " + band.n + "件的中"));
    }
    group.append(element("p", "keirin-public-clocks", confidenceText(tickets.length, rating)));
    group.append(rankedTickets(arm, tickets));
    return group;
  }

  function dtResult(forecast, results) {
    const result = results?.get(forecast.race_id);
    const label = element("p", "keirin-public-clocks");
    if (!results) label.textContent = "公開結果を確認できません";
    else if (!result || result.reason === "result_unpublished") label.textContent = "結果待ち";
    else if (result.reason === "source_unavailable") label.textContent = "結果の取得待ち";
    else if (result.reason === "special_result") label.textContent = "中止・返還・同着の確認待ち";
    else if (result.reason === "source_disagreement") label.textContent = "出典間の相違を確認中";
    else {
      const { winning_3t: winner, observed_at: observed, sources } = result.comparison;
      const cutoff = instant(forecast.cutoff_at);
      if (!winner.every(car => forecast.starter_cars.includes(car)) ||
          sources.some(source => instant(source.checked_at) < cutoff) || instant(observed) < cutoff) {
        label.textContent = "着順の照合を保留中";
      } else {
        const matched = forecast.tickets.some(ticket => ticket.every((car, i) => car === winner[i]));
        label.append("公開結果（2媒体一致） " + winner.join("–") + " · ",
          element("strong", "", matched ? "一致" : "不一致"));
      }
    }
    return label;
  }

  function dtCard(row, day, results) {
    const group = element("section", "keirin-public-model keirin-public-dt-r1");
    const header = element("div", "keirin-public-race-head");
    header.append(element("h3", "", "DT-R1"), element("span", "keirin-public-badge", row.timing));
    const dates = element("p", "keirin-public-clocks");
    dates.append("締切 ", clock(row.cutoff_at, day, false), "　選定 ", clock(row.selected_at, day),
      "　掲載 ", clock(row.published_at, day));
    group.append(header, dates, element("p", "keirin-public-clocks", row.tickets.length + "点"),
      rankedTickets("DT-R1", row.tickets), dtResult(row, results));
    return group;
  }

  function raceCard(row, day, ratings, replayRatings, dtRow, results) {
    const venueCode = row.race_id.slice(8, 10);
    const name = (venues[venueCode] || "開催コード " + venueCode) + " " + Number(row.race_id.slice(-2)) + "R";
    const card = element("article", "keirin-public-race");
    const head = element("div", "keirin-public-race-head");
    const labels = { saved: "掲載済み", reference: "締切前の参考", research: "出走表の参考",
      "late-research": "締切後の参考", pending: "未掲載", "dt-only": "DT-R1掲載" };
    const hasAB = row.status !== "pending" && row.status !== "dt-only";
    head.append(element("h2", "", name),
      element("span", "keirin-public-badge " + (row.status === "saved" ? "is-saved" : ""), labels[row.status]));
    const clocks = element("p", "keirin-public-clocks");
    const cutoff = row.cutoff_at ?? dtRow?.cutoff_at;
    clocks.append("締切 ", cutoff ? clock(cutoff, day, false) : "未確認");
    if (hasAB) {
      const fromRacecard = row.status === "research" || row.status === "late-research";
      clocks.append(fromRacecard ? "　作成 " : "　保存 ", clock(row.saved_at, day));
    }
    card.append(head);
    if (row.status !== "dt-only") card.append(clocks);
    card.append(element("p", "keirin-public-clocks keirin-public-result"));
    if (hasAB) {
      const arms = element("div", "keirin-public-arms");
      const lane = row.status === "saved" ? "official" : row.status === "reference" ? "reference" : "racecard";
      for (const [arm, tickets] of [["A", row.a], ["B", row.b]]) {
        const rating = row.status === "late-research" ? null : ratings.get(confidenceKey(lane, arm, tickets.length));
        const replay = row.status === "research" && arm === "A" ? replayRatings.get(row.race_id) : undefined;
        arms.append(ticketList(arm, tickets, rating, replay));
      }
      card.append(arms);
    }
    if (dtRow) card.append(dtCard(dtRow, day, results));
    return card;
  }

  function renderResults(view, receipt) {
    const outcomes = receipt?.outcomes || new Map();
    const groups = { saved: "締切前保存", reference: "締切前の参考", research: "出走表の参考" };
    const counts = new Map();
    const yen = value => value.toLocaleString("ja-JP") + "円";
    let matched = 0, held = 0, dtScored = 0, dtHits = 0;
    for (const [index, row] of view.ordered.entries()) {
      const card = races.children[index], result = outcomes.get(row.race_id);
      const note = card.querySelector(".keirin-public-result");
      const winner = result?.winning_3t;
      if (winner) {
        matched++;
        note.replaceChildren("三連単 " + winner.join("–") + " · " + yen(result.payouts_100yen["3t"]),
          "　2車単 " + result.winning_2t.join("–") + " · " + yen(result.payouts_100yen["2t"]), "　");
        for (const source of result.sources) {
          const link = element("a", "", source.source_id === "kdreams" ? "Kドリームス" : "netkeirin");
          link.href = source.url;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          note.append(link, " ");
        }
      } else {
        const reasons = { source_disagreement: "結果確認中 · 2媒体に差異", special_result: "結果確認中 · 同着・返還等",
          source_unavailable: "結果の取得再開待ち", result_unpublished: "結果発表待ち" };
        if (["source_disagreement", "special_result"].includes(result?.reason)) held++;
        note.textContent = Object.hasOwn(reasons, result?.reason) ? reasons[result.reason] : "結果待ち";
      }
      const saved = instant(row.saved_at), forecastCutoff = instant(row.cutoff_at);
      const eligible = winner && Object.hasOwn(groups, row.status) && saved !== null && forecastCutoff !== null &&
        saved < forecastCutoff && saved < result.cutoff;
      const sameResearchRoster = !row.starter_cars ||
        (row.starter_cars.length === result?.cars?.size && row.starter_cars.every(car => result.cars.has(car)));
      for (const badge of card.querySelectorAll("[data-forecast-arm]")) {
        const arm = badge.dataset.forecastArm, tickets = row[arm.toLowerCase()];
        badge.hidden = !winner;
        if (!winner) continue;
        if (!sameResearchRoster || tickets.some(ticket => ticket.some(car => !result.cars.has(car)))) {
          badge.classList.remove("is-saved");
          badge.textContent = "出走車番の確認中";
          continue;
        }
        const hit = tickets.some(ticket => ticket.every((car, i) => car === winner[i]));
        badge.classList.toggle("is-saved", Boolean(hit));
        badge.textContent = eligible ? (hit ? "的中" : "不的中") : (hit ? "参考一致" : "参考不一致");
        if (!eligible) continue;
        const key = row.status + arm, total = counts.get(key) || { hits: 0, races: 0 };
        total.races++;
        if (hit) total.hits++;
        counts.set(key, total);
      }
      const dt = view.dtRows.get(row.race_id);
      if (winner && dt?.timing === "締切前掲載" && instant(dt.published_at) < result.cutoff &&
          dt.starter_cars.length === result.cars.size && dt.starter_cars.every(car => result.cars.has(car)) &&
          result.sources.every(source => instant(source.checked_at) >= instant(dt.cutoff_at))) {
        dtScored++;
        if (dt.tickets.some(ticket => ticket.every((car, i) => car === winner[i]))) dtHits++;
      }
    }
    const title = element("strong", "", "結果照合 " + matched + " / " + view.ordered.length + "件");
    const display = element("div", "");
    display.append(title);
    if (matched || held) display.append(" · 2媒体一致 " + matched + "件" + (held ? " · 確認中 " + held + "件" : ""));
    if (receipt) {
      const checked = element("p", "keirin-public-clocks");
      checked.append("結果の最終確認 ", clock(receipt.checkedAt), " JST");
      display.append(checked);
    }
    const stats = element("div", "");
    stats.append(element("strong", "", "モデル別的中率"));
    const rate = (lane, arm) => {
      const item = counts.get(lane + arm);
      return arm + " " + (item ? percent(item.hits / item.races) + "（" + item.hits + " / " + item.races + "）" : "照合待ち");
    };
    for (const [lane, label] of Object.entries(groups)) {
      if (lane === "saved" || counts.has(lane + "A") || counts.has(lane + "B")) {
        stats.append(element("p", "keirin-public-clocks", label + "　" + rate(lane, "A") + " · " + rate(lane, "B")));
      }
    }
    if (view.dtRows.size) stats.append(element("p", "keirin-public-clocks", "DT-R1 締切前　" +
      (dtScored ? percent(dtHits / dtScored) + "（" + dtHits + " / " + dtScored + "）" : "照合待ち")));
    scoreboard.replaceChildren(display, stats);
    scoreboard.hidden = false;
  }

  async function render(day, snapshot, referencePacket, researchPacket, confidencePacket, resultPackets, dtRows, request) {
    const references = publicCandidates(referencePacket, day, false);
    const research = publicCandidates(researchPacket, day, true);
    const ratings = confidenceRows(confidencePacket, day);
    const [roster, resultPacket] = resultPackets;
    const results = publishedResultRows(resultPacket, day);
    const ordered = (snapshot?.races ?? []).map(row => {
      if (row.status === "saved") return row;
      const supplements = [references.get(row.race_id), research.get(row.race_id)];
      return supplements.find(item => item && (row.cutoff_at === null ||
        Date.parse(row.cutoff_at) === Date.parse(item.cutoff_at))) ?? row;
    });
    let replay = new Map();
    if (ordered.some(row => row.status === "research" && row.starter_cars.length === 7 && row.a.length === 8 && !row.b.length)) {
      const packet = await fetchDay("measurements", "replay-confidence-" + day, request).catch(() => null);
      replay = await replayConfidenceRows(packet, day, research);
    }
    if (request.signal.aborted || (currentRequest !== request && resultRequest !== request)) return;
    const saved = ordered.filter(row => row.status === "saved").length;
    const pending = ordered.filter(row => row.status === "pending").length;
    const available = ordered.length - pending;
    status.replaceChildren("掲載済み ", element("strong", "", available + " / " + ordered.length), " レース");
    if (saved !== available) status.append(" ・ 締切前保存 " + saved + " ・ 参考 " + (available - saved));
    if (pending) status.append(" ・ 未掲載 " + pending + " レース");
    if (!ordered.length) status.textContent = "この日の公開データにレースはありません。";
    if (!snapshot) status.textContent = "A/B未掲載";
    if (dtRows.size) status.append(" ・ DT-R1 " + dtRows.size + " レース");
    const notices = [...ordered, ...dtRows.values()];
    const latest = notices.reduce((time, row) =>
      Date.parse(row.published_at) > Date.parse(time) ? row.published_at : time,
      snapshot?.published_at ?? notices[0].published_at);
    updated.replaceChildren("公開データ更新 ", clock(latest), " JST");
    updated.hidden = false;
    const registered = new Set(ordered.map(row => row.race_id));
    const visible = [...ordered, ...[...dtRows.values()].filter(row => !registered.has(row.race_id))
      .map(row => ({ race_id: row.race_id, cutoff_at: row.cutoff_at, status: "dt-only" }))];
    const sortClock = row => Date.parse(row.cutoff_at ?? dtRows.get(row.race_id)?.cutoff_at) || Infinity;
    visible.sort((a, b) => sortClock(a) - sortClock(b) || a.race_id.localeCompare(b.race_id));
    races.replaceChildren(...visible.map(row => raceCard(row, day, ratings, replay, dtRows.get(row.race_id), results)));
    const receipt = resultReceipt(day, roster, resultPacket, results);
    activeDay = { day, ordered: visible, dtRows, checkedAt: receipt?.checkedAt };
    renderResults(activeDay, receipt);
  }

  async function fetchDay(lane, day, request, source = base) {
    const response = await fetch(source + lane + "/" + day + ".json", {
      cache: "no-store", credentials: "omit", redirect: "error", referrerPolicy: "no-referrer", signal: request.signal
    });
    if (response.status === 404) return undefined;
    if (!response.ok) throw new Error("Public forecast unavailable");
    return response.json().catch(() => null);
  }

  function fetchResults(day, request) {
    return Promise.all(["rosters", "results"].map(lane => fetchDay(lane, day, request, resultsBase).catch(() => null)));
  }

  async function loadDay(day, request, resultPackets) {
    const [forecast, dtPacket] = await Promise.allSettled([
      fetchDay("forecasts", day, request), fetchDay("dt-r1", day, request)
    ]);
    if (request.signal.aborted) return;
    const snapshot = forecast.status === "fulfilled" && validSnapshot(forecast.value, day) ? forecast.value : null;
    const dtRows = dtShortlists(dtPacket.value, day);
    if (!snapshot && !dtRows.size) {
      return forecast.status === "rejected" ? "公開予想を取得できませんでした。再読み込みで確認できます。" :
        forecast.value === undefined ? "この日の公開予想は掲載されていません。" : "公開データの形式を確認できません。";
    }
    const supplements = snapshot?.races.some(row => row.status === "pending")
      ? ["references", "research"].map(lane => fetchDay(lane, day, request).catch(() => null))
      : [null, null];
    const packets = await Promise.all([...supplements,
      snapshot ? fetchDay("measurements", "confidence-" + day, request).catch(() => null) : null,
      resultPackets ?? fetchResults(day, request)
    ]);
    await render(day, snapshot, ...packets, dtRows, request);
  }

  async function refreshResults() {
    const view = activeDay;
    if (!view || currentRequest || resultRequest || document.hidden || view.day !== jstToday()) return;
    const request = new AbortController();
    resultRequest = request;
    const timeout = setTimeout(() => request.abort(), 15000);
    try {
      const data = await fetchResults(view.day, request);
      if (activeDay !== view || request.signal.aborted) return;
      const checked = instant(data[1]?.checked_at);
      if (checked === null || (view.checkedAt && checked <= instant(view.checkedAt))) return;
      const receipt = resultReceipt(view.day, ...data, publishedResultRows(data[1], view.day));
      if (!receipt) return;
      // A new settlement may arrive after the saved model replaced a reference.
      const failed = await loadDay(view.day, request, data).catch(() => true);
      if (failed && activeDay === view && !request.signal.aborted) renderResults(view, receipt);
    } finally {
      clearTimeout(timeout);
      if (resultRequest === request) resultRequest = null;
    }
  }

  async function load() {
    currentRequest?.abort();
    currentRequest = null;
    resultRequest?.abort();
    resultRequest = null;
    activeDay = null;
    scoreboard.hidden = true;
    updated.hidden = true;
    races.replaceChildren();
    dayInput.max = jstToday();
    const day = dayInput.value;
    if (!validDay(day) || day < dayInput.min || day > dayInput.max) {
      dayInput.setAttribute("aria-invalid", "true");
      races.setAttribute("aria-busy", "false");
      status.textContent = "選択できる範囲の日付を入力してください。";
      return;
    }
    dayInput.removeAttribute("aria-invalid");
    status.textContent = "公開予想を読み込んでいます。";
    races.setAttribute("aria-busy", "true");
    const request = new AbortController();
    currentRequest = request;
    const timeout = setTimeout(() => request.abort(), 15000);
    try {
      const message = await loadDay(day, request);
      if (message && currentRequest === request) status.textContent = message;
    } catch {
      if (currentRequest === request) status.textContent = "公開予想を取得できませんでした。再読み込みで確認できます。";
    } finally {
      clearTimeout(timeout);
      if (currentRequest === request) {
        races.setAttribute("aria-busy", "false");
        currentRequest = null;
      }
    }
  }

  dayInput.value = jstToday();
  dayInput.addEventListener("change", load);
  byId("keirin-public-refresh").addEventListener("click", load);
  window.setInterval(refreshResults, 60_000);
  load();
})();

if (!globalThis.document?.body?.classList.contains("keirin-public-page")) {
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

"use strict";
/* PR #62 page shell, saved originals and server-managed automatic generation. */
(() => {
  const $ = id => document.getElementById(id);
  const U = globalThis.RaceUI, M = globalThis.RaceProductData, A = globalThis.RaceAuditModel, C = globalThis.RaceExistingModelCatalog, P = globalThis.RaceSavedPerformance, O = globalThis.RaceOwnerFormal;
  const sports = {boat: "ボートレース", keirin: "競輪", autorace: "オートレース", horse: "競馬"};
  const icons = {boat: "◒", keirin: "♧", autorace: "♧", horse: "♞"};
  const pageNames = {
    home: ["YOUR RACE DASHBOARD", "今日のレースを、確かなデータで。", "保存済みの予想・結果と、あなたの買い目候補をひとつに。"],
    races: ["RACES & RESULTS", "レース", "締切前の予想と、会場別のレース結果を確認。"],
    detail: ["RACE DETAIL", "レース詳細", "出走情報・保存済み予想・根拠を、取得時点ごとに。"],
    picks: ["TICKET ALLOCATION", "買い目配分", "予算に合わせて候補を編集。確定した候補も、実購入とは別の記録です。"],
    results: ["AI FORECAST RESULTS", "AI予想結果", "保存予想の的中状況と、日予算を変えた場合の収支を確認。"],
    research: ["RESEARCH & VERIFICATION", "研究・検証", "モデルの検証情報と保存データの詳細を確認。"],
    settings: ["PREFERENCES", "設定", "予算・表示と、読み込む情報源を管理。"]
  };
  const storageKey = "race-ai-display-v1";
  let preferences = {};
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || "{}");
    if (saved && typeof saved === "object" && !Array.isArray(saved)) preferences = saved;
  } catch { /* Storage is optional. */ }
  const validBudget = n => Number.isSafeInteger(n) && n >= 100 && n <= 10000000 && n % 100 === 0;
  const state = {
    page: "home", sport: Object.hasOwn(sports, preferences.sport) ? preferences.sport : "boat",
    day: A.jstToday(), allDates: false, period: "day", statusFilter: "all", followsToday: true, query: "", venue: "", sort: "time",
    raceView: "upcoming", forecastOnly: false, candidatesOnly: false, selectedId: "", detailTab: "outlook", predictionKeys: {}, modelBySport: {}, modelOriginals: {},
    budget: validBudget(preferences.budget) ? preferences.budget : 10000,
    raceBudget: validBudget(preferences.raceBudget) ? preferences.raceBudget : 2000,
    simulationBudget: validBudget(preferences.simulationBudget) ? preferences.simulationBudget : 10000, resultGroupKey: "",
    simulationRaceBudget: [800,1000].includes(preferences.simulationRaceBudget) ? preferences.simulationRaceBudget : 800,
    maxPicks: [8, 16, 24, 32].includes(preferences.maxPicks) ? preferences.maxPicks : 8,
    candidates: [], purchases: [], confirmed: new Set(), visible: 60,
    favoriteVenues: [...new Set((Array.isArray(preferences.favoriteVenues) ? preferences.favoriteVenues : []).filter(value =>
      typeof value === "string" && value.length <= 110 && Object.keys(sports).some(sport => value.startsWith(sport + ":"))))].slice(0, 64)
  };
  let dataset = null, importVersion = 0, savedHistory = null, refreshSavedResults = null, raceBoundaryTimer = null;
  let ownerEncryptedTrusted = false, ownerAuditCache = null;
  const resultCheck = {busy:false,failed:false};
  const savedViewConfigured = Boolean(document.getElementById("race-ai-private-saved-data") || document.querySelector('meta[name="race-ai-private-saved-view"],meta[name="race-ai-encrypted-saved-view"]'));
  const savedMessages = {
    LOADING: ["レース情報を読み込んでいます", "保存された予想・結果を確認しています。"],
    LINK_REQUIRED: ["閲覧用リンクから開いてください", "このURLではレース情報を読み込めません。いつもの閲覧用リンクから開いてください。データファイルの入力は不要です。"],
    UNAVAILABLE: ["レース情報を確認できません", "レース情報を読み込めませんでした。時間をおいて再読み込みするか、閲覧用リンクを確認してください。"],
    CLEARED: ["レース情報の表示を消去しました", "再読み込みすると、閲覧用リンクの保存情報を表示します。"]
  };
  const generation = {api: null, ready: false, busy: false, nonce: null, capabilities: {}, day: null, message: "",
    savedState: savedViewConfigured ? "LOADING" : null,
    auto: null, delivery: {}, autoMessage: "", connectionUncertain: false, ownsDisplay: false, suppressed: false,
    revisions: {}, seen: {}, timer: null, statusBusy: false, latestBusy: false, latestQueued: false,
    latestQueuedFollow: false, pausedForDrafts: false, pausedForEditing: false};
  const text = v => v === null || v === undefined || v === "" ? "未取得" :
    typeof v === "string" ? v.slice(0, 4000) : typeof v === "number" && Number.isFinite(v) ? String(v) :
      typeof v === "boolean" ? (v ? "あり" : "なし") : "未取得";
  const yen = n => Number.isFinite(n) ? n.toLocaleString("ja-JP") + "円" : "未取得";
  const stamp = value => {
    if (!value || !Number.isFinite(Date.parse(value))) return "未取得";
    return new Intl.DateTimeFormat("ja-JP", {timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false}).format(new Date(value));
  };
  const time = value => value && Number.isFinite(Date.parse(value)) ? new Intl.DateTimeFormat("ja-JP", {timeZone: "Asia/Tokyo", hour: "2-digit", minute: "2-digit", hour12: false}).format(new Date(value)) : "未取得";
  const node = (tag, cls, content) => { const n = document.createElement(tag); if (cls) n.className = cls; if (content !== undefined) n.textContent = String(content); return n; };
  const button = (content, cls, handler) => { const n = node("button", cls, content); n.type = "button"; n.addEventListener("click", handler); return n; };
  const append = (parent, ...children) => { parent.append(...children); return parent; };
  const empty = (title, description, importAction = false) => {
    const box = append(node("div", "empty-state"), node("span", "empty-icon", "≋"), node("h3", "", title), node("p", "muted", description));
    if (importAction) box.append(button("保存JSONを読み込む", "primary", () => $("race-file").click()));
    return box;
  };
  const metric = (label, value, sub, icon = "▥") => append(node("article", "metric"), node("span", "metric-icon", icon), append(node("div"), node("span", "metric-label", label), node("strong", "", value), node("small", "muted", sub)));
  const hitRate = stats => stats.hits + stats.misses ? (stats.hits / (stats.hits + stats.misses) * 100).toFixed(1) + "%" : "算出対象なし";
  const scopeName = scope => ({official: "保存データ", research: "参考予想", synthetic: "合成テスト"})[scope] || "確認中";
  const races = () => dataset?.records || [];
  const scoped = () => U.filterRaces(races(), {sport: state.sport, day: state.day, allDates: state.allDates, period: state.period, sort: state.sort});
  const currentRace = () => races().find(r => r.race_id === state.selectedId);
  const raceName = r => r ? (U.venueName(r) || "開催場 未取得") + " " + (Number.isInteger(r.race_no) ? r.race_no + "R" : "レース番号 未取得") + (r.venue == null || r.race_no == null ? " · " + r.race_id : "") : "レース未選択";
  const retiredModelIds = new Set(C.retired_model_ids || []);
  const activeModel = value => value && !retiredModelIds.has(value.model_id);
  const storedPredictions = r => r ? (M.candidates ? M.candidates(r) : [r.prediction, ...(r.comparison_predictions || [])].filter(Boolean)) : [];
  const predictions = r => storedPredictions(r).filter(activeModel);
  const displayRows = rows => rows.map(C.forDisplay);
  const modelMemoryKey = (r, modelId) => JSON.stringify([r.race_id, modelId]);
  const selectedModelId = r => state.modelBySport[r?.sport] ?? (predictions(r)[state.predictionKeys[r?.race_id]] || predictions(r)[0])?.model_id ?? "";
  const prediction = r => {
    const list = predictions(r), modelId = selectedModelId(r), identity = r && state.modelOriginals[modelMemoryKey(r, modelId)];
    const remembered = identity ? list.findIndex(p => M.savedPredictionIdentity(p) === identity) : -1;
    return U.modelPrediction(list, modelId, remembered >= 0 ? remembered : state.predictionKeys[r?.race_id]);
  };
  function rememberModelSelections(sport) {
    for (const r of races().filter(row => row.sport === sport)) {
      const p = prediction(r); if (p?.model_id) state.modelOriginals[modelMemoryKey(r,p.model_id)] = M.savedPredictionIdentity(p);
    }
  }
  function chooseModel(sport, modelId, focusId) {
    rememberModelSelections(sport);
    if (modelId) state.modelBySport[sport] = modelId; else delete state.modelBySport[sport];
    renderAll(); $(focusId)?.focus();
  }
  const modelTechnicalName = p => {
    if(!p)return "未予想";
    const code=p.code_identity || M.codeIdentity?.(p), version=p.model_version ?? (code ? "保存コード "+code.slice(0,7) : "未取得");
    return text(p.model_id || p.model_version) + (p.model_id ? " / " + text(version) : "") + (p.variant ? " · " + ({HISTORY_BASELINE:"履歴なし",HISTORY_ADDED:"履歴あり"}[p.variant] || text(p.variant)) : "");
  };
  const modelLabels = {
    "boat-display-rating-PL-reference-v1-UNVALIDATED":"展示データ", "boat-course-motor-shadow-v0.1-UNTRAINED":"コース・モーター",
    "boat-local-start-course-shadow-v0.1-UNTRAINED":"当地・スタート", "boat-course-entry-method-scenarios-v0.1-UNTRAINED":"進入・展開",
    "boat-comprehensive-v1":"総合評価", "boat-scenario-mixture-v1":"展開シナリオ", "boat-observed-pairwise-factor-v1":"選手・機力比較",
    "boat-observed-pairwise-start-v1":"スタート比較", "multisport-factor-interaction-v1":"要素比較", "multisport-scenario-ensemble-v1":"シナリオ比較",
    "multisport-conditional-duel-v1":"条件別比較", "multisport-race-trajectory-v1":"レース展開", "multisport-chronological-ranker-v1":"時系列評価",
    "autorace-personal-observed-baseline-v1":"走行実績", "boat-pdca-lane-shadow-v1":"コース実績"
  };
  const modelName = p => !p ? "未予想" : (modelLabels[p.model_id] || "保存モデル") + (p.variant ? " · " + ({HISTORY_BASELINE:"履歴なし",HISTORY_ADDED:"履歴あり"}[p.variant] || "別条件") : "");
  const stageName = p => ({P0: "P0 朝版", P1: "P1 展示・試走後", A_PRE_TRIAL:"A 試走前", B_POST_TRIAL:"B 試走後"})[p?.stage] || "時点未取得";
  const ticketsFor = id => state.candidates.filter(t => t.raceId === id);
  const dailyPurchases = () => state.purchases.filter(p => p.day === A.jstToday());
  const knownParticipants = r => Array.isArray(r?.participants) ? r.participants : [];
  const participantNumber = p => p.number ?? p.lane ?? p.horse_no ?? p.bib_number;
  const participantRegistration = p => p.registration_no || p.registration_number || p.registration_id || p.racer_registration_id || p.racer_id;
  const participantLabel = (p, r) => {
    const registration = participantRegistration(p), number = participantNumber(p);
    const bound = registration ? knownParticipants(r).find(person => participantRegistration(person) === registration &&
      (number == null || participantNumber(person) === number)) : null;
    const name = p.name || bound?.name;
    return (name ? text(name) : "名前 未取得") + (registration ? "（登録 " + text(registration) + "）" : "");
  };
  const maxNumber = r => {
    const numbers = knownParticipants(r).map(participantNumber).filter(Number.isInteger);
    const saved = predictions(r).flatMap(p => p.ordered_top8.flat());
    return Math.min(99, Math.max(r?.sport === "boat" ? 6 : r?.sport === "horse" ? 18 : r?.sport === "keirin" ? 9 : 8, ...numbers, ...saved));
  };
  const badge = n => node("span", "lane lane-" + (n <= 6 ? n : "other"), String(n));
  const combo = values => { const n = node("span", "combo"); values.forEach((v, i) => { if (i) n.append(node("span", "combo-dash", "−")); n.append(badge(v)); }); return n; };
  function persistPreferences() {
    try { localStorage.setItem(storageKey, JSON.stringify({budget: state.budget, raceBudget: state.raceBudget, simulationBudget: state.simulationBudget, simulationRaceBudget: state.simulationRaceBudget, maxPicks: state.maxPicks, sport: state.sport, favoriteVenues: state.favoriteVenues})); } catch { /* App remains usable with storage disabled. */ }
  }
  function table(headers, rows) {
    const t = node("table"), head = node("tr"), body = node("tbody");
    headers.forEach(h => head.append(node("th", "", h)));
    rows.forEach(fields => { const tr = node("tr"); fields.forEach(value => { const td = node("td"); value instanceof Node ? td.append(value) : td.textContent = text(value); tr.append(td); }); body.append(tr); });
    t.append(append(node("thead"), head), body); return append(node("div", "table-scroll"), t);
  }
  function facts(fields) {
    const list = node("dl", "provenance");
    fields.forEach(([label, value]) => list.append(node("dt", "", label), node("dd", "", text(value))));
    return list;
  }
  function sourceText(value) {
    if (Array.isArray(value)) return value.map(v => typeof v === "string" ? v : JSON.stringify(v)).join(" / ");
    return value && typeof value === "object" ? JSON.stringify(value) : text(value);
  }
  function weatherPanel(weather, label, includeDetails = true) {
    const panel = node("section", "weather-panel"); panel.setAttribute("aria-label", label);
    panel.append(node("h3", "", "気象・水面"));
    const grid = node("div", "weather-metrics");
    for (const [name, keys, unit] of [["天候", ["weather_label", "weather", "condition"], ""], ["気温", ["air_temperature_c", "temperature"], "℃"],
      ["風速", ["wind_speed_mps", "wind_speed"], "m/s"], ["波高", ["wave_height_cm", "wave_height"], "cm"], ["水温", ["water_temperature_c", "water_temperature"], "℃"]]) {
      const value = keys.map(key => weather[key]).find(value => (typeof value === "number" || typeof value === "string") && value !== "");
      if (value === undefined) continue;
      grid.append(append(node("div", "weather-metric"), node("span", "weather-label", name), node("strong", "weather-value", text(value) + (unit ? " " + unit : ""))));
    }
    panel.append(grid.childElementCount ? grid : node("p", "muted small", "気象の保存項目は詳細で確認できます。"));
    const details = node("details", "weather-details");
    details.append(node("summary", "", "気象の保存項目をすべて確認"), facts(Object.entries(weather).map(([key, value]) => [key, sourceText(value)])));
    if (includeDetails) panel.append(details);
    return panel;
  }
  function previewCards(race, people, live = false) {
    const grid = node("div", "preview-people");
    const value = v => typeof v === "number" && Number.isFinite(v) ? v.toFixed(2) : v == null && live ? "未公表" : text(v);
    for (const person of people) {
      const card = node("article", "preview-boat"), header = node("div", "preview-person");
      const profilePerson = live ? knownParticipants(race).find(p => participantNumber(p) === participantNumber(person) && participantRegistration(p) === participantRegistration(person)) || person : person;
      const trigger = button(person.name || "出走者情報", "text-button", () => openParticipant(profilePerson, race, trigger));
      trigger.dataset.openParticipant = participantRegistration(person) || "unverified";
      const number = participantNumber(person); if (Number.isInteger(number)) header.append(badge(number));
      header.append(trigger); card.append(header);
      const metrics = node("dl", "preview-metrics");
      const fields = [["展示タイム", value(person.display_time)], ["展示ST", value(person.preview_st)], [live ? "展示コース" : "進入", value(person.preview_course)]];
      if (live) fields.push(["体重 kg", value(person.bodyweight_kg)], ["チルト 度", value(person.tilt)]);
      for (const [label, item] of fields) {
        metrics.append(append(node("div"), node("dt", "", label), node("dd", "", item)));
      }
      card.append(metrics);
      if (person.comment || person.last_comment) card.append(node("p", "preview-comment", person.comment || person.last_comment));
      grid.append(card);
    }
    return grid;
  }
  function validBoatObservationContext(context, raceId) {
    const record = value => value !== null && typeof value === "object" && !Array.isArray(value);
    const optionalText = value => value == null || typeof value === "string" && value.length <= 4000;
    const timestamp = value => typeof value === "string" && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(value) && Number.isFinite(Date.parse(value));
    const optionalStamp = value => value == null || timestamp(value);
    const sha = value => typeof value === "string" && /^[a-f0-9]{64}$/i.test(value);
    const optionalNumber = (value, minimum = -Infinity) => value == null || typeof value === "number" && Number.isFinite(value) && value >= minimum;
    const optionalInteger = (value, minimum, maximum) => value == null || Number.isSafeInteger(value) && value >= minimum && value <= maximum;
    const optionalBoolean = value => value == null || typeof value === "boolean";
    const optionalEnum = (value, values) => value == null || values.includes(value);
    const source = (value, hashField) => {
      if (!record(value) || !sha(value[hashField]) || !timestamp(value.captured_at) || !optionalStamp(value.published_at) || !optionalText(value.published_time_raw)) return false;
      try { const url = new URL(value.source_url); return url.protocol === "https:" && !url.username && !url.password; } catch { return false; }
    };
    if (!record(context) || context.race_id != null && context.race_id !== raceId || context.forecast_inputs_used != null && context.forecast_inputs_used !== false || !optionalStamp(context.cutoff_at)) return false;
    for (const kind of ["beforeinfo", "pitreport"]) {
      const page = context[kind];
      if (page == null) continue;
      if (!record(page) || page.schema !== "RACE_AI_BOAT_OBSERVATION_CONTEXT_V1" || page.kind !== kind || page.race_id !== raceId || !source(page.source, "sha256") || !Array.isArray(page.participants) || page.participants.length > 6 || !optionalStamp(page.source_cutoff_at) || !optionalBoolean(page.captured_before_cutoff) || page.forecast_ready != null && page.forecast_ready !== false || !optionalEnum(page.status, ["PARSED", "NOT_OFFERED", "UNSUPPORTED_STRUCTURE"]) || !optionalEnum(page.roster_binding_status, ["VERIFIED", "NOT_PUBLISHED"]) || !optionalText(page.reporter)) return false;
      if (page.cutoff_eligibility != null && (!record(page.cutoff_eligibility) || !optionalBoolean(page.cutoff_eligibility.captured_before_cutoff))) return false;
      const capturedBefore = page.cutoff_eligibility?.captured_before_cutoff ?? page.captured_before_cutoff;
      if (capturedBefore === true && [page.source_cutoff_at, context.cutoff_at].some(cutoff => cutoff != null && Date.parse(page.source.captured_at) >= Date.parse(cutoff))) return false;
      const lanes = new Set();
      for (const person of page.participants) {
        if (!record(person) || !Number.isInteger(person.lane) || person.lane < 1 || person.lane > 6 || lanes.has(person.lane) || person.registration_number != null && (typeof person.registration_number !== "string" || !/^\d{4}$/.test(person.registration_number)) || !optionalText(person.name)) return false;
        lanes.add(person.lane);
        if (kind === "beforeinfo") {
          if (!["bodyweight_kg", "adjustmentweight_kg", "display_time", "exhibition_st"].every(field => optionalNumber(person[field], 0)) || !optionalNumber(person.tilt) || !optionalText(person.propeller_change_marker) || !optionalText(person.exhibition_st_raw) || !optionalEnum(person.exhibition_st_status, ["OK", "F", "L", "NOT_PUBLISHED"]) || !optionalInteger(person.exhibition_source_position_number, 1, 6) || !optionalInteger(person.exhibition_course, 1, 6) || person.parts_replacement != null && (!Array.isArray(person.parts_replacement) || person.parts_replacement.length > 40 || person.parts_replacement.some(value => typeof value !== "string" || value.length > 4000))) return false;
        } else {
          if (!optionalText(person.comment)) return false;
          const attribution = person.comment_attribution;
          if (attribution != null && (!record(attribution) || !optionalText(attribution.racer_name) || !optionalText(attribution.reporter))) return false;
        }
      }
      const weather = page.weather;
      if (weather != null && (!record(weather) || !["air_temperature_c", "water_temperature_c"].every(field => optionalNumber(weather[field])) || !["wind_speed_mps", "wave_height_cm"].every(field => optionalNumber(weather[field], 0)) || !["weather_label", "source_reported_local_time"].every(field => optionalText(weather[field])) || !optionalInteger(weather.wind_direction_source_code, 1, 17) || !optionalInteger(weather.reported_race_no, 1, 12) || !optionalStamp(weather.reported_at))) return false;
    }
    if (context.entry_history == null) return true;
    const history = context.entry_history;
    if (!record(history) || !Array.isArray(history.profiles) || history.profiles.length > 6) return false;
    const bucket = (value, sample) => {
      if (!record(value) || !["starts", "wins", "top2", "top3", "denominator"].every(field => Number.isSafeInteger(value[field]) && value[field] >= 0 && value[field] <= sample) || value.denominator !== value.starts || value.wins > value.top2 || value.top2 > value.top3 || value.top3 > value.starts) return false;
      return [["win_rate", "wins"], ["top2_rate", "top2"], ["top3_rate", "top3"]].every(([rate, count]) => !Object.hasOwn(value, rate) || (value.starts === 0 ? value[rate] === null : typeof value[rate] === "number" && Number.isFinite(value[rate]) && value[rate] >= 0 && value[rate] <= 1 && Math.abs(value[rate] - value[count] / value.starts) < 1e-12));
    };
    const identities = new Set();
    for (const profile of history.profiles) {
      if (!record(profile) || typeof profile.racer_id !== "string" || !/^\d{4}$/.test(profile.racer_id) || identities.has(profile.racer_id) || !timestamp(profile.as_of) || !Number.isSafeInteger(profile.sample_races) || profile.sample_races < 0 || profile.sample_races > 25000 || !record(profile.conditional_buckets) || !["inward", "outer_to_inner3", "displaced", "crossed_by_outer_frame", "any_inward_mover_present"].every(key => bucket(profile.conditional_buckets[key], profile.sample_races)) || !Array.isArray(profile.source_proofs) || profile.source_proofs.length > 10000 || profile.sample_races > 0 && !profile.source_proofs.length) return false;
      identities.add(profile.racer_id);
      if (profile.actual_course_when_inward_mover_present != null && (!record(profile.actual_course_when_inward_mover_present) || !Array.from({length:6}, (_, index) => String(index + 1)).every(key => bucket(profile.actual_course_when_inward_mover_present[key], profile.sample_races)))) return false;
      for (const proof of profile.source_proofs) {
        if (!record(proof) || typeof proof.date_jst !== "string" || !/^\d{4}-\d\d-\d\d$/.test(proof.date_jst) || !Number.isFinite(Date.parse(proof.date_jst + "T00:00:00Z")) || !["B", "K"].every(kind => source(proof[kind], "source_sha256") && sha(proof[kind].extracted_text_sha256) && Date.parse(proof[kind].captured_at) < Date.parse(profile.as_of))) return false;
      }
    }
    return true;
  }
  function officialBoatRoster(context, raceId, page, checkedAt) {
    const program = context.program;
    const record = value => value !== null && typeof value === "object" && !Array.isArray(value);
    const stamp = value => typeof value === "string" && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)$/.test(value) && Number.isFinite(Date.parse(value));
    if (!record(program) || program.schema !== "RACE_AI_BOAT_OFFICIAL_PROGRAM_V1" || program.body_identity_verified !== true ||
        program.status !== "OFFICIAL_BODY_IDENTITY_VERIFIED" || program.race_status !== "LISTED" || program.race_id !== raceId ||
        program.date_jst !== raceId.slice(0,4)+"-"+raceId.slice(4,6)+"-"+raceId.slice(6,8) || program.venue !== raceId.slice(9,11) ||
        !stamp(program.captured_at) || !stamp(program.closed_at) || !stamp(checkedAt) || program.closed_at !== context.cutoff_at || program.closed_at !== page.source_cutoff_at ||
        !/^[a-f0-9]{64}$/.test(program.source_sha256) || !record(program.source) || program.source.sha256 !== program.source_sha256 ||
        program.source.source_url !== program.source_url || !stamp(program.source.captured_at) ||
        Date.parse(program.source.captured_at) !== Date.parse(program.captured_at) ||
        Date.parse(program.captured_at) > Date.parse(page.source.captured_at) || Date.parse(page.source.captured_at) > Date.parse(checkedAt) ||
        !Array.isArray(program.boats) || program.boats.length < 3 || program.boats.length > 6 ||
        !Array.isArray(program.active_lanes) || !Number.isInteger(program.active_entrant_count)) return null;
    try {
      const url = new URL(program.source_url), q = url.searchParams;
      if (url.origin !== "https://www.boatrace.jp" || url.username || url.password || url.hash || url.pathname !== "/owpc/pc/race/racelist" ||
          [...q].length !== 3 || new Set(q.keys()).size !== 3 || q.get("hd") !== raceId.slice(0,8) || q.get("jcd") !== raceId.slice(9,11) || q.get("rno") !== String(Number(raceId.slice(-2)))) return null;
    } catch { return null; }
    const active = new Map(), full = new Map(), withdrawn = new Set(), lanes = new Set(), registrations = new Set();
    for (const person of program.boats) {
      if (!record(person) || !Number.isInteger(person.lane) || person.lane < 1 || person.lane > 6 || lanes.has(person.lane) ||
          !["listed", "withdrawn"].includes(person.entry_status) || person.race_id !== raceId || person.closed_at !== program.closed_at ||
          person.source_url !== program.source_url || person.verified_source !== true || !stamp(person.captured_at) ||
          Date.parse(person.captured_at) !== Date.parse(program.captured_at)) return null;
      lanes.add(person.lane);
      const registration = person.racer_registration_id;
      full.set(person.lane, registration);
      if (person.entry_status === "withdrawn") withdrawn.add(person.lane);
      if (registration === null && person.entry_status === "withdrawn") continue;
      if (typeof registration !== "string" || !/^[0-9]{4}$/.test(registration) || registrations.has(registration)) return null;
      registrations.add(registration);
      if (person.entry_status === "listed") active.set(person.lane, registration);
    }
    const expected = [...active.keys()].sort((a,b) => a-b);
    if (active.size < 3 || active.size > 6 || program.active_entrant_count !== active.size || program.active_lanes.length !== active.size ||
        !expected.every((lane, index) => program.active_lanes[index] === lane)) return null;
    return {active, full, withdrawn};
  }
  function liveBoatObservation(r) {
    const live = r.sport === "boat" ? r.live_boat_observation : null;
    if (!live || live.schema !== "RACE_AI_LIVE_BOAT_OBSERVATION_V1" || live.forecast_inputs_used !== false ||
        !["READY", "AWAITING_EXHIBITION", "SOURCE_WAIT", "SOURCE_ERROR"].includes(live.state) || !Number.isFinite(Date.parse(live.checked_at))) return null;
    if (live.context === null) return live.state === "READY" ? null : live;
    const context = live.context, page = context?.beforeinfo, people = knownParticipants(r);
    if (!validBoatObservationContext(context, r.race_id) || context.schema !== "RACE_AI_BOAT_SUPPLEMENTAL_CONTEXT_V1" ||
        context.race_id !== r.race_id || context.forecast_inputs_used !== false || page?.body_identity_verified !== true || page.status !== "PARSED" || page.roster_binding_status !== "VERIFIED" ||
        people.length < 3 || people.length > 6 || page.participants.length < 3 || page.participants.length > 6 ||
        !Array.isArray(context.roster) || context.roster.length !== page.participants.length) return null;
    const bound = Object.hasOwn(context, "program") ? officialBoatRoster(context, r.race_id, page, live.checked_at) : null;
    if (Object.hasOwn(context, "program") ? !bound || bound.active.size !== page.participants.length : people.length !== 6 || page.participants.length !== 6) return null;
    if (bound && (r.event_date_jst !== context.program.date_jst ||
        r.race_no != null && (!Number.isInteger(r.race_no) || r.race_no !== Number(r.race_id.slice(-2))))) return null;
    if (bound && Object.hasOwn(r, "withdrawn_lanes") && (!Array.isArray(r.withdrawn_lanes) ||
        new Set(r.withdrawn_lanes).size !== r.withdrawn_lanes.length ||
        r.withdrawn_lanes.some(lane => !Number.isInteger(lane) || !bound.withdrawn.has(lane)))) return null;
    if (bound && Object.hasOwn(r, "withdrawn_participants")) {
      if (!Array.isArray(r.withdrawn_participants) || r.withdrawn_participants.length > 6) return null;
      const absent = new Set();
      for (const person of r.withdrawn_participants) {
        if (!person || typeof person !== "object" || !Number.isInteger(person.number) || absent.has(person.number) ||
            !bound.withdrawn.has(person.number) || person.lane != null && person.lane !== person.number) return null;
        const keys = ["registration_no", "registration_number", "registration_id", "racer_registration_id", "racer_id"];
        const registration = keys.map(key => person[key]).find(value => value != null) ?? null;
        if (registration !== bound.full.get(person.number) || keys.some(key => person[key] != null && person[key] !== registration)) return null;
        absent.add(person.number);
      }
    }
    const lanes = new Set(), registrations = new Set();
    for (const person of people) {
      if (!person || typeof person !== "object") return null;
      const number = participantNumber(person), registration = participantRegistration(person);
      if (!Number.isInteger(number) || number < 1 || number > 6 || lanes.has(number) ||
          typeof registration !== "string" || !/^[0-9]{4}$/.test(registration) || registrations.has(registration) ||
          ["number", "lane"].some(key => person[key] != null && person[key] !== number) ||
          ["registration_no", "registration_number", "registration_id", "racer_registration_id", "racer_id"].some(key => person[key] != null && person[key] !== registration) ||
          bound && (bound.full.get(number) !== registration ||
            bound.active.has(number) && (person.active === false || person.withdrawn === true)) ||
          (!bound || bound.active.has(number)) && (
            context.roster.filter(p => p && p.lane === number && p.registration_number === registration).length !== 1 ||
            page.participants.filter(p => p.lane === number && p.registration_number === registration).length !== 1)) return null;
      lanes.add(number); registrations.add(registration);
    }
    if (bound && [...bound.active.keys()].some(lane => !lanes.has(lane))) return null;
    try {
      const url = new URL(page.source.source_url), q = url.searchParams, rid = r.race_id;
      if (url.origin !== "https://www.boatrace.jp" || url.username || url.password || url.hash || url.pathname !== "/owpc/pc/race/beforeinfo" ||
          [...q].length !== 3 || new Set(q.keys()).size !== 3 || q.get("hd") !== rid.slice(0,8) || q.get("jcd") !== rid.slice(9,11) || q.get("rno") !== String(Number(rid.slice(-2)))) return null;
    } catch { return null; }
    return live;
  }
  function selectedBoatContext(r) {
    const live = liveBoatObservation(r)?.context, legacy = r.boat_observation_context;
    if (!live) return legacy;
    if (!legacy || !validBoatObservationContext(legacy, r.race_id)) return live;
    const people = knownParticipants(r), registrations = new Set(people.map(participantRegistration));
    const matches = person => people.some(p => participantNumber(p) === person.lane && participantRegistration(p) === person.registration_number);
    const pit = legacy.pitreport?.participants.every(matches) ? legacy.pitreport : null;
    const history = legacy.entry_history?.profiles.every(profile => registrations.has(profile.racer_id)) ? legacy.entry_history : null;
    // This is a display composition, never a new capture. Each independently
    // validated component retains its own clock, source and admission flags.
    const composed = {...live,pitreport:live.pitreport || pit,entry_history:live.entry_history || history};
    if (legacy.cutoff_at !== live.cutoff_at) delete composed.cutoff_at;
    return composed;
  }
  function liveBeforeinfoPanel(r) {
    const live = liveBoatObservation(r); if (!live) return null;
    const panel = node("section"); panel.id = "live-beforeinfo"; panel.dataset.previewState = live.state;
    panel.append(node("h2", "", "直前情報"));
    const labels = {READY:"公式情報を取得済み", AWAITING_EXHIBITION:"展示発表待ち · 公表済みの情報を表示", SOURCE_WAIT:"次の取得確認を待っています", SOURCE_ERROR:"直前情報の取得を再確認しています"};
    if (live.state === "AWAITING_EXHIBITION" && live.context?.beforeinfo?.participants.some(person => person.display_time != null || person.exhibition_st_raw != null)) labels.AWAITING_EXHIBITION = "一部の展示情報は未公表 · 取得済みの項目を表示";
    panel.append(node("p", "muted small", labels[live.state]));
    const before = live.context?.beforeinfo;
    if (before) {
      panel.append(node("p", "muted small", "公式情報の取得 " + stamp(before.source.captured_at) + " JST"));
      if (["SOURCE_WAIT", "SOURCE_ERROR"].includes(live.state)) panel.append(node("p", "notice", "前回取得した情報です。取得時刻を確認してください。"));
      panel.append(previewCards(r, before.participants.map(person => ({...person,number:person.lane,registration_no:person.registration_number,
        preview_st:person.exhibition_st_raw ?? person.exhibition_st,preview_course:person.exhibition_course})), true));
      if (before.weather) panel.append(weatherPanel(before.weather, "公式の直前気象・水面", false));
      const source = node("a", "source-link", "公式の直前情報を開く ↗"); source.href = before.source.source_url; source.target = "_blank"; source.rel = "noopener noreferrer";
      panel.append(source);
    } else panel.append(node("p", "muted", "取得でき次第、自動で表示します。"));
    return panel;
  }
  function boatObservationContext(r) {
    const context = r.sport === "boat" ? selectedBoatContext(r) : null;
    if (context == null) return null;
    const box = node("section"); box.id = "boat-observation-context";
    box.append(node("h2", "member-heading", "補足観測"), node("p", "notice", "保存予想への反映は未検証です。補足の取得時刻・出典を個別に表示します。"));
    if (!validBoatObservationContext(context, r.race_id)) {
      box.append(node("p", "notice", "補足観測を照合できません。形式・件数・出典の記録を確認してください。"));
      return box;
    }
    const sourceFacts = page => {
      const source = page.source || {};
      const status = {PARSED:"取得した項目を表示", NOT_OFFERED:"公式ページで提供なし", UNSUPPORTED_STRUCTURE:"ページ構造を確認できず・照合不可"}[page.status] || "取得状態は未確認";
      const capturedBefore = page.cutoff_eligibility?.captured_before_cutoff ?? page.captured_before_cutoff;
      const cutoffRelation = capturedBefore === false ? "締切後に取得（保存予想への後付けなし）" : capturedBefore === true ? "締切前に取得（入力への反映は別確認）" : "未確認";
      const wrapper = node("div", "context-source"), details = node("details", "context-source-details");
      wrapper.append(node("p", "muted small", "観測取得 " + stamp(source.captured_at) + " JST · " + cutoffRelation));
      details.append(node("summary", "", "取得状態・出典の詳細"), facts([["取得状態", status], ["観測取得 JST", stamp(source.captured_at)], ["公式ページの締切 JST", stamp(page.source_cutoff_at)], ["締切と取得の関係", cutoffRelation], ["取得元URL", source.source_url], ["元ページSHA", source.sha256], ["公式公開日時 JST", stamp(source.published_at)], ["掲載時刻の原文", source.published_time_raw], ["鮮度の確認", "未確認（取得時刻と公式公開日時は別の記録）"]]));
      wrapper.append(details); return wrapper;
    };
    const before = context.beforeinfo;
    if (before) {
      const section = node("section"); section.id = "boat-context-beforeinfo";
      section.append(node("h3", "", "公式直前情報の観測"), sourceFacts(before));
      if (Array.isArray(before.participants) && before.participants.length) {
        section.append(table(["艇番", "選手 / 登録", "体重 kg", "調整重量 kg", "チルト 度", "プロペラ表示", "部品交換の記載"], before.participants.map(person => [person.lane, participantLabel(person, r), person.bodyweight_kg, person.adjustmentweight_kg, person.tilt, person.propeller_change_marker, Array.isArray(person.parts_replacement) && person.parts_replacement.length ? person.parts_replacement.join(" / ") : null])));
        section.append(node("h3", "member-heading", "展示タイム・展示ST"), table(["艇番", "選手 / 登録", "展示タイム 秒", "展示ST 原文", "ST状態", "展示の表示位置", "実進入コース"], before.participants.map(person => [person.lane, participantLabel(person, r), person.display_time, person.exhibition_st_raw ?? person.exhibition_st, {OK:"正常ST", F:"F（フライング表示）", L:"L（出遅れ表示）", NOT_PUBLISHED:"未公表"}[person.exhibition_st_status] || "未取得", person.exhibition_source_position_number, person.exhibition_course])), node("p", "muted small", "展示の表示位置は、本番の実進入コースの確定値ではありません。空欄は変更なし・STゼロを意味しません。"));
      } else section.append(node("p", "muted", "選手別の直前観測値は未取得です。"));
      const weather = before.weather;
      if (weather) section.append(weatherPanel(weather, "補足観測の気象・水面"));
      section.append(node("h3", "member-heading", "公式気象・水面の観測"), weather ? facts([["天候", weather.weather_label], ["気温 ℃", weather.air_temperature_c], ["水温 ℃", weather.water_temperature_c], ["風速 m/s", weather.wind_speed_mps], ["波高 cm", weather.wave_height_cm], ["風向の公式表示コード", weather.wind_direction_source_code], ["掲載対象レース", Number.isInteger(weather.reported_race_no) ? weather.reported_race_no + "R時点" : null], ["気象欄の時刻原文", weather.source_reported_local_time], ["気象の公開日時 JST", stamp(weather.reported_at)], ["気象の鮮度", "未確認（日付付きの公式公開日時は未取得）"]]) : node("p", "muted", "気象・水面の補足観測は未取得です。"));
      box.append(section);
    } else box.append(node("p", "muted", "公式直前情報の補足観測は未取得です。"));
    const pit = context.pitreport;
    if (pit) {
      const section = node("section"); section.id = "boat-context-pitreport";
      section.append(node("h3", "member-heading", "公式ピットレポートの選手コメント"), node("p", "muted small", "公式掲載の発言・取材記録です。選手の評価を走行性能の計測値へ置き換えません。"), sourceFacts(pit));
      if (Array.isArray(pit.participants) && pit.participants.length) section.append(table(["艇番", "選手 / 登録", "公式掲載コメント", "発言者 / 取材者"], pit.participants.map(person => [person.lane, participantLabel(person, r), person.comment, "選手 " + text(person.comment_attribution?.racer_name) + " / 取材 " + text(person.comment_attribution?.reporter ?? pit.reporter)])));
      else section.append(node("p", "muted", pit.status === "NOT_OFFERED" ? "この公式ページではピットレポートの提供がありません。" : "選手コメントは未取得です。"));
      box.append(section);
    } else box.append(node("p", "muted", "公式ピットレポートの補足観測は未取得です。"));
    const history = context.entry_history;
    const historySection = node("section"); historySection.id = "boat-context-entry-history";
    historySection.append(node("h3", "member-heading", "過去の進入条件別成績（観測）"), node("p", "muted small", "過去の実進入と着順の条件別集計です。前付けの意図・抵抗・原因や今回の進入は確定できません。少数例の率は大きく変動します。"));
    const profiles = Array.isArray(history?.profiles) ? history.profiles : [];
    const rate = (count, denominator) => denominator > 0 ? (count / denominator * 100).toFixed(1) + "%" : null;
    const bucketFields = bucket => [bucket.starts, bucket.wins, bucket.top2, bucket.top3, rate(bucket.top3, bucket.denominator)];
    for (const profile of profiles) {
      historySection.append(node("h3", "", participantLabel({registration_no:profile.racer_id}, r)), facts([["集計基準 JST", stamp(profile.as_of)], ["全観測レース数", profile.sample_races], ["率の意味", "条件に該当した過去の観測割合・将来の確率は未検証"]]), table(["過去の条件", "出走数", "1着数", "2着内数", "3着内数", "観測3着内率"], [["inward", "枠より内へ入った"], ["outer_to_inner3", "外枠から1〜3コースへ入った"], ["displaced", "枠より外へずれた"], ["crossed_by_outer_frame", "外枠艇が内側にいた"], ["any_inward_mover_present", "内へ入った艇がいたレース"]].map(([key, label]) => [label, ...bucketFields(profile.conditional_buckets?.[key])])));
      if (profile.actual_course_when_inward_mover_present) {
        const courses = node("details"); courses.append(node("summary", "", "内へ入った艇がいた時の実コース別成績"), table(["実コース", "出走数", "1着数", "2着内数", "3着内数", "観測3着内率"], Array.from({length:6}, (_, index) => [index + 1, ...bucketFields(profile.actual_course_when_inward_mover_present[String(index + 1)])]))); historySection.append(courses);
      }
      const sources = node("details"); sources.append(node("summary", "", "過去集計の出典・取得時刻・SHA"), node("p", "muted small", "読み込んだ出典記録です。公式出典との独立照合は未完了です。"));
      const proofs = Array.isArray(profile.source_proofs) ? profile.source_proofs : [];
      for (const proof of proofs) for (const kind of ["B", "K"]) {
        const source = proof[kind];
        if (source) sources.append(facts([["対象日 / 種別", text(proof.date_jst) + " / " + kind], ["観測取得 JST", stamp(source.captured_at)], ["取得元URL", source.source_url], ["配布原本SHA", source.source_sha256], ["展開テキストSHA", source.extracted_text_sha256]]));
      }
      if (!proofs.length) sources.append(node("p", "muted", "過去集計の出典原本は未取得です。"));
      historySection.append(sources);
    }
    if (!profiles.length) historySection.append(node("p", "muted", "条件別の過去レース観測は未取得です。ゼロ件の成績としては扱いません。"));
    box.append(historySection, node("h3", "member-heading", "展示映像・走行性能の確認"), facts(["ターン", "出足・立ち上がり", "行き足・助走", "直線の伸び"].map(label => [label, "未取得（検証済みの映像・手動観測なし）"])));
    return box;
  }
  function evidenceFields(r, p) {
    return [["データ区分", scopeName(r.scope)], ["開催日 JST", r.event_date_jst], ["モデル", p?.model_id], ["モデル版", p?.model_version], ["予想時点", stageName(p)],
      ["生成時刻 JST", stamp(p?.generated_at)], ["保存時刻 JST", stamp(p?.persisted_at)], ["予想原本の締切 JST", stamp(p?.cutoff_at || r.cutoff_at)],
      ...(r.saved_cutoff_variants?.length>1 ? [["保存原本の締切一覧 JST",r.saved_cutoff_variants.map(stamp).join(" / ")]]:[]),
      ["取得 / as-of JST", stamp(p?.as_of || r.as_of || r.observed_at)], ["情報源", sourceText(r.source_provenance)],
      ["予想の元SHA", p?.source_sha256], ["レース観測の元SHA", r.source_sha || r.source_sha256], ["入力SHA", p?.input_sha256], ["予想SHA", p?.prediction_sha256],
      ["出力本文SHA", p?.output_sha256], ["モデル / 学習物SHA", p?.model_sha256],
      ...(p?.variant==="LEARNED_SHADOW" || p?.training_sha256 ? [["学習元artifact ID",p?.training_artifact_id],["学習物SHA",p?.training_sha256],["学習元ZIP digest",p?.training_receipt_digest],["基準モデル原本SHA",p?.baseline_model_sha256]]:[]),
      ["原本JSON SHA", p?.original_json_sha256], ["原本artifact ID", p?.artifact_id], ["保存コードのコミット", p?.source_code_commit], ["保存モデル区分", p?.variant], ["保存済みサーバー時刻の申告 JST", stamp(p?.server_saved_at)],
      ["レシート時刻 JST", stamp(p?.external_receipt?.server_received_at || p?.receipt_timestamp || p?.evidence_receipt?.timestamp)], ["独立検証", "取込値のみ・原本と外部時刻の独立照合は別途必要"]];
  }
  function forecastStatus(r, p = prediction(r)) {
    if (!p) return "未予想";
    if (p.native_dispatch_prediction) return r.scope === "synthetic" ? "合成・取込予想" : "参考予想";
    if (r.scope === "synthetic") return "合成・保存予想";
    if (M.eligiblePrediction?.(r, p)) return "保存した予想";
    return "参考予想";
  }
  let participantDialog = null, participantOpener = null, activeDaily = null;
  function closeParticipant() {
    const opener = participantOpener; participantOpener = null;
    participantDialog?.close(); document.body.classList.remove("participant-dialog-open");
    if (opener?.isConnected) opener.focus();
    else { $("page-title").tabIndex = -1; $("page-title").focus({preventScroll: true}); }
  }
  function referenceEntryMap(race, api) {
    let entryMap = null;
    const people = knownParticipants(race), live = liveBoatObservation(race);
    let context = live?.context || race.boat_observation_context;
    if (live?.context) {
      const page = context.beforeinfo, captured = Date.parse(page.source.captured_at);
      const originals = [race.cutoff_at, ...(race.saved_cutoff_variants || []), ...(race.saved_schedule_cutoff_variants || [])].filter(Boolean);
      const limits = [...originals, context.cutoff_at, page.source_cutoff_at].map(Date.parse);
      if (!originals.length || !limits.every(Number.isFinite) || page.cutoff_eligibility?.captured_before_cutoff !== true ||
          page.cutoff_eligibility?.pre_cutoff_eligible !== true || captured >= Math.min(...limits)) context = race.boat_observation_context;
    }
    const reported = people.filter(p => p.preview_course !== null && p.preview_course !== undefined);
    if (reported.length) entryMap = Object.fromEntries(reported.map(p => [participantNumber(p), p.preview_course]));
    else if ((people.length === 6 || live?.context === context) && context && validBoatObservationContext(context, race.race_id) && context.beforeinfo?.status === "PARSED" && context.beforeinfo.roster_binding_status === "VERIFIED") {
      const observed = people.map(p => {
        const expected = api.get(race, p);
        return expected && context.beforeinfo.participants.find(value => value.lane === participantNumber(p) && value.registration_number === participantRegistration(p) && api.get(race, value) === expected);
      });
      if (context.beforeinfo.participants.some(p => p.exhibition_course !== null && p.exhibition_course !== undefined)) entryMap = Object.fromEntries(observed.filter(p => p && p.exhibition_course !== null && p.exhibition_course !== undefined).map(p => [p.lane, p.exhibition_course]));
    }
    return entryMap;
  }
  function athleteReference(race, person, profile) {
    const api = globalThis.RaceRacerProfiles, panel = node("section", "racer-reference"); panel.id = "racer-reference";
    panel.append(node("h3", "", "選手の公式資料"));
    const basic = profile.basic, basicPanel = node("section", "reference-basic");
    const birthday = new Date(basic.birth_date + "T00:00:00Z"), captured = new Date(api.capturedAt);
    let age = captured.getUTCFullYear() - birthday.getUTCFullYear();
    if (captured.getUTCMonth() < birthday.getUTCMonth() || captured.getUTCMonth() === birthday.getUTCMonth() && captured.getUTCDate() < birthday.getUTCDate()) age--;
    basicPanel.append(facts([["登録番号", profile.registration], [basic.grade_basis === "TERM_RECORDED" ? "級別（期別記載）" : "級別（公式検索・資料）", basic.grade], ["支部（資料記載）", basic.branch],
      ["資料取得時の年齢", Number.isInteger(age) && age >= 0 ? age + "歳" : null], ["登録期", basic.training_term ? basic.training_term + "期" : null],
      ["資料の身長", basic.height_cm ? basic.height_cm + " cm" : null], ["資料の体重", basic.weight_kg ? basic.weight_kg + " kg" : null]]));
    panel.append(basicPanel, node("p", "reference-period", "成績集計：" + api.period.start + " 〜 " + api.period.end));
    if (!profile.term) panel.append(node("p", "reference-empty", "この選手は今回の公式期別資料に未収録です。基本情報と公式プロフィールは確認できます。"));
    else {
      const term = profile.term, rate = value => Number.isFinite(value) ? value.toFixed(1) + "%" : "未収録", number = value => Number.isFinite(value) ? value.toFixed(2) : "未収録";
      const summary = node("div", "reference-summary");
      for (const [label, value] of [["期別勝率", number(term.win_rate)], ["期別2連率", rate(term.top2_percent)], ["期別3連率", rate(term.top3_percent)], ["期別平均ST", number(term.average_st)]])
        summary.append(append(node("div"), node("small", "", label), node("strong", "", value)));
      panel.append(summary, node("p", "reference-records", "出走 " + term.starts + "回 · 1着 " + term.wins + "回 · 優出 " + term.finals + "回 · 優勝 " + term.victories + "回"));
      const preferred = api.preferredCourses(profile), strengths = node("section", "reference-strengths");
      strengths.append(node("h4", "", "得意コースの目安"));
      if (preferred.courses.length) for (const row of preferred.courses) {
        strengths.append(node("span", "course-strength", row.course + "コース · 2連率 " + rate(row.top2_percent) + (preferred.basis === "COHORT_ADJUSTED" ? " · 同コース平均比 +" + row.advantage.toFixed(1) + "pt" : " · 本人内で成績上位")));
      } else strengths.append(node("p", "muted small", "10走以上のコースがないため、得意コースは評価しません。"));
      strengths.append(node("p", "muted small", "10走以上のコースで、同じ期別資料の全選手を合算した同コース2連率との差を比較。得意な決まり手を断定する指標ではありません。"));
      panel.append(strengths, node("h4", "", "1〜6コースの成績"));
      const cards = node("div", "reference-courses");
      for (const row of term.courses) {
        const card = node("article", "reference-course"); card.dataset.course = String(row.course);
        card.append(append(node("div", "reference-course-heading"), badge(row.course), node("strong", "", row.course + "コース"), node("small", "", row.starts + "走")));
        const metrics = node("dl");
        for (const [label, value] of [["1着率", rate(row.win_percent)], ["2連率", rate(row.top2_percent)], ["3連率", rate(row.top3_percent)], ["平均ST", number(row.average_st)]])
          metrics.append(append(node("div"), node("dt", "", label), node("dd", "", value)));
        card.append(metrics);
        if (row.top2_percent !== null) {
          const meter = node("meter"); meter.min = 0; meter.max = 100; meter.value = row.top2_percent; meter.setAttribute("aria-label", row.course + "コースの2連率"); card.append(meter);
        }
        cards.append(card);
      }
      panel.append(cards, node("p", "muted small", "1着率・3連率は着順件数÷コース出走数で計算。失格等も出走数に含みます。2連率は公式資料の収録値です。"), node("h4", "", "このコースで出る場合の展開予想（参考）"));
      const entryMap = referenceEntryMap(race, api);
      const lane = participantNumber(person);
      let selectedCourse = Number.isInteger(entryMap?.[lane]) && entryMap[lane] >= 1 && entryMap[lane] <= 6 ? entryMap[lane] : Number.isInteger(person.preview_course) && person.preview_course >= 1 && person.preview_course <= 6 ? person.preview_course : lane || 1;
      const controls = node("nav", "study-course-controls"), scenario = node("section", "reference-scenario");
      controls.setAttribute("aria-label", "展開の参考にするコース"); scenario.setAttribute("aria-live", "polite");
      function renderScenario() {
        const result = api.scenario(race, person, selectedCourse, {entryMap});
        controls.querySelectorAll("button").forEach(button => button.setAttribute("aria-pressed", String(Number(button.dataset.studyCourse) === selectedCourse)));
        cards.querySelectorAll(".reference-course").forEach(card => card.classList.toggle("selected", Number(card.dataset.course) === selectedCourse));
        scenario.replaceChildren();
        if (!result.stats) { scenario.append(node("p", "", result.message)); return; }
        if (result.entryMessage) scenario.append(node("p", "notice", result.entryMessage));
        scenario.append(node("span", "tag", {FRAME_ASSUMPTION: "枠なりを仮定（本番進入は未確定）", EXHIBITION: "展示進入の並びを参照（本番進入は未確定）", HYPOTHETICAL: "選択したコースを仮定（他艇の進入は未設定）"}[result.basis]),
          node("h4", "", selectedCourse + "コース：" + result.path),
          node("p", "", result.stats.starts + "走 · 1着率 " + rate(result.stats.win_percent) + " · 2連率 " + rate(result.stats.top2_percent) + " · 3連率 " + rate(result.stats.top3_percent) + " · 平均ST " + number(result.stats.average_st)),
          node("p", "", "成立する条件：" + result.condition), node("p", "", "注意する点：" + result.caution));
        if (result.comparisons.length) {
          scenario.append(node("h4", "", "隣のコースの選手と比較（同じ期別集計）"));
          for (const other of result.comparisons) scenario.append(node("p", "", other.course + "コース " + other.name + "：2連率 " + rate(other.stats.top2_percent) + "、平均ST " + number(other.stats.average_st) + "（" + other.stats.starts + "走）。" +
            (other.stDelta === null ? "STの比較値は未収録。" : Math.abs(other.stDelta) < 0.005 ? "平均STは同水準。" : "本人の平均STが " + Math.abs(other.stDelta).toFixed(2) + (other.stDelta < 0 ? "早い。" : "遅い。"))));
        } else scenario.append(node("p", "muted small", "相手の対応コースや10走以上の成績が揃わないため、相対評価は表示していません。"));
        scenario.append(node("p", "muted small", result.message + " 今節の展示ST・モーター・風や波はこの比較に加えていません。保存済みの予想とは別の参考表示です。"));
      }
      for (let course = 1; course <= 6; course++) {
        const button = node("button", "", course + "コース"); button.type = "button"; button.dataset.studyCourse = String(course);
        button.addEventListener("click", () => { selectedCourse = course; renderScenario(); }); controls.append(button);
      }
      panel.append(controls, scenario); renderScenario();
    }
    const sources = node("details", "reference-sources");
    sources.append(node("summary", "", "公式資料の出典・参照時点"), facts([["期別資料", api.source.url], ["資料SHA", api.source.sha256],
      ["資料の集計期間", api.period.start + " 〜 " + api.period.end], ["資料の接続・取得 JST", stamp(api.capturedAt)], ["公式検索の級別取得 JST", stamp(api.source.current_grade_source?.captured_at)],
      ["個別プロフィール", basic.source_url], ["個別プロフィールSHA", basic.source_sha256]]));
    panel.append(sources); return panel;
  }
  function renderDailyCard() {
    if (!activeDaily || !activeDaily.host.isConnected || !participantDialog?.open) return;
    const {host, race, person} = activeDaily, api = globalThis.RaceRacerDaily, profile = api?.get(race, person);
    const focused = host.contains(document.activeElement) ? document.activeElement.dataset.dailyCourse : null;
    host.replaceChildren(node("h3", "", "選手の直近成績（過去90日）"));
    if (!profile) { host.append(node("p", "muted small", api?.status === "LOADING" ? "日次の成績を確認しています。" : "この選手の日次成績はまだ取得できていません。公式期別成績は下で確認できます。")); return; }
    const own = profile.daily, data = api.data, live = data.today, percent = value => Number.isFinite(value) ? value.toFixed(1) + "%" : "未集計", st = value => Number.isFinite(value) ? value.toFixed(2) : "未集計";
    if (live) host.firstChild.textContent = "レースごとに更新する成績";
    const yesterday = new Date(Date.parse(A.jstToday() + "T00:00:00Z") - 86400000).toISOString().slice(0, 10);
    if (api.status !== "READY" || data.period.end < yesterday) host.append(node("p", "notice", "更新待ち：前回の集計を表示しています。"));
    host.append(node("p", "reference-period", (live ? "過去90日：" : "集計対象：") + data.period.start + " 〜 " + data.period.end + (live ? " ＋当日確定分（" + live.day + "）" : "")),
      node("p", "muted small", "集計更新 " + stamp(data.generated_at) + " JST · 元結果の取得 " + stamp(data.last_source_at) + " JST"),
      node("p", data.coverage.complete ? "muted small" : "notice", data.coverage.parsed_days + " / 90日分の日次資料を取得" + (data.coverage.partial_days.length ? " · 一部会場が未収録の日 " + data.coverage.partial_days.length + "日" : "") + (data.coverage.complete ? "。" : "。確認できた結果だけを集計しています。")));
    if (live) {
      host.append(node("p", "muted small", "本日 " + live.confirmed_races + "レースを反映 / " + (live.expected_races === null ? "対象レース確認中" : "対象 " + live.expected_races + "レース") + " · 更新チェック " + stamp(api.heartbeat?.checked_at || live.last_checked_at) + " JST"));
      const today = node("section", "reference-strengths daily-today-results");
      today.append(node("h4", "", "この選手の当日結果 · 出走 " + own.today_stats.starts + "回" + (own.today_stats.confirmed_absences ? " · 欠場 " + own.today_stats.confirmed_absences + "回" : "")));
      for (const row of own.today_races) {
        const venue = U.venueName({sport: "boat", venue: "場コード" + row.race_id.slice(9, 11)}), number = Number(row.race_id.slice(-2));
        const finish = Number.isInteger(row.finish) ? row.finish + "着" : ({F: "フライング", L: "出遅れ", 欠: "欠場", 転: "転覆", 落: "落水", 妨: "妨害", 失: "失格"}[row.result_code] || "失格等");
        today.append(node("p", "small", venue + " " + number + "R · " + finish + " · " + (row.course ? row.course + "コース" : "進入未確認") + " · ST " + (row.st_status === "OK" ? st(row.st) : row.st_status === "F" || row.st_status === "L" ? row.st_status : "未集計")));
      }
      if (!own.today_races.length) today.append(node("p", "muted small", "この選手の当日結果はまだ反映されていません。確定を確認でき次第、成績に加えます。"));
      host.append(today);
    }
    const summary = node("div", "reference-summary");
    for (const [label, value] of [["1着率", percent(own.summary.win_percent)], ["2連率", percent(own.summary.top2_percent)], ["3連率", percent(own.summary.top3_percent)], ["平均ST", st(own.summary.average_st)]]) summary.append(append(node("div"), node("small", "", label), node("strong", "", value)));
    host.append(summary, node("p", "reference-records", "出走 " + own.summary.starts + "回 · 1着 " + own.summary.wins + "回 · ST集計 " + own.summary.st_samples + "回 · 欠場 " + own.summary.confirmed_absences + "回"));
    const preferred = globalThis.RaceRacerProfiles.preferredCourses(profile, {baselines: api.baselines}), strengths = node("section", "reference-strengths");
    strengths.append(node("h4", "", "直近の得意コースの目安"));
    for (const row of preferred.courses) strengths.append(node("span", "course-strength", row.course + "コース · 2連率 " + percent(row.top2_percent) + (preferred.basis === "COHORT_ADJUSTED" ? " · 同コース平均比 +" + row.advantage.toFixed(1) + "pt" : " · 本人内で成績上位")));
    strengths.append(node("p", "muted small", preferred.courses.length ? "10走以上のコースを同じ集計期間の全選手・同コース平均と比較しています。" : "10走以上のコースがないため、得意コースは評価しません。"));
    host.append(strengths);
    const cards = node("div", "reference-courses");
    for (const row of own.courses) {
      const card = node("article", "reference-course daily-course"); card.dataset.course = String(row.course);
      card.append(append(node("div", "reference-course-heading"), badge(row.course), node("strong", "", row.course + "コース"), node("small", "", row.starts + "走")));
      const metrics = node("dl");
      for (const [label, value] of [["1着率", percent(row.win_percent)], ["2連率", percent(row.top2_percent)], ["3連率", percent(row.top3_percent)], ["平均ST", st(row.average_st)]]) metrics.append(append(node("div"), node("dt", "", label), node("dd", "", value)));
      card.append(metrics, node("p", "muted small", "ST集計 " + row.st_samples + "走")); cards.append(card);
    }
    host.append(cards, node("p", "muted small", "率の分母は失格・F・L等も含む実出走数です。欠場は除外し、STは正常に記録された標本のみ。期別の得点勝率とは異なります。"));
    const entryMap = referenceEntryMap(race, api), lane = participantNumber(person);
    let selected = Number(host.dataset.selectedCourse) || entryMap?.[lane] || person.preview_course || lane || 1;
    if (!Number.isInteger(selected) || selected < 1 || selected > 6) selected = 1;
    const controls = node("nav", "study-course-controls"), scenario = node("section", "reference-scenario daily-scenario");
    controls.setAttribute("aria-label", "日次成績で参考にするコース"); scenario.setAttribute("aria-live", "polite");
    const render = () => {
      host.dataset.selectedCourse = String(selected); controls.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", String(Number(b.dataset.dailyCourse) === selected)));
      cards.querySelectorAll("article").forEach(c => c.classList.toggle("selected", Number(c.dataset.course) === selected));
      const result = globalThis.RaceRacerProfiles.scenario(race, person, selected, {entryMap, referenceApi: api}); scenario.replaceChildren(node("h4", "", "直近成績で見る展開（参考）"));
      if (!result.stats) { scenario.append(node("p", "", result.message)); return; }
      if (result.entryMessage) scenario.append(node("p", "notice", result.entryMessage));
      scenario.append(node("span", "tag", {FRAME_ASSUMPTION: "枠なりを仮定（本番進入は未確定）", EXHIBITION: "展示進入を参照（本番進入は未確定）", HYPOTHETICAL: "選択コースを仮定（他艇の進入は未設定）"}[result.basis]),
        node("p", "", selected + "コース：" + result.path + " · " + result.stats.starts + "走 · 2連率 " + percent(result.stats.top2_percent)), node("p", "", result.condition), node("p", "", result.caution));
      for (const other of result.comparisons) scenario.append(node("p", "", other.course + "コース " + other.name + "：2連率 " + percent(other.stats.top2_percent) + " · 平均ST " + st(other.stats.average_st) + "（" + other.stats.starts + "走）"));
      scenario.append(node("p", "muted small", "日次の実績を使った条件別の参考説明です。保存された予想・買い目を変更しません。"));
    };
    for (let c = 1; c <= 6; c++) { const b = button(c + "コース", "", () => {selected = c; render();}); b.dataset.dailyCourse = String(c); controls.append(b); }
    host.append(controls, scenario); render();
    const sources = node("details", "reference-sources"); sources.append(node("summary", "", "日次集計の出典・未取得日"), facts([["公式結果資料", data.source.url], ["出典集合SHA", data.source.sha256], ["未取得日", data.coverage.missing_days.join("、") || "なし"], ["進入不明の出走", own.summary.unknown_course_starts + "回"]])); host.append(sources);
    if (focused) controls.querySelector('[data-daily-course="' + focused + '"]')?.focus({preventScroll: true});
  }
  function openParticipant(person, race, opener) {
    if (!participantDialog) {
      participantDialog = node("dialog", "participant-dialog"); participantDialog.id = "participant-dialog";
      participantDialog.setAttribute("aria-labelledby", "participant-dialog-title");
      participantDialog.addEventListener("cancel", event => { event.preventDefault(); closeParticipant(); });
      participantDialog.addEventListener("click", event => {
        if (event.target !== participantDialog) return;
        const bounds = participantDialog.getBoundingClientRect();
        if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) closeParticipant();
      });
      document.body.append(participantDialog);
    }
    const dialog = participantDialog, portrait = globalThis.RaceRacerPortraits?.get(race, person), registration = participantRegistration(person);
    participantOpener = opener;
    const header = node("header", "profile-header"), heading = node("div"), title = node("h2", "", portrait?.name || person.name || "選手情報");
    title.id = "participant-dialog-title";
    heading.append(node("p", "eyebrow", "RACER CARD"), title);
    const close = button("×", "profile-close", closeParticipant); close.dataset.closeParticipant = ""; close.setAttribute("aria-label", "選手カルテを閉じる");
    header.append(heading, close);
    const body = node("div", "profile-body"), hero = node("div", "profile-hero");
    hero.append(participantCard(person, race, false, false));
    const introduction = node("div", "profile-introduction");
    introduction.append(node("span", "tag scope-" + race.scope, scopeName(race.scope)), node("p", "", raceName(race)), node("p", "muted small", "出走情報の保存値 · 取得 " + stamp(person.captured_at || person.observed_at || race.observed_at || race.as_of) + " JST"));
    if (portrait) {
      const link = node("a", "outline profile-official", "公式プロフィールを開く ↗");
      link.href = portrait.sourceUrl; link.target = "_blank"; link.rel = "noopener noreferrer"; link.referrerPolicy = "no-referrer"; link.dataset.officialProfile = "";
      introduction.append(link);
    }
    hero.append(introduction); body.append(hero);
    const reference = globalThis.RaceRacerProfiles?.get(race, person);
    if (reference) {
      const daily = node("section", "racer-reference daily-reference"); daily.id = "racer-daily-reference";
      activeDaily = {host: daily, race, person}; body.append(daily, athleteReference(race, person, reference));
    }
    const values = node("div", "profile-values");
    const decimal = (value, suffix = "") => typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) + suffix : value;
    const group = (label, fields, always = false) => {
      const section = node("section", "profile-section"), available = fields.filter(([, value]) => value !== null && value !== undefined && value !== "");
      if (!available.length && reference) return;
      section.append(node("h3", "", label));
      section.append(available.length || always ? facts(always ? fields : available) : node("p", "muted", "この項目の保存値はありません。"));
      values.append(section);
    };
    if (!reference || [person.grade, person.branch, person.age].some(value => value !== undefined && value !== null)) group("読込出走表の基本情報", [["登録番号", registration], ["級別", person.grade], ["支部", person.branch], ["年齢", person.age]], true);
    group("成績・スタート", [["全国勝率", decimal(person.national_win_rate)], ["当地勝率", decimal(person.local_win_rate)],
      ["全国2連率", decimal(person.national_top2_rate, "%")], ["当地2連率", decimal(person.local_top2_rate, "%")], ["平均ST", decimal(person.average_st)]]);
    group("モーター・ボート", [["モーター番号", person.motor_no], ["モーター2連率", decimal(person.motor_top2_rate, "%")],
      ["ボート番号", person.boat_no], ["ボート2連率", decimal(person.boat_top2_rate, "%")]]);
    group("このレースの直前情報", [["展示タイム", decimal(person.display_time)], ["展示ST", person.preview_st], ["展示進入", person.preview_course],
      ["選手コメント", person.comment || person.last_comment]]);
    body.append(values);
    const context = selectedBoatContext(race), lane = participantNumber(person);
    if (portrait && registration && Number.isInteger(lane) && context && validBoatObservationContext(context, race.race_id)) {
      const supplement = node("section", "profile-supplement"); supplement.id = "profile-supplement";
      supplement.append(node("h3", "", "補足として取得した直前情報"), node("p", "muted small", "保存予想への反映は未検証です。以下の観測値は保存予想の入力とは別に表示しています。"));
      let count = 0;
      for (const [kind, label] of [["beforeinfo", "展示・直前情報の観測"], ["pitreport", "選手コメントの観測"]]) {
        const page = context[kind];
        if (page?.status !== "PARSED" || page.roster_binding_status !== "VERIFIED") continue;
        const observed = page.participants.find(value => value.lane === lane && value.registration_number === registration &&
          [value.name, value.comment_attribution?.racer_name].every(name => globalThis.RaceRacerPortraits.get(race, {registration_number: registration, name}) === portrait));
        if (!observed) continue;
        const fields = kind === "beforeinfo" ? [["展示タイム", decimal(observed.display_time)], ["展示ST", observed.exhibition_st_raw ?? decimal(observed.exhibition_st)],
          ["ST表示", {OK: "正常ST", F: "F（フライング表示）", L: "L（出遅れ表示）", NOT_PUBLISHED: "未公表"}[observed.exhibition_st_status]],
          ["実進入コース", observed.exhibition_course], ["体重 kg", observed.bodyweight_kg], ["調整重量 kg", observed.adjustmentweight_kg], ["チルト 度", observed.tilt],
          ["部品交換", observed.parts_replacement?.join(" / ")]] : [["選手コメント", observed.comment], ["取材者", observed.comment_attribution?.reporter || page.reporter]];
        const present = fields.filter(([, value]) => value !== null && value !== undefined && value !== ""); if (!present.length) continue;
        const section = node("section", "profile-section"), details = node("details", "context-source-details");
        const late = (page.cutoff_eligibility?.captured_before_cutoff ?? page.captured_before_cutoff) === false;
        section.append(node("h4", "", label), node("p", "muted small", "観測取得 " + stamp(page.source.captured_at) + " JST" + (late ? " · 締切後の取得" : "")), facts(present));
        details.append(node("summary", "", "取得元と観測の記録"), facts([["取得元URL", page.source.source_url], ["観測SHA", page.source.sha256], ["公式公開日時 JST", stamp(page.source.published_at)]]));
        section.append(details); supplement.append(section); count++;
      }
      if (count) body.append(supplement);
    }
    body.append(node("p", "muted small profile-source", "出典：" + sourceText(race.source_provenance) + "。成績は出走情報に保存された期間の値です。未取得の項目を現在の成績で補完していません。"));
    dialog.replaceChildren(header, body); document.body.classList.add("participant-dialog-open");
    if (!dialog.open) dialog.showModal();
    renderDailyCard();
    dialog.scrollTop = 0;
    close.focus();
  }
  function participantCard(p, race, expanded = false, interactive = true) {
    const number = participantNumber(p), card = node("article", "racer-card"), avatar = node("div", "racer-avatar");
    if (Number.isInteger(number)) avatar.append(badge(number));
    const silhouette = node("span", "avatar-silhouette", "◉");
    silhouette.setAttribute("aria-hidden", "true");
    const status = node("small", "portrait-status", race?.scope === "synthetic" ? "合成表示" : "イラスト準備中");
    const portrait = globalThis.RaceRacerPortraits?.get(race, p);
    if (portrait) {
      const img = node("img", portrait.atlas ? "portrait-atlas-image" : "racer-portrait");
      let artwork = img;
      if (portrait.atlas) {
        const a = portrait.atlas;
        artwork = node("span", "racer-portrait portrait-atlas atlas-size-" + a.columns + " atlas-x-" + a.column + " atlas-y-" + a.row);
        artwork.append(img);
      }
      img.alt = portrait.name + "選手のイラスト";
      img.width = img.height = 88;
      img.loading = "lazy"; img.decoding = "async"; img.referrerPolicy = "no-referrer";
      img.dataset.registration = portrait.registration;
      img.addEventListener("error", () => { artwork.remove(); avatar.append(silhouette); status.textContent = "イラスト読込待ち"; status.hidden = false; }, {once: true});
      img.src = portrait.src; avatar.append(artwork); status.textContent = ""; status.hidden = true;
    } else avatar.append(silhouette);
    const registration = participantRegistration(p);
    const identity = [avatar, node("strong", "racer-name", p.placeholder ? "出走者 未取得" : p.name ? text(p.name) : "名前 未取得"), node("small", "muted", p.placeholder ? "表示用の枠" : registration ? "登録 " + text(registration) : "登録 未取得")];
    if (interactive && !p.placeholder) {
      const trigger = button("", "racer-identity", () => openParticipant(p, race, trigger));
      trigger.dataset.openParticipant = registration || "unverified";
      trigger.setAttribute("aria-label", (p.name || "出走者") + "の選手情報を開く");
      trigger.append(...identity); card.append(trigger);
    } else card.append(...identity);
    if (!p.placeholder) card.append(status);
    if (expanded && !p.placeholder) {
      const fields = node("dl", "racer-fields");
      for (const [label, value] of [["登録番号", registration], ["モーター", p.motor_no], ["平均ST", p.average_st], ["展示タイム", p.display_time]]) {
        if (value !== undefined && value !== null) fields.append(node("dt", "", label), node("dd", "", text(value)));
      }
      card.append(fields);
    }
    return card;
  }
  function participantGrid(r, expanded = false) {
    const people = knownParticipants(r), box = node("div", "racer-grid" + (expanded ? " expanded" : ""));
    if (people.length) {
      box.dataset.entrants = String(people.length);
      people.forEach(p => box.append(participantCard(p, r, expanded)));
    } else if (r.sport === "boat") {
      box.classList.add("placeholder-entrants");
      for (let i = 1; i <= 6; i++) box.append(participantCard({number: i, placeholder: true}, r));
    } else return empty("出走メンバーは未取得です", "人数・個別成績は保存原本に含まれていません。");
    return box;
  }
  function ticketPreview(p, count = 4) {
    const list = node("div", "saved-tickets");
    if (!p) { list.append(node("p", "muted", "保存された買い目は未取得")); return list; }
    p.ordered_top8.slice(0, count).forEach((t, index) => list.append(append(node("span", "saved-ticket"), node("small", "ticket-rank", String(index + 1)), combo(t))));
    return list;
  }
  function informationButtons(race) {
    const context = selectedBoatContext(race);
    const supplement = race.sport === "boat" && context && validBoatObservationContext(context, race.race_id) &&
      [context.beforeinfo, context.pitreport].some(page => page?.status === "PARSED" && (page.participants?.length || page.weather && Object.values(page.weather).some(value => value != null)));
    const nav = node("nav", "race-information"); nav.setAttribute("aria-label", raceName(race) + "の情報");
    for (const info of U.raceInformation(C.forDisplay(race), {supplementalPreview: Boolean(supplement)})) {
      const action = button("", "information-button" + (info.available ? " info-available" : ""), () => openRace(race.race_id, info.key));
      action.dataset.raceTab = info.key; action.dataset.infoAvailable = String(info.available);
      action.append(node("strong", "", info.label), node("small", "", info.detail)); nav.append(action);
    }
    return nav;
  }
  function officialRaceLinks(race) {
    const nav = node("nav", "official-race-links"); nav.setAttribute("aria-label", "公式情報を別タブで開く");
    for (const info of U.boatRaceLinks(race)) {
      const link = node("a", "", info.label + " ↗"); link.href = info.url;
      link.target = "_blank"; link.rel = "noopener noreferrer"; link.referrerPolicy = "no-referrer"; link.dataset.officialRace = info.kind; nav.append(link);
    }
    return nav;
  }
  const venueEntries = () => U.venueOverview(scoped(), {sport: state.sport, favorites: state.favoriteVenues});
  function chooseVenue(venue, toggle = false) {
    state.venue = toggle && state.venue === venue ? "" : venue; state.visible = 60;
    refreshSelects(); renderAll(); showPage("races", true);
  }
  function venueButton(entry, home = false) {
    const action = button("", "venue-button" + (home ? " home-venue-button" : "") + (entry.venue === state.venue ? " active" : "") + (entry.favorite ? " favorite-venue" : ""), () => { if (home) state.raceView = state.day < A.jstToday() ? "results" : "upcoming"; chooseVenue(entry.venue, !home); });
    action.dataset.venue = entry.venue;
    action.setAttribute("aria-pressed", String(entry.venue === state.venue));
    action.append(node("span", "venue-name", entry.venue));
    const next = entry.nextRace, raceNumber = Number.isInteger(next?.race_no) ? next.race_no + "R " : "";
    const clock = next ? (next.event_date_jst !== state.day ? next.event_date_jst.slice(5) + " " : "") + time(U.raceDeadline(next)) : "";
    const label = !entry.count ? "未取得" : !home && state.raceView === "results" ? "結果 " + entry.resultCount + "件 · 確認済 " + entry.settledCount : !home && state.raceView === "unknown" ? "締切未確認 " + entry.unknownCount + "件" : next ? raceNumber + clock : "締切前 0件 · 結果 " + entry.resultCount + "件";
    action.append(node("small", "venue-meta", label));
    return action;
  }
  function renderVenueExplorer(entries) {
    const countKey = {upcoming:"upcomingCount",results:"resultCount",unknown:"unknownCount"}[state.raceView];
    const ordered = [...entries].sort((a,b) => Number(b.favorite)-Number(a.favorite) || Number(b[countKey]>0)-Number(a[countKey]>0));
    $("venue-buttons").replaceChildren(...ordered.map(entry => venueButton(entry)));
    $("venue-title").textContent = state.venue || "すべての会場";
    const selected = entries.find(entry => entry.venue === state.venue);
    $("venue-summary").hidden = !selected;
    $("venue-summary").textContent = selected ? (selected.count ? "締切前 " + selected.upcomingCount + "件 · レース結果 " + selected.resultCount + "件（結果待ち " + selected.pendingResultCount + "・保留 " + selected.heldCount + "）" : "この会場のレースデータは未取得です。開催なしを意味しません。") : "会場を選ぶと、その会場のレースだけを表示します。";
    $("pin-venue").hidden = !selected;
    const pinned = Boolean(selected?.favorite);
    $("pin-venue").textContent = pinned ? "★ マイ会場" : "☆ マイ会場に追加";
    $("pin-venue").setAttribute("aria-pressed", String(pinned));
    $("all-venues").hidden = !state.venue;
    const picker = $("venue-picker");
    if (picker.dataset.selection !== state.venue) { picker.open = !state.venue; picker.dataset.selection = state.venue; }
  }
  function sameVenueRaces(race) {
    const venue = U.venueName(race);
    if (!venue || !race.event_date_jst || !Number.isInteger(race.race_no)) return null;
    const rows = races().filter(row => row.sport === race.sport && row.event_date_jst === race.event_date_jst && U.venueName(row) === venue);
    const panel = node("section", "same-venue-races"); panel.id = "same-venue-races";
    const heading = node("div", "section-heading");
    heading.append(node("strong", "", venue + " · " + race.event_date_jst), button("会場の一覧へ →", "text-button", () => chooseVenue(venue)));
    panel.append(heading);
    const nav = node("nav", "race-number-nav"); nav.setAttribute("aria-label", "同じ会場・同じ日のレース");
    const numbers = race.sport === "boat" ? Array.from({length: 12}, (_, i) => i + 1) : [...new Set(rows.map(row => row.race_no).filter(Number.isInteger))].sort((a, b) => a - b);
    for (const number of numbers) {
      const matches = rows.filter(row => row.race_no === number), target = matches.length === 1 ? matches[0] : matches.find(row => row.race_id === race.race_id);
      const action = button(number + "R", target?.race_id === race.race_id ? "active" : "", () => openRace(target.race_id, state.detailTab));
      action.dataset.raceNumber = String(number); action.disabled = !target;
      action.setAttribute("aria-label", number + "R" + (!target ? matches.length ? " 複数の記録があり照合が必要です" : " データ未取得" : "を開く"));
      if (target?.race_id === race.race_id) action.setAttribute("aria-current", "true");
      nav.append(action);
    }
    panel.append(nav); return panel;
  }
  function raceCard(r, featured = false) {
    const p = prediction(r), card = node("article", "race-card" + (featured ? " featured" : ""));
    card.dataset.raceId = r.race_id; card.dataset.racePhase = U.racePhase(r); card.dataset.cutoffAt = U.raceDeadline(r) || "";
    const head = node("div", "race-card-head"), title = node("div"), meta = node("div", "race-time");
    title.append(node("span", "sport-tag", icons[r.sport] + " " + sports[r.sport]), node("h3", "", raceName(r)));
    meta.append(node("span", "", r.event_date_jst || "日付 未取得"), node("strong", "", "締切 " + time(U.raceDeadline(r))));
    head.append(title, meta); card.append(head);
    const tags = node("div", "race-tags"); tags.append(node("span", "tag scope-" + r.scope, scopeName(r.scope)), node("span", "tag", forecastStatus(r, p)), node("span", "tag", stageName(p))); card.append(tags);
    tags.append(outcomeBadge(r,p));
    if (r.result?.status === "final") card.append(node("p","small","結果 " + resultCombination(r) + " · 100円払戻 " + payoutSummary(r.result)));
    if (r.missing_reasons?.includes("SAVED_FORECAST_CUTOFF_CONFLICT")) tags.append(node("span","tag","原本間で締切の記録差あり"));
    card.append(participantGrid(r), informationButtons(r));
    const foot = node("div", "race-card-footer"), saved = node("div", "card-prediction");
    saved.append(node("strong", "small", p ? p.native_top8_available === false ? "保存" + p.ordered_top8.length + "点プラン" : "保存Top8 · " + p.ordered_top8.length + "点" : "未予想"), node("p", "muted model-caption", modelName(p)), ticketPreview(p, featured ? 4 : 2));
    const open = button("レース詳細を見る →", "outline", () => openRace(r.race_id)); open.dataset.openRace = r.race_id;
    foot.append(saved, open); card.append(foot);
    if (featured) card.append(node("p", "muted small card-rationale", U.forecastExplanation(r,p)?.rationale || r.no_forecast_reason || "保存予想の読み込みを待っています。"));
    return card;
  }
  function showPage(page, moveFocus = false) {
    if (!Object.hasOwn(pageNames, page)) page = "home";
    state.page = page;
    document.querySelectorAll(".page").forEach(n => { n.hidden = n.id !== "page-" + page; });
    document.querySelectorAll("[data-page]").forEach(b => {
      const active = b.dataset.page === page || (page === "detail" && b.dataset.page === "races");
      b.classList.toggle("active", active); if (active) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
    });
    const [eyebrow, title, description] = pageNames[page];
    $("page-eyebrow").textContent = eyebrow; $("page-title").textContent = title; $("page-description").textContent = description;
    $("preference-strip").hidden = !["home", "races", "picks"].includes(page);
    if (!document.querySelector('meta[name="race-ai-encrypted-saved-view"]') && location.hash !== "#" + page) history.pushState(null, "", "#" + page);
    if (page === "detail") renderDetail();
    if (page === "races") renderRaces();
    if (page === "results") renderResults();
    if (page === "research") renderResearch();
    if (page === "picks") renderTickets();
    if (moveFocus) { $("page-title").tabIndex = -1; $("page-title").focus({preventScroll: true}); window.scrollTo({top: 0}); }
  }
  function setSport(sport) {
    state.sport = sport; state.venue = ""; state.visible = 60;
    if (state.page === "detail") showPage("races");
    persistPreferences(); refreshSelects(); renderAll();
    if (automaticMode()) { loadAutomaticLatest(true);scheduleAutomaticPoll(); }
  }
  function openRace(id, tab = "outlook") {
    state.selectedId = id; state.detailTab = ["outlook", "participants", "preview", "analysis", "history"].includes(tab) ? tab : "outlook";
    refreshSelects(); showPage("detail", true);
  }
  function renderHome() {
    const manual = U.summarize(dailyPurchases()), all = scoped(), actualImported = M.summary(displayRows(all)).overall;
    const entries = venueEntries();
    $("home-venues").replaceChildren(...entries.slice(0, 6).map(entry => venueButton(entry, true)));
    $("home-venue-note").textContent = entries.some(entry => entry.favorite) ? "★ マイ会場を先頭に表示 · 時刻は読込済みレースの次の締切" : "会場を選んで、☆でマイ会場に追加できます。時刻は次の締切です。";
    const outcomes=all.map(r=>P.compare(r,prediction(r)).status),hits=outcomes.filter(v=>v==="HIT").length,misses=outcomes.filter(v=>v==="MISS").length;
    $("home-metrics").replaceChildren(
      metric("本日の予算", yen(state.budget), "ご自身の設定", "▣"),
      metric("使用額", manual.purchases ? yen(manual.spent) : "記録なし", "この端末の実購入申告", "▤"),
      metric("残予算", yen(state.budget - manual.spent), "予算 − 手動購入記録", "▣"),
      metric("購入の回収率", manual.roi === null ? "未集計" : manual.roi.toFixed(1) + "%", "手入力・確定分のみ", "▥"),
      metric("表示中の予想の的中", hits+misses ? hits+" / "+(hits+misses)+"レース" : "未集計", "取得した結果との照合 · 未取得分は除外", "◎")
    );
    const savedMessage = !dataset && savedMessages[generation.savedState];
    $("home-races").replaceChildren(...(all.length ? all.slice(0, 3).map((r, i) => raceCard(r, i === 0)) : [empty(savedMessage?.[0] || "この条件のレースは未取得です", savedMessage?.[1] || (dataset ? "競技・日付を変更するか、「読み込んだ全期間」を確認してください。" : "会場・日付を選んで確認できます。レース情報が届いていない会場は「未取得」と表示します。"))]));
    $("home-candidates").replaceChildren(...candidateItems());
    const budget = $("home-budget"); budget.replaceChildren(node("strong", "", yen(state.budget - manual.spent)), node("p", "muted", "残予算 / " + yen(state.budget)));
    const progress = node("progress"); progress.max = state.budget; progress.value = Math.min(manual.spent, state.budget); progress.setAttribute("aria-label", "本日の予算使用額"); budget.append(progress, node("p", "muted small", "候補額は使用額に含めません。"));
    $("home-data").replaceChildren(metric("レース情報", all.length + "件", sports[state.sport] + " / 選択期間", "▦"), node("p", "muted small", dataset ? "現在表示しているレースの情報です。" : "レース情報の取得を待っています。"));
  }
  function candidateItems() {
    const groups = [...new Set(state.candidates.map(t => t.raceId))];
    if (!groups.length) return [node("p", "muted", "購入候補はまだありません。")];
    return groups.map(id => {
      const r = races().find(row => row.race_id === id), ts = ticketsFor(id);
      return append(node("div", "candidate-mini"), button(raceName(r), "text-button", () => { state.selectedId = id; refreshSelects(); showPage("picks", true); }), node("strong", "", yen(ts.reduce((s, t) => s + t.amount, 0))), node("small", "muted", ts.length + "点 · " + (state.confirmed.has(id) ? "候補確定 / 未購入" : "編集中 / 未購入")));
    });
  }
  function raceResultCard(r) {
    const p = prediction(r), card = node("article", "race-card race-result-card"), head = node("div", "race-card-head");
    card.dataset.raceId = r.race_id; card.dataset.racePhase = "results"; card.dataset.venue = U.venueName(r);
    head.append(append(node("div"),node("h3", "", raceName(r)),node("p", "muted small",r.event_date_jst + " · 締切 " + time(U.raceDeadline(r)))),outcomeBadge(r,p));
    card.append(head,resultView(r,{showBadge:false}),node("p", "muted small",p ? "AI予想：" + stageName(p) + " · " + modelName(p) : "保存された予想はありません"));
    const actions = node("div", "race-result-actions"), details = button("結果詳細", "outline", () => openRace(r.race_id,"history")), forecast = button("予想を見る", "text-button", () => openRace(r.race_id));
    details.dataset.openResult = r.race_id; forecast.dataset.openRace = r.race_id; forecast.dataset.openPrediction = r.race_id; actions.append(details,forecast); card.append(actions); return card;
  }
  function setRaceView(view, focus = false) {
    state.raceView = ["upcoming","results","unknown"].includes(view) ? view : "upcoming"; state.visible = 60; renderRaces();
    if (focus) $("race-view-" + state.raceView).focus();
  }
  function scheduleRaceBoundary(all, now) {
    clearTimeout(raceBoundaryTimer); raceBoundaryTimer = null;
    if (state.page !== "races" || document.hidden) return;
    const lists = U.raceLists(all,{now}); if (!lists.upcoming.length && !lists.unknown.length) return;
    const next = lists.upcoming[0], delay = next ? Math.max(25,Math.min(60000,Date.parse(U.raceDeadline(next))-now+25)) : 60000;
    raceBoundaryTimer = setTimeout(() => { raceBoundaryTimer = null; if (state.page === "races") renderRaces(); },delay);
  }
  function renderRaces() {
    const now = Date.now(), all = scoped(), baseMatches = U.filterRaces(displayRows(races()), {sport: state.sport, day: state.day, allDates: state.allDates, period: state.period, query: state.query, venue: state.venue, sort: state.sort, candidatesOnly: state.candidatesOnly, candidateRaceIds: state.candidates.map(t => t.raceId)});
    const matches = state.forecastOnly ? baseMatches.filter(r => prediction(r)) : baseMatches, lists = U.raceLists(matches,{now});
    if (state.raceView === "unknown" && !lists.unknown.length) state.raceView = "upcoming";
    const phase = state.raceView, status = state.statusFilter === "PREDICTION_UNVERIFIED" ? "REVIEW" : state.statusFilter;
    let modelControls = $("race-model-controls");
    if (!modelControls) { modelControls = node("section", "model-switch-bar"); modelControls.id = "race-model-controls"; $("page-races").querySelector(".race-view-tabs").before(modelControls); }
    modelControls.replaceChildren(modelPicker(lists[phase],state.sport,"race-model-select",state.modelBySport[state.sport] || "",true));
    let filtered = phase === "results" && status !== "all" ? lists.results.filter(r => P.compare(r,prediction(r)).status === status) : lists[phase];
    if (state.sort !== "time") { const ids = new Map(matches.map((r,i)=>[r.race_id,i])); filtered = [...filtered].sort((a,b)=>ids.get(a.race_id)-ids.get(b.race_id)); }
    for (const [view,label] of [["upcoming","これからのレース"],["results","レース結果"],["unknown","締切未確認"]]) {
      const tab = $("race-view-"+view); tab.textContent = label + "（" + lists[view].length + "）"; tab.hidden = view === "unknown" && !lists.unknown.length; tab.setAttribute("aria-selected",String(view === phase)); tab.tabIndex = view === phase ? 0 : -1;
    }
    $("race-status-label").hidden = phase !== "results";
    $("race-sort").querySelector('[value="time"]').textContent = phase === "results" ? "締切が新しい順" : "締切時刻順";
    $("all-races").setAttribute("aria-labelledby","race-view-"+phase); $("all-races").dataset.raceListView = phase;
    const heading = $("all-races").previousElementSibling; if (heading?.classList.contains("race-row-heading")) heading.hidden = phase === "results";
    $("race-count").textContent = {upcoming:"締切前 ",results:"レース結果 ",unknown:"締切未確認 "}[phase] + filtered.length + "件 / 選択期間の対象 " + all.length + "件";
    const coverage = U.modelCoverage(displayRows(all), C.models, {sport: state.sport});
    $("all-race-model-scope").textContent = sports[state.sport] + " · 適用 " + coverage.applicable_models + " / 登録 " + C.models.length + "モデル · 対象台帳 " + coverage.target_races + "レース（保存予想なし " + all.filter(r => !predictions(r).length).length + "レースを含む） · " + coverage.display_stages.map(stage=>stageName({stage}) + " " + coverage.models.reduce((sum,m)=>sum+(m.stages[stage].target_races||0),0) + "対象枠").join(" / ");
    const content = filtered.slice(0,state.visible).map(r => phase === "results" ? raceResultCard(r) : raceCard(r));
    if (!filtered.length) {
      const unloaded = state.venue && !all.some(r => U.venueName(r) === state.venue), title = unloaded ? state.venue + "のレースデータは未取得です" : phase === "upcoming" && all.length ? (lists.unknown.length ? "締切前と確認できるレースはありません" : "締切前のレースはありません") : phase === "results" && all.length && !lists.results.length ? "レース結果はまだありません" : all.length ? "条件に一致するレースがありません" : sports[state.sport] + "のレースは未取得です";
      const message = empty(title,unloaded || !all.length ? "未取得は開催なしを意味しません。対象日や保存情報を確認してください。" : "会場・検索条件を変更するか、レース結果を確認できます。");
      if (phase === "upcoming" && lists.results.length) message.append(button("レース結果を見る", "primary", () => setRaceView("results",true)));
      if (phase === "results" && lists.upcoming.length) message.append(button("これからのレースを見る", "primary", () => setRaceView("upcoming",true)));
      if (unloaded) {
        const links = node("nav", "empty-venue-links"); links.setAttribute("aria-label", "この会場の公式情報");
        for (const info of U.boatVenueLinks({sport: state.sport, venue: state.venue, event_date_jst: state.day})) {
          const link = node("a", "outline", info.label); link.href = info.url; link.target = "_blank"; link.rel = "noopener noreferrer"; link.referrerPolicy = "no-referrer"; link.dataset.officialVenue = info.kind; links.append(link);
        }
        if (links.childElementCount) message.append(links);
      }
      content.push(message);
    }
    if (filtered.length > state.visible) content.push(button("さらに60件表示", "outline full", () => { state.visible += 60; renderRaces(); }));
    $("all-races").replaceChildren(...content); renderVenueExplorer(venueEntries()); $("candidate-count").replaceChildren(...candidateItems()); scheduleRaceBoundary(all,now);
  }
  function predictionPicker(r, id = "prediction-select") {
    const wrapper = node("div", "prediction-controls"), label = node("label", "prediction-picker", "予想の時点・保存履歴"), select = node("select"); select.id = id;
    const list = predictions(r), chosen = prediction(r), modelId = selectedModelId(r);
    wrapper.append(modelPicker([r],r.sport,id === "prediction-select" ? "detail-model-select" : "research-model-select",modelId));
    if (!chosen) select.append(new Option("このモデルの保存予想はありません", ""));
    const modelIdentity=p=>JSON.stringify([p.stage,p.model_id,p.model_version,p.variant,M.codeIdentity?.(p)]);
    list.forEach((p, i) => {
      const repeated=list.filter(other=>modelIdentity(other)===modelIdentity(p)).length>1;
      const clock=p.as_of && Number.isFinite(Date.parse(p.as_of)) ? new Intl.DateTimeFormat("ja-JP",{timeZone:"Asia/Tokyo",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false}).format(new Date(p.as_of)) : "未取得";
      select.append(new Option(stageName(p) + " · " + modelName(p) + (repeated ? " · " + clock + " · " + (i+1) : ""), String(i)));
    });
    select.disabled = !list.length; select.value = chosen ? String(list.indexOf(chosen)) : "";
    select.addEventListener("change", () => {
      if (select.value === "") return;
      const index = Number(select.value), p = list[index]; if (!p) return;
      rememberModelSelections(r.sport);state.predictionKeys[r.race_id] = index;
      if (p.model_id) { state.modelBySport[r.sport] = p.model_id;state.modelOriginals[modelMemoryKey(r,p.model_id)] = M.savedPredictionIdentity(p); }
      else delete state.modelBySport[r.sport];
      renderAll(); $(id)?.focus();
    });
    label.append(select); wrapper.append(label); return wrapper;
  }
  function modelPicker(rows,sport,id,selected,allowDefault=false) {
    const label = node("label", "model-picker", "予想モデルを切り替える"), select = node("select"); select.id = id;
    const options = U.modelOptions(rows,C,sport);
    if (allowDefault || !selected) select.append(new Option(sport === "all" ? "競技を選ぶとモデルを切り替えられます" : "各レースの保存予想", ""));
    for (const item of options) select.append(new Option(modelName(item) + (item.races ? allowDefault ? " · " + item.races + "レース" : " · 予想あり" : " · 未保存"),item.model_id));
    if (selected && !options.some(item => item.model_id === selected)) select.append(new Option(modelName({model_id:selected}) + " · この一覧は未保存",selected));
    select.value = selected;select.disabled = sport === "all";
    select.addEventListener("change", () => chooseModel(sport,select.value,id));
    label.append(select,node("small","muted small",allowDefault ? "保存件数はこの一覧の対象です。選んだモデルを同じ競技で引き継ぎます。" : "モデルを選ぶと買い目・根拠・照合表示が切り替わります。"));
    return label;
  }
  function forecastPanel(r, p) {
    const box = node("section", "forecast-panel");
    if(p){box.dataset.modelId=p.model_id || "";box.dataset.nativeDispatch=String(p.native_dispatch_prediction===true);}
    box.append(append(node("div", "section-heading"), node("h2", "", p?.native_dispatch_prediction ? "取り込んだ予想" : "予想の買い目"), node("span", "tag scope-" + r.scope, forecastStatus(r, p))));
    if (p) {
      box.append(ticketPreview(p, 8));
      const explanation=U.forecastExplanation(r,p);
      if(explanation){
        const rationale=node("p", "forecast-rationale",text(explanation.rationale));rationale.id="forecast-rationale";
        const outlook=node("p", "forecast-outlook",explanation.outlook);outlook.id="forecast-outlook";
        const basis=node("p", "muted small",explanation.basis);basis.id="forecast-outlook-basis";
        box.append(node("h3", "forecast-rationale-heading", "予想根拠"),rationale,node("p", "muted small",explanation.composition),node("h3", "forecast-rationale-heading", "展開予想"),outlook);
        if(explanation.alternative){const other=node("p", "forecast-alternative",explanation.alternative);other.id="forecast-alternative";box.append(other);}
        box.append(basis);
      }
      box.append(node("p", "muted small", "保存 " + stamp(p.persisted_at) + " JST · " + p.ordered_top8.length + "点"));
    }
    else box.append(empty("このモデルの予想は未保存です", modelName({model_id:selectedModelId(r)}) + "の保存予想は、このレースにはありません。モデル選択で保存状況を確認できます。"));
    box.append(button("このレースの買い目を編集 →", "primary full", () => { state.selectedId = r.race_id; refreshSelects(); showPage("picks", true); }));
    return box;
  }
  function resultSyncCaption() {
    if (resultCheck.busy) return "結果の更新を確認しています";
    if (resultCheck.failed) return "更新を確認できません。前回の結果を表示中です";
    if (!refreshSavedResults) return "保存された結果を表示しています";
    const sync=globalThis.RaceRacerDaily?.heartbeat?.result_sync;
    if (sync?.state==="HOLD" || sync?.state==="RETRY") return "結果の更新を再確認しています。前回の結果を表示中です";
    if (sync?.state==="SOURCE_WAIT") return "公式サイトの応答を待っています";
    return "自動更新 · 最終確認 " + stamp(sync?.checked_at || dataset?.results_synced_at) + " JST";
  }
  function syncResultRefreshUI() {
    document.querySelectorAll('[data-result-refresh]').forEach(b=>{b.disabled=!refreshSavedResults||resultCheck.busy;});
    document.querySelectorAll('[data-result-sync-caption]').forEach(n=>{n.textContent=resultSyncCaption();});
  }
  function resultRefreshButton() {
    const control=button("結果を更新", "text-button", ()=>refreshSavedResults?.());control.dataset.resultRefresh="";control.disabled=!refreshSavedResults||resultCheck.busy;return control;
  }
  function resultView(r,{showBadge=true}={}) {
    const result = r.result, box = node("div", "result-block");
    if(showBadge)box.append(outcomeBadge(r,prediction(r)));
    if (!result || result.status==="pending") return append(box, node("p", "muted small", U.racePhase(r)==="upcoming"?"レース終了後に結果を表示します。":U.racePhase(r)==="unknown"?"締切時刻が不明のため、レース前か結果未取得かを判定できません。":"公式結果の反映を待っています。未取得の結果は不的中に含めません。"));
    if(result.status==="unsupported")return append(box,node("p","muted small",resultReason(r)));
    result.winning_combinations.forEach(t => box.append(combo(t)));
    if (result.status === "final") box.append(node("p", "muted", "100円当たり払戻 " + payoutSummary(result) + (r.scope === "synthetic" ? "（架空）" : "")));
    if (result.observed_at || result.confirmed_at) box.append(node("p", "muted small", "結果取得 " + stamp(result.observed_at || result.confirmed_at) + " JST"));
    if (U.refundSummary(result) !== "未取得") box.append(node("p", "muted", U.refundSummary(result)));
    return box;
  }
  function renderDetail() {
    const target = $("race-detail"), r = currentRace(); target.replaceChildren();
    if (!r) { target.append(empty("レースを選択してください", "全レースから保存原本を選ぶと詳細を確認できます。"), button("全レースを開く →", "primary", () => showPage("races", true))); return; }
    const p = prediction(r), layout = node("div", "detail-layout race-detail-focused"), main = node("div");
    const raceNavigation = sameVenueRaces(r);
    const panel = node("section", "panel detail-panel"), title = node("div", "detail-title");
    title.append(node("span", "sport-tag", sports[r.sport]), node("h2", "", raceName(r)), node("span", "tag scope-" + r.scope, scopeName(r.scope)));
    const reference=r.result?.cutoff_reference;
    panel.append(title, node("p", "detail-cutoff", "締切 " + time(reference?.result_schedule_cutoff_at || p?.cutoff_at || r.cutoff_at) + (reference?"（変更あり）":"") + (r.start_at ? " · 発走 " + time(r.start_at) : "")), node("p", "muted small", text(r.event_date_jst) + " JST"));
    const resultSummary=node("section","race-result-summary");resultSummary.setAttribute("aria-label","このレースの結果");
    resultSummary.append(append(node("div","section-heading"),node("h3","","結果"),outcomeBadge(r,p)),resultView(r,{showBadge:false}));
    const caption=node("p","muted small",resultSyncCaption());caption.dataset.resultSyncCaption="";
    resultSummary.append(append(node("div","result-refresh-row"),caption,resultRefreshButton()));panel.append(resultSummary);
    if(raceNavigation)panel.append(raceNavigation);panel.append(predictionPicker(r));
    const links=node("details","race-official-links");links.append(node("summary","","公式情報を開く"),officialRaceLinks(r));panel.append(links);
    const tabs = node("nav", "detail-tabs"); tabs.setAttribute("aria-label", "レース詳細タブ"); tabs.setAttribute("role", "tablist");
    for (const [key, label] of [["outlook", "レース展望"], ["participants", "出走表"], ["preview", "直前情報"], ["analysis", "データ分析"], ["history", "過去レース"]]) {
      const b = button(label, key === state.detailTab ? "active" : "", () => { state.detailTab = key; renderDetail(); $("detail-tab-" + key)?.focus(); }); b.id = "detail-tab-" + key; b.dataset.detailTab = key; b.setAttribute("role", "tab"); b.setAttribute("aria-selected", String(key === state.detailTab)); b.setAttribute("aria-controls", "detail-tab-content"); b.tabIndex = key === state.detailTab ? 0 : -1; tabs.append(b);
    }
    panel.append(tabs); const content = node("div"); content.id = "detail-tab-content"; content.setAttribute("role", "tabpanel"); content.setAttribute("aria-labelledby", "detail-tab-" + state.detailTab); content.tabIndex = 0;
    tabs.addEventListener("keydown", event => { const keys = ["outlook", "participants", "preview", "analysis", "history"], index = keys.indexOf(state.detailTab); let next; if (event.key === "ArrowRight") next = keys[(index + 1) % keys.length]; if (event.key === "ArrowLeft") next = keys[(index + keys.length - 1) % keys.length]; if (event.key === "Home") next = keys[0]; if (event.key === "End") next = keys.at(-1); if (next) { event.preventDefault(); state.detailTab = next; renderDetail(); $("detail-tab-" + next).focus(); } });
    if (state.detailTab === "outlook") content.append(forecastPanel(r, p), append(node("div", "section-heading member-heading"), node("h2", "", "出走メンバー"), node("span", "tag", knownParticipants(r).length ? knownParticipants(r).length + "名の読込値" : "出走表 未取得")), participantGrid(r, true));
    if (state.detailTab === "participants") {
      content.append(participantGrid(r, true));
      if (knownParticipants(r).length) content.append(table(["番号", "名前", "登録", "モーター", "平均ST", "展示"], knownParticipants(r).map(person => [participantNumber(person), person.name || "名前 未取得", participantRegistration(person), person.motor_no, person.average_st, person.display_time])));
    }
    if (state.detailTab === "preview") {
      const livePanel = liveBeforeinfoPanel(r);
      if (livePanel) content.append(livePanel);
      else {
      const people = knownParticipants(r), observationContext = boatObservationContext(r);
      content.append(node("h2", "", observationContext ? "保存予想原本の直前情報" : "直前情報"), node("p", "muted small", "出走情報の取得 " + stamp(r.observed_at || r.as_of) + " JST · 保存された項目を表示しています。"));
      if (people.some(person => [person.display_time, person.preview_st, person.preview_course, person.comment, person.last_comment].some(value => value !== undefined && value !== null && value !== ""))) content.append(previewCards(r, people));
      if (people.length) {
        const details = node("details", "preview-table");
        details.append(node("summary", "", "全出走者の直前情報を一覧表で見る"), table(["番号", "選手 / 登録", "展示タイム", "展示ST", "進入", "直前コメント"], people.map(person => [participantNumber(person), participantLabel(person, r), person.display_time, person.preview_st, person.preview_course, person.comment || person.last_comment])));
        content.append(details);
      }
      const weather = r.weather || r.weather_preview;
      if (weather && typeof weather === "object" && Object.keys(weather).length) content.append(weatherPanel(weather, "保存された気象・水面"));
      else content.append(empty(observationContext ? "保存予想原本の気象・直前情報は未取得です" : "気象・直前情報は未取得です", "保存原本に存在する項目だけを表示します。"));
      content.append(node("p", "muted small", "展示・試走の原本値は取得時点の記録です。予想への反映状況はモデル版と時点を確認してください。"));
      if (observationContext) content.append(observationContext);
      }
      const videoMeasurements = globalThis.RaceBoatVideoView?.createPanel(r);
      if (videoMeasurements) content.append(videoMeasurements);
    }
    if (state.detailTab === "analysis") {
      content.append(forecastPanel(r, p), node("h2", "", "同一レースの別モデル・時点"));
      const rows = predictions(r).map(other => [stageName(other), modelName(other), stamp(other.persisted_at), other.ordered_top8.length + "点", forecastStatus(r, other)]);
      content.append(rows.length ? table(["時点", "モデル / 版", "保存 JST", "保存点数", "証拠状態"], rows) : empty("比較予想は未取得です", "別モデル・朝版・展示後版が保存されるとここで比較できます。"));

    }
    if (state.detailTab === "history") {
      content.append(node("h2", "", r.private_cycle_view ? "保存された結果の観測" : "今回の公式結果と改訂履歴"), resultView(r));

      const revisions = r.result_revisions || [];
      content.append(revisions.length ? table(["改訂", "状態", "組合せ", "確認 JST", "100円払戻", "返還情報"], revisions.map(rev => [rev.revision_no, rev.status, rev.winning_combinations.map(t => t.join("−")).join(" / "), stamp(rev.confirmed_at), rev.payout_yen_per_100 == null ? "未取得" : yen(rev.payout_yen_per_100), U.refundSummary(rev)])) : node("p", "muted", "結果改訂履歴は未取得です。改訂がなかったことの証明ではありません。"));
      const past = r.past_races;
      content.append(node("h2", "", "過去レース"), Array.isArray(past) && past.length ? facts(past.map((value, i) => [String(i + 1), sourceText(value)])) : node("p", "muted", "過去レースの個別原本は未取得です。"));
    }
    panel.append(content);
    main.append(panel);
    layout.append(main); target.append(layout);
  }
  function refreshSelects() {
    const venues = venueEntries().map(entry => entry.venue);
    if (!venues.includes(state.venue)) state.venue = "";
    $("venue-filter").replaceChildren(new Option("すべての開催場", ""), ...venues.map(venue => new Option(venue, venue))); $("venue-filter").value = state.venue;
    const list = scoped(), selected = currentRace();
    if (!selected || !list.some(r => r.race_id === selected.race_id)) state.selectedId = list[0]?.race_id || "";
    $("ticket-race").replaceChildren(new Option("レースを選択", ""), ...list.map(r => new Option(raceName(r) + " · " + text(r.event_date_jst), r.race_id))); $("ticket-race").value = state.selectedId;
    refreshLaneSelects();
  }
  function refreshLaneSelects() {
    const max = maxNumber(currentRace());
    ["lane-first", "lane-second", "lane-third"].forEach((id, i) => { const select = $(id), previous = select.value; select.replaceChildren(...Array.from({length: max}, (_, index) => new Option(String(index + 1), String(index + 1)))); select.value = Number(previous) >= 1 && Number(previous) <= max ? previous : String(i + 1); });
  }
  function invalidateConfirmation(id) { state.confirmed.delete(id); $("purchase-ack").checked = false; }
  function renderTickets() {
    const r = currentRace(), id = r?.race_id || "", p = prediction(r), ts = ticketsFor(id), total = ts.reduce((s, t) => s + t.amount, 0), invalid = U.validateDraft(ts, state.raceBudget, state.maxPicks, maxNumber(r));
    $("ticket-race").value = id; $("race-budget").value = state.raceBudget; $("max-picks").value = state.maxPicks;
    $("copy-top8").disabled = !p || !r; $("allocation-source").textContent = p ? modelName(p) + " · " + stageName(p) + " · " + scopeName(r.scope) : "保存予想は未取得です。手動候補は予想原本と別に記録します。";
    $("copy-top8").textContent = p?.native_top8_available === false ? "保存" + p.ordered_top8.length + "点プランを候補へ" : "保存Top8を候補へ";
    const list = $("ticket-list"); list.replaceChildren();
    if (!ts.length) list.append(empty("買い目候補を追加しましょう", r ? (p?.native_top8_available === false ? "保存済みプラン" : "保存Top8") + "または異なる3つの番号と金額を入力できます。" : "対象レースの保存原本を先に読み込んでください。"));
    ts.forEach((t, index) => {
      const row = node("article", "ticket-row"), label = node("label", "ticket-edit", "金額（円）"), input = node("input", "ticket-amount");
      input.type = "number"; input.min = "100"; input.max = "10000000"; input.step = "100"; input.value = t.amount; input.setAttribute("aria-label", t.lanes.join("-") + " の候補金額");
      input.addEventListener("change", () => { const amount = Number(input.value), error = U.validateTicket(t.lanes, amount, maxNumber(r)); if (error) { $("ticket-message").textContent = error; input.value = t.amount; return; } t.amount = amount; invalidateConfirmation(id); $("ticket-message").textContent = "金額を変更しました。候補を再確認してください。"; renderAll(); });
      label.append(input);
      const del = button("削除", "text-button", () => { state.candidates = state.candidates.filter(other => other !== t); invalidateConfirmation(id); renderAll(); }); del.dataset.deleteTicket = "";
      row.append(node("span", "ticket-rank", String(index + 1)), combo(t.lanes), node("span", "tag", t.origin === "saved" ? "保存券からの候補" : "手入力"), label, del); list.append(row);
    });
    $("allocation-summary").replaceChildren(metric("合計候補額", yen(total), ts.length + "点 / 未購入", "▤"), metric("未使用予算", yen(state.raceBudget - total), "1レース予算との差額", "▣"), node("p", "muted small", "想定払戻・期待値・リスク：未検証"));
    $("confirm-candidates").disabled = !r || !!invalid;
    $("equal-allocate").disabled = !ts.length; $("clear-tickets").disabled = !ts.length;
    const confirmed = state.confirmed.has(id);
    $("confirmation-state").textContent = confirmed ? "候補確定済み · 実購入ではありません。編集すると確認を差し戻します。" : invalid && ts.length ? invalid : "編集中 · 候補確定は実購入ではありません。";
    $("reopen-candidates").hidden = !confirmed;
    $("record-purchase").disabled = !confirmed || !!invalid || !$("purchase-ack").checked || !r || r.scope === "synthetic";
    if (r?.scope === "synthetic") $("confirmation-state").textContent += " 合成テストを実購入として記録することはできません。";
    $("ticket-form").querySelector("button").disabled = !r;
  }
  function ownerAudit() {
    if (!ownerEncryptedTrusted || !dataset || !O) return null;
    if (ownerAuditCache?.source === dataset) return ownerAuditCache.result;
    const source = dataset.records.filter(r=>r.sport==="boat" && r.event_date_jst===O.DAY);
    const anchor = document.querySelector('meta[name="race-ai-saved-view-forecast-sha"]')?.content;
    const result = O.inspect(source,P,anchor);
    ownerAuditCache = {source:dataset,result};
    return result;
  }
  function ownerFormalRow(r) {
    const proof=ownerAudit();
    return proof?.verified===true && r?.sport==="boat" && r.event_date_jst===O.DAY &&
      r.result?.cutoff_reference?.basis==="RAW_OFFICIAL_SP_SAME_ROSTER_SAVED_BEFORE_BOTH";
  }
  function ownerFormalPanel(rows) {
    const box=$("boat-owner-formal-proof");
    if(!box)return null;
    const active=state.sport==="boat" && state.day===O?.DAY && rows.length===142 &&
      rows.every(r=>r.event_date_jst===O.DAY && r.sport==="boat");
    box.hidden=!active;
    if(!active)return null;
    const proof=ownerAudit();
    box.replaceChildren(node("h3","","2026年11月12日 · モデル別の正式照合"));
    if(!proof?.verified) {
      box.append(node("p","notice","保存した予想・公式結果と独立監査の一致を確認できないため、正式照合の表示は保留しています。"));
      return null;
    }
    box.append(node("p","","全142レース／2モデルの284予想を正式照合済み。従来は参考扱いだった締切差10レースも、元の予想保存時刻と公式SP結果の記録を検証して採用しました。"));
    box.append(table(["モデル","的中","不的中","照合済み","的中率"],
      Object.entries(proof.counts).map(([id,c])=>[
        id==="boat-observed-pairwise-factor-v1"?"Pairwise Factor":"Pairwise Start",
        String(c.hits),String(c.misses),String(c.forecasts)+" / 142",
        (100*c.hits/c.forecasts).toFixed(2)+"%"
      ])));
    box.append(node("p","muted small","購入実績ではなく保存Top8の事後検証です。元の暗号化原本と予想は変更していません。"));
    const link=node("a","source-link","独立照合の原本記録を確認");
    link.href=proof.evidence;link.target="_blank";link.rel="noopener noreferrer";
    box.append(link);
    return proof;
  }
  function outcomeBadge(r,p) {
    const status=P.compare(r,p).status;
    const phase=U.racePhase(r),displayStatus=status==="PENDING"&&phase!=="results"?(phase==="upcoming"?"UPCOMING":"TIME_UNKNOWN"):status;
    const labels={HIT:"的中",MISS:"不的中",PENDING:"結果待ち",UPCOMING:"レース前",TIME_UNKNOWN:"締切未確認",VOID:"中止・返還",REVIEW:"照合不可",NO_FORECAST:"未予想・原本未選択"};
    const note=(r.result?.cutoff_reference||r.result?.cutoff_reconciliation)&&status!=="VOID"?(ownerFormalRow(r)?"（正式照合・締切差確認済み）":"（参考照合・締切差あり）"):displayStatus==="UPCOMING"?"（締切 "+time(U.raceDeadline(r))+"）":displayStatus==="PENDING"?"（"+resultReason(r)+"）":"";
    return node("span","saved-outcome outcome-"+displayStatus.toLowerCase(),(r.scope==="synthetic"?"合成・":"")+labels[displayStatus]+note);
  }
  function resultReason(r) {
    const result=r.result,reference=result?.cutoff_reference;
    if(result?.cutoff_reconciliation){
      const proof=result.cutoff_reconciliation;
      return "原本締切 "+proof.original_cutoffs.map(stamp).join(" / ")+" JST。公式結果と登録出走者を照合。各予想が自身の締切と公式締切の前に保存済み。最大"+proof.maximum_offset_seconds+"秒の記録差を残した参考照合です。";
    }
    if(reference) {
      const clocks="原本締切 "+stamp(reference.original_cutoff_at)+" JST／結果ページ "+stamp(reference.result_schedule_cutoff_at)+" JST（差 "+reference.offset_seconds/60+"分）。";
      return clocks+(reference.basis==="RAW_OFFICIAL_CANCELLATION_SELECTED_RACE"?"公式の中止表示を照合。中止ページの予定時刻変更を保持しています。":"公式結果と6選手を照合。原本は両方の締切前に保存済み。"+(ownerFormalRow(r)?"所有者承認の正式照合に採用済みです。":"締切差を残した参考照合です。"));
    }
    if(result?.status==="unsupported") {
      const reason=r.result_observation_rejections?.find(e=>e.captured_at===result.observed_at)?.reason;
      const clocks=(r.saved_cutoff_variants||[]).map(Date.parse).filter(Number.isFinite);
      if(reason==="RESULT_CUTOFF_MISMATCH"&&clocks.length>1&&Math.max(...clocks)-Math.min(...clocks)>60000)return "予想原本の締切が一致しないため集計対象外（原本は保持）";
      return ({RESULT_CUTOFF_MISMATCH:"締切情報の不一致を確認中",RESULT_ROSTER_MISMATCH:"出走者情報の不一致を確認中",RESULT_IDENTITY_UNVERIFIED:"公式ページのレース識別を確認できません",RESULT_FINISH_ORDER_MISMATCH:"着順と払戻の整合性を確認中"})[reason]||"取得した結果の整合性を確認中";
    }
    if(result?.status==="void")return r.result_observations?.some(o=>o.captured_at===result.observed_at&&o.source_sha256===result.source_sha256&&o.data?.status==="no_contest"&&o.data?.confirmed_scope==="TRIFECTA_ONLY")?"3連単不成立・全額返還を照合済み":"公式の中止・返還表示を照合済み";
    if(result?.status==="final")return "取得結果と保存Top8を照合済み";
    if(U.racePhase(r)==="upcoming")return "レース前";
    if(U.racePhase(r)==="unknown")return "締切時刻を確認できていません";
    if(result?.status==="pending")return "取得した結果情報はまだ未確定です";
    return "公式結果を確認中";
  }
  function resultCombination(r) { return r.result?.winning_combinations?.map(t=>t.join("−")).join(" / ") || (r.result?.status==="void"?"中止・不成立":"未取得"); }
  function payoutSummary(result) {
    if (result?.status!=="final") return "未取得";
    const winners=result.winning_combinations||[];
    const values=winners.map(t=>{
      let amount;
      if (result.payouts!==undefined) {
        const matches=Array.isArray(result.payouts)?result.payouts.filter(p=>p?.bet_type==="trifecta"&&Array.isArray(p.combination)&&p.combination.join("-")===t.join("-")):[];
        if (matches.length===1) amount=matches[0].payout_per_100_yen;
      } else if (winners.length===1) amount=result.payout_yen_per_100;
      return (winners.length>1?t.join("−")+"：":"")+(Number.isSafeInteger(amount)&&amount>=0?yen(amount):"未取得・照合不可");
    });
    return values.join(" / ") || "未取得";
  }
  function savedResultsTable(rows,group) {
    const block=node("div"),mobile=node("div","result-list-mobile");
    const reason=r=>r.result?.cutoff_reference||r.result?.cutoff_reconciliation?(ownerFormalRow(r)?"締切変更・公式SP記録を照合済み（正式）":"締切変更を照合済み（参考）"):resultReason(r);
    const desktop=table(["レース","結果","予想の判定","100円払戻","結果取得 JST","照合状態・理由"],rows.map(r=>[button(raceName(r),"text-button",()=>openRace(r.race_id)),resultCombination(r),outcomeBadge(r,group?P.pick(r,group):null),payoutSummary(r.result),stamp(r.result?.observed_at),reason(r)]));desktop.classList.add("result-list-table");
    for(const r of rows){const card=node("article","result-mobile-card");card.append(append(node("div","section-heading"),button(raceName(r),"text-button",()=>openRace(r.race_id)),outcomeBadge(r,group?P.pick(r,group):null)));
      if(r.result?.winning_combinations?.length)r.result.winning_combinations.forEach(t=>card.append(combo(t)));else card.append(node("p","muted small",resultCombination(r)));
      if(r.result?.status==="final")card.append(node("p","result-price","100円当たり払戻 "+payoutSummary(r.result)));
      card.append(node("p","muted small",reason(r)+(r.result?.observed_at?" · 取得 "+time(r.result.observed_at)+" JST":"")));mobile.append(card);}
    block.append(mobile,desktop);return block;
  }
  function allocationView(entry) {
    const a=entry.allocation;if(!a)return "—";
    const baseStake=a.baseStake ?? a.tickets.length*100;
    const detail=node("details");detail.append(node("summary","",a.raceBudget===800?"保存"+a.tickets.length+"点各100円"+(a.held?" · 未配分 "+yen(a.held):""):"追加配分 "+yen(a.stake-baseStake)+" · 未配分 "+yen(a.held)));
    detail.append(node("p","muted small","配分判定時点 "+stamp(a.decisionAt)+" JST。支持モデルはIDごとに1種類と数えます。履歴安定は同じモデル・版の履歴あり／なし両方で支持された数。同点は組合せの数値順です。"));
    detail.append(table(["組合せ","配分額","支持モデル","履歴安定"],a.tickets.map(t=>[t.combination.join("−"),yen(t.amount),a.raceBudget===800?"—":t.families+"種類",a.raceBudget===800?"—":t.stableFamilies+"種類"])));
    if(a.held)detail.append(node("p","notice",a.raceBudget===800?"保存された全点の購入額とレース上限の差は未配分として残します。":"支持する異なるモデルが2種類に満たないため、追加"+yen(a.held)+"は未配分です。"));
    return detail;
  }
  function renderSavedResults(rows) {
    const approved=ownerFormalPanel(rows);
    const groups=M.modelGroups(rows).filter(activeModel),select=$("results-model");
    if (!groups.some(g=>g.key===state.resultGroupKey)) state.resultGroupKey=groups[0]?.key || "";
    select.replaceChildren(...groups.map(g=>new Option(stageName(g)+" · "+modelName(g)+(g.ambiguous_originals?" · 複数原本 "+g.ambiguous_originals+"レース":""),g.key)));select.value=state.resultGroupKey;select.disabled=!groups.length;
    $("simulation-budget").value=state.simulationBudget;
    $("simulation-budget").disabled=!groups.length;
    $("simulation-race-budget").value=String(state.simulationRaceBudget);$("simulation-race-budget").disabled=!groups.length;
    $("simulation-race-budget").querySelector('[value="800"]').textContent="800円 · 各100円（最大8点）";
    $("simulation-rule").textContent=state.simulationRaceBudget===1000?"各日、締切順に1レース上限1,000円を確保。保存予想の各点に100円（最大8点、3名出走の全6通りは600円）を配分し、残りをモデル間の支持・履歴安定性による参考指標で配分します。根拠不足の追加分は未配分として残し、後続へ配り直しません。払戻・返還は再投資しません。":"各日、締切順に1レース上限800円を確保し、保存予想の各点に100円（最大8点、3名出走の全6通りは600円）を配分します。未配分額は後続へ配り直しません。上限を確保できないレースは見送り、払戻・返還は再投資しません。予想が締切前に保存され、3連単を買えた場合の試算です。";
    $("simulation-allocation-note").hidden=state.simulationRaceBudget!==1000;
    const phase=U.raceLists(rows),closed=new Set(phase.results),resultRows=rows.filter(r=>closed.has(r)),group=groups.find(g=>g.key===state.resultGroupKey)||null,c=P.summarize(resultRows,group);
    $("saved-result-metrics").replaceChildren(metric("取得結果",c.available+"レース","保存された結果・中止"),metric("的中",c.hits+"レース","選択モデルと取得結果の一致"),metric("不的中",c.misses+"レース","選択モデルと取得結果の不一致"),metric("結果待ち",c.pending+"レース","締切後の結果未取得分 · レース前は除外"));
    $("saved-result-metrics").append(metric("レース前",phase.upcoming.length+"レース","締切前の対象 · 未予想を含む"));
    if(phase.unknown.length)$("saved-result-metrics").append(metric("締切未確認",phase.unknown.length+"レース","時刻を確認できない対象 · 結果待ちとは別集計"));
    $("saved-result-metrics").append(metric("保存Top8的中率",hitRate(c),c.hits+" / "+(c.hits+c.misses)+"レース（結果待ち・照合不可等を除外）"));
    $("saved-result-metrics").append(metric("中止・返還",c.void+"レース","不的中に含めません"),metric("照合保留",c.review+"レース","情報不一致などを確認中"));
    const latest=rows.map(r=>r.result?.observed_at).filter(v=>v&&Number.isFinite(Date.parse(v))).sort((a,b)=>Date.parse(a)-Date.parse(b)).at(-1);
    const references=rows.filter(r=>(r.result?.cutoff_reference||r.result?.cutoff_reconciliation)&&r.result.status==="final").length,cancelReferences=rows.filter(r=>r.result?.cutoff_reference&&r.result.status==="void").length;
    $("result-coverage").textContent="対象 "+rows.length+"レース · レース前 "+phase.upcoming.length+" · 結果対象 "+phase.results.length+" · 締切未確認 "+phase.unknown.length+" · 結果取得 "+c.available+" · 中止・返還 "+c.void+" · 未予想・照合不可 "+(c.noForecast+c.review)+" · 最終同期 "+stamp(dataset?.results_synced_at)+" JST · 最終結果取得 "+stamp(latest)+" JST · 締切差の参考照合 "+references+" · 中止ページの時刻変更 "+cancelReferences+(approved?.verified?"。11月12日分は元の時刻を維持したまま、10レースを正式照合へ採用済み。":"。原本の時刻は変更せず、独立監査で確認されるまでは公式成績への採用を保留します。");
    $("saved-results-table").replaceChildren(resultRows.length?savedResultsTable(resultRows,group):empty("結果を確認するレースはまだありません","締切前のレースは「レース → これからのレース」で確認できます。"));
    if (!groups.length) {
      $("simulation-metrics").replaceChildren(empty("試算する保存予想は未取得です","取得した結果は上の一覧に表示しています。"));
      for (const id of ["simulation-comparison","simulation-ledger"]) $(id).replaceChildren();return;
    }
    try {
      const scenarios=groups.flatMap(g=>[800,1000].map(raceBudget=>({group:g,sim:P.simulate(rows,g,state.simulationBudget,{raceBudget})})));
      const chosen=scenarios.find(s=>s.group.key===state.resultGroupKey&&s.sim.raceBudget===state.simulationRaceBudget),s=chosen.sim;
      const net=n=>n===null?"未確定":(n>0?"＋":"")+yen(n);
      $("simulation-metrics").replaceChildren(metric("予定購入額",yen(s.spent),s.bought+"レース · 上限"+yen(s.raceBudget)+"/レース · 実購入なし"),metric("未使用予算",yen(s.unspent),"1日 "+yen(s.budgetPerDay)+" × "+s.days.length+"日 · 追加未配分 "+yen(s.held)),metric("確認済み払戻",yen(s.payout),"返還 "+yen(s.refund)),metric("確定分の収支",net(s.settledNet),"購入額 "+yen(s.settledStake)+" の分だけ"),metric("未確定購入額",yen(s.pendingStake),"レース前・結果未取得・払戻未確認の予定分"),metric("全体の収支",net(s.net),"仮の残高 "+yen(s.balance)));
      $("simulation-metrics").append(metric("確定分の回収率",s.roi===null?"未確定":s.roi.toFixed(1)+"%","確認済み払戻・返還 ÷ 確定分購入額"),metric("収支確定の購入予定",s.settledCount+" / "+s.bought+"レース","日予算で選んだ対象のみ"),metric("購入予定分の的中率",hitRate(s.boughtComparison),s.boughtComparison.hits+" / "+(s.boughtComparison.hits+s.boughtComparison.misses)+"レース（結果待ち等を除外）"));
      $("simulation-comparison").replaceChildren(table(["モデル・履歴条件","1レース上限","購入予定分の的中 / 照合済","購入予定分の的中率","確定分回収率","予定購入額","払戻","返還","確定分収支","未確定額","全体収支"],scenarios.map(({group,sim:t})=>[modelName(group),yen(t.raceBudget)+(t.raceBudget===1000?" · 参考配分":" · 均等"),t.boughtComparison.hits+" / "+(t.boughtComparison.hits+t.boughtComparison.misses),hitRate(t.boughtComparison),t.roi===null?"未確定":t.roi.toFixed(1)+"%",yen(t.spent),yen(t.payout),yen(t.refund),net(t.settledNet),yen(t.pendingStake),net(t.net)])));
      const raceMap=new Map(rows.map(r=>[r.race_id,r]));
      const reasons={DAILY_BUDGET_LIMIT:"日予算上限で見送り",NO_UNAMBIGUOUS_SAVED_MODEL:"原本未取得、または同条件に複数原本",MODEL_IDENTITY_UNKNOWN:"モデル・版・時点が未取得",COMPLETE_TOP8_NOT_SAVED:"Top8が未完備",TRIFECTA_NOT_OFFERED:"3連単非発売",SAVE_CLOCK_UNKNOWN:"保存時刻未確認",NOT_SAVED_BEFORE_CUTOFF:"締切前保存を確認できません"};
      $("simulation-ledger").replaceChildren(table(["日付・レース","予定額","払戻","返還","収支","配分内訳・根拠","配分の状態"],s.rows.map(e=>[e.day+" · "+raceName(raceMap.get(e.race_id)),yen(e.stake),e.stake?net(e.payout):"—",e.stake?net(e.refund):"—",e.stake?net(e.net):"—",allocationView(e),e.reason?(reasons[e.reason]||e.reason):e.net===null?({upcoming:"レース前の予定",unknown:"締切未確認",results:"結果・払戻待ち"}[U.racePhase(raceMap.get(e.race_id))]):"取得結果で試算済み"])));
    } catch {
      for (const id of ["simulation-comparison","simulation-ledger"]) $(id).replaceChildren();
      $("simulation-metrics").replaceChildren(empty("試算を表示できません","金額・結果・保存原本の整合性を確認してください。"));
      $("simulation-message").textContent="試算できない金額または結果が含まれています。";
    }
  }
  function renderResults() {
    const rows = scoped(), sum = M.summary(displayRows(rows)), g = sum.overall;
    renderSavedResults(rows);
    $("result-metrics").replaceChildren(metric("全対象の台帳", g.ledger + "件", "取得範囲は独立確認が必要"), metric("公式・評価可能", g.evaluable + "件", "未予想も分母に含む"), metric("全対象 Hit@8_all", g.hit8 === null ? "未検証" : (g.hit8 * 100).toFixed(2) + "%", "的中 " + (g.hits ?? "未検証") + " / 評価可能 " + g.evaluable), metric("証拠不足・評価外", g.excluded + "件", "未確定・研究・合成を区別"));
    $("rate-limitations").textContent = g.identity_mixed ? "モデル・版・時点が混在するため、合算率を表示しません。研究ページのモデル別集計を確認してください。" : g.stage_mixed ? "朝版・展示後版が混在するため、合算率を表示しません。時点別の集計を確認してください。" : "保存された取込値の整合性に基づく集計です。原本の権限・署名・独立時刻はブラウザで認証していません。";
    $("result-sports").replaceChildren(table(["競技", "台帳", "評価可能", "的中", "Hit@8_all"], Object.entries(sum.bySport).map(([sport, stats]) => [sports[sport], stats.ledger, stats.evaluable, stats.hits ?? "未検証", stats.hit8 === null ? "未検証" : (stats.hit8 * 100).toFixed(2) + "%"])));
    $("result-stages").replaceChildren(table(["時点", "台帳", "評価可能", "的中", "Hit@8_all"], Object.entries(sum.byStage).map(([stage, stats]) => [stageName({stage}), stats.ledger, stats.evaluable, stats.hits ?? "未検証", stats.hit8 === null ? "未検証" : (stats.hit8 * 100).toFixed(2) + "%"])));
    const settled = rows.filter(r => r.result);
    const resultHeading = $("official-results").parentElement.querySelector("h2");
    resultHeading.textContent = rows.some(r => r.private_cycle_view) ? "レース別の結果観測（独立未検証）" : "レース別の公式結果";
    $("official-results").replaceChildren(...(settled.length ? settled.map(r => append(node("article", "official-result-row"), button(raceName(r), "text-button", () => openRace(r.race_id)), node("span", "tag scope-" + r.scope, scopeName(r.scope)), resultView(r))) : [empty("公式結果は未取得です", "予想と別時点の結果原本が読み込まれると表示されます。全レースの取得完了を意味しません。") ]));
    const imported = rows.filter(r => r.scope !== "synthetic" && r.actual_purchase?.confirmed === true);
    const importedTotal = imported.reduce((sum, r) => ({stake: sum.stake + r.actual_purchase.stake_yen, payout: sum.payout + r.actual_purchase.payout_yen, refund: sum.refund + r.actual_purchase.refund_yen}), {stake: 0, payout: 0, refund: 0});
    $("imported-purchases").replaceChildren(...(imported.length ? [node("p", "muted", "取込申告 " + imported.length + "件 · 支出 " + yen(importedTotal.stake) + " · 払戻 " + yen(importedTotal.payout) + " · 返還 " + yen(importedTotal.refund)), table(["レース", "区分", "購入申告", "払戻申告", "返還申告"], imported.map(r => [raceName(r), scopeName(r.scope), yen(r.actual_purchase.stake_yen), yen(r.actual_purchase.payout_yen), yen(r.actual_purchase.refund_yen)]))] : [node("p", "muted", "取込購入申告 0件 · 記録なし。合成テストは実購入に含めません。") ]));
    const manualRows = state.purchases.filter(p => A.inPeriod({event_date_jst: p.day}, state.allDates ? "all" : state.period === "week" ? "week" : "today", state.day) && p.sport === state.sport), manual = U.summarize(manualRows);
    $("manual-metrics").replaceChildren(metric("手動購入額", manual.purchases ? yen(manual.spent) : "記録なし", "この画面の購入申告のみ"), metric("手動払戻額", manual.settled ? yen(manual.returned) : "未集計", "確定 " + manual.settled + "点"), metric("手動回収率", manual.roi === null ? "未集計" : manual.roi.toFixed(1) + "%", "AI成績とは別の台帳"));
    const list = $("purchase-list"); list.replaceChildren();
    if (!manualRows.length) list.append(empty("手動の購入記録はありません", "候補確定だけでは購入記録は作成されません。"));
    manualRows.forEach(p => {
      const row = node("article", "purchase-row"), info = node("div"); info.append(node("strong", "", p.raceLabel), node("small", "muted", p.day + " · 購入申告 " + yen(p.amount)), combo(p.lanes)); row.append(info);
      if (p.payout === null) {
        const form = node("form", "settle-form"), label = node("label", "", "払戻額（円）"), input = node("input"); input.type = "number"; input.min = "0"; input.max = "1000000000"; input.step = "1"; input.required = true; input.setAttribute("aria-label", p.raceLabel + " " + p.lanes.join("-") + " の手動払戻額");
        label.append(input); const submit = node("button", "outline", "手動結果を記録"); submit.type = "submit"; form.append(label, submit);
        form.addEventListener("submit", e => { e.preventDefault(); const value = Number(input.value); if (!Number.isSafeInteger(value) || value < 0 || value > 1000000000) { $("result-message").textContent = "払戻額は0以上の整数で入力してください。"; return; } p.payout = value; renderAll(); $("result-message").textContent = "手動払戻を記録しました。公式予想成績には含みません。"; }); row.append(form);
      } else row.append(node("span", "tag", "手動払戻 " + yen(p.payout)));
      list.append(row);
    });
  }
  function renderResearchRaceAudit(rows) {
    const target = $("research-race-audit"), r = currentRace(); target.replaceChildren();
    if (!r || !rows.some(row => row.race_id === r.race_id)) {
      delete target.dataset.raceId;
      target.append(empty("この期間の検証情報はありません", "レースを読み込むと、保存情報と取得状況をここで確認できます。")); return;
    }
    target.dataset.raceId = r.race_id;
    const p = prediction(r), heading = node("div", "section-heading"), back = button("レース画面へ戻る", "text-button", () => openRace(r.race_id)); back.dataset.returnToRace = "";
    heading.append(node("h2", "", "レースごとの検証情報"), back);
    const controls = node("div", "research-audit-controls"), label = node("label", "", "検証するレース"), select = node("select"); select.id = "research-race-select";
    select.append(...rows.map(row => new Option(raceName(row) + " · " + row.event_date_jst, row.race_id))); select.value = r.race_id;
    select.addEventListener("change", () => { state.selectedId = select.value; refreshSelects(); renderAll(); $("research-race-select").focus(); });
    label.append(select); controls.append(label, predictionPicker(r, "research-prediction-select"));
    target.append(heading, node("p", "muted", raceName(r) + " · " + r.event_date_jst + " JST"), controls);
    const audit = node("section", "race-audit-details"), auditBody = node("div", "race-audit-body");
    audit.dataset.modelId = p?.model_id || ""; audit.dataset.predictionStage = p?.stage || "";
    auditBody.append(facts([["モデル", modelTechnicalName(p)], ["データ区分", r.scope], ...evidenceFields(r, p)]));
    if (liveBoatObservation(r)?.context) auditBody.append(boatObservationContext(r));
    const missing = [...new Set([...(r.missing_reasons || []), ...(p?.missing_reasons || []), ...(r.no_forecast_reason ? [r.no_forecast_reason] : [])])];
    if (missing.length) auditBody.append(node("h3", "", "保存情報の補足"), node("p", "audit-codes", missing.join(" / ")));
    auditBody.append(node("p", "muted small", "参考予想や取得した結果の照合は、公式な予想成績の証明とは別です。保存時刻や元の記録は変更しません。"));
    if(r.source_observation_view) auditBody.append(node("h2","","保存済みの出走ページ観測"),node("p","notice","出走ページの取得記録です。モデル入力・締切・予想・結果は未接続です。"),facts([["取得元URL",r.source_observation.source_url],["観測取得 JST",stamp(r.source_observation.observed_at)],["元ページSHA",r.source_observation.source_sha256],["原本JSON SHA",r.source_observation.original_json_sha256],["原本artifact ID",r.source_observation.artifact_id]]));
    if (r.dispatch_slots?.some(activeModel)) {
      const labels={NOT_APPLICABLE:"対象外",INPUT_MISSING:"入力未取得",TRAINED_ARTIFACT_MISSING:"学習物未取得",DEADLINE_PASSED:"締切超過・補完なし",RULE_FILTERED:"既存条件の対象外",UNCONNECTED_NATIVE_RUNTIME:"実行経路未接続",SOURCE_NOT_AUTHORIZED:"入力の利用条件未確認",INPUT_REJECTED:"入力不一致",GENERATED_UNATTESTED:"生成済み・外部保存未検証",ORIGINAL_REUSED:"元原本を再利用"};
      const slots=node("section");slots.id="dispatch-slot-status";slots.append(node("h2","","モデル別の入力・生成状態"),node("p","muted","取込データの状態です。生成済みの表示だけでは、締切前の外部保存や全レースの稼働を確認できません。"),table(["時点","モデル / 版","状態","理由"],r.dispatch_slots.filter(activeModel).map(slot=>[stageName(slot),modelName(slot),labels[slot.status],slot.projection_reason || slot.reason])));auditBody.append(slots);
    }
    if (r.private_cycle_view) {
      const observations = node("section"); observations.id = "result-observations";
      observations.append(node("h2", "", "取得観測履歴（公式改訂番号なし）"), node("p", "muted", "取得した原本の履歴です。観測順を公式な改訂番号や確定時刻として扱いません。"));
      if (r.result_observation_rejections?.length) observations.append(node("p","notice","照合不可の観測 " + r.result_observation_rejections.length + "件。取得原文は履歴に保持しています。"));
      if (r.result_observations?.length) r.result_observations.forEach(observation => {
        const details = node("article", "panel");details.append(node("h4", "", "観測取得 " + stamp(observation.captured_at) + " JST · " + text(observation.status)));
        const rejected=(r.result_observation_rejections||[]).find(value=>Date.parse(value.captured_at)===Date.parse(observation.captured_at) && (value.source_sha256??null)===(observation.source_sha256??null));
        if(rejected) details.append(node("p","notice","照合不可：" + ({RESULT_CUTOFF_MISMATCH:"予想原本と結果観測で締切が異なります",RESULT_AMBIGUOUS_FORECAST_CUTOFF:"予想原本間で締切が異なります",RESULT_AMBIGUOUS_SCHEDULE_CUTOFF:"台帳間で締切が異なります",RESULT_ROSTER_MISMATCH:"出走者の記録が一致しません",RESULT_FINISH_ORDER_MISMATCH:"着順の記録が一致しません",RESULT_IDENTITY_UNVERIFIED:"結果本文のレースを確認できません"}[rejected.reason]||rejected.reason)));
        details.append(facts([["レースID",observation.race_id],["観測取得 JST",stamp(observation.captured_at)],["観測SHA",observation.source_sha256]]));
        const raw=node("pre","raw-observation");raw.dataset.observationRaw="";raw.textContent=JSON.stringify(observation);
        details.append(node("h3","","保存観測の原文"),raw);observations.append(details);
      }); else observations.append(node("p", "muted", "結果の取得観測原本は未取得です。"));
      auditBody.append(observations);
    }
    audit.append(auditBody); target.append(audit);
  }
  function renderResearch() {
    const rows = scoped(), allPredictions = rows.flatMap(predictions), groups = M.modelGroups(rows).filter(activeModel);
    if (state.page === "research") renderResearchRaceAudit(rows);
    $("research-metrics").replaceChildren(metric("対象レース", rows.length + "件", "選択した競技・期間"), metric("保存予想", allPredictions.length + "件", "基準・比較モデルを含む"), metric("モデル・時点の版", groups.length + "組", "再予想・再採点なし"), metric("原本の独立監査", "未完了", "取込値の表示"));
    $("model-comparison").replaceChildren(groups.length ? table(["モデル / 版", "区分", "時点", "予想 / 台帳", "評価可能", "Hit@8_all", "比較条件"], groups.map(g => [modelName(g), scopeName(g.scope), stageName(g), g.issued + " / " + g.ledger, g.evaluable, g.hit8 === null ? "未検証" : (g.hit8 * 100).toFixed(2) + "%", g.comparison])) : empty("モデル原本は未取得です", "保存済み予想とモデル版を読み込むと表示します。"));
    renderModelCoverage(rows);
    const content = $("research-content"); content.replaceChildren();
    if (!dataset) { content.append(empty("データは未取得です", "保存JSONを端末内で読み込んでください。", true)); return; }
    content.append(facts([["データ区分", dataset.dataset_status], ["読込全件", races().length + "件"], ["選択競技・期間", rows.length + "件"], ["出典", sourceText(dataset.sources || dataset.provenance_urls || [])], ["取得範囲", "全開催・全レースの捕捉は未検証"], ["再計算", "表示操作による予想・結果の書換はありません"]]));
    content.append(table(["レース", "区分", "モデル・時点", "取得時刻 JST", "元SHA", "未取得・理由"], rows.slice(0, 200).map(r => [raceName(r), scopeName(r.scope), modelName(prediction(r)) + " / " + stageName(prediction(r)), stamp(r.observed_at || r.as_of), r.source_sha || r.source_sha256, (r.missing_reasons || []).join(" / ") || r.no_forecast_reason || "追加情報なし"])));
  }
  function renderModelCoverage(rows) {
    const coverage = U.modelCoverage(displayRows(rows), C.models, {sport: state.sport});
    $("all-model-coverage-summary").textContent = "登録 " + coverage.models.length + "モデル · " + sports[state.sport] + "に適用 " + coverage.applicable_models + " / 対象外 " + coverage.not_applicable_models + " · 対象台帳 " + coverage.target_races + "レース（保存予想なし " + rows.filter(r => !predictions(r).length).length + "レースを含む）";
    const values = coverage.models.map(spec => {
      const name = append(node("div", "catalog-model-name"), node("strong", "", spec.model_id), node("small", "muted", "適用競技：" + spec.applicable_sports.map(sport => sports[sport]).join(" / ")));
      const stageCounts = node("div", "catalog-lines");
      if (spec.applicable) {
        for (const stage of coverage.display_stages) stageCounts.append(node("p", "", stageName({stage}) + " " + spec.stages[stage].saved_races + " / " + spec.stages[stage].target_races + "（未予想 " + spec.stages[stage].missing_races + "）"));
        stageCounts.append(node("p", "muted small", "時点不明の保存 " + spec.stages.UNKNOWN.saved_races + "件"));
      } else stageCounts.append(node("p", "muted", "対象外 · 分母に含めません"));
      const versions = node("div", "catalog-lines");
      if (spec.versions.length) spec.versions.forEach(v => versions.append(node("p", "", scopeName(v.scope) + " · " + stageName(v) + " · " + text(v.model_version) + " · " + v.saved_races + "レース")));
      else versions.append(node("p", "muted", "保存版 未取得"));
      const status = node("div", "catalog-status");
      status.append(node("strong", "", !spec.applicable ? "対象外" : !spec.saved_races ? "未予想／入力未接続" : spec.missing_races || coverage.display_stages.some(stage=>spec.stages[stage].missing_races) ? "保存原本あり／一部未予想" : "取込対象の保存原本あり"));
      if (spec.applicable) status.append(node("p", "muted small", spec.saved_races ? "原本の存在数です。稼働・入力接続の完了は未実証です。" : coverage.target_races ? "保存原本なし。必要入力の接続・実行状態は未確認です。" : "レース台帳・保存原本とも未取得です。"));
      if (spec.inapplicable_saved_races) status.append(node("p", "catalog-mismatch", "対象外競技の保存原本 " + spec.inapplicable_saved_races + "レース。適用実績に含めません。"));
      status.append(node("p", "muted small", "必要入力：" + spec.required_input_ja));
      return [name, node("span", "tag " + (spec.applicable ? "scope-research" : ""), spec.applicable ? "適用対象" : "対象外"), spec.applicable ? spec.saved_races + " / " + spec.target_races + "レース（未予想 " + spec.missing_races + "）" : "対象外 · 0レース", stageCounts, versions, status];
    });
    const coverageTable = table(["既存モデル", "適用", "保存済み / 対象台帳", "予想時点ごとの存在数", "保存版・区分", "接続状態・必要入力"], values);
    coverageTable.classList.add("catalog-coverage-table");
    coverageTable.querySelectorAll("tbody tr").forEach((tr, index) => { const spec = coverage.models[index]; tr.dataset.modelId = spec.model_id; tr.dataset.applicable = String(spec.applicable); tr.dataset.state = spec.state; });
    $("all-model-coverage").replaceChildren(coverageTable);
    $("additional-models-note").textContent = coverage.additional_model_ids.length ? "カタログ外の保存モデルID：" + coverage.additional_model_ids.join(" / ") + "。下の保存原本比較で個別に確認できます。" : "モデルIDのない原本を既存モデルへ推測で割り当てません。モデル版・区分・時点は下の保存原本比較で確認できます。";
  }
  function renderPortraitGallery() {
    const portraits = globalThis.RaceRacerPortraits;
    if (!portraits || $("racer-portrait-gallery")) return;
    const panel = node("section", "panel portrait-panel"); panel.id = "racer-portrait-gallery";
    const coverage = portraits.coverage;
    panel.append(node("h2", "", "選手イラスト"), node("p", "muted", "公式プロフィール写真を参考にしたイラストです。対象" + coverage.total + "名／" + (portraits.offline ? "このファイルに収録" : "作成済み") + portraits.all.length + "名。未作成の選手は「イラスト準備中」と表示します。"));
    const details = node("details"), grid = node("div", "racer-grid portrait-gallery");
    details.append(node("summary", "", "対応選手と参照元を確認する"));
    const label = node("label", "portrait-search-label", "氏名・登録番号で検索"), search = node("input", "portrait-search");
    search.type = "search"; search.maxLength = 80; search.id = "portrait-search"; label.htmlFor = search.id;
    const count = node("p", "muted"), more = button("さらに表示", "outline", () => { shown += 30; render(); });
    let shown = 30;
    function render() {
      const query = search.value.replace(/\s+/g, "");
      const matches = portraits.all.filter(p => !query || p.registration.includes(query) || p.aliases.some(name => name.replace(/\s+/g, "").includes(query)));
      grid.replaceChildren();
      for (const entry of matches.slice(0, shown)) {
        const card = participantCard({registration_no:entry.registration, name:entry.name}, {sport:"boat", scope:"research"}, false, false);
        const link = node("a", "text-link", "公式プロフィール");
        link.href = entry.sourceUrl; link.target = "_blank"; link.rel = "noopener noreferrer";
        card.append(link); grid.append(card);
      }
      count.textContent = matches.length ? Math.min(shown, matches.length) + "名を表示／該当" + matches.length + "名" : "該当する作成済みイラストはありません。";
      more.hidden = shown >= matches.length;
    }
    search.addEventListener("input", () => { shown = 30; render(); });
    details.append(label, search, count, grid, more); render(); panel.append(details);
    document.querySelector("#page-settings .two-column > div").append(panel);
  }
  function renderMeta() {
    renderPortraitGallery();
    document.querySelectorAll("[data-sport]").forEach(b => { const active = b.dataset.sport === state.sport; b.classList.toggle("active", active); b.setAttribute("aria-pressed", String(active)); });
    const historyActive=savedHistory?.active&&savedHistory.version===importVersion;
    $("period-all").disabled=Boolean(historyActive);
    for(const option of $("period-filter").options)option.disabled=Boolean(historyActive&&option.value!=="day");
    $("selected-date").value = state.day; $("period-all").checked = state.allDates; $("period-filter").value = state.allDates ? "all" : state.period; $("display-day").textContent = state.allDates ? "読み込んだ全期間 / " + sports[state.sport] : (state.period === "week" ? "週の基準 " : "") + state.day + " JST / " + sports[state.sport];
    $("daily-budget").value = state.budget; $("settings-sport").value = state.sport;
    const kind = dataset?.dataset_status;
    $("data-banner").classList.toggle("synthetic-banner", kind === "SYNTHETIC_ONLY");
    $("data-banner").hidden=kind==="REAL_REPORTED";
    $("data-banner").textContent = kind === "SYNTHETIC_ONLY" ? "合成テスト専用 · レース・予想・結果・払戻は架空です。実績には含みません。" : kind === "REAL_REPORTED" ? "読込原本の申告値 · 出典・外部時刻の独立照合は別途必要です。" : dataset ? "研究・監査データ · 実績の証明には使用しません。" : savedMessages[generation.savedState]?.[0] || "レース情報は未取得です。会場・日付を選んで確認できます。";
    $("source-state").textContent = kind === "SYNTHETIC_ONLY" ? "合成テスト表示中" : dataset ? "保存データを表示中" : generation.savedState === "LINK_REQUIRED" ? "閲覧用リンク待ち" : "データ未取得";
    const dates = [...new Set(races().map(r => r.event_date_jst).filter(Boolean))].sort();
    $("source-date").textContent = "対象日：" + (dates.length ? dates[0] + (dates.length > 1 ? "〜" + dates.at(-1) : "") : "未取得");
    $("source-time").textContent = "取得時刻：" + (dataset ? "各レースの保存原本を参照" : "未取得");
    $("clear-data").disabled = !dataset;
    renderGeneration();
  }
  function renderAll() { renderMeta(); renderHome(); renderRaces(); renderTickets(); renderResults(); renderResearch(); if (state.page === "detail") renderDetail();syncResultRefreshUI(); }
  function adoptDataset(parsed) {
    ownerEncryptedTrusted=false;ownerAuditCache=null;
    refreshSavedResults=null;resultCheck.busy=false;resultCheck.failed=false;
    generation.ownsDisplay = false;generation.suppressed = true;generation.pausedForDrafts = false;generation.pausedForEditing = false;
    dataset = parsed; state.selectedId = ""; state.predictionKeys = {}; state.modelOriginals = {}; state.candidates = []; state.confirmed.clear(); state.venue = ""; state.visible = 60; $("purchase-ack").checked = false;
    refreshSelects(); renderAll();
  }
  function selectedDelivery() { return generation.delivery[state.sport]?.[$("forecast-stage").value] || null; }
  function renderDelivery() {
    const delivery = automaticMode() ? selectedDelivery() : null;
    $("generation-delivery").hidden = delivery === null;
    if (!delivery) return;
    const labels = {RUNNING:"予想を準備しています",SOURCE_WAIT:"入力待ち（必要な情報は未取得・未完備です）",SCHEDULE_WAIT:delivery.reason === "NEXT_DAY_PROGRAM_NOT_PUBLISHED" ? "日程の公表待ち" : "日程の取得待ち",WAITING_TARGET:"保存目標の時刻を待っています",LATE_INPUT:Date.parse(delivery.source_captured_at) > Date.parse(delivery.target_due_at) ? "入力取得が目標時刻後です" : "入力待ち（保存目標の時刻を過ぎています）",SAVED:"保存済みの予想があります",STOPPED:"予想の準備は停止しています",UNAVAILABLE:"適格な実入力は未接続です",NOT_SAVED:"予想の保存待ちです",UNKNOWN:"保存時刻の状態は未確認です"};
    const stale = generation.connectionUncertain;
    $("delivery-state").textContent = (stale ? "前回の状態：" : "") + labels[delivery.state];
    $("delivery-next").textContent = delivery.next_cutoff_at ? "次の締切 " + stamp(delivery.next_cutoff_at) + " JST · 保存目標 " + time(delivery.target_open_at) + "〜" + time(delivery.target_due_at) + " JST" : "次の締切：未取得";
    const recorded = {ON_TIME:"保存記録は目標内です",EARLY:"保存記録は目標時刻より前です",LATE:Date.parse(delivery.saved_at) >= Date.parse(delivery.next_cutoff_at) ? "締切後の保存記録です" : "保存記録は目標時刻後です",UNKNOWN:"保存時刻の評価は未確認です"};
    $("delivery-record").textContent = (stale ? "前回の保存記録：" : "") + recorded[delivery.window_status] + (delivery.saved_at ? " · 保存 " + stamp(delivery.saved_at) + " JST" : " · 保存完了の時刻は未確認です");
  }
  function renderGeneration() {
    const operation = $("operation-details");
    if (generation.api && operation.dataset.connected !== "true") {
      document.querySelector(".view-controls").before(operation); operation.open = true; operation.dataset.connected = "true";
    }
    if (savedViewConfigured) {
      $("forecast-generate").hidden = true;$("forecast-follow-latest").hidden = true;$("forecast-stage").disabled = true;
      $("generation-title").textContent = "保存済み予想";
      $("generation-description").textContent = "保存原本の買い目と結果を表示しています。モデル・履歴あり／なしをレース詳細で選べます。";
      $("generation-message").textContent = generation.message || "保存原本を読み込んでいます。";
      return;
    }
    const stage = $("forecast-stage").value;
    const automatic = automaticMode();
    const available = generation.ready && generation.capabilities[state.sport]?.[stage] === true;
    $("forecast-stage").disabled = !generation.ready || generation.busy;
    $("forecast-generate").disabled = automatic || !available || generation.busy;
    $("forecast-generate").hidden = automatic;
    $("forecast-follow-latest").hidden = !automatic || generation.ownsDisplay && !generation.suppressed;
    $("forecast-follow-latest").disabled = generation.latestBusy;
    $("generation-title").textContent = automatic ? "自動予想" : "当日の予想を生成";
    $("generation-description").textContent = automatic ? "サーバーの巡回で予想を生成・私有保存し、最新の保存原本を自動表示します。" : "選択した競技の実入力で、既存モデルを実行・私有保存します。";
    $("forecast-generate").textContent = generation.busy ? "生成・保存しています…" : "新しい予想を生成";
    $("forecast-generation").setAttribute("aria-busy", String(generation.busy || automatic && ["STARTING","RUNNING"].includes(generation.auto.state)));
    if (automatic) {
      const labels = {NOT_STARTED:"自動予想の開始を待っています",STARTING:"自動予想を準備しています",RUNNING:"自動予想を実行中です",WAITING:"次の自動巡回を待っています",HANDOFF_WAIT:"次の自動実行へ引き継いでいます",SOURCE_WAIT:"取得元の再開を待っています",REVIEW_WAIT:"取得条件・保存原本の確認を待っています",PAUSED:"自動予想は停止しています",ALREADY_RUNNING:"別の自動巡回が実行中です",STOPPING:"自動予想を停止しています",STOPPED:"自動予想は停止しました",HALTED:"自動予想は停止しました",FAILED:"自動予想を停止しました"};
      const reasons = {SOURCE_REQUEST_LIMIT:"以前の取得回数上限で停止した状態を保持しています",SOURCE_BUDGET_EXHAUSTED:"以前の取得回数上限で停止した状態を保持しています",SESSION_LIMIT_REACHED:"以前の巡回上限による停止記録を保持しています",ROUND_LIMIT_REACHED:"以前の巡回上限による停止記録を保持しています",BOUNDED_SESSION_END:"以前の65分上限による停止記録を保持しています",MAX_ROUNDS_REACHED:"以前の24回上限による停止記録を保持しています",DAY_BOUNDARY:"以前の日付境界による停止記録を保持しています",DATE_BOUNDARY:"以前の日付境界による停止記録を保持しています",DAY_CHANGED:"以前の日付境界による停止記録を保持しています",CLOCK_REVERSED:"時刻の逆行を検知して停止しました",STOP_REQUESTED:"停止が指示されました",NO_FUTURE_RACES:"締切前の対象レースがありません",SOURCE_HTTP_4XX_STOP:"取得元の拒否応答で停止しました",SOURCE_IDENTITY_OR_PARSE_STOP:"取得した出典の照合に失敗して停止しました",AUTOMATIC_SOURCE_STATUS_REJECTED:"出典の取得状態を確認できず停止しました",AUTOMATIC_GENERATION_REJECTED:"予想と保存の条件を確認できず停止しました",AUTOMATIC_STATE_UNAVAILABLE:"巡回の保存状態を確認できず停止しました",ANOTHER_AUTOMATIC_WRITER_ACTIVE:"別の自動巡回が実行中のため開始していません",INTERRUPTED_ROUND_REQUIRES_REVIEW:"中断した巡回の状態確認が必要です"};
      const info = [generation.connectionUncertain ? "自動運転の状態を確認できません。前の表示を保持しています" : labels[generation.auto.state] || "自動運転の状態を確認しています"];
      if (!generation.connectionUncertain && generation.auto.continuous === true && ["STARTING","RUNNING","WAITING","HANDOFF_WAIT","SOURCE_WAIT"].includes(generation.auto.state)) info.unshift("継続運転");
      if (generation.auto.halted_reason) info.push(reasons[generation.auto.halted_reason] || (generation.auto.state === "REVIEW_WAIT" ? "取得条件と保存済み原本の確認が必要です" : "停止条件に達しました。取得元と保存の状態を確認してください"));
      if (!generation.connectionUncertain && generation.auto.next_run_at && ["STARTING","RUNNING","WAITING","HANDOFF_WAIT","SOURCE_WAIT"].includes(generation.auto.state)) info.push((selectedDelivery()?.state === "SOURCE_WAIT" ? "次の入力確認 " : "次回 ") + stamp(generation.auto.next_run_at) + " JST");
      if (Number.isSafeInteger(generation.auto.round_no) && generation.auto.round_no >= 0) info.push("巡回 " + generation.auto.round_no + "回");
      if (Object.prototype.hasOwnProperty.call(generation.auto,"source_limit") && generation.auto.source_limit === null) info.push("取得回数上限なし");
      if (Number.isSafeInteger(generation.auto.requests_used) && generation.auto.requests_used >= 0) info.push("取得 " + generation.auto.requests_used + "回");
      if (!available) info.push(sports[state.sport] + "の適格な実入力は未接続です");
      if (generation.autoMessage) info.push(generation.autoMessage);
      $("generation-message").textContent = info.join(" · ");
      renderDelivery();
      return;
    }
    renderDelivery();
    $("generation-message").textContent = generation.busy ? "実入力を確認し、締切前の予想を生成・保存しています。" :
      generation.ready && !available ? sports[state.sport] + "の" + (stage === "P1" ? "展示後" : "朝版") + "実入力はまだ接続されていません。保存原本の読み込みは使えます。" :
      generation.message || (generation.ready ? generation.day + " JST のレースが対象です。生成した予想に表示を切り替え、編集中の購入候補はクリアします。" : "ローカル予想サーバーで起動すると生成できます。保存JSONの読み込みはそのまま使えます。");
  }
  function generationError(code) {
    return ({LOCAL_REQUEST_REQUIRED:"この端末の予想画面から操作してください。", INVALID_REQUEST:"競技と予想時点を選び直してください。",
      REQUEST_TOO_LARGE:"リクエストが上限を超えています。", JSON_REQUIRED:"JSON形式で操作してください。", NOT_FOUND:"この画面または取得経路はありません。", METHOD_NOT_ALLOWED:"予想生成ボタンから操作してください。",
      SOURCE_PERMISSION_REQUIRED:"取得元の解析・私有保存の利用条件を確認してください。", SOURCE_TIMEOUT:"入力の取得が時間内に完了しませんでした。取得状態を確認してください。",
      AUTOMATIC_MANAGED:"予想は自動巡回で管理しています。生成ボタンの操作は不要です。",
      GENERATION_INPUT_UNAVAILABLE:"対象レース・予想時点・必要な実入力を確認してください。", PRIVATE_STORAGE_UNAVAILABLE:"私有保存先または入力の取得経路を確認してください。",
      GENERATION_UNAVAILABLE:"予想生成を完了できませんでした。入力と保存の状態を確認してください。"})[code] || "予想の生成・保存を完了できませんでした。接続と入力状況を確認してください。";
  }
  function generationDay(value) {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const epoch = Date.parse(value + "T00:00:00Z");
    return Number.isFinite(epoch) && new Date(epoch).toISOString().slice(0,10) === value;
  }
  function automaticMode() { return generation.auto?.enabled === true; }
  function deliveryStatus(raw) {
    if (raw == null) return {};
    if (typeof raw !== "object" || Array.isArray(raw)) throw new Error("delivery status");
    const states = ["RUNNING","SOURCE_WAIT","SCHEDULE_WAIT","WAITING_TARGET","LATE_INPUT","SAVED","STOPPED","UNAVAILABLE","NOT_SAVED","UNKNOWN"];
    const timestamp = value => typeof value === "string" && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(value) && generationDay(value.slice(0,10)) && Number.isFinite(Date.parse(value));
    const result = {};
    for (const [sport,stages] of Object.entries(raw)) {
      if (!Object.hasOwn(sports,sport) || !stages || typeof stages !== "object" || Array.isArray(stages)) throw new Error("delivery sport");
      result[sport] = {};
      for (const [stage,value] of Object.entries(stages)) {
        if (!["P0","P1"].includes(stage) || !value || typeof value !== "object" || Array.isArray(value) || !states.includes(value.state) || !["ON_TIME","EARLY","LATE","UNKNOWN"].includes(value.window_status) || !(value.reason === null || typeof value.reason === "string" && /^[A-Z][A-Z0-9_]{0,95}$/.test(value.reason)) || !timestamp(value.assessed_at) || value.visible_at !== null) throw new Error("delivery fields");
        const fields = ["next_cutoff_at","target_open_at","target_due_at","source_captured_at","generated_at","saved_at"];
        if (fields.some(key=>value[key] !== null && !timestamp(value[key]))) throw new Error("delivery timestamp");
        const at = Date.parse(value.assessed_at), cutoff = Date.parse(value.next_cutoff_at), open = Date.parse(value.target_open_at), due = Date.parse(value.target_due_at);
        if (value.next_cutoff_at === null ? value.target_open_at !== null || value.target_due_at !== null : open !== cutoff-900000 || due !== cutoff-600000) throw new Error("delivery target");
        if (["source_captured_at","generated_at","saved_at"].some(key=>value[key] !== null && Date.parse(value[key]) > at)) throw new Error("future delivery evidence");
        if (value.window_status !== "UNKNOWN") {
          if (["source_captured_at","generated_at","saved_at","next_cutoff_at"].some(key=>value[key] === null)) throw new Error("missing delivery evidence");
          const source = Date.parse(value.source_captured_at), generated = Date.parse(value.generated_at), saved = Date.parse(value.saved_at);
          if (!(source <= generated && generated <= saved && saved <= at) || value.state !== "SAVED" || value.window_status !== (saved < open ? "EARLY" : saved <= due ? "ON_TIME" : "LATE")) throw new Error("delivery evidence order");
        }
        result[sport][stage] = Object.fromEntries(["state","reason","assessed_at","visible_at","window_status",...fields].map(key=>[key,value[key]]));
      }
    }
    return result;
  }
  function applyGenerationStatus(status) {
    if (typeof status.nonce !== "string" || !status.nonce || status.nonce.length > 256 || !status.capabilities || typeof status.capabilities !== "object" || !generationDay(status.day_jst)) throw new Error("status");
    if (status.auto != null && (typeof status.auto !== "object" || typeof status.auto.enabled !== "boolean" || status.auto.enabled && typeof status.auto.state !== "string")) throw new Error("automatic status");
    if (status.auto?.continuous != null && typeof status.auto.continuous !== "boolean") throw new Error("automatic policy");
    const delivery = deliveryStatus(status.delivery);
    generation.nonce = status.nonce;generation.capabilities = status.capabilities;generation.day = status.day_jst;generation.ready = true;
    generation.auto = status.auto || null;generation.delivery = delivery;generation.revisions = status.latest_revisions || {};generation.connectionUncertain = false;
  }
  function scheduleAutomaticPoll() {
    if (generation.timer !== null) clearTimeout(generation.timer);
    const delivery = selectedDelivery();
    const near = delivery && Date.parse(delivery.assessed_at) >= Date.parse(delivery.target_open_at) && Date.parse(delivery.assessed_at) < Date.parse(delivery.next_cutoff_at);
    const active = generation.auto?.continuous === true && (["STARTING","RUNNING"].includes(generation.auto.state) || near && ["RUNNING","SOURCE_WAIT","WAITING_TARGET","LATE_INPUT","NOT_SAVED"].includes(delivery.state));
    generation.timer = automaticMode() ? setTimeout(pollAutomaticStatus,active ? 60000 : 180000) : null;
  }
  async function pollAutomaticStatus() {
    if (!automaticMode() || generation.statusBusy) return;
    generation.statusBusy = true;
    try {
      const response = await fetch(generation.api + "/status", {credentials:"same-origin",cache:"no-store"});
      if (!response.ok) throw new Error("status");
      applyGenerationStatus(await response.json());
      if (automaticMode()) await loadAutomaticLatest(false);
    } catch { generation.connectionUncertain = true; }
    finally { generation.statusBusy = false;renderGeneration();scheduleAutomaticPoll(); }
  }
  function automaticView(result, sport, stage, expectedDay) {
    if (!result || result.available !== true || typeof result.revision !== "string" || !result.revision || result.revision.length > 256 || !generationDay(result.day_jst) || result.day_jst !== expectedDay) throw new Error("automatic response");
    const parsed = M.parse(result.view), summary = result.summary;
    const count = value => Number.isSafeInteger(value) && value >= 0;
    const unknownCoverage = summary?.coverage_known === false;
    const validCounts = summary && count(summary.generated) && count(summary.reused) && (unknownCoverage ? summary.missing === null && summary.generated === 0 && count(summary.races) && summary.races === parsed.records.length && summary.reused === parsed.records.reduce((sum,row)=>sum+storedPredictions(row).length,0) : count(summary.missing));
    if (parsed.event_date_jst != null && parsed.event_date_jst !== result.day_jst || parsed.records.some(row=>row.event_date_jst !== result.day_jst || row.sport !== sport || row.stage != null && row.stage !== stage || row.scheduled_stages?.some(value=>value !== stage) || (row.dispatch_slots || []).some(slot=>slot.stage !== stage) || storedPredictions(row).some(p=>p.stage !== stage)) || !validCounts) throw new Error("automatic response");
    return parsed;
  }
  function activeCandidateEdit() { return document.activeElement?.matches("#ticket-list .ticket-amount, #race-budget") === true; }
  function adoptAutomaticDataset(parsed, result, explicitFollow) {
    if (dataset && !generation.ownsDisplay && !explicitFollow || generation.suppressed && !generation.pausedForDrafts && !generation.pausedForEditing && !explicitFollow) {
      generation.autoMessage = "手動で選んだ原本の表示を保持しています。最新の自動予想は保存されています。";return true;
    }
    if (activeCandidateEdit()) {
      generation.pausedForEditing = true;generation.suppressed = true;
      generation.autoMessage = "金額の入力中のため、現在の表示を保持しています。入力が終わると保存原本を再確認します。";return false;
    }
    const identifiers = new Set(parsed.records.map(row=>row.race_id));
    if (state.candidates.length && state.day !== result.day_jst || state.candidates.some(ticket=>!identifiers.has(ticket.raceId))) {
      generation.pausedForDrafts = true;generation.suppressed = true;
      generation.autoMessage = "編集中の購入候補があるため、現在の表示を保持しています。候補を整理してから自動予想を表示してください。";return false;
    }
    const chosen = new Map(races().map(row=>[row.race_id,prediction(row)]));
    const first = !dataset;
    ownerEncryptedTrusted=false;ownerAuditCache=null;dataset = parsed;generation.ownsDisplay = true;generation.suppressed = false;generation.pausedForDrafts = false;generation.pausedForEditing = false;
    state.predictionKeys = {};
    for (const row of parsed.records) {
      const old = chosen.get(row.race_id), list = predictions(row);
      const index = old ? list.findIndex(p=>M.savedPredictionIdentity ? M.savedPredictionIdentity(p)===M.savedPredictionIdentity(old) : p.stage===old.stage && p.model_id===old.model_id && p.model_version===old.model_version && p.variant===old.variant && p.prediction_sha256===old.prediction_sha256 && p.output_sha256===old.output_sha256) : -1;
      if (index >= 0) state.predictionKeys[row.race_id] = index;
    }
    if (!identifiers.has(state.selectedId)) state.selectedId = "";
    if (first || explicitFollow || state.followsToday) state.day = result.day_jst;
    if (first || explicitFollow) { state.allDates = false;state.period = "day";state.followsToday = true; }
    refreshSelects();renderAll();
    $("forecast-generation").dataset.viewRevision = result.revision;
    generation.autoMessage = result.summary.coverage_known === false ? "保存原本を自動更新しました。保存済み " + result.summary.reused + "件・全モデルの網羅性は未検証です。" : "保存原本を自動更新しました。モデル別：新規 " + result.summary.generated + "件 · 再利用 " + result.summary.reused + "件 · 未予想 " + result.summary.missing + "件。";
    return true;
  }
  async function loadAutomaticLatest(force = false, explicitFollow = false) {
    if (!automaticMode()) return;
    if (generation.latestBusy) { generation.latestQueued = true;generation.latestQueuedFollow ||= explicitFollow;return; }
    const sport = state.sport, stage = $("forecast-stage").value, key = sport + "/" + stage, version = importVersion, expectedDay = generation.day;
    if (!force && (generation.pausedForDrafts && state.candidates.length || generation.pausedForEditing && activeCandidateEdit())) return;
    const hints = generation.revisions[sport];
    if (!force && hints && Object.hasOwn(hints,stage) && Object.hasOwn(generation.seen,key) && generation.seen[key] === hints[stage]) return;
    generation.latestBusy = true;renderGeneration();
    try {
      const query = new URLSearchParams({sport,stage});
      const response = await fetch(generation.api + "/latest?" + query, {credentials:"same-origin",cache:"no-store"});
      if (!response.ok) throw new Error("latest");
      const result = await response.json();
      if (version !== importVersion || sport !== state.sport || stage !== $("forecast-stage").value) return;
      if (generation.day !== expectedDay) { generation.latestQueued = true;return; }
      if (result?.available === false && generationDay(result.day_jst) && result.day_jst === expectedDay) {
        generation.seen[key] = result.revision ?? null;
        generation.autoMessage = (stage === "P1" ? "展示後" : "朝版") + "の保存予想はまだありません。現在の表示を保持しています。";
      } else {
        const parsed = automaticView(result,sport,stage,expectedDay);
        if (adoptAutomaticDataset(parsed,result,explicitFollow)) generation.seen[key] = result.revision;
      }
    } catch { generation.autoMessage = "自動予想の応答を確認できませんでした。前の表示を保持しています。"; }
    finally {
      generation.latestBusy = false;renderGeneration();
      if (generation.latestQueued) { const follow = generation.latestQueuedFollow;generation.latestQueued = false;generation.latestQueuedFollow = false;queueMicrotask(()=>loadAutomaticLatest(true,follow)); }
    }
  }
  async function connectGeneration() {
    const endpoint = document.querySelector('meta[name="race-ai-generation-api"]')?.content;
    if (endpoint !== "/api/forecast" || location.protocol !== "http:" || !["127.0.0.1", "localhost", "[::1]"].includes(location.hostname)) return;
    generation.api = endpoint;generation.message = "予想機能に接続しています…";renderGeneration();
    try {
      const response = await fetch(endpoint + "/status", {credentials:"same-origin", cache:"no-store"});
      if (!response.ok) throw new Error("status");
      const status = await response.json();
      applyGenerationStatus(status);generation.message = "";
      if (automaticMode()) { await loadAutomaticLatest(true);scheduleAutomaticPoll(); }
    } catch { generation.message = "予想サーバーに接続できません。起動状態を確認して画面を再読み込みしてください。"; }
    renderGeneration();
  }
  async function generateForecasts() {
    const sport = state.sport, stage = $("forecast-stage").value;
    if (automaticMode() || generation.busy || !generation.ready || generation.capabilities[sport]?.[stage] !== true) return;
    generation.busy = true;generation.message = "";renderGeneration();
    const version = ++importVersion;
    try {
      const response = await fetch(generation.api + "/generate", {method:"POST", credentials:"same-origin", cache:"no-store",
        headers:{"Content-Type":"application/json", "X-Race-AI-Nonce":generation.nonce}, body:JSON.stringify({sport,stage})});
      const result = await response.json();
      if (!response.ok || result.error) { generation.message = generationError(result.error?.code) + " 前の表示データは保持しています。";return; }
      const parsed = M.parse(result.view), summary = result.summary;
      if (!generationDay(result.day_jst) || parsed.event_date_jst != null && parsed.event_date_jst !== result.day_jst || parsed.records.some(row=>row.event_date_jst !== result.day_jst) || !summary || ["generated","reused","missing"].some(key=>!Number.isSafeInteger(summary[key]) || summary[key]<0)) throw new Error("invalid generation response");
      if (version !== importVersion) { generation.message = "予想処理は完了しました。後から読み込んだデータの表示を保持しています。";return; }
      state.day = result.day_jst;state.sport = sport;state.followsToday = false;state.allDates = false;state.period = "day";
      generation.day = result.day_jst;adoptDataset(parsed);showPage("races", true);
      generation.message = "モデル別：新規 " + summary.generated + "件 · 再利用 " + summary.reused + "件 · 未予想 " + summary.missing + "件。" +
        (summary.generated + summary.reused ? "保存済み予想を表示しています。" : "入力・締切の状態を表示しています。予想はまだ生成されていません。");
    } catch { generation.message = "予想の応答を確認できませんでした。前の表示データは保持しています。"; }
    finally { generation.busy = false;renderGeneration(); }
  }
  async function importFiles(files) {
    const version = ++importVersion;
    try {
      if (!files.length || files.length > 16) throw new Error("一度に読み込めるJSONは1〜16ファイルです。");
      if (files.reduce((sum, f) => sum + f.size, 0) > 20 * 1024 * 1024) throw new Error("ファイルの合計上限は20MBです。");
      const parsed = [];
      for (const file of files) {
        if (file.size > 5 * 1024 * 1024) throw new Error("1ファイルの上限は5MBです。");
        parsed.push(M.parse(JSON.parse(await file.text())));
      }
      if (version !== importVersion) return;
      const types = new Set(parsed.map(d => d.dataset_status));
      if (types.has("SYNTHETIC_ONLY") && types.size > 1) throw new Error("合成と実データは一緒に読み込めません。");
      const records = parsed.flatMap(d => d.records);
      if (new Set(records.map(r => r.race_id)).size !== records.length) throw new Error("ファイル間でレースIDが重複しています。原本を自動上書きしません。");
      adoptDataset(Object.freeze({dataset_status: types.has("SYNTHETIC_ONLY") ? "SYNTHETIC_ONLY" : types.has("REAL_REPORTED") ? "REAL_REPORTED" : "AUDIT_ONLY", records: Object.freeze(records), sources: parsed.flatMap(d => d.sources || d.provenance_urls || [])}));
      $("file-message").textContent = records.length + "件を端末内で読み込みました。競技・日付を選んでください。" + (records.some(r => r.event_date_jst !== state.day) ? " 過去・別日の原本は「読み込んだ全期間」で確認できます。" : "");
    } catch (error) { if (version === importVersion) $("file-message").textContent = "読込失敗：" + error.message + " 前の読込データは保持しています。"; }
    finally { if (version === importVersion) $("race-file").value = ""; }
  }
  async function loadSynthetic() {
    const version = ++importVersion; $("load-synthetic").disabled = true;
    try {
      const response = await fetch("./data/example-synthetic-forecast-audit.json", {credentials: "same-origin", cache: "no-store"});
      if (!response.ok) throw new Error("合成テストJSONを取得できませんでした。");
      const parsed = M.parse(await response.json());
      if (parsed.dataset_status !== "SYNTHETIC_ONLY") throw new Error("合成専用データではありません。");
      if (version !== importVersion) return;
      state.allDates = true; adoptDataset(parsed);
      $("file-message").textContent = "合成テスト専用の架空データを表示しています。実レースの予想・成績ではありません。";
    } catch (error) { if (version === importVersion) $("file-message").textContent = "合成テストの読込失敗：" + error.message; }
    finally { $("load-synthetic").disabled = false; }
  }
  async function loadSavedDataset() {
    const inline = document.getElementById("race-ai-private-saved-data");
    const endpoint = document.querySelector('meta[name="race-ai-private-saved-view"]');
    const encrypted = document.querySelector('meta[name="race-ai-encrypted-saved-view"]');
    if (!inline && !endpoint && !encrypted) return;
    const version = ++importVersion;
    generation.savedState = "LOADING";
    if (encrypted && !/^#saved=[a-f0-9]{64}\.[A-Za-z0-9_-]{43}$/.test(location.hash)) {
      generation.savedState = "LINK_REQUIRED"; generation.message = savedMessages.LINK_REQUIRED[1];
      $("file-message").textContent = generation.message; renderAll(); return;
    }
    try {
      let raw;
      if (inline) raw = JSON.parse(inline.textContent);
      else if (encrypted) raw = await window.SavedViewCrypto.read(encrypted.content,location.hash);
      else {
        if (endpoint.content !== "/api/forecast/saved") throw new Error("invalid saved endpoint");
        const response = await fetch(endpoint.content,{credentials:"same-origin",cache:"no-store"});
        if (!response.ok) throw new Error("saved originals unavailable");
        raw = await response.json();
      }
      const parsed = M.parse(raw);
      if (version !== importVersion) return;
      if (!parsed.records.length) throw new Error("saved originals empty");
      generation.savedState = "READY";
      const today=A.jstToday();
      if(state.followsToday) {
        // A historical saved snapshot must remain usable after its race day.
        // Keep following today's new originals; never relabel old picks as today's.
        const savedDays=[...new Set(parsed.records.filter(row=>storedPredictions(row).some(activeModel)).map(row=>row.event_date_jst))].sort();
        state.day=savedDays.includes(today)?today:(savedDays.filter(day=>day<=today).at(-1)??savedDays[0]??today);
      }
      state.raceView = state.day < today || !U.raceLists(parsed.records.filter(row=>row.event_date_jst===state.day)).upcoming.length ? "results" : "upcoming";state.sport = parsed.records[0].sport;
      state.allDates = false;state.period = "day";
      const currentRows=parsed.records.filter(row=>row.event_date_jst===state.day);
      const showingSavedFallback=state.followsToday&&state.day!==today;
      generation.message = (currentRows.length ? "保存済み予想・レース情報 " + currentRows.length + "レース · " + state.day : "保存済み予想を確認中 · " + state.day) +
        (showingSavedFallback ? " · 今日の新規予想は未保存です。" + (state.day<today?"最後の保存日":"次の保存日") + "の予想を表示しています。" : "");
      adoptDataset(parsed);ownerEncryptedTrusted=Boolean(encrypted);ownerAuditCache=null;renderAll();showPage("races",true);
      $("file-message").textContent = generation.message;
      if (encrypted) startSavedFeed(encrypted.content,version);
    } catch {
      if (version !== importVersion) return;
      generation.savedState = "UNAVAILABLE"; generation.message = savedMessages.UNAVAILABLE[1];
      $("file-message").textContent = generation.message;renderAll();
    }
  }
  function startSavedFeed(path,version) {
    const forecastSha=document.querySelector('meta[name="race-ai-saved-view-forecast-sha"]')?.content;
    if(!forecastSha||!window.SavedViewCrypto?.readLive)return;
    const status=node("p","muted small","結果の自動同期を確認しています。");status.id="saved-view-sync";status.setAttribute("role","status");
    $("result-coverage").after(status);
    let previous={forecastSha,generation:0,cipherSha:path.split("/").at(-1).replace(".json","")},busy=false,queuedDay=null,followToday=state.followsToday;
    const choices=new Map();
    function rememberChoices() {
      if(!races().some(row=>row.event_date_jst===state.day))return;
      const identities={};
      for(const row of races()){const p=prediction(row);if(p)identities[row.race_id]=M.savedPredictionIdentity(p);}
      choices.delete(state.day);choices.set(state.day,{selectedId:state.selectedId,resultGroupKey:state.resultGroupKey,identities,venue:state.venue});
      if(choices.size>32)choices.delete(choices.keys().next().value);
    }
    function applySaved(result,day=result.history?.day??(followToday&&result.view.records.some(row=>row.event_date_jst===A.jstToday())?A.jstToday():state.day)) {
      const parsed=M.parse(result.view);if(!parsed.records.length)throw new Error("saved originals empty");
      if(result.history&&(day!==result.history.day||parsed.records.some(row=>row.event_date_jst!==day)))throw new Error("saved history day mismatch");
      const draftIds=['ticket-amount','lane-first','lane-second','lane-third','simulation-budget','race-budget','daily-budget','race-search'];
      const drafts=draftIds.map(id=>[id,$(id)?.value]),focused=document.activeElement?.id,selection=document.activeElement?.selectionStart,sameDay=day===state.day;
      rememberChoices();const choice=choices.get(day),keys={};
      for(const row of parsed.records) {
        const identity=choice?.identities[row.race_id];if(identity==null)continue;
        const index=predictions(row).findIndex(p=>M.savedPredictionIdentity(p)===identity);
        if(index<0)throw new Error("saved original selection unavailable");keys[row.race_id]=index;
      }
      dataset=parsed;ownerEncryptedTrusted=true;ownerAuditCache=null;state.day=day;state.predictionKeys=keys;
      generation.message="保存済み予想・レース情報 " + parsed.records.filter(row=>row.event_date_jst===day).length + "レース · " + day;
      if(!sameDay)state.raceView=day<A.jstToday()||!U.raceLists(parsed.records).upcoming.length?"results":"upcoming";
      if(choice){state.selectedId=choice.selectedId;state.resultGroupKey=choice.resultGroupKey;state.venue=choice.venue;}
      previous={forecastSha,generation:result.header.generation,cipherSha:result.cipherSha};
      if(result.history) {
        savedHistory.active=true;state.followsToday=false;state.allDates=false;state.period="day";
      }
      refreshSelects();renderAll();status.dataset.generation=String(previous.generation);status.dataset.historyDay=state.day;
      if(sameDay)for(const [id,value] of drafts){const input=$(id);if(input&&value!==undefined&&(input.tagName!=="SELECT"||[...input.options].some(o=>o.value===value)))input.value=value;}
      const focus=sameDay&&focused&&$(focused);if(focus){focus.focus({preventScroll:true});if(Number.isInteger(selection))try{focus.setSelectionRange(selection,selection);}catch{}}
    }
    // An open results page needs a shorter *saved-view manifest* check, not
    // another official racing-provider GET. No polling while tab is hidden.
    function fastResultsView() {
      return state.day===A.jstToday() &&
        (state.page==="results" || state.page==="detail" ||
          (state.page==="races" && state.raceView==="results"));
    }
    let lastSavedPollAt=0;
    function syncedMessage() {
      const seconds=fastResultsView()?15:60;
      status.textContent=(savedHistory.active?"保存履歴は日付を選んで表示できます。":"")+"結果を自動同期中（"+seconds+"秒ごとに確認） · 最終同期 "+stamp(dataset.results_synced_at)+" JST。収集処理の停止中は前回の結果を表示します。";
    }
    async function selectDay(day) {
      if(version!==importVersion||!savedHistory.active)return;
      followToday=false;
      if(busy){queuedDay=day;return;}
      busy=true;const oldDay=state.day;status.textContent=day+" の保存原本を読み込んでいます。";
      try {
        const result=await window.SavedViewCrypto.readDay(location.hash,previous,day);
        if(version!==importVersion||!dataset)return;
        applySaved(result,day);state.visible=60;syncedMessage();
      } catch {
        $("selected-date").value=oldDay;
        status.textContent="保存履歴を取得できません。前回取得した日付・原本を表示中です。日付を選び直して再確認できます。";
      } finally {busy=false;drainDay();}
    }
    function drainDay() {if(queuedDay!==null){const day=queuedDay;queuedDay=null;selectDay(day);}}
    savedHistory={version,active:false,selectDay,noteDayChange:day=>{followToday=false;rememberChoices();if(busy)queuedDay=day;}};
    async function check() {
      if(busy||version!==importVersion||!dataset||document.hidden)return;
      lastSavedPollAt=Date.now();
      busy=true;resultCheck.busy=true;syncResultRefreshUI();
      try {
        const result=await window.SavedViewCrypto.readLive(location.hash,previous,{day:state.day,preferredDay:followToday?A.jstToday():undefined});
        if(version!==importVersion||!dataset)return;
        if(result) {
          applySaved(result);
        }
        resultCheck.failed=false;
        syncedMessage();
      } catch {resultCheck.failed=true;status.textContent="自動同期を確認できません。前回取得した結果を表示中です。60秒後に再確認します。";}
      finally {busy=false;resultCheck.busy=false;syncResultRefreshUI();drainDay();}
    }
    refreshSavedResults=()=>check();const control=resultRefreshButton();status.before(control);syncResultRefreshUI();
    check();const timer=setInterval(()=>{
      if(version!==importVersion){clearInterval(timer);return;}
      const interval=fastResultsView()?15000:60000;
      if(Date.now()-lastSavedPollAt>=interval)check();
    },15000);
    document.addEventListener("visibilitychange",()=>{if(!document.hidden)check();});
  }
  document.querySelectorAll("[data-page]").forEach(b => b.addEventListener("click", () => showPage(b.dataset.page, true)));
  document.querySelectorAll("[data-sport]").forEach(b => b.addEventListener("click", () => setSport(b.dataset.sport)));
  window.addEventListener("hashchange", () => {
    if (document.querySelector('meta[name="race-ai-encrypted-saved-view"]')) { location.reload();return; }
    showPage(location.hash.slice(1));
  });
  document.addEventListener("click", event => {
    if (!document.querySelector('meta[name="race-ai-encrypted-saved-view"]')) return;
    const anchor = event.target.closest?.('a[href^="#"]');if (!anchor) return;
    const target = anchor.getAttribute("href").slice(1);
    if (Object.hasOwn(pageNames,target)) { event.preventDefault();showPage(target,true); }
    else { const element = document.getElementById(target);if (element) { event.preventDefault();element.focus();element.scrollIntoView(); } }
  });
  $("selected-date").addEventListener("change", () => { if (!$("selected-date").value) { $("selected-date").value = state.day; return; } state.raceView = $("selected-date").value < A.jstToday() ? "results" : "upcoming"; if(savedHistory?.version===importVersion){if(savedHistory.active){savedHistory.selectDay($("selected-date").value);return;}savedHistory.noteDayChange($("selected-date").value);} state.day = $("selected-date").value; state.followsToday = false; state.allDates = false; state.period = "day"; state.visible = 60; refreshSelects(); renderAll(); });
  $("period-all").addEventListener("change", () => { state.allDates = $("period-all").checked; state.visible = 60; refreshSelects(); renderAll(); });
  $("period-filter").addEventListener("change", e => { state.allDates = e.target.value === "all"; state.period = state.allDates ? "day" : e.target.value; state.visible = 60; refreshSelects(); renderAll(); });
  function search(value) { state.query = value; state.visible = 60; $("race-search").value = value; $("global-search").value = value; renderRaces(); }
  $("global-search").addEventListener("input", e => { search(e.target.value); showPage("races"); });
  $("race-search").addEventListener("input", e => search(e.target.value));
  document.querySelectorAll("[data-race-view]").forEach(tab => tab.addEventListener("click", () => setRaceView(tab.dataset.raceView,true)));
  $("race-view-tabs").addEventListener("keydown", event => {
    const tabs = [...$("race-view-tabs").querySelectorAll("[data-race-view]")].filter(t => !t.hidden), index = tabs.findIndex(t => t.dataset.raceView === state.raceView); let next;
    if (event.key === "ArrowRight") next = tabs[(index+1)%tabs.length]; if (event.key === "ArrowLeft") next = tabs[(index+tabs.length-1)%tabs.length]; if (event.key === "Home") next = tabs[0]; if (event.key === "End") next = tabs.at(-1);
    if (next) { event.preventDefault(); setRaceView(next.dataset.raceView,true); }
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden && state.page === "races") renderRaces(); });
  $("race-sort").addEventListener("change", e => { state.sort = e.target.value; renderRaces(); });
  $("venue-filter").addEventListener("change", e => { state.venue = e.target.value; renderRaces(); });
  $("all-venues").addEventListener("click", () => chooseVenue(""));
  $("home-all-venues").addEventListener("click", () => chooseVenue(""));
  $("pin-venue").addEventListener("click", () => {
    if (!state.venue) return;
    const key = state.sport + ":" + state.venue;
    state.favoriteVenues = state.favoriteVenues.includes(key) ? state.favoriteVenues.filter(value => value !== key) : [...state.favoriteVenues, key].slice(-64);
    persistPreferences(); renderHome(); renderRaces();
  });
  $("status-filter").addEventListener("change", e => { state.statusFilter = e.target.value; renderRaces(); });
  $("prediction-filter").addEventListener("change", e => { state.forecastOnly = e.target.checked; renderRaces(); });
  $("candidate-filter").addEventListener("change", e => { state.candidatesOnly = e.target.checked; renderRaces(); });
  $("clear-filters").addEventListener("click", () => { state.venue = ""; state.forecastOnly = false; state.candidatesOnly = false; state.statusFilter = "all"; state.sort = "time"; $("venue-filter").value = ""; $("status-filter").value = "all"; $("prediction-filter").checked = false; $("candidate-filter").checked = false; $("race-sort").value = "time"; search(""); });
  $("ticket-race").addEventListener("change", e => { state.selectedId = e.target.value; $("purchase-ack").checked = false; refreshLaneSelects(); renderTickets(); });
  $("race-budget").addEventListener("change", e => { const value = Number(e.target.value); if (!validBudget(value)) { $("ticket-message").textContent = "予算は100〜10,000,000円の100円単位で入力してください。"; e.target.value = state.raceBudget; return; } state.raceBudget = value; state.confirmed.clear(); $("purchase-ack").checked = false; persistPreferences(); renderTickets(); });
  $("max-picks").addEventListener("change", e => { state.maxPicks = Number(e.target.value); state.confirmed.clear(); $("purchase-ack").checked = false; persistPreferences(); renderTickets(); });
  $("ticket-form").addEventListener("submit", e => {
    e.preventDefault(); const r = currentRace(); if (!r) return;
    const lanes = ["lane-first", "lane-second", "lane-third"].map(id => Number($(id).value)), amount = Number($("ticket-amount").value), ts = ticketsFor(r.race_id);
    const error = U.validateTicket(lanes, amount, maxNumber(r)) || U.validateDraft([...ts, {lanes, amount}], state.raceBudget, state.maxPicks, maxNumber(r));
    if (error) { $("ticket-message").textContent = error; return; }
    state.candidates.push({raceId: r.race_id, lanes, amount, origin: "manual"}); invalidateConfirmation(r.race_id); renderAll(); $("ticket-message").textContent = "未購入の候補に追加しました。";
  });
  $("copy-top8").addEventListener("click", () => {
    const r = currentRace(), p = prediction(r); if (!r || !p) return;
    const existing = ticketsFor(r.race_id), additions = p.ordered_top8.filter(lanes => !existing.some(t => t.lanes.join("-") === lanes.join("-"))).map(lanes => ({raceId: r.race_id, lanes: lanes.slice(), amount: 100, origin: "saved"}));
    const error = U.validateDraft([...existing, ...additions], state.raceBudget, state.maxPicks, maxNumber(r));
    if (error) { $("ticket-message").textContent = error; return; }
    state.candidates.push(...additions); invalidateConfirmation(r.race_id); renderAll(); $("ticket-message").textContent = additions.length + "点を未購入候補に追加しました。予想原本の順位・金額は変更しません。";
  });
  $("equal-allocate").addEventListener("click", () => { const ts = ticketsFor(state.selectedId), amounts = U.allocate(state.raceBudget, ts.length); if (!amounts.length) { $("ticket-message").textContent = "全候補に100円以上配分できる予算を設定してください。"; return; } ts.forEach((t, i) => { t.amount = amounts[i]; }); invalidateConfirmation(state.selectedId); renderAll(); $("ticket-message").textContent = "1レース予算を均等配分しました。"; });
  $("clear-tickets").addEventListener("click", () => { state.candidates = state.candidates.filter(t => t.raceId !== state.selectedId); invalidateConfirmation(state.selectedId); renderAll(); });
  $("confirm-candidates").addEventListener("click", () => { const r = currentRace(), error = U.validateDraft(ticketsFor(state.selectedId), state.raceBudget, state.maxPicks, maxNumber(r)); if (!r || error) { $("ticket-message").textContent = error || "レースを選択してください。"; return; } state.confirmed.add(r.race_id); renderAll(); $("ticket-message").textContent = "配分を候補として確定しました。実購入・使用額には含みません。"; });
  $("reopen-candidates").addEventListener("click", () => { invalidateConfirmation(state.selectedId); renderTickets(); });
  $("purchase-ack").addEventListener("change", renderTickets);
  $("record-purchase").addEventListener("click", () => {
    const r = currentRace(), ts = ticketsFor(state.selectedId), error = U.validateDraft(ts, state.raceBudget, state.maxPicks, maxNumber(r));
    if (!r || r.scope === "synthetic" || !state.confirmed.has(r.race_id) || !$("purchase-ack").checked || error) return;
    const total = ts.reduce((sum, t) => sum + t.amount, 0), day = r.event_date_jst;
    const existingSpent = U.summarize(state.purchases.filter(p => p.day === day)).spent;
    if (existingSpent + total > state.budget) { $("ticket-message").textContent = "1日の予算を超えるため記録できません。設定で予算を確認してください。"; return; }
    ts.forEach(t => state.purchases.push({...t, lanes: t.lanes.slice(), raceLabel: raceName(r), sport: r.sport, day, payout: null}));
    state.candidates = state.candidates.filter(t => t.raceId !== r.race_id); invalidateConfirmation(r.race_id); renderAll(); $("ticket-message").textContent = "購入済みの申告を別台帳に記録しました。投票は行っていません。";
  });
  $("settings-form").addEventListener("submit", e => { e.preventDefault(); const value = Number($("daily-budget").value); if (!validBudget(value) || value < U.summarize(dailyPurchases()).spent) { $("settings-message").textContent = "予算は本日の購入済み金額以上、100〜10,000,000円の100円単位で入力してください。"; return; } state.budget = value; state.sport = $("settings-sport").value; persistPreferences(); refreshSelects(); renderAll(); $("settings-message").textContent = "予算と初期競技の設定を保存しました。予想や購入明細は保存していません。"; });
  $("race-file").addEventListener("change", e => importFiles([...e.target.files]));
  $("forecast-generate").addEventListener("click", generateForecasts);
  $("forecast-stage").addEventListener("change", () => { generation.message = "";renderGeneration();if (automaticMode()) { loadAutomaticLatest(true);scheduleAutomaticPoll(); } });
  $("forecast-follow-latest").addEventListener("click",()=>loadAutomaticLatest(true,true));
  $("load-synthetic").addEventListener("click", loadSynthetic);
  $("clear-data").addEventListener("click", () => { ++importVersion;ownerEncryptedTrusted=false;ownerAuditCache=null;refreshSavedResults=null;resultCheck.busy=false;resultCheck.failed=false;generation.savedState = savedViewConfigured ? "CLEARED" : null;generation.ownsDisplay = false;generation.suppressed = true; dataset = null; state.selectedId = ""; state.predictionKeys = {}; state.modelOriginals = {}; state.modelBySport = {}; state.candidates = []; state.confirmed.clear(); $("purchase-ack").checked = false; refreshSelects(); renderAll(); $("file-message").textContent = "読み込んだ予想と候補をメモリから消去しました。手動購入記録は再読込まで保持します。"; });
  $("results-model").addEventListener("change",e=>{state.resultGroupKey=e.target.value;renderResults();});
  $("simulation-race-budget").addEventListener("change",e=>{
    const value=Number(e.target.value);if(![800,1000].includes(value))return;
    state.simulationRaceBudget=value;persistPreferences();$("simulation-message").textContent="1レース上限 "+yen(value)+" で再計算しました。";renderResults();
  });
  $("simulation-budget").addEventListener("change",e=>{
    const value=Number(e.target.value);
    if (!validBudget(value)) { e.target.value=state.simulationBudget;$("simulation-message").textContent="日予算は100〜10,000,000円の100円単位で入力してください。";return; }
    state.simulationBudget=value;persistPreferences();$("simulation-message").textContent="1日予算 "+yen(value)+" で再計算しました。";renderResults();
  });
  // A local clock change updates the display day, without fetching race sources.
  function checkDay() {
    if (automaticMode() || !state.followsToday) return;
    const today = A.jstToday();
    if (state.day === today) return;
    // A verified historical forecast remains visible until today's saved
    // predictions really exist. A clock tick must never empty the race list.
    const todayRecords = races().filter(row => row.event_date_jst === today);
    if (!todayRecords.some(row => predictions(row).length)) return;
    state.day = today;
    state.raceView = U.raceLists(todayRecords).upcoming.length ? "upcoming" : "results";
    refreshSelects(); renderAll();
  }
  setInterval(checkDay, 30000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) checkDay(); });
  window.addEventListener("pagehide",()=>{if(generation.timer!==null)clearTimeout(generation.timer);generation.timer=null;});
  window.addEventListener("pageshow",event=>{if(event.persisted && automaticMode())scheduleAutomaticPoll();});
  document.addEventListener("focusout",()=>{if(automaticMode() && generation.pausedForEditing)queueMicrotask(()=>loadAutomaticLatest(true));});
  document.addEventListener("change",()=>{if(automaticMode() && generation.pausedForEditing)queueMicrotask(()=>loadAutomaticLatest(true));});
  refreshSelects(); renderAll(); showPage(location.hash.slice(1) || "home");
  connectGeneration();
  loadSavedDataset();
  window.addEventListener("race-ai-daily-updated", ()=>{renderDailyCard();syncResultRefreshUI();});
  globalThis.RaceRacerDaily?.load();
})();
}

(function(root){
  'use strict';
  // Rank/role weights express an allocation example, not fitted probabilities.
  function allocate(tickets,budget){
    if(![2000,2500,3000].includes(budget))throw new RangeError('Unsupported budget');
    if(!Array.isArray(tickets)||tickets.length<1||tickets.length>12)throw new RangeError('Invalid ticket count');
    const seen={};
    const weights=tickets.map(t=>{
      if(!['本線','押さえ','波乱'].includes(t.role))throw new TypeError('Invalid ticket role');
      const i=seen[t.role]||0;seen[t.role]=i+1;
      return ({'本線':8,'押さえ':2,'波乱':0.75}[t.role])/(1+i*0.35);
    });
    const remaining=budget/100-tickets.length;
    const total=weights.reduce((a,b)=>a+b,0);
    const raw=weights.map(w=>remaining*w/total);
    const units=raw.map(x=>1+Math.floor(x));
    let left=budget/100-units.reduce((a,b)=>a+b,0);
    const order=raw.map((v,i)=>({i,rem:v-Math.floor(v)})).sort((a,b)=>b.rem-a.rem||a.i-b.i);
    for(let j=0;j<left;j++)units[order[j].i]++;
    return units.map(x=>x*100);
  }
  function profitOdds(budget,amount){
    if(!Number.isFinite(budget)||!Number.isFinite(amount)||budget<=0||amount<=0)throw new RangeError('Positive amounts required');
    return (Math.floor(budget*10/amount)+1)/10;
  }
  function estimate(budget,amount,odds){
    if(typeof odds!=='number'||!Number.isFinite(odds)||odds<1||odds>=9999.9)return null;
    const payout=Math.round(amount*odds);
    return {payout,net:payout-budget};
  }
  const api={allocate,profitOdds,estimate};
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.KeirinStaking=api;
})(typeof window==='object'?window:globalThis);

(function(root){
  'use strict';
  const base=typeof module==='object'&&module.exports?require('./staking.js'):root.KeirinStaking;
  function allocate(tickets,budget){
    if(![2000,2500,3000].includes(budget))throw new RangeError('Unsupported budget');
    if(!Array.isArray(tickets)||tickets.length<1||tickets.length>504)throw new RangeError('Invalid ticket count');
    if(tickets.length*100>budget)throw new RangeError('Budget is below 100 yen per selected ticket');
    const seen={};
    const weights=tickets.map(t=>{if(!['本線','押さえ','波乱'].includes(t.role))throw new TypeError('Invalid ticket role');const i=seen[t.role]||0;seen[t.role]=i+1;return ({'本線':8,'押さえ':2,'波乱':0.75}[t.role])/(1+i*0.35);});
    const remaining=budget/100-tickets.length,total=weights.reduce((a,b)=>a+b,0);
    const raw=weights.map(w=>remaining*w/total),units=raw.map(x=>1+Math.floor(x));
    const left=budget/100-units.reduce((a,b)=>a+b,0),order=raw.map((v,i)=>({i,rem:v-Math.floor(v)})).sort((a,b)=>b.rem-a.rem||a.i-b.i);
    for(let j=0;j<left;j++)units[order[j].i]++;
    return units.map(x=>x*100);
  }
  const api={...base,allocate,canAllocate:(tickets,budget)=>tickets.length>0&&tickets.length*100<=budget};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.KeirinStaking=api;
})(typeof window==='object'?window:globalThis);

(function(root,factory){
  if(typeof module==='object'&&module.exports)module.exports=factory(require('./staking.js'));
  else root.KeirinRollover=factory(root.KeirinStaking);
})(typeof window==='object'?window:globalThis,function(staking){
  'use strict';
  const budgets=[2000,2500,3000];
  const maxReceipt=100000000;

  function checkBudget(value){
    if(!budgets.includes(value))throw new RangeError('初回予算は2000・2500・3000円から選んでください。');
  }
  function checkReceipt(value){
    if(value!==null&&(!Number.isSafeInteger(value)||value<0||value>maxReceipt)){
      throw new RangeError('受取額は0〜100000000円の整数、未入力はnullにしてください。');
    }
  }
  function positiveInteger(value){
    if(!Number.isSafeInteger(value)||value<=0)throw new RangeError('正の整数の金額が必要です。');
  }

  // Receipts include refunds. Only profit may fund the second and final stage.
  function plan({initialBudget,firstReturn=null,secondReturn=null}={}){
    checkBudget(initialBudget);
    checkReceipt(firstReturn);
    checkReceipt(secondReturn);
    const base={firstStake:initialBudget,nextStake:0,reserve:0,finalReturn:null,net:null};
    if(firstReturn===null){
      return {...base,status:'awaiting_first',reason:'1戦目の受取額（払戻と返還の合計）を入力してください。'};
    }

    const profit=firstReturn-initialBudget;
    if(profit<2000){
      const reason=firstReturn===0
        ?'1戦目の受取が0円で終了。初回予算が損失になります。'
        :profit<0
          ?'1戦目は購入額を回収できず終了。返還を含む受取額で計算しています。'
          :profit===0
            ?'1戦目の受取が初回予算と同額のため、差額0円で終了します。'
            :'利益が次の最低額2,000円に届かないため終了。受取は取り分けます。';
      return {...base,status:'stopped',reserve:firstReturn,finalReturn:firstReturn,net:profit,reason};
    }

    const nextStake=profit>=3000?3000:profit>=2500?2500:2000;
    const reserve=firstReturn-nextStake;
    if(secondReturn===null){
      return {
        ...base,status:'awaiting_second',nextStake,reserve,
        reason:'元金と余剰分を取り分け、利益の範囲で2戦目へ。2戦目の受取額を入力してください。',
      };
    }
    const finalReturn=reserve+secondReturn;
    return {
      ...base,status:'completed',nextStake,reserve,finalReturn,net:finalReturn-initialBudget,
      reason:'2戦目の受取を取り分け分に加えて終了。3戦目へは進みません。',
    };
  }

  // Bounds assume one winning ticket and no refund, in 0.1-odds increments.
  function positiveBounds(total,amount){
    positiveInteger(total);
    positiveInteger(amount);
    const scaled=total*10;
    if(!Number.isSafeInteger(scaled))throw new RangeError('金額が計算可能な範囲を超えています。');
    return {breakEvenOdds:Math.ceil(scaled/amount)/10,profitOdds:(Math.floor(scaled/amount)+1)/10};
  }
  function continuationOdds(initialBudget,amount,minNext=2000){
    checkBudget(initialBudget);
    positiveInteger(minNext);
    return positiveBounds(initialBudget+minNext,amount).breakEvenOdds;
  }
  return {plan,positiveBounds,continuationOdds,allocate:staking.allocate};
});

/* Presentation and validation of saved assessments. This module never assigns a grade. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.RaceKeirinConfidence = factory();
})(typeof window === 'object' ? window : globalThis, function () {
  'use strict';

  const SCHEMA = 'RACE_AI_KEIRIN_CONFIDENCE_ASSESSMENT_V1';
  const RULES = 'research-coherence-v1';
  const UNIVERSE_SCHEMA = 'RACE_AI_KEIRIN_CONFIDENCE_UNIVERSE_V1';
  const PHASES = ['INITIAL', 'BELL', 'FINAL_HOME', 'FINAL_BACK', 'FOURTH_CORNER', 'GOAL'];
  // Immutable research-coherence-v1 acceptance constraints. These only reject
  // contradictory saved metrics/grades; they never create or change a rating.
  const V1_GRADE_CONSTRAINTS = [[4, .85, .85, .90, .90], [3, .70, .70, .80, .80], [2, .50, .50, .60, .50]];
  const GRADES = new Map([['未評価', 0], ['低', 1], ['中', 2], ['高', 3], ['激アツ', 4]]);
  const verified = new WeakSet();
  const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const exact = (value, names) => record(value) && Object.keys(value).sort().join(',') === names.slice().sort().join(',');
  const need = condition => { if (!condition) throw new Error('KEIRIN_CONFIDENCE_INVALID'); };
  const hex = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
  const bounded = (value, max) => typeof value === 'string' && value.trim().length > 0 && value.length <= max;
  const ratio = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1;
  const unique = values => new Set(values).size === values.length;
  const canonical = value => JSON.stringify(value && typeof value === 'object'
    ? Array.isArray(value) ? value.map(item => JSON.parse(canonical(item)))
      : Object.fromEntries(Object.keys(value).sort().map(key => [key, JSON.parse(canonical(value[key]))]))
    : value);
  function timestamp(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)$/.test(value)) return null;
    const time = Date.parse(value), date = value.slice(0, 10), midnight = Date.parse(date + 'T00:00:00Z');
    if (!Number.isFinite(time) || !Number.isFinite(midnight) || new Date(midnight).toISOString().slice(0, 10) !== date || Number(value.slice(11, 13)) > 23 || Number(value.slice(14, 16)) > 59 || Number(value.slice(17, 19)) > 59) return null;
    return time;
  }
  function timestampMicros(value) {
    const milliseconds = timestamp(value);if (milliseconds === null) return null;
    const fraction = /\.(\d{1,6})(?:Z|[+-]\d\d:\d\d)$/.exec(value)?.[1] || '';
    return BigInt(milliseconds) * 1000n + BigInt(fraction.padEnd(6, '0').slice(3));
  }
  async function digest(value) {
    const crypto = globalThis.crypto?.subtle ? globalThis.crypto : require('node:crypto').webcrypto;
    const bytes = new TextEncoder().encode(canonical(value));
    return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), byte => byte.toString(16).padStart(2, '0')).join('');
  }

  function normalize(raw) {
    switch (typeof raw === 'string' ? raw.trim() : null) {
      case '激アツ':
      case '激アツ🔥': return { label: '激アツ', rank: 4 };
      case '高':
      case '高い':
      case '高め': return { label: '高', rank: 3 };
      case '中':
      case '中位': return { label: '中', rank: 2 };
      case '低':
      case '低め':
      case '控えめ': return { label: '低', rank: 1 };
      default: return { label: '未評価', rank: 0 };
    }
  }
  function displayLabel(raw) {
    const value = normalize(raw);
    return value.rank === 4 ? '激アツ🔥' : value.label;
  }
  function matches(raw, filter = 'all') {
    const { rank } = normalize(raw);
    switch (filter) {
      case 'all': return true;
      case 'high_plus': return rank >= 3;
      case 'hot': return rank === 4;
      case 'high': return rank === 3;
      case 'medium': return rank === 2;
      case 'low': return rank === 1;
      case 'unrated': return rank === 0;
      default: return false;
    }
  }
  function predictionMatches(prediction, filter = 'all') {
    return filter === 'all' || Boolean(prediction?.tickets?.length && matches(prediction.confidence, filter));
  }
  function selected(bundle, name) {
    if (bundle == null) return { confidence: null, confidenceAssessment: null, confidenceBundle: null };
    need(verified.has(bundle));
    const entry = bundle.evaluations[name];
    return { confidence: entry?.grade ?? null, confidenceAssessment: entry || null, confidenceBundle: entry ? bundle : null };
  }

  function ticketArrays(values, market, cars) {
    const places = market === '2t' ? 2 : 3;
    need(Array.isArray(values) && values.length <= 504);
    const tuples = values.map(value => {
      const tuple = Array.isArray(value) ? value : typeof value?.combo === 'string' && new RegExp('^[1-9](?:-[1-9]){' + (places - 1) + '}$').test(value.combo) ? value.combo.split('-').map(Number) : null;
      need(Array.isArray(tuple) && tuple.length === places && unique(tuple) && tuple.every(car => Number.isInteger(car) && car >= 1 && car <= 9 && (!cars || cars.includes(car))));
      return tuple.slice();
    });
    need(unique(tuples.map(tuple => tuple.join('-'))));
    return tuples.sort((a, b) => a.join('-').localeCompare(b.join('-')));
  }
  function checkedUniverse(universe) {
    need(exact(universe, ['schema', 'race_id', 'source_as_of', 'cutoff', 'source_prediction_sha256', 'source_facts_sha256', 'cars', 'evidence_kind', 'candidate_origin', 'source_status', 'scenarios']));
    need(universe.schema === UNIVERSE_SCHEMA && /^20\d{10}$/.test(universe.race_id) && timestamp(universe.source_as_of) !== null && timestamp(universe.cutoff) !== null);
    need(hex(universe.source_prediction_sha256) && hex(universe.source_facts_sha256));
    need(Array.isArray(universe.cars) && universe.cars.length >= 5 && universe.cars.length <= 9 && unique(universe.cars) && universe.cars.every((car, index) => Number.isInteger(car) && car >= 1 && car <= 9 && (!index || universe.cars[index - 1] < car)));
    need(['canonical_b_orders', 'authored_goals'].includes(universe.evidence_kind) && ['canonical_projection_v1', 'independent_preselection_v1', 'legacy_ticket_links'].includes(universe.candidate_origin));
    const status = universe.source_status;
    need(exact(status, ['lineup', 'required_missing', 'conflicting_fields']) && ['published_prediction', 'not_applicable_girls', 'unknown'].includes(status.lineup));
    for (const key of ['required_missing', 'conflicting_fields']) need(Array.isArray(status[key]) && status[key].length <= 128 && unique(status[key]) && status[key].every(value => bounded(value, 200)));
    need(Array.isArray(universe.scenarios) && universe.scenarios.length > 0 && universe.scenarios.length <= 128);
    const ids = new Set();
    for (const scenario of universe.scenarios) {
      need(exact(scenario, ['id', 'role', 'counter_family', 'phases', 'goal_candidates', 'research_weight']) && bounded(scenario.id, 120) && !ids.has(scenario.id));
      ids.add(scenario.id);
      need(['main', 'counter'].includes(scenario.role) && (scenario.role === 'main' ? scenario.counter_family === null : ['counterattack', 'follower_sashi', 'late_sprint', 'pace_fade', 'other'].includes(scenario.counter_family)));
      need(Array.isArray(scenario.phases) && scenario.phases.length <= 128);
      const prose = scenario.phases.every(phase => bounded(phase, 2000));
      if (!prose) scenario.phases.forEach(phase => {
        need(exact(phase, ['phase', 'projected_order', 'projected_top3', 'hypothesis_actions', 'actual_rider_position_video_verified']) && PHASES.includes(phase.phase) && phase.actual_rider_position_video_verified === false);
        need(Array.isArray(phase.projected_order) && phase.projected_order.length === universe.cars.length && unique(phase.projected_order) && phase.projected_order.every(car => universe.cars.includes(car)));
        need(canonical(phase.projected_top3) === canonical(phase.projected_order.slice(0, 3)) && Array.isArray(phase.hypothesis_actions) && phase.hypothesis_actions.length > 0 && phase.hypothesis_actions.length <= 32 && phase.hypothesis_actions.every(action => bounded(action, 120) && /^[A-Z][A-Z0-9_]*$/.test(action)));
      });
      need(record(scenario.goal_candidates) && Object.keys(scenario.goal_candidates).length > 0 && Object.keys(scenario.goal_candidates).every(market => ['3t', '2t'].includes(market)));
      for (const [market, candidates] of Object.entries(scenario.goal_candidates)) {
        need(ticketArrays(candidates, market, universe.cars).length > 0);
        const goal = scenario.phases.find(phase => record(phase) && phase.phase === 'GOAL');
        if (goal) need(candidates.some(candidate => canonical(candidate) === canonical(goal.projected_order.slice(0, market === '2t' ? 2 : 3))));
      }
      if (universe.evidence_kind === 'canonical_b_orders') need(!prose && typeof scenario.research_weight === 'string' && /^(?:0\.\d{12}|1\.000000000000)$/.test(scenario.research_weight) && Number(scenario.research_weight) > 0);
      else need(scenario.research_weight === null);
    }
    if (universe.evidence_kind === 'canonical_b_orders') need(Math.abs(universe.scenarios.reduce((sum, scenario) => sum + Number(scenario.research_weight), 0) - 1) <= 1e-8);
    return ids;
  }
  function universeFromBaseline(baseline, source) {
    need(record(baseline) && record(source) && Array.isArray(source.riders) && Array.isArray(baseline.B?.six_phase_scenarios));
    const riders = source.riders.slice().sort((a, b) => a.car - b.car), missing = [];
    for (const rider of riders) {
      if (rider.competition_points <= 0) missing.push('riders.' + rider.car + '.competition_points');
      if (rider.style === 'UNKNOWN') missing.push('riders.' + rider.car + '.style');
    }
    const families = [
      ['pace_fade', ['FRONT_LEADER_PACE_FADE']], ['late_sprint', ['LATE_SPRINT_OVERTAKE']],
      ['follower_sashi', ['FOLLOWER_SASHI_SCENARIO']], ['counterattack', ['CHALLENGER_EARLY_COUNTER', 'CHALLENGER_MAKURI']],
    ];
    return {
      schema: UNIVERSE_SCHEMA, race_id: baseline.race_id, source_as_of: baseline.source_as_of, cutoff: baseline.published_cutoff_at,
      source_prediction_sha256: baseline.prediction_sha256, source_facts_sha256: baseline.source_facts_sha256,
      cars: riders.map(rider => rider.car), evidence_kind: 'canonical_b_orders', candidate_origin: 'canonical_projection_v1',
      source_status: { lineup: source.competition === 'GIRLS' ? 'not_applicable_girls' : 'published_prediction', required_missing: missing, conflicting_fields: [] },
      scenarios: baseline.B.six_phase_scenarios.map(scenario => {
        const actions = scenario.six_phases.flatMap(phase => phase.hypothesis_actions);
        const family = families.find(([, labels]) => labels.some(label => actions.includes(label)))?.[0] || null;
        return { id: scenario.scenario_id, role: family ? 'counter' : 'main', counter_family: family, phases: scenario.six_phases,
          goal_candidates: { '3t': [scenario.projected_3ren_tan], '2t': [scenario.projected_3ren_tan.slice(0, 2)] }, research_weight: scenario.relative_research_weight.toFixed(12) };
      }),
    };
  }
  function authoredPredictionBody(raw) {
    const value = Object.fromEntries(Object.entries(raw).filter(([key]) => key !== 'confidence_assessment'));
    if (Object.hasOwn(value, 'rollover')) value.rollover = authoredPredictionBody(value.rollover);
    return value;
  }
  function freezeAssessment(value) {
    if (value !== null && typeof value === 'object') {
      for (const child of Object.values(value)) freezeAssessment(child);
      Object.freeze(value);
    }
    return value;
  }
  async function validate(bundle, context) {
    need(exact(bundle, ['schema', 'rules_version', 'race_id', 'assessed_at', 'cutoff', 'source_prediction_sha256', 'source_facts_sha256', 'scenario_universe_sha256', 'evaluations']));
    need(bundle.schema === SCHEMA && bundle.rules_version === RULES && bundle.race_id === context.raceId && bundle.cutoff === context.cutoff);
    const assessed = timestampMicros(bundle.assessed_at), generated = timestampMicros(context.generatedAt), cutoff = timestampMicros(bundle.cutoff), sourceAt = timestampMicros(context.universe.source_as_of);
    need(assessed !== null && generated !== null && cutoff !== null && sourceAt !== null && sourceAt <= generated && generated <= assessed && cutoff - assessed >= 65000000n);
    if (context.sealedAt !== undefined) {
      const sealed = timestampMicros(context.sealedAt);need(sealed !== null && assessed <= sealed && cutoff - sealed >= 65000000n);
    }
    for (const name of ['source_prediction_sha256', 'source_facts_sha256', 'scenario_universe_sha256']) need(hex(bundle[name]));
    need(bundle.source_prediction_sha256 === context.predictionSha256 && bundle.source_facts_sha256 === context.universe.source_facts_sha256);
    const ids = checkedUniverse(context.universe);
    need(context.universe.race_id === bundle.race_id && context.universe.cutoff === bundle.cutoff && await digest(context.universe) === bundle.scenario_universe_sha256);
    need(exact(bundle.evaluations, Object.keys(context.evaluations)));
    for (const [name, expected] of Object.entries(context.evaluations)) {
      const entry = bundle.evaluations[name];
      need(exact(entry, ['grade', 'rank', 'market', 'strategy', 'tickets_sha256', 'metrics', 'reasons', 'limitations']) && GRADES.has(entry.grade) && entry.rank === GRADES.get(entry.grade));
      need(entry.market === expected.market && entry.strategy === expected.strategy && hex(entry.tickets_sha256));
      need(await digest(ticketArrays(expected.tickets, entry.market, context.universe.cars)) === entry.tickets_sha256);
      const metrics = entry.metrics;
      need(exact(metrics, ['scenario_count', 'axis_cars', 'axis_top2_share', 'pair_top4_share', 'triple_top6_share', 'scenario_coverage', 'major_uncovered_ids', 'evidence_kind', 'weight_basis', 'late_phase_axis_presence']));
      need(Number.isInteger(metrics.scenario_count) && metrics.scenario_count === ids.size && metrics.scenario_count <= 128 && Array.isArray(metrics.axis_cars) && metrics.axis_cars.length <= 2 && unique(metrics.axis_cars) && metrics.axis_cars.every(car => context.universe.cars.includes(car)));
      for (const key of ['axis_top2_share', 'pair_top4_share', 'triple_top6_share', 'scenario_coverage', 'late_phase_axis_presence']) need(metrics[key] === null || ratio(metrics[key]));
      if (entry.rank === 0) need(metrics.axis_cars.length === 0 && ['axis_top2_share', 'pair_top4_share', 'triple_top6_share', 'scenario_coverage', 'late_phase_axis_presence'].every(key => metrics[key] === null) && Array.isArray(metrics.major_uncovered_ids) && metrics.major_uncovered_ids.length === 0);
      else {
        need(['axis_top2_share', 'pair_top4_share', 'scenario_coverage'].every(key => metrics[key] !== null) && (entry.market !== '3t' || metrics.triple_top6_share !== null));
        need(context.universe.scenarios.every(scenario => scenario.phases.length === 6 && (typeof scenario.phases[0] === 'string' || scenario.phases.every((phase, index) => phase.phase === PHASES[index])) && Object.hasOwn(scenario.goal_candidates, entry.market)));
        const status = context.universe.source_status;
        need(status.lineup !== 'unknown' && status.required_missing.length === 0 && status.conflicting_fields.length === 0);
      }
      if (entry.market === '2t') need(metrics.triple_top6_share === null);
      need(Array.isArray(metrics.major_uncovered_ids) && unique(metrics.major_uncovered_ids) && metrics.major_uncovered_ids.every(id => ids.has(id)));
      if (entry.rank > 0) {
        const accepted = V1_GRADE_CONSTRAINTS.find(([rank, axis, pair, triple, coverage]) => metrics.axis_top2_share >= axis && metrics.pair_top4_share >= pair && (entry.market === '2t' || metrics.triple_top6_share >= triple) && metrics.scenario_coverage >= coverage && (rank < 3 || metrics.major_uncovered_ids.length === 0));
        need(entry.rank === (accepted ? accepted[0] : 1));
      }
      need(metrics.evidence_kind === context.universe.evidence_kind && metrics.weight_basis === (context.universe.evidence_kind === 'canonical_b_orders' ? 'canonical_relative_research' : 'equal_scenarios'));
      need(Array.isArray(entry.reasons) && entry.reasons.length > 0 && entry.reasons.length <= 128);
      for (const reason of entry.reasons) need(exact(reason, ['code', 'message', 'scenario_ids']) && bounded(reason.code, 120) && /^[A-Z][A-Z0-9_]*$/.test(reason.code) && bounded(reason.message, 2000) && Array.isArray(reason.scenario_ids) && unique(reason.scenario_ids) && reason.scenario_ids.every(id => ids.has(id)));
      need(Array.isArray(entry.limitations) && entry.limitations.length > 0 && entry.limitations.length <= 32 && entry.limitations.every(value => bounded(value, 2000)));
      if (context.universe.candidate_origin === 'legacy_ticket_links') need(entry.rank === 0);
    }
    freezeAssessment(bundle);
    verified.add(bundle);
    return bundle;
  }
  async function validateBaseline(bundle, baseline, { source, sealedAt, raceId = baseline?.race_id } = {}) {
    need(record(baseline) && baseline.schema === 'RACE_AI_KEIRIN_AUTOMATIC_MARKS_AND_SIX_PHASE_V1' && baseline.race_id === raceId && hex(baseline.prediction_sha256) && hex(baseline.source_facts_sha256));
    const universe = universeFromBaseline(baseline, source);
    return validate(bundle, { raceId, cutoff: baseline.published_cutoff_at, generatedAt: baseline.generated_at, sealedAt, predictionSha256: baseline.prediction_sha256, universe,
      evaluations: Object.fromEntries(['A', 'B'].map(name => [name, { market: '3t', strategy: 'normal', tickets: baseline[name]?.ranked_tickets }])) });
  }
  async function validateAuthored(raw, { raceId, market, strategy }) {
    const keys = ['race_id', 'analysis_created_at', 'deadline_jst', 'market', 'strategy', 'headline', 'reason', 'risk', 'tickets', 'scenarios', 'confidence_universe', 'confidence_assessment'];
    if (strategy === 'rollover') { keys.push('eligible');need(raw.eligible === true); }
    if (Object.hasOwn(raw, 'rollover')) { keys.push('rollover');need(market === '2t' && strategy === 'normal'); }
    need(exact(raw, keys) && raw.race_id === raceId && raw.market === market && raw.strategy === strategy);
    for (const field of ['headline', 'reason', 'risk']) need(bounded(raw[field], 2000));
    need(Array.isArray(raw.tickets) && raw.tickets.length > 0 && raw.tickets.every(ticket => exact(ticket, ['combo', 'role']) && bounded(ticket.role, 30)));
    const universe = raw.confidence_universe;
    need(record(universe) && universe.evidence_kind === 'authored_goals' && universe.candidate_origin === 'independent_preselection_v1');
    checkedUniverse(universe);
    need(raw.confidence_assessment?.assessed_at === raw.analysis_created_at && canonical(raw.scenarios) === canonical(universe.scenarios.map(scenario => ({ scenario_id: scenario.id, six_phases: scenario.phases }))));
    if (Object.hasOwn(raw, 'rollover')) {
      await validateAuthored(raw.rollover, { raceId, market: '2t', strategy: 'rollover' });
      need(canonical(raw.rollover.confidence_universe) === canonical(universe) && timestampMicros(raw.rollover.analysis_created_at) <= timestampMicros(raw.analysis_created_at));
    }
    return validate(raw.confidence_assessment, { raceId, cutoff: raw.deadline_jst, generatedAt: raw.analysis_created_at, predictionSha256: await digest(authoredPredictionBody(raw)), universe,
      evaluations: { selected: { market, strategy, tickets: raw.tickets } } });
  }

  return { normalize, displayLabel, matches, predictionMatches, selected, validate, validateBaseline, validateAuthored, universeFromBaseline, authoredPredictionBody, canonical, digest, timestamp, SCHEMA, RULES, UNIVERSE_SCHEMA };
});

/* Checked comparison-B probabilities. This module never changes saved tickets or grades. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.RaceKeirinJointForecast = factory();
})(typeof window === 'object' ? window : globalThis, function () {
  'use strict';

  const FULL = 'RACE_AI_KEIRIN_JOINT_FORECAST_V1';
  const PROJECTION = 'RACE_AI_KEIRIN_JOINT_PROJECTION_V1';
  const TOLERANCE = 1e-8;
  const checked = new WeakMap();
  const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const need = condition => { if (!condition) throw new Error('KEIRIN_JOINT_FORECAST_INVALID'); };
  const hash = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
  const text = (value, max) => typeof value === 'string' && value.trim().length > 0 && value.length <= max;
  const probability = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1;
  const close = (a, b) => Math.abs(a - b) <= TOLERANCE;
  const sum = values => values.reduce((total, value) => total + value, 0);
  const field = cars => Array.isArray(cars) && cars.length >= 3 && cars.length <= 9 &&
    new Set(cars).size === cars.length && cars.every(car => Number.isInteger(car) && car >= 1 && car <= 9);
  const sameField = (a, b) => field(a) && field(b) && a.length === b.length && a.every(car => b.includes(car));
  const escape = value => String(value).replace(/[&<>"']/g, character =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);

  function timestamp(value) {
    if (typeof value !== 'string') return null;
    const parts = /^(\d{4}-\d{2}-\d{2})T(\d\d):(\d\d):(\d\d)(?:\.(\d{1,6}))?(Z|[+-]\d\d:\d\d)$/.exec(value);
    if (!parts || Number(parts[2]) > 23 || Number(parts[3]) > 59 || Number(parts[4]) > 59) return null;
    const midnight = Date.parse(parts[1] + 'T00:00:00Z'), milliseconds = Date.parse(value);
    if (!Number.isFinite(midnight) || !Number.isFinite(milliseconds) ||
      new Date(midnight).toISOString().slice(0, 10) !== parts[1]) return null;
    // Preserve Python's six-digit clocks at the cutoff; Date.parse alone drops microseconds.
    return BigInt(milliseconds) * 1000n + BigInt((parts[5] || '').padEnd(6, '0').slice(3));
  }

  function events(rows, places, cars, maximum, complete) {
    need(Array.isArray(rows) && rows.length <= maximum && (!complete || rows.length === maximum));
    const seen = new Set();
    for (const row of rows) {
      need(object(row) && Array.isArray(row.order) && row.order.length === places &&
        new Set(row.order).size === places && row.order.every(car => Number.isInteger(car) && cars.includes(car)) &&
        probability(row.probability));
      const key = row.order.join('-');
      need(!seen.has(key));
      seen.add(key);
    }
    if (complete) need(close(sum(rows.map(row => row.probability)), 1));
    return rows;
  }

  function riders(record) {
    const cars = record.cars, n = cars.length;
    need(Array.isArray(record.riders) && record.riders.length === n);
    const byCar = new Map(), registrations = new Set();
    for (const rider of record.riders) {
      need(object(rider) && Number.isInteger(rider.car) && cars.includes(rider.car) && !byCar.has(rider.car) &&
        text(rider.name, 200) && (rider.registration === null ||
          typeof rider.registration === 'string' && /^\d{6}$/.test(rider.registration)));
      if (rider.registration !== null) {
        need(!registrations.has(rider.registration));
        registrations.add(rider.registration);
      }
      const ranks = rider.rank_probabilities;
      need(Array.isArray(ranks) && ranks.length === n && ranks.every(probability) && close(sum(ranks), 1));
      for (const name of ['top2_probability', 'top3_probability', 'outside_top3_probability']) need(probability(rider[name]));
      need(close(rider.top2_probability, sum(ranks.slice(0, 2))) &&
        close(rider.top3_probability, sum(ranks.slice(0, 3))) &&
        close(rider.outside_top3_probability, sum(ranks.slice(3))));
      const mode = ranks.reduce((best, p, index) => p > ranks[best] ? index : best, 0) + 1;
      need(Number.isInteger(rider.most_likely_rank) && rider.most_likely_rank === mode &&
        typeof rider.expected_rank === 'number' && Number.isFinite(rider.expected_rank) &&
        rider.expected_rank >= 1 && rider.expected_rank <= n &&
        close(rider.expected_rank, sum(ranks.map((p, index) => p * (index + 1)))));
      byCar.set(rider.car, rider);
    }
    for (let place = 0; place < n; place++) need(close(sum(record.riders.map(rider => rider.rank_probabilities[place])), 1));
    return byCar;
  }

  function completeLaw(record, byCar) {
    const n = record.cars.length;
    const triples = events(record.trifectas, 3, record.cars, n * (n - 1) * (n - 2), true);
    const pairs = events(record.exactas, 2, record.cars, n * (n - 1), true);
    const mass = new Map(record.cars.map(car => [car, [0, 0, 0]])), pairMass = new Map();
    for (const row of triples) {
      row.order.forEach((car, place) => { mass.get(car)[place] += row.probability; });
      const key = row.order.slice(0, 2).join('-');
      pairMass.set(key, (pairMass.get(key) || 0) + row.probability);
    }
    for (const row of pairs) need(close(row.probability, pairMass.get(row.order.join('-'))));
    for (const car of record.cars) for (let place = 0; place < 3; place++) {
      need(close(byCar.get(car).rank_probabilities[place], mass.get(car)[place]));
    }
  }

  function projectionLaw(record, byCar) {
    need(hash(record.source_joint_sha256) && !Object.hasOwn(record, 'trifectas') &&
      !Object.hasOwn(record, 'exactas') && object(record.ranked_markets));
    for (const [market, places, maximum] of [['3t', 3, 8], ['2t', 2, 4]]) {
      const rows = events(record.ranked_markets[market], places, record.cars, maximum, false);
      need(sum(rows.map(row => row.probability)) <= 1 + TOLERANCE);
      const mass = new Map(record.cars.map(car => [car, Array(places).fill(0)]));
      rows.forEach((row, index) => {
        if (index) need(row.probability <= rows[index - 1].probability);
        row.order.forEach((car, place) => {
          need(row.probability <= byCar.get(car).rank_probabilities[place] + TOLERANCE);
          mass.get(car)[place] += row.probability;
        });
      });
      // Selected events are disjoint. Their partial mass must also fit each marginal.
      for (const car of record.cars) {
        const selected = mass.get(car), rider = byCar.get(car);
        selected.forEach((p, place) => need(p <= rider.rank_probabilities[place] + TOLERANCE));
        need(sum(selected.slice(0, 2)) <= rider.top2_probability + TOLERANCE &&
          sum(selected) <= rider.top3_probability + TOLERANCE);
      }
    }
    const selectedTriples=new Map();
    for(const row of record.ranked_markets['3t']){
      const key=row.order.slice(0,2).join('-');
      selectedTriples.set(key,(selectedTriples.get(key)||0)+row.probability);
    }
    for(const row of record.ranked_markets['2t'])need(row.probability+TOLERANCE>=(selectedTriples.get(row.order.join('-'))||0));
  }

  function validateForecast(record, binding) {
    need(object(record));
    checked.delete(record);
    need([FULL, PROJECTION].includes(record.schema) && object(binding) &&
      typeof record.race_id === 'string' && /^20\d{10}$/.test(record.race_id) &&
      record.race_id === binding.race_id && sameField(record.cars, binding.cars) &&
      hash(record.input_sha256) && hash(record.source_packet_sha256) &&
      record.source_packet_sha256 === binding.source_packet_sha256 &&
      record.source_forecast_generated_at === binding.source_forecast_generated_at &&
      text(record.model_id, 200) && text(record.model_version, 200) &&
      ['PROSPECTIVE_RESEARCH', 'RETROSPECTIVE_RESEARCH'].includes(record.scope) &&
      record.premise === 'ALL_FINISH_NO_TIES' && record.calibration_status === 'UNVALIDATED');
    const generated = timestamp(record.generated_at), cutoff = timestamp(record.cutoff_at);
    const asOf = timestamp(record.source_as_of), sourceGenerated = timestamp(record.source_forecast_generated_at);
    need(generated !== null && cutoff !== null && asOf !== null && sourceGenerated !== null &&
      record.cutoff_at===binding.cutoff_at && record.source_as_of===binding.source_as_of &&
      asOf <= sourceGenerated && sourceGenerated <= generated);
    const raceDate=record.race_id.slice(0,4)+'-'+record.race_id.slice(4,6)+'-'+record.race_id.slice(6,8);
    const raceDay=Date.parse(raceDate+'T00:00:00Z');
    need(Number.isFinite(raceDay)&&new Date(raceDay).toISOString().slice(0,10)===raceDate);
    const cutoffDay=Date.parse(new Date(Number(cutoff/1000n)+9*3600000).toISOString().slice(0,10)+'T00:00:00Z');
    need(cutoffDay>=raceDay&&cutoffDay<=raceDay+86400000);
    need(record.scope === (generated < cutoff ? 'PROSPECTIVE_RESEARCH' : 'RETROSPECTIVE_RESEARCH'));
    if (record.scope === 'PROSPECTIVE_RESEARCH') need(generated < cutoff && asOf < cutoff && sourceGenerated < cutoff);
    const byCar = riders(record);
    if (record.schema === FULL) completeLaw(record, byCar);
    else projectionLaw(record, byCar);
    // Keep only checked display fields in private memory. Caller-owned source bytes stay untouched.
    const snapshot = {};
    for (const key of ['schema', 'race_id', 'model_id', 'model_version', 'scope', 'generated_at',
      'cutoff_at', 'source_as_of', 'source_forecast_generated_at', 'input_sha256',
      'source_packet_sha256', 'source_joint_sha256']) snapshot[key] = record[key];
    snapshot.riders = new Map([...byCar].map(([car, rider]) => [car, {
      car, name: rider.name, registration: rider.registration, rank_probabilities: rider.rank_probabilities.slice(),
      top2_probability: rider.top2_probability, top3_probability: rider.top3_probability,
      outside_top3_probability: rider.outside_top3_probability,
      most_likely_rank: rider.most_likely_rank, expected_rank: rider.expected_rank
    }]));
    checked.set(record, snapshot);
    return record;
  }

  function renderForecast(record, car) {
    const snapshot = checked.get(record), rider = snapshot?.riders.get(car);
    need(snapshot && Number.isInteger(car) && rider);
    const percent = p => (p * 100).toFixed(1) + '%';
    const clock = (label, value) => '<p>' + label + ' <time datetime="' + escape(value) + '">' + escape(value) + '</time></p>';
    const summary = [
      ['2着以内', percent(rider.top2_probability)], ['3着以内', percent(rider.top3_probability)],
      ['着外（4着以下）', percent(rider.outside_top3_probability)],
      ['最頻着順', rider.most_likely_rank + '着'], ['期待着順', rider.expected_rank.toFixed(2)],
      ['登録番号', rider.registration || '未取得']
    ];
    const projection = snapshot.schema === PROJECTION;
    return '<section class="kn-joint-forecast" aria-label="' +
      escape(car + '番の比較B・着順確率') + '" data-joint-race="' + escape(snapshot.race_id) + '">' +
      '<h3>' + escape(car + '番 ' + rider.name) + ' · 比較Bの着順確率</h3>' +
      '<p class="kn-joint-scope">' + (snapshot.scope === 'PROSPECTIVE_RESEARCH' ?
        '締切前に生成した研究予測' : '締切後の参考解析・事後研究') + ' · 確率は未校正</p>' +
      '<p>全員完走・同着なしを条件とする確率です。欠場・失格・落車・同着を含む無条件の確率ではありません。</p>' +
      '<p>比較Bの新しい解析です。保存済みの旧買い目とは別です。信頼度の格上げには使用していません。</p>' +
      '<ol class="kn-joint-ranks">' + rider.rank_probabilities.map((p, index) =>
        '<li><span>' + (index + 1) + '着</span><meter min="0" max="1" value="' + p +
        '" aria-label="' + (index + 1) + '着の予測確率">' + percent(p) + '</meter><span>' + percent(p) + '</span></li>').join('') +
      '</ol><dl class="kn-joint-summary">' +
      summary.map(([label, value]) => '<div><dt>' + label + '</dt><dd>' + escape(value) + '</dd></div>').join('') + '</dl>' +
      '<details class="kn-joint-source"><summary>モデル・出典・予想時点</summary><p>モデル ' + escape(snapshot.model_id) +
      ' · 版 ' + escape(snapshot.model_version) + '</p>' + clock('比較Bの生成', snapshot.generated_at) +
      clock('資料の基準', snapshot.source_as_of) + clock('元資料の予想時点', snapshot.source_forecast_generated_at) +
      clock('掲載締切', snapshot.cutoff_at) + '<p>元資料SHA256 ' + escape(snapshot.source_packet_sha256) +
      '</p><p>比較B入力SHA256 ' + escape(snapshot.input_sha256) + '</p>' + (projection ?
        '<p>元同時分布SHA256 ' + escape(snapshot.source_joint_sha256) + '</p><p>同時分布の出典ハッシュに結んだ派生表示です。' +
        'この画面は予想原本を独立認証しません。選択した上位買い目を100%へ正規化していません。</p>' :
        '<p>全三連単・二車単・上位3着の周辺確率を同じ分布として検査しました。出典資料の真正性の独立認証は別途必要です。</p>') +
      '</details></section>';
  }

  return { validateForecast, renderForecast };
});

/* Descriptive, separately timestamped historical samples for an unchanged race card. */
(function(root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.RaceKeirinRiderHistory = factory();
})(typeof window === 'object' ? window : globalThis, function() {
  'use strict';
  const periods = {all:null, '3_years':36, '1_year':12, '6_months':6, '4_months':4, '3_months':3, '1_month':1};
  const labels = {all:'収録全期間', '3_years':'3年', '1_year':'1年', '6_months':'6か月', '4_months':'4か月', '3_months':'3か月', '1_month':'1か月'};
  const starts = [30, 20, 10, 5];
  const ranks = Array.from({length:9}, (_,i)=>String(i+1));
  const required = ['observed_count','missing_finish_count','finish_counts','finish_rates','first_observed_day','latest_observed_day'];
  const need = ok => { if (!ok) throw Error('KEIRIN_RIDER_HISTORY_INVALID'); };
  const exact = (value, keys) => value && typeof value === 'object' && !Array.isArray(value) &&
    Object.keys(value).length === keys.length && keys.every(key=>Object.hasOwn(value,key));
  const sha = v => typeof v === 'string' && /^[0-9a-f]{64}$/.test(v);
  const registration = v => typeof v === 'string' && /^\d{6}$/.test(v) && v !== '000000';
  const count = v => Number.isSafeInteger(v) && v >= 0;
  const normalized = name => typeof name === 'string' ? name.normalize('NFKC').replace(/\s/g,'') : '';
  const admitted = new WeakSet();

  function monthsBefore(end, months) {
    const day = new Date(end+'T00:00:00Z'), number = day.getUTCDate();
    day.setUTCDate(1);
    day.setUTCMonth(day.getUTCMonth()-months+1, 0);
    day.setUTCDate(Math.min(number,day.getUTCDate()));
    return day.toISOString().slice(0,10);
  }
  function validateSample(sample, end, first, limit, day) {
    need(exact(sample, required.concat(limit ? ['unfilled_slots','tied_boundary_observations'] : ['start_day_inclusive'])));
    const n = sample.observed_count;
    need(count(n) && sample.missing_finish_count === null && exact(sample.finish_counts,ranks));
    need(ranks.every(rank=>count(sample.finish_counts[rank])) && ranks.reduce((a,rank)=>a+sample.finish_counts[rank],0)===n);
    if (n) {
      need(exact(sample.finish_rates,ranks) && ranks.every(rank=>{
        const v=sample.finish_rates[rank];
        return typeof v==='number' && v>=0 && v<=1 && Math.abs(v-sample.finish_counts[rank]/n)<=1e-12;
      }));
      need(day(sample.first_observed_day) && day(sample.latest_observed_day) &&
        sample.first_observed_day<=sample.latest_observed_day && sample.latest_observed_day<end &&
        (first===null || sample.first_observed_day>=first));
    } else {
      need(sample.finish_rates===null && sample.first_observed_day===null && sample.latest_observed_day===null);
    }
    if (limit) need(n<=limit && sample.unfilled_slots===limit-n && count(sample.tied_boundary_observations));
    else need(sample.start_day_inclusive===first);
  }
  function validateHistory(h, person, date, day) {
    need(exact(h,['registration','as_of_exclusive','periods','last_starts']) && h.registration===person.registration &&
      day(h.as_of_exclusive) && h.as_of_exclusive<=date && exact(h.periods,Object.keys(periods)) && exact(h.last_starts,starts));
    const all=h.periods.all;
    for (const [name,months] of Object.entries(periods)) {
      validateSample(h.periods[name],h.as_of_exclusive,months===null?null:monthsBefore(h.as_of_exclusive,months),null,day);
    }
    for(const n of starts) validateSample(h.last_starts[n],h.as_of_exclusive,null,n,day);
    for(const samples of [Object.keys(periods).map(name=>h.periods[name]),
                          [all,...starts.map(n=>h.last_starts[n])]]) {
      for(let i=1;i<samples.length;i++) {
        const large=samples[i-1],small=samples[i];
        need(ranks.every(r=>small.finish_counts[r]<=large.finish_counts[r]));
        if(small.observed_count) need(small.latest_observed_day===large.latest_observed_day && small.first_observed_day>=large.first_observed_day);
      }
    }
  }
  function freeze(value) {
    if(value && typeof value==='object' && !Object.isFrozen(value)) {
      Object.values(value).forEach(freeze);Object.freeze(value);
    }
    return value;
  }
  function attach(doc, rows, date, rosterSha, clock) {
    const meta=['generated_at','knowledge_as_of','source_roster_sha256','registry_sha256','archive_sha256s','predictive_model_changed'];
    need(exact(doc,['schema',...meta,'races']) && doc.schema==='RACE_AI_KEIRIN_RIDER_HISTORY_SUPPLEMENT_V1' &&
      doc.predictive_model_changed===false && clock.utc(doc.generated_at) && clock.utc(doc.knowledge_as_of) &&
      clock.instantMicros(doc.knowledge_as_of)<=clock.instantMicros(doc.generated_at) && sha(rosterSha) &&
      doc.source_roster_sha256===rosterSha && sha(doc.registry_sha256) && Array.isArray(doc.archive_sha256s) &&
      doc.archive_sha256s.length===2 && doc.archive_sha256s.every(sha) && new Set(doc.archive_sha256s).size===2 &&
      Array.isArray(doc.races) && doc.races.length<=300);
    const knowledgeDayJST=new Date(Date.parse(doc.knowledge_as_of)+9*3600000).toISOString().slice(0,10);
    const byRace=new Map(rows.map(row=>[row.id,row])),seen=new Set();
    for(const race of doc.races) {
      need(exact(race,['race_id','riders']) && byRace.has(race.race_id) && !seen.has(race.race_id));
      seen.add(race.race_id);
      const row=byRace.get(race.race_id), observed=new Set(), ids=new Set();
      need(Array.isArray(race.riders) && race.riders.length>=3 && race.riders.length===row.riders.length);
      for(const person of race.riders) {
        need(exact(person,['car','name','registration','history']) && Number.isInteger(person.car) && !observed.has(person.car) &&
          registration(person.registration) && !ids.has(person.registration) && normalized(person.name));
        const rider=row.riders.find(p=>p.number===person.car),joint=row.jointForecast?.riders.find(p=>p.car===person.car);
        need(rider && normalized(rider.name)===normalized(person.name) &&
          [rider,joint].every(p=>!p || p.registration==null || p.registration===person.registration));
        validateHistory(person.history,person,date,clock.day);
        const latest=person.history.periods.all.latest_observed_day;
        need(latest===null || latest<=knowledgeDayJST);
        observed.add(person.car);ids.add(person.registration);
      }
      const supplement=Object.fromEntries(meta.map(key=>[key,doc[key]]));
      supplement.race_id=race.race_id;supplement.riders=race.riders;
      const cutoff=clock.instantMicros(row.cutoff);
      supplement.generated_at_or_after_cutoff=cutoff!==null&&clock.instantMicros(doc.generated_at)>=cutoff;
      const snapshot=freeze(JSON.parse(JSON.stringify(supplement)));
      admitted.add(snapshot);row.riderHistory=snapshot;row.riderHistoryVersions=[];
    }
  }
  function render(row, car) {
    const s=row.riderHistory;
    if(!s || !admitted.has(s)) return '';
    const p=s.riders.find(person=>person.car===car),r=row.riders.find(person=>person.number===car);
    if(!p || !r || s.race_id!==row.id || normalized(p.name)!==normalized(r.name) ||
      (r.registration!=null && p.registration!==r.registration))return '';
    const h=p.history, all=h.periods.all;
    function sample(label,item) {
      const n=item.observed_count;
      const pct=places=>n?(100*ranks.slice(0,places).reduce((v,rank)=>v+item.finish_counts[rank],0)/n).toFixed(1)+'%':'—';
      const placeCounts=ranks.map(rank=>item.finish_counts[rank]).join(' / ');
      const dates=n?item.first_observed_day+' ～ '+item.latest_observed_day:'観測なし';
      return '<tr><th scope="row">'+label+'</th><td>'+n+'走</td><td>'+pct(1)+'</td><td>'+pct(2)+'</td><td>'+pct(3)+'</td><td>'+placeCounts+'</td><td>'+dates+'</td></tr>';
    }
    const rows=Object.keys(periods).map(key=>sample(labels[key],h.periods[key]))
      .concat(starts.map(n=>sample('直近'+n+'走',h.last_starts[n]))).join('');
    const short=all.observed_count && all.first_observed_day>h.periods['3_years'].start_day_inclusive;
    const timing=s.generated_at_or_after_cutoff?'（掲載締切後に作成）':'';
    return '<details class="kn-details kn-rider-history"><summary>長期・直近の着順履歴</summary><p>履歴の登録番号 '+p.registration+
      '。集計対象は '+h.as_of_exclusive+' より前の確認済み着順です。勝率・連対率・3連対率は各行の観測走数を分母にした実績です。</p>'+
      '<p>資料の取得基準 '+s.knowledge_as_of+' · 履歴集計の作成 '+s.generated_at+timing+'。保存済みの予測確率・買い目は別に表示します。</p>'+
      '<div class="kn-table-scroll"><table><thead><tr><th>対象</th><th>観測走数</th><th>1着</th><th>2着以内</th><th>3着以内</th><th>1～9着の件数</th><th>観測日範囲</th></tr></thead><tbody>'+rows+'</tbody></table></div>'+
      '<p>資料に含まれない出走の件数は不明です。直近の集計は確認できた着順に限り、同日の先後が判別できない境界を除きます。'+
      (short?'この選手で確認できた履歴の範囲は3年未満です。':'')+'</p></details>';
  }
  return {attach,render};
});

/* Owner-provided Site view adapter. Original/revised/research records stay separate. */
(function(root,factory){
  if(typeof module==='object'&&module.exports)module.exports=factory(require('./keirin-note-source/staking_flexible.js'),require('./confidence.js'),require('./keirin-joint-forecast.js'),require('./keirin-rider-history.js'));
  else root.RaceKeirinNote=factory(root.KeirinStaking,root.RaceKeirinConfidence,root.RaceKeirinJointForecast,root.RaceKeirinRiderHistory);
})(typeof window==='object'?window:globalThis,function(staking,confidence,joint,history){
  'use strict';
  const SCHEMA='RACE_AI_KEIRIN_NOTE_VIEW_V1',OUTER='RACE_AI_SAVED_WEB_VIEW_V1';
  const LIMIT=64*1024*1024,encoder=new TextEncoder();
  const record=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
  const exact=(value,keys)=>record(value)&&Object.keys(value).sort().join(',')===keys.slice().sort().join(',');
  const fail=()=>{throw new Error('KEIRIN_NOTE_INVALID');};
  const need=v=>{if(!v)fail();};
  const hex=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
  const day=v=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(v)&&Number.isFinite(Date.parse(v+'T00:00:00Z'))&&new Date(v+'T00:00:00Z').toISOString().slice(0,10)===v;
  const text=(v,max=2000)=>typeof v==='string'&&v.length<=max?v:'';
  const rid=v=>typeof v==='string'&&/^20\d{10}$/.test(v);
  const sameKeys=(v,keys)=>record(v)&&Object.keys(v).sort().join(',')===keys.split(',').sort().join(',');
  const utc=v=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}T\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(v)&&clock(v.slice(0,10),v)!==null;
  const canonical=v=>JSON.stringify(v&&typeof v==='object'?Array.isArray(v)?v.map(x=>JSON.parse(canonical(x))):Object.fromEntries(Object.keys(v).sort().map(k=>[k,JSON.parse(canonical(v[k]))])):v);
  const RESULT_SCHEMA='RACE_AI_KEIRIN_NOTE_RESEARCH_RESULTS_V1',CONSENSUS_SCHEMA='RACE_AI_KEIRIN_INDEPENDENT_SECONDARY_RESULT_MATCH_V1';
  const MATCHED='SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL';
  const RESULT_STATES=new Set([MATCHED,'HOLD_SECONDARY_RESULT_DISAGREEMENT','HOLD_NO_PUBLISHED_CUTOFF_HINT','HOLD_PROVIDER_DENIED_OR_RATE_LIMITED_STOP','HOLD_RESULT_SOURCE_UNAVAILABLE','HOLD_RESULT_SOURCE_UNVERIFIED','HOLD_RESULT_DAY_MISMATCH','HOLD_RESULT_RACE_MISMATCH','HOLD_SPECIAL_REFUND_OR_TIE_REQUIRES_OFFICIAL','HOLD_CONFLICTING_SOURCE_RESULT','PENDING_RESULT_NOT_PUBLISHED','PENDING_RESULT_NOT_FINAL']);
  const NATIONWIDE_SCHEMA='RACE_AI_KEIRIN_NATIONWIDE_FORECAST_VIEW_V1';
  const NATIONAL_STATES=new Set('WAITING_SOURCE_CAPTURE UNSUPPORTED_CLASS_OR_ROUND PUBLISHED_RESULT_NO_PRE_CUTOFF_ORIGINAL FROZEN_ORIGINAL_PRESERVED SOURCE_CAPTURE_BUDGET_PENDING CUTOFF_MARGIN_INSUFFICIENT BASELINE_SOURCE_UNVERIFIED PROVIDER_STOPPED SOURCE_UNAVAILABLE A_B_ARCHIVED_AWAITING_INDEPENDENT_READBACK A_B_AUTHENTICATED_PRE_CUTOFF ORIGIN_PROOF_PENDING FROZEN_ARCHIVE_UNVERIFIED RACE_DISAPPEARED_FROM_CURRENT_LIST'.split(' '));
  const CONDITION_STATES=new Set('HISTORY_NOT_COLLECTED HISTORY_SOURCE_UNAVAILABLE HISTORY_UNVERIFIED INSUFFICIENT_CAPTURE_MARGIN CONDITIONED_ARCHIVED_AWAITING_READBACK CONDITIONED_AUTHENTICATED_PRE_CUTOFF CONDITIONED_ORIGIN_PROOF_PENDING CONDITIONED_ARCHIVE_UNVERIFIED NO_CONDITIONED_ORIGINAL'.split(' '));
  const apiCrypto=()=>globalThis.crypto?.subtle?globalThis.crypto:require('node:crypto').webcrypto;
  const digest=async v=>Array.from(new Uint8Array(await apiCrypto().subtle.digest('SHA-256',typeof v==='string'?encoder.encode(v):v)),n=>n.toString(16).padStart(2,'0')).join('');
  function safeUrl(value){
    try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password&&(!u.port||u.port==='443')&&['keirin.kdreams.jp','keirin.netkeiba.com','keirin.jp','www.keirin.jp','winticket.jp','www.winticket.jp','www.jma.go.jp','www.sponichi.co.jp','keirin.sponichi.co.jp'].includes(u.hostname)?u.href:null;}catch{return null;}
  }
  function mapRows(value){
    const a=Array.isArray(value)?value:record(value)&&Array.isArray(value.races)?value.races:[];
    const result=new Map();for(const row of a){need(record(row));const id=row.race_id||row.input?.race_id||row.output?.race_id;need(rid(id)&&!result.has(id)&&[row.race_id,row.input?.race_id,row.output?.race_id].every(value=>value===undefined||value===id));result.set(id,row);}return result;
  }
  function clock(date,value){
    if(typeof value!=='string'||!value)return null;
    const stamp=/^\d\d:\d\d$/.test(value)?date+'T'+value+':00+09:00':value;
    const parts=/^(\d{4}-\d{2}-\d{2})T(\d\d):(\d\d)(?::(\d\d))?(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.exec(stamp);
    if(!parts||!day(parts[1])||Number(parts[2])>23||Number(parts[3])>59||Number(parts[4]||0)>59)return null;
    const n=Date.parse(stamp);return Number.isFinite(n)?stamp:null;
  }
  function instantMicros(value){
    if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}T\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)$/.test(value)||!clock(value.slice(0,10),value))return null;
    const fraction=/\.(\d{1,6})(?:Z|[+-]\d\d:\d\d)$/.exec(value)?.[1]||'';
    return BigInt(Date.parse(value))*1000n+BigInt(fraction.padEnd(6,'0').slice(3));
  }
  function sameClock(left,right){const value=instantMicros(left);return value!==null&&value===instantMicros(right);}
  function checkedShadowVerification(packet, files){
    const fields=(value,names)=>record(value)&&Object.keys(value).length===names.length&&names.every(name=>Object.hasOwn(value,name));
    need(fields(packet,['schema','scope','source_site','source_commit','imported_at','dates','files','formal_model_admission','production_weight_switch','wagers_placed','shadow_verification_private_nonce']) &&
      packet.scope==='OWNER_MAC_SHADOW_VERIFICATION' && packet.source_site===null &&
      typeof packet.source_commit==='string' && /^[0-9a-f]{40}$/.test(packet.source_commit) &&
      packet.wagers_placed===false && packet.dates.length===1 && files.size===1);
    const nonce=packet.shadow_verification_private_nonce;
    need(typeof nonce==='string' && /^[A-Za-z0-9_-]{43}$/.test(nonce) &&
      b64(nonce.replaceAll('-','+').replaceAll('_','/')+'=',44).length===32);
    const dayKey=packet.dates[0],path='data/'+dayKey+'/shadow_verification.json';
    const value=files.get(path);
    need(value && fields(packet.files[path],['text','bytes','sha256']) && packet.files[path].bytes<=8192 && fields(value,
      ['schema','day_jst','race_id','verified_at','start_at','original','result','scores','tracking_learning','production_weights_promoted']) &&
      value.schema==='RACE_AI_KEIRIN_SHADOW_VERIFICATION_V1' && value.day_jst===dayKey &&
      rid(value.race_id) && value.race_id.startsWith(dayKey.replaceAll('-','')) &&
      /^(0[1-9]|1[0-2])$/.test(value.race_id.slice(-2)) &&
      value.tracking_learning==='HELD' && value.production_weights_promoted===false);
    const {original,result,scores}=value;
    need(fields(original,['sha256','archive_cipher_sha256','generated_at','cutoff_at']) &&
      fields(result,['evidence_sha256','observed_at','scope']) &&
      ['TWO_SOURCE_MATCHED_PODIUM_ONLY','OFFICIAL_COMPLETE_FINISH_RESEARCH'].includes(result.scope));
    const digests=[original.sha256,original.archive_cipher_sha256,result.evidence_sha256];
    need(digests.every(value=>hex(value) && value!=='0'.repeat(64)) && new Set(digests).size===digests.length);
    const clocks=[original.generated_at,original.cutoff_at,value.start_at,result.observed_at,value.verified_at,packet.imported_at].map(instantMicros);
    need(clocks.every(t=>t!==null));
    const [generated,cutoff,start,observed,verified,imported]=clocks;
    const jstDay=instant=>new Date(Date.parse(instant)+9*60*60*1000).toISOString().slice(0,10);
    need(jstDay(original.cutoff_at)===dayKey && jstDay(value.start_at)===dayKey &&
      generated<cutoff && cutoff<start && start<=observed && observed<=verified && verified<=imported);
    need(fields(scores,['trifecta','exacta']));
    for(const [market,points] of [['trifecta',4],['exacta',2]]){
      const score=scores[market];
      need(fields(score,['points','saved_hit','challenger_hit']) && score.points===points &&
        typeof score.saved_hit==='boolean' && typeof score.challenger_hit==='boolean');
    }
    return value;
  }
  function tickets(value,places,cars){
    if(value==null)return [];
    need(Array.isArray(value)&&value.length<=504);
    const seen=new Set();return value.map(item=>{
      const t=Array.isArray(item)?{combo:item.join('-'),role:'参考'}:item;
      need(record(t)&&typeof t.combo==='string'&&new RegExp('^[1-9](?:-[1-9]){'+(places-1)+'}$').test(t.combo));
      const numbers=t.combo.split('-').map(Number);
      need(new Set(numbers).size===places&&!seen.has(t.combo)&&(!cars.size||numbers.every(n=>cars.has(n))));seen.add(t.combo);
      return {...t,combo:t.combo,role:text(t.role,30)||'参考'};
    });
  }
  function binding(files,shas,cipherSha,date,name,legacy=false){
    const path=files.has('data/'+date+'/'+name)?'data/'+date+'/'+name:legacy&&files.has('data/'+name)?'data/'+name:null;
    return path?{cipherSha,fileSha256:shas.get(path),path}:null;
  }
  function inputSpans(text){
    // Hash the stored Python JSON bytes: parsing and stringifying would change
    // 80.0 into 80 and invalidate authentic originals. Walk JSON structure so
    // strings containing "input" cannot masquerade as an input member.
    need(typeof text==='string');let at=0;const spans=new Map();
    const space=()=>{while(/\s/.test(text[at]||'')&&at<text.length)at++;};
    function string(){const begin=at;need(text[at++]==='"');while(at<text.length){const c=text[at++];if(c==='"')return JSON.parse(text.slice(begin,at));if(c==='\\')at++;}fail();}
    function value(path,depth){
      need(depth<=32);space();const begin=at,c=text[at];
      if(c==='{'){
        at++;space();const keys=new Set();
        if(text[at]!=='}')for(;;){space();const key=string();need(!keys.has(key));keys.add(key);space();need(text[at++]===':');value([...path,key],depth+1);space();if(text[at]!==',')break;at++;}
        need(text[at++]==='}');
      }else if(c==='['){
        at++;space();let index=0;if(text[at]!==']')for(;;){value([...path,index++],depth+1);space();if(text[at]!==',')break;at++;}need(text[at++]==']');
      }else if(c==='"')string();
      else{while(at<text.length&&!/[\s,}\]]/.test(text[at]))at++;need(at>begin);}
      if(path.length===3&&path[0]==='races'&&Number.isInteger(path[1])&&path[2]==='input')spans.set(path[1],text.slice(begin,at));
    }
    value([],0);space();need(at===text.length);return spans;
  }
  async function jointSupplements(date,files,shas,rows,rawFiles){
    const path='data/'+date+'/',doc=files.get(path+'joint_forecasts.json');
    if(doc==null)return;
    const inputs=files.get(path+'comparison_inputs.json'),sourceSha=shas.get(path+'comparison_inputs.json');
    need(joint&&exact(doc,['schema','races'])&&doc.schema==='RACE_AI_KEIRIN_JOINT_FORECASTS_V1'&&Array.isArray(doc.races)&&doc.races.length<=300);
    need(exact(inputs,['schema','races'])&&inputs.schema==='RACE_AI_KEIRIN_COMPARISON_INPUTS_V1'&&Array.isArray(inputs.races)&&inputs.races.length<=300&&hex(sourceSha));
    const sources=mapRows(inputs),byId=new Map(rows.map(row=>[row.id,row])),seen=new Set();
    const spans=inputSpans(rawFiles[path+'comparison_inputs.json'].text),hashes=new Map();
    for(const [index,source] of inputs.races.entries()){const raw=spans.get(index);need(typeof raw==='string');hashes.set(source.race_id,await digest(raw));}
    const name=value=>typeof value==='string'?value.replace(/\s/g,''):'';
    for(const forecast of doc.races){
      need(rid(forecast?.race_id)&&forecast.race_id.startsWith(date.replaceAll('-',''))&&!seen.has(forecast.race_id));seen.add(forecast.race_id);
      const row=byId.get(forecast.race_id),source=sources.get(forecast.race_id);
      need(row&&source&&forecast.input_sha256===hashes.get(row.id)&&forecast.source_as_of===source.source_as_of&&forecast.cutoff_at===source.cutoff_at);
      need(sameClock(row.cutoff,source.cutoff_at)&&utc(source.source_as_of)&&utc(source.forecast_generated_at));
      need(forecast.input_sha256&&source.input?.race_id===row.id&&Array.isArray(source.roster)&&source.roster.length===row.riders.length&&Array.isArray(source.input.riders));
      const people=new Map();for(const p of source.roster){need(record(p)&&Number.isInteger(p.car)&&!people.has(p.car)&&name(p.name));people.set(p.car,p);}
      need(source.input.riders.length===row.riders.length&&new Set(source.input.riders.map(p=>p.car)).size===row.riders.length&&source.input.riders.every(p=>row.cars.has(p.car)));
      for(const p of row.riders){
        const expected=people.get(p.number);need(expected&&name(expected.name)===name(p.name));
        const known=value=>typeof value==='string'&&/^[0-9]{6}$/.test(value);
        need(!known(p.registration)||!known(expected.registration)||p.registration===expected.registration);
      }
      const context={race_id:row.id,cars:[...row.cars],source_packet_sha256:sourceSha,source_forecast_generated_at:source.forecast_generated_at,cutoff_at:source.cutoff_at,source_as_of:source.source_as_of};
      joint.validateForecast(forecast,context);
      for(const p of forecast.riders){const expected=people.get(p.car);need(expected&&name(expected.name)===name(p.name)&&(expected.registration??null)===(p.registration??null));}
      row.jointForecast=forecast;row.jointForecastBindings=context;row.jointForecastHistory=[];
      row.comparisonRiders=source.input.riders.map(p=>({...p,name:people.get(p.car).name}));
    }
  }
  function normalize(date,files,shas,cipherSha,results){
    const read=name=>files.get('data/'+date+'/'+name);
    const roster=mapRows(read('races.json')??files.get('data/races.json'));
    const originals=mapRows(read('forecasts.json')??files.get('data/forecasts.json'));
    const two=mapRows(read('two_car_forecasts.json'));
    const flexible=mapRows(read('flexible_forecasts.json'));
    const refs=mapRows(read('reference_AB.json'));
    const quotes=mapRows(read('odds_snapshot_flexible.json'));
    const settled=mapRows(read('settlement.json'));
    const rollover=mapRows(read('three_car_rollover_forecasts.json'));
    for(const name of ['races.json','forecasts.json','two_car_forecasts.json','flexible_forecasts.json','reference_AB.json','odds_snapshot_flexible.json','settlement.json','three_car_rollover_forecasts.json']){
      if(files.has('data/'+date+'/'+name))need([...mapRows(read(name)).keys()].every(id=>id.startsWith(date.replaceAll('-',''))));
    }
    const ids=new Set([...roster.keys(),...originals.keys(),...two.keys(),...refs.keys()].filter(id=>id.startsWith(date.replaceAll('-',''))));
    const out=[];
    for(const id of ids){
      const r=roster.get(id)||{},p=originals.get(id)||{},riders=r.riders||[];
      need(Array.isArray(riders)&&riders.length<=9);
      const cars=new Set();const people=riders.map(raw=>{need(record(raw));const number=raw.number??raw.car;need(Number.isInteger(number)&&number>=1&&number<=9&&!cars.has(number));cars.add(number);return {...raw,number,name:text(raw.name,120)||'氏名未取得',score:raw.score??raw.points};});
      const row={id,date,venue:text(r.venue||p.venue,100)||'会場名未取得',number:r.race_no??r.no??p.no??Number(id.slice(-2)),title:text(r.race_title||r.title,200),
        cutoff:clock(date,r.deadline_time||r.cutoff||p.deadline_jst),start:clock(date,r.start_time||r.start||p.start_jst),
        sourceUrl:safeUrl(r.source_url),raw:r,riders:people,cars,lines:Array.isArray(r.lines)?r.lines:[],original:p,
        two:two.get(id)||{},flexible:flexible.get(id)||{},referenceEnvelope:refs.get(id)||{},reference:refs.get(id)?.output||refs.get(id)||{},quote:quotes.get(id)||{},
        settlement:settled.get(id)||null,rollover:rollover.get(id)||{},environment:read('environment.json')||null,
        bindings:Object.fromEntries([['original','forecasts.json',true],['two','two_car_forecasts.json'],['flexible','flexible_forecasts.json'],['reference','reference_AB.json'],['rollover','three_car_rollover_forecasts.json']].map(([key,name,legacy])=>[key,binding(files,shas,cipherSha,date,name,legacy)])),
        referenceHistory:[],resultHistory:[],resultUpdate:null,researchResultHistory:[...(results.get(id)||[])],latestResearchResult:(results.get(id)||[]).at(-1)||null};
      tickets(p.tickets,3,cars);tickets(row.two.tickets,2,cars);tickets(row.two.rollover?.tickets,2,cars);tickets(row.rollover.tickets,3,cars);
      for(const market of ['3t','2t'])tickets(row.flexible.markets?.[market]?.tickets,market==='2t'?2:3,cars);
      for(const model of ['A','B'])tickets(row.reference[model]?.ranked_tickets,3,cars);
      for(const saved of row.researchResultHistory)need(saved.observation.winning_triple===null||!cars.size||saved.observation.winning_triple.every(n=>cars.has(n)));
      need(Number.isInteger(row.number)&&row.number>=1&&row.number<=12);
      out.push(row);
    }
    return out.sort((a,b)=>(Date.parse(a.cutoff)||Infinity)-(Date.parse(b.cutoff)||Infinity)||a.id.localeCompare(b.id));
  }
  function resultUrl(provider,value,id){
    need(typeof value==='string'&&value.length<2048);
    const u=new URL(value);need(u.protocol==='https:'&&!u.username&&!u.password&&!u.hash&&!u.port&&value.startsWith('https://'+u.hostname+'/'));
    if(provider==='netkeirin')need(u.hostname==='keirin.netkeiba.com'&&u.pathname==='/race/result/'&&u.search==='?race_id='+id);
    else{
      need(provider==='Kdreams'&&u.hostname==='keirin.kdreams.jp'&&['','?pageType=result'].includes(u.search));
      const m=/^\/[a-z0-9-]+\/racedetail\/([0-9]{2})(20[0-9]{6})([0-9]{2})00([0-9]{2})\/$/.exec(u.pathname);
      need(m&&m[1]===id.slice(8,10)&&m[4]===id.slice(10)&&Number(m[3])>=1&&Number(m[3])<=8);
      const begin=m[2].slice(0,4)+'-'+m[2].slice(4,6)+'-'+m[2].slice(6);need(day(begin));
      need(new Date(Date.parse(begin+'T00:00:00Z')+(Number(m[3])-1)*86400000).toISOString().slice(0,10).replaceAll('-','')===id.slice(0,8));
    }
  }
  async function resultRecords(files,shas,cipherSha,dates){
    const results=new Map();
    for(const [path,value] of files){
      if(!path.endsWith('/research_results.json'))continue;
      const d=path.split('/')[1];need(dates.includes(d)&&sameKeys(value,'schema,day_jst,observations')&&value.schema===RESULT_SCHEMA&&value.day_jst===d&&Array.isArray(value.observations)&&value.observations.length<=10000);
      for(const o of value.observations){
        need(sameKeys(o,'schema,race_id,state,winning_triple,payout_per_100yen,provider_receipts,official_primary_result_authenticated,actual_organizer_cutoff_authenticated,qualifies_for_formal_settlement,captured_at,observation_sha256,previous_observation_sha256')&&o.schema===CONSENSUS_SCHEMA&&rid(o.race_id)&&o.race_id.startsWith(d.replaceAll('-',''))&&RESULT_STATES.has(o.state)&&utc(o.captured_at)&&hex(o.observation_sha256)&&(o.previous_observation_sha256===null||hex(o.previous_observation_sha256))&&o.previous_observation_sha256!==o.observation_sha256);
        need(o.official_primary_result_authenticated===false&&o.actual_organizer_cutoff_authenticated===false&&o.qualifies_for_formal_settlement===false&&Array.isArray(o.provider_receipts)&&o.provider_receipts.length<=2);
        const providers=new Set();for(const receipt of o.provider_receipts){need(sameKeys(receipt,'provider,source_bytes_sha256,observed_at,source_url')&&!providers.has(receipt.provider)&&hex(receipt.source_bytes_sha256)&&utc(receipt.observed_at)&&Date.parse(receipt.observed_at)<=Date.parse(o.captured_at));resultUrl(receipt.provider,receipt.source_url,o.race_id);providers.add(receipt.provider);}
        if(o.state===MATCHED)need(providers.size===2&&Array.isArray(o.winning_triple)&&o.winning_triple.length===3&&new Set(o.winning_triple).size===3&&o.winning_triple.every(n=>Number.isInteger(n)&&n>=1&&n<=9)&&Number.isSafeInteger(o.payout_per_100yen)&&o.payout_per_100yen>=100&&o.payout_per_100yen<=1000000000);
        else need(o.winning_triple===null&&o.payout_per_100yen===null);
        const fact={...o,provider_receipts:o.provider_receipts.map(({provider,source_url})=>({provider,source_url})).sort((a,b)=>(a.provider<b.provider?-1:a.provider>b.provider?1:0)||(a.source_url<b.source_url?-1:a.source_url>b.source_url?1:0))};
        for(const key of ['captured_at','observation_sha256','previous_observation_sha256'])delete fact[key];
        need(await digest(canonical(fact))===o.observation_sha256);
        const prior=results.get(o.race_id)||[],last=prior.at(-1)?.observation;
        if(last)need(o.previous_observation_sha256===last.observation_sha256&&Date.parse(o.captured_at)>=Date.parse(last.captured_at));
        prior.push({observation:o,binding:{cipherSha,fileSha256:shas.get(path),path}});results.set(o.race_id,prior);
      }
    }
    return results;
  }
  function resultUpdates(date,files){
    const value=files.get('data/'+date+'/result_updates.json'),updates=new Map();
    if(value==null)return updates;
    need(exact(value,['schema','observed_at','races'])&&value.schema==='RACE_AI_KEIRIN_RESULT_UPDATES_V1'&&clock(date,value.observed_at)&&Array.isArray(value.races)&&value.races.length<=300);
    for(const row of value.races){
      need(exact(row,['race_id','revision','observed_at','authority','order_status','payout_status','winning_triples','payouts_100yen','source_comparison','diagnostics','arms'])&&rid(row.race_id)&&row.race_id.startsWith(date.replaceAll('-',''))&&!updates.has(row.race_id)&&hex(row.revision)&&clock(date,row.observed_at)&&Date.parse(row.observed_at)<=Date.parse(value.observed_at));
      need(['official','secondary'].includes(row.authority)&&['confirmed','pending','conflict'].includes(row.order_status)&&['confirmed','pending','held'].includes(row.payout_status));
      need(Array.isArray(row.winning_triples)&&row.winning_triples.length<=20&&new Set(row.winning_triples).size===row.winning_triples.length);
      for(const combo of row.winning_triples)need(typeof combo==='string'&&/^[1-9]-[1-9]-[1-9]$/.test(combo)&&new Set(combo.split('-')).size===3);
      need((row.order_status==='confirmed')===(row.winning_triples.length>0)&&record(row.payouts_100yen));
      const money=row.authority==='official'&&row.order_status==='confirmed'&&row.payout_status==='confirmed';
      if(row.payout_status==='confirmed')need(money);
      if(money){
        need(Object.keys(row.payouts_100yen).sort().join(',')===row.winning_triples.slice().sort().join(','));
        Object.values(row.payouts_100yen).forEach(yen=>need(Number.isSafeInteger(yen)&&yen>=100&&yen<=1000000000));
      }else need(Object.keys(row.payouts_100yen).length===0);
      need(Array.isArray(row.source_comparison)&&row.source_comparison.length<=5&&new Set(row.source_comparison.map(s=>s?.source_id)).size===row.source_comparison.length);
      row.source_comparison.forEach(s=>need(exact(s,['source_id','state'])&&['keirin_jp','kdreams','netkeirin','official_pdf','official_json'].includes(s.source_id)&&['matched','different','unavailable','unverified'].includes(s.state)));
      checkedDiagnostics(row.diagnostics,date);need(exact(row.arms,['A','B','C','adjusted_A','adjusted_B']));
      const arms={};
      for(const [name,value] of Object.entries(row.arms)){
        need(exact(value,['state','points','stake_yen','return_yen'])&&['hit','miss','pending','void','unverifiable'].includes(value.state));
        const arm={...value};
        need(arm.points===null||Number.isSafeInteger(arm.points)&&arm.points>=1&&arm.points<=504);
        for(const field of ['stake_yen','return_yen'])need(arm[field]===null||Number.isSafeInteger(arm[field])&&arm[field]>=0&&arm[field]<=504000000000);
        if(!money||['pending','unverifiable'].includes(arm.state))need(arm.stake_yen===null&&arm.return_yen===null);
        if(row.authority!=='official'||row.order_status!=='confirmed')need(!['hit','miss','void'].includes(arm.state));
        arms[name]=arm;
      }
      updates.set(row.race_id,{...row,arms});
    }
    return updates;
  }
  function checkedDiagnostics(rows,date){
    const routes={OFFICIAL_CALENDAR:['keirin.jp','/sp/raceschedule','GET'],CALENDAR_SCRIPT:['keirin.jp','/sp/static/js/SJ0201.js','GET'],FORM_SCRIPT:['keirin.jp','/sp/static/js/commonSubmit.js','GET'],OFFICIAL_RACE_LIST:['keirin.jp','/sp/racelist','POST'],RACE_LIST_VIEW_SCRIPT:['keirin.jp','/sp/static/js/SJ0301_v.js','GET'],RACE_LIST_CONTROLLER_SCRIPT:['keirin.jp','/sp/static/js/SJ0301_c.js','GET'],OFFICIAL_FINAL_RESULT:['keirin.jp','/sp/race','POST'],OFFICIAL_PAYOUT_UNIT:['www.hofukeirin.jp','/ticket/','GET'],OFFICIAL_JSON_CALENDAR:['keirin.jp','/pc/json','GET'],OFFICIAL_JSON_DAY_LIST:['keirin.jp','/pc/json','GET'],OFFICIAL_JSON_RESULT_SUMMARY:['keirin.jp','/pc/json','GET'],OFFICIAL_JSON_HEADER:['keirin.jp','/pc/json','GET'],OFFICIAL_JSON_DETAIL:['keirin.jp','/pc/json','GET']};
    const reasons=['SOURCE_ACCEPTED','TRANSPORT_FAILED','HTTP_DENIED','HTTP_ERROR','REDIRECT_REFUSED','SOURCE_BYTES_INVALID','CHALLENGE_MARKUP','CAPTURE_CLOCK_INVALID','SOURCE_VALIDATION_FAILED','UNIT_TEXT_MISSING','UNIT_VERIFIED','RESULT_VALIDATED','RESULT_NOT_PUBLISHED','PROVIDER_STOP_PERSISTENCE_FAILED'];
    need(Array.isArray(rows)&&rows.length<=32);
    for(const row of rows){
      need(record(row)&&Object.keys(row).sort().join(',')==='http_status,method,observed_at,purpose,reason,schema,source_host,source_path,stage'&&row.schema==='RACE_AI_KEIRIN_RESULT_DIAGNOSTIC_V1');
      const route=routes[row.purpose];need(route&&row.source_host===route[0]&&row.source_path===route[1]&&row.method===route[2]);
      need(['REQUEST','HTTP_RESPONSE','CONTENT_CHECK','PARSE_RESULT','VERIFY_UNIT','PERSIST_STOP'].includes(row.stage)&&reasons.includes(row.reason)&&clock(date,row.observed_at));
      need(row.http_status===null||Number.isInteger(row.http_status)&&row.http_status>=100&&row.http_status<=599);
    }
  }
  function frozenForecasts(date,files){
    const doc=files.get('data/'+date+'/frozen_forecasts.json');if(doc==null)return new Map();
    need(exact(doc,['schema','races'])&&doc.schema==='RACE_AI_KEIRIN_FROZEN_FORECASTS_V1'&&Array.isArray(doc.races)&&doc.races.length>0&&doc.races.length<=300);
    return checkedFrozenRows(date,doc.races,true);
  }
  function checkedFrozenRows(date,rows,conditionedRequired){
    const out=new Map();
    const baseKeys='schema race_id generated_at published_cutoff_at source_facts_sha256 source_as_of A B C official_cutoff_independently_authenticated official_result_observed all_six_phase_orders_are_hypotheses_not_video_truth branch_weights_are_not_calibrated_probabilities formal_model_promoted old_PR71_four_models_required real_money_wager_placed prediction_sha256'.split(' ');
    const shadowKeys='schema race_id generated_at published_cutoff_at baseline_source_sha256 baseline_prediction_sha256 condition_supplement_sha256 A_research B_research rider_assessments verified_source_receipt_count medical_recovery_or_crash_causality_inferred comments_quoted_in_private_supplement_only historical_originals_mutated is_official_calibrated_or_production_forecast C_optional_unrelated sha256'.split(' ');
    const phases=['INITIAL','BELL','FINAL_HOME','FINAL_BACK','FOURTH_CORNER','GOAL'],number=(v,lo,hi)=>Number.isFinite(v)&&v>=lo&&v<=hi;
    for(const row of rows){
      const rowKeys=['race_id','revision','baseline_cipher_sha256','conditioned_cipher_sha256','baseline_sealed_at','conditioned_sealed_at','facts','baseline','conditioned'];
      need((exact(row,rowKeys)||exact(row,[...rowKeys,'confidence_assessment']))&&rid(row.race_id)&&row.race_id.startsWith(date.replaceAll('-',''))&&!out.has(row.race_id));
      for(const key of ['revision','baseline_cipher_sha256'])need(hex(row[key]));
      const base=row.baseline,adjusted=row.conditioned,facts=row.facts;
      need(exact(base,baseKeys)&&base.schema==='RACE_AI_KEIRIN_AUTOMATIC_MARKS_AND_SIX_PHASE_V1'&&base.race_id===row.race_id&&hex(base.prediction_sha256)&&hex(base.source_facts_sha256));
      if(adjusted===null)need(!conditionedRequired&&row.conditioned_cipher_sha256===null&&row.conditioned_sealed_at===null);
      else{
        need(exact(adjusted,shadowKeys)&&adjusted.schema==='RACE_AI_KEIRIN_CONDITIONED_AB_SHADOW_V1'&&adjusted.race_id===row.race_id&&hex(row.conditioned_cipher_sha256));
        need(hex(adjusted.sha256)&&hex(adjusted.condition_supplement_sha256)&&adjusted.baseline_prediction_sha256===base.prediction_sha256&&adjusted.baseline_source_sha256===base.source_facts_sha256&&adjusted.generated_at===base.generated_at&&adjusted.published_cutoff_at===base.published_cutoff_at);
      }
      for(const value of [base.generated_at,base.published_cutoff_at,base.source_as_of,row.baseline_sealed_at,...(adjusted?[row.conditioned_sealed_at]:[])])need(clock(date,value));
      need(Date.parse(base.source_as_of)<=Date.parse(base.generated_at));
      for(const key of ['baseline_sealed_at',...(adjusted?['conditioned_sealed_at']:[])])need(Date.parse(base.generated_at)<=Date.parse(row[key])&&Date.parse(base.published_cutoff_at)-Date.parse(row[key])>=65000);
      need(exact(base.C,['state'])&&base.C.state==='HOLD_NO_INDEPENDENT_HISTORICAL_FOLLOW_LABELS');
      for(const key of ['official_cutoff_independently_authenticated','official_result_observed','formal_model_promoted','old_PR71_four_models_required','real_money_wager_placed'])need(base[key]===false);
      need(base.all_six_phase_orders_are_hypotheses_not_video_truth===true&&base.branch_weights_are_not_calibrated_probabilities===true);
      if(adjusted){
        for(const key of ['medical_recovery_or_crash_causality_inferred','historical_originals_mutated','is_official_calibrated_or_production_forecast'])need(adjusted[key]===false);
        need(adjusted.comments_quoted_in_private_supplement_only===true&&adjusted.C_optional_unrelated===true&&Number.isInteger(adjusted.verified_source_receipt_count)&&adjusted.verified_source_receipt_count>=1&&adjusted.verified_source_receipt_count<=400);
      }
      need(exact(facts,['competition','line_groups','riders'])&&['CHALLENGE','A1_A2','S','GIRLS','OTHER'].includes(facts.competition)&&Array.isArray(facts.riders)&&facts.riders.length>=5&&facts.riders.length<=9);
      const cars=new Set();
      for(const r of facts.riders){
        need(exact(r,['car','athlete_id','mark_rank','competition_points','recent_form_score','h_count','b_count','style'])&&Number.isInteger(r.car)&&r.car>=1&&r.car<=9&&!cars.has(r.car));cars.add(r.car);
        need(r.athlete_id===null||typeof r.athlete_id==='string'&&/^\d{4,8}$/.test(r.athlete_id));
        need(r.mark_rank==='UNMARKED'||Number.isInteger(r.mark_rank)&&r.mark_rank>=1&&r.mark_rank<=facts.riders.length);
        need(number(r.competition_points,0,150)&&number(r.recent_form_score,0,1)&&['h_count','b_count'].every(k=>Number.isInteger(r[k])&&r[k]>=0&&r[k]<=99)&&['NIGE','MAKURI','SASHI','MARK','ALLROUND','UNKNOWN'].includes(r.style));
      }
      need(Array.isArray(facts.line_groups)&&facts.line_groups.length>0&&facts.line_groups.length<=cars.size&&facts.line_groups.every(g=>Array.isArray(g)&&g.length>0&&g.every(c=>Number.isInteger(c)&&cars.has(c))));
      const members=facts.line_groups.flat();need(members.length===cars.size&&new Set(members).size===cars.size&&(facts.competition!=='GIRLS'||facts.line_groups.every(g=>g.length===1)));
      need(exact(base.A,['model','ranked_tickets','based_on_published_marks_not_shared_PR71'])&&base.A.model==='marks-ordinal-plus-observed-rider-strength-v1'&&base.A.based_on_published_marks_not_shared_PR71===true&&exact(base.B,['model','ranked_tickets','six_phase_scenarios','round_objective_source'])&&base.B.model==='line-tactical-six-phase-untrained-v1'&&['SOURCE_EVIDENCED','UNKNOWN_NOT_IMPUTED'].includes(base.B.round_objective_source));
      const scenarios=base.B.six_phase_scenarios,ids=new Set();need(Array.isArray(scenarios)&&scenarios.length>=2&&scenarios.length<=20);
      for(const scenario of scenarios){
        need(exact(scenario,['scenario_id','six_phases','projected_3ren_tan','relative_research_weight'])&&typeof scenario.scenario_id==='string'&&/^L[1-9]_V[0-3]$/.test(scenario.scenario_id)&&!ids.has(scenario.scenario_id)&&number(scenario.relative_research_weight,0,1));ids.add(scenario.scenario_id);
        need(Array.isArray(scenario.six_phases)&&scenario.six_phases.length===6);
        scenario.six_phases.forEach((s,i)=>{need(exact(s,['phase','projected_order','projected_top3','hypothesis_actions','actual_rider_position_video_verified'])&&s.phase===phases[i]&&s.actual_rider_position_video_verified===false&&Array.isArray(s.projected_order)&&s.projected_order.length===cars.size&&new Set(s.projected_order).size===cars.size&&s.projected_order.every(c=>Number.isInteger(c)&&cars.has(c))&&JSON.stringify(s.projected_top3)===JSON.stringify(s.projected_order.slice(0,3))&&Array.isArray(s.hypothesis_actions)&&s.hypothesis_actions.length>0&&s.hypothesis_actions.length<=8&&s.hypothesis_actions.every(a=>typeof a==='string'&&/^[A-Z][A-Z0-9_]{0,79}$/.test(a)));});
        need(JSON.stringify(scenario.projected_3ren_tan)===JSON.stringify(scenario.six_phases[5].projected_top3));
      }
      need(Math.abs(scenarios.reduce((sum,s)=>sum+s.relative_research_weight,0)-1)<=1e-6);
      for(const name of ['A','B']){const value=base[name].ranked_tickets;need(Array.isArray(value)&&value.length>=1&&value.length<=12&&value.every(t=>Array.isArray(t)&&t.length===3&&t.every(Number.isInteger)));tickets(value,3,cars);}
      if(adjusted){
      for(const [name,label] of [['A','baseline-plus-documented-form-v1'],['B','six-phase-plus-documented-form-v1']]){
        const arm=adjusted[name+'_research'],keys=['model','ranked_tickets','baseline_ranked_tickets','changed_from_original'];if(name==='B')keys.push('branch_condition_factors','branch_factor_is_uncalibrated');
        need(exact(arm,keys)&&arm.model===label&&JSON.stringify(arm.baseline_ranked_tickets)===JSON.stringify(base[name].ranked_tickets)&&typeof arm.changed_from_original==='boolean'&&arm.changed_from_original===(JSON.stringify(arm.ranked_tickets)!==JSON.stringify(base[name].ranked_tickets)));
        for(const value of [base[name].ranked_tickets,arm.ranked_tickets]){need(Array.isArray(value)&&value.length>=1&&value.length<=12&&value.every(t=>Array.isArray(t)&&t.length===3&&t.every(Number.isInteger)));tickets(value,3,cars);}
      }
      const factors=adjusted.B_research.branch_condition_factors;
      need(adjusted.B_research.branch_factor_is_uncalibrated===true&&Array.isArray(factors)&&factors.length===ids.size&&new Set(factors.map(f=>f?.scenario_id)).size===ids.size&&factors.every(f=>exact(f,['scenario_id','relative_weight_after'])&&ids.has(f.scenario_id)&&number(f.relative_weight_after,0,1))&&Math.abs(factors.reduce((sum,f)=>sum+f.relative_weight_after,0)-1)<=1e-6);
      need(Array.isArray(adjusted.rider_assessments)&&adjusted.rider_assessments.length===cars.size);const assessed=new Set(),trends=['IMPROVING','DECLINING','NO_CLEAR_CHANGE','INSUFFICIENT_DATA'];
      for(const a of adjusted.rider_assessments){
        need(exact(a,'car trend recent_result_change post_fall_change post_fall_trend fall_on_record documented_absence_days return_after_absence_results comments_count score_adjustment effect_on_tactics'.split(' '))&&Number.isInteger(a.car)&&cars.has(a.car)&&!assessed.has(a.car));assessed.add(a.car);
        need(trends.includes(a.trend)&&trends.includes(a.post_fall_trend)&&typeof a.fall_on_record==='boolean'&&number(a.score_adjustment,-.08,.08)&&['UNKNOWN_NO_ADJUSTMENT','OBSERVED_RESULTS_UPWEIGHT_RESEARCH','OBSERVED_RESULTS_DOWNWEIGHT_RESEARCH'].includes(a.effect_on_tactics));
        for(const key of ['recent_result_change','post_fall_change'])need(a[key]===null||number(a[key],-1,1));
        for(const key of ['documented_absence_days','return_after_absence_results','comments_count'])need(a[key]===null||Number.isInteger(a[key])&&a[key]>=0&&a[key]<=36525);
      }
      }
      out.set(row.race_id,row);
    }
    return out;
  }
  function nationwideDay(date,files){
    const doc=files.get('data/'+date+'/nationwide_forecasts.json');if(doc==null)return null;
    need(exact(doc,['schema','day_jst','revision','observed_at','registry_available','inventory_complete','missing_venues','disappeared_race_ids','races'])&&doc.schema===NATIONWIDE_SCHEMA&&doc.day_jst===date&&hex(doc.revision)&&typeof doc.observed_at==='string'&&doc.observed_at.includes('T')&&clock(date,doc.observed_at));
    need(typeof doc.registry_available==='boolean'&&typeof doc.inventory_complete==='boolean'&&Array.isArray(doc.races)&&doc.races.length<=600&&Array.isArray(doc.missing_venues)&&doc.missing_venues.length<=43&&new Set(doc.missing_venues).size===doc.missing_venues.length&&doc.missing_venues.every(v=>Number.isInteger(v)&&v>=0&&v<=99));
    const ids=new Set();
    for(const row of doc.races){
      need(exact(row,['race_id','venue_code','race_no','cutoff_at','state','condition_state','original_identity','original'])&&rid(row.race_id)&&row.race_id.startsWith(date.replaceAll('-',''))&&!ids.has(row.race_id));ids.add(row.race_id);
      need(Number.isInteger(row.venue_code)&&row.venue_code===Number(row.race_id.slice(8,10))&&Number.isInteger(row.race_no)&&row.race_no>=1&&row.race_no<=12&&row.race_no===Number(row.race_id.slice(-2))&&NATIONAL_STATES.has(row.state)&&CONDITION_STATES.has(row.condition_state));
      need(row.cutoff_at===null||typeof row.cutoff_at==='string'&&row.cutoff_at.includes('T')&&clock(date,row.cutoff_at)&&new Date(Date.parse(row.cutoff_at)+9*3600000).toISOString().slice(0,10)===date);
      if(row.original===null){const identity=row.original_identity;
        if(identity===null)need(row.state!=='A_B_AUTHENTICATED_PRE_CUTOFF'&&row.condition_state!=='CONDITIONED_AUTHENTICATED_PRE_CUTOFF');
        else need(exact(identity,['baseline','conditioned'])&&hex(identity.baseline)&&(identity.conditioned===null||hex(identity.conditioned))&&(row.condition_state!=='CONDITIONED_AUTHENTICATED_PRE_CUTOFF'||identity.conditioned!==null));
        continue;}
      checkedFrozenRows(date,[row.original],false);const original=row.original,identity=row.original_identity,adjusted=original.conditioned!==null;
      need(exact(identity,['baseline','conditioned'])&&hex(identity.baseline)&&(identity.conditioned===null||hex(identity.conditioned))&&original.race_id===row.race_id&&original.baseline.published_cutoff_at===row.cutoff_at&&Date.parse(original.baseline_sealed_at)<=Date.parse(doc.observed_at));
      need((identity.conditioned!==null)===adjusted&&(row.condition_state==='CONDITIONED_AUTHENTICATED_PRE_CUTOFF')===adjusted&&(!adjusted||Date.parse(original.conditioned_sealed_at)<=Date.parse(doc.observed_at)));
    }
    need(Array.isArray(doc.disappeared_race_ids)&&new Set(doc.disappeared_race_ids).size===doc.disappeared_race_ids.length&&doc.disappeared_race_ids.every(id=>ids.has(id)));
    need(!doc.inventory_complete||doc.registry_available&&!doc.missing_venues.length&&!doc.disappeared_race_ids.length);
    need(doc.registry_available||!doc.races.length&&!doc.missing_venues.length&&!doc.disappeared_race_ids.length);
    return doc;
  }
  function combineFrozen(prior,fresh){
    if(!prior)return fresh||null;if(!fresh)return prior;
    for(const name of ['race_id','baseline_cipher_sha256','baseline_sealed_at','facts','baseline'])need(canonical(prior[name])===canonical(fresh[name]));
    need(Object.hasOwn(prior,'confidence_assessment')===Object.hasOwn(fresh,'confidence_assessment'));
    if(Object.hasOwn(prior,'confidence_assessment'))need(canonical(prior.confidence_assessment)===canonical(fresh.confidence_assessment));
    if(prior.conditioned&&fresh.conditioned)for(const name of ['conditioned','conditioned_cipher_sha256','conditioned_sealed_at'])need(canonical(prior[name])===canonical(fresh[name]));
    return fresh.conditioned||!prior.conditioned?fresh:prior;
  }
  function mergeNationwide(prior,fresh){
    if(!prior)return fresh;need(prior.day_jst===fresh.day_jst);
    const old=new Map(prior.races.map(row=>[row.race_id,row]));
    for(const row of fresh.races){const previous=old.get(row.race_id);combineFrozen(previous?.original,row.original);
      if(previous?.original_identity&&row.original_identity)need(previous.original_identity.baseline===row.original_identity.baseline&&(previous.original_identity.conditioned===null||row.original_identity.conditioned===null||previous.original_identity.conditioned===row.original_identity.conditioned));}
    if(Date.parse(fresh.observed_at)<Date.parse(prior.observed_at))return prior;
    const ids=new Set(fresh.races.map(row=>row.race_id));need(prior.races.every(row=>ids.has(row.race_id)));
    return {...fresh,races:fresh.races.map(row=>{const previous=old.get(row.race_id),original=combineFrozen(previous?.original,row.original);let identity=row.original_identity||previous?.original_identity||null;
      if(identity&&previous?.original_identity?.conditioned&&!identity.conditioned)identity={...identity,conditioned:previous.original_identity.conditioned};
      return {...row,cutoff_at:original?.baseline.published_cutoff_at||row.cutoff_at,original,original_identity:identity};})};
  }
  function nationwideSemantic(doc){
    const semantic=Object.fromEntries(Object.entries(doc).filter(([key])=>key!=='observed_at'));
    semantic.races=doc.races.map(row=>Object.fromEntries(Object.entries(row).filter(([key])=>key!=='original')));
    return semantic;
  }
  function attachNationwide(days,nationwide){
    for(const [date,doc] of nationwide){
      const byId=new Map((days.get(date)||[]).map(row=>[row.id,row]));
      for(const item of doc.races){
        let row=byId.get(item.race_id);
        if(!row){const facts=item.original?.facts,riders=(facts?.riders||[]).map(r=>({number:r.car,name:'氏名未取得',score:r.competition_points}));
          row={id:item.race_id,date,venue:'開催コード '+String(item.venue_code).padStart(2,'0'),number:item.race_no,title:'',cutoff:item.cutoff_at,start:null,sourceUrl:null,raw:{},riders,cars:new Set(riders.map(r=>r.number)),lines:facts?.line_groups||[],original:{},two:{},flexible:{},reference:{},referenceEnvelope:{},quote:{},settlement:null,rollover:{},environment:null,bindings:{},referenceHistory:[],resultHistory:[],resultUpdate:null,researchResultHistory:[],latestResearchResult:null,nationwideOnly:true};
        }
        const original=combineFrozen(row.frozenForecast,item.original);
        byId.set(item.race_id,{...row,nationwideStatus:item,...(original?{frozenForecast:original}:{}),...(row.nationwideOnly?{cutoff:item.cutoff_at}: {})});
      }
      days.set(date,[...byId.values()].sort((a,b)=>(Date.parse(a.cutoff)||Infinity)-(Date.parse(b.cutoff)||Infinity)||a.id.localeCompare(b.id)));
    }
    return days;
  }
  async function decodePacket(packet,cipherSha,shadowOnly=false){
    need(record(packet)&&packet.schema===SCHEMA&&packet.formal_model_admission===false&&packet.production_weight_switch===false&&record(packet.files));
    need(Array.isArray(packet.dates)&&packet.dates.length>0&&packet.dates.every(day)&&new Set(packet.dates).size===packet.dates.length);
    const parsed=new Map(),fileShas=new Map();let total=0;
    for(const [path,entry] of Object.entries(packet.files)){
      need(/^data\/(?:\d{4}-\d{2}-\d{2}\/)?[A-Za-z0-9_.-]+\.json$/.test(path)&&record(entry)&&typeof entry.text==='string'&&hex(entry.sha256));
      const bytes=encoder.encode(entry.text),fileLimit=/^data\/\d{4}-\d{2}-\d{2}\/nationwide_forecasts\.json$/.test(path)?32*1024*1024:12*1024*1024;
      total+=bytes.length;need(bytes.length<=fileLimit&&total<=LIMIT&&bytes.length===entry.bytes);
      need(await digest(bytes)===entry.sha256);
      const dated=/^data\/(\d{4}-\d{2}-\d{2})\//.exec(path);need(!dated||packet.dates.includes(dated[1]));
      const value=JSON.parse(entry.text);parsed.set(path,value);fileShas.set(path,entry.sha256);
    }
    if(shadowOnly)return {dates:packet.dates,importedAt:packet.imported_at,shadowVerification:checkedShadowVerification(packet,parsed)};
    const results=await resultRecords(parsed,fileShas,cipherSha,packet.dates),days=new Map(packet.dates.slice().sort().map(date=>[date,normalize(date,parsed,fileShas,cipherSha,results)]));
    for(const [date,rows] of days){
      await jointSupplements(date,parsed,fileShas,rows,packet.files);
      const path='data/'+date+'/', sidecar=path+'rider_histories.json';
      if(parsed.has(sidecar)){
        need(history);
        const roster=parsed.has(path+'races.json')?path+'races.json':'data/races.json';
        history.attach(parsed.get(sidecar),rows,date,fileShas.get(roster),{utc,instantMicros,day});
      }
    }
    const updates=new Map([...days.keys()].map(date=>[date,resultUpdates(date,parsed)]));
    const frozen=new Map([...days.keys()].map(date=>[date,frozenForecasts(date,parsed)]));
    const nationwide=new Map([...days.keys()].flatMap(date=>{const doc=nationwideDay(date,parsed);return doc?[[date,doc]]:[];}));
    await validateConfidence(days,frozen,nationwide);
    attachNationwide(days,nationwide);
    for(const [date,rows] of days)for(const row of rows){const update=updates.get(date).get(row.id);if(update){row.resultUpdate=update;row.resultHistory=[update];}const original=frozen.get(date).get(row.id);if(original)row.frozenForecast=combineFrozen(row.frozenForecast,original);const history=results.get(row.id)||[];if(history.length){row.researchResultHistory=[...history];row.latestResearchResult=history.at(-1);}}
    return {schema:SCHEMA,dates:[...days.keys()],days,resultUpdates:updates,frozenForecasts:frozen,nationwide,sourceCommit:packet.source_commit,importedAt:packet.imported_at,files:parsed,fileShas,cipherSha,results,formal:false};
  }
  async function openPacket(packet){return decodePacket(packet,null);}
  async function validateConfidence(days,frozen,nationwide){
    const originals=new Set();
    for(const rows of frozen.values())for(const original of rows.values())originals.add(original);
    for(const doc of nationwide.values())for(const row of doc.races)if(row.original)originals.add(row.original);
    for(const original of originals)if(Object.hasOwn(original,'confidence_assessment')){
      need(confidence);await confidence.validateBaseline(original.confidence_assessment,original.baseline,{source:original.facts,sealedAt:original.baseline_sealed_at});
    }
    for(const rows of days.values())for(const row of rows){
      if(Object.hasOwn(row.referenceEnvelope,'confidence_assessment')){
        need(confidence);await confidence.validateBaseline(row.referenceEnvelope.confidence_assessment,row.reference,{source:row.referenceEnvelope.input,raceId:row.id});
      }
      const selected=[[row.original,'3t','normal'],[row.two,'2t','normal'],[row.rollover,'3t','rollover'],[row.two.rollover,'2t','rollover'],...['3t','2t'].map(market=>[row.flexible.markets?.[market],market,'normal'])];
      for(const [raw,market,strategy] of selected)if(raw&&Object.hasOwn(raw,'confidence_assessment')){
        need(confidence);await confidence.validateAuthored(raw,{raceId:row.id,market,strategy});
      }
    }
  }
  function rows(data,date){return data.days.get(date)||[];}
  function historyRows(data,{period='day',day:selectedDay='',from='',to=''}={}){
    if(!data||!Array.isArray(data.dates))return [];
    let dates;
    if(period==='day')dates=day(selectedDay)?data.dates.filter(d=>d===selectedDay):[];
    else if(period==='range')dates=day(from)&&day(to)&&from<=to?data.dates.filter(d=>from<=d&&d<=to):[];
    else if(period==='all')dates=data.dates.slice();
    else return [];
    return dates.sort().reverse().flatMap(date=>rows(data,date));
  }
  const searchText=value=>String(value??'').normalize('NFKC').toLocaleLowerCase('ja');
  function matchesHistory(row,{query='',venue='',raceNumber=''}={}){
    if(venue&&row.venue!==venue||raceNumber!==''&&row.number!==Number(raceNumber))return false;
    const text=searchText([row.venue,row.title,row.id,row.date,row.original?.headline,
      ...(row.riders||[]).map(r=>r.name)].join(' '));
    const parts=searchText(query).replace(/(\d{1,2})r\b/g,' $1r ').trim().split(/\s+/).filter(Boolean);
    return parts.every(term=>{
      const race=/^(\d{1,2})r$/.exec(term);
      if(race)return Number(race[1])>=1&&Number(race[1])<=12&&row.number===Number(race[1]);
      const date=/^(?:(\d{4})[-/])?(\d{1,2})[-/](\d{1,2})$/.exec(term);
      if(date)return (!date[1]||row.date.slice(0,4)===date[1])&&
        Number(row.date.slice(5,7))===Number(date[2])&&Number(row.date.slice(8,10))===Number(date[3]);
      return text.includes(term);
    });
  }
  function historyPage(list,page,size=20){
    const length=Number.isInteger(size)&&size>0&&size<=100?size:20;
    const pages=Math.max(1,Math.ceil(list.length/length));
    page=Math.min(pages,Math.max(1,Number.isInteger(page)?page:1));
    const start=(page-1)*length,items=list.slice(start,start+length);
    return {items,page,pages,total:list.length,first:items.length?start+1:0,last:start+items.length};
  }
  function frozenArm(row,name){
    const frozen=row.frozenForecast;if(!frozen||!['A','B','adjusted_A','adjusted_B'].includes(name))return null;
    const adjusted=name.startsWith('adjusted_'),role=adjusted?name.slice(9):name;if(adjusted&&!frozen.conditioned)return null;
    const arm=adjusted?frozen.conditioned[role+'_research']:frozen.baseline[role];
    const factors=new Map((frozen.conditioned?.B_research.branch_condition_factors||[]).map(f=>[f.scenario_id,f.relative_weight_after]));
    const assessment=!adjusted&&Object.hasOwn(frozen,'confidence_assessment')?confidence.selected(frozen.confidence_assessment,role):{confidence:null,confidenceAssessment:null,confidenceBundle:null};
    return {name,role,adjusted,source:arm,...assessment,tickets:tickets(arm.ranked_tickets,3,new Set(frozen.facts.riders.map(r=>r.car))),
      scenarios:role==='B'?frozen.baseline.B.six_phase_scenarios.map(s=>({...s,relative_research_weight:adjusted?factors.get(s.scenario_id):s.relative_research_weight})):[],
      assessments:adjusted?frozen.conditioned.rider_assessments:[],facts:frozen.facts,generatedAt:frozen.baseline.generated_at,
      sourceAsOf:frozen.baseline.source_as_of,sealedAt:adjusted?frozen.conditioned_sealed_at:frozen.baseline_sealed_at,cutoffAt:frozen.baseline.published_cutoff_at};
  }
  function forecast(row,market='3t',variant='flexible'){
    const places=market==='2t'?2:3;
    if(['A','B','C'].includes(variant)){
      const ref=row.reference[variant]||{};
      const assessment=market==='3t'&&['A','B'].includes(variant)&&Object.hasOwn(row.referenceEnvelope||{},'confidence_assessment')?confidence.selected(row.referenceEnvelope.confidence_assessment,variant):{confidence:null,confidenceAssessment:null,confidenceBundle:null};
      return {label:'参考'+variant,tickets:market==='3t'?tickets(ref.ranked_tickets,3,row.cars):[],scenarios:ref.six_phase_scenarios||[],
        allocatable:false,headline:'既存モデルの研究出力',reason:variant==='C'?'独立した連係履歴が不足しているため未生成':'公開印・統計・並びを使用した参考計算',
        createdAt:row.reference.generated_at,binding:row.bindings?.reference||null,...assessment,risk:'学習済み・校正済みの確率ではありません。',source:ref};
    }
    const base=market==='2t'?row.two:row.original;
    let current=base,assessmentSource=base,label=market==='2t'?'2車単・通常予想':'3連単・通常予想';
    if(variant==='flexible'&&row.flexible.markets?.[market]){assessmentSource=row.flexible.markets[market];current={...base,...assessmentSource,analysis_created_at:assessmentSource.analysis_created_at||row.flexible.analysis_created_at};label=market==='2t'?'2車単・改訂予想':'3連単・改訂予想';}
    if(variant==='rollover'){
      if(market==='3t'&&row.rollover.tickets){current=row.rollover;assessmentSource=current;label='3連単・転がし予想';}
      else if(market==='2t'&&base.rollover?.eligible){assessmentSource=base.rollover;current={...base,...base.rollover,risk:base.rollover.excluded_risk||base.rollover.risk||base.risk};label='2車単・転がし予想';}
      else{assessmentSource={};current={...base,tickets:[],confidence:null,reason:base.rollover?.reason||'このレースは転がし候補に選んでいません。',headline:'転がし候補は見送り'};label='転がし・見送り';}
    }
    const assessment=Object.hasOwn(assessmentSource,'confidence_assessment')?confidence.selected(assessmentSource.confidence_assessment,'selected'):{confidence:text(current.confidence,40),confidenceAssessment:null,confidenceBundle:null};
    return {label,tickets:tickets(current.tickets,places,row.cars),scenarios:[...(current.scenarios||row.original.scenarios||[]),...(current.extra_scenarios||[])],allocatable:true,
      headline:text(current.headline)||text(base.headline)||'予想未取得',reason:text(current.point_reason||current.reason||current.confidence_reason||current.verdict||current.selection_reason),
      ...assessment,risk:text(current.risk),createdAt:current.analysis_created_at,
      binding:row.bindings?.[variant==='rollover'&&market==='3t'?'rollover':variant==='flexible'&&row.flexible.markets?.[market]?'flexible':market==='2t'?'two':'original']||null,source:current};
  }
  function displayedPredictions(row,market='3t',variant='flexible'){
    const saved=(row.nationwideOnly||market==='3t'&&variant!=='rollover')?['A','B','adjusted_A','adjusted_B'].map(name=>frozenArm(row,name)).filter(Boolean):[];
    return row.nationwideOnly?saved:[forecast(row,market,variant),...saved];
  }
  function compare(row,market='3t',variant='A',version=null){
    need(['3t','2t'].includes(market)&&['original','flexible','rollover','A','B','C'].includes(variant));
    const context=version?{...row,reference:version.reference,referenceEnvelope:version.envelope,bindings:{...row.bindings,reference:version.binding}}:row;
    const prediction=forecast(context,market,variant),saved=row.latestResearchResult,observation=saved?.observation;
    const generated=clock(row.date,prediction.createdAt),cutoff=clock(row.date,row.cutoff);
    const score={raceId:row.id,market,variant,status:'RESEARCH_UNKNOWN',ticketCount:prediction.tickets.length,hitAt1:null,hitAtAll:null,stakeYen:prediction.tickets.length*100,payoutYen:null,netYen:null,
      generatedAt:generated,cutoff,predictionBinding:prediction.binding,resultBinding:saved?.binding||null,resultObservationSha256:observation?.observation_sha256||null,
      timingStatus:!generated?'GENERATED_AT_MISSING':!cutoff?'CUTOFF_UNVERIFIED':Date.parse(generated)>=Date.parse(cutoff)?'GENERATED_AFTER_OR_AT_CUTOFF':'RECORDED_PRE_CUTOFF_NOT_FORMAL',formal:false,scope:'CONDITIONAL_RESEARCH_ONLY'};
    const history=row.researchResultHistory||[];
    if(observation&&(!history.length||history[0].observation.previous_observation_sha256!==null||history.at(-1).observation.observation_sha256!==observation.observation_sha256||!history.every((entry,n)=>n===0||entry.observation.previous_observation_sha256===history[n-1].observation.observation_sha256)))return {...score,reason:'RESULT_HISTORY_INCOMPLETE'};
    if(!prediction.tickets.length||!prediction.binding||observation?.state!==MATCHED||observation.race_id!==row.id||!row.cars.size||!observation.winning_triple.every(n=>row.cars.has(n)))return score;
    const combo=observation.winning_triple.slice(0,market==='2t'?2:3).join('-');score.hitAt1=prediction.tickets[0].combo===combo;score.hitAtAll=prediction.tickets.some(t=>t.combo===combo);score.status=score.hitAtAll?'RESEARCH_HIT':'RESEARCH_MISS';
    if(market==='3t'){score.payoutYen=score.hitAtAll?observation.payout_per_100yen:0;score.netYen=score.payoutYen-score.stakeYen;}
    return score;
  }
  function summarize(values,market='3t'){
    need(Array.isArray(values));const unique=new Map(values.map(row=>[row.id,row]));need(unique.size===values.length);
    const pairs=values.map(row=>({A:compare(row,market,'A'),B:compare(row,market,'B')}));
    const arm=(name,subset=pairs)=>{const scores=subset.map(p=>p[name]),known=scores.filter(s=>s.status!=='RESEARCH_UNKNOWN');return {evaluableRaces:known.length,unknownRaces:scores.length-known.length,hitRaces:known.filter(s=>s.hitAtAll).length,ticketCounts:[...new Set(known.map(s=>s.ticketCount))].sort((a,b)=>a-b),stakeYen:known.reduce((n,s)=>n+s.stakeYen,0),payoutYen:known.every(s=>s.payoutYen!==null)?known.reduce((n,s)=>n+s.payoutYen,0):null};};
    const paired=pairs.filter(p=>p.A.status!=='RESEARCH_UNKNOWN'&&p.B.status!=='RESEARCH_UNKNOWN');
    return {raceCount:values.length,pairedRaceCount:paired.length,A:arm('A'),B:arm('B'),paired:{A:arm('A',paired),B:arm('B',paired)},formal:false,improvementProven:false};
  }
  function allocate(prediction,budget,excluded=new Set()){
    need([2000,2500,3000].includes(budget));
    const chosen=prediction.tickets.filter(t=>!excluded.has(t.combo));
    const available=prediction.allocatable&&chosen.length>0&&chosen.length*100<=budget&&chosen.every(t=>['本線','押さえ','波乱'].includes(t.role));
    if(!available)return {available:false,total:0,chosen,amounts:prediction.tickets.map(()=>0)};
    const paid=staking.allocate(chosen,budget),byCombo=new Map(chosen.map((t,i)=>[t.combo,paid[i]]));
    return {available:true,total:budget,chosen,amounts:prediction.tickets.map(t=>byCombo.get(t.combo)||0)};
  }
  function b64(value,max=LIMIT*2){
    need(typeof value==='string'&&value.length>0&&value.length<=max&&value.length%4===0&&!/[^A-Za-z0-9+/=]/.test(value));
    const binary=atob(value);need(btoa(binary)===value);return Uint8Array.from(binary,c=>c.charCodeAt(0));
  }
  async function openCipher(bytes,{cipherSha,key,shadowOnly=false}){
    need(bytes instanceof Uint8Array&&bytes.length<=90*1024*1024&&hex(cipherSha)&&await digest(bytes)===cipherSha);
    const envelope=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
    need(record(envelope)&&Object.keys(envelope).sort().join(',')==='ciphertext,header,nonce');
    const h=envelope.header;need(record(h)&&Object.keys(h).sort().join(',')==='schema,source_content_sha256'&&h.schema===OUTER&&hex(h.source_content_sha256));
    need(typeof key==='string'&&/^[A-Za-z0-9_-]{43}$/.test(key));
    const rawKey=b64(key.replaceAll('-','+').replaceAll('_','/')+'=',44),nonce=b64(envelope.nonce,16),encrypted=b64(envelope.ciphertext);
    need(rawKey.length===32&&nonce.length===12&&encrypted.length>=16);
    const imported=await apiCrypto().subtle.importKey('raw',rawKey,{name:'AES-GCM'},false,['decrypt']);
    const aad=encoder.encode(JSON.stringify({schema:h.schema,source_content_sha256:h.source_content_sha256}));
    const plain=new Uint8Array(await apiCrypto().subtle.decrypt({name:'AES-GCM',iv:nonce,additionalData:aad,tagLength:128},imported,encrypted));
    need(plain.length<=LIMIT&&(!shadowOnly||plain.length===2048)&&await digest(plain)===h.source_content_sha256);
    return decodePacket(JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(plain)),cipherSha,shadowOnly);
  }
  return {openPacket,openCipher,rows,historyRows,matchesHistory,historyPage,forecast,frozenArm,displayedPredictions,compare,summarize,allocate,resultUpdates,checkedDiagnostics,combineFrozen,mergeNationwide,nationwideSemantic,attachNationwide,safeUrl,digest,clock,instantMicros,sameClock,utc,day,SCHEMA};
});

/* Independent display capability. Its private key never enters a request URL. */
(function(root,factory){
  if(typeof module==='object'&&module.exports)module.exports=factory(require('./keirin-note-model.js'));
  else root.RaceKeirinNoteFeed=factory(root.RaceKeirinNote);
})(typeof window==='object'?window:globalThis,function(M){
  'use strict';
  const BASE='https://raw.githubusercontent.com/haji84/RACE-AI/state/keirin-note-view/';
  const SHADOW_VERIFICATION='shadow-verification';
  const INFO='RACE_AI_KEIRIN_NOTE_FEED_V1:',encoder=new TextEncoder(),MAX=90*1024*1024;
  const need=v=>{if(!v)throw Error('KEIRIN_NOTE_FEED_INVALID');};
  const cryptoApi=()=>globalThis.crypto?.subtle?globalThis.crypto:require('node:crypto').webcrypto;
  const hex=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
  const record=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
  const sameKeys=(v,keys)=>record(v)&&Object.keys(v).sort().join(',')===keys.split(',').sort().join(',');
  const encode=raw=>btoa(String.fromCharCode(...new Uint8Array(raw))).replaceAll('+','-').replaceAll('/','_').replace(/=+$/,'');
  function decode(value){need(typeof value==='string'&&/^[A-Za-z0-9_-]+$/.test(value));const raw=Uint8Array.from(atob(value.replaceAll('-','+').replaceAll('_','/')+'='.repeat((-value.length%4+4)%4)),c=>c.charCodeAt(0));need(encode(raw)===value);return raw;}
  const ids=v=>Array.isArray(v)&&new Set(v).size===v.length&&v.every(n=>typeof n==='string'&&/^20[0-9]{10}$/.test(n));
  function checkIndex(index,recipient){
    const fields='schema,repository,recipient_id,entries,provider_denied,covered_race_ids,priority_window_race_ids';
    need((sameKeys(index,fields)||sameKeys(index,fields+',result_checks'))&&index.schema==='RACE_AI_KEIRIN_NOTE_FEED_V1'&&index.repository==='haji84/RACE-AI'&&index.recipient_id===recipient&&typeof index.provider_denied==='boolean'&&Array.isArray(index.entries)&&ids(index.covered_race_ids)&&ids(index.priority_window_race_ids));
    const hashes=new Set(),covered=new Set(),priority=new Set();
    for(const e of index.entries){
      const keys='cipher_sha256,source_content_sha256,ephemeral_public_key,salt,created_at,days,kind,captured_race_ids,priority_window_race_ids'+(e?.kind==='result'?',result_revisions':e?.kind==='canary-original'?',original_revisions':e?.kind==='nationwide'?',day_revision,original_revisions,registered_race_ids':'');
      need(sameKeys(e,keys)&&hex(e.cipher_sha256)&&hex(e.source_content_sha256)&&!hashes.has(e.cipher_sha256)&&['import','research','archive','result','results','canary-original','nationwide',SHADOW_VERIFICATION].includes(e.kind));
      need(decode(e.ephemeral_public_key).length===65&&decode(e.salt).length===32&&Array.isArray(e.days)&&e.days.length&&new Set(e.days).size===e.days.length&&e.days.every(M.day)&&Number.isFinite(Date.parse(e.created_at))&&ids(e.captured_race_ids)&&ids(e.priority_window_race_ids));
      need(e.captured_race_ids.every(id=>e.days.some(d=>id.startsWith(d.replaceAll('-',''))))&&(e.kind!=='results'||e.captured_race_ids.length===0&&e.priority_window_race_ids.length===0));
      need(e.priority_window_race_ids.every(id=>e.captured_race_ids.includes(id)));hashes.add(e.cipher_sha256);e.captured_race_ids.forEach(id=>covered.add(id));e.priority_window_race_ids.forEach(id=>priority.add(id));
      if(e.kind===SHADOW_VERIFICATION)need(e.days.length===1&&e.captured_race_ids.length===0&&e.priority_window_race_ids.length===0);
      if(e.kind==='result')need(e.captured_race_ids.length===0&&e.priority_window_race_ids.length===0&&record(e.result_revisions)&&Object.keys(e.result_revisions).length>0&&Object.keys(e.result_revisions).length<=300&&ids(Object.keys(e.result_revisions))&&Object.values(e.result_revisions).every(hex));
      if(e.kind==='canary-original')need(e.captured_race_ids.length===0&&e.priority_window_race_ids.length===0&&record(e.original_revisions)&&Object.keys(e.original_revisions).length>0&&Object.keys(e.original_revisions).length<=300&&ids(Object.keys(e.original_revisions))&&Object.values(e.original_revisions).every(hex));
      if(e.kind==='nationwide'){
        need(e.days.length===1&&e.captured_race_ids.length===0&&e.priority_window_race_ids.length===0&&hex(e.day_revision)&&ids(e.registered_race_ids)&&e.registered_race_ids.length<=600&&e.registered_race_ids.every(id=>id.startsWith(e.days[0].replaceAll('-',''))&&Number(id.slice(-2))>=1&&Number(id.slice(-2))<=12));
        need(record(e.original_revisions)&&Object.keys(e.original_revisions).every(id=>e.registered_race_ids.includes(id))&&Object.values(e.original_revisions).every(v=>sameKeys(v,'baseline,conditioned')&&hex(v.baseline)&&(v.conditioned===null||hex(v.conditioned))));
      }
    }
    need(index.covered_race_ids.length===covered.size&&index.covered_race_ids.every(id=>covered.has(id))&&index.priority_window_race_ids.length===priority.size&&index.priority_window_race_ids.every(id=>priority.has(id)));
    if(Object.hasOwn(index,'result_checks')){
      need(record(index.result_checks));
      for(const [id,check] of Object.entries(index.result_checks))need(ids([id])&&M.day(id.slice(0,4)+'-'+id.slice(4,6)+'-'+id.slice(6,8))&&index.entries.some(e=>e.days.some(d=>id.startsWith(d.replaceAll('-',''))))&&sameKeys(check,'checked_at,digest,status')&&M.utc(check.checked_at)&&(check.digest===null||hex(check.digest))&&['MATCHED','HOLD','PENDING'].includes(check.status)&&(check.status!=='MATCHED'||check.digest!==null));
    }
    return index;
  }
  async function capability(value){
    need(typeof value==='string'&&value.length>=150&&value.length<=400);
    const c=cryptoApi(),privateKey=await c.subtle.importKey('pkcs8',decode(value),{name:'ECDH',namedCurve:'P-256'},true,['deriveBits']);
    const jwk=await c.subtle.exportKey('jwk',privateKey),raw=new Uint8Array(65);raw[0]=4;raw.set(decode(jwk.x),1);raw.set(decode(jwk.y),33);
    return {privateKey,recipient:await M.digest(raw)};
  }
  async function openEntry(bytes,e,cap,{archives=new Map()}={}){
    const c=cryptoApi(),ephemeral=await c.subtle.importKey('raw',decode(e.ephemeral_public_key),{name:'ECDH',namedCurve:'P-256'},false,[]);
    const shared=await c.subtle.deriveBits({name:'ECDH',public:ephemeral},cap.privateKey,256),material=await c.subtle.importKey('raw',shared,'HKDF',false,['deriveBits']);
    const key=await c.subtle.deriveBits({name:'HKDF',hash:'SHA-256',salt:decode(e.salt),info:encoder.encode(INFO+cap.recipient)},material,256);
    need(await M.digest(bytes)===e.cipher_sha256);const h=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes)).header;need(h?.source_content_sha256===e.source_content_sha256);
    const shadowOnly=e.kind===SHADOW_VERIFICATION;
    const data=await M.openCipher(bytes,{cipherSha:e.cipher_sha256,key:encode(key),shadowOnly});
    need(data.dates.slice().sort().join(',')===e.days.slice().sort().join(','));
    if(shadowOnly){
      const value=data.shadowVerification,original=value.original,archive=archives.get(original.archive_cipher_sha256);
      need(e.captured_race_ids.length===0&&e.priority_window_race_ids.length===0&&
        archive?.kind==='archive'&&archive.days.length===1&&archive.days[0]===value.day_jst&&
        archive.captured_race_ids.length===0&&archive.priority_window_race_ids.length===0);
      const clocks=[original.generated_at,archive.created_at,original.cutoff_at,data.importedAt,e.created_at].map(M.instantMicros);
      need(clocks.every(clock=>clock!==null));
      const [generated,archived,cutoff,imported,published]=clocks;
      need(generated<=archived&&archived<cutoff&&imported<=published);
    }
    if(e.kind==='results')need(e.captured_race_ids.length===0&&e.priority_window_race_ids.length===0&&[...data.files.keys()].every(path=>/^data\/\d{4}-\d{2}-\d{2}\/research_results\.json$/.test(path))&&data.dates.every(date=>M.rows(data,date).length===0));
    if(e.kind==='result'){
      need([...data.files.keys()].every(path=>/^data\/\d{4}-\d{2}-\d{2}\/result_updates\.json$/.test(path))&&data.resultUpdates.size===data.dates.length);
      const revisions=Object.fromEntries([...data.resultUpdates.values()].flatMap(rows=>[...rows.values()].map(row=>[row.race_id,row.revision])));
      need(Object.keys(revisions).sort().join(',')===Object.keys(e.result_revisions).sort().join(',')&&Object.entries(revisions).every(([id,revision])=>e.result_revisions[id]===revision));
    }
    if(e.kind==='canary-original'){
      need([...data.files.keys()].every(path=>/^data\/\d{4}-\d{2}-\d{2}\/frozen_forecasts\.json$/.test(path))&&data.frozenForecasts.size===data.dates.length);
      const revisions=Object.fromEntries([...data.frozenForecasts.values()].flatMap(rows=>[...rows.values()].map(row=>[row.race_id,row.revision])));
      need(Object.keys(revisions).sort().join(',')===Object.keys(e.original_revisions).sort().join(',')&&Object.entries(revisions).every(([id,revision])=>e.original_revisions[id]===revision));
    }
    if(e.kind==='nationwide'){
      need(data.dates.length===1&&data.nationwide.size===1&&[...data.files.keys()].join(',')==='data/'+data.dates[0]+'/nationwide_forecasts.json');
      const doc=data.nationwide.get(data.dates[0]),revisions=Object.fromEntries(doc.races.filter(row=>row.original_identity!==null).map(row=>[row.race_id,row.original_identity]));
      need(doc.revision===e.day_revision&&doc.races.map(r=>r.race_id).sort().join(',')===e.registered_race_ids.slice().sort().join(',')&&Object.keys(revisions).sort().join(',')===Object.keys(e.original_revisions).sort().join(','));
      need(Object.entries(revisions).every(([id,v])=>v.baseline===e.original_revisions[id].baseline&&v.conditioned===e.original_revisions[id].conditioned));
    }
    return data;
  }
  function merge(parts,{resultChecks={}}={}){
    need(Array.isArray(parts)&&parts.length>0);
    const days=new Map(),files=new Map(),fileShas=new Map(),results=new Map(),refreshHolds=[],updates=new Map(),histories=new Map(),frozen=new Map(),nationwide=new Map(),nationwideHistory=new Map();let importedAt=parts[0].importedAt;
    const shadowVerifications=new Map(),shadowVerificationHolds=new Set();
    const stable=v=>Array.isArray(v)?'['+v.map(stable).join(',')+']':record(v)?'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+stable(v[k])).join(',')+'}':JSON.stringify(v);
    const semantic=result=>Object.fromEntries(Object.entries(result).filter(([key])=>key!=='observed_at'));
    const measurement=({verified_at,result,...value})=>stable({...value,result:semantic(result)});

    const roster=row=>row.riders.map(p=>p.number+':'+p.name.replace(/\s/g,'')).sort().join('|');
    const registrations=row=>{
      const result=new Map();
      for(const p of [...row.riders,...(row.jointForecast?.riders||[]),...(row.riderHistory?.riders||[])])if(typeof p.registration==='string'&&/^[0-9]{6}$/.test(p.registration)){
        const car=p.number??p.car;need(!result.has(car)||result.get(car)===p.registration);result.set(car,p.registration);
      }
      return result;
    };
    for(const part of parts){
      const verification=part.shadowVerification;
      if(verification){
        const {race_id:id}=verification,prior=shadowVerifications.get(id);
        // A later timestamp cannot replace a scored original or its outcome.
        if(!prior)shadowVerifications.set(id,verification);
        else if(measurement(prior)!==measurement(verification))shadowVerificationHolds.add(id);
        continue;
      }
      for(const [path,value] of part.files)files.set(path,value);
      for(const [path,value] of part.fileShas||[])fileShas.set(path,value);
      importedAt=part.importedAt;
      for(const date of part.dates){
        const national=part.nationwide?.get(date);
        if(national){
          const history=nationwideHistory.get(date)||new Map(),seen=history.get(national.revision);
          need(!seen||stable(M.nationwideSemantic(seen))===stable(M.nationwideSemantic(national)));
          if(!seen||Date.parse(national.observed_at)>=Date.parse(seen.observed_at))history.set(national.revision,national);
          nationwideHistory.set(date,history);nationwide.set(date,M.mergeNationwide(nationwide.get(date),national));
        }
        if(!frozen.has(date))frozen.set(date,new Map());
        for(const [id,original] of part.frozenForecasts?.get(date)||[]){const prior=frozen.get(date).get(id);need(!prior||stable(prior)===stable(original));frozen.get(date).set(id,original);}
        if(!updates.has(date))updates.set(date,new Map());
        for(const [id,result] of part.resultUpdates?.get(date)||[]){
          const history=histories.get(id)||new Map(),seen=history.get(result.revision);
          need(!seen||stable(semantic(seen))===stable(semantic(result)));
          if(!seen||Date.parse(result.observed_at)>=Date.parse(seen.observed_at))history.set(result.revision,result);
          histories.set(id,history);
          const prior=updates.get(date).get(id);
          if(!prior||Date.parse(result.observed_at)>=Date.parse(prior.observed_at))updates.get(date).set(id,result);
        }

        const byId=new Map((days.get(date)||[]).map(row=>[row.id,row]));
        for(const row of M.rows(part,date)){
          if(row.nationwideOnly)continue;
          const prior=byId.get(row.id);if(!prior){byId.set(row.id,{...row,referenceHistory:[...(row.referenceHistory||[])],researchResultHistory:[],latestResearchResult:null,resultHistory:[],resultUpdate:null});continue;}
          // Immutable snapshots keep every version. An input refresh does not
          // replace the authored originals imported from the owner's Site.
          const authored=(prior.original.tickets||[]).length>0;
          const predicted=authored||Boolean(prior.jointForecast)||Object.keys(prior.reference||{}).length>0||(prior.two.tickets||[]).length>0||Object.keys(prior.flexible?.markets||{}).length>0;
          const sameCutoff=prior.cutoff===row.cutoff||M.sameClock(prior.cutoff,row.cutoff);
          const oldIds=registrations(prior),newIds=registrations(row),identityConflict=[...oldIds].some(([car,id])=>newIds.has(car)&&newIds.get(car)!==id);
          if((predicted||row.jointForecast||prior.riderHistory||row.riderHistory)&&(roster(prior)!==roster(row)||!sameCutoff||identityConflict)){
            refreshHolds.push({raceId:row.id,reason:'HOLD_RESEARCH_REFRESH_SOURCE_CONTEXT_CHANGED'});continue;
          }
          const combined={...prior,bindings:{...prior.bindings}};
          if(row.riderHistory){
            const priorHistory=prior.riderHistory, incoming=row.riderHistory;
            const versions=[...(prior.riderHistoryVersions||[])];
            if(priorHistory&&stable(priorHistory)!==stable(incoming)){
              need(M.instantMicros(incoming.generated_at)>M.instantMicros(priorHistory.generated_at));
              need(M.instantMicros(incoming.knowledge_as_of)>=M.instantMicros(priorHistory.knowledge_as_of));
              versions.push(priorHistory);
            }
            combined.riderHistory=incoming;combined.riderHistoryVersions=versions;
          }
          if(row.jointForecast){
            const history=[...(prior.jointForecastHistory||[])];
            if(prior.jointForecast&&stable(prior.jointForecast)!==stable(row.jointForecast)){
              need(M.instantMicros(row.jointForecast.generated_at)>M.instantMicros(prior.jointForecast.generated_at));
              history.push({forecast:prior.jointForecast,binding:prior.jointForecastBindings});
            }
            combined.jointForecast=row.jointForecast;combined.jointForecastBindings=row.jointForecastBindings;combined.jointForecastHistory=history;combined.comparisonRiders=row.comparisonRiders;
          }
          for(const name of ['original','two','flexible','rollover','settlement']){
            const old=prior[name],fresh=row[name];
            if(name==='settlement'&&fresh&&(!record(fresh)||Object.keys(fresh).length))combined[name]=fresh;
            else if((!old||record(old)&&!Object.keys(old).length)&&fresh){combined[name]=fresh;if(row.bindings?.[name])combined.bindings[name]=row.bindings[name];}
          }
          combined.referenceHistory=[...(prior.referenceHistory||[])];
          if(Object.keys(row.reference||{}).length){
            if(Object.keys(prior.reference||{}).length&&JSON.stringify(prior.bindings?.reference)!==JSON.stringify(row.bindings?.reference))combined.referenceHistory.push({reference:prior.reference,envelope:prior.referenceEnvelope,binding:prior.bindings?.reference||null});
            combined.reference=row.reference;combined.referenceEnvelope=row.referenceEnvelope;combined.bindings.reference=row.bindings?.reference||null;
          }
          byId.set(row.id,combined);
        }
        days.set(date,[...byId.values()].sort((a,b)=>(Date.parse(a.cutoff)||Infinity)-(Date.parse(b.cutoff)||Infinity)||a.id.localeCompare(b.id)));
      }
      for(const [id,observations] of part.results||[]){
        const history=results.get(id)||[];
        for(const saved of observations){
          const o=saved.observation,last=history.at(-1)?.observation;
          need(last?o.previous_observation_sha256===last.observation_sha256&&o.observation_sha256!==last.observation_sha256&&Date.parse(o.captured_at)>=Date.parse(last.captured_at):o.previous_observation_sha256===null);
          history.push(saved);
        }
        results.set(id,history);
      }
    }
    M.attachNationwide(days,nationwide);
    for(const [date,list] of days)days.set(date,list.map(row=>{
      const history=results.get(row.id)||[];
      need(history.every(saved=>saved.observation.winning_triple===null||!row.cars.size||saved.observation.winning_triple.every(n=>row.cars.has(n))));
      return {...row,researchResultHistory:[...history],latestResearchResult:history.at(-1)||null};
    }));
    for(const [date,rows] of days)days.set(date,rows.map(row=>{
      const result=updates.get(date)?.get(row.id),original=frozen.get(date)?.get(row.id);if(!result&&!original)return row;
      return {...row,...(result?{resultUpdate:result,resultHistory:[...histories.get(row.id).values()]}:{}),...(original?{frozenForecast:M.combineFrozen(row.frozenForecast,original)}:{})};
    }));
    const checks=new Map(Object.entries(resultChecks));
    for(const [id,check] of checks){
      const latest=results.get(id)?.at(-1)?.observation;
      if(check.digest!==null)need(latest&&latest.observation_sha256===check.digest&&Date.parse(check.checked_at)>=Date.parse(latest.captured_at)&&check.status===(latest.state==='SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL'?'MATCHED':latest.state.startsWith('PENDING_')?'PENDING':'HOLD'));
      else need(!latest&&check.status!=='MATCHED');
    }
    return {schema:M.SCHEMA,dates:[...days.keys()].sort(),days,files,fileShas,results,resultUpdates:updates,frozenForecasts:frozen,nationwide,nationwideHistory,resultChecks:checks,cipherSha:null,formal:false,importedAt,sourceCommit:parts.find(part=>!part.shadowVerification)?.sourceCommit,refreshHolds,shadowVerifications,shadowVerificationHolds};
  }
  async function bytes(response,signal){
    need(response.ok);const length=response.headers?.get('content-length');need(length==null||/^\d+$/.test(length)&&Number(length)<=MAX);
    const reader=response.body?.getReader();need(reader);const parts=[];let size=0;
    try{for(;;){need(!signal?.aborted);const {value,done}=await reader.read();if(done)break;size+=value.byteLength;need(size<=MAX);parts.push(value);}}catch(e){await reader.cancel().catch(()=>{});throw e;}
    const result=new Uint8Array(size);let offset=0;for(const p of parts){result.set(p,offset);offset+=p.length;}return result;
  }
  async function createSession(key,{fetcher=globalThis.fetch}={}){
    let cap=await capability(key),previous=null,busy=false,closed=false;
    const cache=new Map();
    const sameEntry=(a,b)=>Object.keys(a).sort().every(name=>JSON.stringify(a[name])===JSON.stringify(b[name]));
    async function refresh({signal,onStatus}={}){
      need(!closed&&!busy&&!signal?.aborted);busy=true;
      try{
        const options={credentials:'omit',referrerPolicy:'no-referrer',cache:'no-store',redirect:'error',signal};
        const wire=await bytes(await fetcher(BASE+'index.json',options),signal);
        const index=checkIndex(JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(wire)),cap.recipient);
        if(previous){
          need(index.entries.length>=previous.entries.length&&(!previous.provider_denied||index.provider_denied));
          previous.entries.forEach((entry,i)=>need(sameEntry(entry,index.entries[i])));
          for(const [id,check] of Object.entries(previous.result_checks||{})){const fresh=index.result_checks?.[id];need(fresh&&Date.parse(fresh.checked_at)>=Date.parse(check.checked_at));}
        }
        const parts=[],archives=new Map(),displayCount=index.entries.filter(e=>e.kind!=='archive').length;
        for(const entry of index.entries){
          need(!closed&&!signal?.aborted);
          if(entry.kind==='archive'){archives.set(entry.cipher_sha256,entry);continue;}
          if(!cache.has(entry.cipher_sha256)){
            onStatus?.('暗号化した保存履歴を確認しています。 '+(parts.length+1)+' / '+displayCount);
            const body=await bytes(await fetcher(BASE+'views/'+entry.cipher_sha256+'.json',options),signal);
            const part=await openEntry(body,entry,cap,{archives});need(!closed&&!signal?.aborted);cache.set(entry.cipher_sha256,part);
          }
          parts.push(cache.get(entry.cipher_sha256));
        }
        need(!closed&&!signal?.aborted);
        const data=merge(parts,{resultChecks:index.result_checks||{}});
        data.feed={entries:index.entries.length,providerDenied:index.provider_denied,revision:await M.digest(wire),checkedAt:new Date().toISOString()};
        need(!closed&&!signal?.aborted);previous=index;return data;
      }finally{busy=false;}
    }
    return {refresh,close(){closed=true;cap=null;previous=null;cache.clear();}};
  }
  async function open(key,{signal,onStatus,fetcher=globalThis.fetch}={}){
    const session=await createSession(key,{fetcher});
    try{return await session.refresh({signal,onStatus});}finally{session.close();}
  }
  function watchSession(session,{onUpdate,onError=()=>{},isActive=()=>true,setTimer=globalThis.setTimeout,clearTimer=globalThis.clearTimeout}={}){
    need(typeof session?.refresh==='function'&&typeof onUpdate==='function');
    let closed=false,busy=false,timer=null,timeout=null,abort=null;
    async function check(){
      if(timer!==null){clearTimer(timer);timer=null;}
      if(closed||busy||!isActive())return;
      busy=true;abort=new AbortController();timeout=setTimer(()=>abort?.abort(),120000);
      try{const value=await session.refresh({signal:abort.signal});if(!closed&&!abort.signal.aborted)await onUpdate(value);}
      catch{if(!closed)onError();}
      finally{clearTimer(timeout);timeout=null;abort=null;busy=false;if(!closed&&isActive())timer=setTimer(check,30000);}
    }
    function stop(){if(closed)return;closed=true;if(timer!==null)clearTimer(timer);if(timeout!==null)clearTimer(timeout);timer=timeout=null;abort?.abort();session.close();}
    return {check,stop};
  }
  return {open,createSession,watchSession,openEntry,capability,checkIndex,merge,BASE};
});

/* A separate owner view. It never writes the formal model ledger or changes its keys. */
(() => {
  'use strict';
  const M=window.RaceKeirinNote,C=window.RaceKeirinConfidence;
  const reviewedGrowth = {"historical":{"from":"2026-10-01","to":"2026-11-22","races":3201,"days":48,"hits":{"top1_3t":{"baseline":401,"challenger":428},"top4_3t":{"baseline":928,"challenger":947},"top8_3t":{"baseline":1298,"challenger":1323},"top2_2t":{"baseline":1237,"challenger":1240}},"intervals":{"top4_3t":[0.0006240941083707286,0.01141774882240312],"top2_2t":[-0.004423415677557355,0.005897049978602079]}},"forward":{"day":"2026-11-25","registered":10,"matched":10,"hits":{"top1_3t":{"baseline":2,"challenger":2},"top4_3t":{"baseline":3,"challenger":4},"top8_3t":{"baseline":4,"challenger":4},"top2_2t":{"baseline":3,"challenger":3}}},"replay":{"day":"2026-11-25","race":"\u6b66\u96c41R","frames":12,"riders":6,"agreed":65,"correct":46,"incorrect":7,"abstained":12,"unscorable":7,"official_finish_positions":6,"trial_training_segments":2}};
  if(!M||!C||document.getElementById('keirin-note-dialog'))return;
  const fragment=window.RaceNoteInitialFragment||location.hash;
  const dialog=document.createElement('dialog');dialog.id='keirin-note-dialog';dialog.className='kn-modal';dialog.setAttribute('aria-label','競輪の予想・分析ガイド');
  const host=document.createElement('div');host.className='kn-host';dialog.append(host);
  const root=host.attachShadow({mode:'open'}),sheet=document.createElement('link');sheet.rel='stylesheet';sheet.href=document.querySelector('link[rel="stylesheet"]')?.href||'./style.css';root.append(sheet);
  const shell=document.createElement('div');shell.className='kn-shell';root.append(shell);document.body.append(dialog);
  const launcher=document.createElement('button');launcher.id='keirin-note-open';launcher.type='button';launcher.className='kn-launcher';launcher.textContent='競輪の予想・分析ガイドを開く';
  const strip=document.createElement('div');strip.className='kn-launch-strip';strip.append(launcher);(document.getElementById('data-banner')||document.querySelector('main'))?.after(strip);
  let data=null,currentDay='',venue='',query='',market='3t',variant='flexible',confidenceFilter='all',futureOnly=false,selectedOnly=false;
  let period='day',rangeFrom='',rangeTo='',raceNumber='',pageNumber=1;
  let riderDetails=null;
  let loadVersion=0,activeLoadAbort=null,feedWatcher=null,pendingFeed=null;
  const preferences=new Map(),selected=new Set(),expanded=new Set();
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money=v=>Number.isFinite(v)?v.toLocaleString('ja-JP')+'円':'未確認';
  const $=id=>root.getElementById(id),all=()=>M.historyRows(data,{period,day:currentDay,from:rangeFrom,to:rangeTo});
  const time=v=>v&&Number.isFinite(Date.parse(v))?new Date(v).toLocaleTimeString('ja-JP',{timeZone:'Asia/Tokyo',hour:'2-digit',minute:'2-digit'}):'未確認';
  const stamp=v=>v&&Number.isFinite(Date.parse(v))?new Date(v).toLocaleString('ja-JP',{timeZone:'Asia/Tokyo',hour12:false}):'未確認';
  const num=(v,suffix='')=>typeof v==='number'&&Number.isFinite(v)?esc(v)+suffix:'未確認';
  const car=n=>Number.isInteger(n)&&n>=1&&n<=9?'<span class="kn-car kn-c'+n+'">'+n+'</span>':'';
  const pref=row=>{const key=row.id+':'+market+':'+variant;if(!preferences.has(key))preferences.set(key,{budget:2500,excluded:new Set()});return preferences.get(key);};
  const riderAbilities=['捲りへの抵抗力','番手からの自力発動','並走時の持続力','戦術の切り替え能力','消耗後の末脚','内外の位置別能力'];
  function sourceLink(url,label){const safe=M.safeUrl(url);return safe?'<a target="_blank" rel="noopener noreferrer" href="'+esc(safe)+'">'+esc(label)+'</a>':'';}
  function note(message,error=false){$('kn-status').textContent=message;$('kn-status').classList.toggle('kn-error',error);}
  function beginLoad(){closeRiderDetails(false);loadVersion++;activeLoadAbort?.abort();activeLoadAbort=null;feedWatcher?.stop();feedWatcher=null;pendingFeed=null;return loadVersion;}
  function build(){
    shell.innerHTML=`<header class="kn-head"><div><p class="kn-eyebrow">RACE AI · KEIRIN NOTE</p><h1>競輪の読みどころ</h1><p>保存された分析・参考モデル・買い目を確認する</p></div><button type="button" id="kn-close" class="kn-close">閉じる</button></header>
      <div class="kn-scroll"><section class="kn-import"><div><label class="kn-file">保存データを開く<input id="kn-file" type="file" accept=".json,application/json"></label><button id="kn-clear" type="button" class="kn-secondary">読込データを消す</button></div><p id="kn-status" role="status">本人用リンク、または保存データJSONから開けます。</p></section>
      <section class="kn-history" aria-label="保存履歴を探す"><div class="kn-history-top"><label>日付を指定<input id="kn-date" type="date"></label><button type="button" data-history="all">全期間から探す</button></div><details id="kn-history-filters"><summary>期間・レース番号で絞り込む</summary><div class="kn-history-grid"><label>検索する期間<select id="kn-period"><option value="day">指定した1日</option><option value="range">期間を指定</option><option value="all">すべての保存日</option></select></label><label>レース番号<select id="kn-race-number"><option value="">すべてのレース</option>${Array.from({length:12},(_,i)=>'<option value="'+(i+1)+'">'+(i+1)+'R</option>').join('')}</select></label><label id="kn-from-label" hidden>開始日<input id="kn-from" type="date"></label><label id="kn-to-label" hidden>終了日<input id="kn-to" type="date"></label></div><div class="kn-history-shortcuts"><button type="button" data-history="latest">最新日</button><button type="button" data-history="week">直近7日</button><button type="button" id="kn-reset-search">条件をリセット</button></div></details><p id="kn-period-status" class="kn-small" role="status"></p></section>
      <nav id="kn-days" class="kn-day-tabs" aria-label="予想の日付"></nav><section id="kn-metrics" class="kn-metrics"></section>
      <details id="kn-growth" class="kn-growth" hidden><summary>成長記録</summary><div id="kn-growth-content" class="kn-growth-content"></div><div id="kn-shadow-growth"></div></details>
      <section class="kn-tools"><div id="kn-venues" class="kn-venues" aria-label="会場"></div><div class="kn-prediction-tabs" aria-label="通常予想と転がし予想"><button type="button" data-prediction="flexible">通常予想</button><button type="button" data-prediction="rollover">転がし予想</button><button type="button" data-confidence-filter="high_plus">高以上だけ見る</button></div><div class="kn-controls"><label>券種<select id="kn-market"><option value="3t">3連単</option><option value="2t">2車単</option></select></label><label>表示する予想<select id="kn-variant"><option value="flexible">通常予想・改訂版</option><option value="original">通常予想・原版</option><option value="rollover">転がし予想</option><option value="A">参考A</option><option value="B">参考B・6局面</option><option value="C">参考Cの状況</option></select></label><label>展開評価<select id="kn-confidence"><option value="all">すべて</option><option value="high_plus">高以上（高・激アツ🔥）</option><option value="hot">激アツ🔥のみ</option><option value="high">高のみ</option><option value="medium">中のみ</option><option value="low">低のみ</option><option value="unrated">未評価のみ</option></select></label><label class="kn-search-label">検索<input id="kn-search" type="search" placeholder="会場・選手・レース名"></label></div><div class="kn-small-controls"><label><input id="kn-future" type="checkbox">これからのレース</label><label><input id="kn-selected" type="checkbox">検討リストのみ</label><span id="kn-count"></span></div><p id="kn-confidence-count" class="kn-small" aria-live="polite"></p><p class="kn-small">展開評価は保存時の展開と買い目の整合です。<a href="#keirin-public">的中確率と検証実績を見る</a></p></section>
      <section id="kn-nationwide-summary" class="kn-result kn-nationwide-summary" hidden></section><section id="kn-research-summary" class="kn-result" hidden></section><div id="kn-result-only"></div><div id="kn-races" class="kn-grid"></div>
      <details class="kn-rollover"><summary>転がし・2段階の資金配分を試算する</summary><p>受取額は払戻と返還の合計を手入力します。実購入の記録とは別の試算です。</p><div class="kn-controls"><label>初回の予算<select id="kn-roll-budget"><option>2000</option><option selected>2500</option><option>3000</option></select></label><label>1戦目の受取額<input id="kn-return-one" type="number" min="0" max="100000000" step="100" placeholder="未入力"></label><label>2戦目の受取額<input id="kn-return-two" type="number" min="0" max="100000000" step="100" placeholder="未入力"></label></div><div id="kn-roll-result"></div></details>
      <footer class="kn-footer"><p>個別分析・改訂・参考A/Bはそれぞれの保存原本を保持します。参考Cの未生成も表示します。参考モデルの重みは校正済み確率ではありません。</p><p>画面での選択と配分は購入候補です。投票・決済は行いません。データと本人用リンクの鍵は外部へ送信しません。</p><p id="kn-provenance"></p></footer></div>
      <div class="kn-selection"><div><strong id="kn-selection-count">検討リスト 0件</strong><small>候補・配分の試算</small></div><button id="kn-copy-selection" type="button">検討リストをコピー</button></div>
      <dialog id="kn-rider-details" class="kn-rider-dialog" aria-labelledby="kn-rider-heading">
        <header><div><p id="kn-rider-venue" class="kn-small"></p><h2 id="kn-rider-heading"></h2></div><button type="button" data-rider-close autofocus>閉じる</button></header>
        <label class="kn-rider-switch">選手を切り替える<select id="kn-rider-select"></select></label>
        <div id="kn-rider-facts"></div>
      </dialog>`;
    $('kn-close').addEventListener('click',()=>dialog.close());
    dialog.addEventListener('close',()=>closeRiderDetails(false));
    $('kn-rider-select').addEventListener('change',event=>renderRiderDetails(Number(event.target.value)));
    $('kn-rider-details').addEventListener('close',restoreRiderFocus);
    $('kn-rider-details').addEventListener('cancel',event=>event.stopPropagation());
    $('kn-file').addEventListener('change',async event=>{
      // Shadow-tree event targets are cleared after dispatch. Keep the input
      // itself before awaiting file reads so the completed import can reset it.
      const input=event.currentTarget,file=input.files?.[0];if(!file)return;
      const version=beginLoad();
      try{if(file.size>64*1024*1024)throw Error();note('保存データを確認しています。');await accept(await M.openPacket(JSON.parse(await file.text())),version);}
      catch{if(version===loadVersion)note('保存データを開けませんでした。形式と原本の整合を確認してください。',true);}
      if(version===loadVersion)input.value='';
    });
    $('kn-clear').addEventListener('click',()=>{beginLoad();data=null;resetSearch();preferences.clear();selected.clear();expanded.clear();if(/^#(?:note|notefeed)=/.test(location.hash)){history.replaceState(null,'',location.pathname+location.search);window.RaceNoteInitialFragment='';}render();note('読込データを消去しました。');});
    $('kn-market').addEventListener('change',event=>{market=event.target.value;pageNumber=1;renderCards();});
    $('kn-variant').addEventListener('change',event=>{variant=event.target.value;pageNumber=1;renderCards();});
    $('kn-confidence').addEventListener('change',event=>{confidenceFilter=event.target.value;pageNumber=1;renderCards();});
    $('kn-search').placeholder='会場・選手・日付・5R（例：青葉 1R）';$('kn-search').maxLength=200;
    $('kn-search').addEventListener('input',event=>{query=event.target.value;pageNumber=1;renderCards();});
    $('kn-future').addEventListener('change',event=>{futureOnly=event.target.checked;pageNumber=1;renderCards();});
    $('kn-selected').addEventListener('change',event=>{selectedOnly=event.target.checked;pageNumber=1;renderCards();});
    $('kn-date').addEventListener('change',event=>{currentDay=event.target.value;period='day';venue='';pageNumber=1;pastSearch();render();});
    $('kn-period').addEventListener('change',event=>{period=event.target.value;pageNumber=1;pastSearch();render();});
    for(const id of ['kn-from','kn-to'])$(id).addEventListener('change',event=>{
      if(id==='kn-from')rangeFrom=event.target.value;else rangeTo=event.target.value;
      pageNumber=1;render();
    });
    $('kn-race-number').addEventListener('change',event=>{raceNumber=event.target.value;pageNumber=1;renderCards();});
    $('kn-reset-search').addEventListener('click',()=>{resetSearch();render();});
    const pagination=document.createElement('nav');pagination.id='kn-pagination';pagination.className='kn-pagination';pagination.setAttribute('aria-label','検索結果のページ');
    pagination.innerHTML='<button type="button" id="kn-page-prev">前へ</button><label>ページ<input id="kn-page" type="number" min="1" inputmode="numeric"></label><span id="kn-page-total"></span><button type="button" id="kn-page-next">次へ</button>';
    $('kn-races').after(pagination);$('kn-races').tabIndex=-1;
    $('kn-page').addEventListener('change',event=>{pageNumber=Number(event.target.value);renderCards();});
    root.addEventListener('click',event=>click(event.target.closest('button')));
    root.addEventListener('change',event=>{const e=event.target;if(e.matches('[data-budget]')){const row=all().find(r=>r.id===e.dataset.budget);if(row){pref(row).budget=Number(e.value);renderCards();}}else if(e.matches('[data-ticket]')){const row=all().find(r=>r.id===e.dataset.race);if(row){const p=pref(row);e.checked?p.excluded.delete(e.dataset.ticket):p.excluded.add(e.dataset.ticket);renderCards();}}});
    for(const id of ['kn-roll-budget','kn-return-one','kn-return-two'])$(id).addEventListener('input',renderRollover);
    $('kn-copy-selection').addEventListener('click',()=>copy(all().filter(r=>selected.has(r.id)).map(copyRace).filter(Boolean).join('\n\n')));
    render();renderRollover();
  }
  function pastSearch(){futureOnly=false;$('kn-future').checked=false;}
  function sevenDaysBefore(date){return M.day(date)?new Date(Date.parse(date+'T00:00:00Z')-6*86400000).toISOString().slice(0,10):'';}
  function resetSearch(){
    period='day';currentDay=data?.dates.at(-1)||'';rangeTo=currentDay;rangeFrom=sevenDaysBefore(currentDay);
    venue='';query='';raceNumber='';pageNumber=1;confidenceFilter='all';selectedOnly=false;pastSearch();
    $('kn-search').value='';$('kn-confidence').value='all';$('kn-selected').checked=false;
  }
  async function accept(value,version){if(version!==loadVersion)return;data=value;resetSearch();preferences.clear();selected.clear();expanded.clear();const authored=all().some(row=>row.original?.tickets?.length||row.two?.tickets?.length||row.flexible?.markets?.['3t']?.tickets?.length||row.flexible?.markets?.['2t']?.tickets?.length);variant=authored?'flexible':'A';if(!authored){market='3t';$('kn-market').value=market;}$('kn-variant').value=variant;render();note(data.feed?.providerDenied?'保存データを端末内で開きました。入力元への取得は停止中です。保存済み結果の更新は確認します。':'保存データを端末内で開きました。',Boolean(data.feed?.providerDenied));}
  function refreshDisplay(value,version){
    if(version!==loadVersion)return;
    if(root.activeElement?.matches('[data-budget],[data-ticket]')){pendingFeed={value,version};return;}
    pendingFeed=null;const same=data?.feed?.revision===value.feed?.revision;
    data=value;
    if(same){renderProvenance();note(data.feed?.providerDenied?'保存データの更新を確認しました。入力元への取得は停止中です。':'保存データの更新を確認しました。',Boolean(data.feed?.providerDenied));return;}
    const scroll=root.querySelector('.kn-scroll'),position=scroll.scrollTop;render();scroll.scrollTop=position;
    note(data.feed?.providerDenied?'保存された結果を更新しました。入力元への取得は停止中です。':'保存された最新の結果を反映しました。',Boolean(data.feed?.providerDenied));
  }
  function renderProvenance(){
    const observations=data?[...data.resultUpdates.values()].flatMap(rows=>[...rows.values()].map(r=>r.observed_at)):[];
    const latest=observations.sort((a,b)=>Date.parse(a)-Date.parse(b)).at(-1);
    $('kn-provenance').textContent=data?'読込日時 '+stamp(data.importedAt)+' · 出典と予想時点は各レースで確認できます。'+(data.feed?' · 表示確認 '+stamp(data.feed.checkedAt)+'（表示中は30秒ごとに保存データを確認）':'')+(latest?' · 結果確認 '+stamp(latest):'')+(data.refreshHolds?.length?' · 入力変更 '+data.refreshHolds.length+'件は原分析との照合待ちです。':''):'';
  }
  function render(){
    const days=data?.dates||[];let shortcuts=days.slice(-7);
    if(days.includes(currentDay)&&!shortcuts.includes(currentDay))shortcuts=[currentDay,...shortcuts.slice(-6)].sort();
    const showYears=new Set(shortcuts.map(d=>d.slice(0,4))).size>1;
    const fullDate=d=>d.slice(0,4)+'年'+Number(d.slice(5,7))+'月'+Number(d.slice(8,10))+'日';
    $('kn-days').innerHTML=shortcuts.map(d=>'<button type="button" data-day="'+esc(d)+'" aria-label="'+fullDate(d)+'" aria-pressed="'+(period==='day'&&d===currentDay)+'">'+esc(showYears?fullDate(d):d.slice(5).replace('-','月')+'日')+'</button>').join('');
    $('kn-date').value=currentDay;$('kn-date').disabled=period!=='day';$('kn-period').value=period;
    $('kn-from').value=rangeFrom;$('kn-to').value=rangeTo;$('kn-race-number').value=raceNumber;
    $('kn-from-label').hidden=$('kn-to-label').hidden=period!=='range';
    const invalid=period==='range'&&(!M.day(rangeFrom)||!M.day(rangeTo)||rangeFrom>rangeTo);
    $('kn-period-status').textContent=!data?'保存データを開くと日付・期間を指定できます。':invalid?'開始日と終了日を確認してください。開始日は終了日以前を指定してください。':period==='all'?'すべての保存日を検索します。':period==='range'?rangeFrom+' 〜 '+rangeTo+' の保存データを検索します。':!M.day(currentDay)?'日付を指定してください。':!days.includes(currentDay)?'指定した日付の保存データはありません。':currentDay+' の保存データを表示します。';
    if(venue)$('kn-period-status').textContent+=' · 会場：'+venue;
    $('kn-period-status').classList.toggle('kn-error',invalid);
    $('kn-metrics').hidden=period!=='day';
    const list=all();
    const nationwide=period==='day'?data?.nationwide?.get(currentDay):null,saved=nationwide?.races.filter(row=>row.original_identity).length||0,adjusted=nationwide?.races.filter(row=>row.original_identity?.conditioned).length||0;
    if(period==='day'){
      const riders=list.reduce((n,r)=>n+r.riders.length,0),original=list.reduce((n,r)=>n+M.forecast(r,'3t','original').tickets.length,0),priced=list.filter(r=>r.quote.fetched_at).length;
      const metrics=nationwide?[['確認した対象',nationwide.registry_available?nationwide.races.length+'件':'確認中'],['A保存済み',saved+'件'],['B保存済み',saved+'件'],['補正A/B保存済み',adjusted+'件']]:[['対象レース',list.length+'件'],['出走メンバー',riders+'名'],['原分析の買い目',original+'点'],['保存オッズ',priced+'レース']];
      $('kn-metrics').innerHTML=metrics.map(([k,v])=>'<div><span>'+esc(k)+'</span><strong>'+esc(v)+'</strong></div>').join('');
    }else $('kn-metrics').textContent='';
    const imported=list.some(row=>!row.nationwideOnly),onlyNational=Boolean(nationwide)&&!imported;$('kn-market').disabled=onlyNational;$('kn-variant').disabled=onlyNational;
    if(onlyNational){market='3t';$('kn-market').value=market;}
    for(const button of root.querySelectorAll('[data-prediction]'))button.disabled=onlyNational;
    const availableVenues=new Set(list.map(r=>r.venue)),venues=[...availableVenues];
    if(venue&&!availableVenues.has(venue))venues.unshift(venue);
    $('kn-venues').innerHTML=[['','締切順・全会場'],...venues.map(v=>[v,v+(availableVenues.has(v)?'':'（この期間は0件）')])].map(([v,label])=>'<button type="button" data-venue="'+esc(v)+'" aria-pressed="'+(v===venue)+'">'+esc(label)+'</button>').join('');
    renderProvenance();
    renderGrowth();
    renderCards();
  }
  function signedGrowth(value,digits=0){
    return (value>0?'+':value<0?'−':'')+Math.abs(value).toFixed(digits);
  }
  function growthTable(hits,heading,races=0){
    const metrics=[['top1_3t','三連単1点'],['top4_3t','三連単4点'],['top8_3t','三連単8点'],['top2_2t','二車単2点']];
    const cell=value=>races?`<strong>${(100*value/races).toFixed(2)}%</strong><small>${value.toLocaleString('ja-JP')}件</small>`:`${value}件`;
    const rows=metrics.map(([key,label])=>{
      const {baseline,challenger}=hits[key],difference=challenger-baseline;
      const change=races?signedGrowth(100*difference/races,2)+'pt':signedGrowth(difference)+'件';
      return `<tr><th scope="row">${label}</th><td>${cell(baseline)}</td><td>${cell(challenger)}</td><td>${change}</td></tr>`;
    });
    return `<table aria-labelledby="${heading}"><thead><tr><th scope="col">指標</th><th scope="col">保存B</th><th scope="col">比較B</th><th scope="col">差</th></tr></thead><tbody>${rows.join('')}</tbody></table>`;
  }
  function renderShadowGrowth(){
    const target=$('kn-shadow-growth');
    const checks=data?.feed?data.shadowVerifications:null;
    if(!checks?.size){target.textContent='';return false;}
    const hit=value=>value?'的中':'不的中';
    const markets=[['trifecta','三連単'],['exacta','二車単']];
    const entries=[...checks.values()].reverse().map(({race_id:id,day_jst:day,original,result,scores})=>{
      const race=M.rows(data,day).find(row=>row.id===id);
      const label=race?`${race.venue} ${race.number}R`:id;
      const evidence=result.scope==='TWO_SOURCE_MATCHED_PODIUM_ONLY'?'2媒体で一致した上位着順':'保存した公式全着順';
      const rows=markets.map(([market,name])=>{
        const score=scores[market];
        return `<tr><th scope="row">${name}</th><td>${score.points}点</td><td>${hit(score.saved_hit)}</td><td>${hit(score.challenger_hit)}</td></tr>`;
      }).join('');
      const warning=data.shadowVerificationHolds.has(id)?'<p class="kn-small">先に照合した比較を表示しています。後から届いた照合は保留です。</p>':'';
      return `<article><h3 id="kn-shadow-${esc(id)}">${esc(day)} · ${esc(label)}</h3>
        <p class="kn-small">${evidence} · ${stamp(result.observed_at)}</p>
        <table aria-labelledby="kn-shadow-${esc(id)}"><thead><tr><th scope="col">券種</th><th scope="col">点数</th><th scope="col">保存B</th><th scope="col">比較B</th></tr></thead><tbody>${rows}</tbody></table>
        <p>追跡・学習は保留</p>${warning}
        <details class="kn-details"><summary>照合資料</summary>
          <p>締切前原本 <code>${esc(original.sha256)}</code></p><p>結果根拠 <code>${esc(result.evidence_sha256)}</code></p>
        </details></article>`;
    }).join('');
    const markup=`<div class="kn-growth-content"><section aria-labelledby="kn-growth-shadow"><h2 id="kn-growth-shadow">締切前に保存した研究比較の検証</h2>${entries}</section></div>`;
    if(target.innerHTML!==markup)target.innerHTML=markup;
    return true;
  }
  function renderGrowth(){
    const panel=$('kn-growth'),content=$('kn-growth-content');
    const shadowVisible=renderShadowGrowth();
    panel.hidden=!data||(!reviewedGrowth&&!shadowVisible);
    if(panel.hidden){panel.open=false;content.textContent='';return;}
    if(!reviewedGrowth||content.hasChildNodes())return;
    const {historical,forward,replay}=reviewedGrowth;
    const interval=key=>historical.intervals[key].map(value=>signedGrowth(value*100,2)).join('〜')+'ポイント';
    content.innerHTML=`<section aria-labelledby="kn-growth-historical"><h2 id="kn-growth-historical">既知期間の再現</h2>
      <p class="kn-small">${esc(historical.from)}〜${esc(historical.to)} · ${historical.races.toLocaleString('ja-JP')}件</p>
      <p>保存Bの順位モデルに条件別の補正を加え、同じ入力と点数で比較しました。</p>
      ${growthTable(historical.hits,'kn-growth-historical',historical.races)}
      <p class="kn-small">${historical.days}開催日を単位にした差の95%範囲は、三連単4点が${interval('top4_3t')}、二車単2点が${interval('top2_2t')}です。A級3班・L級・9車では三連単4点の的中率が下がりました。</p></section>
      <section aria-labelledby="kn-growth-forward"><h2 id="kn-growth-forward">掲載締切前の保存原本</h2>
      <p class="kn-small">${esc(forward.day)} · 照合 ${forward.matched} / ${forward.registered}件</p>
      <p>原本を別の実行環境で復号し、2媒体で一致した結果を同じ点数で採点しました。</p>
      ${growthTable(forward.hits,'kn-growth-forward')}
      <p class="kn-small">主催者による締切・公式結果の認証は未確認です。</p></section>
      <section aria-labelledby="kn-growth-replay"><h2 id="kn-growth-replay">映像検証</h2>
      <p class="kn-small">${esc(replay.day)} · ${esc(replay.race)} · ${replay.frames}フレーム・${replay.riders}車</p>
      <p>追跡結果を伏せて別々に行ったAI判読が一致した${replay.agreed}件を照合しました。車番追跡は一致${replay.correct}件、誤り${replay.incorrect}件、判定保留${replay.abstained}件でした。判読できなかった${replay.unscorable}件は集計から外しました。</p>
      <p>公式着順は${replay.official_finish_positions}車分を別に照合しました。映像で確認した動き${replay.trial_training_segments}件を試験学習に使用し、本番採用は保留です。</p></section>
      <p class="kn-growth-decision">比較Bの採用は保留です。精度向上を判定するには、未使用の複数開催日での比較が必要です。</p>`;
  }
  function renderCards(){
    const list=all(),now=Date.now();const candidates=list.filter(r=>M.matchesHistory(r,{venue,query,raceNumber})&&(!futureOnly||r.cutoff&&Date.parse(r.cutoff)>now)&&(!selectedOnly||selected.has(r.id))&&(r.nationwideOnly||variant!=='rollover'||M.forecast(r,market,variant).tickets.length>0));
    const shown=candidates.filter(r=>confidenceFilter==='all'||displayedPredictions(r).some(prediction=>C.predictionMatches(prediction,confidenceFilter)));
    const page=M.historyPage(shown,pageNumber);pageNumber=page.page;
    $('kn-count').textContent='表示 '+page.first+'〜'+page.last+' / 該当 '+shown.length+'件（対象 '+list.length+'レース）';
    $('kn-pagination').hidden=page.pages<=1;$('kn-page-prev').disabled=page.page<=1;$('kn-page-next').disabled=page.page>=page.pages;
    $('kn-page').value=String(page.page);$('kn-page').max=String(page.pages);$('kn-page-total').textContent='/ '+page.pages+'ページ';
    const counts=[0,0,0,0,0];for(const row of candidates)for(const prediction of displayedPredictions(row))if(prediction.tickets.length)counts[C.normalize(prediction.confidence).rank]++;
    $('kn-confidence-count').textContent='表示条件内の展開評価：激アツ🔥 '+counts[4]+'件 / 高 '+counts[3]+'件 / 中 '+counts[2]+'件 / 低 '+counts[1]+'件 / 未評価 '+counts[0]+'件';
    for(const button of root.querySelectorAll('[data-prediction]'))button.setAttribute('aria-pressed',String(button.dataset.prediction==='rollover'?variant==='rollover':['original','flexible'].includes(variant)));
    root.querySelector('[data-confidence-filter]').setAttribute('aria-pressed',String(confidenceFilter==='high_plus'));
    const empty=data?(confidenceFilter==='high_plus'||confidenceFilter==='hot'?'この条件に合う保存予想はありません。展開評価は保存時の判定を表示しています。':variant==='rollover'?'この条件の転がし候補はありません。':'条件に合うレースはありません。'):'本人用リンク、または保存データを開くと予想を表示します。';
    $('kn-races').innerHTML=page.items.length?page.items.map(renderRace).join(''):'<div class="kn-empty">'+empty+'</div>';
    renderNationwideSummary();
    renderResearchSummary(list);
    selectionSummary();
    if(riderDetails&&$('kn-rider-details').open)renderRiderDetails(riderDetails.number);
  }
  function displayedPredictions(row){return M.displayedPredictions(row,market,variant);}
  function confidenceBadge(prediction){const value=C.normalize(prediction.confidence);return '<span class="kn-confidence kn-confidence-'+value.rank+'" data-confidence-rank="'+value.rank+'">展開評価 '+esc(C.displayLabel(prediction.confidence))+'</span>';}
  function confidenceEvidence(prediction){
    const entry=prediction.confidenceAssessment,bundle=prediction.confidenceBundle;if(!entry||!bundle)return '';
    return '<details class="kn-details kn-confidence-evidence"><summary>展開評価の根拠</summary><p>保存時の展開と買い目の整合を評価した記録です。</p><ul>'+entry.reasons.map(reason=>'<li>'+esc(reason.message)+'</li>').join('')+'</ul><p class="kn-small">'+entry.limitations.map(esc).join('<br>')+'</p><p class="kn-small">評価 '+stamp(bundle.assessed_at)+' · ルール '+esc(bundle.rules_version)+'</p></details>';
  }
  function lineHtml(row){
    const line=n=>Number.isInteger(n)?car(n):n&&Array.isArray(n.contest)?'<span class="kn-contest">'+n.contest.map(car).join('')+'<small>競り</small></span>':'';
    return row.lines.map(group=>'<span class="kn-line">'+(Array.isArray(group)?group:[]).map(line).join('<span>−</span>')+'</span>').join('<span class="kn-line-gap">/</span>');
  }
  function renderRace(row){
    if(row.nationwideOnly||confidenceFilter!=='all'&&!C.predictionMatches(M.forecast(row,market,variant),confidenceFilter))return renderNationwideRace(row);
    const prediction=M.forecast(row,market,variant),p=pref(row),allocation=M.allocate(prediction,p.budget,p.excluded),key=row.id+':'+market+':'+variant,open=expanded.has(key);
    const late=row.cutoff&&Date.parse(row.cutoff)<Date.now();
    const items=prediction.tickets.map((ticket,i)=>{
      const quote=row.quote[market==='2t'?'odds_2t':'odds_3t']?.[ticket.combo],status=row.quote[market==='2t'?'quote_status_2t':'quote_status_3t']?.[ticket.combo];
      const odds=typeof quote==='number'&&quote>0&&quote<9999.9?quote+'倍':status==='capped'?'上限表示':'未確認';
      return '<div class="kn-ticket '+(!open&&i>=3?'kn-ticket-folded':'')+'"><label>'+ (prediction.allocatable?'<input type="checkbox" data-ticket="'+esc(ticket.combo)+'" data-race="'+row.id+'" '+(!p.excluded.has(ticket.combo)?'checked':'')+' aria-label="'+esc(ticket.combo)+'を配分対象にする">':'')+'<span class="kn-combo">'+ticket.combo.split('-').map(Number).map(car).join('<span>−</span>')+'</span><span class="kn-role">'+esc(ticket.role)+'</span></label><div><b>'+ (prediction.allocatable?money(allocation.amounts[i]):'比較用')+'</b><small>'+esc(odds)+'</small></div></div>';
    }).join('');
    const outcome=row.settlement;
    const result=liveResult(row)+(outcome?'<section class="kn-result"><b>提供サイトの保存分析の照合</b><p>'+esc(outcome.winning_combo||'結果未確認')+' · '+(outcome.sources_agree===false?'出典間の相違で保留':outcome.hit?'的中':outcome.status==='MISS'?'不的中':esc(outcome.status||'照合未確認'))+'</p><p>各100円の想定：'+money(outcome.net_yen)+'（実購入ではありません）</p></section>':'');
    const budget=prediction.allocatable?'<div class="kn-budget"><label>候補予算<select data-budget="'+row.id+'">'+[2000,2500,3000].map(n=>'<option value="'+n+'" '+(n===p.budget?'selected':'')+'>'+money(n)+'</option>').join('')+'</select></label><span>配分 '+allocation.chosen.length+'点 / 合計 '+money(allocation.total)+'</span></div>':'';
    return '<article class="kn-race" data-note-race="'+row.id+'"><div class="kn-race-top"><div><p class="kn-race-date">'+esc(row.date)+'</p><h2>'+esc(row.venue)+' '+row.number+'R</h2><p>'+esc(row.title)+'</p></div><div class="kn-time"><small>掲載締切</small><b>'+time(row.cutoff)+'</b><small>発走 '+time(row.start)+'</small></div></div><div class="kn-badges"><span>'+esc(prediction.label)+'</span>'+(late?'<span class="kn-past">掲載締切後</span>':'')+confidenceBadge(prediction)+'</div><h3>'+esc(prediction.headline)+'</h3><p class="kn-reason">'+esc(prediction.reason)+'</p>'+confidenceEvidence(prediction)+'<div class="kn-lines">'+lineHtml(row)+'</div><p class="kn-small">媒体の並び予想・位置取りの参考です。</p>'+riderButtons(row)+budget+
      '<div class="kn-point-heading"><b>予想 '+prediction.tickets.length+'点'+(prediction.allocatable?' · 配分 '+allocation.chosen.length+'点':'')+'</b></div><div class="kn-tickets">'+(items||'<p class="kn-empty">'+esc(prediction.reason||'この券種の保存予想はありません。')+'</p>')+'</div>'+(prediction.tickets.length>3?'<button type="button" class="kn-more" data-expand="'+row.id+'">'+(open?'上位3点に戻す':'全'+prediction.tickets.length+'点を表示')+'</button>':'')+
      (prediction.allocatable&&!allocation.available?'<p class="kn-warning">配分対象がないか、全点への100円単位の配分に予算が足りません。点数を選び直してください。</p>':'')+
      '<div class="kn-race-actions"><button type="button" data-select="'+row.id+'" aria-pressed="'+selected.has(row.id)+'">'+(selected.has(row.id)?'検討リストから外す':'検討リストに追加')+'</button><button type="button" data-copy="'+row.id+'" '+(prediction.allocatable&&!allocation.available?'disabled':'')+'>買い目をコピー</button></div>'+nationalStatus(row)+result+researchResult(row)+
      scenarios(prediction.scenarios)+roster(row)+
      '<details class="kn-details"><summary>出典・予想時点・注意点</summary><p>'+esc(prediction.risk||'保存された条件付きの分析です。')+'</p><p>予想の記載時点 '+stamp(prediction.createdAt)+'</p><p>オッズの保存時点 '+stamp(row.quote.source_updated_at||row.quote.fetched_at)+'</p><p>'+esc(row.quote.scope_label||'保存時点の値。現在値は掲載元で確認してください。')+'</p>'+sourceLink(row.sourceUrl,'出走表・掲載オッズ')+referenceProvenance(row)+'<p class="kn-small">参考A/Bは既存計算、Cは独立した連係履歴が不足しているため未生成です。正式な全モデル実測の認証とは別に表示しています。</p></details></article>';
  }
  function nationalStateLabel(state){
    const labels={WAITING_SOURCE_CAPTURE:'出走表などの取得待ち',UNSUPPORTED_CLASS_OR_ROUND:'この種別・勝ち上がり条件の確認待ち',PUBLISHED_RESULT_NO_PRE_CUTOFF_ORIGINAL:'締切前の保存予想なし',FROZEN_ORIGINAL_PRESERVED:'締切前に保存した予想を保持',SOURCE_CAPTURE_BUDGET_PENDING:'次の情報取得を待っています',CUTOFF_MARGIN_INSUFFICIENT:'締切前の保存に間に合わず未作成',BASELINE_SOURCE_UNVERIFIED:'出走表・並びの照合待ち',PROVIDER_STOPPED:'取得先の制限により情報収集を停止中',SOURCE_UNAVAILABLE:'必要な情報を取得できず保留',A_B_ARCHIVED_AWAITING_INDEPENDENT_READBACK:'A/Bの保存内容を確認中',A_B_AUTHENTICATED_PRE_CUTOFF:'A/Bの締切前保存を確認済み',ORIGIN_PROOF_PENDING:'締切前の保存記録を確認中',FROZEN_ARCHIVE_UNVERIFIED:'保存原本の再確認待ち',RACE_DISAPPEARED_FROM_CURRENT_LIST:'開催一覧から外れたため確認中'};
    return labels[state]||'保存状況を確認中';
  }
  function conditionLabel(state){
    const labels={HISTORY_NOT_COLLECTED:'近況・落車後の資料を収集中',HISTORY_SOURCE_UNAVAILABLE:'近況・落車後の資料を取得できず補正は保留',HISTORY_UNVERIFIED:'近況・落車後の資料を照合中',INSUFFICIENT_CAPTURE_MARGIN:'締切までに補正を保存できず未作成',CONDITIONED_ARCHIVED_AWAITING_READBACK:'補正A/Bの保存内容を確認中',CONDITIONED_AUTHENTICATED_PRE_CUTOFF:'補正A/Bの締切前保存を確認済み',CONDITIONED_ORIGIN_PROOF_PENDING:'補正A/Bの保存記録を確認中',CONDITIONED_ARCHIVE_UNVERIFIED:'補正A/Bの原本を再確認中',NO_CONDITIONED_ORIGINAL:'補正A/Bの保存予想なし'};
    return labels[state]||'補正A/Bの資料待ち';
  }
  function nationalStatus(row){
    const status=row.nationwideStatus;if(!status)return '';
    return '<section class="kn-nationwide-status" data-nationwide-state="'+esc(status.state)+'"><p><b>'+nationalStateLabel(status.state)+'</b></p><p>'+conditionLabel(status.condition_state)+'</p>'+(status.original_identity&&!row.frozenForecast?'<p class="kn-warning">以前に保存した買い目は未読込です。未作成や不的中には数えていません。</p>':'')+'</section>';
  }
  function renderNationwideRace(row){
    return '<article class="kn-race kn-national-race" data-note-race="'+row.id+'"><div class="kn-race-top"><div><p class="kn-race-date">'+esc(row.date)+'</p><h2>'+esc(row.venue)+' '+row.number+'R</h2><p>各予想の買い目・根拠・採点を確認できます。</p></div><div class="kn-time"><small>掲載締切</small><b>'+time(row.cutoff)+'</b></div></div>'+riderButtons(row)+nationalStatus(row)+liveResult(row)+researchResult(row)+roster(row)+'</article>';
  }
  function renderNationwideSummary(){
    const panel=$('kn-nationwide-summary'),doc=period==='day'?data?.nationwide?.get(currentDay):null;
    if(!doc){panel.hidden=true;panel.textContent='';return;}
    const total=doc.races.length,saved=doc.races.filter(row=>row.original_identity).length,adjusted=doc.races.filter(row=>row.original_identity?.conditioned).length,unread=doc.races.filter(row=>row.original_identity&&!row.original).length,unsupported=doc.races.filter(row=>row.state==='UNSUPPORTED_CLASS_OR_ROUND').length;
    panel.hidden=false;panel.dataset.registeredRaces=total;
    const heading=doc.inventory_complete?'全'+total+'レースの保存状況':'確認できた'+total+'レースの保存状況';
    const coverage=doc.inventory_complete?'この日付の登録済み全レースが分母です。':(doc.registry_available?'全国の対象総数はまだ確認中です。':'この日の開催一覧をまだ確認できていません。')+(doc.missing_venues.length?' 未確認の開催コード：'+doc.missing_venues.map(n=>String(n).padStart(2,'0')).join('・'):'');
    panel.innerHTML='<h2>'+heading+'</h2><p>A/B保存済み '+saved+' / '+total+'件 · 補正A/B保存済み '+adjusted+' / '+total+'件</p><p>保存予想が未確認 '+(total-saved)+'件（うち種別・条件の確認待ち '+unsupported+'件）</p>'+(unread?'<p class="kn-warning">保存記録は確認できましたが、買い目の原本が未読込のレースが '+unread+'件あります。</p>':'')+'<p class="kn-small">'+esc(coverage)+' 未作成は外れに含めません。Cは別に未作成を表示します。</p><p class="kn-small">保存状況の確認 '+stamp(doc.observed_at)+'</p>';
  }
  function frozenBasis(saved){
    const facts=saved.facts,styles={NIGE:'逃げ',MAKURI:'捲り',SASHI:'差し',MARK:'追込',ALLROUND:'自在',UNKNOWN:'未確認'};
    const line=facts.line_groups.map(g=>g.join('−')).join(' / ');
    const factsTable='<p>保存時の'+(facts.competition==='GIRLS'?'位置取りの仮定':'並び予想')+'：'+esc(line)+'</p><div class="kn-table-scroll"><table><thead><tr><th>車</th><th>印順位</th><th>得点</th><th>近況値</th><th>H/B</th><th>脚質</th></tr></thead><tbody>'+facts.riders.map(r=>'<tr><td>'+r.car+'</td><td>'+(r.mark_rank==='UNMARKED'?'無印':r.mark_rank)+'</td><td>'+r.competition_points+'</td><td>'+r.recent_form_score+'</td><td>'+r.h_count+'/'+r.b_count+'</td><td>'+styles[r.style]+'</td></tr>').join('')+'</tbody></table></div>';
    const actions={PREDICTED_LINE_ORDER_ONLY:'掲載の並びを出発点にする想定',LEADER_ATTACKS:'主導権候補が動く想定',CHALLENGER_EARLY_COUNTER:'別の先頭候補が早めに仕掛け返す想定',LEADER_TRIES_TO_HOLD_PACE:'主導権候補がペースを保つ想定',LEADER_MAKURI_OR_KAMASHI:'主導権候補が捲り・かましで前へ出る想定',CHALLENGER_MAKURI:'別の先頭候補が捲る想定',FRONT_LINE_CONTINUITY_UNVERIFIED:'前の隊列が続くかは未確認',FOLLOWER_SASHI_SCENARIO:'番手から差す展開を想定',FOURTH_CORNER_ORDER_CONTINUES:'4コーナーの順序が続く想定',LATE_SPRINT_OVERTAKE:'終盤の加速で前を交わす想定',FRONT_LEADER_PACE_FADE:'前の選手が失速する想定'};
    const actionText=value=>actions[value]||(/^LEADER_CAR_[1-9]$/.test(value)?'主導権候補は'+value.at(-1)+'番':/^CAR_[1-9]$/.test(value)?'対象は'+value.at(-1)+'番':'保存された動きの仮定');
    const phases=['初周','打鐘','最終ホーム','最終バック','4コーナー','ゴール'];
    const scenarios=saved.scenarios.map((s,i)=>'<article class="kn-frozen-scenario"><h5>見立て '+(i+1)+' · '+esc(s.projected_3ren_tan.join('−'))+'</h5><p>候補内の重み '+(s.relative_research_weight*100).toFixed(1)+'%</p><ol>'+s.six_phases.map((p,j)=>'<li><b>'+phases[j]+'</b> '+esc(p.projected_order.join(' → '))+'<br>'+esc(p.hypothesis_actions.map(actionText).join(' / '))+'</li>').join('')+'</ol></article>').join('');
    const trend={IMPROVING:'上向き',DECLINING:'下向き',NO_CLEAR_CHANGE:'目立つ変化なし',INSUFFICIENT_DATA:'比較材料が不足'};
    const change=v=>v===null?'未比較':(v>0?'+':'')+v;
    const adjustments=saved.assessments.length?'<p>直近成績と落車前後の成績差に基づく、保存時点の補正です。落車の記録だけで状態を決めつけていません。</p><div class="kn-table-scroll"><table><thead><tr><th>車</th><th>近況</th><th>直近の差</th><th>落車前後の差</th><th>補正値</th></tr></thead><tbody>'+saved.assessments.map(a=>'<tr><td>'+a.car+'</td><td>'+trend[a.trend]+'</td><td>'+change(a.recent_result_change)+'</td><td>'+change(a.post_fall_change)+'</td><td>'+change(a.score_adjustment)+'</td></tr>').join('')+'</tbody></table></div>'+saved.assessments.map(a=>'<p>'+a.car+'番：'+(a.fall_on_record?'落車の保存記録あり':'落車の保存記録なし')+' · 欠場期間 '+(a.documented_absence_days===null?'未確認':a.documented_absence_days+'日')+' · 復帰後 '+(a.return_after_absence_results===null?'未確認':a.return_after_absence_results+'走')+' · コメント記録 '+(a.comments_count??'未確認')+'件</p>').join('')+'<p class="kn-small">数値は保存された比較用の値です。体調の診断や的中率を表すものではありません。</p>':'';
    const title=saved.adjusted?(saved.role==='B'?'展開の見立て・近況の補正':'近況の補正・根拠'):(saved.role==='B'?'展開の見立て・根拠':'予想の根拠');
    return '<details class="kn-details kn-frozen-basis"><summary>'+title+'</summary><p>'+(saved.role==='A'?'保存時の印順位と選手の数値をもとに候補順を付けています。Aの原本には局面別の見立てはありません。':'保存された6局面の見立てです。各局面の順序は予想上の仮定です。')+'</p>'+factsTable+adjustments+(scenarios?'<p class="kn-small">分岐の重みは候補内の比重です。的中確率ではありません。</p>'+scenarios:'')+'</details>';
  }
  function frozenTickets(saved){
    if(!saved)return '';
    return '<div class="kn-badges">'+confidenceBadge(saved)+'</div>'+confidenceEvidence(saved)+'<p class="kn-frozen-clock">作成 '+stamp(saved.generatedAt)+'<br>締切前の保存 '+stamp(saved.sealedAt)+'</p><p>全部の買い目</p><ol class="kn-frozen-tickets" data-frozen-arm="'+saved.name+'">'+saved.tickets.map(t=>'<li data-frozen-combo="'+t.combo+'">'+t.combo.split('-').map(Number).map(car).join('<span>−</span>')+'</li>').join('')+'</ol>'+frozenBasis(saved);
  }
  function resultLabel(state){
    if(state==='SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL')return '二つの掲載元が一致（公式認証なし）';
    if(state==='HOLD_SECONDARY_RESULT_DISAGREEMENT')return '出典間の相違で保留';
    if(state?.startsWith('PENDING_'))return '結果の掲載・確定待ち';
    const holds={HOLD_NO_PUBLISHED_CUTOFF_HINT:'掲載締切を確認できないため保留',HOLD_PROVIDER_DENIED_OR_RATE_LIMITED_STOP:'入力元の取得拒否で保留',HOLD_RESULT_SOURCE_UNAVAILABLE:'結果の取得を保留',HOLD_RESULT_SOURCE_UNVERIFIED:'結果の根拠を確認できないため保留',HOLD_RESULT_DAY_MISMATCH:'結果の日付照合を保留',HOLD_RESULT_RACE_MISMATCH:'結果のレース照合を保留',HOLD_SPECIAL_REFUND_OR_TIE_REQUIRES_OFFICIAL:'返還・中止・同着の公式確認待ち',HOLD_CONFLICTING_SOURCE_RESULT:'掲載内容の相違で保留'};
    return holds[state]||'結果の照合は未取得';
  }
  function comparisonHtml(row,model,version=null){
    const context=version?{...row,reference:version.reference,referenceEnvelope:version.envelope}:row;
    if(!C.predictionMatches(M.forecast(context,market,model),confidenceFilter))return '';
    const score=M.compare(row,market,model,version),status=score.status==='RESEARCH_HIT'?'的中':score.status==='RESEARCH_MISS'?'不的中':'未判定';
    const label=['A','B','C'].includes(model)?'参考'+model:M.forecast(row,market,model).label;
    const timing={GENERATED_AT_MISSING:'予想の生成時点は未確認',CUTOFF_UNVERIFIED:'掲載締切は未確認',GENERATED_AFTER_OR_AT_CUTOFF:'掲載締切以後に生成された保存版',RECORDED_PRE_CUTOFF_NOT_FORMAL:'記載時点は掲載締切前（正式な保存時刻の認証なし）'};
    return '<div class="'+(['A','B','C'].includes(model)?'kn-reference-comparison':'kn-selected-comparison')+'" data-model="'+esc(model)+'"><p><b>'+esc(label)+' · '+score.ticketCount+'点 · '+status+'</b></p><p>各100円の想定：投資 '+money(score.stakeYen)+' · 払戻 '+money(score.payoutYen)+' · 差引 '+money(score.netYen)+'</p><p class="kn-small">予想の記載時点 '+stamp(score.generatedAt)+' · '+esc(timing[score.timingStatus])+'</p>'+(score.reason==='RESULT_HISTORY_INCOMPLETE'?'<p class="kn-warning">先行する結果の保存版が未読込のため、比較は保留しています。</p>':'')+'</div>';
  }
  function bindingHtml(value,label){
    return value?'<p class="kn-small">'+esc(label)+'のファイルSHA256 '+esc(value.fileSha256)+'<br>暗号文SHA256 '+esc(value.cipherSha||'暗号文経由の読込ではありません')+'</p>':'';
  }
  function resultRevision(saved,n){
    const o=saved.observation;
    return '<section data-result-revision="'+n+'"><p><b>結果の保存版 '+n+' · '+esc(resultLabel(o.state))+'</b></p><p>取得 '+stamp(o.captured_at)+' · '+esc(o.winning_triple?.join('−')||'結果保留')+' · 各100円の3連単払戻 '+money(o.payout_per_100yen)+'</p>'+o.provider_receipts.map(r=>'<p>'+sourceLink(r.source_url,r.provider+'の結果')+' · 出典取得 '+stamp(r.observed_at)+'</p>').join('')+bindingHtml(saved.binding,'結果原本')+'</section>';
  }
  function researchResult(row){
    if(!row.latestResearchResult&&!Object.keys(row.reference||{}).length)return '';
    const latest=row.latestResearchResult?.observation,history=row.researchResultHistory||[],versions=row.referenceHistory||[];
    return '<section class="kn-result kn-research-result kn-details" data-result-state="'+esc(latest?.state||'UNOBSERVED')+'"><b>参考A/Bと保存結果の照合</b><p>'+esc(resultLabel(latest?.state))+' · '+esc(latest?.winning_triple?.join('−')||'結果未確認')+'</p>'+(!['A','B','C'].includes(variant)?comparisonHtml(row,variant):'')+comparisonHtml(row,'A')+comparisonHtml(row,'B')+'<p class="kn-small">条件付きの研究比較です。点数は各保存版の全買い目を使用し、1点100円で計算します。実購入・正式PR71成績・学習効果の証明ではありません。2車単の払戻は独立した根拠がないため未確認です。</p><details class="kn-details"><summary>結果の改訂履歴・出典</summary>'+(history.length?history.map((saved,n)=>resultRevision(saved,n+1)).join(''):'<p>結果の保存履歴はありません。</p>')+'</details><details class="kn-details"><summary>参考予想の保存版・原本の照合</summary>'+[...versions,{reference:row.reference,envelope:row.referenceEnvelope,binding:row.bindings?.reference}].map((version,n)=>'<section><p><b>参考予想の保存版 '+(n+1)+(n===versions.length?'（現在）':'')+'</b></p>'+comparisonHtml(row,'A',version)+comparisonHtml(row,'B',version)+bindingHtml(version.binding,'参考予想原本')+'</section>').join('')+'</details></section>';
  }
  function renderResearchSummary(list){
    const panel=$('kn-research-summary'),only=$('kn-result-only');
    if(!data||period!=='day'||!M.day(currentDay)||!data.dates.includes(currentDay)){panel.hidden=true;panel.textContent='';only.innerHTML='';return;}
    const results=[...(data.results||new Map())].filter(([id])=>id.startsWith(currentDay.replaceAll('-',''))),known=new Set(list.map(row=>row.id)),unpaired=results.filter(([id])=>!known.has(id));
    if(data.nationwide?.has(currentDay)&&!results.length&&list.every(row=>row.nationwideOnly)){panel.hidden=true;panel.textContent='';only.innerHTML='';return;}
    const summary=M.summarize(list,market),arm=name=>{const v=summary[name];return '参考'+name+'：的中 '+v.hitRaces+' / 判定 '+v.evaluableRaces+'レース · 未判定 '+v.unknownRaces+'件 · 保存点数 '+(v.ticketCounts.length?v.ticketCounts.join('・'):'未確認')+'点';};
    panel.hidden=false;panel.innerHTML='<b>保存結果と参考予想の研究比較</b><p>保存結果 '+results.length+'件 · 予想未読込 '+unpaired.length+'件</p><p>同じレースでA/Bを比較できる数 '+summary.pairedRaceCount+' / '+summary.raceCount+' · その共通レースの的中 A '+summary.paired.A.hitRaces+' / '+summary.pairedRaceCount+'、B '+summary.paired.B.hitRaces+' / '+summary.pairedRaceCount+'</p><p>'+esc(arm('A'))+'</p><p>'+esc(arm('B'))+'</p><p class="kn-small">表示中の日付の全保存レースが分母です。未判定は外れに含めません。A/Bの差から学習による改善は判断できません。</p>';
    only.innerHTML=unpaired.map(([id,history])=>'<details class="kn-details"><summary>'+esc(id)+' · '+esc(resultLabel(history.at(-1)?.observation.state))+'</summary><p>このレースの予想原本は未読込のため、的中比較の分母へ加えません。</p>'+history.map((saved,n)=>resultRevision(saved,n+1)).join('')+'</details>').join('');
  }
  function liveResult(row){
    const result=row.resultUpdate,frozen=row.frozenForecast,national=row.nationwideStatus;if(!result&&!frozen&&!national)return '';
    const official=result?.authority==='official',confirmed=result?.order_status==='confirmed',paid=official&&result?.payout_status==='confirmed';
    const order=result?.order_status==='conflict'?'出典間の相違を確認中':confirmed?result.winning_triples.join(' / '):'着順を確認中';
    const status={hit:'的中',miss:'不的中',pending:'未照合',void:'返還・採点対象外',unverifiable:'原本の確認待ち'};
    const arms=[['A','A'],['B','B'],['adjusted_A','補正A'],['adjusted_B','補正B'],['C','C']].map(([name,label])=>{
      const arm=result?.arms[name],saved=M.frozenArm(row,name),aligned=!saved||arm?.points==null||arm.points===saved.tickets.length;
      if(confidenceFilter!=='all'&&((!row.nationwideOnly&&(market!=='3t'||variant==='rollover'))||!C.predictionMatches(saved,confidenceFilter)))return '';
      const state=aligned?(arm?.state||'pending'):'unverifiable',missing=national&&!saved&&!arm?.points;
      const referencePending=!saved&&national?.original_identity&&(['A','B'].includes(name)||name.startsWith('adjusted_')&&national.original_identity.conditioned);
      const outcome=(frozen||national)&&name==='C'?'未作成':referencePending?'保存原本の読込待ち':missing?(name.startsWith('adjusted_')?'補正の保存待ち':'未作成'):!result?'結果待ち':status[state]||'未照合';
      return '<div class="kn-result-arm" data-result-arm="'+name+'"><h4>'+(frozen||national?label:'締切前保存'+label)+'</h4><p>採点結果：<strong>'+esc(outcome)+'</strong></p><p>'+(saved?'点数 '+saved.tickets.length+'点':arm?.points!=null?arm.points+'点':(frozen||national)&&name==='C'?'Cの予想は未作成です。':'点数未確認')+'</p>'+(missing&&name.startsWith('adjusted_')?'<p class="kn-small">'+conditionLabel(national.condition_state)+'</p>':'')+(paid&&aligned&&arm?.stake_yen!=null&&arm?.return_yen!=null?'<p>各100円の想定：投資 '+money(arm.stake_yen)+' / 払戻 '+money(arm.return_yen)+'</p>':'')+(!aligned?'<p class="kn-warning">保存原本と採点側の点数が一致していないため、採点結果の表示を保留しています。</p>':'')+frozenTickets(saved)+'</div>';
    }).join('');
    if(confidenceFilter!=='all'&&!arms)return '';
    const sourceNames={keirin_jp:'KEIRIN.JP',kdreams:'Kドリームス',netkeirin:'netkeirin',official_pdf:'公式PDF',official_json:'公式データ'};
    const comparisonNames={matched:'一致',different:'相違あり',unavailable:'取得待ち',unverified:'未確認'};
    const comparisons=(result?.source_comparison||[]).map(s=>sourceNames[s.source_id]+'：'+comparisonNames[s.state]).join(' / ');
    const payout=paid?Object.entries(result.payouts_100yen).map(([combo,yen])=>esc(combo)+' '+money(yen)).join(' / '):(result?.payout_status==='held'?'配当の確認を保留中':'配当確認中');
    const purposes={OFFICIAL_CALENDAR:'開催日程',CALENDAR_SCRIPT:'開催日程の画面処理',FORM_SCRIPT:'画面の遷移処理',OFFICIAL_RACE_LIST:'レース一覧',RACE_LIST_VIEW_SCRIPT:'レース一覧の表示処理',RACE_LIST_CONTROLLER_SCRIPT:'レース一覧の遷移処理',OFFICIAL_FINAL_RESULT:'公式の着順・配当',OFFICIAL_PAYOUT_UNIT:'配当単位の説明',OFFICIAL_JSON_CALENDAR:'開催日程',OFFICIAL_JSON_DAY_LIST:'開催別のレース一覧',OFFICIAL_JSON_RESULT_SUMMARY:'結果一覧',OFFICIAL_JSON_HEADER:'レース情報',OFFICIAL_JSON_DETAIL:'公式の着順・配当'};
    const stages={REQUEST:'通信',HTTP_RESPONSE:'応答確認',CONTENT_CHECK:'ページ内容の確認',PARSE_RESULT:'結果の読取',VERIFY_UNIT:'配当単位の確認',PERSIST_STOP:'取得停止の保存'};
    const diagnostics=result?.diagnostics.length?'<details class="kn-details"><summary>取得先と確認状況</summary>'+result.diagnostics.map(d=>'<p class="kn-small"><b>'+purposes[d.purpose]+'</b> · '+esc(d.method)+' '+esc(d.source_host+d.source_path)+'<br>HTTP '+(d.http_status===null?'応答なし':d.http_status)+' · '+stages[d.stage]+' · '+esc(d.reason)+'<br>'+stamp(d.observed_at)+'</p>').join('')+'</details>':'';
    return '<section class="kn-result kn-live-result"><h3>'+(frozen?'締切前に保存した予想':official?'公式結果':national&&!result?'予想の保存状況':'参考結果・公式確認待ち')+'</h3>'+(frozen?'<p class="kn-small">入力の保存時点 '+stamp(frozen.baseline.source_as_of)+' · 締切 '+stamp(frozen.baseline.published_cutoff_at)+'</p>':'')+'<p class="kn-result-order">'+(result?(official?'公式結果：':'参考結果・公式確認待ち：'):'')+esc(order)+'</p><p>'+payout+(paid?'（100円あたり）':'')+'</p><div class="kn-result-arms'+(frozen?' kn-has-originals':'')+'">'+arms+'</div><p class="kn-small">'+(frozen?'締切前に保存された各原本の照合です。':'')+(result?'結果確認 '+stamp(result.observed_at):'結果の保存を待っています。')+'</p>'+(comparisons?'<p class="kn-small kn-result-comparison">保存資料との照合：'+esc(comparisons)+'</p>':'')+diagnostics+'</section>';
  }
  function scenarios(values){
    if(!Array.isArray(values)||!values.length)return '';
    const names=['初周','打鐘','最終ホーム','最終バック','4コーナー','ゴール'];
    return '<details class="kn-details"><summary>展開と根拠・6局面を読む</summary>'+values.slice(0,64).map((s,i)=>{
      if(!s||typeof s!=='object')return '';
      const phases=s.six_phases||s.phases||s.phase_orders||[];
      const list=Array.isArray(phases)?phases:Object.entries(phases).map(([phase,order])=>({phase,order}));
      return '<section class="kn-scenario"><h4>'+esc(s.label||s.scenario_id||s.id||'展開 '+(i+1))+'</h4><p>'+esc(s.condition||'条件付きの展開仮説')+'</p><ol>'+list.map((p,n)=>{const order=p?.projected_order||p?.order||p?.ordering;const actions=p?.hypothesis_actions;return '<li><b>'+esc(typeof p==='object'?p?.label||p?.phase||names[n]||'局面':names[n]||'局面')+'</b><span>'+esc(typeof p==='string'?p:p?.description||p?.event||(Array.isArray(order)?order.map(v=>Array.isArray(v)?v.join('−'):v).join(' → '):'')||'記述未取得')+'</span>'+(actions?'<p>'+esc(Array.isArray(actions)?actions.join(' / '):actions)+'</p>':'')+'</li>';}).join('')+'</ol><p class="kn-small">'+esc(Array.isArray(s.evidence)?s.evidence.join(' / '):s.evidence||'')+'</p></section>';
    }).join('')+'</details>';
  }
  function roster(row){
    return '<details class="kn-details"><summary>選手の数字・コメント・近況</summary><div class="kn-table-scroll"><table><thead><tr><th>車</th><th>選手</th><th>得点</th><th>S/H/B</th><th>逃/捲/差/マ</th><th>勝率</th><th>3連対</th></tr></thead><tbody>'+row.riders.map(p=>'<tr><td>'+car(p.number)+'</td><td>'+riderButton(row,p)+'</td><td>'+num(p.score)+'</td><td>'+[p.S,p.H,p.B].map(v=>num(v)).join('/')+'</td><td>'+[p.nige??p.escape,p.makuri,p.sashi,p.mark].map(v=>num(v)).join('/')+'</td><td>'+num(p.win_rate??p.win,'%')+'</td><td>'+num(p.top3_rate,'%')+'</td></tr>').join('')+'</tbody></table></div>'+row.riders.map(p=>'<p class="kn-rider-note"><b>'+p.number+' '+esc(p.name)+'</b><span>コメント：'+esc(p.comment||'未取得')+'</span><span>近況：'+esc((Array.isArray(p.recent_meets)?p.recent_meets:Array.isArray(p.recent_meetings)?p.recent_meetings:Object.values(p.recent_meetings||{})).filter(Boolean).join(' / ')||'未取得')+'</span></p>'+fieldProvenance(p)).join('')+'<p class="kn-small">主表示の統計は掲載元の値を保持します。参考A/Bのnetkeirin統計と平均しません。H/Bは過去の先頭回数で、今日の隊列ではありません。</p></details>';
  }
  function riderButton(row,rider){return '<button type="button" class="kn-rider-open" data-rider-open="'+esc(row.id)+'" data-rider-car="'+rider.number+'" aria-haspopup="dialog">'+car(rider.number)+'<span>'+esc(rider.name)+'</span></button>';}
  function riderButtons(row){return row.riders.length?'<ul class="kn-rider-list" aria-label="出走選手">'+row.riders.map(rider=>'<li>'+riderButton(row,rider)+'</li>').join('')+'</ul>':'';}
  function riderRow(id){return M.historyRows(data,{period:'all'}).find(row=>row.id===id);}
  function clearRiderContents(){for(const id of ['kn-rider-heading','kn-rider-venue'])$(id).textContent='';$('kn-rider-select').innerHTML='';$('kn-rider-facts').innerHTML='';}
  function closeRiderDetails(restore=true){
    const modal=$('kn-rider-details');if(!modal)return;
    if(!restore){riderDetails=null;clearRiderContents();}
    if(modal.open)modal.close();
  }
  function restoreRiderFocus(){
    const saved=riderDetails;riderDetails=null;clearRiderContents();if(!saved)return;
    const opener=saved.opener.isConnected?saved.opener:root.querySelector('[data-rider-open="'+saved.raceId+'"][data-rider-car="'+saved.openerCar+'"]');
    (opener||$('kn-races')).focus({preventScroll:true});
  }
  function jointRiderForecast(row,number){
    const forecast=row.jointForecast,binding=row.jointForecastBindings,J=window.RaceKeirinJointForecast;
    if(!forecast)return {admitted:false,html:'<p class="kn-rider-probability-state" data-joint-state="unavailable">比較Bの着順確率は未取得です。</p>'};
    try{
      const cars=row.riders.map(rider=>rider.number);
      if(!J||forecast.schema!=='RACE_AI_KEIRIN_JOINT_PROJECTION_V1'||!binding||binding.race_id!==row.id||!Array.isArray(binding.cars)||binding.cars.length!==cars.length||!cars.every(car=>binding.cars.includes(car))||row.cutoff&&!sameRiderClock(row.cutoff,binding.cutoff_at))throw Error();
      if(!Array.isArray(forecast.riders)||!forecast.riders.every(p=>row.riders.some(person=>person.number===p.car&&person.name.replace(/\s/g,'')===p.name.replace(/\s/g,''))))throw Error();
      const known=value=>typeof value==='string'&&/^[0-9]{6}$/.test(value);
      if(forecast.riders.some(p=>row.riders.some(person=>person.number===p.car&&known(person.registration)&&known(p.registration)&&person.registration!==p.registration)))throw Error();
      J.validateForecast(forecast,binding);
      return {admitted:true,html:J.renderForecast(forecast,number)};
    }catch{return {admitted:false,html:'<p class="kn-rider-probability-state" data-joint-state="held">比較Bの着順確率は出典・対象選手・予想時点を照合できないため、表示を保留しています。</p>'};}
  }
  function sameRiderClock(left,right){
    const identity=value=>{const parsed=Date.parse(value),fraction=typeof value==='string'?/\.(\d{1,6})(?:Z|[+-]\d\d:\d\d)$/.exec(value)?.[1]||'':'';return Number.isFinite(parsed)?parsed+':'+fraction.padEnd(6,'0').slice(3):null;};
    const expected=identity(left);return expected!==null&&expected===identity(right);
  }
  function riderRole(row,number){
    if(row.raw.line_type==='individual_positions'||row.frozenForecast?.facts.competition==='GIRLS')return '個人戦の位置取り参考';
    const line=row.lines.find(group=>Array.isArray(group)&&group.some(value=>value===number||value?.contest?.includes(number)));
    if(!line)return '掲載の並び未取得';
    const position=line.indexOf(number);if(position<0)return '競り（掲載の並び）';
    return line.length===1?'単騎':['先頭','番手'][position]||String(position+1)+'番手';
  }
  function comparisonRiderFacts(row,rider){
    const fresh=Array.isArray(row.comparisonRiders)&&row.comparisonRiders.find(person=>person.car===rider.number&&typeof person.name==='string'&&person.name.replace(/\s/g,'')===rider.name.replace(/\s/g,''));
    if(!fresh)return '';
    const styles={NIGE:'逃げ',MAKURI:'捲り',SASHI:'差し',MARK:'追込',ALLROUND:'自在',UNKNOWN:'未取得'};
    const rate=value=>typeof value==='number'&&Number.isFinite(value)&&value>=0&&value<=100?num(Number(value.toFixed(2)),'%'):'未取得';
    const win=fresh.win_rate??(typeof fresh.recent_form_score==='number'&&fresh.recent_form_score>=0&&fresh.recent_form_score<=1?fresh.recent_form_score*100:null);
    const values=[['級班',esc(fresh.class??fresh.racer_class??fresh.rider_class??'未取得')],['脚質',esc(styles[fresh.style]||fresh.style||'未取得')],
      ['競走得点',num(fresh.competition_points)],['4か月勝率',rate(win)],['4か月2連対率',rate(fresh.top2_rate)],['4か月3連対率',rate(fresh.top3_rate)],
      ['H',num(fresh.h_count)],['B',num(fresh.b_count)]];
    const asOf=row.jointForecastBindings.source_as_of;
    return '<section class="kn-comparison-input"><h3>比較Bの入力資料</h3><p class="kn-small">資料の基準 <time datetime="'+esc(asOf)+'">'+stamp(asOf)+'</time>。今回の比較Bに使用した掲載値です。</p><dl class="kn-rider-stats">'+values.map(([label,value])=>'<div><dt>'+label+'</dt><dd>'+value+'</dd></div>').join('')+'</dl></section>';
  }
  function renderRiderDetails(number){
    const row=riderDetails&&riderRow(riderDetails.raceId),rider=row?.riders.find(person=>person.number===number);
    if(!rider){closeRiderDetails(false);return;}
    riderDetails.number=number;
    $('kn-rider-venue').textContent=row.date+' '+row.venue+' '+row.number+'R';
    $('kn-rider-heading').textContent=number+'番 '+rider.name;
    $('kn-rider-select').innerHTML=row.riders.map(person=>'<option value="'+person.number+'">'+person.number+'番 '+esc(person.name)+'</option>').join('');
    $('kn-rider-select').value=String(number);
    const stats=[['競走得点',num(rider.score)],['脚質',esc(rider.style||'未取得')],['掲載の並びでの役割',esc(riderRole(row,number))],
      ['勝率（掲載値）',num(rider.win_rate??rider.win,'%')],['2連対率（掲載値）',num(rider.top2_rate,'%')],['3連対率（掲載値）',num(rider.top3_rate,'%')],
      ['S',num(rider.S)],['H',num(rider.H)],['B',num(rider.B)]];
    const recent=Array.isArray(rider.recent_meets)?rider.recent_meets:Array.isArray(rider.recent_meetings)?rider.recent_meetings:Object.values(rider.recent_meetings||{});
    const forecast=jointRiderForecast(row,number);
    const history=window.RaceKeirinRiderHistory?.render(row,number)||'<p class="kn-small">長期・直近の着順履歴は未取得です。</p>';
    $('kn-rider-facts').innerHTML=forecast.html+(forecast.admitted?comparisonRiderFacts(row,rider):'')+'<h3>保存した出走表の掲載値</h3><dl class="kn-rider-stats kn-rider-source-stats">'+stats.map(([label,value])=>'<div><dt>'+label+'</dt><dd>'+value+'</dd></div>').join('')+'</dl>'+history+
      '<p class="kn-small">成績の集計期間：'+esc(row.raw.source_data_period||'掲載資料の期間未確認')+'。掲載率と今回の予測確率は別の値です。</p>'+
      '<details class="kn-details"><summary>コメント・近況・出典</summary><p>コメント：'+esc(rider.comment||'未取得')+'</p><p>近況：'+esc(recent.filter(value=>typeof value==='string'&&value).join(' / ')||'未取得')+'</p>'+fieldProvenance(rider)+
      '<p class="kn-small">出走表の取得 '+stamp(row.raw.source_as_of||row.raw.fetched_at)+'<br>'+sourceLink(row.sourceUrl,'掲載した出走表')+'</p></details>'+
      '<details class="kn-details"><summary>戦術・能力の資料</summary><dl class="kn-rider-stats">'+riderAbilities.map(label=>'<div data-rider-ability><dt>'+label+'</dt><dd>観測資料未取得</dd></div>').join('')+'</dl><p class="kn-small">確認できた観測機会・期間・出典がそろうまで、能力値や成功率は表示しません。</p></details>';
  }
  function openRiderDetails(opener){
    const row=riderRow(opener.dataset.riderOpen),number=Number(opener.dataset.riderCar);
    if(!row?.riders.some(rider=>rider.number===number))return;
    riderDetails={raceId:row.id,number,openerCar:number,opener};
    renderRiderDetails(number);$('kn-rider-details').showModal();
  }
  function providerName(url){const host=new URL(url).hostname;return host==='keirin.netkeiba.com'?'netkeirin':host==='keirin.kdreams.jp'?'Kドリームス':host;}
  function referenceProvenance(row){const pages=row.referenceEnvelope?.input?.source_pages;if(!Array.isArray(pages))return '';const seen=new Set(),links=pages.flatMap(page=>{const url=M.safeUrl(page?.url);if(!url||seen.has(url))return [];seen.add(url);return [sourceLink(url,'参考A/Bの入力・'+providerName(url))];});return links.length?'<p class="kn-small kn-reference-provenance">'+links.join(' / ')+'</p>':'';}
  function fieldProvenance(person){const fields=person.field_sources;if(!fields||typeof fields!=='object'||Array.isArray(fields))return '';const labels={statistics:'得点・率・成績',H:'H',B:'B',comment:'コメント',recent_meetings:'近況',venue_5yr:'当場の成績',same_distance_year:'同じ周長の成績'};const links=Object.entries(fields).flatMap(([field,value])=>{const url=M.safeUrl(typeof value==='string'?value:value?.url);return url?[sourceLink(url,(labels[field]||field)+'：'+providerName(url))]:[];});return links.length?'<p class="kn-small kn-field-provenance">'+esc(person.number)+'番の項目別出典：'+links.join(' / ')+'</p>':'';}
  function selectionSummary(){const list=all().filter(r=>selected.has(r.id));const total=list.reduce((n,r)=>{const f=M.forecast(r,market,variant),p=pref(r);return n+M.allocate(f,p.budget,p.excluded).total;},0);$('kn-selection-count').textContent='検討リスト '+list.length+'件 · '+money(total);$('kn-copy-selection').disabled=!list.length;}
  function copyRace(row){const f=M.forecast(row,market,variant),p=pref(row),a=M.allocate(f,p.budget,p.excluded);if(f.allocatable&&!a.available)return '';return row.date+' '+row.venue+' '+row.number+'R / '+f.label+' / 掲載締切 '+time(row.cutoff)+'\n'+f.tickets.filter((t,i)=>!f.allocatable||a.amounts[i]>0).map(t=>{const i=f.tickets.indexOf(t);return t.combo+(f.allocatable?' '+money(a.amounts[i]):'');}).join('\n')+'\n'+(f.allocatable?'候補配分 '+money(a.total)+' · 未購入':'参考計算・比較用');}
  async function copy(value){if(!value)return;try{await navigator.clipboard.writeText(value);note('買い目候補をコピーしました。');}catch{const area=document.createElement('textarea');area.value=value;root.append(area);area.select();const ok=document.execCommand('copy');area.remove();note(ok?'買い目候補をコピーしました。':'このブラウザーではコピーできませんでした。',!ok);}}
  function click(button){
    if(!button)return;
    if(button.dataset.riderOpen){openRiderDetails(button);return;}
    if(Object.hasOwn(button.dataset,'riderClose')){closeRiderDetails();return;}
    if(button.id==='kn-page-next'||button.id==='kn-page-prev'){
      pageNumber+=button.id==='kn-page-next'?1:-1;renderCards();$('kn-races').focus({preventScroll:true});$('kn-races').scrollIntoView({block:'start'});return;
    }
    if(button.dataset.history){
      const latest=data?.dates.at(-1)||'';
      if(button.dataset.history==='all'){period='all';$('kn-history-filters').open=true;}
      else if(button.dataset.history==='week'){period='range';rangeTo=latest;rangeFrom=sevenDaysBefore(latest);}
      else {period='day';currentDay=latest;}
      pageNumber=1;pastSearch();render();if(button.dataset.history==='all')$('kn-search').focus();return;
    }
    if(button.dataset.prediction){variant=button.dataset.prediction;$('kn-variant').value=variant;pageNumber=1;renderCards();return;}
    if(button.dataset.confidenceFilter){confidenceFilter=button.dataset.confidenceFilter;$('kn-confidence').value=confidenceFilter;pageNumber=1;renderCards();return;}
    if(button.dataset.day){currentDay=button.dataset.day;period='day';venue='';pageNumber=1;pastSearch();render();return;}
    if(Object.hasOwn(button.dataset,'venue')){venue=button.dataset.venue;pageNumber=1;render();return;}
    if(button.dataset.expand){const key=button.dataset.expand+':'+market+':'+variant;expanded.has(key)?expanded.delete(key):expanded.add(key);renderCards();return;}
    if(button.dataset.select){const id=button.dataset.select;selected.has(id)?selected.delete(id):selected.add(id);renderCards();return;}
    if(button.dataset.copy){const row=all().find(r=>r.id===button.dataset.copy);if(row)copy(copyRace(row));}
  }
  function renderRollover(){
    try{const value=id=>$(id).value===''?null:Number($(id).value);const p=window.KeirinRollover.plan({initialBudget:Number($('kn-roll-budget').value),firstReturn:value('kn-return-one'),secondReturn:value('kn-return-two')});$('kn-roll-result').innerHTML='<p>初回 '+money(p.firstStake)+' · 次の候補 '+money(p.nextStake)+' · 留保 '+money(p.reserve)+'</p><p>'+esc(p.reason||'最終の試算：'+money(p.net))+'</p>';}catch{$('kn-roll-result').textContent='受取額は0〜100,000,000円の整数で入力してください。';}
  }
  async function bounded(response){const limit=90*1024*1024,length=response.headers.get('content-length');if(length!==null&&(!/^\d+$/.test(length)||Number(length)>limit))throw Error();const reader=response.body?.getReader();if(!reader)throw Error();const parts=[];let total=0;try{for(;;){const {value,done}=await reader.read();if(done)break;total+=value.byteLength;if(total>limit)throw Error();parts.push(value);}}catch{await reader.cancel().catch(()=>{});throw Error();}const bytes=new Uint8Array(total);let offset=0;for(const p of parts){bytes.set(p,offset);offset+=p.length;}return bytes;}
  async function fromFragment(){
    const match=/^#note=([a-f0-9]{64})\.([A-Za-z0-9_-]{43})$/.exec(fragment);
    const feed=/^#notefeed=([A-Za-z0-9_-]{150,400})$/.exec(fragment);
    if(!match&&!feed)return;
    const version=beginLoad();
    dialog.showModal();note('本人用の保存データを開いています。');
    if(feed&&typeof window.RaceKeirinNoteFeed?.createSession==='function'){
      try{
        const session=await window.RaceKeirinNoteFeed.createSession(feed[1]);
        if(version!==loadVersion){session.close();return;}
        let first=true;
        feedWatcher=window.RaceKeirinNoteFeed.watchSession(session,{
          isActive:()=>dialog.open&&document.visibilityState!=='hidden',
          onUpdate:async value=>{if(version!==loadVersion)return;if(first){first=false;await accept(value,version);}else refreshDisplay(value,version);},
          onError:()=>{if(version===loadVersion)note(data?'更新を確認できませんでした。前回確認できた表示を保持しています。':'本人用リンクのデータを開けませんでした。保存データまたはリンクを確認してください。',true);}
        });
        await feedWatcher.check();
      }catch{if(version===loadVersion)note('本人用リンクのデータを開けませんでした。保存データまたはリンクを確認してください。',true);}
      return;
    }
    const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),feed?120000:20000);
    activeLoadAbort=abort;
    try{let value;if(feed){if(typeof window.RaceKeirinNoteFeed?.open!=='function')throw Error();value=await window.RaceKeirinNoteFeed.open(feed[1],{signal:abort.signal,onStatus:()=>{if(version===loadVersion)note('保存された最新データを確認しています。');}});}else{const response=await fetch(new URL('./views/'+match[1]+'.json',document.baseURI),{cache:'no-store',credentials:'omit',referrerPolicy:'no-referrer',signal:abort.signal});if(!response.ok)throw Error();value=await M.openCipher(await bounded(response),{cipherSha:match[1],key:match[2]});}await accept(value,version);}
    catch{if(version===loadVersion)note('本人用リンクのデータを開けませんでした。保存データまたはリンクを確認してください。',true);}finally{clearTimeout(timer);if(activeLoadAbort===abort)activeLoadAbort=null;}
  }
  build();launcher.addEventListener('click',()=>{dialog.showModal();feedWatcher?.check();});
  document.addEventListener('visibilitychange',()=>feedWatcher?.check());
  window.addEventListener('pageshow',()=>feedWatcher?.check());
  root.addEventListener('focusout',()=>queueMicrotask(()=>{if(pendingFeed)refreshDisplay(pendingFeed.value,pendingFeed.version);}));
  fromFragment();
})();
