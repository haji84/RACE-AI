"""Generate the current result-unread analysis from allowlisted pre-race facts.

Uses the evidence-driven processor in the canonical RACE-AI module. The
published daily packet is replaced in place. Real generation time and source
receipts are preserved; this never rewrites sealed pre-cutoff originals.
"""
from __future__ import annotations

import argparse
import copy
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import json
from math import isfinite
from pathlib import Path
import re
import subprocess
import sys
from unicodedata import normalize
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
MODEL_FILE = REPO / 'race_ai/keirin_nationwide_auto_generator.py'
MODEL_SHA256 = 'b30b7940cb054fc3225f109f1f35e70cab034c704e0d701937ded8309b8f5b47'
DAY = '2026-11-22'
JST = ZoneInfo('Asia/Tokyo')
STYLE_MAP = {'逃': 'NIGE', '両': 'ALLROUND', '追': 'MARK'}
PHASE_LABELS = {'INITIAL': '初周', 'BELL': '打鐘', 'FINAL_HOME': '最終ホーム',
                'FINAL_BACK': '最終バック', 'FOURTH_CORNER': '最終4角', 'GOAL': 'ゴール'}
ACTION_LABELS = {
    'PREDICTED_LINE_ORDER_ONLY': '掲載並びを置いた初周仮説。実際の位置取りは未確定',
    'LEADER_ATTACKS': '主導権候補が仕掛ける',
    'CHALLENGER_EARLY_COUNTER': '別線の先頭が早めに反撃する',
    'LEADER_TRIES_TO_HOLD_PACE': '主導権候補がペースを保つ',
    'LEADER_MAKURI_OR_KAMASHI': '主導権候補が捲り・カマシで前に出る',
    'CHALLENGER_MAKURI': '別線の先頭が捲る',
    'FRONT_LINE_CONTINUITY_UNVERIFIED': '先頭ラインの連続を仮定。追走成功は未確認',
    'FOLLOWER_SASHI_SCENARIO': '番手の差しを置く',
    'FOURTH_CORNER_ORDER_CONTINUES': '最終4角の順序が続く',
    'LATE_SPRINT_OVERTAKE': '終盤の加速で前を交わす',
    'FRONT_LEADER_PACE_FADE': '先頭の失速を置く',
}
FORBIDDEN_KEYS = {'result', 'results', 'payout', 'payouts', 'payoff', 'payoffs',
                  'finish_order', 'official_result', 'official_results',
                  'previous_race_result', 'recent_meets', 'current_meeting_results',
                  'settlement', 'settled', 'outcome', 'outcomes'}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return sha256(canonical(value)).hexdigest()


def need(condition, reason):
    if not condition:
        raise ValueError(reason)


def load_model():
    need(sha256(MODEL_FILE.read_bytes()).hexdigest() == MODEL_SHA256,
         'PINNED_MODEL_SOURCE_CHANGED')
    spec = importlib.util.spec_from_file_location('pinned_keirin_analysis_core', MODEL_FILE)
    model = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(model)
    return model


def check_no_result_fields(value):
    if isinstance(value, dict):
        need(not (FORBIDDEN_KEYS & set(value)), 'RESULT_FIELD_PRESENT_IN_INPUT')
        for child in value.values():
            check_no_result_fields(child)
    elif isinstance(value, list):
        for child in value:
            check_no_result_fields(child)


def instant(raw):
    need(isinstance(raw, str), 'SOURCE_TIME_MISSING')
    value = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    need(value.utcoffset() is not None, 'SOURCE_TIME_MUST_INCLUDE_TIMEZONE')
    return value.astimezone(timezone.utc)


def source_url(value):
    need(isinstance(value, str), 'SOURCE_URL_MISSING')
    parsed = urlsplit(value)
    need(parsed.scheme == 'https' and parsed.hostname and not parsed.username
         and not parsed.password and not parsed.fragment, 'SOURCE_URL_INVALID')
    return value


def person_key(value):
    # Only these observed ordinary character variants are normalized. This is
    # a race/car/name cross-check, never an official registration attestation.
    return re.sub(r'[\s\u3000]+', '', normalize('NFKC', str(value))).translate(
        str.maketrans({'眞': '真', '齋': '斎', '邊': '辺'}))


