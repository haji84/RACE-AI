"""Invented HTTP bodies and a public fixture key; no provider GET or real secrets.

These regressions keep opaque raw retention separate from typed first-P0 B
authority. The expected RED is absent HTTP-200 capture or absent strict P1
URL admission on the pinned source; production changes follow observed CI RED.
"""
import base64
from contextlib import contextmanager, ExitStack, redirect_stdout
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from race_ai import boat_private_original_vault as V
from race_ai import boat_program_source as program_source
from race_ai import boat_source_capture_files as C
from race_ai import repeated_cycle as cycle
from race_ai import saved_view_feed as F
from race_ai.source_retry_policy import SourceWait
from scripts import boat_nationwide_ab_pilot as pilot
from scripts import existing_day_program as collector
from tests.test_boat_official_program import page, source_url
from tests.test_boat_observation_context import frame, before_table, starts, weather, sg_program
from tests.test_boat_program_source import collector_archive
from tests import test_boat_source_capture_batching as batch_fixtures
from tests.test_nationwide_get_policy import schedule_snapshot

KEY = bytes(range(32))  # Deliberately public fixture material, never owner state.
HEAD = 'a' * 40
NOW = datetime(2030, 4, 1, 9, tzinfo=timezone.utc)
DAY = date(2030, 4, 1)
P1_URL = 'https://www.boatrace.jp/owpc/pc/race/racelist?rno=12&jcd=12&hd=20300401'
PREVIEW_URL = 'https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno=12&jcd=12&hd=20300401'
B_DAY = date(2030, 1, 15)
B_NOW = datetime(2030, 1, 15, 0, tzinfo=timezone.utc)
B_URL = 'https://www1.mbrace.or.jp/od2/B/203001/b300115.lzh'
RACE = dict(race_id='20300401-12-12', cutoff_at='2030-04-01T20:30:00+09:00')


class FixedClock(datetime):
    current = NOW

    @classmethod
    def now(cls, tz=None):
        return cls.current.astimezone(tz) if tz is not None else cls.current.replace(tzinfo=None)


class Response:
    def __init__(self, url, raw, *, status=200, content_type='text/html; charset=utf-8', after_read=None,
                 effective_url=None):
        self.url = url if effective_url is None else effective_url; self.raw = raw; self.status = status
        self.headers = {'content-type': content_type}; self.after_read = after_read

    def geturl(self):
        return self.url

    def read(self, limit):
        result = self.raw[:limit]
        if self.after_read is not None:self.after_read()
        return result

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class Transport:
    def __init__(self, bodies=None, *, response_options=None, failure=None):
        self.bodies = bodies or {}; self.response_options = response_options or {}
        self.failure = failure; self.urls = []

    def open(self, req, *, timeout):
        self.urls.append(req.full_url)
        if self.failure is not None:raise self.failure
        return Response(req.full_url, self.bodies.get(req.full_url, b'invented unsupported market body'),
                        **self.response_options)


