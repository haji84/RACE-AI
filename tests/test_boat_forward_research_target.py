"""One explicit real-race scope, using only fictional official HTML boundaries."""
from contextlib import redirect_stdout
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
from urllib.parse import parse_qs, urlsplit

from race_ai.actions_contract import digest
from tests.test_boat_active_exhibition import main_table, start_table
from tests.test_boat_official_program import page


DAY = date(2030, 4, 1)
NOW = datetime.fromisoformat('2030-04-01T20:18:00+09:00')
RID = '20300401-01-03'
CUTOFF = '2030-04-01T20:30:00+09:00'


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz is not None else NOW.replace(tzinfo=None)


class DiscoveryClock(datetime):
    current = NOW

    @classmethod
    def now(cls, tz=None):
        return cls.current.astimezone(tz) if tz is not None else cls.current.replace(tzinfo=None)


def day_index(venues):
    rows = ''.join(f'<tbody><tr><td><img src="/static_extra/pc/images/text_place1_{venue}.png"></td>'
        f'<td><a href="/owpc/pc/race/raceindex?jcd={venue}&amp;hd=20300401">合成開催</a></td>'
        f'<td><a href="/owpc/pc/race/racelist?rno=1&amp;jcd={venue}&amp;hd=20300401">出走表</a></td>'
        '</tr></tbody>' for venue in venues)
    return ('<div class="contentsFrame1_inner"><span class="title2_mainLabel">4月1日のレース情報</span>'
        '<p class="btnGroup3_refreshBtn"><a href="/owpc/pc/race/index?hd=20300401">更新</a></p>'
        '<table><thead><tr><th>レース場</th><th>進行状況</th><th>開催期間/日次</th><th>レース別情報</th>'
        '</tr></thead>' + rows + '</table><ul class="notes1">'
        '<li>締切予定時刻は締切5分前より赤く表示されます。</li></ul></div>').encode()


def target(*, race_id=RID, cutoff_at=CUTOFF, registration_ids=None, lane_map=None):
    registrations = ['4001', '4002', '4003', '4004', '4005', '4006'] if registration_ids is None else registration_ids
    roster = {str(lane): registration for lane, registration in enumerate(registrations, 1)} if lane_map is None else lane_map
    return dict(race_id=race_id, cutoff_at=cutoff_at, roster_sha256=digest(roster),
                active_count=len(roster))


def schedule():
    at = (NOW - timedelta(minutes=1)).isoformat()
    return dict(official_day_source=dict(url='https://www.boatrace.jp/owpc/pc/race/index?hd=20300401',
        source_sha256='a' * 64, captured_at=at), verified_active_venues=['01'],
        official_race_registry=[dict(race_id=f'20300401-01-{n:02d}', cutoff_at=CUTOFF,
            schedule_captured_at=at, source_sha256='b' * 64) for n in range(1, 8)])


def sources(*, lanes=(1, 2, 3, 4, 5, 6), withdrawn=()):
    program = page(venue='01', race_no=3, lanes=lanes, withdrawn=withdrawn,
        row_options={n: dict(name=f'選手 {n}') for n in lanes})
    active = tuple(sorted(set(lanes) - set(withdrawn)))
    preview = page(venue='01', race_no=3, content=main_table(lanes=active) + start_table(lanes=active)).replace(
        b'/owpc/pc/race/racelist?rno=', b'/owpc/pc/race/beforeinfo?rno=')
    return program, preview


