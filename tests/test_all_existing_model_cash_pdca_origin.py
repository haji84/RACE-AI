"""Archived synthetic forecasts authenticate after results; no new fit per case."""
import base64
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import importlib
from functools import lru_cache
import io
import json
import os
import unittest
from unittest.mock import patch
import zipfile

from race_ai.actions_contract import digest
from race_ai import boat_all_model_store as store
from race_ai import all_existing_model_future_baseline as baseline
from race_ai.all_existing_model_pairs import make_private_pairs,record_partition_key
from race_ai.all_existing_model_receipt import _verified_private_pairs_artifact
from scripts import all_existing_model_native_future as future
from tests import test_all_existing_model_native_future as boat
from tests.test_all_existing_model_native_future_v3 import KEY,NOW,metadata
from tests import test_all_existing_model_native_future_v4 as nineteen


def api(test):
    spec=importlib.util.find_spec('race_ai.all_existing_model_cash_pdca_origin')
    test.assertIsNotNone(spec,'archive-only cash PDCA origin reader is missing')
    return importlib.import_module('race_ai.all_existing_model_cash_pdca_origin').verify_origin_artifact


def zipped_members(members):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,raw in sorted(members.items()):archive.writestr(name,raw)
    return out.getvalue()


class CashOriginKeyTests(unittest.TestCase):
    def test_owner_key_is_required_before_untrusted_archive_parsing(self):
        verify=api(self)
        with patch.dict(os.environ,RACE_AI_STATE_KEY=''),self.assertRaises(ValueError):
            verify(None,None,None,None,None,None,now=NOW,candidate_cell_count=19)


@lru_cache(maxsize=1)
def _future_fixture():
    nineteen.NineteenFutureTests.setUpClass()
    fixture=nineteen.NineteenFutureTests('test_real_nineteen_fit_fresh_attachment_encrypted_pairs_and_origin_actual_readback')
    fixture.setUp()
    try:
        # Author the future JRA identity before the sole source/forecast freeze.
        # This is synthetic input construction, never a rewrite of saved data.
        old_metadata=json.loads(fixture.mapping['actions/artifacts/100'])
        _,old_records=_verified_private_pairs_artifact(fixture.mapping['actions/artifacts/100/zip'],old_metadata,
            now=NOW,expected_run_id=8,expected_head_sha='c'*40)
        carrier=dict(training=old_records[0]['training'],receipt=old_records[0]['training_receipt'])
        for request in fixture.requests:
            if not request['cell_key'].startswith('horse/'):continue
            native=deepcopy(request['native_payload']);proof=native.pop('baseline_attachment',None)
            native.pop('learned_model',None);snapshot=native['snapshot']
            snapshot['race'].update(race_id='horse:2030-02-02:jra-03:11',venue='福島',event_date_jst='2030-02-02')
            for participant in snapshot['participants']:
                participant['identity']='jra:202000000'+str(participant['number'])
            request['native_payload']=(baseline.attach(native,fixture.baseline,sport='horse',
                source_metadata=proof['source_metadata'],now=future.future.stamp(proof['attached_at'])) if proof else native)
        source=fixture.temp/'jra-source'
        make_private_pairs(carrier,fixture.requests,source,now=NOW-timedelta(minutes=2),allow_source=lambda *_:True)
        (source/'summary.json').unlink();source_raw=boat.zipped(source)
        actual=dict(old_metadata,size_in_bytes=len(source_raw),digest='sha256:'+sha256(source_raw).hexdigest())
        fixture.mapping['actions/artifacts/100']=json.dumps(actual).encode()
        fixture.mapping['actions/artifacts/100/zip']=source_raw
        fixture.manifest['source_input_artifacts'][0]['digest']=actual['digest']
        result=future.generate(fixture.manifest,fixture.root,fixture.env)
        if result.get('forecast_partition_count')!=19:raise AssertionError(result)
        native_raw=boat.zipped(fixture.root)
        origin_raw=boat.zipped(fixture.root.with_name(fixture.root.name+'.origin'))
        native_metadata=metadata(201,'all-existing-model-pairs-42-900004',native_raw,
            saved=NOW+timedelta(seconds=2),head='d'*40)
        origin_metadata=metadata(202,'all-native-future-origin-42-900010',origin_raw,
            saved=NOW+timedelta(seconds=3),head='d'*40)
        now=NOW+timedelta(hours=2)
        admission,records=_verified_private_pairs_artifact(native_raw,native_metadata,
            now=now,expected_run_id=42,expected_head_sha='d'*40)
        with zipfile.ZipFile(io.BytesIO(origin_raw)) as archive:
            bundle=store.open_forecasts(archive.read('origin.enc'),key=KEY)
        return dict(native_raw=native_raw,native_metadata=native_metadata,origin_raw=origin_raw,
            origin_metadata=origin_metadata,admission=admission,records=records,bundle=bundle,
            mapping=deepcopy(fixture.mapping),now=now,generated_at=NOW)
    finally:fixture.doCleanups()


