"""Opt-in encrypted Git publication and pinned production readback.

No secret creation/registration, plaintext publication, source crawling, bets or
live-worker changes. Production publication requires the existing owner key.
The state ref is separate from main/PR refs; every generation is immutable.
"""
from contextlib import closing
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.request import Request,build_opener

from .actions_contract import digest
from .boat_history_store import wire,instant
from .boat_history_comparison import load_pair,read_freeze_receipt
from .boat_pdca_state import PdcaState,restore_state,state_key,scope_for,sha,need,MAX_CIPHER
from .permissioned_source_delivery import NoRedirect
from scripts.boat_history_collect import private_root,save

REPO='haji84/RACE-AI'
STATE_REF='state/boat-pdca-encrypted-history'
TRANSFER_REF='state/boat-pdca-transfer'
HEAD_PATH='state/boat-pdca/v1/latest.json'
INPUT_SCHEMA='RACE_AI_BOAT_PRODUCTION_STATE_INPUT_V1'


class GitStateRepository:
    def __init__(self,repo,*,ref=STATE_REF):
        need(ref in (STATE_REF,TRANSFER_REF),'STATE_REF_NOT_ALLOWED');self.ref=ref
        self.repo=Path(repo).resolve();self._reject_rewrites();self._check_remote()

    def _reject_rewrites(self,env=None):
        result=subprocess.run(['git','config','--get-regexp',r'^url\..*\.(insteadof|pushinsteadof)$'],
            cwd=self.repo,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15,env=env)
        need(result.returncode in (0,1),'STATE_GIT_CONFIG_INSPECTION_FAILED')
        # Passing a once-expanded URL back to Git applies rewrites again. Reject
        # them instead of changing inherited credential helpers or auth headers.
        need(result.returncode==1,'STATE_GIT_URL_REWRITES_REJECTED')

    def _run(self,args,*,body=None,env=None):
        if args and args[0] in ('ls-remote','fetch','push'):self._reject_rewrites(env)
        result=subprocess.run(['git',*args],cwd=self.repo,input=body,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,timeout=180 if args and args[0]=='fetch' else 60,env=env)
        need(result.returncode==0,'STATE_GIT_OPERATION_FAILED');return result.stdout

    def _check_remote(self):
        fetch=self._run(['remote','get-url','--all','origin']).decode().splitlines()
        push=self._run(['remote','get-url','--push','--all','origin']).decode().splitlines()
        allowed={'https://github.com/'+REPO,'https://github.com/'+REPO+'.git','git@github.com:'+REPO+'.git'}
        need(len(fetch)==len(push)==1 and fetch[0] in allowed and push[0] in allowed,'STATE_GIT_REPOSITORY_REJECTED')
        self.fetch_url=fetch[0];self.push_url=push[0]

    def head(self):
        raw=self._run(['ls-remote','--heads',self.fetch_url,'refs/heads/'+self.ref]).decode().strip()
        if not raw:return None
        m=re.fullmatch(r'([a-f0-9]{40})\s+refs/heads/'+re.escape(self.ref),raw)
        need(m is not None,'STATE_REF_IDENTITY_INVALID');return m[1]

    def fetch(self,commit):
        need(type(commit) is str and re.fullmatch('[a-f0-9]{40}',commit),'STATE_COMMIT_INVALID')
        # Keep the exact object locally reachable so the next pinned dataset
        # fetch can negotiate its already-restored monthly ancestors. These
        # private local refs are never pushed or used as trusted remote heads.
        self._run(['fetch','--no-tags','--no-write-fetch-head',self.fetch_url,
                   commit+':refs/race-ai/pinned-state/'+commit])

    def read(self,commit,path,limit):
        need(re.fullmatch('[a-f0-9]{40}',commit) is not None,'STATE_COMMIT_INVALID')
        object_id=commit+':'+path
        size=int(self._run(['cat-file','-s',object_id]));need(0<size<=limit,'STATE_GIT_BLOB_BOUND_EXCEEDED')
        raw=self._run(['show',object_id]);need(len(raw)==size,'STATE_GIT_BLOB_SIZE_CHANGED');return raw

    def exists(self,commit,path):
        result=subprocess.run(['git','cat-file','-e',commit+':'+path],cwd=self.repo,
                              stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)
        return result.returncode==0

    def commit(self,files,parent):
        with tempfile.TemporaryDirectory(prefix='boat-cipher-index-') as folder:
            env=dict(os.environ,GIT_INDEX_FILE=str(Path(folder)/'index'))
            self._run(['read-tree',parent] if parent else ['read-tree','--empty'],env=env)
            for path,raw in sorted(files.items()):
                blob=self._run(['hash-object','-w','--stdin'],body=raw,env=env).decode().strip()
                self._run(['update-index','--add','--cacheinfo','100644,'+blob+','+path],env=env)
            tree=self._run(['write-tree'],env=env).decode().strip()
            args=['-c','user.name=RACE-AI encrypted state','-c','user.email=race-ai-state@users.noreply.github.com',
                  '-c','commit.gpgSign=false','commit-tree',tree]
            if parent:args+=['-p',parent]
            return self._run(args,body=b'Retain authenticated encrypted BOAT state generation\n',env=env).decode().strip()

    def push(self,commit,parent):
        need(self.head()==parent,'STATE_REF_CONCURRENT_UPDATE')
        # A normal fast-forward push also rejects a concurrent divergent writer.
        self._run(['push',self.push_url,commit+':refs/heads/'+self.ref])
        need(self.head()==commit,'STATE_REMOTE_COMMIT_NOT_VERIFIED')


