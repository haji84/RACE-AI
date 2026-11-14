"""Authored sixteen-request probe evidence; no live source or actual owner key.

The nine wire requests below are invented before the fixture journal is sealed.
They are not recovered network traffic or a claim about a genuine source run.
"""
import base64
from copy import deepcopy
from datetime import datetime, timedelta
from functools import lru_cache
from hashlib import sha256
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai.boat_all_model_store import open_forecasts, seal_forecasts
from tests import test_all_existing_model_official_continuation as seed
from tests import test_all_existing_model_official_recovery as legacy


PROFILE_MODULE = 'race_ai.all_existing_model_official_probe16'
PROFILE_REQUEST = 'RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V4'
PROFILE_MODE = 'FIXED_ATTEMPT_TWO_SINGLE_NORMAL_UI_PROBE_16'
HISTORICAL_PROFILE_MODE = 'FIXED_ATTEMPT_TWO_HISTORICAL_SINGLE_NORMAL_UI_PROBE_16'
PROBE_RUN = 177
PROBE_HEAD = 'd' * 40
PROBE_JOURNAL_ID = 190001
PROBE_RESULT_ID = 190002
AUTHORED_REQUEST_COUNT = 9


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def _shift_timestamps(value, delta):
    """Move authored acquisition clocks, leaving event dates and raw facts exact."""
    if type(value) is dict:
        return {key: _shift_timestamps(child, delta) for key, child in value.items()}
    if type(value) is list:
        return [_shift_timestamps(child, delta) for child in value]
    if type(value) is str and 'T' in value:
        try:
            clock = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if clock.utcoffset() is not None:
                return (clock + delta).isoformat()
        except ValueError:
            pass
    return value


def _write_private(path, raw):
    path.write_bytes(raw)
    path.chmod(0o600)


def _unpack_wire(journal, root, *, delta=timedelta()):
    index = None
    for item in journal['browser_quarantine']['files']:
        raw = base64.b64decode(item['raw_base64'], validate=True)
        if item['kind'] == 'CANONICAL_RETURNED_OBJECT':
            index = _shift_timestamps(json.loads(raw), delta)
            continue
        if item['kind'] in ('HTTP_METADATA', 'ORIGINAL_INDEX'):
            raw = _wire(_shift_timestamps(json.loads(raw), delta))
        _write_private(root / item['file'], raw)
    if index is None:
        raise AssertionError('authored seed lacks its original canonical UI index')
    return index


def _append_static_requests(index, root, *, count):
    """Give every extra invented request its own raw body, metadata and outcome."""
    start = datetime.fromisoformat(index['started_at'])
    existing = {entry['sequence'] for entry in index['responses']}
    for number in range(3, count + 1):
        if number in existing:
            continue
        raw = ('/* authored normal UI fixture asset %d */' % number).encode()
        source = 'https://autorace.jp/assets/authored-probe-%02d.js' % number
        began = start + timedelta(seconds=number - .2)
        completed = start + timedelta(seconds=number)
        metadata = dict(source_url=source, final_url=source, status=200,
            method='GET', http_method='GET', resource_type='script',
            fetched_at=began.isoformat(), response_received_at=completed.isoformat(),
            byte_count=len(raw), source_sha256=sha256(raw).hexdigest(),
            headers={'Content-Type': 'application/javascript'})
        body_name = 'authored-static-%02d.body' % number
        metadata_name = 'authored-static-%02d.metadata.json' % number
        _write_private(root / body_name, raw)
        _write_private(root / metadata_name, _wire(metadata))
        index['responses'].append(dict(sequence=number, body_file=body_name,
                                       metadata_file=metadata_name))
        index['ledger'].append(dict(sequence=number, status=200, method='GET',
            resource_type='script', request_started_at=began.isoformat(),
            headers_received_at=completed.isoformat()))
    index['actual_request_count'] = count


