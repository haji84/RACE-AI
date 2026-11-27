from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from http.client import IncompleteRead
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from race_ai import keirin_secondary_result_consensus as consensus
from scripts import keirin_capture_public_two_sources as capture
from scripts import keirin_public_site_results as publisher

DATE = '2026-11-23'
NOW = datetime(2026, 11, 23, 1, 40, tzinfo=timezone.utc)
IDS = ['202611236201', '202611236202', '202611236203']


def race(index, cutoff='2026-11-23T09:00:00+09:00'):
    return {'date':DATE,'race_id':IDS[index],'venue':'広島','race_no':index+1,
            'source_url':f'https://keirin.kdreams.jp/hiroshima/racedetail/622026112202000{index+1}/',
            'published_cutoff_at':cutoff,'observed_riders':[{'number':n} for n in range(1,8)]}


def roster(races):
    return {'schema':'KEIRIN_PUBLIC_RESULT_ROSTER_V1','date':DATE,'generated_at':'2026-11-23T00:29:47Z',
            'forecast_asset_sha256':'a'*64,'races':races}


def snapshot(entries):
    return {'schema':'KEIRIN_PUBLISHED_RESULTS_V1','date':DATE,'checked_at':'2026-11-23T01:04:00Z','races':entries}


class PublicDailyRosterTests(unittest.TestCase):
    def forecasts(self, *, published='2026-11-23T00:33:00+00:00', cutoff='2026-11-23T09:00:00+09:00'):
        return json.dumps(dict(schema='RACE_AI_KEIRIN_PUBLIC_FORECASTS_V1', day=DATE,
            published_at=published, races=[dict(race_id=rid, status='pending', cutoff_at=cutoff,
                saved_at=None, a=[], b=[]) for rid in IDS[:2]])).encode()

    def source(self, number):
        row = race(number)
        return dict(race_id=row['race_id'], source_url=row['source_url'],
                    cutoff_at=row['published_cutoff_at'], riders=row['observed_riders'])

    def test_registers_the_daily_forecast_universe_from_confirmed_cards(self):
        with patch.object(publisher, 'discover_missing_links') as fallback:
            manifest = publisher.build_public_roster(self.forecasts(), [self.source(0), self.source(1)], [])
        fallback.assert_not_called()
        self.assertEqual(manifest['races'], [race(0), race(1)])
        self.assertEqual(manifest['generated_at'], '2026-11-23T00:33:00+00:00')

    def test_fallback_uses_an_official_starter_list_and_an_observed_provider_link(self):
        official = [dict(race_id=IDS[1], riders=race(1)['observed_riders'])]
        with patch.object(publisher, 'discover_missing_links', return_value={IDS[1]:race(1)['source_url']}) as fallback:
            manifest = publisher.build_public_roster(self.forecasts(), [self.source(0)], official)
        fallback.assert_called_once()
        self.assertEqual(fallback.call_args.args[:2], (DATE, {IDS[1]}))
        self.assertEqual(manifest['races'], [race(0), race(1)])

    def test_incomplete_starters_cannot_create_a_roster_or_trigger_provider_lookup(self):
        with patch.object(publisher, 'discover_missing_links') as fallback:
            with self.assertRaisesRegex(ValueError, 'PUBLIC_ROSTER_INPUT_INCOMPLETE'):
                publisher.build_public_roster(self.forecasts(), [self.source(0)], [])
        fallback.assert_not_called()

    def test_representation_refresh_leaves_the_time_bound_to_existing_results(self):
        previous = roster([race(0), race(1)])
        later = '2026-11-23T09:02:00+09:00'
        updated = publisher.build_public_roster(self.forecasts(cutoff=later), [], [], previous=previous)
        self.assertEqual(updated['generated_at'], previous['generated_at'])
        self.assertEqual(updated['races'], [race(0, later), race(1, later)])
        self.assertEqual(publisher.build_public_roster(self.forecasts(cutoff=later), [], [], previous=updated), updated)

    def test_cutoff_revision_cannot_invalidate_the_earlier_of_two_result_receipts(self):
        matched = {'race_id':IDS[0], 'state':'matched', 'comparison':{
            'observed_at':'2026-11-23T00:12:00Z',
            'sources':[{'checked_at':'2026-11-23T00:10:00Z'}, {'checked_at':'2026-11-23T00:12:00Z'}]}}
        with self.assertRaisesRegex(ValueError, 'PUBLIC_ROSTER_SETTLED_CLOCK_CONFLICT'):
            publisher.build_public_roster(self.forecasts(cutoff='2026-11-23T09:11:00+09:00'), [], [],
                                         previous=roster([race(0), race(1)]), results=snapshot([matched]))

    def test_legacy_roster_uses_the_display_clock_and_retains_prior_clocks_for_unlisted_rows(self):
        original = roster([race(0, '2026-11-23T09:02:00+09:00'), race(1, '2026-11-23T09:04:00+09:00')])
        updated = publisher.build_public_roster(self.forecasts(cutoff=None), [self.source(0), self.source(1)], [],
                                               display_cutoffs={IDS[0]:race(0)['published_cutoff_at']}, previous=original)
        self.assertEqual(updated['generated_at'], original['generated_at'])
        self.assertEqual(updated['races'], [race(0), original['races'][1]])

    def test_published_reference_clock_precedes_research_and_unregistered_layers_are_held(self):
        raw = self.forecasts(cutoff=None)
        head = 'a'*40
        packet = dict(day=DATE, published_at='2026-11-23T00:33:00+00:00')
        picks = dict(a=[[1, 2, 3]], b=[[2, 1, 3]])
        ref = dict(packet, schema='RACE_AI_KEIRIN_PUBLIC_REFERENCE_FORECASTS_V1', races=[dict(
            race_id=IDS[0], cutoff_at='2026-11-23T09:35:00+09:00', saved_at='2026-11-23T00:29:00+00:00', **picks)])
        research = dict(packet, schema='RACE_AI_KEIRIN_PUBLIC_RESULT_UNREAD_AB_V1', races=[dict(
            race_id=rid, cutoff_at='2026-11-23T09:37:00+09:00', generated_at='2026-11-23T00:29:00+00:00',
            starter_cars=list(range(1, 8)), **picks) for rid in IDS[:2]])
        store = Mock()
        store.read_previous.side_effect = [json.dumps(ref), json.dumps(research), None]
        self.assertEqual(publisher.published_display_cutoffs(store, head, json.loads(raw)),
                         {IDS[0]:'2026-11-23T09:35:00+09:00', IDS[1]:'2026-11-23T09:37:00+09:00'})
        research['races'][1]['race_id'] = IDS[2]
        store.read_previous.side_effect = [json.dumps(ref), json.dumps(research), None]
        self.assertEqual(publisher.published_display_cutoffs(store, head, json.loads(raw)),
                         {IDS[0]:'2026-11-23T09:35:00+09:00'})

    def test_roster_lookup_denial_stops_both_paths_on_following_runs(self):
        rejection = capture.SourceCaptureError('PROVIDER_DENIED_OR_RATE_LIMITED_STOP', http_status=403)
        with TemporaryDirectory() as folder, redirect_stdout(io.StringIO()), \
             patch('sys.argv', ['publisher', '--state-directory', folder, '--refresh-rosters']), \
             patch('race_ai.keirin_public_forecasts.PublicForecastGit'), \
             patch.object(publisher, 'refresh_public_rosters', side_effect=rejection) as refresh, \
             patch.object(publisher, 'collect') as collect:
            self.assertEqual(publisher.main(), 75)
            self.assertEqual(publisher.main(), 0)
            self.assertEqual(json.loads((Path(folder) / 'results/provider-pause.json').read_text()),
                             dict(status=403, retry_at=None))
        refresh.assert_called_once()
        collect.assert_not_called()


