"""Collect bounded, private evidence for unadmitted published class labels.

Uses the already approved official card control and shared source lease. It
does not map unknown labels, generate forecasts or promote model admission.
Only safe_summary may enter a public job receipt; all other source data must
be saved inside the existing owner-encrypted registry envelope.
"""
from datetime import timedelta
import re

from . import keirin_official_nationwide_extension as extension
from . import keirin_official_nationwide_sources as sources
from . import keirin_official_canary_card as cards
from . import keirin_official_form_history as form


SCHEMA = 'RACE_AI_KEIRIN_UNADMITTED_CLASS_EVIDENCE_V1'
# Official program documents also use "ガールズ予選（第1走）" and "ガールズ予選（第2走）".
# These normalized forms are limited to evidence reporting; admission uses OBSERVED_CLASSES.
LABEL = re.compile(
    r'(?:[ASL]級[一-鿿ぁ-ゟ゠-ヿーA-C0-9 ]{1,32}|(?:ガールズ予選|ガ予)[12]|(?:L級)?ガールズ予選\(第[12]走\))'
)
GRADE = re.compile(r'A[123]|S[12S]|L1|[ASL]級[123S]班')


def _need(ok, code):
    if not ok:
        raise ValueError('CLASS_EVIDENCE_'+code)


def _card_reference(listed, calendar, day, number):
    calendar = dict(calendar, observed_at=form._aware(calendar['observed_at']))
    listing = cards.receipt.parse_race_list(listed['raw_bytes'], expected_day=day,
        expected_venue_code=listed['venue_code'], observed_at=form._aware(listed['observed_at']),
        expected_sha256=listed['expected_sha256'], calendar_receipt=calendar)
    ref = next(row for row in listing['race_references'] if row['race_no'] == number)
    row = next(row for row in cards._current_rows(listed['raw_bytes'], day)
               if int(cards.receipt._norm(row['strRaceNo'])) == number)
    _need(ref['link_kind'] == '1' and ref['path'] == '/sp/race', 'PUBLISHED_REFERENCE')
    return cards.receipt._norm(row['strSyumokuName']), ref


def replay_cutoff_hints(previous, inventory, *, now):
    """Use the replayed official registry only for ordering fresh captures."""
    day = inventory['registry']['event_day']
    evidence = previous.get('unadmitted_class_evidence') if previous is not None else None
    if (type(evidence) is not dict or evidence.get('schema') != SCHEMA or
            evidence.get('day_jst') != day or previous['day_jst'] != day):
        return {}
    records = evidence.get('records')
    if (type(records) is not list or len(records) > 4 or
            any(type(row) is not dict or type(row.get('race_id')) is not str for row in records) or
            len({row['race_id'] for row in records}) != len(records)):
        return {}

    now, saved_at = form._aware(now), form._aware(previous['observed_at'])
    old_inventory = previous['inventory']
    old_lists = {source['venue_code']:source for source in old_inventory['list_sources']}
    current_lists = {source['venue_code']:source for source in inventory['list_sources']}
    old_races = {race['race_id'] for race in previous['registry']['races']
                 if race['source_state'] == 'RACECARD_PUBLISHED'}
    current_races = {race['race_id']:race for race in inventory['registry']['races']
                     if race['source_state'] == 'RACECARD_PUBLISHED'}

    cutoff_hints = {}
    for record in records:
        race = current_races.get(record['race_id'])
        if race is None or record['race_id'] not in old_races:
            continue
        try:
            venue, number = race['venue_code'], race['race_no']
            listed = old_lists[venue]
            _need(record['prediction_admitted'] is False and record['list_source'] == listed, 'SAVED_LIST')
            label, reference = _card_reference(listed, old_inventory['calendar_receipt'], day, number)
            current = _card_reference(current_lists[venue], inventory['calendar_receipt'], day, number)
            _need(label in extension.OBSERVED_CLASSES and label == record['class_label'] and
                  current == (label, reference), 'CURRENT_CARD_BINDING')
            source = record['detail_source']
            url = 'https://keirin.jp/sp/race'
            _need(type(source) is dict and source.get('source_url') == source.get('request_url') == url and
                  source.get('http_status') == 200, 'SAVED_DETAIL')
            _need(source.get('receipt') == dict(source_url=url, method='POST', http_status=200,
                form_fields={'encp':reference['opaque_reference'], 'disp':'SJ0315'},
                captured_at=source['observed_at'], bytes_sha256=source['expected_sha256'], kind='PROGRAM'),
                'SAVED_REQUEST_BINDING')
            observed = form._aware(source['observed_at'])
            _need(form._aware(listed['observed_at']) <= observed <= saved_at <= now, 'REPLAY_SOURCE_CLOCK')
            calendar = dict(old_inventory['calendar_receipt'],
                            observed_at=form._aware(old_inventory['calendar_receipt']['observed_at']))
            detail = cards.receipt.parse_race_detail(source['raw_bytes'], expected_day=day,
                expected_venue_code=venue, expected_race_number=number, observed_at=observed,
                expected_sha256=source['expected_sha256'], calendar_receipt=calendar)
            cutoff = form._aware(detail['official_cutoff_at'])
            if not detail['race_cancelled'] and now + timedelta(seconds=65) <= cutoff:
                cutoff_hints[race['race_id']] = cutoff
        except (ValueError, KeyError, TypeError, StopIteration):
            continue
    return cutoff_hints


