"""Run the imported input profile inside an existing GitHub Actions run body."""
from contextlib import contextmanager
from datetime import datetime,timezone
import argparse
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from race_ai.keirin_note_feed import (NoteFeedGit,checked_recipient,load_index,
    seal_snapshot,publish_snapshot,result_clock,need,REPO)
from race_ai.keirin_note_view import import_site,attach_archive,MAX_VIEW


_CONCURRENT_UPDATE = 'KEIRIN_NOTE_FEED_CONCURRENT_UPDATE'
_MOVED_READBACK = 'KEIRIN_NOTE_FEED_REMOTE_READBACK'
_MAX_PUBLISH_ATTEMPTS = 3
_FAILURES = (ValueError, KeyError, TypeError, OSError, RuntimeError, subprocess.SubprocessError)
_SECONDARY_CONTEXT_HOLD = 'HOLD_PUBLIC_RIDER_CONTEXT_SECONDARY'
_SECONDARY_CONTEXT_STATES = frozenset({
    'PUBLIC_RIDER_CONTEXT_SECONDARY_UPDATED', 'PUBLIC_RIDER_CONTEXT_SECONDARY_UNCHANGED',
    'PUBLIC_RIDER_CONTEXT_SECONDARY_NO_QUALIFYING_ROWS',
})
_SECONDARY_CONTEXT_COUNTS = (
    'registered_races', 'verified_races', 'registered_riders', 'verified_riders',
    'comments_confirmed', 'comments_held', 'comments_missing',
)
_SAFE_REASONS = frozenset({
    'CAPTURE_REPORT', 'RESULT_REPORT',
    'GIT_OPERATION_FAILED', 'CONCURRENT_UPDATE', 'REMOTE_READBACK',
    'PARENT_NOT_FAST_FORWARD', 'RETAINED_HISTORY_CHANGED', 'RESULT_PREDECESSOR_CHANGED',
    'FORECAST_COVERAGE_CHANGED',
    'PREVIOUS_PROVIDER_DENIAL_NO_RETRY', 'INDEX_TREE_MISMATCH', 'RETAINED_CIPHERTEXT_SHA',
    'RESULT_CHECK_CLOCK_BACKWARD_OR_CONFLICT', 'RESULT_HISTORY_MISSING_NO_RESET',
    'RESULT_OBSERVATION_BINDING', 'SOURCE_ARCHIVE_BOUND', 'VIEW_BOUND', 'PLAIN_BOUND',
})


class FeedCycleFailure(ValueError):
    def __init__(self, stage, reason):
        super().__init__(reason)
        self.stage = stage
        self.reason = reason


@contextmanager
def _phase(stage):
    try:
        yield
    except FeedCycleFailure:
        raise
    except _FAILURES as error:
        failed_operation = isinstance(error, (OSError, RuntimeError, subprocess.SubprocessError))
        reason = 'OPERATION_FAILED' if failed_operation else 'INVALID_DATA'
        if type(error) is ValueError:
            code = str(error).removeprefix('KEIRIN_NOTE_FEED_').removeprefix('KEIRIN_NOTE_')
            if code in _SAFE_REASONS:
                reason = code
        raise FeedCycleFailure(stage, reason) from None


