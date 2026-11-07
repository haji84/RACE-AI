"""Authored full thirty-cell native/origin/raw RESULT codecs; no real sources."""
import base64
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from functools import lru_cache
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai.actions_contract import digest
from race_ai import all_existing_model_registry as registry
from race_ai import all_existing_model_official_results as official
from race_ai.all_existing_model_pairs import make_private_pairs
from race_ai.boat_all_model_store import seal_forecasts
from race_ai.boat_private_original_archive import seal_original_zip
from race_ai.boat_venue_learning import read_candidate
from race_ai.manual_official_capture import official_rights_ref
from race_ai.official_order_only_result import EVALUATION_SCOPE
from scripts import all_existing_model_native_future as future
from tests import test_all_existing_model_native_future as boat
from tests import test_all_existing_model_native_future_v3 as future_fixture
from tests.test_all_existing_model_native_future_v3 import KEY,NOW,metadata
from tests.test_all_existing_model_result_intake import packed
from tests.test_frozen_day_cycle import observation as boat_observation
from tests import test_autorace_official_result_adapter as auto
from tests import test_keirin_official_result_adapter as kei
from tests import test_jra_official_result_adapter as horse

EVALUATED = NOW+timedelta(hours=2)
JST=timezone(timedelta(hours=9))
b64=lambda raw:base64.b64encode(raw).decode()
wire=lambda value:json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()


def shifted_clocks(value,delta):
    if type(value) is dict:return {k:shifted_clocks(v,delta) for k,v in value.items()}
    if type(value) is list:return [shifted_clocks(v,delta) for v in value]
    if type(value) is str and 'T' in value:
        try:
            t=datetime.fromisoformat(value.replace('Z','+00:00'))
            if t.utcoffset() is not None:return (t+delta).isoformat()
        except ValueError:pass
    return value


def actual_metadata(raw,ident,name,run,head,saved):
    return metadata(ident,name,raw,saved=saved,run=run,head=head)


@lru_cache(maxsize=1)
def _sources():
    future_fixture.NativeFutureV3Tests.setUpClass()
    fixture=future_fixture.NativeFutureV3Tests('runTest');fixture.setUp()
    try:
        # Author actual-shaped identifiers before the only source/forecast freeze.
        # None of these fictional records is a historical or live-source claim.
        for request in fixture.requests:
            sport,mid=request['cell_key'].split('/',1)
            if sport=='boat':continue
            native=request['native_payload'];info=registry.identity(mid,sport,native)
            venue={'autorace':'isesaki','keirin':'keirin-jyo-48','horse':'福島'}[sport]
            rid={'autorace':'autorace:2030-02-02:isesaki:1',
                 'keirin':'keirin:2030-02-02:keirin-jyo-48:2',
                 'horse':'horse:2030-02-02:jra-03:11'}[sport]
            native=json.loads(json.dumps(native).replace(info['race_id'],rid).replace(
                info['race_cutoff_at'],'2030-02-02T23:50:00+09:00'))
            if registry.group(mid)=='autorace_personal':
                native['registered_roster']['roster']={str(n):str(1000+n) for n in range(1,4)}
                native['registered_roster']['native_input_sha256']=digest(native['snapshot'])
            else:
                native['snapshot']['race']['venue']=venue
                for p in native['snapshot']['participants']:
                    n=p['number'];p['identity']=str(1000+n) if sport=='autorace' else \
                        f'01{n:04d}' if sport=='keirin' else 'jra:202000000'+str(n)
            request['native_payload']=native
        source=fixture.temp/'authored-new-source'
        make_private_pairs(fixture.source_context,fixture.requests,source,now=NOW-timedelta(minutes=6),allow_source=lambda *_:True)
        (source/'summary.json').unlink();source_raw=boat.zipped(source)
        source_meta=dict(fixture.source,size_in_bytes=len(source_raw),digest='sha256:'+sha256(source_raw).hexdigest())
        fixture.mapping['actions/artifacts/100']=json.dumps(source_meta).encode()
        fixture.mapping['actions/artifacts/100/zip']=source_raw
        fixture.manifest['source_input_artifacts'][0]['digest']=source_meta['digest']
        generated=future.generate(fixture.manifest,fixture.root,fixture.env)
        if generated.get('forecast_partition_count')!=30:raise AssertionError(generated)
        native_raw=boat.zipped(fixture.root);origin_raw=boat.zipped(fixture.root.with_name(fixture.root.name+'.origin'))
        native_meta=actual_metadata(native_raw,201,'all-existing-model-pairs-42-900004',42,'d'*40,NOW+timedelta(seconds=2))
        origin_meta=actual_metadata(origin_raw,202,'all-native-future-origin-42-900010',42,'d'*40,NOW+timedelta(seconds=3))
        return dict(native_raw=native_raw,native_metadata=native_meta,origin_raw=origin_raw,origin_metadata=origin_meta,
                    requests=deepcopy(fixture.requests),generated=generated)
    finally:fixture.doCleanups()


