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
LABEL = re.compile(r'[ASL]級[一-鿿ぁ-ゟ゠-ヿーA-C0-9 ]{1,32}')
GRADE = re.compile(r'A[123]|S[12S]|L1|[ASL]級[123S]班')


def _need(ok, code):
    if not ok:
        raise ValueError('CLASS_EVIDENCE_'+code)


def collect_unknown_class_evidence(*, session, inventory, clock, max_classes=4):
    _need(type(max_classes) is int and 1 <= max_classes <= 4, 'BOUND')
    registry = inventory['registry']
    _need(type(registry) is dict, 'REGISTRY_REQUIRED')
    day = registry['event_day']
    cal = dict(inventory['calendar_receipt'])
    cal['observed_at'] = form._aware(cal['observed_at'])
    records, rejected, safe, attempted = [], [], [], set()
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
        except (ValueError, KeyError, TypeError, OSError):
            summary['state'] = stage
            if raw is not None:
                rejected.append(dict(race_id=race['race_id'], list_source=listed, detail_source=raw,
                                     prediction_admitted=False))
        safe.append(summary)
    return dict(schema=SCHEMA, day_jst=day, records=records, rejected_sources=rejected,
        safe_summary=safe, source_requests=session.count-before, provider_denied=session.provider_denied,
        model_generation=0)
