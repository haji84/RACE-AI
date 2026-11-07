"""Pure authored JRA future-result binding; no source, key, clock or Git I/O."""
import base64
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai.manual_official_capture import official_rights_ref
from tests import test_jra_official_result_adapter as fixtures


def capture(raw,url,started,completed):
    return dict(raw_base64=base64.b64encode(raw).decode(),metadata=dict(source_url=url,final_url=url,status=200,
        byte_count=len(raw),source_sha256=sha256(raw).hexdigest(),fetched_at=started.isoformat(),
        response_received_at=completed.isoformat(),headers={'Content-Type':'text/html; charset=shift_jis'},
        method='GET',http_method='GET'))


def fixture(*,result_raw=None,link=True):
    native=json.loads(json.dumps(fixtures.frozen()).replace('SYNTHETIC_PERSONAL_SOURCE',official_rights_ref('horse')))
    card_url=native['source_evidence'][0]['source_ref'];result_url=fixtures.URL.replace('pw01sde10','pw01sde01')
    card=fixtures.sparse_fixtures.card()
    if link:card+=('<a href="'+result_url+'">結果</a>').encode('cp932')
    start=fixtures.NOW-timedelta(seconds=20)
    case=dict(sport='horse',race_id=native['snapshot']['race']['race_id'],route=dict(kind='JRA_CARD_PUBLISHED_GET',card_url=card_url))
    return case,native,capture(card,card_url,start,start+timedelta(seconds=1)),capture(
        fixtures.result_html() if result_raw is None else result_raw,result_url,start+timedelta(seconds=2),start+timedelta(seconds=3))


