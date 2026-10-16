"""Explicit v2 selection and full normalized backup replay with controlled transport."""
import copy,hashlib,inspect,json
import unittest
from unittest.mock import patch
import tests.test_name_bound_result_caller as old
from web import name_bound_result as contract
from web.name_bound_evaluation import build_name_bound_evaluation
from web.race_contract import canonical

CONTRACT='official-result-dispositions/v2'

class ResultCallerV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        old.ResultCallerTests.setUpClass.__func__(cls)
    def setUp(self):
        self.assertIn('result_disposition_contract',inspect.signature(self.c.run).parameters,
            'explicit publication selection required')
        old.ResultCallerTests.setUp(self)
        packet=self.result['receipt']['snapshot'];record=packet['result_record']
        record['result_disposition_contract']=CONTRACT
        record['data']['results'][5].update(finish=None,finish_status='エ')
        record['snapshot_id']=hashlib.sha256(canonical({k:v for k,v in record.items() if k not in {'snapshot_id','saved_at','storage_eligible_pre_race'}})).hexdigest()
        packet['snapshot_id']=contract.digest({k:v for k,v in packet.items() if k!='snapshot_id'})
        self.result['finalization'].update(snapshot_id=packet['snapshot_id'],receipt_sha256=contract.digest(self.result['receipt']))
        contract.validate_name_bound_result_envelope(self.result,self.race,self.forecast,now=self.now)
        self.report=build_name_bound_evaluation(self.forecast,contract.result_bundle(self.result,self.race,self.forecast,now=self.now),self.race,self.now)
        import api.name_bound_result_store as store
        self.meta=dict(store.metadata(self.result,self.race),commit_sha=old.COMMIT)
        self.bodies[3:]=[self.meta,self.result,self.report]
        self.v2=self.stack.enter_context(patch.object(self.c,'collect_name_bound_result_v2',side_effect=self.collect.side_effect))
    def run_v2(self):
        return self.c.run(self.race['race_id'],self.fid,self.folder,execute=True,result_disposition_contract=CONTRACT)
    def test_v2_full_pipeline_has_exact_bounds_and_full_backup_replay(self):
        manifest=self.run_v2()
        self.assertEqual(manifest['status'],'COMPLETED')
        self.assertEqual(manifest['result_disposition_contract'],CONTRACT)
        self.assertEqual((manifest['reads_used'],manifest['posts_attempted'],manifest['official_source_requests']),(5,1,1))
        self.collect.assert_not_called();self.v2.assert_called_once()
        request=json.loads((self.folder/'request.json').read_bytes())
        self.assertEqual(request['snapshot']['result_record']['result_disposition_contract'],CONTRACT)
        self.c.verify_backups(self.folder,manifest)
    def test_default_cannot_publish_a_v2_source_packet(self):
        manifest=self.c.run(self.race['race_id'],self.fid,self.folder,execute=True)
        self.assertEqual((manifest['status'],manifest['posts_attempted']),('STOPPED',0))
        self.v2.assert_not_called()
    def test_unknown_version_stops_before_auth_directory_or_source(self):
        with self.assertRaises(ValueError):
            self.c.run(self.race['race_id'],self.fid,self.folder,execute=True,result_disposition_contract='other')
        self.session.assert_not_called();self.collect.assert_not_called();self.v2.assert_not_called()
        self.assertFalse(self.folder.exists())
    def test_existing_v2_label_stops_without_source_or_post(self):
        self.opener.bodies[2]=self.result;self.current[0]=self.now
        manifest=self.run_v2()
        self.assertEqual((manifest['status'],manifest['reads_used'],manifest['posts_attempted'],manifest['official_source_requests']),('STOPPED',3,0,0))
        self.collect.assert_not_called();self.v2.assert_not_called()
    def test_v2_backup_cannot_hide_or_change_selected_contract(self):
        manifest=self.run_v2()
        self.assertEqual(manifest['status'],'COMPLETED')
        for version in (None,'other',False):
            bad=copy.deepcopy(manifest)
            if version is None:bad.pop('result_disposition_contract')
            else:bad['result_disposition_contract']=version
            (self.folder/'manifest.json').write_bytes(canonical(bad))
            with self.subTest(version=version),self.assertRaises(ValueError):self.c.verify_backups(self.folder,bad)

if __name__=='__main__':unittest.main()
