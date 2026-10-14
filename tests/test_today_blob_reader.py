import copy
import importlib.util
import json
import os
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock

MODULE = Path(__file__).resolve().parents[1] / 'web/api/today.py'
spec = importlib.util.spec_from_file_location('race_today_api', MODULE)
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)
NOW = datetime(2026, 10, 14, 23, tzinfo=timezone.utc)
DAY = '2026-10-15'
KEY = f'race-ai/day/{DAY}.json'
ENV = {'RACE_AI_FEED_APPROVED': '1', 'BLOB_READ_WRITE_TOKEN': 'test-fixture-token'}


def payload():
    return dict(date_jst=DAY, source_url='https://www.boatrace.jp/approved', source_sha256='a' * 64,
        first_observed_at='2026-10-15T07:00:00+09:00', redistribution_authorized=True,
        races=1, complete_six_boat_races=1, venues=[dict(venue='18', races=[dict(
            race_id='20261015-18-01', closed_at='2026-10-15T08:43:00+09:00',
            boats=[dict(lane=i, racer_registration_id=str(4000 + i), motor_no=10 + i,
                        boat_no=20 + i, name=f'合成選手{i}') for i in range(1, 7)])])])


def response(data=None, **changes):
    raw = json.dumps(payload() if data is None else data).encode()
    result = dict(status_code=200, pathname=KEY, content_type='application/json',
                  size=len(raw), content=raw, url='https://fixture.private.blob.vercel-storage.com/' + KEY)
    result.update(changes)
    return SimpleNamespace(**result)