class FutureHorseResultTests(unittest.TestCase):
    def api(self):return importlib.import_module('race_ai.official_future_horse_result')

    def test_fresh_literal_card_result_reuses_original_settled_label_without_mutation(self):
        api=self.api();case,native,card,result=fixture();before=deepcopy((case,native,card,result))
        self.assertEqual(api.discover_result(case,native,card,now=fixtures.NOW),result['metadata']['source_url'])
        expected=api.C._parse(result,native,'horse',now=fixtures.NOW,allow_order_only=False)
        actual=api.bind_result(case,native,card,result,now=fixtures.NOW)
        self.assertEqual(actual,expected);self.assertEqual(actual['status'],'settled');self.assertEqual(actual['payout_per_100_yen'],1230)
        self.assertEqual((case,native,card,result),before)

    def test_absent_or_wrong_race_anchor_is_none_and_distinct_same_race_links_are_ambiguous(self):
        api=self.api();case,native,card,result=fixture(link=False)
        self.assertIsNone(api.discover_result(case,native,card,now=fixtures.NOW))
        wrong=result['metadata']['source_url'].replace('1120261107','1020261107')
        raw=base64.b64decode(card['raw_base64'])+('<a href="'+wrong+'">結果</a>').encode('cp932')
        changed=capture(raw,case['route']['card_url'],fixtures.NOW-timedelta(seconds=20),fixtures.NOW-timedelta(seconds=19))
        self.assertIsNone(api.discover_result(case,native,changed,now=fixtures.NOW))
        case,native,card,result=fixture();raw=base64.b64decode(card['raw_base64'])
        raw+=('<a href="'+result['metadata']['source_url'].replace('/AA','/AB')+'">別の結果</a>').encode('cp932')
        changed=capture(raw,case['route']['card_url'],fixtures.NOW-timedelta(seconds=20),fixtures.NOW-timedelta(seconds=19))
        with self.assertRaises(ValueError):api.discover_result(case,native,changed,now=fixtures.NOW)

    def test_no_prefilled_link_missing_frozen_card_or_wrong_identity_can_discover(self):
        api=self.api()
        for mutation in ('race','sport','route','frozen_source','prefilled','roster'):
            case,native,card,result=fixture()
            if mutation=='race':case['race_id']=case['race_id'].replace(':11',':10')
            elif mutation=='sport':case['sport']='keirin'
            elif mutation=='route':case['route']['kind']='DIRECT_RESULT_GET'
            elif mutation=='frozen_source':native=json.loads(json.dumps(native).replace(case['route']['card_url'],
                'https://www.jra.go.jp/other-frozen-source'))
            elif mutation=='prefilled':case['route'].update(result_url=result['metadata']['source_url'],link_capture=card)
            else:native['snapshot']['participants'][1]['number']=native['snapshot']['participants'][0]['number']
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):api.discover_result(case,native,card,now=fixtures.NOW)

    def test_wait_is_enforced_on_actual_get_starts_even_when_conversion_is_later(self):
        api=self.api();case,native,card,result=fixture()
        cutoff=api.C.stamp(native['snapshot']['race']['sales_cutoff_at']);due=cutoff+timedelta(seconds=120)
        for kind in ('now','card','result'):
            changed_card=deepcopy(card);changed_result=deepcopy(result);now=fixtures.NOW
            if kind=='now':now=due-timedelta(microseconds=1)
            elif kind=='card':changed_card['metadata']['fetched_at']=(due-timedelta(microseconds=1)).isoformat()
            else:changed_result['metadata']['fetched_at']=(due-timedelta(microseconds=1)).isoformat()
            with self.subTest(kind=kind),self.assertRaises(ValueError):api.bind_result(case,native,changed_card,changed_result,now=now)
        card['metadata']['fetched_at']=due.isoformat();card['metadata']['response_received_at']=(due+timedelta(seconds=1)).isoformat()
        result['metadata']['fetched_at']=(due+timedelta(seconds=2)).isoformat();result['metadata']['response_received_at']=(due+timedelta(seconds=3)).isoformat()
        self.assertEqual(api.bind_result(case,native,card,result,now=due+timedelta(seconds=3))['status'],'settled')

    def test_clock_bytes_method_url_and_discovery_order_mismatches_hold(self):
        api=self.api()
        for mutation in ('raw','hash','redirect','wrong_url','method','missing_start','future_completion','result_before_discovery','meeting'):
            case,native,card,result=fixture()
            if mutation=='raw':result['raw_base64']=base64.b64encode(base64.b64decode(result['raw_base64'])+b'changed').decode()
            elif mutation=='hash':card['metadata']['source_sha256']='f'*64
            elif mutation=='redirect':result['metadata']['final_url']+='&changed=1'
            elif mutation=='wrong_url':result['metadata']['source_url']=result['metadata']['final_url']=result['metadata']['source_url'].replace('/AA','/AB')
            elif mutation=='method':card['metadata']['method']='POST'
            elif mutation=='missing_start':result['metadata'].pop('fetched_at')
            elif mutation=='future_completion':result['metadata']['response_received_at']=(fixtures.NOW+timedelta(seconds=1)).isoformat()
            elif mutation=='result_before_discovery':result['metadata']['fetched_at']=card['metadata']['fetched_at']
            else:
                # Alter the meeting-day component only in the literal href.
                original=result['metadata']['source_url'];other=original.replace('20260301','20260302')
                raw=base64.b64decode(card['raw_base64']).replace(original.encode(),other.encode())
                card=capture(raw,case['route']['card_url'],fixtures.NOW-timedelta(seconds=20),fixtures.NOW-timedelta(seconds=19))
                with self.assertRaisesRegex(ValueError,'PUBLISHED_RESULT_FULL_IDENTITY'):
                    api.discover_result(case,native,card,now=fixtures.NOW)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):api.bind_result(case,native,card,result,now=fixtures.NOW)

    def test_exact_frozen_roster_and_pending_special_semantics_are_preserved(self):
        api=self.api()
        for raw,status in ((fixtures.result_html(table=False),'pending'),(fixtures.result_html(places=('1','1','3')),'special')):
            case,native,card,result=fixture(result_raw=raw)
            expected=api.C._parse(result,native,'horse',now=fixtures.NOW,allow_order_only=False)
            self.assertEqual(api.bind_result(case,native,card,result,now=fixtures.NOW),expected)
            self.assertEqual(expected['status'],status);self.assertIsNone(expected['payout_per_100_yen'])
        case,native,card,result=fixture(result_raw=fixtures.result_html().replace(b'2020000002',b'2020000099'))
        with self.assertRaises(ValueError):api.bind_result(case,native,card,result,now=fixtures.NOW)

    def test_history_joins_real_typed_jra_source_zip_and_rejects_unknown_or_denied_epochs(self):
        from race_ai import all_existing_model_future_source_capture as history
        from race_ai import jra_future_source_capture as horse
        from race_ai import manual_official_capture as policy
        from scripts import jra_future_source_capture as wrapper
        from scripts import all_existing_model_future_source_capture as common
        from tests.test_jra_future_source_capture import manifest,NOW,CARD,DISCOVERY
        from tests.test_all_existing_model_future_source_capture import archive_directory
        from tests.test_all_existing_model_source_packet_freeze import KEY
        from tests.test_official_issue_transport import FakeGitHub
        from tests.test_manual_official_capture import Response
        for outcome in ('success','expired_success','late_wire','unknown','denied'):
            value=manifest();pin=value['horse_baseline_artifact'];clock=[NOW]
            native_model=dict(sport='horse',input_schema=horse.jra.native.SCHEMA_SPARSE,
                created_at=(NOW-timedelta(days=1)).isoformat())
            baseline=dict(receipt=dict(id=pin['id'],digest=pin['digest'],created_at=(NOW-timedelta(minutes=2)).isoformat(),
                workflow_run=dict(id=pin['run_id'],head_sha=pin['head_sha'])),training=dict(scope='OPERATOR_SUPPLIED_RESEARCH',
                training_sha256='b'*64,models={'horse/'+horse.LEARNED_ID:dict(sport='horse',input_schema=horse.jra.native.SCHEMA_SPARSE,
                    native_training=native_model),**{str(n):{} for n in range(29)}}))
            env=dict(run_id=42,head_sha='a'*40,run_attempt=1);plan=horse.prepare(value,baseline,now=NOW)
            body=horse.marker_body(value,env,baseline,{},plan,now=NOW)
            consumed=horse.reserve(body,KEY,horse.MarkerTransport(FakeGitHub()),now=NOW);cipher=consumed.pop('_ciphertext')
            if outcome=='late_wire':clock[0]+=timedelta(hours=2)
            def get(request,timeout):
                if outcome=='unknown':raise RuntimeError('authored interruption')
                clock[0]+=timedelta(seconds=.1)
                raw=('<html><a href="'+CARD+'">公開出馬表</a></html>').encode()
                return Response(raw,url=request.full_url,status=403 if outcome=='denied' else 200,
                    headers={'Content-Type':'text/html; charset=UTF-8'})
            def sleep(seconds):clock[0]+=timedelta(seconds=seconds)
            with tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);root.chmod(0o700);source=root/'source';source.mkdir(mode=0o700);directory=root/'cache'
                with patch.object(wrapper,'utc_now',side_effect=lambda:clock[0]):
                    try:
                        if outcome=='late_wire':
                            # Authored invalid original: bypass only the injected
                            # HTTP fixture's runtime guard, then require archive
                            # verification to reject its real later wire clocks.
                            with patch.object(wrapper,'guarded_opener',side_effect=lambda _plan,fetch,**_:fetch):
                                wrapper.collect(value,plan,directory,opener=get,sleeper=sleep,monotonic=lambda:clock[0].timestamp())
                        else:wrapper.collect(value,plan,directory,opener=get,sleeper=sleep,monotonic=lambda:clock[0].timestamp())
                    except RuntimeError:pass
                cache=policy._load(directory);items,complete=common.inventory(directory,source,env,key=KEY)
                reservation=dict(schema=horse.JOURNAL,state='RESERVED',manifest=value,manifest_sha256=horse.digest(value),
                    workflow_run_id=42,code_sha='a'*40,epoch_started_at=NOW.isoformat(),plan_sha256=horse.digest(plan),
                    once_body=body,history={},maximum_requests=32,source_requests_actual=None)
                journal=dict(reservation,state='CAPTURE_RETAINED',completed_at=clock[0].isoformat(),capture_inventory=items,
                    raw_retention_complete=complete,source_requests_actual=None if outcome=='unknown' else len(cache['attempts']),
                    source_request_upper_bound=32,native_ready=False,fixed_as_of=None,capture_cache=cache,once_proof=consumed)
                for name,payload in (('reservation.enc',reservation),('plan.enc',plan),('collection.enc',journal)):
                    common._seal(source/name,payload,env,KEY)
                (source/'once.enc').write_bytes(cipher);(source/'once.enc').chmod(0o600)
                raw=archive_directory(source);actual=dict(id=801,name='official-jra-future-source-capture-42',expired=False,
                    size_in_bytes=len(raw),digest='sha256:'+sha256(raw).hexdigest(),created_at=(clock[0]+timedelta(seconds=1)).isoformat(),
                    expires_at=(NOW+timedelta(days=1)).isoformat(),workflow_run=dict(id=42,head_sha='a'*40,
                        repository_id=1416489937,head_repository_id=1416489937))
                source_pin=dict(id=801,digest=actual['digest'],run_id=42,head_sha='a'*40)
                now=clock[0]+timedelta(seconds=2)
                if outcome=='expired_success':now+=timedelta(hours=6)
                if outcome in ('success','expired_success'):
                    admitted,_=history._future_epoch(dict(raw=raw,metadata=actual),source_pin,now=now,key=KEY)
                    self.assertEqual(admitted['capture_cache'],cache);self.assertEqual(admitted['source_requests_actual'],3)
                else:
                    with self.subTest(outcome=outcome),self.assertRaises(ValueError):
                        history._future_epoch(dict(raw=raw,metadata=actual),source_pin,now=now,key=KEY)


if __name__=='__main__':unittest.main()
