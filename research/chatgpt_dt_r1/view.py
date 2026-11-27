"""Standalone Japanese research dashboard, aggregate-only by default.

The aggregate projection is an allowlist, not a copy of the supplied report.
Private tickets require the separate explicit owner entry point. No network
asset, service, raw rider identity, or prediction input is embedded by default.
"""
from __future__ import annotations

from datetime import date
from html import escape
import json
import math
import os
from pathlib import Path
import re
import secrets


TRIFECTA_K = (1, 2, 4, 9, 12)
EXACTA_K = (1, 2)
ENTRANTS = (('existing-integrated', '既存統合モデル'), ('codex-new', 'Codex 新モデル'),
            ('chatgpt-dt-r1', 'ChatGPT DT-R1'))
CANDIDATES = {
    'full_without_pairs': '履歴あり・相互作用なし',
    'full_with_pairs': '履歴あり・ライン相互作用あり',
    'without_history_with_pairs': '履歴なし・ライン相互作用あり',
    'without_context_with_pairs': '外部資料なし・履歴とライン相互作用あり',
    'without_agari_interactions_with_pairs': '上がり相互作用なし・同一入力',
    'without_context_or_agari_with_pairs': '外部資料・上がり相互作用なし',
}
CLASS_LABELS = {'S': 'S級', 'A12': 'A級1・2班', 'A3': 'A級3班', 'L1': 'L級',
                'MIXED': '混在', 'UNKNOWN': '級班不明'}
RESULT_CODES = {'MISSING', 'DEAD_HEAT', 'CANCELLED', 'PENDING', 'INCOMPLETE',
                'SPECIAL_OR_INCOMPLETE', 'NO_UNIQUE_TOP3', 'REFUNDED', 'OTHER'}
HOLD_CODES = {'MISSING_PREDICTION', 'HOLD_UNSUPPORTED_ROSTER', 'HOLD_NONFINITE_FEATURE',
              'FEATURE_SCHEMA_MISMATCH', 'FEATURE_INPUT_HASH_MISMATCH', 'VALID_ROSTER_REQUIRED', 'OTHER'}


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _count(value):
    return value if type(value) is int and 0 <= value <= 10**12 else None


def _number(value, *, probability=False):
    if type(value) not in (float, int) or not math.isfinite(value):
        return None
    number = float(value)
    return number if not probability or 0 <= number <= 1 else None


def _rate(hits, total):
    return hits / total if hits is not None and total is not None and 0 <= hits <= total and total > 0 else None


def _sha(value):
    return value if isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) else None


def _day(value):
    try:
        return value if isinstance(value, str) and date.fromisoformat(value).isoformat() == value else None
    except ValueError:
        return None


def _counts(value, allowed):
    result = {}
    for key, count in _mapping(value).items():
        count = _count(count)
        if count is None:
            continue
        key = key.upper() if isinstance(key, str) else 'OTHER'
        key = key if key in allowed else 'OTHER'
        result[key] = result.get(key, 0) + count
    return result


def _metrics(value):
    value = _mapping(value)
    total, predicted = _count(value.get('evaluable')), _count(value.get('predicted_evaluable'))
    output = dict(registered=_count(value.get('registered')), evaluable=total,
                  predicted_evaluable=predicted, prediction_coverage=_rate(predicted, total),
                  not_evaluable=_counts(value.get('not_evaluable'), RESULT_CODES),
                  holds=_counts(value.get('holds'), HOLD_CODES),
                  exclusions_available=isinstance(value.get('not_evaluable'), dict),
                  holds_available=isinstance(value.get('holds'), dict))
    for market, ks in (('trifecta', TRIFECTA_K), ('exacta', EXACTA_K)):
        output[market] = {}
        for k in ks:
            cell = _mapping(_mapping(value.get(market)).get(str(k)))
            hits = _count(cell.get('hits'))
            if total is not None and hits is not None and hits > total:
                hits = None
            output[market][str(k)] = dict(hits=hits, all_target_rate=_rate(hits, total),
                                           predicted_rate=_rate(hits, predicted))
    scores = _mapping(value.get('proper_scores'))
    output['proper_scores'] = {key: _number(scores.get(key)) for key in
                               ('joint_top3_log_loss', 'exacta_log_loss', 'multiclass_brier')}
    output['proper_scores']['n'] = _count(scores.get('n'))
    return output


def _contest_metrics(value):
    value = _mapping(value)
    total, predicted = _count(value.get('eligible_n')), _count(value.get('forecast_n'))
    normalized = dict(registered=total, evaluable=total, predicted_evaluable=predicted)
    for market in ('trifecta', 'exacta'):
        normalized[market] = _mapping(_mapping(value.get(market)).get('hit_at'))
    return _metrics(normalized)


def _selection(value):
    value = _mapping(value)
    return {key: (_number(value.get(key)) if key in ('mean_ticket_count', 'net_on_payout_scored')
                  else _count(value.get(key))) for key in
            ('eligible_n', 'presented_n', 'hits', 'mean_ticket_count', 'payout_scored_n',
             'payout_missing_n', 'payout_unverified_n', 'net_on_payout_scored')}


def _confidence(report):
    groups = _mapping(report.get('fixed_policy_confidence_test'))
    calibration = _mapping(report.get('fixed_policy_calibration'))
    output = []
    for market, ks in (('trifecta', TRIFECTA_K), ('exacta', EXACTA_K)):
        for k in ks:
            key = f'{market}_{k}'
            if key not in groups:
                continue
            labels = {}
            for label in ('HOT', 'HIGH', 'MEDIUM', 'LOW', 'HOLD'):
                cell = _mapping(_mapping(groups[key]).get(label))
                n = _count(cell.get('n'))
                hits = _count(cell.get('hits'))
                if label not in _mapping(groups[key]):
                    n, hits = 0, 0
                labels[label] = dict(n=n, hits=hits, observed_rate=_rate(hits, n))
            c = _mapping(calibration.get(key))
            output.append(dict(id=key, market=market, ticket_limit=k, labels=labels,
                               calibration_rows=_count(c.get('calibration_rows')),
                               audit_rows=_count(c.get('audit_rows')),
                               actual_count_breakdown_available=False))
    return output


