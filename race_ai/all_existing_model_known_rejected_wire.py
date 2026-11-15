"""Count-only replay of an authenticated data-rejected browser original.

The caller authenticates the journal MAC and artifact receipt. This function
never changes its REJECTED state and grants no source, cache, or result use.
"""
import base64
from datetime import timedelta
from hashlib import sha256
from pathlib import Path,PurePosixPath
import tempfile
from .actions_contract import digest
from . import all_existing_model_official_recovery as probe
from .permissioned_source_delivery import read_json_bytes


def known_data_rejected_wire(body,artifact_metadata,*,now):
    from scripts import all_existing_model_official_result_collect as collector
    need=probe.need;clock=probe.clock;now=clock(now)
    need(type(body) is dict and type(artifact_metadata) is dict,'REJECTED_WIRE_SCHEMA')
    probe.no_known_denial(body)
    browser=body.get('browser_attempt');failure=body.get('browser_failure');q=body.get('browser_quarantine')
    need(type(browser) is dict and browser.get('state')=='REJECTED' and type(failure) is dict and
        failure.get('stage')=='SOURCE_VALIDATION' and body.get('attempts')==[], 'REJECTED_SOURCE_VALIDATION_REQUIRED')
    count=browser.get('actual_request_count');maximum=body.get('maximum_requests')
    need(type(count) is int and type(maximum) is int and 1<=count<=maximum<=32,'REJECTED_WIRE_COUNT')
    epoch=clock(body['epoch_started_at']);started=clock(browser['started_at']);completed=clock(browser['completed_at'])
    need(epoch<=started<=completed<=min(now,clock(artifact_metadata['created_at'])+timedelta(seconds=1)),'REJECTED_WIRE_CLOCK')
    need(type(q) is dict and q.get('schema')=='RACE_AI_OFFICIAL_BROWSER_QUARANTINE_V1' and
        q.get('complete') is True and q.get('failure_code') is None and type(q.get('files')) is list and
        len(q['files'])<=128 and type(q.get('inventory')) is list and q.get('inventory_sha256')==digest(q['inventory']),
        'REJECTED_WIRE_QUARANTINE')
    limits={'HTTP_METADATA':65536,'REQUEST_BODY':16384,'RESPONSE_BODY':collector.MAX_BYTES,
        'RENDERED_DOM':collector.MAX_BYTES,'ORIGINAL_INDEX':collector.MAX_BYTES,'CANONICAL_RETURNED_OBJECT':collector.MAX_BYTES}
    files={};kinds={};inventory=[];used=0;index=None;original=None
    for item in q['files']:
        need(type(item) is dict and set(item)=={'file','kind','byte_count','source_sha256','raw_base64'} and
            type(item['file']) is str and 0<len(item['file'])<=240 and item['kind'] in limits and
            item['file'] not in files and not PurePosixPath(item['file']).is_absolute() and
            '..' not in PurePosixPath(item['file']).parts and PurePosixPath(item['file']).as_posix()==item['file'],
            'REJECTED_WIRE_FILE')
        encoded=item['raw_base64'];limit=limits[item['kind']]
        need(type(encoded) is str and len(encoded)<=4*((limit+2)//3),'REJECTED_WIRE_FILE_BOUND')
        try:raw=base64.b64decode(encoded,validate=True)
        except (ValueError,TypeError):raise ValueError('REJECTED_WIRE_BASE64') from None
        used+=len(raw)
        need(base64.b64encode(raw).decode()==encoded and type(item['byte_count']) is int and
            len(raw)==item['byte_count']<=limit and used<=8*1024*1024 and sha256(raw).hexdigest()==item['source_sha256'],
            'REJECTED_WIRE_BYTES')
        files[item['file']]=raw;kinds[item['file']]=item['kind']
        inventory.append({k:item[k] for k in ('file','kind','byte_count','source_sha256')}|{'status':'RETAINED'})
        if item['kind'] in ('HTTP_METADATA','ORIGINAL_INDEX','CANONICAL_RETURNED_OBJECT'):
            document=read_json_bytes(raw);probe.no_known_denial(document)
            if item['kind']=='CANONICAL_RETURNED_OBJECT':
                need(index is None and item['file']=='returned-index.canonical.json','REJECTED_RETURNED_INDEX');index=document
            elif item['kind']=='ORIGINAL_INDEX':
                need(original is None and item['file']=='capture-index.json','REJECTED_ORIGINAL_INDEX');original=document
    need(inventory==q['inventory'] and type(q.get('referenced_file_count')) is int and q['referenced_file_count']==len(files) and
        type(q.get('retained_raw_bytes')) is int and q['retained_raw_bytes']==used and type(index) is dict and
        original==index and digest(index)==q.get('returned_index_sha256') and
        files['returned-index.canonical.json']==collector.future.wire(index),'REJECTED_WIRE_INVENTORY')
    need(type(body.get('browser_index')) is dict and type(body['browser_index'].get('cases')) is list,'REJECTED_INDEX_REQUIRED')
    planned=[dict(sport=c['sport'],race_id=c['race_id']) for c in body['browser_index']['cases']]
    collector._index_header(index,planned,started=started,now=completed,remaining=maximum)
    need(index['actual_request_count']==count and collector._index_diagnostic(index,planned)==body['browser_index'],
        'REJECTED_WIRE_INDEX_PROJECTION')
    refs={'returned-index.canonical.json':'CANONICAL_RETURNED_OBJECT','capture-index.json':'ORIGINAL_INDEX'}
    for entry in index['responses']:
        for field,kind in (('body_file','RESPONSE_BODY'),('metadata_file','HTTP_METADATA'),('request_body_file','REQUEST_BODY')):
            if field in entry:
                need(entry[field] not in refs,'REJECTED_WIRE_DUPLICATE_REFERENCE');refs[entry[field]]=kind
    for case in index['cases']:
        if type(case.get('rendered_dom')) is dict:
            name=case['rendered_dom']['file'];need(name not in refs,'REJECTED_WIRE_DUPLICATE_REFERENCE');refs[name]='RENDERED_DOM'
    need(refs==kinds,'REJECTED_WIRE_FILE_CLOSURE')
    with tempfile.TemporaryDirectory(prefix='known-data-rejected-wire-') as folder:
        root=Path(folder);root.chmod(0o700)
        for name,raw in files.items():
            path=root/name;path.parent.mkdir(parents=True,mode=0o700,exist_ok=True);collector._write(path,raw)
        responses={entry['sequence']:(files[entry['body_file']],read_json_bytes(files[entry['metadata_file']]),
            files[entry['request_body_file']] if 'request_body_file' in entry else None) for entry in index['responses']}
        collector._browser_complete_source_wire(index,responses,root,started=started,now=completed)
    return dict(state='WIRE_KNOWN_DATA_REJECTED',actual_request_count=count,source_data_admitted=False,
        reusable_static_cache_granted=False,original_journal_sha256=digest(body),
        original_index_sha256=sha256(files['capture-index.json']).hexdigest())