class RawFixture(unittest.TestCase):
    def setUp(self):
        # Clear inherited process environment before any fixture can see it.
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start(); self.addCleanup(environment.stop)
        network = patch('urllib.request.OpenerDirector.open',
                        side_effect=AssertionError('provider/GitHub request forbidden in fixture'))
        network.start(); self.addCleanup(network.stop)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.repo = self.root/'repository'
        self.repo.mkdir(mode=0o700)
        self.folder = self.root/'boat-saved-view-captures'
        self.env = dict(RACE_AI_ORIGINAL_VAULT_ENABLED='true',
            RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED='true', RACE_AI_SAVED_PROGRAM_CAPTURE='true',
            RACE_AI_STATE_KEY=base64.b64encode(KEY).decode('ascii'),
            GITHUB_ACTIONS='true', GITHUB_REPOSITORY='haji84/RACE-AI',
            GITHUB_REF_NAME='production/boat-p0-p1-20261111', GITHUB_EVENT_NAME='workflow_dispatch',
            GITHUB_RUN_ID='4242', GITHUB_SHA=HEAD, RUNNER_TEMP=str(self.root))
        FixedClock.current = NOW

    def sink(self, raw, url=P1_URL, received_at=NOW, *, guard=None, environment=None):
        sink = getattr(C, 'capture_http200', None)
        self.assertTrue(callable(sink), 'accepted HTTP-200 opaque raw preservation is absent')
        with patch.dict(os.environ, self.env if environment is None else environment, clear=True):
            return sink(raw, source_url=url, received_at=received_at, source_guard=guard)

    def captures(self, *, now=None):
        if not self.folder.exists():return []
        with C.CaptureInventory(self.folder, repo=self.repo,
                               now=now or max(NOW, FixedClock.current)) as inventory:
            return [pair for group in inventory.groups() for pair in inventory.materialize(group)]

    def assert_capture(self, raw, url, at):
        matches = [(body, V._json(receipt)) for body, receipt in self.captures()
                   if V._json(receipt)['source_url'] == url]
        self.assertEqual(len(matches), 1, 'one exact accepted response must survive before parsing')
        body, receipt = matches[0]
        self.assertEqual(body, raw)
        self.assertEqual(set(receipt), {'source_url','source_sha256','captured_at','http_status'})
        self.assertEqual(receipt['http_status'], 200)
        self.assertEqual(receipt['source_sha256'], sha256(raw).hexdigest())
        self.assertEqual(receipt['source_url'], url)
        self.assertEqual(datetime.fromisoformat(receipt['captured_at'].replace('Z','+00:00')), at)
        self.assertEqual(datetime.fromisoformat(receipt['captured_at'].replace('Z','+00:00')).utcoffset(),
                         timedelta(0))
        self.assertEqual(self.folder.stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in self.folder.iterdir()))
        return receipt

    def assert_hold(self, exception, *, suppressed=True):
        self.assertIsInstance(exception, SourceWait)
        self.assertEqual((exception.reason, exception.retry_at, exception.state),
                         ('SOURCE_CAPTURE_UNAVAILABLE', None, 'SOURCE_REVIEW_WAIT'))
        self.assertEqual(str(exception), 'SOURCE_CAPTURE_UNAVAILABLE')
        if suppressed:self.assertTrue(exception.__suppress_context__)

    @contextmanager
    def p1(self, transport, *, guard=None, environment=None):
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, self.env if environment is None else environment, clear=True))
            stack.enter_context(patch.object(pilot, 'datetime', FixedClock))
            stack.enter_context(patch.object(pilot, 'SOURCE_GUARD', guard))
            stack.enter_context(patch.object(pilot, 'requests_used', 0))
            stack.enter_context(patch.object(pilot.request, 'build_opener', return_value=transport))
            stack.enter_context(patch.object(pilot.time, 'sleep'))
            stack.enter_context(patch.object(pilot, 'supplemental_contexts', {}))
            yield

    @contextmanager
    def b_source(self, transport, *, environment=None):
        with patch.dict(os.environ, self.env if environment is None else environment, clear=True), \
             patch.object(collector, 'datetime', FixedClock), \
             patch.object(collector.request, 'build_opener', return_value=transport):
            yield

    def new_guard(self, now=NOW):
        path = self.root/'session.json'
        cycle.start(path, day=now.astimezone(pilot.JST).date().isoformat(), run_id=4242, now=now)
        return cycle.SourceGuard(path, clock=lambda: FixedClock.current)


