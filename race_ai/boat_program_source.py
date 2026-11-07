"""Preserve exact official B from the existing GET and restore it without HTTP.

Temporary plaintext stays in a private Actions runner directory. The durable
day catalog contains only authenticated hashes and an encrypted vault locator.
The original P0 document and actual physical receipt remain unchanged; the
seller's existing raw/archive/day/roster checks authenticate the projection.
"""
from datetime import date,datetime,timezone
import os
from pathlib import Path
import re
import stat

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from . import boat_private_original_vault as V
from .actions_contract import digest
from .boat_pdca_state import state_key
from .boat_seller_inputs import official_b_cards_source
# Reuse the same pinned official URL/header implementation and parser setup as
# the existing producer. Importing the module performs no requests or inference.
from scripts.existing_day_program import official_url,inspect_lzh,JST
from scripts.boat_private_original_vault import _private_path,_read_private,_write

SCHEMA='RACE_AI_BOAT_PROGRAM_SOURCE_V1'
PREFIX='state/boat-program-source/v1/'
ROOT=Path(__file__).resolve().parents[1]
MAX_PROGRAM_BYTES=4*1024*1024


def _need(ok,reason):
    if not ok:raise ValueError('PROGRAM_SOURCE_'+reason)


def _day(value):
    try:
        day=value if type(value) is date else date.fromisoformat(value)
        _need(type(value) is date or day.isoformat()==value,'DAY_INVALID')
        return day
    except (TypeError,ValueError):raise ValueError('PROGRAM_SOURCE_DAY_INVALID') from None


def _key(key):
    return HKDF(algorithm=hashes.SHA256(),length=32,salt=V.REPO_ID.encode(),
        info=SCHEMA.encode()+b'\0catalog').derive(state_key('production',key))


def _capture_receipt(value,day):
    _need(type(value) is dict and set(value)=={'source_url','captured_at','source_sha256','http_status'}
          and type(value['http_status']) is int and value['http_status']==200
          and value['source_url']==official_url(day,'B'),'CAPTURE_RECEIPT_INVALID')
    V._hex(value['source_sha256'])
    _need(V._time(value['captured_at']).astimezone(JST).date()==day,'CAPTURE_DAY_INVALID')
    return value


def _expected_capture(document,day):
    return _capture_receipt(dict(source_url=document['source_url'],captured_at=document['captured_at'],
        source_sha256=document['source_sha256'],http_status=200),day)


def _private_directory(path):
    _private_path(path,ROOT,directory=True)
    _need(path.stat().st_uid==os.getuid(),'PRIVATE_DIRECTORY_OWNER_REQUIRED')
    return path


