"""Run the imported input profile inside an existing GitHub Actions run body."""
from datetime import datetime,timezone
import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from race_ai.keirin_note_feed import (NoteFeedGit,checked_recipient,load_index,
    seal_snapshot,publish_snapshot,need,REPO)
from race_ai.keirin_note_view import import_site,attach_archive,MAX_VIEW


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


def cycle(repo,*,recipient=None,store=None,collector=None,result_collector=None,clock=None,source_commit=None):
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
                note=import_site(Path(collected['site_root']),source_commit=source_commit,clock=clock)
                note.update(scope='OWNER_MATCHED_SOURCE_RESEARCH_REFRESH',source_site=None,
                    source_profile='owner-imported-kdreams-netkeirin-20261120',
                    actual_four_model_forecast_saved=False)
                note=attach_archive(note,'source-inputs.tar.gz',source_archive(root))
                sealed=seal_snapshot(note,recipient,kind='research',
                    captured_ids=safe['captured_race_ids'],priority_ids=safe['priority_window_race_ids'],clock=clock)
                result=publish_snapshot(store,recipient,sealed,expected_parent=parent,denied=safe['provider_denied'])
                result['acquisition']=safe
        except Exception:
            if private_denial(root,safe):latch_denial(store,recipient)
            raise
    if safe['provider_denied']:return result
    # Publish pre-cutoff output FIRST. Historical result work uses a distinct
    # temporary root and refreshed CAS parent, including no-new-input ticks.
    if result_collector is None:
        from scripts.keirin_note_collect_results import collect_results
        result_collector=collect_results
    parent=store.head();prior=load_index(store,recipient,parent)
    need(prior is not None,'RESULT_HISTORY_MISSING_NO_RESET')
    if prior['provider_denied']:return dict(result,results=dict(
        state='HOLD_NOTE_PREVIOUS_PROVIDER_DENIAL_NO_RETRY',provider_requests=0))
    days=sorted({day for entry in prior['entries'] for day in entry['days']})
    with TemporaryDirectory(prefix='keirin-note-results-') as folder:
        root=Path(folder);root.chmod(0o700);safe_results=None
        try:
            collected=result_collector(days=days,private_root=root,clock=clock,
                result_checks=prior.get('result_checks',{}))
            safe_results=collected['safe_report']
            need(type(safe_results.get('provider_denied')) is bool and
                type(safe_results.get('changed_observations')) is int and
                safe_results['changed_observations']>=0,'RESULT_REPORT')
            checks=collected['result_checks'];sealed=None
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
                published=publish_snapshot(store,recipient,sealed,expected_parent=parent,
                    denied=safe_results['provider_denied'],result_checks=checks)
                result.update(published)
            result['results']=safe_results
            return result
        except Exception:
            # Keep a real denial even if import, encryption, or publication
            # fails. The original private marker contains no source values.
            if private_denial(root,safe_results):latch_denial(store,recipient)
            raise


def validate_result_delta(note,checks,prior,expected_count):
    """Bind public progress to the new private facts before either is written."""
    from scripts.keirin_note_collect_results import SCHEMA,checked_observation,_status
    from race_ai.keirin_note_feed import checked_result_checks,result_clock
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
    args=parser.parse_args(argv)
    # This new source profile never grants production-state access or executes
    # code from untrusted PRs. No new workflow trigger/permission is required.
    need(os.getenv('GITHUB_REPOSITORY')==REPO and os.getenv('GITHUB_REF')=='refs/heads/main'
         and os.getenv('GITHUB_EVENT_NAME') in {'schedule','workflow_dispatch'},'TRUSTED_MAIN_EVENT')
    try:
        result=cycle(args.repo)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True))
        return 0
    except (ValueError,KeyError,TypeError,OSError,RuntimeError):
        print('{"state":"HOLD_NOTE_SOURCE_OR_ENCRYPTED_PUBLICATION"}')
        return 2


if __name__=='__main__':raise SystemExit(main())
