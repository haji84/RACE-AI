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



class FixedBootstrapP0CountTests(unittest.TestCase):
    """Invented bytes exercise the real ZIP/AES/native readers for one fixed scope.

    The fixture changes ONLY the private byte-pin tuple: invented ciphertext
    cannot have the real retained ZIP's hash. Run, producer, workflow, repository,
    artifact, round, day and vault commit remain the literal reviewed identities.
    Git transport and owner-key resolution are the external boundaries replaced.
    """
    RUN=44170869325
    ARTIFACT=14367093570
    HEAD='bb49215034b779ea1493b35dd91e5c3ebfc04032'
    VAULT='d853f5d6db9089d91748add90560a0b9037b2a1f'
    DAY='2026-11-18'
    SAVED='2026-11-17T20:38:49Z'
    ARCHIVED='2026-11-17T20:39:15.465177+00:00'
    CLOCK=datetime(2026,11,17,20,40,tzinfo=timezone.utc)
    KEY=bytes(range(32))
    COUNT_FIELDS=('contexts','generated_forecasts','reused_forecasts',
        'projected_forecasts','applicable_slots','non_generated_applicable_slots',
        'waiting_exhibition_slots','retained_original_slots','dispatch_status_counts')
    STAGES={'PRECONDITION','RUN','VAULT_LOOKUP','VAULT_RESTORE',
            'PIN_BINDING','PROJECT','SCOPE','COUNTS'}
    FALSE_FIELDS=('full_day_coverage','all_models_operational','qualifying_g8_proven',
                  'efficacy_proven','promotion_allowed','dispatch_authorized',
                  'website_end_to_end_proven','source_originals_modified')

    def setUp(self):
        self.assertTrue(callable(getattr(exact,'audit_fixed_bootstrap_p0',None)),
                        'the fixed retained P0 count-only reader is missing')

    @staticmethod
    def wire(value):
        return json.dumps(value,ensure_ascii=False,sort_keys=True,
                          separators=(',',':'),allow_nan=False).encode()

    @staticmethod
    def zipped(members):
        import io,zipfile
        target=io.BytesIO()
        with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_STORED) as archive:
            for name,body in members:
                archive.writestr(zipfile.ZipInfo(name,(1980,1,1,0,0,0)),body)
        return target.getvalue()

    def payload(self,*,zero=False,reused=False):
        import tempfile
        from race_ai import boat_all_model_cycle as engine
        from race_ai.actions_contract import digest
        from race_ai.boat_history_store import HistoryStore
        from race_ai.boat_observed_pairwise_models import predict_pair
        from race_ai.four_sport_model_suite import ALL_MODELS
        from tests.test_boat_observed_pairwise_models import fixture
        observed=json.loads(json.dumps(fixture(research=True)).replace('2030-04-01',self.DAY))
        observed['as_of']=self.DAY+'T05:20:00+09:00'
        observed['sources'][0].update(published_at=self.DAY+'T04:00:00+09:00',
                                     captured_at=self.DAY+'T05:00:00+09:00')
        suite=predict_pair(observed,allow_source=lambda *_:True)
        document=dict(schema='RACE_AI_EXISTING_P0_DAY_V1',day_jst=self.DAY,
            predictions=[suite],schedule=[dict(race_id='20261118-01-01',
            cutoff_at=suite['sales_cutoff_at'])],race_count=1,model_forecast_count=2,
            actual_purchases=False,skipped=[])
        prior=dict(repository_id='1416489937',repository='haji84/RACE-AI',
            run_id=str(self.RUN),head_sha=self.HEAD,artifact_id=14366264478,
            created_at='2026-11-17T20:36:54Z',payload_sha256=digest(document),
            independently_verified=True)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);root.chmod(0o700)
            history=root/'history.sqlite'
            db=HistoryStore(history);db.close()
            metadata=root/'metadata.json'
            metadata.write_bytes(self.wire(dict(schema='FICTIONAL_RUNTIME',
                                               source_code_commit=self.HEAD)))
            metadata.chmod(0o600);history.chmod(0o600)
            runtime={'history.sqlite':str(history),'metadata.json':str(metadata),
                'verified_runtime':True,'history_identity_verified':True,
                'owner_reviewed':True,'source_code_commit':self.HEAD,
                'run_id':str(self.RUN)}
            value=engine.forecast_saved_p0(document,prior,runtime,
                now=exact.moment('2026-11-17T20:38:20Z'),
                issued_models={'20261118-01-01':list(ALL_MODELS)} if zero else None)
        if reused:
            from race_ai.existing_model_dispatch import dispatch
            base=deepcopy(value);report=value['dispatch_reports'][0]
            original=deepcopy(next(s for s in report['slots']
                                  if s['status']=='GENERATED_UNATTESTED'))
            capsule=value['native_input_capsules'][0]
            schedule=report['schedule'];rid=schedule[0]['race_id']
            refs={tuple(pair) for pair in capsule['analysis_source_refs']}
            replay=dispatch(schedule,{rid:{'P0':capsule['native_inputs']}},
                now=exact.moment(value['generated_at']),
                allow_source=lambda ref,rights,purpose:
                    purpose=='analysis' and (ref,rights) in refs,
                originals=[original])
            replay['schedule']=deepcopy(schedule)
            previous={s['model_id']:s for s in report['slots']}
            for slot in replay['slots']:
                old=previous[slot['model_id']]
                if old['status'] not in ('GENERATED_UNATTESTED','ORIGINAL_REUSED'):
                    slot.clear();slot.update(deepcopy(old))
            replay['status_counts']=dict(Counter(s['status'] for s in replay['slots']))
            value['dispatch_reports']=[replay]
            value['summary'].update(generated_forecasts=3,reused_baseline_forecasts=1)
            body_hash=digest(base)
            value['baseline']=dict(document_sha256=body_hash,receipt=dict(
                repository_id='1416489937',repository='haji84/RACE-AI',
                run_id=str(self.RUN),head_sha=self.HEAD,artifact_id=14367093569,
                created_at='2026-11-17T20:38:30Z',
                payload_sha256=body_hash,independently_verified=True))
        return value

    def fixture(self,*,payload=None,cipher_change=None,zip_change=None,meta_change=None):
        from hashlib import sha256
        from race_ai import boat_all_model_store as store,boat_private_original_vault as V
        value=self.payload() if payload is None else deepcopy(payload)
        cipher=store.seal_forecasts(value,run_id=str(self.RUN),round_no=0,key=self.KEY)
        if cipher_change is not None:cipher=cipher_change(cipher)
        raw=self.zipped([('forecasts.enc',cipher)])
        if zip_change is not None:raw=zip_change(raw,cipher)
        meta=dict(id=self.ARTIFACT,name=f'boat-all-model-forecasts-{self.RUN}-r0',
            expired=False,size_in_bytes=len(raw),digest='sha256:'+sha256(raw).hexdigest(),
            created_at=self.SAVED,updated_at=self.SAVED,expires_at='2026-11-24T20:38:47Z',
            workflow_run=dict(id=self.RUN,repository_id=1416489937,
                              head_repository_id=1416489937,head_sha=self.HEAD))
        if meta_change is not None:meta_change(meta)
        metadata=json.dumps(meta,ensure_ascii=False,indent=3).encode()+b'\n\n'
        summary=dict(kind='ALL_MODEL',artifact_id=meta['id'],
            run_id=meta['workflow_run']['id'],head_sha=meta['workflow_run']['head_sha'],
            created_at=meta['created_at'],month='2026-11')
        record=dict(files={'original.zip':raw,'metadata.json':metadata},summary=summary)
        encryption,mac=V._keys(self.KEY)
        entry,chunks=V._seal(record,exact.moment(self.ARCHIVED),encryption)
        batch=V._signed(dict(schema=V.SCHEMA,repository_id='1416489937',entries=[entry]),mac)
        batch_hash=sha256(batch).hexdigest()
        batch_path=V.PREFIX+'2026-11/batches/'+batch_hash+'.json'
        reference=V._reference(batch_path,batch_hash,entry)
        lookup=V._signed(dict(schema=V.SCHEMA,repository_id='1416489937',
            kind='lookup',bucket=self.ARTIFACT//V.LOOKUP_SPAN,
            entries={str(self.ARTIFACT):reference}),mac)
        files={**chunks,batch_path:batch,V._lookup_path(self.ARTIFACT):lookup}
        fixed=self.VAULT
        class MemoryGit:
            ref='state/boat-private-originals'
            repo=Path('/fictional-private-owner-package')
            def __init__(self):
                self.files=files;self.reads=[];self.fetches=[]
            def fetch(self,commit):
                if commit!=fixed:raise AssertionError('unreviewed vault commit')
                self.fetches.append(commit)
            def exists(self,commit,path):
                if commit!=fixed:raise AssertionError('unreviewed vault commit')
                return path in self.files
            def read(self,commit,path,limit):
                if commit!=fixed:raise AssertionError('unreviewed vault commit')
                body=self.files[path]
                if len(body)>limit:raise ValueError('fixture byte bound')
                self.reads.append((commit,path,limit))
                return body
            def __getattr__(self,name):
                raise AssertionError('private-write-or-unknown-operation-sentinel')
        header=store.forecast_header(cipher)
        pins=(('original_zip_sha256',sha256(raw).hexdigest()),
              ('original_zip_bytes',len(raw)),('metadata_sha256',sha256(metadata).hexdigest()),
              ('metadata_bytes',len(metadata)),('cipher_sha256',sha256(cipher).hexdigest()),
              ('plain_sha256',header['plain_sha256']),('plain_bytes',header['plain_size']),
              ('vault_batch_sha256',batch_hash),('vault_entry_sha256',reference['entry_sha256']))
        return dict(value=value,git=MemoryGit(),pins=pins,raw=raw,metadata=metadata,
                    meta=meta,cipher=cipher,lookup_path=V._lookup_path(self.ARTIFACT),
                    chunk_paths=list(chunks))

    def run_reader(self,fixture=None,*,run_change=None,get_error=None,now=None):
        import io
        from contextlib import redirect_stdout,redirect_stderr
        from race_ai import boat_private_original_vault as V,boat_all_model_store as store
        f=self.fixture() if fixture is None else fixture
        run=dict(id=self.RUN,workflow_id=405276784,
            head_branch='production/boat-p0-p1-20261111',event='workflow_dispatch',
            head_sha=self.HEAD,status='in_progress',conclusion=None,
            created_at='2026-11-17T20:35:16Z',updated_at='2026-11-17T20:35:20Z',
            repository=dict(id=1416489937,full_name='haji84/RACE-AI'),
            head_repository=dict(id=1416489937,full_name='haji84/RACE-AI'))
        if run_change is not None:run_change(run)
        calls=[];output=io.StringIO()
        def get(endpoint):
            calls.append(endpoint)
            if endpoint!=f'actions/runs/{self.RUN}':
                raise AssertionError('provider-or-unreviewed-route-sentinel')
            if get_error is not None:raise get_error
            return self.wire(run)
        before=deepcopy(f['git'].files)
        with patch.object(V,'_transport',return_value=f['git']), \
             patch.object(V,'state_key',return_value=self.KEY), \
             patch.object(store,'state_key',return_value=self.KEY), \
             patch.object(exact,'_FIXED_BOOTSTRAP_P0_BYTE_PINS',f['pins']), \
             redirect_stdout(output),redirect_stderr(output):
            report=exact.audit_fixed_bootstrap_p0(get=get,repo=f['git'].repo,
                                                now=self.CLOCK if now is None else now)
        self.assertEqual(f['git'].files,before,'a readback must not rewrite retained evidence')
        self.assertEqual(output.getvalue(),'','private validation must not print intermediate data')
        self.assertTrue(all(c==f'actions/runs/{self.RUN}' for c in calls))
        return report,f

    def assert_safe(self,report):
        self.assertIs(type(report),dict)
        self.assertTrue(report['counts_only'])
        self.assertEqual(report['official_source_requests'],0)
        for name in self.FALSE_FIELDS:self.assertIs(report[name],False)
        rendered=json.dumps(report,allow_nan=False,sort_keys=True)
        for private in ('20261118-01-01','private-','example.test','synthetic://',
                        'registration_no','participants','ordered_top8','native_inputs',
                        'UNLISTED_OWNER_CREDENTIAL','validated_cf_value'):
            self.assertNotIn(private,rendered)
        self.assertFalse({'view','records','rows','roster','picks','tickets',
                          'exception','message','key'}&set(report))

    def assert_hold(self,report):
        self.assert_safe(report)
        self.assertEqual(report['status'],'HOLD_FIXED_BOOTSTRAP_P0_COUNTS')
        self.assertIs(report['authenticated_original'],False)
        self.assertIn(report['failure_stage'],self.STAGES)
        for name in self.COUNT_FIELDS:self.assertIsNone(report[name],name)

    def test_real_retained_zip_aes_and_native_replay_report_four_new_p0s(self):
        report,f=self.run_reader()
        self.assert_safe(report)
        self.assertEqual(report['status'],'FIXED_BOOTSTRAP_P0_COUNTS_VERIFIED')
        self.assertIs(report['authenticated_original'],True)
        self.assertEqual(report['contexts'],1)
        self.assertEqual(report['generated_forecasts'],4)
        self.assertEqual(report['reused_forecasts'],0)
        self.assertEqual(report['projected_forecasts'],4)
        self.assertEqual(report['applicable_slots'],14)
        self.assertEqual(report['non_generated_applicable_slots'],10)
        self.assertEqual(report['waiting_exhibition_slots'],7)
        self.assertEqual(report['retained_original_slots'],2)
        self.assertEqual(report['dispatch_status_counts']['RULE_FILTERED'],9)
        self.assertEqual(report['dispatch_status_counts']['GENERATED_UNATTESTED'],4)
        self.assertEqual(sum(report['dispatch_status_counts'].values()),15)
        self.assertTrue(f['git'].fetches)
        self.assertEqual(set(f['git'].fetches),{self.VAULT})

    def test_authenticated_zero_generated_payload_is_verified_zero_not_unknown_or_nonzero(self):
        report,_=self.run_reader(self.fixture(payload=self.payload(zero=True)))
        self.assert_safe(report)
        self.assertEqual(report['status'],'FIXED_BOOTSTRAP_P0_COUNTS_VERIFIED')
        self.assertEqual(report['generated_forecasts'],0)
        self.assertEqual(report['reused_forecasts'],0)
        self.assertEqual(report['projected_forecasts'],0)
        self.assertEqual(report['applicable_slots'],14)
        self.assertEqual(report['non_generated_applicable_slots'],14)
        self.assertEqual(report['waiting_exhibition_slots'],7)
        self.assertEqual(report['retained_original_slots'],6)

    def test_reused_original_is_counted_separately_and_never_added_to_new_generation(self):
        report,_=self.run_reader(self.fixture(payload=self.payload(reused=True)))
        self.assert_safe(report)
        self.assertEqual(report['generated_forecasts'],3)
        self.assertEqual(report['reused_forecasts'],1)
        self.assertEqual(report['projected_forecasts'],4)
        self.assertEqual(report['applicable_slots'],14)
        self.assertEqual(report['non_generated_applicable_slots'],10)
        self.assertEqual(report['dispatch_status_counts']['ORIGINAL_REUSED'],1)

    def test_other_run_source_workflow_branch_event_or_repository_cannot_use_the_fixed_archive(self):
        changes=[lambda r:r.update(id=44170869326),lambda r:r.update(head_sha='f'*40),
            lambda r:r.update(workflow_id=405276785),lambda r:r.update(event='pull_request'),
            lambda r:r.update(event='push'),lambda r:r.update(head_branch='feat/four-sport-forecast-audit-view-20261022'),
            lambda r:r['repository'].update(id=7),lambda r:r['head_repository'].update(full_name='foreign/private')]
        for index,change in enumerate(changes):
            with self.subTest(case=index):
                report,f=self.run_reader(run_change=change)
                self.assert_hold(report)
                self.assertEqual(f['git'].fetches,[])

    def test_missing_archive_and_bad_hmac_or_chunk_remain_hold_without_live_artifact_fallback(self):
        for case in ('missing','lookup-mac','chunk'):
            with self.subTest(case=case):
                f=self.fixture()
                if case=='missing':f['git'].files.pop(f['lookup_path'])
                elif case=='lookup-mac':
                    bad=json.loads(f['git'].files[f['lookup_path']]);bad['mac']='0'*64
                    f['git'].files[f['lookup_path']]=self.wire(bad)+b'\n'
                else:
                    path=f['chunk_paths'][0];body=f['git'].files[path]
                    f['git'].files[path]=body[:-1]+bytes([body[-1]^1])
                report,_=self.run_reader(f)
                self.assert_hold(report)

    def test_full_zip_framing_crc_and_single_member_are_checked_after_pins_match(self):
        def crc_break(raw,cipher):
            offset=raw.index(cipher)
            return raw[:offset]+bytes([raw[offset]^1])+raw[offset+1:]
        cases=[lambda raw,cipher:raw+b'private-trailing-sentinel',
               lambda raw,cipher:self.zipped([('forecasts.enc',cipher),('private-extra',b'private-sentinel')]),
               crc_break]
        for index,change in enumerate(cases):
            with self.subTest(case=index):
                report,_=self.run_reader(self.fixture(zip_change=change))
                self.assert_hold(report)

    def test_inner_aes_authentication_is_not_replaced_by_vault_or_zip_hashes(self):
        report,_=self.run_reader(self.fixture(
            cipher_change=lambda c:c[:-1]+bytes([c[-1]^1])))
        self.assert_hold(report)

    def test_authenticated_body_hash_and_canonical_encoding_are_rechecked(self):
        import struct
        from hashlib import sha256
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from race_ai import boat_all_model_store as store
        def change(cipher,canonical):
            header,nonce,encrypted=store._split(cipher)
            plain=AESGCM(store._key(self.KEY)).decrypt(nonce,encrypted,store._aad(header,nonce))
            changed=plain+b' '
            if canonical:header.update(plain_size=len(changed),plain_sha256=sha256(changed).hexdigest())
            else:header.update(plain_size=len(changed))
            encoded=store._wire(header)
            encrypted=AESGCM(store._key(self.KEY)).encrypt(nonce,changed,store._aad(header,nonce))
            return store.MAGIC+struct.pack('>I',len(encoded))+encoded+nonce+encrypted
        for canonical in (False,True):
            with self.subTest(canonical=canonical):
                report,_=self.run_reader(self.fixture(
                    cipher_change=lambda c:change(c,canonical)))
                self.assert_hold(report)

    def test_source_body_summary_and_context_counts_cannot_disagree_with_verified_slots(self):
        cases=[lambda p:p.update(source_code_commit='f'*40),
               lambda p:p['summary'].update(generated_forecasts=5),
               lambda p:p['summary'].update(reused_baseline_forecasts=1),
               lambda p:p['summary'].update(contexts=2),
               lambda p:p.update(stage='P1')]
        for index,change in enumerate(cases):
            with self.subTest(case=index):
                value=self.payload();change(value)
                report,_=self.run_reader(self.fixture(payload=value))
                self.assert_hold(report)

    def test_native_roster_binding_and_capsule_context_day_are_not_waived(self):
        from race_ai.actions_contract import digest
        for case in ('roster','day'):
            with self.subTest(case=case):
                value=self.payload();capsule=value['native_input_capsules'][0]
                if case=='roster':
                    capsule['native_inputs']['shared']['snapshot']['participants'][0]['participant_id']='private-roster-sentinel'
                else:
                    value['dispatch_reports'][0]['schedule'][0]['race_id']='20261119-01-01'
                    capsule['race_id']='20261119-01-01'
                capsule['native_payload_sha256']={g:digest(v) for g,v in capsule['native_inputs'].items()}
                capsule['capsule_sha256']=digest({k:v for k,v in capsule.items() if k!='capsule_sha256'})
                report,_=self.run_reader(self.fixture(payload=value))
                self.assert_hold(report)

    def test_exact_archived_metadata_identity_clock_digest_and_size_are_required(self):
        cases=[lambda m:m.update(id=14367093571),lambda m:m.update(name='private-unrecognized-sentinel'),
               lambda m:m.update(created_at='2026-11-17T20:38:50Z'),
               lambda m:m.update(expired=True),lambda m:m.update(digest='sha256:'+'0'*64),
               lambda m:m.update(size_in_bytes=1),lambda m:m['workflow_run'].update(head_sha='f'*40),
               lambda m:m['workflow_run'].update(repository_id=7)]
        for index,change in enumerate(cases):
            with self.subTest(case=index):
                report,_=self.run_reader(self.fixture(meta_change=change))
                self.assert_hold(report)

    def test_unknown_private_fields_and_reasons_never_escape_safe_status_counts(self):
        value=self.payload()
        value['UNLISTED_OWNER_CREDENTIAL']='private-key-sentinel'
        slot=next(s for s in value['dispatch_reports'][0]['slots']
                  if s['status']=='TRAINED_ARTIFACT_MISSING')
        slot['reason']='private-unknown-reason-sentinel https://private-owner.invalid/'
        slot['UNLISTED_OWNER_CREDENTIAL']='private-slot-sentinel'
        report,_=self.run_reader(self.fixture(payload=value))
        self.assert_safe(report)
        self.assertEqual(report['generated_forecasts'],4)
        self.assertEqual(report['dispatch_status_counts']['TRAINED_ARTIFACT_MISSING'],1)

    def test_unknown_status_and_private_error_messages_produce_only_static_hold_stage(self):
        value=self.payload();report=value['dispatch_reports'][0]
        slot=next(s for s in report['slots'] if s['status']=='TRAINED_ARTIFACT_MISSING')
        slot['status']='private-status-sentinel'
        report['status_counts']=dict(Counter(s['status'] for s in report['slots']))
        rejected,_=self.run_reader(self.fixture(payload=value));self.assert_hold(rejected)
        unavailable,_=self.run_reader(get_error=RuntimeError('private-exception-sentinel https://private.invalid/'))
        self.assert_hold(unavailable)
        self.assertEqual(unavailable['failure_stage'],'RUN')

    def test_unaware_clock_is_hold_and_caller_cannot_select_another_scope_or_key(self):
        import inspect
        self.assertEqual(tuple(inspect.signature(exact.audit_fixed_bootstrap_p0).parameters),
                         ('get','repo','now'))
        report,f=self.run_reader(now=datetime(2026,11,17,20,40))
        self.assert_hold(report)
        self.assertEqual(f['git'].fetches,[])
        for name,value in (('artifact_id',1),('run_id',1),('round_no',1),
                           ('day','2030-04-01'),('owner_key',self.KEY),('target',{})):
            with self.subTest(argument=name),self.assertRaises(TypeError):
                exact.audit_fixed_bootstrap_p0(get=lambda _:b'',repo=Path('/not-used'),
                                               now=self.CLOCK,**{name:value})

    def test_new_closed_artifact_count_does_not_waive_existing_completed_round_guard(self):
        from scripts import boat_owner_active_snapshot_audit as active
        report,_=self.run_reader()
        self.assertEqual(report['generated_forecasts'],4)
        run=dict(id=self.RUN,head_sha=self.HEAD,created_at='2026-11-17T20:35:16Z')
        job=dict(id=134349278782,run_id=self.RUN,head_sha=self.HEAD,run_attempt=1,
            name='Existing frozen P0, exhibition P1, separate official results and PDCA',
            status='in_progress',steps=[dict(name='Deadline-ordered five-model round 01',
                                           status='pending',conclusion=None)])
        with self.assertRaisesRegex(ValueError,'NO_COMPLETED_ROUND'):
            active._jobs(lambda _:self.wire(dict(total_count=1,jobs=[job])),
                         run,self.CLOCK,expected_owner_sha=self.HEAD)
        event=dict(repository=dict(full_name='haji84/RACE-AI'),ref='refs/heads/main')
        target=dict(schema='RACE_AI_M2_READONLY_AUDIT_TARGET_V1',run_id=44075021607,
                    source_commit='86b029ae5bddd5d4956497d8b32b2c92b8eec521')
        before=deepcopy(target)
        selected=active.select_audit_target('push',event,main_target=target)
        self.assertEqual(selected['run_id'],44075021607)
        self.assertEqual(selected['expected_owner_sha'],'86b029ae5bddd5d4956497d8b32b2c92b8eec521')
        self.assertEqual(target,before)

if __name__=='__main__':unittest.main()
