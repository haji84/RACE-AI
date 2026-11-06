"""Encrypted saved-view bundle for the owner's GitHub Pages secret link.

The independent view key cannot decrypt original checkpoints. It never enters
the public bundle or this module's return values. No forecast generation,
root-key read, HTTP, Pages configuration or active-worker control happens here.
"""
import base64
import json
import os
from pathlib import Path
import re

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from .boat_history_store import wire
from .boat_pdca_state import PdcaState,need,sha
from .boat_pdca_github_handoff import GitStateRepository
from .boat_pdca_recipient import _json
from .boat_pdca_projection import project_pdca
from .local_forecast_server import _asset_bytes
from .saved_pdca_view import WEB
from scripts.boat_history_collect import private_root,save

SCHEMA='RACE_AI_SAVED_WEB_VIEW_V1'
UPDATED_SCHEMA='RACE_AI_SAVED_WEB_VIEW_V2'
BUILD='RACE_AI_SAVED_PAGES_BUILD_V1'
BASE_URL='https://haji84.github.io/RACE-AI/'
MAX_VIEW=5*1024*1024
MAX_WIRE=8*1024*1024
HEX=re.compile('[a-f0-9]{64}\\Z')
ASSETS=('style.css','app.js','forecast-audit-model.js','product-data.js',
        'existing-model-catalog.js','ui-model.js','saved-performance.js','saved-view-crypto.js',
        'data/example-synthetic-forecast-audit.json')


def _hex(value):
    need(type(value) is str and HEX.fullmatch(value),'PAGES_HASH_REQUIRED');return value


def _index(ident):
    html=_asset_bytes(WEB,'index.html').decode()
    tag='<script defer src="./app.js"></script>'
    need(html.count(tag)==html.count('</head>')==1,'PAGES_INDEX_INVALID')
    html=html.replace(tag,'<script defer src="./saved-view-crypto.js"></script>\n  '+tag)
    html=html.replace('</head>','<meta name="referrer" content="no-referrer">\n'
        '<meta name="race-ai-encrypted-saved-view" content="./views/'+ident+'.json">\n</head>')
    html=html.replace('href="./forecast-audit.html"','href="#research"')
    for name in ASSETS:
        if name.endswith(('.js','.css')):
            version=sha(_asset_bytes(WEB,name))[:12]
            html=html.replace('"./'+name+'"','"./'+name+'?v='+version+'"')
    return html.encode()


def _read(path,limit=MAX_WIRE):
    path=Path(path)
    need(path.is_file() and not path.is_symlink() and path.stat().st_size<=limit,'PAGES_FILE_REJECTED')
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    with os.fdopen(fd,'rb') as src:raw=src.read(limit+1)
    need(len(raw)<=limit,'PAGES_FILE_BOUND');return raw


def _decode(value):
    need(type(value) is str and len(value)<=MAX_WIRE,'PAGES_CIPHER_INVALID')
    try:raw=base64.b64decode(value,validate=True)
    except ValueError:raise ValueError('PAGES_CIPHER_INVALID') from None
    need(base64.b64encode(raw).decode()==value,'PAGES_CIPHER_INVALID');return raw


def _envelope(raw):
    body=_json(raw,MAX_WIRE)
    need(type(body) is dict and set(body)=={'header','nonce','ciphertext'},'PAGES_CIPHER_INVALID')
    header=body['header']
    need(type(header) is dict,'PAGES_CIPHER_INVALID')
    fields={'schema','source_content_sha256'}
    if header.get('schema')==UPDATED_SCHEMA:fields.add('view_id');_hex(header.get('view_id'))
    else:need(header.get('schema')==SCHEMA,'PAGES_CIPHER_INVALID')
    need(set(header)==fields,'PAGES_CIPHER_INVALID')
    _hex(header['source_content_sha256'])
    need(len(_decode(body['nonce']))==12 and 16<=len(_decode(body['ciphertext']))<=MAX_VIEW+16,'PAGES_CIPHER_INVALID')
    return body


