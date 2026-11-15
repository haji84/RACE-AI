"""Synthetic separately frozen originals; real codecs, never live source data."""
import base64
from copy import deepcopy
from datetime import timedelta
from functools import lru_cache
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai.all_existing_model_pairs import make_private_pairs
from race_ai.boat_venue_learning import seal_candidate
from tests import test_all_existing_model_native_future as boat
from tests import test_all_existing_model_native_future_v3 as authored
from tests.test_all_existing_model_thirty_order_pdca_artifacts import full_fixture, EVALUATED


def pin(meta):
    return dict(id=meta['id'],digest=meta['digest'],run_id=meta['workflow_run']['id'],
                head_sha=meta['workflow_run']['head_sha'])


@lru_cache(maxsize=1)
def _candidate_fixture():
    """One real optimizer result and one original candidate for every variant."""
    training,owner,_,borrower=authored.fitted()
    with tempfile.TemporaryDirectory() as temporary,patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(authored.KEY).decode()):
        root=Path(temporary)/'candidate'
        seal_candidate(dict(training=deepcopy(training),owner_research_record=deepcopy(owner),excluded=[],
            summary=dict(state='FITTED_SHADOW_ONLY',fitted_model_count=30,actual_purchases=False,production_promoted=False)),root)
        raw=boat.zipped(root)
    meta=authored.metadata(200,'all-existing-model-learning-7-1',raw,saved=authored.FIXTURE_NOW+timedelta(minutes=1),run=7)
    source_context=dict(training=deepcopy(borrower),receipt=authored.metadata(90,'all-existing-model-learning-6-1',b'older fixture',
        saved=authored.FIXTURE_NOW-timedelta(days=1),run=6))
    return raw,meta,source_context


@lru_cache(maxsize=8)
def separate_fixture(short_horse=False,mode='normal'):
    """Author both source sets before their own real writer freezes them."""
    base=deepcopy(separate_fixture(short_horse=short_horse)) if mode!='normal' else None
    if mode=='missing_model':
        base['batches']=base['batches'][1:];base['archives']=base['archives'][1:]
        return base
    temporary=tempfile.TemporaryDirectory();temp=Path(temporary.name)
    environment=patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(authored.KEY).decode());environment.start()
    candidate_raw,candidate,source_context=deepcopy(_candidate_fixture())
    mapping={'actions/artifacts/200':json.dumps(candidate).encode(),'actions/artifacts/200/zip':candidate_raw}
    current=[authored.NOW]
    patches=[patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('NO_NETWORK')),
        patch.object(authored.future.future,'utc_now',side_effect=lambda:current[0]),
        patch.object(authored.future.future,'gh',side_effect=lambda route:mapping[route]),
        patch.object(authored.future.future,'metadata',side_effect=lambda ident:json.loads(mapping['actions/artifacts/'+str(ident)]))]
    for item in patches:item.start()
    try:
        requests=base['requests'] if base else full_fixture()['requests']
        early=(authored.NOW+timedelta(minutes=11)).isoformat()
        for request in requests:
            if short_horse and request['cell_key'].startswith('horse/'):
                request['native_payload']=json.loads(json.dumps(request['native_payload']).replace(
                    '2030-02-02T23:50:00+09:00',early))
        pairs=[];archives=[];source_archives=[]
        all_source_pins={}
        for index,sports in enumerate(({'horse'},{'autorace','keirin'},{'boat'})):
            if base:
                archive=deepcopy(base['source_archives'][index]);meta=archive['metadata'];raw=archive['raw']
                mapping['actions/artifacts/'+str(meta['id'])]=json.dumps(meta).encode()
                mapping['actions/artifacts/'+str(meta['id'])+'/zip']=raw
                source_archives.append(archive);all_source_pins[index]=pin(meta)
                continue
            chosen=[r for r in requests if r['cell_key'].split('/',1)[0] in sports]
            source=temp/('source-part-'+str(index))
            make_private_pairs(source_context,chosen,source,now=authored.NOW-timedelta(minutes=6),
                               allow_source=lambda *_:True)
            (source/'summary.json').unlink();raw=boat.zipped(source)
            round_no=(900002,900003,1)[index]
            meta=authored.metadata(100+index,'all-existing-model-pairs-'+str(8+index)+'-'+str(round_no),raw,
                saved=authored.NOW-timedelta(minutes=5),run=8+index,head='c'*40)
            mapping['actions/artifacts/'+str(100+index)]=json.dumps(meta).encode()
            mapping['actions/artifacts/'+str(100+index)+'/zip']=raw
            source_archives.append(dict(raw=raw,metadata=meta));all_source_pins[index]=pin(meta)
        groups=({'horse'},) if base else ({'horse'},{'boat','autorace','keirin'})
        for index,sports in enumerate(groups):
            manifest=dict(schema='RACE_AI_ALL_NATIVE_FUTURE_INPUT_V3',candidate_cell_count=30,
                candidate_artifact_id=200,candidate_digest=candidate['digest'])
            manifest['source_input_artifacts']=[all_source_pins[n] for n in ([0] if index==0 else [1,2])]
            if mode=='mixed_candidate':
                copied=deepcopy(candidate);copied['id']=300
                mapping['actions/artifacts/300']=json.dumps(copied).encode()
                mapping['actions/artifacts/300/zip']=candidate_raw
                manifest['candidate_artifact_id']=300
            current[0]=authored.NOW+timedelta(minutes=2 if base and not short_horse else 2*index)
            root=temp/('partial-'+str(index))
            run=44 if base else 42+index;head='f'*40 if base else ('d' if index==0 else 'e')*40
            env=dict(temp=temp,run_id=run,head_sha=head)
            generated=authored.future.generate(manifest,root,env)
            if not generated['ready']:raise AssertionError(generated)
            native_raw=boat.zipped(root);origin_raw=boat.zipped(root.with_name(root.name+'.origin'))
            ident=301 if base else 201+2*index
            native=authored.metadata(ident,'all-existing-model-pairs-'+str(run)+'-900004',native_raw,
                saved=current[0]+timedelta(seconds=2),run=run,head=env['head_sha'])
            origin=authored.metadata(ident+1,'all-native-future-origin-'+str(run)+'-900010',origin_raw,
                saved=current[0]+timedelta(seconds=3),run=run,head=env['head_sha'])
            pairs.append(dict(future_artifact=pin(native),origin_artifact=pin(origin)))
            archives.append(dict(future=dict(raw=native_raw,metadata=native),origin=dict(raw=origin_raw,metadata=origin)))
        if base:
            if mode=='mixed_candidate':base['batches'][0]=pairs[0];base['archives'][0]=archives[0]
            elif mode=='overlap':base['batches']+=pairs;base['archives']+=archives
            else:raise AssertionError('unknown authored variant')
            return base
        return dict(batches=pairs,archives=archives,requests=requests,source_archives=source_archives)
    finally:
        for item in reversed(patches):item.stop()
        environment.stop();temporary.cleanup()


