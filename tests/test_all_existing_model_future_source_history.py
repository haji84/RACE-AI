"""Authored encrypted future-source history, never live acquisition or owner data."""
import base64
from copy import deepcopy
from datetime import timedelta
from functools import lru_cache
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai.actions_contract import digest
from race_ai.boat_all_model_store import seal_forecasts
from race_ai import all_existing_model_future_source_capture as core
from race_ai import all_existing_model_official_recovery as recovery
from scripts import all_existing_model_future_source_capture as wrapper
from tests import test_all_existing_model_official_recovery as old
from tests.test_official_future_source_packet import capture_fixture


KEY = old.KEY
ENV = dict(run_id=94, head_sha='d' * 40)
SOURCE_ID = 9400
RESULT_ID = 9300


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def _pin(metadata):
    return dict(id=metadata['id'], digest=metadata['digest'],
        run_id=metadata['workflow_run']['id'], head_sha=metadata['workflow_run']['head_sha'])


def _archive(directory):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.iterdir()):
            archive.writestr(path.name, path.read_bytes())
    return stream.getvalue()


def _metadata(raw, ident, name, env, saved):
    return dict(id=ident, name=name, expired=False, digest='sha256:' + sha256(raw).hexdigest(),
        size_in_bytes=len(raw), created_at=saved.isoformat(),
        expires_at=(saved + timedelta(days=7)).isoformat(), workflow_run=dict(
            id=env['run_id'], head_sha=env['head_sha'], repository_id=1416489937,
            head_repository_id=1416489937))


def _run(ident, head, started, updated):
    return dict(id=ident, head_sha=head, run_attempt=1, status='completed', conclusion='success',
        updated_at=updated.isoformat(), run_started_at=started.isoformat(),
        repository=dict(id=1416489937, full_name='haji84/RACE-AI'),
        head_repository=dict(id=1416489937, full_name='haji84/RACE-AI'),
        pull_requests=[dict(number=71)])


@lru_cache(maxsize=1)
def _old_fixture():
    # One random encrypted original supplies one consistent pin throughout.
    return old.fixture()