def _cipher_path(scope):
    need(1<=scope['generation']<=999999,'STATE_GENERATION_BOUND_EXCEEDED')
    return f"state/boat-pdca/v1/g{scope['generation']:06d}/state.enc"


def _scope(scope):
    need(type(scope) is dict and scope==scope_for(scope['mode'],scope['generation'],scope['previous_cipher_sha256'])
         and scope['mode']=='production','PRODUCTION_STATE_SCOPE_REQUIRED')
    return scope


def _no_regression(previous,current):
    previous.verify_files();current.verify_files()
    for table in ('files','pairs','results','scores'):
        old=set(previous.db.execute('SELECT * FROM '+table))
        new=set(current.db.execute('SELECT * FROM '+table))
        need(old<=new,'STATE_REGRESSION_'+table.upper())
    need({r[0] for r in previous.db.execute('SELECT sha FROM blobs')}<=
         {r[0] for r in current.db.execute('SELECT sha FROM blobs')},'STATE_REGRESSION_BLOBS')
    old_heads=dict(previous.db.execute('SELECT name,sha FROM heads'))
    need(set(old_heads)<={r[0] for r in current.db.execute('SELECT name FROM heads')},'STATE_REGRESSION_HEAD_NAMES')
    versions=set(previous.db.execute('SELECT name,sha FROM files'))
    for name,value in current.db.execute('SELECT name,sha FROM heads'):
        need(name not in old_heads or old_heads[name]==value or (name,value) not in versions,'STATE_REGRESSION_HEAD')


def _audit(state,root,now):
    clock=instant(now);before=state.inventory();content_id=state.content_sha256();state.materialize(root/'materialized')
    pairs={}
    for ident, in state.db.execute('SELECT sha FROM pairs'):
        path=root/'materialized/pairs'/f'{ident}.json';pair=load_pair(path);receipt=read_freeze_receipt(path,pair)
        need(all(pair[v]['snapshot']['scope']=='OPERATOR_SUPPLIED_RESEARCH' for v in ('baseline','history')),
             'PRODUCTION_READBACK_REFUSES_SYNTHETIC_PAIRS')
        need(instant(receipt['write_completed_at'])<=clock,'STATE_FREEZE_FROM_FUTURE');pairs[ident]=pair
    need(pairs,'STATE_REGRESSION_EMPTY_OR_MISSING_PAIRS')
    need(all(instant(r[0])<=clock for r in state.db.execute('SELECT captured_at FROM results')),'STATE_RESULT_FROM_FUTURE')
    replays=0
    for ident, in state.db.execute('SELECT DISTINCT pair_sha FROM scores').fetchall():
        pair=pairs[ident]
        latest=state.db.execute('SELECT sha,body FROM results WHERE race_id=? ORDER BY captured_at DESC LIMIT 1',
                               (pair['race_id'],)).fetchone()
        need(latest is not None and state.db.execute('SELECT 1 FROM scores WHERE pair_sha=? AND result_sha=?',
             (ident,latest[0])).fetchone() is not None,'STATE_LATEST_RESULT_NOT_SCORED')
        need(state.score(ident,json.loads(latest[1]),clock)['reused'] is True,'STATE_SCORE_REPLAY_NOT_IDEMPOTENT');replays+=1
    need(state.inventory()==before and state.content_sha256()==content_id,'STATE_READBACK_CHANGED_INVENTORY')
    from .boat_history_prospective import verify_retained_trials
    admitted=verify_retained_trials(state,root/'materialized',clock)
    return dict(before,pairs_verified=len(pairs),score_replays=replays,original_bytes_verified=True,
                state_content_sha256=content_id,
                accuracy_improvement_proven=False,independent_pre_cutoff_receipt_verified=False,**admitted)


