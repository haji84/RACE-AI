"""Source-bound current research coherence, never a calibrated win chance.

Forward v4 measures the leading four triples over the whole independent market
pool, retaining the established thresholds and actual selected coverage.
Ticket count itself earns no bonus and is not capped by this assessment.
Historical official confidence and its deadline gates are untouched.
"""
from collections import defaultdict
from datetime import datetime
from hashlib import sha256
import json
from math import isfinite, log

from race_ai import keirin_confidence as confidence
from race_ai.keirin_nationwide_auto_generator import PHASES

GRADES = ['未評価', '低', '中', '高', '激アツ']
RULES_VERSION = 'evidence-scenario-stability-20261122'
FORWARD_RULES_VERSION = 'forward-research-coherence-20261122-v4'
FORWARD_TRIPLE_TOP_N = {'forward-research-coherence-20261122-v3': 6,
                      FORWARD_RULES_VERSION: 4}
LEGACY_FORWARD_RULES_VERSION = 'forward-scenario-stability-20261122-v2'
FORWARD_FAMILIES = {'HOLD': None, 'COUNTER': 'counterattack',
                    'FOLLOWER_PASS': 'follower_sashi', 'ATTACKER_FADE': 'pace_fade',
                    'LATE_FINISH': 'late_sprint'}


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


def _unassessed(market, message, *, code='ESSENTIAL_EVIDENCE_MISSING'):
    return {'grade':'未評価', 'rank':0, 'market':market, 'metrics':None,
            'scope':'RESULT_UNREAD_HYPOTHESIS_STABILITY',
            'reasons':[_reason(code, message)],
            'official_pre_cutoff_assessment_created':False}


def _distribution(scenarios, arm, places):
    exact = {}
    direct_pair = places == 2 and all('pair_support_' + arm in s for s in scenarios)
    for scenario in scenarios:
        weight = scenario.get('support_' + arm, scenario.get('relative_research_weight', 0))
        if direct_pair:
            weight = scenario.get('pair_support_' + arm, weight)
        if not isinstance(weight, (int, float)) or weight < 0:
            raise ValueError('INVALID_SCENARIO_SUPPORT')
        ticket = tuple(scenario['projected_3ren_tan'][:2] if direct_pair else scenario['projected_3ren_tan'])
        exact[ticket] = max(exact.get(ticket, 0), weight)
    support = defaultdict(float)
    for ticket, weight in exact.items():
        support[ticket[:places]] += weight
    total = sum(support.values())
    if not total:
        return {}
    return {ticket: weight/total for ticket, weight in support.items()}


