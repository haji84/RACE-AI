"""Supplemental collection must not become model readiness or bypass a source wait."""
import json
from datetime import date, datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import boat_nationwide_ab_pilot as pilot

RID='20300401-01-01'
CUTOFF='2030-04-01T11:00:00+09:00'
AT=datetime.fromisoformat('2030-04-01T01:45:00+00:00')
ROSTER=[dict(lane=i,racer_registration_id=str(4000+i)) for i in range(1,7)]

def context():
    return dict(schema='RACE_AI_BOAT_SUPPLEMENTAL_CONTEXT_V1',race_id=RID,cutoff_at=CUTOFF,
        roster=[dict(lane=r['lane'],registration_number=r['racer_registration_id']) for r in ROSTER],
        beforeinfo=dict(status='PARSED',source=dict(sha256='a'*64,captured_at=AT.isoformat())),
        pitreport=None,entry_history=None,forecast_inputs_used=False)

class SupplementalCollectionTests(unittest.TestCase):
    def test_pending_exhibition_retains_separate_weather_context(self):
        ctx=context()
        with patch.object(pilot,'_clock',return_value=AT), patch.object(pilot,'get',side_effect=[(b'program',AT,'a'*64),(b'pending',AT,'b'*64)]), patch.object(pilot,'parse_official_racelist',return_value=dict(race_id=RID,closed_at=CUTOFF,boats=[dict(r,entry_status='listed') for r in ROSTER])), patch.object(pilot,'motor_top2',return_value={}), patch.object(pilot,'parse_active_beforeinfo',return_value=dict(status='PENDING',data=None,context=ctx['beforeinfo'])), patch.object(pilot,'capture_before_context',return_value=ctx,create=True), patch.object(pilot,'supplemental_contexts',{},create=True), patch.object(pilot,'collect_pitreport',return_value=None,create=True) as comments, patch.object(pilot,'collect_entry_history',return_value=None):
            result=pilot.make_pair(date(2030,4,1),dict(race_id=RID,cutoff_at=CUTOFF))
            self.assertIsNone(result[1])
            self.assertEqual(pilot.supplemental_contexts.get(RID),ctx,'weather observations disappeared with pending exhibition')
            comments.assert_called_once_with(ctx,date(2030,4,1))

    def test_optional_comments_do_not_get_after_source_wait(self):
        ctx=context()
        with patch.object(pilot,'get') as get, patch.object(pilot,'_clock',return_value=AT):
            result=pilot.collect_pitreport(ctx,date(2030,4,1),paused={'reason':'HTTP429'})
        get.assert_not_called()
        self.assertEqual(result,{'reason':'HTTP429'})
        self.assertIsNone(ctx['pitreport'])

    def test_optional_comment_failure_keeps_source_wait_and_before_facts(self):
        ctx=context()
        wait=pilot.SourceWait('HTTP429','2030-04-01T01:50:00+00:00',state='SOURCE_WAIT')
        with patch.object(pilot,'get',side_effect=wait) as get, patch.object(pilot,'_clock',return_value=AT):
            result=pilot.collect_pitreport(ctx,date(2030,4,1))
        self.assertEqual(get.call_count,1)
        self.assertEqual(result['reason'],'HTTP429')
        self.assertEqual(ctx['beforeinfo']['status'],'PARSED')
        self.assertFalse(ctx['forecast_inputs_used'])

    def test_optional_comment_worker_handoff_returns_pause_without_losing_ready_pair(self):
        ctx=context()
        with patch.object(pilot,'get',side_effect=ValueError('WORKER_HANDOFF')), patch.object(pilot,'_clock',return_value=AT):
            result=pilot.collect_pitreport(ctx,date(2030,4,1))
        self.assertEqual(result['state'],'WORKER_HANDOFF')
        self.assertIsNone(result['retry_at'])
        self.assertEqual(ctx['beforeinfo']['status'],'PARSED')

    def test_output_supplement_does_not_claim_forecast_or_change_saved_model(self):
        ctx=context()
        with tempfile.TemporaryDirectory() as folder, patch.object(pilot,'OUTPUT',Path(folder)), patch.object(pilot,'supplemental_contexts',{RID:ctx},create=True):
            pilot.stop('PENDING_EXHIBITION')
            result=json.loads((Path(folder)/'national.json').read_text())
        self.assertEqual(result.get('supplemental_boat_observations'),[ctx])
        self.assertEqual(result['paired_forecasts'],[])
        self.assertEqual(result['paired_forecast_count'],0)

if __name__=='__main__':unittest.main()
