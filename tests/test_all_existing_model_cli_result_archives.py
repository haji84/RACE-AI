"""Encrypted input + separate encrypted official-result admission into fitting."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import io,json
from pathlib import Path
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai.boat_active_exhibition import parse_active_beforeinfo
from race_ai.boat_private_original_archive import seal_original_zip
from race_ai.boat_venue_learning import read_candidate
from scripts import all_existing_model_learning as cli
from tests import test_all_existing_model_round_intake as native
from tests import test_all_existing_model_result_intake as result_fixture
from tests.test_boat_active_exhibition import program,main_table,start_table
from tests.test_boat_observation_context import frame,url
from tests.test_frozen_day_cycle import observation
from tests.test_boat_venue_research import personal_data,SOURCE,CONTENT
from tests.test_boat_venue_learning import POINTER

class CliResultArchiveTests(unittest.TestCase):
    def setUp(self):
        native.RoundIntakeTests.setUpClass()
        self.case=native.RoundIntakeTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.root=self.case.root
        card=program(withdrawn=())
        raw=frame(main_table()+start_table(lanes=(1,2,3,4,5,6)))
        before=parse_active_beforeinfo(raw,program=card,source_url=url(),captured_at=native.fixtures.ASOF)
        ctx=json.loads(json.dumps(dict(program=card,beforeinfo=before,as_of=native.fixtures.ASOF)).replace(
            '2030-04-01','2030-04-02').replace('20300401','20300402'))
        self.asof=datetime.fromisoformat(ctx['as_of'])
        payload=native.engine.forecast_round([ctx],self.case.runtime(),now=self.asof+timedelta(seconds=10))
        self.input_raw,self.input_meta=self.case.artifact(payload,saved=(self.asof+timedelta(seconds=20)).isoformat())
        capsule=payload['native_input_capsules'][0]
        group=next(iter(capsule['native_inputs']));mid=capsule['group_model_ids'][group][0]
        info=native.registry.identity(mid,'boat',capsule['native_inputs'][group])
        cutoff=datetime.fromisoformat(info['race_cutoff_at'])
        observed=observation(dict(race_id=info['race_id'],cutoff_at=info['race_cutoff_at'],
            top8=[[1,2,3]],roster=info['roster']))
        day=ctx['program']['race_id'][:8];venue=ctx['program']['race_id'][9:11];race=int(ctx['program']['race_id'][12:])
        observed.update(captured_at=(cutoff+timedelta(minutes=5)).isoformat(),closed_at=info['race_cutoff_at'],
            source_url=f'https://www.boatrace.jp/owpc/pc/race/raceresult?hd={day}&jcd={venue}&rno={race}',
            kind='raceresult',information_phase='official_result',upstream_published_at=None)
        report=dict(schema='RACE_AI_EXISTING_MODEL_CYCLE_REPORT_V1',day_jst='2030-04-02',run_id='42',
            code_sha=native.fixtures.HEAD,updated_at=(cutoff+timedelta(minutes=6)).isoformat(),
            result_observation_versions=1,actual_purchases=False)
        report['report_sha256']=digest(report)
        inner=result_fixture.packed([('official-result-observations.json',json.dumps([observed])),('status.json',json.dumps(report))])
        cipher=seal_original_zip(inner,run_id=42,head_sha=native.fixtures.HEAD,kind='RESULT',key=native.KEY)
        self.result_raw=result_fixture.packed([('private-original.enc',cipher)])
        self.result_meta=dict(self.input_meta,id=202,name='race-existing-cycle-42-cycle-02',
            created_at=(cutoff+timedelta(minutes=7)).isoformat(),size_in_bytes=len(self.result_raw),
            digest='sha256:'+sha256(self.result_raw).hexdigest())
        self.now=cutoff+timedelta(hours=1)
        self.inpath=self.archive('native',self.input_raw,self.input_meta)
        self.resultpath=self.archive('result',self.result_raw,self.result_meta)
        self.dataset=self.root/'dataset.json';self.dataset.write_text(json.dumps(POINTER))
        self.oldrows,self.oldresults=personal_data(8)
        self.metadata={self.input_meta['id']:self.input_meta,self.result_meta['id']:self.result_meta}
    def archive(self,name,raw,metadata):
        root=self.root/name;root.mkdir(mode=0o700)
        for file,data in (('archive.zip',raw),('metadata.json',json.dumps(metadata).encode())):
            path=root/file;path.write_bytes(data);path.chmod(0o600)
        return root
    def source(self):return deepcopy((self.oldrows,self.oldresults,SOURCE,CONTENT))
    def external(self,url):return deepcopy(self.metadata[int(url.rsplit('/',1)[1])])
    def test_exact_frozen_native_and_separate_result_archives_enter_new_scope_and_fit(self):
        decision=self.root/'new-owner.json';out=self.root/'fit'
        args=['--restored-dir','unused','--state-input','unused','--dataset-input',str(self.dataset),
            '--derive-from-observed','--native-round-archive-dir',str(self.inpath),
            '--result-archive-dir',str(self.resultpath),'--owner-research-record',str(decision),'--out-dir',str(out)]
        for command in ('issue-decision','fit'):
            public=io.StringIO()
            with patch.object(cli,'load_verified_intake',side_effect=lambda *a,**k:self.source()), \
                 patch.object(cli,'_github_json',side_effect=self.external),redirect_stdout(public):
                code=cli.main([command,*args],now=self.now)
            self.assertEqual(code,0,public.getvalue())
        summary=json.loads(public.getvalue());actual=read_candidate(out)
        self.assertEqual(summary['result_archive_count'],1)
        self.assertEqual(summary['native_archive_count'],1)
        self.assertGreater(summary['native_admitted_records'],0)
        self.assertEqual(summary['fitted_model_count'],9)
        self.assertTrue(actual['training']['result_archive_admissions_sha256'])
        self.assertTrue(summary['encrypted_readback_verified'])
    def test_timezone_alias_conflicts_are_rejected_in_both_archive_orders(self):
        original=result_fixture.settled()
        conflicting=deepcopy(original)
        conflicting['captured_at']=datetime.fromisoformat(original['captured_at']).astimezone(
            __import__('datetime').timezone.utc).isoformat().replace('+00:00','Z')
        conflicting['source_sha256']='b'*64
        conflicting['data']['payouts'][0]['payout_per_100_yen']+=100
        # Both observations are independently admissible encrypted archives;
        # the cross-archive union must not let order decide the teacher label.
        for value in (original,conflicting):
            raw,meta,_,_=result_fixture.fixture([value])
            result_fixture.intake.observations_from_result_artifact(raw,meta,now=result_fixture.NOW,
                expected_run_id=99,expected_head_sha=result_fixture.HEAD)
        for values in ((original,conflicting),(conflicting,original)):
            with self.assertRaisesRegex(ValueError,'CONFLICTING_REVISIONS'):
                cli._merge_verified_result_observations(values)
        same=deepcopy(original);same['captured_at']=conflicting['captured_at']
        self.assertEqual(len(cli._merge_verified_result_observations([original,same])),1)
        self.assertEqual(cli._merge_verified_result_observations([original,same]),
                         cli._merge_verified_result_observations([same,original]))

    def test_equivalent_offset_clocks_merge_without_rewriting_original_bytes(self):
        original=result_fixture.settled();offset=deepcopy(original)
        for field in ('captured_at','available_at','published_at','upstream_published_at','closed_at'):
            if offset.get(field) is not None:
                offset[field]=datetime.fromisoformat(offset[field].replace('Z','+00:00')).astimezone(
                    timezone(timedelta(hours=9))).isoformat()
        first=cli._merge_verified_result_observations([original,offset])
        second=cli._merge_verified_result_observations([offset,original])
        self.assertEqual(first,second);self.assertEqual(len(first),1)
        self.assertIn(first[0],[original,offset])

    def test_cached_result_receipt_must_match_independent_github_metadata(self):
        self.metadata[202]=dict(self.result_meta,digest='sha256:'+'0'*64)
        with patch.object(cli,'load_verified_intake',side_effect=lambda *a,**k:self.source()), \
             patch.object(cli,'_github_json',side_effect=self.external),self.assertRaisesRegex(ValueError,'ACTUAL_METADATA_MISMATCH'):
            cli.load_intake('unused','unused',self.dataset,now=self.now,result_archive_dirs=[self.resultpath])

    def test_already_frozen_native_slots_keep_their_exact_bytes_before_optional_derivation(self):
        from race_ai.all_existing_model_result_intake import observations_from_result_artifact
        from race_ai.all_existing_model_round_intake import records_from_round_artifact
        observations=observations_from_result_artifact(self.result_raw,self.result_meta,now=self.now,
            expected_run_id=42,expected_head_sha=native.fixtures.HEAD)['observations']
        frozen=records_from_round_artifact(self.input_raw,self.input_meta,observations,now=self.now,
            expected_run_id=42,expected_head_sha=native.fixtures.HEAD)['records']
        with patch.object(cli,'load_verified_intake',side_effect=lambda *a,**k:self.source()), \
             patch.object(cli,'_github_json',side_effect=self.external):
            records,_,intake=cli.load_intake('unused','unused',self.dataset,now=self.now,
                derive_observed=True,native_round_archive_dirs=[self.inpath],result_archive_dirs=[self.resultpath])
        self.assertTrue(frozen);self.assertGreater(intake['derived_native_slots_preserved'],0)
        for record in frozen:
            self.assertIn(record,records)
            self.assertNotIn('input_derivation',record)

if __name__=='__main__':unittest.main()