def _assess_legacy_research_analysis(analysis, *, assessed_at=None):
    at = assessed_at or analysis['generated_at']
    if _clock(at) < _clock(analysis['generated_at']):
        raise ValueError('ASSESSMENT_BEFORE_CREATION')
    forward_method = analysis.get('method', {}).get('id') == 'forward-phase-independent-pair-selection-20261122'
    result = dict(schema='KEIRIN_RESULT_UNREAD_RESEARCH_COHERENCE_V1',
        rules_version=LEGACY_FORWARD_RULES_VERSION if forward_method else RULES_VERSION,
        race_id=analysis['race_id'], assessed_at=at,
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
            selection = analysis.get(arm, {}).get('selection', {}).get(market, {})
            abstained = selection.get('recommendation') == 'ABSTAIN_INSUFFICIENT_SEPARATION'
            if abstained:
                rank = 1
            concentration_reason = (
                '別の展開にも候補が分散しており、絞り込みの根拠は弱めです。' if rank==1 else
                '対抗展開も残るため、中心候補が崩れる条件を併記しています。' if rank==2 else
                '複数の展開分岐で中心候補に支持が集まっています。ただし資料不足の影響は残ります。')
            if forward_method:
                concentration_reason += (
                    f' 最上位1候補の支持比率は{concentration:.1%}。'
                    f'「高」の数値条件は{high:.0%}以上とA/Bの最上位候補一致、'
                    f'「中」は{medium:.0%}以上です。候補内の支持比率であり、的中率ではありません。')
            reasons = [
                _reason('ENTIRE_CANDIDATE_POOL',
                    f'採用前の全{len(distribution)}通りを比較して判定。点数を増減しても評価は変わりません。'),
                _reason('UNTRAINED_STABILITY_RULE',
                    '出走表と展開仮説に基づく暫定評価です。過去の的中率から学習した予測確率ではありません。'),
                _reason('MAIN_ALTERNATIVE_STABILITY',
                    ('基礎重視と展開重視で最上位候補が一致しています。' if same_top else
                     '基礎重視と展開重視で最上位候補が分かれています。')),
                _reason('CANDIDATE_CONCENTRATION',
                    concentration_reason),
                _reason('NO_UNSUPPORTED_HOT_GRADE',
                    'この方式では「高」までを判定し、既存の4段階評価の「激アツ」判定は未接続です。'
                    if forward_method else
                    '時系列の近況・状態確認・実結果による検証が不足しているため、激アツにはしていません。'),
            ]
            if analysis.get('condition_evidence'):
                reasons.append(_reason('CONDITION_CAUTION', '落車後の本人コメントに不確実性があるため、高以上を付けていません。'))
            if abstained:
                reasons.append(_reason('ABSTAIN_INSUFFICIENT_SEPARATION', '全候補が選別窓内に残り、絞る根拠が不足。買い目は見送りです。'))
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


def _forward_scenarios(scenarios):
    """Require actual saved six-phase orders; never invent missing branches."""
    if type(scenarios) is not list or not scenarios:
        raise ValueError('FORWARD_SCENARIOS_MISSING')
    ids, kinds, distinct = set(), set(), set()
    cars = None
    for scenario in scenarios:
        if type(scenario) is not dict:
            raise ValueError('FORWARD_SCENARIO_INVALID')
        sid, kind = scenario.get('scenario_id'), scenario.get('branch_kind')
        if type(sid) is not str or not sid or sid in ids:
            raise ValueError('FORWARD_SCENARIO_ID_INVALID')
        ids.add(sid)
        if type(kind) is not str or kind not in FORWARD_FAMILIES:
            raise ValueError('FORWARD_BRANCH_UNCONFIRMED')
        if scenario.get('known_line_hypothesis') is False:
            raise ValueError('FORWARD_LINE_EVIDENCE_MISSING')
        kinds.add(kind)
        phases = scenario.get('six_phases')
        if (type(phases) is not list or len(phases) != 6 or
                any(type(phase) is not dict for phase in phases) or
                [phase.get('phase') for phase in phases] != list(PHASES)):
            raise ValueError('SIX_PHASES_INCOMPLETE')
        for phase in phases:
            order = phase.get('projected_order')
            if (type(order) is not list or not 5 <= len(order) <= 9 or
                    any(type(car) is not int or not 1 <= car <= 9 for car in order) or
                    len(set(order)) != len(order)):
                raise ValueError('FORWARD_PHASE_ORDER_INVALID')
            if cars is None:
                cars = sorted(order)
            top3 = phase.get('projected_top3')
            if (sorted(order) != cars or type(top3) is not list or
                    any(type(car) is not int for car in top3) or top3 != order[:3] or
                    phase.get('actual_rider_position_video_verified') is not False or
                    phase.get('position_unknown') is True):
                raise ValueError('FORWARD_PHASE_ORDER_INVALID')
            actions = phase.get('hypothesis_actions')
            if (type(actions) is not list or not actions or
                    any(type(action) is not str or not action for action in actions)):
                raise ValueError('FORWARD_PHASE_EVIDENCE_MISSING')
        goal = scenario.get('projected_3ren_tan')
        if (type(goal) is not list or any(type(car) is not int for car in goal) or
                goal != phases[-1]['projected_order'][:3]):
            raise ValueError('FORWARD_PHASE_GOAL_MISMATCH')
        distinct.add(_canonical([[phase['projected_order'] for phase in phases],
                                 scenario['projected_3ren_tan']]))
    if len(distinct) < 2:
        raise ValueError('DISTINCT_SCENARIOS_REQUIRED')
    if 'HOLD' not in kinds or not (kinds - {'HOLD'}):
        raise ValueError('COUNTER_SCENARIO_REQUIRED')
    return cars


def _market_support(scenario, arm, places):
    key = ('pair_support_' if places == 2 else 'support_') + arm
    value = scenario.get(key)
    if type(value) not in (int, float) or not isfinite(value) or value <= 0:
        raise ValueError('FORWARD_MARKET_SUPPORT_MISSING_OR_INVALID')
    return value


def _selected_tickets(analysis, arm, places, cars):
    field = 'ranked_2ren_tan' if places == 2 else 'ranked_tickets'
    selected = analysis[arm].get(field)
    if type(selected) is not list:
        raise ValueError('FORWARD_SELECTED_TICKETS_MISSING')
    tickets = set()
    for ticket in selected:
        if (type(ticket) is not list or len(ticket) != places or
                any(type(car) is not int or car not in cars for car in ticket) or
                len(set(ticket)) != places or tuple(ticket) in tickets):
            raise ValueError('FORWARD_SELECTED_TICKETS_INVALID')
        tickets.add(tuple(ticket))
    return tickets


def _forward_metrics(scenarios, distribution, selected, arm, places, *, triple_top_n):
    """Use max-support outcomes and real branch representatives as denominator.

    A candidate carrying at least 10% is major. Its strongest actual source
    scenario represents it. The strongest scenario of each present counter
    family is also major. Direct pair support is used at every two-car step,
    so additional third-place variants cannot manufacture pair evidence.
    """
    winners, pairs = defaultdict(float), defaultdict(float)
    sources, families = defaultdict(list), defaultdict(list)
    for ticket, weight in distribution.items():
        winners[ticket[0]] += weight
        pairs[ticket[:2]] += weight
    for scenario in scenarios:
        ticket = tuple(scenario['projected_3ren_tan'][:places])
        sources[ticket].append(scenario)
        family = FORWARD_FAMILIES[scenario['branch_kind']]
        if family is not None:
            families[family].append(scenario)
    strongest = lambda rows: min(rows, key=lambda s: (-_market_support(s, arm, places), s['scenario_id']))
    major = {}
    for ticket, weight in distribution.items():
        if weight >= .10 - 1e-12:
            scenario = strongest(sources[ticket])
            major[scenario['scenario_id']] = ticket
    for rows in families.values():
        scenario = strongest(rows)
        major[scenario['scenario_id']] = tuple(scenario['projected_3ren_tan'][:places])
    axis = sorted(sorted(winners, key=lambda car: (-winners[car], car))[:2])
    share = lambda value: round(min(1.0, max(0.0, value)), 12)
    return dict(axis_cars=axis, axis_top2_share=share(sum(winners[car] for car in axis)),
        pair_top4_share=share(sum(sorted(pairs.values(), reverse=True)[:4])),
        **{f'triple_top{triple_top_n}_share':
           share(sum(sorted(distribution.values(), reverse=True)[:triple_top_n])) if places == 3 else None},
        scenario_coverage=share(sum(weight for ticket, weight in distribution.items() if ticket in selected)),
        major_scenario_ids=sorted(major),
        major_uncovered_ids=sorted(sid for sid, ticket in major.items() if ticket not in selected))


def assess_research_analysis(analysis, *, assessed_at=None):
    """Create the current research assessment; never rewrite a saved original."""
    if analysis.get('method', {}).get('id') != 'forward-phase-independent-pair-selection-20261122':
        return _assess_legacy_research_analysis(analysis, assessed_at=assessed_at)
    return _assess_forward_research_analysis(analysis, assessed_at=assessed_at,
                                           rules_version=FORWARD_RULES_VERSION)


def _assess_forward_research_analysis(analysis, *, assessed_at=None, rules_version):
    """Keep v3's explicit metric/reason contract available for historical replay."""
    if rules_version not in FORWARD_TRIPLE_TOP_N:
        raise ValueError('FORWARD_RULES_VERSION_UNSUPPORTED')
    triple_top_n = FORWARD_TRIPLE_TOP_N[rules_version]
    triple_share_field = f'triple_top{triple_top_n}_share'
    at = assessed_at or analysis['generated_at']
    if _clock(at) < _clock(analysis['generated_at']):
        raise ValueError('ASSESSMENT_BEFORE_CREATION')
    if analysis.get('source_as_of') and _clock(analysis['source_as_of']) > _clock(analysis['generated_at']):
        raise ValueError('SOURCE_CAPTURE_AFTER_GENERATION')
    result = dict(schema='KEIRIN_RESULT_UNREAD_RESEARCH_COHERENCE_V1',
        rules_version=rules_version, inherited_rules_version=confidence.RULES_VERSION,
        race_id=analysis['race_id'], assessed_at=at,
        official_pre_cutoff_assessment_created=False, production_guard_modified=False,
        production_guard_bypassed=False, target_results_used=False, calibrated_probability=False,
        scope_label='全展開候補と採用買い目の整合性による暫定評価（的中率ではありません）',
        timing_label=analysis.get('timing_label'),
        source_discrepancies_disclosed=analysis.get('source_discrepancies') or [],
        limitations=[
            '実結果による精度検証は未実施。支持値や判定境界は未学習の判断規則です。',
            'AとBは同じ資料・展開候補を使うため、一致しても独立した予測の裏付けではありません。',
            '点数そのものは加点しません。全候補を固定の分母として、採用買い目が残す支持比率と主要分岐を評価します。',
            '登録番号による落車・復帰履歴、時系列の近況、当日の気象・個別バンク適性は未確認です。',
            '出走表の統計更新時刻が不明のため、結果欄未参照でも厳密な事前検証とは扱いません。',
        ], evaluations={})
    missing = [value for value in analysis.get('missing_model_features', [])
               if value.startswith('riders.') or value == 'published_line_groups']
    essential_problem = bool(missing or analysis.get('line_warnings') or
                             analysis.get('line_status') == 'UNAVAILABLE')
    for arm in ('A', 'B'):
        for market, places in (('3t', 3), ('2t', 2)):
            key = arm + '_' + market
            scenarios = analysis.get(arm, {}).get('six_phase_scenarios') or []
            if essential_problem or not scenarios:
                result['evaluations'][key] = _unassessed(market,
                    '並び・競走得点などの不足または未解決の資料差があり、信頼度は付けていません。')
                continue
            try:
                cars = _forward_scenarios(scenarios)
                for scenario in scenarios:
                    _market_support(scenario, arm, places)
                selected = _selected_tickets(analysis, arm, places, cars)
            except (ValueError, TypeError, KeyError) as error:
                result['evaluations'][key] = _unassessed(market,
                    '6局面・分岐・券種別の支持値と買い目を確認できないため、評価を付けていません。',
                    code=str(error))
                continue
            selection = analysis[arm].get('selection', {}).get(market, {})
            abstained = selection.get('recommendation') == 'ABSTAIN_INSUFFICIENT_SEPARATION'
            if not selected and not abstained:
                result['evaluations'][key] = _unassessed(market,
                    '評価対象の買い目がないため、信頼度を付けていません。', code='EMPTY_TICKET_SET')
                continue
            distribution = _distribution(scenarios, arm, places)
            other_arm = 'B' if arm == 'A' else 'A'
            # Agreement is a diagnostic only, not an independent evidence gate.
            other_scenarios = analysis.get(other_arm, {}).get('six_phase_scenarios') or []
            try:
                for scenario in other_scenarios:
                    _market_support(scenario, other_arm, places)
                other = _distribution(other_scenarios, other_arm, places)
            except (ValueError, TypeError, KeyError):
                other = {}
            top = min(distribution, key=lambda ticket: (-distribution[ticket], ticket))
            other_top = min(other, key=lambda ticket: (-other[ticket], ticket)) if other else None
            entropy = -sum(weight * log(weight) for weight in distribution.values() if weight > 0)
            metrics = dict(candidate_count=len(distribution), top_candidate=list(top),
                uncalibrated_support_concentration=distribution[top],
                normalized_support_entropy=entropy / log(len(distribution)) if len(distribution) > 1 else 0,
                A_B_top_candidate_agreement=top == other_top,
                selected_ticket_count_used_for_grade=False,
                **_forward_metrics(scenarios, distribution, selected, arm, places,
                                   triple_top_n=triple_top_n))
            rank = confidence.grade_coherence_metrics(metrics, market,
                                                     triple_share_field=triple_share_field)
            reasons = [
                _reason('ENTIRE_CANDIDATE_POOL',
                    f'採用前の全{len(distribution)}通りを固定の分母に判定。点数そのものへの加点はありません。'),
                _reason('AXIS_GOAL_CONCENTRATION',
                    f'勝ち切り候補上位2車は「{"・".join(map(str, metrics["axis_cars"]))}」。全候補内の支持比率は{metrics["axis_top2_share"]:.1%}。的中率ではありません。'),
                _reason('PARTNER_GOAL_CONCENTRATION',
                    f'1・2着候補上位4組の支持比率は{metrics["pair_top4_share"]:.1%}。' +
                    (f'3着までの上位{triple_top_n}組は{metrics[triple_share_field]:.1%}。' if places == 3 else '') +
                    '採用前の全候補に対する比率です。'),
                _reason('FIXED_UNIVERSE_COVERAGE',
                    f'採用買い目が残す全候補内の支持比率は{metrics["scenario_coverage"]:.1%}。候補集合は買い目の増減で変えません。'),
                _reason('UNTRAINED_STABILITY_RULE',
                    '既存の4段階の暫定研究ルールを適用。実績から校正した的中率・回収率ではありません。'),
            ]
            if metrics['major_uncovered_ids']:
                reason = _reason('MAJOR_SCENARIO_UNCOVERED',
                    '全候補内の支持比率10%以上の筋、または各対抗分岐の最上位候補に未採用があるため、高以上にはしません。')
                reason['scenario_ids'] = list(metrics['major_uncovered_ids'])
                reasons.append(reason)
            gap = confidence._next_level_reason(metrics, market, rank,
                                                triple_share_field=triple_share_field)
            if gap is not None:
                reasons.append(gap)
            if analysis.get('condition_evidence'):
                rank = min(rank, 2)
                reasons.append(_reason('CONDITION_CAUTION',
                    '落車後の本人コメントに不確実性があるため、高以上を付けていません。'))
            if abstained:
                rank = 1
                reasons.append(_reason('ABSTAIN_INSUFFICIENT_SEPARATION',
                    '全候補が選別窓内に残り、絞る根拠が不足。買い目は見送りです。'))
            reasons.append(_reason('PROVISIONAL_RESEARCH_RULE',
                f'未校正の4段階研究ルールにより「{GRADES[rank]}」と判定しました。'))
            result['evaluations'][key] = dict(grade=GRADES[rank], rank=rank, market=market,
                strategy='normal', metrics=metrics, reasons=reasons,
                scope='RESULT_UNREAD_HYPOTHESIS_STABILITY',
                official_pre_cutoff_assessment_created=False)
    result['universe_state'] = 'EVIDENCE_SCENARIOS_EVALUATED'
    result['scenario_universe_sha256'] = sha256(_canonical({
        arm: analysis.get(arm, {}).get('six_phase_scenarios', []) for arm in ('A', 'B')})).hexdigest()
    return result