def _viewer(path):
    path=Path(path)
    need(path.is_file() and not path.is_symlink() and not path.stat().st_mode&0o077,'PAGES_VIEW_KEY_PRIVATE_REQUIRED')
    private_root(path.absolute().parent)
    doc=_json(_read(path,1024),1024)
    need(type(doc) is dict and set(doc) in ({'key','cipher_sha256'},{'key','cipher_sha256','view_id'}),'PAGES_VIEW_KEY_INVALID')
    _hex(doc['cipher_sha256']);view_id=_hex(doc.get('view_id',doc['cipher_sha256']))
    text=doc['key'];need(type(text) is str and re.fullmatch('[A-Za-z0-9_-]{43}',text),'PAGES_VIEW_KEY_INVALID')
    key=base64.b64decode(text.replace('-','+').replace('_','/')+'=',validate=True)
    need(len(key)==32 and base64.urlsafe_b64encode(key).decode().rstrip('=')==text,'PAGES_VIEW_KEY_INVALID')
    return key,view_id


def build_site(state_path,public_dir,private_dir,*,expected_source_sha256,viewer_from=None):
    _hex(expected_source_sha256)
    public=Path(public_dir).absolute();private=Path(private_dir).absolute()
    a=public.resolve();b=private.resolve()
    need(a!=b and a not in b.parents and b not in a.parents,'PAGES_OUTPUTS_MUST_BE_SEPARATE')
    reused=_viewer(viewer_from) if viewer_from is not None else None
    state=PdcaState(state_path)
    try:
        need(state.content_sha256()==expected_source_sha256,'PAGES_SOURCE_CONTENT_MISMATCH')
        view=project_pdca(state)
        need(state.content_sha256()==expected_source_sha256,'PAGES_SOURCE_CHANGED')
    finally:state.close()
    raw=wire(view).encode();need(0<len(raw)<=MAX_VIEW,'PAGES_VIEW_BOUND')
    # Display capability only: never a replacement for RACE_AI_STATE_KEY.
    key=reused[0] if reused else AESGCM.generate_key(bit_length=256);nonce=os.urandom(12)
    header=dict(schema=SCHEMA,source_content_sha256=expected_source_sha256)
    if reused:header.update(schema=UPDATED_SCHEMA,view_id=reused[1])
    cipher=AESGCM(key).encrypt(nonce,raw,wire(header).encode())
    encoded=(wire(dict(header=header,nonce=base64.b64encode(nonce).decode(),ciphertext=base64.b64encode(cipher).decode()))+'\n').encode()
    need(len(encoded)<=MAX_WIRE,'PAGES_CIPHER_BOUND');ident=sha(encoded)
    private=private_root(private);public=private_root(public)
    keytext=base64.urlsafe_b64encode(key).decode().rstrip('=')
    viewer=dict(key=keytext,cipher_sha256=ident)
    if reused:viewer['view_id']=reused[1]
    save(private/'viewer.json',(wire(viewer)+'\n').encode())
    save(private/'owner-url.txt',(BASE_URL+'#saved='+(reused[1] if reused else ident)+'.'+keytext+'\n').encode())
    files={name:_asset_bytes(WEB,name) for name in ASSETS}
    path='views/'+ident+'.json';files.update({'index.html':_index(ident),'.nojekyll':b'',path:encoded})
    manifest=dict(schema=BUILD,source_content_sha256=expected_source_sha256,cipher_path=path,cipher_sha256=ident,
        races=len(view['records']),predictions=sum(1+len(r.get('comparison_predictions',[])) for r in view['records']),
        files={name:dict(sha256=sha(body),bytes=len(body)) for name,body in sorted(files.items())})
    if reused:manifest['view_id']=reused[1]
    for name,body in files.items():private_root((public/name).parent);save(public/name,body)
    metadata=(wire(manifest)+'\n').encode();save(public/'site-build.json',metadata)
    validate_bundle(public,expected_manifest_sha256=sha(metadata))
    return dict(manifest,manifest_sha256=sha(metadata))


