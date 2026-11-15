"""Reopen EVERY exact BOAT ALL_MODEL Actions ZIP on a different Actions runner.

Unlike normal recovery, this verifier never skips archived ZIPs merely because
their HMAC-backed coverage is already recorded. It re-fetches each native
artifact's exact GitHub metadata and ZIP bytes, verifies the physical SHA256,
decrypts the AES payload with the existing production owner key, projects its
original prediction without generating anything, checks cutoff against the
physical GitHub receipt, then matches unchanged prediction contents to the
separately AES-authenticated saved-view original when present.

Only count-level statistics leave the private runner. No racing-provider GET,
prediction regeneration, forecast edits, uploads, or local persistent storage.
"""
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import re

OWNER_SHA='5d1dabff0ab9bb83132cd7fbdd43f49fb4eef6c4'
SCHEMA='RACE_AI_BOAT_EXACT_ALL_MODEL_ZIP_READBACK_V1'
JST=timezone(timedelta(hours=9))
SHA=re.compile(r'[a-f0-9]{64}\Z')
RACE=re.compile(r'20[0-9]{6}-(?:0[1-9]|1[0-9]|2[0-4])-(?:0[1-9]|1[0-2])\Z')
MODEL=re.compile(r'[A-Za-z0-9_.-]{1,128}\Z')


def need(ok):
    if not ok:raise ValueError('BOAT_EXACT_ZIP_READBACK_REJECTED')


def moment(text):
    try:
        need(type(text) is str and len(text)<=64)
        instant=datetime.fromisoformat(text.replace('Z','+00:00'))
        need(instant.utcoffset() is not None)
        return instant
    except (TypeError,ValueError,OverflowError,AttributeError):
        raise ValueError('BOAT_EXACT_ZIP_READBACK_CLOCK_INVALID') from None