def _publish_collected(store, recipient, snapshot, *, parent, prior, denied, result_checks=None):
    """Recover only a proven concurrent append, using already collected bytes."""
    for attempt in range(1, _MAX_PUBLISH_ATTEMPTS + 1):
        try:
            return publish_snapshot(store, recipient, snapshot, expected_parent=parent,
                                    denied=denied, result_checks=result_checks)
        except ValueError as error:
            if type(error) is not ValueError:
                raise
            code = str(error)
            if code not in (_CONCURRENT_UPDATE, _MOVED_READBACK):
                raise
            latest = store.head()
            if latest is None or latest == parent:
                raise

            current = load_index(store, recipient, latest)
            try:
                store.run(['merge-base', '--is-ancestor', parent, latest])
            except ValueError:
                raise ValueError('KEIRIN_NOTE_FEED_PARENT_NOT_FAST_FORWARD') from None
            need(current['entries'][:len(prior['entries'])] == prior['entries'] and
                 (not prior['provider_denied'] or current['provider_denied']), 'RETAINED_HISTORY_CHANGED')

            old_checks = prior.get('result_checks', {})
            current_checks = current.get('result_checks', {})
            need(all(rid in current_checks and (row == current_checks[rid] or
                     result_clock(row['checked_at']) < result_clock(current_checks[rid]['checked_at']))
                     for rid, row in old_checks.items()), 'RETAINED_HISTORY_CHANGED')

            checks = result_checks or {}
            if ((snapshot is None or snapshot['entry'] in current['entries'])
                    and all(current_checks.get(rid) == row for rid, row in checks.items())
                    and (not denied or current['provider_denied'])):
                # The exact entry and its checks are already public on a descendant.
                return dict(state='KEIRIN_NOTE_ENCRYPTED_GIT_READBACK_VERIFIED',
                            source_commit=latest, entries=len(current['entries']),
                            provider_denied=current['provider_denied'],
                            covered_races=len(current['covered_race_ids']),
                            priority_window_races=len(current['priority_window_race_ids']),
                            private_plaintext_uploaded=False, production_state_key_used=False)
            if code != _CONCURRENT_UPDATE or attempt == _MAX_PUBLISH_ATTEMPTS:
                raise
            need(not current['provider_denied'], 'PREVIOUS_PROVIDER_DENIAL_NO_RETRY')
            entry = snapshot['entry'] if snapshot is not None else None
            if entry is not None and entry['kind'] == 'research':
                added_entries = current['entries'][len(prior['entries']):]
                captured = set(entry['captured_race_ids'])
                days = set(entry['days'])
                need(not any(other['kind'] == 'research' and
                             (captured.intersection(other['captured_race_ids']) if captured else
                              days.intersection(other['days'])) for other in added_entries),
                     'FORECAST_COVERAGE_CHANGED')
            need(all(current_checks.get(rid) == old_checks.get(rid) for rid in checks),
                 'RESULT_PREDECESSOR_CHANGED')
            parent = latest


def source_archive(root):
    """Compress original private bytes; the result enters only an AES envelope."""
    root=Path(root);buffer=io.BytesIO()
    with tarfile.open(fileobj=buffer,mode='w:gz') as archive:
        for path in sorted(root.rglob('*')):
            need(not path.is_symlink(),'PRIVATE_SOURCE_SYMLINK')
            if path.is_file():
                need(path.stat().st_size<=MAX_VIEW,'PRIVATE_SOURCE_BOUND')
                archive.add(path,arcname=path.relative_to(root),recursive=False)
    raw=buffer.getvalue();need(len(raw)<=MAX_VIEW,'SOURCE_ARCHIVE_BOUND');return raw


def private_denial(root,safe=None):
    """Read the existing private stop before a failed temporary root is removed."""
    if safe is not None and safe.get('provider_denied') is True:return True
    marker=Path(root)/'raw/provider-denial-stop.json'
    return marker.is_file() and not marker.is_symlink() and json.loads(marker.read_bytes()).get(
        'state')=='HOLD_PROVIDER_DENIED_OR_RATE_LIMITED_STOP'


def _publish_reference_projection(repo,note,entry,*,published_at):
    from race_ai import keirin_public_forecasts
    try:
        public=keirin_public_forecasts.project_reference(note,entry,published_at=published_at)
        if not public['races']:
            return {'state':'NO_PRE_CUTOFF_PUBLIC_REFERENCES'}
        return keirin_public_forecasts.publish_reference(repo,public)
    except _FAILURES:
        return {'state':'HOLD_PUBLIC_REFERENCE_FORECASTS'}


def _publish_secondary_context_projection(repo,root,note,entry,*,published_at):
    from scripts.keirin_publish_secondary_context import publish_saved_reference

    return publish_saved_reference(repo,root,note,entry,published_at=published_at)


