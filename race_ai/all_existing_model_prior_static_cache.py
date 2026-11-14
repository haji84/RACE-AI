"""Replay static originals from an already MAC/receipt-admitted private journal.

This grants neither dispatch nor result authority. The caller authenticates the
journal artifact first; every retained wire member is checked before filtering.
"""
import base64
from copy import deepcopy
from hashlib import sha256
import os
from pathlib import Path
import re
import subprocess
import tempfile

from .actions_contract import digest
from . import all_existing_model_official_continuation as continuation
from .manual_official_capture import _url
from .permissioned_source_delivery import read_json_bytes

MAX_BODY=2*1024*1024
MAX_CACHE=16*1024*1024
need=continuation.need
clock=continuation.clock
_NODE="""const fs=require('node:fs'),api=require(process.argv[1]);
const v=JSON.parse(fs.readFileSync(0,'utf8'));
for(const entries of v.groups)api.validateStaticCache(entries,{cases:v.sports.map(sport=>({sport}))},new Date(v.now));
process.stdout.write('OK');"""


def _raw(value,maximum):
    need(type(value) is str and len(value)<=4*((maximum+2)//3),'STATIC_CACHE_BYTES')
    try:raw=base64.b64decode(value,validate=True)
    except (ValueError,TypeError):raise ValueError('PRIOR_STATIC_CACHE_BASE64') from None
    need(base64.b64encode(raw).decode()==value and len(raw)<=maximum,'STATIC_CACHE_BYTES')
    return raw


def merge_static_cache(existing,additions,*,now,sports):
    """Validate all entries, retain the first original, then filter by sport."""
    from scripts import all_existing_model_official_result_collect as collector
    now=clock(now);sports=set(sports)
    need(sports and sports<={'autorace','keirin'} and type(existing) is list and type(additions) is list and
        len(existing)<=128 and len(additions)<=128,'STATIC_CACHE_BOUND')
    entries=[];by_url={};used=0
    for item in existing+additions:
        need(type(item) is dict and set(item)=={'raw_base64','metadata'} and type(item['metadata']) is dict,'STATIC_CACHE_SCHEMA')
        raw=_raw(item['raw_base64'],MAX_BODY);meta=item['metadata'];url=meta.get('source_url')
        need(raw and type(meta.get('byte_count')) is int and meta['byte_count']==len(raw) and
            meta.get('source_sha256')==sha256(raw).hexdigest() and
            clock(meta['fetched_at'])<=clock(meta['response_received_at'])<=now,'STATIC_CACHE_PROOF')
        _url(url)
        if url in by_url:
            need(by_url[url]['metadata']['source_sha256']==meta['source_sha256'],'CONFLICTING_STATIC_CACHE')
        else:
            by_url[url]=item;entries.append(item);used+=len(raw)
        need(len(entries)<=128 and used<=MAX_CACHE,'STATIC_CACHE_BOUND')
    # Fixed trusted code only; no inherited owner, Git, Node or provider secrets.
    payload=collector.future.wire(dict(groups=[existing,additions],sports=['autorace','keirin'],now=now.isoformat()))
    env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'LANG':'C.UTF-8','LC_ALL':'C.UTF-8'}
    try:
        checked=subprocess.run(['node','-e',_NODE,str(Path(__file__).resolve().parents[1]/'scripts/official_result_browser_capture.cjs')],
            input=payload,capture_output=True,timeout=12,env=env)
    except (OSError,subprocess.TimeoutExpired):raise ValueError('PRIOR_STATIC_CACHE_VALIDATOR_UNAVAILABLE') from None
    need(checked.returncode==0 and checked.stdout==b'OK','STATIC_CACHE_POLICY')
    return deepcopy([item for item in entries if _url(item['metadata']['source_url'])[0] in sports])


def _source(entry,files,*,started,completed):
    raw=files[entry['body_file']];meta=read_json_bytes(files[entry['metadata_file']])
    need(type(meta) is dict and type(meta.get('headers')) is dict,'STATIC_SOURCE_METADATA')
    continuation.probe.no_known_denial(meta)
    mime=[v for k,v in meta['headers'].items() if type(k) is str and k.lower()=='content-type']
    need(len(mime)==1 and type(mime[0]) is str and mime[0] and all(type(k) is str and type(v) is str
        for k,v in meta['headers'].items()),'STATIC_SOURCE_HEADERS')
    need(entry.get('method') in ('GET','POST') and entry.get('resource_type') in ('document','xhr','fetch','script','stylesheet') and
        meta.get('source_url')==meta.get('final_url')==entry.get('url') and
        meta.get('method')==meta.get('http_method')==entry['method'] and meta.get('resource_type')==entry['resource_type'] and
        type(entry.get('status')) is int and entry['status']==meta.get('status')==200 and
        type(entry.get('byte_count')) is int and entry['byte_count']==meta.get('byte_count')==len(raw) and
        entry.get('source_sha256')==meta.get('source_sha256')==sha256(raw).hexdigest() and
        entry.get('content_type')==mime[0],'STATIC_SOURCE_WIRE_JOIN')
    _url(entry['url'])
    need(started<=clock(entry['request_started_at'])==clock(meta['fetched_at'])<=clock(entry['headers_received_at'])<=
        clock(entry['response_received_at'])==clock(entry['body_captured_at'])==clock(meta['response_received_at'])<=completed,
        'STATIC_SOURCE_CLOCK')
    if entry['method']=='POST':
        request=files[entry['request_body_file']]
        need(entry.get('request_body_sha256')==meta.get('request_body_sha256')==sha256(request).hexdigest() and
            entry.get('request_content_type')==meta.get('request_content_type') and type(meta['request_content_type']) is str and
            meta['request_content_type'] and meta.get('request_body_file')==entry['request_body_file'],'STATIC_SOURCE_REQUEST')
    else:need(not any(k in entry or k in meta for k in ('request_body_file','request_body_sha256','request_content_type')),'STATIC_SOURCE_REQUEST')
    return dict(raw_base64=base64.b64encode(raw).decode(),metadata=meta)


def verified_browser_wire(journal,artifact_metadata,*,now,strict_http=False):
    """Replay already authenticated originals; this grants no source authority."""
    from scripts import all_existing_model_official_result_collect as collector
    now=clock(now);continuation._complete(journal,artifact_metadata,now,required=False)
    browser=journal.get('browser_attempt');q=journal.get('browser_quarantine')
    need(type(browser) is dict and browser.get('state')=='COMPLETE' and type(q) is dict and
        q.get('schema')=='RACE_AI_OFFICIAL_BROWSER_QUARANTINE_V1' and q.get('complete') is True and
        q.get('failure_code') is None and type(q.get('files')) is list and len(q['files'])<=128 and
        type(q.get('inventory')) is list and q.get('inventory_sha256')==digest(q['inventory']),'STATIC_COMPLETE_QUARANTINE')
    files={};kinds={};inventory=[];used=0;index=None;original=None
    limits={'HTTP_METADATA':65536,'REQUEST_BODY':16384,'RESPONSE_BODY':MAX_BODY,'RENDERED_DOM':MAX_BODY,
        'ORIGINAL_INDEX':MAX_BODY,'CANONICAL_RETURNED_OBJECT':MAX_BODY}
    for item in q['files']:
        need(type(item) is dict and set(item)=={'file','kind','byte_count','source_sha256','raw_base64'} and
            type(item['file']) is str and len(item['file'])<=240 and
            re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_-][A-Za-z0-9_.-]*)*',item['file']) and
            item['file'] not in files and item['kind'] in limits,'STATIC_QUARANTINE_FILE')
        raw=_raw(item['raw_base64'],limits[item['kind']]);used+=len(raw)
        need(type(item['byte_count']) is int and len(raw)==item['byte_count'] and used<=8*1024*1024 and
            sha256(raw).hexdigest()==item['source_sha256'],'STATIC_QUARANTINE_BYTES')
        files[item['file']]=raw;kinds[item['file']]=item['kind']
        inventory.append({k:item[k] for k in ('file','kind','byte_count','source_sha256')}|{'status':'RETAINED'})
        if item['kind'] in ('HTTP_METADATA','ORIGINAL_INDEX','CANONICAL_RETURNED_OBJECT'):
            document=read_json_bytes(raw);continuation.probe.no_known_denial(document)
            if item['kind']=='CANONICAL_RETURNED_OBJECT':
                need(index is None and item['file']=='returned-index.canonical.json','STATIC_RETURNED_INDEX');index=document
            elif item['kind']=='ORIGINAL_INDEX':
                need(original is None and item['file']=='capture-index.json','STATIC_ORIGINAL_INDEX');original=document
    need(inventory==q['inventory'] and q.get('referenced_file_count')==len(files) and q.get('retained_raw_bytes')==used and
        type(index) is dict and index==original and digest(index)==q.get('returned_index_sha256') and
        files['returned-index.canonical.json']==collector.future.wire(index),'STATIC_QUARANTINE_INVENTORY')
    planned=[dict(sport=c['sport'],race_id=c['race_id']) for c in journal['browser_index']['cases']]
    started=clock(browser['started_at']);completed=clock(browser['completed_at']);remaining=journal['maximum_requests']-len(journal['attempts'])
    collector._index_header(index,planned,started=started,now=completed,remaining=remaining)
    need(collector._index_diagnostic(index,planned)==journal['browser_index'],'STATIC_INDEX_PROJECTION')
    numbered=[e for e in index['ledger'] if 'sequence' in e];responses=index['responses']
    need(len(responses)==len(numbered) and {e['sequence']:e for e in responses}=={e['sequence']:e for e in numbered},'STATIC_LEDGER_SOURCE_JOIN')
    refs={'returned-index.canonical.json':'CANONICAL_RETURNED_OBJECT','capture-index.json':'ORIGINAL_INDEX'}
    for entry in responses:
        for field,kind in (('body_file','RESPONSE_BODY'),('metadata_file','HTTP_METADATA'),('request_body_file','REQUEST_BODY')):
            if field in entry:
                name=entry[field];need(name not in refs,'STATIC_DUPLICATE_FILE_REFERENCE');refs[name]=kind
    for case in index['cases']:
        if type(case.get('rendered_dom')) is dict:
            dom=case['rendered_dom'];name=dom['file'];need(name not in refs,'STATIC_DUPLICATE_FILE_REFERENCE');refs[name]='RENDERED_DOM'
            need(dom.get('byte_count')==len(files[name]) and dom.get('source_sha256')==sha256(files[name]).hexdigest() and
                started<=clock(dom['captured_at'])<=completed,'STATIC_DOM_ORIGINAL')
    need(refs==kinds,'STATIC_FILE_CLOSURE')
    assets=[_source(e,files,started=started,completed=completed) for e in responses]
    with tempfile.TemporaryDirectory(prefix='official-prior-static-') as directory:
        root=Path(directory);root.chmod(0o700)
        for name,raw in files.items():
            path=root/name;path.parent.mkdir(parents=True,mode=0o700,exist_ok=True);collector._write(path,raw)
        if strict_http:
            wire={e['sequence']:(files[e['body_file']],read_json_bytes(files[e['metadata_file']]),
                files[e['request_body_file']] if 'request_body_file' in e else None) for e in responses}
            collector._browser_complete_source_wire(index,wire,root,started=started,now=completed)
        found,states,originals=collector.browser_sources(index,root,planned,started=started,now=completed,remaining=remaining)
    need(originals==journal.get('browser_captures') and [r[2] for r in found]==[c for c in journal.get('captures',[])
        if _url(c['metadata']['source_url'])[0] in ('autorace','keirin')],'STATIC_CAPTURE_SOURCE_JOIN')
    actual={(c['sport'],collector._race_key(c['race_id'],c['sport'])):c for c in journal['cases']}
    for state in states:
        saved=actual.get((state['sport'],collector._race_key(state['race_id'],state['sport'])),{})
        need(saved.get('state')==state['state'] or state['state']=='CAPTURED' and
            saved.get('state') in ('settled','rank_confirmed','special','HOLD_RESULT_PARSE'),'STATIC_CASE_STATE_JOIN')
    return index,files,assets


def extract_static_cache(journal,artifact_metadata,*,now):
    """Validate the entire COMPLETE wire; a normal result is not required."""
    index,_,assets=verified_browser_wire(journal,artifact_metadata,now=now)
    sports={c['sport'] for c in index['cases']}
    return merge_static_cache([], [a for a in assets if a['metadata']['resource_type'] in ('script','stylesheet')],now=now,sports=sports)