def future_fixture():
    """Independent originals in RAM only; callers receive isolated copies."""
    return deepcopy(_future_fixture())


class CashOriginArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture=future_fixture()
        for key in ('native_raw','native_metadata','origin_raw','origin_metadata','admission','records','bundle'):
            setattr(cls,key,fixture[key])
        cls.after_results=fixture['now']
    def setUp(self):
        key=patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(KEY).decode())
        key.start();self.addCleanup(key.stop)
    def verify(self,**changes):
        values=dict(origin_raw=self.origin_raw,origin_metadata=deepcopy(self.origin_metadata),
            native_raw=self.native_raw,native_metadata=deepcopy(self.native_metadata),
            admission=deepcopy(self.admission),records=self.records,now=self.after_results,candidate_cell_count=19)
        values.update(changes)
        return api(self)(**values)
    def reseal(self,bundle):
        cipher=store.seal_forecasts(bundle,run_id='42',round_no=900010,key=KEY)
        raw=zipped_members({'origin.enc':cipher})
        return raw,dict(self.origin_metadata,size_in_bytes=len(raw),digest='sha256:'+sha256(raw).hexdigest())
    def subset(self,records):
        prefixes={record_partition_key(record)+'/' for record in records}
        with zipfile.ZipFile(io.BytesIO(self.native_raw)) as archive:
            members={entry.filename:archive.read(entry) for entry in archive.infolist()
                if any(entry.filename.startswith(prefix) for prefix in prefixes)}
        raw=zipped_members(members);actual=dict(self.native_metadata,size_in_bytes=len(raw),digest='sha256:'+sha256(raw).hexdigest())
        bundle=deepcopy(self.bundle);generation=bundle['generation'];audit=bundle['source_audit']
        cells={record['cell_key'] for record in records};sports={record['pair']['sport'] for record in records}
        counts={sport:sum(record['pair']['sport']==sport for record in records) for sport in future.V4_CELLS}
        capsules=[cap for record in records for cap in record.get('captured_native_inputs',[])]
        audit['capsules']=deepcopy(capsules)
        audit['original_source_partitions']=[entry for entry in audit['original_source_partitions']
            if any(entry['cell_key']==cap['cell_key'] and entry['input_sha256']==cap['input_sha256'] for cap in capsules)]
        audit['selected_cases']=[case for case in audit['selected_cases'] if case['sport'] in sports]
        clocks,unknown=future._retained_source_clocks([dict(cell_key=cap['cell_key'],native_payload=cap['native_payload'])
            for cap in capsules],future.future.stamp(audit['selected_at']))
        audit.update(retained_source_clocks=clocks,source_capture_clock_missing_count=unknown)
        generation.update(source_audit_sha256=digest(audit),local_record_sha256=sorted(digest(record) for record in records),
            local_member_sha256={name:sha256(body).hexdigest() for name,body in members.items()},
            forecast_counts_by_sport=counts,all_nineteen_cells_produced=len(records)==19,
            forecast_partition_count=len(records),baseline_forecast_count=len(records),learned_forecast_count=len(records),
            captured_native_input_count=len(capsules),held_sports={sport:dict(reason='HOLD_SYNTHETIC_SOURCE_UNAVAILABLE',
                not_generated_cells=sorted(future.V4_CELLS[sport]),unavailable_source_cells=sorted(future.V4_CELLS[sport]))
                for sport in future.V4_CELLS if sport not in sports})
        generation['ranker_comparisons']={sport:value for sport,value in generation['ranker_comparisons'].items() if sport in sports}
        generation['owner_generation_mac']=future._generation_mac_v3(generation)
        origin_raw,origin_meta=self.reseal(bundle)
        admission=dict(self.admission,artifact_digest=actual['digest'],record_sha256=sorted(digest(record) for record in records),
            partition_count=len(records),forecast_partition_count=len(records),baseline_forecast_count=len(records),
            learned_forecast_count=len(records),captured_native_input_count=len(capsules),cell_count=len(cells),
            cell_forecast_counts={cell:1 for cell in cells},unique_races=len(sports))
        return dict(native_raw=raw,native_metadata=actual,admission=admission,records=records,
            origin_raw=origin_raw,origin_metadata=origin_meta)
    def test_original_owner_source_and_member_bytes_authenticate_after_results_without_runtime(self):
        before=digest(self.records);result=self.verify()
        self.assertEqual(digest(self.records),before)
        self.assertEqual(result['manifest'],self.bundle['manifest'])
        self.assertEqual(result['source_audit'],self.bundle['source_audit'])
        self.assertEqual(result['summary']['forecast_partition_count'],19)
        self.assertTrue(result['summary']['independent_origin_receipt_verified'])
        self.assertTrue(result['summary']['original_owner_research_record_verified'])
        self.assertEqual(result['summary']['forecast_counts_by_sport'],dict(boat=14,horse=5))
        self.assertFalse(result['summary']['current_training_admission_created'])
        self.assertFalse(result['summary']['raw_source_documents_replayed'])
        self.assertFalse(result['summary']['baseline_full_training_replayed'])
    def test_wrong_origin_metadata_and_late_original_saves_reject(self):
        for field,value in (('name','all-native-future-origin-42-900011'),('expired',True),
                ('digest','sha256:'+'f'*64),('size_in_bytes',len(self.origin_raw)+1),
                ('created_at',(NOW+timedelta(minutes=40)).isoformat())):
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.verify(origin_metadata=dict(self.origin_metadata,**{field:value}))
        for field,value in (('id',43),('head_sha','e'*40),('repository_id',1),('head_repository_id',1)):
            wrong=dict(self.origin_metadata,workflow_run=dict(self.origin_metadata['workflow_run'],**{field:value}))
            with self.subTest(field=field),self.assertRaises(ValueError):self.verify(origin_metadata=wrong)
    def test_origin_mac_owner_and_source_capsule_tampering_rejects(self):
        for field in ('mac','owner','source_capsule','original_generation'):
            bundle=deepcopy(self.bundle)
            if field=='mac':bundle['generation']['owner_generation_mac']='0'*64
            elif field=='owner':bundle['source_audit']['owner_research_record']['mac']='0'*64
            elif field=='source_capsule':bundle['source_audit']['capsules'][0]['input_sha256']='f'*64
            else:bundle['source_audit']['original_source_partitions'][0]['original_generated_at']=(NOW+timedelta(hours=1)).isoformat()
            if field!='mac':
                bundle['generation']['source_audit_sha256']=digest(bundle['source_audit'])
                bundle['generation']['owner_generation_mac']=future._generation_mac_v3(bundle['generation'])
            raw,actual=self.reseal(bundle)
            with self.subTest(field=field),self.assertRaises(ValueError):self.verify(origin_raw=raw,origin_metadata=actual)
    def test_native_member_replacement_and_wrong_candidate_scope_reject(self):
        with zipfile.ZipFile(io.BytesIO(self.native_raw)) as archive:
            members={entry.filename:archive.read(entry) for entry in archive.infolist()}
        name=next(name for name in members if name.endswith('summary.json'));members[name]+=b'\n'
        raw=zipped_members(members);actual=dict(self.native_metadata,size_in_bytes=len(raw),digest='sha256:'+sha256(raw).hexdigest())
        with self.assertRaisesRegex(ValueError,'NATIVE_MEMBER_BYTES'):
            self.verify(native_raw=raw,native_metadata=actual,admission=dict(self.admission,artifact_digest=actual['digest']))
        with self.assertRaises(ValueError):self.verify(candidate_cell_count=30)
    def test_complete_partial_sport_is_explicitly_bound_without_claiming_all_nineteen(self):
        records=[record for record in self.records if record['pair']['sport']=='boat']
        context=self.verify(**self.subset(records))
        self.assertEqual(context['summary']['forecast_partition_count'],14)
        self.assertEqual(context['summary']['forecast_counts_by_sport'],dict(boat=14,horse=0))
        self.assertFalse(context['summary']['all_candidate_cells_produced'])
    def test_resealed_incomplete_horse_sport_cannot_be_presented_as_partial_success(self):
        victim=next(record for record in self.records if record['pair']['sport']=='horse' and not record.get('captured_native_inputs'))
        records=[record for record in self.records if record is not victim]
        with self.assertRaisesRegex(ValueError,'COMPLETE_SPORT_CASE'):self.verify(**self.subset(records))
    def test_after_results_does_not_refresh_expired_origin_or_native_receipts(self):
        for origin,native in ((dict(self.origin_metadata,expires_at=self.after_results.isoformat()),self.native_metadata),
                (self.origin_metadata,dict(self.native_metadata,expires_at=self.after_results.isoformat()))):
            with self.subTest(origin=origin['expires_at'],native=native['expires_at']),self.assertRaises(ValueError):
                self.verify(origin_metadata=origin,native_metadata=native)


if __name__=='__main__':unittest.main()
