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


def cycle(repo,*,recipient=None,store=None,collector=None,clock=None,source_commit=None):
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
        root=Path(folder);root.chmod(0o700)
        collected=collector(day_jst=day,private_root=root,clock=clock,
            already_captured_ids=prior['covered_race_ids'],
            priority_captured_ids=prior['priority_window_race_ids'],
            model_source_commit=source_commit)
        safe=collected['safe_report']
        need(type(safe.get('provider_denied')) is bool,'CAPTURE_REPORT')
        if safe.get('selected_races')==0 and not safe['provider_denied']:
            return dict(state='NOTE_NO_NEW_ELIGIBLE_RESEARCH_INPUTS',acquisition=safe,
                provider_requests=safe.get('public_page_requests'),entries=len(prior['entries']))
        try:
            note=import_site(Path(collected['site_root']),source_commit=source_commit,clock=clock)
            note.update(scope='OWNER_MATCHED_SOURCE_RESEARCH_REFRESH',source_site=None,
                source_profile='owner-imported-kdreams-netkeirin-20261120',
                actual_four_model_forecast_saved=False)
            note=attach_archive(note,'source-inputs.tar.gz',source_archive(root))
            sealed=seal_snapshot(note,recipient,kind='research',
                captured_ids=safe['captured_race_ids'],priority_ids=safe['priority_window_race_ids'],clock=clock)
            result=publish_snapshot(store,recipient,sealed,expected_parent=parent,denied=safe['provider_denied'])
            result['acquisition']=safe
            return result
        except Exception:
            if safe['provider_denied']:
                latch_denial(store,recipient)
            raise


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