def capture_program(raw,receipt):
    """Save the one already-verified GET's exact bytes; perform no requests.

    Enabled by the producer's explicit flag. The owner Actions context and
    existing key must be present before any plaintext directory is created.
    Captured-at is the supplied actual source clock, never a save receipt.
    """
    state_key('production')
    _need(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('GITHUB_REPOSITORY')=='haji84/RACE-AI',
          'ACTIONS_OWNER_CONTEXT_REQUIRED')
    _need(type(raw) is bytes and 0<len(raw)<=MAX_PROGRAM_BYTES,'PROGRAM_BOUND_INVALID')
    day=V._time(receipt.get('captured_at')).astimezone(JST).date() if type(receipt) is dict else None
    _need(day is not None,'CAPTURE_RECEIPT_INVALID');_capture_receipt(receipt,day)
    _need(inspect_lzh(raw)['sha256']==receipt['source_sha256'],'CAPTURE_HASH_INVALID')
    runner=Path(os.environ.get('RUNNER_TEMP','')).absolute()
    _need(os.environ.get('RUNNER_TEMP') and runner.is_absolute() and '..' not in runner.parts and runner.is_dir()
          and not any(p.is_symlink() for p in (runner,*runner.parents))
          and not any((p/'.git').exists() for p in (runner,*runner.parents))
          and not runner.is_relative_to(ROOT.resolve()) and runner.stat().st_uid==os.getuid()
          and not runner.stat().st_mode&0o022,'PRIVATE_RUNNER_TEMP_REQUIRED')
    for path in (runner/'boat-program-source',runner/'boat-program-source'/day.isoformat()):
        if not path.exists():path.mkdir(mode=0o700)
        _private_directory(path)
    encoded=V._wire(receipt)+b'\n';ident=V._sha(encoded)
    folder=runner/'boat-program-source'/day.isoformat()/ident
    if folder.exists():
        _private_directory(folder)
        _need({p.name for p in folder.iterdir()}=={'program.lzh','receipt.json'}
              and _read_private(folder/'program.lzh',ROOT,MAX_PROGRAM_BYTES)==raw
              and _read_private(folder/'receipt.json',ROOT,16384)==encoded,'EXISTING_CAPTURE_CONFLICT')
    else:
        folder.mkdir(mode=0o700)
        _write(folder/'program.lzh',raw);_write(folder/'receipt.json',encoded)
    return dict(status='OFFICIAL_B_CAPTURED_PRIVATE',day_jst=day.isoformat(),capture_dir=str(folder),
        source_sha256=V._sha(raw),source_requests=0,plaintext_published=False)


def _binding(day,document,receipt):
    _need(type(document) is dict and document.get('day_jst')==day.isoformat() and type(receipt) is dict,
          'DOCUMENT_DAY_INVALID')
    return dict(day_jst=day.isoformat(),document_sha256=digest(document),receipt_sha256=digest(receipt),
        source_sha256=document.get('source_sha256'),source_url=document.get('source_url'),
        captured_at=document.get('captured_at'))


def _catalog(raw,mac_key):
    state=V._unsigned(raw,mac_key)
    _need(type(state) is dict and set(state)=={'schema','repository_id','binding','capture_locator'}
          and state['schema']==SCHEMA and state['repository_id']==V.REPO_ID,'CATALOG_INVALID')
    V._validate_locator(state['capture_locator'])
    _need(state['capture_locator']['kind']=='SOURCE_CAPTURES','CAPTURE_LOCATOR_INVALID')
    return state


def _restore(state,day,document,receipt,repo,*,key,transport,as_of=None):
    _need(state['binding']==_binding(day,document,receipt),'IMMUTABLE_DAY_BINDING_CONFLICT')
    restored=V.restore_capture_bundle(state['capture_locator'],repo,key=key,transport=transport)
    _need(len(restored['captures'])==1,'ONE_PROGRAM_CAPTURE_REQUIRED')
    raw,metadata_raw=restored['captures'][0]
    metadata=V._json(metadata_raw,16384);_capture_receipt(metadata,day)
    _need(metadata==_expected_capture(document,day) and V._sha(raw)==metadata['source_sha256'],
          'CAPTURE_DOCUMENT_CONFLICT')
    # This validates preserved source clocks against the actual P0 save receipt.
    # Model consumers retain their own current as-of admission checks.
    return official_b_cards_source(raw,document,receipt,day=day,
        as_of=receipt['created_at'] if as_of is None else as_of)


def load_program_source(day,document,receipt,repo,key=None,transport=None,*,as_of=None):
    """Return authenticated typed official B, or None only for an absent index.

    No HTTP, local-cache fallback, source clock rewrite or fake live receipt.
    A corrupt/missing referenced bundle or conflicting document fails closed.
    """
    mac_key=_key(key);day=_day(day);git=V._transport(repo,transport);commit=git.head()
    _need(commit is not None,'EXISTING_TRANSFER_REF_REQUIRED');git.fetch(commit)
    path=PREFIX+day.isoformat()+'.json'
    if not git.exists(commit,path):return None
    state=_catalog(V._read(git,commit,path,16384),mac_key)
    return _restore(state,day,document,receipt,repo,key=key,transport=git,as_of=as_of)