def history_fixture(*, change_index=None, change_files=None, change_journal=None,
                    include_result=True, unresolved_source=False, no_browser=False):
    """Return a fresh exact original archive chain, with real public-fixture AES."""
    old_data, old_body, _ = deepcopy(_old_fixture())
    plan, index, files, terms = capture_fixture()
    plan['request_budget'] = 32
    started = core.clock(plan['available_after'])
    plan['available_after'] = started.isoformat()
    index['available_after'] = plan['available_after']
    completed = core.clock(index['completed_at'])
    old_meta = old_data['old_journal_metadata']
    old_meta['expires_at'] = (completed + timedelta(days=7)).isoformat()
    old_pin = _pin(old_meta)
    archives = [dict(raw=old_data['old_journal_raw'], metadata=old_meta)]
    prior_runs = []
    prior_pins = [old_pin]
    if include_result:
        result_started = started - timedelta(hours=2)
        result_saved = result_started + timedelta(seconds=8)
        result_env = dict(run_id=93, head_sha='c' * 40)
        result_body = deepcopy(old_body)
        result_body.pop('browser_attempt')
        result_body['manifest'].update(execution_day=plan['cases'][0]['expected_date'],
                                        prior_journal_artifacts=[deepcopy(old_pin)])
        result_body.update(workflow_run_id=93, code_sha=result_env['head_sha'],
            execution_day=plan['cases'][0]['expected_date'],
            epoch_started_at=result_started.isoformat(), manifest_sha256=digest(result_body['manifest']),
            cases=[])
        for attempt in result_body['attempts']:
            attempt.update(started_at=result_started.isoformat(), finished_at=result_saved.isoformat())
        cipher = seal_forecasts(result_body, run_id='93', round_no=900006, key=KEY)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('collection.enc', cipher)
        raw = stream.getvalue()
        metadata = _metadata(raw, RESULT_ID, 'official-result-collection-journal-93',
                             result_env, result_saved)
        prior_pins.append(_pin(metadata))
        archives.append(dict(raw=raw, metadata=metadata))
        prior_runs.append(_run(93, result_env['head_sha'], result_started - timedelta(minutes=1),
                               result_saved + timedelta(seconds=1)))
    baseline_pin = lambda n: dict(id=n, digest='sha256:' + str(n % 10) * 64,
                                  run_id=n + 10, head_sha='a' * 40)
    manifest = dict(schema=core.SCHEMA, execution_day=plan['cases'][0]['expected_date'],
        cases=deepcopy(plan['cases']), terms_manifest=terms, maximum_requests=32,
        baseline_artifacts={sport:baseline_pin(900) for sport in ('autorace', 'keirin')},
        carrier_artifact=baseline_pin(700), prior_journal_artifacts=deepcopy(prior_pins))
    if change_index is not None:
        change_index(index)
    if change_files is not None:
        change_files(files, index)
    files['capture-index.json'] = _wire(index)
    with tempfile.TemporaryDirectory(prefix='authored-future-history-') as folder:
        root = Path(folder)
        root.chmod(0o700)
        browser = root / 'browser'
        if not no_browser:
            browser.mkdir(mode=0o700)
        source = root / 'source'; source.mkdir(mode=0o700)
        for name, raw in (() if no_browser else files.items()):
            path = browser / name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.write_bytes(raw); path.chmod(0o600)
        items, complete = wrapper.inventory(browser, source, ENV, key=KEY)
        if not no_browser and complete is not True:
            raise AssertionError('authored complete fixture lost an original file')
        if no_browser and (items or complete is not False):
            raise AssertionError('missing authored browser directory gained a retained original')
        reservation = dict(schema=core.JOURNAL, state='RESERVED', manifest=deepcopy(manifest),
            manifest_sha256=digest(manifest), workflow_run_id=ENV['run_id'], code_sha=ENV['head_sha'],
            epoch_started_at=started.isoformat(), plan_sha256=digest(plan),
            source_requests_actual=None, maximum_requests=32, history={})
        journal = dict(reservation, state='CAPTURE_RETAINED', completed_at=completed.isoformat(),
            capture_index=None if no_browser else deepcopy(index), capture_inventory=items,
            raw_retention_complete=complete,
            source_requests_actual=None if unresolved_source or no_browser else index['actual_request_count'],
            source_request_upper_bound=32, fixed_as_of=None, native_ready=False)
        if change_journal is not None:
            change_journal(journal)
        wrapper._seal(source / 'reservation.enc', reservation, ENV, KEY)
        wrapper._seal(source / 'plan.enc', plan, ENV, KEY)
        wrapper._seal(source / 'collection.enc', journal, ENV, KEY)
        source_raw = _archive(source)
    source_saved = completed + timedelta(seconds=2)
    source_meta = _metadata(source_raw, SOURCE_ID, 'official-future-source-capture-94',
                             ENV, source_saved)
    archives.append(dict(raw=source_raw, metadata=source_meta))
    prior_pins.append(_pin(source_meta))
    prior_runs.append(_run(94, ENV['head_sha'], started - timedelta(minutes=1),
                           completed + timedelta(seconds=3)))
    next_manifest = dict(deepcopy(manifest), prior_journal_artifacts=prior_pins)
    now = completed + timedelta(hours=1, seconds=4)
    return dict(manifest=next_manifest, journal_archives=archives, old_run=old_data['old_run'],
        prior_runs=prior_runs, current_run=95, now=now, key=KEY)


def admit(data):
    return core.authenticate_future_history(**data)


