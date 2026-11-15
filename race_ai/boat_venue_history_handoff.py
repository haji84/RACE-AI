"""Owner-authenticated monthly history on the existing encrypted transfer ref.

No raw publication, new branch/schedule or canonical PDCA-pointer changes.
The frozen collection MAC and every AES scope/hash are checked before publish;
all prior generations and unrelated transfer files remain in the Git tree.
"""
import hashlib,hmac,json,re
from pathlib import Path

from .teiai_history import need
from .actions_contract import stamp
from .boat_pdca_github_handoff import GitStateRepository,TRANSFER_REF
from scripts.boat_venue_history import _manifest_mac,restore_month,_scope
from scripts.boat_all_racers import _read,_write,_key_ready

PREFIX='state/boat-venue-history/v1/'
LATEST=PREFIX+'latest.json'
SCHEMA='RACE_AI_BOAT_VENUE_COLLECTION_INPUT_V1'
DATED_SCHEMA='RACE_AI_ALL_PUBLISHED_HISTORY_PROGRESS_V2'

def _dated_structure(s):
    """Recognize a bounded V2 locator; encrypted inventory is still required."""
    required={'schema','months','menu_sha256','captured_at','not_after','heads',
              'inventory_captured_at','inventory_lineage'}
    need(set(s) in (required,required|{'full_archive_validation'}),'VENUE_DATED_COLLECTION_FIELDS_INVALID')
    from .boat_history_dated_inventory import validate_ancestral_metadata
    validate_ancestral_metadata(s)
    lineage=s['inventory_lineage']
    need(type(lineage) is list and 1<=len(lineage)<=512 and
         type(s['menu_sha256']) is str and re.fullmatch('[a-f0-9]{64}',s['menu_sha256']) and
         stamp(s['captured_at'])<=stamp(s['inventory_captured_at']),
         'VENUE_DATED_COLLECTION_LINEAGE_INVALID')
    folders=set()
    for item in lineage:
        need(type(item) is dict and set(item)=={'folder','parent_manifest_sha256','inventory_captured_at',
             'not_after','month_indices','ciphertext_sha256','sqlite_sha256','scope'},
             'VENUE_DATED_COLLECTION_DESCRIPTOR_INVALID')
        need(type(item['folder']) is str and re.fullmatch(r'dated-inventory/[a-f0-9]{64}',item['folder']) and
             item['folder'] not in folders and all(type(item[k]) is str and re.fullmatch('[a-f0-9]{64}',item[k])
             for k in ('parent_manifest_sha256','ciphertext_sha256','sqlite_sha256')),
             'VENUE_DATED_COLLECTION_LOCATOR_INVALID')
        folders.add(item['folder']);stamp(item['inventory_captured_at'])
        indices=item['month_indices']
        need(type(indices) is dict and 1<=len(indices)<=512 and set(indices)<=set(s['months']),
             'VENUE_DATED_COLLECTION_INDICES_INVALID')
        for index in indices.values():
            need(type(index) is dict and set(index)=={'sha256','captured_at'} and
                 type(index['sha256']) is str and re.fullmatch('[a-f0-9]{64}',index['sha256']),
                 'VENUE_DATED_COLLECTION_INDEX_INVALID')
            stamp(index['captured_at'])

def _signed(raw):
    record=json.loads(raw);need(set(record)=={'state','mac'} and hmac.compare_digest(record['mac'],_manifest_mac(record['state'])),
        'VENUE_COLLECTION_AUTHENTICATION_FAILED')
    s=record['state'];need(s['schema'] in ('RACE_AI_ALL_PUBLISHED_HISTORY_PROGRESS_V1',DATED_SCHEMA) and
        isinstance(s['months'],list) and len(s['months'])==len(set(s['months'])) and
        all(re.fullmatch('[0-9]{6}',m) for m in s['months']) and set(s['heads'])<=set(s['months']),'VENUE_COLLECTION_INVALID')
    for m,h in s['heads'].items():
        need(h['kind']=='ENCRYPTED' and re.fullmatch(m+r'/attempt-[0-9]{6}',h['folder']) and
             re.fullmatch('[a-f0-9]{64}',h['ciphertext_sha256']),'VENUE_COLLECTION_HEAD_INVALID')
    if s['schema']==DATED_SCHEMA:_dated_structure(s)
    return record

