"""Append-only GitHub display feed encrypted to an independent owner recipient.

The runner needs only the public P-256 recipient. Neither the display private
key nor RACE_AI_STATE_KEY is read by the scheduled writer. Prior source and
forecast snapshots remain immutable encrypted Git objects.
"""
import base64
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from .keirin_note_view import canonical, _private_root, _create, MAX_VIEW, OUTER, SCHEMA

REPO='haji84/RACE-AI'
BRANCH='state/keirin-note-view'
INDEX='RACE_AI_KEIRIN_NOTE_FEED_V1'
RECIPIENT='RACE_AI_KEIRIN_NOTE_PUBLIC_RECIPIENT_V1'
INFO=b'RACE_AI_KEIRIN_NOTE_FEED_V1:'
MAX_WIRE=90*1024*1024


def need(ok,code):
    if not ok:raise ValueError('KEIRIN_NOTE_FEED_'+code)


def b64(raw):return base64.urlsafe_b64encode(raw).decode().rstrip('=')


def unb64(value):
    need(type(value) is str and re.fullmatch('[A-Za-z0-9_-]+',value),'BASE64')
    raw=base64.urlsafe_b64decode(value+'='*((-len(value))%4))
    need(b64(raw)==value,'BASE64');return raw


def checked_recipient(doc):
    from cryptography.hazmat.primitives.asymmetric import ec
    need(type(doc) is dict and set(doc)=={'schema','recipient_id','public_key'} and
         doc['schema']==RECIPIENT,'RECIPIENT')
    raw=unb64(doc['public_key']);need(len(raw)==65 and raw[0]==4 and
         sha256(raw).hexdigest()==doc['recipient_id'],'RECIPIENT_HASH')
    ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(),raw)
    return doc


