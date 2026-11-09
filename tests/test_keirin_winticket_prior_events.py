"""Invented past results only; no official provider or model admission claims."""
from copy import deepcopy
from datetime import datetime
import importlib.util
import unittest

TARGET='203001151203'
URL='https://www.winticket.jp/keirin/aomori/racecard/2030011312/3/3'
CAPTURE='2030-01-15T08:10:00+09:00'
CUTOFF='2030-01-15T09:25:00+09:00'
PAST='203001101201'
RESULT='https://www.winticket.jp/keirin/aomori/raceresult/2030011012/1/1'


def epoch(value):
    return int(datetime.fromisoformat(value).timestamp())


def page_data(rid='031220300115', *, old=False):
    meta={'id':rid,'number':int(rid[:2]),'startAt':epoch(
        '2030-01-10T10:05:00+09:00' if old else '2030-01-15T09:30:00+09:00'),
        'closeAt':epoch('2030-01-10T10:00:00+09:00' if old else CUTOFF),
        'decidedAt':epoch('2030-01-10T10:10:00+09:00') if old else 0,
        'class':'A','raceType3':'general','distance':1625,'entriesNumber':7}
    return {'races':[meta],
            'entries':[{'number':n,'raceId':rid,'playerId':'fiction-'+str(n),
                        'absent':False} for n in range(1,8)],
            'records':[{'playerId':'fiction-'+str(n),
                        'latestCupResults':[{'cupId':'2030011012','racePoint':80,
                          'raceResults':[{'raceId':'011220300110',
                           'playerId':'fiction-'+str(n),'order':n,
                           'finalHalfRecord':12.0+n/10}]}],
                        'currentCupResults':[], 'latestVenueResults':[]}
                       for n in range(1,8)],
            'results':[{'raceId':rid,'playerId':'fiction-'+str(n),'order':n,
                        'finalHalfRecord':str(12+n/10),'hasAccident':False}
                       for n in range(1,8)] if old else [],
            'venues':[{'id':'12','slug':'aomori'}]}


class PriorEventContractTests(unittest.TestCase):
    def test_source_contract_exists(self):
        self.assertIsNotNone(importlib.util.find_spec(
            'race_ai.keirin_winticket_prior_events'))

    def refs(self,data=None):
        from race_ai.keirin_winticket_prior_events import history_references
        return history_references([page_data() if data is None else data],
            target_race_id=TARGET,target_url=URL,captured_at=CAPTURE)

    def result(self,data=None,**kw):
        from race_ai.keirin_winticket_prior_events import normalize_result_event
        return normalize_result_event([page_data('011220300110',old=True)
                if data is None else data],source_url=RESULT,
            expected_race_id=PAST,source_sha256='a'*64,
            captured_at=kw.get('captured_at',CAPTURE),target_cutoff_at=CUTOFF)

    def test_source_join_deduplicates_shared_history_without_new_model(self):
        r=self.refs()
        self.assertEqual(len(r['references']),1)
        self.assertEqual(r['references'][0]['url'],RESULT)
        self.assertEqual(r['references'][0]['race_id'],PAST)
        self.assertEqual(len(r['references'][0]['rider_ids']),7)
        self.assertEqual(r['history_rows_seen'],7)
        self.assertEqual(r['target']['race_id'],TARGET)
        self.assertFalse(r['forecast_created'])

    def test_target_and_same_day_results_never_enter_historical_features(self):
        d=page_data()
        for r in d['records']:
            r['latestCupResults'][0]['raceResults'].append(
                {'raceId':'031220300115','playerId':r['playerId']})
        out=self.refs(d)
        self.assertEqual(len(out['references']),1)
        self.assertEqual(out['excluded_current_or_future_rows'],7)

    def test_wrong_rider_cup_or_unmapped_venue_is_not_invented(self):
        d=page_data()
        d['records'][0]['latestCupResults'][0]['raceResults'][0]['playerId']='foreign'
        d['records'][1]['latestCupResults'][0]['cupId']='2030011025'
        d['records'][2]['latestCupResults'][0]['cupId']='2030010925'
        d['records'][2]['latestCupResults'][0]['raceResults'][0]['raceId']='012520300110'
        out=self.refs(d)
        self.assertEqual(len(out['references'][0]['rider_ids']),4)
        self.assertEqual(out['rejected_or_unmapped_rows'],3)

    def test_complete_result_has_real_times_but_no_invented_line_or_splits(self):
        event=self.result()
        self.assertEqual(len(event['starters']),7)
        self.assertEqual(event['starters'][0]['agari_s'],12.1)
        self.assertEqual(event['starters'][0]['finish_rank'],1)
        self.assertIsNone(event['ended_at'])
        self.assertIsNone(event['lineup_published_at'])
        self.assertIsNone(event['starters'][0]['line_id'])
        self.assertIsNone(event['starters'][0]['final_two_splits'])
        self.assertEqual(event['result_captured_at'],CAPTURE)

    def test_invalid_result_timing_roster_duplicates_and_wrong_identity_rejected(self):
        from race_ai.keirin_winticket_prior_events import PriorSourceError
        for kind in ('clock','race','duplicate','absent'):
            d=page_data('011220300110',old=True)
            if kind=='clock':
                d['races'][0]['decidedAt']=epoch('2030-01-15T09:40:00+09:00')
            if kind=='race': d['results'][0]['raceId']='021220300110'
            if kind=='duplicate': d['results'][0]['order']=2
            if kind=='absent': d['entries'][0]['absent']=True
            with self.subTest(kind=kind),self.assertRaises(PriorSourceError):
                self.result(d)
        with self.assertRaises(PriorSourceError):
            self.result(captured_at='2030-01-15T10:00:00+09:00')

    def test_missing_agari_and_accident_not_fabricated_from_finish(self):
        d=page_data('011220300110',old=True)
        d['results'][0]['finalHalfRecord']='----'
        d['results'][1]['hasAccident']=True
        out=self.result(d)
        self.assertIsNone(out['starters'][0]['agari_s'])
        self.assertIsNone(out['starters'][1]['finish_rank'])
        self.assertIsNone(out['starters'][1]['agari_s'])
        self.assertEqual(out['starters'][2]['finish_rank'],3)

    def test_public_summary_contains_no_athlete_identifier_or_measurement(self):
        from race_ai.keirin_winticket_prior_events import safe_prior_counts
        counts=safe_prior_counts(self.refs(),[self.result()])
        self.assertEqual(counts['prior_result_pages_verified'],1)
        self.assertEqual(counts['prior_rider_results_verified'],7)
        self.assertNotIn('fiction-',str(counts))
        self.assertNotIn('12.1',str(counts))
        self.assertFalse(counts['model_input_admitted'])