def _report(state,commit,path,raw,*,unchanged=False):
    return dict(status='OFFICIAL_B_PROGRAM_SOURCE_UNCHANGED' if unchanged else 'OFFICIAL_B_PROGRAM_SOURCE_RETAINED',
        day_jst=state['binding']['day_jst'],source_commit=commit,catalog_path=path,catalog_sha256=V._sha(raw),
        source_sha256=state['binding']['source_sha256'],capture_locator=state['capture_locator'],
        source_requests=0,plaintext_published=False)


def retain_program_source(day,document,receipt,repo,*,expected_parent,capture_dir=None,key=None,
                          transport=None,readback_transport=None,now=None):
    """Bind one actual first-P0 B source to its immutable encrypted day catalog.

    ``receipt`` is the existing independently verified normalized physical P0
    receipt. Callers authenticate it before this boundary; the CLI additionally
    restores the first-P0 original and matches the local exact document bytes.
    """
    mac_key=_key(key);day=_day(day);clock=now or datetime.now(timezone.utc)
    _need(type(clock) is datetime and clock.utcoffset() is not None,'AWARE_CLOCK_REQUIRED')
    binding=_binding(day,document,receipt);git=V._transport(repo,transport)
    V._hex(expected_parent,V._HEAD);_need(git.head()==expected_parent,'REF_CONCURRENT_UPDATE')
    git.fetch(expected_parent);path=PREFIX+day.isoformat()+'.json'
    if git.exists(expected_parent,path):
        raw=V._read(git,expected_parent,path,16384);state=_catalog(raw,mac_key)
        with V._independent_reader(git,readback_transport) as reader:
            reader.fetch(expected_parent)
            _need(V._read(reader,expected_parent,path,16384)==raw,'REMOTE_CATALOG_READBACK_MISMATCH')
            _restore(state,day,document,receipt,reader.repo,key=key,transport=reader,as_of=clock.isoformat())
        return _report(state,expected_parent,path,raw,unchanged=True)
    metadata=_expected_capture(document,day);expected_raw=V._wire(metadata)+b'\n'
    root=Path(capture_dir) if capture_dir is not None else Path(os.environ['RUNNER_TEMP'])/'boat-program-source'
    folder=root/day.isoformat()/V._sha(expected_raw)
    raw=_read_private(folder/'program.lzh',repo,MAX_PROGRAM_BYTES)
    metadata_raw=_read_private(folder/'receipt.json',repo,16384)
    _need(metadata_raw==expected_raw and V._sha(raw)==binding['source_sha256'],'CAPTURE_HASH_OR_CLOCK_CONFLICT')
    official_b_cards_source(raw,document,receipt,day=day,as_of=clock.isoformat())
    locator=V.retain_capture_bundle([(raw,metadata_raw)],repo,run_id=int(receipt['run_id']),head_sha=receipt['head_sha'],
        expected_parent=expected_parent,key=key,transport=git,readback_transport=readback_transport,now=clock)
    parent=locator['source_commit']
    state=dict(schema=SCHEMA,repository_id=V.REPO_ID,binding=binding,capture_locator=locator)
    encoded=V._signed(state,mac_key);_need(len(encoded)<=16384,'CATALOG_BOUND_EXCEEDED')
    _need(not git.exists(parent,path),'DAY_CATALOG_ALREADY_EXISTS')
    commit=git.commit({path:encoded},parent);git.push(commit,parent)
    with V._independent_reader(git,readback_transport) as reader:
        reader.fetch(commit)
        _need(V._read(reader,commit,path,16384)==encoded,'REMOTE_CATALOG_READBACK_MISMATCH')
        _restore(state,day,document,receipt,reader.repo,key=key,transport=reader,as_of=clock.isoformat())
    return _report(state,commit,path,encoded)
