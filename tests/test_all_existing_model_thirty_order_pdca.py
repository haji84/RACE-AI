"""Explicit all-thirty rank objective; authored labels, no source or real key."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import base64
import importlib
import os
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai.all_existing_model_intake import _legacy_boat
from race_ai.official_order_only_result import EVALUATION_SCOPE
from tests.test_all_existing_model_result_intake import settled

NOW = datetime(2030, 4, 1, 3, tzinfo=timezone.utc)


class ThirtyOrderLabelTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('race_ai.all_existing_model_thirty_order_pdca'),
                             'explicit mixed-label thirty-cell rank-only path absent')
        return importlib.import_module('race_ai.all_existing_model_thirty_order_pdca')

    def label(self, sport='horse', status='settled'):
        observation = dict(sport=sport, race_id=f'{sport}:2030-04-01:fixture:1',
            status=status, ordered_top3=[3, 1, 2] if status in ('settled', 'rank_confirmed') else [],
            roster={'1':'one', '2':'two', '3':'three'}, captured_at='2030-04-01T02:30:00Z',
            published_at=None, source_ref='https://www.jra.go.jp/fixture',
            source_rights_ref='synthetic', source_sha256='a'*64, identity_verified=True,
            payout_per_100_yen=1230 if status=='settled' else None, refund_numbers=[],
            closed_at='2030-04-01T11:00:00+09:00', reason='NORMAL')
        return observation

    def context(self, observations, *, kind='OFFICIAL'):
        from race_ai.all_existing_model_intake import _results
        normalized, _ = _results(observations, NOW)
        return dict(kind=kind, original_observations=deepcopy(observations),
                    observations=[v['result'] for v in normalized.values()])

    def forecast(self, label):
        return dict(pair=dict(sport=label['sport'], race_id=label['race_id'],
            cutoff_at=label['closed_at'], race_cutoff_at=label['closed_at'],
            baseline_normalized={'roster':deepcopy(label['roster'])},
            learned_normalized={'roster':deepcopy(label['roster'])}))

    def test_original_settled_label_is_rank_teacher_without_status_or_money_rewrite(self):
        api=self.module();label=self.label();context=self.context([label]);before=deepcopy(context)
        selected,counts=api._order_observations([context],[self.forecast(label)],now=NOW)
        self.assertEqual(len(selected),1)
        self.assertEqual(selected[0]['original_observation'],label)
        self.assertEqual(selected[0]['order_observation']['status'],'settled')
        self.assertEqual(selected[0]['order_observation']['payout_per_100_yen'],1230)
        self.assertEqual(selected[0]['result_original_sha256'],digest(label))
        self.assertEqual(counts['matched_order_result_count'],1);self.assertEqual(context,before)

    def test_authenticated_legacy_boat_original_is_preserved_and_uses_existing_conversion(self):
        api=self.module();original=settled();generic=_legacy_boat(original)
        context=self.context([original],kind='BOAT')
        selected,_=api._order_observations([context],[self.forecast(generic)],now=NOW)
        self.assertEqual(selected[0]['original_observation'],original)
        self.assertEqual(selected[0]['order_observation']['ordered_top3'],generic['ordered_top3'])
        self.assertEqual(selected[0]['order_observation']['status'],'settled')
        self.assertEqual(original['status'],'AVAILABLE')

    def test_pending_and_special_newer_revisions_exclude_older_normal_teacher(self):
        api=self.module();normal=self.label()
        for status in ('pending','special'):
            newer=dict(self.label(status=status),captured_at='2030-04-01T02:40:00Z')
            selected,counts=api._order_observations([self.context([normal]),self.context([newer])],
                                                  [self.forecast(normal)],now=NOW)
            self.assertEqual(selected,[]);self.assertEqual(counts['outside_normal_order_result_state_counts'],{status:1})

    def test_wrong_roster_cutoff_future_and_refund_never_become_rank_teachers(self):
        api=self.module();normal=self.label();pair=self.forecast(normal)
        for change in ({'roster':{'1':'changed','2':'two','3':'three'}},
                       {'closed_at':'2030-04-01T10:59:00+09:00'},
                       {'captured_at':'2030-04-01T03:01:00Z'}, {'refund_numbers':[1]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                context=self.context([dict(normal,**change)])
                api._order_observations([context],[pair],now=NOW)

    def test_conflicting_same_capture_revisions_fail_closed(self):
        api=self.module();label=self.label();changed=dict(label,ordered_top3=[1,2,3])
        with self.assertRaises(ValueError):
            api._order_observations([self.context([label]),self.context([changed])],
                                    [self.forecast(label)],now=NOW)

    def test_explicit_artifact_api_is_separate_from_original_rank_and_cash_paths(self):
        api=self.module()
        for name in ('score_thirty_order_pairs_artifacts','verify_private_thirty_order_pdca',
                     'verify_thirty_order_pdca_artifact'):
            self.assertTrue(callable(getattr(api,name,None)), 'missing explicit thirty-cell API: '+name)
        from race_ai import all_existing_model_order_only_pdca as old
        self.assertNotEqual(api.SCHEMA,old.SCHEMA)

    def test_full_official_journal_hash_is_distinct_from_latest_revision_hash(self):
        api=self.module();first=self.label(status='pending');latest=self.label()
        latest['captured_at']='2030-04-01T02:40:00Z';full=[first,latest]
        metadata=dict(id=1,name='all-existing-official-results-42-1',expired=False,size_in_bytes=100,
            digest='sha256:'+'a'*64,created_at='2030-04-01T02:50:00Z',expires_at='2030-04-02T00:00:00Z',
            workflow_run=dict(id=42,head_sha='b'*40,repository_id=1416489937,head_repository_id=1416489937))
        receipt=dict(artifact_id=1,artifact_name=metadata['name'],digest=metadata['digest'],workflow_run_id=42,
            head_sha='b'*40,saved_at=metadata['created_at'],expires_at=metadata['expires_at'],artifact_metadata=metadata,
            original_journal_sha256=digest(full),cipher_sha256='c'*64,original_payload_sha256='d'*64,
            capture_index_sha256='e'*64,frozen_inputs_sha256='f'*64,authenticated_encrypted_result_artifact=True)
        context=self.context([latest]);context.update(receipt=receipt,source_evidence=[],
            observations_sha256=digest(context['observations']),original_journal_observations=full)
        api._result_receipts({'result_contexts':[context]},NOW)
        context['original_observations']=[first]
        with self.assertRaises(ValueError):api._result_receipts({'result_contexts':[context]},NOW)

    def test_origin_receipt_restore_rejects_expired_late_or_foreign_metadata(self):
        api=self.module();self.assertTrue(callable(getattr(api,'_origin_receipt',None)))
        run=dict(id=42,head_sha='b'*40,repository_id=1416489937,head_repository_id=1416489937)
        native=dict(id=1,name='all-existing-model-pairs-42-900004',workflow_run=run)
        origin=dict(id=2,name='all-native-future-origin-42-900010',workflow_run=deepcopy(run),expired=False,
            digest='sha256:'+'a'*64,size_in_bytes=123,created_at='2030-04-01T01:00:03Z',expires_at='2030-04-02T00:00:00Z')
        context=dict(source_native_metadata=native,origin=dict(origin_metadata=origin,
            origin_cipher_sha256='b'*64,generation=dict(origin_generated_at='2030-04-01T01:00:02Z',
            cutoff_at='2030-04-01T02:00:00Z',workflow_run_id=42,expected_head_sha='b'*40)))
        api._origin_receipt(context,NOW)
        for change in ({'expired':True},{'created_at':'2030-04-01T02:00:00Z'},
                       {'name':'all-native-future-origin-43-900010'},
                       {'workflow_run':dict(run,repository_id=7)}):
            wrong=deepcopy(context);wrong['origin']['origin_metadata'].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):api._origin_receipt(wrong,NOW)

    def test_real_fixture_crypto_keeps_full_pending_to_rank_confirmed_journal(self):
        from tests import test_all_existing_model_order_only_auth as auth
        from tests import test_autorace_official_result_adapter as auto
        from race_ai.autorace_official_result_adapter import parse_result
        from race_ai.manual_official_capture import official_rights_ref
        from race_ai import all_existing_model_official_results as official
        helper=auth.OrderOnlyAuthenticatedResultsTests('runTest')
        normal_raw,normal_meta,native,now,normal=helper.case('autorace')
        pending=auto.fixture();pending['metadata'].pop('auto_result_archive_context',None)
        pending['result']['body']['raceResult']=[];auto.reseal_result(pending)
        pending['metadata']['response_received_at']=(datetime.fromisoformat(
            pending['metadata']['response_received_at'])-timedelta(seconds=1)).isoformat()
        pending_raw=auto.wire(pending['result'])
        pending_label=parse_result(pending_raw,pending['metadata'],frozen_native_payload=native,now=now,
            source_rights_ref=official_rights_ref('autorace'),allow_order_only=True)
        self.assertEqual(pending_label['status'],'pending')
        full=[pending_label,normal]
        captures=[dict(raw_base64=base64.b64encode(raw).decode(),metadata=meta)
                  for raw,meta in ((pending_raw,pending['metadata']),(normal_raw,normal_meta))]
        with patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(auth.KEY).decode()):
            payload=official.build_result_payload(captures,full,run_id=42,code_sha=auth.HEAD,
                generated_at=now,day_jst='2030-01-15',frozen_native_payloads=[native],allow_order_only=True)
            raw,meta=helper.archive(payload,now)
            admitted=official.observations_from_official_result_artifact(raw,meta,now=now+timedelta(seconds=10),
                expected_run_id=42,expected_head_sha=auth.HEAD,frozen_native_payloads=[native],allow_order_only=True)
        self.assertEqual(admitted['observations'],[normal])
        self.assertEqual(admitted['receipt']['original_journal_sha256'],digest(full))
        context=self.context(admitted['observations']);context.update(receipt=admitted['receipt'],
            original_journal_observations=full,source_evidence=admitted['result_source_evidence'],
            observations_sha256=digest(context['observations']))
        self.module()._result_receipts({'result_contexts':[context]},now+timedelta(seconds=10))


if __name__=='__main__': unittest.main()