def _bundle_bytes(folder,*,expected_manifest_sha256=None):
    root=Path(folder);need(root.is_dir() and not root.is_symlink(),'PAGES_FOLDER_REJECTED')
    raw=_read(root/'site-build.json',32768)
    if expected_manifest_sha256 is not None:need(sha(raw)==_hex(expected_manifest_sha256),'PAGES_BUILD_PIN_MISMATCH')
    m=_json(raw,32768)
    fields={'schema','source_content_sha256','cipher_path','cipher_sha256','races','predictions','files'}
    need(type(m) is dict and set(m) in (fields,fields|{'view_id'})
         and m['schema']==BUILD,'PAGES_MANIFEST_INVALID')
    if 'view_id' in m:_hex(m['view_id'])
    ident=_hex(m['cipher_sha256']);_hex(m['source_content_sha256']);path='views/'+ident+'.json'
    need(m['cipher_path']==path and type(m['races']) is int and 0<m['races']<=5000
         and type(m['predictions']) is int and m['predictions']==4*m['races'],'PAGES_SCOPE_INVALID')
    expected=set(ASSETS)|{'index.html','.nojekyll',path}
    need(type(m['files']) is dict and set(m['files'])==expected,'PAGES_FILES_REJECTED')
    actual=set()
    for file in root.rglob('*'):
        need(not file.is_symlink(),'PAGES_SYMLINK_REJECTED')
        if file.is_file():actual.add(file.relative_to(root).as_posix())
        else:need(file.is_dir(),'PAGES_FILE_REJECTED')
    need(actual==expected|{'site-build.json'},'PAGES_FILES_REJECTED')
    files={'site-build.json':raw}
    for name in sorted(expected):
        body=_read(root/name);entry=m['files'][name]
        need(type(entry) is dict and entry==dict(bytes=len(body),sha256=sha(body)),'PAGES_FILE_HASH_MISMATCH')
        if name in ASSETS:need(body==_asset_bytes(WEB,name),'PAGES_ASSET_MODIFIED')
        elif name=='index.html':need(body==_index(ident),'PAGES_ASSET_MODIFIED')
        elif name=='.nojekyll':need(body==b'','PAGES_ASSET_MODIFIED')
        else:
            need(sha(body)==ident,'PAGES_CIPHER_HASH_MISMATCH')
            envelope=_envelope(body)
            need(envelope['header']['source_content_sha256']==m['source_content_sha256'],'PAGES_SOURCE_CONTENT_MISMATCH')
            need(envelope['header'].get('view_id')==m.get('view_id'),'PAGES_VIEW_ID_MISMATCH')
        files[name]=body
    return m,files


def validate_bundle(folder,*,expected_manifest_sha256=None):
    return _bundle_bytes(folder,expected_manifest_sha256=expected_manifest_sha256)[0]


def _tree(git,commit):
    rows=git._run(['ls-tree','-r','--format=%(objectmode)\t%(path)',commit]).decode().splitlines()
    paths=[];allowed=set(ASSETS)|{'index.html','.nojekyll','site-build.json'}
    for row in rows:
        mode,tab,path=row.partition('\t')
        need(mode=='100644' and tab and (path in allowed or re.fullmatch('views/[a-f0-9]{64}\\.json',path)),
             'PAGES_EXISTING_TREE_REJECTED')
        paths.append(path)
    return paths


class PagesRepository(GitStateRepository):
    """A separate, fixed publication target; never expands state-ref authority."""
    def __init__(self,repo):
        super().__init__(repo)
        self.ref='gh-pages'


def publish_site(repo,folder,*,expected_manifest_sha256,initialize=False,expected_parent=None,transport=None):
    manifest,files=_bundle_bytes(folder,expected_manifest_sha256=expected_manifest_sha256)
    git=transport or PagesRepository(repo)
    need(git.ref=='gh-pages','PAGES_REF_REQUIRED');parent=git.head()
    if parent is None:need(initialize is True and expected_parent is None,'PAGES_INITIALIZATION_REQUIRED')
    else:
        need(not initialize and expected_parent==parent,'PAGES_TRUSTED_PARENT_REQUIRED');git.fetch(parent)
        paths=_tree(git,parent)
        need('site-build.json' in paths,'PAGES_EXISTING_TREE_REJECTED')
        for path in paths:
            if path.startswith('views/'):
                raw=git.read(parent,path,MAX_WIRE);need(sha(raw)==Path(path).stem,'PAGES_EXISTING_CIPHER_INVALID');_envelope(raw)
        prior=_json(git.read(parent,'site-build.json',32768),32768)
        need(type(prior) is dict and prior.get('schema')==BUILD,'PAGES_EXISTING_TREE_REJECTED')
    commit=git.commit(files,parent)
    # Validate the actual inherited + new tree before the first write to GitHub.
    _tree(git,commit)
    git.push(commit,parent)
    for name,body in files.items():
        if body:need(git.read(commit,name,MAX_WIRE)==body,'PAGES_REMOTE_BYTES_MISMATCH')
    return dict(status='PAGES_BRANCH_PUBLISHED',source_commit=commit,branch='gh-pages',
                cipher_sha256=manifest['cipher_sha256'],manifest_sha256=expected_manifest_sha256,
                races=manifest['races'],predictions=manifest['predictions'],plaintext_published=False)
