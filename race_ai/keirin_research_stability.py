"""Current-method hypothesis stability, not a calibrated chance of winning.

Evaluate the entire pre-selection scenario universe. Adding tickets cannot
raise a grade. Historical official confidence and deadline gates are untouched.
"""
from collections import defaultdict
from datetime import datetime
from hashlib import sha256
import json
from math import log

GRADES = ['未評価', '低', '中', '高', '激アツ']
RULES_VERSION = 'evidence-scenario-stability-20261122'


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode()


def _clock(value):
    out = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if out.utcoffset() is None:
        raise ValueError('TIMEZONE_REQUIRED')
    return out


def _reason(code, message):
    return {'code': code, 'message': message, 'scenario_ids': []}


def _unassessed(market, message):
    return {'grade':'未評価', 'rank':0, 'market':market, 'metrics':None,
            'scope':'RESULT_UNREAD_HYPOTHESIS_STABILITY',
            'reasons':[_reason('ESSENTIAL_EVIDENCE_MISSING', message)],
            'official_pre_cutoff_assessment_created':False}


def _distribution(scenarios, arm, places):
    exact = {}
    for scenario in scenarios:
        weight = scenario.get('support_' + arm, scenario.get('relative_research_weight', 0))
        if not isinstance(weight, (int, float)) or weight < 0:
            raise ValueError('INVALID_SCENARIO_SUPPORT')
        triple = tuple(scenario['projected_3ren_tan'])
        exact[triple] = max(exact.get(triple, 0), weight)
    support = defaultdict(float)
    for triple, weight in exact.items():
        support[triple[:places]] += weight
    total = sum(support.values())
    if not total:
        return {}
    return {ticket: weight/total for ticket, weight in support.items()}


def assess_research_analysis(analysis, *, assessed_at=None):
    at = assessed_at or analysis['generated_at']
    if _clock(at) < _clock(analysis['generated_at']):
        raise ValueError('ASSESSMENT_BEFORE_CREATION')
    result = dict(schema='KEIRIN_RESULT_UNREAD_RESEARCH_COHERENCE_V1',
        rules_version=RULES_VERSION, race_id=analysis['race_id'], assessed_at=at,
        official_pre_cutoff_assessment_created=False, production_guard_modified=False,
        production_guard_bypassed=False, target_results_used=False,
        calibrated_probability=False,
        scope_label='全展開候補の安定度による暫定評価（的中率ではありません）',
        timing_label=analysis.get('timing_label'),
        source_discrepancies_disclosed=analysis.get('source_discrepancies') or [],
        limitations=[
            '実結果による精度検証は未実施。支持値や判定境界は未学習の判断規則です。',
            'AとBは同じ資料・展開候補を使うため、一致しても独立した予測の裏付けではありません。',
            '買い目を増やしても、この信頼度は上がりません。',
            '登録番号による落車・復帰履歴、時系列の近況、当日の気象・個別バンク適性は未確認です。',
            '出走表の統計更新時刻が不明のため、結果欄未参照でも厳密な事前検証とは扱いません。',
        ], evaluations={})
    missing = [x for x in analysis.get('missing_model_features', [])
               if x.startswith('riders.') or x == 'published_line_groups']
    essential_problem = bool(missing or analysis.get('line_warnings'))
    for arm in ('A', 'B'):
        for market, places in (('3t',3), ('2t',2)):
            key = arm + '_' + market
            scenarios = analysis.get(arm, {}).get('six_phase_scenarios') or []
            if not scenarios or essential_problem:
                text = ('並び・競走得点などの不足または未解決の資料差があり、信頼度は付けていません。'
                        if essential_problem else '展開候補を作る材料が不足しています。')
                result['evaluations'][key] = _unassessed(market, text)
                continue
            distribution = _distribution(scenarios, arm, places)
            other = _distribution(scenarios, 'B' if arm == 'A' else 'A', places)
            if not distribution:
                result['evaluations'][key] = _unassessed(market, '展開支持値が未算出です。')
                continue
            ranked = sorted(distribution, key=lambda t:(-distribution[t], t))
            top = ranked[0]
            concentration = distribution[top]
            other_top = min(other, key=lambda t:(-other[t], t)) if other else None
            same_top = top == other_top
            entropy = -sum(p*log(p) for p in distribution.values() if p > 0)
            normalized_entropy = entropy/log(len(distribution)) if len(distribution)>1 else 0
            # Uncalibrated, explicit thresholds for concentration of hypotheses,
            # never selection coverage or an implied probability of a race event.
            high = .40 if places == 3 else .55
            medium = .15 if places == 3 else .25
            rank = 3 if concentration >= high and same_top else 2 if concentration >= medium else 1
            if analysis.get('condition_evidence'):
                rank = min(rank, 2)
            reasons = [
                _reason('ENTIRE_CANDIDATE_POOL',
                    f'採用前の全{len(distribution)}通りを比較して判定。点数を増減しても評価は変わりません。'),
                _reason('UNTRAINED_STABILITY_RULE',
                    '出走表と展開仮説に基づく暫定評価です。過去の的中率から学習した予測確率ではありません。'),
                _reason('MAIN_ALTERNATIVE_STABILITY',
                    ('基礎重視と展開重視で最上位候補が一致しています。' if same_top else
                     '基礎重視と展開重視で最上位候補が分かれています。')),
                _reason('CANDIDATE_CONCENTRATION',
                    '別の展開にも候補が分散しており、絞り込みの根拠は弱めです。' if rank==1 else
                    '対抗展開も残るため、中心候補が崩れる条件を併記しています。' if rank==2 else
                    '複数の展開分岐で中心候補に支持が集まっています。ただし資料不足の影響は残ります。'),
                _reason('NO_UNSUPPORTED_HOT_GRADE',
                    '時系列の近況・状態確認・実結果による検証が不足しているため、激アツにはしていません。'),
            ]
            if analysis.get('condition_evidence'):
                reasons.append(_reason('CONDITION_CAUTION', '落車後の本人コメントに不確実性があるため、高以上を付けていません。'))
            result['evaluations'][key] = dict(
                grade=GRADES[rank], rank=rank, market=market, strategy='normal',
                metrics={'candidate_count':len(distribution),
                         'top_candidate':list(top),
                         'uncalibrated_support_concentration':concentration,
                         'normalized_support_entropy':normalized_entropy,
                         'A_B_top_candidate_agreement':same_top,
                         'selected_ticket_count_used_for_grade':False},
                reasons=reasons, scope='RESULT_UNREAD_HYPOTHESIS_STABILITY',
                official_pre_cutoff_assessment_created=False)
    result['universe_state']='EVIDENCE_SCENARIOS_EVALUATED'
    result['scenario_universe_sha256']=sha256(_canonical({arm:analysis.get(arm,{}).get('six_phase_scenarios',[]) for arm in ('A','B')})).hexdigest()
    return result
