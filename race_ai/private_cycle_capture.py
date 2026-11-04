"""Read selected original GitHub artifacts into a fresh private directory.

No provider scraping, workflow dispatch, inference, credential extraction or
publication. API access uses the inherited gh authentication/proxy/TLS route.
Selected artifacts are not proof of complete daily history or source rights.
"""
from datetime import date, datetime
from hashlib import sha256
import argparse
import io
import json
import os
from pathlib import Path
import re
import selectors
import stat
import subprocess
import sys
import time
import zipfile
from contextlib import contextmanager

from .frozen_day_cycle import read_p0, read_p1
from .cycle_recovery import result_archive, p0_original_or_empty
from .repeated_cycle import matches

REPO='haji84/RACE-AI'
REPOSITORY_ID=1416489937
MAX_ZIP=32*1024*1024
MAX_METADATA=1024*1024
MAX_TOTAL=256*1024*1024
HEX=re.compile(r'^[a-f0-9]{64}$')


class CaptureError(ValueError):
    pass


def need(ok, reason):
    if not ok: raise CaptureError(reason)


def _output_path(value):
    p=Path(value).expanduser()
    need(p.is_absolute() and not p.exists() and not p.is_symlink(), 'NEW_PRIVATE_OUTPUT_REQUIRED')
    need(p.parent.is_dir(), 'PRIVATE_PARENT_REQUIRED')
    for parent in p.parents:
        need(not parent.is_symlink() and not os.path.lexists(parent/'.git'), 'PRIVATE_OUTPUT_OUTSIDE_GIT_REQUIRED')
    mode=p.parent.stat().st_mode
    need(not mode & 0o022 or mode & stat.S_ISVTX, 'PRIVATE_PARENT_IS_UNPROTECTED')
    return p


@contextmanager
def _parent_handle(parent):
    """Walk without following links and bind subsequent writes to the directory."""
    parent=Path(parent)
    need(parent.is_absolute() and '..' not in parent.parts,'PRIVATE_PARENT_REQUIRED')
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for part in parent.parts[1:]:
            try: os.stat('.git',dir_fd=fd,follow_symlinks=False)
            except FileNotFoundError: pass
            else: raise CaptureError('PRIVATE_OUTPUT_OUTSIDE_GIT_REQUIRED')
            next_fd=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd);fd=next_fd
        try: os.stat('.git',dir_fd=fd,follow_symlinks=False)
        except FileNotFoundError: pass
        else: raise CaptureError('PRIVATE_OUTPUT_OUTSIDE_GIT_REQUIRED')
        current=os.fstat(fd)
        need(current.st_uid==os.getuid() or current.st_mode & stat.S_ISVTX,
             'PRIVATE_PARENT_OWNER_REQUIRED')
        need(not current.st_mode & 0o022 or current.st_mode & stat.S_ISVTX,
             'PRIVATE_PARENT_IS_UNPROTECTED')
        yield fd
    finally:
        os.close(fd)


def _unique(pairs):
    result={}
    for key,value in pairs:
        need(key not in result,'DUPLICATE_METADATA_KEY');result[key]=value
    return result


def _gh_get(endpoint):
    need(re.fullmatch(r'actions/artifacts/[1-9][0-9]*(?:/zip)?',endpoint) is not None,
         'ARTIFACT_ENDPOINT_REQUIRED')
    limit=MAX_ZIP if endpoint.endswith('/zip') else MAX_METADATA
    process=None
    try:
        process=subprocess.Popen(['gh','api',f'repos/{REPO}/{endpoint}'],stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL)
        data=bytearray();deadline=time.monotonic()+50
        with selectors.DefaultSelector() as select:
            select.register(process.stdout,selectors.EVENT_READ)
            done=False
            while not done:
                remaining=deadline-time.monotonic()
                need(remaining>0,'GITHUB_ARTIFACT_READ_UNAVAILABLE')
                for key,_ in select.select(min(remaining,1)):
                    chunk=os.read(key.fd,65536)
                    if not chunk: done=True;break
                    data.extend(chunk)
                    need(len(data)<=limit,'ARTIFACT_READ_TOO_LARGE')
        need(process.wait(timeout=max(0.01,deadline-time.monotonic()))==0,
             'GITHUB_ARTIFACT_READ_UNAVAILABLE')
        return bytes(data)
    except (OSError,subprocess.SubprocessError) as exc:
        raise CaptureError('GITHUB_ARTIFACT_READ_UNAVAILABLE') from None
    finally:
        if process is not None:
            if process.poll() is None: process.kill()
            process.wait()
            if process.stdout: process.stdout.close()