class ExistingPriorEquationIntegrationTests(unittest.TestCase):
    refs=PriorEventContractTests.refs
    result=PriorEventContractTests.result

    def test_actual_existing_formula_and_unknown_tactical_inputs_are_separate(self):
        from race_ai.keirin_winticket_prior_events import observed_prior_candidates
        from race_ai.keirin_historical_prior_signal_rules import FORMULA_VERSION
        refs=self.refs()
        events=[]
        for n in range(10):
            e=deepcopy(self.result())
            e['race_id']='203001'+f'{n+1:02d}'+'1201'
            e['started_at']=f'2030-01-{n+1:02d}T10:00:00+09:00'
            e['result_published_at']=f'2030-01-{n+1:02d}T10:10:00+09:00'
            e['venue']='12' if n<5 else '25'
            events.append(e)
        value=observed_prior_candidates(refs,events,as_of=CAPTURE)
        self.assertEqual(value['formula_version'],FORMULA_VERSION)
        for rider in value['riders'].values():
            f=rider['features']
            self.assertIsNotNone(f['finishing_power']['candidate_value'])
            self.assertAlmostEqual(f['bank_fit']['candidate_value'],.5)
            self.assertIsNone(f['line_coordination']['candidate_value'])
            self.assertIsNone(f['sprint_acceleration']['candidate_value'])
            self.assertFalse(f['finishing_power']['approved_for_pr71_input'])
        self.assertFalse(value['model_input_admitted'])
        self.assertEqual(value['forecasts_created'],0)
        e=deepcopy(events[0]); e['result_captured_at']='2030-01-15T10:00:00+09:00'
        with self.assertRaises(ValueError):
            observed_prior_candidates(refs,[e],as_of=CAPTURE)

    def test_unknown_finish_does_not_become_venue_loss_or_zero_input(self):
        from race_ai.keirin_winticket_prior_events import observed_prior_candidates
        refs=self.refs()
        e=self.result()
        e['starters'][0]['finish_rank']=None
        e['starters'][0]['agari_s']=None
        out=observed_prior_candidates(refs,[e],as_of=CAPTURE)
        rider=out['riders']['fiction-1']
        self.assertEqual(rider['matched_prior_events'],0)
        self.assertEqual(rider['features']['bank_fit']['same_venue_count'],0)


if __name__=='__main__': unittest.main()