def net_name_match_kind(name, source_names, metadata=None):
    if not isinstance(source_names, list) or not source_names:
        return None
    expected = person_key(name)
    if any(expected in person_key(raw) for raw in source_names if isinstance(raw, str)):
        return 'CAR_AND_FULL_NAME_CONFIRMED'
    # A source may truncate a full name (observed: アニー紗世 vs アニー紗世子).
    # Admit only a 1–2-character suffix truncation, plus matching prefecture,
    # age and registration cohort. This remains below official-ID verification.
    if not isinstance(metadata, dict):
        return None
    text = ' '.join(raw for raw in source_names if isinstance(raw, str))
    joined = person_key(text)
    tokens = [person_key(token) for token in text.split()]
    prefix_match = any(len(token) >= 3 and 1 <= len(expected) - len(token) <= 2
                       and expected.startswith(token) for token in tokens)
    age, term, prefecture = metadata.get('age'), metadata.get('term'), metadata.get('prefecture')
    metadata_match = (type(age) is int and type(term) is int and
                      f'{age}歳' in joined and f'{term}期' in joined and
                      isinstance(prefecture, str) and len(prefecture) >= 2 and
                      person_key(prefecture)[:2] in joined)
    return 'CAR_ABBREVIATED_NAME_PREFECTURE_AGE_TERM_MATCH' if prefix_match and metadata_match else None


def net_name_matches(name, source_names, metadata=None):
    return net_name_match_kind(name, source_names, metadata) is not None


def merge_supplements(row, net=None, secondary=None):
    value = copy.deepcopy(row)
    cars = {rider['number'] for rider in value['riders']}
    value.setdefault('source_discrepancies', [])
    value.setdefault('supplemental_sources', [])
    if net is not None:
        check_no_result_fields(net)
        need(net.get('race_id') == row['race_id'] and net.get('target_results_referenced') is False,
             'NET_TARGET_OR_RESULT_POLICY_INVALID')
        need(net.get('http_status') == 200 and isinstance(net.get('riders'), list), 'NET_SOURCE_UNAVAILABLE')
        source_url(net.get('source_url'))
        instant(net.get('captured_at'))
        need(re.fullmatch('[a-f0-9]{64}', str(net.get('source_sha256', ''))), 'NET_SOURCE_DIGEST_MISSING')
        net_riders = {rider['number']: rider for rider in net['riders']}
        need(len(net_riders) == len(net['riders']) == len(cars) and set(net_riders) == cars,
             'NET_ROSTER_MISMATCH')
        statistics = ('score', 'style', 'S', 'H', 'B', 'nige', 'makuri', 'sashi', 'mark',
                      'wins', 'seconds', 'thirds', 'unplaced', 'win_rate', 'top2_rate', 'top3_rate', 'gear')
        for rider in value['riders']:
            observed = net_riders[rider['number']]
            identity_kind = net_name_match_kind(rider['name'], observed.get('source_names'), rider)
            need(identity_kind is not None, 'NET_NAME_AND_ROSTER_METADATA_MISMATCH')
            before = {key: rider.get(key) for key in (*statistics, 'source_tip')}
            differences = {key: {'kdreams': rider.get(key), 'netkeirin': observed.get(key)}
                           for key in statistics if rider.get(key) is not None and
                           observed.get(key) is not None and rider.get(key) != observed.get(key)}
            if differences:
                value['source_discrepancies'].append({'car': rider['number'], 'fields': differences,
                    'choice': 'NETKEIRIN_SINGLE_PROVIDER_STATISTICS_NO_AVERAGING'})
            rider['kdreams_observed_statistics'] = before
            for key in statistics:
                # Do not mix providers when one field is missing: the selected
                # statistical vector is exactly the secondary provider's vector.
                rider[key] = observed.get(key)
            rider.setdefault('field_sources', {})['statistics'] = net['source_url']
            rider['field_sources']['H'] = net['source_url']
            rider['netkeirin_source_tip'] = observed.get('source_tip')
            net_mark = mark_rank(observed.get('source_tip'), len(cars))
            if net_mark not in (None, 'UNMARKED'):
                rider['source_tip'] = observed['source_tip']
                rider['field_sources']['source_tip'] = net['source_url']
            else:
                rider['source_tip'] = before.get('source_tip')
                rider['field_sources']['source_tip'] = row['source_url']
            if not rider.get('comment') and observed.get('comment'):
                rider['comment'] = observed['comment']
                rider['field_sources']['comment'] = net['source_url']
            rider['name_crosscheck'] = identity_kind
        value['supplemental_sources'].append({key: net.get(key) for key in
            ('source_url', 'captured_at', 'http_status', 'source_sha256')})
        value['netkeirin_statistics_selected'] = True
    if secondary is not None:
        check_no_result_fields(secondary)
        need(secondary.get('race_id') == row['race_id'] and secondary.get('date') == DAY
             and secondary.get('target_results_excluded') is True, 'SECONDARY_TARGET_OR_RESULT_POLICY_INVALID')
        source_url(secondary.get('source_url'))
        comments = secondary.get('comments') or []
        comments_by_car = {comment['car']: comment for comment in comments}
        need(len(comments_by_car) == len(comments) and set(comments_by_car) <= cars,
             'SECONDARY_COMMENT_ROSTER_MISMATCH')
        for rider in value['riders']:
            comment = comments_by_car.get(rider['number'])
            if comment:
                need(person_key(comment.get('name')) == person_key(rider['name']), 'SECONDARY_COMMENT_NAME_MISMATCH')
                need(isinstance(comment.get('comment'), str), 'SECONDARY_COMMENT_INVALID')
                rider['comment'] = comment['comment']
                rider.setdefault('field_sources', {})['comment'] = secondary['source_url']
        value['line_hypotheses'] = secondary.get('line_hypotheses') or []
        value['secondary_lines'] = secondary.get('lines')
        value['secondary_source_kind'] = secondary.get('source_kind')
        receipt = secondary.get('source_receipt') or {}
        value['supplemental_sources'].append({'source_url': secondary['source_url'],
            'captured_at': receipt.get('captured_at'), 'http_status': receipt.get('http_status'),
            'source_sha256': receipt.get('sha256')})
    return value


