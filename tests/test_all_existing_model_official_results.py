"""Authored JRA HTML and actual AES/ZIP admission; no network or real key."""
from copy import deepcopy
from datetime import timedelta
import base64
import hashlib
import io
import json
import unittest
import zipfile

from race_ai.actions_contract import digest
from race_ai import all_existing_model_official_results as results
from race_ai.boat_all_model_store import seal_forecasts
from race_ai.manual_official_capture import official_rights_ref
from tests import test_jra_official_result_adapter as fixture

KEY=bytes(range(32))
HEAD='a'*40


class OfficialResultsArchiveTests(unittest.TestCase):
    def setUp(self):
        from race_ai.jra_official_result_adapter import parse_result
        self.native=fixture.frozen();self.raw=fixture.result_html();self.meta=fixture.source_metadata(self.raw)
        self.generated=fixture.NOW;self.now=self.generated+timedelta(seconds=10)
        self.observation=parse_result(self.raw,self.meta,frozen_native_payload=self.native,now=self.generated,
            source_rights_ref=official_rights_ref('horse'))
        self.capture=dict(raw_base64=base64.b64encode(self.raw).decode(),metadata=deepcopy(self.meta))

    def payload(self,captures=None,observations=None,**changes):
        value=results.build_result_payload([self.capture] if captures is None else captures,
            [self.observation] if observations is None else observations,run_id=42,code_sha=HEAD,
            generated_at=self.generated,day_jst='2026-11-07',frozen_native_payloads=[self.native])
        value.update(changes);return value

    def archive(self,payload=None,*,run_id='42',round_no=1,members=None):
        payload=self.payload() if payload is None else payload
        cipher=seal_forecasts(payload,run_id=run_id,round_no=round_no,key=KEY)
        body=io.BytesIO()
        with zipfile.ZipFile(body,'w',zipfile.ZIP_DEFLATED) as archive:
            for name,raw in [('results.enc',cipher)] if members is None else members:
                archive.writestr(name,raw)
        raw=body.getvalue()
        metadata=dict(id=801,name='all-existing-official-results-42-1',expired=False,size_in_bytes=len(raw),
            digest='sha256:'+hashlib.sha256(raw).hexdigest(),created_at=(self.generated+timedelta(seconds=2)).isoformat(),
            expires_at=(self.generated+timedelta(days=7)).isoformat(),workflow_run=dict(id=42,head_sha=HEAD,
                repository_id=1416489937,head_repository_id=1416489937))
        return raw,metadata

    def read(self,payload=None,*,metadata_change=None,key=KEY,frozen=None):
        raw,metadata=self.archive(payload)
        metadata.update(metadata_change or {})
        return results.observations_from_official_result_artifact(raw,metadata,now=self.now,
            expected_run_id=42,expected_head_sha=HEAD,frozen_native_payloads=[self.native] if frozen is None else frozen,key=key)

    def test_native_result_replays_independently_and_only_cipher_counts_receipt_are_public(self):
        payload=self.payload();before=deepcopy(payload)
        cipher=results.seal_results(payload,round_no=1,frozen_native_payloads=[self.native],key=KEY)
        self.assertIsInstance(cipher,bytes);self.assertNotIn(self.raw,cipher)
        value=self.read(payload)
        self.assertEqual(value['observations'],[self.observation]);self.assertEqual(payload,before)
        summary=value['summary'];self.assertEqual(summary['ordinary_settled_result_count'],1)
        self.assertTrue(summary['authenticated_encrypted_result_artifact'])
        self.assertFalse(summary['production_promoted'])
        public=json.dumps([summary,value['receipt']])
        for private in ('ordered_top3','raw_base64','captured_at','roster',fixture.URL):self.assertNotIn(private,public)

    def test_raw_body_hash_actual_capture_clock_status_and_host_are_bound(self):
        for field,value in (('source_sha256','f'*64),('byte_count',1),('status',403),
                            ('source_url','https://untrusted.invalid/result'),
                            ('response_received_at',(self.generated+timedelta(seconds=1)).isoformat())):
            capture=deepcopy(self.capture);capture['metadata'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.payload([capture])

    def test_self_hashed_false_teacher_or_source_binding_cannot_replace_parser_replay(self):
        for field,value in (('ordered_top3',[1,2,3]),('payout_per_100_yen',9999),('roster',{'1':'invented'}),
                            ('identity_verified',False),('source_sha256','f'*64),('reason','INVENTED'),
                            ('source_rights_ref','arbitrary-training-grant')):
            observation=deepcopy(self.observation);observation[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.payload(observations=[observation])

    def test_unknown_payload_fields_or_schema_and_changed_run_head_round_are_rejected(self):
        baseline=self.payload()
        for change in ({'extra':1},{'schema':'BOAT_OLD_RESULT'},{'run_id':43},{'code_sha':'b'*40},
                       {'generated_at':(self.generated+timedelta(days=1)).isoformat()}):
            payload=deepcopy(baseline);payload.update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):self.read(payload)
        for run,round_no in (('43',1),('42',2)):
            raw,metadata=self.archive(run_id=run,round_no=round_no)
            with self.subTest(run=run,round_no=round_no),self.assertRaises(ValueError):
                results.observations_from_official_result_artifact(raw,metadata,now=self.now,
                    expected_run_id=42,expected_head_sha=HEAD,frozen_native_payloads=[self.native],key=KEY)

    def test_actual_metadata_digest_repo_head_save_expiry_and_wrong_key_reject(self):
        for change in ({'digest':'sha256:'+'0'*64},{'expired':True},{'size_in_bytes':1},
                       {'name':'all-existing-official-results-42-0'},
                       {'created_at':(self.generated-timedelta(seconds=2)).isoformat()},
                       {'expires_at':self.now.isoformat()}):
            with self.subTest(change=change),self.assertRaises(ValueError):self.read(metadata_change=change)
        raw,metadata=self.archive()
        for field,value in (('head_sha','b'*40),('repository_id',1),('head_repository_id',1),('id',43)):
            changed=deepcopy(metadata);changed['workflow_run'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                results.observations_from_official_result_artifact(raw,changed,now=self.now,
                    expected_run_id=42,expected_head_sha=HEAD,frozen_native_payloads=[self.native],key=KEY)
        with self.assertRaises(ValueError):self.read(key=bytes(reversed(range(32))))

    def test_full_frozen_race_roster_cutoff_and_snapshot_duplicates_must_match(self):
        for kind in ('roster','race','cutoff'):
            native=deepcopy(self.native)
            if kind=='roster':native['snapshot']['participants'][0]['identity']='jra:9999999999'
            elif kind=='race':native['snapshot']['race']['race_id']='horse:2026-11-07:jra-03:10'
            else:native['snapshot']['race']['sales_cutoff_at']='2026-11-07T15:18:00+09:00'
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.read(frozen=[native])
        self.assertEqual(self.read(frozen=[self.native,deepcopy(self.native)])['observations'],[self.observation])
        changed=deepcopy(self.native);changed['snapshot']['race']['as_of']='2026-11-07T01:11:00+00:00'
        with self.assertRaises(ValueError):self.read(frozen=[self.native,changed])

    def test_only_exact_results_cipher_member_is_accepted(self):
        cipher=results.seal_results(self.payload(),round_no=1,frozen_native_payloads=[self.native],key=KEY)
        for members in ([('other.enc',cipher)],[('results.enc',cipher),('raw.html',self.raw)],
                        [('folder/results.enc',cipher)]):
            raw,metadata=self.archive(members=members)
            with self.subTest(members=[x[0] for x in members]),self.assertRaises(ValueError):
                results.observations_from_official_result_artifact(raw,metadata,now=self.now,
                    expected_run_id=42,expected_head_sha=HEAD,frozen_native_payloads=[self.native],key=KEY)

    def test_pending_and_special_revisions_are_retained_without_ordinary_losses(self):
        from race_ai.jra_official_result_adapter import parse_result
        for raw,expected in ((fixture.result_html(table=False),'pending'),
                             (fixture.result_html(places=('1','1','3')),'special')):
            metadata=fixture.source_metadata(raw)
            metadata.update(fetched_at='2026-11-07T07:00:28+00:00',response_received_at='2026-11-07T07:00:30+00:00')
            capture=dict(raw_base64=base64.b64encode(raw).decode(),metadata=metadata)
            observation=parse_result(raw,metadata,frozen_native_payload=self.native,now=self.generated,
                source_rights_ref=official_rights_ref('horse'))
            payload=self.payload([self.capture,capture],[self.observation,observation])
            value=self.read(payload)
            self.assertEqual(value['observations'],[observation])
            self.assertEqual(value['summary']['ordinary_settled_result_count'],0)
            self.assertEqual(value['summary'][expected+'_result_count'],1)
            self.assertTrue(value['summary']['missing_results_are_not_losses'])

    def test_duplicate_capture_and_result_never_expand_teacher_cohort(self):
        value=self.read(self.payload([self.capture,deepcopy(self.capture)],
            [self.observation,deepcopy(self.observation)]))
        self.assertEqual(len(value['observations']),1)
        self.assertEqual(value['summary']['unique_revision_count'],1)
        self.assertEqual(value['summary']['duplicate_revision_count'],1)


if __name__=='__main__':unittest.main()
