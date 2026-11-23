from datetime import datetime, timezone
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
