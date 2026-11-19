"""Self-contained owner-only view. Rendered picks must never enter public Git.

The renderer selects display fields explicitly, does no network or file I/O,
and treats only the existing settlement states as scored or neutral outcomes.
It does not promote source-page claims to verified results or probabilities.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from html import escape
import math
import re

JST = timezone(timedelta(hours=9))
SETTLED = "AB_SETTLED_FROM_INDEPENDENT_RECEIPTS"
CANCELLED = "CANCELLED_FULL_REFUND_NO_MODEL_SCORE"
RACE = re.compile(r"^20[0-9]{10}$")


class OwnerReportError(ValueError):
    pass


def _need(condition, reason):
    if not condition:
        raise OwnerReportError(reason)


def _text(value):
    return escape(str(value), quote=True)


def _triple(value):
    _need(type(value) is list and len(value) == 3 and
          all(type(car) is int and 1 <= car <= 9 for car in value) and
          len(set(value)) == 3, "OWNER_REPORT_TICKET_INVALID")
    return tuple(value)


def _tickets(forecast):
    if forecast is None:
        return []
    _need(type(forecast) is dict, "OWNER_REPORT_FORECAST_INVALID")
    tickets = forecast.get("ranked_tickets")
    if tickets is None:
        return []
    _need(type(tickets) is list and 1 <= len(tickets) <= 12,
          "OWNER_REPORT_TICKET_COUNT_INVALID")
    values = [_triple(ticket) for ticket in tickets]
    _need(len(set(values)) == len(values), "OWNER_REPORT_TICKET_DUPLICATE")
    return values


def _paid(row):
    result = row.get("result")
    _need(type(result) is dict and result.get("race_id") == row["race_id"],
          "OWNER_REPORT_SETTLED_RESULT_MISSING")
    if row["state"] == CANCELLED:
        _need(result.get("status") == "CANCELLED" and result.get("refund_status") == "FULL"
              and result.get("winning_triples") == [] and result.get("payouts_100yen") == [],
              "OWNER_REPORT_CANCELLED_RESULT_INVALID")
        return {}
    _need(result.get("status") == "FINAL_NORMAL" and result.get("refund_status") == "NONE"
          and type(result.get("winning_triples")) is list
          and type(result.get("payouts_100yen")) is list,
          "OWNER_REPORT_SETTLED_RESULT_INVALID")
    winners = [_triple(ticket) for ticket in result["winning_triples"]]
    _need(1 <= len(winners) <= 20 and len(set(winners)) == len(winners),
          "OWNER_REPORT_WINNERS_INVALID")
    paid = {}
    for item in result["payouts_100yen"]:
        _need(type(item) is dict and type(item.get("yen")) is int and
              100 <= item["yen"] <= 10**9, "OWNER_REPORT_PAYOUT_INVALID")
        ticket = _triple(item.get("triple"))
        _need(ticket not in paid, "OWNER_REPORT_PAYOUT_DUPLICATE")
        paid[ticket] = item["yen"]
    _need(set(paid) == set(winners), "OWNER_REPORT_WINNERS_PAYOUT_MISMATCH")
    return paid


def _metric(value, kind):
    if value is None:
        return "未集計"
    _need(type(value) in (int, float) and math.isfinite(value),
          "OWNER_REPORT_METRIC_INVALID")
    if kind == "rate":
        _need(value >= 0, "OWNER_REPORT_RATE_INVALID")
        return f"{value * 100:,.1f}%"
    _need(type(value) is int, "OWNER_REPORT_INTEGER_METRIC_REQUIRED")
    if kind == "profit":
        return ("+" if value > 0 else "") + f"{value:,}円"
    _need(value >= 0, "OWNER_REPORT_NEGATIVE_COUNT_OR_AMOUNT")
    return f"{value:,}" + ("円" if kind == "yen" else "件")


def _cutoff(value):
    if value is None:
        return "締切未確認"
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if at.utcoffset() is None:
            return "締切未確認"
        return "締切 " + at.astimezone(JST).strftime("%H:%M") + " JST"
    except (ValueError, TypeError, AttributeError):
        return "締切未確認"


def _summary(role, stats):
    title = "公開印ベース" if role == "A" else "6局面モデル"
    metrics = (
        ("hit_at_1", "1点目の的中", "count"),
        ("hit_at_all", "候補内の的中", "count"),
        ("hit_at_1_rate", "1点目の的中率", "rate"),
        ("hit_at_all_rate", "候補内の的中率", "rate"),
        ("stake_yen", "仮想投資額", "yen"),
        ("payout_yen", "仮想払戻額", "yen"),
        ("virtual_roi", "仮想回収率", "rate"),
        ("virtual_profit_yen", "仮想収支", "profit"),
    )
    values = "".join(
        f'<div><dt>{label}</dt><dd data-metric="{key}">{_metric(stats.get(key), kind)}</dd></div>'
        for key, label, kind in metrics)
    note = ('<p class="model-note">Bの候補は研究用の順位で、的中確率ではありません。</p>'
            if role == "B" else "")
    return (f'<section class="model-summary model-{role.lower()}" data-model="{role}">'
            f'<h3><span class="model-letter">{role}</span>{title}</h3>'
            f'<dl class="metric-grid">{values}</dl>{note}</section>')


# Display-only extensions. C must come from independently admitted private evidence.
# The renderer cannot turn an unauthenticated C claim into a scored prediction.
_PHASE_LABELS = {
    "INITIAL": "初周", "BELL": "打鐘", "FINAL_HOME": "最終ホーム",
    "FINAL_BACK": "最終バック", "FOURTH_CORNER": "4コーナー", "GOAL": "ゴール",
}
_PHASE_ORDER = tuple(_PHASE_LABELS)
_ACTION_LABELS = {
    "PREDICTED_LINE_ORDER_ONLY": "想定ラインの隊列",
    "LEADER_ATTACKS": "主導権を狙う",
    "CHALLENGER_EARLY_COUNTER": "別線が早めに反撃",
    "LEADER_TRIES_TO_HOLD_PACE": "先行のペース維持を試みる",
    "LEADER_MAKURI_OR_KAMASHI": "主導権側のカマシ・捲り",
    "CHALLENGER_MAKURI": "別線の捲り",
    "FRONT_LINE_CONTINUITY_UNVERIFIED": "ライン継続は未検証",
    "FOLLOWER_SASHI_SCENARIO": "番手差しの仮説",
    "FOURTH_CORNER_ORDER_CONTINUES": "4角の隊列が続く",
    "LATE_SPRINT_OVERTAKE": "直線での追い抜き",
    "FRONT_LEADER_PACE_FADE": "先頭選手の減速",
}


def _phase_cause(stage):
    # Only fixed published research-action codes are rendered. Ignore identifiers,
    # arbitrary raw labels and unknown strings rather than leaking source data.
    actions = stage.get("hypothesis_actions")
    if type(actions) is not list or len(actions) > 8:
        return "局面の動作理由は未収録"
    reasons = [_ACTION_LABELS[action] for action in actions
               if type(action) is str and action in _ACTION_LABELS]
    return "・".join(reasons) if reasons else "局面の動作理由は未収録"


def _phase_details(forecast):
    """Present evidenced *hypotheses* only; never invent a missing stage."""
    if type(forecast) is not dict or not forecast.get("six_phase_scenarios"):
        return '<p class="method-pending">6局面の詳細は、この表示用原本に未収録です。</p>'
    scenarios = forecast["six_phase_scenarios"]
    if type(scenarios) is not list or not 1 <= len(scenarios) <= 24:
        return '<p class="method-pending">局面詳細を検証できません。</p>'
    sections = []
    for idx, item in enumerate(scenarios):
        if type(item) is not dict or type(item.get("six_phases")) is not list:
            return '<p class="method-pending">局面詳細を検証できません。</p>'
        stages = item["six_phases"]
        if len(stages) != len(_PHASE_ORDER) or any(
            type(stage) is not dict or stage.get("phase") != expected
            for stage, expected in zip(stages, _PHASE_ORDER)
        ):
            return '<p class="method-pending">6局面の順序を検証できません。</p>'
        lines = []
        for stage in stages:
            try:
                first_three = _triple(stage.get("projected_top3"))
            except OwnerReportError:
                return '<p class="method-pending">局面の車番を検証できません。</p>'
            triple = "-".join(str(n) for n in first_three)
            lines.append('<li><span>' + _PHASE_LABELS[stage["phase"]] +
                         '</span><strong>' + triple + '</strong>' +
                         '<small>' + _text(_phase_cause(stage)) + '</small></li>')
        finish = "-".join(str(n) for n in _triple(stages[-1]["projected_top3"]))
        sections.append(
            f'<details class="phase-branch"><summary>展開{idx+1}　ゴール予測 {finish}</summary>'
            '<ol class="phase-steps">' + "".join(lines) + '</ol></details>')
    return ('<p class="stage-note">すべて予測上の隊列。実映像で確認した着順・確率ではありません。</p>'
            + "".join(sections))


def _basis(role, forecast, ready):
    if not ready:
        if role == "C":
            return '<p class="method-pending">独立認証済みの過去連係履歴・締切前C原本を確認できません。</p>'
        return '<p class="method-pending">予想原本をこの画面へ読み込めていません。</p>'
    if role == "A":
        return ('<p class="method-copy">公開予想印・競走得点・近況・H/Bなどを使う基準方式。'
                '個別の材料が原本に未記録の場合、具体的な動きまでは断定できません。</p>')
    if role == "B":
        return ('<p class="method-copy">ライン・先行・捲り・番手差しを複数の6局面で仮説検討。'
                '候補順位は的中確率ではありません。</p>' + _phase_details(forecast))
    return ('<p class="method-copy">Bの展開に、独立検証された過去の追走・連係履歴を追加。'
            'この表示は予想原本が事前認証された場合のみです。</p>'
            + _phase_details(forecast))


def _arm(role, tickets, state, paid, *, forecast=None, c_unverified=False):
    if not tickets:
        label, tone = ("認証待ち" if c_unverified else "未生成", "muted") if role == "C" else ("予測なし", "muted")
    elif state == CANCELLED:
        label, tone = "集計対象外", "neutral"
    elif state == SETTLED:
        label, tone = ("的中", "hit") if any(t in paid for t in tickets) else ("不的中", "miss")
    else:
        label, tone = "照合待ち", "pending"
    entries = []
    for index, ticket in enumerate(tickets):
        winning = state == SETTLED and ticket in paid
        classes = "ticket" + (" ticket-hit" if winning else "")
        rank = "1点目" if index == 0 else str(index + 1)
        number = "-".join(str(car) for car in ticket)
        entries.append(f'<li class="{classes}"><span class="rank">{rank}</span>'
                       f'<strong>{number}</strong></li>')
    picks = ('<ol class="tickets">' + "".join(entries) + "</ol>" if tickets else
             ('<p class="empty">Cは未生成、または独立証拠の確認待ちです。A/Bの表示には影響しません。</p>'
              if role == "C" else
              '<p class="empty">今回の照合に読み込めた予測はありません。</p>'))
    title = {"A": "A｜基準予想", "B": "B｜6局面", "C": "C｜連係履歴"}[role]
    status_class = "c-outcome" if role == "C" else "outcome"
    method = _basis(role, forecast, bool(tickets))
    # Do not collapse picks. Only the optional per-branch explanations fold.
    return (f'<section class="arm arm-{role.lower()}" data-model="{role}">'
            f'<div class="arm-heading"><h3>{title}</h3>'
            f'<span class="{status_class} {tone}">{label}</span></div>'
            f'<p class="pick-count">三連単 <strong>{len(tickets)}点</strong>・全買い目</p>'
            + picks + '<div class="basis"><h4>展開と根拠</h4>' + method +
            '</div><p class="model-outcome">このモデルの照合：' + label +
            '</p></section>')


def _race_card(row, a, b, c, paid):
    state = row["state"]
    label = "照合済み" if state == SETTLED else "中止・全額返還" if state == CANCELLED else "照合待ち"
    tone = "settled" if state == SETTLED else "neutral" if state == CANCELLED else "pending"
    if state == SETTLED:
        results = "".join(
            '<div class="payout"><strong>' + "-".join(str(car) for car in ticket) +
            f'</strong><span>{yen:,}円</span></div>' for ticket, yen in paid.items())
        result_html = '<p class="result-caption">3連単・100円あたり</p>' + results
    elif state == CANCELLED:
        result_html = '<p class="result-neutral">中止・全額返還</p><p class="muted-copy">成績の集計対象外です。</p>'
    else:
        result_html = '<p class="result-waiting">照合待ち</p><p class="muted-copy">確定結果と保存済み予測の照合を待っています。</p>'
    return (
        f'<article class="race-card" data-race-id="{row["race_id"]}">'
        '<header class="race-heading"><div><p class="venue">' + _text(row["venue"]) + '</p>'
        f'<h2>{row["race_no"]}<span>R</span></h2></div>'
        f'<div class="race-meta"><span class="badge {tone}">{label}</span>'
        f'<p>{_text(_cutoff(row.get("official_cutoff_at")))}</p></div></header>'
        '<div class="race-columns">' +
        _arm("A", a, state, paid, forecast=row.get("A")) +
        _arm("B", b, state, paid, forecast=row.get("B")) +
        _arm("C", c, state, paid, forecast=row.get("C") if c else None,
             c_unverified=row.get("C") is not None and not c) +
        f'<section class="result-panel"><h3>公式結果</h3>{result_html}</section></div></article>')


STYLE = """
:root{color-scheme:light;--ink:#203047;--muted:#627186;--line:#dfe4e8;--paper:#fff;--blue:#315b85;--green:#196345}
*{box-sizing:border-box}body{margin:0;background:#f3f4f2;color:var(--ink);font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans JP",sans-serif}
main{max-width:1160px;margin:0 auto;padding:32px 28px 60px}h1,h2,h3,p,dl,dd{margin:0}h1{font-size:clamp(26px,4vw,38px);line-height:1.4;letter-spacing:.02em}h2,h3{line-height:1.4}
.page-header{margin-bottom:28px}.eyebrow{display:flex;flex-wrap:wrap;gap:12px;align-items:center;color:var(--muted);font-size:13px;margin-bottom:12px}.private-label{border:1px solid #ccd5dc;border-radius:6px;padding:2px 9px;font-weight:700;color:#43586b}.intro{margin-top:10px;color:var(--muted)}
.provider-notice{padding:15px 18px;margin-bottom:24px;border:1px solid #e0c99e;border-radius:10px;background:#fff8eb;color:#69522f;font-size:13px}.provider-notice strong{display:block;font-size:14px;margin-bottom:3px}.provider-notice details{margin-top:8px}.provider-notice code{display:block;overflow-wrap:anywhere;margin-top:5px;font-size:11px}
.section-heading{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:8px;margin-bottom:14px}.section-heading h2{font-size:20px}.section-heading p{color:var(--muted);font-size:13px}
.coverage-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.coverage-cell{padding:18px 20px;background:var(--paper);border:1px solid var(--line);border-radius:12px}.coverage-cell dt{font-size:13px;color:var(--muted)}.coverage-cell dd{font-size:34px;font-weight:750;font-variant-numeric:tabular-nums;line-height:1.4;margin:5px 0}.coverage-cell p{font-size:12px;color:var(--muted)}
.coverage-note{font-size:13px;color:var(--muted);margin-top:10px}#comparison{margin-top:30px}.summary-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.model-summary{background:var(--paper);border:1px solid var(--line);border-top:4px solid var(--blue);border-radius:12px;padding:20px}.model-b{border-top-color:var(--green)}.model-summary h3{display:flex;gap:10px;align-items:center;font-size:17px;margin-bottom:20px}.model-letter{background:#eaf0f5;color:var(--blue);font-size:16px;width:30px;height:30px;display:inline-grid;place-items:center;border-radius:7px}.model-b .model-letter{background:#e8f2ec;color:var(--green)}.metric-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px 22px}.metric-grid dt{font-size:12px;color:var(--muted)}.metric-grid dd{font-size:21px;font-weight:700;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}.comparison-note,.model-note{font-size:13px;color:var(--muted);margin-top:12px}
#races{margin-top:34px}.race-list{display:grid;gap:20px}.race-card{border:1px solid var(--line);border-radius:14px;background:var(--paper);overflow:hidden}.race-heading{display:flex;justify-content:space-between;gap:16px;padding:18px 22px;border-bottom:1px solid var(--line);background:#fcfcfb}.venue{font-size:14px;font-weight:650;overflow-wrap:anywhere}.race-heading h2{font-size:31px;line-height:1.1;margin-top:4px}.race-heading h2 span{font-size:17px;margin-left:4px}.race-meta{text-align:right;flex-shrink:0}.race-meta p{font-size:12px;color:var(--muted);margin-top:8px}.badge,.outcome{display:inline-block;border-radius:6px;padding:3px 9px;font-size:12px;font-weight:700;white-space:nowrap}.settled,.pending{background:#ecf1f5;color:#45627e}.neutral,.muted{background:#edf0ee;color:#59645f}.hit{background:#e4f2e9;color:#17613e}.miss{background:#f6ebe7;color:#94553e}
.race-columns{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr) minmax(190px,.8fr)}.arm,.result-panel{padding:18px 20px;min-width:0}.arm+.arm,.result-panel{border-left:1px solid var(--line)}.arm-heading{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:14px}.arm h3,.result-panel h3{font-size:14px}.tickets{list-style:none;padding:0;margin:0;display:flex;gap:7px;flex-wrap:wrap}.ticket{display:flex;gap:7px;align-items:center;border:1px solid #e0e5e9;border-radius:6px;padding:5px 8px;line-height:1.4}.ticket strong{font-size:16px;letter-spacing:.05em;font-variant-numeric:tabular-nums}.rank{font-size:10px;color:var(--muted)}.ticket-hit{border-color:#b4d7c1;background:#f0f8f3}.ticket-hit strong{color:var(--green)}.empty,.muted-copy{font-size:13px;color:var(--muted)}.result-caption{font-size:11px;color:var(--muted);margin:10px 0}.payout{display:flex;flex-wrap:wrap;justify-content:space-between;gap:6px 12px;align-items:baseline;padding:7px 0;border-bottom:1px solid #edf0f2}.payout strong{font-size:20px;letter-spacing:.05em}.payout span{font-size:16px;font-weight:700;font-variant-numeric:tabular-nums}.result-neutral,.result-waiting{font-size:16px;font-weight:650;margin:13px 0 7px}.page-footer{border-top:1px solid var(--line);margin-top:30px;padding-top:16px;color:var(--muted);font-size:12px}.no-races{padding:28px;background:white;border:1px solid var(--line);border-radius:12px;color:var(--muted)}
@media(max-width:700px){main{padding:22px 16px 40px}.page-header{margin-bottom:24px}.coverage-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.coverage-cell{padding:14px 16px}.coverage-cell dd{font-size:30px}.summary-grid{grid-template-columns:1fr;gap:14px}.model-summary{padding:18px}.metric-grid dd{font-size:20px}.race-columns{grid-template-columns:1fr}.arm+.arm,.result-panel{border-left:0;border-top:1px solid var(--line)}.race-heading{padding:16px 18px}.arm,.result-panel{padding:16px 18px}.race-meta{max-width:52%}.badge{white-space:normal;text-align:center}.section-heading h2{font-size:19px}.comparison-note,.intro{font-size:13px}}
@media print{body{background:white}main{padding:0;max-width:none}.race-card,.model-summary{break-inside:avoid}.race-list{gap:12px}.page-footer{font-size:10px}}
"""


STYLE += "\n/* Editorial, mobile-first cards. Do not hide any tickets behind JS or tabs. */\n:root{--ink:#252a27;--muted:#65716b;--line:#e6e1d6;--paper:#fff;--blue:#39576a;--green:#476c58}\nbody{background:#f8f6f1;color:var(--ink)}.page-header h1{letter-spacing:.01em}\n.race-columns{grid-template-columns:repeat(3,minmax(0,1fr))}\n.result-panel{grid-column:1/-1;border-left:0!important;border-top:1px solid var(--line);background:#fcfaf5}\n.race-heading{background:#fffdf9}.arm{padding:20px 18px;border-left:0;min-width:0}\n.arm+.arm{border-left:1px solid var(--line)}.arm-heading{align-items:flex-start}\n.arm h3{font-size:16px}.pick-count{font-size:13px;margin:0 0 13px;color:var(--muted)}\n.pick-count strong{font-size:19px;color:var(--ink);margin-left:4px}\n.tickets{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}\n.ticket{justify-content:space-between;background:#fff;border-radius:9px;padding:9px 10px}\n.ticket strong{font-size:17px}.rank{font-size:11px}\n.arm-a{border-top:3px solid #4b6174}.arm-b{border-top:3px solid #5b7659}\n.arm-c{border-top:3px solid #a77946;background:#fffdf8}\n.c-outcome{display:inline-block;border-radius:6px;padding:3px 9px;font-size:12px;font-weight:700}\n.basis{border-top:1px solid var(--line);margin-top:17px;padding-top:14px}\n.basis h4{margin:0 0 8px;font-size:13px;color:#4b514d}\n.method-copy,.method-pending,.stage-note{font-size:12px;color:var(--muted);line-height:1.8}\n.phase-branch{border:1px solid var(--line);border-radius:8px;margin-top:7px;background:#fff}\n.phase-branch summary{cursor:pointer;padding:8px 10px;font-size:13px;font-weight:600}\n.phase-steps{list-style:none;padding:0 11px 8px;margin:0}\n.phase-steps li{display:flex;justify-content:space-between;gap:12px;font-size:12px;padding:5px 0;border-top:1px solid #f0ede7}\n.phase-steps strong{font-variant-numeric:tabular-nums}
.phase-steps li{flex-wrap:wrap}.phase-steps small{flex-basis:100%;font-size:11px;color:var(--muted);line-height:1.4}\n.model-outcome{font-size:12px;margin-top:12px;color:var(--muted)}\n@media(max-width:950px){.race-columns{grid-template-columns:repeat(2,minmax(0,1fr))}.arm-c{grid-column:1/-1;border-top:1px solid var(--line);border-left:0!important}}\n@media(max-width:700px){.race-columns{grid-template-columns:1fr}.arm+.arm{border-left:0;border-top:1px solid var(--line)}.arm-c{grid-column:auto}.arm{padding:18px}.tickets{grid-template-columns:repeat(2,minmax(0,1fr))}}\n"

def render_private_report(report: dict, rows: list[dict], *, verify_optional_c=None) -> str:
    """Render trusted settlement output and selected decrypted rows in memory."""
    _need(type(report) is dict and type(rows) is list, "OWNER_REPORT_INPUT_REQUIRED")
    day = report.get("day_jst")
    try:
        _need(type(day) is str and date.fromisoformat(day).isoformat() == day,
              "OWNER_REPORT_DAY_INVALID")
    except ValueError:
        raise OwnerReportError("OWNER_REPORT_DAY_INVALID") from None
    total, scored = report.get("registered_races"), report.get("paired_A_B_scored")
    scope_note = report.get("evidence_scope_note",
                            "この画面で復号・検証できた原本を集計しています。")
    _need(type(scope_note) is str and len(scope_note) <= 2000,
          "OWNER_REPORT_EVIDENCE_SCOPE_NOTE_INVALID")
    provider_state = report.get("provider_state")
    _need(provider_state is None or (type(provider_state) is str and
          0 < len(provider_state) <= 500), "OWNER_REPORT_PROVIDER_STATE_INVALID")
    provider_notice = (
        '<aside class="provider-notice" role="note"><strong>今回の取得は保留中です。</strong>'
        '<p>表示している数値は、これまでに保存・検証できたデータです。今回の取得で更新できたとは限りません。</p>'
        f'<details><summary>取得状態のコード</summary><code>{_text(provider_state)}</code></details></aside>'
        if provider_state is not None else "")
    _need(type(total) is int and 0 <= total <= 1000 and len(rows) == total and
          type(scored) is int and 0 <= scored <= total, "OWNER_REPORT_COHORT_COUNT_MISMATCH")
    scorecard = report.get("scorecard")
    _need(type(scorecard) is dict, "OWNER_REPORT_SCORECARD_REQUIRED")
    stats_a, stats_b = scorecard.get("A_existing", {}), scorecard.get("B_six_phase", {})
    _need(type(stats_a) is dict and type(stats_b) is dict and
          stats_a.get("eligible", scored) == stats_b.get("eligible", scored) == scored,
          "OWNER_REPORT_AB_DENOMINATOR_MISMATCH")
    seen, prepared = set(), []
    for row in rows:
        _need(type(row) is dict, "OWNER_REPORT_RACE_REQUIRED")
        rid = row.get("race_id")
        _need(type(rid) is str and RACE.fullmatch(rid) and rid not in seen and
              rid[:8] == day.replace("-", "") and type(row.get("race_no")) is int and
              1 <= row["race_no"] <= 12 and int(rid[-2:]) == row["race_no"] and
              type(row.get("venue")) is str and type(row.get("state")) is str,
              "OWNER_REPORT_RACE_SCOPE_INVALID")
        seen.add(rid)
        a, b = _tickets(row.get("A")), _tickets(row.get("B"))
        # C is strictly opt-in to this PRIVATE renderer. The trusted caller
        # must independently authenticate C source, forecast SHA, cutoff,
        # private historical-follow labels and the exact same race identity.
        # No callback means HOLD, even if a C-looking payload is supplied.
        c = []
        if row.get("C") is not None and callable(verify_optional_c):
            try:
                if verify_optional_c(row) is True:
                    c = _tickets(row["C"])
            except (ValueError, TypeError, KeyError):
                c = []
        paid = _paid(row) if row["state"] in (SETTLED, CANCELLED) else {}
        _need(row["state"] != SETTLED or (a and b), "OWNER_REPORT_SCORED_FORECAST_MISSING")
        prepared.append((row, a, b, c, paid))
    actual_scored = sum(row["state"] == SETTLED for row, _, _, _, _ in prepared)
    neutral = sum(row["state"] == CANCELLED for row, _, _, _, _ in prepared)
    _need(actual_scored == scored and
          report.get("confirmed_cancelled_full_refund_races", neutral) == neutral,
          "OWNER_REPORT_SETTLEMENT_COUNT_MISMATCH")
    count_a = sum(bool(a) for _, a, _, _, _ in prepared)
    count_b = sum(bool(b) for _, _, b, _, _ in prepared)
    count_c = sum(bool(c) for _, _, _, c, _ in prepared)
    paired = sum(bool(a) and bool(b) for _, a, b, _, _ in prepared)
    waiting = total - scored - neutral
    coverage = "".join(
        f'<div class="coverage-cell"><dt>{label}</dt><dd data-metric="{metric}">{value}</dd>'
        f'<p>{detail}</p></div>' for metric, label, value, detail in (
            ("registered_races", "登録レース", total, "当日の全登録レース"),
            ("paired_forecasts", "A/B予測を読込済み", paired, f"A {count_a}件 / B {count_b}件"),
            ("paired_A_B_scored", "A/B照合済み", scored, "同じレースで成績を比較"),
            ("pending_races", "照合待ち", waiting, "未取得・予測なしを含む"),
        ))
    cards = "".join(_race_card(*entry) for entry in sorted(prepared, key=lambda x: x[0]["race_id"]))
    if not cards:
        cards = '<p class="no-races">この日の登録レースはありません。</p>'
    return (
        '<!doctype html><html lang="ja"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        'style-src \'unsafe-inline\'; script-src \'none\'; base-uri \'none\'; form-action \'none\'">'
        f'<title>{_text(day)} A/B予測・公式結果</title><style>{STYLE}</style></head><body><main>'
        '<header class="page-header"><div class="eyebrow"><span class="private-label">所有者用・非公開</span>'
        f'<span>{_text(day)} / 日本時間</span></div><h1>A/B予測と公式結果</h1>'
        '<p class="intro">予測が残っているか。結果を照合できたか。全レースを同じ画面で確認できます。</p></header>' + provider_notice +
        '<section id="coverage" aria-labelledby="coverage-title"><div class="section-heading">'
        '<h2 id="coverage-title">取得・照合の状況</h2></div><dl class="coverage-grid">' + coverage + '</dl>'
        f'<p class="coverage-note">{_text(scope_note)}</p>'
        f'<p class="coverage-note">C（過去連係追加）認証済み原本：{count_c}件。'
        'Cが未生成でもA/Bはそれぞれ表示します。Cの実績集計は同一レース分母の別監査待ちです。</p>'
        f'<p class="coverage-note">中止・全額返還：{neutral}件。照合待ちのレースは成績に含めていません。</p></section>'
        '<section id="comparison" aria-labelledby="comparison-title"><div class="section-heading">'
        f'<h2 id="comparison-title">A/Bの実績比較</h2><p>同じ{scored}レースを集計</p></div>'
        '<div class="summary-grid">' + _summary("A", stats_a) + _summary("B", stats_b) + '</div>'
        '<p class="comparison-note">A/Bの的中率は照合済みの同一レース分母です。'
        'Cが存在する場合は独立認証済みの該当レースに限定し、A/B全体の分母と混ぜません。'
        '中止・返還と照合待ちは分母に含めません。'
        '投資額・払戻額・収支は各候補100円で計算した仮想値です。</p></section>'
        '<section id="races" aria-labelledby="races-title"><div class="section-heading">'
        f'<h2 id="races-title">レース別の記録</h2><p>全{total}レース</p></div><div class="race-list">{cards}</div></section>'
        '<footer class="page-footer">この画面には非公開の予測候補が含まれます。「予測なし」は、この画面に読み込めた原本がないという意味です。'
        '保存先全体で予測が作られなかったことを示しません。予測なし・照合待ちは不的中として数えません。'
        '候補の順番はモデルの順位で、的中確率を示すものではありません。</footer></main></body></html>'
    )