def safe_merge_supplements(row, net=None, secondary=None):
    value = copy.deepcopy(row)
    rejected = []
    for kind, supplement in (('net', net), ('secondary', secondary)):
        if supplement is None:
            continue
        try:
            value = merge_supplements(value, **{kind: supplement})
        except (ValueError, TypeError, KeyError) as error:
            rejected.append({'kind': kind, 'reason': str(error)[:160],
                             'source_url': supplement.get('source_url')})
    value['rejected_supplements'] = rejected
    return value


def numeric(value, low, high, *, integer=False):
    if value is None:
        return None
    need(type(value) in (int, float) and isfinite(value) and low <= value <= high,
         'SOURCE_NUMERIC_FIELD_OUT_OF_RANGE')
    if integer:
        need(type(value) is int, 'SOURCE_COUNT_MUST_BE_INTEGER')
    return value


def mark_rank(raw, count):
    if raw is None:
        return None
    need(isinstance(raw, str), 'SOURCE_MARK_MUST_BE_TEXT')
    value = normalize('NFKC', raw).strip()
    if value in ('', '--', '-', '100', '消', '無', '未選択'):
        return 'UNMARKED'
    if value in ('◎', '本命'):
        return 1
    if value in ('○', '◯', '対抗'):
        return 2
    if value in ('▲', '単穴'):
        return 3
    if value in ('△', '☆', '注', '×', '✕', '押'):
        return 4
    if value.isdecimal() and 1 <= int(value) <= count:
        return int(value)
    return None


def checked_groups(value, cars):
    if not isinstance(value, list) or not value:
        return None
    if not all(isinstance(group, list) and group and
               all(type(car) is int for car in group) for group in value):
        return None
    flat = [car for group in value for car in group]
    return value if len(flat) == len(set(flat)) == len(cars) and set(flat) == set(cars) else None


def normalized_riders(row):
    riders = row.get('riders')
    need(isinstance(riders, list) and 5 <= len(riders) <= 9, 'INCOMPLETE_ROSTER')
    normalized = []
    for rider in riders:
        need(isinstance(rider, dict), 'RIDER_OBJECT_REQUIRED')
        car = rider.get('number', rider.get('car'))
        need(type(car) is int and 1 <= car <= 9, 'INVALID_CAR')
        need(isinstance(rider.get('name'), str) and rider['name'].strip(), 'RIDER_NAME_MISSING')
        athlete = rider.get('registration_number')
        need(athlete is None or isinstance(athlete, str) and re.fullmatch('[0-9]{4,8}', athlete),
             'OFFICIAL_REGISTRATION_INVALID')
        if athlete is not None:
            source_url(rider.get('registration_source'))
        style = normalize('NFKC', str(rider.get('style') or ''))
        parsed_style = next((mapped for label, mapped in STYLE_MAP.items() if label in style), 'UNKNOWN')
        score = numeric(rider.get('score', rider.get('competition_points')), 0, 150)
        win = numeric(rider.get('win_rate'), 0, 100)
        recent = None  # Published four-month win rate is NOT a recent-form trend.
        if score == 0:
            score = None  # Zero is unverified, not evidence of the weakest rider.
        normalized.append(dict(car=car, athlete_id=athlete,
            mark_rank=mark_rank(rider.get('source_tip'), len(riders)),
            competition_points=score, recent_form_score=recent,
            h_count=numeric(rider.get('H'), 0, 99, integer=True),
            b_count=numeric(rider.get('B'), 0, 99, integer=True), style=parsed_style,
            number=car, name=rider['name'], score=score, win_rate=win,
            top2_rate=numeric(rider.get('top2_rate'), 0, 100),
            top3_rate=numeric(rider.get('top3_rate'), 0, 100),
            S=numeric(rider.get('S'), 0, 99, integer=True),
            nige=numeric(rider.get('nige'), 0, 99, integer=True),
            makuri=numeric(rider.get('makuri'), 0, 99, integer=True),
            sashi=numeric(rider.get('sashi'), 0, 99, integer=True),
            mark=numeric(rider.get('mark'), 0, 99, integer=True),
            gear=rider.get('gear'), comment=rider.get('comment'),
            field_sources=copy.deepcopy(rider.get('field_sources') or {})))
    cars = [r['car'] for r in normalized]
    need(len(cars) == len(set(cars)), 'DUPLICATE_CAR')
    registrations = [r['athlete_id'] for r in normalized if r['athlete_id']]
    need(len(registrations) == len(set(registrations)), 'DUPLICATE_OFFICIAL_REGISTRATION')
    return sorted(normalized, key=lambda r: r['car'])


