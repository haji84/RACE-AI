"""Display the authenticated canary's existing four arms without recomputing them.

The trusted caller first completes compare_frozen/replay_saved_result. This
adapter rechecks frozen identities, key pin, times and bounded display fields;
it does not establish source authority from a caller's flag. No raw sources,
supplements, result data or private key enter the display packet.
"""
from copy import deepcopy
from hashlib import sha256
import hmac
import json
import math
from pathlib import Path
import re

from . import keirin_note_feed as feed
from . import keirin_nationwide_auto_generator as model
from . import keirin_form_fall_shadow as shadow
from .keirin_form_fall_blind_pdca import _tickets
from .keirin_note_view import canonical, SCHEMA as NOTE_SCHEMA

SCHEMA = 'RACE_AI_KEIRIN_FROZEN_FORECASTS_V1'
KIND = 'canary-original'
HOLD_C = 'HOLD_NO_INDEPENDENT_HISTORICAL_FOLLOW_LABELS'
BASE_FIELDS = set(('schema race_id generated_at published_cutoff_at source_facts_sha256 source_as_of '
    'A B C official_cutoff_independently_authenticated official_result_observed '
    'all_six_phase_orders_are_hypotheses_not_video_truth branch_weights_are_not_calibrated_probabilities '
    'formal_model_promoted old_PR71_four_models_required real_money_wager_placed prediction_sha256').split())
SHADOW_FIELDS = set(('schema race_id generated_at published_cutoff_at baseline_source_sha256 '
    'baseline_prediction_sha256 condition_supplement_sha256 A_research B_research rider_assessments '
    'verified_source_receipt_count medical_recovery_or_crash_causality_inferred '
    'comments_quoted_in_private_supplement_only historical_originals_mutated '
    'is_official_calibrated_or_production_forecast C_optional_unrelated sha256').split())
ASSESSMENT_FIELDS = set(('car trend recent_result_change post_fall_change post_fall_trend '
    'fall_on_record documented_absence_days return_after_absence_results comments_count '
    'score_adjustment effect_on_tactics').split())
TRENDS = {'IMPROVING', 'DECLINING', 'NO_CLEAR_CHANGE', 'INSUFFICIENT_DATA'}


def need(ok, code):
    if not ok: raise ValueError('FROZEN_DISPLAY_' + code)


def exact(value, fields):
    return type(value) is dict and set(value) == set(fields)


def number(value, low, high):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def _scenarios(values, cars):
    need(type(values) is list and 2 <= len(values) <= 20, 'SCENARIOS')
    seen = set()
    for item in values:
        need(exact(item, ('scenario_id', 'six_phases', 'projected_3ren_tan', 'relative_research_weight')),
             'SCENARIO_FIELDS')
        sid = item['scenario_id']
        need(type(sid) is str and re.fullmatch(r'L[1-9]_V[0-3]', sid) and sid not in seen,
             'SCENARIO_ID'); seen.add(sid)
        need(type(item['six_phases']) is list and len(item['six_phases']) == 6 and
             number(item['relative_research_weight'], 0, 1), 'SCENARIO_PHASES')
        for phase, step in zip(model.PHASES, item['six_phases']):
            need(exact(step, ('phase', 'projected_order', 'projected_top3', 'hypothesis_actions',
                             'actual_rider_position_video_verified')) and step['phase'] == phase and
                 step['actual_rider_position_video_verified'] is False, 'SCENARIO_STEP')
            order = step['projected_order']
            need(type(order) is list and len(order) == len(cars) and set(order) == cars and
                 all(type(car) is int for car in order) and step['projected_top3'] == order[:3], 'PHASE_ORDER')
            need(type(step['hypothesis_actions']) is list and 1 <= len(step['hypothesis_actions']) <= 8 and
                 all(type(action) is str and re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}', action)
                     for action in step['hypothesis_actions']), 'PHASE_ACTIONS')
        need(item['projected_3ren_tan'] == item['six_phases'][-1]['projected_top3'], 'SCENARIO_TICKET')
    need(abs(sum(row['relative_research_weight'] for row in values)-1) <= 1e-6, 'SCENARIO_WEIGHTS')
    return seen


