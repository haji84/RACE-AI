"""Invented normal-UI source fixtures test parsing, never real predictions."""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import base64
import importlib
import json
import unittest

from race_ai.keirin_official_sparse_adapter import build_native_inputs
from race_ai.manual_official_capture import official_rights_ref
from tests.test_keirin_official_sparse_adapter import fixture as input_fixture, capture, NOW as BEFORE

NOW=BEFORE+timedelta(hours=4)
RIGHTS=official_rights_ref('keirin')
CONTEXT='RACE_AI_KEIRIN_OFFICIAL_RESULT_ARCHIVE_CONTEXT_V1'
b64=lambda raw:base64.b64encode(raw).decode('ascii')
wire=lambda value:json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()


def fixture(*,unit=True):
    listing,live=input_fixture();a,ma,b,mb,dom=capture(listing,live)
    frozen=build_native_inputs(a,ma,b,mb,now=BEFORE,rendered_dom_bytes=dom)['requests'][0]['native_payload']
    selected=deepcopy(live['PC0201']['C0201data']);selected['encSelParaR']='fictional-public-race-selector-2'
    identity=dict(C0201data=selected,resultCd=0,writeANA=False)
    result=dict(resultCd=0,writeANA=False,tyakujyunDispFlg=True,haraiGakuDispFlg=True,bikouDispFlg=False,
        tyakujyunItemSubData=[dict(tyaku=str(n),syaban=str(n),sensyuRegistNo=f'01{n:04d}',
            sensyuName=f'架空選手{n}',kojinStateItemSubData=[]) for n in range(1,10)],
        haraiGakuSubData=dict(APartReturnDispFlg=False,RT3HaraiGakuDispItemSubData=[dict(
            kumiBan='1-2-3',haraiGaku='1,230',ninki='5',ninkiDispFlg=True,kumiDispFlg=True)]))
    def http(raw,url,offset,mime='application/json;charset=UTF-8'):
        return dict(source_url=url,final_url=url,method='GET',status=200,byte_count=len(raw),
            source_sha256=sha256(raw).hexdigest(),fetched_at=(NOW+timedelta(seconds=offset-1)).isoformat(),
            response_received_at=(NOW+timedelta(seconds=offset)).isoformat(),headers={'content-type':mime})
    identity_raw=wire(identity);raw=wire(result)
    im=http(identity_raw,'https://keirin.jp/pc/json?encp=fictional-public-race-selector-2&type=JSJ001',-7)
    metadata=http(raw,'https://keirin.jp/pc/json?encp=fictional-public-race-selector-2&type=JSJ012',-4)
    dom=b'<html><body>Fictional normal result panel</body></html>'
    ledger=[]
    for i,m in enumerate((im,metadata),1):
        ledger.append(dict(sequence=i,url=m['source_url'],method='GET',resource_type='xhr',status=200,
            byte_count=m['byte_count'],source_sha256=m['source_sha256'],request_started_at=m['fetched_at'],
            response_received_at=m['response_received_at'],body_captured_at=m['response_received_at']))
    ledger.append(dict(event='NORMAL_SEMANTIC_UI_CLICK',label='競走結果',before='https://keirin.jp/pc/racelive',
        after='https://keirin.jp/pc/racelive',at=(NOW-timedelta(seconds=3)).isoformat()))
    browser=dict(schema='RACE_AI_PRIVATE_OFFICIAL_BROWSER_PROBE_V1',source_url='https://keirin.jp/pc/top',
        started_at=(NOW-timedelta(seconds=20)).isoformat(),captured_at=(NOW-timedelta(seconds=1)).isoformat(),
        normal_ui_only=True,undocumented_api_manually_called=False,http_access_denied=False,
        entire_host_stopped=False,stop_reason='FINISHED',network_host_allowlist=['keirin.jp','www.keirin.jp'],
        ledger=ledger,rendered_dom=dict(byte_count=len(dom),source_sha256=sha256(dom).hexdigest()))
    unit_raw='<html><body>払戻金は100円あたりの金額です。</body></html>'.encode()
    unit_capture=dict(raw_base64=b64(unit_raw),metadata=http(unit_raw,'https://keirin.jp/pc/static/help/payout.html',-2,'text/html;charset=UTF-8')) if unit else None
    metadata['keirin_result_archive_context']=dict(schema=CONTEXT,identity_capture=dict(raw_base64=b64(identity_raw),metadata=im),
        browser_capture=dict(metadata=browser,rendered_dom_base64=b64(dom)),payout_unit_capture=unit_capture)
    return result,raw,metadata,frozen


