"use strict";
/* PR #62 page shell, saved originals and server-managed automatic generation. */
(() => {
  const $ = id => document.getElementById(id);
  const U = globalThis.RaceUI, M = globalThis.RaceProductData, A = globalThis.RaceAuditModel, C = globalThis.RaceExistingModelCatalog, P = globalThis.RaceSavedPerformance;
  const sports = {boat: "ボートレース", keirin: "競輪", autorace: "オートレース", horse: "競馬"};
  const icons = {boat: "◒", keirin: "♧", autorace: "♧", horse: "♞"};
  const pageNames = {
    home: ["YOUR RACE DASHBOARD", "今日のレースを、確かなデータで。", "保存済みの予想・結果と、あなたの買い目候補をひとつに。"],
    races: ["ALL RACES", "全レース一覧", "未予想も含めて、取得できたレースを確認。"],
    detail: ["RACE DETAIL", "レース詳細", "出走情報・保存済み予想・根拠を、取得時点ごとに。"],
    picks: ["TICKET ALLOCATION", "買い目配分", "予算に合わせて候補を編集。確定した候補も、実購入とは別の記録です。"],
    results: ["RESULTS & SIMULATION", "レース結果・収支", "保存予想の的中状況と、日予算を変えた場合の収支を確認。"],
    research: ["MODEL & EVIDENCE", "研究", "モデル・学習版・時点と、保存された根拠を比較。"],
    settings: ["PREFERENCES", "設定", "予算・表示と、読み込む情報源を管理。"]
  };
  const storageKey = "race-ai-display-v1";
  let preferences = {};
  try { preferences = JSON.parse(localStorage.getItem(storageKey) || "{}"); } catch { /* Storage is optional. */ }
  const validBudget = n => Number.isSafeInteger(n) && n >= 100 && n <= 10000000 && n % 100 === 0;
  const state = {
    page: "home", sport: Object.hasOwn(sports, preferences.sport) ? preferences.sport : "boat",
    day: A.jstToday(), allDates: false, period: "day", statusFilter: "all", followsToday: true, query: "", venue: "", sort: "time",
    forecastOnly: false, candidatesOnly: false, selectedId: "", detailTab: "outlook", predictionKeys: {},
    budget: validBudget(preferences.budget) ? preferences.budget : 10000,
    raceBudget: validBudget(preferences.raceBudget) ? preferences.raceBudget : 2000,
    simulationBudget: validBudget(preferences.simulationBudget) ? preferences.simulationBudget : 10000, resultGroupKey: "",
    simulationRaceBudget: [800,1000].includes(preferences.simulationRaceBudget) ? preferences.simulationRaceBudget : 800,
    maxPicks: [8, 16, 24, 32].includes(preferences.maxPicks) ? preferences.maxPicks : 8,
    candidates: [], purchases: [], confirmed: new Set(), visible: 60
  };
  let dataset = null, importVersion = 0;
  const generation = {api: null, ready: false, busy: false, nonce: null, capabilities: {}, day: null, message: "",
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
  const scopeName = scope => ({official: "公式対象・読込値", research: "研究 / 監査", synthetic: "合成テスト"})[scope] || "証拠未確認";
  const races = () => dataset?.records || [];
  const scoped = () => U.filterRaces(races(), {sport: state.sport, day: state.day, allDates: state.allDates, period: state.period, sort: state.sort});
  const currentRace = () => races().find(r => r.race_id === state.selectedId);
  const raceName = r => r ? (r.venue || "開催場 未取得") + " " + (Number.isInteger(r.race_no) ? r.race_no + "R" : "レース番号 未取得") + (r.venue == null || r.race_no == null ? " · " + r.race_id : "") : "レース未選択";
  const predictions = r => r ? (M.candidates ? M.candidates(r) : [r.prediction, ...(r.comparison_predictions || [])].filter(Boolean)) : [];
  const prediction = r => {
    const list = predictions(r), saved = state.predictionKeys[r?.race_id];
    return saved === undefined ? list[0] || null : list[saved] || null;
  };
  const modelName = p => {
    if(!p)return "未予想";
    const code=p.code_identity || M.codeIdentity?.(p), version=p.model_version ?? (code ? "保存コード "+code.slice(0,7) : "未取得");
    return text(p.model_id || p.model_version) + (p.model_id ? " / " + text(version) : "") + (p.variant ? " · " + ({HISTORY_BASELINE:"履歴なし",HISTORY_ADDED:"履歴あり"}[p.variant] || text(p.variant)) : "");
  };
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
    try { localStorage.setItem(storageKey, JSON.stringify({budget: state.budget, raceBudget: state.raceBudget, simulationBudget: state.simulationBudget, simulationRaceBudget: state.simulationRaceBudget, maxPicks: state.maxPicks, sport: state.sport})); } catch { /* App remains usable with storage disabled. */ }
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
  function boatObservationContext(r) {
    const context = r.sport === "boat" ? r.boat_observation_context : null;
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
      return facts([["取得状態", status], ["観測取得 JST", stamp(source.captured_at)], ["公式ページの締切 JST", stamp(page.source_cutoff_at)], ["締切と取得の関係", cutoffRelation], ["取得元URL", source.source_url], ["元ページSHA", source.sha256], ["公式公開日時 JST", stamp(source.published_at)], ["掲載時刻の原文", source.published_time_raw], ["鮮度の確認", "未確認（取得時刻と公式公開日時は別の記録）"]]);
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
    if (p.native_dispatch_prediction) return r.scope === "synthetic" ? "合成・取込予想" : "取込予想・保存証拠未確認";
    if (r.scope === "synthetic") return "合成・保存予想";
    if (M.eligiblePrediction?.(r, p)) return "証拠付き保存予想（読込値）";
    return "保存予想・証拠不足";
  }
  function participantCard(p, expanded = false) {
    const number = participantNumber(p), card = node("article", "racer-card"), avatar = node("div", "racer-avatar");
    if (Number.isInteger(number)) avatar.append(badge(number));
    avatar.append(node("span", "avatar-silhouette", "◉"));
    const registration = participantRegistration(p);
    card.append(avatar, node("strong", "racer-name", p.placeholder ? "出走者 未取得" : p.name ? text(p.name) : "名前 未取得"), node("small", "muted", p.placeholder ? "表示用の枠" : registration ? "登録 " + text(registration) : "登録 未取得"));
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
      people.forEach(p => box.append(participantCard(p, expanded)));
    } else if (r.sport === "boat") {
      box.classList.add("placeholder-entrants");
      for (let i = 1; i <= 6; i++) box.append(participantCard({number: i, placeholder: true}));
    } else return empty("出走メンバーは未取得です", "人数・個別成績は保存原本に含まれていません。");
    return box;
  }
  function ticketPreview(p, count = 4) {
    const list = node("div", "saved-tickets");
    if (!p) { list.append(node("p", "muted", "保存された買い目は未取得")); return list; }
    p.ordered_top8.slice(0, count).forEach((t, index) => list.append(append(node("span", "saved-ticket"), node("small", "ticket-rank", String(index + 1)), combo(t))));
    return list;
  }
  function raceCard(r, featured = false) {
    const p = prediction(r), card = node("article", "race-card" + (featured ? " featured" : ""));
    const head = node("div", "race-card-head"), title = node("div"), meta = node("div", "race-time");
    title.append(node("span", "sport-tag", icons[r.sport] + " " + sports[r.sport]), node("h3", "", raceName(r)));
    meta.append(node("span", "", r.event_date_jst || "日付 未取得"), node("strong", "", "締切 " + time(r.cutoff_at)));
    head.append(title, meta); card.append(head);
    const tags = node("div", "race-tags"); tags.append(node("span", "tag scope-" + r.scope, scopeName(r.scope)), node("span", "tag", forecastStatus(r, p)), node("span", "tag", stageName(p))); card.append(tags);
    tags.append(outcomeBadge(r,p));
    if (r.result?.status === "final") card.append(node("p","small","結果 " + resultCombination(r) + " · 100円払戻 " + payoutSummary(r.result)));
    if (r.missing_reasons?.includes("SAVED_FORECAST_CUTOFF_CONFLICT")) tags.append(node("span","tag","原本間で締切の記録差あり"));
    card.append(participantGrid(r));
    const foot = node("div", "race-card-footer"), saved = node("div", "card-prediction");
    saved.append(node("strong", "small", p ? p.native_top8_available === false ? "保存" + p.ordered_top8.length + "点プラン" : "保存Top8 · " + p.ordered_top8.length + "点" : "未予想"), node("p", "muted model-caption", modelName(p)), ticketPreview(p, featured ? 4 : 2));
    const open = button("レース詳細を見る →", "outline", () => openRace(r.race_id)); open.dataset.openRace = r.race_id;
    foot.append(saved, open); card.append(foot);
    if (featured) card.append(node("p", "muted small card-rationale", p?.rationale || r.no_forecast_reason || "予想根拠は未取得です。"));
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
    if (page === "picks") renderTickets();
    if (moveFocus) { $("page-title").tabIndex = -1; $("page-title").focus({preventScroll: true}); window.scrollTo({top: 0}); }
  }
  function setSport(sport) {
    state.sport = sport; state.venue = ""; state.visible = 60;
    if (state.page === "detail") showPage("races");
    persistPreferences(); refreshSelects(); renderAll();
    if (automaticMode()) { loadAutomaticLatest(true);scheduleAutomaticPoll(); }
  }
  function openRace(id) {
    state.selectedId = id; state.detailTab = "outlook";
    refreshSelects(); showPage("detail", true);
  }
  function renderHome() {
    const manual = U.summarize(dailyPurchases()), all = scoped(), actualImported = M.summary(all).overall;
    $("home-metrics").replaceChildren(
      metric("本日の予算", yen(state.budget), "ご自身の設定", "▣"),
      metric("使用額", manual.purchases ? yen(manual.spent) : "記録なし", "この端末の実購入申告", "▤"),
      metric("残予算", yen(state.budget - manual.spent), "予算 − 手動購入記録", "▣"),
      metric("購入の回収率", manual.roi === null ? "未集計" : manual.roi.toFixed(1) + "%", "手入力・確定分のみ", "▥"),
      metric("公式 Hit@8_all", actualImported.hit8 === null ? "未検証" : (actualImported.hit8 * 100).toFixed(1) + "%", "母数 " + actualImported.evaluable + " / 対象 " + actualImported.ledger, "◎")
    );
    $("home-races").replaceChildren(...(all.length ? all.slice(0, 3).map((r, i) => raceCard(r, i === 0)) : [empty("この条件のレースは未取得です", dataset ? "競技・日付を変更するか、「読み込んだ全期間」を確認してください。" : "許可された保存JSONを読み込むと、レース・モデル・結果を確認できます。", true)]));
    $("home-candidates").replaceChildren(...candidateItems());
    const budget = $("home-budget"); budget.replaceChildren(node("strong", "", yen(state.budget - manual.spent)), node("p", "muted", "残予算 / " + yen(state.budget)));
    const progress = node("progress"); progress.max = state.budget; progress.value = Math.min(manual.spent, state.budget); progress.setAttribute("aria-label", "本日の予算使用額"); budget.append(progress, node("p", "muted small", "候補額は使用額に含めません。"));
    $("home-data").replaceChildren(metric("読込レース", all.length + "件", sports[state.sport] + " / 選択期間", "▦"), node("p", "muted small", dataset ? "入力元の追加取得・再予想は行いません。" : "各競技の保存原本は未接続です。"));
  }
  function candidateItems() {
    const groups = [...new Set(state.candidates.map(t => t.raceId))];
    if (!groups.length) return [node("p", "muted", "購入候補はまだありません。")];
    return groups.map(id => {
      const r = races().find(row => row.race_id === id), ts = ticketsFor(id);
      return append(node("div", "candidate-mini"), button(raceName(r), "text-button", () => { state.selectedId = id; refreshSelects(); showPage("picks", true); }), node("strong", "", yen(ts.reduce((s, t) => s + t.amount, 0))), node("small", "muted", ts.length + "点 · " + (state.confirmed.has(id) ? "候補確定 / 未購入" : "編集中 / 未購入")));
    });
  }
  function renderRaces() {
    const all = scoped(), filtered = U.filterRaces(races(), {sport: state.sport, day: state.day, allDates: state.allDates, period: state.period, query: state.query, venue: state.venue, sort: state.sort, forecastOnly: state.forecastOnly, candidatesOnly: state.candidatesOnly, candidateRaceIds: state.candidates.map(t => t.raceId)}).filter(r => state.statusFilter === "all" || (r.private_cycle_view && r.scope !== "synthetic" && state.statusFilter !== "PREDICTION_UNVERIFIED" ? P.compare(r,prediction(r)).status : U.outcome(r, {predictionEligible: M.eligiblePrediction(r, r.prediction), resultEligible: M.eligibleResult(r)})) === state.statusFilter);
    $("race-count").textContent = "表示 " + filtered.length + "件 / 対象 " + all.length + "件（未予想 " + all.filter(r => !predictions(r).length).length + "件を含む）";
    const coverage = U.modelCoverage(all, C.models, {sport: state.sport});
    $("all-race-model-scope").textContent = sports[state.sport] + " · 適用 " + coverage.applicable_models + " / 登録 " + C.models.length + "モデル · 対象台帳 " + coverage.target_races + "レース（保存予想なし " + all.filter(r => !predictions(r).length).length + "レースを含む） · " + coverage.display_stages.map(stage=>stageName({stage}) + " " + coverage.models.reduce((sum,m)=>sum+(m.stages[stage].target_races||0),0) + "対象枠").join(" / ");
    const content = filtered.slice(0, state.visible).map(r => raceCard(r));
    if (!filtered.length) content.push(empty(all.length ? "条件に一致するレースがありません" : sports[state.sport] + "のレースは未取得です", all.length ? "検索・開催場・候補の条件を変更してください。" : "未取得は開催なしを意味しません。保存原本や対象日を確認してください。"));
    if (filtered.length > state.visible) content.push(button("さらに60件表示", "outline full", () => { state.visible += 60; renderRaces(); }));
    $("all-races").replaceChildren(...content);
    const venues = [...new Set(all.map(r => r.venue).filter(Boolean))].sort((a, b) => a.localeCompare(b, "ja"));
    $("venue-buttons").replaceChildren(...(venues.length ? venues.map(venue => { const b = button(venue, "venue-button" + (venue === state.venue ? " active" : ""), () => { state.venue = state.venue === venue ? "" : venue; $("venue-filter").value = state.venue; renderRaces(); }); b.setAttribute("aria-pressed", String(state.venue === venue)); return b; }) : [node("p", "muted", "開催場は未取得です。") ]));
    $("candidate-count").replaceChildren(...candidateItems());
  }
  function predictionPicker(r) {
    const label = node("label", "prediction-picker", "保存予想・モデル・時点"), select = node("select"); select.id = "prediction-select";
    const list = predictions(r);
    if (!list.length) select.append(new Option("未予想・保存原本なし", ""));
    const modelIdentity=p=>JSON.stringify([p.stage,p.model_id,p.model_version,p.variant,M.codeIdentity?.(p)]);
    list.forEach((p, i) => {
      const repeated=list.filter(other=>modelIdentity(other)===modelIdentity(p)).length>1;
      const clock=p.as_of && Number.isFinite(Date.parse(p.as_of)) ? new Intl.DateTimeFormat("ja-JP",{timeZone:"Asia/Tokyo",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false}).format(new Date(p.as_of)) : "未取得";
      select.append(new Option(stageName(p) + " · " + modelName(p) + (p === r.prediction ? " · 基準原本" : " · 比較原本") + (repeated ? " · 取得 " + clock + " JST · 原本 " + (i+1) : ""), String(i)));
    });
    select.disabled = !list.length; select.value = String(state.predictionKeys[r.race_id] ?? 0);
    select.addEventListener("change", () => { state.predictionKeys[r.race_id] = Number(select.value); renderAll(); });
    label.append(select); return label;
  }
  function forecastPanel(r, p) {
    const box = node("section", "forecast-panel");
    box.append(append(node("div", "section-heading"), node("h2", "", p?.native_dispatch_prediction ? "取り込んだ予想" : "保存された予想"), node("span", "tag scope-" + r.scope, forecastStatus(r, p))));
    if (p) box.append(node("p", "muted", modelName(p) + " · " + stageName(p)), ticketPreview(p, 8), node("p", "forecast-rationale", text(p.rationale)), node("p", "muted small", "保存 " + stamp(p.persisted_at) + " JST · " + (p.native_top8_available === false ? "保存された" + p.ordered_top8.length + "点プランです。全候補順位とTop8は未取得です。" : "Top8は予想順位、購入候補とは別の記録です。")));
    else box.append(empty("予想原本は未取得です", r.no_forecast_reason || "このモデル・時点の保存予想がありません。"));
    box.append(button("このレースの買い目を編集 →", "primary full", () => { state.selectedId = r.race_id; refreshSelects(); showPage("picks", true); }));
    return box;
  }
  function resultView(r) {
    const result = r.result, box = node("div", "result-block");
    box.append(outcomeBadge(r,prediction(r)));
    if (!result) return append(box, node("p", "muted", "結果待ち：結果はまだ取得されていません。"));
    const label = (r.private_cycle_view ? {final:"取得結果（公式確定時刻は未取得）",pending:"取得結果待ち",void:"中止・不成立（観測値）",unsupported:"照合不可"} : {final: "確定結果（読込値）", pending: "結果待ち", void: "中止・不成立", unsupported: "照合不可"})[result.status] || "結果未確認";
    box.append(node("strong", "", (r.scope === "synthetic" ? "合成テスト · " : "") + label));
    box.append(node("p","muted small",resultReason(r)));
    result.winning_combinations.forEach(t => box.append(combo(t)));
    if (result.status === "final") box.append(node("p", "muted", "100円当たり払戻 " + payoutSummary(result) + (r.scope === "synthetic" ? "（架空）" : "（読込値）")));
    box.append(node("p", "muted small", "結果確認 " + stamp(result.confirmed_at) + " JST"));
    if (result.observed_at) box.append(node("p", "muted small", "観測取得 " + stamp(result.observed_at) + " JST（公式確定時刻とは別）"));
    if (U.refundSummary(result) !== "未取得") box.append(node("p", "muted", U.refundSummary(result)));
    return box;
  }
  function renderDetail() {
    const target = $("race-detail"), r = currentRace(); target.replaceChildren();
    if (!r) { target.append(empty("レースを選択してください", "全レースから保存原本を選ぶと詳細を確認できます。"), button("全レースを開く →", "primary", () => showPage("races", true))); return; }
    const p = prediction(r), layout = node("div", "two-column detail-layout"), main = node("div"), rail = node("aside", "right-rail");
    const panel = node("section", "panel detail-panel"), title = node("div", "detail-title");
    title.append(node("span", "sport-tag", sports[r.sport]), node("h2", "", raceName(r)), node("span", "tag scope-" + r.scope, scopeName(r.scope)));
    panel.append(title, node("p", "detail-cutoff", (r.cutoff_at==null && r.saved_cutoff_variants?.length ? "選択原本の締切 " : "締切 ") + time(p?.cutoff_at || r.cutoff_at) + " · 発走 " + time(r.start_at)), node("p", "muted small", text(r.event_date_jst) + " JST · 取得 " + stamp(r.observed_at || r.as_of) + " · 状態 " + text(r.race_status)), predictionPicker(r));
    if (r.missing_reasons?.includes("SAVED_FORECAST_CUTOFF_CONFLICT") || r.missing_reasons?.includes("SAVED_SCHEDULE_CUTOFF_CONFLICT")) panel.append(append(node("div","notice"),node("strong","","締切の保存記録に差があります"),node("p","","各予想の元時刻を保持しています。現在の単一の締切へ補正せず、照合できない結果は別に記録します。")));
    const hero = node("div", "detail-hero");
    hero.append(node("p", "eyebrow", "SAVED FORECAST / EVIDENCE"), node("h3", "", p ? "保存された予想を、根拠とともに。" : "出走情報から、レースを知る。"), node("p", "", p?.rationale ? text(p.rationale).slice(0, 180) : r.no_forecast_reason || "取得時点・モデル版と、未取得の項目を確認できます。"), node("span", "hero-wave", "≋"));
    panel.append(hero);
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
      const people = knownParticipants(r), observationContext = boatObservationContext(r);
      if (observationContext) content.append(node("h2", "", "保存予想原本の直前情報"));
      if (people.length) content.append(table(["番号", "選手 / 登録", "展示タイム", "展示ST", "進入", "直前コメント"], people.map(person => [participantNumber(person), participantLabel(person, r), person.display_time, person.preview_st, person.preview_course, person.comment || person.last_comment])));
      const weather = r.weather || r.weather_preview;
      if (weather && Object.keys(weather).length) content.append(facts(Object.entries(weather).map(([key, value]) => [key, sourceText(value)])));
      else content.append(empty(observationContext ? "保存予想原本の気象・直前情報は未取得です" : "気象・直前情報は未取得です", "保存原本に存在する項目だけを表示します。"));
      content.append(node("p", "muted small", "展示・試走の原本値は取得時点の記録です。予想への反映状況はモデル版と時点を確認してください。"));
      if (observationContext) content.append(observationContext);
      const videoMeasurements = globalThis.RaceBoatVideoView?.createPanel(r);
      if (videoMeasurements) content.append(videoMeasurements);
    }
    if (state.detailTab === "analysis") {
      content.append(forecastPanel(r, p), facts(evidenceFields(r, p)), node("h2", "", "同一レースの別モデル・時点"));
      const rows = predictions(r).map(other => [stageName(other), modelName(other), stamp(other.persisted_at), other.ordered_top8.length + "点", forecastStatus(r, other)]);
      content.append(rows.length ? table(["時点", "モデル / 版", "保存 JST", "保存点数", "証拠状態"], rows) : empty("比較予想は未取得です", "別モデル・朝版・展示後版が保存されるとここで比較できます。"));
      if(r.source_observation_view) content.append(node("h2","","保存済みの出走ページ観測"),node("p","notice","出走ページの取得記録です。モデル入力・締切・予想・結果は未接続です。"),facts([["取得元URL",r.source_observation.source_url],["観測取得 JST",stamp(r.source_observation.observed_at)],["元ページSHA",r.source_observation.source_sha256],["原本JSON SHA",r.source_observation.original_json_sha256],["原本artifact ID",r.source_observation.artifact_id]]));
      if (r.dispatch_slots?.length) {
        const labels={NOT_APPLICABLE:"対象外",INPUT_MISSING:"入力未取得",TRAINED_ARTIFACT_MISSING:"学習物未取得",DEADLINE_PASSED:"締切超過・補完なし",RULE_FILTERED:"既存条件の対象外",UNCONNECTED_NATIVE_RUNTIME:"実行経路未接続",SOURCE_NOT_AUTHORIZED:"入力の利用条件未確認",INPUT_REJECTED:"入力不一致",GENERATED_UNATTESTED:"生成済み・外部保存未検証",ORIGINAL_REUSED:"元原本を再利用"};
        const slots=node("section");slots.id="dispatch-slot-status";slots.append(node("h2","","モデル別の入力・生成状態"),node("p","muted","取込データの状態です。生成済みの表示だけでは、締切前の外部保存や全レースの稼働を確認できません。"),table(["時点","モデル / 版","状態","理由"],r.dispatch_slots.map(slot=>[stageName(slot),modelName(slot),labels[slot.status],slot.projection_reason || slot.reason])));content.append(slots);
      }
    }
    if (state.detailTab === "history") {
      content.append(node("h2", "", r.private_cycle_view ? "保存された結果の観測" : "今回の公式結果と改訂履歴"), resultView(r));
      if (r.private_cycle_view) {
        const observations = node("section"); observations.id = "result-observations";
        observations.append(node("h2", "", "取得観測履歴（公式改訂番号なし）"), node("p", "muted", "取得した原本の履歴です。観測順を公式な改訂番号や確定時刻として扱いません。"));
        if (r.result_observation_rejections?.length) observations.append(node("p","notice","照合不可の観測 " + r.result_observation_rejections.length + "件。取得原文は履歴に保持しています。"));
        if (r.result_observations?.length) r.result_observations.forEach(observation => {
          const details = node("details", "panel");details.append(node("summary", "", "観測取得 " + stamp(observation.captured_at) + " JST · " + text(observation.status)));
          const rejected=(r.result_observation_rejections||[]).find(value=>Date.parse(value.captured_at)===Date.parse(observation.captured_at) && (value.source_sha256??null)===(observation.source_sha256??null));
          if(rejected) details.append(node("p","notice","照合不可：" + ({RESULT_CUTOFF_MISMATCH:"予想原本と結果観測で締切が異なります",RESULT_AMBIGUOUS_FORECAST_CUTOFF:"予想原本間で締切が異なります",RESULT_AMBIGUOUS_SCHEDULE_CUTOFF:"台帳間で締切が異なります",RESULT_ROSTER_MISMATCH:"出走者の記録が一致しません",RESULT_FINISH_ORDER_MISMATCH:"着順の記録が一致しません",RESULT_IDENTITY_UNVERIFIED:"結果本文のレースを確認できません"}[rejected.reason]||rejected.reason)));
          details.append(facts([["レースID",observation.race_id],["観測取得 JST",stamp(observation.captured_at)],["観測SHA",observation.source_sha256]]));
          const raw=node("pre","raw-observation");raw.dataset.observationRaw="";raw.textContent=JSON.stringify(observation);
          details.append(node("h3","","保存観測の原文"),raw);observations.append(details);
        }); else observations.append(node("p", "muted", "結果の取得観測原本は未取得です。"));
        content.append(observations);
      }
      const revisions = r.result_revisions || [];
      content.append(revisions.length ? table(["改訂", "状態", "組合せ", "確認 JST", "100円払戻", "返還情報"], revisions.map(rev => [rev.revision_no, rev.status, rev.winning_combinations.map(t => t.join("−")).join(" / "), stamp(rev.confirmed_at), rev.payout_yen_per_100 == null ? "未取得" : yen(rev.payout_yen_per_100), U.refundSummary(rev)])) : node("p", "muted", "結果改訂履歴は未取得です。改訂がなかったことの証明ではありません。"));
      const past = r.past_races;
      content.append(node("h2", "", "過去レース"), Array.isArray(past) && past.length ? facts(past.map((value, i) => [String(i + 1), sourceText(value)])) : node("p", "muted", "過去レースの個別原本は未取得です。"));
    }
    panel.append(content); const missing = [...new Set([...(r.missing_reasons || []), ...(p?.missing_reasons || []), ...(r.no_forecast_reason ? [r.no_forecast_reason] : [])])];
    if (missing.length) panel.append(append(node("div", "notice subtle"), node("strong", "", "未取得・検証中の理由"), node("p", "", missing.join(" / "))));
    main.append(panel);
    rail.append(append(node("section", "panel"), forecastPanel(r, p)), append(node("section", "panel"), node("h2", "", "結果の状態"), resultView(r)), append(node("section", "panel"), node("h2", "", "取得・保存の証拠"), facts(evidenceFields(r, p).filter(([label]) => ["モデル版", "生成時刻 JST", "保存時刻 JST", "元SHA", "予想SHA"].includes(label))), node("p", "muted small", "独立時刻・公式出典は別途照合が必要です。")));
    layout.append(main, rail); target.append(layout);
  }
  function refreshSelects() {
    const venues = [...new Set(scoped().map(r => r.venue).filter(Boolean))].sort((a, b) => a.localeCompare(b, "ja"));
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
    const labels={HIT:"的中",MISS:"不的中",PENDING:"結果待ち",VOID:"中止・返還",REVIEW:"照合不可",NO_FORECAST:"未予想・原本未選択"};
    const note=(r.result?.cutoff_reference||r.result?.cutoff_reconciliation)&&status!=="VOID"?"（参考照合・締切差あり）":status==="PENDING"?"（"+resultReason(r)+"）":"";
    return node("span","saved-outcome outcome-"+status.toLowerCase(),(r.scope==="synthetic"?"合成・":"")+labels[status]+note);
  }
  function resultReason(r) {
    const result=r.result,reference=result?.cutoff_reference;
    if(result?.cutoff_reconciliation){
      const proof=result.cutoff_reconciliation;
      return "原本締切 "+proof.original_cutoffs.map(stamp).join(" / ")+" JST。公式結果と登録出走者を照合。全原本が両方の締切前に保存済み。最大"+proof.maximum_offset_seconds+"秒の記録差を残した参考照合です。";
    }
    if(reference) {
      const clocks="原本締切 "+stamp(reference.original_cutoff_at)+" JST／結果ページ "+stamp(reference.result_schedule_cutoff_at)+" JST（差 "+reference.offset_seconds/60+"分）。";
      return clocks+(reference.basis==="RAW_OFFICIAL_CANCELLATION_SELECTED_RACE"?"公式の中止表示を照合。中止ページの予定時刻変更を保持しています。":"公式結果と6選手を照合。原本は両方の締切前に保存済み。締切差を残した参考照合です。");
    }
    if(result?.status==="unsupported") {
      const reason=r.result_observation_rejections?.find(e=>e.captured_at===result.observed_at)?.reason;
      return ({RESULT_CUTOFF_MISMATCH:"締切情報の不一致を確認中",RESULT_ROSTER_MISMATCH:"出走者情報の不一致を確認中",RESULT_IDENTITY_UNVERIFIED:"公式ページのレース識別を確認できません",RESULT_FINISH_ORDER_MISMATCH:"着順と払戻の整合性を確認中"})[reason]||"取得した結果の整合性を確認中";
    }
    if(result?.status==="void")return "公式の中止・返還表示を照合済み";
    if(result?.status==="final")return "取得結果と保存Top8を照合済み";
    if(Number.isFinite(Date.parse(r.cutoff_at))&&Date.parse(r.cutoff_at)>Date.now())return "締切前";
    if(result?.status==="pending")return "公式の着順情報が未公表";
    return "締切後・結果未同期";
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
    return table(["レース","結果","Top8の判定","100円払戻","結果取得 JST","照合状態・理由"],rows.map(r=>[button(raceName(r),"text-button",()=>openRace(r.race_id)),resultCombination(r),outcomeBadge(r,group?P.pick(r,group):null),payoutSummary(r.result),stamp(r.result?.observed_at),resultReason(r)]));
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
    const groups=M.modelGroups(rows),select=$("results-model");
    if (!groups.some(g=>g.key===state.resultGroupKey)) state.resultGroupKey=groups[0]?.key || "";
    select.replaceChildren(...groups.map(g=>new Option(stageName(g)+" · "+modelName(g)+(g.ambiguous_originals?" · 複数原本 "+g.ambiguous_originals+"レース":""),g.key)));select.value=state.resultGroupKey;select.disabled=!groups.length;
    $("simulation-budget").value=state.simulationBudget;
    $("simulation-budget").disabled=!groups.length;
    $("simulation-race-budget").value=String(state.simulationRaceBudget);$("simulation-race-budget").disabled=!groups.length;
    $("simulation-race-budget").querySelector('[value="800"]').textContent="800円 · 各100円（最大8点）";
    $("simulation-rule").textContent=state.simulationRaceBudget===1000?"各日、締切順に1レース上限1,000円を確保。保存予想の各点に100円（最大8点、3名出走の全6通りは600円）を配分し、残りをモデル間の支持・履歴安定性による参考指標で配分します。根拠不足の追加分は未配分として残し、後続へ配り直しません。払戻・返還は再投資しません。":"各日、締切順に1レース上限800円を確保し、保存予想の各点に100円（最大8点、3名出走の全6通りは600円）を配分します。未配分額は後続へ配り直しません。上限を確保できないレースは見送り、払戻・返還は再投資しません。予想が締切前に保存され、3連単を買えた場合の試算です。";
    $("simulation-allocation-note").hidden=state.simulationRaceBudget!==1000;
    const group=groups.find(g=>g.key===state.resultGroupKey)||null,c=P.summarize(rows,group);
    $("saved-result-metrics").replaceChildren(metric("取得結果",c.available+"レース","保存された結果・中止"),metric("的中",c.hits+"レース","選択モデルと取得結果の一致"),metric("不的中",c.misses+"レース","選択モデルと取得結果の不一致"),metric("結果待ち",c.pending+"レース","未取得分を不的中にしません"));
    $("saved-result-metrics").append(metric("保存Top8的中率",hitRate(c),c.hits+" / "+(c.hits+c.misses)+"レース（結果待ち・照合不可等を除外）"));
    $("saved-result-metrics").append(metric("中止・返還",c.void+"レース","不的中に含めません"),metric("照合保留",c.review+"レース","情報不一致などを確認中"));
    const latest=rows.map(r=>r.result?.observed_at).filter(v=>v&&Number.isFinite(Date.parse(v))).sort((a,b)=>Date.parse(a)-Date.parse(b)).at(-1);
    const references=rows.filter(r=>(r.result?.cutoff_reference||r.result?.cutoff_reconciliation)&&r.result.status==="final").length,cancelReferences=rows.filter(r=>r.result?.cutoff_reference&&r.result.status==="void").length;
    $("result-coverage").textContent="対象 "+rows.length+"レース · 結果取得 "+c.available+" · 中止・返還 "+c.void+" · 未予想・照合不可 "+(c.noForecast+c.review)+" · 最終同期 "+stamp(dataset?.results_synced_at)+" JST · 最終結果取得 "+stamp(latest)+" JST · 締切差の参考照合 "+references+" · 中止ページの時刻変更 "+cancelReferences+"。原本の時刻は変更せず、公式成績には加算しません。";
    $("saved-results-table").replaceChildren(savedResultsTable(rows,group));
    if (!groups.length) {
      $("simulation-metrics").replaceChildren(empty("試算する保存予想は未取得です","取得した結果は上の一覧に表示しています。"));
      for (const id of ["simulation-comparison","simulation-ledger"]) $(id).replaceChildren();return;
    }
    try {
      const scenarios=groups.flatMap(g=>[800,1000].map(raceBudget=>({group:g,sim:P.simulate(rows,g,state.simulationBudget,{raceBudget})})));
      const chosen=scenarios.find(s=>s.group.key===state.resultGroupKey&&s.sim.raceBudget===state.simulationRaceBudget),s=chosen.sim;
      const net=n=>n===null?"未確定":(n>0?"＋":"")+yen(n);
      $("simulation-metrics").replaceChildren(metric("予定購入額",yen(s.spent),s.bought+"レース · 上限"+yen(s.raceBudget)+"/レース · 実購入なし"),metric("未使用予算",yen(s.unspent),"1日 "+yen(s.budgetPerDay)+" × "+s.days.length+"日 · 追加未配分 "+yen(s.held)),metric("確認済み払戻",yen(s.payout),"返還 "+yen(s.refund)),metric("確定分の収支",net(s.settledNet),"購入額 "+yen(s.settledStake)+" の分だけ"),metric("未確定購入額",yen(s.pendingStake),"結果・払戻待ちのレース分"),metric("全体の収支",net(s.net),"仮の残高 "+yen(s.balance)));
      $("simulation-metrics").append(metric("確定分の回収率",s.roi===null?"未確定":s.roi.toFixed(1)+"%","確認済み払戻・返還 ÷ 確定分購入額"),metric("収支確定の購入予定",s.settledCount+" / "+s.bought+"レース","日予算で選んだ対象のみ"),metric("購入予定分の的中率",hitRate(s.boughtComparison),s.boughtComparison.hits+" / "+(s.boughtComparison.hits+s.boughtComparison.misses)+"レース（結果待ち等を除外）"));
      $("simulation-comparison").replaceChildren(table(["モデル・履歴条件","1レース上限","購入予定分の的中 / 照合済","購入予定分の的中率","確定分回収率","予定購入額","払戻","返還","確定分収支","未確定額","全体収支"],scenarios.map(({group,sim:t})=>[modelName(group),yen(t.raceBudget)+(t.raceBudget===1000?" · 参考配分":" · 均等"),t.boughtComparison.hits+" / "+(t.boughtComparison.hits+t.boughtComparison.misses),hitRate(t.boughtComparison),t.roi===null?"未確定":t.roi.toFixed(1)+"%",yen(t.spent),yen(t.payout),yen(t.refund),net(t.settledNet),yen(t.pendingStake),net(t.net)])));
      const raceMap=new Map(rows.map(r=>[r.race_id,r]));
      const reasons={DAILY_BUDGET_LIMIT:"日予算上限で見送り",NO_UNAMBIGUOUS_SAVED_MODEL:"原本未取得、または同条件に複数原本",MODEL_IDENTITY_UNKNOWN:"モデル・版・時点が未取得",COMPLETE_TOP8_NOT_SAVED:"Top8が未完備",TRIFECTA_NOT_OFFERED:"3連単非発売",SAVE_CLOCK_UNKNOWN:"保存時刻未確認",NOT_SAVED_BEFORE_CUTOFF:"締切前保存を確認できません"};
      $("simulation-ledger").replaceChildren(table(["日付・レース","予定額","払戻","返還","収支","配分内訳・根拠","配分の状態"],s.rows.map(e=>[e.day+" · "+raceName(raceMap.get(e.race_id)),yen(e.stake),e.stake?net(e.payout):"—",e.stake?net(e.refund):"—",e.stake?net(e.net):"—",allocationView(e),e.reason?(reasons[e.reason]||e.reason):e.net===null?"結果・払戻待ち":"取得結果で試算済み"])));
    } catch {
      for (const id of ["simulation-comparison","simulation-ledger"]) $(id).replaceChildren();
      $("simulation-metrics").replaceChildren(empty("試算を表示できません","金額・結果・保存原本の整合性を確認してください。"));
      $("simulation-message").textContent="試算できない金額または結果が含まれています。";
    }
  }
  function renderResults() {
    const rows = scoped(), sum = M.summary(rows), g = sum.overall;
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
  function renderResearch() {
    const rows = scoped(), allPredictions = rows.flatMap(predictions), groups = M.modelGroups(rows);
    $("research-metrics").replaceChildren(metric("対象レース", rows.length + "件", "選択した競技・期間"), metric("保存予想", allPredictions.length + "件", "基準・比較モデルを含む"), metric("モデル・時点の版", groups.length + "組", "再予想・再採点なし"), metric("原本の独立監査", "未完了", "取込値の表示"));
    $("model-comparison").replaceChildren(groups.length ? table(["モデル / 版", "区分", "時点", "予想 / 台帳", "評価可能", "Hit@8_all", "比較条件"], groups.map(g => [modelName(g), scopeName(g.scope), stageName(g), g.issued + " / " + g.ledger, g.evaluable, g.hit8 === null ? "未検証" : (g.hit8 * 100).toFixed(2) + "%", g.comparison])) : empty("モデル原本は未取得です", "保存済み予想とモデル版を読み込むと表示します。"));
    renderModelCoverage(rows);
    const content = $("research-content"); content.replaceChildren();
    if (!dataset) { content.append(empty("データは未取得です", "保存JSONを端末内で読み込んでください。", true)); return; }
    content.append(facts([["データ区分", dataset.dataset_status], ["読込全件", races().length + "件"], ["選択競技・期間", rows.length + "件"], ["出典", sourceText(dataset.sources || dataset.provenance_urls || [])], ["取得範囲", "全開催・全レースの捕捉は未検証"], ["再計算", "表示操作による予想・結果の書換はありません"]]));
    content.append(table(["レース", "区分", "モデル・時点", "取得時刻 JST", "元SHA", "未取得・理由"], rows.slice(0, 200).map(r => [raceName(r), scopeName(r.scope), modelName(prediction(r)) + " / " + stageName(prediction(r)), stamp(r.observed_at || r.as_of), r.source_sha || r.source_sha256, (r.missing_reasons || []).join(" / ") || r.no_forecast_reason || "追加情報なし"])));
  }
  function renderModelCoverage(rows) {
    const coverage = U.modelCoverage(rows, C.models, {sport: state.sport});
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
  function renderMeta() {
    document.querySelectorAll("[data-sport]").forEach(b => { const active = b.dataset.sport === state.sport; b.classList.toggle("active", active); b.setAttribute("aria-pressed", String(active)); });
    $("selected-date").value = state.day; $("period-all").checked = state.allDates; $("period-filter").value = state.allDates ? "all" : state.period; $("display-day").textContent = state.allDates ? "読み込んだ全期間 / " + sports[state.sport] : (state.period === "week" ? "週の基準 " : "") + state.day + " JST / " + sports[state.sport];
    $("daily-budget").value = state.budget; $("settings-sport").value = state.sport;
    const kind = dataset?.dataset_status;
    $("data-banner").classList.toggle("synthetic-banner", kind === "SYNTHETIC_ONLY");
    $("data-banner").textContent = kind === "SYNTHETIC_ONLY" ? "合成テスト専用 · レース・予想・結果・払戻は架空です。実績には含みません。" : kind === "REAL_REPORTED" ? "読込原本の申告値 · 出典・外部時刻の独立照合は別途必要です。" : dataset ? "研究・監査データ · 実績の証明には使用しません。" : "データ未取得 · 許可された保存原本を端末内で読み込めます。";
    $("source-state").textContent = kind === "SYNTHETIC_ONLY" ? "合成テスト表示中" : dataset ? "ローカル原本 / 独立監査未完了" : "データ未取得";
    const dates = [...new Set(races().map(r => r.event_date_jst).filter(Boolean))].sort();
    $("source-date").textContent = "対象日：" + (dates.length ? dates[0] + (dates.length > 1 ? "〜" + dates.at(-1) : "") : "未取得");
    $("source-time").textContent = "取得時刻：" + (dataset ? "各レースの保存原本を参照" : "未取得");
    $("clear-data").disabled = !dataset;
    renderGeneration();
  }
  function renderAll() { renderMeta(); renderHome(); renderRaces(); renderTickets(); renderResults(); renderResearch(); if (state.page === "detail") renderDetail(); }
  function adoptDataset(parsed) {
    generation.ownsDisplay = false;generation.suppressed = true;generation.pausedForDrafts = false;generation.pausedForEditing = false;
    dataset = parsed; state.selectedId = ""; state.predictionKeys = {}; state.candidates = []; state.confirmed.clear(); state.venue = ""; state.visible = 60; $("purchase-ack").checked = false;
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
    if (document.getElementById("race-ai-private-saved-data") || document.querySelector('meta[name="race-ai-private-saved-view"],meta[name="race-ai-encrypted-saved-view"]')) {
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
    const validCounts = summary && count(summary.generated) && count(summary.reused) && (unknownCoverage ? summary.missing === null && summary.generated === 0 && count(summary.races) && summary.races === parsed.records.length && summary.reused === parsed.records.reduce((sum,row)=>sum+predictions(row).length,0) : count(summary.missing));
    if (parsed.event_date_jst != null && parsed.event_date_jst !== result.day_jst || parsed.records.some(row=>row.event_date_jst !== result.day_jst || row.sport !== sport || row.stage != null && row.stage !== stage || row.scheduled_stages?.some(value=>value !== stage) || (row.dispatch_slots || []).some(slot=>slot.stage !== stage) || predictions(row).some(p=>p.stage !== stage)) || !validCounts) throw new Error("automatic response");
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
      const dates = parsed.records.map(r=>r.event_date_jst).filter(Boolean).sort();
      state.day = dates.at(-1) || state.day;state.sport = parsed.records[0].sport;
      state.followsToday = false;state.allDates = false;state.period = "day";
      generation.message = "保存済み予想 " + parsed.records.length + "レースを表示しています。";
      adoptDataset(parsed);showPage("races",true);
      $("file-message").textContent = generation.message;
      if (encrypted) startSavedFeed(encrypted.content,version);
    } catch {
      generation.message = "保存原本を読み込めませんでした。保存先と同期状態を確認してください。";
      $("file-message").textContent = generation.message;renderGeneration();
    }
  }
  function startSavedFeed(path,version) {
    const forecastSha=document.querySelector('meta[name="race-ai-saved-view-forecast-sha"]')?.content;
    if(!forecastSha||!window.SavedViewCrypto?.readLive)return;
    const status=node("p","muted small","結果の自動同期を確認しています。");status.id="saved-view-sync";status.setAttribute("role","status");
    $("result-coverage").after(status);
    let previous={forecastSha,generation:0,cipherSha:path.split("/").at(-1).replace(".json","")},busy=false;
    async function check() {
      if(busy||version!==importVersion||!dataset||document.hidden)return;
      if(document.activeElement?.matches('input,select,textarea'))return;
      busy=true;
      try {
        const result=await window.SavedViewCrypto.readLive(location.hash,previous);
        if(version!==importVersion||!dataset)return;
        if(result) {
          const parsed=M.parse(result.view);
          if(document.activeElement?.matches('input,select,textarea'))return;
          const chosen=new Map(races().map(row=>{const p=prediction(row);return [row.race_id,p?M.savedPredictionIdentity(p):null];})),keys={};
          for(const row of parsed.records){
            const identity=chosen.get(row.race_id);if(identity==null)continue;
            const index=predictions(row).findIndex(p=>M.savedPredictionIdentity(p)===identity);
            if(index<0)throw new Error("saved original selection unavailable");
            keys[row.race_id]=index;
          }
          dataset=parsed;state.predictionKeys=keys;previous={forecastSha,generation:result.header.generation,cipherSha:result.cipherSha};
          refreshSelects();
          renderAll();status.dataset.generation=String(previous.generation);
        }
        status.textContent="結果を自動同期中（60秒ごとに確認） · 最終同期 "+stamp(dataset.results_synced_at)+" JST。収集処理の停止中は前回の結果を表示します。";
      } catch {status.textContent="自動同期を確認できません。前回取得した結果を表示中です。60秒後に再確認します。";}
      finally {busy=false;}
    }
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
  $("selected-date").addEventListener("change", () => { if (!$("selected-date").value) { $("selected-date").value = state.day; return; } state.day = $("selected-date").value; state.followsToday = false; state.allDates = false; state.period = "day"; state.visible = 60; refreshSelects(); renderAll(); });
  $("period-all").addEventListener("change", () => { state.allDates = $("period-all").checked; state.visible = 60; refreshSelects(); renderAll(); });
  $("period-filter").addEventListener("change", e => { state.allDates = e.target.value === "all"; state.period = state.allDates ? "day" : e.target.value; state.visible = 60; refreshSelects(); renderAll(); });
  function search(value) { state.query = value; state.visible = 60; $("race-search").value = value; $("global-search").value = value; renderRaces(); }
  $("global-search").addEventListener("input", e => { search(e.target.value); showPage("races"); });
  $("race-search").addEventListener("input", e => search(e.target.value));
  $("race-sort").addEventListener("change", e => { state.sort = e.target.value; renderRaces(); });
  $("venue-filter").addEventListener("change", e => { state.venue = e.target.value; renderRaces(); });
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
  $("clear-data").addEventListener("click", () => { ++importVersion;generation.ownsDisplay = false;generation.suppressed = true; dataset = null; state.selectedId = ""; state.predictionKeys = {}; state.candidates = []; state.confirmed.clear(); $("purchase-ack").checked = false; refreshSelects(); renderAll(); $("file-message").textContent = "読み込んだ予想と候補をメモリから消去しました。手動購入記録は再読込まで保持します。"; });
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
  function checkDay() { if (automaticMode()) return;const today = A.jstToday(); if (state.followsToday && state.day !== today) { state.day = today; refreshSelects(); renderAll(); } }
  setInterval(checkDay, 30000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) checkDay(); });
  window.addEventListener("pagehide",()=>{if(generation.timer!==null)clearTimeout(generation.timer);generation.timer=null;});
  window.addEventListener("pageshow",event=>{if(event.persisted && automaticMode())scheduleAutomaticPoll();});
  document.addEventListener("focusout",()=>{if(automaticMode() && generation.pausedForEditing)queueMicrotask(()=>loadAutomaticLatest(true));});
  document.addEventListener("change",()=>{if(automaticMode() && generation.pausedForEditing)queueMicrotask(()=>loadAutomaticLatest(true));});
  refreshSelects(); renderAll(); showPage(location.hash.slice(1) || "home");
  connectGeneration();
  loadSavedDataset();
})();
