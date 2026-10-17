"""Operational readiness depends on the actual validated daily feed."""
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'web'))


class HealthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from api import health
        cls.api = health

    def feed(self):
        return {'date_jst':'2026-10-15', 'first_observed_at':'2026-10-15T00:00:00Z',
                'last_observed_at':'2026-10-15T00:00:00Z',
                'schedule_verified':True,
                'races':12, 'complete_six_boat_races':12,
                'venues':[{'venue':'02','status':'READY','no_event':False,'races':[{}]*12}]
                         + [{'venue':f'{n:02d}','status':'NO_EVENT','no_event':True,'races':[]}
                            for n in range(1,25) if n != 2]}

    def test_missing_feed_is_unavailable_and_does_not_claim_readiness(self):
        with patch.object(self.api, 'load_feed', return_value=(503, {'error':'FEED_NOT_APPROVED'})):
            status, body = self.api.readiness()
        self.assertEqual(status,503)
        self.assertFalse(body['ready'])
        self.assertEqual(body['error'],'FEED_NOT_APPROVED')
        self.assertNotIn('venues',body)

    def test_complete_day_has_counts_and_observation_age_without_boat_details(self):
        with patch.object(self.api, 'load_feed', return_value=(200,self.feed())), patch.object(
                self.api, 'utc_now', return_value=datetime(2026,10,15,0,2,tzinfo=timezone.utc)):
            status, body = self.api.readiness()
        self.assertEqual(status,200)
        self.assertTrue(body['ready'])
        self.assertEqual(body['venue_states'],24)
        self.assertEqual(body['active_venues'],1)
        self.assertEqual(body['observation_age_seconds'],120)
        self.assertNotIn('boats',body)

    def test_incomplete_programs_report_degraded_instead_of_ready(self):
        feed=self.feed();feed['venues'][0]['status']='ERROR';feed['races']=0;feed['complete_six_boat_races']=0
        with patch.object(self.api,'load_feed',return_value=(200,feed)):
            status, body = self.api.readiness()
        self.assertEqual(status,503)
        self.assertFalse(body['ready'])
        self.assertEqual(body['error_venues'],['02'])

    def test_verified_no_event_day_is_ready_with_zero_races(self):
        feed=self.feed();feed['venues'][0].update(status='NO_EVENT',no_event=True,races=[])
        feed.update(races=0,complete_six_boat_races=0)
        with patch.object(self.api,'load_feed',return_value=(200,feed)):
            status, body = self.api.readiness()
        self.assertEqual(status,200)
        self.assertEqual(body['active_venues'],0)
        self.assertTrue(body['ready'])

    def test_ready_label_with_incomplete_active_program_is_still_degraded(self):
        feed = self.feed()
        feed['venues'][0]['races'] = [{}]
        feed.update(races=1, complete_six_boat_races=1)
        with patch.object(self.api, 'load_feed', return_value=(200, feed)):
            status, body = self.api.readiness()
        self.assertEqual(status, 503)
        self.assertFalse(body['ready'])
        self.assertIn('02', body['error_venues'])

    def test_legacy_feed_without_complete_schedule_proof_is_not_ready(self):
        feed = self.feed()
        feed.pop('schedule_verified')
        with patch.object(self.api, 'load_feed', return_value=(200, feed)):
            status, body = self.api.readiness()
        self.assertEqual(status, 503)
        self.assertFalse(body['ready'])


if __name__=='__main__':
    unittest.main()
