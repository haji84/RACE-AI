"""Collect one explicit upcoming race's two original-timing TSVs in RAM.

--day-input approved.json --race-id YYYYMMDD-VV-RR --review media.json
--output-dir NEW_DIRECTORY [--execute]. No credentials or environment variables
are needed. Outputs exclusive canonical observation.json, then input.json with
runner_saved_at measured after observation write/readback, plus manifest.json.
Dry-run reads nothing. No source originals, video or tokens are retained.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib import request

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from publish_day_feed import NoRedirect
from publish_race_updates import select_race
from race_ai.boatcast_original import parse_original,endpoint
from race_ai.tokuyama_day_worker import FetchResponse
from web.race_contract import canonical,program_digest,stamp,_time as instant,JST

REVIEW='user-confirmation-2026-10-15-exhibition-private-analysis'
SCOPES=(dict(component='original_numeric',origin='https://race.boatcast.jp',path_template='/txt/{venue}/bc_oriten_{day}_{venue}_{race}.txt'),
        dict(component='standard_numeric',origin='https://race.boatcast.jp',path_template='/hp_txt/{venue}/bc_j_tkz_{day}_{venue}_{race}.txt'))
MAX_BYTES=1048576


def fetch_original(url,*,timeout=15,max_bytes=MAX_BYTES):
    match=re.fullmatch(r'https://race\.boatcast\.jp/(txt|hp_txt)/(0[1-9]|1[0-9]|2[0-4])/(bc_oriten|bc_j_tkz)_([0-9]{8})_([0-9]{2})_(0[1-9]|1[0-2])\.txt',url)
    if match is None or timeout!=15 or max_bytes!=MAX_BYTES:raise ValueError('ORIGINAL_SOURCE_SCOPE_INVALID')
    path,venue,prefix,day,second_venue,number=match.groups()
    component='original' if path=='txt' else 'standard'
    if venue!=second_venue or prefix!=('bc_oriten' if component=='original' else 'bc_j_tkz') or url!=endpoint(f'{day}-{venue}-{number}',component):
        raise ValueError('ORIGINAL_SOURCE_SCOPE_INVALID')
    req=request.Request(url,headers={'User-Agent':'RACE-AI-authorized-original-numeric/1','Accept':'text/plain'})
    with request.build_opener(NoRedirect()).open(req,timeout=timeout) as response:
        return FetchResponse(response.read(max_bytes+1),response.geturl(),response.status,response.headers.get('Content-Type',''))


def _read(path,limit):
    path=Path(path)
    if not 0<path.stat().st_size<=limit:raise ValueError('ORIGINAL_INPUT_SIZE_INVALID')
    from web.api.today import unique_object,reject_constant,finite_float
    value=json.loads(path.read_text(encoding='utf-8-sig'),object_pairs_hook=unique_object,parse_constant=reject_constant,parse_float=finite_float)
    canonical(value);return value


def _review(value,race,now):
    if (not isinstance(value,dict) or value.get('review_type')!='owner_attestation' or value.get('evidence_reference')!=REVIEW
        or not all(value.get(key) is True for key in ('original_numeric_ingest','original_numeric_store','original_numeric_protected_preview'))
        or race['race_id'][9:11] not in value.get('venue_codes',[]) or not value.get('reviewed_by') or not value.get('owner_statement')
        or instant(value.get('reviewed_at'))>now
        or not all(any(isinstance(scope,dict) and all(scope.get(key)==entry for key,entry in expected.items())
            for scope in value.get('source_scopes',[])) for expected in SCOPES)):
        raise ValueError('ORIGINAL_REVIEW_INVALID')


def _write(path,value):
    raw=canonical(value)
    if not 0<len(raw)<=256000:raise ValueError('ORIGINAL_BACKUP_SIZE_INVALID')
    with path.open('xb') as handle:handle.write(raw)
    if path.read_bytes()!=raw:raise ValueError('ORIGINAL_LOCAL_READBACK_MISMATCH')
    return dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())


def run(day_input,race_id,review_path,output_dir,*,execute=False,transport=None,clock=None):
    if not execute:
        result=dict(result='DRY_RUN',network_requests=0,official_source_requests=0,maximum_official_source_requests=2)
        print(json.dumps(result));return result
    output_dir=Path(output_dir)
    if output_dir.exists():raise ValueError('ORIGINAL_OUTPUT_ALREADY_EXISTS')
    clock=clock or (lambda:datetime.now(timezone.utc));now=clock()
    feed=_read(day_input,6000000);review=_read(review_path,100000)
    race,_=select_race(feed,now,mode='exhibition',race_id=race_id)
    if race is None:raise ValueError('ORIGINAL_NO_UPCOMING_RACE')
    identity=program_digest(race);_review(review,race,clock())
    values=[];captures=[]
    for component in ('original','standard'):
        # Retain exact identity across latency and source calls; no result or
        # another race is substituted when the actual120-second margin expires.
        selected,_=select_race(feed,clock(),mode='exhibition',race_id=race_id)
        if selected is None or program_digest(selected)!=identity:raise ValueError('ORIGINAL_CUTOFF_MARGIN')
        url=endpoint(race_id,component)
        response=(transport or fetch_original)(url,timeout=15,max_bytes=MAX_BYTES)
        captured=clock()
        if (not isinstance(response,FetchResponse) or response.status!=200 or response.url!=url
            or not isinstance(response.body,bytes) or not 0<len(response.body)<=MAX_BYTES
            or not isinstance(response.content_type,str) or response.content_type.split(';')[0].strip().lower()
                not in {'text/plain','application/octet-stream','text/tab-separated-values'}):
            raise ValueError('ORIGINAL_SOURCE_RESPONSE_INVALID')
        values.append(response.body);captures.append(captured)
    observation=parse_original(values[0],values[1],race=race,source_url=endpoint(race_id,'original'),captured_at=stamp(captures[0]),
        companion_source_url=endpoint(race_id,'standard'),companion_captured_at=stamp(captures[1]),now=clock())
    del values,response
    output_dir.mkdir(parents=True,exist_ok=False)
    backups={'observation.json':_write(output_dir/'observation.json',observation)}
    runner=clock()
    if runner<max(captures) or runner.astimezone(JST).date()!=now.astimezone(JST).date():raise ValueError('ORIGINAL_RUNNER_CLOCK_INVALID')
    packet=dict(schema_version=1,race_id=race_id,observation=observation,runner_saved_at=stamp(runner))
    backups['input.json']=_write(output_dir/'input.json',packet)
    result=dict(schema_version=1,result='ORIGINAL_EXHIBITION_COLLECTED',race_id=race_id,status=observation['status'],
        snapshot_id=observation['snapshot_id'],runner_saved_at=stamp(runner),official_source_requests=2,source_originals_retained=False,backups=backups)
    _write(output_dir/'manifest.json',result);print(json.dumps(result,sort_keys=True));return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--day-input',required=True,type=Path);parser.add_argument('--race-id',required=True)
    parser.add_argument('--review',required=True,type=Path);parser.add_argument('--output-dir',required=True,type=Path)
    parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    try:run(args.day_input,args.race_id,args.review,args.output_dir,execute=args.execute)
    except (ValueError,RuntimeError,OSError,TypeError,KeyError) as error:
        code=str(error);safe=code if re.fullmatch(r'ORIGINAL_[A-Z0-9_]+',code) else type(error).__name__
        print('SAFE_STOP: bounded original collection failed '+safe,flush=True);raise SystemExit(2)