def collect_unknown_class_evidence(*, session, inventory, clock, max_classes=4):
    _need(type(max_classes) is int and 1 <= max_classes <= 4, 'BOUND')
    registry = inventory['registry']
    _need(type(registry) is dict, 'REGISTRY_REQUIRED')
    day = registry['event_day']
    cal = dict(inventory['calendar_receipt'])
    cal['observed_at'] = form._aware(cal['observed_at'])
    records, rejected, safe, attempted = [], [], [], set()
    budget_pending = False
    before = session.count
    for race in sorted(registry['races'], key=lambda r:(r['race_no'], r['venue_code'])):
        if session.halted or len(attempted) >= max_classes:
            break
        if race['source_state'] == 'RESULT_PUBLISHED':
            continue
        listed = next(s for s in inventory['list_sources'] if s['venue_code'] == race['venue_code'])
        selected = [r for r in cards._current_rows(listed['raw_bytes'], day)
                    if int(cards.receipt._norm(r['strRaceNo'])) == race['race_no']]
        if len(selected) != 1:
            continue
        label = cards.receipt._norm(selected[0]['strSyumokuName'])
        if label in extension.OBSERVED_CLASSES or label in attempted:
            continue
        parsed = cards.receipt.parse_race_list(listed['raw_bytes'], expected_day=day,
            expected_venue_code=race['venue_code'], observed_at=form._aware(listed['observed_at']),
            expected_sha256=listed['expected_sha256'], calendar_receipt=cal)
        ref = next((r for r in parsed['race_references'] if r['race_no'] == race['race_no']), None)
        if ref is None or ref['link_kind'] != '1' or ref['path'] != '/sp/race':
            continue
        attempted.add(label)
        summary = dict(race_id=race['race_id'], class_label=label if LABEL.fullmatch(label) else
            'UNRECOGNIZED_CLASS_LABEL', prediction_admitted=False, state='SOURCE_CAPTURE_FAILED',
            source_host='keirin.jp', source_path='/sp/race', http_status=None)
        raw = None
        stage = 'SOURCE_CAPTURE_FAILED'
        try:
            sources.require_list_scripts(session, listed)
            raw = session.fetch('https://keirin.jp/sp/race',
                [('encp', ref['opaque_reference']), ('disp', 'SJ0315')], 'https://keirin.jp/sp/racelist')
            stage = 'DETAIL_VALIDATION_FAILED'
            summary['http_status'] = raw['http_status']
            detail = cards.receipt.parse_race_detail(raw['raw_bytes'], expected_day=day,
                expected_venue_code=race['venue_code'], expected_race_number=race['race_no'],
                observed_at=form._aware(raw['observed_at']), expected_sha256=raw['expected_sha256'],
                calendar_receipt=cal)
            at, now = form._aware(raw['observed_at']), form._aware(clock())
            _need(form._aware(listed['observed_at']) <= at <= now and
                  now + timedelta(seconds=65) <= form._aware(detail['official_cutoff_at']), 'FUTURE_CLOCK')
            embedded = cards.receipt._embedded(cards.browser_source._document(raw['raw_bytes']))
            grades = sorted(set(cards.receipt._norm(row['kyuhan'])
                                for row in embedded['SJ0315']['sensyuTypeInfo']))
            _need(detail['race_id'] == race['race_id'], 'RACE_IDENTITY')
            summary.update(state='PUBLISHED_CLASS_CARD_EVIDENCE_ONLY',
                grades=[grade if GRADE.fullmatch(grade) else 'UNRECOGNIZED_GRADE' for grade in grades],
                rider_count=len(detail['riders']), official_cutoff_at=detail['official_cutoff_at'],
                observed_at=at.isoformat(), list_sha256=listed['expected_sha256'],
                detail_sha256=raw['expected_sha256'])
            records.append(dict(race_id=race['race_id'], class_label=label, grades=grades,
                list_source=listed, detail_source=raw, parsed_card=detail, prediction_admitted=False))
        except sources.CaptureBudgetPending:
            budget_pending = True
            break
        except (ValueError, KeyError, TypeError, OSError):
            summary['state'] = stage
            if raw is not None:
                rejected.append(dict(race_id=race['race_id'], list_source=listed, detail_source=raw,
                                     prediction_admitted=False))
        safe.append(summary)
    return dict(schema=SCHEMA, day_jst=day, records=records, rejected_sources=rejected,
        safe_summary=safe, source_requests=session.count-before, provider_denied=session.provider_denied,
        budget_pending=budget_pending, model_generation=0)
