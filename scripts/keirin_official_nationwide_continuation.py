"""Run the admitted official-SP continuation with bounded, private evidence.

Capture, independent Git readback, source-free publication and result polling
are separate operations. No global source flag or existing stop is changed.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from subprocess import TimeoutExpired
from tempfile import TemporaryDirectory
import argparse
import json
import os
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from race_ai import keirin_nationwide_auto_generator as model
from race_ai import keirin_confidence as confidence
from race_ai import keirin_nationwide_auto_storage as storage
from race_ai import keirin_nationwide_cipher_history as archive
from race_ai import keirin_official_nationwide_extension as extension
from race_ai import keirin_official_nationwide_records as records
from race_ai import keirin_official_nationwide_sources as sources
from race_ai import keirin_official_form_history as form
from race_ai import keirin_form_fall_shadow as shadow
from race_ai import keirin_official_run_history as history
from scripts import keirin_official_day_pipeline as pipeline
from scripts import keirin_capture_official_form_history as capture_files

SCHEMA='RACE_AI_KEIRIN_GITHUB_ONLY_LIVE_AB_DAY_V1'
CAPTURE_ARCHIVE_FETCH_HOLD = 'HOLD_OFFICIAL_SP_CAPTURE_ARCHIVE_FETCH_TIMEOUT'
WORKFLOW='haji84/RACE-AI/.github/workflows/keirin-nationwide-ab-auto.yml@refs/heads/main'
WATCH_WORKFLOW='haji84/RACE-AI/.github/workflows/keirin-result-live.yml@refs/heads/main'


def now_utc():return datetime.now(timezone.utc)


def need(ok,code):
    if not ok:raise ValueError('OFFICIAL_CONTINUATION_'+code)


def _runtime(*,repo,private_root,owner_public_pem,owner_private_pem,day,clock,mode):
    at=form._aware(clock());today=at.astimezone(form.JST).date().isoformat()
    day=day or today;history._day(day)
    need(mode in ('capture','publish','settle','measure'),'MODE_INVALID')
    need(os.getenv('GITHUB_ACTIONS')=='true' and os.getenv('GITHUB_REPOSITORY')==archive.REPO and
         os.getenv('GITHUB_REPOSITORY_ID')==archive.REPO_ID and os.getenv('GITHUB_REF')=='refs/heads/main' and
         os.getenv('GITHUB_EVENT_NAME') in ('schedule','workflow_dispatch') and
         os.getenv('RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED')=='true','TRUSTED_RUNTIME_REQUIRED')
    pair=(os.getenv('GITHUB_WORKFLOW_REF'),os.getenv('GITHUB_JOB'))
    allowed = {'capture': {(WORKFLOW,'official-sp-capture')}, 'publish': {(WORKFLOW,'official-sp-publish')},
               'settle': {(WORKFLOW,'official-sp-settle'), (WATCH_WORKFLOW,'observe-results')},
               'measure': {(WATCH_WORKFLOW,'measured-results')}}
    need(pair in allowed[mode], 'EXACT_SOURCE_JOB_REQUIRED')
    need(mode!='capture' or day==today,'CAPTURE_ACTUAL_DAY_REQUIRED')
    private_public=pipeline.check_owner_private_key(owner_private_pem)
    public=Path(owner_public_pem).read_bytes();parsed=storage.checked_public_key(public)
    need(parsed.public_numbers()==storage.checked_public_key(private_public).public_numbers(),'OWNER_KEY_PAIR_REQUIRED')
    root=capture_files._private_directory(private_root);repo=Path(repo).resolve()
    need(root.resolve()!=repo and repo not in root.resolve().parents,'PRIVATE_ROOT_OUTSIDE_REPOSITORY')
    commit=os.getenv('GITHUB_SHA','')
    need(archive.COMMIT.fullmatch(commit) and archive.RUN.fullmatch(os.getenv('GITHUB_RUN_ID','')),
         'RUN_CODE_IDENTITY_REQUIRED')
    checked=archive._remote(repo,synthetic_local=False)
    need(archive._cmd(checked,'rev-parse','HEAD')[1]==commit,'CHECKOUT_CODE_CHANGED')
    return repo,root,day,public,commit


def _begin_lease(repo,owner_private_pem,clock,commit,*,expected_day=None):
    from race_ai import keirin_official_source_continuation as continuation
    at = form._aware(clock())
    event_day = at.astimezone(form.JST).date().isoformat()
    need(expected_day is None or expected_day == event_day, 'CAPTURE_ACTUAL_DAY_REQUIRED')
    return continuation.begin(repo=repo,now=at,source_commit=commit,
        owner_private_pem=owner_private_pem,event_day=event_day,
        max_requests=300,lease_seconds=900)


def _summary(day,state='OFFICIAL_SP_CAPTURE_PARTIAL'):
    return dict(schema=SCHEMA,day_jst=day,state=state,registered_races=0,
        day_inventory_complete=False,all_prediction_coverage_complete=False,
        new_A_B_sealed=0,new_A_B_git_archived=0,new_conditioned_A_B_git_archived=0,
        new_encrypted_originals=[],source_requests=0,provider_denied=False,
        source_or_forecast_plaintext_exposed=False,paired_comparable_races=0,
        safe_diagnostics=[],statuses={})


def _baseline_already_exists(store,race_id):
    if race_id in store.index['originals']:return True
    raw=archive.read_blob_bytes(store.repo,store.head,archive._refs(race_id)[1],max_bytes=16384)
    if raw is None:
        need(archive.read_blob_bytes(store.repo,store.head,archive._refs(race_id)[0]) is None,'ORPHAN_BASELINE_ARCHIVE')
        return False
    receipt=history._json(raw)
    archive._read_at(store.repo,store.head,race_id,receipt['cipher_sha256'])
    return True


def _label(inventory,race):
    listed=next((s for s in inventory['list_sources'] if s['venue_code']==race['venue_code']),None)
    if listed is None:return None
    row=next((r for r in sources.cards._current_rows(listed['raw_bytes'],inventory['registry']['event_day'])
              if int(sources.cards.receipt._norm(r['strRaceNo']))==race['race_no']),None)
    return sources.cards.receipt._norm(row['strSyumokuName']) if row else None


def _save_registry(store,inventory,states,source_attempts,prior,public,clock):
    registry=inventory['registry']
    need(registry is not None,'REGISTRY_NOT_CAPTURED')
    at=form._aware(clock()).isoformat()
    payload=dict(schema=records.DAY_SCHEMA,day_jst=store.day,observed_at=at,
        producer_run_id=os.environ['GITHUB_RUN_ID'],producer_commit=os.environ['GITHUB_SHA'],
        prior_race_ids=prior,registry=registry,
        inventory={key:inventory[key] for key in ('calendar_receipt','list_sources')},
        states=sorted(states.values(),key=lambda r:r['race_id']),
        source_attempt_counts=source_attempts,
        safe_report=dict(day_jst=store.day,registered_races=len(registry['registered_race_ids'])))
    if 'unadmitted_class_evidence' in inventory:
        payload['unadmitted_class_evidence']=inventory['unadmitted_class_evidence']
    records.replay_registry(payload)
    return store.append(kind='registry',payload=payload,public_pem=public,observed_at=at)


def _seal_and_archive(*,candidate,condition_input,history_manifest,condition_state,session,
                      store,public,root,clock,commit,cohort,condition_history=None):
    snapshot=candidate['snapshot'];rid=snapshot['race_id']
    generated=form._aware(clock()).isoformat()
    baseline=model.generate_A_B(snapshot,generated_at=generated,max_tickets=12)
    assessment=confidence.assess_baseline(snapshot,baseline,
        assessed_at=form._aware(clock()).isoformat())
    adjusted=supplement=None
    if condition_input is not None:
        try:
            supplement=condition_input['supplement']
            adjusted=shadow.generate_shadow(snapshot,supplement,baseline=baseline,generated_at=generated)
        except (ValueError,KeyError,TypeError):
            adjusted=supplement=None;condition_state='HISTORY_UNVERIFIED'
    sealed_at=form._aware(clock()).isoformat()
    directory=capture_files._private_directory(root/rid)
    path=directory/(rid+'.sealed.json')
    saved=storage.seal_once(snapshot=snapshot,prediction=baseline,public_key_pem=public,path=path,
        sealed_at=sealed_at,confidence_assessment=assessment)
    digest=saved['cipher_sha256'];cohort_sha=model.digest(cohort)
    restored=archive.append_once(repo=store.repo,raw_cipher=path.read_bytes(),expected_cipher_sha256=digest,
        producer_run_id=os.environ['GITHUB_RUN_ID'],producer_commit=commit,cohort_sha256=cohort_sha)
    need(restored['state'] in ('GIT_ORIGINAL_CREATE_ONCE_AND_RESTORED','IDENTICAL_ORIGINAL_ALREADY_FROZEN_NO_NEW_WRITE'),
         'BASELINE_ARCHIVE_ACK_INVALID')
    condition_sha=condition_at=None
    condition_archive_state='NO_CONDITIONED_ORIGINAL'
    if adjusted is not None:
        try:
            condition_at=form._aware(clock()).isoformat();p=directory/(rid+'.form.sealed.json')
            sealed=shadow.seal_shadow_once(snapshot=snapshot,supplement=supplement,shadow=adjusted,
                public_key_pem=public,path=p,sealed_at=condition_at)
            condition_sha=sealed['file_sha256']
            written=archive.append_conditioned_once(repo=store.repo,raw_cipher=p.read_bytes(),
                expected_cipher_sha256=condition_sha,expected_baseline_cipher_sha256=digest,
                expected_baseline_prediction_sha256=baseline['prediction_sha256'],cohort_sha256=cohort_sha,
                producer_run_id=os.environ['GITHUB_RUN_ID'],producer_commit=commit)
            condition_archive_state=written['state']
            need(condition_archive_state in ('GIT_CONDITIONED_ORIGINAL_CREATE_ONCE_AND_RESTORED',
                 'IDENTICAL_CONDITIONED_ORIGINAL_ALREADY_FROZEN'),'CONDITION_ARCHIVE_ACK_INVALID')
            condition_state='CONDITIONED_ARCHIVED_AWAITING_READBACK'
        except (ValueError,KeyError,TypeError,OSError):
            adjusted=supplement=condition_sha=condition_at=None
            condition_state='CONDITIONED_ARCHIVE_UNVERIFIED';condition_archive_state='NO_CONDITIONED_ORIGINAL'
    needed=set()
    if history_manifest is not None:
        needed.update(r['bytes_sha256'] for r in history_manifest['source_receipts'])
    source_bytes={digest:session.sources[digest] for digest in needed if digest in session.sources}
    payload=dict(schema=records.PRE_SCHEMA,day_jst=store.day,race_id=rid,cohort=cohort,cohort_sha256=cohort_sha,
        producer_run_id=os.environ['GITHUB_RUN_ID'],producer_commit=commit,snapshot=snapshot,baseline=baseline,
        confidence_assessment=assessment,
        baseline_arguments=candidate['arguments'],baseline_cipher_sha256=digest,baseline_sealed_at=sealed_at,
        conditioned=adjusted,supplement=supplement,conditioned_cipher_sha256=condition_sha,
        conditioned_sealed_at=condition_at,condition_state=condition_state,
        history_manifest=history_manifest if adjusted is not None else None,
        source_bytes_by_sha=source_bytes if adjusted is not None else {},
        identity_proof=condition_input['identity_proof'] if adjusted is not None else None,
        availability=condition_input['availability'] if adjusted is not None else None,
        safe_report=dict(day_jst=store.day,race_id=rid,state='FROZEN_ORIGINAL_SOURCE_BUNDLE'))
    trial = None
    if condition_history is not None:
        from race_ai import keirin_official_condition_trial as trial_model

        try:
            trial = trial_model.build_from_official_card(snapshot, baseline,
                        candidate['arguments']['card_arguments'], condition_history)
        except (OSError, ValueError, TypeError, KeyError, ArithmeticError):
            # The ageing history or trial must never block the original forecast.
            trial = None
        if trial is not None and model.when(snapshot['published_cutoff_at']) - clock() >= trial_model.WITNESS_MARGIN:
            payload['condition_trial'] = trial
            try:
                combined = trial_model.build_combined(snapshot, baseline, trial,
                    generated_at=form._aware(clock()).isoformat(), form_shadow=adjusted, supplement=supplement)
            except (ValueError, TypeError, KeyError, ArithmeticError):
                combined = None
            if combined is not None and model.when(snapshot['published_cutoff_at']) - clock() >= trial_model.WITNESS_MARGIN:
                payload['combined_forecast'] = combined
    evidence=store.append(kind='original',payload=payload,public_pem=public,observed_at=clock(),race_id=rid)
    row=dict(race_id=rid,cipher_sha256=digest,conditioned_state=condition_archive_state,
             baseline_prediction_sha256=baseline['prediction_sha256'],cohort_sha256=cohort_sha,
             evidence_cipher_sha256=evidence['cipher_sha256'])
    if condition_sha is not None:row['conditioned_cipher_sha256']=condition_sha
    if 'condition_trial' in payload:
        row.update(condition_trial_sha256=model.digest(trial), evidence_sha256=evidence['evidence_sha256'])
    return row,condition_state


# Each baseline can add one card, one marks response and at most nine profiles.
# The list, line and marks scripts are shared by the entire source session.
BASELINE_RACE_REQUESTS = 11
BASELINE_SHARED_REQUESTS = len(sources.LIST_SCRIPTS) + 1 + len(sources.cards._TAB_SCRIPT_REQUIREMENTS)
CAPTURE_CLASS_SAMPLES = 4
CLASS_EVIDENCE_REQUESTS = CAPTURE_CLASS_SAMPLES + len(sources.LIST_SCRIPTS)
MAX_CUTOFF_PROBES = 8
NEAR_CUTOFF_WINDOW = timedelta(minutes=30)


def _probe_capture_cutoffs(session, inventory, store, required_calls, clock):
    cutoffs = {}
    venues = set()
    races = sorted(inventory['registry']['races'], key=lambda row: (row['race_no'], row['venue_code']))
    # A first card can require two shared controller scripts. Leave enough
    # scope for the existing full baseline and class verification.
    probe_calls = required_calls + 1 + len(sources.LIST_SCRIPTS)
    probe_seconds = sources.CAPTURE_LEASE_RESERVE_SECONDS + probe_calls * sources.REQUEST_SPACING_SECONDS
    for race in races:
        if len(venues) >= MAX_CUTOFF_PROBES or session.halted:
            break
        rid, venue = race['race_id'], race['venue_code']
        if (venue in venues or rid in store.index['originals'] or race['source_state'] != 'RACECARD_PUBLISHED'
                or _label(inventory, race) not in extension.OBSERVED_CLASSES):
            continue
        if _baseline_already_exists(store, rid):
            continue
        if not session.has_capture_capacity(probe_calls, seconds=probe_seconds):
            break
        venues.add(venue)
        try:
            cutoff = sources.collect_capture_cutoff(session=session, inventory=inventory, race=race, clock=clock)
        except sources.CaptureBudgetPending:
            break
        except (ValueError, KeyError, TypeError, OSError, StopIteration):
            continue
        if cutoff is not None:
            cutoffs[rid] = cutoff
            feasible_at = form._aware(clock()) + timedelta(seconds=sources.CAPTURE_START_MARGIN_SECONDS)
            if feasible_at <= cutoff <= feasible_at + timedelta(seconds=sources.CAPTURE_LEASE_RESERVE_SECONDS):
                break
    return cutoffs


def _prioritize_capture_races(races, source_attempts, saved_cutoffs, fresh_cutoffs, now):
    unknown = datetime.max.replace(tzinfo=timezone.utc)
    earliest = now + timedelta(seconds=sources.CAPTURE_START_MARGIN_SECONDS)
    horizon = now + NEAR_CUTOFF_WINDOW

    def priority(race):
        rid = race['race_id']
        fresh = fresh_cutoffs.get(rid, unknown)
        urgent = fresh if earliest <= fresh <= horizon else unknown
        return (urgent, source_attempts.get(rid, 0), race['race_no'],
                saved_cutoffs.get(rid, unknown), race['venue_code'])

    return sorted(races, key=priority)


_REPORTABLE_BASELINE_HOLDS = {
    sources.SourceError: frozenset({
        'OFFICIAL_CONTINUATION_CAPTURE_START_MARGIN_REQUIRED',
        'OFFICIAL_CONTINUATION_CLASS_OR_ROUND_NOT_OBSERVED',
        'OFFICIAL_CONTINUATION_FUTURE_REFERENCE_REQUIRED',
        'OFFICIAL_CONTINUATION_LINE_VIEW_NOT_LINKED',
        'OFFICIAL_CONTINUATION_LIST_SCRIPT_CHANGED',
        'OFFICIAL_CONTINUATION_LIST_SCRIPT_NOT_LINKED',
        'OFFICIAL_CONTINUATION_MARKS_SCRIPTS_NOT_LINKED',
    }),
    extension.OfficialExtensionError: frozenset({
        'OFFICIAL_EXTENSION_CARD_CLASS_DISAGREEMENT',
        'OFFICIAL_EXTENSION_CLASS_OR_ROUND_NOT_YET_OBSERVED',
        'OFFICIAL_EXTENSION_CONTESTED_OR_MULTILEVEL_LINE_UNSUPPORTED',
        'OFFICIAL_EXTENSION_CURRENT_RACE_CLASS_MISSING',
        'OFFICIAL_EXTENSION_FUTURE_CARD_REFERENCE_REQUIRED',
        'OFFICIAL_EXTENSION_FUTURE_CLOCK_MARGIN_REQUIRED',
        'OFFICIAL_EXTENSION_GIRLS_LINE_NOT_EXPLICIT',
        'OFFICIAL_EXTENSION_LINE_GROUP_COUNT_OR_LABEL_UNKNOWN',
        'OFFICIAL_EXTENSION_LINE_NOT_PUBLISHED',
        'OFFICIAL_EXTENSION_LINE_PARENTHESIS_OR_ROSTER_UNSUPPORTED',
        'OFFICIAL_EXTENSION_LINE_POSITION_DUPLICATED',
        'OFFICIAL_EXTENSION_LINE_POSITION_UNSUPPORTED',
        'OFFICIAL_EXTENSION_LINE_ROSTER_MISMATCH',
        'OFFICIAL_EXTENSION_LINE_VIEW_AFTER_INPUT',
        'OFFICIAL_EXTENSION_LINE_VIEW_CHANGED',
        'OFFICIAL_EXTENSION_LINE_VIEW_NOT_BOUND',
        'OFFICIAL_EXTENSION_PROFILE_CARD_DISAGREEMENT',
        'OFFICIAL_EXTENSION_PROFILE_REGISTRATION_MISMATCH',
        'OFFICIAL_EXTENSION_PROFILE_ROSTER_INCOMPLETE',
        'OFFICIAL_EXTENSION_PROFILE_SOURCE_OR_CLOCK_INVALID',
        'OFFICIAL_EXTENSION_WITHDRAWAL_OR_ROSTER_UNRESOLVED',
    }),
    sources.cards.receipt.OfficialSPReceiptError: frozenset({
        'KEIRIN_OFFICIAL_SP_CALENDAR_BINDING_INVALID',
        'KEIRIN_OFFICIAL_SP_CUTOFF_NOT_BEFORE_START',
        'KEIRIN_OFFICIAL_SP_DETAIL_DAY_OR_RACE_MISMATCH',
        'KEIRIN_OFFICIAL_SP_OFFICIAL_CUTOFF_DATE_MISMATCH',
        'KEIRIN_OFFICIAL_SP_RIDER_IDENTITY_INVALID',
        'KEIRIN_OFFICIAL_SP_ROSTER_ROW_SCHEMA',
        'KEIRIN_OFFICIAL_SP_ROSTER_UNAVAILABLE',
    }),
    sources.cards.CanaryCardError: frozenset({
        'PUBLIC_PREDICTION_MODE_NOT_OBSERVED',
        'PUBLIC_PREDICTION_TAB_NOT_OBSERVED',
        'PUBLIC_TAB_SCRIPTS_NOT_LINKED',
    }),
}


def _baseline_hold_reason(error):
    code = str(error)
    if code in _REPORTABLE_BASELINE_HOLDS.get(type(error), ()):
        return code
    return 'BASELINE_VALIDATION_OR_OPERATION_HELD'


def _archive_batch_deadline(cutoffs, reserve):
    # A pending original can use the full reserve before the next write starts.
    return min(cutoff - position * reserve
               for position, cutoff in enumerate(sorted(cutoffs), start=1))


def run_capture(*,repo,private_root,owner_public_pem,owner_private_pem,day=None,clock=now_utc,max_races=4):
    repo,root,day,public,commit=_runtime(repo=repo,private_root=private_root,owner_public_pem=owner_public_pem,
        owner_private_pem=owner_private_pem,day=day,clock=clock,mode='capture')
    need(type(max_races) is int and 1<=max_races<=8,'CAPTURE_RACE_BOUND')
    report = _summary(day)
    try:
        # The fresh capture runner needs the lineage and selected records, not
        # every historical ciphertext. This still precedes the source lease.
        store = records.RecordStore(repo, day, retry_archive_timeout=True, blobless_fetch=True)
    except archive.GitCipherFetchTimeout:
        report['state'] = CAPTURE_ARCHIVE_FETCH_HOLD
        return report
    prior=[];source_attempts={};previous=None
    if store.index['registry']:
        previous=store.read(store.index['registry'],owner_private_pem)
        prior=records.replay_registry(previous)['registered_race_ids']
        if 'source_attempt_counts' in previous:
            source_attempts=dict(previous['source_attempt_counts'])
        else:
            # Older registries can establish an attempt for these final states.
            attempted_states={'BASELINE_SOURCE_UNVERIFIED','CUTOFF_MARGIN_INSUFFICIENT','FROZEN_ARCHIVE_UNVERIFIED'}
            source_attempts={r['race_id']:1 for r in previous['states'] if r['state'] in attempted_states}
    prior=sorted(set(prior)|set(store.index['originals']))
    from race_ai.keirin_official_condition_trial import HistoryPacket, study_is_open

    try:
        study_open = study_is_open(day)
        condition_history = HistoryPacket.from_repository(repo, day, allow_previous=True) if study_open else None
        report['condition_history_state'] = ('STUDY_INACTIVE' if not study_open else
                                             'AVAILABLE' if condition_history else 'NOT_PUBLISHED')
    except (ValueError, KeyError, TypeError, OSError, TimeoutExpired):
        condition_history = None
        report['condition_history_state'] = 'SOURCE_READ_HELD'
    lease=_begin_lease(repo,owner_private_pem,clock,commit,expected_day=day)
    session=sources.OfficialSourceSession(repo=repo,private_root=capture_files._private_directory(root/'sources'),
                                         lease=lease,clock=clock)
    finish='FAILED'
    try:
        inventory=extension.collect_day_inventory(request=session.request,clock=clock,event_day=day,
                                                  prior_race_ids=prior)
        registry=inventory['registry']
        if registry is None:
            report['state']='HOLD_OFFICIAL_DAY_SOURCE_UNAVAILABLE'
            finish='PROVIDER_STOPPED' if session.provider_denied else 'PARTIAL'
            return report
        need(len(registry['registered_race_ids'])<=records.MAX_RACES,'REGISTRY_RACE_BOUND')
        session.capture_budget_enabled=True
        states={rid:dict(race_id=rid,state='WAITING_SOURCE_CAPTURE',condition_state='HISTORY_NOT_COLLECTED')
                for rid in registry['registered_race_ids']}
        report.update(registered_races=len(states),day_inventory_complete=registry['day_inventory_complete'])
        for rid in registry['disappeared_race_ids']:states[rid]['state']='RACE_DISAPPEARED_FROM_CURRENT_LIST'
        _save_registry(store,inventory,states,source_attempts,prior,public,clock)
        cohort=records.cohort(registry);attempted=0
        finalization_reserve = timedelta(seconds=sources.CAPTURE_FINALIZATION_SECONDS)
        request_reserve = timedelta(seconds=sources.CAPTURE_LEASE_RESERVE_SECONDS)
        start_margin = timedelta(seconds=sources.CAPTURE_START_MARGIN_SECONDS)
        history_duration = timedelta(seconds=sources.CONDITION_DURATION_SECONDS)
        required_calls = BASELINE_RACE_REQUESTS + BASELINE_SHARED_REQUESTS + CLASS_EVIDENCE_REQUESTS
        from race_ai.keirin_official_class_evidence import collect_unknown_class_evidence, replay_cutoff_hints, LABEL
        fresh_cutoffs = _probe_capture_cutoffs(session, inventory, store, required_calls, clock)
        now = form._aware(clock())
        saved_cutoffs = replay_cutoff_hints(previous, inventory, now=now)
        ordered = _prioritize_capture_races(registry['races'], source_attempts, saved_cutoffs, fresh_cutoffs, now)
        baseline_holds = Counter()
        ready = []
        for race in ordered:
            rid=race['race_id'];row=states[rid]
            if _baseline_already_exists(store,rid):row['state']='FROZEN_ORIGINAL_PRESERVED';continue
            if race['source_state']=='RESULT_PUBLISHED':row['state']='PUBLISHED_RESULT_NO_PRE_CUTOFF_ORIGINAL';continue
            if _label(inventory,race) not in extension.OBSERVED_CLASSES:
                row['state']='UNSUPPORTED_CLASS_OR_ROUND';continue
            if session.halted:
                row['state']='PROVIDER_STOPPED' if session.provider_denied else 'SOURCE_UNAVAILABLE';continue
            cutoff = fresh_cutoffs.get(rid)
            if cutoff is not None and cutoff - form._aware(clock()) < start_margin:
                row['state'] = 'CUTOFF_MARGIN_INSUFFICIENT'
                baseline_holds['OFFICIAL_CONTINUATION_CAPTURE_START_MARGIN_REQUIRED'] += 1
                continue
            if attempted>=max_races:row['state']='SOURCE_CAPTURE_BUDGET_PENDING';continue
            if ready:
                deadline = _archive_batch_deadline([cutoff for cutoff, _, _ in ready], finalization_reserve)
                # Leave a write slot for this candidate in addition to the queued originals.
                session.capture_deadline = deadline - finalization_reserve
                if session.capture_deadline - form._aware(clock()) < request_reserve:
                    row['state']='SOURCE_CAPTURE_BUDGET_PENDING';continue
            if not session.has_capture_capacity(required_calls, seconds=(
                    sources.CAPTURE_LEASE_RESERVE_SECONDS + required_calls * sources.REQUEST_SPACING_SECONDS)):
                row['state']='SOURCE_UNAVAILABLE' if session.halted else 'SOURCE_CAPTURE_BUDGET_PENDING'
                continue
            attempted+=1
            source_attempts[rid]=source_attempts.get(rid,0)+1
            try:
                candidate=sources.collect_candidate(session=session,inventory=inventory,race=race,clock=clock)
            except sources.CaptureBudgetPending:
                row['state']='SOURCE_CAPTURE_BUDGET_PENDING'
                continue
            except (ValueError,KeyError,TypeError,OSError) as exc:
                row['state']=('PROVIDER_STOPPED' if session.provider_denied else 'SOURCE_UNAVAILABLE' if session.halted else
                    'CUTOFF_MARGIN_INSUFFICIENT' if 'MARGIN' in str(exc) else 'BASELINE_SOURCE_UNVERIFIED')
                if row['state'] in ('CUTOFF_MARGIN_INSUFFICIENT', 'BASELINE_SOURCE_UNVERIFIED'):
                    baseline_holds[_baseline_hold_reason(exc)] += 1
                continue
            ready.append((form._aware(candidate['snapshot']['published_cutoff_at']), rid, candidate))

        # Optional history uses the same leased provider. If it stops, every
        # baseline already collected can still be frozen and read back.
        ready.sort(key=lambda entry: entry[0])
        cutoffs = [cutoff for cutoff, _, _ in ready]
        readback_deadline = cutoffs[0] - finalization_reserve if cutoffs else None
        for index, (_, rid, candidate) in enumerate(ready):
            row = states[rid]
            session.capture_deadline = min(readback_deadline,
                _archive_batch_deadline(cutoffs[index:], finalization_reserve))
            joined=manifest=None;condition_state='HISTORY_NOT_COLLECTED'
            if not session.halted and session.capture_deadline > form._aware(clock()) + history_duration and session.has_capture_capacity(
                    sources.CONDITION_REQUEST_LIMIT + CLASS_EVIDENCE_REQUESTS, seconds=(
                        sources.CAPTURE_LEASE_RESERVE_SECONDS + sources.CONDITION_DURATION_SECONDS
                        + CLASS_EVIDENCE_REQUESTS * sources.REQUEST_SPACING_SECONDS)):
                try:
                    manifest=sources.collect_conditions(session=session,candidate=candidate,clock=clock)
                    args=candidate['arguments']
                    joined=sources.build_condition_candidate(snapshot=candidate['snapshot'],
                        card_arguments=args['card_arguments'],prediction_source=args['prediction_source'],
                        prediction_scripts=args['prediction_scripts'],history_manifest=manifest,
                        source_bytes_by_sha=session.sources,now=clock())
                except sources.CaptureBudgetPending:
                    joined=manifest=None
                except (ValueError,KeyError,TypeError,OSError):
                    joined=manifest=None
                    condition_state='HISTORY_SOURCE_UNAVAILABLE' if session.halted else 'HISTORY_UNVERIFIED'
            elif session.halted:
                condition_state='HISTORY_SOURCE_UNAVAILABLE'
            try:
                saved,condition_state=_seal_and_archive(candidate=candidate,condition_input=joined,
                    history_manifest=manifest,condition_state=condition_state,session=session,store=store,
                    public=public,root=root,clock=clock,commit=commit,cohort=cohort,
                    condition_history=condition_history)
                report['new_encrypted_originals'].append(saved)
                row.update(state='A_B_ARCHIVED_AWAITING_INDEPENDENT_READBACK',condition_state=condition_state)
            except (ValueError,KeyError,TypeError,OSError):
                row.update(state='FROZEN_ARCHIVE_UNVERIFIED',condition_state=condition_state)
            _save_registry(store,inventory,states,source_attempts,prior,public,clock)
        session.capture_deadline = readback_deadline
        if not session.halted and (readback_deadline is None or form._aware(clock()) < readback_deadline):
            if session.has_capture_capacity(CLASS_EVIDENCE_REQUESTS, seconds=(
                    sources.CAPTURE_LEASE_RESERVE_SECONDS + CLASS_EVIDENCE_REQUESTS * sources.REQUEST_SPACING_SECONDS)):
                try:
                    evidence=collect_unknown_class_evidence(session=session,inventory=inventory,clock=clock,
                                                             max_classes=CAPTURE_CLASS_SAMPLES)
                    inventory['unadmitted_class_evidence']=evidence
                    report['class_evidence']=evidence['safe_summary']
                    if evidence.get('budget_pending'):
                        report['class_evidence_hold']='UNADMITTED_CLASS_EVIDENCE_BUDGET_PENDING'
                except (ValueError,KeyError,TypeError,OSError):
                    report['class_evidence_hold']='UNADMITTED_CLASS_EVIDENCE_UNAVAILABLE'
            else:
                report['class_evidence_hold']=('UNADMITTED_CLASS_EVIDENCE_UNAVAILABLE' if session.halted
                                               else 'UNADMITTED_CLASS_EVIDENCE_BUDGET_PENDING')
        classes={}
        for race in registry['races']:
            label=_label(inventory,race)
            label=label if label and (LABEL.fullmatch(label) or label in extension.OBSERVED_CLASSES) else 'UNRECOGNIZED_CLASS_LABEL'
            classes.setdefault(label,Counter())[states[race['race_id']]['state']]+=1
        report['class_statuses']=[dict(class_label=label,statuses=dict(sorted(counts.items())))
                                  for label,counts in sorted(classes.items())]
        report['baseline_hold_reasons'] = dict(sorted(baseline_holds.items()))
        _save_registry(store,inventory,states,source_attempts,prior,public,clock)
        count=len(report['new_encrypted_originals'])
        report['condition_trials_frozen'] = sum('condition_trial_sha256' in row
                                                for row in report['new_encrypted_originals'])
        report.update(new_A_B_sealed=count,new_A_B_git_archived=count,
            new_conditioned_A_B_git_archived=sum('conditioned_cipher_sha256' in row for row in report['new_encrypted_originals']),
            statuses=dict(sorted(Counter(row['state'] for row in states.values()).items())))
        report['state']='OFFICIAL_SP_BASELINES_ARCHIVED' if count else 'OFFICIAL_SP_DAY_REGISTERED_WITH_EXPLICIT_HOLDS'
        finish='PROVIDER_STOPPED' if session.provider_denied else 'PARTIAL'
        return report
    finally:
        report.update(source_requests=session.count,provider_denied=session.provider_denied,
                      safe_diagnostics=session.safe_diagnostics)
        if session.halted and not session.provider_denied and report['state'] in (
                'OFFICIAL_SP_BASELINES_ARCHIVED','OFFICIAL_SP_DAY_REGISTERED_WITH_EXPLICIT_HOLDS'):
            report['state']='HOLD_OFFICIAL_SP_SOURCE_UNAVAILABLE'
        session.close()
        try:lease.finish(state=finish,now=clock())
        except Exception:
            # This closes source work, but a receipt failure cannot erase
            # already archived originals from the independent readback job.
            report['source_lease_finish_failed']=True
            report['state']='HOLD_OFFICIAL_SP_FINISH_RECEIPT_FAILED'


def run_publish(*,repo,private_root,owner_public_pem,owner_private_pem,day=None,clock=now_utc):
    repo,root,day,public,commit=_runtime(repo=repo,private_root=private_root,owner_public_pem=owner_public_pem,
        owner_private_pem=owner_private_pem,day=day,clock=clock,mode='publish')
    from race_ai.keirin_nationwide_forecast_view import publish_day
    from scripts.keirin_publish_rider_context import publish_day as publish_rider_context
    from scripts.keirin_public_rider_projection import publish_starters
    # Keep the shallow promisor repository out of the archive and Note writer checkouts.
    with TemporaryDirectory(prefix='official-publish-archive-',dir=root) as folder:
        reader=Path(folder)
        archive._cmd(reader,'init','--quiet','--template=')
        archive._cmd(reader,'remote','add','origin',f'https://github.com/{archive.REPO}.git')
        archive._cmd(reader,'config','--local','remote.origin.promisor','true')
        archive._cmd(reader,'config','--local','remote.origin.partialclonefilter','blob:none')
        admitted=records.load_admitted_day(reader,owner_private_pem,day,partial_read=True,include_starters=True,
                                          include_dossier_context=True)
    result=publish_day(repo,admitted,commit,owner_private_pem,clock=clock,public_view=True)
    need(type(result) is dict and result.get('provider_requests')==0 and result.get('state') in
         ('KEIRIN_NOTE_ENCRYPTED_GIT_READBACK_VERIFIED','EXISTING_NATIONWIDE_DISPLAY_REUSED'),
         'PUBLICATION_ACK_INVALID')
    try:
        public_starters=publish_starters(repo,day=day,rows=admitted['starter_rows'],published_at=clock())
    except (OSError,ValueError,TypeError,KeyError,OverflowError,TimeoutExpired):
        public_starters={'state':'HOLD_PUBLIC_OFFICIAL_STARTERS'}
    public_starters['source_projection_holds']=admitted['starter_source_holds']
    try:
        public_context = publish_rider_context(repo, day, admitted.get('dossier_rows', []), published_at=clock())
    except (OSError,ValueError,TypeError,KeyError,OverflowError,TimeoutExpired):
        public_context={'state':'HOLD_PUBLIC_RIDER_CONTEXT'}
    public_context['source_projection_holds']=admitted.get('dossier_holds', 0)
    return dict(result,day_jst=day,source_requests=0,authenticated_originals=len(admitted['records']),
                public_starters=public_starters,public_rider_context=public_context)


class SettlementContext:
    """One lazily opened source lease for a bounded result observer process."""
    def __init__(self):
        self.lease=None;self.session=None;self.tick=0;self.client=None;self.packet_cache={}
        self.source_day=None;self.closed=False;self.finish_failed=False
        self.attempted={};self.replay_attempted={};self.published_revisions=set();self.stores={}
        self.original_day_signatures={};self.original_day_attempted={}
        self.safe_holds=[]
        self.archive_preflight_pending = True

    def allow_archive_timeout_retry(self):
        allowed = self.archive_preflight_pending and self.lease is None
        self.archive_preflight_pending = False
        return allowed

    def ensure(self,*,repo,private_root,owner_private_pem,clock,commit):
        need(not self.closed,'RESULT_CONTEXT_CLOSED')
        day=form._aware(clock()).astimezone(form.JST).date().isoformat()
        if self.lease is not None:
            need(self.source_day==day and not self.session.halted,'RESULT_SOURCE_CONTEXT_ENDED')
            self.lease.assert_active(repo=repo,now=clock())
            self.session.cache.clear()
            return self.session
        self.lease=_begin_lease(repo,owner_private_pem,clock,commit);self.source_day=day
        self.session=sources.OfficialSourceSession(repo=repo,
            private_root=capture_files._private_directory(Path(private_root)/'result-sources'),
            lease=self.lease,clock=clock)
        return self.session

    def close(self,clock=now_utc):
        if self.closed:return
        self.closed=True
        if self.session is not None:self.session.close()
        if self.lease is not None:
            try:self.lease.finish(state='PROVIDER_STOPPED' if self.session and self.session.provider_denied else 'PARTIAL',now=clock())
            except Exception:self.finish_failed=True


def _join_updates(documents):
    from race_ai import keirin_result_updates as updates
    latest={}
    for doc in documents:
        for row in doc['races']:
            prior=latest.get(row['race_id'])
            if prior is None or form._aware(row['observed_at'])>=form._aware(prior['observed_at']):
                latest[row['race_id']]=row
    rows=list(latest.values())
    at=max((form._aware(row['observed_at']) for row in rows),default=datetime(1970,1,1,tzinfo=timezone.utc))
    return updates.checked_updates(dict(schema=updates.SCHEMA,observed_at=at.isoformat(),races=rows))


def _publish_result(repo,doc,commit,private):
    from race_ai.keirin_result_updates import publish_updates
    ack=publish_updates(repo,doc,source_commit=commit,owner_private_pem=private)
    need(type(ack) is dict and ack.get('provider_requests')==0 and ack.get('state') in (
        'KEIRIN_NOTE_ENCRYPTED_GIT_READBACK_VERIFIED','EXISTING_RESULT_DISPLAY_REUSED'),
        'RESULT_DISPLAY_ACK_INVALID')
    return ack


def _hold(context,stage,code,race_id=None):
    # stage/code are local literals; exception text and source values never
    # become public diagnostics.
    row=dict(stage=stage,code=code)
    if race_id is not None:row['race_id']=race_id
    context.safe_holds.append(row);context.safe_holds=context.safe_holds[-32:]


def _known_days(repo,clock,context,days=None):
    now=form._aware(clock());today=now.astimezone(form.JST).date().isoformat()
    if days is None:
        known = records.discover_days(repo, retry_archive_timeout=context.allow_archive_timeout_retry())
    else:
        known = list(days)
    known=[day for day in known if day<=today]
    current=[d for d in known if d==today];older=sorted((d for d in known if d!=today),reverse=True)
    # One bounded backlog opportunity per observer window; current due originals
    # otherwise stay ahead of yesterday's unresolved publication.
    return ((older+current) if context.tick and context.tick%10==0 else current+older)[:10]


def _store_for_tick(repo,day,context):
    if day not in context.stores:
        context.stores[day] = records.RecordStore(
            repo, day, retry_archive_timeout=context.allow_archive_timeout_retry())
    return context.stores[day]


def _refresh_origin_metadata(context):
    """Refresh mutable run lists without replacing a refusal-latched client."""
    from race_ai.keirin_github_evidence_client import GitHubEvidenceClient
    if isinstance(context.client,GitHubEvidenceClient):
        for path in list(context.client._cache):
            if path.startswith('/actions/runs/'):
                del context.client._cache[path]
    # Immutable artifact downloads and completed packet_cache remain intact.


def _recover_saved_originals(repo,private,context,days,commit,publish,report):
    """Restore at most two saved day displays, before results or any source lease."""
    if not publish:return
    from race_ai.keirin_nationwide_forecast_view import publish_day
    from race_ai.keirin_github_evidence_client import GitHubEvidenceClient
    candidates=[]
    for position,day in enumerate(days):
        store=_store_for_tick(repo,day,context)
        if store.index['registry'] is None:continue
        signature=model.digest(dict(registry=store.index['registry'],originals=store.index['originals']))
        if context.original_day_signatures.get(day)==signature:continue
        candidates.append((context.original_day_attempted.get(day,0),position,day,signature,store))
    for _,_,day,signature,store in sorted(candidates)[:2]:
        context.original_day_attempted[day]=context.tick
        try:
            context.client=context.client or GitHubEvidenceClient()
            admitted=records.load_admitted_day(repo,private,day,origin_client=context.client)
            ack=publish_day(repo,admitted,commit,private)
            need(type(ack) is dict and ack.get('provider_requests')==0 and ack.get('state') in (
                'KEIRIN_NOTE_ENCRYPTED_GIT_READBACK_VERIFIED','EXISTING_NATIONWIDE_DISPLAY_REUSED') and
                type(ack.get('published_originals')) is int and 0<=ack['published_originals']<=len(admitted['records']) and
                type(ack.get('published_day_status')) is int and ack['published_day_status'] in (0,1) and
                (ack['state']!='EXISTING_NATIONWIDE_DISPLAY_REUSED' or
                 ack['published_originals']==ack['published_day_status']==0),'SAVED_ORIGINAL_DISPLAY_ACK_INVALID')
            report['published_originals']+=ack['published_originals']
            report['original_publication_acks']+=1
            report['published_day_status']+=ack['published_day_status']
            admitted_ids={row['race_id'] for row in admitted['records']}
            pending_condition=any(row.get('condition_state') in (
                'CONDITIONED_ARCHIVED_AWAITING_READBACK','CONDITIONED_ORIGIN_PROOF_PENDING',
                'CONDITIONED_ARCHIVE_UNVERIFIED') for row in admitted['records'])
            # A later GitHub readback can become visible without an index
            # change. Do not cache a partially admitted day as complete.
            if admitted_ids==set(store.index['originals']) and not pending_condition:
                context.original_day_signatures[day]=signature
        except (ValueError,KeyError,TypeError,OSError):
            report['origin_held']+=1
            _hold(context,'ORIGINAL_DISPLAY_RECOVERY','SAVED_ORIGINAL_ADMISSION_OR_PUBLICATION_HELD')


def _recover_saved_results(repo,private,context,days,commit,publish,documents,report):
    """Archive success survives a failed/aborted prior publication, without I/O to sources."""
    attempts=0
    for day in days:
        store=_store_for_tick(repo,day,context)
        candidates=sorted(store.index['results'].items(),key=lambda item:(
            context.replay_attempted.get((day,item[0]),0),item[0]))
        for rid,versions in candidates:
            meta=versions[-1];key=(day,rid,meta['evidence_sha256'])
            if key in context.published_revisions:continue
            if attempts>=8:return
            attempts+=1;context.replay_attempted[(day,rid)]=context.tick
            stage='SAVED_RESULT_REPLAY'
            try:
                doc=records.replay_saved_result(store,store.index['originals'][rid],meta,private)
                documents.append(doc)
                if publish:
                    stage='RESULT_PUBLICATION';ack=_publish_result(repo,doc,commit,private)
                    report['published_races']+=ack['published_races'];report['publication_acks']+=1
                context.published_revisions.add(key)
            except (ValueError,KeyError,TypeError,OSError):
                report['origin_held']+=1
                _hold(context,stage,'SAVED_RESULT_REPLAY_OR_PUBLICATION_HELD',rid)


def _pending_originals(repo,private,clock,context,max_races,days=None):
    from race_ai.keirin_github_evidence_client import GitHubEvidenceClient
    now=form._aware(clock());selected=_known_days(repo,clock,context,days)
    context.client=context.client or GitHubEvidenceClient()
    out=[];held=0;attempts=0
    for day in selected:
        store=_store_for_tick(repo,day,context)
        # Unobserved order checks take priority over unit-only retries. Within
        # each class the least recently attempted row prevents starvation.
        candidates=sorted(store.index['originals'].items(),key=lambda item:(
            bool(store.index['results'].get(item[0])),context.attempted.get((day,item[0]),0),
            item[1]['cutoff_at'],item[0]))
        for rid,meta in candidates:
            if len(out)>=max_races or attempts>=32:return out,held
            if form._aware(meta['cutoff_at'])>=now:continue
            previous=store.index['results'].get(rid,[])
            if previous and previous[-1]['monetary_complete']:continue
            attempts+=1;context.attempted[(day,rid)]=context.tick
            try:
                payload=store.read(meta,private)
                original,packets=records.admit_original(store,payload,private,
                    origin_client=context.client,packet_cache=context.packet_cache)
                out.append(dict(store=store,meta=meta,payload=payload,original=original,packets=packets))
            except (ValueError,KeyError,TypeError,OSError):
                held+=1;_hold(context,'ORIGINAL_ADMISSION','ORIGINAL_SOURCE_OR_SERVER_ORIGIN_UNVERIFIED',rid)
    return out,held


def settle_tick(*,repo,owner_private_pem,private_root,clock=now_utc,max_races=8,
                context=None,days=None,publish=True,source_commit=None):
    """One bounded SP poll. No source lease is opened when nothing is due."""
    need(type(max_races) is int and 1<=max_races<=8,'RESULT_RACE_BOUND')
    public=pipeline.check_owner_private_key(owner_private_pem)
    commit=source_commit or os.environ['GITHUB_SHA']
    need(archive.COMMIT.fullmatch(commit),'RESULT_CODE_IDENTITY')
    owned=context is None;context=context or SettlementContext();context.tick+=1
    context.stores={};context.safe_holds=[]
    _refresh_origin_metadata(context)
    report=dict(state='NO_DUE_ADMITTED_OFFICIAL_ORIGINALS',source_requests=0,provider_denied=False,
        source_unavailable=False,no_provider_tick=True,origin_held=0,settled_races=0,
        published_races=0,publication_acks=0,published_originals=0,original_publication_acks=0,
        published_day_status=0,safe_diagnostics=[],safe_holds=[],updates=None)
    documents=[];before=context.session.count if context.session else 0
    try:
        known=_known_days(repo,clock,context,days)
        _recover_saved_originals(repo,owner_private_pem,context,known,commit,publish,report)
        _recover_saved_results(repo,owner_private_pem,context,known,commit,publish,documents,report)
        pending,held=_pending_originals(repo,owner_private_pem,clock,context,max_races,known)
        report['origin_held']+=held
        if not pending:
            if report['publication_acks'] or report['original_publication_acks']:
                report['state']='OFFICIAL_SP_SAVED_RESULT_UPDATES_PUBLISHED'
            return report
        session=context.ensure(repo=repo,private_root=private_root,owner_private_pem=owner_private_pem,
                               clock=clock,commit=commit)
        report['no_provider_tick']=False;inventories={}
        for item in pending:
            store,original=item['store'],item['original'];day=store.day;rid=original['race_id']
            if session.halted:break
            if day not in inventories:
                prior=[]
                if store.index['registry']:
                    prior=records.replay_registry(store.read(store.index['registry'],owner_private_pem))['registered_race_ids']
                inventories[day]=extension.collect_day_inventory(request=session.request,clock=clock,
                    event_day=day,prior_race_ids=prior)
            inventory=inventories[day]
            if inventory['registry'] is None or session.halted:
                _hold(context,'DAY_RESULT_NAVIGATION','OFFICIAL_DAY_NAVIGATION_UNAVAILABLE',rid)
                break
            stage='OFFICIAL_FINAL_RESULT'
            try:
                capture=sources.collect_final(session=session,inventory=inventory,original=original,clock=clock)
                stage='ORIGINAL_AND_RESULT_COMPARISON'
                raw,adjusted=records.archived_original(store,item['payload'])
                scored=records.compare_result(original=original,payload=item['payload'],raw_baseline=raw,
                    raw_conditioned=adjusted,packets=item['packets'],final_capture=capture)
                previous=store.index['results'].get(rid,[])
                if previous:
                    prior=store.read(previous[-1],owner_private_pem)
                    same=(prior['scored']['official_result']['source_sha256']==scored['official_result']['source_sha256'] and
                          prior['scored']['monetary_comparison_eligible']==scored['monetary_comparison_eligible'])
                    if same:
                        doc=records.replay_saved_result(store,item['meta'],previous[-1],owner_private_pem)
                        documents.append(doc)
                        if publish:
                            stage='RESULT_PUBLICATION'
                            ack=_publish_result(repo,doc,commit,owner_private_pem)
                            report['published_races']+=ack['published_races'];report['publication_acks']+=1
                        context.published_revisions.add((day,rid,previous[-1]['evidence_sha256']))
                        continue
                saved=dict(schema=records.RESULT_SCHEMA,day_jst=day,race_id=rid,
                    producer_run_id=os.environ['GITHUB_RUN_ID'],producer_commit=commit,
                    original_evidence_sha256=item['meta']['evidence_sha256'],origin_packets=item['packets'],
                    final_capture=capture,scored=scored,safe_report=dict(day_jst=day,
                        state='OFFICIAL_SP_RESULT_SCORED',order_comparable_races=1,
                        paired_comparable_races=int(scored['comparison'] is not None)))
                stage='ENCRYPTED_RESULT_ARCHIVE'
                meta=store.append(kind='result',payload=saved,public_pem=public,observed_at=clock(),
                    race_id=rid,monetary_complete=scored['monetary_comparison_eligible'])
                # The encrypted archive/readback precedes every publication.
                doc=records.result_updates(original,scored,capture);documents.append(doc)
                report['settled_races']+=1
                if publish:
                    stage='RESULT_PUBLICATION'
                    ack=_publish_result(repo,doc,commit,owner_private_pem)
                    report['published_races']+=ack['published_races'];report['publication_acks']+=1
                context.published_revisions.add((day,rid,meta['evidence_sha256']))
            except (ValueError,KeyError,TypeError,OSError) as error:
                code=('OFFICIAL_RESULT_NOT_YET_PUBLISHED' if type(error) is sources.SourceError and
                      str(error)=='OFFICIAL_CONTINUATION_RESULT_NOT_PUBLISHED' else 'RESULT_STAGE_VALIDATION_OR_OPERATION_HELD')
                _hold(context,stage,code,rid)
                if session.halted:break
                report['origin_held']+=1
        report['state']='OFFICIAL_SP_RESULT_POLL_COMPLETE'
        if session.halted:report['state']='HOLD_OFFICIAL_SP_PROVIDER_STOP' if session.provider_denied else 'HOLD_OFFICIAL_SP_SOURCE_UNAVAILABLE'
        return report
    except Exception as error:
        report['state']='HOLD_OFFICIAL_SP_RESULT_GATE_OR_SOURCE_FAILED'
        report['source_unavailable']=True
        if isinstance(error, archive.GitCipherFetchTimeout):
            _hold(context, 'RESULT_ARCHIVE_FETCH', 'ENCRYPTED_ARCHIVE_FETCH_TIMEOUT')
        else:
            _hold(context,'RESULT_GATE_OR_SOURCE','CONTINUATION_OR_SAVED_ARCHIVE_UNAVAILABLE')
        return report
    finally:
        if context.session is not None:
            report.update(source_requests=context.session.count-before,provider_denied=context.session.provider_denied,
                source_unavailable=report['source_unavailable'] or context.session.halted and not context.session.provider_denied,
                safe_diagnostics=context.session.safe_diagnostics)
        report['updates']=_join_updates(documents) if documents else None
        report['safe_holds']=context.safe_holds
        if owned:context.close(clock)


def replay_results(*,repo,owner_private_pem,day,source_commit,publish=True):
    """Explicit saved-only path; does not create transport, source lease or model."""
    pipeline.check_owner_private_key(owner_private_pem)
    store=records.RecordStore(repo,day);documents=[];held=0;written=acks=0
    original_count=original_acks=day_status=0
    public_forecasts=None
    if publish:
        try:
            from race_ai.keirin_nationwide_forecast_view import publish_day
            admitted=records.load_admitted_day(repo,owner_private_pem,day)
            original_ack=publish_day(repo,admitted,source_commit,owner_private_pem,
                public_view=day==now_utc().astimezone(form.JST).date().isoformat())
            need(original_ack.get('provider_requests')==0 and original_ack.get('state') in
                ('KEIRIN_NOTE_ENCRYPTED_GIT_READBACK_VERIFIED','EXISTING_NATIONWIDE_DISPLAY_REUSED'),
                'SAVED_ORIGINAL_PUBLICATION_ACK_INVALID')
            original_count=original_ack['published_originals'];day_status=original_ack['published_day_status']
            original_acks=1
            public_forecasts=original_ack.get('public_forecasts')
        except (ValueError,KeyError,TypeError,OSError):held+=1
    for rid,versions in sorted(store.index['results'].items()):
        try:
            doc=records.replay_saved_result(store,store.index['originals'][rid],versions[-1],owner_private_pem)
            documents.append(doc)
            if publish:
                ack=_publish_result(repo,doc,source_commit,owner_private_pem)
                written+=ack['published_races'];acks+=1
        except (ValueError,KeyError,TypeError,OSError):held+=1
    report = dict(state='OFFICIAL_SP_SAVED_RESULTS_REPLAYED',source_requests=0,provider_requests=0,
        published_races=written,publication_acks=acks,results_held=held,
        published_originals=original_count,original_publication_acks=original_acks,published_day_status=day_status,
        updates=_join_updates(documents) if documents else None)
    if public_forecasts is not None:
        report['public_forecasts']=public_forecasts
    return report


def run_settle(*,repo,private_root,owner_public_pem,owner_private_pem,day=None,clock=now_utc,max_races=8):
    repo,root,day,public,commit=_runtime(repo=repo,private_root=private_root,owner_public_pem=owner_public_pem,
        owner_private_pem=owner_private_pem,day=day,clock=clock,mode='settle')
    out=settle_tick(repo=repo,owner_private_pem=owner_private_pem,private_root=root,clock=clock,
                    max_races=max_races,days=[day],source_commit=commit)
    out.pop('updates',None)
    return dict(out,day_jst=day)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('capture','publish','settle'))
    parser.add_argument('--repo',required=True);parser.add_argument('--private-root',required=True)
    parser.add_argument('--owner-public-pem',required=True);parser.add_argument('--report',required=True)
    parser.add_argument('--day');parser.add_argument('--max-races',type=int,default=4)
    args=parser.parse_args(argv);code=0
    try:
        root=capture_files._private_directory(args.private_root)
        target=Path(args.report).absolute();need(target==root/'safe'/'summary.json','SAFE_REPORT_PATH')
        capture_files._private_directory(target.parent)
        options=dict(repo=args.repo,private_root=root,owner_public_pem=args.owner_public_pem,
            owner_private_pem=os.getenv('RACE_AI_KEIRIN_PRIVATE_RSA_PEM','').encode(),day=args.day)
        if args.mode=='capture':
            report=run_capture(**options,max_races=args.max_races)
            if report['state'] == CAPTURE_ARCHIVE_FETCH_HOLD:
                code = 2
        elif args.mode=='publish':report=run_publish(**options)
        else:report=run_settle(**options,max_races=args.max_races)
    except Exception:
        day=args.day or now_utc().astimezone(form.JST).date().isoformat()
        report=_summary(day,'HOLD_OFFICIAL_CONTINUATION_RUNTIME_OR_CONTRACT_FAILED');code=2
    try:
        root=capture_files._private_directory(args.private_root);target=Path(args.report).absolute()
        need(target==root/'safe'/'summary.json','SAFE_REPORT_PATH')
        capture_files._private_directory(target.parent)
        capture_files._save_once(target,history._canonical(report))
    except Exception:
        print('{"state":"HOLD_OFFICIAL_CONTINUATION_SAFE_REPORT_FAILED"}');return 2
    print(json.dumps(report,sort_keys=True));return code


if __name__=='__main__':raise SystemExit(main())
