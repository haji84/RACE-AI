"""Source-free sealed BOAT model archive replay contract.

All races, artifact bytes and clocks are fictional. No GitHub requests,
racing GET, plaintext forecast export, or source upload.
"""
from collections import Counter
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
PIN_ROOT=str(ROOT/'owner-source')
if PIN_ROOT not in sys.path:sys.path.insert(0,PIN_ROOT)
# Import the whole pinned owner package, never mix its modules with main's
# incompatible dispatch dependencies (e.g. sparse-schema constants).
import race_ai
for folder in ('pr64-reference','pr72-reference'):
    pin=str(ROOT/'owner-source'/folder/'race_ai')
    if pin not in race_ai.__path__:race_ai.__path__.append(pin)
import scripts
MAIN_SCRIPTS=str(ROOT/'scripts')
if MAIN_SCRIPTS not in scripts.__path__:scripts.__path__.append(MAIN_SCRIPTS)
from copy import deepcopy
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import patch

from scripts import boat_exact_all_model_zip_readback as exact

DAY='2030-04-01'
CREATED='2030-04-01T11:45:00+09:00'
CUTOFF='2030-04-01T12:00:00+09:00'
NOW=datetime(2030,4,1,4,0,tzinfo=timezone.utc)


def original(*,rid='20300401-01-01',mid='boat-model-A',created=CREATED,
             cutoff=CUTOFF,tickets=None):
    forecast=dict(stage='P1',model_id=mid,model_version='0.1',
      artifact_id=101,original_json_sha256='a'*64,
      source_code_commit=exact.OWNER_SHA,prediction_sha256='b'*64,
      output_sha256='c'*64,ordered_top8=tickets or ['1-2-3'],
      as_of='2030-04-01T11:40:00+09:00',
      generated_at='2030-04-01T11:41:00+09:00',
      cutoff_at=cutoff,server_saved_at=created,
      external_receipt_verified=True,eligible_pre_cutoff=True,
      dispatch_status='GENERATED_UNATTESTED')
    return dict(sport='boat',event_date_jst=DAY,race_id=rid,
                cutoff_at=CUTOFF,prediction=forecast,comparison_predictions=[])


