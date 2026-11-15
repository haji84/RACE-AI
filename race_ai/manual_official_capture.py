"""One-time owner-directed official captures and private encrypted recovery.

No model execution, scheduler, provider licence, publication-time attestation,
key discovery or Git/network publication. Thirty-two is a local collection
bound, never a claim about a provider's published quota. Source body/race
identity and downstream feature interpretation remain separate checks.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import base64
import json
import os
from pathlib import Path
import re
import stat
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

TERMS_SCHEMA='RACE_AI_MANUAL_OFFICIAL_TERMS_V1'
CACHE_SCHEMA='RACE_AI_MANUAL_OFFICIAL_CAPTURE_CACHE_V1'
SOURCE_SCHEMA='RACE_AI_MANUAL_OFFICIAL_CAPTURE_SOURCE_V1'
INDEX_SCHEMA='RACE_AI_MANUAL_OFFICIAL_CAPTURE_INDEX_V1'
MAX_REQUESTS=32
MAX_BYTES=2*1024*1024
TIMEOUT=12
INTERVAL=.8
MAX_METADATA=2*1024*1024
JST=timezone(timedelta(hours=9))
ROOT=Path(__file__).resolve().parents[1]
HOSTS={'keirin':frozenset(('keirin.jp','www.keirin.jp')),
       'autorace':frozenset(('autorace.jp','www.autorace.jp')),
       'horse':frozenset(('jra.go.jp','www.jra.go.jp'))}
_CREDENTIALS=frozenset(('key','api_key','apikey','token','access_token','authorization','auth','password',
                      'passwd','pwd','secret','signature','credential','credentials','cookie','session','sessionid'))
_HEX=re.compile(r'[0-9a-f]{64}\Z')
_SOURCE_FIELDS={'url','final_url','source_rights_ref','source_sha256','size','captured_at','published_at',
                'content_type','redirect_chain','raw_file','capture_origin','body_identity_verified'}
HTTP_SCHEMA='RACE_AI_MANUAL_OFFICIAL_HTTP_METADATA_V1'
HTTP_HEADER_NAMES=frozenset(('content-type','content-length','content-encoding','date','cache-control','location'))


def _need(ok,reason):
    if not ok:raise ValueError('MANUAL_OFFICIAL_'+reason)


def _wire(value):
    try:return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    except (ValueError,TypeError,UnicodeError,RecursionError,OverflowError):
        raise ValueError('MANUAL_OFFICIAL_JSON_INVALID') from None


def _json(raw):
    def unique(pairs):
        out={}
        for key,value in pairs:
            _need(key not in out,'DUPLICATE_JSON_FIELD');out[key]=value
        return out
    try:return json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _: _need(False,'NONFINITE_JSON'))
    except (ValueError,UnicodeError,RecursionError):raise ValueError('MANUAL_OFFICIAL_JSON_INVALID') from None


def _time(value):
    _need(type(value) is str and len(value)<=64,'AWARE_CLOCK_REQUIRED')
    try:instant=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:raise ValueError('MANUAL_OFFICIAL_AWARE_CLOCK_REQUIRED') from None
    _need(instant.utcoffset() is not None,'AWARE_CLOCK_REQUIRED');return instant


def _now(clock):
    instant=clock()
    _need(type(instant) is datetime and instant.utcoffset() is not None,'AWARE_CLOCK_REQUIRED')
    return instant


def _day(value):
    _need(type(value) is str,'EXECUTION_DAY_REQUIRED')
    try:parsed=date.fromisoformat(value)
    except ValueError:raise ValueError('MANUAL_OFFICIAL_EXECUTION_DAY_INVALID') from None
    _need(parsed.isoformat()==value,'EXECUTION_DAY_INVALID');return parsed


def official_rights_ref(sport):
    _need(type(sport) is str and sport in HOSTS,'OFFICIAL_SPORT_INVALID')
    return 'OWNER_PERSONAL_OFFICIAL_'+sport.upper()+'_FACTUAL_ANALYSIS_20261107'


def _url(url):
    _need(type(url) is str and 1<=len(url)<=4096 and not any(c.isspace() or ord(c)<32 or ord(c)==127 for c in url)
          and '\\' not in url and '#' not in url,'OFFICIAL_URL_INVALID')
    try:
        parts=urlsplit(url)
        _need(parts.scheme=='https' and parts.username is None and parts.password is None and
              parts.port in (None,443) and not parts.fragment and parts.hostname is not None,'OFFICIAL_URL_INVALID')
        sport=next((sport for sport,hosts in HOSTS.items() if parts.hostname in hosts),None)
        _need(sport is not None,'OFFICIAL_HOST_NOT_ALLOWED')
        query=parse_qsl(parts.query,keep_blank_values=True,max_num_fields=100)
        _need(all(key.lower().replace('-','_') not in _CREDENTIALS for key,_ in query),'URL_CREDENTIALS_REJECTED')
    except (ValueError,UnicodeError):raise ValueError('MANUAL_OFFICIAL_OFFICIAL_URL_INVALID') from None
    return sport,parts.hostname


def validate_source_pair(url,rights):
    sport,_=_url(url)
    _need(type(rights) is str and rights==official_rights_ref(sport),'SOURCE_RIGHTS_MISMATCH')
    return url,rights


def _terms(value,urls,execution_day,now):
    fields={'schema','execution_day','purpose','public_redistribution',
            'provider_model_training_permission_confirmed','owner_instruction_ref','terms'}
    _need(type(value) is dict and set(value)==fields and value['schema']==TERMS_SCHEMA and
          value['execution_day']==execution_day and value['purpose']=='PRIVATE_FACTUAL_ANALYSIS' and
          value['public_redistribution'] is False and value['provider_model_training_permission_confirmed'] is False and
          type(value['owner_instruction_ref']) is str and 0<len(value['owner_instruction_ref'])<=512,'TERMS_MANIFEST_REQUIRED')
    records=value['terms'];_need(type(records) is list and 1<=len(records)<=3,'TERMS_MANIFEST_REQUIRED')
    covered=set();sports=set()
    for record in records:
        _need(type(record) is dict and set(record)=={'sport','terms_url','policy_sha256','policy_captured_at','source_urls','uses'},
              'TERMS_RECORD_INVALID')
        sport=record['sport'];_need(sport in HOSTS and sport not in sports,'TERMS_SPORT_INVALID');sports.add(sport)
        validate_source_pair(record['terms_url'],official_rights_ref(sport))
        _need(type(record['policy_sha256']) is str and _HEX.fullmatch(record['policy_sha256']) and
              _time(record['policy_captured_at'])<=now,'POLICY_CAPTURE_REQUIRED')
        _need(record['uses']==['private_retention','private_factual_analysis'],'TERMS_USE_INVALID')
        members=record['source_urls'];_need(type(members) is list and 1<=len(members)<=MAX_REQUESTS,'TERMS_SOURCE_URLS_REQUIRED')
        for url in members:
            validate_source_pair(url,official_rights_ref(sport));_need(url not in covered,'DUPLICATE_TERMS_URL');covered.add(url)
    _need(covered==set(urls),'TERMS_URL_SCOPE_MISMATCH')
    return deepcopy(value)


def _location(value):
    path=Path(value)
    _need(path.is_absolute() and '..' not in path.parts and not path.is_relative_to(ROOT),'PRIVATE_OUTSIDE_GIT_REQUIRED')
    for parent in (path,*path.parents):
        _need(not parent.is_symlink() and not (parent/'.git').exists() and not (parent/'.git').is_symlink(),
              'PRIVATE_OUTSIDE_GIT_REQUIRED')
    return path


def _private_root(value,*,create=False,exclusive=False):
    root=_location(value)
    if create:
        missing=[];parent=root
        while not parent.exists():missing.append(parent);parent=parent.parent
        if exclusive:_need(not root.exists(),'OUTPUT_EXISTS_DO_NOT_RESET')
        for parent in reversed(missing):parent.mkdir(mode=0o700)
    info=root.lstat()
    _need(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode)==0o700 and info.st_uid==os.getuid(),
          'PRIVATE_DIRECTORY_REQUIRED')
    return root


@contextmanager
def _directory(root):
    # Reuse the existing no-follow ancestor walk. File operations stay bound
    # to this checked inode even if a pathname is replaced concurrently.
    from .private_cycle_capture import _parent_handle
    with _parent_handle(_location(root)) as descriptor:
        info=os.fstat(descriptor)
        _need(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode)==0o700 and info.st_uid==os.getuid(),
              'PRIVATE_DIRECTORY_REQUIRED')
        yield descriptor


def _read_at(directory,name,limit):
    fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory)
    with os.fdopen(fd,'rb') as source:
        before=os.fstat(source.fileno())
        _need(stat.S_ISREG(before.st_mode) and stat.S_IMODE(before.st_mode)==0o600 and
              before.st_uid==os.getuid() and before.st_nlink==1 and 0<before.st_size<=limit,'PRIVATE_FILE_REQUIRED')
        raw=source.read(limit+1);after=os.fstat(source.fileno())
        _need(len(raw)==before.st_size<=limit and (before.st_ino,before.st_dev,before.st_mtime_ns,before.st_ctime_ns)==
              (after.st_ino,after.st_dev,after.st_mtime_ns,after.st_ctime_ns),'PRIVATE_FILE_CHANGED')
    return raw


def _read(path,limit):
    path=Path(path)
    with _directory(path.parent) as directory:return _read_at(directory,path.name,limit)


def _write(path,raw,*,replace=False):
    path=Path(path)
    with _directory(path.parent) as directory:
        if replace:_read_at(directory,path.name,MAX_METADATA)
        temporary='.'+path.name+'.'+os.urandom(8).hex() if replace else path.name
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory)
        try:
            with os.fdopen(fd,'wb') as target:target.write(raw);target.flush();os.fsync(target.fileno())
            if replace:os.replace(temporary,path.name,src_dir_fd=directory,dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            if replace:
                try:os.unlink(temporary,dir_fd=directory)
                except FileNotFoundError:pass


@contextmanager
def _lock(root):
    with _directory(root) as directory:
        try:fd=os.open('.lock',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory)
        except OSError:raise ValueError('MANUAL_OFFICIAL_CAPTURE_LOCKED') from None
        try:
            identity=os.fstat(fd);os.fsync(fd);os.fsync(directory);yield
        finally:
            os.close(fd)
            current=os.stat('.lock',dir_fd=directory,follow_symlinks=False)
            _need((identity.st_ino,identity.st_dev)==(current.st_ino,current.st_dev),'LOCK_CHANGED')
            os.unlink('.lock',dir_fd=directory);os.fsync(directory)


def _source_metadata(value,execution_day,updated):
    _need(type(value) is dict and set(value) in (_SOURCE_FIELDS,_SOURCE_FIELDS|{'http_metadata'}),'CAPTURE_METADATA_INVALID')
    url=value['url'];sport,host=_url(url);validate_source_pair(url,value['source_rights_ref'])
    _need(_url(value['final_url'])==(sport,host),'REDIRECT_HOST_MISMATCH')
    chain=value['redirect_chain']
    _need(type(chain) is list and 1<=len(chain)<=4 and len(chain)==len(set(chain)) and
          chain[0]==url and chain[-1]==value['final_url'] and all(_url(item)==(sport,host) for item in chain),
          'REDIRECT_CHAIN_INVALID')
    captured=_time(value['captured_at'])
    _need(captured<=updated and captured.astimezone(JST).date()==_day(execution_day) and value['published_at'] is None and
          value['body_identity_verified'] is False,'SOURCE_CLOCK_OR_CLAIM_INVALID')
    _need(type(value['source_sha256']) is str and _HEX.fullmatch(value['source_sha256']) and
          type(value['size']) is int and 0<value['size']<=MAX_BYTES and
          value['raw_file']==sha256(url.encode()).hexdigest()+'.raw' and
          value['capture_origin'] in ('HTTP_GET','IMPORTED_PRIOR_CAPTURE') and
          type(value['content_type']) is str and len(value['content_type'])<=512,'SOURCE_HASH_OR_SIZE_INVALID')
    if 'http_metadata' in value:_http_metadata(value['http_metadata'],value,execution_day)


def _http_metadata(value,source,execution_day):
    fields={'schema','attempt_no','source_url','final_url','status','byte_count','source_sha256',
            'fetched_at','headers_received_at','response_received_at','headers'}
    _need(type(value) is dict and set(value)==fields and value['schema']==HTTP_SCHEMA and
          type(value['attempt_no']) is int and 1<=value['attempt_no']<=MAX_REQUESTS and
          source['capture_origin']=='HTTP_GET','HTTP_METADATA_INVALID')
    _need(value['source_url']==value['final_url']==source['final_url'] and type(value['status']) is int and value['status']==200 and
          type(value['byte_count']) is int and value['byte_count']==source['size'] and value['source_sha256']==source['source_sha256'], 'HTTP_SOURCE_BINDING')
    clocks=[_time(value[key]) for key in ('fetched_at','headers_received_at','response_received_at')]
    _need(clocks==sorted(clocks) and value['response_received_at']==source['captured_at'] and
          all(clock.astimezone(JST).date()==_day(execution_day) for clock in clocks),'HTTP_SOURCE_CLOCK')
    headers=value['headers']
    _need(type(headers) is list and len(headers)<=32 and all(type(pair) is list and len(pair)==2 and
          type(pair[0]) is str and pair[0].lower() in HTTP_HEADER_NAMES and
          type(pair[1]) is str and len(pair[1])<=2048 for pair in headers),'HTTP_HEADERS_INVALID')


def _http_headers(headers):
    # Keep original casing, values and duplicate observations. The sidecar join
    # decides whether these observations are unambiguous enough for JRA.
    pairs=headers.raw_items() if hasattr(headers,'raw_items') else headers.items()
    return [[name,value] for name,value in pairs if type(name) is str and name.lower() in HTTP_HEADER_NAMES]


def _validate_cache(cache):
    fields={'schema','execution_day','urls','terms_manifest','terms_manifest_sha256','created_at','updated_at',
            'request_limit','attempts','blocked_hosts','captures','failures','last_request_finished_at'}
    _need(type(cache) is dict and set(cache)==fields and cache['schema']==CACHE_SCHEMA,'CACHE_SCHEMA_INVALID')
    day=cache['execution_day'];_day(day);created=_time(cache['created_at']);updated=_time(cache['updated_at'])
    _need(created<=updated and created.astimezone(JST).date()==_day(day),'CACHE_CLOCK_INVALID')
    urls=cache['urls'];_need(type(urls) is list and 1<=len(urls)<=MAX_REQUESTS and len(urls)==len(set(urls)),'URL_PLAN_INVALID')
    for url in urls:_url(url)
    terms=_terms(cache['terms_manifest'],urls,day,created)
    _need(sha256(_wire(terms)).hexdigest()==cache['terms_manifest_sha256'],'TERMS_HASH_MISMATCH')
    limit=cache['request_limit'];attempts=cache['attempts']
    _need(type(limit) is int and 1<=limit<=MAX_REQUESTS and type(attempts) is list and len(attempts)<=limit,'REQUEST_LIMIT_INVALID')
    for item in attempts:
        _need(type(item) is dict and set(item)=={'url','target_url','started_at','finished_at','state','http_status'},'ATTEMPT_INVALID')
        _url(item['url']);_need(item['target_url'] in urls and _url(item['url'])[1]==_url(item['target_url'])[1], 'ATTEMPT_URL_INVALID')
        start=_time(item['started_at']);_need(created<=start<=updated,'ATTEMPT_CLOCK_INVALID')
        if item['state']=='RESERVED':_need(item['finished_at'] is None and item['http_status'] is None,'ATTEMPT_INVALID')
        else:
            _need(item['state'] in ('SUCCESS','REDIRECT','DENIED','HTTP_FAILURE','TRANSPORT_FAILURE','RESPONSE_REJECTED') and
                  start<=_time(item['finished_at'])<=updated,'ATTEMPT_INVALID')
            _need(item['http_status'] is None or type(item['http_status']) is int and 100<=item['http_status']<=599,'ATTEMPT_INVALID')
    hosts={_url(url)[1] for url in urls}
    _need(type(cache['blocked_hosts']) is dict and set(cache['blocked_hosts'])<=hosts,'HOST_STOP_INVALID')
    for value in cache['blocked_hosts'].values():
        _need(type(value) is dict and set(value)=={'http_status','at','retry_after'} and value['http_status'] in (401,403,429)
              and _time(value['at'])<=updated and (value['retry_after'] is None or type(value['retry_after']) is str and
                  len(value['retry_after'])<=512),'HOST_STOP_INVALID')
    _need(type(cache['captures']) is dict and set(cache['captures'])<=set(urls) and
          type(cache['failures']) is dict and set(cache['failures'])<=set(urls),'CAPTURE_SET_INVALID')
    for url,value in cache['captures'].items():
        _need(value['url']==url,'CAPTURE_URL_MISMATCH');_source_metadata(value,day,updated)
    _need(all(type(reason) is str and re.fullmatch('[A-Z0-9_]{1,100}',reason) for reason in cache['failures'].values()),'FAILURE_CODE_INVALID')
    if cache['last_request_finished_at'] is not None:_need(_time(cache['last_request_finished_at'])<=updated,'CACHE_CLOCK_INVALID')
    return cache


def _load(root,*,locked=False):
    cache=_validate_cache(_json(_read(root/'cache.json',MAX_METADATA)))
    names={'cache.json'}|{source['raw_file'] for source in cache['captures'].values()}|({'.lock'} if locked else set())
    with _directory(root) as directory:_need(set(os.listdir(directory))==names,'CACHE_INVENTORY_MISMATCH')
    for source in cache['captures'].values():
        raw=_read(root/source['raw_file'],MAX_BYTES)
        _need(len(raw)==source['size'] and sha256(raw).hexdigest()==source['source_sha256'],'RAW_SOURCE_HASH_MISMATCH')
    return cache


def _save(root,cache,clock):
    now=_now(clock);_need(now>=_time(cache['updated_at']),'CLOCK_REGRESSED');cache['updated_at']=now.isoformat()
    raw=_wire(_validate_cache(cache));_need(len(raw)<=MAX_METADATA,'CACHE_METADATA_LIMIT')
    _write(root/'cache.json',raw,replace=(root/'cache.json').exists())


def _prepare(urls,execution_day,terms_manifest,cache_dir,clock,request_limit=MAX_REQUESTS):
    now=_now(clock);_need(_day(execution_day)==now.astimezone(JST).date(),'EXECUTION_DAY_MISMATCH')
    _need(type(urls) is list and 1<=len(urls)<=MAX_REQUESTS and len(urls)==len(set(urls)),'URL_PLAN_INVALID')
    for url in urls:_url(url)
    terms=_terms(terms_manifest,urls,execution_day,now)
    _need(type(request_limit) is int and 1<=request_limit<=MAX_REQUESTS,'REQUEST_LIMIT_INVALID')
    root=_private_root(cache_dir,create=True)
    if (root/'cache.json').exists():
        cache=_load(root)
        _need(cache['execution_day']==execution_day and cache['urls']==urls and cache['terms_manifest']==terms and
              cache['request_limit']==request_limit,'EXISTING_PLAN_MISMATCH')
        _need(_time(cache['updated_at'])<=now,'CLOCK_REGRESSED')
    else:
        _need(not any(root.iterdir()),'CACHE_EXISTS_DO_NOT_RESET')
        cache=dict(schema=CACHE_SCHEMA,execution_day=execution_day,urls=deepcopy(urls),terms_manifest=terms,
            terms_manifest_sha256=sha256(_wire(terms)).hexdigest(),created_at=now.isoformat(),updated_at=now.isoformat(),
            request_limit=request_limit,attempts=[],blocked_hosts={},captures={},failures={},last_request_finished_at=None)
        _save(root,cache,clock)
    return root


def _report(cache,*,source_requests=0,cache_hits=0,imported_sources=0):
    return dict(schema='RACE_AI_MANUAL_OFFICIAL_CAPTURE_COUNTS_V1',execution_day=cache['execution_day'],
        captured_sources=len(cache['captures']),cache_hits=cache_hits,imported_sources=imported_sources,
        source_requests=source_requests,total_collector_requests=len(cache['attempts']),request_limit=cache['request_limit'],
        blocked_host_count=len(cache['blocked_hosts']),failed_sources=len(cache['failures']),
        request_limit_basis='LOCAL_ONE_TIME_BOUND_NOT_PROVIDER_QUOTA',body_identity_verified=False,
        provider_model_training_permission_confirmed=False,public_redistribution=False,
        independent_pre_cutoff_receipt_verified=False,plaintext_published=False)


def _store(root,cache,url,raw,*,final_url,captured_at,content_type,chain,origin,http_metadata=None):
    metadata=dict(url=url,final_url=final_url,source_rights_ref=official_rights_ref(_url(url)[0]),
        source_sha256=sha256(raw).hexdigest(),size=len(raw),captured_at=captured_at,published_at=None,
        content_type=content_type,redirect_chain=chain,raw_file=sha256(url.encode()).hexdigest()+'.raw',
        capture_origin=origin,body_identity_verified=False)
    if http_metadata is not None:metadata['http_metadata']=deepcopy(http_metadata)
    _source_metadata(metadata,cache['execution_day'],max(_time(cache['updated_at']),_time(captured_at)))
    if url in cache['captures']:
        _need(cache['captures'][url]==metadata and _read(root/metadata['raw_file'],MAX_BYTES)==raw,'ORIGINAL_EXISTS_DO_NOT_REPLACE')
    else:_write(root/metadata['raw_file'],raw);cache['captures'][url]=metadata


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None


def collect_once(urls,*,execution_day,terms_manifest,cache_dir,clock=lambda:datetime.now(timezone.utc),
                 opener=None,sleeper=time.sleep,monotonic=time.monotonic,request_limit=MAX_REQUESTS):
    """Collect explicit public URLs once, preserving successful cached originals.

    Resuming reuses captured bytes and never retries an already failed target.
    A crash after a durable request reservation stops the session for review.
    Same-host redirects consume requests and spacing just like initial GETs.
    """
    root=_prepare(urls,execution_day,terms_manifest,cache_dir,clock,request_limit)
    fetch=opener if opener is not None else build_opener(_NoRedirect()).open
    with _lock(root):
        cache=_load(root,locked=True)
        _need(not any(item['state']=='RESERVED' for item in cache['attempts']),'UNCERTAIN_PRIOR_REQUEST_NO_RETRY')
        used=0;hits=0;last_mono=None
        for target in urls:
            if target in cache['captures']:hits+=1;continue
            host=_url(target)[1]
            if host in cache['blocked_hosts'] or target in cache['failures']:continue
            current=target;chain=[target]
            while True:
                if len(cache['attempts'])>=cache['request_limit']:break
                now=_now(clock);_need(now.astimezone(JST).date()==_day(execution_day),'EXECUTION_DAY_MISMATCH')
                previous=cache['last_request_finished_at']
                if previous is not None:
                    elapsed=(now-_time(previous)).total_seconds();_need(elapsed>=0,'CLOCK_REGRESSED')
                    if last_mono is not None:elapsed=min(elapsed,monotonic()-last_mono)
                    _need(elapsed>=0,'CLOCK_REGRESSED')
                    if elapsed<INTERVAL:sleeper(INTERVAL-elapsed)
                started=_now(clock)
                _need(started.astimezone(JST).date()==_day(execution_day),'EXECUTION_DAY_MISMATCH')
                attempt=dict(url=current,target_url=target,started_at=started.isoformat(),finished_at=None,state='RESERVED',http_status=None)
                cache['attempts'].append(attempt);_save(root,cache,clock);used+=1
                response=None;status=None;state='TRANSPORT_FAILURE';reason=None;headers={};redirect=None
                try:
                    try:response=fetch(Request(current,headers={'User-Agent':'RACE-AI-owner-manual-private-factual-analysis/1.0',
                                                              'Accept':'text/html,application/pdf,application/json;q=0.8'}),timeout=TIMEOUT)
                    except HTTPError as exc:response=exc
                    headers_received=_now(clock)
                    status=getattr(response,'status',None) or getattr(response,'code',None)
                    _need(type(status) is int,'RESPONSE_STATUS_INVALID')
                    # Any observed authorization/rate denial stops the
                    # original host, even if response identity is anomalous.
                    _need(status in (401,403,429) or response.geturl()==current,'UNEXPECTED_AUTOMATIC_REDIRECT')
                    headers=response.headers
                    if status in (401,403,429):
                        state='DENIED';reason='HOST_AUTHORIZATION_OR_RATE_STOP'
                    elif status in (301,302,303,307,308):
                        state='REDIRECT';location=headers.get('Location')
                        _need(type(location) is str and location,'REDIRECT_LOCATION_REQUIRED')
                        redirect=urljoin(current,location)
                        _need(_url(redirect)==_url(target) and redirect not in chain and len(chain)<4,'REDIRECT_NOT_ALLOWED')
                    elif status==200:
                        state='RESPONSE_REJECTED'
                        observed_headers=_http_headers(headers)
                        length=headers.get('Content-Length')
                        if length is not None:_need(str(length).isdigit() and 0<int(length)<=MAX_BYTES,'SOURCE_SIZE_LIMIT')
                        _need(headers.get('Content-Encoding','identity').lower() in ('','identity'),'SOURCE_ENCODING_UNSUPPORTED')
                        raw=response.read(MAX_BYTES+1);_need(type(raw) is bytes and 0<len(raw)<=MAX_BYTES,'SOURCE_SIZE_LIMIT')
                        _need(length is None or len(raw)==int(length),'SOURCE_BODY_TRUNCATED')
                        captured=_now(clock);_need(captured>=started and captured.astimezone(JST).date()==_day(execution_day),'SOURCE_CLOCK_INVALID')
                        content_type=headers.get('Content-Type','')
                        _need(type(content_type) is str and len(content_type)<=512,'SOURCE_CONTENT_TYPE_INVALID')
                        _store(root,cache,target,raw,final_url=current,captured_at=captured.isoformat(),
                               content_type=content_type,chain=deepcopy(chain),origin='HTTP_GET',
                               http_metadata=dict(schema=HTTP_SCHEMA,attempt_no=len(cache['attempts']),source_url=current,
                                   final_url=response.geturl(),status=status,byte_count=len(raw),source_sha256=sha256(raw).hexdigest(),
                                   fetched_at=started.isoformat(),headers_received_at=headers_received.isoformat(),
                                   response_received_at=captured.isoformat(),headers=observed_headers))
                        state='SUCCESS'
                    else:state='HTTP_FAILURE';reason='HTTP_STATUS_UNAVAILABLE'
                except (ValueError,URLError,TimeoutError,OSError):
                    reason='SOURCE_RESPONSE_REJECTED' if response is not None else 'SOURCE_TRANSPORT_UNAVAILABLE'
                    state='RESPONSE_REJECTED' if response is not None else 'TRANSPORT_FAILURE';redirect=None
                finally:
                    if response is not None:response.close()
                finished=_now(clock);_need(finished>=started,'CLOCK_REGRESSED')
                attempt.update(finished_at=finished.isoformat(),state=state,http_status=status)
                cache['last_request_finished_at']=finished.isoformat();last_mono=monotonic()
                if state=='DENIED':
                    retry=headers.get('Retry-After');retry=retry[:512] if type(retry) is str else None
                    cache['blocked_hosts'][host]=dict(http_status=status,at=finished.isoformat(),retry_after=retry)
                if reason is not None:cache['failures'][target]=reason
                _save(root,cache,clock)
                if redirect is None:break
                current=redirect;chain.append(current)
            if len(cache['attempts'])>=cache['request_limit']:break
        _load(root,locked=True)
        return _report(cache,source_requests=used,cache_hits=hits)


def import_captures(captures,*,execution_day,terms_manifest,cache_dir,clock=lambda:datetime.now(timezone.utc)):
    """Retain caller-supplied prior captures without fetching or changing clocks."""
    _need(type(captures) is list and 1<=len(captures)<=MAX_REQUESTS,'IMPORT_BOUND_INVALID')
    urls=[]
    for item in captures:
        _need(type(item) is dict and set(item)=={'url','raw','captured_at','content_type','final_url'} and
              type(item['raw']) is bytes and 0<len(item['raw'])<=MAX_BYTES,'IMPORT_CAPTURE_INVALID')
        _url(item['url']);_need(_url(item['url'])==_url(item['final_url']),'IMPORT_REDIRECT_INVALID')
        _need(_time(item['captured_at'])<=_now(clock),'IMPORT_CAPTURE_FROM_FUTURE');urls.append(item['url'])
    root=_prepare(urls,execution_day,terms_manifest,cache_dir,clock)
    with _lock(root):
        cache=_load(root,locked=True);count=0
        for item in captures:
            existed=item['url'] in cache['captures']
            chain=[item['url']] if item['url']==item['final_url'] else [item['url'],item['final_url']]
            _store(root,cache,item['url'],item['raw'],final_url=item['final_url'],captured_at=item['captured_at'],
                   content_type=item['content_type'],chain=chain,origin='IMPORTED_PRIOR_CAPTURE')
            count+=not existed
        _save(root,cache,clock);return _report(cache,imported_sources=count)


def read_capture(cache_dir,url):
    root=_private_root(cache_dir);cache=_load(root)
    _need(url in cache['captures'],'CAPTURE_NOT_AVAILABLE');metadata=cache['captures'][url]
    return dict(metadata=deepcopy(metadata),raw=_read(root/metadata['raw_file'],MAX_BYTES))


def _key(key):
    _need(type(key) is bytes and len(key)==32,'EXPLICIT_OWNER_KEY_REQUIRED');return key


def seal_cache(cache_dir,sealed_dir,*,key,run_id,round_no):
    """Use the existing owner AES codec; retain plaintext until full readback.

    The authenticated run/round fields provide a namespace, not a capture or
    upload timestamp. The caller owns any later independent receipt.
    """
    _key(key)
    from .boat_all_model_store import seal_forecasts,open_forecasts
    root=_private_root(cache_dir);destination=_location(sealed_dir)
    _need(root!=destination and root not in destination.parents and destination not in root.parents,'OUTPUT_OVERLAP_REJECTED')
    with _lock(root):
        cache=_load(root,locked=True);batch=sha256(_wire(cache)).hexdigest();members=[]
        destination=_private_root(destination,create=True,exclusive=True)
        for number,(url,metadata) in enumerate(sorted(cache['captures'].items())):
            raw=_read(root/metadata['raw_file'],MAX_BYTES)
            payload=dict(schema=SOURCE_SCHEMA,batch_id=batch,execution_day=cache['execution_day'],
                terms_manifest_sha256=cache['terms_manifest_sha256'],metadata=deepcopy(metadata),raw_base64=base64.b64encode(raw).decode())
            cipher=seal_forecasts(payload,run_id=run_id,round_no=round_no,key=key)
            name=f'source-{number:04d}.enc';_write(destination/name,cipher)
            _need(open_forecasts(_read(destination/name,4*1024*1024),key=key)==payload,'ENCRYPTED_SOURCE_READBACK_FAILED')
            members.append(dict(name=name,cipher_sha256=sha256(cipher).hexdigest(),cipher_size=len(cipher),url=url))
        index=dict(schema=INDEX_SCHEMA,batch_id=batch,cache=cache,sources=members)
        encrypted=seal_forecasts(index,run_id=run_id,round_no=round_no,key=key);_write(destination/'index.enc',encrypted)
        _need(_read_sealed(destination,key=key,expected_index_sha256=sha256(encrypted).hexdigest())[0]==cache,
              'ENCRYPTED_INDEX_READBACK_FAILED')
        return dict(schema='RACE_AI_MANUAL_OFFICIAL_SEALED_COUNTS_V1',captured_sources=len(members),
            index_sha256=sha256(encrypted).hexdigest(),encrypted_readback_verified=True,
            plaintext_published=False,independent_pre_cutoff_receipt_verified=False)


def _read_sealed(sealed_dir,*,key,expected_index_sha256):
    _key(key);_need(type(expected_index_sha256) is str and _HEX.fullmatch(expected_index_sha256),'EXPECTED_INDEX_SHA_REQUIRED')
    from .boat_all_model_store import open_forecasts
    root=_private_root(sealed_dir);raw=_read(root/'index.enc',4*1024*1024)
    _need(sha256(raw).hexdigest()==expected_index_sha256,'INDEX_CIPHER_HASH_MISMATCH')
    index=open_forecasts(raw,key=key)
    _need(type(index) is dict and set(index)=={'schema','batch_id','cache','sources'} and index['schema']==INDEX_SCHEMA,
          'ENCRYPTED_INDEX_SCHEMA_INVALID')
    cache=_validate_cache(index['cache']);batch=sha256(_wire(cache)).hexdigest()
    _need(index['batch_id']==batch and type(index['sources']) is list and len(index['sources'])==len(cache['captures']),
          'ENCRYPTED_INDEX_BINDING_INVALID')
    files={'index.enc'};bodies={};urls=set()
    for number,member in enumerate(index['sources']):
        _need(type(member) is dict and set(member)=={'name','cipher_sha256','cipher_size','url'} and
              member['name']==f'source-{number:04d}.enc' and member['url'] in cache['captures'] and member['url'] not in urls,
              'ENCRYPTED_MEMBER_INVALID')
        name=member['name'];files.add(name);urls.add(member['url'])
        body=_read(root/name,4*1024*1024)
        _need(type(member['cipher_size']) is int and len(body)==member['cipher_size'] and
              sha256(body).hexdigest()==member['cipher_sha256'],'SOURCE_CIPHER_HASH_MISMATCH')
        source=open_forecasts(body,key=key)
        _need(type(source) is dict and set(source)=={'schema','batch_id','execution_day','terms_manifest_sha256','metadata','raw_base64'} and
              source['schema']==SOURCE_SCHEMA and source['batch_id']==batch and source['execution_day']==cache['execution_day'] and
              source['terms_manifest_sha256']==cache['terms_manifest_sha256'] and
              source['metadata']==cache['captures'][member['url']],'ENCRYPTED_SOURCE_BINDING_INVALID')
        encoded=source['raw_base64'];_need(type(encoded) is str and len(encoded)<=((MAX_BYTES+2)//3)*4,'SOURCE_BASE64_INVALID')
        try:plain=base64.b64decode(encoded,validate=True)
        except ValueError:raise ValueError('MANUAL_OFFICIAL_SOURCE_BASE64_INVALID') from None
        metadata=source['metadata']
        _need(base64.b64encode(plain).decode()==encoded and len(plain)==metadata['size'] and
              sha256(plain).hexdigest()==metadata['source_sha256'],'ENCRYPTED_RAW_HASH_MISMATCH')
        bodies[metadata['raw_file']]=plain
    with _directory(root) as directory:
        _need(set(os.listdir(directory))==files and urls==set(cache['captures']),'ENCRYPTED_INVENTORY_MISMATCH')
    return cache,bodies


def restore_cache(sealed_dir,output_dir,*,key,expected_index_sha256):
    """Independently authenticate every ciphertext and restore exact raw bytes."""
    cache,bodies=_read_sealed(sealed_dir,key=key,expected_index_sha256=expected_index_sha256)
    output=_private_root(output_dir,create=True,exclusive=True)
    for name,raw in bodies.items():_write(output/name,raw)
    _write(output/'cache.json',_wire(cache));_need(_load(output)==cache,'RESTORE_READBACK_FAILED')
    return dict(schema='RACE_AI_MANUAL_OFFICIAL_RESTORE_COUNTS_V1',captured_sources=len(bodies),
        encrypted_readback_verified=True,plaintext_published=False,independent_pre_cutoff_receipt_verified=False)
