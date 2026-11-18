"""Bounded public racecard capture -> normalized private A/B source cards.

Owner-authored manifest supplies *exact published URLs*. No URL patterns are
guessed from a race ID; no hidden API, credentials, antibot bypass, parallel
provider hammering or retries after 403/429. Captured HTML and normalized
cards are kept only in an owner-private 0700 path and never printed.

This collector does not independently certify publication rights, organizer
cutoff, race result or calendar completeness. Unknown/missing data stays HOLD.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
import json
import os
import stat
import argparse

from .keirin_public_two_source_normalizer import (
    merge_pre_race_pages, PublicPageNormalizeError)
from .keirin_nationwide_auto_generator import (
    AutomaticForecastError,VENUE,canonical,when)

SCHEMA="RACE_AI_KEIRIN_APPROVED_PUBLIC_TWO_SOURCE_DAY_URLS_V1"
REPORT="RACE_AI_KEIRIN_TWO_SOURCE_AUTO_CAPTURE_REPORT_V1"
MAX_BYTES=6_000_000
MAX_RACES_PER_RUN=8


class SourceCaptureError(ValueError):
    pass


def need(ok,code):
    if not ok:raise SourceCaptureError(code)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return None


def _allow_url(url,kind,rid):
    from .keirin_public_two_source_normalizer import _url_role
    try:
        _url_role(url,"net" if kind=="net" else "k",rid)
    except (PublicPageNormalizeError,AutomaticForecastError,TypeError):
        raise SourceCaptureError("UNAPPROVED_RACEPAGE_URL_OR_RID") from None
    return url


def fetch_once(url):
    """One regular GET, readable public HTML only. No retry on denial."""
    req=Request(url,headers={
        "User-Agent":"RACE-AI-PersonalResearch/1.0 (source attribution; no bypass)",
        "Accept":"text/html; charset=utf-8",
    },method="GET")
    response=None
    try:
        response=build_opener(NoRedirect()).open(req,timeout=12)
        code=response.status
        actual=response.geturl()
        content_type=response.headers.get("Content-Type","").lower()
        if code!=200 or actual!=url or (
                "text/html" not in content_type and
                "application/xhtml" not in content_type):
            raise SourceCaptureError("PROVIDER_NON_HTML_OR_REDIRECT")
        data=response.read(MAX_BYTES+1)
        if not 0<len(data)<=MAX_BYTES:
            raise SourceCaptureError("PROVIDER_EMPTY_OR_OVERSIZED_HTML")
        return data
    except HTTPError as exc:
        if exc.code in (403,429):
            raise SourceCaptureError("PROVIDER_DENIED_OR_RATE_LIMITED_STOP") from None
        raise SourceCaptureError("PUBLIC_PROVIDER_HTTP_ERROR_STOP") from None
    except (URLError, TimeoutError, OSError):
        raise SourceCaptureError("PUBLIC_PROVIDER_UNAVAILABLE_STOP") from None
    finally:
        if response is not None:response.close()


def private_dir(path):
    p=Path(path)
    need(p.is_absolute() and p.is_dir() and not p.is_symlink() and
         stat.S_IMODE(p.stat().st_mode)==0o700,
         "OWNER_PRIVATE_0700_FOLDER_REQUIRED")
    workspace=os.getenv("GITHUB_WORKSPACE")
    if workspace:
        ws=Path(workspace).resolve()
        resolved=p.resolve()
        need(resolved!=ws and ws not in resolved.parents,
             "PRIVATE_SOURCE_CANNOT_BE_IN_PUBLIC_GITHUB_WORKSPACE")
    return p


def manifest_check(doc,*,registered_ids):
    need(type(doc) is dict and set(doc)=={
        "schema","day_jst","races","source_use_scope"},
        "PUBLIC_CAPTURE_MANIFEST_SCHEMA_REQUIRED")
    need(doc["schema"]==SCHEMA and
         doc["source_use_scope"]=="OWNER_PERSONAL_RESEARCH_ONLY" and
         type(doc["day_jst"]) is str and len(doc["day_jst"])==10 and
         type(doc["races"]) is list and len(doc["races"])<=1000,
         "DAY_MANIFEST_WRONG_SCOPE")
    good_ids=set(registered_ids)
    seen=set()
    for row in doc["races"]:
        need(type(row) is dict and set(row)=={
            "race_id","netkeirin_url","kdreams_url","cutoff_hint"},
            "PUBLIC_SOURCE_PAIR_FIELDS_REQUIRED")
        rid=row["race_id"]
        need(type(rid) is str and VENUE.fullmatch(rid) and
             rid in good_ids and rid not in seen and
             rid[:4]+"-"+rid[4:6]+"-"+rid[6:8]==doc["day_jst"],
             "SOURCE_URL_RACE_NOT_IN_REGISTERED_DAY")
        seen.add(rid)
        _allow_url(row["netkeirin_url"],"net",rid)
        _allow_url(row["kdreams_url"],"kd",rid)
        hint=row["cutoff_hint"]
        if hint is not None:
            try:
                t=when(hint)
            except (AutomaticForecastError,TypeError):
                raise SourceCaptureError("CUTOFF_SORT_HINT_CLOCK_INVALID") from None
            need(t.date().isoformat() in (
                doc["day_jst"],
                # JST and UTC may span a date boundary; compare JST only.
                (t.astimezone(timezone.utc)).date().isoformat()),
                "CUTOFF_SORT_HINT_MISSING_DAY_BINDING")
    return doc


def _write_once(path,data):
    need(type(data) is bytes and len(data)<=MAX_BYTES,
         "PRIVATE_CAPTURE_BYTES_OVER_LIMIT")
    if path.exists() or path.is_symlink():
        need(path.is_file() and not path.is_symlink() and
             path.read_bytes()==data,
             "PRIVATE_SOURCE_EXISTING_SHA_CONFLICT")
        return False
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|
               getattr(os,"O_NOFOLLOW",0),0o600)
    with os.fdopen(fd,"wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    need(path.read_bytes()==data,"PRIVATE_SOURCE_CREATE_ONCE_READBACK_FAILED")
    return True


def capture_cycle(*,day_manifest,registered_ids,private_cards_dir,
                  private_raw_dir,clock=None,fetch=None,max_races=8):
    manifest_check(day_manifest,registered_ids=registered_ids)
    cards=private_dir(private_cards_dir)
    raw=private_dir(private_raw_dir)
    need(type(max_races) is int and 1<=max_races<=MAX_RACES_PER_RUN,
         "PUBLIC_SOURCE_BOUNDED_RACES_PER_RUN")
    clock=clock or (lambda:datetime.now(timezone.utc))
    fetch=fetch or fetch_once
    need(callable(clock) and callable(fetch),
         "SOURCE_COLLECTOR_CLOCK_OR_FETCH_REQUIRED")
    visited=0
    rows=[]
    # Prefer actual published close timestamps from venue-day manifests, but
    # only to order GETs: never treat a cutoff hint as verified official time.
    candidates=sorted(day_manifest["races"],
        key=lambda r:(r["cutoff_hint"] is None,r["cutoff_hint"] or "",
                      r["race_id"]))
    for item in candidates:
        rid=item["race_id"]
        dest=cards/(rid+".json")
        if dest.exists():
            rows.append({"race_id":rid,"state":"CAPTURE_ALREADY_PRESENT_CREATE_ONCE"})
            continue
        if visited>=max_races:
            rows.append({"race_id":rid,"state":"HOLD_FETCH_BUDGET_NOT_YET_TRIED"})
            continue
        visited+=1
        try:
            net=fetch(item["netkeirin_url"])
            net_at=clock().astimezone(timezone.utc).isoformat()
            kd=fetch(item["kdreams_url"])
            kd_at=clock().astimezone(timezone.utc).isoformat()
            created=clock().astimezone(timezone.utc).isoformat()
            result=merge_pre_race_pages(
                race_id=rid,netkeirin_raw=net,
                netkeirin_url=item["netkeirin_url"],
                netkeirin_captured_at=net_at,
                kdreams_raw=kd,
                kdreams_url=item["kdreams_url"],
                kdreams_captured_at=kd_at,
                created_at=created)
            # Only after BOTH sources validate may the card enter forecast
            # intake. The private original source byte receipts remain.
            _write_once(raw/(result["netkeirin_sha256"]+".html"),net)
            _write_once(raw/(result["kdreams_sha256"]+".html"),kd)
            payload=canonical(result["source_packet"])+b"\n"
            _write_once(dest,payload)
            rows.append({"race_id":rid,"state":"PRIVATE_CARD_NORMALIZED_FROM_TWO_PUBLIC_SOURCES",
                         "packet_sha256":sha256(payload).hexdigest()})
        except (SourceCaptureError,PublicPageNormalizeError,
                AutomaticForecastError,KeyError,ValueError,TypeError,OSError) as exc:
            reason=str(exc)
            if reason not in (
                "PROVIDER_DENIED_OR_RATE_LIMITED_STOP",
                "PUBLIC_PROVIDER_HTTP_ERROR_STOP",
                "PUBLIC_PROVIDER_UNAVAILABLE_STOP"):
                reason="SOURCE_PAGE_PARSING_OR_PROVENANCE_HOLD"
            rows.append({"race_id":rid,"state":"HOLD_"+reason})
            if reason in (
                "PROVIDER_DENIED_OR_RATE_LIMITED_STOP",
                "PUBLIC_PROVIDER_HTTP_ERROR_STOP",
                "PUBLIC_PROVIDER_UNAVAILABLE_STOP"):
                # Stop globally, no repeated probes to a blocked provider.
                break
    counts=Counter(row["state"] for row in rows)
    return {
        "schema":REPORT,"day_jst":day_manifest["day_jst"],
        "source_manifest_races":len(day_manifest["races"]),
        "GET_pair_attempts":visited,
        "normalized_private_cards":counts[
            "PRIVATE_CARD_NORMALIZED_FROM_TWO_PUBLIC_SOURCES"],
        "unlisted_races_are_unregistered_not_forecasted":True,
        "official_cutoff_independently_certified":False,
        "provider_rights_independently_certified":False,
        "no_official_results_used":True,
        "no_plaintext_rider_data_in_report":True,
        "states":dict(sorted(counts.items())),"records":rows}


def main(argv=None):
    from .keirin_nationwide_auto_forecast import registered_race_ids
    p=argparse.ArgumentParser()
    p.add_argument("--day-manifest",required=True)
    p.add_argument("--registry",required=True)
    p.add_argument("--private-cards-dir",required=True)
    p.add_argument("--private-raw-dir",required=True)
    p.add_argument("--report",required=True)
    p.add_argument("--max-races",type=int,default=8)
    a=p.parse_args(argv)
    try:
        manifest=json.loads(Path(a.day_manifest).read_text(encoding="utf-8"))
        reg=json.loads(Path(a.registry).read_text(encoding="utf-8"))
        report=capture_cycle(
            day_manifest=manifest,registered_ids=registered_race_ids(reg),
            private_cards_dir=a.private_cards_dir,
            private_raw_dir=a.private_raw_dir,
            max_races=a.max_races)
        target=Path(a.report)
        need(target.is_absolute() and target.parent.is_dir() and
             not target.exists() and not target.is_symlink(),
             "PUBLIC_CAPTURE_REPORT_MUST_BE_CREATE_ONCE")
        data=canonical(report)+b"\n"
        _write_once(target,data)
        print(json.dumps({k:report[k] for k in (
            "day_jst","source_manifest_races","GET_pair_attempts",
            "normalized_private_cards","states")},sort_keys=True))
        return 0
    except (ValueError,KeyError,TypeError,OSError):
        print('{"state":"HOLD_PUBLIC_TWO_SOURCE_CAPTURE_NOT_AVAILABLE"}')
        return 2


if __name__=="__main__":
    raise SystemExit(main())
