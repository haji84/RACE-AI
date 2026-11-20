"""Rebuild one official card and its condition evidence from original bytes.

The manifests locate captured documents; their normalized rider facts are not
trusted. Public card, marks, profile and historical results must all identify
the same official registration. This proves local source consistency, not an
independent acquisition timestamp or a medically established fall effect.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from html import unescape
from pathlib import Path
from urllib.parse import urlsplit

from . import keirin_official_canary_card as cards
from . import keirin_official_form_history as history
from . import keirin_nationwide_auto_generator as core
from . import keirin_form_fall_shadow as shadow
from . import keirin_rider_form_evidence as conditions
from .keirin_public_two_source_normalizer import _style


class OfficialJoinError(ValueError):
    pass


def need(ok, code):
    if not ok:
        raise OfficialJoinError('OFFICIAL_JOIN_'+code)


def _raw(sources, digest):
    value = sources.get(digest)
    need(type(digest) is str and core.SHA.fullmatch(digest) is not None and
         type(value) is bytes and 0 < len(value) <= 9_000_000 and
         sha256(value).hexdigest() == digest, 'RAW_SOURCE_SHA_MISMATCH')
    return value


def _one(rows, predicate, code):
    selected = [r for r in rows if predicate(r)]
    need(len(selected) == 1, code)
    return selected[0]


def _page(source, kind='PROGRAM'):
    return dict(kind=kind, url=source.get('url', source.get('source_url')),
                bytes_sha256=source['bytes_sha256'],
                captured_at=history._aware(source.get('captured_at', source.get('observed_at'))).isoformat())


def _require_capture_selection(profile, results_by_reference):
    """Rebuild the bounded collector's required selection from the raw index.

    Valid result pages alone do not prevent a changed manifest from dropping a
    fall or substituting older finishes. The profile's published order, not a
    manifest claim of completeness, establishes which references are required.
    """
    groups = {}
    for ref in profile['history_references']:
        key = (ref['current_meeting'], ref['meeting_label'], ref['venue_label'])
        groups.setdefault(key, []).append(ref)
    newest = [ref for group in groups.values() for ref in reversed(group)]
    normal, required = 0, set()
    for ref in newest:
        if ref['observed_status_symbol'] not in frozenset('123456789'):
            continue
        token_sha = ref['token_sha256']
        need(token_sha in results_by_reference, 'HISTORY_SELECTION_OMITS_PUBLISHED_RESULT')
        required.add(token_sha)
        normal += results_by_reference[token_sha]['status'] == 'FINISHED'
        if normal >= 6:
            break
    need(normal >= 6, 'SIX_NORMAL_FINISHES_REQUIRED')
    crash = next((i for i, ref in enumerate(newest)
                  if ref['observed_status_symbol'] in ('落', '落再')), None)
    if crash is not None:
        required.add(newest[crash]['token_sha256'])
        before = [r for r in newest[crash+1:]
                  if r['observed_status_symbol'] in frozenset('123456789')][:3]
        after = [r for r in reversed(newest[:crash])
                 if r['observed_status_symbol'] in frozenset('123456789')][:3]
        required.update(r['token_sha256'] for r in before+after)
    need(required <= set(results_by_reference), 'HISTORY_SELECTION_OMITS_PUBLISHED_RESULT')


def reparse_card(card_manifest, source_bytes_by_sha, *, now):
    """Ignore normalized marks/IDs; reconstruct them using the published view."""
    now = history._aware(now)
    need(type(card_manifest) is dict and card_manifest.get('schema') == cards.SCHEMA,
         'CARD_MANIFEST_INVALID')
    rid = card_manifest.get('race_id')
    need(type(rid) is str and core.VENUE.fullmatch(rid), 'RACE_ID_INVALID')
    sources = card_manifest.get('sources')
    need(type(sources) is list, 'CARD_SOURCES_REQUIRED')
    roles = {kind: _one(sources, lambda r: r.get('kind') == kind, 'CARD_ROLE_MISSING_OR_DUPLICATE')
             for kind in ('CALENDAR', 'RACE_LIST', 'RACECARD', 'PREDICTION_TAB')}
    paths = {'CALENDAR': ('https://keirin.jp/sp/raceschedule', 'GET'),
             'RACE_LIST': ('https://keirin.jp/sp/racelist', 'POST'),
             'RACECARD': ('https://keirin.jp/sp/race', 'POST')}
    for kind, (url, method) in paths.items():
        need(roles[kind]['url'] == url and roles[kind]['method'] == method,
             'CARD_SOURCE_OR_METHOD_INVALID')
    for source in roles.values():
        need(history._aware(source['captured_at']) <= now, 'SOURCE_CAPTURE_AFTER_PREDICTION')
    cal, listed, detail, tab = (roles[k] for k in ('CALENDAR', 'RACE_LIST', 'RACECARD', 'PREDICTION_TAB'))
    bound = dict(raw_bytes=_raw(source_bytes_by_sha, cal['bytes_sha256']),
                 expected_sha256=cal['bytes_sha256'], observed_at=history._aware(cal['captured_at']))
    detail_raw = _raw(source_bytes_by_sha, detail['bytes_sha256'])
    card = cards.parse_canary_card(list_raw=_raw(source_bytes_by_sha, listed['bytes_sha256']),
        detail_raw=detail_raw, expected_day=f'{rid[:4]}-{rid[4:6]}-{rid[6:8]}',
        venue_code=int(rid[8:10]), race_number=int(rid[10:]), calendar_receipt=bound,
        list_observed_at=history._aware(listed['captured_at']),
        detail_observed_at=history._aware(detail['captured_at']),
        list_sha256=listed['bytes_sha256'], detail_sha256=detail['bytes_sha256'], now=now,
        minimum_margin_seconds=65)
    script_sources = card_manifest.get('navigation_script_receipts')
    need(type(script_sources) is list, 'PUBLISHED_VIEW_SCRIPTS_MISSING')
    scripts = {}
    for path in cards._TAB_SCRIPT_REQUIREMENTS:
        source = _one(script_sources, lambda r: r.get('url') == 'https://keirin.jp'+path,
                      'VIEW_SCRIPT_MISSING_OR_DUPLICATE')
        need(source.get('status') == 200 and source.get('method') == 'GET' and
             history._aware(source['observed_at']) <= history._aware(tab['captured_at']),
             'VIEW_SCRIPT_CAPTURE_INVALID')
        scripts[path] = _raw(source_bytes_by_sha, source['bytes_sha256'])
    need(tab.get('method') == 'GET', 'PREDICTION_TAB_METHOD_INVALID')
    prediction = cards.parse_prediction_tab(raw_bytes=_raw(source_bytes_by_sha, tab['bytes_sha256']),
        expected_sha256=tab['bytes_sha256'], observed_at=history._aware(tab['captured_at']),
        now=now, card=card, detail_raw=detail_raw, scripts=scripts,
        request_url=tab['url'], minimum_margin_seconds=65)
    marks = {r['car']: r for r in prediction['riders']}
    for rider in card['riders']:
        rider.update(marks[rider['car']])
    card['sources'].append(deepcopy(tab))
    card['prediction_tab_updated_at'] = prediction['publisher_updated_at']
    card['mark_provider_raw'] = prediction['mark_provider_raw']
    card['comment_provider_raw'] = prediction['comment_provider_raw']
    need(card.get('line_prediction', {}).get('kind') == 'NO_FIXED_LINE',
         'OBSERVED_LINE_REQUIRED')
    return card


def build_inputs(*, card_manifest, history_manifest, source_bytes_by_sha, now):
    """Build unchanged-model inputs and a separately sealed form supplement.

    V1 condition receipts call a page's displayed update time published_at;
    availability below explicitly records that it is NOT first publication.
    Unknown absence endpoints never become zero days or fabricated intervals.
    """
    now = history._aware(now)
    card = reparse_card(card_manifest, source_bytes_by_sha, now=now)
    rid = card['race_id']
    need(type(history_manifest) is dict and
         history_manifest.get('schema') == 'RACE_AI_KEIRIN_OFFICIAL_FORM_CAPTURE_V1' and
         history_manifest.get('state') == 'OFFICIAL_FORM_HISTORY_CAPTURED' and
         history_manifest.get('target_race_id') == rid, 'HISTORY_MANIFEST_INVALID')
    captured_riders, receipts = history_manifest.get('riders'), history_manifest.get('source_receipts')
    need(type(captured_riders) is list and len(captured_riders) == len(card['riders']) and
         type(receipts) is list and 1 <= len(receipts) <= 150, 'HISTORY_ROSTER_OR_RECEIPTS_INVALID')
    expected = {(r['car'], r['registration_id']) for r in card['riders']}
    need(len(expected) == len(card['riders']) and
         {(r.get('car'), r.get('registration_id')) for r in captured_riders} == expected,
         'HISTORY_REGISTRATION_ROSTER_MISMATCH')
    for row in receipts:
        need(row.get('http_status') == 200 and
             history._aware(row['captured_at']) <= now, 'HISTORY_CAPTURE_INVALID')
    tab = _one(card['sources'], lambda r:r['kind']=='PREDICTION_TAB', 'TAB_SOURCE_REQUIRED')
    program_pages = {_page(tab)['bytes_sha256']: _page(tab)}
    baseline_pages = [_page(_one(card['sources'], lambda r:r['kind']=='RACECARD', 'CARD_REQUIRED'), 'RACECARD'),
                      _page(tab, 'MARKS')]
    riders, evidence, identities, availability = [], [], [], []
    total_results = 0
    for rider in card['riders']:
        car, registration = rider['car'], rider['registration_id']
        captured = _one(captured_riders, lambda r:r.get('car')==car, 'HISTORY_CAR_DUPLICATE')
        psha = captured.get('profile', {}).get('source_sha256')
        psource = _one(receipts, lambda r:r.get('bytes_sha256')==psha and
                      r.get('source_url')=='https://keirin.jp/sp/racerracentrecord?snum='+registration,
                      'PROFILE_REGISTRATION_RECEIPT_MISSING')
        need(psource.get('method') == 'GET', 'PROFILE_METHOD_INVALID')
        profile = history.parse_profile(_raw(source_bytes_by_sha, psha),
            expected_registration_id=registration, observed_at=psource['captured_at'])
        need(cards.receipt._norm(profile['name']) == cards.receipt._norm(rider['name']),
             'PROFILE_REGISTRATION_NAME_MISMATCH')
        stats = profile['stats']
        need(float(rider['score_raw']) == stats['competition_points'] and
             int(rider['statistics_raw']['backCnt']) == stats['b_count'],
             'CARD_PROFILE_STATISTICS_DISAGREE')
        baseline_pages.append(_page(psource)); program_pages[psha] = _page(psource)
        riders.append(dict(car=car, athlete_id=registration, mark_rank=rider['mark_rank'],
            competition_points=stats['competition_points'], recent_form_score=stats['win_rate_percent']/100,
            h_count=stats['h_count'], b_count=stats['b_count'], style=_style(rider['style_raw'])))
        refs = {r['token_sha256']: r for r in profile['history_references']}
        result_rows, history_shas, seen, results_by_reference = [], [], set(), {}
        need(type(captured.get('results')) is list and 1 <= len(captured['results']) <= 40,
             'HISTORY_RESULT_SET_INVALID')
        for hint in captured['results']:
            token_sha, digest = hint.get('reference_token_sha256'), hint.get('source_sha256')
            need(token_sha in refs, 'UNPUBLISHED_HISTORY_REFERENCE')
            ref = refs[token_sha]
            source = _one(receipts, lambda r:r.get('bytes_sha256')==digest and
                          r.get('form_fields')=={'encp':ref['token'], 'disp':'SJ0326'},
                          'HISTORY_RESULT_REFERENCE_RECEIPT_MISSING')
            need(source.get('source_url') == ref['source_url'] and source.get('method') == 'POST',
                 'HISTORY_RESULT_SOURCE_INVALID')
            result = history.parse_history_result(_raw(source_bytes_by_sha, digest),
                expected_registration_id=registration, observed_at=source['captured_at'], expected_reference=ref)
            need(result['race_id'] not in seen and result['race_id'][:8] < rid[:8] and
                 result['status'] in conditions.RESULT_STATES, 'HISTORY_DUPLICATE_FUTURE_OR_UNSUPPORTED')
            seen.add(result['race_id']); history_shas.append(digest)
            results_by_reference[token_sha] = result
            result_rows.append({k:result[k] for k in ('race_id','race_date','status','place','field_size')})
            result_rows[-1].update(published_at=result['source_updated_at'], source_sha256=digest)
            program_pages[digest] = _page(source)
        need(sum(r['status']=='FINISHED' for r in result_rows) >= 6, 'SIX_NORMAL_FINISHES_REQUIRED')
        _require_capture_selection(profile, results_by_reference)
        total_results += len(result_rows)
        comment = unescape(rider.get('comment_raw', ''))
        comments = []
        comment_usable = bool(comment) and len(comment) <= 300 and all(ord(c)>=32 for c in comment)
        if comment_usable:
            # The official page credits a publication; it is not a direct
            # medical examination or independently transcribed rider audio.
            comments.append(dict(speaker='MEDIA', text=comment,
                published_at=card['prediction_tab_updated_at'], source_sha256=tab['bytes_sha256']))
        evidence.append(dict(car=car, results=sorted(result_rows,key=lambda r:(r['race_date'],r['race_id'])),
                             absences=[], comments=comments))
        identities.append(dict(car=car, registration_id=registration, card_sha256=card['source_sha256'],
            marks_sha256=tab['bytes_sha256'], profile_sha256=psha, history_sha256=history_shas))
        availability.append(dict(car=car, registration_id=registration,
            absence_observations=profile['absence_observations'],
            comment_preserved_in_source=bool(comment), comment_encoded_in_v1=comment_usable,
            profile_history_index_count=len(profile['history_references']),
            acquired_result_count=len(result_rows), exhaustive_fall_history_claimed=False))
    all_pages = baseline_pages+list(program_pages.values())
    asof = max(history._aware(p['captured_at']) for p in all_pages).isoformat()
    detail = _one(card['sources'], lambda r:r['kind']=='RACECARD', 'CARD_REQUIRED')
    snapshot = dict(schema=core.SCHEMA, race_id=rid, as_of=asof,
        published_cutoff_at=card['official_cutoff_at'],
        cutoff_source={k:_page(detail)[k] for k in ('url','bytes_sha256','captured_at')},
        source_pages=baseline_pages, competition=card['competition'],
        round_stage=card['round_stage_raw'], round_rule=None,
        line_groups=deepcopy(card['line_prediction']['groups']), riders=riders)
    supplement = dict(schema=shadow.SUPPLEMENT_SCHEMA, race_id=rid,
        source_pages=list(program_pages.values()),
        condition_evidence=dict(schema=conditions.SCHEMA, as_of=asof, riders=evidence))
    core.validate_snapshot(snapshot, computed_at=now.isoformat())
    shadow.source_bundle(snapshot, supplement, generated_at=now.isoformat())
    return dict(snapshot=snapshot, supplement=supplement,
        identity_proof=dict(schema='RACE_AI_KEIRIN_OFFICIAL_IDENTITY_JOIN_V1', race_id=rid,
            verified_riders=len(riders), verified_rider_results=total_results,
            source_facts_sha256=core.digest(snapshot), supplement_sha256=core.digest(supplement),
            independent_origin_attested=False, bindings=identities),
        availability=dict(timestamp_basis='DISPLAYED_PAGE_UPDATE_NOT_FIRST_PUBLICATION',
            absence_records_without_verified_period=sum(len(x['absence_observations']) for x in availability),
            medical_recovery_inferred=False, riders=availability))


def loader_from_capture(*, card_manifest, history_manifest):
    """Trusted runner callback: re-read all bytes and rejoin every identity."""
    cards_copy, history_copy = deepcopy(card_manifest), deepcopy(history_manifest)
    digests = {r['bytes_sha256'] for r in cards_copy['sources']}
    digests.update(r['bytes_sha256'] for r in cards_copy['navigation_script_receipts'])
    digests.update(r['bytes_sha256'] for r in history_copy['source_receipts'])

    def load(*, snapshot, raw_pages_dir, captured_at):
        raw = {}
        for digest in digests:
            need(type(digest) is str and core.SHA.fullmatch(digest), 'RAW_SOURCE_SHA_INVALID')
            path = Path(raw_pages_dir)/(digest+'.html')
            need(path.is_file() and not path.is_symlink() and 0<path.stat().st_size<=9_000_000,
                 'RAW_SOURCE_MISSING')
            raw[digest] = path.read_bytes()
        rebuilt = build_inputs(card_manifest=cards_copy, history_manifest=history_copy,
                               source_bytes_by_sha=raw, now=captured_at)
        need(core.digest(rebuilt['snapshot']) == core.digest(snapshot), 'BASELINE_SOURCE_MISMATCH')
        return rebuilt['supplement']
    return load