class OpaqueRawSinkTests(RawFixture):
    def test_exact_bytes_and_actual_utc_receive_clock_are_private_and_idempotent(self):
        raw = b'invented malformed source \x00\xff\r\n'
        received = NOW.astimezone(timezone(timedelta(hours=9)))
        self.sink(raw, received_at=received)
        before = {p.name:p.read_bytes() for p in self.folder.iterdir()}
        self.sink(raw, received_at=received)
        self.assertEqual({p.name:p.read_bytes() for p in self.folder.iterdir()}, before)
        self.assert_capture(raw, P1_URL, NOW)
        self.assertFalse((self.root/'boat-program-source').exists())
        self.assertEqual(list(self.repo.iterdir()), [])

    def test_disabled_flag_does_not_read_key_validate_context_or_touch_files(self):
        for value in (None, '', 'false', 'TRUE', '1'):
            env = {} if value is None else {'RACE_AI_ORIGINAL_VAULT_ENABLED':value}
            with self.subTest(flag=value), patch.object(C.os, 'open', side_effect=AssertionError('disabled write')), \
                 patch.object(Path, 'mkdir', side_effect=AssertionError('disabled directory')):
                self.assertIsNone(self.sink(b'opaque synthetic bytes', environment=env))
        self.assertFalse(self.folder.exists())

    def test_enabled_missing_or_wrong_owner_context_is_hold_before_plaintext_creation(self):
        defects = [
            ('GITHUB_ACTIONS', None), ('GITHUB_ACTIONS', 'false'),
            ('GITHUB_REPOSITORY', 'someone-else/RACE-AI'),
            ('GITHUB_REF_NAME', None), ('GITHUB_REF_NAME', 'main'),
            ('GITHUB_EVENT_NAME', None), ('GITHUB_EVENT_NAME', 'pull_request'),
            ('GITHUB_EVENT_NAME', 'push'), ('RACE_AI_STATE_KEY', None),
            ('RACE_AI_STATE_KEY', 'not-base64'), ('RACE_AI_STATE_KEY', base64.b64encode(b'x'*32).decode()),
            ('RUNNER_TEMP', None),
        ]
        for name, value in defects:
            env = dict(self.env)
            if value is None:env.pop(name, None)
            else:env[name] = value
            with self.subTest(field=name, value=value):
                with self.assertRaises(SourceWait) as held:
                    self.sink(b'invented private raw body', environment=env)
                self.assert_hold(held.exception)
                self.assertFalse(self.folder.exists())

    def test_existing_legacy_push_and_owner_dispatch_origin_rules_are_reused(self):
        raw = b'public fixture body for already permitted legacy origin'
        env = dict(self.env, GITHUB_REF_NAME='feat/four-sport-forecast-audit-view-20261022',
                   GITHUB_EVENT_NAME='push')
        self.sink(raw, environment=env)
        self.assert_capture(raw, P1_URL, NOW)

    def test_existing_p1_review_and_b_capture_flags_are_required_when_enabled(self):
        for name, url in (('RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED', P1_URL),
                          ('RACE_AI_SAVED_PROGRAM_CAPTURE', B_URL)):
            for value in (None, 'false'):
                env = dict(self.env)
                if value is None:env.pop(name)
                else:env[name] = value
                with self.subTest(flag=name, value=value):
                    with self.assertRaises(SourceWait) as held:
                        self.sink(b'invented raw response', url=url, environment=env)
                    self.assert_hold(held.exception)
                    self.assertFalse(self.folder.exists())

    def test_unrelated_review_flag_is_not_a_new_cross_source_permission(self):
        self.sink(b'invented raw program', url=B_URL,
                  environment=dict(self.env, RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED='false'))
        self.sink(b'invented raw racelist',
                  environment=dict(self.env, RACE_AI_SAVED_PROGRAM_CAPTURE='false'))
        self.assertEqual(len(self.captures()), 2)

    def test_untrusted_runner_locations_and_permissions_hold_without_raw_exception(self):
        bad_locations = []
        public = self.root/'public'; public.mkdir(mode=0o755); bad_locations.append(public)
        link = self.root/'symlink'; link.symlink_to(self.root, target_is_directory=True); bad_locations.append(link)
        checkout = self.root/'checkout'; checkout.mkdir(mode=0o700); (checkout/'.git').mkdir()
        child = checkout/'runner'; child.mkdir(mode=0o700); bad_locations.append(child)
        missing = self.root/'missing'; bad_locations.append(missing)
        for path in bad_locations:
            with self.subTest(defect=path.name):
                with self.assertRaises(SourceWait) as held:
                    self.sink(b'invented secret body', environment=dict(self.env, RUNNER_TEMP=str(path)))
                self.assert_hold(held.exception)
                self.assertFalse((path/'boat-saved-view-captures').exists())
        with patch.object(C.os, 'geteuid', return_value=os.geteuid()+1), self.assertRaises(SourceWait) as held:
            self.sink(b'invented owner mismatch')
        self.assert_hold(held.exception)
        self.assertFalse(self.folder.exists())

    def test_preexisting_symlink_hardlink_public_file_and_wrong_bytes_hold(self):
        raw = b'invented response with a preexisting body identity'
        target = self.root/'retained'; target.write_bytes(raw); target.chmod(0o600)
        self.folder.mkdir(mode=0o700)
        body = self.folder/(sha256(raw).hexdigest()+'.raw')
        for defect in ('symlink', 'hardlink', 'public', 'conflict'):
            with self.subTest(defect=defect):
                try:
                    if defect == 'symlink':body.symlink_to(target)
                    elif defect == 'hardlink':os.link(target, body)
                    else:
                        body.write_bytes(raw if defect == 'public' else raw+b'changed')
                        body.chmod(0o644 if defect == 'public' else 0o600)
                    with self.assertRaises(SourceWait) as held:self.sink(raw)
                    self.assert_hold(held.exception)
                finally:
                    body.unlink(missing_ok=True)

    def test_same_exact_body_can_share_legacy_html_without_an_ambiguous_raw_duplicate(self):
        raw = b'invented identical raw source bytes across two legitimate source URLs'
        receipt = dict(source_url='https://www.boatrace.jp/owpc/pc/race/raceresult?rno=1&jcd=01&hd=20300401',
            captured_at=NOW.isoformat(),source_sha256=sha256(raw).hexdigest(),http_status=200)
        F.retain_capture(self.folder,raw,receipt)
        self.sink(raw,P1_URL,NOW)
        self.assertEqual(len(self.captures()),2)
        self.assertEqual(len([p for p in self.folder.iterdir() if p.suffix in ('.raw','.html')]),1)

    def test_capture_bound_holds_instead_of_truncating_or_marking_complete(self):
        for raw in (b'', b'x'*(4*1024*1024+1), bytearray(b'invented bytes')):
            with self.subTest(size=len(raw)):
                with self.assertRaises(SourceWait) as held:
                    self.sink(raw)
                self.assert_hold(held.exception)
                self.assertFalse(self.folder.exists())

    def test_naive_or_non_datetime_receive_clock_never_becomes_a_receipt(self):
        for at in (datetime(2030,4,1), NOW.isoformat(), None):
            with self.subTest(clock=type(at).__name__):
                with self.assertRaises(SourceWait) as held:
                    self.sink(b'invented body', received_at=at)
                self.assert_hold(held.exception)
                self.assertFalse(self.folder.exists())