def _project(report):
    if not isinstance(report, dict):
        raise ValueError('AGGREGATE_REPORT_REQUIRED')
    if report.get('schema') not in (None, 'dt-r1-real-archive-study-v1'):
        raise ValueError('REPORT_SCHEMA_UNSUPPORTED')
    audit = _mapping(report.get('source_audit'))
    contract = _mapping(report.get('evaluation_contract'))
    splits = _mapping(contract.get('splits'))
    split_counts = _mapping(report.get('split_counts'))
    main = _metrics(report.get('final_period'))
    groups = {'field_size': {}, 'class': {}, 'venue': {}}
    for dimension in groups:
        for key, value in _mapping(_mapping(report.get('subgroups')).get(dimension)).items():
            valid = isinstance(key, str) and ((dimension == 'field_size' and key in {str(i) for i in range(3, 10)})
                or (dimension == 'class' and key in CLASS_LABELS)
                or (dimension == 'venue' and re.fullmatch(r'\d{2}', key)))
            if valid:
                groups[dimension][key] = _metrics(value)
    contest = _mapping(report.get('three_way_contest'))
    all_models = _mapping(_mapping(contest.get('all_target')).get('models'))
    common = _mapping(contest.get('common_cohort'))
    common_n = _count(common.get('eligible_n'))
    entrants = []
    for model_id, label in ENTRANTS:
        source = _mapping(all_models.get(model_id))
        received = _count(source.get('forecast_n'))
        if model_id == 'chatgpt-dt-r1' and received is None:
            received = main['predicted_evaluable']
        present = received is not None and received > 0
        if present and common_n and model_id in _mapping(common.get('models')):
            result = _contest_metrics(common['models'][model_id])
            scope = '共通対象'
        elif present:
            result = _contest_metrics(source) if source else main
            scope = '各モデルの全対象'
        else:
            result, scope = None, '比較待ち'
        entrants.append(dict(id=model_id, name=label, received=received,
                             status='受領済み' if present else '未受領', metrics=result, metric_scope=scope))
    source_rows = []
    for i, item in enumerate(audit.get('sources', []) if isinstance(audit.get('sources'), list) else []):
        item = _mapping(item)
        source_rows.append(dict(label=f'資料{i + 1}', sha256=_sha(item.get('sha256')),
                                bytes=_count(item.get('bytes')), races=_count(_mapping(item.get('rows')).get('races'))))
    evidence = _mapping(report.get('evidence_summary'))
    evidence_keys = ('venue_count', 'geometry_sources', 'half_lap_observations',
                     'video_observations', 'pre_cutoff_originals', 'payout_scored_races', 'contemporaneous_odds_races')
    selection = _selection(_mapping(all_models.get('chatgpt-dt-r1')).get('actual_selection'))
    return dict(
        mode='aggregate', model_id='chatgpt-dt-r1', model_sha256=_sha(report.get('model_sha256')),
        selected_candidate=CANDIDATES.get(report.get('selected_candidate'), '未確定'),
        selected_candidate_id=report.get('selected_candidate') if report.get('selected_candidate') in CANDIDATES else None,
        main=main, subgroups=groups, class_labels=CLASS_LABELS,
        entrants=entrants, common_n=common_n, verdict='勝敗未判定', confidence=_confidence(report),
        splits=[dict(id=key, label=label, start=_day(_mapping(splits.get(key)).get('start')),
                     end=_day(_mapping(splits.get(key)).get('end')), count=_count(split_counts.get(key)))
                for key, label in (('fit', '学習'), ('tune', '候補選択'), ('calibration', '校正'),
                                   ('audit', '独立監査'), ('test', '評価'))],
        ablations=[dict(id=key, label=label, metrics=_metrics(value))
                   for key, label in CANDIDATES.items()
                   if (value := _mapping(report.get('ablations_frozen_before_test')).get(key)) is not None],
        sources=source_rows, dataset_sha256=_sha(audit.get('dataset_sha256')),
        contract_sha256=_sha(contract.get('contract_sha256')),
        archive_races=_count(audit.get('unique_races')), feature_count=_count(report.get('feature_count')),
        runtime_seconds=_number(_mapping(report.get('runtime')).get('seconds')),
        evidence_summary={key: _count(evidence.get(key)) for key in evidence_keys},
        variable_selection=selection,
    )