class FutureBatchTests(unittest.TestCase):
    def api(self):
        from race_ai import all_existing_model_future_result_capture as existing
        api=getattr(existing,'admit_forecast_batches',None)
        self.assertTrue(callable(api),'multi-origin RESULT admission is missing')
        return api

    def test_separate_horse_and_later_other_origins_keep_own_clocks_and_same_f30(self):
        api=self.api();value=deepcopy(separate_fixture(short_horse=True));before=deepcopy(value)
        with patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(authored.KEY).decode()):
            result=api(value['batches'],value['archives'],now=EVALUATED,key=authored.KEY)
        self.assertEqual(len(result['records']),30)
        self.assertEqual([len(batch['records']) for batch in result['batches']],[5,25])
        self.assertEqual(result['forecast_counts_by_sport'],dict(boat=14,autorace=6,keirin=5,horse=5))
        self.assertEqual(len(result['source_input_artifacts']),3)
        self.assertNotEqual(result['batches'][0]['origin']['origin_metadata']['created_at'],
                            result['batches'][1]['origin']['origin_metadata']['created_at'])
        self.assertEqual(value,before)

    def test_bad_pairing_bytes_or_late_early_horse_origin_rejects(self):
        api=self.api();fixture=deepcopy(separate_fixture(short_horse=True))
        for change in ('origin_pair','forecast_bytes','late_horse','missing_batch','overlap'):
            value=deepcopy(fixture)
            if change=='origin_pair':value['archives'][0]['origin']=value['archives'][1]['origin']
            elif change=='forecast_bytes':value['archives'][0]['future']['raw']=value['archives'][0]['future']['raw'][:-1]
            elif change=='late_horse':value['archives'][0]['origin']['metadata']['created_at']=(authored.NOW+timedelta(minutes=2)).isoformat()
            elif change=='missing_batch':value['batches'].pop();value['archives'].pop()
            else:value['batches'].append(deepcopy(value['batches'][0]));value['archives'].append(deepcopy(value['archives'][0]))
            with self.subTest(change=change),patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(authored.KEY).decode()),self.assertRaises(ValueError):
                api(value['batches'],value['archives'],now=EVALUATED,key=authored.KEY)

    def test_distinct_authenticated_forecasts_still_reject_mixed_candidate_overlap_and_missing_model(self):
        api=self.api()
        for mode,reason in (('mixed_candidate','SAME_EXACT_F30'),('overlap','DISJOINT_CELLS'),
                            ('missing_model','EXACT_DISJOINT_THIRTY_UNION')):
            value=deepcopy(separate_fixture(mode=mode))
            with self.subTest(mode=mode),patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(authored.KEY).decode()),self.assertRaisesRegex(ValueError,reason):
                api(value['batches'],value['archives'],now=EVALUATED,key=authored.KEY)


if __name__=='__main__':unittest.main()
