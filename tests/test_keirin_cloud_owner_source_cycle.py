"""No real network: existing cloud cycle must keep private owner-source limits."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import os
import unittest

from scripts import keirin_cloud_pr71_state as cloud
from scripts.keirin_cloud_owner_inputs import PROFILE


class CloudOwnerSourceCycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.inbox=Path(self.tmp.name)/'inbox'; self.inbox.mkdir(mode=0o700)
        self.env={
            'GITHUB_ACTIONS':'true', 'GITHUB_REPOSITORY':cloud.REPO,
            'GITHUB_REPOSITORY_ID':cloud.REPOSITORY_ID,
            'GITHUB_REF':'refs/heads/main', 'GITHUB_EVENT_NAME':'schedule',
        }
        self.safe={'schema':'RACE_AI_KEIRIN_CLOUD_OWNER_SOURCE_CONNECTION_V1',
            'new_pre_race_inputs':0,'actual_four_model_forecast_saved':False,
            'provider_machine_rights_independently_verified':False,
            'history_races_processed':1,'races':[]}

    def test_no_opt_in_stays_offline_and_no_license_is_created(self):
        with patch.dict(os.environ,self.env,clear=True), patch(
            'scripts.keirin_cloud_owner_inputs.collect_owner_inputs') as collect:
            grant,stage,state=cloud._licensed_inputs(self.inbox,self.tmp.name)
        self.assertIsNone(grant); self.assertIsNone(stage)
        self.assertEqual(state,'SOURCE_FEED_NOT_CONFIGURED')
        collect.assert_not_called()

    def test_explicit_existing_owner_scope_calls_capture_but_not_model_or_license(self):
        with patch.dict(os.environ,{**self.env,'RACE_AI_OWNER_AUTO_SOURCE_PROFILE':PROFILE},clear=True), patch(
            'scripts.keirin_cloud_owner_inputs.collect_owner_inputs',return_value=self.safe) as collect:
            grant,stage,state=cloud._licensed_inputs(self.inbox,self.tmp.name)
        collect.assert_called_once_with(self.inbox,owner_auto_confirmed=True)
        self.assertIsNone(grant)
        self.assertEqual(stage['new_pre_race_inputs'],0)
        self.assertEqual(stage['owner_source_acquisition'],self.safe)
        self.assertEqual(state,'OWNER_ATTESTED_PARTIAL_SOURCE_COLLECTED')
        self.assertFalse((self.inbox/'pre').exists())
        self.assertFalse((self.inbox/'license').exists())

    def test_partial_owner_collection_cannot_execute_from_pr(self):
        for event,ref in [('pull_request','refs/pull/1/merge'),('push','refs/heads/main')]:
            with self.subTest(event=event),patch.dict(os.environ,
                {**self.env,'GITHUB_EVENT_NAME':event,'GITHUB_REF':ref,
                 'RACE_AI_OWNER_AUTO_SOURCE_PROFILE':PROFILE},clear=True),patch(
                    'scripts.keirin_cloud_owner_inputs.collect_owner_inputs') as collect:
                with self.assertRaises(cloud.ArchiveError):
                    cloud._licensed_inputs(self.inbox,self.tmp.name)
                collect.assert_not_called()

    def test_fully_configured_but_invalid_licensed_feed_never_falls_back(self):
        full={name:'not-valid-base64-or-license' for name in cloud.LICENSED_SOURCE_REQUIRED_KEYS}
        with patch.dict(os.environ,{**self.env,**full,
            'RACE_AI_OWNER_AUTO_SOURCE_PROFILE':PROFILE},clear=True),patch(
                'scripts.keirin_cloud_owner_inputs.collect_owner_inputs') as collect:
            with self.assertRaises(cloud.ArchiveError):
                cloud._licensed_inputs(self.inbox,self.tmp.name)
            collect.assert_not_called()

    def test_partial_source_is_not_a_production_archive_genesis(self):
        stage={'new_pre_race_inputs':0,'owner_source_acquisition':self.safe}
        with patch.dict(os.environ,{**self.env,'RACE_AI_STATE_KEY':'configured-test-placeholder'},clear=True),patch.object(
            cloud,'check_owner_cipher_consent',return_value=True),patch.object(
            cloud,'restore',return_value=(None,None)),patch.object(
            cloud,'_licensed_inputs',return_value=(None,stage,'OWNER_ATTESTED_PARTIAL_SOURCE_COLLECTED')),patch.object(
            cloud,'commit') as commit:
            report=cloud.cycle(self.tmp.name,self.tmp.name)
        self.assertEqual(report['state'],'HOLD_OWNER_SOURCE_PARTIAL_NO_COMPLETE_PR71_INPUT')
        self.assertEqual(report['new_forecasts'],0)
        self.assertEqual(report['owner_source_acquisition'],self.safe)
        self.assertEqual(report['missing_source_config_keys'],[])
        self.assertEqual(cloud.missing_source_configuration(
            source_state='OWNER_ATTESTED_PARTIAL_SOURCE_COLLECTED'),[])
        self.assertEqual(len(cloud.missing_source_configuration(self.env)),4)
        commit.assert_not_called()

if __name__=='__main__':
    unittest.main()
