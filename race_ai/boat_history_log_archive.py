"""Exact registered raw job log from its documented GitHub attempt ZIP.

No source, key, fixture, text conversion or alternate digest admission exists.
Member names and all payload bounds are checked without extracting files.
"""
from hashlib import sha256
import io
import re
import stat
import zipfile
import zlib

from .boat_venue_future_grid import readback_log_archive

MAX_ARCHIVE=32*1024*1024
MAX_TOTAL=32*1024*1024
MAX_MEMBER=8*1024*1024
MAX_MEMBERS=512


def _need(ok,reason):
    if not ok:raise ValueError('GITHUB_API_READ_LOG_ARCHIVE_'+reason+'_HALT')


def extract_readback_log(raw,*,job_log_path):
    selected=readback_log_archive(job_log_path)
    _need(type(raw) is bytes and 0<len(raw)<=MAX_ARCHIVE,'BOUND')
    _need(raw.startswith(b'PK\x03\x04') and raw[-22:-18]==b'PK\x05\x06' and raw[-2:]==b'\0\0','ENVELOPE')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries=archive.infolist();_need(0<len(entries)<=MAX_MEMBERS and not archive.comment,'COUNT')
            seen=set();total=0;matching=[];selected_body=None
            for entry in entries:
                name=entry.filename;directory=entry.is_dir();parts=name[:-1].split('/') if directory else name.split('/')
                _need(name==entry.orig_filename and name not in seen and 0<len(name)<=1024 and
                    '\\' not in name and not re.search(r'[\x00-\x1f\x7f]',name) and not re.match(r'^[A-Za-z]:',name) and
                    all(part and part not in ('.','..') for part in parts),'NAME')
                seen.add(name)
                kind=stat.S_IFMT(entry.external_attr>>16)
                _need(not entry.flag_bits&0x41 and entry.compress_type in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED) and
                    kind in ((0,stat.S_IFDIR) if directory else (0,stat.S_IFREG)),'MEMBER_TYPE')
                _need(0<=entry.file_size<=MAX_MEMBER and (not directory or entry.file_size==0),'MEMBER_BOUND')
                total+=entry.file_size;_need(total<=MAX_TOTAL,'TOTAL_BOUND')
                if directory:continue
                digestor=sha256();size=0;chunks=[]
                with archive.open(entry) as stream:
                    while True:
                        body=stream.read(min(65536,MAX_MEMBER-size+1))
                        if not body:break
                        size+=len(body);_need(size<=entry.file_size<=MAX_MEMBER,'INFLATED_BOUND');digestor.update(body)
                        if name==selected['member']:chunks.append(body)
                _need(size==entry.file_size,'MEMBER_SIZE')
                if name==selected['member']:selected_body=b''.join(chunks)
                if digestor.hexdigest()==selected['log_sha256']:matching.append(name)
            _need(selected_body is not None,'SELECTED_MEMBER_MISSING')
            _need(matching==[selected['member']],'EXACT_SELECTED_HASH')
            return selected_body
    except (zipfile.BadZipFile,RuntimeError,NotImplementedError,EOFError,OSError,zlib.error,OverflowError):
        raise ValueError('GITHUB_API_READ_LOG_ARCHIVE_FORMAT_HALT') from None
