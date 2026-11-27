"""Read two externally pinned B ciphertext files from an immutable Git commit.

No private key, archive source, training, branch update or durable state write
is used. Temporary ciphertext is discarded after verification. Source commit
identity comes from the external receipt; matching local source hashes does
not decrypt or authenticate the candidate's private training evidence.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from http.client import IncompleteRead
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from race_ai import keirin_official_run_history as codec
from .back_candidate import SOURCE_FILES, _source_pins, verify_candidate_bundle
from .policy import checked_sha, require
from .runtime import _write

REPOSITORY='haji84/RACE-AI'
RECEIPT_SCHEMA='DT_R1_RETAINED_BACK_RECEIPT_V1'
MAX_RECEIPT_BYTES=64*1024
MAX_MANIFEST_BYTES=64*1024
NAMES={'manifest':'manifest.json','cipher':'candidate.sealed.json'}
RECEIPT_FIELDS={'schema','repository','archive_commit','path','source_code_commit',
    'source_code_sha256','manifest','cipher','candidate_bytes_sha256','artifact_sha256','dataset_sha256'}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise ValueError('RETAINED_B_REDIRECT_REFUSED')


_OPENER=build_opener(NoRedirect())


def _commit(value):
    require(isinstance(value,str) and re.fullmatch('[0-9a-f]{40}',value) is not None,
            'RETAINED_B_FULL_COMMIT_REQUIRED')
    return value


def validate_receipt(receipt):
    require(isinstance(receipt,dict) and set(receipt)==RECEIPT_FIELDS,'RETAINED_B_RECEIPT_FIELDS')
    require(receipt['schema']==RECEIPT_SCHEMA and receipt['repository']==REPOSITORY,
            'RETAINED_B_RECEIPT_REPOSITORY_OR_SCHEMA')
    _commit(receipt['archive_commit']);_commit(receipt['source_code_commit'])
    for key in ('candidate_bytes_sha256','artifact_sha256','dataset_sha256'):
        checked_sha(receipt[key],'RETAINED_B_RECEIPT_SHA')
    for kind,name in NAMES.items():
        item=receipt[kind];limit=MAX_MANIFEST_BYTES if kind=='manifest' else codec.MAX_CIPHER_BYTES
        require(isinstance(item,dict) and set(item)=={'file','bytes','sha256'} and item['file']==name,
                'RETAINED_B_RECEIPT_FILE_ALLOWLIST')
        require(type(item['bytes']) is int and 0<item['bytes']<=limit,'RETAINED_B_RECEIPT_FILE_SIZE')
        checked_sha(item['sha256'],'RETAINED_B_RECEIPT_SHA')
    path=receipt['path']
    require(isinstance(path,str) and re.fullmatch(
        r'research/chatgpt-dt-r1/[A-Za-z0-9][A-Za-z0-9_-]{0,63}/[0-9a-f]{64}',path) is not None and
        path.rsplit('/',1)[-1]==receipt['manifest']['sha256'],'RETAINED_B_RECEIPT_PATH')
    sources=receipt['source_code_sha256']
    require(isinstance(sources,dict) and set(sources)==set(SOURCE_FILES),'RETAINED_B_SOURCE_FILE_SET')
    for value in sources.values():checked_sha(value,'RETAINED_B_SOURCE_SHA')
    require(sources==_source_pins(),'RETAINED_B_SOURCE_CODE_MISMATCH')
    return receipt


def _unique(pairs):
    result={}
    for key,value in pairs:
        require(key not in result,'RETAINED_B_DUPLICATE_RECEIPT_FIELD');result[key]=value
    return result


def load_receipt(path):
    path=Path(path)
    require(path.is_file() and not path.is_symlink(),'RETAINED_B_RECEIPT_FILE_INVALID')
    require(0<path.stat().st_size<=MAX_RECEIPT_BYTES,'RETAINED_B_RECEIPT_SIZE')
    with path.open('rb') as handle:raw=handle.read(MAX_RECEIPT_BYTES+1)
    require(0<len(raw)<=MAX_RECEIPT_BYTES,'RETAINED_B_RECEIPT_SIZE')
    try:
        receipt=json.loads(raw,object_pairs_hook=_unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('RETAINED_B_NONFINITE_RECEIPT')))
    except (UnicodeError,TypeError,RecursionError) as error:
        raise ValueError('RETAINED_B_RECEIPT_JSON_INVALID') from error
    return validate_receipt(receipt),sha256(raw).hexdigest()


def fetch_exact(receipt,kind):
    """Fixed public origin only, no credentials or redirect request is sent."""
    validate_receipt(receipt)
    require(kind in NAMES,'RETAINED_B_MEMBER_INVALID')
    item=receipt[kind]
    url=('https://raw.githubusercontent.com/'+REPOSITORY+'/'+receipt['archive_commit']+
         '/'+receipt['path']+'/'+NAMES[kind])
    request=Request(url,headers={'User-Agent':'RACE-AI-DT-R1-B-cipher-readback/1','Accept-Encoding':'identity'})
    try:
        with _OPENER.open(request,timeout=45) as response:
            require(response.geturl()==url,'RETAINED_B_URL_CHANGED')
            require(not 300<=response.status<400,'RETAINED_B_REDIRECT_REFUSED')
            require(response.status==200,'RETAINED_B_HTTP_STATUS')
            encodings=response.headers.get_all('Content-Encoding') or []
            require(len(encodings)<=1 and (not encodings or encodings[0].lower()=='identity'),
                    'RETAINED_B_RESPONSE_ENCODING')
            lengths=response.headers.get_all('Content-Length') or []
            require(not lengths or (len(lengths)==1 and re.fullmatch('[0-9]+',lengths[0]) is not None and
                    int(lengths[0])==item['bytes']),'RETAINED_B_RESPONSE_SIZE')
            transfer=response.headers.get_all('Transfer-Encoding') or []
            require(not transfer or (len(transfer)==1 and transfer[0].lower()=='chunked' and not lengths),
                    'RETAINED_B_RESPONSE_ENCODING')
            raw=response.read(item['bytes']+1)
    except HTTPError as error:
        error.close()
        raise ValueError('RETAINED_B_REDIRECT_REFUSED' if 300<=error.code<400 else 'RETAINED_B_HTTP_STATUS') from None
    except IncompleteRead:
        raise ValueError('RETAINED_B_FILE_INTEGRITY') from None
    except (URLError,TimeoutError,OSError):
        raise ValueError('RETAINED_B_NETWORK_UNAVAILABLE') from None
    require(len(raw)==item['bytes'] and sha256(raw).hexdigest()==item['sha256'],'RETAINED_B_FILE_INTEGRITY')
    return raw


@contextmanager
def verified_bundle(receipt_path):
    """Yield verified temporary ciphertext for this readback or an owner reader.

    Only the owner reader may separately obtain its existing approved key and
    call restore_candidate while this context is open. This helper never does.
    """
    receipt,receipt_sha=load_receipt(receipt_path)
    with tempfile.TemporaryDirectory(prefix='dt-r1-back-readback-') as temporary:
        folder=Path(temporary)
        for kind,name in NAMES.items():_write(folder/name,fetch_exact(receipt,kind))
        manifest=verify_candidate_bundle(folder,expected_manifest_sha256=receipt['manifest']['sha256'])
        candidate=next(item for item in manifest['files'] if item['file']=='back_candidate.json')
        require(manifest['cipher']==receipt['cipher'] and
                manifest['artifact_sha256']==receipt['artifact_sha256'] and
                manifest['dataset_sha256']==receipt['dataset_sha256'] and
                candidate['sha256']==receipt['candidate_bytes_sha256'],'RETAINED_B_RECEIPT_BINDING')
        require(receipt['source_code_sha256']==_source_pins(),'RETAINED_B_SOURCE_CODE_CHANGED')
        yield {'directory':folder,'manifest':manifest,'receipt':receipt,'receipt_file_sha256':receipt_sha}


def _reader_metadata():
    runner=os.environ.get('GITHUB_ACTIONS')=='true'
    run_id=os.environ.get('GITHUB_RUN_ID') if runner else None
    code_commit=os.environ.get('GITHUB_SHA') if runner else None
    if runner:
        require(os.environ.get('GITHUB_REPOSITORY')==REPOSITORY,'RETAINED_B_READER_REPOSITORY')
        require(isinstance(run_id,str) and re.fullmatch('[1-9][0-9]{0,19}',run_id) is not None,'RETAINED_B_READER_RUN_ID')
        _commit(code_commit)
    return {'reader_environment':'github_actions' if runner else 'local',
            'reader_run_id':run_id,'reader_code_commit':code_commit}


def readback(receipt_path):
    reader=_reader_metadata()
    with verified_bundle(receipt_path) as verified:
        receipt=verified['receipt']
        result={'schema':'DT_R1_RETAINED_BACK_READBACK_V1','status':'RETAINED_B_CIPHERTEXT_VERIFIED',
            'repository':REPOSITORY,'archive_commit':receipt['archive_commit'],'path':receipt['path'],
            'receipt_file_sha256':verified['receipt_file_sha256'],
            'manifest_sha256':receipt['manifest']['sha256'],'cipher_sha256':receipt['cipher']['sha256'],
            'candidate_bytes_sha256':receipt['candidate_bytes_sha256'],'artifact_sha256':receipt['artifact_sha256'],
            'dataset_sha256':receipt['dataset_sha256'],'files_verified':2,
            'source_code_commit':receipt['source_code_commit'],'source_code_commit_basis':'external_receipt',
            'source_code_files_verified':len(SOURCE_FILES),'observed_at':datetime.now(timezone.utc).isoformat(),
            **reader,'owner_decryption_verified':False,'candidate_plaintext_verified':False,
            'source_authenticated':False,'production_promoted':False,'private_key_used':False,
            'independent_run_verified':False,'github_file_requests':2,'provider_source_requests':0,'state_writes':0}
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt',type=Path,required=True)
    args=parser.parse_args(argv)
    print('DT_R1_RETAINED_BACK_READBACK '+json.dumps(readback(args.receipt),sort_keys=True,allow_nan=False))
    return 0


if __name__=='__main__':raise SystemExit(main())
