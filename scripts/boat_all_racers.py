"""Official all-racer intake. Only counts/hashes leave the private process.

Real Actions capture requires the existing owner key before any provider GET.
No fallback key, raw artifact, API crawl, forecast mutation or model training.
"""
import argparse
from datetime import datetime,timedelta,timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.request import Request,build_opener

from race_ai.boat_racer_database import RacerDatabase
from race_ai.actions_contract import stamp
from race_ai.boat_racer_term import term_info
from race_ai.permissioned_source_delivery import NoRedirect
from race_ai.teiai_history import need

TERM='2026-2'
PINNED_ARCHIVE_SHA='5c1e21cfe5a4dd53ea26eb07aca4905c4c20c3160b4a206ba96e92702eb4b46d'
ROOT=Path(__file__).resolve().parents[1]
CODEC=ROOT/'scripts'/'keirin_github_checkpoint.mjs'


def _now():return datetime.now(timezone.utc).isoformat()


def _read(path,limit=4_000_000):
    need(not Path(path).is_symlink(),'BULK_REGULAR_INPUT_REQUIRED')
    with Path(path).open('rb') as stream:raw=stream.read(limit+1)
    need(0<len(raw)<=limit,'BULK_INPUT_SIZE_INVALID');return raw


def _write(path,raw):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    except BaseException:raise


def _key_ready():
    if not os.environ.get('RACE_AI_STATE_KEY'):return False
    code="import {readKey} from './scripts/keirin_github_checkpoint.mjs'; readKey(process.env.RACE_AI_STATE_KEY,'production');"
    proc=subprocess.run(['node','--input-type=module','-e',code],cwd=ROOT,capture_output=True,timeout=10)
    need(proc.returncode==0,'OWNER_STATE_KEY_INVALID_OR_PUBLIC_FIXTURE');return True


def _codec(action,source,target,scope,*,cipher_sha=None):
    env=os.environ.copy()
    if cipher_sha is not None:env['RACE_AI_EXPECTED_CIPHER_SHA256']=cipher_sha
    proc=subprocess.run(['node',str(CODEC),action,str(source),str(target),str(scope)],
                        env=env,capture_output=True,timeout=30)
    need(proc.returncode==0,'BULK_CHECKPOINT_AUTHENTICATION_FAILED')


def _download():
    url=term_info(TERM)['source_url']
    client=build_opener(NoRedirect())
    with client.open(Request(url,headers={'User-Agent':'RACE-AI-owner-personal-all-racer-integrity/1'}),timeout=30) as response:
        need(response.status==200 and response.geturl()==url,'OFFICIAL_BULK_HTTP_REJECTED')
        raw=response.read(4_000_001)
    need(0<len(raw)<=4_000_000 and hashlib.sha256(raw).hexdigest()==PINNED_ARCHIVE_SHA,'OFFICIAL_BULK_SOURCE_REVISION_REVIEW_REQUIRED')
    return raw,_now()


def _personal_term_analysis(url,rights,purpose):
    return url==term_info(TERM)['source_url'] and rights=='OFFICIAL_DOWNLOAD_PERSONAL_RESEARCH' and purpose=='analysis'


def _build(raw,captured_at,*,k_raw=None,k_day=None,k_captured_at=None):
    db=RacerDatabase();source=term_info(TERM)
    db.import_term(raw,term=TERM,source_url=source['source_url'],captured_at=captured_at)
    if k_raw is not None:
        from datetime import date
        from race_ai.official_archive_probe import official_url
        need(k_day is not None,'K_DAY_REQUIRED')
        db.import_results(k_raw,day=k_day,source_url=official_url(date.fromisoformat(k_day),'K'),captured_at=k_captured_at)
    verified=zero_national=zero_course=0
    for (pid,) in db.db.execute('SELECT DISTINCT racer_id FROM racers').fetchall():
        row=db.lookup(pid,as_of=_now(),allow_source=_personal_term_analysis)
        need(row['racer_id']==pid and len(row['courses'])==6,'BULK_RACER_READBACK_MISMATCH');verified+=1
        zero_national+=row['starts']==0
        zero_course+=sum(c['entry_n']==0 for c in row['courses'])
    plain=db.serialize();sha=hashlib.sha256(plain).hexdigest()
    reopened=RacerDatabase.restore(plain,expected_sha256=sha)
    need(reopened.summary()==db.summary(),'BULK_SERIALIZED_POPULATION_MISMATCH')
    report=dict(status='ALL_PUBLISHED_TERM_RACERS_LOADED_PRIVATE_MEMORY',term=TERM,
        scope='ALL_RECORDS_IN_PUBLISHED_TERM_FILE_NOT_ALL_CAREERS_OR_ACTIVE_REGISTRY',
        period_start=source['period_start'],period_end=source['period_end'],source_url=source['source_url'],
        source_archive_sha256=hashlib.sha256(raw).hexdigest(),source_captured_at=captured_at,
        checked_at=_now(),population=db.summary(),lookup_verified_racers=verified,
        zero_national_sample_racers=zero_national,zero_course_sample_rows=zero_course,
        sqlite_bytes=len(plain),sqlite_sha256=sha,serialized_readback_verified=True,
        durable_encrypted_storage_verified=False,forward_race_verified=False,
        formal_backtest_eligible=False,production_promoted=False,raw_or_plaintext_published=False)
    return plain,report


