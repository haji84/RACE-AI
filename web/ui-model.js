/* Reused from PR #62: manual accounting is independent of forecast/result evidence. */
(function (root) {
  "use strict";
  const boatVenues = Object.freeze([
    "桐生", "戸田", "江戸川", "平和島", "多摩川", "浜名湖", "蒲郡", "常滑", "津", "三国", "びわこ", "住之江",
    "尼崎", "鳴門", "丸亀", "児島", "宮島", "徳山", "下関", "若松", "芦屋", "福岡", "唐津", "大村"
  ]);
  const validVenueDay = value => {
    if (typeof value !== "string" || !/^\d{4}-\d\d-\d\d$/.test(value)) return false;
    const clock = Date.parse(value + "T00:00:00Z");
    return Number.isFinite(clock) && new Date(clock).toISOString().slice(0, 10) === value;
  };
  const model = {
    modelOptions(rows, catalog, sport) {
      const retired = new Set(catalog?.retired_model_ids || []), counts = new Map(), specs = new Map();
      for (const spec of catalog?.models || []) if (!retired.has(spec.model_id) && spec.applicable_sports.includes(sport)) specs.set(spec.model_id, spec);
      for (const row of rows || []) {
        if (row.sport !== sport) continue;
        for (const p of [row.prediction, ...(row.comparison_predictions || [])]) {
          if (!p || typeof p.model_id !== "string" || !p.model_id || retired.has(p.model_id)) continue;
          if (!specs.has(p.model_id)) specs.set(p.model_id, {model_id:p.model_id});
          if (!counts.has(p.model_id)) counts.set(p.model_id, new Set());
          counts.get(p.model_id).add(row.race_id);
        }
      }
      return [...specs.keys()].map(model_id => ({model_id,races:counts.get(model_id)?.size || 0}))
        .sort((a,b) => b.races-a.races);
    },
    modelPrediction(list, modelId, preferredIndex) {
      const preferred = Number.isInteger(preferredIndex) ? list[preferredIndex] : null;
      if (preferred && (!modelId || preferred.model_id === modelId)) return preferred;
      return modelId ? list.find(p => p.model_id === modelId) || null : list[0] || null;
    },
    venueName(row) {
      // Resolve the saved BOAT code for display without rewriting the original record.
      const code = row?.sport === "boat" && typeof row.venue === "string" ? /^(?:場コード|boatrace-jcd-)(0[1-9]|1[0-9]|2[0-4])$/.exec(row.venue) : null;
      return code ? boatVenues[Number(code[1]) - 1] : row?.venue;
    },
    participantName(row, person) {
      // The existing catalogue checks every supplied registration field and
      // exact observed name alias before returning the full public name.
      return root.RaceRacerPortraits?.get(row, person)?.name || person?.name || null;
    },
    forecastExplanation(row, prediction) {
      const tickets=prediction?.ordered_top8;
      if(!Array.isArray(tickets)||!tickets.length||tickets.length>8||tickets.some(t=>!Array.isArray(t)||t.length!==3||t.some(n=>!Number.isInteger(n)||n<1||n>99)||new Set(t).size!==3))return null;
      const unit=row?.sport==="boat"?"号艇":row?.sport==="horse"?"番":"番車",label=n=>n+unit;
      const method={
        "boat-observed-pairwise-factor-v1":"出走表と取得できた観測値を、選手間で比較する方式です。",
        "boat-observed-pairwise-start-v1":"スタート関連の観測値を重視し、選手間で比較する方式です。",
        "boat-comprehensive-v1":"複数の要素をまとめて評価し、3連単を順位付けする方式です。",
        "boat-scenario-mixture-v1":"前残り・攻め・荒れた条件の複数の想定を組み合わせる方式です。",
        "boat-course-entry-method-scenarios-v0.1-UNTRAINED":"進入コースや決まり手の履歴から、複数の展開を比較する方式です。",
        "multisport-conditional-duel-v1":"出走者どうしの相性と着順の組み合わせを比較する方式です。",
        "multisport-race-trajectory-v1":"先行・追走などの複数の流れを組み合わせて比較する方式です。"
      }[prediction.model_id]||"モデルが保存した3連単の順位と、上位買い目の構成をもとにしています。";
      const saved=[prediction.rationale,prediction.explanation].find(v=>typeof v==="string"&&v.trim());
      const counts=new Map();for(const ticket of tickets)counts.set(ticket[0],(counts.get(ticket[0])||0)+1);
      const main=tickets[0],other=tickets.find(t=>t[0]!==main[0])||tickets.find(t=>t[1]!==main[1])||tickets.find(t=>t.some((n,i)=>n!==main[i]));
      const sequence=t=>t.map(label).join(" → ");
      return {
        rationale:saved||method+" 保存された上位"+tickets.length+"点を表示しています。",
        composition:"1着に置く買い目の内訳："+[...counts].map(([n,count])=>label(n)+"を"+count+"点").join("、")+"。",
        outlook:"本線は "+sequence(main)+" の決着を想定。"+label(main[0])+"を中心に、"+label(main[1])+"と"+label(main[2])+"が続く組み立てです。",
        alternative:other?"対抗は "+sequence(other)+"。"+(other[0]!==main[0]?label(other[0])+"が本線の先頭に代わる形も買い目に残しています。":label(other[1])+"と"+label(other[2])+"を続く相手に置く別の組み立てです。"):null,
        basis:"保存買い目の着順から整理した想定です。進入や具体的な仕掛けの判断までは、この買い目だけでは分かりません。"
      };
    },
    raceDeadline(row = {}) {
      const valid = value => typeof value === "string" && Number.isFinite(Date.parse(value));
      if (valid(row.cutoff_at)) return row.cutoff_at;
      return [...(Array.isArray(row.saved_cutoff_variants) ? row.saved_cutoff_variants : []), row.prediction?.cutoff_at,
        ...(Array.isArray(row.comparison_predictions) ? row.comparison_predictions.map(p => p?.cutoff_at) : [])]
        .filter(valid).sort((a, b) => Date.parse(a) - Date.parse(b))[0] || null;
    },
    racePhase(row = {}, {now = Date.now()} = {}) {
      if (["final", "settled", "void", "cancelled"].includes(row.result?.status)) return "results";
      const deadline = model.raceDeadline(row);
      if (deadline) return Date.parse(deadline) > now ? "upcoming" : "results";
      const today = new Date(now + 9 * 3600000).toISOString().slice(0, 10);
      return validVenueDay(row.event_date_jst) && row.event_date_jst < today ? "results" : "unknown";
    },
    raceLists(records, {now = Date.now()} = {}) {
      const lists = {upcoming: [], results: [], unknown: []};
      for (const row of records) lists[model.racePhase(row, {now})].push(row);
      const deadline = row => { const value = Date.parse(model.raceDeadline(row)); return Number.isFinite(value) ? value : -Infinity; };
      lists.upcoming.sort((a, b) => deadline(a) - deadline(b) || a.race_id.localeCompare(b.race_id));
      lists.results.sort((a, b) => deadline(b) - deadline(a) || a.race_id.localeCompare(b.race_id));
      return lists;
    },
    venueOverview(records, {sport = "boat", now = Date.now(), favorites = []} = {}) {
      const groups = new Map((sport === "boat" ? boatVenues : []).map(venue => [venue, []]));
      for (const row of records) {
        const venue = model.venueName(row);
        if (row.sport !== sport || typeof venue !== "string" || !venue) continue;
        if (!groups.has(venue)) groups.set(venue, []);
        groups.get(venue).push(row);
      }
      const pinned = new Set(Array.isArray(favorites) ? favorites : []);
      return [...groups].map(([venue, rows]) => {
        const lists = model.raceLists(rows, {now}), settledCount = lists.results.filter(r => ["final", "settled", "void", "cancelled"].includes(r.result?.status)).length,
          heldCount = lists.results.filter(r => r.result?.status === "unsupported").length;
        return {venue, count: rows.length, favorite: pinned.has(sport + ":" + venue), nextRace: lists.upcoming[0] || null,
          upcomingCount: lists.upcoming.length, resultCount: lists.results.length, unknownCount: lists.unknown.length,
          settledCount, heldCount, pendingResultCount: lists.results.length - settledCount - heldCount};
      }).sort((a, b) => Number(b.favorite) - Number(a.favorite) || Number(b.count > 0) - Number(a.count > 0) || a.venue.localeCompare(b.venue, "ja"));
    },
    raceInformation(row = {}, {supplementalPreview = false} = {}) {
      const people = Array.isArray(row.participants) ? row.participants : [];
      const present = value => value !== null && value !== undefined && value !== "";
      const weather = row.weather || row.weather_preview;
      const preview = supplementalPreview === true || people.some(p => ["display_time", "preview_st", "preview_course", "comment", "last_comment"].some(key => present(p[key]))) ||
        weather != null && typeof weather === "object" && Object.values(weather).some(present);
      const predictions = [row.prediction, ...(Array.isArray(row.comparison_predictions) ? row.comparison_predictions : [])].filter(Boolean).length;
      const result = row.result && ["final", "settled", "void", "cancelled", "unsupported"].includes(row.result.status);
      return [
        {key: "participants", label: "出走表", available: people.length > 0, detail: people.length ? people.length + "名" : "未取得"},
        {key: "preview", label: "直前情報", available: Boolean(preview), detail: preview ? "取得項目あり" : "未取得"},
        {key: "outlook", label: "保存予想", available: predictions > 0, detail: predictions ? predictions + "原本" : "未予想"},
        {key: "history", label: "結果", available: Boolean(result), detail: result ? "結果あり" : model.racePhase(row)==="upcoming" ? "レース前" : model.racePhase(row)==="unknown" ? "締切未確認" : "結果待ち"}
      ];
    },
    boatRaceLinks(row) {
      if (!row || row.sport !== "boat" || row.scope === "synthetic" || row.synthetic === true ||
          !Number.isInteger(row.race_no) || row.race_no < 1 || row.race_no > 12 ||
          !validVenueDay(row.event_date_jst)) return [];
      const venue = boatVenues.indexOf(model.venueName(row));
      if (venue < 0) return [];
      const code = String(venue + 1).padStart(2, "0"), day = row.event_date_jst.replaceAll("-", "");
      const identity = /^(\d{8})-(\d{2})-(\d{2})$/.exec(row.race_id || "");
      if (identity && (identity[1] !== day || identity[2] !== code || Number(identity[3]) !== row.race_no)) return [];
      return [["participants", "公式出走表", "racelist"], ["preview", "公式直前情報", "beforeinfo"],
        ["odds", "公式オッズ", "odds3t"], ["history", "公式結果", "raceresult"]].map(([kind, label, page]) =>
        ({kind, label, url: "https://www.boatrace.jp/owpc/pc/race/" + page + "?" + new URLSearchParams({rno: String(row.race_no), jcd: code, hd: day})}));
    },
    boatVenueLinks(row) {
      if (!row || row.sport !== "boat") return [];
      const index = boatVenues.indexOf(model.venueName(row)); if (index < 0) return [];
      const links = [{kind: "stadium", label: "公式の会場情報・開催日程 ↗", url: "https://www.boatrace.jp/owpc/pc/site/place/stadium?jcd=" + String(index + 1).padStart(2, "0")}];
      if (validVenueDay(row.event_date_jst)) links.push({kind: "calendar", label: "選択日の公式開催一覧 ↗", url: "https://www.boatrace.jp/owpc/pc/race/index?hd=" + row.event_date_jst.replaceAll("-", "")});
      return links;
    },
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
    modelCoverage(records, catalog, {sport} = {}) {
      // Presence counts only: genuine predictions/results keep their own gates.
      const selected = records.filter(row => row.sport === sport);
      const targetRaces = new Set(selected.map(row => row.race_id)).size;
      const allPredictions = row => [row.prediction, ...(row.comparison_predictions || [])].filter(Boolean);
      const phaseNames=["P0","P1","A_PRE_TRIAL","B_POST_TRIAL","UNKNOWN"];
      const hasLegacy=selected.some(row=>allPredictions(row).some(p=>["P0","P1"].includes(p.stage)));
      const hasNative=selected.some(row=>allPredictions(row).some(p=>["A_PRE_TRIAL","B_POST_TRIAL"].includes(p.stage)));
      const declared=row=>[...(row.scheduled_stages||[]),...(row.dispatch_slots||[]).map(s=>s.stage)];
      const declaredSet=new Set(selected.flatMap(declared));
      const savedSet=new Set(selected.flatMap(row=>allPredictions(row).map(p=>p.stage)));
      const displayStages=declaredSet.size ? phaseNames.filter(p=>p!=="UNKNOWN"&&(declaredSet.has(p)||savedSet.has(p))) : sport === "autorace" ? [...(hasLegacy?["P0","P1"]:[]),...(!hasLegacy || hasNative?["A_PRE_TRIAL","B_POST_TRIAL"]:[])] : ["P0","P1"];
      const phaseTargets=Object.fromEntries(phaseNames.map(phase=>[phase,new Set(selected.filter(row=>{
        const stated=declared(row);return stated.length ? stated.includes(phase)||allPredictions(row).some(p=>p.stage===phase) : displayStages.includes(phase);
      }).map(row=>row.race_id)).size]));
      const known = new Set(catalog.map(spec => spec.model_id));
      const additional = [...new Set(selected.flatMap(allPredictions).map(p => p.model_id).filter(id => id && !known.has(id)))].sort();
      const models = catalog.map(spec => {
        const applicable = spec.applicable_sports.includes(sport), targets = applicable ? targetRaces : 0;
        const saved = new Set(), incompatible = new Set(), phaseRaces = Object.fromEntries(phaseNames.map(p=>[p,new Set()])), variants = new Map();
        for (const row of selected) for (const p of allPredictions(row)) {
          // Exact identity only. A version or alias is never inferred as a model ID.
          if (p.model_id !== spec.model_id) continue;
          if (!applicable) { incompatible.add(row.race_id); continue; }
          const stage = phaseNames.includes(p.stage) ? p.stage : "UNKNOWN";
          saved.add(row.race_id); phaseRaces[stage].add(row.race_id);
          const key = JSON.stringify([row.scope || "unknown", stage, p.model_version ?? null]);
          if (!variants.has(key)) variants.set(key, {scope: row.scope || "unknown", stage, model_version: p.model_version ?? null, raceIds: new Set()});
          variants.get(key).raceIds.add(row.race_id);
        }
        const stages = Object.fromEntries(Object.entries(phaseRaces).map(([stage, ids]) => [stage, {target_races: stage === "UNKNOWN" ? null : applicable ? phaseTargets[stage] : 0, saved_races: ids.size, missing_races: stage === "UNKNOWN" ? null : (applicable ? phaseTargets[stage] : 0) - ids.size}]));
        const versions = [...variants.values()].map(v => ({scope: v.scope, stage: v.stage, model_version: v.model_version, saved_races: v.raceIds.size}));
        return {...spec, applicable, target_races: targets, saved_races: saved.size, missing_races: targets - saved.size,
          stages, versions, inapplicable_saved_races: incompatible.size,
          state: !applicable ? "NOT_APPLICABLE" : !saved.size ? "INPUT_MISSING" : saved.size < targets ? "PARTIAL_SAVED" : "SAVED_FOR_IMPORTED_RACES"};
      });
      return {models, target_races: targetRaces, applicable_models: models.filter(m => m.applicable).length,
        display_stages: displayStages,
        not_applicable_models: models.filter(m => !m.applicable).length, additional_model_ids: additional,
        counts_only: true, scope: "IMPORTED_RACE_LEDGER_ONLY", all_models_operational: false};
    },
    filterRaces(records, {sport = "all", day = "", allDates = false, period = "day", query = "", venue = "", forecastOnly = false, candidatesOnly = false, candidateRaceIds = [], sort = "venue"} = {}) {
      const needle = query.trim().toLocaleLowerCase("ja-JP");
      let weekStart = "", weekEnd = "";
      if (day && period === "week") { const start = new Date(day + "T00:00:00Z"); start.setUTCDate(start.getUTCDate() - (start.getUTCDay() + 6) % 7); weekStart = start.toISOString().slice(0, 10); start.setUTCDate(start.getUTCDate() + 7); weekEnd = start.toISOString().slice(0, 10); }
      const rows = records.filter(r => (sport === "all" || r.sport === sport) && (allDates || !day || (period === "week" ? r.event_date_jst >= weekStart && r.event_date_jst < weekEnd : r.event_date_jst === day)) &&
        (!venue || model.venueName(r) === venue || r.venue === venue) && (!forecastOnly || !!r.prediction || !!r.comparison_predictions?.length) &&
        (!candidatesOnly || candidateRaceIds.includes(r.race_id)) &&
        (!needle || [model.venueName(r), r.venue, r.race_no + "R", r.race_id, r.prediction?.model_id, r.prediction?.model_version,
          ...(r.participants || []).flatMap(p => [model.participantName(r,p), p.name, p.registration_no, p.registration_id, p.racer_registration_id])].filter(Boolean).join(" ").toLocaleLowerCase("ja-JP").includes(needle)));
      const cutoff = r => Number.isFinite(Date.parse(r.cutoff_at)) ? Date.parse(r.cutoff_at) : Infinity;
      return rows.sort((a, b) => (sort === "time" ? cutoff(a) - cutoff(b) : (model.venueName(a) || "").localeCompare(model.venueName(b) || "", "ja") || (a.race_no ?? 0) - (b.race_no ?? 0)) || a.race_id.localeCompare(b.race_id));
    }
  };
  if (typeof module === "object" && module.exports) module.exports = model;
  else root.RaceUI = model;
})(typeof globalThis !== "undefined" ? globalThis : this);
"use strict";
/* Optional experimental sidecar. This checks format and binding, not a report seal. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports.boatVideoView = api;
  root.RaceBoatVideoView = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const phases = {turn:"ターン", exit:"出足（ターン出口）", runup:"行き足（スタート助走）", straight:"伸び（直線）"};
  const metricDefinitions = {
    window_duration:["観測区間", "s"], sampled_heading_change:["観測方向変化", "deg"],
    sampled_absolute_heading_change:["観測方向変化の絶対量", "deg"],
    sampled_path_length:["標本間の移動距離", "px"], equivalent_sampled_radius:["標本からの相当半径", "px"],
    sampled_speed_trend:["標本間速度の傾向", "px/s^2"], first_interval_speed:["最初の標本間速度", "px/s"],
    last_interval_speed:["最後の標本間速度", "px/s"], interval_speed_change:["標本間速度差", "px/s"],
    speed_trend_residual_rms:["傾向への残差 RMS", "px/s"],
    max_supplied_interval_speed_error:["申告位置誤差からの速度誤差", "px/s"],
    sampled_speed_trend_error_bound:["申告位置誤差からの傾向誤差", "px/s^2"],
    mean_interval_speed:["平均標本間速度", "px/s"], max_lateral_deviation:["最大横ずれ", "px"],
    rms_lateral_deviation:["横ずれ RMS", "px"]
  };
  const phaseMetrics = {
    turn:["window_duration", "sampled_heading_change", "sampled_absolute_heading_change", "sampled_path_length", "equivalent_sampled_radius"],
    exit:["window_duration", "sampled_speed_trend", "first_interval_speed", "last_interval_speed", "interval_speed_change", "speed_trend_residual_rms", "max_supplied_interval_speed_error", "sampled_speed_trend_error_bound"],
    runup:["window_duration", "sampled_speed_trend", "first_interval_speed", "last_interval_speed", "interval_speed_change", "speed_trend_residual_rms", "max_supplied_interval_speed_error", "sampled_speed_trend_error_bound"],
    straight:["window_duration", "mean_interval_speed", "max_lateral_deviation", "rms_lateral_deviation"]
  };
  const reasons = {PHASE_NOT_OBSERVED:"該当する走行区間を観測できず", IDENTITY_UNRESOLVED:"艇の識別が未確定",
    START_REFERENCE_REQUIRED:"スタート基準線が未設定", START_GATE_CROSSING_NOT_OBSERVED:"基準線の通過を観測できず",
    INSUFFICIENT_SAMPLES:"標本数不足", OCCLUDED_OR_INVALID_SAMPLE:"遮蔽・無効な標本あり",
    CAMERA_SCENE_CHANGE:"カメラ場面が切り替わった", SAMPLE_GAP:"標本の間隔が空いた",
    INSUFFICIENT_WINDOW_COVERAGE:"指定区間を十分に観測できず", NO_MEASURABLE_DISPLACEMENT:"移動を計測できず",
    NO_OBSERVED_TURN:"旋回を観測できず", UNRESOLVED_HEADING:"進行方向が未確定",
    STRAIGHT_AXIS_UNRESOLVED:"直線の基準方向が未確定",
    WINDOW_NOT_BEFORE_OBSERVED_START_CROSSING:"観測した基準線通過前の区間を確認できず"};
  const record = value => value !== null && typeof value === "object" && !Array.isArray(value);
  const finite = value => typeof value === "number" && Number.isFinite(value);
  const integer = (value, min = 0, max = Number.MAX_SAFE_INTEGER) => Number.isSafeInteger(value) && value >= min && value <= max;
  const short = value => typeof value === "string" && value.length > 0 && value.length <= 4096;
  const sha = value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
  function timestamp(value) {
    if (typeof value !== "string" || value.length > 50 || !/^\d{4}-\d\d-\d\dT(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(value) || !Number.isFinite(Date.parse(value))) return false;
    const day = value.slice(0, 10);
    return new Date(day + "T00:00:00Z").toISOString().slice(0, 10) === day;
  }
  const jstDay = value => new Date(Date.parse(value) + 9 * 3600000).toISOString().slice(0, 10).replaceAll("-", "");
  // Python ISO clocks retain microseconds; Date.parse alone truncates them.
  const clockValue = value => BigInt(Date.parse(value)) * 1000n + BigInt((value.match(/\.(\d+)/)?.[1] || "").padEnd(6, "0").slice(3, 6));
  function safeTree(value, depth = 0, budget = {count:0}) {
    if (depth > 24 || ++budget.count > 1500000) return false;
    if (record(value)) return Object.keys(value).length <= 1000 && Object.entries(value).every(([key, child]) => {
      if ((["model_eligible", "identity_validated", "source_authenticity_independently_verified"].includes(key) && child !== false) ||
          (key === "validation_status" && child !== "UNVALIDATED") ||
          (key === "coordinate_space" && child !== "REFERENCE_IMAGE_PX")) return false;
      return safeTree(child, depth + 1, budget);
    });
    if (Array.isArray(value)) return value.length <= 500000 && value.every(child => safeTree(child, depth + 1, budget));
    return value === null || typeof value === "boolean" || finite(value) || typeof value === "string" && value.length <= 4096;
  }
  function roster(value, view = false) {
    if (!Array.isArray(value) || value.length !== 6) return null;
    const result = new Map();
    for (const person of value) {
      if (!record(person)) return null;
      const lane = person[view ? "number" : "lane"], registration = person[view ? "registration_no" : "registration_number"];
      if (!integer(lane, 1, 6) || result.has(lane) || typeof registration !== "string" || !/^\d{4}$/.test(registration)) return null;
      result.set(lane, registration);
    }
    return new Set(result.values()).size === 6 ? result : null;
  }
  function publicPage(value, race) {
    try {
      if (typeof value !== "string" || value.length > 2048 || /\s/.test(value)) return false;
      const url = new URL(value), [day, venue, number] = race.split("-"), query = url.searchParams;
      return url.protocol === "https:" && url.host === "www.boatrace.jp" && !url.username && !url.password && !url.hash &&
        /^\/owpc\/(?:pc|sp)\/race\/[a-z]+$/.test(url.pathname) && [...query].length === 3 &&
        query.get("hd") === day && query.get("jcd") === venue && [number, String(Number(number))].includes(query.get("rno")) &&
        [...query.keys()].every(key => ["hd", "jcd", "rno"].includes(key));
    } catch { return false; }
  }
  function validate(report, row) {
    if (!record(report) || !record(row) || row.sport !== "boat" || !safeTree(report) || report.schema_version !== "RACE_AI_BOAT_VIDEO_EVALUATION_V1" ||
        !sha(report.report_sha256) || report.race_id !== row.race_id || !/^\d{8}-(?:0[1-9]|1\d|2[0-4])-(?:0[1-9]|1[0-2])$/.test(report.race_id) ||
        report.model_eligible !== false || report.validation_status !== "UNVALIDATED") return false;
    const expected = roster(row.participants, true), supplied = roster(report.roster);
    if (!expected || !supplied || [...expected].some(([lane, registration]) => supplied.get(lane) !== registration)) return false;
    if (![report.cutoff_at, row.cutoff_at, report.analysis_started_at, report.analysis_completed_at].every(timestamp) ||
        clockValue(report.cutoff_at) !== clockValue(row.cutoff_at) || jstDay(report.cutoff_at) !== report.race_id.slice(0, 8)) return false;
    for (const field of ["saved_cutoff_variants", "saved_schedule_cutoff_variants"]) {
      if (row[field] != null && (!Array.isArray(row[field]) || row[field].some(value => !timestamp(value) || clockValue(value) !== clockValue(report.cutoff_at)))) return false;
    }
    const source = report.source;
    if (!record(source) || !sha(source.media_sha256) || !timestamp(source.captured_at) ||
        jstDay(source.captured_at) < report.race_id.slice(0, 8) ||
        !Object.keys(source).every(key => ["kind", "media_sha256", "captured_at", "identity_status", "public_page_url", "source_metadata_sha256"].includes(key))) return false;
    const allowedIdentity = {OWNER_LOCAL:["OWNER_DECLARED"], OFFICIAL_BROWSER_CAPTURE:["OWNER_DECLARED", "SOURCE_METADATA_LINKED"], SYNTHETIC_TEST:["SYNTHETIC"]};
    if (!Object.hasOwn(allowedIdentity, source.kind) || !allowedIdentity[source.kind].includes(source.identity_status) ||
        source.source_metadata_sha256 != null && !sha(source.source_metadata_sha256) ||
        source.identity_status === "SOURCE_METADATA_LINKED" && !sha(source.source_metadata_sha256) ||
        source.public_page_url != null && !publicPage(source.public_page_url, report.race_id)) return false;
    const synthetic = source.kind === "SYNTHETIC_TEST";
    if (report.dataset_status !== (synthetic ? "SYNTHETIC_ONLY" : "REAL_REPORTED") || synthetic && row.scope !== "synthetic") return false;
    const captured = clockValue(source.captured_at), start = clockValue(report.analysis_started_at), end = clockValue(report.analysis_completed_at), cutoff = clockValue(report.cutoff_at);
    if (!(captured <= start && start <= end) || report.pre_cutoff_available !== (end < cutoff)) return false;
    const tracking = report.tracking, media = report.media, measurements = report.measurements;
    if (!record(tracking) || !record(media) || !record(measurements) ||
        tracking.schema_version !== "RACE_AI_BOAT_VIDEO_TRACKS_V1" || tracking.media_sha256 !== source.media_sha256 ||
        tracking.coordinate_space !== "REFERENCE_IMAGE_PX" || tracking.timeline_source !== "MEDIA_PTS" ||
        tracking.model_eligible !== false || tracking.validation_status !== "UNVALIDATED" ||
        !integer(tracking.width, 1, 16384) || !integer(tracking.height, 1, 16384) || !finite(tracking.duration_seconds) || tracking.duration_seconds < 0 ||
        !record(tracking.quality) || !record(report.analysis_parameters) ||
        media.sha256 !== source.media_sha256 || ["width", "height", "duration_seconds", "timeline_source"].some(key => media[key] !== tracking[key])) return false;
    if (tracking.quality.flags != null && (!Array.isArray(tracking.quality.flags) || tracking.quality.flags.length > 1000 || !tracking.quality.flags.every(short))) return false;
    if (!Array.isArray(tracking.tracks) || tracking.tracks.length !== 6) return false;
    const tracks = new Map(), duration = tracking.duration_seconds;
    for (const track of tracking.tracks) {
      if (!record(track) || !integer(track.lane, 1, 6) || tracks.has(track.lane) || !Array.isArray(track.samples)) return false;
      let previousTime = -1, previousFrame = -1;
      for (const sample of track.samples) {
        if (!record(sample) || typeof sample.valid !== "boolean" || !finite(sample.t) || sample.t < 0 || sample.t > duration + 1e-6 || sample.t <= previousTime ||
            !integer(sample.frame_index) || sample.frame_index <= previousFrame || !integer(sample.scene) ||
            !["x", "y"].every(key => finite(sample[key]) || sample.valid === false && sample[key] === null) ||
            sample.position_error != null && (!finite(sample.position_error) || sample.position_error < 0) ||
            sample.valid === true && Object.hasOwn(sample, "position_error") && sample.position_error === null) return false;
        previousTime = sample.t; previousFrame = sample.frame_index;
      }
      tracks.set(track.lane, track);
    }
    if (measurements.schema_version !== "RACE_AI_BOAT_VIDEO_MEASUREMENTS_V1" || measurements.coordinate_space !== "REFERENCE_IMAGE_PX" ||
        measurements.time_basis !== "MEDIA_TIMELINE_SECONDS" || measurements.model_eligible !== false || measurements.validation_status !== "UNVALIDATED" ||
        measurements.identity_validated !== false || measurements.candidate_measurements !== true || measurements.calibration_status !== "IMAGE_COORDINATES_ONLY" ||
        measurements.physical_velocity !== "NOT_ESTABLISHED" || !Array.isArray(measurements.lanes) || measurements.lanes.length !== 6) return false;
    const seen = new Set();
    for (const lane of measurements.lanes) {
      if (!record(lane) || !tracks.has(lane.lane) || seen.has(lane.lane) || lane.identity_validated !== false || !record(lane.phases) ||
          Object.keys(lane.phases).length !== 4 || !Object.keys(phases).every(key => Object.hasOwn(lane.phases, key))) return false;
      seen.add(lane.lane);
      const track = tracks.get(lane.lane), identity = ["COLOR_CANDIDATE", "NUMBER_COLOR_AGREEMENT", "NUMBER_TEMPORAL_CANDIDATE", "REVIEWED"].includes(track.identity_status) ? track.identity_status : "UNRESOLVED";
      if (lane.identity_status !== identity) return false;
      for (const [name, phase] of Object.entries(lane.phases)) {
        if (!record(phase) || !["MISSING", "MEASURED"].includes(phase.status) || phase.validation_status !== "UNVALIDATED" ||
            phase.identity_validated !== false || !integer(phase.sample_count) || !short(phase.window_source) || !Array.isArray(phase.metrics)) return false;
        if (Object.hasOwn(phase, "gate_crossing_frame_indices") || Object.hasOwn(phase, "gate_crossing_t") || name === "runup" && phase.status === "MEASURED") {
          const indices = phase.gate_crossing_frame_indices, crossing = phase.gate_crossing_t;
          if (name !== "runup" || phase.status !== "MEASURED" || !Array.isArray(indices) || indices.length !== 2 ||
              !indices.every(value => integer(value)) || indices[0] >= indices[1] || !finite(crossing) || crossing < phase.t_end || crossing > duration) return false;
          const first = track.samples.find(sample => sample.frame_index === indices[0]), last = track.samples.find(sample => sample.frame_index === indices[1]);
          if (!first || !last || !first.valid || !last.valid || first.scene !== last.scene || !(first.t <= crossing && crossing <= last.t)) return false;
        }
        if (phase.status === "MISSING") {
          if (!short(phase.reason) || !/^[A-Z0-9_]+$/.test(phase.reason) || phase.metrics.length) return false;
          if (phase.t_start !== null || phase.t_end !== null) {
            if (!finite(phase.t_start) || !finite(phase.t_end) || phase.t_start < 0 || phase.t_start > phase.t_end || phase.t_end > duration + 1e-6) return false;
          }
          continue;
        }
        if (identity === "UNRESOLVED" || phase.reason !== null || phase.sample_count < 3 || !finite(phase.t_start) || !finite(phase.t_end) ||
            !(0 <= phase.t_start && phase.t_start < phase.t_end && phase.t_end <= duration + 1e-6) || !integer(phase.scene)) return false;
        const samples = track.samples.filter(sample => sample.t >= phase.t_start - 1e-12 && sample.t <= phase.t_end + 1e-12);
        if (samples.length !== phase.sample_count || samples.some(sample => !sample.valid || sample.scene !== phase.scene) ||
            samples[0].t !== phase.t_start || samples.at(-1).t !== phase.t_end) return false;
        const names = new Set();
        for (const metric of phase.metrics) {
          if (!record(metric) || !Object.hasOwn(metricDefinitions, metric.name) || !phaseMetrics[name].includes(metric.name) || names.has(metric.name) ||
              !finite(metric.value) || metric.unit !== metricDefinitions[metric.name][1]) return false;
          names.add(metric.name);
        }
        if (!phaseMetrics[name].slice(0, name === "turn" || name === "straight" ? undefined : 6).every(key => names.has(key))) return false;
        const elapsed = phase.metrics.find(metric => metric.name === "window_duration").value;
        if (Math.abs(elapsed - (phase.t_end - phase.t_start)) > 1e-9) return false;
      }
    }
    return true;
  }
  function validateReport(report, row) {
    try { return validate(report, row); } catch { return false; }
  }
  function createPanel(row, document = globalThis.document) {
    if (row?.sport !== "boat" || row.boat_video_evaluations == null || Array.isArray(row.boat_video_evaluations) && !row.boat_video_evaluations.length) return null;
    const make = (tag, content, cls) => { const element = document.createElement(tag); if (content !== undefined) element.textContent = String(content); if (cls) element.className = cls; return element; };
    const panel = make("section"); panel.id = "boat-video-evaluations";
    panel.append(make("h2", "映像の実験計測", "member-heading"), make("p", "未検証の実験計測。本番予想への採用は未実施。研究版への使用状況はモデル版・入力証拠を確認してください。画像上の標本と動画時刻による候補計測です。実際の速さ・加速度や艇の強さを確定する値ではありません。", "notice"));
    const reports = row.boat_video_evaluations;
    if (!Array.isArray(reports) || reports.length > 100 || reports.some(report => !validateReport(report, row))) {
      panel.append(make("p", "映像の実験計測を照合できません。形式・艇番と登録番号・取得時刻・締切の記録を確認してください。", "notice")); return panel;
    }
    const stamp = value => new Intl.DateTimeFormat("ja-JP", {timeZone:"Asia/Tokyo", year:"numeric", month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", second:"2-digit", hour12:false}).format(new Date(value));
    const facts = fields => {
      const list = make("dl", undefined, "provenance");
      fields.forEach(([label, value]) => list.append(make("dt", label), make("dd", value == null ? "未取得" : value))); return list;
    };
    const number = value => Number(value.toPrecision(6)).toString();
    for (const report of reports) {
      const details = make("details"), source = report.source, quality = report.tracking.quality;
      const sourceLabel = {OWNER_LOCAL:"所有者のローカル映像（申告）", OFFICIAL_BROWSER_CAPTURE:"公式ページに関連付けた保存映像（申告）", SYNTHETIC_TEST:"合成テスト映像"}[source.kind];
      details.append(make("summary", sourceLabel + " · " + (report.pre_cutoff_available ? "締切前に解析完了（時刻は申告値）" : "締切以後の取得・解析を含む") + " · 詳細"),
        make("p", "形式照合のみ。報告SHAの本文照合、出典・取得日時・艇の識別の独立検証は未実施です。COLOR_CANDIDATE は色による艇番候補です。NUMBER_TEMPORAL_CANDIDATE は数字の反復観測と時系列の追跡による艇番候補です。画像 px・動画の秒を使い、物理的な速度・瞬間加速度へ換算しません。", "muted small"),
        facts([["報告SHA（記録値）", report.report_sha256], ["映像SHA（記録値）", source.media_sha256],
          ["取得 JST（申告）", stamp(source.captured_at)], ["解析開始 JST", stamp(report.analysis_started_at)],
          ["解析完了 JST", stamp(report.analysis_completed_at)], ["照合した締切 JST", stamp(report.cutoff_at)],
          ["出典の関連付け", source.identity_status], ["公開ページURL（記録値）", source.public_page_url],
          ["出典メタデータSHA", source.source_metadata_sha256],
          ["映像の寸法・長さ", report.media.width + " × " + report.media.height + " px / " + number(report.media.duration_seconds) + " s"],
          ["時刻の基準", "MEDIA_PTS / MEDIA_TIMELINE_SECONDS（実時間との対応は未検証）"],
          ["画質・追跡の注意", Array.isArray(quality.flags) && quality.flags.length ? quality.flags.join(" / ") : "未取得"],
          ["復号フレーム数", integer(quality.decoded_frame_count) ? quality.decoded_frame_count : null],
          ["位置誤差の範囲", typeof quality.position_error_scope === "string" ? quality.position_error_scope : null],
          ["カメラ推定の記録数", Array.isArray(quality.camera_estimates) ? quality.camera_estimates.length : null]]));
      for (const lane of report.measurements.lanes) {
        const laneDetails = make("details");
        laneDetails.append(make("summary", lane.lane + "号艇 / 登録 " + report.roster.find(person => person.lane === lane.lane).registration_number + " · " + lane.identity_status + "（艇の識別は未検証）"));
        const scroll = make("div", undefined, "table-scroll"), table = make("table"), header = make("tr"), body = make("tbody");
        ["走行区間", "画像上の候補計測・欠測理由", "証拠区間・フレーム"].forEach(label => header.append(make("th", label)));
        for (const [name, label] of Object.entries(phases)) {
          const phase = lane.phases[name], tr = make("tr"), value = make("td"), evidence = make("td");
          if (phase.status === "MISSING") value.textContent = "欠測: " + (reasons[phase.reason] || "計測条件を満たさず") + "（" + phase.reason + "）";
          else for (const metric of phase.metrics) value.append(make("p", metricDefinitions[metric.name][0] + ": " + number(metric.value) + " " + metric.unit));
          const track = report.tracking.tracks.find(item => item.lane === lane.lane);
          const samples = phase.t_start == null ? [] : track.samples.filter(sample => sample.t >= phase.t_start - 1e-12 && sample.t <= phase.t_end + 1e-12);
          evidence.append(make("p", "標本 " + phase.sample_count + " / " + phase.window_source));
          if (phase.t_start != null) evidence.append(make("p", number(phase.t_start) + "–" + number(phase.t_end) + " s"));
          if (samples.length) evidence.append(make("p", "フレーム: " + samples.slice(0, 16).map(sample => sample.frame_index).join(", ") + (samples.length > 16 ? " …（全" + samples.length + "件）" : "")));
          if (Array.isArray(phase.gate_crossing_frame_indices)) evidence.append(make("p", "基準線の通過フレーム: " + phase.gate_crossing_frame_indices.join(", ")));
          tr.append(make("th", label), value, evidence); body.append(tr);
        }
        const head = make("thead"); head.append(header); table.append(head, body); scroll.append(table); laneDetails.append(scroll); details.append(laneDetails);
      }
      panel.append(details);
    }
    return panel;
  }
  return {validateReport, createPanel};
});
