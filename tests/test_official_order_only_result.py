"""Invented official-order contracts; no provider, owner key or monetary claim."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
import unittest

from race_ai.actions_contract import digest
from race_ai.manual_official_capture import official_rights_ref
from tests.test_nonboat_sparse_contracts import sparse_snapshot, training_rows

SCHEMA = 'RACE_AI_OFFICIAL_ORDER_ONLY_RESULT_V1'
SCOPE = 'ORDER_ONLY_NO_MONETARY_EVALUATION'
NOW = datetime(2030, 1, 15, 3, tzinfo=timezone.utc)
HOST = {'horse':'www.jra.go.jp', 'autorace':'autorace.jp', 'keirin':'keirin.jp'}


def label(sport='autorace', snapshot=None):
    snapshot = sparse_snapshot(sport) if snapshot is None else snapshot
    race = snapshot['race']
    return dict(schema=SCHEMA, race_id=race['race_id'], sport=sport, status='rank_confirmed',
        ordered_top3=[3, 2, 1], roster={str(p['number']):p['identity'] for p in snapshot['participants']},
        identity_verified=True, captured_at='2030-01-15T11:00:00+09:00', published_at=None,
        source_ref='https://'+HOST[sport]+'/fictional/official-result', source_rights_ref=official_rights_ref(sport),
        source_sha256='b'*64, payout_per_100_yen=None, published_payout_yen=21710,
        refund_numbers=[], closed_at=race['sales_cutoff_at'], payout_unit_verified=False,
        evaluation_scope=SCOPE, reason='ORDER_CONFIRMED_PAYOUT_UNIT_UNVERIFIED')


class OfficialOrderOnlyResultTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('race_ai.official_order_only_result'), 'typed rank-only validator absent')
        return importlib.import_module('race_ai.official_order_only_result')

    def test_exact_nineteen_fields_all_three_sports_preserve_original_and_optional_raw_money(self):
        api = self.module()
        self.assertEqual(api.SCHEMA, SCHEMA); self.assertEqual(api.EVALUATION_SCOPE, SCOPE)
        for sport in HOST:
            for money in (None, 21710):
                value = label(sport); value['published_payout_yen'] = money; before = deepcopy(value)
                checked = api.validate_order_only(value, sport=sport, roster=value['roster'], race_id=value['race_id'])
                self.assertEqual(checked, before); self.assertEqual(value, before)
                self.assertEqual(set(checked), api.OBSERVATION_FIELDS); self.assertEqual(len(checked), 19)
                self.assertEqual(digest(checked), digest(before)); self.assertIsNot(checked, value)
                checked['ordered_top3'][0] = 99; self.assertEqual(value, before)

    def test_fake_unit_money_flags_source_sport_and_nonnormal_rosters_reject(self):
        api = self.module()
        changes = [dict(schema='UNTYPED'),dict(status='settled'),dict(evaluation_scope='CASH'),dict(reason='SELF_ASSERTED'),
            dict(payout_per_100_yen=21710),dict(payout_unit_verified=True),dict(payout_unit_verified=0),
            dict(published_payout_yen=True),dict(published_payout_yen=1.0),dict(published_payout_yen=0),
            dict(refund_numbers=[8]),dict(refund_numbers=None),dict(identity_verified=1),dict(ordered_top3=[1,1,2]),
            dict(ordered_top3=[True,2,3]),dict(ordered_top3=[1,2,99]),dict(source_sha256='x'*64),
            dict(source_ref='https://www.jra.go.jp/fictional/result'),dict(source_rights_ref='self-granted'),
            dict(sport='boat'),dict(roster={'1':'same','2':'same','3':'different'}),dict(roster={'01':'a','2':'b','3':'c'}),
            dict(roster={'1':'a','2':'b','9':'c'}),dict(roster={'1':'','2':'b','3':'c'})]
        for change in changes:
            value=label();value.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):api.validate_order_only(value)
        for field in label():
            value=label();value.pop(field)
            with self.subTest(missing=field),self.assertRaises(ValueError):api.validate_order_only(value)
        with self.assertRaises(ValueError):api.validate_order_only(dict(label(),unknown='ignored'))
        with self.assertRaises(ValueError):api.validate_order_only(label(),sport='horse')
        with self.assertRaises(ValueError):api.validate_order_only(label(),roster={'1':'other'})
        with self.assertRaises(ValueError):api.validate_order_only(label(),race_id='different-race')

    def test_result_clocks_require_real_cutoff_before_capture_and_no_fake_publication(self):
        api=self.module()
        for change in (dict(captured_at=label()['closed_at']),dict(captured_at='2030-01-15T08:00:00+09:00'),
                       dict(captured_at='2030-01-15T11:00:00'),dict(closed_at=None),
                       dict(published_at='2030-01-15T12:00:00+09:00'),dict(published_at='2030-01-15T08:00:00+09:00')):
            value=label();value.update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):api.validate_order_only(value)

    def test_native_intake_keeps_full_typed_label_and_original_status_without_cash_projection(self):
        from race_ai.all_existing_model_intake import _ordinary_result
        from race_ai import all_existing_model_registry as registry
        from race_ai.four_sport_model_suite import ALL_MODELS
        for sport in HOST:
            snapshot=sparse_snapshot(sport);value=label(sport,snapshot);before=deepcopy(value)
            payload=dict(snapshot=snapshot,scope=snapshot['scope'],stage='P1')
            info=registry.identity(ALL_MODELS[0],sport,payload)
            admitted,reason=_ordinary_result(value,info,NOW)
            self.assertIsNone(reason);self.assertEqual(admitted,before);self.assertEqual(value,before)
            self.assertEqual(admitted['status'],'rank_confirmed');self.assertIsNone(admitted['payout_per_100_yen'])
            changed=deepcopy(value);changed['closed_at']='2030-01-15T09:59:00+09:00'
            with self.assertRaises(ValueError):_ordinary_result(changed,info,NOW)
            with self.assertRaises(ValueError):_ordinary_result(value,info,NOW-timedelta(days=1))

    def test_ranker_consumes_complete_typed_order_with_existing_window_and_authorizer(self):
        from race_ai import four_sport_learning as ranker
        for sport in HOST:
            snapshot=sparse_snapshot(sport);snapshot['scope']='OPERATOR_SUPPLIED_RESEARCH'
            value=label(sport,snapshot);before=deepcopy(value);calls=[]
            def authorized(ref,rights,purpose):
                calls.append((ref,rights,purpose));return purpose=='result_evaluation'
            order=ranker._label(value,snapshot,scope=snapshot['scope'],allow_result=authorized,window_end=NOW)
            self.assertEqual(order,[3,2,1]);self.assertEqual(value,before)
            self.assertEqual(calls,[(value['source_ref'],value['source_rights_ref'],'result_evaluation')])
            for kind in ('rights','roster','cutoff','race','future'):
                changed=deepcopy(value);end=NOW
                if kind=='rights':changed['source_rights_ref']='wrong'
                elif kind=='roster':changed['roster']['1']='wrong-identity'
                elif kind=='cutoff':changed['closed_at']='2030-01-15T09:59:00+09:00'
                elif kind=='race':changed['race_id']='another-race'
                else:end=NOW-timedelta(days=1)
                with self.subTest(sport=sport,kind=kind),self.assertRaises(ValueError):
                    ranker._label(changed,snapshot,scope=snapshot['scope'],allow_result=authorized,window_end=end)
            with self.assertRaises(ValueError):
                ranker._label(value,snapshot,scope=snapshot['scope'],allow_result=lambda *_:False,window_end=NOW)

    def test_malformed_typed_markers_never_fall_through_to_ordinary_cash_label(self):
        from race_ai.all_existing_model_intake import _ordinary_result
        from race_ai import all_existing_model_registry as registry
        from race_ai.four_sport_model_suite import ALL_MODELS
        snapshot=sparse_snapshot('autorace');value=label('autorace',snapshot)
        info=registry.identity(ALL_MODELS[0],'autorace',dict(snapshot=snapshot))
        for change in (dict(schema='WRONG',status='settled',payout_per_100_yen=21710),
                       dict(payout_unit_verified=True),dict(evaluation_scope='CASH')):
            changed=deepcopy(value);changed.update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):_ordinary_result(changed,info,NOW)

    def test_legacy_cash_intake_and_ranker_label_contracts_remain_exact(self):
        from race_ai import four_sport_learning as ranker
        from race_ai.all_existing_model_intake import _ordinary_result
        from race_ai import all_existing_model_registry as registry
        from race_ai.four_sport_model_suite import ALL_MODELS
        from tests.test_comprehensive_four_sport_models import sample
        snapshot=sparse_snapshot('autorace');typed=label('autorace',snapshot)
        legacy={k:v for k,v in typed.items() if k not in ('schema','published_payout_yen','payout_unit_verified','evaluation_scope')}
        legacy.update(status='settled',reason='NORMAL_ORDINARY_RESULT',payout_per_100_yen=21710)
        before=deepcopy(legacy);info=registry.identity(ALL_MODELS[0],'autorace',dict(snapshot=snapshot))
        admitted,reason=_ordinary_result(legacy,info,NOW);self.assertIsNone(reason)
        self.assertEqual(legacy,before);self.assertNotIn('evaluation_scope',admitted)
        self.assertEqual((admitted['status'],admitted['payout_per_100_yen']),('settled',21710))
        old={k:deepcopy(legacy[k]) for k in ('race_id','status','ordered_top3','published_at','captured_at','source_ref','source_rights_ref','source_sha256')}
        self.assertEqual(ranker._label(old,snapshot,scope='SYNTHETIC_ONLY',allow_result=None,window_end=NOW),[3,2,1])
        dense=sample('autorace',size=8);old.pop('source_sha256')
        with self.assertRaises(ValueError):ranker._label(old,dense,scope='SYNTHETIC_ONLY',allow_result=None,window_end=NOW)
        old['published_at']='2030-01-15T10:30:00+09:00'
        self.assertEqual(ranker._label(old,dense,scope='SYNTHETIC_ONLY',allow_result=None,window_end=NOW),[3,2,1])

    def test_six_native_ranker_examples_fit_from_nineteen_field_labels_without_rewriting_them(self):
        from race_ai import four_sport_learning as ranker
        for sport in HOST:
            rows=training_rows(sport)
            for row in rows:
                day=row['snapshot']['race']['event_date_jst'];row['result']=label(sport,row['snapshot'])
                row['result']['captured_at']=day+'T11:00:00+09:00'
            before=deepcopy(rows)
            model=ranker.fit_training_only(rows,sport=sport,train_end_at='2030-01-06T23:59:00+09:00',epochs=1,
                now=lambda:datetime(2030,1,7,tzinfo=timezone.utc))
            self.assertEqual(model['trained_examples'],6);self.assertEqual(rows,before)
            self.assertEqual(model['training_data_sha256'],digest(sorted(before,key=lambda r:r['snapshot']['race']['race_id'])))


class OfficialOrderOnlyNativeArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.test_all_existing_model_pairs import AllExistingModelPrivatePairsTests
        AllExistingModelPrivatePairsTests.setUpClass()

    def test_owner_cipher_native_intake_preserves_three_original_nineteen_field_observations(self):
        from race_ai import all_existing_model_pairs as pairs
        from race_ai import all_existing_model_registry as registry
        from race_ai.all_existing_model_intake import records_from_private_artifact
        from race_ai.four_sport_model_suite import ALL_MODELS
        from tests import test_all_existing_model_pairs as fixtures
        fixture=fixtures.AllExistingModelPrivatePairsTests(methodName='runTest');fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        requests=[];observations=[]
        for sport in HOST:
            snapshot=sparse_snapshot(sport);race=snapshot['race']
            race.update(race_id=f'{sport}:2030-04-01:fictional-venue:1',event_date_jst='2030-04-01',
                as_of=(fixtures.FORECAST_NOW-timedelta(seconds=1)).isoformat(),
                sales_cutoff_at=(fixtures.FORECAST_NOW+timedelta(minutes=20)).isoformat())
            payload=dict(snapshot=snapshot,stage='P1',scope='SYNTHETIC_ONLY')
            requests.append(dict(cell_key=sport+'/'+ALL_MODELS[0],native_payload=payload))
            observed=label(sport,snapshot);observed.update(captured_at=(fixtures.FORECAST_NOW+timedelta(minutes=21)).isoformat(),
                                                        published_payout_yen=None)
            observations.append(observed)
        before=deepcopy((requests,observations))
        pairs.make_private_pairs(fixture.context,requests,fixture.root/'pairs',now=fixtures.FORECAST_NOW,allow_source=lambda *_:True)
        raw,_=fixture.archive();metadata=fixture.metadata(raw)
        value=records_from_private_artifact(raw,metadata,observations,now=fixtures.FORECAST_NOW+timedelta(minutes=22),
                                          expected_run_id=99,expected_head_sha=fixtures.HEAD)
        self.assertEqual(len(value['records']),3);self.assertEqual((requests,observations),before)
        by_sport={row['sport']:row for row in observations}
        for record in value['records']:
            self.assertEqual(record['result'],by_sport[record['sport']])
            self.assertEqual(record['result_observation'],by_sport[record['sport']])
            self.assertEqual(digest(record['result_observation']),digest(by_sport[record['sport']]))
            self.assertEqual(record['input_saved_at'],metadata['created_at'])
            self.assertEqual(len(record['result']),19)
            self.assertEqual(record['result']['status'],'rank_confirmed')
            self.assertIsNone(record['result']['payout_per_100_yen'])


if __name__=='__main__':unittest.main()
