"use strict";
/* PR #62 page shell, saved originals and server-managed automatic generation. */
(() => {
  const $ = id => document.getElementById(id);
  const U = globalThis.RaceUI, M = globalThis.RaceProductData, A = globalThis.RaceAuditModel, C = globalThis.RaceExistingModelCatalog, P = globalThis.RaceSavedPerformance;
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
  function liveBoatObservation(r) {
    const live = r.sport === "boat" ? r.live_boat_observation : null;
    if (!live || live.schema !== "RACE_AI_LIVE_BOAT_OBSERVATION_V1" || live.forecast_inputs_used !== false ||
        !["READY", "AWAITING_EXHIBITION", "SOURCE_WAIT", "SOURCE_ERROR"].includes(live.state) || !Number.isFinite(Date.parse(live.checked_at))) return null;
    if (live.context === null) return live.state === "READY" ? null : live;
    const context = live.context, page = context?.beforeinfo, people = knownParticipants(r);
    if (!validBoatObservationContext(context, r.race_id) || context.schema !== "RACE_AI_BOAT_SUPPLEMENTAL_CONTEXT_V1" ||
        context.race_id !== r.race_id || context.forecast_inputs_used !== false || page?.body_identity_verified !== true || page.status !== "PARSED" || page.roster_binding_status !== "VERIFIED" ||
        people.length !== 6 || page.participants.length !== 6 || !Array.isArray(context.roster) || context.roster.length !== 6) return null;
    for (const person of people) {
      const number = participantNumber(person), registration = participantRegistration(person);
      if (typeof registration !== "string" || !/^\d{4}$/.test(registration) ||
          context.roster.filter(p => p.lane === number && p.registration_number === registration).length !== 1 ||
          page.participants.filter(p => p.lane === number && p.registration_number === registration).length !== 1) return null;
    }
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
    else if (people.length === 6 && context && validBoatObservationContext(context, race.race_id) && context.beforeinfo?.status === "PARSED" && context.beforeinfo.roster_binding_status === "VERIFIED") {
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
  function chooseVenue(venue, toggle = false, fromHome = false) {
    state.venue = toggle && state.venue === venue ? "" : venue; state.visible = 60;
    refreshSelects(); renderAll(); showPage("races", true);
    // A direct venue shortcut should reveal the first actual race, especially
    // on 320px screens with a long navigation and venue-picker header.
    if (fromHome) $("all-races").querySelector(".race-card h3")?.scrollIntoView({block:"center"});
  }
  function venueButton(entry, home = false) {
    const action = button("", "venue-button" + (home ? " home-venue-button" : "") + (entry.venue === state.venue ? " active" : "") + (entry.favorite ? " favorite-venue" : ""), () => { if (home) state.raceView = state.day < A.jstToday() ? "results" : "upcoming"; chooseVenue(entry.venue, !home, home); });
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
  function outcomeBadge(r,p) {
    const status=P.compare(r,p).status;
    const phase=U.racePhase(r),displayStatus=status==="PENDING"&&phase!=="results"?(phase==="upcoming"?"UPCOMING":"TIME_UNKNOWN"):status;
    const labels={HIT:"的中",MISS:"不的中",PENDING:"結果待ち",UPCOMING:"レース前",TIME_UNKNOWN:"締切未確認",VOID:"中止・返還",REVIEW:"照合不可",NO_FORECAST:"未予想・原本未選択"};
    const note=(r.result?.cutoff_reference||r.result?.cutoff_reconciliation)&&status!=="VOID"?"（参考照合・締切差あり）":displayStatus==="UPCOMING"?"（締切 "+time(U.raceDeadline(r))+"）":displayStatus==="PENDING"?"（"+resultReason(r)+"）":"";
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
      return clocks+(reference.basis==="RAW_OFFICIAL_CANCELLATION_SELECTED_RACE"?"公式の中止表示を照合。中止ページの予定時刻変更を保持しています。":"公式結果と6選手を照合。原本は両方の締切前に保存済み。締切差を残した参考照合です。");
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
    const reason=r=>r.result?.cutoff_reference||r.result?.cutoff_reconciliation?"締切変更を照合済み（参考）":resultReason(r);
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
    $("result-coverage").textContent="対象 "+rows.length+"レース · レース前 "+phase.upcoming.length+" · 結果対象 "+phase.results.length+" · 締切未確認 "+phase.unknown.length+" · 結果取得 "+c.available+" · 中止・返還 "+c.void+" · 未予想・照合不可 "+(c.noForecast+c.review)+" · 最終同期 "+stamp(dataset?.results_synced_at)+" JST · 最終結果取得 "+stamp(latest)+" JST · 締切差の参考照合 "+references+" · 中止ページの時刻変更 "+cancelReferences+"。原本の時刻は変更せず、公式成績には加算しません。";
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
      const labels={NOT_APPLICABLE:"対象外",INPUT_MISSING:"入力未取得",TRAINED_ARTIFACT_MISSING:"学習物未取得",DEADLINE_PASSED:"締切超過・補完なし",RULE_FILTERED:"既存条件の対象外",UNCONNECTED_NATIVE_RUNTIME:"実行経路未接続",SOURCE_NOT_AUTHORIZED:"入力の利用条件未確認",INPUT_REJECTED:"入力不一致",EXECUTION_FAILED:"モデル実行エラー",GENERATED_UNATTESTED:"生成済み・外部保存未検証",ORIGINAL_REUSED:"元原本を再利用"};
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
    dataset = parsed;generation.ownsDisplay = true;generation.suppressed = false;generation.pausedForDrafts = false;generation.pausedForEditing = false;
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
      adoptDataset(parsed);showPage("races",true);
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
      dataset=parsed;state.day=day;state.predictionKeys=keys;
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
    function syncedMessage() {
      status.textContent=(savedHistory.active?"保存履歴は日付を選んで表示できます。":"")+"結果を自動同期中（60秒ごとに確認） · 最終同期 "+stamp(dataset.results_synced_at)+" JST。収集処理の停止中は前回の結果を表示します。";
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
    check();const timer=setInterval(()=>{if(version!==importVersion){clearInterval(timer);return;}check();},60000);
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
  $("clear-data").addEventListener("click", () => { ++importVersion;refreshSavedResults=null;resultCheck.busy=false;resultCheck.failed=false;generation.savedState = savedViewConfigured ? "CLEARED" : null;generation.ownsDisplay = false;generation.suppressed = true; dataset = null; state.selectedId = ""; state.predictionKeys = {}; state.modelOriginals = {}; state.modelBySport = {}; state.candidates = []; state.confirmed.clear(); $("purchase-ack").checked = false; refreshSelects(); renderAll(); $("file-message").textContent = "読み込んだ予想と候補をメモリから消去しました。手動購入記録は再読込まで保持します。"; });
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
