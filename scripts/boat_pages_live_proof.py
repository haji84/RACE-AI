"""Verify approved presentation updates without changing frozen BOAT originals.

Reads only this public repository and its existing Pages origin. The original
forecast identity and legacy reader remain pinned; presentation bytes follow
the exact protected-main web tree instead of a superseded full-app digest.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from urllib.request import Request,build_opener,HTTPRedirectHandler

REFERENCE='f60308ef7443ca13b5ca23c4896e15ffc67b0427'
BASE='https://haji84.github.io/RACE-AI/'
SELECTED=('index.html','app.js','saved-performance.js','saved-view-crypto.js','style.css')
MAX_FILE=6*1024*1024


def need(value,code):
    if not value:raise ValueError('BOAT_PAGES_'+code)


def digest(raw):return sha256(raw).hexdigest()


def _pairs(items):
    result={}
    for key,value in items:
        need(key not in result,'DUPLICATE_JSON_KEY');result[key]=value
    return result


def decode(raw):
    need(type(raw) is bytes and 0<len(raw)<=1024*1024,'MANIFEST_BOUND')
    return json.loads(raw.decode('utf-8'),object_pairs_hook=_pairs)


def render_index(template,manifest,source_assets):
    text=template.decode('utf-8');tag='<script defer src="./app.js"></script>'
    need(text.count(tag)==text.count('</head>')==1,'INDEX_TEMPLATE')
    text=text.replace(tag,'<script defer src="./saved-view-crypto.js"></script>\n  '+tag)
    text=text.replace('</head>','<meta name="referrer" content="no-referrer">\n'
        '<meta name="race-ai-saved-view-forecast-sha" content="'+manifest['forecast_sha256']+'">\n'
        '<meta name="race-ai-encrypted-saved-view" content="./'+manifest['cipher_path']+'">\n</head>')
    text=text.replace('href="./forecast-audit.html"','href="#research"')
    text=text.replace("connect-src 'self'","connect-src 'self' https://raw.githubusercontent.com/haji84/RACE-AI/state/boat-saved-view/ https://raw.githubusercontent.com/haji84/RACE-AI/")
    for name,body in source_assets.items():
        if name.endswith(('.js','.css')):
            text=text.replace('"./'+name+'"','"./'+name+'?v='+digest(body)[:12]+'"')
    return text.encode('utf-8')


def verify_bytes(*,reference,manifest,deployed,source_assets,source_template,reference_app,fetch):
    fields={'schema','source_content_sha256','cipher_path','cipher_sha256','forecast_sha256',
            'races','predictions','files'}
    need(type(reference) is dict and type(manifest) is dict and
         set(reference) in (fields,fields|{'view_id'}) and set(manifest)==set(reference), 'MANIFEST_FIELDS')
    need(reference['schema']=='RACE_AI_SAVED_PAGES_BUILD_V1' and
         {k:v for k,v in reference.items() if k!='files'}==
         {k:v for k,v in manifest.items() if k!='files'},'ORIGINAL_FORECAST_IDENTITY_CHANGED')
    need(type(manifest['files']) is dict and set(manifest['files'])==set(reference['files']) and
         set(SELECTED)<=set(manifest['files']),'ASSET_FOOTPRINT_CHANGED')
    need(manifest['files'][manifest['cipher_path']]==reference['files'][reference['cipher_path']],
         'ORIGINAL_CIPHER_ENTRY_CHANGED')
    need(reference_app and reference_app in source_assets['app.js'],'LEGACY_CORE_CHANGED')
    for name in ('saved-performance.js','saved-view-crypto.js'):
        body=source_assets[name]
        need(reference['files'][name]==dict(bytes=len(body),sha256=digest(body)), 'LEGACY_READER_CHANGED')
    expected=dict(source_assets);expected['index.html']=render_index(source_template,manifest,source_assets)
    checked=tuple(dict.fromkeys((*SELECTED,*sorted(source_assets))))
    for name in checked:
        raw=expected[name]
        need(type(raw) is bytes and 0<len(raw)<=MAX_FILE,'ASSET_BOUND')
        need(deployed[name]==raw and manifest['files'][name]==dict(bytes=len(raw),sha256=digest(raw)),
             'SOURCE_OR_DEPLOYED_BYTES_DIFFER')
    html=expected['index.html'].decode()
    need('<section id="boat-owner-formal-proof"' in html and 'owner-formal.js' not in html and
         b'RaceOwnerFormal' in expected['app.js'],'OWNER_FORMAL_HOOKS_CHANGED')
    for name in checked:
        body=fetch(name,len(expected[name]))
        need(type(body) is bytes and body==expected[name],'LIVE_HTTP_BYTES_DIFFER')
    return dict(status='BOAT_APPROVED_PRESENTATION_AND_HTTP_VERIFIED',assets=len(checked),
        original_forecast_rewrites=0,official_provider_gets=0,source_state_mutations=0,
        original_forecast_identity_unchanged=True,legacy_reader_unchanged=True)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def http_bytes(path,size,commit):
    need(path in SELECTED or path=='site-build.json' or
         re.fullmatch(r'[a-z][a-z0-9-]*\.(?:js|css)',path),'HTTP_PATH')
    need(type(size) is int and 0<size<=MAX_FILE,'HTTP_BOUND')
    request=Request(BASE+path+'?verify='+commit,headers={
        'User-Agent':'RACE-AI-approved-pages-delivery-proof/1','Cache-Control':'no-cache'})
    with build_opener(NoRedirect()).open(request,timeout=25) as response:
        need(response.status==200 and response.geturl()==request.full_url,'HTTP_IDENTITY')
        body=response.read(size+1)
    need(len(body)<=size,'HTTP_OVERSIZE');return body


class GitRead:
    def __init__(self,repo):
        self.repo=Path(repo)
        urls=self.run(['remote','get-url','--all','origin']).decode().splitlines()
        need(len(urls)==1 and urls[0] in {'https://github.com/haji84/RACE-AI',
            'https://github.com/haji84/RACE-AI.git','git@github.com:haji84/RACE-AI.git'},'REPOSITORY')
    def run(self,args):
        r=subprocess.run(['git',*args],cwd=self.repo,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=90)
        need(r.returncode==0,'GIT_READ_FAILED');return r.stdout
    def fetch(self,ref):
        need(re.fullmatch('[a-f0-9]{40}',ref),'COMMIT')
        # Do not shorten a shared developer checkout's history.
        self.run(['fetch','--no-tags','origin',ref])
    def read(self,ref,path,limit=MAX_FILE):
        need(re.fullmatch('[a-f0-9]{40}',ref) and
             re.fullmatch('[A-Za-z0-9_./-]+',path) and '..' not in path.split('/'),'GIT_PATH')
        row=self.run(['ls-tree',ref,'--',path]).decode()
        need(row.startswith('100644 blob '),'GIT_FILE_MODE')
        size=int(self.run(['cat-file','-s',ref+':'+path]));need(0<size<=limit,'GIT_FILE_BOUND')
        raw=self.run(['show',ref+':'+path]);need(len(raw)==size,'GIT_FILE_CHANGED');return raw
    def blob(self,ref,path):return self.run(['rev-parse',ref+':'+path]).strip()
    def pages_head(self):
        rows=self.run(['ls-remote','origin','refs/heads/gh-pages']).decode().splitlines()
        need(len(rows)==1,'PAGES_HEAD');ref=rows[0].split()[0]
        need(re.fullmatch('[a-f0-9]{40}',ref),'PAGES_HEAD');return ref


def verify_live(repo,ui_source):
    git=GitRead(repo);git.fetch(REFERENCE);git.fetch(ui_source)
    head=git.pages_head();git.fetch(head)
    reference=decode(git.read(REFERENCE,'site-build.json',1024*1024))
    raw_manifest=git.read(head,'site-build.json',1024*1024);manifest=decode(raw_manifest)
    need(http_bytes('site-build.json',len(raw_manifest),head)==raw_manifest,'LIVE_MANIFEST_CHANGED')
    assets={p:git.read(ui_source,'web/'+p) for p in reference['files'] if p.endswith(('.js','.css'))}
    deployed={p:git.read(head,p) for p in set(SELECTED)|set(assets)}
    result=verify_bytes(reference=reference,manifest=manifest,deployed=deployed,source_assets=assets,
        source_template=git.read(ui_source,'web/index.html'),reference_app=git.read(REFERENCE,'app.js'),
        fetch=lambda path,size:http_bytes(path,size,head))
    cipher=reference['cipher_path']
    need(git.blob(REFERENCE,cipher)==git.blob(head,cipher),'ORIGINAL_CIPHER_BLOB_CHANGED')
    before=git.run(['ls-tree','-r',REFERENCE,'--','views']).splitlines()
    after=set(git.run(['ls-tree','-r',head,'--','views']).splitlines())
    need(all(row in after for row in before),'HISTORICAL_CIPHER_BLOBS_CHANGED')
    result.update(page_commit=head,trusted_ui_source=ui_source,original_reference=REFERENCE,
        manifest_sha256=digest(raw_manifest),encrypted_original_blob_unchanged=True)
    return result


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--repo',required=True);p.add_argument('--ui-source',required=True)
    args=p.parse_args(argv)
    try:
        print(json.dumps(verify_live(args.repo,args.ui_source),sort_keys=True));return 0
    except (ValueError,KeyError,TypeError,OSError,subprocess.SubprocessError):
        print('{"status":"HOLD_APPROVED_PAGES_DELIVERY_NOT_VERIFIED"}');return 2


if __name__=='__main__':raise SystemExit(main())