def _refresh_wire_projection(journal, index, root):
    from scripts import all_existing_model_official_result_collect as collector
    planned = [dict(sport=case['sport'], race_id=case['race_id'])
               for case in journal['cases']]
    journal['browser_index'] = collector._index_diagnostic(index, planned)
    journal['browser_quarantine'] = collector._browser_quarantine(
        index, root, maximum_json=12 * 1024 * 1024)
    if journal['browser_quarantine']['complete'] is not True:
        raise AssertionError('authored fixture unexpectedly exceeded its unchanged wire bound')


@lru_cache(maxsize=2)
def _authored_continuation(historical=False):
    """Real fixture fit/native/V4 MAC/wire/RESULT/new-MAC inputs, privately sealed."""
    from race_ai import all_existing_model_official_probe16 as profile
    from race_ai import all_existing_model_official_recovery as recovery
    from race_ai import all_existing_model_official_historical as history
    from race_ai import all_existing_model_official_results as official
    from scripts import all_existing_model_official_result_collect as collector
    from tests import test_all_existing_model_order_only_pdca as pairs

    previous, _ = seed.complete_fixture()
    previous = deepcopy(previous)
    old_archive = next(item for item in previous['journal_archives']
                       if item['metadata']['id'] == recovery.OLD_ARTIFACT)
    old_cipher = collector._journal_cipher(old_archive['raw'])
    old_body = open_forecasts(old_cipher, key=legacy.KEY)
    original_plan = deepcopy(previous['old_plan'])
    new_plan = dict(deepcopy(original_plan), maximum_requests=16)
    plan_cipher = seal_forecasts(new_plan, run_id=str(PROBE_RUN), round_no=900006,
                                key=legacy.KEY)
    plan_sha = sha256(plan_cipher).hexdigest()
    source_archive = next(item for item in previous['journal_archives']
                          if item['metadata']['id'] == 90001)
    journal = open_forecasts(collector._journal_cipher(source_archive['raw']),
                             key=legacy.KEY)
    delta = timedelta(days=1) if historical else timedelta()
    start = datetime.fromisoformat(journal['epoch_started_at']) + delta
    end = start + timedelta(seconds=20)
    manifest = deepcopy(old_body['manifest'])
    manifest.update(schema=collector.SCHEMA_V3 if historical else collector.SCHEMA_V2,
        execution_day=start.astimezone(collector.JST).date().isoformat(),
        plan_path='audit/state/official-result-collection-plan-' + plan_sha + '.enc',
        plan_sha256=plan_sha, prior_journal_artifacts=[seed.pin(old_archive['metadata'])],
        allow_order_only=True)
    if historical:
        manifest['target_event_day'] = original_plan['execution_day']
    request = dict(schema=PROFILE_REQUEST, repository_id=recovery.REPOSITORY_ID,
        pull_request=71, mode=HISTORICAL_PROFILE_MODE if historical else PROFILE_MODE,
        probe_sport='autorace', old_journal_artifact_id=recovery.OLD_ARTIFACT,
        manifest=manifest)
    first = deepcopy(previous['probe_first_attempt'])
    first.update(id=PROBE_RUN, head_sha=PROBE_HEAD,
                 updated_at=(start - timedelta(seconds=1)).isoformat(),
                 run_started_at=(start - timedelta(minutes=10)).isoformat())
    issued = dict(request=request,
        target=dict(run_id=PROBE_RUN, head_sha=PROBE_HEAD, run_attempt=2),
        issued_at=start.isoformat(), not_before=start.isoformat(),
        expires_at=(start + timedelta(minutes=30)).isoformat(),
        old_journal_raw=old_archive['raw'], old_journal_metadata=old_archive['metadata'],
        old_run=previous['old_run'], prior_runs=[], first_attempt=first,
        old_plan=original_plan, new_plan=new_plan,
        prior_journal_archives=[deepcopy(old_archive)])
    authority = profile.issue_consume_capsule(issued, legacy.KEY)
    active = dict(first, run_attempt=2, status='in_progress', conclusion=None)
    validated = profile.validate_capsule(authority, data=issued, current_run=active,
                                         now=start, key=legacy.KEY)

    journal.update(schema=collector.JOURNAL_V3 if historical else collector.JOURNAL_V2,
        execution_day=manifest['execution_day'], manifest=deepcopy(manifest),
        manifest_sha256=digest(manifest), collection_plan_sha256=plan_sha,
        epoch_started_at=start.isoformat(), workflow_run_id=PROBE_RUN,
        code_sha=PROBE_HEAD, maximum_requests=16,
        recovery_authorization=validated.audit())
    if historical:
        journal['target_event_day'] = manifest['target_event_day']
    journal['browser_attempt'].update(state='COMPLETE', reserved_request_limit=16,
        actual_request_count=AUTHORED_REQUEST_COUNT, started_at=start.isoformat(),
        completed_at=end.isoformat(), stop_reason='FINISHED')
    with tempfile.TemporaryDirectory(prefix='authored-probe16-wire-') as folder:
        root = Path(folder)
        root.chmod(0o700)
        index = _unpack_wire(journal, root, delta=delta)
        index.update(maximum_requests=16, completed_at=end.isoformat())
        _append_static_requests(index, root, count=AUTHORED_REQUEST_COUNT)
        case = new_plan['cases'][0]
        planned = [dict(sport=case['sport'], race_id=case['race_id'])]
        found, states, originals = collector.browser_sources(index, root, planned,
            started=start, now=end, remaining=16)
        journal['browser_captures'] = originals
        journal['captures'] = [row[2] for row in found]
        _refresh_wire_projection(journal, index, root)
    if states != [dict(sport=case['sport'], race_id=case['race_id'], state='CAPTURED')]:
        raise AssertionError('authored normal UI closure did not capture exactly one case')
    native = deepcopy(pairs.templates()['autorace'][2])
    label = collector._parse(journal['captures'][0], native, 'autorace', now=end,
                             allow_order_only=True)
    if label['status'] != 'rank_confirmed':
        raise AssertionError('authored original normal RESULT unexpectedly changed')
    journal['cases'] = [dict(sport=case['sport'], race_id=case['race_id'],
                             state=label['status'])]
    payload = official.build_result_payload(journal['captures'], [label],
        run_id=PROBE_RUN, code_sha=PROBE_HEAD, generated_at=end,
        day_jst=original_plan['execution_day'], frozen_native_payloads=[native],
        allow_order_only=True)
    result_raw = seed.zipped(seal_forecasts(payload, run_id=str(PROBE_RUN),
        round_no=collector.ROUND, key=legacy.KEY), 'results.enc')
    result_meta = seed.metadata(result_raw, PROBE_RESULT_ID,
        'all-existing-official-results-%d-%d' % (PROBE_RUN, collector.ROUND),
        PROBE_RUN, PROBE_HEAD, end + timedelta(seconds=2))
    journal_raw = seed.zipped(seal_forecasts(journal, run_id=str(PROBE_RUN),
        round_no=900006, key=legacy.KEY), 'collection.enc')
    journal_meta = seed.metadata(journal_raw, PROBE_JOURNAL_ID,
        'official-result-collection-journal-' + str(PROBE_RUN),
        PROBE_RUN, PROBE_HEAD, end + timedelta(seconds=2))
    now = end + timedelta(hours=1, seconds=10)
    continuation = deepcopy(previous)
    continuation['request'].update(
        schema=history.REQUEST if historical else 'RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V2',
        mode=history.CONTINUATION_MODE if historical else 'FIXED_ATTEMPT_TWO_AFTER_VERIFIED_SAME_HOST_PROBE',
        probe_journal_artifact_id=PROBE_JOURNAL_ID,
        probe_result_artifact_id=PROBE_RESULT_ID,
        probe_request_sha256=digest(request))
    continuation['request']['manifest'].update(
        schema=collector.SCHEMA_V3 if historical else collector.SCHEMA_V2,
        execution_day=manifest['execution_day'],
        prior_journal_artifacts=[seed.pin(old_archive['metadata']), seed.pin(journal_meta)],
        checkpoint_artifacts=[seed.pin(result_meta)])
    if historical:
        continuation['request']['manifest']['target_event_day'] = original_plan['execution_day']
    completed = dict(first, run_attempt=2, status='completed', conclusion='success',
                     updated_at=(end + timedelta(seconds=3)).isoformat())
    continuation.update(issued_at=now.isoformat(), not_before=now.isoformat(),
        expires_at=(now + timedelta(minutes=30)).isoformat(),
        prior_runs=[completed], probe_first_attempt=deepcopy(first),
        journal_archives=[deepcopy(old_archive), dict(raw=journal_raw, metadata=journal_meta)],
        checkpoint_archives=[dict(raw=result_raw, metadata=result_meta)],
        probe_capsule_raw=authority)
    continuation['first_attempt'].update(
        updated_at=(now - timedelta(seconds=1)).isoformat(),
        run_started_at=(now - timedelta(minutes=10)).isoformat())
    return continuation, now, issued


