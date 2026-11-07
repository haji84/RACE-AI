"""Explicit manifest contract and trusted-entry guards; no key/source access."""
from copy import deepcopy
import importlib
import importlib.util
import json
import os
import io
from contextlib import redirect_stdout
from unittest.mock import patch
from pathlib import Path
import tempfile
import unittest

class CashManifestTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('scripts.all_existing_model_cash_pdca'), 'cash PDCA CLI is absent')
        return importlib.import_module('scripts.all_existing_model_cash_pdca')
    def manifest(self):
        def pin(n):return dict(id=n,digest='sha256:'+str(n%10)*64,run_id=40+n,head_sha='a'*40)
        return dict(schema='RACE_AI_CASH_NATIVE_PDCA_INPUT_V1',candidate_cell_count=19,future_artifact=pin(1),origin_artifact=pin(2),
            result_artifacts=[dict(kind='OFFICIAL',**pin(3))],additional_native_artifacts=[])
    def test_explicit19_and30_profiles_validate_without_relabeling_typed_teachers(self):
        api=self.module()
        for count in (19,30):
            manifest=dict(self.manifest(),candidate_cell_count=count)
            self.assertEqual(api.validate_manifest(manifest),manifest)
    def test_unknown_count_duplicatepin_unknownkind_and_unbounded_sources_reject(self):
        api=self.module();original=self.manifest()
        for change in ({'candidate_cell_count':14},{'candidate_cell_count':True},{'extra':1},
                       {'origin_artifact':original['future_artifact']},
                       {'result_artifacts':[dict(original['result_artifacts'][0],kind='unchecked')]},
                       {'additional_native_artifacts':[dict(original['future_artifact'],id=100+n) for n in range(17)]}):
            with self.subTest(change=change),self.assertRaises(ValueError):api.validate_manifest(dict(original,**change))
        self.assertEqual(original,self.manifest())

    def test_real_legacy_result_first_and_later_artifact_names_reuse_existing_contract(self):
        api=self.module()
        from datetime import datetime,timedelta,timezone
        from hashlib import sha256
        now=datetime(2030,2,3,tzinfo=timezone.utc);raw=b'fixture'
        pin=dict(id=301,digest='sha256:'+sha256(raw).hexdigest(),run_id=55,head_sha='a'*40)
        base=dict(id=301,expired=False,digest=pin['digest'],size_in_bytes=len(raw),created_at=(now-timedelta(seconds=2)).isoformat(),
            expires_at=(now+timedelta(days=7)).isoformat(),workflow_run=dict(id=55,head_sha='a'*40,repository_id=1416489937,head_repository_id=1416489937))
        for name in ('race-existing-cycle-55','race-existing-cycle-55-cycle-02'):
            self.assertEqual(api._actual(dict(base,name=name),pin,'BOAT',now)['name'],name)
        for name in ('race-existing-cycle-55-cycle-01','race-existing-cycle-55-cycle-2'):
            with self.assertRaises(ValueError):api._actual(dict(base,name=name),pin,'BOAT',now)

    def test_untrusted_or_missing_key_holds_before_any_github_source_read(self):
        api=self.module()
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);manifest=root/'input.json';manifest.write_text(json.dumps(self.manifest()))
            for values in (dict(RACE_AI_STATE_KEY=''),dict(RACE_AI_STATE_KEY='public-fixture',GITHUB_ACTIONS='false')):
                output=io.StringIO()
                with patch.dict(os.environ,values),patch.object(api.future,'gh',side_effect=AssertionError('unexpected GitHub read')),redirect_stdout(output):
                    code=api.main(['--input',str(manifest),'--out-dir',str(root/'out')])
                status=json.loads(output.getvalue());self.assertEqual(code,0);self.assertFalse(status['ready'])
                self.assertFalse((root/'out').exists());self.assertEqual(status['source_requests'],0)
                self.assertNotIn('public-fixture',output.getvalue())


# Slow native fitting is cached by the origin fixture; negative cases below
# reuse immutable original bytes and execute only the boundary being tested.
from datetime import timedelta
from functools import lru_cache
from hashlib import sha256
import base64
import zipfile
from race_ai.actions_contract import digest
from race_ai.boat_venue_learning import read_candidate
from tests.test_all_existing_model_native_future_v3 import KEY,NOW,metadata
from tests.test_all_existing_model_order_only_pdca import archive


def pin(meta):return dict(id=meta['id'],digest=meta['digest'],run_id=meta['workflow_run']['id'],head_sha=meta['workflow_run']['head_sha'])