def official_sources(requests):
    natives={request['cell_key'].split('/',1)[0]:request['native_payload'] for request in requests
             if 'snapshot' in request['native_payload'] and request['native_payload']['snapshot'].get('race',{}).get('sport')}
    # AUTO: three authored complete finishers, actual raw JSON + request + DOM.
    data=auto.fixture();main=data['metadata'];capture=NOW+timedelta(minutes=50)
    delta=capture-datetime.fromisoformat(main['response_received_at']);main=shifted_clocks(main,delta)
    main.pop('auto_result_archive_context',None);context=main['auto_result_context']
    result=data['result'];result['body']['raceResult']=[dict(order=i+1,carNo=n,playerCode=1000+n,
        playerName=f'Invented Driver {n}',accidentCode=None,accidentName=None,retireFlag=0,foulCode=None)
        for i,n in enumerate((3,1,2))]
    result['body']['refundInfo']['rt3']['list']=[{'1thCarNo':3,'2thCarNo':1,'3thCarNo':2,'refund':21710}]
    request=wire(dict(placeCode=3,raceDate='2030-02-02',raceNo='1'))
    info=json.loads(base64.b64decode(context['race_info_capture']['raw_base64']))
    info['body'].update(periodStartDate='2030-02-02',periodEndDate='2030-02-02',paragraphday=1,
                        raceStartTime='23:53',telvoteTime='23:50')
    context['request_body_base64']=b64(request);companion=context['race_info_capture'];companion['raw_base64']=b64(wire(info))
    companion['request_body_base64']=b64(request)
    for m in (main,companion['metadata']):m['request_body_sha256']=sha256(request).hexdigest()
    companion['metadata'].update(source_sha256=sha256(wire(info)).hexdigest(),byte_count=len(wire(info)))
    dom=('<html><body><h1>伊勢崎 レース結果 2030年</h1><table class="race-infoTable"><tr><td>2月2日</td><td>1R</td><td>3100m</td></tr></table>'
         '<p>投票締切23:50 発走予定23:53</p>'+''.join(f'<p>Invented Driver {n}</p>' for n in (1,2,3))+
         '<p>3連単3-1-221,710円</p></body></html>').encode()
    context['rendered_dom_capture']['raw_base64']=b64(dom)
    context['rendered_dom_capture']['metadata'].update(byte_count=len(dom),source_sha256=sha256(dom).hexdigest(),
        final_url='https://autorace.jp/race_info/Live/isesaki/RaceResult/2030-02-02_1')
    raw_auto=wire(result);main.update(byte_count=len(raw_auto),source_sha256=sha256(raw_auto).hexdigest())
    # KEIRIN: seven authored registered finishers + independently captured header.
    result,_,km,_=kei.fixture(unit=False);target=NOW+timedelta(minutes=52)
    km=shifted_clocks(km,target-datetime.fromisoformat(km['response_received_at']))
    result['tyakujyunItemSubData']=result['tyakujyunItemSubData'][:7]
    def change(selected):
        selected.update(selKaisai='20300202')
        selected['C0201racedtl'].update(aftBetTime='23:50',bfrBetTime='23:50',aftStartTime='23:53',bfrStartTime='23:53')
        selected['C0201racedtl']['C0201sensyu']=selected['C0201racedtl']['C0201sensyu'][:7]
    kei.change_identity(km,change);raw_kei=kei.rebuild(result,km)
    # HORSE: complete raw official-shaped result; no source data is inferred.
    raw_horse=horse.result_html().decode('cp932').replace('2026年11月7日','2030年2月2日').encode('cp932')
    hm=horse.source_metadata(raw_horse);horse_url='https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde1003203003011120300202/AA'
    hm.update(source_url=horse_url,final_url=horse_url,
        fetched_at=(NOW+timedelta(minutes=53,seconds=59)).isoformat(),
        response_received_at=(NOW+timedelta(minutes=54)).isoformat())
    captures=[dict(raw_base64=b64(raw),metadata=meta) for raw,meta in ((raw_auto,main),(raw_kei,km),(raw_horse,hm))]
    from race_ai.autorace_official_result_adapter import parse_result as parse_auto
    from race_ai.keirin_official_result_adapter import parse_result as parse_kei
    from race_ai.jra_official_result_adapter import parse_result as parse_horse
    labels=[parse_auto(raw_auto,main,frozen_native_payload=natives['autorace'],now=EVALUATED,
                       source_rights_ref=official_rights_ref('autorace'),allow_order_only=True),
            parse_kei(raw_kei,km,frozen_native_payload=natives['keirin'],now=EVALUATED,
                      source_rights_ref=official_rights_ref('keirin'),allow_order_only=True),
            parse_horse(raw_horse,hm,frozen_native_payload=natives['horse'],now=EVALUATED,
                        source_rights_ref=official_rights_ref('horse'))]
    payload=official.build_result_payload(captures,labels,run_id=51,code_sha='e'*40,generated_at=NOW+timedelta(hours=1),
        day_jst='2030-02-02',frozen_native_payloads=list(natives.values()),allow_order_only=True)
    raw=packed([('results.enc',seal_forecasts(payload,run_id='51',round_no=1,key=KEY))])
    return dict(kind='OFFICIAL',raw=raw,metadata=actual_metadata(raw,301,'all-existing-official-results-51-1',51,'e'*40,
        NOW+timedelta(hours=1,seconds=2)),expected_run_id=51,expected_head_sha='e'*40),labels


