"""One-GET behavior exercised with real parsers and synthetic HTTP responses."""
from datetime import timedelta
from http.client import HTTPException
import importlib
import json
from pathlib import Path
import unittest
from urllib.error import URLError

from race_ai.core import SourceError
from race_ai.official_racelist_adapter import endpoint, MAX_BYTES
from race_ai.tokuyama_day_worker import FetchResponse
from tests.test_name_binding_contract import (body, program, PINS, CAPTURE, GENERATED, NOW, DAY)
from tests.test_official_racelist_adapter import fixture
from web import race_contract as facts


def review():
    return json.loads((Path(__file__).resolve().parents[1]/'config/operator-official-facts.json').read_text(encoding='utf-8'))


class NameBindingSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.worker = importlib.import_module('race_ai.name_binding_source')
        except ModuleNotFoundError:
            cls.worker = None

    def setUp(self):
        self.assertIsNotNone(self.worker, 'bounded registered-name collector must exist')
        self.calls = []
        self.race = program()

    def collect(self, *, raw=None, response=None, failure=None, clocks=None, **kwargs):
        clocks = iter(clocks or [CAPTURE, CAPTURE+timedelta(milliseconds=100), GENERATED])
        def transport(url, *, timeout, max_bytes):
            self.calls.append((url, timeout, max_bytes))
            if failure: raise failure
            return response if response is not None else FetchResponse(body() if raw is None else raw, url, 200, 'text/html; charset=UTF-8')
        return self.worker.collect_name_binding(self.race, **PINS, review=kwargs.pop('review', review()),
            execute=kwargs.pop('execute', True), transport=transport, clock=lambda:next(clocks), **kwargs)

    def test_default_dry_run_never_performs_a_source_request(self):
        result = self.worker.collect_name_binding(self.race, **PINS, review=review(),
            transport=lambda *a, **k:self.fail('dry run fetched'), clock=lambda:CAPTURE)
        self.assertEqual(result['status'], 'DRY_RUN')
        self.assertEqual(result, dict(status='DRY_RUN', race_id=self.race['race_id'],
            source_url=endpoint(DAY, '18', 1), **PINS))

    def test_one_exact_get_uses_real_postresponse_clock_and_keeps_only_normalized_names(self):
        before = facts.canonical(self.race)
        result = self.collect()
        self.assertEqual(result['status'], 'COLLECTED')
        self.assertEqual(self.calls, [(endpoint(DAY, '18', 1), 10, MAX_BYTES)])
        self.assertEqual(set(result), {'status', 'snapshot'})
        snapshot = result['snapshot']
        self.assertEqual(snapshot['source']['captured_at'], facts.stamp(CAPTURE+timedelta(milliseconds=100)))
        self.assertEqual(snapshot['generated_at'], facts.stamp(GENERATED))
        self.assertEqual(snapshot['bindings'][0]['verified_full_name'], '松田 大志郎')
        self.assertEqual(facts.canonical(self.race), before)
        self.assertNotIn('<html', facts.canonical(result).decode())
        self.assertNotIn('body', result)

    def test_wrong_review_scope_purpose_and_future_review_stop_before_get(self):
        for field, value in (('facts_ingest', False), ('facts_store', False), ('source_scopes',
            ['https://www.boatrace.jp/owpc/pc/race/beforeinfo']), ('venue_codes', ['17']),
            ('review_type', 'self_approval'), ('evidence_reference', ''),
            ('reviewed_at', '2026-10-16T00:00:00+09:00')):
            checked = review(); checked[field] = value
            self.calls = []
            result = self.collect(review=checked)
            with self.subTest(field=field):
                self.assertEqual(result, {'status':'SOURCE_RIGHTS_BLOCKED'})
                self.assertEqual(self.calls, [])

    def test_invalid_program_pin_day_or_120second_margin_stops_before_get(self):
        close = facts._time(self.race['closed_at'])
        for clock, status in ((CAPTURE-timedelta(days=1), 'DAY_INVALID'),
            (CAPTURE.replace(tzinfo=None), 'DAY_INVALID'), (close-timedelta(seconds=120), 'CUTOFF_PASSED'),
            (close, 'CUTOFF_PASSED')):
            self.calls = []; result = self.collect(clocks=[clock])
            with self.subTest(clock=clock):
                self.assertEqual(result['status'], status); self.assertEqual(self.calls, [])
        for field, value in (('racer_registration_id', 'invalid'), ('racer_registration_id', '0000'),
            ('name', '松田\u200b大志'), ('name', '松'*129)):
            self.race = program(); self.race['boats'][0][field] = value
            result = self.collect()
            with self.subTest(field=field, value=value):
                self.assertEqual(result, {'status':'PROGRAM_INVALID'}); self.assertEqual(self.calls, [])
        self.race = program()
        result = self.worker.collect_name_binding(self.race, baseline_snapshot_id='BAD',
            b_program_sha256=PINS['b_program_sha256'], review=review(), execute=True,
            transport=lambda *a, **k:self.fail('invalid pin fetched'), clock=lambda:CAPTURE)
        self.assertEqual(result['status'], 'PROGRAM_INVALID')

    def test_body_date_lane_link_printed_registration_and_registration_lane_swaps_reject(self):
        html = body().decode()
        swapped = html.replace('4544', 'SWAP').replace('4002', '4544').replace('SWAP', '4002')
        for raw in (fixture(DAY.replace(day=14)).encode(),
            html.replace('is-boatColor6', 'is-boatColor1').encode(),
            html.replace('toban=4544', 'toban=4999', 1).encode(),
            html.replace('4544 /', '4999 /').encode(), swapped.encode(),
            html.replace('08:03', '08:04').encode(), b'<p>no data</p>'):
            self.calls = []; result = self.collect(raw=raw)
            with self.subTest(raw=raw[:60]):
                self.assertIn(result['status'], {'SOURCE_INVALID', 'NAME_BINDING_INVALID'})
                self.assertEqual(len(self.calls), 1); self.assertNotIn('snapshot', result)

    def test_transport_and_response_failures_do_not_retry_or_leak_raw_messages(self):
        for failure, status in ((URLError('PRIVATE_RESPONSE'), 'SOURCE_UNAVAILABLE'),
            (TimeoutError('PRIVATE_RESPONSE'), 'SOURCE_UNAVAILABLE'),
            (HTTPException('PRIVATE_RESPONSE'), 'SOURCE_UNAVAILABLE'),
            (SourceError('PRIVATE_RESPONSE'), 'SOURCE_INVALID')):
            self.calls = []; result = self.collect(failure=failure)
            with self.subTest(failure=type(failure).__name__):
                self.assertEqual(result, {'status':status}); self.assertEqual(len(self.calls), 1)
                self.assertNotIn('PRIVATE_RESPONSE', repr(result))
        url = endpoint(DAY, '18', 1)
        for response in (None, FetchResponse(body(), url, 302, 'text/html'),
            FetchResponse(body(), url+'#other', 200, 'text/html'),
            FetchResponse(body(), url, 200, 'application/json'),
            FetchResponse(body().decode(), url, 200, 'text/html'),
            FetchResponse(b'x'*(MAX_BYTES+1), url, 200, 'text/html')):
            if response is None: continue
            self.calls = []; result = self.collect(response=response)
            with self.subTest(response_type=type(response.body).__name__, status=response.status):
                self.assertEqual(result['status'], 'SOURCE_INVALID'); self.assertEqual(len(self.calls), 1)

    def test_actual_clock_crossing_close_midnight_or_reversing_cannot_make_a_proof(self):
        close = facts._time(self.race['closed_at'])
        for clocks, status in (([CAPTURE, close], 'CUTOFF_PASSED'),
            ([CAPTURE, CAPTURE+timedelta(days=1)], 'DAY_INVALID'),
            ([CAPTURE, CAPTURE-timedelta(seconds=1)], 'SOURCE_INVALID'),
            ([CAPTURE, GENERATED, CAPTURE], 'SOURCE_INVALID'),
            ([CAPTURE, GENERATED, close], 'CUTOFF_PASSED')):
            self.calls = []; result = self.collect(clocks=clocks)
            with self.subTest(clocks=clocks):
                self.assertEqual(result['status'], status); self.assertEqual(len(self.calls), 1)
                self.assertNotIn('snapshot', result)

if __name__ == '__main__': unittest.main()
