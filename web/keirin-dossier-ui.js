/* Presentation for the checked public KEIRIN rider dossier. */
(() => {
  "use strict";
  const axes = ["先行力", "捲り", "瞬発力", "差し", "戦術対応力", "現在の調子"];
  const fields = ["back_count", "makuri_count", null, "difference_count", null, null];
  const observations = ["最終バック先頭", "捲りの掲載", "", "差しの掲載", "", ""];
  const styles = { 逃: "先行型", 追: "追込型", 両: "自在型" };
  const percent = ratio => (ratio * 100).toFixed(1) + "%";
  const numeric = value => Number.isSafeInteger(value) && value >= 0;
  const jst = new Intl.DateTimeFormat("ja-JP", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Tokyo" });
  const stamp = clock => jst.format(new Date(clock)) + " JST";

  function node(tag, className, content) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (content !== undefined) element.textContent = content;
    return element;
  }

  function svg(tag, fields) {
    const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [key, value] of Object.entries(fields)) element.setAttribute(key, value);
    return element;
  }

  function badge(rider) {
    return node("span", "kd-car kd-car-" + rider.number, String(rider.number));
  }

  function radarScale(statsRows) {
    return Math.max(5, Math.ceil(Math.max(0, ...statsRows.flatMap(stats => fields.map(field => {
      const value = field && stats?.[field];
      return numeric(value) ? value : 0;
    }))) / 5) * 5);
  }

  function radar(stats, scale, form, agari) {
    const section = node("section", "kd-section");
    section.append(node("h3", "", "能力分析"));
    const chart = svg("svg", { viewBox: "0 0 360 264", role: "img", "aria-label": axes.join("、") + "のレーダー" });
    const at = (i, radius) => [180 + radius * Math.sin(i * Math.PI / 3), 131 - radius * Math.cos(i * Math.PI / 3)];
    const points = (radius) => axes.map((_, i) => at(i, radius).join(",")).join(" ");
    for (const fraction of [.25, .5, .75, 1]) chart.append(svg("polygon", { points: points(88 * fraction), class: "kd-radar-grid" }));
    const facts = node("dl", "kd-ability-facts");
    axes.forEach((label, i) => {
      const [x2, y2] = at(i, 88), [x, y] = at(i, 111);
      chart.append(svg("line", { x1: 180, y1: 131, x2, y2, class: "kd-radar-grid" }));
      const text = svg("text", { x, y: y + 4, "text-anchor": i === 0 || i === 3 ? "middle" : i < 3 ? "start" : "end" });
      text.textContent = label;
      chart.append(text);
      const count = fields[i] ? stats?.[fields[i]] : null;
      const recent = i === 5 && form, sprint = i === 2 && agari;
      const fraction = recent ? recent.numerator / recent.denominator :
        sprint ? sprint.percentile : numeric(count) ? count / scale : null;
      const value = recent ? "直近の3着以内 " + percent(fraction) + "（" + recent.numerator + "/" + recent.denominator + "走）" :
        sprint ? "上がりの同走者比較 " + percent(fraction) + "（" + sprint.runs + "走）" :
          numeric(count) ? observations[i] + " " + count + "回" : "0件";
      if (fraction !== null) {
        const [cx, cy] = at(i, 88 * fraction);
        const dot = svg("circle", { cx, cy, r: 4.5, class: "kd-radar-point", "data-evidence-point": "" });
        const title = svg("title", {});
        title.textContent = value;
        dot.append(title);
        chart.append(dot);
      }
      const item = node("div");
      item.append(node("dt", "", label), node("dd", "", value));
      facts.append(item);
    });
    section.append(chart, node("p", "kd-note", "出走表の掲載回数を参照。外枠はこのレースで共通の " + scale + "回です。"), facts);
    if (agari) section.append(node("p", "kd-note", "瞬発力の参考は同じレースで上がりが速かった割合。同タイムは半分、外枠が100%。" +
      "対象 " + agari.startDay + "〜" + agari.endDay + "、" + agari.runs + "走・" + agari.peers + "比較。"));
    if (form) section.append(node("p", "kd-note", "調子の目安は直近30日以内に確認できた着順。外枠が100%。" +
      "対象 " + form.startDay + "〜" + form.endDay + "、" + form.denominator + "走。"));
    return section;
  }

  function metric(label, value, caption) {
    const box = node("div", "kd-metric");
    box.append(node("span", "", label), node("strong", "", value));
    if (caption) box.append(node("small", "", caption));
    return box;
  }

  function sourceLink(label, url, at) {
    const text = node("p", "kd-note");
    const link = node("a", "", label);
    link.href = url;
    text.append(link, " · " + stamp(at) + " に確認");
    return text;
  }

  function recordedRates(rider, day, venue) {
    const section = node("section", "kd-section");
    const metrics = node("div", "kd-metrics");
    const semi = rider.semi;
    const start = new Date(day + "T00:00:00Z");
    const previousDay = new Date(start.getTime() - 86400000).toISOString().slice(0, 10);
    start.setUTCFullYear(start.getUTCFullYear() - 1);
    const annual = semi?.sourceUrl || (semi && start.toISOString().slice(0, 10) === semi.startDay && previousDay === semi.endDay);
    metrics.append(metric(semi && !annual ? "準決勝3連対率（収録分）" : "年間準決勝3連対率",
      semi ? percent(semi.numerator / semi.denominator) : percent(0),
      semi ? semi.numerator + "/" + semi.denominator + "走" +
        (semi.startDay ? " · " + semi.startDay + "〜" + semi.endDay : "") : "0走"));
    const venueRate = rider.venue;
    metrics.append(metric(venue + (venueRate?.startDay ? "3連対率（収録分）" : "5年間3連対率"),
      venueRate ? percent(venueRate.numerator / venueRate.denominator) : percent(0),
      venueRate ? venueRate.numerator + "/" + venueRate.denominator + "走" +
        (venueRate.startDay ? " · " + venueRate.startDay + "〜" + venueRate.endDay : "") : "0走"));
    section.append(metrics);
    const sources = new Map([semi, venueRate].filter(rate => rate?.sourceUrl).map(rate => [rate.sourceUrl, rate]));
    for (const [url, rate] of sources) {
      const label = rate.afterCutoff ? "Kドリームスの締切後確認資料" : "Kドリームスの出走表成績";
      section.append(sourceLink(label, url, rate.sourceAt));
    }
    return section;
  }

  function recordedFinishes(rider, day, actual) {
    const section = node("section", "kd-section");
    if (actual) section.append(metric("このレースの確定着順", actual + "着"));
    if (rider.history) {
      const {counts, startDay, endDay} = rider.history;
      const n = counts.reduce((total, value) => total + value, 0), top3 = counts[0] + counts[1] + counts[2];
      const earliest = new Date((endDay > day ? endDay : day) + "T00:00:00Z");
      earliest.setUTCFullYear(earliest.getUTCFullYear() - 3);
      const title = startDay >= earliest.toISOString().slice(0, 10) ? "過去3年の収録成績" : "固定期間の収録成績";
      section.append(node("h3", "", title),
        node("p", "kd-note", startDay + "〜" + endDay + " · 確認 " + n + "走"),
        node("p", "", "1着 " + counts[0] + "走 · 3着以内 " + top3 + "走（" + percent(top3 / n) + "）"));
    }
    if (rider.techniques) {
      const {counts, startDay, endDay} = rider.techniques;
      const labels = {escape:"逃げ", makuri:"捲り", difference:"差し", mark:"マーク"};
      const methods = Object.entries(labels).filter(([key]) => counts[key]).map(([key, label]) => label + counts[key] + "回");
      section.append(node("h3", "", "1・2着の決まり手"),
        node("p", "", methods.join(" · ")),
        node("p", "kd-note", "掲載のある記録 " + startDay + "〜" + endDay));
    }
    section.append(node("h3", "", "直近着順（収録分・新しい順）"));
    const recent = node("ul", "kd-recents");
    for (const row of (rider.recent || []).slice(0, 10)) {
      const label = row.rank ? row.rank + "着" : row.counts.map((n, i) => n ? (i + 1) + "着" + n + "回" : "").filter(Boolean).join("・") + "（同日）";
      recent.append(node("li", "", row.day.slice(5).replace("-", "/") + " " + label));
    }
    section.append(recent.childElementCount ? recent : node("p", "kd-note", "0走"));
    return section;
  }

  function ranks(rank) {
    const section = node("section", "kd-section");
    section.append(node("h3", "", "今回のレースでの着順予測"));
    if (!rank) {
      section.append(node("p", "kd-note", "未算出"));
      return section;
    }
    const p = rank.probabilities, grouped = node("div", "kd-metrics kd-metrics-three"), rows = node("ol", "kd-ranks");
    ["1着確率", "2着以内", "3着以内"].forEach((label, index) =>
      grouped.append(metric(label, percent(p.slice(0, index + 1).reduce((sum, value) => sum + value, 0)))));
    const largest = Math.max(...p);
    for (const [i, value] of p.entries()) {
      const li = node("li", Math.abs(value - largest) < 1e-12 ? "kd-rank-peak" : "");
      const meter = node("meter");
      meter.max = 1; meter.value = value;
      meter.setAttribute("aria-label", (i + 1) + "着の確率");
      li.append(node("span", "", (i + 1) + "着"), meter, node("span", "", percent(value)));
      rows.append(li);
    }
    section.append(grouped, rows, node("p", "kd-note", "比較Bの締切前研究予測。全員完走・同着なしの条件。確率校正の検証前。"),
      node("p", "kd-note", "予想の保存 " + stamp(rank.frozenAt) + " ／ 独立確認 " + stamp(rank.witnessedAt)));
    return section;
  }

  function analysis(rider, riders) {
    const section = node("section", "kd-section"), comment = rider.comment, tactics = rider.tactics;
    if (comment) {
      const follow = comment.targetCar && riders.find(p => p.number === comment.targetCar);
      section.append(node("h3", "", "本人コメントの要旨"),
        node("p", "", comment.summary + (follow ? " 対象 " + follow.number + "番 " + follow.name : "")));
      if (comment.url) section.append(sourceLink("本人コメントの出典", comment.url, comment.at));
      else if (comment.at) section.append(node("p", "kd-note", "コメント確認 " + stamp(comment.at)));
    }
    if (tactics) {
      section.append(node("h3", "", "今回の戦術分析"));
      const phases = ["初周", "打鐘", "最終ホーム", "最終バック", "最終4コーナー", "ゴール"];
      tactics.positions.forEach((course, index) => {
        const steps = phases.flatMap((phase, i) => Number.isInteger(course?.[i]) ? [phase + " " + course[i] + "番手"] : []);
        if (steps.length) section.append(node("p", "", "保存Bの展開 " + (index + 1) + "　" + steps.join(" → ")));
      });
      for (const reason of tactics.reasons) section.append(node("p", "kd-note", reason));
      section.append(node("p", "kd-note", "戦術の保存 " + stamp(tactics.savedAt)));
    }
    const p = rider.rank?.probabilities;
    if (p) {
      const peak = Math.max(...p), modes = p.flatMap((x, n) => Math.abs(x - peak) < 1e-12 ? [n + 1] : []);
      const expected = p.reduce((sum, value, i) => sum + value * (i + 1), 0);
      section.append(node("h3", "", "予想着順評価"),
        node("p", "", "最頻 " + modes.join("・") + "着 · 期待着順 " + expected.toFixed(2) + "着"));
    }
    return section;
  }

  function showRiders(container, data, day, venue) {
    const list = node("ul", "kd-riders"), detail = node("div", "kd-detail");
    list.setAttribute("aria-label", "出走選手");
    detail.id = "keirin-dossier-selected";
    const riders = data.riders, buttons = [];
    const scale = radarScale(riders.map(rider => rider.stats));
    let selected = 0, results = new Map(), newest = new Map();
    const current = node("div");
    current.setAttribute("aria-live", "polite");
    function showFinishes() {
      const rider = riders[selected], update = newest.get(rider.number);
      current.replaceChildren(recordedFinishes({...rider, ...update}, day, results.get(rider.number)));
    }
    function select(index) {
      selected = index;
      buttons.forEach((button, i) => button.setAttribute("aria-pressed", String(i === index)));
      const rider = riders[index], heading = node("header", "kd-selected");
      const identity = node("div");
      identity.append(node("h2", "", rider.name));
      if (rider.style) identity.append(node("p", "kd-note", styles[rider.style]));
      if (rider.registration) identity.append(node("p", "kd-note", "登録番号 " + rider.registration +
        (rider.registrationBasis ? " · " + rider.registrationBasis : "")));
      heading.append(badge(rider), identity);
      const stats = rider.stats;
      if (stats?.competition_points != null) heading.append(node("p", "kd-note", "競走得点 " + stats.competition_points));
      const tactics = analysis(rider, riders);
      detail.replaceChildren(heading, recordedRates(rider, day, venue), current, radar(stats, scale, rider.form, rider.agari), ranks(rider.rank));
      if (tactics.childElementCount) detail.append(tactics);
      showFinishes();
      if (stats?.sourceAt) {
        const provider = stats.source === "official" ? "KEIRIN.JP" : "Kドリームス";
        const timing = stats.source === "archive" || (data.cutoffAt && Date.parse(stats.sourceAt) >= Date.parse(data.cutoffAt)) ?
          " 出走表の締切後確認 " : " 出走表の確認 ";
        detail.append(node("p", "kd-note", provider + timing + stamp(stats.sourceAt)));
      }
    }
    riders.forEach((rider, i) => {
      const row = node("li"), button = node("button", "kd-rider-button");
      button.type = "button";
      button.setAttribute("aria-controls", detail.id);
      button.append(badge(rider), node("strong", "", rider.name), node("span", "kd-style", styles[rider.style] || ""));
      button.addEventListener("click", () => select(i));
      buttons.push(button);
      row.append(button); list.append(row);
    });
    const attribution = data.rosterSource ? [sourceLink("Kドリームスの公開出走表", data.rosterSource.url, data.rosterSource.at)] : [];
    container.replaceChildren(...attribution, list, detail);
    select(0);
    return ({history, finishes}) => {
      if (history) newest = history;
      if (finishes) results = finishes;
      if (history || finishes) showFinishes();
    };
  }

  async function open({ raceId, title, day, venue, opener, load, refresh }) {
    if (document.getElementById("keirin-dossier-dialog")) return;
    const dialog = node("dialog", "kd-dialog");
    dialog.id = "keirin-dossier-dialog";
    const header = node("header", "kd-header"), heading = node("h2", "", title), close = node("button", "", "閉じる");
    heading.id = "keirin-dossier-title";
    dialog.setAttribute("aria-labelledby", heading.id);
    close.type = "button"; close.autofocus = true;
    close.addEventListener("click", () => dialog.close());
    header.append(heading, close);
    const body = node("div", "kd-body");
    body.append(node("p", "kd-note", "出走表と選手の資料を読み込んでいます。"));
    body.setAttribute("aria-busy", "true");
    dialog.append(header, body);
    const request = new AbortController();
    const timeout = setTimeout(() => request.abort(), 15000);
    let interval, updateRequest;
    dialog.addEventListener("close", () => {
      request.abort(); clearTimeout(timeout); clearInterval(interval); updateRequest?.abort(); dialog.remove();
      const target = opener?.isConnected ? opener : document.querySelector('[data-keirin-dossier="' + raceId + '"]');
      (target || document.getElementById("keirin-public-title"))?.focus({preventScroll: true});
    }, { once: true });
    document.body.append(dialog);
    dialog.showModal();
    try {
      const data = await load(request);
      if (!dialog.open) return;
      if (data?.riders.length) {
        const apply = showRiders(body, data, day, venue);
        if (refresh) {
          const check = async () => {
            if (!dialog.open || document.hidden || updateRequest) return;
            const source = updateRequest = new AbortController();
            const timeout = setTimeout(() => source.abort(), 15000);
            try {
              await refresh(data, source, update => {
                if (dialog.open && !source.signal.aborted) apply(update);
              });
            } catch {
              // Keep the last confirmed result visible when GitHub is temporarily unavailable.
            } finally {
              clearTimeout(timeout);
              updateRequest = null;
            }
          };
          interval = setInterval(check, 60_000);
          void check();
        }
      } else body.replaceChildren(node("p", "kd-note", "出走者未掲載"));
    } catch {
      if (dialog.open) body.replaceChildren(node("p", "kd-note", "選手の公開資料を取得できませんでした。"));
    } finally {
      clearTimeout(timeout);
      body.setAttribute("aria-busy", "false");
    }
  }

  globalThis.RaceKeirinDossier = { open, radar, radarScale };
})();