def _chain(root,m,head):
    candidates={}
    for folder in (root/m).glob('attempt-*'):
        if not (folder/'history.checkpoint').is_file():continue
        r=json.loads(_read(folder/'summary.json',64000));candidates[r['ciphertext_sha256']]=folder
    expected=head['ciphertext_sha256'];generation=head['generation'];chain=[]
    while expected is not None:
        need(expected in candidates and generation>=1,'VENUE_COLLECTION_PREVIOUS_GENERATION_MISSING')
        folder=candidates[expected];c,r=restore_month(folder,expected_month=m);c.db.close()
        need(r['ciphertext_sha256']==expected and r['scope']==_scope(generation,r['scope']['previous_cipher_sha256']),
            'VENUE_COLLECTION_GENERATION_MISMATCH')
        chain.append((folder,r));expected=r['scope']['previous_cipher_sha256'];generation-=1
    need(generation==0 and str(chain[0][0].relative_to(root))==head['folder'],'VENUE_COLLECTION_CHAIN_INVALID')
    return chain

def _pointer(commit,path,raw):
    return dict(schema=SCHEMA,status='READY',repository_id='1416489937',source_commit=commit,
                manifest_path=path,manifest_sha256=hashlib.sha256(raw).hexdigest())

def publish_collection(root,repo,*,transport=None):
    need(_key_ready(),'OWNER_STATE_KEY_REQUIRED');root=Path(root)
    raw=_read(root/'collection.json',1000000);s=_signed(raw)['state']
    dated=None
    if s['schema']==DATED_SCHEMA:
        from .boat_history_dated_inventory import validate_inventory
        dated=validate_inventory(root,s,manifest_raw=raw)
    git=transport or GitStateRepository(repo,ref=TRANSFER_REF);parent=git.head()
    need(parent is not None,'VENUE_EXISTING_TRANSFER_REF_REQUIRED');git.fetch(parent)
    manifest=PREFIX+'manifests/'+hashlib.sha256(raw).hexdigest()+'.json';files={};old=None
    if git.exists(parent,LATEST):
        old_pointer=json.loads(git.read(parent,LATEST,16384))
        oldraw=git.read(parent,old_pointer['manifest_path'],1000000)
        need(hashlib.sha256(oldraw).hexdigest()==old_pointer['manifest_sha256'],'VENUE_PREVIOUS_MANIFEST_HASH_INVALID')
        old=_signed(oldraw)['state']
        if old['schema']==s['schema']=='RACE_AI_ALL_PUBLISHED_HISTORY_PROGRESS_V1':
            need(old['months']==s['months'] and old['menu_sha256']==s['menu_sha256'] and old['not_after']==s['not_after']
                 and set(old['heads'])<=set(s['heads']),'VENUE_COLLECTION_REGRESSION')
        else:
            same_inventory=(old['schema']==s['schema']==DATED_SCHEMA and
                            dict(old,heads={})==dict(s,heads={}))
            need(dated is not None and (same_inventory or hashlib.sha256(oldraw).hexdigest() in
                 dated['ancestor_manifest_sha256']) and set(old['heads'])<=set(s['heads']),
                 'VENUE_COLLECTION_REGRESSION')
    if dated is not None:
        from .boat_history_dated_inventory import inventory_files
        for relative,limit in inventory_files(s):
            path=PREFIX+relative;body=_read(root/relative,limit)
            if git.exists(parent,path):need(git.read(parent,path,limit)==body,'VENUE_IMMUTABLE_FILE_CHANGED')
            else:files[path]=body
    for m,h in sorted(s['heads'].items()):
        chain=_chain(root,m,h)
        if old and m in old['heads']:
            need(old['heads'][m]['ciphertext_sha256'] in {r['ciphertext_sha256'] for _,r in chain},'VENUE_MONTH_REGRESSION')
        for folder,_ in chain:
            for name,limit in [('history.checkpoint',12*1024*1024),('summary.json',64000)]:
                path=PREFIX+folder.relative_to(root).as_posix()+'/'+name;body=_read(folder/name,limit)
                if git.exists(parent,path):need(git.read(parent,path,limit)==body,'VENUE_IMMUTABLE_FILE_CHANGED')
                else:files[path]=body
    if git.exists(parent,manifest):need(git.read(parent,manifest,1000000)==raw,'VENUE_MANIFEST_COLLISION')
    else:files[manifest]=raw
    if old and old==s and not files:return _pointer(parent,manifest,raw)
    files[LATEST]=json.dumps(dict(manifest_path=manifest,manifest_sha256=hashlib.sha256(raw).hexdigest()),sort_keys=True).encode()
    commit=git.commit(files,parent);git.push(commit,parent)
    need(git.read(commit,manifest,1000000)==raw,'VENUE_REMOTE_MANIFEST_READBACK_MISMATCH')
    return _pointer(commit,manifest,raw)