class P1RawCaptureTests(RawFixture):
    def test_raw_is_saved_before_pacing_and_returned_admission_clock_is_unchanged(self):
        raw = b'invented accepted raw HTML'
        received = NOW+timedelta(seconds=5)
        returned = NOW+timedelta(seconds=20)
        transport = Transport({P1_URL:raw},
            response_options={'after_read':lambda:setattr(FixedClock, 'current', received)})
        def pace(_):
            self.assert_capture(raw, P1_URL, received)
            FixedClock.current = returned
        with self.p1(transport), patch.object(pilot.time, 'sleep', side_effect=pace):
            body, at, identity = pilot.get(P1_URL, day=DAY)
            self.assertEqual(pilot.requests_used, 1)
        self.assertEqual((body, at, identity), (raw, returned, sha256(raw).hexdigest()))
        self.assertEqual(transport.urls, [P1_URL])
        self.assert_capture(raw, P1_URL, received)

    def test_program_parse_rejection_preserves_exact_malformed_http200_body(self):
        raw = b'<table><tr>invented malformed program'
        transport = Transport({P1_URL:raw})
        with self.p1(transport), self.assertRaises((ValueError, pilot.SourceError, UnicodeError)):
            pilot.make_pair(DAY, RACE)
        self.assert_capture(raw, P1_URL, NOW)
        self.assertEqual(transport.urls, [P1_URL])

    def test_beforeinfo_parse_rejection_preserves_both_accepted_bodies(self):
        program = page(row_options={lane:dict(name=f'選手 {lane}') for lane in range(1,7)}); preview = b'<table><tr>invented malformed exhibition'
        transport = Transport({P1_URL:program, PREVIEW_URL:preview})
        with self.p1(transport), self.assertRaises((ValueError, pilot.SourceError, UnicodeError)):
            pilot.make_pair(DAY, RACE)
        self.assert_capture(program, P1_URL, NOW); self.assert_capture(preview, PREVIEW_URL, NOW)
        self.assertEqual(transport.urls, [P1_URL, PREVIEW_URL])

    def test_stats_fallback_keeps_raw_and_remains_context_only(self):
        program = sg_program(); preview = frame(before_table()+starts()+weather())
        transport = Transport({P1_URL:program, PREVIEW_URL:preview})
        with self.p1(transport), patch.object(pilot, 'collect_pitreport', return_value=None), \
             patch.object(pilot, 'collect_entry_history', return_value=None):
            status, *forecasts = pilot.make_pair(DAY, RACE)
        self.assertEqual(status['state'], 'PROGRAM_STATS_UNSUPPORTED_CONTEXT_ONLY')
        self.assertEqual(forecasts, [None,None,None,None])
        self.assertEqual(transport.urls, [P1_URL, PREVIEW_URL])
        self.assert_capture(program, P1_URL, NOW); self.assert_capture(preview, PREVIEW_URL, NOW)

    def test_pending_exhibition_retains_raw_without_optional_get_or_model_work(self):
        program = page(row_options={lane:dict(name=f'選手 {lane}') for lane in range(1,7)}); preview = frame(before_table()+starts()+weather())
        transport = Transport({P1_URL:program, PREVIEW_URL:preview})
        with self.p1(transport):
            status, *forecasts = pilot.make_pair(DAY, RACE)
        self.assertEqual(status['state'], 'EXHIBITION_TIME_INCOMPLETE')
        self.assertEqual(status['source_wait']['state'], 'WAITING_PUBLICATION')
        self.assertEqual(forecasts, [None,None,None,None])
        self.assertEqual(transport.urls, [P1_URL, PREVIEW_URL])
        self.assert_capture(program, P1_URL, NOW); self.assert_capture(preview, PREVIEW_URL, NOW)

    def test_enabled_and_disabled_ready_outputs_are_byte_identical_with_same_gets(self):
        program = page(row_options={lane:dict(name=f'選手 {lane}') for lane in range(1,7)}); preview = frame(before_table(display='6.82',tilt='-0.5')+
                                           starts(populated=True)+weather())
        def produce(enabled):
            transport = Transport({P1_URL:program, PREVIEW_URL:preview})
            env = dict(self.env, RACE_AI_ORIGINAL_VAULT_ENABLED='true' if enabled else 'false')
            with self.p1(transport, environment=env), \
                 patch.object(pilot, 'collect_pitreport', return_value=None), \
                 patch.object(pilot, 'collect_entry_history', return_value=None):
                result = pilot.make_pair(DAY, RACE)
                count = pilot.requests_used
            return result, transport.urls, count
        plain, urls, count = produce(False)
        self.assertFalse(self.folder.exists())
        retained, retained_urls, retained_count = produce(True)
        self.assertEqual(plain[0]['state'], 'AB_GENERATED_NOT_YET_EXTERNAL_FROZEN')
        self.assertIsNotNone(plain[1])
        self.assertEqual(V._wire(retained), V._wire(plain))
        self.assertEqual((retained_urls, retained_count), (urls, count))
        self.assertEqual(urls, [P1_URL, PREVIEW_URL, source_url(kind='odds3t')])
        self.assertEqual(count, 3)
        self.assertEqual(len(self.captures()), 2)

    def test_invalid_http_identity_type_or_size_and_denials_never_claim_raw_capture(self):
        cases = [
            (b'invented', {'status':302}),
            (b'invented', {'content_type':'application/json'}),
            (b'invented', {'effective_url':'https://example.invalid/redirect'}),
            (b'', {}),
        ]
        for raw, options in cases:
            with self.subTest(options=options, size=len(raw)):
                transport = Transport({P1_URL:raw}, response_options=options)
                with self.p1(transport), self.assertRaises(pilot.SourceError):
                    pilot.get(P1_URL, day=DAY)
                self.assertFalse(self.folder.exists())
                self.assertEqual(transport.urls, [P1_URL])
        denied = Transport(failure=HTTPError(P1_URL,403,'fictional denial',{},None))
        with self.p1(denied), self.assertRaises(SourceWait) as held:pilot.get(P1_URL, day=DAY)
        self.assertEqual(held.exception.reason, 'SOURCE_AUTHORIZATION_REQUIRED')
        self.assertFalse(self.folder.exists())

    def test_accepted_body_over_capture_bound_holds_without_changing_getter_bound(self):
        raw = b'invented-large-body-' + b'x'*(4*1024*1024)
        transport = Transport({P1_URL:raw})
        with self.p1(transport), patch.object(pilot,'MAX_HTML',16_000_000), \
             self.assertRaises(SourceWait) as held:
            pilot.get(P1_URL, day=DAY)
        self.assert_hold(held.exception)
        self.assertEqual(transport.urls, [P1_URL])
        self.assertFalse(self.folder.exists())

    def test_write_failure_latches_existing_guard_and_stops_the_next_get(self):
        raw = b'invented accepted response whose private write fails'
        transport = Transport({P1_URL:raw})
        guard = self.new_guard(); before = cycle.load(guard.path)
        with self.p1(transport, guard=guard):
            with patch.object(C.os, 'open', side_effect=OSError('fictional private path/key/body')), \
                 self.assertRaises(SourceWait) as held:
                pilot.get(P1_URL, day=DAY)
            self.assert_hold(held.exception)
            with self.assertRaises(SourceWait) as again:pilot.get(PREVIEW_URL, day=DAY)
            self.assert_hold(again.exception, suppressed=False)
            self.assertEqual(pilot.requests_used, 1)
        after = cycle.load(guard.path)
        self.assertEqual(transport.urls, [P1_URL])
        self.assertEqual(after['requests_used'], before['requests_used']+1)
        self.assertEqual(after['lifetime_requests'], before['lifetime_requests']+1)
        self.assertEqual(after['requests_by_kind']['forecast'], 1)
        self.assertEqual(after['source_wait']['reason'], 'SOURCE_CAPTURE_UNAVAILABLE')
        self.assertEqual(after['source_wait']['state'], 'SOURCE_REVIEW_WAIT')
        self.assertIsNone(after['source_wait']['retry_at'])
        self.assertEqual(after['receipts'], before['receipts'])

    def test_latch_write_failure_still_raises_fixed_hold_without_private_details(self):
        transport = Transport({P1_URL:b'invented accepted response'})
        guard = self.new_guard()
        with self.p1(transport, guard=guard), \
             patch.object(C.os,'open',side_effect=OSError('fictional raw/key/path')), \
             patch.object(guard,'verification_failure',side_effect=OSError('fictional latch/key/path')), \
             self.assertRaises(SourceWait) as held:
            pilot.get(P1_URL, day=DAY)
        self.assert_hold(held.exception)
        self.assertEqual(transport.urls, [P1_URL])

    def test_national_loop_keeps_prior_pairs_and_request_counts_then_breaks_on_capture_hold(self):
        FixedClock.current = datetime(2030,4,1,3,35,tzinfo=timezone.utc)
        guard = self.new_guard(FixedClock.current)
        transport = Transport()
        calls = []
        def candidate(day, row, **_):
            calls.append(row['race_id'])
            url = pilot.racelist_endpoint(day, row['race_id'][9:11], int(row['race_id'][-2:]))
            if len(calls) == 2:
                with patch.object(C.os,'open',side_effect=OSError('fictional private write failure')):
                    pilot.get(url, day=day)
            else:pilot.get(url, day=day)
            # This generator boundary has no Actions artifact-time verifier.
            # Keep the earlier pair pending that independent check; a later
            # capture SourceWait must preserve it without claiming a receipt.
            return dict(race_id=row['race_id'],state='AB_GENERATED_NOT_YET_EXTERNAL_FROZEN'), \
                   dict(race_id=row['race_id']), None, None, None
        env = dict(self.env, RACE_AI_EVENT_DAY='2030-04-01')
        output = io.StringIO()
        with self.p1(transport, guard=guard, environment=env), \
             patch.object(pilot,'OUTPUT',self.root/'count-only-result'), \
             patch.object(pilot,'make_pair',side_effect=candidate), \
             patch.object(pilot,'load_original_race_ids',return_value=frozenset()), redirect_stdout(output):
            result = pilot.run(schedule_snapshot=schedule_snapshot(3))
        # On the unimplemented source, all three candidates run: fail first
        # on that missing stop, not on the normal end-of-batch receipt warning.
        self.assertEqual(calls, ['20300401-01-01','20300401-01-02'])
        self.assertEqual(result['reason'], 'SOURCE_CAPTURE_UNAVAILABLE')
        self.assertEqual([p['race_id'] for p in result['paired_forecasts']], ['20300401-01-01'])
        self.assertFalse(result['external_artifact_preclose_verified'])
        self.assertEqual(result['candidate_attempts'][0]['state'], 'AB_GENERATED_NOT_YET_EXTERNAL_FROZEN')
        self.assertEqual(result['source_request_count'], 2)
        self.assertEqual(cycle.load(guard.path)['requests_used'], 2)
        self.assertEqual(len(transport.urls), 2)
        self.assertEqual(len(self.captures()), 1)
        self.assertNotIn('fictional private write failure', output.getvalue())

    def test_midnight_response_is_retained_with_real_receive_time_before_generation_handoff(self):
        initial = datetime(2030,4,1,14,59,59,tzinfo=timezone.utc)
        received = datetime(2030,4,1,15,0,1,tzinfo=timezone.utc)
        FixedClock.current = initial
        raw = b'invented HTTP200 raw received after JST midnight'
        transport = Transport({P1_URL:raw},
            response_options={'after_read':lambda:setattr(FixedClock,'current',received)})
        env = dict(self.env,RACE_AI_EVENT_DAY='2030-04-01')
        with self.p1(transport,environment=env), self.assertRaisesRegex(ValueError,'DAY_HANDOFF'):
            pilot.get(P1_URL,day=DAY)
        self.assert_capture(raw,P1_URL,received)
        self.assertEqual(transport.urls,[P1_URL])


