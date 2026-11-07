"""Fictional public-browser responses test conversion, never real accuracy."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import importlib
import json
import unittest

from race_ai import comprehensive_four_sport_models as native
from race_ai.four_sport_learning import LEARNED_ID, _vectors, vector_schema
from race_ai.four_sport_model_suite import ALL_MODELS
from race_ai import all_existing_model_registry as registry

JST=timezone(timedelta(hours=9))
NOW=datetime(2030,1,15,9,tzinfo=JST)


def html(data):
    return ('<!doctype html><html><body><script>var jsonData={};'+''.join(
        'jsonData['+json.dumps(k)+']='+json.dumps(v,ensure_ascii=False)+';' for k,v in data.items())+
        '</script><main>出走表 発売締切 発走予定</main></body></html>').encode()


def fixture():
    listed=[];details=[];header=[]
    for number in range(1,10):
        identity=f'01{number:04d}'
        listed.append(dict(syaban=number,senNo=identity,senName=f'架空選手{number}',kyaku='追'))
        details.append(dict(syaban=number,wakuban=(number+1)//2,sensyuRegistNo=identity,
            sensyuName=f'架空選手{number}',kyakusitu='追',age='30',kyuhan='S2',
            heikinTokuten=str(80+number),syouritu=str(number*3),rentairitu2='40.0',rentairitu3='50.0',
            konResultInfoSubData=dict(resultInfoSubData=[]),tyo4InfoSubData=dict(resultInfoSubData=[])))
        header.append(dict(carNum=number,numPlayer=identity))
    clock=dict(syumoku='S級一般',kyori=2025,syukai=5,nameKyosou='先固',aftStartTime='11:53',
        aftBetTime='11:50',bfrStartTime='11:53',bfrBetTime='11:50',flgViewPut=True,C0201sensyu=header)
    case=dict(selKaisai='20300115',selKjyoCd='48',selRaceNo=2,C0201racedtl=clock)
    listing=dict(PC0201=dict(C0201data=deepcopy(case)),PJ0305=dict(kaisaihi='20300115',keirinCd='48',
        rInfo=[dict(raceNo=2,denTime='11:50',stTime='11:53',sInfo=listed,nInfo=[])]))
    live=dict(PC0201=dict(C0201data=deepcopy(case)),PJ0315=dict(bKeirinjyoCd='48',sensyuTypeInfo=details))
    return listing,live


def capture(listing,live):
    a,b=html(listing),html(live);dom=b
    def stamp(seconds):return (NOW+timedelta(seconds=seconds)).isoformat()
    ledger=[]
    for seq,path,raw,start,end in ((1,'racelist',a,-35,-30),(2,'racelive',b,-25,-20)):
        ledger.append(dict(sequence=seq,url='https://keirin.jp/pc/'+path,method='POST',status=200,
            resource_type='document',content_type='text/html;charset=UTF-8',byte_count=len(raw),
            source_sha256=sha256(raw).hexdigest(),request_started_at=stamp(start),
            response_received_at=stamp(end-1),body_captured_at=stamp(end)))
    ledger.extend([dict(event='NORMAL_SEMANTIC_UI_CLICK',label='出走表\n一覧',before='https://keirin.jp/pc/top',
        after='https://keirin.jp/pc/racelist',at=stamp(-28)),dict(event='NORMAL_SEMANTIC_UI_CLICK',label='2R',
        before='https://keirin.jp/pc/racelist',after='https://keirin.jp/pc/racelive',at=stamp(-18))])
    metadata=dict(schema='RACE_AI_PRIVATE_OFFICIAL_BROWSER_PROBE_V1',source_url='https://keirin.jp/pc/top',
        final_url='https://keirin.jp/pc/racelive',started_at=stamp(-40),captured_at=stamp(-10),
        normal_ui_only=True,undocumented_api_manually_called=False,http_access_denied=False,
        entire_host_stopped=False,stop_reason='FINISHED',network_host_allowlist=['keirin.jp','www.keirin.jp'],
        actual_request_count=2,ledger=ledger,rendered_dom=dict(byte_count=len(dom),source_sha256=sha256(dom).hexdigest()))
    return a,metadata,b,deepcopy(metadata),dom


class KeirinOfficialSparseTests(unittest.TestCase):
    def adapter(self):
        self.assertIsNotNone(importlib.util.find_spec('race_ai.keirin_official_sparse_adapter'))
        return importlib.import_module('race_ai.keirin_official_sparse_adapter')

    def convert(self,listing=None,live=None,**options):
        if listing is None:listing,live=fixture()
        a,ma,b,mb,dom=capture(listing,live)
        return self.adapter().build_native_inputs(a,ma,b,mb,rendered_dom_bytes=dom,now=NOW,**options)

    def test_actual_published_percent_and_cohort_rank_make_five_existing_native_inputs(self):
        listing,live=fixture();before=deepcopy((listing,live))
        out=self.convert(listing,live)
        self.assertEqual(out['state'],'READY');self.assertEqual(len(out['requests']),5)
        snap=out['snapshot'];native.validate(snap,allow_source=lambda *a:True)
        self.assertEqual(snap['race']['sales_cutoff_at'],'2030-01-15T11:50:00+09:00')
        self.assertEqual(snap['race']['distance_m'],2025)
        first=snap['participants'][0];last=snap['participants'][-1]
        self.assertAlmostEqual(first['features']['recent_win_form']['value'],.03)
        self.assertEqual(first['features']['recent_points']['value'],0)
        self.assertEqual(last['features']['recent_points']['value'],1)
        self.assertIsNone(first['features']['recent_win_form']['sample_n'])
        self.assertIn('ability',first['missing']);self.assertNotIn('ability',first['features'])
        self.assertFalse(out['source_audit']['request_body_retained'])
        self.assertFalse(out['independent_pre_cutoff_receipt_verified'])
        self.assertEqual((listing,live),before)
        for request in out['requests']:
            mid=request['cell_key'].split('/',1)[1];payload=request['native_payload']
            registry.validate_payload(mid,'keirin',payload,at=NOW,allow_source=lambda *a:True)
            if mid!=LEARNED_ID:
                prediction=registry.predict(mid,'keirin',payload,at=NOW,allow_source=lambda *a:True)
                self.assertEqual(len(prediction['candidates']),504)
                self.assertAlmostEqual(sum(v['score'] for v in prediction['candidates']),1)
        self.assertEqual(len(next(iter(_vectors(snap,'keirin').values()))),len(vector_schema('keirin',sparse=True)))

    def test_tied_points_are_ordinal_midrank_and_missing_points_never_get_zero_filled(self):
        listing,live=fixture()
        for p in live['PJ0315']['sensyuTypeInfo']:p['heikinTokuten']='90'
        out=self.convert(listing,live)
        self.assertEqual({p['features']['recent_points']['value'] for p in out['snapshot']['participants']},{.5})
        live['PJ0315']['sensyuTypeInfo'][0]['heikinTokuten']='--'
        out=self.convert(listing,live)
        self.assertEqual(out['state'],'READY')
        self.assertTrue(all('recent_points' not in p['features'] for p in out['snapshot']['participants']))
        self.assertTrue(all('recent_form' in p['missing'] for p in out['snapshot']['participants']))

    def test_missing_win_frequency_holds_every_cell_and_cannot_borrow_place_rate(self):
        for value in (None,'','--','NaN','101'):
            listing,live=fixture();live['PJ0315']['sensyuTypeInfo'][0]['syouritu']=value
            out=self.convert(listing,live)
            with self.subTest(value=value):self.assertEqual(out['state'],'HOLD');self.assertEqual(out['requests'],[])

    def test_case_clock_roster_dom_and_browser_provenance_mismatches_hold(self):
        for mutation in ('race','day','venue','id','slot','cutoff','browser','dom','source','denial'):
            listing,live=fixture()
            if mutation=='race':live['PC0201']['C0201data']['selRaceNo']=3
            if mutation=='day':live['PC0201']['C0201data']['selKaisai']='20300116'
            if mutation=='venue':live['PJ0315']['bKeirinjyoCd']='74'
            if mutation=='id':live['PJ0315']['sensyuTypeInfo'][0]['sensyuRegistNo']='019999'
            if mutation=='slot':live['PJ0315']['sensyuTypeInfo'][0]['syaban']=9
            if mutation=='cutoff':live['PC0201']['C0201data']['C0201racedtl']['aftBetTime']='11:49'
            a,ma,b,mb,dom=capture(listing,live)
            if mutation=='browser':mb['normal_ui_only']=False
            if mutation=='dom':dom=dom+b'changed'
            if mutation=='source':b=b+b'changed'
            if mutation=='denial':mb['ledger'].append(dict(sequence=3,url='https://keirin.jp/pc/test',method='GET',status=403))
            out=self.adapter().build_native_inputs(a,ma,b,mb,now=NOW,rendered_dom_bytes=dom)
            with self.subTest(mutation=mutation):self.assertEqual(out['state'],'HOLD');self.assertEqual(out['requests'],[])

    def test_withdrawals_preserve_real_numbers_and_seven_or_nine_only(self):
        listing,live=fixture();listing['PJ0305']['rInfo'][0]['sInfo'][2]['assen']='(欠場)'
        self.assertEqual(self.convert(listing,live)['state'],'HOLD')
        listing['PJ0305']['rInfo'][0]['sInfo'][5]['assen']='(取消)'
        listing['PJ0305']['rInfo'][0]['sInfo'][0]['assen']='(追加)'
        out=self.convert(listing,live)
        self.assertEqual(out['state'],'READY')
        self.assertEqual([p['number'] for p in out['snapshot']['participants']],[1,2,4,5,7,8,9])
        self.assertEqual(out['snapshot']['participants'][0]['features']['recent_win_form']['value'],.03)

    def test_false_analysis_callback_and_source_capture_after_now_hold(self):
        self.assertEqual(self.convert(allow_source=lambda *a:False)['state'],'HOLD')
        listing,live=fixture();a,ma,b,mb,dom=capture(listing,live)
        mb['ledger'][1]['body_captured_at']=(NOW+timedelta(seconds=1)).isoformat()
        out=self.adapter().build_native_inputs(a,ma,b,mb,now=NOW,rendered_dom_bytes=dom)
        self.assertEqual(out['state'],'HOLD')

    def test_normal_back_cache_reference_never_becomes_a_new_response_clock(self):
        listing,live=fixture();a,ma,b,mb,dom=capture(listing,live)
        cached=dict(url='https://keirin.jp/pc/racelist',method='POST',resource_type='document',
            browser_cache_replay=True,source_sha256=sha256(a).hexdigest(),
            original_captured_at=ma['ledger'][0]['body_captured_at'],at=(NOW-timedelta(seconds=15)).isoformat())
        ma['ledger'].append(cached);mb['ledger'].append(deepcopy(cached))
        out=self.adapter().build_native_inputs(a,ma,b,mb,now=NOW,rendered_dom_bytes=dom)
        self.assertEqual(out['state'],'READY')
        self.assertEqual(out['source_evidence'][0]['captured_at'],ma['ledger'][0]['body_captured_at'])

    def test_mixed_tactics_style_is_allround_and_keeps_observed_category_lineage(self):
        listing,live=fixture()
        listing['PJ0305']['rInfo'][0]['sInfo'][0]['kyaku']='両'
        live['PJ0315']['sensyuTypeInfo'][0]['kyakusitu']='両'
        out=self.convert(listing,live)
        self.assertEqual(out['state'],'READY')
        self.assertEqual(out['snapshot']['participants'][0]['style'],'allround')
        self.assertEqual(out['feature_lineage'][0]['running_style']['source_value'],'両')
        self.assertEqual(out['feature_lineage'][0]['running_style']['native_category'],'allround')

    def test_unrelated_normal_official_query_history_keeps_selected_document_guards(self):
        listing,live=fixture();a,ma,b,mb,dom=capture(listing,live)
        history=dict(sequence=3,url='https://keirin.jp/pc/json?encp=fictional-public-selector&type=JSJ001',
            method='GET',resource_type='xhr',status=200)
        ma['ledger'].append(deepcopy(history));mb['ledger'].append(deepcopy(history))
        result=self.adapter().build_native_inputs(a,ma,b,mb,now=NOW,rendered_dom_bytes=dom)
        self.assertEqual(result['state'],'READY')
        for url in ('https://foreign.example/pc/json?type=JSJ001',
                    'https://keirin.jp/pc/json?access_token=secret',
                    'https://keirin.jp/pc/json?type=JSJ001#fragment'):
            bad=deepcopy(mb);bad['ledger'][-1]['url']=url
            with self.subTest(url=url):
                self.assertEqual(self.adapter().build_native_inputs(a,ma,b,bad,now=NOW,rendered_dom_bytes=dom)['state'],'HOLD')
        bad=deepcopy(mb);bad['ledger'][-1]['status']=403
        self.assertEqual(self.adapter().build_native_inputs(a,ma,b,bad,now=NOW,rendered_dom_bytes=dom)['state'],'HOLD')


if __name__=='__main__':unittest.main()
