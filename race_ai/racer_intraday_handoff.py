"""Authenticated incremental SQLite packets on the existing transfer ref."""
from copy import deepcopy
from datetime import datetime,timezone
import hashlib,hmac,io,json,re
from .racer_daily import seal,unseal,clock,wire,sha,need
from .boat_pdca_state import state_key
from .boat_pdca_github_handoff import TRANSFER_REF
from .racer_daily_handoff import DailyStateRepository
from .racer_intraday import IntradayState,encode_packet,decode_packet

PREFIX='state/boat-racer-intraday/v1/'
LATEST=PREFIX+'latest.json'
HEAD='RACE_AI_RACER_INTRADAY_HEAD_V1'
PATH=re.compile(re.escape(PREFIX)+r'g([0-9]{6})/([a-f0-9]{64})\.enc\Z')

def _mac(doc,key):return hmac.new(state_key('production',key),(HEAD+'\n'+wire(doc)).encode(),hashlib.sha256).hexdigest()
def _head(raw,key):
    doc=json.loads(raw);unsigned={k:v for k,v in doc.items() if k!='mac'}
    need(set(doc)=={'schema','as_of','head','cipher_path','catalogue_sha256','mac'} and doc['schema']==HEAD and hmac.compare_digest(_mac(unsigned,key),doc['mac']),'INTRADAY_HEAD_AUTHENTICATION')
    need(raw==(wire(doc)+'\n').encode(),'INTRADAY_HEAD_ENCODING');clock(doc['as_of']);h=doc['head'];g=h['generation'];m=PATH.fullmatch(doc['cipher_path'])
    need(type(g) is int and 1<=g<=999999 and m and int(m[1])==g and m[2]==h['cipher_sha256'] and re.fullmatch('[a-f0-9]{64}',doc['catalogue_sha256']),'INTRADAY_HEAD_IDENTITY')
    return doc

def _history(git,parent,current,key):
    """Batch small head reads; never fetch all inherited ciphertext blobs.

    Raw changes across every merge parent expose deleted/replaced ciphertext.
    Every distinct signed head is authenticated, ordered by generation, and
    matched to its immutable blob in the current tree. Reverts cannot hide a
    later generation, and unrelated merges can repeat the identical head.
    """
    changes=git._run(['log','--full-history','-m','--no-renames','--raw','--abbrev=40','--format=',parent,'--',PREFIX]).decode().splitlines()
    blobs=set();ciphers={}
    for line in changes:
        if not line.startswith(':'):continue
        columns,tab,path=line.partition('\t');fields=columns.split();need(tab and len(fields)==5,'INTRADAY_HISTORY_FORMAT')
        oldmode,newmode,old,new,status=fields
        if path==LATEST:
            need(status!='D','INTRADAY_HISTORY_DELETION')
            blobs.update(v for v in (old,new) if v!='0'*40)
        else:
            need(PATH.fullmatch(path) and status=='A' and newmode=='100644','INTRADAY_HISTORY_CIPHER_REWRITE')
            need(path not in ciphers or ciphers[path]==new,'INTRADAY_HISTORY_CIPHER_REWRITE');ciphers[path]=new
    need(blobs and len(blobs)<=100000,'INTRADAY_HISTORY_REQUIRED')
    tree=git._run(['ls-tree','-r',parent,'--',PREFIX]).decode().splitlines();retained={}
    for line in tree:
        meta,tab,path=line.partition('\t');mode,kind,oid=meta.split();need(tab and mode=='100644' and kind=='blob' and (path==LATEST or PATH.fullmatch(path)),'INTRADAY_HISTORY_TREE')
        if path!=LATEST:retained[path]=oid
    need(retained==ciphers,'INTRADAY_HISTORY_CIPHER_MISSING')
    present=set(git._run(['cat-file','--batch-all-objects','--batch-check=%(objectname)']).decode().splitlines())
    missing=sorted(blobs-present)
    for offset in range(0,len(missing),512):
        git._run(['fetch','--no-tags','--no-write-fetch-head','--stdin',git.fetch_url],body=('\n'.join(missing[offset:offset+512])+'\n').encode())
    order=sorted(blobs);output=git._run(['cat-file','--batch'],body=('\n'.join(order)+'\n').encode());stream=io.BytesIO(output);bygen={}
    for oid in order:
        info=stream.readline().split();need(len(info)==3 and info[0].decode()==oid and info[1]==b'blob','INTRADAY_HISTORY_OBJECT')
        size=int(info[2]);need(0<size<=16000,'INTRADAY_HISTORY_HEAD_BOUND');raw=stream.read(size);need(stream.read(1)==b'\n','INTRADAY_HISTORY_OBJECT')
        d=_head(raw,key);g=d['head']['generation'];need(g not in bygen or bygen[g]==d,'INTRADAY_HISTORY_FORK');bygen[g]=d
    generation=current['head']['generation'];need(set(bygen)==set(range(1,generation+1)) and len(ciphers)==generation and bygen[generation]==current,'INTRADAY_HISTORY_ROLLBACK')
    previous=None;at=None
    for g in range(1,generation+1):
        d=bygen[g];h=d['head'];stamp=clock(d['as_of'])
        need(d['cipher_path'] in ciphers and h['previous_cipher_sha256']==previous and (at is None or stamp>=at),'INTRADAY_HISTORY_CHAIN')
        previous=h['cipher_sha256'];at=stamp
    return {d['cipher_path']:d for d in bygen.values()}

