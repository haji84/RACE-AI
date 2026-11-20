"""Source-bound result overlays for the existing encrypted owner display.

This adapter never generates a forecast, fetches a provider or changes a stop.
An official label requires reparse of the saved official response bytes. Scores
are copied only from the existing scorer's matching source/revision receipt.
"""
from datetime import datetime, timezone
from hashlib import sha256
from copy import deepcopy
import hmac
import json
from pathlib import Path
import re

from . import keirin_note_feed as feed
from .keirin_note_view import canonical, SCHEMA as NOTE_SCHEMA

SCHEMA = 'RACE_AI_KEIRIN_RESULT_UPDATES_V1'
ARMS = ('A', 'B', 'C', 'adjusted_A', 'adjusted_B')
SOURCES = {'keirin_jp', 'kdreams', 'netkeirin', 'official_pdf', 'official_json'}
SHA = re.compile(r'[0-9a-f]{64}')


def need(ok, code):
    if not ok: raise ValueError('RESULT_UPDATE_' + code)


def when(value):
    need(type(value) is str and len(value) <= 40, 'CLOCK')
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    need(stamp.utcoffset() is not None, 'CLOCK')
    return stamp


def pending_arm(state='pending'):
    return dict(state=state, points=None, stake_yen=None, return_yen=None)


def checked_updates(doc):
    need(type(doc) is dict and set(doc) == {'schema', 'observed_at', 'races'} and
         doc['schema'] == SCHEMA and type(doc['races']) is list and
         len(doc['races']) <= 300, 'DOCUMENT')
    observed = when(doc['observed_at']); seen = set()
    fields = {'race_id', 'revision', 'observed_at', 'authority', 'order_status',
              'payout_status', 'winning_triples', 'payouts_100yen',
              'source_comparison', 'diagnostics', 'arms'}
    for row in doc['races']:
        need(type(row) is dict and set(row) == fields, 'ROW')
        rid = row['race_id']
        need(type(rid) is str and re.fullmatch(r'20[0-9]{10}', rid) and rid not in seen, 'RACE_ID')
        datetime.strptime(rid[:8], '%Y%m%d'); seen.add(rid)
        need(type(row['revision']) is str and SHA.fullmatch(row['revision']), 'REVISION')
        need(when(row['observed_at']) <= observed, 'OBSERVATION_ORDER')
        need(row['authority'] in {'official', 'secondary'} and
             row['order_status'] in {'confirmed', 'pending', 'conflict'} and
             row['payout_status'] in {'confirmed', 'pending', 'held'}, 'STATUS')
        winners = row['winning_triples']; payouts = row['payouts_100yen']
        need(type(winners) is list and len(winners) <= 20 and
             len(set(winners)) == len(winners), 'WINNERS')
        if row['order_status'] == 'confirmed': need(bool(winners), 'CONFIRMED_ORDER_REQUIRED')
        for triple in winners:
            need(type(triple) is str and re.fullmatch(r'[1-9]-[1-9]-[1-9]', triple) and
                 len(set(triple.split('-'))) == 3, 'WINNER')
        need(type(payouts) is dict and set(payouts) <= set(winners) and
             all(type(v) is int and 100 <= v <= 10**9 for v in payouts.values()), 'PAYOUT')
        if row['payout_status'] == 'confirmed':
            need(row['authority'] == 'official' and row['order_status'] == 'confirmed' and
                 set(payouts) == set(winners), 'OFFICIAL_UNIT_REQUIRED')
        else:
            need(not payouts, 'NO_UNCONFIRMED_MONEY')
        if row['order_status'] != 'confirmed': need(not winners, 'PENDING_ORDER')
        comparisons = row['source_comparison']
        need(type(comparisons) is list and len(comparisons) <= len(SOURCES), 'SOURCE_COMPARISON')
        compared_sources = set()
        for item in comparisons:
            need(type(item) is dict and set(item) == {'source_id', 'state'} and
                 item['source_id'] in SOURCES and item['source_id'] not in compared_sources and
                 item['state'] in {'matched', 'different', 'unavailable', 'unverified'}, 'SOURCE_COMPARISON')
            compared_sources.add(item['source_id'])
        need(type(row['diagnostics']) is list and len(row['diagnostics']) <= 32, 'DIAGNOSTICS')
        if row['diagnostics']:
            from .keirin_result_diagnostics import checked_diagnostics
            checked_diagnostics(row['diagnostics'])
        need(type(row['arms']) is dict and set(row['arms']) == set(ARMS), 'ARMS')
        for arm in row['arms'].values():
            need(type(arm) is dict and set(arm) == {'state', 'points', 'stake_yen', 'return_yen'} and
                 arm['state'] in {'hit', 'miss', 'pending', 'void', 'unverifiable'}, 'ARM')
            need(arm['points'] is None or type(arm['points']) is int and 1 <= arm['points'] <= 504, 'POINTS')
            for key in ('stake_yen', 'return_yen'):
                need(arm[key] is None or type(arm[key]) is int and 0 <= arm[key] <= 504*10**9, 'ARM_MONEY')
            if arm['state'] in {'hit', 'miss', 'void'}:
                need(row['authority'] == 'official' and row['order_status'] == 'confirmed', 'OFFICIAL_ARM_REQUIRED')
            if arm['state'] in {'pending', 'unverifiable'} or row['payout_status'] != 'confirmed':
                need(arm['stake_yen'] is None and arm['return_yen'] is None, 'ARM_MONEY_HELD')
    return doc


