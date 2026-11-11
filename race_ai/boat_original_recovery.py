"""Select exact encrypted closed-run responses before live GitHub requests.

A closure is an owner-authenticated snapshot of one completed workflow attempt,
not a fabricated current API response. Its exact run/list bytes live encrypted
in the original vault. Public create-only attempt catalogs contain only hashes,
identity and pinned encrypted locators; an authenticated selector identifies the
newest retained attempt. Missing/corrupt required material stops
recovery; a failed live request never triggers another source selection.
"""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import re
from urllib.parse import parse_qsl, urlsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from . import boat_private_original_vault as V
from .boat_owner_source_identity import authenticated_live_owner_run, archived_owner_branch
from .boat_pdca_state import state_key

SCHEMA='RACE_AI_BOAT_CLOSED_RUN_RESPONSES_V1'
SELECTOR_SCHEMA='RACE_AI_BOAT_CLOSED_RUN_SELECTOR_V1'
PREFIX='state/boat-original-recovery/v1/runs/'
WORKFLOW=405276784
BRANCH='feat/four-sport-forecast-audit-view-20261022'
API='https://api.github.com/repos/haji84/RACE-AI/'
MAX_PAGES=128
MAX_CATALOG=1024*1024


def _need(ok,reason):
    if not ok:raise ValueError('ORIGINAL_RECOVERY_'+reason)


def _key(key):
    return HKDF(algorithm=hashes.SHA256(),length=32,salt=V.REPO_ID.encode(),
        info=SCHEMA.encode()+b'\0catalog').derive(state_key('production',key))


def _path(run):
    V._id(run)
    return PREFIX+str(run)+'.json'


def _attempt(value):
    _need(type(value) is int and 1<=value<=1000,'RUN_ATTEMPT_INVALID')
    return value


def _attempt_path(run,attempt):
    V._id(run);_attempt(attempt)
    return PREFIX+str(run)+'/attempts/'+str(attempt)+'.json'


def _selector_path(run):
    V._id(run)
    return PREFIX+str(run)+'/latest.json'


def _page_number(endpoint,run):
    _need(type(endpoint) is str and len(endpoint)<=256,'PAGE_ENDPOINT_INVALID')
    parsed=urlsplit(endpoint)
    _need(not parsed.scheme and not parsed.netloc and not parsed.fragment
          and parsed.path==f'actions/runs/{run}/artifacts','PAGE_ENDPOINT_INVALID')
    query=parse_qsl(parsed.query,keep_blank_values=True)
    _need(len(query) in (1,2) and len({k for k,_ in query})==len(query)
          and dict(query).get('per_page')=='100' and set(dict(query))<={'per_page','page'},
          'PAGE_ENDPOINT_INVALID')
    number=dict(query).get('page','1')
    _need(re.fullmatch(r'[1-9][0-9]{0,2}',number) and int(number)<=MAX_PAGES,'PAGE_ENDPOINT_INVALID')
    return int(number)