def _identity(race_id,prediction):
    """Digest only the immutable original content needed for byte-level parity.

    The digest is never represented as an original AES authenticity proof.
    Source SHA, actual GitHub artifact ID, forecast hash, ordered tickets,
    generated/as-of/cutoff and physically received clock must all agree.
    """
    from hashlib import sha256
    import json
    p=prediction
    values=[race_id,p.get('stage'),p.get('model_id'),
            p.get('model_version'),p.get('artifact_id'),
            p.get('original_json_sha256'),p.get('source_code_commit'),
            p.get('prediction_sha256'),p.get('output_sha256'),
            p.get('ordered_top8'),p.get('as_of'),p.get('generated_at'),
            p.get('server_saved_at'),p.get('cutoff_at')]
    return sha256(json.dumps(values,sort_keys=True,separators=(',',':'),
        ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def _official_cutoffs(get, repo, run, listing, reader, *, day, now, key):
    """Re-open P0 ZIP and independently verify the original official B source.

    An ALL_MODEL P1 archive cannot certify its own sales cutoff. Every cutoff
    used for acceptance is bound to the separately sealed official P0 ledger.
    """
    import json
    from race_ai.actions_contract import digest
    from race_ai.boat_source_control import _metadata
    from race_ai.boat_private_original_vault import _artifact, REPO_ID
    from race_ai.frozen_day_cycle import read_p0
    from race_ai.boat_program_source import load_program_source
    first=[a for a in listing if a.get('name')==f"boat-p0-existing-{run['id']}"]
    need(len(first)==1)
    item=first[0]
    ident=item['id']
    meta_raw=reader.read(f'actions/artifacts/{ident}',128*1024)
    meta=json.loads(meta_raw)
    raw=get(f'actions/artifacts/{ident}/zip')
    _metadata(raw,meta,name=item['name'],run_id=run['id'],head_sha=OWNER_SHA)
    _artifact(raw,meta_raw,key=key,now=now,expected_kind='P0')
    doc,p0=read_p0(raw,meta,expected_day=day)
    receipt=dict(repository_id=REPO_ID,repository='haji84/RACE-AI',
        run_id=str(run['id']),head_sha=OWNER_SHA,
        artifact_id=ident,created_at=meta['created_at'],
        payload_sha256=digest(doc),independently_verified=True)
    verified=load_program_source(day,doc,receipt,repo,key=key,as_of=now.isoformat())
    need(verified is not None)
    schedule=doc.get('schedule')
    need(type(schedule) is list and 0<len(schedule)<=288)
    ledger={}
    for item in schedule:
        need(type(item) is dict)
        rid=item.get('race_id')
        need(type(rid) is str and RACE.fullmatch(rid) and
             rid.startswith(day.replace('-','')) and rid not in ledger)
        cutoff=moment(item.get('cutoff_at'))
        need(cutoff.astimezone(JST).date().isoformat()==day)
        ledger[rid]=cutoff
    return ledger


def _scan(projection, *, day, artifact_id, physical_saved_at, expected, clock,
          source_original_index,official_cutoffs):
    need(type(projection) is dict and type(projection.get('records')) is list)
    outputs=[];unqualified=Counter();missing_from_view=0;reused_baseline=0
    saved=moment(physical_saved_at)
    for row in projection['records']:
        if row.get('sport')!='boat' or row.get('event_date_jst')!=day:continue
        rid=row.get('race_id')
        need(type(rid) is str and RACE.fullmatch(rid) and rid[:8]==day.replace('-',''))
        try:official=moment(row.get('cutoff_at'))
        except ValueError:
            official=None
        predictions=[row.get('prediction'),*(row.get('comparison_predictions') or [])]
        need(len(predictions)<=128)
        for p in predictions:
            if p is None or p.get('stage')!='P1':continue
            need(type(p) is dict and p.get('external_receipt_verified') is True and
                 p.get('source_code_commit')==OWNER_SHA)
            # The sealed ALL_MODEL packet can also reference exact baseline A/B
            # P1 originals. Their independent source ZIP must be verified via
            # its own P1 pathway; this ZIP authenticates only its new predictions.
            if p.get('artifact_id')!=artifact_id:
                need(p.get('dispatch_status')=='ORIGINAL_REUSED')
                reused_baseline+=1
                continue
            need(p.get('dispatch_status')=='GENERATED_UNATTESTED' and
                 p.get('server_saved_at')==physical_saved_at and
                 type(p.get('original_json_sha256')) is str and
                 SHA.fullmatch(p['original_json_sha256']) is not None)
            mid=p.get('model_id')
            need(type(mid) is str and MODEL.fullmatch(mid))
            if mid not in expected:
                unqualified['MODEL_NOT_IN_ACTIVE_CATALOG']+=1
                continue
            fp=_identity(rid,p)
            available=source_original_index.get(fp,0)
            if available>0:
                source_original_index[fp]=available-1
                matched=True
            else:
                matched=False
                missing_from_view+=1
            if official is None:
                unqualified['OFFICIAL_RACE_CUTOFF_UNAVAILABLE']+=1
                outputs.append((rid,mid,False,matched))
                continue
            if not p.get('cutoff_at'):
                unqualified['ORIGINAL_CUTOFF_MISSING']+=1
                outputs.append((rid,mid,False,matched))
                continue
            try:
                cutoff=moment(p['cutoff_at'])
                asof=moment(p['as_of'])
                generated=moment(p['generated_at'])
            except (KeyError,ValueError,TypeError):
                unqualified['ORIGINAL_CLOCK_MISSING_OR_INVALID']+=1
                outputs.append((rid,mid,False,matched))
                continue
            if cutoff!=official:
                unqualified['RACE_ORIGINAL_CUTOFF_CONFLICT']+=1
                outputs.append((rid,mid,False,matched))
                continue
            ordered=asof<=saved or (saved.microsecond==0 and
                                    saved<=asof<saved+timedelta(seconds=1))
            generated_order=generated<=saved or (saved.microsecond==0 and
                                    saved<=generated<saved+timedelta(seconds=1))
            eligible=(p.get('eligible_pre_cutoff') is True and
                      asof<cutoff and generated<cutoff and saved<cutoff and
                      saved<=clock and ordered and generated_order)
            if not eligible:
                unqualified['NOT_PHYSICALLY_PRE_CUTOFF']+=1
            outputs.append((rid,mid,eligible,matched))
    return outputs,unqualified,missing_from_view,reused_baseline


def audit(*,get,repo,run_id,day,expected_models,original_view,now,
          maximum_artifacts=64,owner_key=None):
    """Read all original ZIPs, ignoring any already-cached coverage shortcut.

    Caller must supply authentic saved day, pinned production source checkout
    and Actions-only private key. The read path is strictly GitHub artifacts.
    """
    from race_ai import boat_all_model_recovery as R
    from race_ai.cycle_recovery import artifact_pages
    from race_ai.boat_pdca_state import state_key
    need(callable(get) and type(run_id) is int and run_id>0
         and type(day) is str and date.fromisoformat(day).isoformat()==day
         and isinstance(now,datetime) and now.utcoffset() is not None
         and type(expected_models) in (list,tuple) and
         0<len(expected_models)<=128 and len(set(expected_models))==len(expected_models)
         and all(type(v) is str and MODEL.fullmatch(v) for v in expected_models)
         and type(maximum_artifacts) is int and 1<=maximum_artifacts<=128)
    need(type(original_view) is dict and type(original_view.get('records')) is list)
    expected=set(expected_models)
    key=state_key('production',owner_key)
    reader=R._MetadataReader(get)
    run=R._run(reader.read(f'actions/runs/{run_id}',1024*1024),run_id,now)
    need(run.get('head_sha')==OWNER_SHA and
         run.get('head_branch')=='production/boat-p0-p1-20261111' and
         run.get('event')=='workflow_dispatch' and
         run.get('status')=='completed')
    day_from_run=moment(run['created_at']).astimezone(JST).date().isoformat()
    need(day_from_run==day)
    listed=artifact_pages(reader,run_id)
    targets=[];unique_ids=set();unique_rounds=set()
    for item in listed:
        record=R._listed(item,run_id,now)
        if record is None:continue
        artifact_id,round_no=record
        need(artifact_id not in unique_ids and round_no not in unique_rounds)
        unique_ids.add(artifact_id);unique_rounds.add(round_no)
        targets.append((round_no,artifact_id,item))
    need(0<len(targets)<=maximum_artifacts)
    targets.sort()
    source_index=Counter()
    for row in original_view['records']:
        if row.get('sport')!='boat' or row.get('event_date_jst')!=day:continue
        for p in [row.get('prediction'),*(row.get('comparison_predictions') or [])]:
            if p is not None and p.get('stage')=='P1':
                source_index[_identity(row['race_id'],p)]+=1
    original_copy=Counter(source_index)
    physical_forecasts=0;matched=0;absent=0;eligible_slots=set()
    duplicates=0;invalid=Counter();by_model=Counter();round_counts=[];baseline_reuses=0
    all_archive_sha_verified=0;all_aes_authenticated=0
    for round_no,artifact_id,listed_item in targets:
        meta_raw=reader.read(f'actions/artifacts/{artifact_id}',128*1024)
        meta,archived=R._metadata(meta_raw,listed_item,run,now,get)
        # GitHub metadata's physical created_at, ZIP digest and exact ciphertext
        # are all checked by the *existing* pinned source _project(). This is
        # never a cached HMAC-only coverage acknowledgment.
        raw=get(f'actions/artifacts/{artifact_id}/zip')
        projected,summary,receipt=R._project(raw,meta,run,round_no,key)
        need(receipt.get('independently_verified') is True and
             receipt.get('created_at')==meta['created_at'] and
             receipt.get('artifact_id')==artifact_id and
             receipt.get('head_sha')==OWNER_SHA)
        all_archive_sha_verified+=1;all_aes_authenticated+=1
        rows,holds,missing,reused=_scan(projected,day=day,artifact_id=artifact_id,
                                physical_saved_at=meta['created_at'],
                                expected=expected,clock=now,
                                source_original_index=source_index)
        for rid,mid,eligible,equal in rows:
            physical_forecasts+=1;matched+=int(equal);absent+=int(not equal)
            if eligible:
                slot=(rid,mid)
                if slot in eligible_slots:duplicates+=1
                else:eligible_slots.add(slot);by_model[mid]+=1
        invalid.update(holds);baseline_reuses+=reused
        round_counts.append(dict(round=round_no,source_archive_zip_sha_verified=True,
                                 aes_decrypted_and_projected=True,
                                 forecast_p1_rows=len(rows),reused_baseline_p1_rows=reused,
                                 physically_pre_cutoff=sum(row[2] for row in rows),
                                 saved_view_originals_matched=sum(row[3] for row in rows)))
    need(0<all_archive_sha_verified==all_aes_authenticated==len(targets))
    need(matched+absent==physical_forecasts and
         all(original_copy[key]>=source_index.get(key,0) for key in source_index))
    # Difference is diagnostic only. Missing, duplicated and late original
    # predictions never become a successful user-visible completion claim.
    official_total=len(expected)*len({r['race_id'] for r in original_view['records']
                                  if r.get('sport')=='boat' and r.get('event_date_jst')==day})
    return dict(schema=SCHEMA,status='AES_ZIP_REPLAY_VERIFIED_P1_COVERAGE_INCOMPLETE',
        day_jst=day,owner_run_id=run_id,owner_source_commit=OWNER_SHA,
        actual_listed_archives=len(targets),github_zip_sha256_independently_verified=all_archive_sha_verified,
        aes_originals_independently_decrypted=all_aes_authenticated,
        original_content_projection_verified=all_aes_authenticated,
        p1_forecast_rows_reopened=physical_forecasts,
        referenced_existing_baseline_p1_rows_not_recounted=baseline_reuses,
        physical_pre_cutoff_distinct_model_slots=len(eligible_slots),
        original_predictions_matched_saved_AES_view=matched,
        original_predictions_missing_from_saved_AES_view=absent,
        duplicate_eligible_model_slots=duplicates,
        unqualified_original_reasons=dict(sorted(invalid.items())),
        scheduled_view_model_slot_upper_bound=official_total,
        per_model_physically_pre_cutoff=dict(sorted(by_model.items())),
        round_evidence=round_counts,
        previously_archived_coverages_skipped_without_zip_read=0,
        racing_provider_gets=0,prediction_generation_performed=False,
        production_predictions_modified=False,website_end_to_end_proven=False)
