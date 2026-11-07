"""Authored public cards and fake Git/artifact receipts; no live provider/key."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from functools import lru_cache
from hashlib import sha256
import importlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tests.test_all_existing_model_future_source_capture import archive_directory
from tests import test_all_existing_model_source_packet_baseline_v2 as baselines
from tests.test_all_existing_model_source_packet_freeze import KEY
from tests.test_official_issue_transport import FakeGitHub,PARENT
from tests import test_jra_official_sparse_adapter as cards
from tests import test_all_existing_model_official_recovery as old

NOW=datetime(2030,11,9,1,10,tzinfo=timezone.utc)
CARD=cards.CARD_URL.replace('2026','2030').replace('1107/','1109/')
DISCOVERY='https://www.jra.go.jp/JRADB/accessD.html?CNAME=fictional-published-list'


@lru_cache(maxsize=1)
def matching_sparse_baseline():
    from tests.test_all_existing_model_native_future_v4 import ordinary_rows
    from race_ai.actions_contract import digest
    fit=baselines.fit
    def matching_fit(rows,**options):
        sparse=[baselines.shift_fixture(deepcopy(r),-14) for r in ordinary_rows()
            if r['sport']=='horse' and r['model_id']==baselines.LEARNED_ID]
        for row in sparse:
            row['scope']='OPERATOR_SUPPLIED_RESEARCH';row['native_payload']['snapshot']['scope']=row['scope']
            baselines.authorize_fixture(row,'horse');row['input_sha256']=digest(row['native_payload'])
        rows=[r for r in rows if not (r['sport']=='horse' and r['model_id']==baselines.LEARNED_ID)]
        return fit(rows+sparse,**options)
    # Do not alter the shared fixture's cached dense candidate for other tests.
    with patch.object(baselines,'fit',side_effect=matching_fit):return baselines.baseline_training.__wrapped__()


def manifest():
    pin=lambda n:dict(id=n,digest='sha256:'+str(n%10)*64,run_id=n+10,head_sha='a'*40)
    urls=[DISCOVERY,CARD,cards.RULE_URL]
    return dict(schema='RACE_AI_JRA_FUTURE_SOURCE_CAPTURE_INPUT_V1',execution_day='2030-11-09',
        discovery_url=DISCOVERY,card_url=CARD,rule_url=cards.RULE_URL,
        race_id='horse:2030-11-09:jra-03:11',cutoff_at='2030-11-09T15:19:00+09:00',maximum_requests=32,
        horse_baseline_artifact=pin(900),carrier_artifact=pin(700),excluded_native_artifacts=[],
        prior_journal_artifacts=deepcopy(old.fixture()[0]['request']['manifest']['prior_journal_artifacts']),
        terms_manifest=dict(schema='RACE_AI_MANUAL_OFFICIAL_TERMS_V1',execution_day='2030-11-09',
            purpose='PRIVATE_FACTUAL_ANALYSIS',public_redistribution=False,
            provider_model_training_permission_confirmed=False,owner_instruction_ref='AUTHORED_TEST_ONLY',
            terms=[dict(sport='horse',terms_url='https://www.jra.go.jp/fictional-policy',policy_sha256='e'*64,
                policy_captured_at='2030-11-08T01:00:00Z',source_urls=urls,
                uses=['private_retention','private_factual_analysis'])]))


class JraFutureContractsTests(unittest.TestCase):
    def api(self):return importlib.import_module('race_ai.jra_future_source_capture')

    def test_exact_today_literal_manifest_and_one_distinct_horse_baseline(self):
        api=self.api();value=manifest();self.assertEqual(api.validate_manifest(value,now=NOW),value)
        for mutation in ('day','extra','host','card_date','rule','same_carrier','cap','second_discovery','cutoff'):
            changed=deepcopy(value)
            if mutation=='day':changed['execution_day']='2030-11-10'
            elif mutation=='extra':changed['other']=1
            elif mutation=='host':changed['discovery_url']='https://example.test/'
            elif mutation=='card_date':changed['card_url']=CARD.replace('20301109','20301110')
            elif mutation=='rule':changed['rule_url']=cards.RULE_URL+'?changed=1'
            elif mutation=='same_carrier':changed['carrier_artifact']=deepcopy(changed['horse_baseline_artifact'])
            elif mutation=='cap':changed['maximum_requests']=33
            elif mutation=='second_discovery':changed['discovery_urls']=[DISCOVERY]
            else:changed['cutoff_at']=(NOW+timedelta(minutes=10)).isoformat()
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):api.validate_manifest(changed,now=NOW)

    def test_card_must_be_an_exact_published_href_in_the_fresh_discovery_original(self):
        api=self.api();raw=('<html><a href="'+CARD.replace('&','&amp;')+'">出馬表</a></html>').encode()
        api.verify_discovery(manifest(),raw,'utf-8')
        for changed in (raw.replace(b'<a ',b'<div '),raw.replace(b'href=',b'data-href='),raw.replace(b'/AA',b'/AB')):
            with self.assertRaises(ValueError):api.verify_discovery(manifest(),changed,'utf-8')

    def test_mixed_alias_is_rejected_and_a_denied_fixed_host_stops_all_following_gets(self):
        from scripts import jra_future_source_capture as wrapper
        from tests.test_manual_official_capture import Response
        api=self.api();value=manifest();bare=DISCOVERY.replace('www.jra.go.jp','jra.go.jp')
        value['discovery_url']=bare;value['terms_manifest']['terms'][0]['source_urls'][0]=bare
        with self.assertRaisesRegex(ValueError,'SINGLE_PUBLISHED_HOST'):api.validate_manifest(value,now=NOW)
        for status in (403,429):
            calls=[]
            def get(request,timeout):calls.append(request.full_url);return Response(b'denied',url=request.full_url,status=status)
            with tempfile.TemporaryDirectory() as temp,patch.object(wrapper,'utc_now',return_value=NOW):
                plan=dict(available_after=NOW.isoformat(),not_after=(NOW+timedelta(minutes=20)).isoformat(),
                    urls=[DISCOVERY,CARD,cards.RULE_URL])
                report=wrapper.collect(manifest(),plan,Path(temp)/'cache',opener=get,sleeper=lambda _:None)
            self.assertEqual(calls,[DISCOVERY]);self.assertEqual(report['source_requests'],1)

    def test_horse_marker_has_own_scope_and_existing_any_bytes_stops_before_baseline_or_source(self):
        from scripts import jra_future_source_capture as wrapper
        api=self.api();server=FakeGitHub();server.snapshots[PARENT][api.PATH]=b'existing-unknown'
        server._commit(PARENT,server.snapshots[PARENT]);transport=api.MarkerTransport(server)
        with tempfile.TemporaryDirectory() as temp,patch.object(wrapper,'utc_now',return_value=NOW),\
            patch.object(wrapper,'state_key',return_value=KEY),patch.object(wrapper.freeze,'_load_horse_baseline') as baseline,\
            patch.object(wrapper,'collect') as source:
            with self.assertRaisesRegex(ValueError,'ONCE_ALREADY_CONSUMED'):
                wrapper.generate(manifest(),Path(temp)/'output',dict(run_id=42,head_sha='a'*40,run_attempt=1),marker_transport=transport)
            baseline.assert_not_called();source.assert_not_called()
        from race_ai import all_existing_model_future_source_once as ak
        with self.assertRaises(ValueError):api.MarkerTransport(FakeGitHub()).read_file(PARENT,ak.PATH,1024)

    def test_wire_clock_enforces_expiry_after_spacing_and_never_follows_a_nonliteral_redirect(self):
        from scripts import jra_future_source_capture as wrapper
        api=self.api();clock=[NOW];calls=[]
        plan=dict(available_after=NOW.isoformat(),not_after=(NOW+timedelta(seconds=1)).isoformat(),urls=[DISCOVERY,CARD,cards.RULE_URL])
        def get(request,timeout):calls.append(request.full_url);return object()
        guarded=wrapper.guarded_opener(plan,get,clock=lambda:clock[0])
        from urllib.request import Request
        self.assertIsNotNone(guarded(Request(DISCOVERY),timeout=12))
        clock[0]=NOW+timedelta(seconds=1)
        with self.assertRaises(ValueError):guarded(Request(CARD),timeout=12)
        clock[0]=NOW
        with self.assertRaises(ValueError):guarded(Request('https://www.jra.go.jp/not-in-manifest'),timeout=12)
        self.assertEqual(calls,[DISCOVERY])

    def test_marker_mac_scope_rejects_reissue_expiry_caps_and_baseline_receipt_relabelling(self):
        api=self.api();value=manifest();pin=value['horse_baseline_artifact']
        model=dict(sport='horse',input_schema=api.jra.native.SCHEMA_SPARSE,native_training=dict(sport='horse',
            input_schema=api.jra.native.SCHEMA_SPARSE,created_at=(NOW-timedelta(days=1)).isoformat()))
        baseline=dict(receipt=dict(id=pin['id'],digest=pin['digest'],created_at=(NOW-timedelta(minutes=2)).isoformat(),
            workflow_run=dict(id=pin['run_id'],head_sha=pin['head_sha'])),training=dict(scope='OPERATOR_SUPPLIED_RESEARCH',
            training_sha256='b'*64,models={'horse/'+api.LEARNED_ID:model,**{str(n):{} for n in range(29)}}))
        plan=api.prepare(value,baseline,now=NOW);env=dict(run_id=42,head_sha='a'*40,run_attempt=1)
        dense=deepcopy(baseline);dense['training']['models']['horse/'+api.LEARNED_ID]['input_schema']='dense-fixture'
        with self.assertRaisesRegex(ValueError,'MATCHING_SPARSE_HORSE_RANKER'):api.prepare(value,dense,now=NOW)
        body=api.marker_body(value,env,baseline,{},plan,now=NOW);server=FakeGitHub();transport=api.MarkerTransport(server)
        consumed=api.reserve(body,KEY,transport,now=NOW);raw=consumed['_ciphertext']
        self.assertEqual(api.validate_marker(raw,body,KEY,now=NOW)['marker_path'],api.PATH)
        for mutation in ('expiry','cap','attempt','receipt','field'):
            changed=deepcopy(body)
            if mutation=='expiry':changed['expires_at']=(NOW+timedelta(days=1)).isoformat()
            elif mutation=='cap':changed['source_request_upper_bound']=33
            elif mutation=='attempt':changed['target']['run_attempt']=2
            elif mutation=='receipt':changed['baseline_receipt']['id']+=1
            else:changed['extra']=True
            from race_ai.boat_all_model_store import seal_forecasts
            forged=seal_forecasts(dict(schema=api.ONCE,body=changed,mac=api._mac(changed,KEY)),run_id='42',round_no=api.ROUND,key=KEY)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):api.validate_marker(forged,changed,KEY,now=NOW)
            with self.assertRaisesRegex(ValueError,'ONCE_ALREADY_CONSUMED'):api.reserve(changed,KEY,transport,now=NOW)
        server=FakeGitHub();server.cas_race=True
        with self.assertRaises(ValueError):api.reserve(body,KEY,api.MarkerTransport(server),now=NOW)

    def test_staging_validates_all_paths_and_cipher_hashes_before_any_file_creation(self):
        from scripts import jra_future_source_capture as wrapper
        index=b'opaque authored index';metadata=b'opaque authored metadata'
        index_sha=sha256(index).hexdigest();metadata_sha=sha256(metadata).hexdigest();value=manifest()
        fm=dict(schema=wrapper.freeze.V3_SCHEMA,execution_day=value['execution_day'],maximum_races=1,
            sealed_path='audit/state/manual-official-capture/'+index_sha,index_sha256=index_sha,
            source_metadata_path='audit/state/manual-official-source-metadata-'+metadata_sha+'.enc',source_metadata_sha256=metadata_sha,
            horse_baseline_artifact=value['horse_baseline_artifact'],carrier_artifact=value['carrier_artifact'],excluded_native_artifacts=[])
        for mutation in ('relative_cache','relative_metadata','absolute_cache','absolute_metadata','index','metadata','extra','schema','bound'):
            changed=deepcopy(fm);source={'index.enc':index,'metadata.enc':metadata}
            if mutation=='relative_cache':changed['sealed_path']='../escaped-sealed'
            elif mutation=='relative_metadata':changed['source_metadata_path']='../escaped-metadata.enc'
            elif mutation=='absolute_cache':changed['sealed_path']='/escaped-sealed'
            elif mutation=='absolute_metadata':changed['source_metadata_path']='/escaped-metadata.enc'
            elif mutation=='index':source['index.enc']+=b'changed'
            elif mutation=='metadata':source['metadata.enc']+=b'changed'
            elif mutation=='extra':changed['extra']=True
            elif mutation=='schema':changed['schema']=wrapper.freeze.SCHEMA
            else:changed['maximum_races']=2
            with tempfile.TemporaryDirectory() as temp,patch.object(wrapper,'utc_now',return_value=NOW):
                root=Path(temp);before=list(root.iterdir())
                with self.subTest(mutation=mutation),self.assertRaises(ValueError):wrapper._staging(source,changed,root/'stage')
                self.assertEqual(list(root.iterdir()),before)


class JraFutureIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.helper=baselines.SourcePacketBaselineV2Tests('runTest');self.helper.setUp();self.addCleanup(self.helper.doCleanups)
        self.helper.now=NOW;self.root=self.helper.root;self.clock=NOW
        self.api=importlib.import_module('race_ai.jra_future_source_capture')
        self.wrapper=importlib.import_module('scripts.jra_future_source_capture')
        self.env=dict(run_id=42,head_sha='a'*40,run_attempt=1,temp=self.root)
        with patch.object(baselines,'baseline_training',return_value=matching_sparse_baseline()):baseline,bm=self.helper.baseline()
        carrier,cm=self.helper.carrier()
        self.mapping={900:(baseline,bm),700:(carrier,cm)}
        self.input=manifest();self.input.update(horse_baseline_artifact=self.helper.pin,carrier_artifact=self.helper.carrier_pin)
        self.transport=self.api.MarkerTransport(FakeGitHub());self.requested=[]
        self.bodies={DISCOVERY:('<html><a href="'+CARD+'">公開出馬表</a></html>').encode(),
            CARD:cards.card().decode('cp932').replace('2026','2030').replace('1107/','1109/').replace('11月7日','11月9日').encode('cp932'),
            cards.RULE_URL:cards.evidence()['raw'].decode().replace('2026','2030').encode()}

    def advance(self,seconds):self.clock+=timedelta(seconds=seconds)
    def get(self,request,timeout):
        from tests.test_manual_official_capture import Response
        url=request.full_url;self.requested.append(url);self.advance(.1)
        return Response(self.bodies[url],url=url,headers={'Content-Type':'text/html; charset='+('shift_jis' if url==CARD else 'UTF-8')})

    def patches(self):
        from contextlib import ExitStack
        stack=ExitStack()
        stack.enter_context(patch.object(self.wrapper,'utc_now',side_effect=lambda:self.clock))
        stack.enter_context(patch.object(self.wrapper.freeze,'utc_now',side_effect=lambda:self.clock))
        stack.enter_context(patch.object(self.wrapper.future,'metadata',side_effect=lambda ident:deepcopy(self.mapping[ident][1])))
        stack.enter_context(patch.object(self.wrapper.future,'gh',side_effect=lambda path:self.mapping[int(path.split('/')[2])][0]))
        stack.enter_context(patch.object(self.wrapper,'history',return_value=dict(old_source_requests_actual=None,
            old_source_requests_upper_bound=32,old_browser_outcome='UNKNOWN',prior_journal_artifact_count=1)))
        return stack

    def test_real_fixture_mac_capture_sidecar_v3_five_cells_and_dual_actual_zip_readback(self):
        output=self.root/'jra-fresh'
        with self.patches():
            result=self.wrapper.generate(self.input,output,self.env,marker_transport=self.transport,
                opener=self.get,sleeper=self.advance,monotonic=lambda:self.clock.timestamp())
        self.assertTrue(result['ready'],result);self.assertEqual(self.requested,[DISCOVERY,CARD,cards.RULE_URL])
        self.assertEqual(result['captured_native_input_count'],5);self.assertEqual(result['forecast_partition_count'],0)
        records=self.wrapper.freeze.local_records(output/'native');capsules=records[0]['captured_native_inputs']
        self.assertEqual({c['native_payload']['snapshot']['race']['as_of'] for c in capsules},{result['fixed_as_of']})
        for ident,folder,name in ((800,output/'native',result['artifact_name']),(801,output/'source',result['source_artifact_name'])):
            if folder.name=='native':
                stream=io.BytesIO()
                with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
                    for path in sorted(folder.rglob('*')):
                        if path.is_file():archive.writestr(path.relative_to(folder).as_posix(),path.read_bytes())
                raw=stream.getvalue()
            else:raw=archive_directory(folder)
            actual=dict(id=ident,name=name,expired=False,size_in_bytes=len(raw),
                digest='sha256:'+sha256(raw).hexdigest(),created_at=(self.clock+timedelta(seconds=1)).isoformat(),
                expires_at=(NOW+timedelta(days=1)).isoformat(),workflow_run=dict(id=42,head_sha='a'*40,
                    repository_id=1416489937,head_repository_id=1416489937))
            self.mapping[ident]=(raw,actual)
        self.advance(5)
        with self.patches():
            checked=self.wrapper.readback(800,801,output,self.env,self.input,marker_transport=self.transport)
        self.assertTrue(checked['independent_pre_cutoff_receipt_verified']);self.assertTrue(checked['independent_source_capture_receipt_verified'])
        self.assertEqual(checked['fixed_as_of'],result['fixed_as_of']);self.assertEqual(len(self.requested),3)
        with self.patches(),patch.object(self.transport,'read_file',return_value=b'foreign-current-marker'):
            with self.assertRaises(ValueError):self.wrapper.readback(800,801,output,self.env,self.input,marker_transport=self.transport)
        wrong=deepcopy(self.input);wrong['horse_baseline_artifact']['id']=901
        with self.patches(),self.assertRaises(ValueError):self.wrapper.readback(800,801,output,self.env,wrong,marker_transport=self.transport)

    def test_missing_published_link_denial_and_uncertain_capture_keep_encrypted_journal_without_native(self):
        for mutation in ('link','denied','unknown','corrupt'):
            self.requested=[];output=self.root/('failed-'+mutation);transport=self.api.MarkerTransport(FakeGitHub())
            original=self.bodies[DISCOVERY]
            if mutation=='link':self.bodies[DISCOVERY]=b'<html>no published card link</html>'
            def get(request,timeout):
                if mutation in ('unknown','corrupt'):
                    if mutation=='corrupt':output.with_name(output.name+'.jra-cache').joinpath('cache.json').write_bytes(b'{corrupt-cache')
                    raise RuntimeError('authored process interruption')
                if mutation=='denied':
                    from tests.test_manual_official_capture import Response
                    self.requested.append(request.full_url);return Response(b'denied',status=403,url=request.full_url)
                return self.get(request,timeout)
            with self.patches():result=self.wrapper.generate(self.input,output,self.env,marker_transport=transport,
                opener=get,sleeper=self.advance,monotonic=lambda:self.clock.timestamp())
            self.bodies[DISCOVERY]=original
            with self.subTest(mutation=mutation):
                self.assertFalse(result['ready']);self.assertFalse((output/'native').exists())
                self.assertTrue((output/'source'/'collection.enc').exists());self.assertTrue(result['source_capture_encrypted'])
                self.assertEqual(result['old_source_requests_upper_bound'],32)
                self.assertNotIn('authored process',json.dumps(result))
            raw=archive_directory(output/'source');actual=dict(id=802,name=result['source_artifact_name'],expired=False,
                size_in_bytes=len(raw),digest='sha256:'+sha256(raw).hexdigest(),created_at=self.clock.isoformat(),
                expires_at=(NOW+timedelta(days=1)).isoformat(),workflow_run=dict(id=42,head_sha='a'*40,
                    repository_id=1416489937,head_repository_id=1416489937))
            self.mapping[802]=(raw,actual)
            with self.patches():saved=self.wrapper.readback_source(802,output,self.env,self.input,marker_transport=transport)
            self.assertTrue(saved['independent_source_capture_receipt_verified']);self.assertFalse(saved['ready'])
            self.assertFalse(saved['independent_pre_cutoff_receipt_verified'])


if __name__=='__main__':unittest.main()
