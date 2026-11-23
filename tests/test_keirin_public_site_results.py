from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from race_ai import keirin_secondary_result_consensus as consensus
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


class PublicResultRefreshTests(unittest.TestCase):
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