def resolve_lines(row, riders):
    cars = [r['car'] for r in riders]
    source_riders = row['riders']
    girls = all(normalize('NFKC', str(r.get('class', ''))).startswith('L') for r in source_riders)
    if girls:
        return [[car] for car in cars], 'GIRLS_INDIVIDUAL_POSITIONS', [], []
    hypotheses = row.get('line_hypotheses') or []
    checked_hypotheses = []
    for hypothesis in hypotheses:
        groups = checked_groups(hypothesis.get('groups'), cars)
        evidence = hypothesis.get('evidence')
        if groups and isinstance(evidence, list) and evidence:
            source_url(hypothesis.get('source_url'))
            need(all(isinstance(item, dict) and item.get('car') in cars and
                     isinstance(item.get('comment'), str) and item['comment'].strip()
                     for item in evidence), 'LINE_COMMENT_EVIDENCE_MISSING')
            checked_hypotheses.append(hypothesis)
    if checked_hypotheses:
        primary = checked_hypotheses[0]
        status = ('PUBLISHED_SECONDARY_PREDICTION'
                  if primary.get('kind') == 'PUBLISHED_PRE_RACE_LINEUP_WITH_COMMENTS'
                  else 'SOURCED_COMMENT_HYPOTHESIS')
        return primary['groups'], status, checked_hypotheses, []
    details = checked_groups(row.get('lines'), cars)
    meeting = checked_groups(row.get('listed_lines'), cars)
    conflicts = []
    if details and meeting and details != meeting:
        conflicts.append('詳細出走表と開催一覧の並びが不一致。詳細出走表を条件付き仮説に使用。')
    if details:
        return details, 'PUBLISHED_PREDICTION', [], conflicts
    if meeting:
        return meeting, 'PUBLISHED_MEETING_PREDICTION', [], conflicts
    return None, 'UNAVAILABLE', [], ['並び未取得のためBの6局面は未生成。']


def check_tickets(tickets, cars, length):
    physical_max = 1
    for offset in range(length):
        physical_max *= len(cars) - offset
    need(isinstance(tickets, list) and 1 <= len(tickets) <= physical_max and
         all(isinstance(ticket, list) and len(ticket) == length and
             len(set(ticket)) == length and all(car in cars for car in ticket) for ticket in tickets)
         and len({tuple(ticket) for ticket in tickets}) == len(tickets), 'INVALID_ANALYSIS_TICKETS')