def authored_continuation(historical=False):
    return deepcopy(_authored_continuation(historical))


def _mutate_probe_journal(data, mutation, *, raw_index=False):
    from scripts import all_existing_model_official_result_collect as collector
    item = next(value for value in data['journal_archives']
                if value['metadata']['id'] == PROBE_JOURNAL_ID)
    journal = open_forecasts(collector._journal_cipher(item['raw']), key=legacy.KEY)
    if raw_index:
        with tempfile.TemporaryDirectory(prefix='authored-probe16-mutation-') as folder:
            root = Path(folder)
            root.chmod(0o700)
            index = _unpack_wire(journal, root)
            mutation(journal, index, root)
            _refresh_wire_projection(journal, index, root)
    else:
        mutation(journal)
    item['raw'] = seed.zipped(seal_forecasts(journal, run_id=str(PROBE_RUN),
        round_no=900006, key=legacy.KEY), 'collection.enc')
    item['metadata'].update(digest='sha256:' + sha256(item['raw']).hexdigest(),
                            size_in_bytes=len(item['raw']))
    pin = next(value for value in data['request']['manifest']['prior_journal_artifacts']
               if value['id'] == PROBE_JOURNAL_ID)
    pin.update(seed.pin(item['metadata']))


class ProbeSixteenContinuationTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec(PROFILE_MODULE),
                             'explicit sixteen-request probe profile is absent')
        return importlib.import_module(PROFILE_MODULE)

    def test_explicit_sixteen_profile_has_distinct_authority(self):
        api = self.api()
        self.assertEqual(api.REQUEST, 'RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V4')
        self.assertEqual(api.LIMIT, 16)
        self.assertEqual(api.ROUND, 900024)

    def continuation(self, historical=False):
        self.api()
        return authored_continuation(historical)

    def test_nine_real_fixture_wire_outcomes_unlock_current_continuation_and_prior_replay(self):
        from race_ai import all_existing_model_official_continuation as continuation
        from scripts import all_existing_model_official_result_collect as collector
        data, now, _ = self.continuation()
        before = deepcopy(data)
        raw = continuation.issue_consume_capsule(data, legacy.KEY)
        current = dict(data['first_attempt'], run_attempt=2, status='in_progress', conclusion=None)
        auth = continuation.validate_capsule(raw, data=data, current_run=current, now=now,
                                             key=legacy.KEY)
        audit = auth.audit()
        self.assertEqual(audit['verified_probe_requests'], AUTHORED_REQUEST_COUNT)
        self.assertEqual(audit['maximum_new_requests'], 32)
        self.assertIsNone(audit['old_source_requests_actual'])
        self.assertEqual(audit['old_source_requests_upper_bound'], 32)
        authority = open_forecasts(raw, key=legacy.KEY)['body']['evidence']['probe_authority']
        self.assertEqual(authority['probe_profile'], 'SINGLE_NORMAL_UI_PROBE_16_V1')
        self.assertEqual(authority['maximum_new_requests'], 16)
        archives = {item['metadata']['id']: item for item in data['journal_archives']}
        probe_journal = open_forecasts(collector._journal_cipher(
            archives[PROBE_JOURNAL_ID]['raw']), key=legacy.KEY)
        index_file = next(item for item in probe_journal['browser_quarantine']['files']
                          if item['kind'] == 'CANONICAL_RETURNED_OBJECT')
        original_index = json.loads(base64.b64decode(index_file['raw_base64'], validate=True))
        self.assertEqual(original_index['maximum_requests'], 16)
        self.assertEqual(len(original_index['responses']), AUTHORED_REQUEST_COUNT)
        self.assertEqual(len(original_index['ledger']), AUTHORED_REQUEST_COUNT)
        self.assertEqual({entry['sequence'] for entry in original_index['ledger']},
                         set(range(1, AUTHORED_REQUEST_COUNT + 1)))
        raw_files = {item['file']: item for item in probe_journal['browser_quarantine']['files']}
        for response in original_index['responses']:
            body = base64.b64decode(raw_files[response['body_file']]['raw_base64'], validate=True)
            metadata = json.loads(base64.b64decode(
                raw_files[response['metadata_file']]['raw_base64'], validate=True))
            self.assertEqual(metadata['source_sha256'], sha256(body).hexdigest())
            self.assertEqual(metadata['byte_count'], len(body))
            self.assertEqual(metadata['status'], 200)
        def archive(pin, **_options):
            item = archives[pin['id']]
            cipher = collector._journal_cipher(item['raw'])
            return open_forecasts(cipher, key=legacy.KEY), cipher, item['metadata']
        with patch.object(collector, '_journal_artifact', side_effect=archive):
            admitted = collector.prior_journals(data['request']['manifest'], now=now,
                key=legacy.KEY, recovery_authorization=auth)
        self.assertEqual(admitted['prior_journal_artifact_count'], 2)
        self.assertEqual(data, before)

    def test_historical_sixteen_probe_retains_event_clock_and_unlocks_historical_continuation(self):
        from race_ai import all_existing_model_official_continuation as continuation
        from scripts import all_existing_model_official_result_collect as collector
        data, now, issued = self.continuation(historical=True)
        self.assertEqual(issued['request']['mode'], HISTORICAL_PROFILE_MODE)
        self.assertEqual(issued['request']['manifest']['execution_day'], '2030-01-16')
        self.assertEqual(issued['request']['manifest']['target_event_day'], '2030-01-15')
        raw = continuation.issue_consume_capsule(data, legacy.KEY)
        current = dict(data['first_attempt'], run_attempt=2, status='in_progress', conclusion=None)
        auth = continuation.validate_capsule(raw, data=data, current_run=current, now=now,
                                             key=legacy.KEY)
        self.assertEqual(auth.audit()['verified_probe_requests'], AUTHORED_REQUEST_COUNT)
        item = next(a for a in data['journal_archives'] if a['metadata']['id'] == PROBE_JOURNAL_ID)
        cipher = collector._journal_cipher(item['raw'])
        body = open_forecasts(cipher, key=legacy.KEY)
        pin = next(p for p in data['request']['manifest']['prior_journal_artifacts']
                   if p['id'] == PROBE_JOURNAL_ID)
        self.assertFalse(auth.validate_prior(data['request']['manifest'], pin, body, cipher,
                                             item['metadata'], now))
        self.assertEqual(body['target_event_day'], '2030-01-15')
        self.assertTrue(body['captures'][0]['metadata']['response_received_at'].startswith('2030-01-16'))
        self.assertEqual(body['captures'][0]['metadata']['auto_result_context']['request_body_base64'],
            open_forecasts(collector._journal_cipher(seed.complete_fixture()[0]['journal_archives'][1]['raw']),
                key=legacy.KEY)['captures'][0]['metadata']['auto_result_context']['request_body_base64'])

    def test_each_journal_reservation_and_raw_index_budget_must_match_original_sixteen_grant(self):
        from race_ai import all_existing_model_official_continuation as continuation
        for kind in ('journal', 'reservation', 'reservation_float', 'reservation_bool',
                     'raw_index', 'raw_index_missing', 'raw_index_float', 'raw_index_bool'):
            data, _, _ = self.continuation()
            if kind == 'journal':
                _mutate_probe_journal(data, lambda body: body.update(maximum_requests=12))
            elif kind == 'reservation':
                _mutate_probe_journal(data, lambda body: body['browser_attempt'].update(reserved_request_limit=32))
            elif kind in ('reservation_float', 'reservation_bool'):
                value = 16.0 if kind == 'reservation_float' else True
                _mutate_probe_journal(data, lambda body: body['browser_attempt'].update(
                    reserved_request_limit=value))
            else:
                def change(_body, index, _root):
                    if kind == 'raw_index':
                        index['maximum_requests'] = 32
                    elif kind == 'raw_index_missing':
                        index.pop('maximum_requests')
                    elif kind == 'raw_index_float':
                        index['maximum_requests'] = 16.0
                    else:
                        index['maximum_requests'] = True
                _mutate_probe_journal(data, change, raw_index=True)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                continuation.issue_consume_capsule(data, legacy.KEY)

    def test_browser_count_diagnostic_and_original_wire_count_must_agree(self):
        from race_ai import all_existing_model_official_continuation as continuation
        for kind in ('browser_count', 'diagnostic_count', 'original_count'):
            data, _, _ = self.continuation()
            if kind == 'browser_count':
                _mutate_probe_journal(data, lambda body: body['browser_attempt'].update(
                    actual_request_count=AUTHORED_REQUEST_COUNT - 1))
            elif kind == 'diagnostic_count':
                _mutate_probe_journal(data, lambda body: body['browser_index'].update(
                    actual_request_count=AUTHORED_REQUEST_COUNT - 1))
            else:
                def change(_body, index, _root):
                    index['actual_request_count'] = AUTHORED_REQUEST_COUNT - 1
                _mutate_probe_journal(data, change, raw_index=True)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                continuation.issue_consume_capsule(data, legacy.KEY)

    def test_fully_authored_seventeenth_wire_request_cannot_fit_the_sixteen_grant(self):
        from race_ai import all_existing_model_official_continuation as continuation
        data, _, _ = self.continuation()
        def change(body, index, root):
            _append_static_requests(index, root, count=17)
            body['browser_attempt']['actual_request_count'] = 17
        _mutate_probe_journal(data, change, raw_index=True)
        with self.assertRaises(ValueError):
            continuation.issue_consume_capsule(data, legacy.KEY)

    def test_sixteen_complete_authored_wire_requests_fit_the_exact_upper_bound(self):
        from race_ai import all_existing_model_official_continuation as continuation
        data, now, _ = self.continuation()
        def change(body, index, root):
            _append_static_requests(index, root, count=16)
            body['browser_attempt']['actual_request_count'] = 16
        _mutate_probe_journal(data, change, raw_index=True)
        raw = continuation.issue_consume_capsule(data, legacy.KEY)
        current = dict(data['first_attempt'], run_attempt=2, status='in_progress', conclusion=None)
        auth = continuation.validate_capsule(raw, data=data, current_run=current, now=now,
                                             key=legacy.KEY)
        self.assertEqual(auth.audit()['verified_probe_requests'], 16)

    def test_higher_cap_never_waives_unknown_or_denied_wire_outcomes(self):
        from race_ai import all_existing_model_official_continuation as continuation
        for kind in ('unknown', 'interrupted', 'denied'):
            data, _, _ = self.continuation()
            def change(body):
                if kind == 'unknown':
                    body['browser_index']['ledger'][-1].pop('status')
                elif kind == 'interrupted':
                    body['browser_attempt']['state'] = 'INTERRUPTED'
                else:
                    body['browser_process_diagnostic'] = dict(stdout_stopped_host=True)
            _mutate_probe_journal(data, change)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                continuation.issue_consume_capsule(data, legacy.KEY)


if __name__ == '__main__':
    unittest.main()