def create_recipient(private_dir):
    """Explicit owner setup only. Never called from a scheduled collection."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    root=_private_root(private_dir)
    need(not any(root.iterdir()),'EXISTING_OWNER_CAPABILITY_PRESERVED')
    key=ec.generate_private_key(ec.SECP256R1())
    public=key.public_key().public_bytes(serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint)
    private=b64(key.private_bytes(serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    recipient=dict(schema=RECIPIENT,recipient_id=sha256(public).hexdigest(),public_key=b64(public))
    _create(root/'display-key.txt',(private+'\n').encode())
    _create(root/'owner-url.txt',('https://haji84.github.io/RACE-AI/#notefeed='+private+'\n').encode())
    return dict(public=recipient,private_key=str(root/'display-key.txt'),owner_url=str(root/'owner-url.txt'))


def _ids(values):
    need(type(values) is list and len(set(values))==len(values) and
         all(type(v) is str and re.fullmatch('20[0-9]{10}',v) for v in values),'RACE_IDS')
    return sorted(values)


def checked_entry(entry):
    fields={'cipher_sha256','source_content_sha256','ephemeral_public_key','salt',
            'created_at','days','kind','captured_race_ids','priority_window_race_ids'}
    need(type(entry) is dict, 'ENTRY')
    if entry.get('kind') == 'result': fields = fields | {'result_revisions'}
    need(set(entry)==fields and entry['kind'] in {'import','research','archive','result','results'},'ENTRY')
    for name in ('cipher_sha256','source_content_sha256'):
        need(type(entry[name]) is str and re.fullmatch('[a-f0-9]{64}',entry[name]),'ENTRY_HASH')
    need(len(unb64(entry['ephemeral_public_key']))==65 and len(unb64(entry['salt']))==32,'ENTRY_ECDH')
    need(type(entry['days']) is list and entry['days'] and
         all(type(d) is str and re.fullmatch('[0-9]{4}-[0-9]{2}-[0-9]{2}',d) for d in entry['days']),'DAYS')
    clock=datetime.fromisoformat(entry['created_at'].replace('Z','+00:00'))
    need(clock.utcoffset() is not None,'CLOCK')
    captured=_ids(entry['captured_race_ids']);priority=_ids(entry['priority_window_race_ids'])
    need(set(priority)<=set(captured),'PRIORITY_IDS')
    need(entry['kind']!='results' or not captured and not priority,'RESULTS_NOT_FORECAST_COVERAGE')
    if entry['kind'] == 'result':
        revisions = entry['result_revisions']
        need(type(revisions) is dict and 0 < len(revisions) <= 300 and
             not captured and not priority, 'RESULT_REVISIONS')
        _ids(list(revisions))
        need(all(type(v) is str and re.fullmatch('[a-f0-9]{64}',v) for v in revisions.values()), 'RESULT_REVISIONS')
    return entry


def result_clock(value):
    need(type(value) is str and re.fullmatch(
        r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)',value),'RESULT_CHECK_CLOCK')
    at=datetime.fromisoformat(value.replace('Z','+00:00'))
    return at


def checked_result_checks(checks):
    """Only opaque progress metadata belongs in the public display index."""
    need(type(checks) is dict,'RESULT_CHECKS')
    _ids(list(checks))
    for rid,row in checks.items():
        datetime.strptime(rid[:8],'%Y%m%d')
        need(type(row) is dict and set(row)=={'checked_at','digest','status'} and
             row['status'] in {'MATCHED','HOLD','PENDING'},'RESULT_CHECK_FIELDS')
        result_clock(row['checked_at'])
        need(row['digest'] is None or type(row['digest']) is str and
             re.fullmatch('[a-f0-9]{64}',row['digest']),'RESULT_CHECK_DIGEST')
        need(row['status']!='MATCHED' or row['digest'] is not None,'MATCHED_DIGEST_REQUIRED')
    return checks


def seal_snapshot(note,recipient,*,kind,captured_ids=(),priority_ids=(),clock=None):
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    checked_recipient(recipient)
    need(type(note) is dict and note.get('schema')==SCHEMA and
         note.get('formal_model_admission') is False and
         note.get('production_weight_switch') is False,'DISPLAY_SCOPE')
    if kind=='results':
        need(type(note.get('files')) is dict and all(type(path) is str and re.fullmatch(
            r'data/\d{4}-\d{2}-\d{2}/research_results\.json',path) and
            path.split('/')[1] in note['dates'] for path in note['files']),'RESULTS_ONLY_FILES')
    result_revisions = {}
    if kind == 'result':
        from .keirin_result_updates import checked_updates
        need(not captured_ids and not priority_ids and type(note.get('files')) is dict and
             bool(note['files']), 'RESULT_DISPLAY_ONLY')
        for path, value in note['files'].items():
            need(re.fullmatch(r'data/[0-9]{4}-[0-9]{2}-[0-9]{2}/result_updates\.json', path), 'RESULT_DISPLAY_ONLY')
            raw = value['text'].encode('utf-8')
            need(value['sha256'] == sha256(raw).hexdigest() and value['bytes'] == len(raw), 'RESULT_BYTES')
            updates = checked_updates(json.loads(raw))
            for row in updates['races']:
                need(row['race_id'] not in result_revisions, 'DUPLICATE_RESULT_RACE')
                result_revisions[row['race_id']] = row['revision']
        # Public per-race commitments cannot hide a guessable plaintext hash:
        # their values can simply be copied into a guessed result note. Add
        # independent entropy inside the encrypted plaintext only. The stable
        # public revisions still provide cross-run idempotency before sealing.
        # Existing imported/forecast packets and their encryption are unchanged.
        note = dict(note, result_private_nonce=b64(os.urandom(32)))
    plain=canonical(note);need(0<len(plain)<=MAX_VIEW,'PLAIN_BOUND')
    ephemeral=ec.generate_private_key(ec.SECP256R1())
    public=ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(),unb64(recipient['public_key']))
    salt=os.urandom(32)
    aes=HKDF(algorithm=hashes.SHA256(),length=32,salt=salt,
        info=INFO+recipient['recipient_id'].encode()).derive(ephemeral.exchange(ec.ECDH(),public))
    header=dict(schema=OUTER,source_content_sha256=sha256(plain).hexdigest());nonce=os.urandom(12)
    wire=canonical(dict(header=header,nonce=base64.b64encode(nonce).decode(),
        ciphertext=base64.b64encode(AESGCM(aes).encrypt(nonce,plain,canonical(header))).decode()))+b'\n'
    observed=(clock or (lambda:datetime.now(timezone.utc)))()
    need(isinstance(observed,datetime) and observed.utcoffset() is not None,'CLOCK')
    entry_values=dict(cipher_sha256=sha256(wire).hexdigest(),
        source_content_sha256=header['source_content_sha256'],
        ephemeral_public_key=b64(ephemeral.public_key().public_bytes(
            serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)),salt=b64(salt),
        created_at=observed.astimezone(timezone.utc).isoformat(),days=note['dates'],kind=kind,
        captured_race_ids=_ids(list(captured_ids)),priority_window_race_ids=_ids(list(priority_ids)))
    if kind == 'result': entry_values['result_revisions'] = result_revisions
    entry=checked_entry(entry_values)
    return dict(entry=entry,cipher=wire)


def checked_index(doc,recipient):
    checked_recipient(recipient)
    fields={'schema','repository','recipient_id','entries',
        'provider_denied','covered_race_ids','priority_window_race_ids'}
    need(type(doc) is dict and set(doc) in (fields,fields|{'result_checks'}) and
        doc['schema']==INDEX and doc['repository']==REPO and
        doc['recipient_id']==recipient['recipient_id'] and type(doc['provider_denied']) is bool and
        type(doc['entries']) is list,'INDEX')
    hashes=set();covered=set();priority=set()
    for entry in doc['entries']:
        checked_entry(entry);h=entry['cipher_sha256'];need(h not in hashes,'DUPLICATE_ENTRY');hashes.add(h)
        covered.update(entry['captured_race_ids']);priority.update(entry['priority_window_race_ids'])
    need(_ids(doc['covered_race_ids'])==sorted(covered) and
         _ids(doc['priority_window_race_ids'])==sorted(priority),'COVERAGE_INDEX')
    if 'result_checks' in doc:
        checked_result_checks(doc['result_checks'])
        days={d.replace('-','') for entry in doc['entries'] for d in entry['days']}
        need(all(rid[:8] in days for rid in doc['result_checks']),'RESULT_CHECK_DAY_OUTSIDE_HISTORY')
    return doc


def append_index(previous,recipient,*,entry=None,denied=False,result_checks=None):
    doc=json.loads(canonical(checked_index(previous,recipient))) if previous is not None else dict(
        schema=INDEX,repository=REPO,recipient_id=checked_recipient(recipient)['recipient_id'],entries=[],
        provider_denied=False,covered_race_ids=[],priority_window_race_ids=[])
    # A denial latch is persistent across dates and subsequent successful ticks.
    # Publishing an already captured result does not issue a provider request.
    # Input acquisition remains latched in cycle(); this never clears the latch.
    need(not doc['provider_denied'] or entry is None or
         entry.get('kind') == 'result', 'PREVIOUS_PROVIDER_DENIAL_NO_RETRY')
    if entry is not None:
        checked_entry(entry);need(entry['cipher_sha256'] not in {r['cipher_sha256'] for r in doc['entries']},'DUPLICATE_ENTRY')
        doc['entries'].append(entry)
        doc['covered_race_ids']=sorted(set(doc['covered_race_ids'])|set(entry['captured_race_ids']))
        doc['priority_window_race_ids']=sorted(set(doc['priority_window_race_ids'])|set(entry['priority_window_race_ids']))
    doc['provider_denied']=doc['provider_denied'] or denied
    if result_checks is not None:
        checked_result_checks(result_checks)
        need(not previous or not previous['provider_denied'],'PREVIOUS_PROVIDER_DENIAL_NO_RETRY')
        prior=doc.get('result_checks',{})
        for rid,row in result_checks.items():
            old=prior.get(rid)
            need(old is None or result_clock(row['checked_at'])>result_clock(old['checked_at']) or
                 row==old,'RESULT_CHECK_CLOCK_BACKWARD_OR_CONFLICT')
        doc['result_checks']={**prior,**result_checks}
    return checked_index(doc,recipient)


class NoteFeedGit:
    """Fixed canonical display branch; normal FF CAS, isolated temporary index."""
    ref=BRANCH
    def __init__(self,repo):self.repo=Path(repo);self.remote=self._remote()

    def run(self,args,*,body=None,env=None):
        r=subprocess.run(['git',*args],cwd=self.repo,input=body,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,timeout=90,env=env)
        need(r.returncode==0,'GIT_OPERATION_FAILED');return r.stdout

    def _remote(self):
        fetch=self.run(['remote','get-url','--all','origin']).decode().splitlines()
        push=self.run(['remote','get-url','--push','--all','origin']).decode().splitlines()
        allowed={'https://github.com/'+REPO+'.git','https://github.com/'+REPO,
                 'git@github.com:'+REPO+'.git'}
        need(len(fetch)==len(push)==1 and fetch[0] in allowed and push[0] in allowed,
             'CANONICAL_REMOTE_REQUIRED');return 'origin'

    def head(self):
        rows=self.run(['ls-remote',self.remote,'refs/heads/'+self.ref]).decode().splitlines()
        need(len(rows)<=1,'REMOTE_HEAD');return rows[0].split()[0] if rows else None

    def fetch(self,head):
        need(re.fullmatch('[a-f0-9]{40}',head),'COMMIT');self.run(['fetch','--no-tags',self.remote,head])

    def read(self,head,path):
        need(path=='index.json' or re.fullmatch(r'views/[a-f0-9]{64}\.json',path),'PATH')
        size=int(self.run(['cat-file','-s',head+':'+path]));need(0<size<=MAX_WIRE,'BLOB_BOUND')
        body=self.run(['show',head+':'+path]);need(len(body)==size,'BLOB_SIZE');return body

    def tree(self,head):
        rows=self.run(['ls-tree','-r','--format=%(objectmode)\t%(path)',head]).decode().splitlines()
        paths=[]
        for row in rows:
            mode,_,p=row.partition('\t');need(mode=='100644' and (p=='index.json' or
                re.fullmatch(r'views/[a-f0-9]{64}\.json',p)),'UNEXPECTED_TREE');paths.append(p)
        return paths

    def commit(self,files,parent):
        with tempfile.TemporaryDirectory(prefix='keirin-display-index-') as folder:
            env=dict(os.environ,GIT_INDEX_FILE=str(Path(folder)/'index'))
            self.run(['read-tree',parent] if parent else ['read-tree','--empty'],env=env)
            for path,body in sorted(files.items()):
                blob=self.run(['hash-object','-w','--stdin'],body=body,env=env).decode().strip()
                self.run(['update-index','--add','--cacheinfo','100644,'+blob+','+path],env=env)
            tree=self.run(['write-tree'],env=env).decode().strip()
            args=['-c','user.name=RACE-AI encrypted display','-c','user.email=race-ai-state@users.noreply.github.com',
                  '-c','commit.gpgSign=false','commit-tree',tree]
            if parent:args+=['-p',parent]
            return self.run(args,body=b'Retain owner-only encrypted KEIRIN display snapshot\n',env=env).decode().strip()

    def push(self,commit,parent):
        need(self._remote()==self.remote,'REMOTE_CHANGED')
        need(self.head()==parent,'CONCURRENT_UPDATE')
        self.run(['push',self.remote,commit+':refs/heads/'+self.ref])
        need(self.head()==commit,'REMOTE_READBACK')


def load_index(store,recipient,parent):
    if parent is None:return None
    store.fetch(parent);paths=store.tree(parent)
    doc=checked_index(json.loads(store.read(parent,'index.json')),recipient)
    need(set(paths)=={'index.json'}|{'views/'+e['cipher_sha256']+'.json' for e in doc['entries']},'INDEX_TREE_MISMATCH')
    for entry in doc['entries']:
        h=entry['cipher_sha256']
        need(sha256(store.read(parent,'views/'+h+'.json')).hexdigest()==h,'RETAINED_CIPHERTEXT_SHA')
    return doc


def publish_snapshot(store,recipient,snapshot=None,*,expected_parent,denied=False,result_checks=None):
    need(store.head()==expected_parent,'CONCURRENT_UPDATE')
    prior=load_index(store,recipient,expected_parent)
    entry=snapshot['entry'] if snapshot else None
    if result_checks:
        previous=(prior or {}).get('result_checks',{})
        changed=any(rid not in previous or row['digest']!=previous[rid]['digest'] or
            row['status']!=previous[rid]['status'] for rid,row in checked_result_checks(result_checks).items())
        need(not changed or entry is not None and entry.get('kind')=='results',
             'RESULT_FACT_CHANGE_REQUIRES_ENCRYPTED_DELTA')
    index=append_index(prior,recipient,entry=entry,denied=denied,result_checks=result_checks)
    files={'index.json':canonical(index)+b'\n'}
    before=store.run(['ls-tree','-r',expected_parent,'--','views']) if expected_parent else b''
    if snapshot:
        body=snapshot['cipher'];need(sha256(body).hexdigest()==entry['cipher_sha256'],'CIPHER_SHA')
        files['views/'+entry['cipher_sha256']+'.json']=body
    commit=store.commit(files,expected_parent);paths=store.tree(commit)
    need(set(paths)=={'index.json'}|{'views/'+e['cipher_sha256']+'.json' for e in index['entries']},'NEW_TREE')
    if expected_parent:
        after=store.run(['ls-tree','-r',commit,'--','views'])
        need(all(line in after.splitlines() for line in before.splitlines()),'CIPHERTEXT_HISTORY_CHANGED')
    store.push(commit,expected_parent)
    for path,body in files.items():need(store.read(commit,path)==body,'REMOTE_BYTES')
    return dict(state='KEIRIN_NOTE_ENCRYPTED_GIT_READBACK_VERIFIED',source_commit=commit,
        entries=len(index['entries']),provider_denied=index['provider_denied'],
        covered_races=len(index['covered_race_ids']),priority_window_races=len(index['priority_window_race_ids']),
        private_plaintext_uploaded=False,production_state_key_used=False)