def _private_forecasts(rows):
    if not isinstance(rows, list) or len(rows) > 50000:
        raise ValueError('OWNER_FORECAST_LIST_REQUIRED')
    output = []
    for row in rows:
        row = _mapping(row)
        rid = row.get('race_id')
        if not isinstance(rid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', rid):
            continue
        item = dict(race_id=rid, day=_day(row.get('day')), status='READY' if row.get('status') == 'READY' else 'HOLD')
        for market, count, limit in (('trifectas', 3, 12), ('exactas', 2, 2)):
            tickets = []
            for ticket in row.get(market, []) if isinstance(row.get(market), list) else []:
                ticket = _mapping(ticket)
                cars, probability = ticket.get('cars'), _number(ticket.get('probability'), probability=True)
                if (isinstance(cars, list) and len(cars) == count and all(type(c) is int and 1 <= c <= 9 for c in cars)
                        and len(set(cars)) == count and probability is not None):
                    tickets.append(dict(cars=cars, probability=probability))
            item[market] = sorted(tickets, key=lambda t: (-t['probability'], t['cars']))[:limit]
        output.append(item)
    return output


def _json_for_script(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            .replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
            .replace('\u2028', '\\u2028').replace('\u2029', '\\u2029'))


CSS = r'''
:root{color-scheme:dark;--bg:#0b1017;--card:#141c27;--card2:#111924;--border:#283342;--text:#eff2f6;--muted:#a1afbf;--orange:#ff9257;--orange-dim:#39251d;--blue:#85b8e5;--radius:18px}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Hiragino Kaku Gothic ProN','Yu Gothic',sans-serif;font-size:14px;line-height:1.65}button,select{font:inherit}a{color:inherit;text-decoration:none}a:focus-visible,select:focus-visible,summary:focus-visible{outline:2px solid var(--orange);outline-offset:4px}header{border-bottom:1px solid var(--border);background:#0e151e}.topbar{max-width:1300px;margin:auto;padding:20px 36px;display:flex;align-items:center;justify-content:space-between;gap:24px}.brand{display:flex;align-items:center;gap:12px;font-size:13px;font-weight:750;letter-spacing:.12em}.brandmark{width:34px;height:34px;display:grid;place-items:center;border-radius:9px;background:var(--orange);color:#26160e;font-size:16px;letter-spacing:-.06em}nav{display:flex;gap:24px;color:var(--muted);font-size:12px}nav a:hover{color:var(--text)}main{max-width:1300px;margin:auto;padding:36px}.eyebrow{font-size:11px;letter-spacing:.17em;color:var(--orange);font-weight:750;text-transform:uppercase}.hero{display:flex;justify-content:space-between;align-items:flex-start;gap:24px;margin-bottom:24px}h1{font-size:clamp(28px,3.8vw,43px);line-height:1.3;letter-spacing:-.045em;margin:10px 0}h2{font-size:19px;letter-spacing:-.02em;margin:0}h3{font-size:14px;margin:0}.subtle{color:var(--muted);margin:6px 0 0;font-size:13px}.hero-side{text-align:right;padding-top:8px;flex-shrink:0}.pill{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--border);border-radius:99px;padding:5px 10px;color:var(--muted);font-size:11px;white-space:nowrap}.pill.orange{background:var(--orange-dim);border-color:#6b422b;color:#ffc19b}.scope-note{display:flex;gap:14px;align-items:flex-start;background:#1c1c1a;border:1px solid #493629;border-radius:12px;padding:15px 18px;color:#d7c8bb;margin-bottom:28px;font-size:12px}.scope-note strong{color:#ffbf95;white-space:nowrap}.grid{display:grid;gap:16px}.stats{grid-template-columns:repeat(4,minmax(0,1fr));margin-bottom:32px}.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:23px}.stat-label{font-size:12px;color:var(--muted);display:flex;justify-content:space-between;gap:12px}.stat-value{font-size:clamp(28px,3vw,39px);line-height:1.2;letter-spacing:-.055em;font-weight:720;margin:12px 0 9px;font-variant-numeric:tabular-nums}.stat-value.accent{color:var(--orange)}.stat-detail{font-size:11px;color:var(--muted)}section{scroll-margin-top:24px;margin:30px 0}.section-head{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;margin-bottom:16px}.section-head p{margin:5px 0 0}.controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap}select{background:#101823;color:var(--text);border:1px solid #344256;border-radius:9px;min-height:39px;padding:7px 30px 7px 11px;font-size:12px;max-width:100%}.two-col{grid-template-columns:1.3fr 1fr}.card-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:16px}.metric-row{display:grid;grid-template-columns:70px 1fr 72px;gap:14px;align-items:center;margin:14px 0}.metric-row .rate{text-align:right;font-variant-numeric:tabular-nums;font-size:14px;font-weight:650}.metric-row small{display:block;color:var(--muted);font-size:10px;font-weight:400}.metric-row progress{width:100%;height:7px;border:0;border-radius:8px;overflow:hidden;background:#26323f;appearance:none}.metric-row progress::-webkit-progress-bar{background:#26323f;border-radius:8px}.metric-row progress::-webkit-progress-value{background:var(--orange);border-radius:8px}.metric-row progress::-moz-progress-bar{background:var(--orange);border-radius:8px}.metric-row.blue progress::-webkit-progress-value{background:var(--blue)}.metric-row.blue progress::-moz-progress-bar{background:var(--blue)}.caption{font-size:11px;color:var(--muted);border-top:1px solid var(--border);padding-top:12px;margin-top:15px}.mini-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:18px}.mini{padding-top:14px;border-top:1px solid var(--border)}.mini .number{display:block;font-size:22px;font-weight:650;margin:2px 0;color:var(--text)}.mini .label{font-size:10px;color:var(--muted)}.count-list{display:flex;gap:8px;flex-wrap:wrap;margin-top:15px}.count-tag{background:#101721;border:1px solid var(--border);border-radius:8px;padding:6px 9px;font-size:11px;color:var(--muted)}.comparison-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.entrant{min-height:226px;position:relative}.entrant.active{border-color:#855133;background:linear-gradient(155deg,#241e1a,var(--card) 65%)}.entrant.pending{background:var(--card2)}.entrant-title{font-size:15px;font-weight:700;margin:12px 0 7px}.entrant .pending-word{color:#8e9aac;font-size:25px;margin:29px 0 7px;font-weight:650;letter-spacing:-.035em}.entrant-rates{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:25px}.entrant-rates span{display:block;font-size:10px;color:var(--muted)}.entrant-rates strong{font-size:22px;font-weight:680;font-variant-numeric:tabular-nums}.verdict{margin-top:14px;padding:12px 16px;background:#111a26;border:1px solid var(--border);border-radius:11px;color:var(--muted);font-size:12px}.verdict strong{color:var(--text);margin-right:10px}.confidence-grid{grid-template-columns:repeat(5,minmax(0,1fr))}.confidence-card{padding:17px 16px;background:#101822;border:1px solid var(--border);border-radius:12px}.confidence-card .name{font-size:12px;font-weight:650}.confidence-card .threshold{font-size:10px;color:var(--muted)}.confidence-card .amount{font-size:30px;line-height:1.2;font-weight:680;letter-spacing:-.03em;margin:14px 0 4px}.confidence-card .amount small{font-size:11px;font-weight:400;color:var(--muted);margin-left:4px}.confidence-card.hot{border-top:2px solid var(--orange)}.confidence-card.high{border-top:2px solid #dfbc79}.confidence-card.medium{border-top:2px solid var(--blue)}.confidence-card.low{border-top:2px solid #899cac}.confidence-card.hold{border-top:2px solid #b3a5bb}.confidence-card .actual{color:var(--muted);font-size:10px}.confidence-foot{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-top:16px;font-size:11px;color:var(--muted)}.policy-box{display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-top:18px;padding-top:20px;border-top:1px solid var(--border)}.policy-box p{font-size:12px;color:var(--muted);margin:8px 0}.bands{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}.band{background:#0e1620;border:1px solid var(--border);padding:9px 7px;border-radius:8px;text-align:center}.band span{font-size:10px;color:var(--muted);display:block}.band strong{font-size:16px}.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:12px}th{text-align:left;color:var(--muted);font-weight:500;font-size:11px;padding:10px 10px;border-bottom:1px solid var(--border);white-space:nowrap}td{padding:14px 10px;border-bottom:1px solid #232d3a;font-variant-numeric:tabular-nums}tbody tr:last-child td{border-bottom:0}td.num,th.num{text-align:right}tbody tr.selected{background:#231d19}td .picked{font-size:10px;color:var(--orange);margin-left:8px}.split-grid{grid-template-columns:repeat(5,minmax(0,1fr));gap:10px}.split{background:#101823;border:1px solid var(--border);border-radius:12px;padding:15px 13px}.split.active{border-color:#855133}.split .step{color:var(--orange);font-size:10px;letter-spacing:.1em}.split .name{font-weight:650;margin:4px 0 10px;font-size:13px}.split .date{color:var(--muted);font-size:10px;font-variant-numeric:tabular-nums}.split .n{font-size:18px;margin-top:9px;font-variant-numeric:tabular-nums}.split .n small{font-size:10px;color:var(--muted);font-weight:400}.evidence-grid{grid-template-columns:1fr 1fr;margin-top:18px}.evidence-list{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin:16px 0}.evidence-item{padding:12px;border:1px solid var(--border);border-radius:9px;background:#101721}.evidence-item span{display:block;font-size:11px;color:var(--muted)}.evidence-item strong{display:block;font-size:13px;margin-top:5px;font-weight:550}.note-list{padding:0;margin:12px 0;list-style:none}.note-list li{padding:11px 0;border-bottom:1px solid var(--border);font-size:12px;color:var(--muted)}.note-list li:last-child{border:0}.note-list b{display:block;color:#dbe2ea;font-weight:550;margin-bottom:4px}details{background:#101721;border:1px solid var(--border);border-radius:12px;padding:13px 15px;margin-top:15px}summary{cursor:pointer;color:var(--muted);font-size:12px}details[open] summary{margin-bottom:16px}.hash-item{margin:12px 0}.hash-item span{display:block;font-size:10px;color:var(--muted);margin-bottom:5px}code{display:block;overflow-wrap:anywhere;word-break:break-all;background:#0b1118;border:1px solid #202a36;border-radius:6px;padding:9px;color:#bdcddd;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:10px}.footer{color:#8191a3;font-size:10px;margin-top:32px;padding:20px 0 10px;border-top:1px solid var(--border);display:flex;justify-content:space-between;gap:20px}.owner-banner{border:1px solid #8a5735;background:#302117;padding:15px 18px;border-radius:12px;margin-bottom:22px;color:#ffd0aa}.owner-banner b{display:block}.owner-grid{display:grid;grid-template-columns:1fr 1fr;gap:22px}.ticket{font-weight:700;letter-spacing:.11em}.empty{color:var(--muted);padding:16px 0;font-size:12px}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);border:0}noscript{display:block;padding:18px;color:#ffbf95;border:1px solid #66462e;border-radius:10px}
@media(max-width:950px){.topbar,main{padding-left:22px;padding-right:22px}.two-col{grid-template-columns:1fr 1fr}.confidence-grid{grid-template-columns:repeat(3,1fr)}.split-grid{grid-template-columns:repeat(3,1fr)}.entrant-rates{gap:6px}.entrant-rates strong{font-size:19px}.policy-box{grid-template-columns:1fr}.evidence-grid{grid-template-columns:1fr}.hero-side{max-width:220px}.stats{gap:12px}.card{padding:19px}}
@media(max-width:650px){.topbar{padding:16px}nav{gap:15px;font-size:10px}nav a:last-child{display:none}main{padding:25px 16px}.hero{display:block;margin-bottom:19px}.hero-side{text-align:left;padding-top:12px;max-width:none}.hero-side .subtle{display:inline;margin-left:8px;font-size:10px}.scope-note{display:block;padding:13px 14px}.scope-note strong{display:block;margin-bottom:4px}.stats{grid-template-columns:repeat(2,1fr);margin-bottom:26px}.stat-value{font-size:31px}.stat-label{font-size:11px}.stat-detail{font-size:10px}.section-head{display:block}.controls{margin-top:12px}.two-col,.comparison-grid,.owner-grid{grid-template-columns:1fr}.entrant{min-height:0;padding:20px}.entrant .pending-word{font-size:21px;margin:17px 0 4px}.entrant-rates{margin-top:18px}.entrant-rates strong{font-size:25px}.confidence-grid{grid-template-columns:repeat(2,1fr);gap:10px}.confidence-card:last-child{grid-column:span 2}.confidence-card .amount{font-size:26px}.split-grid{grid-template-columns:repeat(2,1fr)}.split:last-child{grid-column:span 2}.split.active{display:grid;grid-template-columns:1fr 1fr;column-gap:12px}.split.active .step{grid-column:span 2}.split.active .n{grid-column:2;grid-row:2 / span 3;font-size:28px;align-self:center;text-align:right}.bands{grid-template-columns:repeat(2,1fr)}.evidence-list{gap:7px}.card{padding:18px 16px}.metric-row{grid-template-columns:62px 1fr 68px;gap:10px}.footer{display:block}.footer span{display:block;margin:5px 0}.mini-grid{gap:8px}.mini .number{font-size:20px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}@media print{body{background:white;color:#111}nav,.controls{display:none}.card,.split,details{break-inside:avoid;background:white;color:#111;border-color:#aaa}.subtle,.caption,.footer{color:#444}main{max-width:none;padding:15px}.scope-note{background:#fff4e9;color:#333}.stats{grid-template-columns:repeat(4,1fr)}}
'''


JAVASCRIPT = r'''
"use strict";
const report=JSON.parse(document.getElementById("report-data").textContent);
const $=id=>document.getElementById(id);
const number=v=>v===null||v===undefined?"未集計":new Intl.NumberFormat("ja-JP").format(v);
const percent=v=>v===null||v===undefined?"未集計":(v*100).toFixed(2)+"%";
const decimal=v=>v===null||v===undefined?"未集計":v.toFixed(4);
const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
const clear=e=>e.replaceChildren();
const put=(id,text)=>$(id).textContent=text;
const detail=(hits,n)=>hits===null||n===null?"件数未集計":number(hits)+" / "+number(n)+"件";
const resultNames={MISSING:"結果未取得",DEAD_HEAT:"同着・採点保留",CANCELLED:"中止",PENDING:"結果待ち",INCOMPLETE:"着順不足",SPECIAL_OR_INCOMPLETE:"特殊・結果不足",NO_UNIQUE_TOP3:"上位3着未確定",REFUNDED:"返還",OTHER:"その他"};
function metricBars(id,metrics,market){const root=$(id);clear(root);for(const [k,cell] of Object.entries(metrics[market])){const row=node("div",undefined,"metric-row"+(market==="exacta"?" blue":""));const label=node("span",k+"点");const bar=node("progress");bar.max=1;bar.value=cell.all_target_rate||0;bar.setAttribute("aria-label",k+"点の全対象的中率 "+percent(cell.all_target_rate));const value=node("span",percent(cell.all_target_rate),"rate");value.append(node("small",detail(cell.hits,metrics.evaluable)));row.append(label,bar,value);root.append(row);}}
function updateMetrics(metrics,label){put("current-scope",label);put("hero-hit1",percent(metrics.trifecta["1"].all_target_rate));put("hero-hit1-detail",detail(metrics.trifecta["1"].hits,metrics.evaluable));put("hero-hit4",percent(metrics.trifecta["4"].all_target_rate));put("hero-hit4-detail",detail(metrics.trifecta["4"].hits,metrics.evaluable));put("hero-exacta2",percent(metrics.exacta["2"].all_target_rate));put("hero-exacta2-detail",detail(metrics.exacta["2"].hits,metrics.evaluable));put("hero-coverage",percent(metrics.prediction_coverage));put("hero-coverage-detail",detail(metrics.predicted_evaluable,metrics.evaluable));metricBars("trifecta-bars",metrics,"trifecta");metricBars("exacta-bars",metrics,"exacta");put("registered-count",number(metrics.registered));put("evaluable-count",number(metrics.evaluable));put("predicted-count",number(metrics.predicted_evaluable));put("nll",decimal(metrics.proper_scores.joint_top3_log_loss));put("brier",decimal(metrics.proper_scores.multiclass_brier));put("proper-count",number(metrics.proper_scores.n));const tags=$("coverage-tags");clear(tags);for(const [key,n] of Object.entries(metrics.not_evaluable)){tags.append(node("span",(resultNames[key]||"その他")+" "+number(n)+"件","count-tag"));}if(!metrics.exclusions_available)tags.append(node("span","採点対象外の内訳 未集計","count-tag"));const held=metrics.holds_available?Object.values(metrics.holds).reduce((a,b)=>a+b,0):null;tags.append(node("span","予想欠落・保留 "+number(held)+(held===null?"":"件"),"count-tag"));}
function selectGroup(){const dimension=$("dimension").value;const pick=$("group");clear(pick);if(dimension==="all"){pick.append(new Option("全登録対象","all"));pick.disabled=true;updateMetrics(report.main,"全体");return;}pick.disabled=false;const groups=report.subgroups[dimension];for(const key of Object.keys(groups).sort((a,b)=>a.localeCompare(b,"ja",{numeric:true}))){const label=dimension==="field_size"?key+"車":dimension==="class"?report.class_labels[key]:"会場 "+key;pick.append(new Option(label,key));}if(!pick.options.length){pick.append(new Option("集計なし",""));pick.disabled=true;updateMetrics(report.main,"全体（区分集計なし）");return;}updateGroup();}
function updateGroup(){const dimension=$("dimension").value;const key=$("group").value;const data=report.subgroups[dimension]&&report.subgroups[dimension][key];if(data)updateMetrics(data,$("group").selectedOptions[0].textContent);}
$("dimension").addEventListener("change",selectGroup);$("group").addEventListener("change",updateGroup);
function comparisons(){const root=$("entrants");clear(root);for(const entry of report.entrants){const card=node("article",undefined,"card entrant "+(entry.id==="chatgpt-dt-r1"?"active":entry.metrics?"":"pending"));card.append(node("span",entry.status,"pill"+(entry.metrics?" orange":"")),node("h3",entry.name,"entrant-title"));if(!entry.metrics){card.append(node("div","未受領","pending-word"),node("p","独立に固定された予想原本の受領待ち。","subtle"));}else{card.append(node("p",entry.metric_scope+"・予想 "+number(entry.received)+"件","subtle"));const grid=node("div",undefined,"entrant-rates");for(const [label,market,k] of [["三連単1点","trifecta","1"],["三連単4点","trifecta","4"],["二車単2点","exacta","2"]]){const box=node("div");box.append(node("span",label),node("strong",percent(entry.metrics[market][k].all_target_rate)));grid.append(box);}card.append(grid);}root.append(card);}put("contest-count","3モデルの共通対象："+number(report.common_n)+"件");}
const confidenceNames={HOT:["激アツ","90%以上","hot"],HIGH:["高","80%以上90%未満","high"],MEDIUM:["中","60%以上80%未満","medium"],LOW:["低","60%未満","low"],HOLD:["判定保留","資料・検証不足","hold"]};
function updateConfidence(){const group=report.confidence.find(x=>x.id===$("confidence-policy").value);const root=$("confidence-cells");clear(root);for(const [key,[label,threshold,cls]] of Object.entries(confidenceNames)){const cell=group?group.labels[key]:{n:null,observed_rate:null};const card=node("div",undefined,"confidence-card "+cls);card.append(node("div",label,"name"),node("div",threshold,"threshold"));const amount=node("div",number(cell.n),"amount");if(cell.n!==null)amount.append(node("small","件"));card.append(amount,node("div","実測的中率 "+percent(cell.observed_rate),"actual"));root.append(card);}put("calibration-support",group?"校正 "+number(group.calibration_rows)+"件 / 独立監査 "+number(group.audit_rows)+"件":"校正・監査の集計未収録");put("actual-ticket-note",group?"固定点数検証："+(group.market==="trifecta"?"三連単":"二車単")+" 最大"+group.ticket_limit+"点。実際の点数内訳は未収録。":"提示点数ごとの判定資料は未収録です。");}
function confidence(){const select=$("confidence-policy");for(const item of report.confidence){select.append(new Option((item.market==="trifecta"?"三連単":"二車単")+"・最大"+item.ticket_limit+"点",item.id));}if(!select.options.length){select.append(new Option("集計未収録",""));select.disabled=true;}select.addEventListener("change",updateConfidence);updateConfidence();const v=report.variable_selection;put("variable-status",v.presented_n?"提示原本 "+number(v.presented_n)+"件":"オッズ連動の実績は未集計");put("variable-detail",v.presented_n?"実際の平均提示点数 "+number(v.mean_ticket_count)+"点 / 的中 "+number(v.hits)+"件 / 払戻照合 "+number(v.payout_scored_n)+"件":"同時点のオッズと提示原本を照合してから、固定点数の成績と分けて集計します。");}
function ablations(){const body=$("ablation-body");clear(body);for(const row of report.ablations){const tr=node("tr");if(row.id===report.selected_candidate_id)tr.className="selected";const name=node("td",row.label);if(row.id===report.selected_candidate_id)name.append(node("span","採用候補","picked"));tr.append(name);for(const val of [percent(row.metrics.trifecta["1"].all_target_rate),percent(row.metrics.trifecta["4"].all_target_rate),percent(row.metrics.exacta["2"].all_target_rate),decimal(row.metrics.proper_scores.joint_top3_log_loss)])tr.append(node("td",val,"num"));body.append(tr);}if(!report.ablations.length){const tr=node("tr");const cell=node("td","構成別の比較結果は未集計です。","empty");cell.colSpan=5;tr.append(cell);body.append(tr);}}
function evidence(){const root=$("splits");for(const [i,part] of report.splits.entries()){const card=node("div",undefined,"split"+(part.id==="test"?" active":""));card.append(node("div","0"+(i+1),"step"),node("div",part.label,"name"),node("div",part.start||"期間未設定","date"),node("div",part.end?"〜 "+part.end:"","date"));const n=node("div",number(part.count),"n");if(part.count!==null)n.append(node("small"," 件"));card.append(n);root.append(card);}const labels={venue_count:"会場資料",geometry_sources:"形状の出典",half_lap_observations:"上がりタイム（最終半周）の観測",video_observations:"映像の観測",pre_cutoff_originals:"締切前原本",payout_scored_races:"払戻照合",contemporaneous_odds_races:"同時点のオッズ"};const items=$("evidence-items");for(const [key,label] of Object.entries(labels)){const n=report.evidence_summary[key];const card=node("div",undefined,"evidence-item");card.append(node("span",label),node("strong",n===null?"集計未収録":number(n)+"件"));items.append(card);}const hashes=$("hashes");for(const [label,value] of [["モデル SHA-256",report.model_sha256],["共通資料 SHA-256",report.dataset_sha256],["評価契約 SHA-256",report.contract_sha256],...report.sources.map(s=>[s.label+" SHA-256",s.sha256])]){const item=node("div",undefined,"hash-item");item.append(node("span",label),node("code",value||"未提供"));hashes.append(item);}put("archive-count",number(report.archive_races));put("feature-count",number(report.feature_count));put("runtime",report.runtime_seconds===null?"未集計":number(Math.round(report.runtime_seconds))+"秒");}
function owner(){if(report.mode!=="owner_private")return;const root=$("owner-root");const section=node("section",undefined,"card");const head=node("div",undefined,"section-head");const words=node("div");words.append(node("h2","所有者用・保存予想の候補"),node("p","三連単は上位12候補、二車単は上位2候補。実際の提示・投票記録とは区別します。","subtle"));const select=node("select");select.setAttribute("aria-label","所有者用レース選択");for(const row of report.forecasts)select.append(new Option((row.day||"日付不明")+" / "+row.race_id,row.race_id));head.append(words,select);const tables=node("div",undefined,"owner-grid");section.append(head,tables);root.append(section);function show(){clear(tables);const row=report.forecasts.find(r=>r.race_id===select.value);if(!row){tables.append(node("p","表示できる保存予想はありません。","empty"));return;}for(const [market,label] of [["trifectas","三連単"],["exactas","二車単"]]){const box=node("div");box.append(node("h3",label+"・モデル確率"));const table=node("table");const tbody=node("tbody");for(const [i,ticket] of row[market].entries()){const tr=node("tr");tr.append(node("td",String(i+1)),node("td",ticket.cars.join("-"),"ticket"),node("td",percent(ticket.probability),"num"));tbody.append(tr);}table.append(tbody);box.append(table);tables.append(box);}}select.addEventListener("change",show);show();}
put("model-short",report.model_sha256?"モデル "+report.model_sha256.slice(0,12):"モデル未固定");put("chosen-candidate",report.selected_candidate);put("test-period",report.splits[4].start&&report.splits[4].end?report.splits[4].start+" 〜 "+report.splits[4].end:"評価期間未設定");selectGroup();comparisons();confidence();ablations();evidence();owner();
'''


BODY = '''
<header><div class="topbar"><a class="brand" href="#top"><span class="brandmark">DT</span>RACE-AI <span>RESEARCH</span></a><nav aria-label="ページ内"><a href="#performance">検証結果</a><a href="#comparison">3モデル比較</a><a href="#confidence">信頼度</a><a href="#evidence">資料と条件</a></nav></div></header>
<main id="top"><div class="hero"><div><div class="eyebrow">Independent research / DT-R1</div><h1>DT-R1 研究レポート</h1><p class="subtle">何件を予測し、同じ点数で何件当たったか。</p></div><div class="hero-side"><span class="pill orange">過去データの再検証</span><p class="subtle" id="test-period">評価期間を読み込み中</p></div></div>
__OWNER_BANNER__
<div class="scope-note"><strong>この数字の対象</strong><span>すでに参照した履歴を使う過去検証です。未来の精度と本番採用は未確認です。的中率は採点可能な全対象を分母にし、予想が欠けたレースも外れとして残します。</span></div>
<noscript>このファイルには集計だけを保存しています。区分の切替と数値表示にはJavaScriptを有効にしてください。外部通信は使用しません。</noscript>
<div class="grid stats" aria-label="主要指標"><article class="card"><div class="stat-label">三連単・1点<span>Hit@1</span></div><div class="stat-value accent" id="hero-hit1">未集計</div><div class="stat-detail" id="hero-hit1-detail">全対象の的中数</div></article><article class="card"><div class="stat-label">三連単・4点<span>Hit@4</span></div><div class="stat-value" id="hero-hit4">未集計</div><div class="stat-detail" id="hero-hit4-detail">全対象の的中数</div></article><article class="card"><div class="stat-label">二車単・2点<span>Hit@2</span></div><div class="stat-value" id="hero-exacta2">未集計</div><div class="stat-detail" id="hero-exacta2-detail">全対象の的中数</div></article><article class="card"><div class="stat-label">予想の網羅率<span>Coverage</span></div><div class="stat-value" id="hero-coverage">未集計</div><div class="stat-detail" id="hero-coverage-detail">採点可能な対象への予想数</div></article></div>
<section id="performance"><div class="section-head"><div><h2>同じ点数で比べる</h2><p class="subtle">表示範囲：<span id="current-scope">全体</span>。区分を一つずつ切り替えられます。</p></div><div class="controls"><label class="sr-only" for="dimension">比較する区分</label><select id="dimension"><option value="all">全体</option><option value="field_size">車立て</option><option value="class">級班</option><option value="venue">会場</option></select><label class="sr-only" for="group">区分の値</label><select id="group"></select></div></div><div class="grid two-col"><article class="card"><div class="card-head"><h3>三連単の的中率</h3><span class="pill">固定点数</span></div><div id="trifecta-bars"></div><p class="caption">1・2・4・9・12点を同じ予想順位で集計。候補総数が指定点数未満の場合は全候補を使います。</p></article><article class="card"><div class="card-head"><h3>二車単と対象件数</h3><span class="pill">最大2点</span></div><div id="exacta-bars"></div><div class="mini-grid"><div class="mini"><span class="label">登録</span><span class="number" id="registered-count">未集計</span></div><div class="mini"><span class="label">採点可能</span><span class="number" id="evaluable-count">未集計</span></div><div class="mini"><span class="label">予想あり</span><span class="number" id="predicted-count">未集計</span></div></div><div id="coverage-tags" class="count-list"></div></article></div><div class="caption">確率の評価：三連単Log Loss <b id="nll">未集計</b> / Brier <b id="brier">未集計</b>（小さいほど良い）。確率を保存できた <span id="proper-count">未集計</span>件が対象です。</div></section>
<section id="comparison"><div class="section-head"><div><h2>3モデルの比較</h2><p class="subtle">実際に受領した独立原本だけを比較します。</p></div><span class="pill" id="contest-count">共通対象未集計</span></div><div class="grid comparison-grid" id="entrants"></div><div class="verdict"><strong>勝敗未判定</strong>同一入力・同一点数・同じ時点の予想を照合し、過去検証と未来の記録を分けて判断します。</div></section>
<section id="confidence"><div class="section-head"><div><h2>点数ごとの信頼度</h2><p class="subtle">選択した買い目全体の校正後確率。件数の少なさも判定に含めます。</p></div><div class="controls"><label class="sr-only" for="confidence-policy">信頼度の点数条件</label><select id="confidence-policy"></select></div></div><article class="card"><div class="grid confidence-grid" id="confidence-cells"></div><div class="confidence-foot"><span id="calibration-support">校正・監査を読み込み中</span><span>基準：90% / 80% / 60%。不足時は判定保留。</span></div><p class="caption" id="actual-ticket-note">固定点数別の検証です。</p><div class="policy-box"><div><h3>オッズ連動の提示は別集計</h3><p id="variable-status">未集計</p><p id="variable-detail"></p><p>オッズ帯の本命は予想時点で固定。全帯で1点提示が可能です。</p></div><div><div class="bands"><div class="band"><span>10倍以下</span><strong>最大2点</strong></div><div class="band"><span>10倍超〜20倍</span><strong>最大4点</strong></div><div class="band"><span>20倍超〜100倍未満</span><strong>最大9点</strong></div><div class="band"><span>100倍以上</span><strong>最大12点</strong></div></div><p>二車単は最大2点。オッズの時刻・払戻が未検証の結果から収益を推定しません。</p></div></div></article></section>
<section><div class="section-head"><div><h2>構成を変えた比較</h2><p class="subtle">構成比較は温度校正前。主結果は校正後。採用候補は選択期間で固定し、評価結果で選び直しません。</p></div></div><article class="card table-wrap"><table><thead><tr><th>構成</th><th class="num">三連単1点</th><th class="num">三連単4点</th><th class="num">二車単2点</th><th class="num">Log Loss</th></tr></thead><tbody id="ablation-body"></tbody></table></article></section>
<section id="evidence"><div class="section-head"><div><h2>資料と検証の条件</h2><p class="subtle">学習、候補選択、校正、監査、評価の期間を分けています。</p></div></div><div class="grid split-grid" id="splits"></div><div class="grid evidence-grid" ><article class="card"><h3>観測資料の収録状況</h3><div id="evidence-items" class="evidence-list"></div><p class="caption">集計未収録は、実測0件と区別します。上がりの半周タイムを最終1周に置き換えていません。</p></article><article class="card"><h3>この検証で確認できる範囲</h3><ul class="note-list"><li><b>過去資料から作った予測</b>当時の公開時刻と締切前保存は、この集計だけでは認証できません。</li><li><b>事故・同着・資料不足も件数を残す</b>一意の上位3着が確定したレースは、後位の事故があっても採点します。</li><li><b>未取得の物理量は未知のまま</b>最終1周・映像・気象・同時点のオッズは、それぞれの根拠と検証が必要です。</li></ul><div class="mini-grid"><div class="mini"><span class="label">読込資料のレース</span><span class="number" id="archive-count">未集計</span></div><div class="mini"><span class="label">特徴量</span><span class="number" id="feature-count">未集計</span></div><div class="mini"><span class="label">研究処理時間</span><span class="number" id="runtime">未集計</span></div></div></article></div><details><summary>固定したモデル・資料のSHA-256を確認</summary><p class="subtle">採用候補：<span id="chosen-candidate">未確定</span></p><div id="hashes"></div></details></section>
<div id="owner-root"></div><footer class="footer"><span>DT-R1 / 独立研究。未来の成績・収益・本番採用は未確認です。</span><span id="model-short">モデル未固定</span></footer></main>
'''


def _render(data):
    nonce = secrets.token_urlsafe(24)
    policy = ("default-src 'none'; base-uri 'none'; object-src 'none'; connect-src 'none'; "
              "form-action 'none'; frame-src 'none'; img-src data:; font-src 'none'; "
              f"script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'")
    owner_banner = ('<div class="owner-banner"><b>所有者用・買い目を含むローカル画面</b>'
                    'この版は公開用ではありません。予想原本の候補を追加表示しています。</div>'
                    if data['mode'] == 'owner_private' else '')
    body = BODY.replace('__OWNER_BANNER__', owner_banner)
    return ('<!doctype html>\n<html lang="ja"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<meta name="referrer" content="no-referrer">'
            f'<meta http-equiv="Content-Security-Policy" content="{escape(policy, quote=True)}">'
            '<title>DT-R1 研究レポート</title>'
            f'<style nonce="{escape(nonce, quote=True)}">{CSS}</style></head><body>{body}'
            f'<script type="application/json" id="report-data" nonce="{escape(nonce, quote=True)}">'
            f'{_json_for_script(data)}</script><script nonce="{escape(nonce, quote=True)}">'
            f'{JAVASCRIPT}</script></body></html>\n')


def render_report(report):
    """Render only allowlisted aggregate evidence; never copy private report rows."""
    return _render(_project(report))


def render_owner_report(report, private_forecasts):
    """Explicit local owner mode; its generated HTML contains private candidates."""
    data = _project(report)
    data.update(mode='owner_private', forecasts=_private_forecasts(private_forecasts))
    return _render(data)


def _write(content, output):
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def write_report(report, output):
    return _write(render_report(report), output)


def write_owner_report(report, private_forecasts, output):
    from .runtime import _private_path
    return _write(render_owner_report(report, private_forecasts), _private_path(output))