def _secondary_context_receipt(receipt):
    state = receipt['state']
    provider_requests=receipt.get('provider_requests')
    if state not in _SECONDARY_CONTEXT_STATES or type(provider_requests) is not int or provider_requests != 0:
        return {'state':_SECONDARY_CONTEXT_HOLD}
    safe = dict(state=state, provider_requests=0)
    commit = receipt.get('commit')
    if isinstance(commit,str) and re.fullmatch('[0-9a-f]{40}',commit):
        safe['commit'] = commit
    coverage = receipt.get('coverage',{})
    safe['coverage'] = {key:coverage[key] for key in _SECONDARY_CONTEXT_COUNTS
                        if type(coverage.get(key)) is int and coverage[key] >= 0}
    return safe


def cycle(repo,*,recipient=None,store=None,collector=None,result_collector=None,clock=None,source_commit=None,
          reference_publisher=None,odds_stager=None,secondary_context_publisher=None):
    with _phase('OWNER_FEED_READ'):
        repo=Path(repo).resolve();store=store or NoteFeedGit(repo)
        recipient=checked_recipient(recipient or json.loads(
            (repo/'config/keirin-note-recipient.json').read_bytes()))
        parent=store.head();prior=load_index(store,recipient,parent)
    if prior is None:
        return dict(state='HOLD_NOTE_OWNER_SEED_REQUIRED',provider_requests=0)
    if prior['provider_denied']:
        return dict(state='HOLD_NOTE_PREVIOUS_PROVIDER_DENIAL_NO_RETRY',provider_requests=0)
    clock=clock or (lambda:datetime.now(timezone.utc))
    now=clock();need(isinstance(now,datetime) and now.utcoffset() is not None,'CLOCK')
    day=now.astimezone(ZoneInfo('Asia/Tokyo')).date().isoformat()
    if collector is None:
        from scripts.keirin_note_collect_inputs import collect_day
        collector=collect_day
    source_commit=source_commit or subprocess.check_output(
        ['git','rev-parse','HEAD'],cwd=repo).decode().strip()
    with TemporaryDirectory(prefix='keirin-note-input-') as folder:
        root=Path(folder);root.chmod(0o700);safe=None
        try:
            with _phase('FORECAST_COLLECTION'):
                collected=collector(day_jst=day,private_root=root,clock=clock,
                    already_captured_ids=prior['covered_race_ids'],
                    priority_captured_ids=prior['priority_window_race_ids'],
                    model_source_commit=source_commit)
                safe=collected['safe_report']
                need(type(safe.get('provider_denied')) is bool,'CAPTURE_REPORT')
            result=dict(state='NOTE_NO_NEW_ELIGIBLE_RESEARCH_INPUTS',acquisition=safe,
                    provider_requests=safe.get('public_page_requests'),entries=len(prior['entries']))
            # Preserve the first collector observation of each JST day even
            # without eligible forecasts. Repeated empty ticks still perform
            # the existing result checks below, without duplicate ciphertext.
            day_recorded=any(entry['kind']=='research' and day in entry['days']
                             for entry in prior['entries'])
            if safe.get('selected_races')!=0 or safe['provider_denied'] or not day_recorded:
                with _phase('FORECAST_PACKAGING'):
                    note=import_site(Path(collected['site_root']),source_commit=source_commit,clock=clock)
                    note.update(scope='OWNER_MATCHED_SOURCE_RESEARCH_REFRESH',source_site=None,
                        source_profile='owner-imported-kdreams-netkeirin-20261120',
                        actual_four_model_forecast_saved=False)
                    note=attach_archive(note,'source-inputs.tar.gz',source_archive(root))
                    sealed=seal_snapshot(note,recipient,kind='research',
                        captured_ids=safe['captured_race_ids'],priority_ids=safe['priority_window_race_ids'],clock=clock)
                with _phase('FORECAST_PUBLICATION'):
                    result=_publish_collected(store,recipient,sealed,parent=parent,prior=prior,
                                              denied=safe['provider_denied'])
                result['acquisition']=safe
                verified_capture = (safe['captured_race_ids'] and not safe['provider_denied'] and
                                    result['state']=='KEIRIN_NOTE_ENCRYPTED_GIT_READBACK_VERIFIED')
                if reference_publisher is not None and verified_capture:
                    result['public_reference']=reference_publisher(repo,note,sealed['entry'],published_at=clock())
                if odds_stager is not None and verified_capture:
                    try:
                        result['public_odds_handoff']=odds_stager(root,note,sealed['entry'])
                    except (_FAILURES + (ImportError,)):
                        result['public_odds_handoff']={'state':'HOLD_PUBLIC_ODDS_HANDOFF'}
                if (secondary_context_publisher is not None and verified_capture
                        and not result.get('provider_denied')):
                    try:
                        published = secondary_context_publisher(repo,root,note,sealed['entry'],published_at=clock())
                        result['public_rider_context_secondary'] = _secondary_context_receipt(published)
                    except Exception:
                        # A supplemental projection must never stop original or result processing.
                        result['public_rider_context_secondary'] = {'state':_SECONDARY_CONTEXT_HOLD}
        except Exception:
            with _phase('PROVIDER_STOP_PERSISTENCE'):
                if private_denial(root,safe):latch_denial(store,recipient)
            raise
    if safe['provider_denied']:return result
    # Publish pre-cutoff output FIRST. Historical result work uses a distinct
    # temporary root and refreshed CAS parent, including no-new-input ticks.
    if result_collector is None:
        from scripts.keirin_note_collect_results import collect_results
        result_collector=collect_results
    with _phase('RESULT_HISTORY'):
        parent=store.head();prior=load_index(store,recipient,parent)
        need(prior is not None,'RESULT_HISTORY_MISSING_NO_RESET')
    if prior['provider_denied']:return dict(result,results=dict(
        state='HOLD_NOTE_PREVIOUS_PROVIDER_DENIAL_NO_RETRY',provider_requests=0))
    days=sorted({day for entry in prior['entries'] for day in entry['days']})
    with TemporaryDirectory(prefix='keirin-note-results-') as folder:
        root=Path(folder);root.chmod(0o700);safe_results=None
        try:
            with _phase('RESULT_COLLECTION'):
                collected=result_collector(days=days,private_root=root,clock=clock,
                    result_checks=prior.get('result_checks',{}))
                safe_results=collected['safe_report']
                need(type(safe_results.get('provider_denied')) is bool and
                    type(safe_results.get('changed_observations')) is int and
                    safe_results['changed_observations']>=0,'RESULT_REPORT')
                checks=collected['result_checks']
            with _phase('RESULT_PACKAGING'):
                sealed=None
                if safe_results['changed_observations']:
                    note=import_site(Path(collected['site_root']),source_commit=source_commit,clock=clock)
                    validate_result_delta(note,checks,prior.get('result_checks',{}),
                        safe_results['changed_observations'])
                    note.update(scope='OWNER_SECONDARY_RESEARCH_RESULT_OBSERVATIONS',source_site=None,
                        source_profile='owner-imported-kdreams-netkeirin-20261120',
                        actual_four_model_forecast_saved=False)
                    note=attach_archive(note,'result-sources.tar.gz',source_archive(root))
                    sealed=seal_snapshot(note,recipient,kind='results',clock=clock)
                else:
                    need(all(rid in prior.get('result_checks',{}) and
                        row['digest']==prior['result_checks'][rid]['digest'] and
                        row['status']==prior['result_checks'][rid]['status'] for rid,row in checks.items()),
                        'RESULT_FACT_CHANGE_WITHOUT_PRIVATE_DELTA')
            if sealed is not None or checks or safe_results['provider_denied']:
                with _phase('RESULT_PUBLICATION'):
                    published=_publish_collected(store,recipient,sealed,parent=parent,prior=prior,
                        denied=safe_results['provider_denied'],result_checks=checks)
                result.update(published)
            result['results']=safe_results
            return result
        except Exception:
            # Keep a real denial even if import, encryption, or publication
            # fails. The original private marker contains no source values.
            with _phase('PROVIDER_STOP_PERSISTENCE'):
                if private_denial(root,safe_results):latch_denial(store,recipient)
            raise


