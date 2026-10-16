"""Literal-v2 result publication archives retain explicit selection during replay."""
import copy, unittest
from datetime import timedelta
from race_ai.name_bound_archive import build_archived_name_bound_cohort
from tests.test_name_bound_archive import archive_fixture,inventory,sha
from web import name_bound_result as labels
from web import race_contract as facts
from web.name_bound_evaluation import build_name_bound_evaluation

CONTRACT='official-result-dispositions/v2'

def fixture_v2():
    entry,now=archive_fixture(publication=True,day_offset=1,race_no=2)
    envelope=entry['result'];packet=envelope['receipt']['snapshot'];record=packet['result_record']
    record['result_disposition_contract']=CONTRACT
    record['data']['results'][5].update(finish=None,finish_status='エ')
    record['snapshot_id']=sha({k:v for k,v in record.items() if k not in facts.STORE_FIELDS})
    packet['snapshot_id']=sha({k:v for k,v in packet.items() if k!='snapshot_id'})
    envelope['finalization'].update(snapshot_id=packet['snapshot_id'],receipt_sha256=sha(envelope['receipt']))
    entry['request']['snapshot']=copy.deepcopy(packet)
    entry['manifest']['result_disposition_contract']=CONTRACT
    bundle=labels.result_bundle(envelope,entry['program'],entry['forecast'],now=now)
    entry['evaluation']=build_name_bound_evaluation(entry['forecast'],bundle,entry['program'],now)
    return inventory(entry),now

class ArchiveV2Tests(unittest.TestCase):
    def setUp(self):self.entry,self.now=fixture_v2()
    def test_old_and_v2_days_replay_without_mutation(self):
        old,_=archive_fixture();entries=[old,self.entry];before=copy.deepcopy(entries)
        try:report=build_archived_name_bound_cohort(entries,now=self.now+timedelta(days=3))
        except ValueError as error:self.fail('explicit v2 publication archive not supported: '+str(error))
        self.assertEqual(entries,before)
        self.assertEqual((report['race_count'],report['day_count']),(2,2))
        self.assertEqual(report['validation_status'],'UNVALIDATED')
        self.assertFalse(report['physical_exhibition_timing_verified'])
    def test_hidden_or_unknown_selection_cannot_replay_v2(self):
        for version in (None,False,'other'):
            bad=copy.deepcopy(self.entry)
            if version is None:bad['manifest'].pop('result_disposition_contract')
            else:bad['manifest']['result_disposition_contract']=version
            with self.subTest(version=version),self.assertRaises(ValueError):build_archived_name_bound_cohort([bad],now=self.now)
    def test_v2_selection_cannot_relabel_legacy_publication(self):
        old,now=archive_fixture(publication=True);old['manifest']['result_disposition_contract']=CONTRACT
        with self.assertRaises(ValueError):build_archived_name_bound_cohort([old],now=now)
    def test_read_only_manifest_cannot_claim_new_collection_mode(self):
        old,now=archive_fixture();old['manifest']['result_disposition_contract']=CONTRACT
        with self.assertRaises(ValueError):build_archived_name_bound_cohort([old],now=now)

if __name__=='__main__':unittest.main()