class BRawCaptureTests(RawFixture):
    def test_raw_survives_extract_failure_before_typed_capture(self):
        raw = collector_archive(); transport = Transport({B_URL:raw})
        FixedClock.current = B_NOW
        with self.b_source(transport), \
             patch.object(collector,'extract_daily_lzh',side_effect=ValueError('INVENTED_EXTRACT_FAILURE')):
            result = collector.collect(clock=lambda:B_NOW)
        self.assertEqual(result['reason'],'INVENTED_EXTRACT_FAILURE')
        self.assertEqual(result['race_count'],0)
        self.assert_capture(raw,B_URL,B_NOW)
        self.assertEqual(transport.urls,[B_URL])
        self.assertFalse((self.root/'boat-program-source').exists())

    def test_raw_survives_normalize_failure_before_typed_capture(self):
        raw = collector_archive(); transport = Transport({B_URL:raw})
        FixedClock.current = B_NOW
        with self.b_source(transport), patch('race_ai.program_race_isolation.normalize_races',
                side_effect=ValueError('INVENTED_NORMALIZE_FAILURE')):
            result = collector.collect(clock=lambda:B_NOW)
        self.assertEqual(result['reason'],'INVENTED_NORMALIZE_FAILURE')
        self.assertEqual(result['model_forecast_count'],0)
        self.assert_capture(raw,B_URL,B_NOW)
        self.assertFalse((self.root/'boat-program-source').exists())
        self.assertEqual(transport.urls,[B_URL])

    def test_malformed_lzh_is_retained_opaque_and_never_gains_typed_b_authority(self):
        raw = b'invented malformed LZH exact body\r\n\x00\xff'
        transport = Transport({B_URL:raw}); FixedClock.current = B_NOW
        with self.b_source(transport):result = collector.collect(clock=lambda:B_NOW)
        self.assertEqual(result['race_count'],0)
        self.assertEqual(result['predictions'],[])
        self.assertEqual(result['source_error_kind'],'VALIDATION')
        self.assert_capture(raw,B_URL,B_NOW)
        self.assertFalse((self.root/'boat-program-source').exists())
        self.assertEqual(transport.urls,[B_URL])

    def test_raw_precedes_clock_controlled_inspection_at_midnight(self):
        raw = collector_archive(); received = B_NOW+timedelta(days=1)
        transport = Transport({B_URL:raw}); FixedClock.current = received
        count = 0
        def day_clock():
            nonlocal count
            count += 1
            if count == 1:return B_NOW
            raise ValueError('DAY_HANDOFF')
        with self.b_source(transport), self.assertRaisesRegex(ValueError,'DAY_HANDOFF'):
            collector.collect(clock=day_clock)
        self.assert_capture(raw,B_URL,received)
        self.assertFalse((self.root/'boat-program-source').exists())
        self.assertEqual(transport.urls,[B_URL])

    def test_enabled_normal_forecasts_remain_byte_identical_and_use_one_existing_get(self):
        raw = collector_archive(); FixedClock.current = B_NOW
        def produce(enabled):
            env = dict(self.env,RACE_AI_ORIGINAL_VAULT_ENABLED='true' if enabled else 'false',
                       RACE_AI_SAVED_PROGRAM_CAPTURE='true' if enabled else 'false')
            transport = Transport({B_URL:raw})
            with self.b_source(transport,environment=env):
                result = collector.collect(clock=lambda:B_NOW)
            self.assertEqual(transport.urls,[B_URL])
            return result
        plain = produce(False)
        self.assertFalse(self.folder.exists())
        retained = produce(True)
        self.assertGreater(plain['race_count'],0)
        self.assertEqual(V._wire(retained),V._wire(plain))
        self.assert_capture(raw,B_URL,B_NOW)
        self.assertTrue((self.root/'boat-program-source'/'2030-01-15').is_dir())

    def test_bad_key_path_or_private_write_is_sourcewait_not_a_caught_model_failure(self):
        for defect in ('key','path','write'):
            FixedClock.current = B_NOW
            transport = Transport({B_URL:collector_archive()})
            env = dict(self.env)
            if defect == 'key':env['RACE_AI_STATE_KEY'] = 'invented-invalid-key'
            if defect == 'path':env['RUNNER_TEMP'] = str(self.repo)
            with self.subTest(defect=defect), ExitStack() as stack:
                # Mark the fake checkout so even a custom repository path is rejected.
                (self.repo/'.git').mkdir(exist_ok=True)
                stack.enter_context(self.b_source(transport,environment=env))
                if defect == 'write':
                    stack.enter_context(patch.object(C.os,'open',side_effect=OSError('invented private body/path')))
                with self.assertRaises(SourceWait) as held:collector.collect(clock=lambda:B_NOW)
                self.assert_hold(held.exception)
            self.assertEqual(transport.urls,[B_URL])
            self.assertFalse((self.root/'boat-program-source').exists())


