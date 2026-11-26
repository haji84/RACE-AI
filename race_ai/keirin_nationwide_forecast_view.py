"""Project authenticated nationwide archives into the existing encrypted view.

The caller must use official_nationwide_records.load_admitted_day: it verifies
raw evidence, encrypted originals and independent GitHub origin receipts.
This adapter rechecks frozen hashes, parent identities, bounded fields and the
owner key pin. It never collects sources or regenerates a prediction. The old
four-arm canary schema remains unchanged and strict.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
from pathlib import Path
import re
from subprocess import TimeoutExpired

from . import keirin_frozen_forecast_view as frozen
from . import keirin_note_feed as feed
from . import keirin_nationwide_auto_generator as model
from . import keirin_confidence as confidence
from .keirin_form_fall_blind_pdca import _tickets
from .keirin_note_view import canonical, SCHEMA as NOTE_SCHEMA

SCHEMA = 'RACE_AI_KEIRIN_NATIONWIDE_FORECAST_VIEW_V1'
PAYLOAD = 'RACE_AI_KEIRIN_OFFICIAL_NATIONWIDE_PRE_CUTOFF_V1'
KIND = 'nationwide'
MAX_RACES = 600
MAX_FILE_BYTES = 32 * 1024 * 1024
JST = timezone(timedelta(hours=9))
RACE_STATES = frozenset(('WAITING_SOURCE_CAPTURE UNSUPPORTED_CLASS_OR_ROUND '
    'PUBLISHED_RESULT_NO_PRE_CUTOFF_ORIGINAL FROZEN_ORIGINAL_PRESERVED '
    'SOURCE_CAPTURE_BUDGET_PENDING CUTOFF_MARGIN_INSUFFICIENT BASELINE_SOURCE_UNVERIFIED '
    'PROVIDER_STOPPED SOURCE_UNAVAILABLE A_B_ARCHIVED_AWAITING_INDEPENDENT_READBACK '
    'A_B_AUTHENTICATED_PRE_CUTOFF ORIGIN_PROOF_PENDING FROZEN_ARCHIVE_UNVERIFIED '
    'RACE_DISAPPEARED_FROM_CURRENT_LIST').split())
CONDITION_STATES = frozenset(('HISTORY_NOT_COLLECTED HISTORY_SOURCE_UNAVAILABLE HISTORY_UNVERIFIED '
    'INSUFFICIENT_CAPTURE_MARGIN CONDITIONED_ARCHIVED_AWAITING_READBACK '
    'CONDITIONED_AUTHENTICATED_PRE_CUTOFF CONDITIONED_ORIGIN_PROOF_PENDING '
    'CONDITIONED_ARCHIVE_UNVERIFIED NO_CONDITIONED_ORIGINAL').split())
ORIGINAL_KEYS = ('race_id', 'revision', 'baseline_cipher_sha256', 'conditioned_cipher_sha256',
    'baseline_sealed_at', 'conditioned_sealed_at', 'facts', 'baseline', 'conditioned')


def need(ok, code):
    if not ok: raise ValueError('NATIONWIDE_DISPLAY_' + code)


def _day(value):
    need(type(value) is str and re.fullmatch(r'20[0-9]{2}-[0-9]{2}-[0-9]{2}', value), 'DAY')
    return date.fromisoformat(value).isoformat()


def _hex(value):
    return type(value) is str and model.SHA.fullmatch(value) is not None


def _ids(values, day):
    need(type(values) is list and len(values) <= MAX_RACES and len(set(values)) == len(values) and
         all(type(rid) is str and model.VENUE.fullmatch(rid) and
             rid.startswith(day.replace('-', '')) and 1 <= int(rid[-2:]) <= 12 for rid in values), 'RACE_IDS')
    return values


def checked_original(row):
    """Validate the new baseline-only variant without relaxing canary V1."""
    need(frozen.exact(row, ORIGINAL_KEYS) or
         frozen.exact(row, (*ORIGINAL_KEYS,'confidence_assessment')), 'ORIGINAL_FIELDS')
    if row['conditioned'] is not None:
        frozen.checked_forecasts(dict(schema=frozen.SCHEMA, races=[row]))
        return row
    need(row['conditioned_cipher_sha256'] is None and row['conditioned_sealed_at'] is None,
         'PENDING_CONDITION_HAS_NO_ORIGINAL')
    rid, base, facts = row['race_id'], row['baseline'], row['facts']
    need(type(rid) is str and model.VENUE.fullmatch(rid) and _hex(row['revision']) and
         _hex(row['baseline_cipher_sha256']), 'ORIGINAL_IDENTITY')
    need(frozen.exact(base, frozen.BASE_FIELDS) and base['schema'] == model.PREDICTION and
         base['race_id'] == rid and _hex(base['source_facts_sha256']) and
         base['prediction_sha256'] == model.digest({k:v for k,v in base.items() if k != 'prediction_sha256'}),
         'BASELINE_IDENTITY')
    generated, cutoff, sealed = (model.when(base['generated_at']),
        model.when(base['published_cutoff_at']), model.when(row['baseline_sealed_at']))
    need(model.when(base['source_as_of']) <= generated <= sealed and
         (cutoff-sealed).total_seconds() >= 65, 'BASELINE_CUTOFF')
    if 'confidence_assessment' in row:
        confidence.checked_assessment(row['confidence_assessment'],snapshot=None,
            baseline=base,sealed_at=row['baseline_sealed_at'])
    need(base['C'] == {'state': frozen.HOLD_C}, 'NO_FABRICATED_C')
    for name in ('official_cutoff_independently_authenticated', 'official_result_observed',
                 'formal_model_promoted', 'old_PR71_four_models_required', 'real_money_wager_placed'):
        need(base[name] is False, 'NO_PROMOTION')
    for name in ('all_six_phase_orders_are_hypotheses_not_video_truth',
                 'branch_weights_are_not_calibrated_probabilities'):
        need(base[name] is True, 'HYPOTHESIS_SCOPE')
    need(frozen.exact(facts, ('competition','line_groups','riders')) and
         facts['competition'] in model.CLASSES and type(facts['riders']) is list and
         5 <= len(facts['riders']) <= 9, 'FACTS')
    cars = set()
    for rider in facts['riders']:
        need(frozen.exact(rider, ('car','athlete_id','mark_rank','competition_points',
            'recent_form_score','h_count','b_count','style')), 'RIDER_FIELDS')
        car = rider['car']
        need(type(car) is int and 1 <= car <= 9 and car not in cars, 'RIDER_CAR'); cars.add(car)
        need(rider['athlete_id'] is None or type(rider['athlete_id']) is str and
             model.RID.fullmatch(rider['athlete_id']), 'RIDER_ID')
        need(rider['mark_rank'] == 'UNMARKED' or type(rider['mark_rank']) is int and
             1 <= rider['mark_rank'] <= len(facts['riders']), 'RIDER_MARK')
        need(frozen.number(rider['competition_points'],0,150) and frozen.number(rider['recent_form_score'],0,1) and
             all(type(rider[k]) is int and 0 <= rider[k] <= 99 for k in ('h_count','b_count')) and
             rider['style'] in model.STYLES, 'RIDER_VALUES')
    lines = facts['line_groups']
    need(type(lines) is list and 1 <= len(lines) <= len(cars) and all(type(line) is list and
         line and all(type(car) is int for car in line) for line in lines), 'LINES')
    members = sum(lines, [])
    need(len(members) == len(cars) and set(members) == cars and
         (facts['competition'] != 'GIRLS' or all(len(line) == 1 for line in lines)), 'LINE_MEMBERS')
    need(frozen.exact(base['A'], ('model','ranked_tickets','based_on_published_marks_not_shared_PR71')) and
         base['A']['model'] == model.MODEL_A and base['A']['based_on_published_marks_not_shared_PR71'] is True and
         frozen.exact(base['B'], ('model','ranked_tickets','six_phase_scenarios','round_objective_source')) and
         base['B']['model'] == model.MODEL_B and base['B']['round_objective_source'] in
         {'SOURCE_EVIDENCED','UNKNOWN_NOT_IMPUTED'}, 'BASELINE_ARMS')
    _tickets(base['A'], cars); _tickets(base['B'], cars)
    frozen._scenarios(base['B']['six_phase_scenarios'], cars)
    return row


def checked_identities(values, day):
    need(type(values) is dict, 'ORIGINAL_IDENTITIES')
    _ids(list(values), day)
    for value in values.values():
        need(frozen.exact(value, ('baseline','conditioned')) and _hex(value['baseline']) and
             (value['conditioned'] is None or _hex(value['conditioned'])), 'ORIGINAL_IDENTITY')
    return values


def checked_day(doc):
    need(frozen.exact(doc, ('schema','day_jst','revision','observed_at','registry_available',
        'inventory_complete','missing_venues','disappeared_race_ids','races')) and doc['schema'] == SCHEMA,
        'DOCUMENT')
    day = _day(doc['day_jst']); observed = model.when(doc['observed_at'])
    need(_hex(doc['revision']) and type(doc['registry_available']) is bool and
         type(doc['inventory_complete']) is bool and type(doc['races']) is list, 'DOCUMENT_FIELDS')
    need(type(doc['missing_venues']) is list and len(set(doc['missing_venues'])) == len(doc['missing_venues']) and
         len(doc['missing_venues']) <= 43 and all(type(code) is int and 0 <= code <= 99
         for code in doc['missing_venues']), 'MISSING_VENUES')
    ids = _ids([row.get('race_id') for row in doc['races'] if type(row) is dict], day)
    need(len(ids) == len(doc['races']), 'RACE_ROWS')
    _ids(doc['disappeared_race_ids'], day)
    need(set(doc['disappeared_race_ids']) <= set(ids) and
         (not doc['inventory_complete'] or doc['registry_available'] and
          not doc['missing_venues'] and not doc['disappeared_race_ids']), 'INVENTORY_SCOPE')
    need(doc['registry_available'] or not ids and not doc['missing_venues'] and
         not doc['disappeared_race_ids'], 'UNAVAILABLE_REGISTRY')
    for row in doc['races']:
        need(frozen.exact(row, ('race_id','venue_code','race_no','cutoff_at','state','condition_state',
            'original_identity','original')) and type(row['venue_code']) is int and
            row['venue_code'] == int(row['race_id'][8:10]) and type(row['race_no']) is int and
            row['race_no'] == int(row['race_id'][-2:]) and row['state'] in RACE_STATES and
            row['condition_state'] in CONDITION_STATES, 'RACE_FIELDS')
        if row['cutoff_at'] is not None:
            need(model.when(row['cutoff_at']).astimezone(JST).date().isoformat() == day, 'CUTOFF_DAY')
        original = row['original']
        if original is None:
            if row['original_identity'] is None:
                need(row['state'] != 'A_B_AUTHENTICATED_PRE_CUTOFF' and
                     row['condition_state'] != 'CONDITIONED_AUTHENTICATED_PRE_CUTOFF', 'MISSING_ORIGINAL')
            else:
                checked_identities({row['race_id']:row['original_identity']}, day)
                need(row['condition_state'] != 'CONDITIONED_AUTHENTICATED_PRE_CUTOFF' or
                     row['original_identity']['conditioned'] is not None, 'MISSING_CONDITION_REFERENCE')
            continue
        checked_original(original); checked_identities({row['race_id']:row['original_identity']}, day)
        need(original['race_id'] == row['race_id'] and
             original['baseline']['published_cutoff_at'] == row['cutoff_at'] and
             model.when(original['baseline_sealed_at']) <= observed, 'ORIGINAL_SCOPE')
        adjusted = original['conditioned'] is not None
        need((row['original_identity']['conditioned'] is not None) == adjusted and
             (row['condition_state'] == 'CONDITIONED_AUTHENTICATED_PRE_CUTOFF') == adjusted,
             'CONDITION_SCOPE')
        if adjusted: need(model.when(original['conditioned_sealed_at']) <= observed, 'CONDITION_CLOCK')
    return doc


def _identity_key(owner_private_pem):
    from scripts.keirin_official_day_pipeline import check_owner_private_key
    from cryptography.hazmat.primitives import serialization
    check_owner_private_key(owner_private_pem)
    key = serialization.load_pem_private_key(owner_private_pem, password=None)
    der = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    return sha256(b'RACE_AI_NATIONWIDE_DISPLAY_ID_KEY_V1\0'+der).digest()


def _opaque(key, purpose, value):
    return hmac.new(key, purpose.encode('ascii')+b'\0'+canonical(value), 'sha256').hexdigest()


def _day_revision(key, doc):
    # A retained original and its exact keyed reference have one identity.
    # This permits bounded deltas and genuine state reversions without
    # republishing every saved ticket/scenario on each collection cycle.
    semantic = {k:v for k,v in doc.items() if k not in {'revision','observed_at'}}
    semantic['races'] = [{k:v for k,v in row.items() if k != 'original'} for row in doc['races']]
    return _opaque(key, 'DAY', semantic)


def from_admitted(admitted, owner_private_pem):
    key = _identity_key(owner_private_pem)
    need(type(admitted) is dict, 'ADMITTED_DAY')
    day = _day(admitted['day_jst']); model.when(admitted['observed_at'])
    registry = admitted['registry']
    if registry is None:
        need(admitted['records'] == [] and admitted['states'] == [], 'REGISTRY_REQUIRED_FOR_ORIGINALS')
        ids, rows, missing, disappeared, complete = [], {}, [], [], False
    else:
        need(type(registry) is dict and registry.get('schema') == 'RACE_AI_OFFICIAL_EXTENSION_DAY_REGISTRY_V1' and
             registry.get('event_day') == day and type(registry.get('day_inventory_complete')) is bool,
             'REGISTRY')
        ids = _ids(registry['registered_race_ids'], day)
        need(type(registry['races']) is list, 'REGISTRY_ROWS')
        rows = {r['race_id']:r for r in registry['races']}
        need(len(rows) == len(registry['races']) and set(rows) <= set(ids), 'REGISTRY_ROWS')
        missing, disappeared, complete = (registry['missing_venues'], registry['disappeared_race_ids'],
                                         registry['day_inventory_complete'])
    need(type(admitted['states']) is list and type(admitted['records']) is list, 'ADMITTED_RECORDS')
    states = {r['race_id']:r for r in admitted['states']}
    records = {r['race_id']:r for r in admitted['records']}
    need(len(states) == len(admitted['states']) and set(states) == set(ids) and
         len(records) == len(admitted['records']) and set(records) <= set(ids), 'FULL_REGISTERED_DENOMINATOR')
    out = []
    for rid in sorted(ids):
        state, meta, payload = states[rid], rows.get(rid), records.get(rid)
        need(frozen.exact(state, ('race_id','state','condition_state')), 'STATE_FIELDS')
        if meta is not None:
            need(type(meta.get('venue_code')) is int and meta['venue_code'] == int(rid[8:10]) and
                 type(meta.get('race_no')) is int and meta['race_no'] == int(rid[-2:]), 'REGISTRY_RACE')
        original = identity = None
        cutoff = meta.get('official_cutoff_at') if meta else None
        if payload is not None:
            need(payload.get('schema') == PAYLOAD and payload.get('day_jst') == day and
                 payload['race_id'] == rid and payload['condition_state'] == state['condition_state'], 'PAYLOAD_SCOPE')
            cohort = payload['cohort']
            need(frozen.exact(cohort, ('schema','day_jst','race_ids','max_tickets_per_arm','calendar_source_sha256')) and
                 cohort['schema'] == 'RACE_AI_KEIRIN_OFFICIAL_SP_DAY_COHORT_V1' and cohort['day_jst'] == day and
                 cohort['max_tickets_per_arm'] == 12 and _hex(cohort['calendar_source_sha256']) and
                 payload['cohort_sha256'] == model.digest(cohort), 'COHORT')
            _ids(cohort['race_ids'], day)
            need(rid in cohort['race_ids'] and set(cohort['race_ids']) <= set(ids) and
                 type(payload['producer_run_id']) is str and re.fullmatch(r'[1-9][0-9]{0,19}', payload['producer_run_id']) and
                 type(payload['producer_commit']) is str and re.fullmatch(r'[a-f0-9]{40}', payload['producer_commit']),
                 'PRODUCER_IDENTITY')
            base, snapshot, adjusted = payload['baseline'], payload['snapshot'], payload['conditioned']
            model.validate_snapshot(snapshot, computed_at=base['generated_at'])
            need(base['race_id'] == snapshot['race_id'] == rid and
                 base['source_facts_sha256'] == model.digest(snapshot) and
                 base['source_as_of'] == snapshot['as_of'] and
                 base['published_cutoff_at'] == snapshot['published_cutoff_at'], 'SNAPSHOT_IDENTITY')
            if adjusted is None: need(payload['supplement'] is None, 'NO_PENDING_SUPPLEMENT')
            else: need(adjusted['condition_supplement_sha256'] == model.digest(payload['supplement']), 'SUPPLEMENT_IDENTITY')
            original = {name:deepcopy(payload[name]) for name in ORIGINAL_KEYS
                        if name not in {'revision','facts'}}
            if 'confidence_assessment' in payload:
                original['confidence_assessment'] = deepcopy(confidence.checked_assessment(payload['confidence_assessment'],
                    snapshot=snapshot,baseline=base,sealed_at=payload['baseline_sealed_at']))
            original['facts'] = {name:deepcopy(snapshot[name]) for name in ('competition','line_groups','riders')}
            original['revision'] = _opaque(key, 'ORIGINAL', original)
            checked_original(original)
            base_identity = {name:original[name] for name in ('race_id','baseline_cipher_sha256',
                'baseline_sealed_at','facts','baseline')}
            if 'confidence_assessment' in original:
                base_identity['confidence_assessment'] = original['confidence_assessment']
            identity = dict(baseline=_opaque(key, 'BASELINE', base_identity), conditioned=None)
            if adjusted is not None:
                identity['conditioned'] = _opaque(key, 'CONDITIONED', dict(baseline=identity['baseline'],
                    conditioned=original['conditioned'], cipher=original['conditioned_cipher_sha256'],
                    sealed_at=original['conditioned_sealed_at']))
            cutoff = base['published_cutoff_at']
        out.append(dict(race_id=rid, venue_code=int(rid[8:10]), race_no=int(rid[-2:]), cutoff_at=cutoff,
            state=state['state'], condition_state=state['condition_state'], original_identity=identity, original=original))
    doc = dict(schema=SCHEMA, day_jst=day, revision='0'*64, observed_at=admitted['observed_at'],
        registry_available=registry is not None, inventory_complete=complete,
        missing_venues=deepcopy(missing), disappeared_race_ids=deepcopy(disappeared), races=out)
    checked_day(doc)
    doc['revision'] = _day_revision(key, doc)
    return doc


def note_packet(doc, source_commit):
    checked_day(doc)
    need(type(source_commit) is str and re.fullmatch('[0-9a-f]{40}', source_commit), 'SOURCE_COMMIT')
    raw = canonical(doc); day = doc['day_jst']
    need(len(raw) <= MAX_FILE_BYTES, 'DAY_FILE_TOO_LARGE')
    return dict(schema=NOTE_SCHEMA, scope='OWNER_AUTHENTICATED_NATIONWIDE_ORIGINALS', dates=[day],
        files={'data/'+day+'/nationwide_forecasts.json':dict(text=raw.decode(), bytes=len(raw), sha256=sha256(raw).hexdigest())},
        source_commit=source_commit, imported_at=doc['observed_at'], formal_model_admission=False,
        production_weight_switch=False, original_files_preserved=True, wagers_placed=False)


def public_identities(doc):
    checked_day(doc)
    return {row['race_id']:row['original_identity'] for row in doc['races'] if row['original_identity'] is not None}


def publish_day(repo, admitted, source_commit, owner_private_pem, *, clock=None, store=None,
                recipient=None, public_view=False):
    doc = from_admitted(admitted, owner_private_pem)
    public_doc = dict(doc, races=[dict(row) for row in doc['races']]) if public_view else None
    repo = Path(repo); store = store or feed.NoteFeedGit(repo)
    recipient = feed.checked_recipient(recipient or json.loads((repo/'config/keirin-note-recipient.json').read_bytes()))
    parent = store.head(); prior = feed.load_index(store, recipient, parent)
    need(prior is not None, 'EXISTING_OWNER_FEED_REQUIRED')
    previous, registered, latest = {}, set(), None
    for entry in prior['entries']:
        if entry['kind'] != KIND or entry['days'] != [doc['day_jst']]: continue
        latest = entry['day_revision']; registered.update(entry['registered_race_ids'])
        for rid, identity in entry['original_revisions'].items():
            old = previous.get(rid)
            need(old is None or old['baseline'] == identity['baseline'] and
                 (old['conditioned'] is None or identity['conditioned'] in {None, old['conditioned']}), 'RETAINED_ORIGINAL_CHANGED')
            previous[rid] = dict(baseline=identity['baseline'], conditioned=identity['conditioned'] or (old or {}).get('conditioned'))
    need(registered <= {r['race_id'] for r in doc['races']}, 'REGISTERED_DENOMINATOR_SHRANK')
    identities = public_identities(doc)
    for rid, identity in identities.items():
        old = previous.get(rid)
        need(old is None or old['baseline'] == identity['baseline'] and
             (old['conditioned'] is None or identity['conditioned'] in {None, old['conditioned']}), 'IMMUTABLE_ORIGINAL_CHANGED')
    # Each entry retains the full registered denominator, but carries the
    # bulky original only when it is new or gains authenticated condition arms.
    # Previously displayed originals remain in append-only encrypted packets.
    changed = 0
    for row in doc['races']:
        old, identity = previous.get(row['race_id']), row['original_identity']
        if old and (identity is None or identity['conditioned'] in {None, old['conditioned']}):
            row['original'] = None
            row['original_identity'] = deepcopy(old)
        elif row['original'] is not None:
            changed += 1
    doc['revision'] = _day_revision(_identity_key(owner_private_pem), doc)
    checked_day(doc)
    if latest == doc['revision']:
        report = dict(state='EXISTING_NATIONWIDE_DISPLAY_REUSED', published_originals=0,
                      published_day_status=0, provider_requests=0)
    else:
        sealed = feed.seal_snapshot(note_packet(doc, source_commit), recipient, kind=KIND, clock=clock)
        saved = feed.publish_snapshot(store, recipient, sealed, expected_parent=parent)
        report = dict(saved, published_originals=changed, published_day_status=1, provider_requests=0)
    if public_doc is not None:
        from . import keirin_public_forecasts as public
        try:
            published_at = (clock or (lambda: datetime.now(timezone.utc)))()
            body = public.project(public_doc, published_at=published_at)
            report['public_forecasts'] = public.publish(repo,body)
        except (OSError,ValueError,TypeError,KeyError,OverflowError,TimeoutExpired):
            report['public_forecasts'] = {'state':'HOLD_PUBLIC_FORECASTS'}
        else:
            try:
                from . import keirin_official_public_card_details as details
                report['public_details'] = details.publish(repo, public_doc, published_at=published_at)
            except (OSError, ValueError, TypeError, KeyError, OverflowError, TimeoutExpired, ImportError):
                report['public_details'] = {'state': 'HOLD_PUBLIC_OFFICIAL_DETAILS'}
    return report
