"""Strict source-free replay tests with fictional saved official pages only."""
from copy import deepcopy
from datetime import timedelta
import unittest
from race_ai import saved_view_feed as F,result_due_ledger as D,result_due_case_audit as C
from race_ai.racer_intraday import IntradayState
from race_ai.retained_case_repair import repair_saved_receipt_mismatches
from tests.test_racer_result_bridge import BridgeTests
from tests.test_racer_daily import NOW
from tests.test_boat_sp_settlement import document
from tests.intraday_fixture import packet


class StrictRetainedCaseRepairTests(unittest.TestCase):
    def setup(self,*,reference_only=False,corrupt_pointer=False,source_rejected=False):
        fixture=BridgeTests('test_confirmed_result_reaches_saved_forecast_without_intake_and_quiet_replay_is_identical')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        raw,receipt=packet(document(),captured=NOW.isoformat())
        actual=F.update_view(fixture.view,[],captures=[(raw,receipt)],synced_at=NOW.isoformat())
        old=deepcopy(actual)
        row=old['records'][0]
        if reference_only:
            row['result']['cutoff_reference']=dict(formal_eligible=False,
                original_cutoff_at=row['cutoff_at'])
        elif source_rejected:
            # Original view contains a rejected observation and no formal
            # result. The authenticated byte packet is kept independently.
            row['result']=None
            row['result_observations']=[]
            row['result_observation_rejections']=[dict(reason='RESULT_WINNER_INVALID')]
        else:row['result']['source_sha256']='f'*64
        fixture.seed(old)
        state=IntradayState()
        pointer=state.remember('RESULT',raw,receipt)
        if corrupt_pointer:pointer['source_sha256']='f'*64
        state.control['settlement_captures']={row['race_id']:pointer}
        due=D.ledger(state.control,now=NOW.isoformat())
        D.update(due,[row],now=NOW.isoformat())
        if not reference_only and not source_rejected:
            D.hold_model_ids(due,[row],[row['race_id']],now=NOW.isoformat())
        outcome=C.record(state.control,due,[row])
        self.assertEqual(outcome['outstanding'],1)
        return fixture,state,row,receipt,due

    def test_verified_same_capture_can_repair_exact_model_evidence_mismatch(self):
        fixture,state,row,receipt,due=self.setup()
        self.assertEqual(state.control['result_due_case_reasons']['cases'][row['race_id']]['reason'],
                         'MODEL_RESULT_EVIDENCE_MISMATCH')
        original=F.forecast_inventory(fixture.view)
        before=deepcopy(state.control)
        old_head=fixture.git.head()
        out=repair_saved_receipt_mismatches(fixture.repo,state=state,
                       now=NOW+timedelta(minutes=1),bridge=fixture.bridge())
        self.assertEqual(out['source_provider_requests'],0)
        self.assertEqual(out['source_bytes_authenticated'],1)
        self.assertEqual(out['formal_result_repairs'],1)
        self.assertEqual(out['view_commits'],1)
        self.assertNotEqual(old_head,fixture.git.head())
        self.assertEqual(state.control,before)
        _,_,_,view=F.current_view(fixture.git,fixture.boot)
        self.assertEqual(view['records'][0]['result']['source_sha256'],receipt['source_sha256'])
        self.assertEqual(F.forecast_inventory(view),original)
        D.update(due,view['records'],now=(NOW+timedelta(minutes=1)).isoformat())
        self.assertEqual(D.pending_count(due),0)

    def test_compatible_parser_metadata_conflict_keeps_original_observation(self):
        fixture,state,row,receipt,due=self.setup()
        original=F.current_view(fixture.git,fixture.boot)[3]
        changed=deepcopy(original)
        changed['records'][0]['result_observations'][0]['source_format']='OLDER_PARSER_PROVENANCE'
        fixture.seed(changed)
        out=repair_saved_receipt_mismatches(fixture.repo,state=state,
                       now=NOW+timedelta(minutes=1),bridge=fixture.bridge())
        self.assertEqual(out['source_bytes_authenticated'],1)
        self.assertEqual(out['metadata_only_reprojections'],1)
        self.assertEqual(out['formal_result_repairs'],1)
        _,_,_,read=F.current_view(fixture.git,fixture.boot)
        self.assertEqual(read['records'][0]['result_observations'],
                         changed['records'][0]['result_observations'])
        self.assertEqual(read['records'][0]['result']['source_sha256'],receipt['source_sha256'])

    def test_material_parser_conflict_does_not_overwrite_result(self):
        fixture,state,row,receipt,due=self.setup()
        original=F.current_view(fixture.git,fixture.boot)[3]
        changed=deepcopy(original)
        changed['records'][0]['result_observations'][0]['data']['payouts'][0]['payout_per_100_yen']=999999
        fixture.seed(changed);before=fixture.git.head()
        out=repair_saved_receipt_mismatches(fixture.repo,state=state,
                       now=NOW+timedelta(minutes=1),bridge=fixture.bridge())
        self.assertEqual(out['formal_result_repairs'],0)
        self.assertEqual(out['formal_hold_reason_counts']['MODEL_REPLAY_PARSER_MATERIAL_CONFLICT'],1)
        self.assertEqual(fixture.git.head(),before)

    def test_retained_source_rejected_is_replayed_only_through_formal_gates(self):
        fixture,state,row,receipt,due=self.setup(source_rejected=True)
        self.assertEqual(state.control['result_due_case_reasons']['cases'][row['race_id']]['reason'],
                         'RESULT_SOURCE_REJECTED')
        original=F.forecast_inventory(fixture.view)
        before=deepcopy(state.control)
        out=repair_saved_receipt_mismatches(fixture.repo,state=state,
                      now=NOW+timedelta(minutes=1),bridge=fixture.bridge())
        self.assertEqual(out['source_provider_requests'],0)
        self.assertEqual(out['replay_candidates'],1)
        self.assertEqual(out['source_bytes_authenticated'],1)
        self.assertEqual(out['formal_result_repairs'],1)
        self.assertEqual(state.control,before)
        _,_,_,view=F.current_view(fixture.git,fixture.boot)
        self.assertEqual(view['records'][0]['result']['source_sha256'],receipt['source_sha256'])
        self.assertEqual(F.forecast_inventory(view),original)
        D.update(due,view['records'],now=(NOW+timedelta(minutes=1)).isoformat())
        self.assertEqual(D.pending_count(due),0)

    def test_rejected_source_cannot_override_prior_reference_only_decision(self):
        fixture,state,row,receipt,due=self.setup(source_rejected=True)
        altered=F.current_view(fixture.git,fixture.boot)[3]
        altered['records'][0]['result']={
            'status':'missing',
            'cutoff_reference':dict(formal_eligible=False,original_cutoff_at=row['cutoff_at'])
        }
        fixture.seed(altered)
        old_head=fixture.git.head()
        report=repair_saved_receipt_mismatches(fixture.repo,state=state,
                   now=NOW+timedelta(minutes=1),bridge=fixture.bridge())
        self.assertEqual(report['replay_candidates'],1)
        self.assertEqual(report['source_bytes_authenticated'],0)
        self.assertEqual(report['formal_result_repairs'],0)
        self.assertEqual(report['formal_hold_reason_counts']['MODEL_REPLAY_REFERENCE_ONLY_BARRIER'],1)
        self.assertEqual(fixture.git.head(),old_head)
        self.assertEqual(D.pending_count(due),1)

    def test_rejected_source_with_corrupt_retained_bytes_remains_unresolved(self):
        fixture,state,row,receipt,due=self.setup(source_rejected=True,corrupt_pointer=True)
        old_head=fixture.git.head()
        result=repair_saved_receipt_mismatches(fixture.repo,state=state,
                   now=NOW+timedelta(minutes=1),bridge=fixture.bridge())
        self.assertEqual(result['replay_candidates'],1)
        self.assertEqual(result['formal_result_repairs'],0)
        self.assertEqual(result['formal_preview_holds'],1)
        self.assertEqual(fixture.git.head(),old_head)
        self.assertEqual(D.pending_count(due),1)

    def test_reference_only_result_is_never_reclassified_to_formal_hit(self):
        fixture,state,row,receipt,due=self.setup(reference_only=True)
        original=fixture.git.head()
        out=repair_saved_receipt_mismatches(fixture.repo,state=state,
                 now=NOW+timedelta(minutes=1),bridge=fixture.bridge())
        self.assertEqual(out['replay_candidates'],0)
        self.assertEqual(out['formal_result_repairs'],0)
        self.assertEqual(fixture.git.head(),original)
        self.assertEqual(D.pending_count(due),1)

    def test_corrupt_capture_cannot_create_new_formal_result(self):
        fixture,state,row,receipt,due=self.setup(corrupt_pointer=True)
        original=fixture.git.head()
        out=repair_saved_receipt_mismatches(fixture.repo,state=state,
                now=NOW+timedelta(minutes=1),bridge=fixture.bridge())
        self.assertEqual(out['formal_result_repairs'],0)
        self.assertEqual(out['formal_preview_holds'],1)
        self.assertEqual(fixture.git.head(),original)
        self.assertEqual(D.pending_count(due),1)