class TodayBlobReaderTests(unittest.TestCase):
    def load(self, data=None, result=None, env=None, after=NOW):
        self.client = Mock()
        self.client.get.return_value = result or response(data)
        self.factory = Mock(return_value=self.client)
        with patch.dict(os.environ, ENV if env is None else env, clear=True), \
             patch.object(api, 'create_blob_client', self.factory), \
             patch.object(api, 'utc_now', side_effect=[NOW, after]):
            return api.load_feed()

    def test_unapproved_never_constructs_client(self):
        status, data = self.load(env={'RACE_AI_FEED_APPROVED': '0'})
        self.assertEqual((status, data['error']), (503, 'FEED_NOT_APPROVED'))
        self.factory.assert_not_called()

    def test_oidc_token_alone_is_not_a_blob_read_write_token(self):
        for env in ({'RACE_AI_FEED_APPROVED': '1'},
                    {'RACE_AI_FEED_APPROVED': '1', 'VERCEL_OIDC_TOKEN': 'oidc-fixture'}):
            status, data = self.load(env=env)
            self.assertEqual((status, data['error']), (503, 'FEED_STORE_NOT_CONFIGURED'))
            self.factory.assert_not_called()

    def test_uses_pinned_sdk_content_and_exact_key_without_guessed_host(self):
        status, data = self.load()
        self.assertEqual(status, 200)
        self.assertEqual(data, payload())
        self.factory.assert_called_once_with('test-fixture-token')
        self.client.get.assert_called_once_with(KEY, access='private', timeout=8, use_cache=False)
        self.client.close.assert_called_once()

    def test_sdk_metadata_and_size_must_match(self):
        for changes in ({'status_code': 304}, {'pathname': 'race-ai/day/2026-10-14.json'},
                        {'content_type': 'text/html'}, {'size': api.MAX_BYTES + 1},
                        {'size': -1}, {'content': b'x' * (api.MAX_BYTES + 1)},
                        {'content': 'not bytes'}, {'url': 'https://evil.example/' + KEY}):
            with self.subTest(changes=list(changes)):
                status, _ = self.load(result=response(**changes))
                self.assertEqual(status, 503)
                self.client.close.assert_called_once()

    def test_full_snapshot_identity_and_allocations_are_validated(self):
        changes = [lambda p: p.update(date_jst='2026-10-14'),
                   lambda p: p.update(redistribution_authorized=False),
                   lambda p: p.update(source_sha256='not a hash'),
                   lambda p: p.update(source_url='https://user:secret@example.org/'),
                   lambda p: p.update(races=2),
                   lambda p: p.update(complete_six_boat_races=2),
                   lambda p: p['venues'][0].update(venue='25'),
                   lambda p: p['venues'].append(copy.deepcopy(p['venues'][0])),
                   lambda p: p['venues'][0]['races'][0].update(race_id='20261015-17-01'),
                   lambda p: p['venues'][0]['races'][0]['boats'][0].update(lane=True),
                   lambda p: p['venues'][0]['races'][0]['boats'][1].update(lane=1),
                   lambda p: p['venues'][0]['races'][0]['boats'][1].update(racer_registration_id='4001'),
                   lambda p: p['venues'][0]['races'][0]['boats'][1].update(motor_no=11),
                   lambda p: p['venues'][0]['races'][0]['boats'][0].update(motor_no=-1),
                   lambda p: p['venues'][0]['races'][0]['boats'][0].update(boat_no=0)]
        for change in changes:
            data = payload()
            change(data)
            with self.subTest(change=change):
                self.assertEqual(self.load(data=data)[0], 503)

    def test_as_of_timestamps_reject_future_naive_wrong_day_and_midnight(self):
        for observed in ('2026-10-15T09:00:00+09:00', '2026-10-14T23:59:00+09:00',
                         '2026-10-15T07:00:00', 'invalid'):
            data = payload()
            data['first_observed_at'] = observed
            self.assertEqual(self.load(data=data)[0], 503)
        data = payload()
        data['venues'][0]['races'][0]['boats'][0]['detail_captured_at'] = '2026-10-15T09:00:00+09:00'
        self.assertEqual(self.load(data=data)[0], 503)
        self.assertEqual(self.load(after=NOW + timedelta(days=1))[0], 503)

    def test_missing_values_remain_missing_and_partial_races_are_counted(self):
        data = payload()
        data['venues'][0]['races'][0]['closed_at'] = None
        boats = data['venues'][0]['races'][0]['boats']
        boats.pop()
        boats[0]['motor_no'] = None
        data['complete_six_boat_races'] = 0
        self.assertEqual(self.load(data=data), (200, data))

    def test_duplicate_json_keys_and_nonfinite_values_are_rejected(self):
        for raw in (b'{"date_jst":"2026-10-15","date_jst":"2026-10-14"}',
                    b'{"value":NaN}', b'{"value":1e999}', b'[]', b'null', b'\xff'):
            self.assertEqual(self.load(result=response(content=raw, size=len(raw)))[0], 503)

    def test_sdk_compressed_content_length_does_not_redefine_decoded_bytes(self):
        self.assertEqual(self.load(result=response(size=32))[0], 200)

    def test_unencodable_json_cannot_reach_response_handler(self):
        data = payload()
        data['extra'] = '\ud800'
        self.assertEqual(self.load(data=data)[0], 503)

    def test_multi_source_provenance_cannot_conflict_with_primary_source(self):
        data = payload()
        data['sources'] = [{key: data[key] for key in ('source_url', 'source_sha256', 'first_observed_at')}]
        self.assertEqual(self.load(data=data)[0], 200)
        data['sources'][0]['source_sha256'] = 'b' * 64
        self.assertEqual(self.load(data=data)[0], 503)

    def test_no_event_missing_and_failed_venues_require_bound_schedule_proof(self):
        from race_ai.official_day_schedule import parse_day_schedule, merge_schedule_programs, endpoint
        from tests.test_official_day_schedule import fixture, DAY as DAY_VALUE, STAMP
        schedule=parse_day_schedule(fixture(),day=DAY_VALUE,source_url=endpoint(DAY_VALUE),observed_at=STAMP)
        data=merge_schedule_programs(schedule,errors={'04':'SOURCE_UNAVAILABLE'})
        data['redistribution_authorized']=True
        self.assertEqual(self.load(data=data)[0],200)
        self.assertEqual(data['venues'][1]['status'],'UNOBTAINED')
        self.assertEqual(data['venues'][3]['status'],'ERROR')
        self.assertEqual(data['venues'][17]['status'],'NO_EVENT')
        for field,value in (('schedule_source_sha256','b'*64),('schedule_observed_at','2026-10-14T03:00:00+09:00'),
                            ('schedule_verified',False),('no_event',False)):
            bad=copy.deepcopy(data);bad['venues'][17][field]=value
            self.assertEqual(self.load(data=bad)[0],503)

    def test_empty_full_day_requires_current_complete_source_reference(self):
        data=payload()
        data.update(venues=[],races=0,complete_six_boat_races=0,status='NO_EVENT',no_event=True,
                    schedule_verified=True,active_venues=[])
        self.assertEqual(self.load(data=data)[0],503)
        data['sources']=[{key:data[key] for key in ('source_url','source_sha256','first_observed_at')}]
        data.update(schedule_source_url=data['source_url'],schedule_source_sha256=data['source_sha256'],
                    schedule_observed_at=data['first_observed_at'])
        self.assertEqual(self.load(data=data)[0],200)
        data['active_venues']=['18']
        self.assertEqual(self.load(data=data)[0],503)

    def test_sdk_exceptions_are_redacted_and_client_is_closed(self):
        self.client = Mock()
        self.client.get.side_effect = RuntimeError('secret-fixture-never-return')
        with patch.dict(os.environ, ENV, clear=True), \
             patch.object(api, 'create_blob_client', return_value=self.client), \
             patch.object(api, 'utc_now', return_value=NOW):
            result = api.load_feed()
        self.assertEqual(result, (503, {'error': 'FEED_STORE_UNAVAILABLE'}))
        self.client.close.assert_called_once()