def checked_forecasts(doc):
    need(exact(doc, ('schema', 'races')) and doc['schema'] == SCHEMA and
         type(doc['races']) is list and 1 <= len(doc['races']) <= 300, 'DOCUMENT')
    seen = set()
    for row in doc['races']:
        need(exact(row, ('race_id', 'revision', 'baseline_cipher_sha256', 'conditioned_cipher_sha256',
            'baseline_sealed_at', 'conditioned_sealed_at', 'facts', 'baseline', 'conditioned')), 'ROW')
        rid = row['race_id']; base, adjusted, facts = row['baseline'], row['conditioned'], row['facts']
        need(type(rid) is str and model.VENUE.fullmatch(rid) and rid not in seen, 'RACE_ID'); seen.add(rid)
        for key in ('revision', 'baseline_cipher_sha256', 'conditioned_cipher_sha256'):
            need(type(row[key]) is str and model.SHA.fullmatch(row[key]), 'IDENTITY')
        need(exact(base, BASE_FIELDS) and exact(adjusted, SHADOW_FIELDS) and
             base['schema'] == model.PREDICTION and adjusted['schema'] == shadow.SCHEMA and
             base['race_id'] == adjusted['race_id'] == rid, 'FORECAST_SHAPES')
        need(base['prediction_sha256'] == model.digest({k:v for k,v in base.items() if k != 'prediction_sha256'}) and
             adjusted['sha256'] == model.digest({k:v for k,v in adjusted.items() if k != 'sha256'}) and
             adjusted['baseline_prediction_sha256'] == base['prediction_sha256'] and
             adjusted['baseline_source_sha256'] == base['source_facts_sha256'], 'FROZEN_LINEAGE')
        for value in (base['source_facts_sha256'], adjusted['condition_supplement_sha256']):
            need(type(value) is str and model.SHA.fullmatch(value), 'SOURCE_IDENTITY')
        need(base['generated_at'] == adjusted['generated_at'] and
             base['published_cutoff_at'] == adjusted['published_cutoff_at'], 'FROZEN_CLOCKS')
        generated, cutoff = model.when(base['generated_at']), model.when(base['published_cutoff_at'])
        need(model.when(base['source_as_of']) <= generated, 'SOURCE_CLOCK')
        for key in ('baseline_sealed_at', 'conditioned_sealed_at'):
            sealed = model.when(row[key]); need(generated <= sealed and (cutoff-sealed).total_seconds() >= 65, 'CUTOFF')
        need(base['C'] == {'state': HOLD_C}, 'C_NOT_GENERATED')
        for key in ('official_cutoff_independently_authenticated', 'official_result_observed',
                    'formal_model_promoted', 'old_PR71_four_models_required', 'real_money_wager_placed'):
            need(base[key] is False, 'NO_PROMOTION')
        for key in ('all_six_phase_orders_are_hypotheses_not_video_truth', 'branch_weights_are_not_calibrated_probabilities'):
            need(base[key] is True, 'HYPOTHESIS_SCOPE')
        for key in ('medical_recovery_or_crash_causality_inferred', 'historical_originals_mutated',
                    'is_official_calibrated_or_production_forecast'):
            need(adjusted[key] is False, 'NO_SHADOW_PROMOTION')
        need(adjusted['comments_quoted_in_private_supplement_only'] is True and
             adjusted['C_optional_unrelated'] is True and
             type(adjusted['verified_source_receipt_count']) is int and
             1 <= adjusted['verified_source_receipt_count'] <= 400, 'SHADOW_SCOPE')
        need(exact(facts, ('competition', 'line_groups', 'riders')) and facts['competition'] in model.CLASSES and
             type(facts['riders']) is list and 5 <= len(facts['riders']) <= 9, 'FACTS')
        cars = set()
        for rider in facts['riders']:
            need(exact(rider, ('car','athlete_id','mark_rank','competition_points','recent_form_score',
                               'h_count','b_count','style')), 'RIDER_FIELDS')
            car = rider['car']; need(type(car) is int and 1 <= car <= 9 and car not in cars, 'RIDER_CAR'); cars.add(car)
            need(rider['athlete_id'] is None or type(rider['athlete_id']) is str and model.RID.fullmatch(rider['athlete_id']), 'RIDER_ID')
            need(rider['mark_rank'] == 'UNMARKED' or type(rider['mark_rank']) is int and
                 1 <= rider['mark_rank'] <= len(facts['riders']), 'RIDER_MARK')
            need(number(rider['competition_points'], 0, 150) and number(rider['recent_form_score'], 0, 1) and
                 all(type(rider[k]) is int and 0 <= rider[k] <= 99 for k in ('h_count','b_count')) and
                 rider['style'] in model.STYLES, 'RIDER_VALUES')
        lines = facts['line_groups']
        need(type(lines) is list and 1 <= len(lines) <= len(cars) and
             all(type(line) is list and line and all(type(car) is int for car in line) for line in lines), 'LINES')
        members = sum(lines, []); need(len(members) == len(cars) and set(members) == cars, 'LINE_MEMBERS')
        need(facts['competition'] != 'GIRLS' or all(len(line) == 1 for line in lines), 'GIRLS_LINES')
        need(exact(base['A'], ('model','ranked_tickets','based_on_published_marks_not_shared_PR71')) and
             base['A']['model'] == model.MODEL_A and base['A']['based_on_published_marks_not_shared_PR71'] is True and
             exact(base['B'], ('model','ranked_tickets','six_phase_scenarios','round_objective_source')) and
             base['B']['model'] == model.MODEL_B and base['B']['round_objective_source'] in
             {'SOURCE_EVIDENCED','UNKNOWN_NOT_IMPUTED'}, 'BASE_ARMS')
        scenario_ids = _scenarios(base['B']['six_phase_scenarios'], cars)
        for name, family, label in (('A','A_research','baseline-plus-documented-form-v1'),
                                    ('B','B_research','six-phase-plus-documented-form-v1')):
            original, arm = base[name], adjusted[family]
            keys = {'model','ranked_tickets','baseline_ranked_tickets','changed_from_original'}
            if name == 'B': keys |= {'branch_condition_factors','branch_factor_is_uncalibrated'}
            need(exact(arm, keys) and arm['model'] == label and
                 arm['baseline_ranked_tickets'] == original['ranked_tickets'] and
                 type(arm['changed_from_original']) is bool and
                 arm['changed_from_original'] == (arm['ranked_tickets'] != original['ranked_tickets']), 'SHADOW_ARM')
            _tickets(original, cars); _tickets(arm, cars)
        factors = adjusted['B_research']['branch_condition_factors']
        need(adjusted['B_research']['branch_factor_is_uncalibrated'] is True and type(factors) is list and
             len(factors) == len(scenario_ids) and all(exact(f, ('scenario_id','relative_weight_after')) and
             f['scenario_id'] in scenario_ids and number(f['relative_weight_after'],0,1) for f in factors) and
             {f['scenario_id'] for f in factors} == scenario_ids and
             abs(sum(f['relative_weight_after'] for f in factors)-1) <= 1e-6, 'CONDITION_FACTORS')
        assessments = adjusted['rider_assessments']
        need(type(assessments) is list and len(assessments) == len(cars), 'ASSESSMENTS')
        assessed = set()
        for item in assessments:
            need(exact(item, ASSESSMENT_FIELDS) and type(item['car']) is int and item['car'] in cars and
                 item['car'] not in assessed, 'ASSESSMENT'); assessed.add(item['car'])
            need(item['trend'] in TRENDS and item['post_fall_trend'] in TRENDS and
                 type(item['fall_on_record']) is bool and number(item['score_adjustment'],-.08,.08) and
                 item['effect_on_tactics'] in {'UNKNOWN_NO_ADJUSTMENT','OBSERVED_RESULTS_UPWEIGHT_RESEARCH',
                                              'OBSERVED_RESULTS_DOWNWEIGHT_RESEARCH'}, 'ASSESSMENT_VALUES')
            for key in ('recent_result_change','post_fall_change'):
                need(item[key] is None or number(item[key],-1,1), 'FORM_CHANGE')
            for key in ('documented_absence_days','return_after_absence_results','comments_count'):
                need(item[key] is None or type(item[key]) is int and 0 <= item[key] <= 36525, 'FORM_COUNTS')
    return doc


