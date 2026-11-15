"""Separate authored forward origins; actual fixture MAC/codecs, no providers."""
from copy import deepcopy
from datetime import timedelta
from functools import lru_cache
import base64,io,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

from scripts import all_existing_model_thirty_order_pdca as cli
from tests import test_all_existing_model_thirty_order_pdca_artifacts as fixture

SCHEMA='RACE_AI_ALL_THIRTY_ORDER_PDCA_INPUT_V2'


def manifest_for(source):
    def pin(meta):return dict(id=meta['id'],digest=meta['digest'],run_id=meta['workflow_run']['id'],head_sha=meta['workflow_run']['head_sha'])
    return dict(schema=SCHEMA,candidate_cell_count=30,forecast_batches=deepcopy(source['batches']),
        result_artifacts=[dict(pin(item['metadata']),kind=item['kind']) for item in source['results']],additional_native_artifacts=[])


class MultiManifestTests(unittest.TestCase):
    def test_explicit_v2_pair_list_and_legacy_v1_are_distinct(self):
        p=lambda n:dict(id=n,digest='sha256:'+str(n)*64,run_id=42,head_sha='a'*40)
        value=dict(schema=SCHEMA,candidate_cell_count=30,forecast_batches=[dict(future_artifact=p(1),origin_artifact=p(2))],
            result_artifacts=[dict(p(3),kind='BOAT')],additional_native_artifacts=[])
        self.assertEqual(cli.validate_manifest(value),value)
        for changes in (dict(forecast_batches=[]),dict(forecast_batches=value['forecast_batches']*2),
                        dict(candidate_cell_count=19),dict(future_artifact=p(4)),dict(schema=cli.SCHEMA)):
            with self.subTest(changes=changes),self.assertRaises(ValueError):cli.validate_manifest(dict(value,**changes))

    def test_post_auth_batch_order_context_replays_complete_original_label_set(self):
        # Pure post-auth label invariant; this does not mock artifact admission
        # or claim that these small dictionaries are native forecasts.
        from tests.test_all_existing_model_thirty_order_pdca import ThirtyOrderLabelTests,NOW
        from race_ai import all_existing_model_thirty_order_aggregate as aggregate
        helper=ThirtyOrderLabelTests();label=helper.label();result=helper.context([label]);forecast=helper.forecast(label)
        selected,counts=aggregate.core._order_observations([result],[forecast],now=NOW)
        context=dict(result_contexts=[result],normal_order_results=selected,projection_counts=counts)
        aggregate._check_batch_order_context(context,[forecast],NOW)
        for change in ('extra','counts'):
            wrong=deepcopy(context)
            if change=='extra':wrong['normal_order_results'].append(deepcopy(selected[0]))
            else:wrong['projection_counts']['matched_order_result_count']+=1
            with self.subTest(change=change),self.assertRaises(ValueError):aggregate._check_batch_order_context(wrong,[forecast],NOW)

    def test_original_horse_receipt_cannot_borrow_other_sport_later_cutoff(self):
        from datetime import datetime
        from race_ai import all_existing_model_thirty_order_pdca as existing
        run=dict(id=42,head_sha='b'*40,repository_id=1416489937,head_repository_id=1416489937)
        context=dict(source_native_metadata=dict(id=1,workflow_run=run),origin=dict(
            origin_metadata=dict(id=2,name='all-native-future-origin-42-900010',workflow_run=deepcopy(run),
                expired=False,digest='sha256:'+'a'*64,size_in_bytes=123,
                created_at='2030-02-02T23:41:00+09:00',expires_at='2030-02-04T00:00:00+09:00'),
            origin_cipher_sha256='b'*64,generation=dict(workflow_run_id=42,expected_head_sha='b'*40,
                origin_generated_at='2030-02-02T23:00:00+09:00',cutoff_at='2030-02-02T23:59:00+09:00')))
        now=datetime.fromisoformat('2030-02-03T01:00:00+09:00')
        existing._origin_receipt(context,now)
        context['origin']['generation']['cutoff_at']='2030-02-02T23:50:00+09:00'
        with self.assertRaises(ValueError):existing._origin_receipt(context,now)


