"""Exercise scheduled video intake, evaluation and safe holds without provider access."""
from datetime import datetime, timezone
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