class ResearchTargetTests(unittest.TestCase):
    def discovery(self, *, snapshot=None, venues=('01', '02'), r1=None, failure=None,
                  prior_wait=None, precharge=0, delays=None):
        """Use the real get and durable SourceGuard; replace only HTTP opener."""
        from scripts import boat_nationwide_ab_pilot as pilot
        from race_ai import repeated_cycle
        DiscoveryClock.current = NOW
        program, preview = sources()
        index_url = 'https://www.boatrace.jp/owpc/pc/race/index?hd=20300401'
        r1_url = 'https://www.boatrace.jp/owpc/pc/race/racelist?rno=1&jcd=01&hd=20300401'
        program_url = 'https://www.boatrace.jp/owpc/pc/race/racelist?rno=3&jcd=01&hd=20300401'
        preview_url = 'https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno=3&jcd=01&hd=20300401'
        bodies = {index_url: day_index(venues), r1_url: page(venue='01', race_no=1) if r1 is None else r1,
                  program_url: program, preview_url: preview}
        calls, retained = [], []
        class Response(io.BytesIO):
            status = 200
            headers = {'content-type': 'text/html; charset=utf-8'}
            def __init__(self, raw, url):
                super().__init__(raw)
                self.url = url
            def geturl(self):
                return self.url
        class Transport:
            def open(self, req, *, timeout):
                calls.append(req.full_url)
                DiscoveryClock.current += timedelta(seconds=(delays or {}).get(len(calls), 1))
                if failure is not None and len(calls) == failure[0]:
                    raise HTTPError(req.full_url, failure[1], 'fictional stop', {'Retry-After': '180'}, None)
                if req.full_url not in bodies:
                    raise AssertionError('out-of-target HTTP request: ' + req.full_url)
                return Response(bodies[req.full_url], req.full_url)
        original_cache = json.dumps(snapshot, sort_keys=True).encode()
        limits = {name: getattr(pilot, name) for name in ('REQUEST_CAP', 'VENUE_CAP', 'MAX_FORECASTS', 'MAX_ATTEMPTS', 'WAIT_SECONDS', 'MIN_TO_CUTOFF')}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'session.json'
            repeated_cycle.start(path, day=DAY.isoformat(), run_id=99, now=NOW)
            repeated_cycle.prepare(path, 1, now=NOW)
            guard = repeated_cycle.SourceGuard(path, clock=lambda: DiscoveryClock.current)
            for _ in range(precharge):
                guard.charge('forecast')
            if prior_wait is not None:
                guard.http_failure(prior_wait, headers={'Retry-After': '180'})
            with patch.object(pilot, 'OUTPUT', Path(folder) / 'output'), \
                 patch.object(pilot, 'datetime', DiscoveryClock), patch.object(pilot, 'SOURCE_GUARD', guard), \
                 patch.object(pilot.request, 'build_opener', return_value=Transport()), \
                 patch.object(pilot.time, 'sleep'), \
                 patch.object(pilot, 'load_original_race_ids', return_value=frozenset({RID})), \
                 patch.object(pilot, 'MODEL_INPUT_SINK', side_effect=lambda *args: retained.append(deepcopy(args))), \
                 patch.object(pilot, 'ISSUED_MODELS', {}), \
                 patch.object(pilot, 'collect_pitreport', return_value=None), \
                 patch.object(pilot, 'collect_entry_history', return_value=None), \
                 patch.dict(os.environ, {'RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED': 'true', 'RACE_AI_EVENT_DAY': DAY.isoformat()}), \
                 redirect_stdout(io.StringIO()):
                result = pilot.run(schedule_snapshot=snapshot, research_target=target())
            state = repeated_cycle.load(path)
        self.assertEqual(json.dumps(snapshot, sort_keys=True).encode(), original_cache)
        self.assertEqual({name: getattr(pilot, name) for name in limits}, limits)
        return result, calls, retained, state, (index_url, r1_url, program_url, preview_url)

    def invoke(self, request, *, snapshot='fresh', raw_program=None):
        from scripts import boat_nationwide_ab_pilot as pilot
        program, preview = sources()
        if raw_program is not None:
            program = raw_program
        requests, retained = [], []
        def get(url, **kwargs):
            requests.append(url)
            query = parse_qs(urlsplit(url).query)
            self.assertEqual(query, dict(rno=['3'], jcd=['01'], hd=['20300401']))
            raw = program if '/racelist?' in url else preview if '/beforeinfo?' in url else None
            self.assertIsNotNone(raw, 'explicit source-only target requested another source')
            return raw, NOW, sha256(raw).hexdigest()
        snapshot = schedule() if snapshot == 'fresh' else snapshot
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(pilot, 'OUTPUT', Path(folder)), patch.object(pilot, 'datetime', Clock), \
             patch.object(pilot, '_clock', return_value=NOW), patch.object(pilot, 'get', side_effect=get), \
             patch.object(pilot, 'official_schedule', side_effect=AssertionError('target must never discover other races')), \
             patch.object(pilot, 'observed_timestamp', return_value=NOW.isoformat()), \
             patch.object(pilot, 'load_original_race_ids', return_value=frozenset({RID})), \
             patch.object(pilot, 'MODEL_INPUT_SINK', side_effect=lambda *args: retained.append(deepcopy(args))), \
             patch.object(pilot, 'ISSUED_MODELS', {}), \
             patch.object(pilot, 'collect_pitreport', return_value=None), \
             patch.object(pilot, 'collect_entry_history', return_value=None), \
             patch.dict(os.environ, {'RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED': 'true', 'RACE_AI_EVENT_DAY': DAY.isoformat()}), \
             redirect_stdout(io.StringIO()):
            result = pilot.run(schedule_snapshot=snapshot, research_target=request)
        return result, requests, retained

    def pair(self, request, *, race=None, raw_program=None, raw_preview=None, preview_captured_at=None, clock_values=None):
        from scripts import boat_nationwide_ab_pilot as pilot
        program, preview = sources()
        program = program if raw_program is None else raw_program
        preview = preview if raw_preview is None else raw_preview
        requests, retained = [], []
        def get(url, **kwargs):
            requests.append(url)
            raw = program if '/racelist?' in url else preview
            at = NOW if preview_captured_at is None else (
                NOW - timedelta(seconds=3) if '/racelist?' in url else preview_captured_at)
            return raw, at, sha256(raw).hexdigest()
        race = dict(race_id=RID, cutoff_at=CUTOFF, source_capture_only=True) if race is None else race
        with patch.object(pilot, '_clock', return_value=NOW, side_effect=clock_values), patch.object(pilot, 'get', side_effect=get), \
             patch.object(pilot, 'MODEL_INPUT_SINK', side_effect=lambda *args: retained.append(deepcopy(args))), \
             patch.object(pilot, 'observed_timestamp', return_value=NOW.isoformat()):
            result = pilot.make_pair(DAY, race, research_target=request)
        return result, requests, retained

    def test_seven_eligible_races_acquire_only_the_exact_explicit_target(self):
        result, requests, retained = self.invoke(target())
        self.assertEqual([row['race_id'] for row in result['official_race_registry']], [RID])
        self.assertEqual([row['race_id'] for row in result['candidate_attempts']], [RID])
        self.assertEqual(result['candidate_attempts'][0]['state'], 'SOURCE_READY_ADDITIONAL_MODELS')
        self.assertEqual(result['deadline_targets']['due_races'], 1)
        self.assertEqual(len(requests), 2)
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0][0]['race_id'], RID)

    def test_wrong_current_roster_hash_or_count_stops_before_preview(self):
        wrong_hash = target()
        wrong_hash['roster_sha256'] = digest({'1': '4999', '2': '4002', '3': '4003',
            '4': '4004', '5': '4005', '6': '4006'})
        wrong_count = target(registration_ids=['4001', '4002', '4003', '4004', '4005'])
        changed_program = sources()[0].replace(b'4001', b'4999')
        for descriptor, raw in ((wrong_hash, None), (wrong_count, None), (target(), changed_program)):
            with self.subTest(descriptor=descriptor, changed=raw is not None):
                result, requests, retained = self.pair(descriptor, raw_program=raw)
                self.assertEqual(result[0]['state'], 'HOLD_RESEARCH_TARGET_ROSTER_MISMATCH')
                self.assertEqual(len(requests), 1)
                self.assertIn('/racelist?', requests[0])
                self.assertEqual(retained, [])

    def test_three_noncontiguous_active_lanes_use_registration_strings_in_lane_order(self):
        program, preview = sources(lanes=(6, 1, 3))
        result, requests, retained = self.pair(
            target(lane_map={'1': '4001', '3': '4003', '6': '4006'}), raw_program=program, raw_preview=preview)
        self.assertEqual(result[0]['state'], 'SOURCE_READY_ADDITIONAL_MODELS')
        self.assertEqual(len(requests), 2)
        self.assertEqual(len(retained), 1)
        self.assertEqual([row['racer_registration_id'] for row in retained[0][0]['boats']], ['4001', '4003', '4006'])

    def test_same_ordered_registration_ids_in_different_lanes_stop_before_preview(self):
        program, preview = sources(lanes=(6, 1, 3))
        descriptor = target(lane_map={'2': '4001', '4': '4003', '5': '4006'})
        result, requests, retained = self.pair(descriptor, raw_program=program, raw_preview=preview)
        self.assertEqual(result[0]['state'], 'HOLD_RESEARCH_TARGET_ROSTER_MISMATCH')
        self.assertEqual(len(requests), 1)
        self.assertEqual(retained, [])

    def test_unsupported_program_does_not_fall_back_to_exhibition_context_capture(self):
        raw = page(venue='01', race_no=3, row_options={1: dict(st='not a supported statistic')})
        result, requests, retained = self.pair(target(), raw_program=raw)
        self.assertEqual(result[0]['state'], 'HOLD_RESEARCH_TARGET_PROGRAM_UNSUPPORTED')
        self.assertEqual(len(requests), 1)
        self.assertEqual(retained, [])

    def test_programs_printed_cutoff_must_still_match_before_preview(self):
        result, requests, retained = self.pair(target(), raw_program=sources()[0].replace(b'20:30', b'20:31'))
        self.assertEqual(result[0]['state'], 'OFFICIAL_PROGRAM_OR_WITHDRAWAL_CONFLICT')
        self.assertEqual(len(requests), 1)
        self.assertEqual(retained, [])

    def test_time_spent_reading_program_cannot_issue_preview_after_safe_cutoff_margin(self):
        late = datetime.fromisoformat('2030-04-01T20:29:00+09:00')
        result, requests, retained = self.pair(target(), clock_values=[NOW] + [late] * 20)
        self.assertEqual(result[0]['state'], 'TOO_LATE_BEFORE_SOURCE')
        self.assertEqual(len(requests), 1)
        self.assertEqual(retained, [])

    def test_different_pair_race_or_cutoff_cannot_issue_even_a_program_request(self):
        for field, value in (('race_id', '20300401-01-04'), ('cutoff_at', '2030-04-01T20:31:00+09:00')):
            race = dict(race_id=RID, cutoff_at=CUTOFF)
            race[field] = value
            with self.subTest(field=field):
                result, requests, retained = self.pair(target(), race=race)
                self.assertEqual(result[0]['state'], 'HOLD_RESEARCH_TARGET_IDENTITY_OR_CUTOFF_MISMATCH')
                self.assertEqual((requests, retained), ([], []))

    def test_cold_or_stale_schedule_uses_real_guarded_discovery_only_for_target_venue(self):
        stale = schedule()
        old_clock = (NOW - timedelta(minutes=45)).isoformat()
        stale['official_day_source']['captured_at'] = old_clock
        for row in stale['official_race_registry']:
            row['schedule_captured_at'] = old_clock
        for snapshot in (None, stale):
            with self.subTest(snapshot=snapshot):
                result, calls, retained, state, urls = self.discovery(snapshot=snapshot)
                self.assertEqual(calls, list(urls))
                self.assertEqual(result['candidate_attempts'][0]['state'], 'SOURCE_READY_ADDITIONAL_MODELS')
                self.assertEqual(result['source_request_count'], 4)
                self.assertEqual(state['requests_used'], 4)
                self.assertEqual(state['requests_by_kind'], {'forecast': 4})
                self.assertEqual(result['official_day_source']['captured_at'], (NOW + timedelta(seconds=1)).astimezone(timezone.utc).isoformat())
                self.assertEqual(result['official_race_registry'][0]['schedule_captured_at'], (NOW + timedelta(seconds=2)).astimezone(timezone.utc).isoformat())
                self.assertEqual(retained[0][0]['captured_at'], (NOW + timedelta(seconds=3)).astimezone(timezone.utc).isoformat())
                self.assertEqual(retained[0][1]['captured_at'], (NOW + timedelta(seconds=4)).astimezone(timezone.utc).isoformat())
                self.assertEqual(retained[0][2], (NOW + timedelta(seconds=4)).astimezone(timezone.utc).isoformat())
        self.assertEqual(stale['official_day_source']['captured_at'], old_clock)

    def test_usable_cache_preserves_original_metadata_and_skips_all_discovery_gets(self):
        cached = schedule()
        result, calls, retained, state, urls = self.discovery(snapshot=cached)
        self.assertEqual(calls, list(urls[2:]))
        self.assertEqual(state['requests_used'], 2)
        self.assertEqual({k: result['official_day_source'][k] for k in cached['official_day_source']},
                         cached['official_day_source'])
        self.assertEqual(result['official_race_registry'][0]['schedule_captured_at'],
                         cached['official_race_registry'][0]['schedule_captured_at'])
        self.assertEqual(retained[0][2], (NOW + timedelta(seconds=2)).astimezone(timezone.utc).isoformat())

    def test_inactive_target_venue_stops_after_verified_index_without_any_racelist(self):
        result, calls, retained, state, urls = self.discovery(venues=('02', '04'))
        self.assertEqual(result['reason'], 'HOLD_RESEARCH_TARGET_VENUE_INACTIVE')
        self.assertEqual(calls, [urls[0]])
        self.assertEqual((retained, state['requests_used']), ([], 1))

    def test_r1_wrong_identity_or_printed_cutoff_stops_before_target_program(self):
        for raw in (page(venue='02', race_no=1), page(venue='01', race_no=1).replace(b'20:30', b'20:31')):
            with self.subTest(body=sha256(raw).hexdigest()):
                result, calls, retained, state, urls = self.discovery(r1=raw)
                self.assertEqual(calls, list(urls[:2]))
                self.assertEqual(retained, [])
                self.assertEqual(state['requests_used'], 2)
                self.assertIn(result['reason'], ('NO_VERIFIED_CUTOFF_ROWS', 'HOLD_RESEARCH_TARGET_SCHEDULE_MISMATCH'))

    def test_real_get_denial_and_rate_limit_latch_same_guard_before_target_program(self):
        for status, reason, waiting in ((401, 'SOURCE_AUTHORIZATION_REQUIRED', 'AUTHORIZATION_WAIT'),
                                        (403, 'SOURCE_AUTHORIZATION_REQUIRED', 'AUTHORIZATION_WAIT'),
                                        (429, 'HTTP_RATE_LIMIT', 'RATE_LIMIT_WAIT')):
            with self.subTest(status=status):
                result, calls, retained, state, urls = self.discovery(failure=(2, status))
                self.assertEqual(calls, list(urls[:2]))
                self.assertEqual((result['reason'], state['source_wait']['state']), (reason, waiting))
                self.assertEqual((retained, state['requests_used']), ([], 2))

    def test_known_wait_blocks_day_index_before_actual_http_request(self):
        for status, reason in ((401, 'SOURCE_AUTHORIZATION_REQUIRED'), (403, 'SOURCE_AUTHORIZATION_REQUIRED'), (429, 'HTTP_RATE_LIMIT'),
                               (503, 'SOURCE_TEMPORARILY_UNAVAILABLE')):
            with self.subTest(status=status):
                result, calls, retained, state, _ = self.discovery(prior_wait=status)
                self.assertEqual(result['reason'], reason)
                self.assertEqual((calls, retained, state['requests_used']), ([], [], 0))

    def test_existing_round_budget_blocks_target_program_without_another_http(self):
        result, calls, retained, state, urls = self.discovery(precharge=43)
        self.assertEqual(calls, list(urls[:2]))
        self.assertEqual(state['requests_used'], 45)
        self.assertEqual(state['halted_reason'], 'ROUND_SOURCE_BUDGET_EXHAUSTED')
        self.assertEqual(retained, [])
        self.assertEqual(result['candidate_attempts'][0]['state'], 'OFFICIAL_RACE_REJECTED')

    def test_discovery_latency_stops_before_any_later_forbidden_http_or_input_sink(self):
        # Each response owns its real new capture clock. Once the 600-second
        # requirement is lost, retain charged HTTP outcomes and make no next GET.
        for delayed_response in range(1, 5):
            with self.subTest(delayed_response=delayed_response):
                result, calls, retained, state, urls = self.discovery(delays={delayed_response: 121 - delayed_response})
                self.assertEqual(calls, list(urls[:delayed_response]))
                self.assertEqual(state['requests_used'], delayed_response)
                self.assertEqual(retained, [])
                if delayed_response == 1:
                    self.assertEqual(result['reason'], 'TOO_LATE_BEFORE_SOURCE')
                else:
                    self.assertEqual(result['candidate_attempts'][0]['state'],
                                     'TOO_LATE_AFTER_SOURCE' if delayed_response == 4 else 'TOO_LATE_BEFORE_SOURCE')

    def test_missing_race_or_different_verified_cutoff_is_held_before_get(self):
        for descriptor in (target(race_id='20300401-01-08'), target(cutoff_at='2030-04-01T20:31:00+09:00')):
            with self.subTest(descriptor=descriptor):
                result, requests, retained = self.invoke(descriptor)
                self.assertEqual(result['reason'], 'HOLD_RESEARCH_TARGET_SCHEDULE_MISMATCH')
                self.assertEqual((requests, retained), ([], []))

    def test_invalid_descriptor_fields_current_day_cutoff_and_count_stop_before_any_get(self):
        cases = []
        for field, value in (('race_id', '20300401-25-03'), ('race_id', '20300331-01-03'),
                             ('cutoff_at', '2030-04-01T20:30:00'), ('cutoff_at', '2030-04-01T11:30:00+00:00'),
                             ('cutoff_at', '2030-04-02T20:30:00+09:00'), ('cutoff_at', '2030-04-01T20:17:00+09:00'),
                             ('roster_sha256', 'A' * 64), ('active_count', True), ('active_count', 2), ('active_count', 7)):
            descriptor = target()
            descriptor[field] = value
            cases.append(descriptor)
        cases += [dict(target(), extra=True), {k: v for k, v in target().items() if k != 'roster_sha256'}, [], False]
        for descriptor in cases:
            with self.subTest(descriptor=descriptor):
                result, requests, retained = self.invoke(descriptor)
                self.assertEqual(result['reason'], 'HOLD_RESEARCH_TARGET_INVALID')
                self.assertEqual((requests, retained), ([], []))

    def test_explicit_none_keeps_default_pair_bytes_and_source_order(self):
        from scripts import boat_nationwide_ab_pilot as pilot
        program, preview = sources()
        race = dict(race_id=RID, cutoff_at=CUTOFF, source_capture_only=True)
        records = []
        for explicit in (False, True):
            calls = []
            def get(url, **kwargs):
                calls.append(url)
                raw = program if '/racelist?' in url else preview
                return raw, NOW, sha256(raw).hexdigest()
            with patch.object(pilot, '_clock', return_value=NOW), patch.object(pilot, 'get', side_effect=get), \
                 patch.object(pilot, 'MODEL_INPUT_SINK', return_value=None), \
                 patch.object(pilot, 'observed_timestamp', return_value=NOW.isoformat()):
                out = pilot.make_pair(DAY, race, **({'research_target': None} if explicit else {}))
            records.append((json.dumps(out, sort_keys=True).encode(), calls))
        self.assertEqual(records[0], records[1])

    def test_only_explicit_target_passes_actual_preview_capture_as_native_master_asof(self):
        captured = NOW - timedelta(seconds=2)
        for descriptor, expected in ((None, NOW.isoformat()), (target(), captured.isoformat())):
            with self.subTest(explicit=descriptor is not None):
                result, requests, retained = self.pair(descriptor, preview_captured_at=captured)
                self.assertEqual(result[0]['state'], 'SOURCE_READY_ADDITIONAL_MODELS')
                self.assertEqual(len(requests), 2)
                self.assertEqual(retained[0][2], expected)
                self.assertEqual(retained[0][1]['captured_at'], captured.isoformat())
                self.assertEqual(result[0]['generated_at'], NOW.isoformat())

    def test_parsed_capture_clock_mismatch_cannot_retime_or_retain_native_inputs(self):
        from scripts import boat_nationwide_ab_pilot as pilot
        original = pilot.parse_active_beforeinfo
        for field in ('captured_at', 'context_source'):
            def mismatch(*args, **kwargs):
                out = original(*args, **kwargs)
                if field == 'captured_at':
                    out['captured_at'] = NOW.isoformat()
                else:
                    out['context']['source']['captured_at'] = NOW.isoformat()
                return out
            with self.subTest(field=field), patch.object(pilot, 'parse_active_beforeinfo', side_effect=mismatch):
                result, requests, retained = self.pair(target(), preview_captured_at=NOW - timedelta(seconds=2))
                self.assertEqual(result[0]['state'], 'HOLD_RESEARCH_TARGET_CAPTURE_CLOCK_MISMATCH')
                self.assertEqual(len(requests), 2)
                self.assertEqual(retained, [])


if __name__ == '__main__':
    unittest.main()
