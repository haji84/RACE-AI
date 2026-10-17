"""Safe in-memory LZH decompression of one official B/K daily archive.

libarchive is required. No arbitrary filesystem writes, shell execution or
path extraction. A single expected text entry is accepted, all others rejected.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import io
import re

from .core import SourceError

MAX_UNCOMPRESSED=20_000_000


def _extract_portable(raw: bytes, expected_name: str) -> bytes:
    """Pinned lhafile fallback, with no path extraction or archive execution."""
    try:
        import lhafile
    except ImportError as exc:
        raise SourceError('install libarchive or the pinned lhafile runtime') from exc
    try:
        with io.BytesIO(raw) as memory:
            archive = lhafile.Lhafile(memory)
            entries = archive.infolist()
            if len(entries) != 1:
                raise SourceError('expected exactly one daily text entry')
            entry = entries[0]
            name = entry.filename
            if (not isinstance(name, str) or name.upper() != expected_name.upper()
                    or '/' in name or '\\' in name or '..' in name
                    or getattr(entry, 'directory', None)):
                raise SourceError('unexpected archive entry name')
            if not 0 < entry.file_size <= MAX_UNCOMPRESSED or not 0 < entry.compress_size <= len(raw):
                raise SourceError('daily text outside size cap')
            content = archive.read(name)
            if not isinstance(content, bytes) or len(content) != entry.file_size or len(content) > MAX_UNCOMPRESSED:
                raise SourceError('declared and actual daily text sizes differ')
            return content
    except SourceError:
        raise
    except Exception as exc:
        raise SourceError('portable LZH validation or decompression failed') from exc


def extract_daily_lzh(raw:bytes, expected_name:str)->bytes:
    if not re.fullmatch(r'[BKbk]\d{6}\.TXT',expected_name,re.I):
        raise SourceError('expected entry name must be B/KYYMMDD.TXT')
    if not isinstance(raw,bytes) or len(raw)<25:
        raise SourceError('missing LZH archive bytes')
    from .official_archive_probe import inspect_lzh
    inspect_lzh(raw)
    libname=ctypes.util.find_library('archive')
    if not libname:
        return _extract_portable(raw, expected_name)
    lib=ctypes.CDLL(libname)
    ptr=ctypes.c_void_p
    def api(symbol,result,args):
        func=getattr(lib,symbol,None)
        if func is None:
            raise SourceError(f'libarchive lacks {symbol}')
        func.restype=result
        func.argtypes=args
        return func
    create=api('archive_read_new',ptr,[])
    support_fmt=api('archive_read_support_format_lha',ctypes.c_int,[ptr])
    support_filter=api('archive_read_support_filter_none',ctypes.c_int,[ptr])
    opener=api('archive_read_open_memory',ctypes.c_int,[ptr,ptr,ctypes.c_size_t])
    next_header=api('archive_read_next_header',ctypes.c_int,[ptr,ctypes.POINTER(ptr)])
    filename=api('archive_entry_pathname',ctypes.c_char_p,[ptr])
    entry_size=api('archive_entry_size',ctypes.c_longlong,[ptr])
    entry_filetype=api('archive_entry_filetype',ctypes.c_uint,[ptr])
    read=api('archive_read_data',ctypes.c_ssize_t,[ptr,ptr,ctypes.c_size_t])
    error=api('archive_error_string',ctypes.c_char_p,[ptr])
    release=api('archive_read_free',ctypes.c_int,[ptr])
    a=create()
    if not a:
        raise SourceError('libarchive failed to initialize')
    buf=ctypes.create_string_buffer(raw,len(raw))
    extracted=None
    count=0
    try:
        if support_fmt(a)<0 or support_filter(a)<0 or opener(a,buf,len(raw))<0:
            raise SourceError('libarchive cannot open LZH safely')
        while True:
            entry=ptr()
            status=next_header(a,ctypes.byref(entry))
            if status==1:
                break
            if status<0:
                raise SourceError('LZH entry header error')
            count+=1
            if count>1:
                raise SourceError('multi-entry LZH archive rejected')
            n=filename(entry)
            try:
                fname=n.decode('cp932') if n else ''
            except UnicodeDecodeError as exc:
                raise SourceError('invalid LZH entry filename encoding') from exc
            # Only a simple file basename. No traversal, separator, or special entry.
            if fname.upper()!=expected_name.upper() or '/' in fname or '\\' in fname or '..' in fname:
                raise SourceError('unexpected archive entry name')
            ftype=entry_filetype(entry)
            if ftype not in (0,0o100000):
                raise SourceError('special archive entry rejected')
            size=entry_size(entry)
            if size<=0 or size>MAX_UNCOMPRESSED:
                raise SourceError('uncompressed daily text outside size cap')
            out=bytearray()
            while True:
                part=ctypes.create_string_buffer(8192)
                nread=read(a,part,len(part))
                if nread==0:
                    break
                if nread<0:
                    raise SourceError('LZH decompression failed')
                out.extend(part.raw[:nread])
                if len(out)>MAX_UNCOMPRESSED:
                    raise SourceError('decompression size cap exceeded')
            if len(out)!=size:
                raise SourceError('declared and actual output sizes differ')
            extracted=bytes(out)
    finally:
        release(a)
    if count!=1 or not extracted:
        raise SourceError('expected exactly one extracted daily text')
    return extracted