def _finish(row):
    row['revision'] = sha256(canonical({key: value for key, value in row.items()
                                      if key not in {'revision', 'observed_at'}})).hexdigest()
    return row


def from_official_records(records, report):
    """Reparse official JSON captures and bind optional existing score receipts."""
    from . import keirin_official_public_source as official
    from . import keirin_nationwide_auto_generator as model
    need(type(records) is dict and type(report) is dict, 'INPUT')
    receipts = {r['race_id']: r for r in report.get('result_receipts', [])}
    rows = []
    for rid, record in sorted(records.items()):
        need(type(record) is dict and record.get('race_id') == rid and
             official.reparse_race_result(record), 'OFFICIAL_RAW_REPARSE_REQUIRED')
        if record['state'] != 'OFFICIAL_FINAL': continue
        result = record['result']
        winners = ['-'.join(map(str, t)) for t in result['winning_triples']]
        paid = {'-'.join(map(str, r['triple'])): r['yen'] for r in result['payouts_100yen']}
        row = dict(race_id=rid, observed_at=result['observed_at'], authority='official',
            order_status='confirmed', payout_status='confirmed', winning_triples=winners,
            payouts_100yen=paid, source_comparison=[dict(source_id='official_json', state='matched')],
            diagnostics=[], arms={role: pending_arm('unverifiable' if role in {'A','B'} else 'pending')
                                  for role in ARMS})
        receipt = receipts.get(rid, {})
        bound = (receipt.get('source_sha256') == result['source_sha256'] and
                 receipt.get('result_revision_sha256') == model.digest({
                     k:v for k,v in result.items() if k != 'observed_at'}))
        if bound and receipt.get('state') == 'AB_SETTLED_FROM_INDEPENDENT_RECEIPTS':
            for role, name in (('A', 'A_existing'), ('B', 'B_six_phase')):
                score = receipt.get(name)
                if type(score) is not dict: continue
                stake = score.get('stake_yen'); returned = score.get('payout_yen')
                need(type(stake) is int and 100 <= stake <= 1200 and stake % 100 == 0 and
                     type(returned) is int and 0 <= returned <= 12*10**9 and
                     type(score.get('hit_at_all')) is bool, 'SCORER_RECEIPT')
                row['arms'][role] = dict(state='hit' if score['hit_at_all'] else 'miss',
                    points=stake//100, stake_yen=stake, return_yen=returned)
        elif bound and receipt.get('state') == 'CANCELLED_FULL_REFUND_NO_MODEL_SCORE':
            row['arms']['A'] = pending_arm('void'); row['arms']['B'] = pending_arm('void')
        rows.append(_finish(row))
    at = max((when(r['observed_at']) for r in rows), default=datetime(1970,1,1,tzinfo=timezone.utc))
    return checked_updates(dict(schema=SCHEMA, observed_at=at.isoformat(), races=rows))


def compare_saved_sources(official_update, secondary_pair):
    """Compare the same race against retained secondary observations only.

    The result remains secondary evidence; this function performs no requests
    and cannot create or upgrade an official result.
    """
    from .keirin_secondary_result_consensus import compare_sources
    need(type(secondary_pair) in (list, tuple) and len(secondary_pair) == 2, 'SECONDARY_PAIR')
    consensus = compare_sources(*secondary_pair)
    need(official_update['authority'] == 'official' and
         consensus['race_id'] == official_update['race_id'], 'SAME_RACE_COMPARISON')
    by_provider = {item['provider']: item for item in secondary_pair}
    compared = []
    for provider, source in (('Kdreams','kdreams'), ('netkeirin','netkeirin')):
        item = by_provider[provider]
        need(item.get('official_organizer_result') is False and
             type(item.get('source_bytes_sha256')) is str and
             SHA.fullmatch(item['source_bytes_sha256']), 'SECONDARY_PROVENANCE')
        when(item['observed_at'])
        triple = item['winning_triple']
        order = '-'.join(map(str, triple))
        matches = order in official_update['winning_triples']
        if official_update['payout_status'] == 'confirmed':
            matches = matches and official_update['payouts_100yen'].get(order) == item['payout_per_100yen']
        compared.append(dict(source_id=source, state='matched' if matches else 'different'))
    return compared


def from_canary_comparison(*, payload, scored, final_capture):
    """Display the existing canary scorer's authenticated comparison.

    Called only after compare_frozen and encrypted archive readback. Reparse
    result bytes again here, so a normalized official flag is insufficient.
    """
    from . import keirin_official_form_history as form
    from .keirin_result_diagnostics import checked_diagnostics
    rid = payload['race_id']
    official_result = form.parse_final_result(final_capture['raw_result'],
        expected_race_id=rid, observed_at=final_capture['observed_at'],
        expected_reference=final_capture['expected_reference'],
        verified_unit_evidence=final_capture.get('unit_evidence'),
        unit_verified_at=final_capture.get('unit_verified_at'),
        source_bytes_by_sha=final_capture['source_bytes_by_sha'])
    need(scored.get('official_result') == official_result and
         type(scored.get('origin_receipts')) is dict and
         set(scored['origin_receipts']) == {'baseline_origin','condition_origin','official_final'},
         'CANARY_VERIFIED_COMPARISON_REQUIRED')
    money = official_result['monetary_comparison_eligible'] is True
    observed = max(when(official_result['observed_at']),
                   when(final_capture.get('unit_verified_at') or official_result['observed_at']))
    row = dict(race_id=rid, observed_at=observed.isoformat(), authority='official',
        order_status='confirmed', payout_status='confirmed' if money else 'pending',
        winning_triples=['-'.join(map(str,t)) for t in official_result['winning_triples']],
        payouts_100yen={'-'.join(map(str,r['triple'])):r['yen']
                       for r in official_result.get('payouts_100yen',[])},
        source_comparison=[dict(source_id='keirin_jp',state='matched')],
        diagnostics=checked_diagnostics(final_capture.get('safe_diagnostics',[])),
        arms={role:pending_arm() for role in ARMS})
    if money:
        comparison = scored['comparison']
        need(comparison['paired_comparable_races'] == 1 and len(comparison['records']) == 1 and
             comparison['records'][0]['race_id'] == rid and
             comparison['records'][0]['state'] == 'PAIRED_CONDITIONED_RESEARCH_COMPARABLE',
             'CANARY_FOUR_ARM_SCORE_REQUIRED')
        scores = comparison['records'][0]['scored']
        for role in ('A','B'):
            for family,name in (('old',role),('conditioned','adjusted_'+role)):
                score = scores[role][family]
                row['arms'][name] = dict(state='hit' if score['all_hit'] else 'miss',
                    points=score['stake_yen']//100, stake_yen=score['stake_yen'], return_yen=score['payout_yen'])
    else:
        comparison = scored['order_comparison']
        need(comparison['race_id'] == rid and comparison['monetary_comparison_eligible'] is False,
             'CANARY_ORDER_SCORE_REQUIRED')
        for role,name in (('A','A'),('B','B'),('A_conditioned','adjusted_A'),('B_conditioned','adjusted_B')):
            score = comparison['arms'][role]
            row['arms'][name] = dict(state='hit' if score['all_hit'] else 'miss',
                points=score['points'],stake_yen=None,return_yen=None)
    return checked_updates(dict(schema=SCHEMA,observed_at=observed.isoformat(),races=[_finish(row)]))


def saved_canary_updates(repo, owner_private_pem):
    """Replay the retained fixed trial, including order-only partial results.

    No provider route, runtime-clock backdating or fresh forecast is involved.
    Saved GitHub origin bundles and original ciphertext are re-authenticated.
    """
    from scripts import keirin_official_form_canary as canary
    payload, receipt, settled = canary._load_original_bundle(repo, owner_private_pem)
    if not settled: return None
    raw_base, raw_conditioned, _ = canary._archived_pair(repo, payload)
    scored = canary.replay_saved_result(payload=payload, bundle_receipt=receipt,
        saved_pair=settled[-1], raw_baseline=raw_base, raw_conditioned=raw_conditioned,
        owner_private_pem=owner_private_pem)
    return from_canary_comparison(payload=payload, scored=scored,
                                 final_capture=settled[-1][0]['final_capture'])


def note_packet(updates, source_commit):
    checked_updates(updates)
    need(updates['races'] and type(source_commit) is str and
         re.fullmatch(r'[0-9a-f]{40}', source_commit), 'PACKET_SCOPE')
    days = sorted({r['race_id'][:4]+'-'+r['race_id'][4:6]+'-'+r['race_id'][6:8] for r in updates['races']})
    files = {}
    for day in days:
        selected = [r for r in updates['races'] if r['race_id'].startswith(day.replace('-', ''))]
        raw = canonical(dict(schema=SCHEMA, observed_at=updates['observed_at'], races=selected))
        files['data/'+day+'/result_updates.json'] = dict(text=raw.decode(), bytes=len(raw), sha256=sha256(raw).hexdigest())
    return dict(schema=NOTE_SCHEMA, scope='OWNER_SOURCE_BOUND_RESULT_UPDATES',
        source_commit=source_commit, imported_at=updates['observed_at'], dates=days, files=files,
        formal_model_admission=False, production_weight_switch=False,
        original_files_preserved=True, wagers_placed=False)


def publish_updates(repo, updates, source_commit, *, owner_private_pem=None,
                    clock=None, store=None, recipient=None):
    """Publish captured results without source I/O or a provider-stop release."""
    checked_updates(updates)
    if not updates['races']:
        return dict(state='NO_ADMITTED_RESULT_UPDATES', published_races=0, provider_requests=0)
    # A plain hash of a small hit/miss summary is guessable. Public revision
    # identifiers are domain-separated keyed commitments, using the private key
    # already configured and verified for this result job. No new secret or
    # key file is created, and forecast/source encryption is unchanged.
    from scripts.keirin_official_day_pipeline import check_owner_private_key
    from cryptography.hazmat.primitives import serialization
    check_owner_private_key(owner_private_pem)
    private_der = serialization.load_pem_private_key(owner_private_pem, password=None).private_bytes(
        serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    identity_key = sha256(b'RACE_AI_RESULT_DISPLAY_ID_KEY_V1\x00'+private_der).digest()
    updates = deepcopy(updates)
    from .keirin_saved_source_comparison import retained_source_comparisons
    comparisons = retained_source_comparisons(repo, updates['races'], clock=clock)
    for row in updates['races']:
        if row['race_id'] in comparisons:
            row['source_comparison'] = comparisons[row['race_id']]
            _finish(row)
        row['revision'] = hmac.new(identity_key,
            b'RACE_AI_RESULT_DISPLAY_REVISION_V1\x00'+row['race_id'].encode()+b':'+row['revision'].encode(),
            'sha256').hexdigest()
    checked_updates(updates)
    repo = Path(repo)
    store = store or feed.NoteFeedGit(repo)
    recipient = feed.checked_recipient(recipient or json.loads((repo/'config/keirin-note-recipient.json').read_bytes()))
    parent = store.head(); prior = feed.load_index(store, recipient, parent)
    need(prior is not None, 'EXISTING_OWNER_FEED_REQUIRED')
    note = note_packet(updates, source_commit)
    current_revisions = {}
    for entry in prior['entries']:
        if entry['kind'] == 'result': current_revisions.update(entry['result_revisions'])
    if all(current_revisions.get(row['race_id']) == row['revision'] for row in updates['races']):
        return dict(state='EXISTING_RESULT_DISPLAY_REUSED', published_races=0, provider_requests=0)
    sealed = feed.seal_snapshot(note, recipient, kind='result', clock=clock)
    saved = feed.publish_snapshot(store, recipient, sealed, expected_parent=parent)
    return dict(saved, published_races=len(updates['races']), provider_requests=0)