def validate_result_delta(note,checks,prior,expected_count):
    """Bind public progress to the new private facts before either is written."""
    from scripts.keirin_note_collect_results import SCHEMA,checked_observation,_status
    from race_ai.keirin_note_feed import checked_result_checks
    checked_result_checks(checks);seen=set()
    for path,entry in note['files'].items():
        need(path.endswith('/research_results.json'),'RESULT_ONLY_PACKET')
        data=json.loads(entry['text'])
        need(type(data) is dict and set(data)=={'schema','day_jst','observations'} and
             data['schema']==SCHEMA and path=='data/'+data['day_jst']+'/research_results.json' and
             type(data['observations']) is list,'RESULT_DELTA_SCHEMA')
        for row in data['observations']:
            checked_observation(row)
            rid=row['race_id'];old=prior.get(rid)
            need(rid not in seen and rid[:8]==data['day_jst'].replace('-','') and rid in checks,
                 'RESULT_OBSERVATION_ID')
            seen.add(rid);result_clock(row['captured_at'])
            need(row['observation_sha256']==checks[rid]['digest'] and
                 row['captured_at']==checks[rid]['checked_at'] and _status(row)==checks[rid]['status'] and
                 row['previous_observation_sha256']==(old['digest'] if old else None),
                 'RESULT_OBSERVATION_BINDING')
    changed={rid for rid,row in checks.items() if rid not in prior or
        row['digest']!=prior[rid]['digest'] or row['status']!=prior[rid]['status']}
    need(seen==changed and len(seen)==expected_count,'RESULT_DELTA_COUNT')


