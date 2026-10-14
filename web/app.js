"use strict";
// No fetch, analytics, remote API calls, or local persistence.
// This reader deliberately does NOT generate predictions or claim official verification.
(() => {
  const el = (id) => document.getElementById(id);
  const sports = Array.from(document.querySelectorAll("[data-sport]"));
  const sportNames = { horse: "競馬", cycle: "競輪", auto: "オートレース" };
  let report = null;
  const pages = ["home","races","detail","picks","results","research"];
  function showPage(page) {
    if (!pages.includes(page)) return;
    document.querySelectorAll("[data-page]").forEach(button => {
      const active = button.dataset.page === page;
      button.classList.toggle("active", active);
      if (active) button.setAttribute("aria-current","page");
      else button.removeAttribute("aria-current");
    });
    el("dashboard-home").hidden = page !== "home";
    for (const name of ["picks","results","research"]) el("page-" + name).hidden = page !== name;
    el("data-pages").hidden = page !== "races" && page !== "detail";
  }
  document.querySelectorAll("[data-page]").forEach(button => button.addEventListener("click", () => showPage(button.dataset.page)));
  document.querySelectorAll("[data-goto]").forEach(button => button.addEventListener("click", () => showPage(button.dataset.goto)));


  function pickSport(sport) {
    const isBoat = sport === "boat";
    sports.forEach((b) => {
      const active = b.dataset.sport === sport;
      b.classList.toggle("active", active);
      b.setAttribute("aria-pressed", String(active));
    });
    el("boat-view").hidden = !isBoat;
    el("coming").hidden = isBoat;
    if (!isBoat) el("coming-title").textContent = sportNames[sport] + " · Coming soon...";
  }

  sports.forEach((button) => button.addEventListener("click", () => pickSport(button.dataset.sport)));
  el("return-boat").addEventListener("click", () => pickSport("boat"));

  function asText(v) {
    if (v === null || v === undefined || v === "") return "未取得";
    if (typeof v === "number") return Number.isFinite(v) ? String(v) : "未取得";
    if (typeof v === "string") return v.slice(0, 100);
    return "未取得";
  }

  function dateWithZone(value) {
    if (typeof value !== "string" || !/T.*(Z|[+-][0-9]{2}:[0-9]{2})$/.test(value)) return false;
    return Number.isFinite(Date.parse(value));
  }

  function validate(raw) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("JSONの形式が正しくありません。");
    if (typeof raw.date_jst !== "string" || !/^\d{4}-\d\d-\d\d$/.test(raw.date_jst)
        || !Number.isFinite(Date.parse(raw.date_jst + "T00:00:00Z"))) throw new Error("対象日が不正です。");
    if (!dateWithZone(raw.first_observed_at)) throw new Error("初回確認時刻に時差情報がありません。");
    if (typeof raw.source_url !== "string" || !raw.source_url.startsWith("https://")
        || !/^[a-f0-9]{64}$/.test(raw.source_sha256 || "")) throw new Error("取得元の証拠情報が不足しています。");
    if (!Array.isArray(raw.venues) || raw.venues.length < 1 || raw.venues.length > 24) throw new Error("開催場データが不正です。");
    const venueCodes = new Set();
    let count = 0;
    let complete = 0;
    for (const venue of raw.venues) {
      if (!venue || !/^(0[1-9]|1[0-9]|2[0-4])$/.test(venue.venue || "")
          || venueCodes.has(venue.venue) || !Array.isArray(venue.races)
          || venue.races.length < 1 || venue.races.length > 12) throw new Error("開催場・レース一覧に矛盾があります。");
      venueCodes.add(venue.venue);
      const raceIds = new Set();
      for (const race of venue.races) {
        const match = typeof race.race_id === "string"
          && race.race_id.match(/^(\d{8})-(\d{2})-(0[1-9]|1[0-2])$/);
        if (!match || match[1] !== raw.date_jst.replaceAll("-", "")
          || match[2] !== venue.venue || raceIds.has(race.race_id)
          || !Array.isArray(race.boats) || race.boats.length < 1 || race.boats.length > 6)
          throw new Error("レース識別子または艇数が不正です。");
        raceIds.add(race.race_id);
        const lanes = new Set();
        for (const boat of race.boats) {
          if (!boat || !Number.isInteger(boat.lane) || boat.lane < 1 || boat.lane > 6
            || lanes.has(boat.lane)
            || !/^\d{4}$/.test(boat.racer_registration_id || "")
            || !Number.isInteger(boat.motor_no) || boat.motor_no < 1 || boat.motor_no > 999)
            throw new Error("艇・選手・モーターの記録が不正です。");
          lanes.add(boat.lane);
        }
        count += 1;
        if (race.boats.length === 6) complete += 1;
      }
    }
    if (raw.races !== undefined && raw.races !== count) throw new Error("レース総数に矛盾があります。");
    if (raw.complete_six_boat_races !== undefined && raw.complete_six_boat_races !== complete)
      throw new Error("6艇の集計値に矛盾があります。");
    return { raw, count, complete };
  }

  function addOption(select, value, label) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    select.append(option);
  }

  function clearStats() {
    ["venues-total", "races-total", "complete-total"].forEach((id) => { el(id).textContent = "―"; });
    el("home-venues").textContent = "未取得";
    el("home-races").textContent = "未取得";
    el("source-state").textContent = "データ未取得";
    el("source-state").classList.remove("warning");
    el("source-date").textContent = "対象日：未取得";
    el("source-time").textContent = "初回確認時刻：未取得";
    el("race-meta").textContent = "データを選択すると、登録番号・モーター・展示情報を表示します。";
    for (const id of ["venue-select", "race-select"]) {
      el(id).replaceChildren();
      el(id).disabled = true;
      addOption(el(id), "", "データ未取得");
    }
    emptyRow("レース未選択");
  }

  function emptyRow(message) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 6;
    cell.className = "empty";
    cell.textContent = message;
    row.append(cell);
    el("racers-body").replaceChildren(row);
  }

  function putRow(boat) {
    const row = document.createElement("tr");
    const name = asText(boat.name);
    const fields = [
      boat.lane + "号艇",
      name === "未取得" ? String(boat.racer_registration_id) : name + "（" + boat.racer_registration_id + "）",
      asText(boat.motor_no),
      asText(boat.average_st),
      asText(boat.display_time),
      asText(boat.preview_course)
    ];
    fields.forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    });
    return row;
  }

  function renderRace() {
    const venue = report?.venues.find((v) => v.venue === el("venue-select").value);
    const race = venue?.races.find((r) => r.race_id === el("race-select").value);
    if (!race) { emptyRow("レース未選択"); return; }
    const number = Number(race.race_id.slice(-2));
    el("race-meta").textContent = "場コード " + venue.venue + " · " + number + "R · 締切時刻 " + asText(race.closed_at) +
      " · 展示 " + (race.preview_available ? "情報あり（取得時点は原本で要確認）" : "未取得");
    el("racers-body").replaceChildren(...race.boats.slice().sort((a, b) => a.lane - b.lane).map(putRow));
  }

  function updateRaceChoices() {
    const venue = report?.venues.find((v) => v.venue === el("venue-select").value);
    const select = el("race-select");
    select.replaceChildren();
    if (!venue) {
      select.disabled = true;
      addOption(select, "", "開催場を選択");
      emptyRow("レース未選択");
      return;
    }
    for (const r of venue.races) addOption(select, r.race_id, Number(r.race_id.slice(-2)) + "R");
    select.disabled = false;
    renderRace();
  }
  el("venue-select").addEventListener("change", updateRaceChoices);
  el("race-select").addEventListener("change", renderRace);

  function showReport(data) {
    report = data;
    el("file-message").classList.remove("error");
    el("file-message").textContent = "端末内で読み込みました。データはサーバーへ送信していません。";
    el("source-state").textContent = "非公式／原本未独立検証";
    el("source-state").classList.add("warning");
    el("source-date").textContent = "対象日：" + data.date_jst;
    el("source-time").textContent = "初回確認時刻：" + data.first_observed_at;
    el("venues-total").textContent = String(data.venues.length);
    el("races-total").textContent = String(data.races);
    el("complete-total").textContent = String(data.complete_six_boat_races);
    el("home-venues").textContent = String(data.venues.length);
    el("home-races").textContent = String(data.races);
    const select = el("venue-select");
    select.replaceChildren();
    for (const v of data.venues) addOption(select, v.venue, "場コード " + v.venue);
    select.disabled = false;
    updateRaceChoices();
  }

  el("race-file").addEventListener("change", async (event) => {
    report = null;
    clearStats();
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      if (file.size > 6_000_000) throw new Error("6MBを超えるファイルは読み取れません。");
      if (!/\.json$/i.test(file.name)) throw new Error("JSONファイルを選択してください。");
      const json = JSON.parse(await file.text());
      const checked = validate(json);
      showReport({ ...checked.raw, races: checked.count, complete_six_boat_races: checked.complete });
    } catch (error) {
      report = null;
      clearStats();
      el("file-message").textContent = "読み込みを停止しました：" + (error instanceof Error ? error.message : "形式不明");
      el("file-message").classList.add("error");
    }
  });
  clearStats();
  showPage("home");
})();