class RawURLAdmissionTests(unittest.TestCase):
    def test_only_canonical_date_valid_p1_urls_extend_existing_vault_admission(self):
        for kind in ('racelist','beforeinfo'):
            for query in ('rno=1&jcd=01&hd=20300401','rno=12&jcd=24&hd=20300228',
                          'rno=2&jcd=12&hd=20320229'):
                with self.subTest(kind=kind,query=query):
                    self.assertTrue(V._capture_url('https://www.boatrace.jp/owpc/pc/race/'+kind+'?'+query))
        self.assertTrue(V._capture_url(B_URL))
        self.assertTrue(V._capture_url('https://www.boatrace.jp/owpc/pc/race/raceresult?rno=1&jcd=01&hd=20300401'))
        self.assertTrue(V._capture_url('https://api.github.com/repos/haji84/RACE-AI/actions/runs/42/artifacts?per_page=100&page=1'))

    def test_foreign_paths_credentials_ports_query_variants_and_impossible_dates_are_rejected(self):
        for bad in (
            P1_URL.replace('https:','http:'), P1_URL.replace('www.boatrace.jp','www.boatrace.jp.example.invalid'),
            P1_URL.replace('www.boatrace.jp','user@www.boatrace.jp'),
            P1_URL.replace('www.boatrace.jp','www.boatrace.jp:443'),
            P1_URL.replace('/racelist?','/racelist/?'), P1_URL.replace('/racelist?','/%72acelist?'),
            P1_URL.replace('/racelist?','/pitreport?'), P1_URL.replace('/racelist?','/odds3t?'),
            P1_URL+'#raw', P1_URL+'&retry=1', P1_URL+'&rno=12',
            P1_URL.replace('rno=12&jcd=12&hd=20300401','hd=20300401&jcd=12&rno=12'),
            P1_URL.replace('rno=12','rno=012'), P1_URL.replace('rno=12','rno=0'),
            P1_URL.replace('rno=12','rno=13'), P1_URL.replace('jcd=12','jcd=00'),
            P1_URL.replace('jcd=12','jcd=25'), P1_URL.replace('hd=20300401','hd=20300229'),
            P1_URL.replace('hd=20300401','hd=20300230'), P1_URL.replace('hd=20300401','hd=20301301'),
            P1_URL.replace('hd=20300401','hd=00000401'),
            PREVIEW_URL.replace('hd=20300401','hd=20310431'),
            B_URL.replace('b300115','b290115'), B_URL.replace('/B/','/K/'), B_URL+'?retry=1',
        ):
            with self.subTest(url=bad):self.assertFalse(V._capture_url(bad))


