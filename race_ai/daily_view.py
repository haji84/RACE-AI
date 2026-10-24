"""Accessible, static daily HTML motor coverage report; no dynamic network requests."""
from __future__ import annotations

from html import escape
from pathlib import Path


def _h(value:object)->str:
    return escape('未取得' if value is None else str(value),quote=True)


def render_daily_html(report:dict)->str:
    status=report.get('status','UNKNOWN')
    motors=report.get('motors') or []
    venues={}
    for m in motors:
        venues.setdefault(m.get('venue','不明'),[]).append(m)
    grouped=[]
    for venue, records in sorted(venues.items()):
        rows=[]
        for m in records:
            prev=m.get('prior_meet') or {}
            if prev:
                rider=f"{_h(prev.get('meeting_id','不明'))} / 新人経験 {_h(prev.get('rookie_starts'))}走"
            else:
                rider="未取得"
            adjusted=m.get('rider_adjusted_motor_residual')
            residue=f"{adjusted:+.4f}" if isinstance(adjusted,(int,float)) else '未計算'
            slots=m.get('current_exhibition') or []
            display=[]
            for slot in slots:
                met=slot.get('metrics',{})
                def val(field):
                    return _h((met.get(field) or {}).get('value'))
                status_label='原展示4項目あり' if slot.get('original_exhibition_complete') else '展示不足'
                display.append(f"<span class='small'>レース {_h(slot.get('race_id'))}・{_h(slot.get('lane'))}号艇 "
                               f"通常:{val('display')} / 1周:{val('lap')} / 回り:{val('turn')} / 直線:{val('straight')} "
                               f"({_h(status_label)})</span>")
            needs='、'.join(m.get('needs') or []) or 'なし'
            rows.append('<tr>'
              f'<td><b>{_h(m.get("motor_no"))}</b></td>'
              f'<td>{_h(m.get("historical_observations"))}走</td>'
              f'<td>{rider}</td>'
              f'<td>{_h(residue)} <span class="small">({ _h(m.get("rider_adjustment_status")) })</span></td>'
              f'<td>{"<p>".join(display) if display else "当日割当・展示未取得"}</td>'
              f'<td class="small">{_h(needs)}</td>'
              '</tr>')
        table='<table><thead><tr><th>モーター</th><th>履歴</th><th>前使用節</th><th>選手補正の残差</th><th>当日展示</th><th>不足情報</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table>'
        grouped.append(f'<details open><summary>場コード {_h(venue)}（{len(records)}モーター）</summary><div class="scroll">{table}</div></details>')
    summary=[('登録モーター',report.get('inventory_count','0')),
             ('過去レース履歴あり',report.get('history_count','0')),
             ('当日展示あり',report.get('current_exhibition_motor_count','0')),
             ('原展示4項目あり',report.get('original_exhibition_complete_motor_count','0')),
             ('前使用節判明',report.get('previous_meet_known_count','0'))]
    cards=''.join(f'<div class="stat"><span>{_h(label)}</span><strong>{_h(value)}</strong></div>' for label,value in summary)
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>RACE AI モーター日次照合 {_h(report.get('report_date_jst',''))}</title>
<style>
:root {{font:15px/1.5 system-ui,'Hiragino Sans',sans-serif;color:#223044;background:#f5f7fa}}
* {{box-sizing:border-box}} body {{margin:0}} main {{max-width:1300px;margin:0 auto;padding:26px 18px 80px}}
h1 {{font-size:1.7rem;margin:0 0 4px}} h2 {{font-size:1.1rem}}
.sub {{color:#64748b}} .warning {{background:#fff8e7;border:1px solid #ead59c;padding:14px;border-radius:12px;margin:18px 0}}
.stats {{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:12px;margin:18px 0}}
.stat {{background:#fff;border:1px solid #e0e5ed;border-radius:12px;padding:12px;display:flex;flex-direction:column}}
.stat span,.small {{font-size:.8rem;color:#62728a}} .stat strong {{font-size:1.65rem}}
details {{background:#fff;margin:14px 0;border-radius:14px;border:1px solid #e0e5ed;overflow:hidden}}
summary {{padding:15px 18px;font-weight:650;cursor:pointer}} .scroll {{overflow-x:auto}}
table {{border-collapse:collapse;width:100%;min-width:900px;text-align:left}} th,td {{padding:10px;border-top:1px solid #e9edf3;vertical-align:top}}
th {{background:#f8fafc;white-space:nowrap}} td p {{margin:0 0 4px}}
code {{font:inherit}}
</style></head>
<body><main><h1>RACE AI モーター日次照合</h1>
<p class="sub">対象日: {_h(report.get('report_date_jst'))} / 判断時点: {_h(report.get('decision_at'))}</p>
<section class="warning"><b>検証状態: {_h(status)}</b><p>掲載モーターだけを対象とした調査結果。公式全場の掲載網羅・原本真偽・予測精度は未検証。自動スクレイピングなし。</p>
<p>元台帳取得時刻: {_h(report.get('source_snapshot_capture_at'))} / 今日の台帳: {_h(report.get('inventory_fresh_today'))}</p></section>
<section class="stats">{cards}</section>
<h2>場別モーターと最新展示</h2>
{''.join(grouped) if grouped else '<p>対象モーター台帳なし。検証停止。</p>'}
<footer class="sub">選手補正残差は校正済みの機力確率ではなく研究用参考値。情報不足のまま購入判断へ使用しない。</footer>
</main></body></html>"""


def save_daily_html(report:dict, path:str|Path)->None:
    Path(path).write_text(render_daily_html(report),encoding='utf-8')
