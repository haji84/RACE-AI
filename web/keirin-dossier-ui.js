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

  function radar(stats, scale) {
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
      const value = numeric(count) ? observations[i] + " " + count + "回" : "観測資料待ち";
      if (numeric(count)) {
        const [cx, cy] = at(i, 88 * count / scale);
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

  function history(rider, day, venue) {
    const section = node("section", "kd-section");
    const metrics = node("div", "kd-metrics");
    const semi = rider.semi;
    const start = new Date(day + "T00:00:00Z");
    const previousDay = new Date(start.getTime() - 86400000).toISOString().slice(0, 10);
    start.setUTCFullYear(start.getUTCFullYear() - 1);
    const annual = semi?.sourceUrl || (semi && start.toISOString().slice(0, 10) === semi.startDay && previousDay === semi.endDay);
    metrics.append(metric(semi && !annual ? "準決勝3連対率（収録分）" : "年間準決勝3連対率",
      semi ? percent(semi.numerator / semi.denominator) : "資料待ち",
      semi && semi.numerator + "/" + semi.denominator + "走" +
        (semi.startDay ? " · " + semi.startDay + "〜" + semi.endDay : "")));
    const venueRate = rider.venue;
    metrics.append(metric(venue + "5年間3連対率", venueRate ? percent(venueRate.numerator / venueRate.denominator) : "資料待ち",
      venueRate && venueRate.numerator + "/" + venueRate.denominator + "走"));
    section.append(metrics);
    const sources = new Map([semi, venueRate].filter(rate => rate?.sourceUrl).map(rate => [rate.sourceUrl, rate]));
    for (const [url, rate] of sources) {
      const label = rate.afterCutoff ? "Kドリームスの締切後確認資料" : "Kドリームスの出走表成績";
      section.append(sourceLink(label, url, rate.sourceAt));
    }
    section.append(node("h3", "", "直近着順（新しい順）"));
    const recent = node("ul", "kd-recents");
    for (const row of (rider.recent || []).slice(0, 10)) {
      const label = row.rank ? row.rank + "着" : row.counts.map((n, i) => n ? (i + 1) + "着" + n + "回" : "").filter(Boolean).join("・") + "（同日）";
      recent.append(node("li", "", row.day.slice(5).replace("-", "/") + " " + label));
    }
    section.append(recent.childElementCount ? recent : node("p", "kd-note", "確認済みの直近着順は資料待ちです。"));
    return section;
  }

  function ranks(rank) {
    const section = node("section", "kd-section");
    section.append(node("h3", "", "今回のレースでの着順予測"));
    if (!rank) {
      section.append(node("p", "kd-note", "このレースの着順別確率は公開資料待ちです。"));
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
    section.append(node("h3", "", "本人コメントの要旨"));
    const follow = comment?.targetCar && riders.find(p => p.number === comment.targetCar);
    section.append(node("p", "", comment ? comment.summary + (follow ? " 対象 " + follow.number + "番 " + follow.name : "") : "確認できた要旨は資料待ちです。"));
    if (comment?.url) section.append(sourceLink("本人コメントの出典", comment.url, comment.at));
    else if (comment?.at) section.append(node("p", "kd-note", "コメント確認 " + stamp(comment.at)));
    section.append(node("h3", "", "今回の戦術分析"));
    if (tactics) {
      const phases = ["初周", "打鐘", "最終ホーム", "最終バック", "最終4コーナー", "ゴール"];
      tactics.positions.forEach((course, index) => {
        const steps = phases.flatMap((phase, i) => Number.isInteger(course?.[i]) ? [phase + " " + course[i] + "番手"] : []);
        if (steps.length) section.append(node("p", "", "保存Bの展開 " + (index + 1) + "　" + steps.join(" → ")));
      });
      for (const reason of tactics.reasons) section.append(node("p", "kd-note", reason));
      section.append(node("p", "kd-note", "戦術の保存 " + stamp(tactics.savedAt)));
    } else section.append(node("p", "kd-note", "対象選手に結び付く保存済みの展開資料を確認中です。"));
    const p = rider.rank?.probabilities;
    section.append(node("h3", "", "予想着順評価"));
    if (p) {
      const peak = Math.max(...p), modes = p.flatMap((x, n) => Math.abs(x - peak) < 1e-12 ? [n + 1] : []);
      const expected = p.reduce((sum, value, i) => sum + value * (i + 1), 0);
      section.append(node("p", "", "最頻 " + modes.join("・") + "着 · 期待着順 " + expected.toFixed(2) + "着"));
    } else section.append(node("p", "kd-note", "着順別の予想資料待ちです。"));
    return section;
  }

  function showRiders(container, data, day, venue) {
    const list = node("ul", "kd-riders"), detail = node("div", "kd-detail");
    list.setAttribute("aria-label", "出走選手");
    detail.id = "keirin-dossier-selected";
    const riders = data.riders, buttons = [];
    const scale = radarScale(riders.map(rider => rider.stats));
    function select(index) {
      buttons.forEach((button, i) => button.setAttribute("aria-pressed", String(i === index)));
      const rider = riders[index], heading = node("header", "kd-selected");
      const identity = node("div");
      identity.append(node("h2", "", rider.name), node("p", "kd-note", styles[rider.style] || "脚質確認待ち"));
      heading.append(badge(rider), identity);
      const stats = rider.stats;
      if (stats?.competition_points != null) heading.append(node("p", "kd-note", "競走得点 " + stats.competition_points));
      detail.replaceChildren(heading, history(rider, day, venue), radar(stats, scale), ranks(rider.rank), analysis(rider, riders));
      if (stats?.sourceAt) detail.append(node("p", "kd-note", (stats.source === "official" ? "KEIRIN.JP" : "Kドリームス") + " 出走表の確認 " + stamp(stats.sourceAt)));
    }
    riders.forEach((rider, i) => {
      const row = node("li"), button = node("button", "kd-rider-button");
      button.type = "button";
      button.setAttribute("aria-controls", detail.id);
      button.append(badge(rider), node("strong", "", rider.name), node("span", "kd-style", styles[rider.style] || "脚質確認待ち"));
      button.addEventListener("click", () => select(i));
      buttons.push(button);
      row.append(button); list.append(row);
    });
    container.replaceChildren(list, detail);
    select(0);
  }

  async function open({ raceId, title, day, venue, opener, load }) {
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
    dialog.addEventListener("close", () => {
      request.abort(); clearTimeout(timeout); dialog.remove();
      const target = opener?.isConnected ? opener : document.querySelector('[data-keirin-dossier="' + raceId + '"]');
      (target || document.getElementById("keirin-public-title"))?.focus({preventScroll: true});
    }, { once: true });
    document.body.append(dialog);
    dialog.showModal();
    try {
      const data = await load(request);
      if (!dialog.open) return;
      if (data?.riders.length) showRiders(body, data, day, venue);
      else body.replaceChildren(node("p", "kd-note", "対象の出走者を確認できる公開資料を待っています。"));
    } catch {
      if (dialog.open) body.replaceChildren(node("p", "kd-note", "選手の公開資料を取得できませんでした。"));
    } finally {
      clearTimeout(timeout);
      body.setAttribute("aria-busy", "false");
    }
  }

  globalThis.RaceKeirinDossier = { open, radar, radarScale };
})();