@lru_cache(maxsize=1)
def original_archives():
    from tests.test_all_existing_model_cash_pdca_origin import future_fixture,zipped_members
    from tests.test_frozen_day_cycle import observation
    from tests.test_jra_official_result_adapter import result_html
    from race_ai.boat_private_original_archive import seal_original_zip
    from race_ai import all_existing_model_official_results as official
    from race_ai.jra_official_result_adapter import parse_result
    from race_ai.manual_official_capture import official_rights_ref
    source=future_fixture();when=NOW+timedelta(minutes=51);generated=NOW+timedelta(minutes=53)
    boat=next(record['pair'] for record in source['records'] if record['pair']['sport']=='boat')
    from race_ai.existing_model_dispatch import _race_key
    race=_race_key(boat['race_id'],'boat');parts=race.split(':');venue=parts[2][-2:];number=int(parts[3])
    row=observation(dict(race_id='20300202-'+venue+'-'+str(number).zfill(2),cutoff_at=boat['race_cutoff_at'],
        top8=boat['baseline_normalized']['top'],roster=boat['baseline_normalized']['roster']))
    row.update(captured_at=when.isoformat(),available_at=when.isoformat(),kind='raceresult',information_phase='official_result',
        source_url=f'https://www.boatrace.jp/owpc/pc/race/raceresult?rno={number}&jcd={venue}&hd=20300202')
    report=dict(schema='RACE_AI_EXISTING_MODEL_CYCLE_REPORT_V1',day_jst='2030-02-02',run_id='55',code_sha='b'*40,
        updated_at=generated.isoformat(),result_observation_versions=1,actual_purchases=False)
    report['report_sha256']=digest(report)
    plain=zipped_members({'official-result-observations.json':json.dumps([row]).encode(),'status.json':json.dumps(report).encode()})
    body=zipped_members({'private-original.enc':seal_original_zip(plain,run_id=55,head_sha='b'*40,kind='RESULT',key=KEY)})
    boat_meta=metadata(301,'race-existing-cycle-55',body,saved=generated+timedelta(seconds=2),run=55,head='b'*40)
    horse=next(record['native_payload'] for record in source['records'] if record['pair']['sport']=='horse')
    raw=result_html().decode('cp932').replace('2026年11月7日','2030年2月2日').encode('cp932')
    url='https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde1003203003011120300202/AA'
    meta=dict(source_url=url,final_url=url,status=200,byte_count=len(raw),source_sha256=sha256(raw).hexdigest(),
        fetched_at=(when-timedelta(seconds=2)).isoformat(),response_received_at=when.isoformat(),headers={'Content-Type':'text/html'})
    label=parse_result(raw,meta,frozen_native_payload=horse,now=generated,source_rights_ref=official_rights_ref('horse'))
    payload=official.build_result_payload([dict(raw_base64=base64.b64encode(raw).decode(),metadata=meta)],[label],
        run_id=56,code_sha='e'*40,generated_at=generated,day_jst='2030-02-02',frozen_native_payloads=[horse])
    from race_ai.boat_all_model_store import seal_forecasts
    official_raw=zipped_members({'results.enc':seal_forecasts(payload,run_id='56',round_no=1,key=KEY)})
    official_meta=metadata(302,'all-existing-official-results-56-1',official_raw,saved=generated+timedelta(seconds=2),run=56,head='e'*40)
    return dict(source=source,boat_raw=body,boat_meta=boat_meta,official_raw=official_raw,official_meta=official_meta)


class CashArtifactPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # These tests require the actual owner codec, real native predictions,
        # two independent result parsers and genuine-shaped receipt boundaries.
        with patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(KEY).decode()):cls.sources=original_archives()
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.out=self.root/'score';self.now=self.sources['source']['now'];self.transport=[]
        env=patch.dict(os.environ,dict(RACE_AI_STATE_KEY=base64.b64encode(KEY).decode(),GITHUB_ACTIONS='true',
            GITHUB_REPOSITORY='haji84/RACE-AI',GITHUB_REPOSITORY_ID='1416489937',GITHUB_RUN_ID='111',RUNNER_TEMP=str(self.root),
            GITHUB_EVENT_NAME='pull_request',GITHUB_REF='refs/pull/71/merge',GITHUB_EVENT_PATH=str(self.root/'event.json')))
        env.start();self.addCleanup(env.stop)
        (self.root/'event.json').write_text(json.dumps(dict(number=71,pull_request=dict(number=71,
            head=dict(sha='f'*40,repo=dict(id=1416489937,full_name='haji84/RACE-AI')),
            base=dict(repo=dict(id=1416489937,full_name='haji84/RACE-AI'))))))
        source=self.sources['source'];self.actual={201:deepcopy(source['native_metadata']),202:deepcopy(source['origin_metadata']),
            301:deepcopy(self.sources['boat_meta']),302:deepcopy(self.sources['official_meta'])}
        self.raws={201:source['native_raw'],202:source['origin_raw'],301:self.sources['boat_raw'],302:self.sources['official_raw']}
        self.manifest=dict(schema='RACE_AI_CASH_NATIVE_PDCA_INPUT_V1',candidate_cell_count=19,
            future_artifact=pin(self.actual[201]),origin_artifact=pin(self.actual[202]),
            result_artifacts=[dict(kind='BOAT',**pin(self.actual[301])),dict(kind='OFFICIAL',**pin(self.actual[302]))],additional_native_artifacts=[])
        self.path=self.root/'manifest.json';self.path.write_text(json.dumps(self.manifest))
    def gh(self,route):
        self.transport.append(route)
        if route=='actions/runs/111':return json.dumps(dict(id=111,head_sha='f'*40,repository=dict(id=1416489937,full_name='haji84/RACE-AI'),head_repository=dict(id=1416489937,full_name='haji84/RACE-AI'))).encode()
        pieces=route.split('/');ident=int(pieces[2]);return self.raws[ident] if len(pieces)==4 else json.dumps(self.actual[ident]).encode()
    def main(self,extra=()):
        from scripts import all_existing_model_cash_pdca as api
        output=io.StringIO()
        with patch.object(api.future,'gh',side_effect=self.gh),patch.object(api,'utc_now',return_value=self.now),patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('provider forbidden')),redirect_stdout(output):
            code=api.main(['--input',str(self.path),'--out-dir',str(self.out),*extra])
        return code,json.loads(output.getvalue())
    def test_real_nineteen_source_result_score_cipher_and_independent_uploaded_readback(self):
        code,ready=self.main();self.assertEqual(code,0);self.assertTrue(ready['ready'],ready)
        self.assertEqual(ready['paired_forecasts'],19);self.assertEqual(ready['partition_count'],19)
        self.assertEqual(ready['source_requests'],0);self.assertFalse(ready['all_thirty_cells_scored'])
        self.assertEqual(ready['matched_cash_result_count'],2);self.assertFalse(ready['independent_pdca_artifact_receipt_verified'])
        for folder in self.out.iterdir():
            self.assertEqual(len(folder.name),64);self.assertEqual(folder.stat().st_mode&0o777,0o700)
            self.assertEqual({p.name for p in folder.iterdir()},{'learning.enc','learning.json','summary.json'})
            public=json.loads((folder/'summary.json').read_text())
            self.assertEqual(public['outside_cash_forecast_count'],0)
            for forbidden in ('scoreboard','roster','ordered_top3','owner_research_record','cash_score','native_payload'):
                self.assertNotIn(forbidden,public)
            payload=read_candidate(folder);self.assertEqual(payload['cash_score']['observation']['status'],'settled')
            self.assertEqual(payload['source_context']['candidate_cell_count'],19)
        raw=archive(self.out);self.raws[1000]=raw;self.actual[1000]=metadata(1000,ready['artifact_name'],raw,
            saved=self.now+timedelta(seconds=2),run=111,head='f'*40);self.now+=timedelta(seconds=3)
        _,actual=self.main(['--readback-artifact','1000']);self.assertTrue(actual['ready'],actual)
        self.assertTrue(actual['independent_pdca_artifact_receipt_verified']);self.assertEqual(actual['paired_forecasts'],19)
        self.assertEqual(actual['source_requests'],0)
        # Reuse exact immutable scoring bytes for boundary negatives; the
        # genuine CLI readback above already re-authenticated every source.
        from race_ai import all_existing_model_cash_pdca as core
        good_meta=deepcopy(self.actual[1000]);good_raw=self.raws[1000]
        wrong=deepcopy(good_meta);wrong['workflow_run']['head_sha']='9'*40
        with self.assertRaises(ValueError):
            core.verify_cash_pdca_artifact(good_raw,wrong,now=self.now,expected_run_id=111,expected_head_sha='f'*40)
        with zipfile.ZipFile(io.BytesIO(good_raw)) as source:
            bodies={name:source.read(name) for name in source.namelist()}
        name=next(name for name in bodies if name.endswith('/learning.enc'));body=bodies[name]
        bodies[name]=body[:-1]+bytes([body[-1]^1])
        from tests.test_all_existing_model_cash_pdca_origin import zipped_members
        bad=zipped_members(bodies);wrong=dict(good_meta,size_in_bytes=len(bad),digest='sha256:'+sha256(bad).hexdigest())
        with self.assertRaises(ValueError):
            core.verify_cash_pdca_artifact(bad,wrong,now=self.now,expected_run_id=111,expected_head_sha='f'*40)
        # Compare actual immutable member bytes. Repackaging ZIPs would compare
        # fresh DOS timestamps, which say nothing about original preservation.
        def members():return {str(path.relative_to(self.out)):sha256(path.read_bytes()).hexdigest()
            for path in self.out.rglob('*') if path.is_file()}
        before=members();_,held=self.main();self.assertFalse(held['ready']);self.assertEqual(members(),before)
    def test_bad_actual_origin_head_or_expired_result_holds_before_any_output(self):
        for ident,change in ((202,dict(workflow_run=dict(self.actual[202]['workflow_run'],head_sha='9'*40))),
                (302,dict(expired=True))):
            self.out=self.root/('score-'+str(ident));self.transport=[]
            original=deepcopy(self.actual[ident]);self.actual[ident].update(change)
            _,held=self.main();self.assertFalse(held['ready']);self.assertFalse(self.out.exists())
            self.assertFalse(any(route.endswith('/zip') for route in self.transport))
            self.actual[ident]=original
    def test_nineteen_artifact_cannot_be_relabelled_thirty(self):
        self.manifest['candidate_cell_count']=30;self.path.write_text(json.dumps(self.manifest))
        _,held=self.main();self.assertFalse(held['ready']);self.assertFalse(self.out.exists())

if __name__=='__main__':unittest.main()