def rebuild(result,metadata):
    raw=wire(result);metadata['source_sha256']=sha256(raw).hexdigest();metadata['byte_count']=len(raw)
    e=metadata['keirin_result_archive_context']['browser_capture']['metadata']['ledger'][1]
    e['source_sha256']=metadata['source_sha256'];e['byte_count']=len(raw)
    return raw


def change_identity(metadata,callback):
    ctx=metadata['keirin_result_archive_context'];cap=ctx['identity_capture']
    value=json.loads(base64.b64decode(cap['raw_base64']));callback(value['C0201data'])
    raw=wire(value);cap['raw_base64']=b64(raw)
    cap['metadata']['source_sha256']=sha256(raw).hexdigest();cap['metadata']['byte_count']=len(raw)
    entry=ctx['browser_capture']['metadata']['ledger'][0]
    entry['source_sha256']=sha256(raw).hexdigest();entry['byte_count']=len(raw)


class KeirinOfficialResultTests(unittest.TestCase):
    def adapter(self):
        self.assertIsNotNone(importlib.util.find_spec('race_ai.keirin_official_result_adapter'))
        return importlib.import_module('race_ai.keirin_official_result_adapter')

    def parse(self,raw,metadata,frozen,**options):
        return self.adapter().parse_result(raw,metadata,frozen_native_payload=frozen,now=NOW,source_rights_ref=RIGHTS,**options)

    def test_full_result_matches_frozen_identity_and_explicit_per100_payment(self):
        result,raw,metadata,frozen=fixture();original=deepcopy((metadata,frozen))
        out=self.parse(raw,metadata,frozen)
        self.assertEqual(out['status'],'settled');self.assertEqual(out['ordered_top3'],[1,2,3])
        self.assertEqual(out['payout_per_100_yen'],1230);self.assertTrue(out['identity_verified'])
        self.assertIsNone(out['published_at']);self.assertEqual(len(out['roster']),9)
        self.assertEqual(out['closed_at'],frozen['snapshot']['race']['sales_cutoff_at'])
        self.assertEqual((metadata,frozen),original)

    def test_missing_unit_keeps_actual_source_facts_and_emits_no_teacher(self):
        result,raw,metadata,frozen=fixture(unit=False)
        facts=self.adapter().parse_official_result_source(raw,metadata,now=NOW)
        self.assertEqual(facts['observed_top3'],[1,2,3]);self.assertEqual(facts['observed_payout_yen'],1230)
        self.assertFalse(facts['future_frozen_input_paired'])
        out=self.parse(raw,metadata,frozen)
        self.assertEqual(out['status'],'pending');self.assertEqual(out['reason'],'PAYOUT_UNIT_NOT_VERIFIED')
        self.assertEqual(out['ordered_top3'],[]);self.assertIsNone(out['payout_per_100_yen'])

    def test_selector_body_identity_roster_source_and_ui_mismatches_reject(self):
        for change in ('selector','identity','roster','source','ui','dom','rights'):
            result,raw,m,frozen=fixture();ctx=m['keirin_result_archive_context']
            if change=='selector':m['source_url']=m['final_url']=m['source_url'].replace('selector-2','selector-3')
            if change=='identity':frozen['snapshot']['race']['race_id']='keirin:2030-01-15:keirin-jyo-48:3'
            if change=='roster':result['tyakujyunItemSubData'][0]['sensyuRegistNo']='019999';raw=rebuild(result,m)
            if change=='source':raw+=b'changed'
            if change=='ui':ctx['browser_capture']['metadata']['undocumented_api_manually_called']=True
            if change=='dom':ctx['browser_capture']['rendered_dom_base64']=b64(b'changed')
            if change=='rights':m['source_rights_ref']='NOT_THE_OWNER_PURPOSE'
            with self.subTest(change=change),self.assertRaises(ValueError):self.parse(raw,m,frozen)

    def test_pending_refund_tie_nonfinish_cancel_and_ambiguous_payment_stay_unscored(self):
        for change in ('pending','refund','tie','nonfinish','cancel','multiple','remark'):
            result,raw,m,frozen=fixture();ctx=m['keirin_result_archive_context']
            if change=='pending':result['tyakujyunDispFlg']=False
            if change=='refund':result['haraiGakuSubData']['APartReturnDispFlg']=True
            if change=='tie':result['tyakujyunItemSubData'][1]['tyaku']='1'
            if change=='nonfinish':result['tyakujyunItemSubData'][-1]['tyaku']='欠場'
            if change=='multiple':result['haraiGakuSubData']['RT3HaraiGakuDispItemSubData']*=2
            if change=='remark':result['bikouDispFlg']=True
            if change=='cancel':
                cap=ctx['identity_capture'];identity=json.loads(base64.b64decode(cap['raw_base64']))
                identity['C0201data']['flgRaceCancel']=True;iraw=wire(identity);cap['raw_base64']=b64(iraw)
                cap['metadata']['source_sha256']=sha256(iraw).hexdigest();cap['metadata']['byte_count']=len(iraw)
                entry=ctx['browser_capture']['metadata']['ledger'][0];entry['source_sha256']=sha256(iraw).hexdigest();entry['byte_count']=len(iraw)
            raw=rebuild(result,m);out=self.parse(raw,m,frozen)
            with self.subTest(change=change):
                self.assertEqual(out['status'],'pending' if change=='pending' else 'special')
                self.assertEqual(out['ordered_top3'],[]);self.assertIsNone(out['payout_per_100_yen'])

    def test_minimum_ticket_price_does_not_prove_payout_unit(self):
        result,raw,m,frozen=fixture();cap=m['keirin_result_archive_context']['payout_unit_capture']
        text='<html><body>車券は100円から購入できます。</body></html>'.encode();cap['raw_base64']=b64(text)
        cap['metadata']['source_sha256']=sha256(text).hexdigest();cap['metadata']['byte_count']=len(text)
        out=self.parse(raw,m,frozen);self.assertEqual(out['status'],'pending')

    def test_payment_conflict_and_capture_before_close_or_in_future_reject(self):
        for change in ('payment','before_close','future','companion_future'):
            result,raw,m,frozen=fixture()
            if change=='payment':result['haraiGakuSubData']['RT3HaraiGakuDispItemSubData'][0]['kumiBan']='3-2-1';raw=rebuild(result,m)
            if change=='before_close':frozen['snapshot']['race']['sales_cutoff_at']=(NOW+timedelta(minutes=1)).isoformat()
            if change=='future':m['response_received_at']=(NOW+timedelta(seconds=1)).isoformat()
            if change=='companion_future':m['keirin_result_archive_context']['identity_capture']['metadata']['response_received_at']=(NOW+timedelta(seconds=1)).isoformat()
            with self.subTest(change=change),self.assertRaises(ValueError):self.parse(raw,m,frozen)

    def test_official_published_cutoff_must_match_frozen_cutoff(self):
        result,raw,m,frozen=fixture()
        change_identity(m,lambda selected:selected['C0201racedtl'].update(aftBetTime='12:00'))
        with self.assertRaises(ValueError):self.parse(raw,m,frozen)

    def test_unknown_published_cutoff_stays_pending_without_inferred_minutes(self):
        for value in (None,'--'):
            result,raw,m,frozen=fixture()
            change_identity(m,lambda selected:selected['C0201racedtl'].update(aftBetTime=value))
            out=self.parse(raw,m,frozen)
            with self.subTest(value=value):
                self.assertEqual(out['status'],'pending');self.assertEqual(out['reason'],'OFFICIAL_CUTOFF_NOT_AVAILABLE')
                self.assertEqual(out['ordered_top3'],[]);self.assertIsNone(out['payout_per_100_yen'])

    def test_nonaffirmative_wrong_denominator_or_hidden_unit_claims_stay_pending(self):
        for text in ('払戻金の手数料は100円あたりの定額です。',
                     '払戻金は1100円あたりの金額です。',
                     '払戻金は100円あたりの金額ではありません。',
                     '<template>払戻金は100円あたりの金額です。</template>車券は100円から。',
                     '<p hidden>払戻金は100円あたりの金額です。</p>',
                     '<p aria-hidden="true">払戻金は100円あたりの金額です。</p>',
                     '<p style="display:none">払戻金は100円あたりの金額です。</p>'):
            result,raw,m,frozen=fixture();cap=m['keirin_result_archive_context']['payout_unit_capture']
            data=('<html><body>'+text+'</body></html>').encode();cap['raw_base64']=b64(data)
            cap['metadata']['source_sha256']=sha256(data).hexdigest();cap['metadata']['byte_count']=len(data)
            out=self.parse(raw,m,frozen)
            with self.subTest(text=text):self.assertEqual(out['status'],'pending')

    def test_status_codes_and_cancellation_flags_require_exact_source_types(self):
        for where,value in (('main',False),('main',True),('identity',False),('identity',True),
                            ('flgRaceCancel',1),('flgRaceCancel','true'),('flgSectionCancel',1),('flgSectionCancel','true')):
            result,raw,m,frozen=fixture()
            if where=='main':result['resultCd']=value;raw=rebuild(result,m)
            elif where=='identity':
                ctx=m['keirin_result_archive_context'];cap=ctx['identity_capture']
                identity=json.loads(base64.b64decode(cap['raw_base64']));identity['resultCd']=value;data=wire(identity)
                cap['raw_base64']=b64(data);cap['metadata']['source_sha256']=sha256(data).hexdigest();cap['metadata']['byte_count']=len(data)
                entry=ctx['browser_capture']['metadata']['ledger'][0];entry['source_sha256']=sha256(data).hexdigest();entry['byte_count']=len(data)
            else:change_identity(m,lambda selected:selected.update({where:value}))
            with self.subTest(where=where,value=value),self.assertRaises(ValueError):self.parse(raw,m,frozen)

    def test_order_only_opt_in_returns_exact_nonmonetary_label_and_keeps_default_pending(self):
        result,raw,m,frozen=fixture(unit=False)
        default=self.parse(raw,m,frozen);out=self.parse(raw,m,frozen,allow_order_only=True)
        self.assertEqual(default['status'],'pending')
        self.assertEqual(out['schema'],'RACE_AI_OFFICIAL_ORDER_ONLY_RESULT_V1')
        self.assertEqual(out['status'],'rank_confirmed')
        self.assertEqual(out['reason'],'ORDER_CONFIRMED_PAYOUT_UNIT_UNVERIFIED')
        self.assertEqual(out['evaluation_scope'],'ORDER_ONLY_NO_MONETARY_EVALUATION')
        self.assertEqual(out['ordered_top3'],[1,2,3]);self.assertEqual(out['published_payout_yen'],1230)
        self.assertFalse(out['payout_unit_verified']);self.assertIsNone(out['payout_per_100_yen'])
        self.assertEqual(len(out),19);self.assertEqual(set(out)-set(default),
            {'schema','published_payout_yen','payout_unit_verified','evaluation_scope'})
        self.assertTrue(out['identity_verified']);self.assertEqual(out['refund_numbers'],[])
        self.assertIsNone(out['published_at'])

    def test_order_only_cannot_upgrade_pending_special_or_unknown_official_cutoff(self):
        for change in ('pending','refund','tie','nonfinish','multiple','remark','cutoff'):
            result,raw,m,frozen=fixture(unit=False)
            if change=='pending':result['tyakujyunDispFlg']=False
            if change=='refund':result['haraiGakuSubData']['APartReturnDispFlg']=True
            if change=='tie':result['tyakujyunItemSubData'][1]['tyaku']='1'
            if change=='nonfinish':result['tyakujyunItemSubData'][-1]['tyaku']='欠場'
            if change=='multiple':result['haraiGakuSubData']['RT3HaraiGakuDispItemSubData']*=2
            if change=='remark':result['bikouDispFlg']=True
            if change=='cutoff':change_identity(m,lambda selected:selected['C0201racedtl'].update(aftBetTime=None))
            raw=rebuild(result,m);default=self.parse(raw,m,frozen)
            with self.subTest(change=change):
                self.assertEqual(self.parse(raw,m,frozen,allow_order_only=True),default)
                self.assertNotEqual(default['status'],'rank_confirmed')

    def test_order_only_does_not_bypass_bindings_or_coerce_option_types(self):
        for value in (None,1,'true'):
            result,raw,m,frozen=fixture(unit=False)
            with self.subTest(option=value),self.assertRaises(ValueError):
                self.parse(raw,m,frozen,allow_order_only=value)
        for change in ('race','roster','selector','cutoff','boolean_status'):
            result,raw,m,frozen=fixture(unit=False)
            if change=='race':frozen['snapshot']['race']['race_id']='keirin:2030-01-15:keirin-jyo-48:3'
            if change=='roster':result['tyakujyunItemSubData'][0]['sensyuRegistNo']='019999';raw=rebuild(result,m)
            if change=='selector':m['source_url']=m['final_url']=m['source_url'].replace('selector-2','selector-3')
            if change=='cutoff':change_identity(m,lambda selected:selected['C0201racedtl'].update(aftBetTime='12:00'))
            if change=='boolean_status':result['resultCd']=False;raw=rebuild(result,m)
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.parse(raw,m,frozen,allow_order_only=True)

    def test_order_only_option_keeps_unit_verified_cash_result_unchanged(self):
        result,raw,m,frozen=fixture()
        default=self.parse(raw,m,frozen);out=self.parse(raw,m,frozen,allow_order_only=True)
        self.assertEqual(out,default);self.assertEqual(out['status'],'settled');self.assertEqual(len(out),15)


if __name__=='__main__':unittest.main()
