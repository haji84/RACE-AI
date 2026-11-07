"""One explicit real-race scope, using only fictional official HTML boundaries."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import date, datetime, timedelta
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from race_ai.actions_contract import digest
from tests.test_boat_active_exhibition import main_table, start_table
from tests.test_boat_official_program import page


DAY = date(2030, 4, 1)
NOW = datetime.fromisoformat('2030-04-01T20:20:00+09:00')
RID = '20300401-01-03'
CUTOFF = '2030-04-01T20:30:00+09:00'


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz is not None else NOW.replace(tzinfo=None)


def target(*, race_id=RID, cutoff_at=CUTOFF, registration_ids=None):
    registrations = ['4001', '4002', '4003', '4004', '4005', '4006'] if registration_ids is None else registration_ids
    return dict(race_id=race_id, cutoff_at=cutoff_at, roster_sha256=digest(registrations),
                active_count=len(registrations))


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
        wrong_hash['roster_sha256'] = digest(['4999', '4002', '4003', '4004', '4005', '4006'])
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
            target(registration_ids=['4001', '4003', '4006']), raw_program=program, raw_preview=preview)
        self.assertEqual(result[0]['state'], 'SOURCE_READY_ADDITIONAL_MODELS')
        self.assertEqual(len(requests), 2)
        self.assertEqual(len(retained), 1)
        self.assertEqual([row['racer_registration_id'] for row in retained[0][0]['boats']], ['4001', '4003', '4006'])

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

    def test_missing_or_stale_schedule_is_held_without_nationwide_discovery(self):
        stale = schedule()
        stale['official_day_source']['captured_at'] = (NOW - timedelta(days=1)).isoformat()
        for snapshot in (None, stale):
            with self.subTest(snapshot=snapshot):
                result, requests, retained = self.invoke(target(), snapshot=snapshot)
                self.assertEqual(result['reason'], 'HOLD_RESEARCH_TARGET_SCHEDULE_UNAVAILABLE')
                self.assertEqual((requests, retained), ([], []))

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
                             ('cutoff_at', '2030-04-02T20:30:00+09:00'), ('cutoff_at', '2030-04-01T20:19:00+09:00'),
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
