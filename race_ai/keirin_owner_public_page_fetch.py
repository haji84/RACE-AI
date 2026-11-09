"""Owner-confirmed normal public HTML page retrieval for KEIRIN.JP/WINTICKET.

Only ordinary documented public HTTPS pages on four exact user-approved
hosts. This does NOT reverse-engineer internal JSON APIs, bypass authentication,
exceed server-provided limits, or turn HTML into invented 210-odds values.
Original bytes + capture clock + SHA stay on the owner's private disk.
No arbitrary RACE-AI per-cycle API request-count quota.
"""
from __future__ import annotations

from datetime import datetime,timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from urllib import request,error
from urllib.parse import urlsplit

from .keirin_owner_auto_sources import (
    OwnerAttestedAutomaticSources,
)
from .keirin_owner_manual import PERSONAL_MARKER
from .keirin_owner_approved_sources import classify_owner_source

MAX_HTML_BYTES=8_000_000


class PublicPageFetchError(ValueError):
    pass


def require(ok, code):
    if not ok:
        raise PublicPageFetchError(code)


def approved_public_url(url,grant):
    require(isinstance(grant,OwnerAttestedAutomaticSources),
            "OWNER_AUTOMATIC_PROFILE_REQUIRED")
    require(classify_owner_source(url) ==
            "OWNER_APPROVED_PRIVATE_MANUAL_REFERENCE_ONLY" and
            grant.allowed(url,PERSONAL_MARKER,"automated_fetch"),
            "UNAPPROVED_PUBLIC_PAGE")
    parts=urlsplit(url)
    require(parts.path.startswith("/keirin/") if "winticket" in
            (parts.hostname or "") else parts.path.startswith("/pc/"),
            "NON_KEIRIN_PUBLIC_PAGE_REJECTED")
    require(parts.port is None and not parts.fragment,
            "PUBLIC_URL_UNSAFE")
    return url


def network_page_once(url):
    """One normal public GET, no redirect/auth/cookie/bypass/retry."""
    class NoRedirect(request.HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,headers,newurl):
            return None
    opener=request.build_opener(NoRedirect)
    req=request.Request(url,headers={
        "Accept":"text/html,application/xhtml+xml",
        "User-Agent":"RACE-AI-Owner-Approved-Research/1.0",
    },method="GET")
    try:
        with opener.open(req,timeout=12) as resp:
            require(resp.status==200, "PUBLIC_PAGE_HTTP_NOT_OK")
            content_type=resp.headers.get("Content-Type","").lower()
            require(("text/html" in content_type or
                    "application/xhtml+xml" in content_type),
                    "PUBLIC_PAGE_UNEXPECTED_MEDIA_TYPE")
            body=resp.read(MAX_HTML_BYTES+1)
            require(0<len(body)<=MAX_HTML_BYTES,
                    "PUBLIC_PAGE_TOO_LARGE_OR_EMPTY")
            return body
    except error.HTTPError as exc:
        if exc.code in (403,429):
            raise PublicPageFetchError(
                "PUBLIC_PAGE_BLOCKED_OR_RATE_LIMITED_NO_RETRY") from None
        if exc.code in (404,410):
            raise PublicPageFetchError(
                "PUBLIC_PAGE_NOT_PUBLISHED_OR_GONE") from None
        raise PublicPageFetchError("PUBLIC_PAGE_HTTP_NOT_OK") from None
    except (OSError,error.URLError) as exc:
        raise PublicPageFetchError("PUBLIC_PAGE_NETWORK_UNAVAILABLE") from exc


