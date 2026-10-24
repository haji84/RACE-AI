"""Bounded official B/K archive transport; no implicit reuse/admission.

B = advance program (prediction candidate, no results); K = settled
outcomes (NEVER prediction input). Actual B/K URLs must be reviewed for
terms/purpose and one-date retrieval before invoking this disabled seam.
"""
from __future__ import annotations
from datetime import date,datetime,timezone
from urllib.request import Request,build_opener,HTTPSHandler,HTTPRedirectHandler
from urllib.error import HTTPError,URLError
from hashlib import sha256
import re

HOST="https://www1.mbrace.or.jp/od2"
MAX_ARCHIVE_BYTES=4_000_000
class ArchiveTransportError(ValueError):pass

class _StopRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ArchiveTransportError("redirect blocked")

def archive_url(day,kind):
    if type(day) is not date or kind not in ("B","K"):
        raise ArchiveTransportError("explicit date and B/K kind required")
    if not date(2000,1,1)<=day<=date(2100,12,31):
        raise ArchiveTransportError("date outside supported official archive layout")
    return (f"{HOST}/{kind}/{day:%Y%m}/"
            f"{kind.lower()}{day:%y%m%d}.lzh")

def ingest_one(day,kind,*,allow_source,opener=None,clock=None):
    """Return private compressed bytes and an AUDIT_ONLY receipt.

    'allow_source' must be an independently reviewed source/purpose/volume
    decision. Passing lambda true is a TEST DOUBLE, not legal authorization.
    Refuse predicted/future K for a race day that has not passed.
    """
    url=archive_url(day,kind)
    purpose="pre_race_program_private_analysis" if kind=="B" else "post_race_results_private_audit"
    if not callable(allow_source) or allow_source(url,purpose) is not True:
        raise ArchiveTransportError("archive access not admitted for this purpose")
    now=(clock() if clock else datetime.now(timezone.utc))
    if not isinstance(now,datetime) or now.utcoffset() is None:
        raise ArchiveTransportError("capture clock must be timezone-aware")
    if kind=="K" and day>=now.astimezone(timezone.utc).date():
        # UTC conservative: a current-day K can only enter settlement once
        # finalized by the provider, not while race outcomes are in-progress.
        raise ArchiveTransportError("current-day/unfinalized K requires separate finality review")
    client=opener or build_opener(_StopRedirect(),HTTPSHandler())
    req=Request(url,method="GET",headers={
        "Accept":"application/octet-stream,application/x-lzh-compressed",
        "User-Agent":"RACE-AI-one-off-official-archive-evidence/1",
    })
    try:
        with client.open(req,timeout=10) as resp:
            if getattr(resp,"status",None)!=200 or resp.geturl()!=url:
                raise ArchiveTransportError("unapproved archive redirect/status")
            mime=resp.headers.get("Content-Type","").split(";",1)[0].strip().lower()
            if mime not in ("application/octet-stream","application/x-lzh-compressed",
                            "application/x-lha","application/lzh","binary/octet-stream"):
                raise ArchiveTransportError("official archive returned unexpected MIME")
            declared=resp.headers.get("Content-Length")
            if declared is not None:
                if not declared.isdigit() or int(declared)>MAX_ARCHIVE_BYTES:
                    raise ArchiveTransportError("oversized or malformed archive length")
            payload=resp.read(MAX_ARCHIVE_BYTES+1)
            # Source headers are self-asserted by HTTP and NOT independent
            # evidence of first publication time.
            hints={
                "http_date_response_header_unverified":resp.headers.get("Date"),
                "last_modified_response_header_unverified":resp.headers.get("Last-Modified"),
                "etag_sha256_if_present":sha256(resp.headers["ETag"].encode()).hexdigest()
                if resp.headers.get("ETag") else None,
            }
    except ArchiveTransportError:raise
    except (HTTPError,URLError,TimeoutError,OSError) as exc:
        raise ArchiveTransportError("one-shot official archive transport failed") from exc
    if len(payload)<8 or len(payload)>MAX_ARCHIVE_BYTES:
        raise ArchiveTransportError("archive bytes missing/oversized")
    if payload[2:7] not in (b"-lh0-",b"-lh1-",b"-lh4-",b"-lh5-",b"-lh6-",b"-lh7-"):
        raise ArchiveTransportError("not an LZH/LHA archive header")
    seen=(clock() if clock else datetime.now(timezone.utc))
    receipt={
        "schema":"RACE_AI_BK_ONE_SHOT_ARCHIVE_RECEIPT_V1",
        "kind":kind,"event_date_jst":day.isoformat(),"source_url":url,
        "purpose_requested":purpose,"provider_archive_sha256":sha256(payload).hexdigest(),
        "compressed_bytes":len(payload),"captured_at_local_clock_claimed":seen.isoformat(),
        **hints,
        "source_publication_time_independently_verified":False,
        "source_sample_sizes_verified":False,
        "source_terms_legally_verified_by_code":False,
        "source_archive_identity_verified_by_decompressed_contents":False,
        "allowed_in_predictive_snapshot":False,
        "allowed_in_verified_settlement":False,
        "published_content_to_github":False,
        "status":"PRIVATE_QUARANTINE_BK_ARCHIVE_ONLY"}
    return payload,receipt