def publish_checkpoint(state_path,repo,output,*,initialize=False,expected_parent=None,key=None,transport=None,now=None):
    key=state_key('production',key)  # Before Git access or creation of an output.
    state=PdcaState(state_path);root=None
    try:
        need(state.mode=='production','PRODUCTION_STATE_REQUIRED')
        git=transport or GitStateRepository(repo);parent=git.head();generation=1;previous=None
        root=private_root(output);clock=now or datetime.now(timezone.utc)
        if parent is None:
            need(initialize is True and expected_parent is None,'STATE_TRUSTED_PARENT_OR_INITIALIZATION_REQUIRED')
        else:
            need(parent==expected_parent and expected_parent is not None,'STATE_TRUSTED_PARENT_REQUIRED')
            git.fetch(parent);old=json.loads(git.read(parent,HEAD_PATH,8192));old_scope=_scope(old['scope'])
            need(old['schema']=='RACE_AI_BOAT_ENCRYPTED_HEAD_V1' and old['repository_id']=='1416489937'
                 and old['cipher_path']==_cipher_path(old_scope),'STATE_PREVIOUS_HEAD_INVALID')
            previous=old['cipher_sha256'];save(root/'previous.enc',git.read(parent,old['cipher_path'],MAX_CIPHER))
            restored=restore_state(root/'previous.enc',root/'previous.sqlite',expected_sha256=previous,expected_scope=old_scope,key=key)
            try:_no_regression(restored,state)
            finally:restored.close()
            generation=old_scope['generation']+1
        proof=state.checkpoint(root,generation=generation,previous_cipher_sha256=previous,key=key)
        verified=restore_state(root/'state.enc',root/'verified.sqlite',expected_sha256=proof['cipher_sha256'],expected_scope=proof['scope'],key=key)
        try:_audit(verified,private_root(root/'verification'),clock)
        finally:verified.close()
        path=_cipher_path(proof['scope']);head=dict(schema='RACE_AI_BOAT_ENCRYPTED_HEAD_V1',repository_id='1416489937',
            scope=proof['scope'],cipher_path=path,cipher_sha256=proof['cipher_sha256'])
        if parent:
            need(not git.exists(parent,path) and not git.exists(parent,path.removesuffix('state.enc')+'proof.json'),
                 'STATE_GENERATION_ALREADY_EXISTS')
        commit=git.commit({path:(root/'state.enc').read_bytes(),path.removesuffix('state.enc')+'proof.json':(root/'proof.json').read_bytes(),
                           HEAD_PATH:(wire(head)+'\n').encode()},parent)
        git.push(commit,parent)
        need(git.read(commit,path,MAX_CIPHER)==(root/'state.enc').read_bytes(),'STATE_REMOTE_CIPHERTEXT_READBACK_MISMATCH')
        pointer=dict(schema=INPUT_SCHEMA,status='READY',repository_id='1416489937',source_commit=commit,
                     cipher_path=path,cipher_sha256=proof['cipher_sha256'],scope=proof['scope'])
        save(root/'production-input.json',(wire(pointer)+'\n').encode());return pointer
    finally:state.close()


def _fetch_cipher(url):
    with build_opener(NoRedirect()).open(Request(url,headers={'User-Agent':'RACE-AI-owner-encrypted-state-readback/1',
            'Accept':'application/json'}),timeout=30) as response:
        need(response.status==200 and response.geturl()==url,'STATE_CIPHERTEXT_SOURCE_REJECTED')
        raw=response.read(MAX_CIPHER+1)
    need(0<len(raw)<=MAX_CIPHER,'STATE_CIPHER_BOUND_EXCEEDED');return raw


def readback(pointer,root,*,key=None,fetch=None,now=None):
    try:key=state_key('production',key)
    except ValueError:return dict(status='HOLD_OWNER_STATE_KEY_MISSING',source_gets=0,production_schema_readback_verified=False)
    need(type(pointer) is dict and pointer.get('schema')==INPUT_SCHEMA and pointer.get('repository_id')=='1416489937',
         'STATE_INPUT_IDENTITY_INVALID')
    if pointer.get('status')=='WAITING_ENCRYPTED_INPUT':
        return dict(status='HOLD_ENCRYPTED_INPUT_REQUIRED',source_gets=0,production_schema_readback_verified=False)
    need(set(pointer)=={'schema','status','repository_id','source_commit','cipher_path','cipher_sha256','scope'} and
         pointer['status']=='READY','STATE_INPUT_FIELDS_INVALID')
    scope=_scope(pointer['scope'])
    need(type(pointer['source_commit']) is str and re.fullmatch('[a-f0-9]{40}',pointer['source_commit']) and
         pointer['cipher_path']==_cipher_path(scope) and type(pointer['cipher_sha256']) is str and
         re.fullmatch('[a-f0-9]{64}',pointer['cipher_sha256']),'STATE_INPUT_LOCATOR_INVALID')
    url='https://raw.githubusercontent.com/'+REPO+'/'+pointer['source_commit']+'/'+pointer['cipher_path']
    raw=(fetch or _fetch_cipher)(url)
    need(type(raw) is bytes and len(raw)<=MAX_CIPHER and sha(raw)==pointer['cipher_sha256'],'STATE_CIPHERTEXT_HASH_MISMATCH')
    root=private_root(root);save(root/'state.enc',raw)
    state=restore_state(root/'state.enc',root/'state.sqlite',expected_sha256=pointer['cipher_sha256'],expected_scope=scope,key=key)
    try:report=_audit(state,root,now or datetime.now(timezone.utc))
    finally:state.close()
    return dict(report,status='PRODUCTION_STATE_READBACK_VERIFIED',source_gets=1,source_commit=pointer['source_commit'],
                production_schema_readback_verified=True,plaintext_published=False)