class SourceFreeExactZipTests(unittest.TestCase):
    def scan(self,row,*,physical=CREATED,view_row=None,official_cutoff=CUTOFF):
        view=row if view_row is None else view_row
        idx=Counter([exact._identity(view['race_id'],view['prediction'])])
        saved=deepcopy(idx)
        result=exact._scan(dict(records=[row]),day=DAY,artifact_id=101,
                  physical_saved_at=physical,expected={'boat-model-A'},
                  clock=NOW,source_original_index=idx,
                   official_cutoffs={row['race_id']:exact.moment(official_cutoff)})
        return result,idx,saved

    def test_real_receipt_before_cutoff_is_required_but_does_not_create_proof(self):
        row=original()
        (seen,holds,missing,reused),index,prior=self.scan(row)
        self.assertEqual(seen,[(row['race_id'],'boat-model-A',True,True,True)])
        self.assertEqual(missing,0)
        self.assertEqual(dict(holds),{})
        self.assertEqual(sum(index.values()),0)
        self.assertEqual(sum(prior.values()),1)

    def test_unmatched_original_tickets_never_pass_content_comparison(self):
        row=original()
        view=original(tickets=['6-5-4'])
        (seen,holds,missing,reused),_,_=self.scan(row,view_row=view)
        self.assertEqual(missing,1)
        self.assertFalse(seen[0][3])
        self.assertTrue(seen[0][2])

    def test_late_actual_artifact_time_is_not_preclose_even_with_claimed_flag(self):
        late='2030-04-01T12:01:00+09:00'
        row=original(created=late)
        (seen,holds,missing,reused),_,_=self.scan(row,physical=late)
        self.assertFalse(seen[0][2])
        self.assertEqual(holds['NOT_PHYSICALLY_PRE_CUTOFF'],1)

    def test_gh_receipt_disagreement_rejects_entire_original(self):
        row=original()
        with self.assertRaises(ValueError):
            self.scan(row,physical='2030-04-01T11:46:00+09:00')

    def test_missing_official_cutoff_cannot_promote_forecast(self):
        row=original();row['cutoff_at']=None
        (seen,holds,_,reused),_,_=self.scan(row)
        self.assertFalse(seen[0][2])
        self.assertEqual(holds['OFFICIAL_RACE_CUTOFF_UNAVAILABLE'],1)

    def test_wrong_owner_head_cannot_count_forecast(self):
        row=original();row['prediction']['source_code_commit']='f'*40
        with self.assertRaises(ValueError):
            self.scan(row)

    def test_historic_original_stays_bound_to_its_authenticated_run_head(self):
        old='5d1dabff0ab9bb83132cd7fbdd43f49fb4eef6c4'
        row=original();row['prediction']['source_code_commit']=old
        with patch.object(exact,'OWNER_SHA','e'*40):
            for expected in (old,'e'*40,'f'*40):
                with self.subTest(expected=expected):
                    index=Counter([exact._identity(row['race_id'],row['prediction'])])
                    def read():
                        return exact._scan(dict(records=[row]),day=DAY,artifact_id=101,
                            physical_saved_at=CREATED,expected={'boat-model-A'},clock=NOW,
                            source_original_index=index,
                            official_cutoffs={row['race_id']:exact.moment(CUTOFF)},
                            expected_owner_sha=expected)
                    if expected==old:
                        self.assertEqual(read()[0][0][2:],(True,True,True))
                    else:
                        with self.assertRaises(ValueError):read()
        self.assertEqual(row['prediction']['source_code_commit'],old)

    def test_last_released_worker_remains_readonly_after_new_source_release(self):
        old='b491fb21ce58ba085dd8f54bb7326442b840d8f4'
        with patch.object(exact,'OWNER_SHA','e'*40):
            self.assertEqual(exact._owner_head(old),old)
            previous='c123b8538006b3189181195bbc91d8f28d216ba5'
            self.assertEqual(exact._owner_head(previous),previous)
            with self.assertRaises(ValueError):exact._owner_head('f'*40)

    def test_independent_official_cutoff_conflict_remains_hold(self):
        row=original()
        (seen,holds,missing,reused),_,_=self.scan(
            row,official_cutoff='2030-04-01T11:59:00+09:00')
        self.assertEqual(missing,0)
        self.assertTrue(seen[0][2])   # the ZIP-declared cutoff is later
        self.assertFalse(seen[0][4])  # separate official schedule disagrees
        self.assertEqual(holds['INDEPENDENT_OFFICIAL_CUTOFF_CONFLICT'],1)

    def test_prior_baseline_receipt_inside_model_zip_is_not_falsely_resaved(self):
        source=original()
        reused=deepcopy(source)
        reused['prediction']['artifact_id']=999
        reused['prediction']['dispatch_status']='ORIGINAL_REUSED'
        idx=Counter()
        row=reused
        rows,holds,missing,baseline=exact._scan(dict(records=[reused]),day=DAY,
             artifact_id=101,physical_saved_at=CREATED,
             expected={'boat-model-A'},clock=NOW,source_original_index=idx,
                   official_cutoffs={row['race_id']:exact.moment(CUTOFF)})
        self.assertEqual(rows,[])
        self.assertEqual(baseline,1)
        self.assertEqual(missing,0)
        self.assertFalse(holds)


    def source_context(self, *, program_cutoff=CUTOFF, preview_cutoff=CUTOFF,
                       context_cutoff=CUTOFF, program_at='2030-04-01T11:30:00+09:00',
                       preview_at='2030-04-01T11:37:00+09:00'):
        row=original()
        rid=row['race_id']
        return dict(program=dict(race_id=rid,closed_at=program_cutoff,
            body_identity_verified=True,status='OFFICIAL_BODY_IDENTITY_VERIFIED',
            source_sha256='a'*64,source={'sha256':'a'*64},captured_at=program_at),
            beforeinfo=dict(race_id=rid,closed_at=preview_cutoff,
            body_identity_verified=True,status='AVAILABLE',source_sha256='b'*64,
            captured_at=preview_at,context=dict(source_cutoff_at=context_cutoff,
                source={'sha256':'b'*64})),
            as_of='2030-04-01T11:40:00+09:00')

    def diagnose(self, *, context=None, official='2030-04-01T11:59:00+09:00'):
        row=original()
        contexts=[] if context is False else [self.source_context() if context is None else context]
        return exact.cutoff_source_disagreement(
            dict(records=[row]),dict(current_inputs=contexts),
            [(row['race_id'],'boat-model-A',True,True,False)],artifact_id=101,
            official_cutoffs={row['race_id']:exact.moment(official)},
            first_p0_saved_at='2030-04-01T11:20:00+09:00',
            p1_saved_at=CREATED)

    def test_round23_p1_racelist_and_exhibition_agree_but_first_p0_differs(self):
        report=self.diagnose()
        self.assertEqual(report['conflicting_model_slots'],1)
        self.assertEqual(report['conflicting_races'],1)
        self.assertEqual(report['source_relation_slots'],
            {'P1_RACELIST_AND_EXHIBITION_AGREE_BUT_FIRST_P0_DIFFERS':1})
        self.assertEqual(report['p1_minus_first_p0_cutoff_seconds_slots'],{'60':1})
        self.assertEqual(report['racelist_captured_after_first_p0_saved_slots'],1)
        self.assertNotIn('20300401-01-01',json.dumps(report))
        self.assertNotIn('a'*64,json.dumps(report))

    def test_round23_source_disagreement_never_grants_official_deadline(self):
        record=self.source_context(preview_cutoff='2030-04-01T11:58:00+09:00')
        report=self.diagnose(context=record)
        self.assertEqual(report['source_relation_slots'],
                         {'P1_RACELIST_AND_EXHIBITION_DISAGREE':1})
        # The existing independent _scan remains authoritative: failure is HOLD.
        (seen,holds,_,_),_,_=self.scan(original(),
            official_cutoff='2030-04-01T11:59:00+09:00')
        self.assertFalse(seen[0][4])
        self.assertEqual(holds['INDEPENDENT_OFFICIAL_CUTOFF_CONFLICT'],1)

    def test_round23_missing_or_late_source_never_masquerades_as_revision(self):
        self.assertEqual(self.diagnose(context=False)['source_relation_slots'],
            {'P1_SOURCE_CONTEXT_MISSING':1})
        future=self.source_context(program_at='2030-04-01T11:50:00+09:00',
                                   preview_at='2030-04-01T11:52:00+09:00')
        self.assertEqual(self.diagnose(context=future)['source_relation_slots'],
            {'P1_SOURCE_PROVENANCE_UNVERIFIED':1})

    def test_source_context_reuses_first_p0_clock_only_for_diagnosis(self):
        row=original()
        no_conflict=exact.cutoff_source_disagreement(
            dict(records=[row]),dict(current_inputs=[]),
            [(row['race_id'],'boat-model-A',True,True,True)],artifact_id=101,
            official_cutoffs={row['race_id']:exact.moment(CUTOFF)},
            first_p0_saved_at='2030-04-01T11:20:00+09:00',
            p1_saved_at=CREATED)
        self.assertEqual(no_conflict['conflicting_model_slots'],0)
        self.assertFalse(no_conflict['source_relation_slots'])

    def test_source_projection_mismatch_is_not_reported_as_later_official_revision(self):
        context=self.source_context(program_cutoff='2030-04-01T11:59:00+09:00',
            preview_cutoff='2030-04-01T11:59:00+09:00',
            context_cutoff='2030-04-01T11:59:00+09:00')
        self.assertEqual(self.diagnose(context=context)['source_relation_slots'],
            {'P1_VIEW_DIFFERS_FROM_BOTH_SOURCE_CUTOFFS':1})

    def test_exact_file_refetched_even_if_view_already_contains_the_same_original(self):
        self.replay_fixture(exact.OWNER_SHA)

    def test_historic_release_can_be_replayed_after_active_source_changes(self):
        with patch.object(exact,'OWNER_SHA','e'*40):
            self.replay_fixture('5d1dabff0ab9bb83132cd7fbdd43f49fb4eef6c4')

    def test_continuation_cutoff_hold_uses_actual_canonical_p0_receipt(self):
        self.replay_fixture(exact.OWNER_SHA,conflict=True)

    def replay_fixture(self,owner_sha,*,conflict=False):
        from race_ai import boat_all_model_recovery as R
        from race_ai import cycle_recovery as C
        run=dict(id=42,head_sha=owner_sha,
                 head_branch='production/boat-p0-p1-20261111',
                 event='workflow_dispatch',status='completed',
                 created_at='2030-04-01T02:00:00Z')
        view=dict(records=[original()])
        view['records'][0]['prediction']['source_code_commit']=owner_sha
        before=deepcopy(view)
        calls=[]
        data={f'actions/runs/42':b'fictional-run',
              f'actions/artifacts/101':b'fictional-metadata',
              f'actions/artifacts/101/zip':b'fictional-zip'}
        def get(uri):
            self.assertIn(uri,data)
            calls.append(uri)
            return data[uri]
        projection=deepcopy(view)
        fake_meta=dict(id=101,created_at=CREATED)
        record=dict(id=101,name='boat-all-model-forecasts-42-r1')
        def fake_project(raw,meta,run_value,round_no,key):
            self.assertEqual(raw,data['actions/artifacts/101/zip'])
            self.assertEqual(meta,fake_meta)
            self.assertEqual(round_no,1)
            return projection,dict(contexts=1,generated_forecasts=1,
                                   reused_baseline_forecasts=0),dict(
              independently_verified=True,created_at=CREATED,artifact_id=101,
              head_sha=owner_sha)
        from unittest.mock import MagicMock
        archive=MagicMock()
        archive.__enter__.return_value.namelist.return_value=['forecasts.enc']
        archive.__enter__.return_value.read.return_value=b'fixture-cipher'
        parent_saved='2030-04-01T01:59:59Z'
        with patch.object(R,'_run',return_value=run),\
             patch.object(R,'_listed',return_value=(101,1)),\
             patch.object(R,'_metadata',return_value=(fake_meta,False)),\
             patch.object(R,'_project',side_effect=fake_project),\
             patch.object(C,'artifact_pages',return_value=[record]),\
             patch.object(exact,'_canonical_p0',return_value=(dict(created_at=parent_saved),dict(id=41))) as canonical,\
             patch.object(R,'_checked_zip',return_value=archive),\
             patch.object(R.store,'open_forecasts',return_value={}),\
             patch.object(exact,'cutoff_source_disagreement',return_value=dict(conflicting_model_slots=1)) as diagnose,\
             patch.object(exact,'_official_cutoffs',
                          return_value={view['records'][0]['race_id']:exact.moment(
                              '2030-04-01T11:59:00+09:00' if conflict else CUTOFF)}):
            report=exact.audit(get=get,repo='unused',run_id=42,day=DAY,
                               expected_models=['boat-model-A'],original_view=view,
                               now=NOW,owner_key=bytes(range(32)))
        if conflict:
            canonical.assert_called_once()
            self.assertEqual(diagnose.call_args.kwargs['first_p0_saved_at'],parent_saved)
            self.assertEqual(report['unqualified_original_reasons']['INDEPENDENT_OFFICIAL_CUTOFF_CONFLICT'],1)
            self.assertEqual(report['official_schedule_crosschecked_pre_cutoff_model_slots'],0)
        else:
            canonical.assert_not_called();diagnose.assert_not_called()
        self.assertEqual(report['actual_listed_archives'],1)
        self.assertEqual(report['owner_source_commit'],owner_sha)
        self.assertEqual(report['github_zip_sha256_independently_verified'],1)
        self.assertEqual(report['aes_originals_independently_decrypted'],1)
        self.assertEqual(report['physical_pre_cutoff_distinct_model_slots'],1)
        self.assertEqual(report['official_schedule_crosschecked_pre_cutoff_model_slots'],0 if conflict else 1)
        self.assertEqual(report['referenced_existing_baseline_p1_rows_not_recounted'],0)
        self.assertEqual(report['original_predictions_matched_saved_AES_view'],1)
        self.assertEqual(report['previously_archived_coverages_skipped_without_zip_read'],0)
        self.assertIn('actions/artifacts/101/zip',calls)
        self.assertEqual(report['racing_provider_gets'],0)
        self.assertNotIn('20300401-01-01',json.dumps(report))
        self.assertFalse(report['production_predictions_modified'])
        self.assertEqual(view,before)

    def test_unknown_run_source_is_rejected_before_artifact_access(self):
        from race_ai import boat_all_model_recovery as R
        from race_ai import cycle_recovery as C
        run=dict(id=42,head_sha='f'*40,
            head_branch='production/boat-p0-p1-20261111',event='workflow_dispatch',
            status='completed',created_at='2030-04-01T02:00:00Z')
        with patch.object(R,'_run',return_value=run),patch.object(C,'artifact_pages') as listing:
            with self.assertRaises(ValueError):
                exact.audit(get=lambda _:b'fictional-run',repo='unused',run_id=42,day=DAY,
                    expected_models=['boat-model-A'],original_view=dict(records=[original()]),
                    now=NOW,owner_key=bytes(range(32)))
        listing.assert_not_called()

    def test_active_run_is_not_admitted_by_the_default_completed_reader(self):
        from race_ai import boat_all_model_recovery as R
        from race_ai import cycle_recovery as C
        run=dict(id=42,head_sha=exact.OWNER_SHA,head_branch='production/boat-p0-p1-20261111',
                 event='workflow_dispatch',status='in_progress',created_at='2030-04-01T02:00:00Z')
        with patch.object(R,'_run',return_value=run),patch.object(C,'artifact_pages') as listing:
            with self.assertRaises(ValueError):
                exact.audit(get=lambda _:b'fixture',repo='unused',run_id=42,day=DAY,
                    expected_models=['boat-model-A'],original_view=dict(records=[original()]),
                    now=NOW,owner_key=bytes(range(32)))
        listing.assert_not_called()


if __name__=='__main__':unittest.main()