def _read(get, endpoint, bound):
    try: raw=get(endpoint)
    except (OSError,ValueError,subprocess.SubprocessError):
        raise CaptureError('GITHUB_ARTIFACT_READ_UNAVAILABLE') from None
    need(isinstance(raw,bytes) and 0<len(raw)<=bound,'BOUNDED_ARTIFACT_READ_REQUIRED')
    return raw


def _write_at(parent_fd, name, raw):
    need(Path(name).name==name and name not in ('.','..'),'PRIVATE_FILENAME_REQUIRED')
    fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent_fd)
    with os.fdopen(fd,'wb') as stream:
        stream.write(raw);stream.flush();os.fsync(stream.fileno())


def _private_write(path, raw):
    path=Path(path)
    with _parent_handle(path.parent) as parent_fd:
        _write_at(parent_fd,path.name,raw)


def capture_artifacts(day, artifact_ids, output_dir, *, github_get=None, expected_zip_sha256=None):
    """Capture exact bytes and a pinned local manifest; never reset prior state."""
    try: parsed_day=date.fromisoformat(day)
    except (ValueError,TypeError): raise CaptureError('CANONICAL_JST_DAY_REQUIRED') from None
    need(parsed_day.isoformat()==day,'CANONICAL_JST_DAY_REQUIRED')
    need(isinstance(artifact_ids,(list,tuple)) and 1<=len(artifact_ids)<=100 and
         all(type(v) is int and 0<v<10**16 for v in artifact_ids) and
         len(set(artifact_ids))==len(artifact_ids),'BOUNDED_UNIQUE_ARTIFACT_IDS_REQUIRED')
    out=_output_path(output_dir)
    with _parent_handle(out.parent) as parent_fd:
        initial_parent=os.fstat(parent_fd)
        parent_identity=(initial_parent.st_dev,initial_parent.st_ino)
    pins=expected_zip_sha256 or {}
    need(isinstance(pins,dict) and set(pins)<=set(artifact_ids) and
         all(isinstance(v,str) and HEX.fullmatch(v) for v in pins.values()),'ZIP_PINS_INVALID')
    get=github_get or _gh_get
    captured=[];entries=[];total=0
    for ident in artifact_ids:
        metadata_wire=_read(get,f'actions/artifacts/{ident}',MAX_METADATA)
        try:
            meta=json.loads(metadata_wire,object_pairs_hook=_unique,
                            parse_constant=lambda _: (_ for _ in ()).throw(CaptureError('INVALID_METADATA')))
        except (ValueError,TypeError,UnicodeError,RecursionError):
            raise CaptureError('INVALID_METADATA') from None
        need(isinstance(meta,dict) and type(meta.get('id')) is int and meta['id']==ident and meta.get('expired') is False,
             'ARTIFACT_IDENTITY_OR_EXPIRY_REJECTED')
        run=meta.get('workflow_run')
        need(isinstance(run,dict) and type(run.get('id')) is int and run['id']>0 and
             type(run.get('head_repository_id')) is int and run['head_repository_id']==REPOSITORY_ID,'ARTIFACT_REPOSITORY_REJECTED')
        if 'repository_id' in run:
            need(type(run['repository_id']) is int and run['repository_id']==REPOSITORY_ID,
                 'ARTIFACT_REPOSITORY_REJECTED')
        size=meta.get('size_in_bytes')
        need(size is None or type(size) is int and 0<size<=MAX_ZIP,'ARTIFACT_READ_TOO_LARGE')
        choices=[kind for kind,prefix in [('p0','boat-p0-existing-'),('p1','boat-national-cutoff-'),
                                         ('result','race-existing-cycle-')]
                 if matches(meta.get('name'),prefix+str(run['id']))]
        need(len(choices)==1,'ARTIFACT_NAME_REJECTED');kind=choices[0]
        raw=_read(get,f'actions/artifacts/{ident}/zip',MAX_ZIP)
        digest=sha256(raw).hexdigest()
        need(meta.get('digest')=='sha256:'+digest and pins.get(ident,digest)==digest,'ARTIFACT_DIGEST_REJECTED')
        if kind=='p0': _,rows=p0_original_or_empty(raw,meta,day);member='forecasts.json'
        elif kind=='p1':
            _,rows=read_p1(raw,meta);member='national.json'
            need(all(re.fullmatch(day.replace('-','')+r'-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])',r['race_id']) for r in rows),
                 'FORECAST_DAY_REJECTED')
            created=datetime.fromisoformat(meta['created_at'].replace('Z','+00:00'))
            from .cycle_recovery import JST
            need(created.utcoffset() is not None and created.astimezone(JST).date()==parsed_day,'FORECAST_DAY_REJECTED')
        else: result_archive(raw,meta,day);member='official-result-observations.json'
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            need(archive.getinfo(member).file_size<=MAX_ZIP,'ARTIFACT_READ_TOO_LARGE')
            member_sha=sha256(archive.read(member)).hexdigest()
        total+=len(raw)+len(metadata_wire)
        need(total<=MAX_TOTAL,'ARTIFACT_SELECTION_TOO_LARGE')
        metadata_name=f'artifact-{ident}.metadata.json';zip_name=f'artifact-{ident}.zip'
        entries.append(dict(kind=kind,artifact_id=ident,run_id=run['id'],metadata_file=metadata_name,
                            zip_file=zip_name,metadata_sha256=sha256(metadata_wire).hexdigest(),zip_sha256=digest,
                            member_sha256=member_sha,created_at=meta['created_at']))
        captured.extend([(metadata_name,metadata_wire),(zip_name,raw)])
    manifest=dict(schema='RACE_AI_PRIVATE_ARTIFACT_MANIFEST_V1',repo=REPO,
                  repository_id=REPOSITORY_ID,day_jst=day,artifacts=entries)
    with _parent_handle(out.parent) as parent_fd:
        current=os.fstat(parent_fd)
        need((current.st_dev,current.st_ino)==parent_identity,'PRIVATE_PARENT_CHANGED')
        os.mkdir(out.name,mode=0o700,dir_fd=parent_fd)
        out_fd=os.open(out.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent_fd)
        try:
            need(os.fstat(out_fd).st_mode & 0o777==0o700,'PRIVATE_OUTPUT_MODE_REQUIRED')
            for name,raw in captured: _write_at(out_fd,name,raw)
            _write_at(out_fd,'manifest.json',(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode())
        finally:
            os.close(out_fd)
    return manifest


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--day',required=True)
    parser.add_argument('--artifact-id',type=int,action='append',required=True)
    parser.add_argument('--out',required=True)
    parser.add_argument('--export-view',action='store_true')
    parser.add_argument('--dataset-status',choices=('REAL_REPORTED','SYNTHETIC_ONLY'),default='REAL_REPORTED')
    args=parser.parse_args(argv)
    try:
        manifest=capture_artifacts(args.day,args.artifact_id,args.out)
        if args.export_view:
            from .private_cycle_restore import restore_manifest
            from .private_cycle_projection import project_state
            with _parent_handle(Path(args.out)) as output_fd:
                state=restore_manifest(manifest,Path(args.out))
                view=project_state(state,dataset_status=args.dataset_status)
                _write_at(output_fd,'readback-state.json',(json.dumps(state,ensure_ascii=False)+'\n').encode())
                _write_at(output_fd,'cycle-view.json',(json.dumps(view,ensure_ascii=False)+'\n').encode())
        print(json.dumps({'status':'SELECTED_ORIGINALS_CAPTURED','artifacts':len(manifest['artifacts']),
                          'view_exported':args.export_view,'complete_day_history_proven':False,
                          'source_requests':0,'forecast_originals_modified':False}))
        return 0
    except (ValueError,OSError,KeyError,TypeError,zipfile.BadZipFile):
        print('{"status":"PRIVATE_CYCLE_CAPTURE_BLOCKED","originals_overwritten":false}',file=sys.stderr)
        return 2


if __name__=='__main__': raise SystemExit(main())