def analyze(row, model, generated_at, observations=None):
    check_no_result_fields(row)
    need(row.get('date') == DAY and re.fullmatch(DAY.replace('-', '') + '[0-9]{4}', str(row.get('race_id', ''))),
         'WRONG_RACE_DATE_OR_ID')
    need(row.get('venue_code') == row['race_id'][8:10] and
         type(row.get('race_no')) is int and row['race_no'] == int(row['race_id'][10:]),
         'VENUE_OR_RACE_NUMBER_MISMATCH')
    need(row.get('no_today_results_used') is True and row.get('current_meeting_results_excluded') is True,
         'RESULT_EXCLUSION_NOT_ATTESTED_BY_COLLECTOR')
    source_url(row.get('source_url'))
    collected_at = max([instant(row.get('fetched_at'))] +
                       [instant(source['captured_at']) for source in row.get('supplemental_sources', [])
                        if source.get('captured_at')])
    generated = instant(generated_at)
    need(collected_at <= generated, 'SOURCE_CAPTURE_AFTER_GENERATION')
    need(re.fullmatch('[a-f0-9]{64}', str(row.get('source_sha256', ''))), 'SOURCE_DIGEST_MISSING')
    receipt = row.get('source_receipt')
    need(isinstance(receipt, dict) and receipt.get('http_status') == 200 and
         receipt.get('url') == row['source_url'] and receipt.get('sha256') == row['source_sha256'] and
         receipt.get('captured_at') == row['fetched_at'], 'SOURCE_RECEIPT_MISMATCH')
    riders = normalized_riders(row)
    cars = [rider['car'] for rider in riders]
    lines, line_status, line_hypotheses, line_warnings = resolve_lines(row, riders)
    cutoff_text = row.get('deadline_time')
    cutoff = None
    if cutoff_text is not None:
        need(re.fullmatch(r'(?:[01]?[0-9]|2[0-3]):[0-5][0-9]', cutoff_text), 'INVALID_CUTOFF_TEXT')
        hour, minute = map(int, cutoff_text.split(':'))
        cutoff = datetime.fromisoformat(f'{DAY}T{hour:02}:{minute:02}:00').replace(tzinfo=JST)
    after = generated >= cutoff if cutoff else None
    condition = []
    names = {rider['car']: rider['name'] for rider in riders}
    for observation in observations or []:
        if observation.get('race_id') != row['race_id']:
            continue
        need(observation.get('car') in names and
             person_key(names[observation['car']]) == person_key(observation.get('name')),
             'CONDITION_COMMENT_IDENTITY_MISMATCH')
        source_url(observation.get('source_url'))
        at = instant(observation.get('captured_at'))
        need(at <= generated, 'CONDITION_EVIDENCE_AFTER_GENERATION')
        collected_at = max(collected_at, at)
        condition.append({key: observation[key] for key in (
            'race_id', 'car', 'name', 'fact', 'judgement', 'possible_ticket_impact',
            'evidence_type', 'source_url', 'captured_at') if key in observation})
    snapshot = {'race_id': row['race_id'], 'riders': riders, 'line_groups': lines,
                'line_warnings': line_warnings, 'round_rule': None,
                'condition_evidence': condition,
                'competition': 'GIRLS' if line_status == 'GIRLS_INDIVIDUAL_POSITIONS' else 'OTHER'}
    revised = model.generate_evidence_analysis(snapshot)
    A, B = revised['A'], revised['B']
    for arm in (A, B):
        if arm.get('state') == 'GENERATED_RESEARCH_ONLY':
            check_tickets(arm['ranked_tickets'], cars, 3)
            check_tickets(arm['ranked_2ren_tan'], cars, 2)
        for scenario in arm.get('six_phase_scenarios', []):
            need([phase['phase'] for phase in scenario['six_phases']] == list(model.PHASES),
                 'SIX_PHASES_MISSING')
            for phase in scenario['six_phases']:
                need((phase['projected_order'] is None and lines is None and phase['phase'] != 'GOAL') or
                     (set(phase['projected_order']) == set(cars) and len(phase['projected_order']) == len(cars)),
                     'SCENARIO_ROSTER_MISMATCH')
    strength_mode = 'EVIDENCE_DRIVEN_SCENARIO_SELECTION'
    missing = [f"riders.{r['car']}.competition_points" for r in riders
               if r['competition_points'] is None]
    missing.extend(['verified_recent_form_trend', 'registered_fall_and_return_history',
                    'race_time_weather', 'bank_specific_rider_performance',
                    'evidenced_advancement_rule'])
    if lines is None:
        missing.append('published_line_groups')
    form = []
    for source_rider in row['riders']:
        form.append({'car': source_rider['number'], 'name': source_rider['name'],
            'registration_number': source_rider.get('registration_number'),
            'confirmed_facts': {'comment': source_rider.get('comment'),
                'comment_source': (source_rider.get('field_sources') or {}).get('comment'),
                'fall_record': None, 'rest_period': None, 'return_performance': None},
            'condition_assessment': '判断材料不足',
            'reason': '落車・欠場・休養・復帰後成績を登録番号と出典で照合した履歴が未取得。',
            'prediction_effect': '調子・落車による補正は未適用。怪我なし・好調と仮定していません。'})
    output = {'schema': 'KEIRIN_RESULT_UNREAD_RESEARCH_ANALYSIS_V1',
        'race_id': row['race_id'], 'date': DAY, 'venue': row['venue'],
        'venue_code': row.get('venue_code'), 'race_no': row['race_no'],
        'race_title': row.get('race_title'), 'start_time': row.get('start_time'),
        'deadline_time': cutoff_text, 'published_cutoff_at': cutoff.isoformat() if cutoff else None,
        'generated_at': generated_at, 'source_captured_at': row['fetched_at'],
        'source_as_of': collected_at.isoformat(),
        'created_after_published_cutoff': after,
        'timing_label': ('締切後作成・結果欄未参照の参考分析' if after else
                         '締切前作成・未検証の参考分析' if after is False else
                         '締切未確認・結果欄未参照の参考分析'),
        'formal_pre_cutoff_saved_forecast': False, 'original_production_guard_modified': False,
        'target_result_fields_read': False, 'pre_cutoff_source_snapshot_verified': False,
        'statistics_update_at_unknown': True,
        'source_snapshot_limit': '結果・払戻・当開催着順欄は取得対象外。出走表の4ヶ月統計が当日何時に更新されたかは未確認。締切前スナップショットではありません。',
        'source_url': row['source_url'], 'source_sha256': row['source_sha256'],
        'source_receipt': row.get('source_receipt'), 'input_sha256': digest(row),
        'supplemental_sources': row.get('supplemental_sources', []),
        'source_discrepancies': row.get('source_discrepancies', []),
        'rejected_supplements': row.get('rejected_supplements', []),
        'model_source_sha256': MODEL_SHA256, 'strength_mode': strength_mode,
        'method': revised.get('method'), 'feature_audit': revised.get('feature_audit'),
        'missing_model_features': missing,
        'observed_riders': row['riders'], 'normalized_riders': riders,
        'observed_detail_lines': row.get('lines'), 'observed_meeting_lines': row.get('listed_lines'),
        'analysis_lines': lines, 'line_status': line_status,
        'line_hypotheses': line_hypotheses, 'line_warnings': line_warnings,
        'A': A, 'B': B,
        'C': {'state': 'UNGENERATED_NO_VERIFIED_HISTORICAL_FOLLOW_LABELS', 'ranked_tickets': [],
              'ranked_2ren_tan': [], 'point_count_3t': 0, 'point_count_2t': 0,
              'confidence': '未評価', 'reason': '独立して検証された連係履歴が未接続。',
              'reconciliation': {'state': 'RESULT_NOT_READ', 'official_result': None, 'hit': None, 'payout': None}},
        'form_and_fall': form, 'form_adjustment_applied': False,
        'phase_labels': PHASE_LABELS, 'action_labels': ACTION_LABELS,
        'calibrated_probabilities': False, 'wager_placed': False}
    output['analysis_sha256'] = digest(output)
    return output


