"""Exercise scheduled video intake, evaluation and safe holds without provider access."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image


NOW = datetime(2026, 11, 26, 3, tzinfo=timezone.utc)
RACE = '20261125-12-03'


class MacCycleTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()

    def write(self, file, *rows):
        path = self.root / file
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
        return path

    def run_cycle(self, *, free_gib=100, **inputs):
        from scripts import keirin_mac_cycle as cycle

        with patch.object(cycle.market, 'evaluate_retained', return_value={
                'candidate_disposition': 'HOLD_INDEPENDENT_MARKET_EVALUATION'}), \
                patch.object(cycle.shutil, 'disk_usage', return_value=SimpleNamespace(free=free_gib*cycle.GIB)):
            return cycle.run_cycle(self.root, clock=lambda: NOW, **inputs)

    def test_no_census_runs_the_retained_comparison_and_preserves_absent_video_state(self):
        result = self.run_cycle()
        self.assertEqual(result['video']['state'], 'WAITING_FOR_CENSUS')
        self.assertEqual(result['market_third']['candidate_disposition'], 'HOLD_INDEPENDENT_MARKET_EVALUATION')
        self.assertFalse((self.root/'corpus.sqlite').exists())
        self.assertEqual(json.loads((self.root/'cycle-report.json').read_bytes()), result)

    def test_cycle_history_retains_multiple_ticks_and_reports_gaps(self):
        from scripts import keirin_mac_cycle as cycle

        with patch.object(cycle.market, 'evaluate_retained', return_value={}):
            for offset in (0, 15, 46):
                cycle.run_cycle(self.root, clock=lambda: NOW + timedelta(minutes=offset))
        audit = cycle.audit_window(self.root, NOW, clock=lambda: NOW + timedelta(minutes=47))
        self.assertEqual(audit['completed_ticks'], 3)
        self.assertEqual(audit['longest_interval_seconds'], 31*60)
        self.assertEqual(audit['intervals_over_16_minutes'], 1)
        self.assertFalse(audit['full_24h_local_cadence'])
        self.assertEqual(audit['scope'], 'LOCAL_KEIRIN_RESEARCH')

    def test_cycle_audit_excludes_active_work_from_idle_gaps(self):
        from scripts import keirin_mac_cycle as cycle

        later = NOW + timedelta(seconds=990)
        with patch.object(cycle.market, 'evaluate_retained', return_value={}), \
                patch.object(cycle, 'monotonic', side_effect=[0, 90, 990, 992]):
            cycle.run_cycle(self.root, clock=lambda: NOW)
            cycle.run_cycle(self.root, clock=lambda: later)
        audit = cycle.audit_window(self.root, NOW, clock=lambda: later+timedelta(seconds=10))
        self.assertEqual(audit['longest_interval_seconds'], 990)
        self.assertEqual(audit['longest_idle_seconds'], 900)
        self.assertEqual(audit['idle_intervals_over_16_minutes'], 0)

    def test_tracking_requires_the_exact_verified_race_and_media(self):
        from scripts import keirin_mac_cycle as cycle
        from scripts import keirin_video_tracking as tracking

        digest = 'a'*64
        race = '20261125-84-01'
        roster = self.write('census.jsonl', dict(race_id=race, race_date='2026-11-25', roster_complete=True,
            event_status='finish_verified', riders=[dict(car=1, rider_id='015001'), dict(car=2, rider_id='015002')]))
        request = self.root/'track-clip.json'
        request.write_text(json.dumps(dict(race_id=race, media_sha256=digest)))
        request.chmod(0o600)
        options = dict(census=roster, track_request=request)
        with patch.object(tracking, '_track_clip', return_value=dict(tracks=[{}])) as track:
            missing = self.run_cycle(**options)
            self.assertEqual(missing['video']['tracking']['state'], 'WAITING_FOR_VERIFIED_TRACKING_MEDIA')
            track.assert_not_called()
            clip = self.root/'movie.mp4'
            clip.touch()
            manifest = self.write('owner-films.jsonl', dict(race_id=race, race_date='2026-11-25',
                kind='clip', source_ref='fixture', path=clip.name, sha256=digest))
            options['manifest'] = manifest
            with patch.object(cycle.media, 'inspect', return_value=('verified', dict(duration_ms=2000))):
                first = self.run_cycle(**options)
                again = self.run_cycle(**options)
                saved_receipt, = self.root.glob('tracks-*/receipt.json')
                cached = json.loads(saved_receipt.read_bytes())
                cached['unexpected_private_value'] = 'not an aggregate field'
                saved_receipt.write_text(json.dumps(cached))
                tampered = self.run_cycle(**options)
        track.assert_called_once_with(clip, digest, race, [1, 2])
        self.assertEqual(first['video']['tracking']['state'], 'TRACKS_GENERATED')
        self.assertEqual(again['video']['tracking']['state'], 'TRACKS_REUSED')
        self.assertEqual(first['video']['tracking']['tracks_sha256'], again['video']['tracking']['tracks_sha256'])
        self.assertEqual(first['video']['observation_count'], 0)
        self.assertEqual(tampered['video']['tracking']['state'], 'HOLD_TRACKING_INPUT_OR_RUNTIME')
        self.assertNotIn('unexpected_private_value', json.dumps(tampered))

    def test_verified_frames_and_registered_reviews_fit_once(self):
        from scripts import keirin_mac_cycle as cycle

        roster = self.write('census.jsonl', dict(race_id=RACE, race_date='2026-11-25', roster_complete=True,
            event_status='finish_verified', riders=[dict(car=1, rider_id='015001'), dict(car=2, rider_id='015002')]))
        frames = []
        for seconds, colour in [(400, 'red'), (800, 'cyan')]:
            frame = self.root / f'{seconds}.png'
            Image.new('RGB', (64, 48), colour).save(frame)
            frames.append(dict(path=frame.name, at_ms=seconds, sha256=sha256(frame.read_bytes()).hexdigest()))
        films = self.write('owner-films.jsonl', dict(race_id=RACE, race_date='2026-11-25',
                           kind='frames', source_ref='fixture frames', frames=frames))
        review = self.write('reviewed.jsonl', dict(race_id=RACE, race_date='2026-11-25', car=1,
            rider_id='015001', task='follow', value='held', scope='B4C', window_level='clip',
            target_car=2, target_rider_id='015002', start_ms=400, end_ms=800,
            reviewer='fixture reviewer', source_ref='fixture frames', note='visible turn',
            evidence_frames=[{key: frame[key] for key in ('at_ms', 'sha256')} for frame in frames]))
        options = dict(census=roster, manifest=films, reviewed=review)
        with patch.object(cycle.learning, 'study', wraps=cycle.learning.study) as fit:
            first = self.run_cycle(**options)
            again = self.run_cycle(**options)
        self.assertEqual(fit.call_count, 1)
        self.assertEqual(first['video']['observation_count'], 1)
        self.assertEqual(first['video']['model_state'], 'TRIAL_PROFILE_FITTED')
        self.assertEqual(again['video']['model_state'], 'TRIAL_PROFILE_REUSED')
        self.assertEqual(first['video']['trial_sha256'], again['video']['trial_sha256'])
        self.assertNotIn('015001', json.dumps(first))
        self.assertNotIn('fixture frames', json.dumps(first))

        for frame in frames:
            (self.root/frame['path']).unlink()
        with patch.object(cycle.learning, 'study', side_effect=AssertionError('learned without verified media')):
            missing = self.run_cycle(**options)
        self.assertEqual(missing['video']['inventory']['unavailable'], 2)
        self.assertEqual(missing['video']['observation_count'], 0)
        self.assertEqual(missing['video']['model_state'], 'WAITING_FOR_REVIEWED_OBSERVATIONS')
        self.assertEqual(missing['video']['unverified_review_inputs'], 1)
        self.assertEqual(missing['video']['media_races'], 0)

    def test_access_refusal_from_prior_tick_does_not_start_a_browser(self):
        from scripts import keirin_mac_cycle as cycle

        digests = self.root/'digests'
        digests.mkdir(mode=0o700)
        attempts = digests/'attempts.jsonl'
        attempts.write_text('{"status":"source HTTP 403"}\n')
        attempts.chmod(0o600)
        roster = self.write('census.jsonl', dict(race_id=RACE, race_date='2026-11-25', roster_complete=False,
            event_status='finish_verified', riders=[]))
        with patch.object(cycle.sources, 'run', side_effect=AssertionError('attempted provider access')):
            result = self.run_cycle(census=roster, source_approval=Path('/test/permission.json'))
        self.assertEqual(result['video']['capture_state'], 'HOLD_PROVIDER_REFUSAL')
        self.assertEqual(result['video']['model_state'], 'WAITING_FOR_REVIEWED_OBSERVATIONS')

    def test_symlinked_media_database_does_not_touch_its_target(self):
        with TemporaryDirectory() as other:
            target = Path(other)/'untouched.sqlite'
            (self.root/'media.sqlite').symlink_to(target)
            roster = self.write('census.jsonl', dict(race_id=RACE, race_date='2026-11-25',
                                event_status='finish_verified', riders=[]))
            manifest = self.write('owner-films.jsonl')
            result = self.run_cycle(census=roster, manifest=manifest)
            self.assertEqual(result['video']['state'], 'HOLD_VIDEO_INPUT_OR_RUNTIME')
            self.assertFalse(target.exists())

    def test_low_disk_holds_video_work_and_continues_the_retained_comparison(self):
        result = self.run_cycle(census=self.write('census.jsonl'), free_gib=39)
        self.assertEqual(result['video']['state'], 'HOLD_VIDEO_STORAGE')
        self.assertEqual(result['market_third']['candidate_disposition'], 'HOLD_INDEPENDENT_MARKET_EVALUATION')
        self.assertFalse((self.root/'corpus.sqlite').exists())
