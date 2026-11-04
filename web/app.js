"use strict";
/* PR #62 page shell and manual ticket flow, connected to saved audit objects only. */
(() => {
  const $ = id => document.getElementById(id);
  const U = globalThis.RaceUI, M = globalThis.RaceProductData, A = globalThis.RaceAuditModel, C = globalThis.RaceExistingModelCatalog;
  const sports = {boat: "ボートレース", keirin: "競輪", autorace: "オートレース", horse: "競馬"};
  const icons = {boat: "◒", keirin: "♧", autorace: "♧", horse: "♞"};
  const pageNames = {
    home: ["YOUR RACE DASHBOARD", "今日のレースを、確かなデータで。", "保存済みの予想・結果と、あなたの買い目候補をひとつに。"],
    races: ["ALL RACES", "全レース一覧", "未予想も含めて、取得できたレースを確認。"],
    detail: ["RACE DETAIL", "レース詳細", "出走情報・保存済み予想・根拠を、取得時点ごとに。"],
    picks: ["TICKET ALLOCATION", "買い目配分", "予算に合わせて候補を編集。確定した候補も、実購入とは別の記録です。"],
    results: ["PERFORMANCE", "成績分析", "公式結果・対象分母と、ご自身の購入記録を確認。"],
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
    maxPicks: [8, 16, 24, 32].includes(preferences.maxPicks) ? preferences.maxPicks : 8,
    candidates: [], purchases: [], confirmed: new Set(), visible: 60
  };
  let dataset = null, importVersion = 0;
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
  const scopeName = scope => ({official: "公式対象・読込値", research: "研究 / 監査", synthetic: "合成テスト"})[scope] || "証拠未確認";
  const races = () => dataset?.records || [];
  const scoped = () => U.filterRaces(races(), {sport: state.sport, day: state.day, allDates: state.allDates, period: state.period, sort: state.sort});
  const currentRace = () => races().find(r => r.race_id === state.selectedId);
  const raceName = r => r ? r.venue + " " + r.race_no + "R" : "レース未選択";
  const predictions = r => r ? (M.candidates ? M.candidates(r) : [r.prediction, ...(r.comparison_predictions || [])].filter(Boolean)) : [];
  const prediction = r => {
    const list = predictions(r), saved = state.predictionKeys[r?.race_id];
    return saved === undefined ? list[0] || null : list[saved] || null;
  };
  const modelName = p => p ? text(p.model_id || p.model_version) + (p.model_id ? " / " + text(p.model_version) : "") + (p.variant ? " · " + text(p.variant) : "") : "未予想";
  const stageName = p => ({P0: "P0 朝版", P1: "P1 展示・試走後"})[p?.stage] || "時点未取得";
  const ticketsFor = id => state.candidates.filter(t => t.raceId === id);
  const dailyPurchases = () => state.purchases.filter(p => p.day === A.jstToday());
  const knownParticipants = r => Array.isArray(r?.participants) ? r.participants : [];
  const participantNumber = p => p.number ?? p.lane ?? p.horse_no ?? p.bib_number;
  const maxNumber = r => {
    const numbers = knownParticipants(r).map(participantNumber).filter(Number.isInteger);
    const saved = predictions(r).flatMap(p => p.ordered_top8.flat());
    return Math.min(99, Math.max(r?.sport === "boat" ? 6 : r?.sport === "horse" ? 18 : r?.sport === "keirin" ? 9 : 8, ...numbers, ...saved));
  };
  const badge = n => node("span", "lane lane-" + (n <= 6 ? n : "other"), String(n));
  const combo = values => { const n = node("span", "combo"); values.forEach((v, i) => { if (i) n.append(node("span", "combo-dash", "−")); n.append(badge(v)); }); return n; };
  function persistPreferences() {
    try { localStorage.setItem(storageKey, JSON.stringify({budget: state.budget, raceBudget: state.raceBudget, maxPicks: state.maxPicks, sport: state.sport})); } catch { /* App remains usable with storage disabled. */ }
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
  function evidenceFields(r, p) {
    return [["データ区分", scopeName(r.scope)], ["開催日 JST", r.event_date_jst], ["モデル", p?.model_id], ["モデル版", p?.model_version], ["予想時点", stageName(p)],
      ["生成時刻 JST", stamp(p?.generated_at)], ["保存時刻 JST", stamp(p?.persisted_at)], ["締切 JST", stamp(r.cutoff_at)],
      ["取得 / as-of JST", stamp(p?.as_of || r.as_of || r.observed_at)], ["情報源", sourceText(r.source_provenance)],
      ["元SHA", r.source_sha || r.source_sha256], ["入力SHA", p?.input_sha256], ["予想SHA", p?.prediction_sha256],
      ["原本JSON SHA", p?.original_json_sha256], ["原本artifact ID", p?.artifact_id], ["保存モデル区分", p?.variant], ["保存済みサーバー時刻の申告 JST", stamp(p?.server_saved_at)],
      ["レシート時刻 JST", stamp(p?.external_receipt?.server_received_at || p?.receipt_timestamp || p?.evidence_receipt?.timestamp)], ["独立検証", "取込値のみ・原本と外部時刻の独立照合は別途必要"]];
  }
  function forecastStatus(r, p = prediction(r)) {
    if (!p) return "未予想";
    if (r.scope === "synthetic") return "合成・保存予想";
    if (M.eligiblePrediction?.(r, p)) return "証拠付き保存予想（読込値）";
    return "保存予想・証拠不足";
  }
  function participantCard(p, expanded = false) {
    const number = participantNumber(p), card = node("article", "racer-card"), avatar = node("div", "racer-avatar");
    if (Number.isInteger(number)) avatar.append(badge(number));
    avatar.append(node("span", "avatar-silhouette", "◉"));
    const registration = p.registration_no || p.registration_id || p.racer_registration_id;
    card.append(avatar, node("strong", "racer-name", p.placeholder ? "出走者 未取得" : p.name ? text(p.name) : registration ? "登録 " + text(registration) : "名前 未取得"), node("small", "muted", p.placeholder ? "表示用の枠" : text(registration)));
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
    card.append(participantGrid(r));
    const foot = node("div", "race-card-footer"), saved = node("div", "card-prediction");
    saved.append(node("strong", "small", p ? "保存Top8 · " + p.ordered_top8.length + "点" : "未予想"), node("p", "muted model-caption", modelName(p)), ticketPreview(p, featured ? 4 : 2));
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
    if (location.hash !== "#" + page) history.pushState(null, "", "#" + page);
    if (page === "detail") renderDetail();
    if (page === "picks") renderTickets();
    if (moveFocus) { $("page-title").tabIndex = -1; $("page-title").focus({preventScroll: true}); window.scrollTo({top: 0}); }
  }
  function setSport(sport) {
    state.sport = sport; state.venue = ""; state.visible = 60;
    if (state.page === "detail") showPage("races");
    persistPreferences(); refreshSelects(); renderAll();
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
    const all = scoped(), filtered = U.filterRaces(races(), {sport: state.sport, day: state.day, allDates: state.allDates, period: state.period, query: state.query, venue: state.venue, sort: state.sort, forecastOnly: state.forecastOnly, candidatesOnly: state.candidatesOnly, candidateRaceIds: state.candidates.map(t => t.raceId)}).filter(r => state.statusFilter === "all" || U.outcome(r, {predictionEligible: M.eligiblePrediction(r, r.prediction), resultEligible: M.eligibleResult(r)}) === state.statusFilter);
    $("race-count").textContent = "表示 " + filtered.length + "件 / 対象 " + all.length + "件（未予想 " + all.filter(r => !predictions(r).length).length + "件を含む）";
    const coverage = U.modelCoverage(all, C.models, {sport: state.sport});
    $("all-race-model-scope").textContent = sports[state.sport] + " · 適用 " + coverage.applicable_models + " / 登録 " + C.models.length + "モデル · 対象台帳 " + coverage.target_races + "レース（保存予想なし " + all.filter(r => !predictions(r).length).length + "レースを含む） · P0 / P1 各 " + coverage.applicable_models * coverage.target_races + "対象枠";
    const content = filtered.slice(0, state.visible).map(r => raceCard(r));
    if (!filtered.length) content.push(empty(all.length ? "条件に一致するレースがありません" : sports[state.sport] + "のレースは未取得です", all.length ? "検索・開催場・候補の条件を変更してください。" : "未取得は開催なしを意味しません。保存原本や対象日を確認してください。"));
    if (filtered.length > state.visible) content.push(button("さらに60件表示", "outline full", () => { state.visible += 60; renderRaces(); }));
    $("all-races").replaceChildren(...content);
    const venues = [...new Set(all.map(r => r.venue))].sort((a, b) => a.localeCompare(b, "ja"));
    $("venue-buttons").replaceChildren(...(venues.length ? venues.map(venue => { const b = button(venue, "venue-button" + (venue === state.venue ? " active" : ""), () => { state.venue = state.venue === venue ? "" : venue; $("venue-filter").value = state.venue; renderRaces(); }); b.setAttribute("aria-pressed", String(state.venue === venue)); return b; }) : [node("p", "muted", "開催場は未取得です。") ]));
    $("candidate-count").replaceChildren(...candidateItems());
  }
  function predictionPicker(r) {
    const label = node("label", "prediction-picker", "保存予想・モデル・時点"), select = node("select"); select.id = "prediction-select";
    const list = predictions(r);
    if (!list.length) select.append(new Option("未予想・保存原本なし", ""));
    list.forEach((p, i) => select.append(new Option(stageName(p) + " · " + modelName(p) + (p === r.prediction ? " · 基準原本" : " · 比較原本"), String(i))));
    select.disabled = !list.length; select.value = String(state.predictionKeys[r.race_id] ?? 0);
    select.addEventListener("change", () => { state.predictionKeys[r.race_id] = Number(select.value); renderDetail(); renderTickets(); });
    label.append(select); return label;
  }
  function forecastPanel(r, p) {
    const box = node("section", "forecast-panel");
    box.append(append(node("div", "section-heading"), node("h2", "", "保存された予想"), node("span", "tag scope-" + r.scope, forecastStatus(r, p))));
    if (p) box.append(node("p", "muted", modelName(p) + " · " + stageName(p)), ticketPreview(p, 8), node("p", "forecast-rationale", text(p.rationale)), node("p", "muted small", "保存 " + stamp(p.persisted_at) + " JST · Top8は予想順位、購入候補とは別の記録です。"));
    else box.append(empty("予想原本は未取得です", r.no_forecast_reason || "このモデル・時点の保存予想がありません。"));
    box.append(button("このレースの買い目を編集 →", "primary full", () => { state.selectedId = r.race_id; refreshSelects(); showPage("picks", true); }));
    return box;
  }
  function resultView(r) {
    const result = r.result, box = node("div", "result-block");
    if (!result) return append(box, node("p", "muted", "公式結果は未取得です。"));
    const label = (r.private_cycle_view ? {final:"取得結果（公式確定時刻は未取得）",pending:"取得結果待ち",void:"中止・不成立（観測値）",unsupported:"照合不可"} : {final: "確定結果（読込値）", pending: "結果待ち", void: "中止・不成立", unsupported: "照合不可"})[result.status] || "結果未確認";
    box.append(node("strong", "", (r.scope === "synthetic" ? "合成テスト · " : "") + label));
    result.winning_combinations.forEach(t => box.append(combo(t)));
    if (result.payout_yen_per_100 !== null && result.payout_yen_per_100 !== undefined) box.append(node("p", "muted", "100円当たり払戻 " + yen(result.payout_yen_per_100) + (r.scope === "synthetic" ? "（架空）" : "（読込値）")));
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
    panel.append(title, node("p", "detail-cutoff", "締切 " + time(r.cutoff_at) + " · 発走 " + time(r.start_at)), node("p", "muted small", text(r.event_date_jst) + " JST · 取得 " + stamp(r.observed_at || r.as_of) + " · 状態 " + text(r.race_status)), predictionPicker(r));
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
      if (knownParticipants(r).length) content.append(table(["番号", "名前", "登録", "モーター", "平均ST", "展示"], knownParticipants(r).map(person => [participantNumber(person), person.name, person.registration_no || person.registration_id || person.racer_registration_id, person.motor_no, person.average_st, person.display_time])));
    }
    if (state.detailTab === "preview") {
      const people = knownParticipants(r);
      if (people.length) content.append(table(["番号", "展示タイム", "展示ST", "進入", "直前コメント"], people.map(person => [participantNumber(person), person.display_time, person.preview_st, person.preview_course, person.comment || person.last_comment])));
      const weather = r.weather || r.weather_preview;
      if (weather && Object.keys(weather).length) content.append(facts(Object.entries(weather).map(([key, value]) => [key, sourceText(value)])));
      else content.append(empty("気象・直前情報は未取得です", "保存原本に存在する項目だけを表示します。"));
      content.append(node("p", "muted small", "展示・試走の原本値は取得時点の記録です。予想への反映状況はモデル版と時点を確認してください。"));
    }
    if (state.detailTab === "analysis") {
      content.append(forecastPanel(r, p), facts(evidenceFields(r, p)), node("h2", "", "同一レースの別モデル・時点"));
      const rows = predictions(r).map(other => [stageName(other), modelName(other), stamp(other.persisted_at), other.ordered_top8.length + "点", forecastStatus(r, other)]);
      content.append(rows.length ? table(["時点", "モデル / 版", "保存 JST", "Top8", "証拠状態"], rows) : empty("比較予想は未取得です", "別モデル・朝版・展示後版が保存されるとここで比較できます。"));
    }
    if (state.detailTab === "history") {
      content.append(node("h2", "", r.private_cycle_view ? "保存された結果の観測" : "今回の公式結果と改訂履歴"), resultView(r));
      if (r.private_cycle_view) {
        const observations = node("section"); observations.id = "result-observations";
        observations.append(node("h2", "", "取得観測履歴（公式改訂番号なし）"), node("p", "muted", "取得した原本の履歴です。観測順を公式な改訂番号や確定時刻として扱いません。"));
        if (r.result_observations?.length) r.result_observations.forEach(observation => {
          const details = node("details", "panel");details.append(node("summary", "", "観測取得 " + stamp(observation.captured_at) + " JST · " + text(observation.status)));
          details.append(facts([["レースID",observation.race_id],["観測取得 JST",stamp(observation.captured_at)],["観測SHA",observation.source_sha256],["保存観測の原文",sourceText(observation)]]));observations.append(details);
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
    const venues = [...new Set(scoped().map(r => r.venue))].sort((a, b) => a.localeCompare(b, "ja"));
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
    const list = $("ticket-list"); list.replaceChildren();
    if (!ts.length) list.append(empty("買い目候補を追加しましょう", r ? "保存Top8または異なる3つの番号と金額を入力できます。" : "対象レースの保存原本を先に読み込んでください。"));
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
  function renderResults() {
    const rows = scoped(), sum = M.summary(rows), g = sum.overall;
    $("result-metrics").replaceChildren(metric("全対象の台帳", g.ledger + "件", "取得範囲は独立確認が必要"), metric("公式・評価可能", g.evaluable + "件", "未予想も分母に含む"), metric("全対象 Hit@8_all", g.hit8 === null ? "未検証" : (g.hit8 * 100).toFixed(2) + "%", "的中 " + (g.hits ?? "未検証") + " / 評価可能 " + g.evaluable), metric("証拠不足・評価外", g.excluded + "件", "未確定・研究・合成を区別"));
    $("rate-limitations").textContent = g.identity_mixed ? "モデル・版・時点が混在するため、合算率を表示しません。研究ページのモデル別集計を確認してください。" : g.stage_mixed ? "朝版・展示後版が混在するため、合算率を表示しません。時点別の集計を確認してください。" : "保存された取込値の整合性に基づく集計です。原本の権限・署名・独立時刻はブラウザで認証していません。";
    $("result-sports").replaceChildren(table(["競技", "台帳", "評価可能", "的中", "Hit@8_all"], Object.entries(sum.bySport).map(([sport, stats]) => [sports[sport], stats.ledger, stats.evaluable, stats.hits ?? "未検証", stats.hit8 === null ? "未検証" : (stats.hit8 * 100).toFixed(2) + "%"])));
    $("result-stages").replaceChildren(table(["時点", "台帳", "評価可能", "的中", "Hit@8_all"], Object.entries(sum.byStage).map(([stage, stats]) => [stageName({stage}), stats.ledger, stats.evaluable, stats.hits ?? "未検証", stats.hit8 === null ? "未検証" : (stats.hit8 * 100).toFixed(2) + "%"])));
    const settled = rows.filter(r => r.result);
    const resultHeading = $("official-results").parentElement.querySelector("h2");
    resultHeading.textContent = rows.some(r => r.private_cycle_view) ? "レース別の結果観測（独立未検証）" : "レース別の公式結果";
    $("official-results").replaceChildren(...(settled.length ? settled.slice(0, 100).map(r => append(node("article", "official-result-row"), button(raceName(r), "text-button", () => openRace(r.race_id)), node("span", "tag scope-" + r.scope, scopeName(r.scope)), resultView(r))) : [empty("公式結果は未取得です", "予想と別時点の結果原本が読み込まれると表示されます。全レースの取得完了を意味しません。") ]));
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
        for (const stage of ["P0", "P1"]) stageCounts.append(node("p", "", stage + " " + spec.stages[stage].saved_races + " / " + spec.stages[stage].target_races + "（未予想 " + spec.stages[stage].missing_races + "）"));
        stageCounts.append(node("p", "muted small", "時点不明の保存 " + spec.stages.UNKNOWN.saved_races + "件"));
      } else stageCounts.append(node("p", "muted", "対象外 · 分母に含めません"));
      const versions = node("div", "catalog-lines");
      if (spec.versions.length) spec.versions.forEach(v => versions.append(node("p", "", scopeName(v.scope) + " · " + stageName(v) + " · " + text(v.model_version) + " · " + v.saved_races + "レース")));
      else versions.append(node("p", "muted", "保存版 未取得"));
      const status = node("div", "catalog-status");
      status.append(node("strong", "", !spec.applicable ? "対象外" : !spec.saved_races ? "未予想／入力未接続" : spec.missing_races || spec.stages.P0.missing_races || spec.stages.P1.missing_races ? "保存原本あり／一部未予想" : "取込対象の保存原本あり"));
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
  }
  function renderAll() { renderMeta(); renderHome(); renderRaces(); renderTickets(); renderResults(); renderResearch(); if (state.page === "detail") renderDetail(); }
  function adoptDataset(parsed) {
    dataset = parsed; state.selectedId = ""; state.predictionKeys = {}; state.candidates = []; state.confirmed.clear(); state.venue = ""; state.visible = 60; $("purchase-ack").checked = false;
    refreshSelects(); renderAll();
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
  document.querySelectorAll("[data-page]").forEach(b => b.addEventListener("click", () => showPage(b.dataset.page, true)));
  document.querySelectorAll("[data-sport]").forEach(b => b.addEventListener("click", () => setSport(b.dataset.sport)));
  window.addEventListener("hashchange", () => showPage(location.hash.slice(1)));
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
  $("load-synthetic").addEventListener("click", loadSynthetic);
  $("clear-data").addEventListener("click", () => { ++importVersion; dataset = null; state.selectedId = ""; state.predictionKeys = {}; state.candidates = []; state.confirmed.clear(); $("purchase-ack").checked = false; refreshSelects(); renderAll(); $("file-message").textContent = "読み込んだ予想と候補をメモリから消去しました。手動購入記録は再読込まで保持します。"; });
  // A local clock change updates the display day, without fetching race sources.
  function checkDay() { const today = A.jstToday(); if (state.followsToday && state.day !== today) { state.day = today; refreshSelects(); renderAll(); } }
  setInterval(checkDay, 30000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) checkDay(); });
  refreshSelects(); renderAll(); showPage(location.hash.slice(1) || "home");
})();