def boat_source(requests):
    request=next(r for r in requests if r['cell_key'].startswith('boat/'))
    sport,mid=request['cell_key'].split('/',1);info=registry.identity(mid,sport,request['native_payload'])
    rid='20300202-17-01';value=boat_observation(dict(race_id=rid,cutoff_at=info['race_cutoff_at'],top8=[[1,2,3]],roster=info['roster']))
    value['captured_at']=(NOW+timedelta(hours=1)).isoformat()
    value['source_url']='https://www.boatrace.jp/owpc/pc/race/raceresult?rno=1&jcd=17&hd=20300202'
    report=dict(schema='RACE_AI_EXISTING_MODEL_CYCLE_REPORT_V1',day_jst='2030-02-02',run_id='52',code_sha='f'*40,
        updated_at=(NOW+timedelta(hours=1,seconds=1)).isoformat(),result_observation_versions=1)
    report['report_sha256']=digest(report)
    inner=packed([('official-result-observations.json',wire([value])),('status.json',wire(report))])
    raw=packed([('private-original.enc',seal_original_zip(inner,run_id=52,head_sha='f'*40,kind='RESULT',key=KEY))])
    meta=actual_metadata(raw,302,'race-existing-cycle-52-cycle-02',52,'f'*40,NOW+timedelta(hours=1,seconds=3))
    return dict(kind='BOAT',raw=raw,metadata=meta,expected_run_id=52,expected_head_sha='f'*40),value


@lru_cache(maxsize=1)
def _full_fixture():
    with patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(KEY).decode()):
        source=deepcopy(_sources());official_result,labels=official_sources(source['requests']);legacy,boat_label=boat_source(source['requests'])
        source.update(results=[legacy,official_result],official_labels=labels,boat_label=boat_label)
        return source


def full_fixture():return deepcopy(_full_fixture())


