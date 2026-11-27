"""Exercise scheduled video intake, evaluation and safe holds without provider access."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from itertools import permutations
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

from PIL import Image
from tests.test_keirin_official_public_source import fixtures
from tests.test_keirin_video_sources import KOMATSUSHIMA, KOMATSUSHIMA_TITLE


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

    def run_cycle(self, *, free_gib=100, now=NOW, **inputs):
        from scripts import keirin_mac_cycle as cycle

        with patch.object(cycle.market, 'evaluate_retained', return_value={
                'candidate_disposition': 'HOLD_INDEPENDENT_MARKET_EVALUATION'}), \
                patch.object(cycle.shutil, 'disk_usage', return_value=SimpleNamespace(free=free_gib*cycle.GIB)):
            return cycle.run_cycle(self.root, clock=lambda: now, **inputs)

    def komatsushima_inputs(self):
        from race_ai import keirin_official_public_source as official
        from scripts import keirin_mac_shadow_result as shadow
        from scripts.keirin_official_day_pipeline import private_snapshot_json

        def file(name, doc):
            path = self.write(name, doc)
            path.chmod(0o600)
            return path

        prior = datetime(2026, 11, 25, 23, 35, tzinfo=timezone.utc)
        raw = fixtures()
        registry = raw['JSJ057']
        registry['reqprm']['kday'] = '20261126'
        registry['kInfo'][0].update(jyoName='小松島', KeirinCd='73', bKeirinCd='73')
        venue = raw['JSJ017']
        venue.update(keirinCd='73', kaisaihi='20261126', lastUpdateTime='2026/11/26 07:00&nbsp;更新',
                     reqprm={'kday': '20261126', 'bkcd': '73'})
        venue['rInfo'][0].update(denTime='08:47', stTime='08:50')
        schedule = official.fetch_day_schedule('2026-11-26', clock=lambda: prior,
            fetcher=lambda url: json.dumps(raw[parse_qs(urlsplit(url).query)['type'][0]]).encode())
        race = schedule['races'][0]
        schedule_path = file('official-schedule.json', private_snapshot_json(schedule))
        schedule_sha = sha256(schedule_path.read_bytes()).hexdigest()
        original_cutoff = datetime(2026, 11, 25, 23, 45, tzinfo=timezone.utc).isoformat()
        tickets = [[list(key), 1/210] for key in permutations(range(1, 8), 3)]
        original = file('original.json', dict(schema='KEIRIN_MAC_PROSPECTIVE_SHADOW_V1',
            scope='PROSPECTIVE_RESEARCH', race_id=race['race_id'], generated_at=(prior+timedelta(minutes=5)).isoformat(),
            score_cutoff_at=original_cutoff, official_cutoff_at=race['official_cutoff_at'],
            production_model_switched=False, selected_arm='trial',
            forecasts={variant: {'trifecta': tickets} for variant in ('saved', 'trial')},
            input=dict(official_schedule_sha256=schedule_sha, official_venue_source_sha256=race['source_sha256'],
                input=dict(race_id=race['race_id'], riders=[dict(car=row['car'], athlete_id=row['registration_id'])
                                                           for row in race['starters']]))))
        request = file('shadow-result.json', dict(original_path=str(original),
            original_sha256=sha256(original.read_bytes()).hexdigest(), schedule_path=str(schedule_path),
            schedule_sha256=schedule_sha))
        self.assertEqual(shadow.run(self.root, request, clock=lambda: prior+timedelta(minutes=6))['state'],
                         'WAITING_FOR_OFFICIAL_START')
        rights = self.root/'fixture-recording-permission'
        rights.write_bytes(b'fictional offline permission')
        rights.chmod(0o600)
        approval = file('komatsushima-replay-approval.json', dict(source_host='www.winticket.jp',
            rights_ref=rights.name, rights_sha256=sha256(rights.read_bytes()).hexdigest(),
            permission_basis='owner_attestation', reviewer='fixture reviewer',
            allowed_uses=['automated_fetch', 'private_retention', 'history_analysis', 'video_recording'],
            race_ids=[KOMATSUSHIMA['race_id']], race_detail_url=KOMATSUSHIMA['race_detail_url']))
        return request, approval

    def settled_shadow(self, now):
        from scripts import keirin_mac_shadow_result as shadow

        rid, day = '202611267301', '2026-11-26'
        source = 'https://keirin.kdreams.jp/komatsushima/racedetail/7320261126010001/'
        cutoff = '2026-11-26T08:45:00+09:00'
        at = (now-timedelta(seconds=10)).isoformat()
        roster = dict(schema='KEIRIN_PUBLIC_RESULT_ROSTER_V1', date=day,
                      generated_at='2026-11-26T08:40:00+09:00', forecast_asset_sha256='b'*64,
                      races=[dict(race_id=rid, date=day, venue='小松島', race_no=1,
                                  published_cutoff_at=cutoff, source_url=source,
                                  observed_riders=[{'number': n} for n in range(1, 8)])])
        comparison = dict(race_id=rid, observed_at=at, authority='cross_source_reference',
                          comparison_scope='POST_CUTOFF_REFERENCE', winning_3t=[1, 2, 3], winning_2t=[1, 2],
                          payouts_100yen={'2t': 300, '3t': 1230},
                          sources=[dict(source_id='kdreams', checked_at=at, url=source+'?pageType=result'),
                                   dict(source_id='netkeirin', checked_at=at,
                                        url='https://keirin.netkeiba.com/race/result/?race_id='+rid)])
        results = dict(schema='KEIRIN_PUBLISHED_RESULTS_V1', date=day, checked_at=at,
                       races=[dict(race_id=rid, state='matched', comparison=comparison)])
        ref = 'a'*40
        docs = {shadow.GITHUB_REF: {'object': {'sha': ref}}, f'contents/rosters/{day}.json?ref={ref}': roster,
                f'contents/results/{day}.json?ref={ref}': results}
        run = shadow.run
        return patch.object(shadow, 'run', side_effect=lambda root, request, *, clock:
                            run(root, request, clock=clock, public_fetcher=lambda path, **_: docs[path]))

    def test_scoped_replay_can_record_only_after_verified_settlement_and_uses_existing_media_ledger(self):
        from scripts import keirin_mac_cycle as cycle

        request, _ = self.komatsushima_inputs()
        api = MagicMock(Error=Exception, TimeoutError=TimeoutError)
        calls = []

        def simulate_capture(_browser, key, url, folder, *, approval):
            cycle.sources.require_capture_scope(approval, key, url, continuous=True)
            calls.append((key, url))
            source_ref = url+'#ordinary-screen-digest'
            (folder/'digest.mp4').write_bytes(b'fixture replay')
            (folder/'clip.json').write_text(json.dumps(dict(race_id=KOMATSUSHIMA['race_id'],
                race_date=KOMATSUSHIMA['race_date'], source_ref=source_ref, public_result_page=url,
                page_title=KOMATSUSHIMA_TITLE, kind='clip', start_ms=0, path='digest.mp4',
                browser_player_ended=True, observed_at_utc=NOW.isoformat(),
                sha256=sha256(b'fixture replay').hexdigest())))

        with (patch.dict('os.environ', {'RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED': 'false'}),
              patch.dict('sys.modules', {'playwright.sync_api': api}),
              patch.object(cycle.sources, 'record_digest', side_effect=simulate_capture),
              patch.object(cycle.media, 'inspect', return_value=('verified', dict(duration_ms=2000)))):
            before = datetime(2026, 11, 25, 23, 49, tzinfo=timezone.utc)
            pending = self.run_cycle(shadow_request=request, now=before)
            self.assertEqual(calls, [])
            self.assertEqual(pending.get('shadow_replay', {}).get('state'), 'WAITING_FOR_SHADOW_SETTLEMENT')
            with self.settled_shadow(NOW):
                first = self.run_cycle(shadow_request=request)
                later = self.run_cycle(shadow_request=request, now=NOW+timedelta(minutes=15))
        self.assertEqual(first['shadow_replay']['state'], 'REPLAY_RECORDED_AWAITING_MEDIA_VERIFICATION')
        self.assertEqual(later['shadow_replay']['state'], 'REPLAY_MEDIA_VERIFIED')
        self.assertEqual(later['shadow_replay']['tracking_state'], 'HOLD_REPLAY_LAYOUT_CALIBRATION')
        self.assertEqual(later['video']['media_races'], 1)
        self.assertEqual(later['video']['observation_count'], 0)
        self.assertEqual(calls, [('202611267301', KOMATSUSHIMA['race_detail_url'])])

    def test_layout_hold_does_not_reuse_the_takeo_tracker(self):
        from scripts import keirin_mac_cycle as cycle
        from scripts import keirin_video_tracking as tracking

        roster = self.write('census.jsonl')
        request = self.write('tracks.json', dict(race_id='20261126-73-01', media_sha256='a'*64))
        with patch.object(tracking, '_track_clip', side_effect=AssertionError('Takeo layout reused')):
            result = self.run_cycle(census=roster, track_request=request)
        self.assertEqual(result['video']['tracking']['state'], 'HOLD_REPLAY_LAYOUT_CALIBRATION')

    def test_general_capture_does_not_pick_up_komatsushima_from_a_broad_census(self):
        from scripts import keirin_mac_cycle as cycle

        roster = self.write('census.jsonl', dict(KOMATSUSHIMA, event_status='finish_verified', riders=[]))
        with patch.object(cycle.sources, 'run', side_effect=AssertionError('general queue opened exact replay')):
            result = self.run_cycle(census=roster, source_approval=Path('/fixture/general.json'))
        self.assertEqual(result['video']['capture_state'], 'NO_ELIGIBLE_REPLAY')

    def test_exact_replay_retries_publication_wait_with_a_bounded_interval(self):
        from collections import Counter
        from scripts import keirin_mac_cycle as cycle

        request, _ = self.komatsushima_inputs()
        now = NOW
        calls = []

        def unpublished(queue, out, **options):
            row = json.loads(queue.read_text())
            self.assertEqual(row, KOMATSUSHIMA)
            self.assertEqual(options['settled_replay_url'], KOMATSUSHIMA['race_detail_url'])
            self.assertTrue(options['stop_after_refusal'])
            calls.append(now)
            out.mkdir(mode=0o700, exist_ok=True)
            status = 'race digest button unavailable'
            with open(out/'attempts.jsonl', 'a', opener=cycle.sources.private_log_fd) as history:
                history.write(json.dumps(dict(race_id=row['race_id'], source_ref=row['race_detail_url'],
                                              status=status, at_utc=now.isoformat()))+'\n')
            return Counter({status: 1})

        with (patch.dict('os.environ', {'RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED': 'false'}),
              self.settled_shadow(NOW), patch.object(cycle.sources, 'run', side_effect=unpublished)):
            for offset, expected in [(0, 'WAITING_FOR_REPLAY_PUBLICATION'),
                                     (15, 'WAITING_FOR_REPLAY_RETRY_INTERVAL'),
                                     (30, 'WAITING_FOR_REPLAY_PUBLICATION'),
                                     (60, 'WAITING_FOR_REPLAY_PUBLICATION'),
                                     (90, 'HOLD_REPLAY_ATTEMPT_LIMIT')]:
                now = NOW+timedelta(minutes=offset)
                result = self.run_cycle(shadow_request=request, now=now)
                self.assertEqual(result.get('shadow_replay', {}).get('state'), expected)
        self.assertEqual(calls, [NOW+timedelta(minutes=offset) for offset in (0, 30, 60)])

    def test_shared_provider_refusal_blocks_exact_replay(self):
        from scripts import keirin_mac_cycle as cycle

        request, _ = self.komatsushima_inputs()
        digests = self.root/'digests'
        digests.mkdir(mode=0o700)
        log = digests/'attempts.jsonl'
        log.write_text('{"status":"source HTTP 403"}\n')
        log.chmod(0o600)
        with (patch.dict('os.environ', {'RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED': 'false'}),
              self.settled_shadow(NOW),
              patch.object(cycle.sources, 'run', side_effect=AssertionError('capture after refusal'))):
            result = self.run_cycle(shadow_request=request)
        self.assertEqual(result.get('shadow_replay', {}).get('state'), 'HOLD_PROVIDER_REFUSAL')

    def test_frame_approval_survives_recording_expiry_and_keeps_the_prior_attempt(self):
        from collections import Counter
        from scripts import keirin_mac_cycle as cycle

        request, approval = self.komatsushima_inputs()
        checks = []
        now = NOW
        recording = json.loads(approval.read_bytes())
        recording['valid_until'] = (NOW + timedelta(minutes=10)).isoformat()
        approval.write_text(json.dumps(recording))

        class ReplayDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now.astimezone(tz)

        def capture(queue, out, **options):
            row = json.loads(queue.read_text())
            checks.append(options['continuous'])
            out.mkdir(mode=0o700, exist_ok=True)
            status = cycle.sources.AMBIGUOUS_PLAYER if options['continuous'] else 'captured'
            if status == 'captured':
                folder = out/'202611267301'
                folder.mkdir(mode=0o700)
                scope = cycle.sources.load_source_approval(options['source_approval'], False)
                frames = []
                for seconds in (.2, 1.8):
                    body = str(seconds).encode()
                    (folder/f't{round(seconds*100):05d}.png').write_bytes(body)
                    frames.append(dict(video_seconds=seconds, frame_sha256=sha256(body).hexdigest()))
                (folder/'overview.json').write_text(json.dumps(dict(public_result_page=row['race_detail_url'],
                    page_title=KOMATSUSHIMA_TITLE, capture_mode=cycle.sources.REPLAY_FRAME_MODE,
                    browser_player_seconds=2, frame_interval_seconds=4, observed_at_utc=now.isoformat(),
                    frames=frames)))
                (folder/'source-approval.json').write_text(json.dumps(dict(race_id=row['race_id'],
                    source_ref=row['race_detail_url'], capture_mode=cycle.sources.REPLAY_FRAME_MODE,
                    decision_sha256=scope.decision_sha256, rights_sha256=scope.rights_sha256,
                    permission_basis=scope.permission_basis)))
                for path in folder.iterdir():
                    path.chmod(0o600)
            with open(out/'attempts.jsonl', 'a', opener=cycle.sources.private_log_fd) as history:
                history.write(json.dumps(dict(race_id=row['race_id'], source_ref=row['race_detail_url'],
                                              status=status, at_utc=now.isoformat()))+'\n')
            return Counter({status: 1})

        with (patch.dict('os.environ', {'RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED': 'false'}),
              self.settled_shadow(NOW), patch.object(cycle.sources, 'run', side_effect=capture),
              patch.object(cycle.media, 'inspect', return_value=('verified', {})),
              patch.object(cycle.sources, 'datetime', ReplayDateTime)):
            first = self.run_cycle(shadow_request=request, now=now)
            self.assertEqual(first['shadow_replay']['state'], 'HOLD_REPLAY_SOURCE_UNVERIFIED')
            decision = json.loads(approval.read_bytes())
            decision['allowed_uses'].remove('video_recording')
            decision['allowed_uses'].append('frame_capture')
            del decision['valid_until']
            self.write('komatsushima-frame-analysis-approval.json', decision).chmod(0o600)
            now = NOW+timedelta(minutes=15)
            waiting = self.run_cycle(shadow_request=request, now=now)
            self.assertEqual(waiting['shadow_replay']['state'], 'WAITING_FOR_REPLAY_RETRY_INTERVAL')
            now = NOW+timedelta(minutes=30)
            stills = self.run_cycle(shadow_request=request, now=now)
            self.assertEqual(stills['shadow_replay']['state'], 'REPLAY_FRAMES_AWAITING_MEDIA_VERIFICATION')
            now = NOW+timedelta(minutes=45)
            verified = self.run_cycle(shadow_request=request, now=now)
        self.assertEqual(verified['shadow_replay']['state'], 'REPLAY_FRAMES_VERIFIED')
        self.assertEqual(verified['video']['observation_count'], 0)
        self.assertFalse((self.root/'digests/202611267301/digest.mp4').exists())
        self.assertEqual(checks, [True, False])

    def test_permission_changed_after_pin_holds_before_the_browser(self):
        from scripts import keirin_mac_cycle as cycle

        request, approval = self.komatsushima_inputs()
        run_capture = cycle.sources.run
        api = MagicMock(Error=Exception, TimeoutError=TimeoutError)

        def change_decision(queue, out, **options):
            decision = json.loads(approval.read_bytes())
            decision['reviewer'] = 'replacement fixture reviewer'
            approval.write_text(json.dumps(decision))
            return run_capture(queue, out, **options)

        with (patch.dict('os.environ', {'RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED': 'false'}),
              self.settled_shadow(NOW), patch.dict('sys.modules', {'playwright.sync_api': api}),
              patch.object(cycle.sources, 'run', side_effect=change_decision),
              patch.object(cycle.sources, 'record_digest') as recorder):
            result = self.run_cycle(shadow_request=request)
        recorder.assert_not_called()
        self.assertEqual(result.get('shadow_replay', {}).get('state'), 'HOLD_REPLAY_EVIDENCE_OR_RUNTIME')

    def test_one_forward_playback_slot_after_the_older_frame_seek_failed(self):
        from collections import Counter
        from scripts import keirin_mac_cycle as cycle

        request, approval = self.komatsushima_inputs()
        calls = []
        now = NOW
        outcomes = [cycle.sources.DIGEST_BUTTON_UNAVAILABLE, cycle.sources.AMBIGUOUS_PLAYER,
                    cycle.sources.PLAYER_SEEK_UNAVAILABLE, cycle.sources.REPLAY_FRAME_UNOBSERVED,
                    cycle.sources.REPLAY_FRAME_UNOBSERVED]

        def capture(queue, out, **options):
            row = json.loads(queue.read_text())
            status = outcomes[len(calls)]
            calls.append((now, options['continuous']))
            out.mkdir(mode=0o700, exist_ok=True)
            attempt = dict(race_id=row['race_id'], source_ref=row['race_detail_url'],
                           status=status, at_utc=now.isoformat())
            if not options['continuous']:
                attempt['capture_mode'] = cycle.sources.REPLAY_FRAME_MODE
                if len(calls) == 4:
                    attempt['sampling'] = cycle.sources.FORWARD_REPLAY_SAMPLING
                if len(calls) == 5:
                    attempt['sampling'] = cycle.sources.PASSIVE_REPLAY_SAMPLING
            with open(out/'attempts.jsonl', 'a', opener=cycle.sources.private_log_fd) as history:
                history.write(json.dumps(attempt)+'\n')
            return Counter({status: 1})

        with (patch.dict('os.environ', {'RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED': 'false'}),
              self.settled_shadow(NOW), patch.object(cycle.sources, 'run', side_effect=capture)):
            for offset in (0, 30):
                now = NOW+timedelta(minutes=offset)
                self.run_cycle(shadow_request=request, now=now)
            decision = json.loads(approval.read_bytes())
            decision['allowed_uses'] = ['automated_fetch', 'private_retention', 'history_analysis', 'frame_capture']
            self.write('komatsushima-frame-analysis-approval.json', decision).chmod(0o600)
            for offset, expected in ((60, 'HOLD_REPLAY_SOURCE_UNVERIFIED'),
                                     (75, 'WAITING_FOR_REPLAY_RETRY_INTERVAL'),
                                     (90, 'HOLD_REPLAY_SOURCE_UNVERIFIED'),
                                     (120, 'HOLD_REPLAY_SOURCE_UNVERIFIED')):
                now = NOW+timedelta(minutes=offset)
                result = self.run_cycle(shadow_request=request, now=now)
                self.assertEqual(result['shadow_replay']['state'], expected)
            admitted = self.root/'keirin-mac-shadow-results/202611267301/github-public/published-result.json'
            evidence = dict(race_id=KOMATSUSHIMA['race_id'], source_ref=KOMATSUSHIMA['race_detail_url'],
                            settlement_sha256=sha256(admitted.read_bytes()).hexdigest(),
                            recorded_at=now.isoformat(), media_saved=False, presented_frames=9,
                            distinct_sampled_frames=2)
            self.write('komatsushima-passive-inspection-proof.json', evidence).chmod(0o600)
            for offset, expected in ((135, 'HOLD_REPLAY_SOURCE_UNVERIFIED'),
                                     (165, 'HOLD_REPLAY_ATTEMPT_LIMIT')):
                now = NOW+timedelta(minutes=offset)
                result = self.run_cycle(shadow_request=request, now=now)
                self.assertEqual(result['shadow_replay']['state'], expected)
        self.assertEqual(calls, [(NOW+timedelta(minutes=offset), mode)
                                 for offset, mode in ((0, True), (30, True), (60, False), (90, False),
                                                      (135, False))])

    def test_published_calendar_retains_future_cancelled_and_verified_result_candidates(self):
        from scripts import keirin_mac_replay_calendar as calendar

        urls = {
            '202611267301': 'https://keirin.kdreams.jp/komatsushima/racedetail/7320261126010001/',
            '202611267302': 'https://keirin.kdreams.jp/komatsushima/racedetail/7320261126010002/',
        }
        past, today = '2026-11-26', '2026-11-27'
        checked = '2026-11-27T10:00:00+09:00'
        cutoff = '2026-11-26T08:45:00+09:00'
        roster = dict(schema='KEIRIN_PUBLIC_RESULT_ROSTER_V1', date=past,
            generated_at='2026-11-26T08:40:00+09:00', forecast_asset_sha256='b'*64,
            races=[dict(race_id=key,date=past,venue='小松島',race_no=int(key[-2:]),
                        published_cutoff_at=cutoff,source_url=url,
                        observed_riders=[{'number': car} for car in range(1, 8)])
                   for key,url in urls.items()])
        comparison = dict(race_id='202611267301', observed_at=checked, authority='cross_source_reference',
            comparison_scope='POST_CUTOFF_REFERENCE', winning_3t=[1,2,3], winning_2t=[1,2],
            payouts_100yen={'2t':300,'3t':1230},
            sources=[dict(source_id='kdreams', checked_at=checked, url=urls['202611267301']+'?pageType=result'),
                     dict(source_id='netkeirin', checked_at=checked,
                          url='https://keirin.netkeiba.com/race/result/?race_id=202611267301')])
        results = dict(schema='KEIRIN_PUBLISHED_RESULTS_V1', date=past, checked_at=checked,
            races=[dict(race_id='202611267301',state='matched',comparison=comparison),
                   dict(race_id='202611267302',state='held',reason='SPECIAL_CANCELLED_REFUND_CONFIRMED')])
        forecast = dict(schema='RACE_AI_KEIRIN_PUBLIC_FORECASTS_V1', day=today,
            races=[dict(race_id='202611277301', cutoff_at='2026-11-27T20:00:00+09:00', status='pending')])
        now=datetime(2026,11,27,10,tzinfo=timezone.utc)
        rows=calendar.combine(today, forecast, None, None, now)
        rows+=calendar.combine(past, None, roster, results, now)
        self.assertEqual({row['race_id']:row['state'] for row in rows}, {
            '20261127-73-01':'scheduled','20261126-73-01':'ended_cross_source','20261126-73-02':'cancelled'})
        self.assertTrue(all('a' not in row and 'comparison' not in row for row in rows))
        self.assertEqual(rows[1]['result_observed_at'],checked)
        self.assertIsNone(rows[2]['result_observed_at'])
        results['races'][0]['comparison']['sources'][0]['checked_at']='2026-11-25T00:00:00+09:00'
        self.assertEqual(calendar.combine(past,None,roster,results,now)[0]['state'],'result_held')

    def test_calendar_capture_checks_scope_and_rotates_before_retrying(self):
        from collections import Counter
        from contextlib import closing
        import sqlite3
        from scripts import keirin_mac_cycle as cycle

        today=NOW+timedelta(days=1)
        queue=[
            dict(race_id='20261126-73-02',race_date='2026-11-26',
                 race_detail_url='https://keirin.kdreams.jp/komatsushima/racedetail/7320261126010002/'),
            dict(race_id='20261127-12-01',race_date='2026-11-27',
                 race_detail_url='https://keirin.kdreams.jp/aomori/racedetail/1220261127010001/'),
            dict(race_id='20261127-12-02',race_date='2026-11-27',
                 race_detail_url='https://keirin.kdreams.jp/aomori/racedetail/1220261127010002/'),
        ]
        rights=self.root/'rights'
        rights.write_bytes(b'fictional research approval')
        scope=self.write('approved.json', dict(source_host='keirin.kdreams.jp',rights_ref='rights',
            rights_sha256=sha256(rights.read_bytes()).hexdigest(),reviewer='fixture reviewer',
            allowed_uses=['automated_fetch','private_retention','history_analysis','video_recording'],
            race_ids=[row['race_id'] for row in queue[:2]]))
        attempts=[]
        now=today

        def capture(path, out, **options):
            row=json.loads(path.read_bytes())
            attempts.append((row['race_id'], options['retry_failed']))
            out.mkdir(mode=0o700,exist_ok=True)
            status=cycle.sources.DIGEST_BUTTON_UNAVAILABLE
            with open(out/'attempts.jsonl','a',opener=cycle.sources.private_log_fd) as log:
                log.write(json.dumps(dict(race_id=row['race_id'],source_ref=row['race_detail_url'],
                                        status=status,at_utc=now.isoformat()))+'\n')
            return Counter({status:1})

        with (closing(sqlite3.connect(':memory:')) as db,
              patch.object(cycle.sources,'run',side_effect=capture),
              patch.object(cycle.shutil,'disk_usage',return_value=SimpleNamespace(free=100*cycle.GIB))):
            cycle.corpus.setup(db)
            with db:
                cycle.corpus.load_race(db,dict(queue[0],riders=[],event_status='finish_verified'))
            self.assertEqual(cycle._capture(db,self.root,scope,None,now,calendar_rows=[queue[0]],
                                            calendar_cancelled={queue[0]['race_id']}),
                             ('NO_ELIGIBLE_REPLAY',0))
            with db:
                cycle.corpus.load_race(db,dict(queue[2],riders=[],event_status='cancelled_reported'))
            self.assertEqual(cycle._capture(db,self.root,scope,None,now,calendar_rows=[queue[2]],
                                            calendar_cancelled={queue[0]['race_id']}),
                             ('NO_ELIGIBLE_REPLAY',0))
            for minute in (0,15,30,45,60,75):
                now=today+timedelta(minutes=minute)
                self.assertEqual(cycle._capture(db,self.root,scope,None,now,calendar_rows=queue),
                                 ('NO_NEW_RECORDING',0))
            now=today+timedelta(minutes=90)
            self.assertEqual(cycle._capture(db,self.root,scope,None,now,calendar_rows=queue),
                             ('HOLD_CAPTURE_ATTEMPTS_OR_PLAYER',0))
        self.assertEqual(attempts,[('20261127-12-01',False),('20261126-73-02',False),
                                   ('20261127-12-01',True),('20261126-73-02',True),
                                   ('20261127-12-01',True),('20261126-73-02',True)])

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
                cached['broadcast_anchors'] = 1
                saved_receipt.write_text(json.dumps(cached))
                changed_count = self.run_cycle(**options)
                cached['unexpected_private_value'] = 'not an aggregate field'
                saved_receipt.write_text(json.dumps(cached))
                tampered = self.run_cycle(**options)
        self.assertEqual(changed_count['video']['tracking']['state'], 'HOLD_TRACKING_INPUT_OR_RUNTIME')
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
            again = self.run_cycle(now=NOW+timedelta(days=1), **options)
        self.assertEqual(fit.call_count, 1)
        self.assertEqual(first['video']['observation_count'], 1)
        self.assertEqual(first['video']['model_state'], 'TRIAL_PROFILE_FITTED')
        self.assertEqual(again['video']['model_state'], 'TRIAL_PROFILE_REUSED')
        self.assertEqual(first['video']['trial_sha256'], again['video']['trial_sha256'])
        dataset = first['video']['dataset_sha256']
        self.assertRegex(dataset, r'^[0-9a-f]{64}$')
        self.assertEqual(again['video']['dataset_sha256'], dataset)
        self.assertNotIn('015001', json.dumps(first))
        self.assertNotIn('fixture frames', json.dumps(first))

        engine_marker = self.root/'different-learner.py'
        engine_marker.write_text('# different installed learner')
        with (patch.object(cycle.learning, '__file__', str(engine_marker)),
              patch.object(cycle.learning, 'study', side_effect=AssertionError('refitted without new data'))):
            changed = self.run_cycle(**options)['video']
        self.assertEqual(changed['model_state'], 'HOLD_TRAINING_ENGINE_VERSION')
        self.assertEqual(changed['dataset_sha256'], dataset)
        self.assertIsNone(changed['trial_sha256'])

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