def _resolve(control,path):
    if isinstance(control,dict):
        for k,v in control.items():
            if k=='packet' and v=='@self':control[k]=path
            else:_resolve(v,path)
    elif isinstance(control,list):
        for v in control:_resolve(v,path)
    return control

def load_intraday(repo,*,initialize=False,key=None,transport=None,now=None):
    state_key('production',key);now=clock(now or datetime.now(timezone.utc));git=transport or DailyStateRepository(repo,ref=TRANSFER_REF)
    need(git.ref==TRANSFER_REF,'INTRADAY_TRANSFER_REF');parent=git.head();need(parent,'INTRADAY_EXISTING_TRANSFER_REQUIRED');git.fetch(parent);previous=None;raw=None;heads={};packets={}
    if git.exists(parent,LATEST):
        raw=git.read(parent,LATEST,16000);previous=_head(raw,key);need(clock(previous['as_of'])<=now,'INTRADAY_CLOCK_REGRESSION');heads=_history(git,parent,previous,key)
        def read(path):
            need(path in heads,'INTRADAY_PACKET_MEMBERSHIP')
            if path not in packets:
                doc=heads[path];plain=unseal(git.read(parent,path,32*1024*1024),doc['head'],key=key);packets[path]=decode_packet(plain)
            return packets[path]
        current=read(previous['cipher_path']);control=_resolve(deepcopy(current['control']),previous['cipher_path'])
        def loader(pointer):
            packet=read(pointer['packet']);found=[c for c in packet['captures'] if c.get('id')==pointer['capture_id']]
            need(len(found)==1,'INTRADAY_CAPTURE_MEMBERSHIP');return found[0]
        state=IntradayState(control,loader=loader)
    else:
        need(initialize is True,'INTRADAY_INITIALIZATION_REQUIRED')
        need(not git._run(['ls-tree','-r','--name-only',parent,'--',PREFIX]).strip() and not git._run(['log','-1','--format=%H',parent,'--',LATEST]).strip(),'INTRADAY_MISSING_STATE_MUST_NOT_RESET')
        state=IntradayState()
    return dict(git=git,parent=parent,previous=previous,previous_raw=raw,state=state)

def save_intraday(loaded,*,catalogue_sha256,now,key=None):
    need(re.fullmatch('[a-f0-9]{64}',catalogue_sha256),'INTRADAY_CATALOGUE_HASH');now=clock(now);prior=loaded['previous'];generation=prior['head']['generation']+1 if prior else 1
    need(prior is None or now>=clock(prior['as_of']),'INTRADAY_CLOCK_REGRESSION')
    state=loaded['state'];plain=encode_packet(state.control,state.new_captures)
    cipher,head=seal(plain,generation=generation,previous=prior['head']['cipher_sha256'] if prior else None,key=key);path=PREFIX+f'g{generation:06d}/'+head['cipher_sha256']+'.enc'
    doc=dict(schema=HEAD,as_of=now.isoformat(),head=head,cipher_path=path,catalogue_sha256=catalogue_sha256);doc['mac']=_mac(doc,key);files={path:cipher,LATEST:(wire(doc)+'\n').encode()};git=loaded['git']
    for attempt in range(4):
        parent=git.head();need(parent,'INTRADAY_TRANSFER_DISAPPEARED');git.fetch(parent);current=git.read(parent,LATEST,16000) if git.exists(parent,LATEST) else None
        need(current==loaded['previous_raw'],'INTRADAY_CONCURRENT_WRITER');commit=git.commit(files,parent)
        try:git.push(commit,parent);break
        except ValueError:
            if attempt==3:raise
    need(git.read(commit,LATEST,16000)==files[LATEST] and git.read(commit,path,32*1024*1024)==cipher,'INTRADAY_STATE_READBACK')
    return dict(status='INTRADAY_ENCRYPTED_DELTA_RETAINED',generation=generation,source_commit=commit,cipher_path=path,cipher_sha256=head['cipher_sha256'],packet_bytes=len(plain),new_capture_count=len(state.new_captures),plaintext_published=False)