def apply_condition_observations(analysis, observations):
    """Keep source facts and explicit conditional caution separate from baseline."""
    if not observations:
        return analysis
    selected = [row for row in observations if row.get('race_id') == analysis['race_id']]
    accepted = []
    people = {row['car']: row for row in analysis['form_and_fall']}
    for observation in selected:
        person = people.get(observation.get('car'))
        need(person is not None and person_key(person['name']) == person_key(observation.get('name')),
             'CONDITION_COMMENT_IDENTITY_MISMATCH')
        source_url(observation.get('source_url'))
        need(instant(observation.get('captured_at')) <= instant(analysis['generated_at']),
             'CONDITION_EVIDENCE_AFTER_GENERATION')
        for key in ('fact', 'judgement', 'possible_ticket_impact', 'evidence_type'):
            need(isinstance(observation.get(key), str) and observation[key].strip(),
                 'CONDITION_FACT_JUDGEMENT_OR_IMPACT_MISSING')
        safe = {key: observation[key] for key in
                ('car', 'name', 'fact', 'judgement', 'possible_ticket_impact',
                 'evidence_type', 'source_url', 'captured_at')}
        accepted.append(safe)
        person['confirmed_facts']['published_self_report'] = safe['fact']
        person['confirmed_facts']['self_report_source'] = safe['source_url']
        person['confirmed_facts']['independently_verified_accident_record'] = False
        person['condition_assessment'] = safe['judgement']
        person['reason'] = '本人発言として確認。登録番号に基づく事故記録・休養期間・復帰後成績の独立照合は未完了。'
        person['prediction_effect'] = safe['possible_ticket_impact']
    analysis['condition_evidence'] = accepted
    # Apply only an explicit, sourced current-pain observation. This is a
    # sensitivity condition, not a diagnosis or an invented injury multiplier.
    cautions = [item for item in accepted if '痛み' in item['fact'] and
                not any(term in item['fact'] for term in ('痛みはない', '痛みなし', '痛みがない'))]
    caution = cautions[0] if cautions else None
    affected_cars = {item['car'] for item in cautions}
    affected_label = '・'.join(str(car) + '番' for car in sorted(affected_cars))
    if caution:
        original_tickets = {arm: {key: copy.deepcopy(analysis[arm].get(key, []))
                            for key in ('ranked_tickets', 'ranked_2ren_tan')} for arm in ('A', 'B')}
        sidecar = {'state': 'CONDITIONAL_CAUTION_REFERENCE_ONLY', 'generated_at': analysis['generated_at'],
            'affected_car': caution['car'], 'affected_name': caution['name'],
            'assumption': f'本人が述べた痛みが今回の走りにも影響する場合、{affected_label}の1着を条件から外す。',
            'fact': caution['fact'], 'judgement': caution['judgement'],
            'source_url': caution['source_url'],
            'baseline_tickets_preserved': True, 'numeric_injury_multiplier_used': False,
            'official_registration_verified': False, 'medical_diagnosis_made': False,
            'target_results_used': False, 'confidence': '未評価',
            'scope': '本人コメントに基づく条件付きの慎重案。影響の強さや確率を実証した補正式ではありません。'}
        for arm in ('A', 'B'):
            original3, original2 = original_tickets[arm]['ranked_tickets'], original_tickets[arm]['ranked_2ren_tan']
            retained3 = [ticket for ticket in original3 if ticket[0] not in affected_cars]
            retained2 = [ticket for ticket in original2 if ticket[0] not in affected_cars]
            sidecar[arm] = {'state': 'GENERATED_CONDITIONAL_REFERENCE' if (retained3 or retained2) else 'NO_TICKETS_UNDER_CONDITION',
                'ranked_tickets': retained3, 'ranked_2ren_tan': retained2,
                'removed_3t': [ticket for ticket in original3 if ticket[0] in affected_cars],
                'removed_2t': [ticket for ticket in original2 if ticket[0] in affected_cars],
                'point_count_3t': len(retained3), 'point_count_2t': len(retained2),
                'original_point_count_3t': len(original3), 'original_point_count_2t': len(original2),
                'original_tickets_sha256': digest(original_tickets[arm]),
                'reconciliation': {'state': 'RESULT_NOT_READ', 'official_result': None, 'hit': None, 'payout': None}}
        need(all(analysis[arm][key] == original_tickets[arm][key]
                 for arm in ('A', 'B') for key in ('ranked_tickets', 'ranked_2ren_tan')),
             'BASELINE_CHANGED_BY_CAUTION_SIDECAR')
        analysis['condition_adjusted'] = sidecar
        analysis['form_adjustment_applied'] = False
        analysis['separate_condition_caution_created'] = True
    return analysis


