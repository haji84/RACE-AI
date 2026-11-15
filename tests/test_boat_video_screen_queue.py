"""Fictional 3–6-boat capture queue and private screen bridge regressions.

No browser navigation, video download, secret use or model inference.
"""
import asyncio
from datetime import datetime,timedelta,timezone
from unittest.mock import patch,AsyncMock
import unittest

from race_ai.boat_video_screen_queue import plan,capture_first

NOW=datetime(2030,4,1,2,0,tzinfo=timezone.utc)
DAY='2030-04-01'
CUTOFF=(NOW+timedelta(minutes=12)).isoformat()
ACTIVE_CASES=((1,3,6),(1,2,4,6),(1,2,3,5,6),(1,2,3,4,5,6))


def fixture(active,*,venue='01',race='01',window=12,withdrawn=()):
    lanes=sorted(set(active)|set(withdrawn))
    return dict(race_id=f'20300401-{venue}-{race}',
                cutoff_at=(NOW+timedelta(minutes=window)).isoformat(),
                race_status='LISTED',program_sha256='a'*64,
                program_captured_at=(NOW-timedelta(minutes=1)).isoformat(),
                roster=[dict(lane=i,registration_number=f'{1000+i}',
                    entry_status='listed' if i in active else 'withdrawn')
                        for i in lanes])


class BoatVideoScheduleTests(unittest.TestCase):
    def test_active_lanes_preserved_exactly_3_4_5_6_including_gaps(self):
        for lanes in ACTIVE_CASES:
            with self.subTest(active=lanes):
                p=plan([fixture(lanes)],day=DAY,now=NOW)
                self.assertEqual(p['candidate_races'],1)
                self.assertEqual(p['held_races'],0)
                job=p['candidates'][0]
                self.assertEqual(job['active_lanes'],list(lanes))
                self.assertEqual(job['source']['race_id'],'20300401-01-01')
                self.assertEqual(job['source']['page_url'],
                                 'https://race.boatcast.jp/replay?jo=01&md=T')
                self.assertIsNone(job['source']['play_selector'])
                self.assertTrue(job['requires_actual_dom_race_identity'])
                self.assertFalse(job['video_prediction_eligible'])
                self.assertFalse(p['official_video_playback_proven'])

    def test_three_active_with_withdrawals_never_renumbered(self):
        p=plan([fixture((1,3,6),withdrawn=(2,4,5))],day=DAY,now=NOW)
        job=p['candidates'][0]
        self.assertEqual(job['active_lanes'],[1,3,6])
        self.assertEqual([r['lane'] for r in job['roster']],[1,3,6])

    def test_earliest_cutoff_first_across_multiple_venues(self):
        p=plan([fixture((1,2,3),venue='24',race='02',window=14),
                fixture((2,4,6),venue='01',race='01',window=11)],
               day=DAY,now=NOW)
        self.assertEqual([j['race_id'] for j in p['candidates']],
                         ['20300401-01-01','20300401-24-02'])
        self.assertEqual(p['candidates'][1]['source']['page_url'],
                         'https://race.boatcast.jp/replay?jo=24&md=T')

    def test_cancelled_short_field_and_outside_window_hold(self):
        short=fixture((1,2),withdrawn=(3,))
        cancel=fixture((1,2,3),race='02');cancel['race_status']='CANCELLED'
        early=fixture((1,2,3),race='03',window=22)
        late=fixture((1,2,3),race='04',window=2)
        p=plan([short,cancel,early,late],day=DAY,now=NOW)
        self.assertEqual(p['candidate_races'],0)
        self.assertEqual(p['held_races'],4)
        self.assertEqual(sum(p['hold_reasons'].values()),4)
        self.assertFalse(p['nationwide_p1_proven'])

    def test_different_day_duplicate_and_invented_source_are_rejected(self):
        first=fixture((1,2,3))
        errors=(
            [first,first],
            [dict(first,program_captured_at=(NOW+timedelta(minutes=1)).isoformat())],
            [dict(first,program_sha256='fake')],
            [dict(first,race_id='20300402-01-01')],
            [dict(first,roster=[dict(lane=1,registration_number='1001',entry_status='listed')]*3)],
        )
        for rows in errors:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                plan(rows,day=DAY,now=NOW)

    def test_actual_recorder_wiring_only_with_dom_verifier(self):
        p=plan([fixture((2,4,6))],day=DAY,now=NOW)
        with patch('race_ai.boat_video_screen_queue.record_screen',
                   new_callable=AsyncMock) as capture:
            capture.return_value=dict(status='SCREEN_REPLAY_CAPTURE_ENCRYPTED_UNVALIDATED',
                                      envelope={'ciphertext':'private-fixture-only'})
            hold=asyncio.run(capture_first(object(),p,now=NOW,aes_key=b'a'*32,
                                          verify_page_identity=None))
            self.assertEqual(hold['status'],'HOLD_REAL_DOM_IDENTITY_CALLBACK_REQUIRED')
            capture.assert_not_called()
            verify=lambda page,source:None
            result=asyncio.run(capture_first(object(),p,now=NOW,aes_key=b'a'*32,
                                             verify_page_identity=verify))
            self.assertEqual(result['active_lanes'],[2,4,6])
            self.assertFalse(result['production_video_forecast_proven'])
            self.assertTrue(result['originals_unchanged'])
            capture.assert_awaited_once()
            self.assertIs(capture.await_args.kwargs['verify_page_identity'],verify)


if __name__=='__main__':unittest.main()