def inspect_files(term_path,*,k_path=None,k_day=None):
    raw=_read(term_path);captured=datetime.fromtimestamp(Path(term_path).stat().st_mtime,timezone.utc).isoformat()
    extra={}
    if k_path is not None:
        extra=dict(k_raw=_read(k_path),k_day=k_day,k_captured_at=datetime.fromtimestamp(Path(k_path).stat().st_mtime,timezone.utc).isoformat())
    _,report=_build(raw,captured,**extra);return report


def capture(out,*,reuse_dir=None):
    out=Path(out);out.mkdir(mode=0o700,parents=True,exist_ok=True)
    need(not any(out.iterdir()),'BULK_OUTPUT_EXISTS_DO_NOT_RESET')
    if not _key_ready():
        report=dict(status='HOLD_OWNER_STATE_KEY_MISSING',upstream_gets=0,encrypted_checkpoint_created=False,
                    durable_encrypted_storage_verified=False,raw_or_plaintext_published=False)
    elif reuse_dir is not None and any(Path(reuse_dir).glob('*')):
        previous=json.loads(_read(Path(reuse_dir)/'summary.json',64_000))
        need(stamp(previous['source_captured_at'])+timedelta(days=7)>stamp(_now()),'BULK_CACHE_RETENTION_REVIEW_REQUIRED')
        restore_checkpoint(reuse_dir) # authenticate before any reuse; invalid cache never resets
        _write(out/'racers.checkpoint',_read(Path(reuse_dir)/'racers.checkpoint',12*1024*1024))
        report=dict(previous,status='VERIFIED_ENCRYPTED_ALL_RACERS_CACHE_REUSED',upstream_gets=0,
                    encrypted_checkpoint_created=True,durable_encrypted_storage_verified=False,checked_at=_now())
    else:
        raw,captured=_download();plain,report=_build(raw,captured)
        scope=dict(schema='RACE_AI_GITHUB_SQLITE_V1',repository_id='1416489937',mode='production',generation=1,previous_cipher_sha256=None)
        with tempfile.TemporaryDirectory(prefix='race-ai-owner-bulk-') as folder:
            p=Path(folder);_write(p/'private.sqlite',plain);_write(p/'scope.json',json.dumps(scope).encode())
            _codec('seal',p/'private.sqlite',out/'racers.checkpoint',p/'scope.json')
        cipher=_read(out/'racers.checkpoint',12*1024*1024)
        report.update(status='ENCRYPTED_ALL_RACERS_CHECKPOINT_CREATED',scope=scope,upstream_gets=1,
                      encrypted_checkpoint_created=True,ciphertext_sha256=hashlib.sha256(cipher).hexdigest())
    _write(out/'summary.json',json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2).encode())
    return report


def restore_checkpoint(folder):
    folder=Path(folder);report=json.loads(_read(folder/'summary.json',64_000))
    scope=report.get('scope')
    need(type(scope) is dict and scope.get('mode')=='production','REAL_BULK_RESTORE_REQUIRES_OWNER_PRODUCTION_KEY')
    need(_key_ready(),'OWNER_STATE_KEY_REQUIRED')
    cipher=_read(folder/'racers.checkpoint',12*1024*1024)
    sha=hashlib.sha256(cipher).hexdigest();need(sha==report['ciphertext_sha256'],'BULK_CIPHERTEXT_SHA_MISMATCH')
    with tempfile.TemporaryDirectory(prefix='race-ai-owner-readback-') as temp:
        p=Path(temp);_write(p/'scope.json',json.dumps(scope).encode())
        _codec('unseal',folder/'racers.checkpoint',p/'private.sqlite',p/'scope.json',cipher_sha=sha)
        raw=_read(p/'private.sqlite',8*1024*1024)
        db=RacerDatabase.restore(raw,expected_sha256=report['sqlite_sha256'])
        need(db.summary()==report['population'],'BULK_RESTORED_POPULATION_MISMATCH')
        sources=db.db.execute('SELECT sha,captured_at FROM sources WHERE kind="TERM"').fetchall()
        need(sources==[(PINNED_ARCHIVE_SHA,report['source_captured_at'])],'BULK_RESTORED_SOURCE_NOT_PINNED')
        count=0
        for (pid,) in db.db.execute('SELECT racer_id FROM racers').fetchall():
            need(db.lookup(pid,as_of=_now(),allow_source=_personal_term_analysis) is not None,'BULK_RESTORED_RACER_MISSING');count+=1
    return dict(status='ENCRYPTED_ALL_RACERS_READBACK_VERIFIED',population=db.summary(),lookup_verified_racers=count,
                durable_encrypted_storage_verified=True,ciphertext_sha256=sha,formal_backtest_eligible=False,
                forward_race_verified=False,production_promoted=False,raw_or_plaintext_published=False)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    inspect=sub.add_parser('inspect');inspect.add_argument('--term-archive',required=True);inspect.add_argument('--k-archive');inspect.add_argument('--k-day')
    cap=sub.add_parser('capture');cap.add_argument('--out-dir',required=True);cap.add_argument('--reuse-dir')
    read=sub.add_parser('restore');read.add_argument('--folder',required=True)
    args=p.parse_args(argv)
    if args.action=='inspect':report=inspect_files(args.term_archive,k_path=args.k_archive,k_day=args.k_day)
    elif args.action=='capture':report=capture(args.out_dir,reuse_dir=args.reuse_dir)
    else:report=restore_checkpoint(args.folder)
    print(json.dumps(report,ensure_ascii=False,sort_keys=True))
    return report


if __name__=='__main__':main()