class PublicResultRefreshTests(unittest.TestCase):
    def test_new_cutoff_does_not_remove_a_match_or_special_result(self):
        match = {'race_id': IDS[0], 'state': 'matched', 'comparison': {'race_id': IDS[0]}}
        special = {'race_id': IDS[1], 'state': 'held', 'reason': 'special_result'}
        later = '2026-11-23T12:00:00+09:00'
        with patch.object(publisher, 'observe', side_effect=ValueError('PAYOUT_NOT_PUBLISHED')):
            data, _ = publisher.collect(roster([race(0, later), race(1, later), race(2)]),
                                        None, consensus, previous=snapshot([match, special]), now=NOW)
        rows = {row['race_id']: row for row in data['races']}
        self.assertEqual(rows.get(IDS[0]), match)
        self.assertEqual(rows.get(IDS[1]), special)
        self.assertEqual(rows[IDS[2]]['reason'], 'result_unpublished')

    def test_missing_page_is_pending_while_http_outage_stops_the_batch(self):
        cases = [(404, 'result_unpublished', 2), (503, 'source_unavailable', 1)]
        for status, reason, calls in cases:
            with self.subTest(status=status), patch.object(capture, 'build_opener') as opener:
                request = opener.return_value.open
                request.side_effect = HTTPError('https://keirin.kdreams.jp/', status, 'fixture', {}, None)
                data, evidence = publisher.collect(roster([race(0), race(1)]), capture.fetch_once,
                                                   consensus, now=NOW)
                self.assertEqual([row['reason'] for row in data['races']], [reason, reason])
                self.assertEqual(request.call_count, calls)
                self.assertEqual(next(row['code'] for row in evidence if 'code' in row),
                                 'RESULT_HTTP_NOT_FOUND' if status == 404 else 'PUBLIC_PROVIDER_HTTP_ERROR_STOP')

    def test_truncated_response_stops_the_batch_and_keeps_the_prior_match(self):
        match = {'race_id': IDS[0], 'state': 'matched', 'comparison': {'race_id': IDS[0]}}
        with patch.object(capture, 'build_opener') as opener:
            request = opener.return_value.open
            response = request.return_value
            response.status = 200
            response.headers = {'Content-Type': 'text/html'}
            response.geturl.side_effect = lambda: request.call_args.args[0].full_url
            response.read.side_effect = IncompleteRead(b'<html>', expected=40)
            data, evidence = publisher.collect(roster([race(0),race(1),race(2)]), capture.fetch_once,
                                               consensus, previous=snapshot([match]), now=NOW)
        self.assertIn(match, data['races'])
        self.assertEqual([row['reason'] for row in data['races'][1:]], ['source_unavailable'] * 2)
        request.assert_called_once()
        self.assertEqual(evidence[-1]['code'], 'PUBLIC_PROVIDER_UNAVAILABLE_STOP')

    def test_only_race_payout_cells_can_produce_a_new_permanent_special_hold(self):
        page = '''<html><head><title>広島競輪 2026年11月23日 1R 結果</title></head>
        <body><div>払戻</div>{notice}<table class="refund_table">
        <tr><th>2枠連</th><th>2車連</th><th>3連勝</th><th>ワイド</th></tr>
        <tr><td>単</td><td></td><td>単</td><td>1-2 780円</td><td>単</td><td>1-2-4 2,110円</td></tr>
        {additional}</table></body></html>'''
        cases = [('', '<tr><td>払戻の補足欄</td></tr>', 'source_disagreement'),
                 ('<footer>返還についてのヘルプ</footer>', '', 'source_disagreement'),
                 ('', '<tfoot><tr><td><a>返還についてのヘルプ</a></td></tr></tfoot>', 'source_disagreement'),
                 ('<section><h3>別の日程</h3><p>レース中止</p></section>', '', 'source_disagreement'),
                 ('', '<tr><td>同着</td></tr>', 'special_result')]
        for notice, additional, expected in cases:
            with self.subTest(notice=notice, additional=additional):
                html = page.format(notice=notice, additional=additional).encode('utf-8')
                data, _ = publisher.collect(roster([race(0)]), lambda _url: html, consensus, now=NOW)
                self.assertEqual(data['races'][0]['state'], 'held')
                self.assertEqual(data['races'][0]['reason'], expected)

    def test_rate_limit_persists_between_polls_until_retry_after(self):
        with TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'rosters').mkdir()
            (state / 'rosters' / f'{DATE}.json').write_text(json.dumps(roster([race(0)])))
            with (patch('sys.argv', ['publisher', '--state-directory', directory]),
                  patch.object(publisher, 'datetime', wraps=datetime) as clock,
                  patch.object(capture, 'build_opener') as opener,
                  redirect_stdout(io.StringIO())):
                request = opener.return_value.open
                request.side_effect = HTTPError('https://keirin.kdreams.jp/', 429, 'fixture',
                                                {'Retry-After': '10800'}, None)
                clock.now.return_value = NOW
                self.assertEqual(publisher.main(), 75)
                clock.now.return_value = NOW + timedelta(minutes=15)
                publisher.main()
                request.assert_called_once()
                clock.now.return_value = NOW + timedelta(hours=3)
                request.side_effect = HTTPError('https://keirin.kdreams.jp/', 404, 'fixture', {}, None)
                self.assertEqual(publisher.main(), 0)
                self.assertEqual(request.call_count, 2)

    def test_budget_preserves_earlier_rows_and_resumes_with_the_next_race(self):
        match = {'race_id': IDS[2], 'state': 'matched', 'comparison': {'race_id': IDS[2]}}
        published = roster([race(0), race(1), race(2)])
        calls = []

        def missing(url):
            calls.append(url)
            raise ValueError('PAYOUT_NOT_PUBLISHED')

        with patch.object(publisher, 'datetime', wraps=datetime) as clock:
            clock.now.return_value = NOW
            first, _ = publisher.collect(published, missing, consensus, previous=snapshot([match]),
                                         now=NOW, can_poll=lambda: not calls)
            self.assertEqual({row['race_id'] for row in first['races']}, {IDS[0], IDS[2]})
            later, _ = publisher.collect(published, missing, consensus, previous=first, now=NOW,
                                         resume_after=IDS[0], can_poll=lambda: len(calls) == 1)
        self.assertEqual([url.split('/')[-2][-1] for url in calls], ['1', '2'])
        self.assertEqual({row['race_id'] for row in later['races']}, set(IDS))
        self.assertIn(match, later['races'])

    @unittest.skipUnless(shutil.which('git') and shutil.which('bash'), 'The public publisher runs with Git and Bash')
    def test_watch_reads_back_the_first_poll_before_checking_again(self):
        repo = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as directory:
            root = Path(directory)
            state_ref = 'state/keirin-public-results'
            remote = root / 'remote.git'
            checkout = root / 'checkout'
            runner_temp = root / 'runner-temp'
            runner_temp.mkdir()

            def git(*args, cwd=root):
                return subprocess.run(['git', *args], cwd=cwd, check=True, text=True, capture_output=True).stdout

            git('init', '--bare', str(remote))
            git('init', '-b', state_ref, str(checkout))
            (checkout / 'rosters').mkdir()
            cutoff = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
            (checkout / 'rosters' / f'{DATE}.json').write_text(json.dumps(roster([race(0, cutoff)])))
            git('add', 'rosters', cwd=checkout)
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                'commit', '-m', 'Fixture roster', cwd=checkout)
            git('remote', 'add', 'origin', str(remote), cwd=checkout)
            git('push', 'origin', state_ref, cwd=checkout)

            summary = runner_temp / 'summary'
            env = {**os.environ, 'RUNNER_TEMP': str(runner_temp), 'GITHUB_STEP_SUMMARY': str(summary),
                   'PYTHONPATH': str(repo)}
            # Advance the real Bash clock in the fixture so both polls run immediately.
            command = 'sleep() { SECONDS=$((SECONDS + $1)); }; source "$1" 16'
            result = subprocess.run(['bash', '-c', command, 'test-watch',
                                     str(repo / 'scripts/keirin_publish_public_site_results.sh')],
                                    cwd=checkout, env=env, text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            polls = [json.loads(line) for line in summary.read_text().splitlines()]
            self.assertEqual([poll['updated'] for poll in polls], [True, False])
            stored = git('--git-dir', str(remote), 'show', f'{state_ref}:results/{DATE}.json')
            self.assertEqual(json.loads(stored)['races'], [])

    def test_watch_reports_completion_only_after_all_published_races_are_resolved(self):
        special = {'race_id': IDS[0], 'state': 'held', 'reason': 'special_result'}
        with TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'rosters').mkdir()
            (state / 'results').mkdir()
            manifest = state / 'rosters' / f'{DATE}.json'
            (state / 'results' / f'{DATE}.json').write_text(json.dumps(snapshot([special])))
            with (patch('sys.argv', ['publisher', '--state-directory', directory, '--stop-when-complete']),
                  patch.object(publisher, 'datetime', wraps=datetime) as clock,
                  redirect_stdout(io.StringIO())):
                clock.now.return_value = NOW
                manifest.write_text(json.dumps(roster([race(0), race(1, '2026-11-23T12:00:00+09:00')])))
                self.assertEqual(publisher.main(), 0)
                manifest.write_text(json.dumps(roster([race(0)])))
                self.assertEqual(publisher.main(), 10)

    def test_publisher_reports_source_failure_after_saving_existing_and_pending_rows(self):
        special = {'race_id': IDS[0], 'state': 'held', 'reason': 'special_result'}
        with TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'rosters').mkdir()
            (state / 'results').mkdir()
            (state / 'rosters' / f'{DATE}.json').write_text(json.dumps(roster([race(0), race(1)])))
            result = state / 'results' / f'{DATE}.json'
            result.write_text(json.dumps(snapshot([special])))
            with (patch('sys.argv', ['publisher', '--state-directory', directory]),
                  patch.object(publisher, 'datetime', wraps=datetime) as clock,
                  patch.object(publisher, 'observe', side_effect=ValueError('PROVIDER_DENIED_OR_RATE_LIMITED_STOP')),
                  redirect_stdout(io.StringIO())):
                clock.now.return_value = NOW
                status = publisher.main()
            self.assertEqual(json.loads(result.read_text())['races'], [
                special, {'race_id': IDS[1], 'state': 'pending', 'reason': 'source_unavailable'},
            ])
            self.assertEqual(status, 75)

    def test_refresh_fetches_only_due_unsettled_races_and_keeps_the_saved_match(self):
        saved={'race_id':IDS[0],'state':'matched','comparison':{'race_id':IDS[0]}}
        prior=snapshot([saved,{'race_id':IDS[1],'state':'pending','reason':'result_unpublished'}])
        values={'2t':([1,2],780),'3t':([1,2,4],2110)}
        first={'source_id':'kdreams','url':'https://example.invalid','checked_at':'2026-11-23T01:39:00Z'}
        second={'source_id':'netkeirin','url':'https://example.invalid','checked_at':'2026-11-23T01:39:00Z'}
        with patch.object(publisher,'observe',side_effect=[(values,first),(values,second)]) as observe:
            data,_=publisher.collect(roster([race(0),race(1),race(2,'2026-11-23T12:00:00+09:00')]),
                                     None,consensus,previous=prior,now=NOW)
        self.assertEqual([call.args[0]['race_id'] for call in observe.call_args_list],[IDS[1],IDS[1]])
        self.assertEqual(data['races'][0],saved)
        self.assertEqual(data['races'][1]['comparison']['payouts_100yen'],{'2t':780,'3t':2110})
        self.assertEqual(prior['races'][1]['state'],'pending')

    def test_unchanged_finished_day_does_not_bump_the_snapshot(self):
        previous=snapshot([{'race_id':IDS[0],'state':'held','reason':'special_result'}])
        with patch.object(publisher,'observe') as observe:
            data,_=publisher.collect(roster([race(0)]),None,consensus,previous=previous,now=NOW)
        observe.assert_not_called()
        self.assertEqual(data,previous)

    def test_provider_rejection_stops_the_batch_and_keeps_prior_matches(self):
        saved={'race_id':IDS[0],'state':'matched','comparison':{'race_id':IDS[0]}}
        previous=snapshot([saved])
        with patch.object(publisher,'observe',side_effect=ValueError('PROVIDER_DENIED_OR_RATE_LIMITED_STOP')) as observe:
            data,evidence=publisher.collect(roster([race(0),race(1),race(2)]),None,consensus,previous=previous,now=NOW)
        self.assertEqual(observe.call_count,1)
        self.assertEqual(data['races'][0],saved)
        self.assertTrue(all(r['reason']=='source_unavailable' for r in data['races'][1:]))
        self.assertEqual(evidence[-1]['code'],'PROVIDER_DENIED_OR_RATE_LIMITED_STOP')

    def test_malformed_roster_url_fails_before_fetch(self):
        wrong=race(0)
        wrong['source_url']='https://keirin.kdreams.jp/hiroshima/racedetail/6220261122020002/'
        with patch.object(publisher,'observe') as observe:
            with self.assertRaisesRegex(ValueError,'KDREAMS_URL_OTHER_RACE'):
                publisher.collect(roster([wrong]),None,consensus,now=NOW)
        observe.assert_not_called()