class MixedRawRetentionTests(RawFixture):
    def harness(self):
        fixture = batch_fixtures.CaptureBatchingTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.env = dict(self.env, RUNNER_TEMP=str(fixture.root))
        return fixture

    def fixture_command(self, fixture, method, *args, **kwargs):
        with patch.dict(os.environ,fixture.env,clear=True):
            return method(*args,**kwargs)

    def test_legacy_result_p1_and_opaque_b_round_trip_beyond_240_without_new_authority(self):
        f = self.harness()
        originals = [batch_fixtures.capture(f.folder,n) for n in range(238)]
        # Capture through the real opaque sink into the existing mixed folder.
        # Its name is fixed in production; the fixture adopts that same path.
        f.folder.rename(f.root/'boat-saved-view-captures'); f.folder = f.root/'boat-saved-view-captures'
        env = dict(f.env)
        bodies = [
            (b'invented raw malformed P1 program retained for independent replay',P1_URL),
            (b'invented raw pending P1 exhibition retained for independent replay',PREVIEW_URL),
            (b'invented malformed official-B raw without a first-P0 binding',B_URL),
        ]
        sink = getattr(C,'capture_http200',None)
        self.assertTrue(callable(sink),'accepted HTTP-200 opaque raw preservation is absent')
        for number,(raw,url) in enumerate(bodies):
            with patch.dict(os.environ,env,clear=True):
                sink(raw,source_url=url,received_at=NOW-timedelta(hours=1)+timedelta(microseconds=500+number))
        with C.CaptureInventory(f.folder,repo=f.repo,now=NOW) as inventory:
            original_pairs = [pair for group in inventory.groups() for pair in inventory.materialize(group)]
        self.assertEqual(len(original_pairs),241)
        code, report = self.fixture_command(f,f.retain)
        self.assertEqual(code,0); self.assertIs(report['complete'],True)
        self.assertEqual(report['retained_captures'],241); self.assertEqual(len(report['locators']),2)
        restored = []
        for locator in report['locators']:
            restored.extend(V.restore_capture_bundle(locator,f.repo,key=KEY,transport=f.reader)['captures'])
        self.assertCountEqual(restored,original_pairs)
        self.assertTrue(all(pair in restored for pair in originals))
        with patch.dict(os.environ,env,clear=True):
            for day in ('2030-01-14','2030-01-15','2030-01-17'):
                self.assertIsNone(program_source.load_program_source(day,{}, {},f.repo,key=KEY,transport=f.reader))
                self.assertIsNone(program_source.load_name_alias_source(day,f.repo,as_of=NOW.isoformat(),
                                                                        key=KEY,transport=f.reader))
        self.assertFalse(any(name.startswith(program_source.PREFIX) for tree in f.remote.objects.values()
                             for name in tree))
        for tree in f.remote.objects.values():
            for stored in tree.values():
                for raw,url in bodies:
                    self.assertNotIn(raw,stored); self.assertNotIn(url.encode(),stored)
        code, proof = self.fixture_command(f,f.restore_report,report)
        self.assertEqual(code,0); self.assertEqual(proof['captures'],241)
        actual = [(p.read_bytes(),p.with_suffix('.json').read_bytes())
                  for p in (f.root/'restored').rglob('capture-*.raw')]
        self.assertCountEqual(actual,original_pairs)

    def test_raw_p1_and_b_do_not_rewrite_existing_result_feed_records_or_forecasts(self):
        from tests.test_saved_view_feed import ProjectionTests
        f = ProjectionTests(); f.setUp(); self.addCleanup(f.doCleanups)
        raw = b'invented raw non-result source body'
        captures = [(raw,dict(source_url=url,captured_at=NOW.isoformat(),
                     source_sha256=sha256(raw).hexdigest(),http_status=200))
                    for url in (P1_URL,PREVIEW_URL,B_URL)]
        prior = deepcopy(f.view)
        baseline = F.update_view(f.view,[],synced_at=NOW.isoformat())
        replayed = F.update_view(f.view,[],synced_at=NOW.isoformat(),captures=captures)
        self.assertEqual(V._wire(replayed),V._wire(baseline))
        self.assertEqual(f.view,prior)
        self.assertEqual(F.originals_sha(replayed),F.originals_sha(prior))


if __name__ == '__main__':
    unittest.main()