class FutureSourceHistoryTests(unittest.TestCase):
    def test_original_future_wire_and_old_result_history_are_admitted_without_native_claim(self):
        data = history_fixture(); before = deepcopy(data)
        admitted = admit(data)
        self.assertEqual(data, before)
        self.assertEqual(admitted['prior_journal_artifact_count'], 3)
        self.assertIsNone(admitted['old_source_requests_actual'])
        self.assertEqual(admitted['old_source_requests_upper_bound'], 32)
        self.assertEqual(admitted['old_browser_outcome'], 'UNKNOWN')
        source = admitted['bodies'][SOURCE_ID]
        original = admitted['bodies'][recovery.OLD_ARTIFACT]
        self.assertEqual(len(original['attempts']), 8)
        self.assertTrue(all(attempt['http_status'] == 200 for attempt in original['attempts']))
        self.assertEqual(original['browser_attempt']['state'], 'RESERVED')
        self.assertEqual(original['browser_attempt']['reserved_request_limit'], 24)
        self.assertNotIn('actual_request_count', original['browser_attempt'])
        self.assertEqual(source['source_requests_actual'], 4)
        self.assertFalse(source['native_ready'])
        self.assertIsNone(source['fixed_as_of'])
        self.assertNotIn('packet.enc', wrapper.source_archive(data['journal_archives'][-1]['raw'],
            data['journal_archives'][-1]['metadata'], ENV, now=data['now'], key=KEY)[1])
        self.assertEqual(core.clock(admitted['latest_possible_old_activity_at']) + timedelta(hours=1),
                         data['now'])

    def test_retained_http_metadata_must_match_the_reported_wire_outcomes(self):
        for field, value in (('status', 403), ('source_sha256', 'f' * 64),
                             ('byte_count', 1), ('response_received_at', '2030-01-15T00:00:00+00:00')):
            def change(files, index):
                name = index['responses'][0]['metadata_file']
                metadata = json.loads(files[name]); metadata[field] = value
                files[name] = _wire(metadata)
            with self.subTest(field=field), self.assertRaises(ValueError):
                admit(history_fixture(change_files=change))

    def test_all_terminal_and_actual_save_times_enforce_the_full_hour_boundary(self):
        for change in ('before_boundary', 'later_terminal', 'later_save'):
            data = history_fixture()
            if change == 'before_boundary':
                data['now'] -= timedelta(microseconds=1)
            elif change == 'later_terminal':
                data['prior_runs'][-1]['updated_at'] = (data['now'] - timedelta(minutes=1)).isoformat()
            else:
                # Save precision allows terminal+1s, but waiting must include
                # that save's own +1s allowance instead of only the terminal.
                data['journal_archives'][-1]['metadata']['created_at'] = (
                    core.clock(data['prior_runs'][-1]['updated_at']) + timedelta(seconds=1)).isoformat()
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'LATEST_TERMINAL_INTERVAL'):
                admit(data)

    def test_every_actual_prior_run_receipt_is_required_and_current_run_is_fresh(self):
        for change in ('missing', 'active', 'head', 'repository', 'current_run'):
            data = history_fixture()
            if change == 'missing':
                data['prior_runs'].pop()
            elif change == 'active':
                data['prior_runs'][-1]['status'] = 'in_progress'
            elif change == 'head':
                data['prior_runs'][-1]['head_sha'] = 'f' * 40
            elif change == 'repository':
                data['prior_runs'][-1]['repository']['id'] = 2
            else:
                data['current_run'] = ENV['run_id']
            with self.subTest(change=change), self.assertRaises(ValueError):
                admit(data)

    def test_authenticated_future_journal_cannot_drop_its_earlier_result_pin(self):
        data = history_fixture()
        data['manifest']['prior_journal_artifacts'] = [p for p in
            data['manifest']['prior_journal_artifacts'] if p['id'] != RESULT_ID]
        data['journal_archives'] = [item for item in data['journal_archives']
                                    if item['metadata']['id'] != RESULT_ID]
        data['prior_runs'] = [run for run in data['prior_runs'] if run['id'] != 93]
        with self.assertRaisesRegex(ValueError, 'TRANSITIVE_PRIOR_PIN_CLOSURE'):
            admit(data)

    def test_own_future_unknown_missing_and_denied_outcomes_never_restart(self):
        for change in ('unknown', 'missing_status', 'denied_status', 'denied_process', 'unretained'):
            change_index = None
            change_journal = None
            if change in ('missing_status', 'denied_status'):
                def change_index(index):
                    for field in ('responses', 'ledger'):
                        if change == 'missing_status':
                            index[field][0].pop('status')
                        else:
                            index[field][0]['status'] = 429
            elif change == 'denied_process':
                change_journal = lambda journal: journal.update(
                    browser_process_diagnostic=[dict(stdout_stopped_host=True)])
            elif change == 'unretained':
                change_journal = lambda journal: journal.update(raw_retention_complete=False)
            data = history_fixture(change_index=change_index, change_journal=change_journal,
                                   unresolved_source=change == 'unknown')
            with self.subTest(change=change), self.assertRaises(ValueError):
                admit(data)

    def test_unknown_archive_retains_none_and_reported_zero_cannot_hide_four_requests(self):
        unknown = history_fixture(unresolved_source=True)
        journal, _, _ = wrapper.source_archive(unknown['journal_archives'][-1]['raw'],
            unknown['journal_archives'][-1]['metadata'], ENV, now=unknown['now'], key=KEY)
        self.assertIsNone(journal['source_requests_actual'])
        self.assertEqual(journal['capture_index']['actual_request_count'], 4)
        with self.assertRaises(ValueError):
            admit(unknown)
        forged_zero = history_fixture(change_journal=lambda value: value.update(source_requests_actual=0))
        with self.assertRaisesRegex(ValueError, 'SOURCE_REQUEST_COUNT_TRUTH'):
            admit(forged_zero)

    def test_original_body_and_request_bytes_must_match_the_retained_http_index(self):
        for field in ('body_file', 'request_body_file'):
            def change(files, index):
                name = index['responses'][0][field]
                files[name] += b'authored changed bytes'
            with self.subTest(field=field), self.assertRaises(ValueError):
                admit(history_fixture(change_files=change))

    def test_exact_actual_archive_pin_metadata_and_transport_remain_required(self):
        for change in ('missing', 'digest', 'head', 'expired', 'size', 'raw', 'duplicate'):
            data = history_fixture()
            source = data['journal_archives'][-1]
            if change == 'missing':
                data['journal_archives'].pop()
            elif change == 'digest':
                source['metadata']['digest'] = 'sha256:' + 'f' * 64
            elif change == 'head':
                source['metadata']['workflow_run']['head_sha'] = 'f' * 40
            elif change == 'expired':
                source['metadata']['expired'] = True
            elif change == 'size':
                source['metadata']['size_in_bytes'] += 1
            elif change == 'raw':
                source['raw'] += b'changed archive'
            else:
                data['journal_archives'].append(deepcopy(source))
            with self.subTest(change=change), self.assertRaises(ValueError):
                admit(data)

    def test_missing_browser_directory_saves_unknown_and_reads_back_without_native_claim(self):
        data = history_fixture(no_browser=True)
        archive = data['journal_archives'][-1]
        journal, ciphertexts, files = wrapper.source_archive(archive['raw'], archive['metadata'],
            ENV, now=data['now'], key=KEY)
        self.assertEqual(set(ciphertexts), {'reservation.enc', 'plan.enc', 'collection.enc'})
        self.assertEqual(files, {})
        self.assertEqual(journal['capture_inventory'], [])
        self.assertIsNone(journal['capture_index'])
        self.assertIsNone(journal['source_requests_actual'])
        self.assertFalse(journal['raw_retention_complete'])
        self.assertFalse(journal['native_ready'])
        with tempfile.TemporaryDirectory(prefix='authored-empty-source-readback-') as folder:
            root = Path(folder); root.chmod(0o700)
            source = root / 'source'; source.mkdir(mode=0o700)
            for name, raw in ciphertexts.items():
                path = source / name; path.write_bytes(raw); path.chmod(0o600)
            with patch.dict(os.environ, {'RACE_AI_STATE_KEY': base64.b64encode(KEY).decode()}), \
                 patch.object(wrapper, 'utc_now', return_value=data['now']), \
                 patch.object(wrapper.future, 'metadata', return_value=archive['metadata']), \
                 patch.object(wrapper.future, 'gh', return_value=archive['raw']):
                checked = wrapper.readback_source(SOURCE_ID, root, ENV, journal['manifest'])
        self.assertFalse(checked['ready'])
        self.assertIsNone(checked['source_requests'])
        self.assertFalse(checked['raw_retention_complete'])
        self.assertTrue(checked['independent_source_capture_receipt_verified'])
        self.assertFalse(checked['independent_pre_cutoff_receipt_verified'])
        self.assertIsNone(checked['old_source_requests_actual'])
        with self.assertRaisesRegex(ValueError, 'FUTURE_PRIOR_OUTCOME_UNKNOWN'):
            admit(data)


if __name__ == '__main__':
    unittest.main()