def from_payload(payload, owner_private_pem):
    from scripts.keirin_official_day_pipeline import check_owner_private_key
    from .keirin_github_origin_evidence import FORM_CANARY_RACE, FORM_CANARY_CUTOFF
    from cryptography.hazmat.primitives import serialization
    check_owner_private_key(owner_private_pem)
    need(type(payload) is dict and payload.get('schema') == 'RACE_AI_KEIRIN_OFFICIAL_FORM_CANARY_PRE_CUTOFF_V1' and
         payload.get('race_id') == FORM_CANARY_RACE, 'AUTHENTICATED_CANARY_SCOPE')
    base, adjusted, snapshot = payload['baseline'], payload['conditioned'], payload['snapshot']
    model.validate_snapshot(snapshot, computed_at=base['generated_at'])
    need(base['race_id'] == snapshot['race_id'] == payload['race_id'] and
         base['published_cutoff_at'] == FORM_CANARY_CUTOFF and
         base['source_facts_sha256'] == model.digest(snapshot) and
         adjusted['condition_supplement_sha256'] == model.digest(payload['supplement']), 'PAYLOAD_IDENTITIES')
    row = {key: deepcopy(payload[key]) for key in ('race_id','baseline_cipher_sha256',
        'conditioned_cipher_sha256','baseline_sealed_at','conditioned_sealed_at','baseline','conditioned')}
    row['facts'] = {key:deepcopy(snapshot[key]) for key in ('competition','line_groups','riders')}
    der = serialization.load_pem_private_key(owner_private_pem, password=None).private_bytes(
        serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    key = sha256(b'RACE_AI_FROZEN_DISPLAY_ID_KEY_V1\x00'+der).digest()
    row['revision'] = hmac.new(key, b'RACE_AI_FROZEN_DISPLAY_REVISION_V1\x00'+canonical(row), 'sha256').hexdigest()
    return checked_forecasts(dict(schema=SCHEMA, races=[row]))


def note_packet(doc, source_commit):
    checked_forecasts(doc)
    need(type(source_commit) is str and re.fullmatch('[0-9a-f]{40}', source_commit), 'SOURCE_COMMIT')
    days = sorted({r['race_id'][:4]+'-'+r['race_id'][4:6]+'-'+r['race_id'][6:8] for r in doc['races']})
    files = {}
    for day in days:
        raw = canonical(dict(schema=SCHEMA, races=[r for r in doc['races'] if r['race_id'].startswith(day.replace('-',''))]))
        files['data/'+day+'/frozen_forecasts.json'] = dict(text=raw.decode(), bytes=len(raw), sha256=sha256(raw).hexdigest())
    return dict(schema=NOTE_SCHEMA, scope='OWNER_AUTHENTICATED_FROZEN_CANARY', dates=days, files=files,
        source_commit=source_commit, imported_at=max(r['conditioned_sealed_at'] for r in doc['races']),
        formal_model_admission=False, production_weight_switch=False, original_files_preserved=True, wagers_placed=False)


def publish_frozen_forecast(repo, payload, source_commit, owner_private_pem, *, clock=None, store=None, recipient=None):
    doc = from_payload(payload, owner_private_pem)
    repo = Path(repo); store = store or feed.NoteFeedGit(repo)
    recipient = feed.checked_recipient(recipient or json.loads((repo/'config/keirin-note-recipient.json').read_bytes()))
    parent = store.head(); prior = feed.load_index(store, recipient, parent)
    need(prior is not None, 'EXISTING_OWNER_FEED_REQUIRED')
    previous = {}
    for entry in prior['entries']:
        if entry['kind'] == KIND: previous.update(entry['original_revisions'])
    for row in doc['races']:
        need(row['race_id'] not in previous or previous[row['race_id']] == row['revision'], 'IMMUTABLE_ORIGINAL_CHANGED')
    if all(previous.get(row['race_id']) == row['revision'] for row in doc['races']):
        return dict(state='EXISTING_FROZEN_DISPLAY_REUSED', published_originals=0, provider_requests=0)
    sealed = feed.seal_snapshot(note_packet(doc, source_commit), recipient, kind=KIND, clock=clock)
    saved = feed.publish_snapshot(store, recipient, sealed, expected_parent=parent)
    return dict(saved, published_originals=len(doc['races']), provider_requests=0)


def saved_frozen_forecast(repo, owner_private_pem, source_commit):
    """Replay the saved completed/order-only trial before exporting its originals."""
    from scripts import keirin_official_form_canary as canary
    payload, receipt, settled = canary._load_original_bundle(repo, owner_private_pem)
    if not settled: return dict(state='NO_ADMITTED_FROZEN_RESULT_DISPLAY', published_originals=0, provider_requests=0)
    raw_base, raw_conditioned, _ = canary._archived_pair(repo, payload)
    canary.replay_saved_result(payload=payload, bundle_receipt=receipt, saved_pair=settled[-1],
        raw_baseline=raw_base, raw_conditioned=raw_conditioned, owner_private_pem=owner_private_pem)
    return publish_frozen_forecast(repo, payload, source_commit, owner_private_pem)