def capture_approved_public_pages(inbox,grant,*,urls,transport=None,clock=None,
                                  odds_race_id=None,
                                  odds_official_cutoff_at=None):
    """Capture owner-approved pages only. No odds/rider parsing or false clock.

    Body and metadata are stored create-once, private mode 0600. A changed
    page produces a NEW SHA rather than rewriting a prior observation.
    """
    root=Path(inbox).expanduser()
    require(root.is_absolute() and root.is_dir() and not root.is_symlink(),
            "PRIVATE_INBOX_REQUIRED")
    require(type(urls) in (tuple,list),"PUBLIC_URLS_LIST_REQUIRED")
    require((odds_race_id is None)==(odds_official_cutoff_at is None),
            "ODDS_RACE_AND_CUTOFF_BOTH_REQUIRED")
    checked=[]
    for url in urls:
        checked.append(approved_public_url(url,grant))
    require(len(checked)==len(set(checked)),
            "SAME_CYCLE_PUBLIC_URL_DUPLICATE")
    folder=root/"owner_public_capture"
    require(not folder.is_symlink(),"PUBLIC_CAPTURE_SYMLINK_REFUSED")
    if not folder.exists():
        folder.mkdir(mode=0o700)
    require(folder.is_dir(),"PUBLIC_CAPTURE_DIRECTORY_REQUIRED")
    receipts=[]
    for url in checked:
        body=transport(url) if transport is not None else network_page_once(url)
        require(type(body) is bytes and 0<len(body)<=MAX_HTML_BYTES,
                "PUBLIC_PAGE_BYTES_INVALID")
        observed=(clock() if clock is not None else
                  datetime.now(timezone.utc))
        require(isinstance(observed,datetime) and
                observed.utcoffset() is not None,
                "PUBLIC_CAPTURE_AWARE_CLOCK_REQUIRED")
        at=observed.astimezone(timezone.utc).isoformat()
        # The upstream publication time is NOT proven from a local wall clock.
        # Use URL plus body digest to dedupe across feeds.
        digest=sha256(body).hexdigest()
        anchor=sha256((url+"\n"+digest).encode("utf-8")).hexdigest()
        target=folder/(anchor+".html")
        receipt=folder/(anchor+".json")
        meta={
            "schema":"RACE_AI_KEIRIN_OWNER_PUBLIC_HTML_CAPTURE_V1",
            "source_url":url,"body_sha256":digest,
            "body_size_bytes":len(body),
            "captured_at_utc":at,
            "upstream_publication_time_independently_verified":False,
            "full_210_odds_parsed":False,
            "full_347_factor_audit_passed":False,
            "owner_automated_use_attested":True,
            "provider_automated_permission_independently_verified":False,
            "public_plaintext_published":False,
        }
        if target.exists() or receipt.exists():
            require(target.is_file() and receipt.is_file()
                    and not target.is_symlink() and not receipt.is_symlink()
                    and sha256(target.read_bytes()).hexdigest()==digest,
                    "PUBLIC_CAPTURE_IMMUTABILITY_CONFLICT")
            prior=json.loads(receipt.read_text(encoding="utf-8"))
            require(prior["source_url"]==url and
                    prior["body_sha256"]==digest and
                    prior["schema"]==meta["schema"],
                    "PUBLIC_CAPTURE_RECEIPT_CONFLICT")
            added=False
        else:
            try:
                fd=os.open(target,
                           os.O_WRONLY|os.O_CREAT|os.O_EXCL|
                           getattr(os,"O_NOFOLLOW",0),0o600)
                with os.fdopen(fd,"wb") as out:
                    out.write(body)
                    out.flush()
                    os.fsync(out.fileno())
                fd=os.open(receipt,
                           os.O_WRONLY|os.O_CREAT|os.O_EXCL|
                           getattr(os,"O_NOFOLLOW",0),0o600)
                with os.fdopen(fd,"wb") as out:
                    out.write(json.dumps(meta,sort_keys=True,
                                         ensure_ascii=False).encode("utf-8"))
                    out.flush()
                    os.fsync(out.fileno())
            except (OSError,ValueError) as exc:
                raise PublicPageFetchError("PUBLIC_CAPTURE_WRITE_FAILED") from exc
            require(sha256(target.read_bytes()).hexdigest()==digest,
                    "PUBLIC_CAPTURE_READBACK_FAILED")
            added=True
        private_odds_stage=None
        if odds_race_id is not None and (
            "/keirin/" in urlsplit(url).path and
            "/odds/" in urlsplit(url).path and
            (urlsplit(url).hostname or "") in (
                "winticket.jp","www.winticket.jp")
        ):
            from .keirin_winticket_embedded_odds import (
                private_winticket_trifecta,stage_private_winticket_odds
            )
            verified=private_winticket_trifecta(
                body,url=url,race_id=odds_race_id,
                captured_at=at,
                official_cutoff_at=odds_official_cutoff_at)
            private_odds_stage=stage_private_winticket_odds(root,verified)
        receipts.append({
            "new_capture":added,
            "capture_sha256":digest,
            "full_210_odds_parsed":bool(private_odds_stage),
            "private_odds_created":(
                private_odds_stage["private_odds_created"]
                if private_odds_stage else 0),
            "source_published_at_independently_proven":False,
        })
    return {
        "schema":"RACE_AI_KEIRIN_OWNER_PUBLIC_FETCH_BATCH_V1",
        "requested_url_count":len(checked),
        "network_requests":0 if transport is not None else len(checked),
        "captures_created":sum(int(x["new_capture"]) for x in receipts),
        "captures_already_retained":sum(int(not x["new_capture"]) for x in receipts),
        "complete_real_race_odds_verified":any(
            r["full_210_odds_parsed"] for r in receipts),
        "private_odds_originals_created":sum(
            r["private_odds_created"] for r in receipts),
        "private_plaintext_uploaded_to_public_repo":False,
    }