class ThirtyOrderArtifactTests(unittest.TestCase):
    def module(self):
        from race_ai import all_existing_model_thirty_order_pdca as api
        return api
    def test_all_thirty_mixed_original_labels_real_crypto_rank_only_restore(self):
        api=self.module();self.assertTrue(callable(getattr(api,'score_thirty_order_pairs_artifacts',None)))
        fixture=full_fixture();before=digest(fixture['requests'])
        with tempfile.TemporaryDirectory() as temporary,patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(KEY).decode()):
            root=Path(temporary)/'score'
            summary=api.score_thirty_order_pairs_artifacts(fixture['native_raw'],fixture['native_metadata'],
                fixture['origin_raw'],fixture['origin_metadata'],fixture['results'],root,now=EVALUATED,
                expected_native_run_id=42,expected_native_head_sha='d'*40)
            self.assertEqual(summary['partition_count'],30);self.assertEqual(summary['teacher_matched_forecasts'],30)
            self.assertTrue(summary['all_thirty_cells_scored']);self.assertFalse(summary['monetary_evaluation_available'])
            self.assertEqual(summary['evaluation_scope'],EVALUATION_SCOPE)
            payloads=[read_candidate(p) for p in root.iterdir() if p.is_dir()]
            self.assertEqual(len(payloads),30)
            for payload in payloads:
                self.assertTrue(api.verify_private_thirty_order_pdca(payload))
                sport=payload['private_forecast']['pair']['sport'];label=payload['order_observation']
                self.assertEqual(label['status'],'rank_confirmed' if sport in ('autorace','keirin') else 'settled')
                original=payload['observation']
                if sport=='boat':self.assertEqual(original,fixture['boat_label'])
                else:self.assertEqual(original,next(o for o in fixture['official_labels'] if o['sport']==sport))
                for part in (payload['score'],payload['comparison'],payload['summary']):self.assert_no_money(part)
            raw=boat.zipped(root);actual=actual_metadata(raw,401,'all-existing-model-thirty-order-pdca-61-900023',61,'a'*40,
                                                       EVALUATED+timedelta(seconds=2))
            restored=api.verify_thirty_order_pdca_artifact(raw,actual,now=EVALUATED+timedelta(seconds=3),
                expected_run_id=61,expected_head_sha='a'*40,expected_source_context_sha256=summary['source_context_sha256'])
            self.assertTrue(restored['independent_pdca_artifact_receipt_verified']);self.assertTrue(restored['all_thirty_cells_scored'])
            self.assertEqual(digest(fixture['requests']),before)
            # Even a fixture-key resealer cannot turn altered receipt clocks or
            # an edited original label into a valid structural restore.
            for change in ('late_origin','expired_origin','label_status','rank_score'):
                wrong=deepcopy(payloads[0]);context=wrong['source_context']
                if change=='late_origin':context['origin']['origin_metadata']['created_at']=context['origin']['generation']['cutoff_at']
                elif change=='expired_origin':context['origin']['origin_metadata']['expired']=True
                elif change=='label_status':wrong['observation']['status']='rank_confirmed'
                else:wrong['score']['paired']=not wrong['score']['paired']
                wrong['source_context_sha256']=digest(context)
                row=api.rank._row(wrong['private_forecast'],wrong['order_observation'],EVALUATED)
                wrong['summary']=api._summary(context,[row])
                with self.subTest(change=change),self.assertRaises(ValueError):api.verify_private_thirty_order_pdca(wrong)
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                first=archive.namelist()[0].split('/')[0]
                members=[(name,archive.read(name)) for name in archive.namelist() if not name.startswith(first+'/')]
            partial=packed(members);partial_meta=dict(actual,size_in_bytes=len(partial),digest='sha256:'+sha256(partial).hexdigest())
            with self.assertRaisesRegex(ValueError,'COMPLETE_FORECAST_SET_REQUIRED'):
                api.verify_thirty_order_pdca_artifact(partial,partial_meta,now=EVALUATED+timedelta(seconds=3),
                    expected_run_id=61,expected_head_sha='a'*40)
    def assert_no_money(self,value):
        forbidden={'stake_yen','payout_yen','refund_yen','net_yen','roi','profit','return_rate','recovery_rate',
                   'payout_per_100_yen','published_payout_yen'}
        if isinstance(value,dict):
            self.assertFalse(forbidden & value.keys())
            for item in value.values():self.assert_no_money(item)
        elif isinstance(value,list):
            for item in value:self.assert_no_money(item)


if __name__=='__main__':unittest.main()