def confidence_helper():
    # Direct CLI execution exposes scripts/, not the repository package root.
    # Resolve the existing shared research rule in an isolated Python process.
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    path = REPO / 'race_ai/keirin_research_stability.py'
    spec = importlib.util.spec_from_file_location('result_unread_confidence_helper', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def method_check(model):
    """Synthetic contract check; no real race outcomes or historical clocks."""
    riders = [dict(car=n, number=n, athlete_id=None, mark_rank=n,
                   competition_points=90-n, win_rate=20-n, top2_rate=40-n,
                   top3_rate=55-n, h_count=n, b_count=2*n, S=n,
                   nige=3 if n in (1,4) else 0, makuri=1, sashi=1, mark=1,
                   gear='3.92', comment=None,
                   style='NIGE' if n in (1,4) else 'MARK') for n in range(1,8)]
    output = model.generate_evidence_analysis({'race_id':'209901016201',
        'riders':riders, 'line_groups':[[1,2,3],[4,5],[6,7]],
        'line_warnings':[], 'condition_evidence':[]})
    for arm in ('A','B'):
        check_tickets(output[arm]['ranked_tickets'], list(range(1,8)), 3)
        check_tickets(output[arm]['ranked_2ren_tan'], list(range(1,8)), 2)
    output.update(race_id='209901016201', generated_at='2099-01-01T01:00:00+09:00',
                  missing_model_features=[], line_warnings=[], condition_evidence=[])
    assessment = confidence_helper().assess_research_analysis(output)
    need(set(assessment['evaluations']) == {'A_3t','A_2t','B_3t','B_2t'} and
         all(entry['rank'] > 0 for entry in assessment['evaluations'].values()),
         'SYNTHETIC_CONFIDENCE_CONTRACT_FAILED')
    return {'synthetic_method_contract':'passed', 'synthetic_confidence_contract':'passed',
            'real_results_read':False}


def main():
    global DAY
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-commit', help='Verified remote commit for the pinned source')
    parser.add_argument('--date', default=DAY, help='Target calendar date in Asia/Tokyo')
    parser.add_argument('--input', '--inputs', dest='input', nargs='+', type=Path)
    parser.add_argument('--net', type=Path)
    parser.add_argument('--secondary', type=Path)
    parser.add_argument('--condition', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--self-check', action='store_true')
    args = parser.parse_args()
    need(bool(re.fullmatch(r'20[0-9]{2}-[0-9]{2}-[0-9]{2}', args.date)), 'TARGET_DATE_INVALID')
    datetime.strptime(args.date, '%Y-%m-%d')
    DAY = args.date
    model = load_model()
    if args.self_check:
        print(json.dumps(method_check(model)))
        return
    need(args.input and args.output, 'INPUT_AND_OUTPUT_REQUIRED')
    need(not args.output.exists(), 'OUTPUT_ALREADY_EXISTS_KEEP_ORIGINAL')
    rows = {}
    input_files = []
    for path in args.input:
        raw = path.read_bytes()
        data = json.loads(raw)
        selected = data.get('races', [data]) if isinstance(data, dict) else data
        need(isinstance(selected, list), 'INPUT_RACES_LIST_REQUIRED')
        for row in selected:
            check_no_result_fields(row)
            race_id = row.get('race_id')
            need(race_id not in rows, 'DUPLICATE_INPUT_RACE')
            rows[race_id] = row
        input_files.append({'name': path.name, 'sha256': sha256(raw).hexdigest()})
    supplements = {}
    for kind, path in (('net', args.net), ('secondary', args.secondary)):
        if path is None:
            supplements[kind] = {}
            continue
        raw = path.read_bytes()
        data = json.loads(raw)
        selected = data.get('races')
        need(isinstance(selected, list), 'SUPPLEMENT_RACES_LIST_REQUIRED')
        indexed = {row['race_id']: row for row in selected}
        need(len(indexed) == len(selected), 'SUPPLEMENT_DUPLICATE_RACE')
        supplements[kind] = indexed
        input_files.append({'name': path.name, 'sha256': sha256(raw).hexdigest()})
    observations = []
    if args.condition:
        raw = args.condition.read_bytes()
        data = json.loads(raw)
        need(data.get('date') == DAY and isinstance(data.get('observations'), list),
             'CONDITION_INPUT_SCHEMA_INVALID')
        observations = data['observations']
        input_files.append({'name': args.condition.name, 'sha256': sha256(raw).hexdigest()})
    generated_at = datetime.now(timezone.utc).isoformat()
    assessment = confidence_helper()
    predictions, errors = [], []
    for race_id, row in sorted(rows.items()):
        try:
            row = safe_merge_supplements(row, supplements['net'].get(race_id), supplements['secondary'].get(race_id))
            analysis = analyze(row, model, generated_at, observations)
            apply_condition_observations(analysis, observations)
            analysis.pop('analysis_sha256', None)
            analysis['research_coherence'] = assessment.assess_research_analysis(analysis, assessed_at=generated_at)
            analysis['analysis_sha256'] = digest(analysis)
            predictions.append(analysis)
        except (ValueError, TypeError, KeyError) as error:
            errors.append({'race_id': race_id, 'state': 'INPUT_VALIDATION_FAILED', 'reason': str(error)[:180]})
    summary = {'input_races': len(rows), 'analyzed_races': len(predictions),
        'A_generated': sum(p['A']['state'] == 'GENERATED_RESEARCH_ONLY' for p in predictions),
        'B_generated': sum(p['B']['state'] == 'GENERATED_RESEARCH_ONLY' for p in predictions),
        'C_generated': 0,
        'canonical_strength_formula_races': sum(p['strength_mode'] == 'CANONICAL_FORMULA' for p in predictions),
        'reduced_feature_races': 0,
        'evidence_driven_method_races': len(predictions),
        'post_cutoff_created': sum(p['created_after_published_cutoff'] is True for p in predictions),
        'pre_cutoff_created': sum(p['created_after_published_cutoff'] is False for p in predictions),
        'cutoff_unknown': sum(p['created_after_published_cutoff'] is None for p in predictions),
        'formal_saved_forecasts': 0, 'result_comparisons_performed': 0,
        'supplement_rejections': sum(len(p['rejected_supplements']) for p in predictions),
        'condition_caution_sidecars': sum('condition_adjusted' in p for p in predictions),
        'research_confidence_grades': dict(Counter(
            entry['grade'] for p in predictions for entry in p['research_coherence']['evaluations'].values())),
        'line_states': dict(Counter(p['line_status'] for p in predictions)), 'errors': len(errors)}
    checkout_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip()
    if args.model_commit:
        need(bool(re.fullmatch('[a-f0-9]{40}', args.model_commit)), 'MODEL_COMMIT_INVALID')
    provenance = {'repository': 'haji84/RACE-AI',
        'verified_source_commit': args.model_commit,
        'base_checkout_commit': checkout_commit, 'source_sha256': MODEL_SHA256,
        'method_entrypoint': 'generate_evidence_analysis',
        'source_status': 'OWNER_REQUESTED_IN_PLACE_METHOD_CORRECTION',
        'previous_model_source_sha256': '9aa0143192707733a9666f8d0dad70e589451f67943130796d3ed4af0387f413',
        'sealed_prediction_originals_modified': False}
    report = {'schema': 'KEIRIN_RESULT_UNREAD_DAY_RESEARCH_V1', 'date': DAY,
        'generated_at': generated_at, 'input_files': input_files,
        'model_source_sha256': MODEL_SHA256,
        'model_repository_commit': args.model_commit,
        'execution_checkout_commit': checkout_commit, 'model_source_provenance': provenance,
        'analysis_script_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
        'summary': summary, 'races': predictions, 'errors': errors}
    report['report_sha256'] = digest(report)
    with args.output.open('x') as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'output': str(args.output), **summary}, ensure_ascii=False))


if __name__ == '__main__':
    main()