def latch_denial(store,recipient):
    """Save the control-only stop even if private source packaging failed."""
    for attempt in range(3):
        parent=store.head();prior=load_index(store,recipient,parent)
        need(prior is not None,'MISSING_SEED_DURING_DENIAL')
        if prior['provider_denied']:return
        try:
            publish_snapshot(store,recipient,expected_parent=parent,denied=True)
            return
        except ValueError:
            # Retry only a changed Git parent; never another provider request.
            if store.head()==parent or attempt==2:raise


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--repo',required=True)
    parser.add_argument('--publish-reference',action='store_true')
    parser.add_argument('--odds-handoff',type=Path)
    args=parser.parse_args(argv)
    # This new source profile never grants production-state access or executes
    # code from untrusted PRs. No new workflow trigger/permission is required.
    need(os.getenv('GITHUB_REPOSITORY')==REPO and os.getenv('GITHUB_REF')=='refs/heads/main'
         and os.getenv('GITHUB_EVENT_NAME') in {'schedule','workflow_dispatch'},'TRUSTED_MAIN_EVENT')
    need(args.odds_handoff is None or args.publish_reference,'PUBLIC_ODDS_TRUSTED_REFERENCE_RUN_REQUIRED')
    if args.publish_reference:
        need(os.getenv('GITHUB_ACTIONS')=='true' and
             os.getenv('GITHUB_REPOSITORY_ID')=='1416489937' and
             os.getenv('GITHUB_WORKFLOW_REF')=='haji84/RACE-AI/.github/workflows/keirin-pr71-owner-autonomous.yml@refs/heads/main' and
             os.getenv('GITHUB_JOB')=='github-hosted-pr71-cycle','PUBLIC_REFERENCE_TRUSTED_MAIN_RUN')
        checked_out=subprocess.check_output(['git','rev-parse','HEAD'],cwd=args.repo).decode().strip()
        need(os.getenv('GITHUB_SHA')==checked_out,'PUBLIC_REFERENCE_TRUSTED_CHECKOUT')
    try:
        with _phase('RUN_CONTEXT'):
            callbacks={}
            if args.publish_reference:
                callbacks['reference_publisher']=_publish_reference_projection
                callbacks['secondary_context_publisher']=_publish_secondary_context_projection
            if args.odds_handoff is not None:
                def stage(root,note,entry):
                    from scripts.keirin_publish_forecast_odds import stage_reference_handoff

                    return stage_reference_handoff(root,note,entry,args.odds_handoff)
                callbacks['odds_stager']=stage
            result=cycle(args.repo,**callbacks)
            print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    except FeedCycleFailure as error:
        print(json.dumps(dict(state='HOLD_NOTE_SOURCE_OR_ENCRYPTED_PUBLICATION',
                              failure_stage=error.stage,failure_reason=error.reason),sort_keys=True))
        return 2
    return 0


if __name__=='__main__':raise SystemExit(main())
