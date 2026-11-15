"""Native archive recovery must retain authentic program names for new racers."""
from copy import deepcopy
from datetime import datetime
import unittest
from unittest.mock import patch

from race_ai import boat_all_model_cycle as E,boat_all_model_recovery as R
from race_ai.saved_view_feed import forecast_inventory
from tests import test_boat_name_aliases as aliases
from tests import test_boat_all_model_recovery as recovery
from tests import test_boat_all_model_cycle as models


class ProgramNameRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        aliases.ProgramNameAliasTests.setUpClass()
        cls.payload=aliases.ProgramNameAliasTests.payload
        cls.manifest=aliases.ProgramNameAliasTests.manifest
        cls.clock=aliases.ProgramNameAliasTests.clock

    def transport(self,payload,*,round_no=1,saved='2030-04-01T09:00:20Z'):
        fixture=recovery.ModelRecoveryTests('test_lost_first_round_is_recovered_when_only_second_round_reached_the_view')
        artifact=fixture.artifact(101,round_no,payload=payload,saved=saved)
        return fixture.transport(artifact)

    def test_real_encrypted_native_round_unblocks_B_abbreviation_for_a_missing_term_racer(self):
        base=E.project_round(self.payload,models.receipt(self.payload))
        source=self.manifest['b_sources'][0]
        for row in base['records']:
            row.update(prediction=None,comparison_predictions=[])
            for person in row['participants']:
                person.update(name='選手名字',name_source=dict(kind='SAME_RACE_PROGRAM',
                    registration_no=person['registration_no'],race_id=row['race_id'],
                    source_url=source['source_url'],source_sha256=source['source_sha256']))
        before=deepcopy(base);get=self.transport(self.payload)
        with patch.object(R,'_now',return_value=self.clock):
            output,counts=R.recover_saved_models(base,get,run_ids=[42],key=recovery.KEY,
                name_alias_sources=self.manifest)
        self.assertEqual(base,before)
        self.assertGreater(counts['appended_p1_forecasts'],0)
        self.assertEqual(output['records'][0]['participants'][0]['name'],'選手 1')
        self.assertEqual(output['records'][0]['participants'][0]['name_source']['kind'],'SAME_RACE_PROGRAM')
        self.assertTrue(any(s['participants']==before['records'][0]['participants'] for s in output['records'][0]['saved_participant_rosters']))
        self.assertTrue(output['records'][0]['official_name_aliases'])
        with patch.object(R,'_now',return_value=self.clock):
            replay,again=R.recover_saved_models(output,get,run_ids=[42],key=recovery.KEY,
                name_alias_sources=self.manifest)
        self.assertIs(replay,output)
        self.assertEqual(again['appended_forecasts'],0)

    def test_real_P0_archive_does_not_call_the_P1_program_alias_adapter(self):
        from tests.test_frozen_day_cycle import sample
        fixture=models.AllModelCycleTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        document,_,_=sample();prior=models.receipt(document,artifact=99,saved='2030-04-01T01:43:00Z')
        payload=E.forecast_saved_p0(document,prior,fixture.runtime(),now=datetime.fromisoformat('2030-04-01T01:44:00Z'))
        receipt=models.receipt(payload,saved='2030-04-01T01:44:05Z')
        base=E.project_round(payload,receipt)
        for row in base['records']:row.update(prediction=None,comparison_predictions=[])
        before=deepcopy(base);get=self.transport(payload,round_no=0,saved='2030-04-01T01:44:05Z')
        get.bodies['actions/runs/42']=recovery.wire(dict(recovery.api_run(),
            created_at='2030-04-01T01:40:00Z',updated_at='2030-04-01T01:44:06Z'))
        with patch.object(R,'_now',return_value=self.clock), \
             patch('race_ai.boat_name_aliases.build_program_name_aliases',side_effect=AssertionError('P0 is not a P1 input')):
            output,counts=R.recover_saved_models(base,get,run_ids=[42],key=recovery.KEY,name_alias_sources=self.manifest)
        self.assertEqual(base,before)
        self.assertGreater(counts['appended_p0_forecasts'],0)
        self.assertTrue(forecast_inventory(output))


if __name__=='__main__':unittest.main()