@lru_cache(maxsize=1)
def sources():
    from tests.test_all_existing_model_future_batches import separate_fixture
    source=deepcopy(separate_fixture());source['results']=fixture.full_fixture()['results'];return source


class MultiAggregateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(fixture.KEY).decode()):cls.source=sources()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.env=dict(run_id=61,head_sha='a'*40,temp=self.root);self.now=fixture.EVALUATED
        setting=patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(fixture.KEY).decode());setting.start();self.addCleanup(setting.stop)
        self.manifest=manifest_for(self.source);self.actual={};self.raw={}
        for batch in self.source['archives']:
            for item in batch.values():self.actual[item['metadata']['id']]=item['metadata'];self.raw[item['metadata']['id']]=item['raw']
        for item in self.source['results']:self.actual[item['metadata']['id']]=item['metadata'];self.raw[item['metadata']['id']]=item['raw']
    def patches(self):
        from contextlib import ExitStack
        stack=ExitStack();stack.enter_context(patch.object(cli.future,'metadata',side_effect=lambda n:deepcopy(self.actual[n])))
        stack.enter_context(patch.object(cli.shared,'_download',side_effect=lambda pin,meta:self.raw[pin['id']]))
        return stack
    def test_two_real_origins_five_plus_twentyfive_score_and_actual_zip_restore(self):
        output=self.root/'score';before=deepcopy(self.source)
        with self.patches():status=cli.generate(output,self.env,self.manifest,now=self.now)
        self.assertTrue(status['ready'],status);self.assertEqual(status['teacher_matched_forecasts'],30)
        self.assertEqual(status['forecast_batch_count'],2);self.assertTrue(status['all_thirty_cells_scored'])
        self.assertEqual(status['forecast_counts_by_sport'],dict(boat=14,autorace=6,keirin=5,horse=5))
        self.assertFalse(status['monetary_evaluation_available']);self.assertEqual(self.source,before)
        self.assertEqual(len([p for p in output.iterdir() if p.is_dir()]),30);self.assertTrue((output/'aggregate.enc').is_file())
        # Existing CLI generation/readback interface and artifact name stay fixed.
        cli._write(output.with_name(output.name+'.generation.json'),cli.future.wire(dict(status,schema=cli.STATUS_V2,
            workflow_run_id=61,expected_head_sha='a'*40)))
        raw=fixture.boat.zipped(output);actual=fixture.actual_metadata(raw,401,'all-existing-model-thirty-order-pdca-61-900023',
            61,'a'*40,self.now+timedelta(seconds=2));self.raw[401]=raw;self.actual[401]=actual
        with self.patches():checked=cli.readback(401,output,self.env,self.manifest,now=self.now+timedelta(seconds=3))
        self.assertTrue(checked['independent_pdca_artifact_receipt_verified']);self.assertTrue(checked['all_thirty_cells_scored'])
        # Real owner-codec rows retain source/result identities; changing those
        # cannot be rescued by recomputing their unkeyed context SHA/summary.
        from race_ai.boat_venue_learning import read_candidate
        from race_ai.actions_contract import digest
        from race_ai import all_existing_model_thirty_order_pdca as existing
        original=read_candidate(next(p for p in output.iterdir() if p.is_dir()))
        for change in ('date','sport','source_context'):
            wrong=deepcopy(original);context=wrong['source_context']
            if change=='date':wrong['private_forecast']['pair']['race_id']+='-different-date'
            elif change=='sport':wrong['private_forecast']['pair']['sport']='wrong-sport'
            else:context['source_native_metadata']['workflow_run']['head_sha']='f'*40
            wrong['source_context_sha256']=digest(context)
            with self.subTest(change=change),self.assertRaises(ValueError):existing.verify_private_thirty_order_pdca(wrong)
        # No correctly re-hashed transport can conceal a removed original row.
        with fixture.zipfile.ZipFile(io.BytesIO(raw)) as archive:
            first=next(n.split('/')[0] for n in archive.namelist() if '/' in n)
            partial=fixture.packed([(n,archive.read(n)) for n in archive.namelist() if not n.startswith(first+'/')])
        from race_ai import all_existing_model_thirty_order_aggregate as aggregate
        bad=dict(actual,size_in_bytes=len(partial),digest='sha256:'+fixture.sha256(partial).hexdigest())
        with self.assertRaises(ValueError):aggregate.verify_artifact(partial,bad,now=self.now+timedelta(seconds=3),
            expected_run_id=61,expected_head_sha='a'*40)
    def test_wrong_pair_missing_overlap_or_late_original_never_succeeds(self):
        for change in ('pair','missing','overlap','late_horse','bytes'):
            manifest=deepcopy(self.manifest);actual=deepcopy(self.actual);raw=deepcopy(self.raw)
            if change=='pair':manifest['forecast_batches'][0]['origin_artifact']=manifest['forecast_batches'][1]['origin_artifact']
            elif change=='missing':manifest['forecast_batches'].pop()
            elif change=='overlap':manifest['forecast_batches'].append(deepcopy(manifest['forecast_batches'][0]))
            elif change=='late_horse':actual[manifest['forecast_batches'][0]['origin_artifact']['id']]['created_at']='2030-02-02T23:41:00+09:00'
            else:raw[manifest['forecast_batches'][0]['future_artifact']['id']]=b'not-original'
            with self.subTest(change=change),patch.object(cli.future,'metadata',side_effect=lambda n:deepcopy(actual[n])),\
                    patch.object(cli.shared,'_download',side_effect=lambda p,m:raw[p['id']]),self.assertRaises(ValueError):
                cli.generate(self.root/change,self.env,manifest,now=self.now)

    def test_valid_result_without_horse_teacher_holds_and_never_counts_missing_as_loss(self):
        from race_ai import all_existing_model_official_results as official
        from race_ai.boat_all_model_store import open_forecasts,seal_forecasts
        result=next(item for item in self.source['results'] if item['kind']=='OFFICIAL')
        payload=open_forecasts(official._cipher(result['raw']),key=fixture.KEY)
        horse=next(o for o in payload['observations'] if o['sport']=='horse')
        captures=[c for c in payload['captures'] if c['metadata']['source_url']!=horse['source_ref']]
        observations=[o for o in payload['observations'] if o['sport']!='horse']
        natives={r['cell_key'].split('/')[0]:r['native_payload'] for r in self.source['requests']
            if r['native_payload'].get('snapshot',{}).get('race',{}).get('sport')}
        changed=official.build_result_payload(captures,observations,run_id=payload['run_id'],code_sha=payload['code_sha'],
            generated_at=fixture.datetime.fromisoformat(payload['generated_at']),day_jst=payload['day_jst'],
            frozen_native_payloads=list(natives.values()),allow_order_only=True)
        raw=fixture.packed([('results.enc',seal_forecasts(changed,run_id=str(payload['run_id']),round_no=1,key=fixture.KEY))])
        ident=result['metadata']['id'];actual=dict(self.actual[ident],size_in_bytes=len(raw),digest='sha256:'+fixture.sha256(raw).hexdigest())
        self.actual[ident]=actual;self.raw[ident]=raw
        for pin in self.manifest['result_artifacts']:
            if pin['id']==ident:pin['digest']=actual['digest']
        with self.patches():status=cli.generate(self.root/'missing-teacher',self.env,self.manifest,now=self.now)
        self.assertFalse(status['ready']);self.assertFalse(status['all_thirty_cells_scored'])
        self.assertEqual(status['teacher_matched_forecasts'],25)
        self.assertEqual(status['result_state_counts']['NO_ORDER_ONLY_TEACHER'],5)
        from race_ai.boat_venue_learning import read_candidate
        rows=[read_candidate(p) for p in (self.root/'missing-teacher').iterdir() if p.is_dir()]
        horse=[p for p in rows if p['private_forecast']['pair']['sport']=='horse']
        self.assertEqual(len(horse),5)
        for payload in horse:
            self.assertIsNone(payload['order_observation']);self.assertIsNone(payload['result_observation_sha256'])
            self.assertEqual(payload['score'],dict(state='NO_ORDER_ONLY_TEACHER',paired=False))
            for arm in ('baseline','learned'):
                board=payload['comparison'][arm]
                self.assertEqual(board['forecasts'],0);self.assertEqual(board['probability_scored_forecasts'],0)
                self.assertIsNone(board['mean_log_loss'])


if __name__=='__main__':unittest.main()