def _validate(run_raw,pages,clock):
    run=V._json(run_raw,1024*1024)
    _need(type(run) is dict,'RUN_RESPONSE_INVALID')
    ident=V._id(run.get('id'));V._hex(run.get('head_sha'),V._HEAD)
    _need(authenticated_live_owner_run(run)
          and run.get('status')=='completed' and run.get('conclusion') in
          ('success','failure','neutral','cancelled','skipped','timed_out','action_required','stale','startup_failure'),
          'COMPLETED_WORKFLOW_REQUIRED')
    _need(all(type(run.get(name)) is dict and type(run[name].get('id')) is int
          and run[name]['id']==1416489937 and run[name].get('full_name')=='haji84/RACE-AI'
          for name in ('repository','head_repository')),'WORKFLOW_REPOSITORY_INVALID')
    attempt=_attempt(run.get('run_attempt',1))
    _need(V._time(run.get('created_at'))<=V._time(run.get('updated_at'))<=clock,'RUN_CLOCK_INVALID')
    _need(type(pages) in (tuple,list) and 1<=len(pages)<=MAX_PAGES,'PAGE_COUNT_INVALID')
    numbered={}
    for pair in pages:
        _need(type(pair) in (tuple,list) and len(pair)==2,'PAGE_PAIR_INVALID')
        endpoint,raw=pair;number=_page_number(endpoint,ident)
        _need(number not in numbered,'DUPLICATE_PAGE')
        value=V._json(raw,4*1024*1024)
        _need(type(value) is dict and type(value.get('total_count')) is int
              and 0<=value['total_count']<=100*MAX_PAGES and type(value.get('artifacts')) is list
              and len(value['artifacts'])<=100,'PAGE_RESPONSE_INVALID')
        numbered[number]=(endpoint,raw,value)
    _need(set(numbered)==set(range(1,len(numbered)+1)),'PAGINATION_INCOMPLETE')
    total=numbered[1][2]['total_count'];expected=max(1,(total+99)//100)
    _need(len(numbered)==expected,'PAGINATION_INCOMPLETE')
    rows=[];seen=set();descriptors=[];response_pages=[]
    for number in range(1,expected+1):
        endpoint,raw,value=numbered[number]
        count=min(100,max(0,total-(number-1)*100))
        _need(value['total_count']==total and len(value['artifacts'])==count,'PAGINATION_CHANGED_OR_INCOMPLETE')
        for artifact in value['artifacts']:
            _need(type(artifact) is dict,'ARTIFACT_ROW_INVALID')
            artifact_id=V._id(artifact.get('id'))
            _need(artifact_id not in seen and type(artifact.get('name')) is str
                  and 0<len(artifact['name'])<=256,'ARTIFACT_DUPLICATE_OR_INVALID')
            seen.add(artifact_id);rows.append(artifact)
        descriptors.append(dict(endpoint=endpoint,sha256=V._sha(raw),page=number,count=count))
        response_pages.append((endpoint,raw))
    _need(len(rows)==total,'PAGINATION_INCOMPLETE')
    identity=dict(run_id=ident,run_attempt=attempt,head_sha=run['head_sha'],workflow_id=WORKFLOW,
        head_branch=run['head_branch'],run_sha256=V._sha(run_raw),pages=descriptors,total_count=total)
    return dict(run=run,rows=rows,pages=response_pages,identity=identity,
                state_sha256=V._sha(V._wire(identity)))


def _native_kind(name,run):
    try:
        kind=V._kind(dict(name=name,workflow_run=dict(id=run)))
        # V1 closed-run inventories cover these six BOAT families. Other
        # independently validated vault families do not change that scope.
        return kind if kind in {'P0','P1','RESULT','CONTINUITY','ALL_MODEL','SOURCE_CONTROL'} else None
    except ValueError:return None


def _catalog(raw,key):
    state=V._unsigned(raw,key)
    _need(set(state)=={'schema','repository_id','complete','identity','state_sha256','capture_locator','originals'}
          and state['schema']==SCHEMA and state['repository_id']==V.REPO_ID and state['complete'] is True,
          'CATALOG_INVALID')
    identity=state['identity']
    _need(type(identity) is dict and set(identity)=={'run_id','run_attempt','head_sha','workflow_id','head_branch',
          'run_sha256','pages','total_count'} and identity['workflow_id']==WORKFLOW and archived_owner_branch(identity['head_branch']),
          'CATALOG_IDENTITY_INVALID')
    V._id(identity['run_id']);V._hex(identity['head_sha'],V._HEAD)
    _attempt(identity['run_attempt']);V._hex(identity['run_sha256'])
    total=identity['total_count'];pages=identity['pages']
    _need(type(total) is int and 0<=total<=100*MAX_PAGES
          and type(pages) is list and len(pages)==max(1,(total+99)//100),'CATALOG_PAGES_INVALID')
    for number,page in enumerate(pages,1):
        _need(type(page) is dict and set(page)=={'endpoint','sha256','page','count'}
              and type(page['page']) is int and page['page']==number
              and type(page['count']) is int and page['count']==min(100,max(0,total-(number-1)*100))
              and _page_number(page['endpoint'],identity['run_id'])==number,'CATALOG_PAGE_INVALID')
        V._hex(page['sha256'])
    _need(V._sha(V._wire(identity))==state['state_sha256'],'CATALOG_STATE_HASH_INVALID')
    V._validate_locator(state['capture_locator'])
    _need(state['capture_locator']['kind']=='SOURCE_CAPTURES' and type(state['originals']) is list
          and len(state['originals'])<=100*MAX_PAGES,'CATALOG_LOCATORS_INVALID')
    seen=set()
    for locator in state['originals']:
        V._validate_locator(locator)
        _need(locator['artifact_id'] is not None and locator['artifact_id'] not in seen,'CATALOG_ORIGINAL_DUPLICATE')
        seen.add(locator['artifact_id'])
    return state


def _catalog_at(git,commit,path,mac_key,run,attempt=None,expected_sha=None):
    raw=V._read(git,commit,path,MAX_CATALOG)
    if expected_sha is not None:_need(V._sha(raw)==expected_sha,'SELECTOR_CATALOG_HASH_CONFLICT')
    state=_catalog(raw,mac_key)
    _need(state['identity']['run_id']==run and
          (attempt is None or state['identity']['run_attempt']==attempt),'CATALOG_RUN_ATTEMPT_CONFLICT')
    return dict(state=state,catalog_path=path,catalog_sha256=V._sha(raw),source_commit=commit,raw=raw)


def _selected_catalog(git,commit,run,mac_key):
    path=_selector_path(run)
    if git.exists(commit,path):
        selector=V._unsigned(V._read(git,commit,path,16384),mac_key)
        _need(set(selector)=={'schema','repository_id','run_id','run_attempt','catalog_path','catalog_sha256'}
              and selector['schema']==SELECTOR_SCHEMA and selector['repository_id']==V.REPO_ID
              and type(selector['run_id']) is int and selector['run_id']==run,'SELECTOR_SCOPE_INVALID')
        attempt=_attempt(selector['run_attempt']);V._hex(selector['catalog_sha256'])
        _need(selector['catalog_path']==_attempt_path(run,attempt),'SELECTOR_PATH_INVALID')
        return _catalog_at(git,commit,selector['catalog_path'],mac_key,run,attempt,selector['catalog_sha256'])
    legacy=_path(run)
    return _catalog_at(git,commit,legacy,mac_key,run) if git.exists(commit,legacy) else None


def _selector(run,attempt,path,raw):
    return dict(schema=SELECTOR_SCHEMA,repository_id=V.REPO_ID,run_id=run,run_attempt=attempt,
                catalog_path=path,catalog_sha256=V._sha(raw))


def _report(state,commit,path,raw,*,unchanged=False):
    return dict(status='CLOSED_RUN_RESPONSES_UNCHANGED' if unchanged else 'CLOSED_RUN_RESPONSES_RETAINED',
        run_id=state['identity']['run_id'],run_attempt=state['identity']['run_attempt'],
        source_commit=commit,catalog_path=path,catalog_sha256=V._sha(raw),
        capture_locator=state['capture_locator'],artifact_count=state['identity']['total_count'],complete=True,
        plaintext_published=False)


def retain_closed_run_responses(run_raw,pages,repo,*,expected_parent,key=None,transport=None,
                                readback_transport=None,now=None):
    """Retain actual completed-attempt API bytes and advance its run selector.

    Native artifacts must already be authenticated in the original vault. The
    caller supplies actual successful API responses; this function performs no
    HTTP. ``now`` is the owner capture/retention clock, never a native original
    save clock. Publication has two explicit CAS stages: encrypted bundle, then
    its create-only attempt catalog and authenticated latest selector. A failed
    catalog publication leaves preserved
    encrypted bytes and must be retried from a newly checked parent.
    """
    mac_key=_key(key);clock=now or datetime.now(timezone.utc)
    _need(type(clock) is datetime and clock.utcoffset() is not None,'AWARE_CLOCK_REQUIRED')
    validated=_validate(run_raw,pages,clock);run=validated['run'];attempt=validated['identity']['run_attempt']
    path=_attempt_path(run['id'],attempt)
    V._hex(expected_parent,V._HEAD);git=V._transport(repo,transport)
    _need(git.head()==expected_parent,'CATALOG_REF_CONCURRENT_UPDATE')
    git.fetch(expected_parent)
    selected=_selected_catalog(git,expected_parent,run['id'],mac_key)
    if not git.exists(expected_parent,path):
        # Keep existing run-only catalogs immutable during an upgrade. A retry
        # for that same attempt still compares against the captured identity.
        legacy=_path(run['id'])
        if git.exists(expected_parent,legacy):
            old=_catalog_at(git,expected_parent,legacy,mac_key,run['id'])
            if old['state']['identity']['run_attempt']==attempt:path=legacy
    if git.exists(expected_parent,path):
        retained=_catalog_at(git,expected_parent,path,mac_key,run['id'],attempt)
        raw=retained['raw'];old=retained['state']
        _need(old['identity']==validated['identity'],'CLOSED_RUN_IMMUTABLE_CONFLICT')
        # Verify the referenced encrypted response bytes still exist. A cached
        # catalog never authorizes falling back to current/expired API data.
        _restore(old,repo,key=key,transport=git)
        return _report(old,expected_parent,path,raw,unchanged=True)
    originals=[]
    for listed in validated['rows']:
        kind=_native_kind(listed['name'],run['id'])
        if kind is None:continue
        locator=V.lookup_original(listed['id'],repo,source_commit=expected_parent,key=key,transport=git)
        _need(locator is not None and locator['kind']==kind,'REQUIRED_ORIGINAL_NOT_RETAINED')
        original=V.restore_original(locator,repo,key=key,transport=git);metadata=original['metadata']
        _need(all(listed.get(field)==metadata.get(field) for field in
                  ('id','name','digest','size_in_bytes','created_at')),'LISTED_ORIGINAL_IDENTITY_CONFLICT')
        workflow=metadata['workflow_run']
        _need(workflow['id']==run['id'] and workflow['head_sha']==run['head_sha'],
              'ORIGINAL_RUN_HEAD_CONFLICT')
        originals.append(locator)
    captured_at=clock.isoformat()
    responses=[(f'actions/runs/{run["id"]}',run_raw),*validated['pages']]
    captures=[(raw,V._wire(dict(source_url=API+endpoint,captured_at=captured_at,http_status=200,
                              source_sha256=V._sha(raw)))) for endpoint,raw in responses]
    locator=V.retain_capture_bundle(captures,repo,run_id=run['id'],head_sha=run['head_sha'],
        expected_parent=expected_parent,key=key,transport=git,readback_transport=readback_transport,now=clock)
    parent=locator['source_commit']
    state=dict(schema=SCHEMA,repository_id=V.REPO_ID,complete=True,identity=validated['identity'],
               state_sha256=validated['state_sha256'],capture_locator=locator,originals=originals)
    raw=V._signed(state,mac_key);_need(len(raw)<=MAX_CATALOG,'CATALOG_BOUND_EXCEEDED')
    _need(not git.exists(parent,path),'CLOSED_RUN_CATALOG_ALREADY_EXISTS')
    files={path:raw}
    if selected is None or attempt>selected['state']['identity']['run_attempt']:
        files[_selector_path(run['id'])]=V._signed(_selector(run['id'],attempt,path,raw),mac_key)
    commit=git.commit(files,parent);git.push(commit,parent)
    with V._independent_reader(git,readback_transport) as reader:
        reader.fetch(commit)
        for retained_path,body in files.items():
            _need(V._read(reader,commit,retained_path,MAX_CATALOG)==body,'CATALOG_REMOTE_READBACK_MISMATCH')
    return _report(state,commit,path,raw)


def _restore(state,repo,*,key,transport):
    restored=V.restore_capture_bundle(state['capture_locator'],repo,key=key,transport=transport)
    responses={}
    for raw,receipt_raw in restored['captures']:
        receipt=V._json(receipt_raw,16384);url=receipt.get('source_url')
        _need(type(url) is str and url.startswith(API),'CAPTURE_API_IDENTITY_INVALID')
        endpoint=url[len(API):]
        _need(endpoint not in responses and receipt.get('source_sha256')==V._sha(raw),'CAPTURE_RESPONSE_CONFLICT')
        responses[endpoint]=raw
    ident=state['identity']['run_id'];run_endpoint=f'actions/runs/{ident}'
    _need(run_endpoint in responses,'CAPTURE_RUN_RESPONSE_MISSING')
    expected={run_endpoint,*[item['endpoint'] for item in state['identity']['pages']]}
    _need(set(responses)==expected,'CAPTURE_PAGE_RESPONSE_MISSING')
    pages=[(item['endpoint'],responses[item['endpoint']]) for item in state['identity']['pages']]
    validated=_validate(responses[run_endpoint],pages,V._time(restored['provenance']['archived_at']))
    _need(validated['identity']==state['identity'],'CAPTURE_CATALOG_CONFLICT')
    required={row['id'] for row in validated['rows'] if _native_kind(row['name'],ident) is not None}
    _need(required=={locator['artifact_id'] for locator in state['originals']},'CATALOG_REQUIRED_ORIGINALS_INCOMPLETE')
    return dict(responses=responses,validated=validated,provenance=restored['provenance'])


class ArtifactRecovery:
    """Callable cache-first adapter with complete closed-run enumeration.

    ``archived_artifact_pages(run_id)`` supplies authenticated native originals'
    actual metadata-as-captured as an availability inventory; other rows retain
    their captured listing facts. Exact listing bytes remain available through
    the callable API, including their actual expired flags. None means no
    closure was selected. Call this before live pagination. ``provenance`` maps
    artifact IDs and served archived endpoints to their explicit scope.
    """
    def __init__(self,get,repo,key=None,transport=None):
        self.mac_key=_key(key);self.repo=repo;self.key=key;self.git=V._transport(repo,transport)
        self.artifacts=V.VaultArtifactReader(get,repo,key=key,transport=self.git)
        self.closures={};self.descriptors={};self.provenance={}

    def closed_run_descriptor(self,run):
        """Authenticate bounded descriptors without fetching private chunks.

        Byte counts allow maintenance to reserve its read/decryption budget
        before ``has_closed_run`` restores the actual response bundle. Selection
        stays pinned for this reader, including an absent catalog.
        """
        V._id(run)
        if run not in self.descriptors:
            commit=self.git.head();_need(commit is not None,'EXISTING_TRANSFER_REF_REQUIRED')
            self.git.fetch(commit)
            selected=_selected_catalog(self.git,commit,run,self.mac_key)
            if selected is not None:
                selected.pop('raw')
                locator=selected['state']['capture_locator'];self.git.fetch(locator['source_commit'])
                _,mac_key=V._keys(self.key)
                reference={name:locator[name] for name in
                    ('batch_path','batch_sha256','entry_sha256','artifact_id','kind')}
                entry=V._batch_entry(self.git,locator['source_commit'],reference,mac_key)
                summary=entry['header']['summary'];identity=selected['state']['identity']
                _need(summary['run_id']==run and summary['head_sha']==identity['head_sha'],
                      'CAPTURE_DESCRIPTOR_IDENTITY_CONFLICT')
                selected['capture_cipher_bytes']=entry['cipher_size']
                selected['capture_plain_bytes']=sum(item['size'] for item in entry['header']['files'].values())
            self.descriptors[run]=selected
        return deepcopy(self.descriptors[run])

    def has_closed_run(self,run):
        """Validate archived responses without hydrating any native ZIPs."""
        return self._closed(run) is not None

    def _closed(self,run):
        V._id(run)
        if run in self.closures:return self.closures[run]
        descriptor=self.closed_run_descriptor(run)
        if descriptor is None:
            self.closures[run]=None
            return None
        state=descriptor['state']
        result=_restore(state,self.repo,key=self.key,transport=self.git)
        result['state']=state;result['catalog_sha256']=descriptor['catalog_sha256']
        for locator in state['originals']:
            self.artifacts.known[locator['artifact_id']]=locator
        self.closures[run]=result
        return result

    def archived_artifact_pages(self,run_id):
        closed=self._closed(run_id)
        if closed is None:return None
        rows=deepcopy(closed['validated']['rows'])
        for number,listed in enumerate(rows):
            if _native_kind(listed['name'],run_id) is None:continue
            ident=listed['id']
            _need(ident not in self.artifacts.selected or self.artifacts.selected[ident] is not None,
                  'ARCHIVE_SELECTION_ALREADY_LIVE')
            # This is the actual archived original receipt response, not a
            # listing row with its expired flag toggled. Full vault restore
            # authenticates bytes before any availability claim is made.
            raw=self(f'actions/artifacts/{ident}')
            metadata=V._json(raw,V.MAX_METADATA)
            _need(all(listed.get(field)==metadata.get(field) for field in
                ('id','name','digest','size_in_bytes','created_at')),'AVAILABLE_ORIGINAL_IDENTITY_CONFLICT')
            rows[number]=metadata
            self.provenance[ident]=dict(self.provenance[ident],receipt_scope='ARCHIVED_AVAILABLE_ORIGINALS',
                listed_expired=listed.get('expired'),listing_catalog_sha256=closed['catalog_sha256'])
        return rows

    def is_archived(self,artifact_id):
        """True only after this adapter authenticated and restored exact bytes."""
        V._id(artifact_id)
        return artifact_id in self.artifacts.cache and self.provenance.get(artifact_id,{}).get('authenticated_archive') is True

    def __call__(self,endpoint):
        run_match=re.fullmatch(r'actions/runs/([1-9][0-9]{0,19})(/artifacts(?:\?[^#]*)?)?',endpoint)
        if run_match:
            run=int(run_match[1]);closed=self._closed(run)
            if closed is not None:
                requested=endpoint
                if run_match[2]:
                    number=_page_number(endpoint,run)
                    matches=[item['endpoint'] for item in closed['state']['identity']['pages'] if item['page']==number]
                    _need(len(matches)==1,'UNCAPTURED_PAGE_REQUESTED');requested=matches[0]
                _need(requested in closed['responses'],'UNCAPTURED_RUN_RESPONSE_REQUESTED')
                self.provenance[endpoint]=dict(closed['provenance'],
                    receipt_scope='ARCHIVED_CLOSED_RUN_API_RESPONSE',run_id=run,complete=True,
                    catalog_sha256=closed['catalog_sha256'],current_artifact_status='NOT_QUERIED')
                return closed['responses'][requested]
        raw=self.artifacts(endpoint)
        artifact_match=re.fullmatch(r'actions/artifacts/([1-9][0-9]{0,19})(?:/zip)?',endpoint)
        if artifact_match and int(artifact_match[1]) in self.artifacts.cache:
            ident=int(artifact_match[1]);restored=self.artifacts.cache[ident]
            proof=dict(restored['provenance'],authenticated_archive=True,artifact_id=ident,
                locator=deepcopy(self.artifacts.selected[ident]),
                metadata_response_sha256=V._sha(restored['metadata_raw']),zip_sha256=V._sha(restored['raw_zip']),
                original_created_at=restored['metadata']['created_at'])
            self.provenance[endpoint]=deepcopy(proof);self.provenance[ident]=deepcopy(proof)
        return raw