def readback_collection(pointer,root,repo,*,transport=None):
    if not _key_ready():return dict(status='HOLD_OWNER_STATE_KEY_MISSING',months_restored=0)
    need(pointer.get('schema')==SCHEMA and pointer.get('repository_id')=='1416489937','VENUE_INPUT_INVALID')
    if pointer.get('status')=='WAITING_ENCRYPTED_INPUT':return dict(status='HOLD_ENCRYPTED_INPUT_REQUIRED',months_restored=0)
    need(set(pointer)=={'schema','status','repository_id','source_commit','manifest_path','manifest_sha256'} and
         pointer['status']=='READY' and re.fullmatch('[a-f0-9]{40}',pointer['source_commit']) and
         re.fullmatch('[a-f0-9]{64}',pointer['manifest_sha256']) and
         pointer['manifest_path']==PREFIX+'manifests/'+pointer['manifest_sha256']+'.json','VENUE_INPUT_LOCATOR_INVALID')
    from .boat_private_original_vault import VaultGitRepository
    git=transport if transport is not None else VaultGitRepository(repo,ref=TRANSFER_REF)
    commit=pointer['source_commit'];git.fetch(commit)
    raw=git.read(commit,pointer['manifest_path'],1000000)
    need(hashlib.sha256(raw).hexdigest()==pointer['manifest_sha256'],'VENUE_MANIFEST_HASH_INVALID');s=_signed(raw)['state']
    root=Path(root);root.mkdir(parents=True,mode=0o700,exist_ok=True);need(not any(root.iterdir()),'VENUE_OUTPUT_EXISTS_DO_NOT_RESET')
    _write(root/'collection.json',raw);totals={k:0 for k in ('listed_days','parsed_days','missing_days','quarantined_days','pending_days','waiting_publication_days','partial_source_days')}
    if s['schema']==DATED_SCHEMA:
        from .boat_history_dated_inventory import inventory_files
        for relative,limit in inventory_files(s):
            target=root/relative;target.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
            _write(target,git.read(commit,PREFIX+relative,limit))
    for m,h in sorted(s['heads'].items()):
        relative=h['folder'];expected=h['ciphertext_sha256'];generation=h['generation'];attempt=h['attempt']
        while expected is not None:
            folder=root/relative;folder.mkdir(parents=True,mode=0o700)
            for name,limit in [('history.checkpoint',12*1024*1024),('summary.json',64000)]:
                _write(folder/name,git.read(commit,PREFIX+relative+'/'+name,limit))
            c,r=restore_month(folder,expected_month=m);c.db.close()
            need(r['ciphertext_sha256']==expected and r['scope']['generation']==generation,'VENUE_REMOTE_HEAD_MISMATCH')
            if relative==h['folder']:
                for k in totals:totals[k]+=r['catalog'].get(k,0)
            expected=r['scope']['previous_cipher_sha256'];generation-=1
            if expected is not None:
                found=False
                for number in range(attempt-1,0,-1):
                    candidate=f'{m}/attempt-{number:06d}';path=PREFIX+candidate+'/summary.json'
                    if git.exists(commit,path) and json.loads(git.read(commit,path,64000)).get('ciphertext_sha256')==expected:
                        relative=candidate;attempt=number;found=True;break
                need(found,'VENUE_REMOTE_PREVIOUS_GENERATION_MISSING')
        need(generation==0,'VENUE_REMOTE_GENERATION_CHAIN_INVALID')
    if s['schema']==DATED_SCHEMA:
        from .boat_history_dated_inventory import validate_inventory
        validate_inventory(root,s,manifest_raw=raw)
    return dict(totals,status='OWNER_VENUE_COLLECTION_READBACK_VERIFIED',months_restored=len(s['heads']),
        published_months=len(s['months']),manifest_sha256=pointer['manifest_sha256'],
        all_period_collection_complete=len(s['heads'])==len(s['months']) and totals['listed_days']>0 and
            totals['parsed_days']==totals['listed_days'] and not any(totals[k] for k in ('missing_days','quarantined_days','partial_source_days','pending_days','waiting_publication_days')),
        unprocessed_listed_days=totals['pending_days']-totals['waiting_publication_days'],
        not_yet_published_days=totals['waiting_publication_days'],plaintext_published=False,formal_backtest_eligible=False)
