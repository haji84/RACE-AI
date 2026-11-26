from hashlib import sha256
import json
import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, MagicMock, patch

from scripts import keirin_video_sources as source


RACE = {'race_id': '20240504-13-01', 'race_date': '2024-05-04',
        'race_detail_url': 'https://keirin.kdreams.jp/iwakitaira/racedetail/1320240430050001/?pageType=showResult'}
TITLE = 'いわき平競輪 レース詳細 | 日本選手権競輪 1R | 2024年05月04日【楽天Kドリームス】'
WINTICKET = {'race_id': '20240503-84-01', 'race_date': '2024-05-03',
             'race_detail_url': 'https://www.winticket.jp/keirin/takeo/raceresult/2024050184/3/1'}
WINTICKET_TITLE = '武雄競輪 開催名（2024年5月3日)1レース 結果【ウィンチケット競輪】'
KOMATSUSHIMA = {'race_id': '20261126-73-01', 'race_date': '2026-11-26',
                'race_detail_url': 'https://www.winticket.jp/keirin/komatsushima/raceresult/2026112673/1/1'}
KOMATSUSHIMA_TITLE = '小松島競輪 開催名（2026年11月26日)1レース 結果【ウィンチケット競輪】'


class CaptureTests(unittest.TestCase):
    def test_network_modes_refuse_before_browser_or_output_for_unapproved_scope(self):
        with TemporaryDirectory() as temp, patch.dict('sys.modules', {'playwright.sync_api': None}):
            root = Path(temp)
            queue = root / 'queue.jsonl'
            queue.write_text(json.dumps(RACE) + '\n')
            out = root / 'captures'
            decision = root / 'owner.json'
            evidence = root / 'reviewed-test-source'
            evidence.write_bytes(b'fictional offline fixture')
            grant = {'source_host': source.HOST, 'rights_ref': evidence.name,
                     'rights_sha256': sha256(evidence.read_bytes()).hexdigest(), 'reviewer': 'test reviewer',
                     'allowed_uses': ['automated_fetch', 'private_retention', 'history_analysis',
                                      'frame_capture', 'video_recording'],
                     'first_race_date': '2024-05-01', 'last_race_date': '2024-05-31'}
            args = dict(interval=3, pause=0, limit=None, executable='unavailable')
            for continuous in (False, True):
                with self.assertRaises(ValueError):
                    source.run(queue, out, continuous=continuous, **args)
                for change in ({'source_host': 'other.example'}, {'rights_ref': decision.name},
                               {'rights_sha256': '0' * 64}, {'reviewer': ''},
                               {'valid_until': '2020-01-01T00:00:00+00:00'},
                               {'allowed_uses': ['automated_fetch', 'private_retention', 'history_analysis']}):
                    decision.write_text(json.dumps({**grant, **change}))
                    with self.subTest(continuous=continuous, change=change), self.assertRaises(ValueError):
                        source.run(queue, out, continuous=continuous, source_approval=decision, **args)
                    self.assertFalse(out.exists())
                for change in ({'first_race_date': '2024-05-05'}, {'race_ids': ['20240504-13-02']}):
                    decision.write_text(json.dumps({**grant, **change}))
                    self.assertEqual(source.run(queue, out, continuous=continuous, source_approval=decision, **args),
                                     {'outside_approved_scope': 1})
                    self.assertFalse(out.exists())

    def test_only_approved_race_reaches_offline_recorder_and_binds_decision(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            queue = root / 'queue.jsonl'
            other = {**RACE, 'race_id': '20240504-13-02', 'race_detail_url':
                     RACE['race_detail_url'].replace('0001/', '0002/')}
            queue.write_text(json.dumps(other) + '\n' + json.dumps(RACE) + '\n')
            evidence = root / 'test-rights'
            evidence.write_bytes(b'synthetic rightsholder evidence')
            approval = root / 'review.json'
            approval.write_text(json.dumps({'source_host': source.HOST, 'rights_ref': evidence.name,
                'rights_sha256': sha256(evidence.read_bytes()).hexdigest(), 'reviewer': 'test reviewer',
                'allowed_uses': ['automated_fetch', 'private_retention', 'history_analysis', 'video_recording'],
                'race_ids': [RACE['race_id']]}))
            def fake_clip(browser, key, url, folder, *, approval):
                source.require_capture_scope(approval, key, url, continuous=True)
                (folder / 'digest.mp4').write_bytes(b'offline fixture')
                (folder / 'clip.json').write_text(json.dumps({'public_result_page': url, 'page_title': TITLE,
                    'kind': 'clip', 'path': 'digest.mp4', 'sha256': sha256(b'offline fixture').hexdigest()}))

            api = MagicMock(Error=Exception, TimeoutError=TimeoutError)
            with patch.dict('sys.modules', {'playwright.sync_api': api}), \
                 patch.object(source, 'record_digest', side_effect=fake_clip) as recorder:
                tally = source.run(queue, root / 'captures', continuous=True, source_approval=approval,
                                   interval=3, pause=0, limit=None, executable='unused')
            self.assertEqual(tally, {'captured': 1, 'outside_approved_scope': 1})
            self.assertEqual(recorder.call_count, 1)
            proof = json.loads((root / 'captures' / '202405041301' / 'source-approval.json').read_text())
            self.assertEqual(proof['race_id'], RACE['race_id'])
            self.assertEqual(proof['decision_sha256'], sha256(approval.read_bytes()).hexdigest())

    def test_listing_binds_track_and_race_with_cross_month_meeting(self):
        self.assertEqual(source.target(RACE)[0], '202405041301')
        bare = dict(RACE, race_detail_url=RACE['race_detail_url'].split('?')[0])
        self.assertEqual(source.target(bare), source.target(RACE))
        for row in (dict(RACE, race_id='20240504-13-10'),
                    dict(RACE, race_date='2024-04-30'),
                    dict(RACE, race_detail_url=RACE['race_detail_url'].replace('keirin.', 'else.')),
                    dict(RACE, race_detail_url=RACE['race_detail_url'] + '&race=9')):
            with self.assertRaises(ValueError):
                source.target(row)

    def test_title_must_confirm_real_day_and_race_including_old_yenjoy_receipts(self):
        key, _ = source.target(RACE)
        source.check_title(key, TITLE)
        source.check_title(key, '最終日（2024年5月4日） 1レース | 競輪')
        for title in (TITLE.replace(' 1R ', ' 11R '), TITLE.replace('05月04日', '04月30日')):
            with self.assertRaises(source.PlayerUnavailable):
                source.check_title(key, title)

    def test_winticket_result_url_binds_meeting_day_venue_and_race(self):
        url = WINTICKET['race_detail_url']
        self.assertEqual(source.target(WINTICKET), ('202405038401', url))
        for changed in (url.replace('takeo', 'kokura'), url.replace('0184', '0181'),
                        url.replace('/3/1', '/2/1'), url.replace('/3/1', '/3/11'),
                        url + '?extra=1', url + '#login', url.replace('https:', 'http:')):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                source.target(dict(WINTICKET, race_detail_url=changed))

    def test_winticket_title_also_confirms_venue(self):
        key, url = '202405038401', WINTICKET['race_detail_url']
        source.check_title(key, WINTICKET_TITLE, url=url)
        for changed in (WINTICKET_TITLE.replace('武雄', '小倉'),
                        WINTICKET_TITLE.replace('5月3日', '5月2日'),
                        WINTICKET_TITLE.replace('1レース', '11レース')):
            with self.subTest(changed=changed), self.assertRaises(source.PlayerUnavailable):
                source.check_title(key, changed, url=url)

    def test_only_the_exact_komatsushima_winticket_route_is_recognized(self):
        key, url = '202611267301', KOMATSUSHIMA['race_detail_url']
        self.assertEqual(source.target(KOMATSUSHIMA), (key, url))
        source.check_title(key, KOMATSUSHIMA_TITLE, url=url)
        for row in (dict(KOMATSUSHIMA, race_id='20261126-73-02', race_detail_url=url[:-1]+'2'),
                    dict(KOMATSUSHIMA, race_detail_url=url.replace('/komatsushima/', '/takeo/')),
                    dict(KOMATSUSHIMA, race_detail_url=url + '?other=1')):
            with self.assertRaises(ValueError):
                source.target(row)
        with self.assertRaises(source.PlayerUnavailable):
            source.check_title(key, KOMATSUSHIMA_TITLE.replace('小松島', '武雄'), url=url)

    def test_generic_queue_cannot_open_komatsushima_player_even_with_the_exact_permission(self):
        with TemporaryDirectory() as temp, patch.dict('sys.modules', {'playwright.sync_api': None}):
            root = Path(temp)
            queue = root / 'queue.jsonl'
            queue.write_text(json.dumps(KOMATSUSHIMA) + '\n')
            rights = root / 'fictional-rights'
            rights.write_bytes(b'fictional operator attestation')
            approval = root / 'approval.json'
            approval.write_text(json.dumps({'source_host': source.WINTICKET_HOST, 'rights_ref': rights.name,
                'rights_sha256': sha256(rights.read_bytes()).hexdigest(), 'reviewer': 'fixture reviewer',
                'permission_basis': 'owner_attestation', 'race_ids': [KOMATSUSHIMA['race_id']],
                'race_detail_url': KOMATSUSHIMA['race_detail_url'],
                'allowed_uses': ['automated_fetch', 'private_retention', 'history_analysis', 'video_recording']}))
            out = root / 'captures'
            result = source.run(queue, out, continuous=True, source_approval=approval,
                                interval=3, pause=0, limit=1, executable='unused', retry_failed=True)
            self.assertEqual(result, {'outside_settled_replay_scope': 1})
            self.assertFalse(out.exists())

    def test_komatsushima_media_denial_takes_priority_over_the_player_timeout(self):
        key, url = '202611267301', KOMATSUSHIMA['race_detail_url']
        page = Mock(url=url)
        page.goto.return_value.status = 200
        page.title.return_value = KOMATSUSHIMA_TITLE
        page.locator.return_value.count.return_value = 0
        control = page.get_by_role.return_value
        control.count.return_value = 1
        control.is_visible.return_value = True

        def unavailable(*_, **__):
            for event, callback in (call.args for call in page.on.call_args_list):
                if event == 'response':
                    callback(Mock(status=403, request=Mock(resource_type='media')))
            raise TimeoutError('fixture replay not loading')

        page.wait_for_function.side_effect = unavailable
        with self.assertRaisesRegex(source.AccessDenied, 'source HTTP 403'):
            source.open_player(page, key, url)

    def test_komatsushima_selects_the_new_replay_dialog_over_the_live_slot(self):
        key, url = '202611267301', KOMATSUSHIMA['race_detail_url']
        page = Mock(url=url)
        page.goto.return_value.status = 200
        page.title.return_value = KOMATSUSHIMA_TITLE
        page.get_by_role.return_value.count.return_value = 1
        page.get_by_role.return_value.is_visible.return_value = True
        dialog = page.locator.return_value
        dialog.count.side_effect = [0, 1]
        video = dialog.locator.return_value
        video.count.return_value = 1
        video.evaluate.return_value = False
        self.assertIs(source.open_player(page, key, url)[0], video)
        dialog.locator.assert_called_once_with('video:visible')
        page.locator.assert_called_once_with('[role="dialog"][aria-modal="true"]:visible')

    def test_komatsushima_denial_during_final_player_binding_beats_timeout(self):
        key, url = source.target(KOMATSUSHIMA)
        page = Mock(url=url)
        page.goto.return_value.status = 200
        page.title.return_value = KOMATSUSHIMA_TITLE
        page.get_by_role.return_value.count.return_value = 1
        page.get_by_role.return_value.is_visible.return_value = True
        dialog = page.locator.return_value
        dialog.count.side_effect = [0, 1]

        def unable_to_bind():
            for event, callback in (call.args for call in page.on.call_args_list):
                if event == 'response':
                    callback(Mock(status=403, request=Mock(resource_type='media')))
            raise TimeoutError('player binding timed out')

        dialog.locator.return_value.count.side_effect = unable_to_bind
        with self.assertRaisesRegex(source.AccessDenied, 'source HTTP 403'):
            source.open_player(page, key, url)

    def test_winticket_still_frames_require_a_separate_exact_approval(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            evidence = root / 'evidence'
            evidence.write_bytes(b'fixture frame analysis scope')
            approved = dict(source_host=source.WINTICKET_HOST, rights_ref=evidence.name,
                rights_sha256=sha256(evidence.read_bytes()).hexdigest(), reviewer='test reviewer',
                permission_basis='owner_attestation', race_ids=[KOMATSUSHIMA['race_id']],
                race_detail_url=KOMATSUSHIMA['race_detail_url'],
                allowed_uses=['automated_fetch', 'private_retention', 'history_analysis', 'frame_capture'])
            approval = root / 'approval.json'
            approval.write_text(json.dumps(approved))
            key, url = source.target(KOMATSUSHIMA)
            scope = source.load_source_approval(approval, False)
            source.require_capture_scope(scope, key, url, continuous=False)
            with self.assertRaises(ValueError):
                source.load_source_approval(approval, True)
            with self.assertRaises(ValueError):
                source.require_capture_scope(scope, *source.target(WINTICKET), continuous=False)

    def test_winticket_still_timeout_preserves_a_refusal_reported_during_the_read(self):
        key, url = source.target(KOMATSUSHIMA)
        approved = source.SourceApproval('a'*64, 'b'*64, None, None,
            frozenset({KOMATSUSHIMA['race_id']}), None, False, source.WINTICKET_HOST,
            'owner_attestation', url)
        locator = Mock()
        video = locator.element_handle.return_value
        video.evaluate.side_effect = [8.0, .2, False]
        refusals = []

        def fail_read(**_):
            refusals.append(403)
            raise TimeoutError('browser read timed out')

        video.screenshot.side_effect = fail_read
        with (TemporaryDirectory() as folder,
              patch.object(source, 'open_player', return_value=(locator, KOMATSUSHIMA_TITLE, refusals))):
            with self.assertRaisesRegex(source.AccessDenied, 'source HTTP 403'):
                source.capture(Mock(url=url), key, url, Path(folder), 4, approval=approved)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_winticket_stills_reject_an_incomplete_or_repeated_presentation(self):
        key, url = source.target(KOMATSUSHIMA)
        with TemporaryDirectory() as temp:
            folder = Path(temp)
            receipt = dict(public_result_page=url, page_title=KOMATSUSHIMA_TITLE,
                           capture_mode=source.REPLAY_FRAME_MODE, browser_player_seconds=90,
                           frame_interval_seconds=4)
            repeated = [{'video_seconds': time, 'frame_sha256': 'a'*64}
                        for time in source.timeline(90, 4)]
            for frames in (repeated, repeated[:1] + [dict(repeated[-1], frame_sha256='b'*64)]):
                (folder/'overview.json').write_text(json.dumps(dict(receipt, frames=frames)))
                with self.assertRaisesRegex(ValueError, 'replay clock'):
                    source.validate_receipt(folder, key, url)

    def test_winticket_single_host_approval_cannot_authorize_a_kdreams_queue(self):
        with TemporaryDirectory() as temp, patch.dict('sys.modules', {'playwright.sync_api': None}):
            root = Path(temp)
            queue = root / 'queue.jsonl'
            queue.write_text(json.dumps(RACE) + '\n')
            evidence = root / 'operator-attestation.json'
            evidence.write_bytes(b'fictional operator attestation')
            approval = root / 'approval.json'
            approval.write_text(json.dumps({
                'source_host': 'www.winticket.jp', 'rights_ref': evidence.name,
                'rights_sha256': sha256(evidence.read_bytes()).hexdigest(),
                'reviewer': 'test reviewer', 'permission_basis': 'owner_attestation',
                'allowed_uses': ['automated_fetch', 'private_retention', 'history_analysis',
                                 'video_recording', 'frame_capture'],
                'first_race_date': '2024-05-01', 'last_race_date': '2024-05-31'}))
            out = root / 'captures'
            options = dict(source_approval=approval, interval=3, pause=0, limit=1, executable='unused')
            self.assertEqual(source.run(queue, out, continuous=True, **options),
                             {'outside_approved_scope': 1})
            with self.assertRaises(ValueError):
                source.run(queue, out, continuous=False, **options)
            self.assertFalse(out.exists())

    def test_winticket_recorder_rejects_protected_or_redirected_page(self):
        key, url = '202405038401', WINTICKET['race_detail_url']
        page = Mock(url=url)
        page.goto.return_value.status = 200
        page.title.return_value = WINTICKET_TITLE
        control = page.get_by_role.return_value
        control.count.return_value = 1
        control.is_visible.return_value = True
        video = page.locator.return_value
        video.count.return_value = 1
        video.evaluate.return_value = True
        with self.assertRaises(source.AccessDenied):
            source.open_player(page, key, url)
        page.url = url.replace('/3/1', '/3/2')
        with self.assertRaises(source.PlayerUnavailable):
            source.open_player(page, key, url)

    def test_decoded_images_required_for_resume(self):
        key, url = source.target(RACE)
        with TemporaryDirectory() as temp:
            folder = Path(temp)
            frame = folder / 't00020.png'
            frame.write_bytes(b'reviewed-frame')
            receipt = {'public_result_page': url, 'page_title': TITLE,
                       'frames': [{'video_seconds': .2, 'frame_sha256': sha256(frame.read_bytes()).hexdigest()}]}
            (folder / 'overview.json').write_text(json.dumps(receipt))
            self.assertEqual(source.validate_receipt(folder, key, url), receipt)
            frame.write_bytes(b'another-frame')
            with self.assertRaises(ValueError):
                source.validate_receipt(folder, key, url)

    def test_denial_stops_before_interaction(self):
        key, url = source.target(RACE)
        for code in (401, 403, 429):
            page = Mock()
            page.goto.return_value.status = code
            with self.assertRaises(source.AccessDenied):
                source.open_player(page, key, url)
            page.locator.assert_not_called()

    def test_browser_access_policy_denial_ends_capture_batch(self):
        class BrowserError(Exception):
            pass

        for code in ('ERR_BLOCKED_BY_ADMINISTRATOR', 'ERR_ACCESS_DENIED', 'ERR_NETWORK_ACCESS_DENIED'):
            with self.subTest(code=code), TemporaryDirectory() as temp:
                root = Path(temp)
                queue = root / 'queue.jsonl'
                second = dict(RACE, race_id='20240504-13-02',
                              race_detail_url=RACE['race_detail_url'].replace('0001/', '0002/'))
                queue.write_text(json.dumps(RACE) + '\n' + json.dumps(second) + '\n')
                rights = root / 'fixture-rights'
                rights.write_bytes(b'fictional provider permission')
                approval = root / 'approval.json'
                approval.write_text(json.dumps({
                    'source_host': source.HOST, 'rights_ref': rights.name,
                    'rights_sha256': sha256(rights.read_bytes()).hexdigest(), 'reviewer': 'test reviewer',
                    'allowed_uses': ['automated_fetch', 'private_retention', 'history_analysis', 'video_recording'],
                    'race_ids': [RACE['race_id'], second['race_id']]}))
                api = MagicMock(Error=BrowserError, TimeoutError=TimeoutError)
                out = root / 'captures'
                with patch.dict('sys.modules', {'playwright.sync_api': api}), \
                     patch.object(source, 'record_digest',
                                  side_effect=BrowserError(f'Page.goto: net::{code} at a replay')):
                    tally = source.run(queue, out, continuous=True, source_approval=approval,
                                       interval=3, pause=0, limit=2, executable='unused')
                self.assertEqual(tally, {'browser access refused': 1})
                attempt = json.loads((out / 'attempts.jsonl').read_text())
                self.assertEqual(attempt['race_id'], RACE['race_id'])
                self.assertEqual(attempt['status'], 'browser access refused')
                with patch.dict('sys.modules', {'playwright.sync_api': None}):
                    tally = source.run(queue, out, continuous=True, source_approval=approval,
                                       interval=3, pause=0, limit=2, executable='unused',
                                       stop_after_refusal=True)
                self.assertEqual(tally, {'browser access refused': 1})
                self.assertEqual(len((out / 'attempts.jsonl').read_text().splitlines()), 1)

    def test_direct_recorder_helpers_refuse_before_starting_without_approval(self):
        key, url = source.target(RACE)
        browser, page = Mock(), Mock()
        with self.assertRaises(ValueError):
            source.record_digest(browser, key, url, None)
        browser.new_context.assert_not_called()
        with self.assertRaises(ValueError):
            source.capture(page, key, url, None, 3)
        page.goto.assert_not_called()

    def test_sampling_includes_last_and_initial_player_times_once(self):
        self.assertEqual(source.timeline(3.4, 3), [.2, 3.2])
        self.assertEqual(source.timeline(3.8, 3), [.2, 3.2, 3.6])
        with self.assertRaises(ValueError):
            source.timeline(float('nan'), 3)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'video toolchain required')
    def test_screen_clip_clock_excludes_non_playback_frames(self):
        with TemporaryDirectory() as temp:
            video = Path(temp) / 'screen.mkv'
            subprocess.run(['ffmpeg', '-loglevel', 'error', '-f', 'lavfi', '-i',
                            'color=black:s=32x720:r=10:d=1',
                            '-vf', "drawbox=x=0:y=700:w=16:h=16:color=lime:t=fill:enable='between(t,0.2,0.6)'",
                            '-c:v', 'ffv1', str(video)], check=True)
            start, end = source.recording_bounds(video)
            self.assertAlmostEqual(start, .2)
            self.assertGreaterEqual(end, .5)
            self.assertLessEqual(end, .6)

    def test_resumed_movie_must_match_saved_hash_and_ordinary_race(self):
        key, url = source.target(RACE)
        with TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / 'digest.mp4').write_bytes(b'example recording')
            receipt = {'public_result_page': url, 'page_title': TITLE, 'kind': 'clip',
                       'path': 'digest.mp4', 'sha256': sha256(b'example recording').hexdigest()}
            (folder / 'clip.json').write_text(json.dumps(receipt))
            source.check_clip(folder, key, url)
            (folder / 'digest.mp4').write_bytes(b'changed')
            with self.assertRaises(ValueError):
                source.check_clip(folder, key, url)

    def test_retry_history_does_not_starve_unvisited_rows(self):
        with TemporaryDirectory() as temp:
            log = Path(temp) / 'attempts.jsonl'
            def row(key, status):
                return json.dumps({'race_id': key, 'source_ref': 'public page', 'status': status})
            log.write_text('\n'.join([row('old', 'ordinary player timeout'), row('old', 'captured'),
                                      row('missing', 'digest button unavailable')]))
            self.assertEqual(source.failed_attempts(log), {('missing', 'public page')})

    def test_capture_log_opener_does_not_follow_a_symbolic_link(self):
        with TemporaryDirectory() as temp:
            target = Path(temp) / 'unused-target'
            alias = Path(temp) / 'attempt-log'
            alias.symlink_to(target)
            with self.assertRaises(OSError):
                source.private_log_fd(alias, os.O_CREAT | os.O_WRONLY)
            self.assertFalse(target.exists())

    def test_capture_refuses_a_linked_race_folder_before_reuse(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            queue = root / 'queue.jsonl'
            queue.write_text(json.dumps(RACE) + '\n')
            rights = root / 'fixture-rights'
            rights.write_bytes(b'fictional provider permission')
            approval = root / 'approval.json'
            approval.write_text(json.dumps({
                'source_host': source.HOST, 'rights_ref': rights.name,
                'rights_sha256': sha256(rights.read_bytes()).hexdigest(), 'reviewer': 'test reviewer',
                'allowed_uses': ['automated_fetch', 'private_retention', 'history_analysis', 'video_recording'],
                'race_ids': [RACE['race_id']]}))
            out = root / 'captures'
            out.mkdir()
            other = root / 'unrelated-fixture'
            other.mkdir()
            (out / '202405041301').symlink_to(other, target_is_directory=True)
            with patch.object(source, 'check_clip') as read_capture, self.assertRaises(ValueError):
                source.run(queue, out, continuous=True, source_approval=approval,
                           interval=3, pause=0, limit=1, executable='unused')
            read_capture.assert_not_called()


if __name__ == '__main__':
    unittest.main()
