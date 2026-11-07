"""Explicit order-only purpose through real synthetic source and AES codecs."""
import base64
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import io
import unittest
import zipfile
from race_ai import all_existing_model_official_results as results
from race_ai.boat_all_model_store import seal_forecasts
from race_ai.manual_official_capture import official_rights_ref
from race_ai.official_order_only_result import EVALUATION_SCOPE
from tests import test_autorace_official_result_adapter as auto
from tests import test_keirin_official_result_adapter as keirin
KEY=bytes(range(32));HEAD='a'*40

class OrderOnlyAuthenticatedResultsTests(unittest.TestCase):
    def case(self,sport):
        if sport=='autorace':
            from race_ai.autorace_official_result_adapter import parse_result
            data=auto.fixture();raw=auto.wire(data['result']);metadata=data['metadata'];native=data['frozen'];now=auto.NOW
            metadata.pop('auto_result_archive_context',None)
        else:
            from race_ai.keirin_official_result_adapter import parse_result
            _,raw,metadata,native=keirin.fixture(unit=False);now=keirin.NOW
        label=parse_result(raw,metadata,frozen_native_payload=native,now=now,
            source_rights_ref=official_rights_ref(sport),allow_order_only=True)
        return raw,metadata,native,now,label
    def archive(self,payload,now):
        cipher=seal_forecasts(payload,run_id='42',round_no=1,key=KEY);stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:archive.writestr('results.enc',cipher)
        raw=stream.getvalue();metadata=dict(id=990,name='all-existing-official-results-42-1',expired=False,
            digest='sha256:'+sha256(raw).hexdigest(),size_in_bytes=len(raw),created_at=(now+timedelta(seconds=2)).isoformat(),
            expires_at=(now+timedelta(days=7)).isoformat(),workflow_run=dict(id=42,head_sha=HEAD,
                repository_id=1416489937,head_repository_id=1416489937))
        return raw,metadata
    def test_both_sports_require_explicit_mode_preserve_nineteen_fields_and_no_cash_claim(self):
        for sport in ('autorace','keirin'):
            raw,metadata,native,now,label=self.case(sport)
            self.assertEqual(label['status'],'rank_confirmed');before=deepcopy(label)
            arguments=dict(captures=[dict(raw_base64=base64.b64encode(raw).decode(),metadata=metadata)],
                observations=[label],run_id=42,code_sha=HEAD,generated_at=now,day_jst='2030-01-15',frozen_native_payloads=[native])
            with self.subTest(sport=sport):
                with self.assertRaises(ValueError):results.build_result_payload(**arguments)
                payload=results.build_result_payload(**arguments,allow_order_only=True)
                results.seal_results(payload,round_no=1,frozen_native_payloads=[native],key=KEY,allow_order_only=True)
                wire,actual=self.archive(payload,now)
                read=dict(now=now+timedelta(seconds=10),expected_run_id=42,expected_head_sha=HEAD,
                    frozen_native_payloads=[native],key=KEY)
                with self.assertRaises(ValueError):results.observations_from_official_result_artifact(wire,actual,**read)
                admitted=results.observations_from_official_result_artifact(wire,actual,**read,allow_order_only=True)
                self.assertEqual(admitted['observations'],[before]);self.assertEqual(label,before)
                self.assertEqual(admitted['summary']['ordinary_settled_result_count'],0)
                self.assertEqual(admitted['summary']['order_only_confirmed_result_count'],1)
                self.assertEqual(admitted['summary']['label_evaluation_scope'],EVALUATION_SCOPE)
                self.assertIsNone(admitted['observations'][0]['payout_per_100_yen'])
                self.assertEqual(len(admitted['result_source_evidence'][0]['sources']),3)

    def test_existing_official_pdca_gate_refuses_rank_only_as_a_formal_outcome(self):
        from race_ai.autorace_ab_pdca import audit_cycle
        _,_,_,now,label=self.case('autorace')
        row=dict(race_id=label['race_id'],sport='autorace',cutoff_at=label['closed_at'],cutoff_verified=True,
            trifecta_offered=True,entrants=list(map(int,label['roster'])))
        def no_write(*_):raise AssertionError('rank-only teacher entered formal result audit')
        result=audit_cycle([row],clock=lambda:now,load_forecast=no_write,load_result=lambda _:label,
            verify_forecast=no_write,verify_result=lambda *_:True,latest_audit=no_write,
            append_audit=no_write,read_audit=no_write)
        self.assertEqual(result['events'][0]['state'],'RESULT_OR_AUDIT_UNVERIFIED_NO_REPOST')
        self.assertEqual({v['evaluable_races'] for v in result['kpis'].values()},{0})
        self.assertIsNone(label['payout_per_100_yen']);self.assertFalse(label['payout_unit_verified'])
        from race_ai.all_existing_model_pdca import _observation,RESULT_FIELDS
        pair=dict(sport='autorace',race_id=label['race_id'],cutoff_at=label['closed_at'],
            baseline_normalized=dict(roster=label['roster']),learned_normalized=dict(roster=label['roster']))
        for value in (label,{name:label[name] for name in RESULT_FIELDS}):
            with self.assertRaises(ValueError):_observation(value,pair,now)
        false_cash={name:label[name] for name in RESULT_FIELDS};false_cash['status']='settled'
        with self.assertRaisesRegex(ValueError,'RESULT_PAYOUT_INVALID'):_observation(false_cash,pair,now)

if __name__=='__main__':unittest.main()
