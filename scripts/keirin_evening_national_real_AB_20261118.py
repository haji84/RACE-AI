"""Actual evening remaining-races pilot: 2026-11-18 KOCHI + UTSUNOMIYA.

Discover race URLs only from the TWO real venue-day Kdreams racecard pages,
then use actual netkeirin/Kdreams HTML to compute A/B six-phase predictions
and RSA/AES-GCM seal each eligible race before its published sales cutoff.

No predictions after cutoff. 17 prospective IDs (1 previously sealed
Utsunomiya, 9 Kochi, 8 further Utsunomiya). 60 earlier races remain
NO_FORECAST. No model C without authenticated real line history.
One GET per verified source URL; stop on provider denial. This is a one-day
bridge before a dynamic nationwide source feeder.
"""
from __future__ import annotations

from datetime import datetime,timezone,timedelta
from pathlib import Path
from hashlib import sha256
from collections import Counter
import json,os,stat

from race_ai import keirin_nationwide_auto_generator as model
from race_ai import keirin_nationwide_auto_storage as storage
from scripts import keirin_capture_public_two_sources as cap
from scripts import keirin_discover_public_race_links as links
from scripts.keirin_nationwide_auto_forecast import (
    checked_raw_sources,registered_race_ids)

DAY="2026-11-18"
SCHEMA="RACE_AI_KEIRIN_REAL_20261118_EVENING_AB_AUTO_BATCH_V1"
JST=timezone(timedelta(hours=9))
SCHEDULE={
  "74": ("高知",
     "https://keirin.kdreams.jp/kochi/racecard/74202611170200/",
     ["20:35","20:55","21:15","21:35","21:55",
      "22:15","22:35","22:55","23:15"]),
  "24": ("宇都宮",
     "https://keirin.kdreams.jp/utsunomiya/racecard/24202611170200/",
     ["20:45","21:05","21:25","21:45","22:05",
      "22:25","22:45","23:05","23:25"]),
}
PREVIOUSLY_SEALED={
  "202611182401":"actual RSA/AES sealed by GitHub run 44234778255",
  "202611182601":"prior manual research A/B sealed immutable Git receipt",
}
PROVIDER_ERRORS={
 "PROVIDER_DENIED_OR_RATE_LIMITED_STOP",
 "PUBLIC_PROVIDER_HTTP_ERROR_STOP",
 "PUBLIC_PROVIDER_UNAVAILABLE_STOP",
}
MAX_NEW_RACES=17


def require(ok,code):
    if not ok:raise ValueError(code)


def safe_record(rid,state,**detail):
    return {"race_id":rid,"state":state,**detail}


def _get_error(exc):
    return str(exc) in PROVIDER_ERRORS


def _time(val):
    return model.when(val)


def _cutoff(code,race_no):
    clock=SCHEDULE[code][2][race_no-1]
    return f"{DAY}T{clock}:00+09:00"


def _is_private(path):
    p=Path(path)
    return (p.is_absolute() and p.is_dir() and not p.is_symlink() and
            stat.S_IMODE(p.stat().st_mode)==0o700)


def run(*,registry, private_root,owner_public_key_pem,
        clock=None,fetch=None,max_new_races=17,
        prior_sealed_sha_by_race=None):
    """One owner-private actual batch with only code-grounded 17 possible RIDs."""
    registered=set(registered_race_ids(registry))
    require(type(max_new_races) is int and 1<=max_new_races<=17,
            "BOUNDED_NEW_RACES_1_TO_17")
    root=Path(private_root)
    require(_is_private(root),"OWNER_PRIVATE_0700_ROOT_REQUIRED")
    for sub in ("cards","raw","sealed"):
        require(_is_private(root/sub),"OWNER_PRIVATE_0700_SUBDIR_REQUIRED")
    storage.checked_public_key(owner_public_key_pem)
    previous=dict(PREVIOUSLY_SEALED)
    if prior_sealed_sha_by_race is not None:
        require(type(prior_sealed_sha_by_race) is dict and
                len(prior_sealed_sha_by_race)<=17,
                "PRIOR_SEALED_SOURCE_RECEIPTS_INVALID")
        for rid,expected_sha in prior_sealed_sha_by_race.items():
            require(rid in registered and rid not in previous and
                    type(expected_sha) is str and len(expected_sha)==64 and
                    all(ch in "0123456789abcdef" for ch in expected_sha),
                    "PRIOR_SEALED_SOURCE_ID_OR_SHA_INVALID")
            file=root/"prior"/"sealed"/(rid+".sealed.json")
            verified=storage.readback_file(file,expected_sha=expected_sha)
            require(verified["race_id"]==rid,
                    "PRIOR_SEALED_RACE_SOURCE_MISMATCH")
            previous[rid]=expected_sha
    clock=clock or (lambda:datetime.now(timezone.utc))
    fetch=fetch or cap.fetch_once
    records={rid:safe_record(rid,"NO_FORECAST_NO_VALID_PRE_RACE_INPUT")
             for rid in sorted(registered)}
    for rid in previous:
        require(rid in registered,"OLD_SAVED_CASE_NOT_IN_REGISTERED_COHORT")
        records[rid]=safe_record(rid,"PREVIOUS_IMMUTABLE_FORECAST_NOT_RECREATED")
    cutoff_candidates=[]
    for code,(_,url,times) in SCHEDULE.items():
        for i in range(1,10):
            rid="20261118"+code+f"{i:02d}"
            require(rid in registered,"NIGHT_RACE_NOT_IN_FROZEN_COHORT")
            if rid in previous:
                continue
            cutoff_candidates.append((rid,_cutoff(code,i),code,i))
    cutoff_candidates.sort(key=lambda item:_time(item[1]))
    # Only pre-cutoff candidates are considered for ordinary source GETs.
    before=[x for x in cutoff_candidates
            if (_time(x[1])-clock().astimezone(timezone.utc)).total_seconds()>=65]
    for rid,at,_,_ in cutoff_candidates:
        if rid not in {x[0] for x in before}:
            records[rid]=safe_record(rid,"NO_FORECAST_PUBLISHED_CUTOFF_ALREADY_PASSED")
    required_codes={rid[8:10] for rid,*_ in before}
    available_urls={}
    source_structure=[]
    count_meeting_GET=0
    for code in sorted(required_codes):
        day_url=SCHEDULE[code][1]
        try:
            blob=fetch(day_url)
            count_meeting_GET+=1
            candidates=links.linked_details(blob,base_url=day_url,
                                             day=DAY,venue=code)
            from bs4 import BeautifulSoup
            from urllib.parse import urlsplit,urljoin
            soup=BeautifulSoup(blob,"html.parser")
            anchors=soup.find_all("a",href=True)
            path_templates={}
            for a in anchors:
                p=urlsplit(urljoin(day_url,a["href"])).path
                if "racedetail" in p.lower() or "racecard" in p.lower():
                    import re
                    masked=re.sub(r"[0-9]","D",p)
                    path_templates[masked]=path_templates.get(masked,0)+1
            source_structure.append({
                "venue_code":code,
                "total_hrefs":len(anchors),
                "detail_links_validated":len(candidates),
                "detail_route_templates":dict(sorted(path_templates.items())),
                "contains_racedetail_literal_in_html":
                    b"racedetail" in blob.lower(),
            })
            for rid,url in candidates.items():
                if rid in registered:
                    available_urls[rid]=url
        except (cap.SourceCaptureError,links.DayLinksError,
                OSError,TypeError,ValueError) as exc:
            msg=str(exc)
            safe=(msg.isascii() and msg.isupper() and
                  msg.replace("_","").isalnum() and len(msg)<90)
            source_structure.append({
                "venue_code":code,
                "source_fetch_or_link_error":msg if safe else "UNVERIFIED_LINK_STRUCTURE",
            })
            if _get_error(exc):
                for rid,*_ in before:
                    records[rid]=safe_record(rid,
                       "HOLD_PUBLIC_PROVIDER_DENIED_OR_UNAVAILABLE_STOP")
                return _summary(records,count_meeting_GET,0,0,True,source_structure,len(previous))
            # Missing venue links keeps its races on HOLD.
    attempt_pairs=0
    saved=0
    abort=False
    for rid,deadline,code,race_no in before:
        if attempt_pairs>=max_new_races or abort:
            records[rid]=safe_record(rid,
                "HOLD_PROBE_LIMIT_OR_PROVIDER_STOP")
            continue
        url=available_urls.get(rid)
        if not url:
            records[rid]=safe_record(rid,
                "HOLD_KDREAMS_RACE_DETAIL_LINK_NOT_SEEN")
            continue
        if (_time(deadline)-clock().astimezone(timezone.utc)).total_seconds()<65:
            records[rid]=safe_record(rid,
                "NO_FORECAST_PUBLISHED_CUTOFF_ALREADY_PASSED")
            continue
        attempt_pairs+=1
        net=f"https://keirin.netkeiba.com/race/entry/?race_id={rid}"
        day_manifest={
            "schema":cap.SCHEMA,
            "day_jst":DAY,
            "source_use_scope":"OWNER_PERSONAL_RESEARCH_ONLY",
            "races":[{
                "race_id":rid,"netkeirin_url":net,
                "kdreams_url":url,"cutoff_hint":deadline}]}
        try:
            captured=cap.capture_cycle(
                day_manifest=day_manifest,
                registered_ids=list(registered),
                private_cards_dir=root/"cards",
                private_raw_dir=root/"raw",
                clock=clock,fetch=fetch,max_races=1)
            if captured["normalized_private_cards"]!=1:
                reasons=captured["states"]
                records[rid]=safe_record(rid,
                    "HOLD_REAL_SOURCE_CAPTURE_OR_NORMALIZATION",
                    source_state_codes=list(reasons))
                if any("PROVIDER_" in reason for reason in reasons):
                    abort=True
                continue
            file=root/"cards"/(rid+".json")
            packet=json.loads(file.read_text(encoding="utf-8"))
            require(packet["race_id"]==rid,"RECEIVED_WRONG_RACE")
            # The verified actual page cutoff MUST match the independent
            # day index published time. Do not use schedule hints for facts.
            require(_time(packet["published_cutoff_at"])==_time(deadline),
                    "OFFICIAL_PROVIDER_CUTOFF_DIFFERENCE_HOLD")
            checked_raw_sources(packet,root/"raw")
            generated_at=clock().astimezone(timezone.utc).isoformat()
            forecast=model.generate_A_B(packet,generated_at=generated_at)
            cipher_path=root/"sealed"/(rid+".sealed.json")
            receipt=storage.seal_once(
                snapshot=packet,prediction=forecast,
                public_key_pem=owner_public_key_pem,
                path=cipher_path,
                sealed_at=clock().astimezone(timezone.utc).isoformat())
            saved+=1
            records[rid]=safe_record(
                rid,"REAL_A_B_RSA_AES_SEALED_SAME_JOB",
                public_source_facts_sha256=model.digest(packet),
                cutoff_at=deadline,
                A_tickets=len(forecast["A"]["ranked_tickets"]),
                B_tickets=len(forecast["B"]["ranked_tickets"]),
                B_six_phase_scenarios=len(forecast["B"]["six_phase_scenarios"]),
                ciphertext_file_sha256=receipt["cipher_sha256"],
                A_cipher_sha256=receipt["A_cipher_sha256"],
                B_cipher_sha256=receipt["B_cipher_sha256"])
        except (cap.SourceCaptureError,ValueError,KeyError,TypeError,
                model.AutomaticForecastError,
                storage.AutoSealError,OSError) as exc:
            reason=str(exc)
            safe=(reason.isascii() and len(reason)<=95 and
                  reason.replace("_","").isalnum() and
                  reason.replace("_","").isupper())
            records[rid]=safe_record(
                rid,"HOLD_"+(reason if safe else "UNVERIFIED_SOURCE_OR_CIPHER"))
    return _summary(records,count_meeting_GET,attempt_pairs,saved,abort,source_structure,len(previous))


def _summary(records,meeting_gets,attempts,saved,blocked,source_structure,prior_count):
    states=Counter(v["state"] for v in records.values())
    require(len(records)==79,"FROZEN_NATIONAL_COHORT_NOT_79")
    return {
       "schema":SCHEMA,"day_jst":DAY,
       "registered_races":79,
       "previously_sealed_A_B_do_not_recreate":prior_count,
       "new_A_B_same_job_encrypted":saved,
       "venue_index_public_GETs":meeting_gets,
       "race_source_pair_attempts":attempts,
       "provider_abort":blocked,
       "source_meeting_link_structure":source_structure,
       "official_result_scored":0,
       "organizer_actual_sales_close_independently_verified":False,
       "source_html_and_plain_predictions_not_in_this_report":True,
       "C_optional_HOLD":True,
       "four_model_PR71_dependency":False,
       "statuses":dict(sorted(states.items())),
       "records":[records[rid] for rid in sorted(records)]
    }


def main(argv=None):
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--registry",required=True)
    p.add_argument("--private-root",required=True)
    p.add_argument("--owner-public-key",required=True)
    p.add_argument("--safe-report",required=True)
    p.add_argument("--prior-artifact-dir")
    args=p.parse_args(argv)
    try:
        root=Path(args.private_root)
        reg=json.loads(Path(args.registry).read_text(encoding="utf-8"))
        prior=None
        if args.prior_artifact_dir:
            prior_dir=Path(args.prior_artifact_dir)
            legacy=json.loads((prior_dir/"producer-summary.json").read_text(
                encoding="utf-8"))
            require(legacy.get("schema")==
                    "RACE_AI_KEIRIN_NATIONWIDE_AUTO_GENERATION_CYCLE_V1" and
                    legacy.get("registered_races")==79 and
                    type(legacy.get("records")) is list and
                    len(legacy["records"])==79,
                    "PRIOR_ARTIFACT_PRODUCER_RECEIPT_INVALID")
            prior={x["race_id"]:x["cipher_file_sha256"]
                   for x in legacy["records"]
                   if x.get("ciphertext_local_created") is True}
            require(len(prior)>0,"PRIOR_ARTIFACT_HAS_NO_REAL_CIPHERS")
        report=run(
            registry=reg,private_root=args.private_root,
            owner_public_key_pem=Path(args.owner_public_key).read_bytes(),
            prior_sealed_sha_by_race=prior)
        dest=Path(args.safe_report)
        require(not dest.exists() and not dest.is_symlink(),
                "REPORT_NO_OVERWRITE")
        raw=model.canonical(report)+b"\n"
        fd=os.open(dest,os.O_WRONLY|os.O_CREAT|os.O_EXCL|
                   getattr(os,"O_NOFOLLOW",0),0o600)
        with os.fdopen(fd,"wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        if report["new_A_B_same_job_encrypted"]>0:
            # For a DIFFERENT independent GitHub runner. No plaintext cards,
            # no winner/score and no organizer-result claim.
            producer={
                "schema":"RACE_AI_KEIRIN_NATIONWIDE_AUTO_GENERATION_CYCLE_V1",
                "day_jst":DAY,
                "registered_races":79,
                "records":[]}
            for row in report["records"]:
                entry={"race_id":row["race_id"],
                       "ciphertext_local_created":row["state"]==
                           "REAL_A_B_RSA_AES_SEALED_SAME_JOB"}
                if entry["ciphertext_local_created"]:
                    entry["cipher_file_sha256"]=row["ciphertext_file_sha256"]
                    entry["A_cipher_sha256"]=row["A_cipher_sha256"]
                    entry["B_cipher_sha256"]=row["B_cipher_sha256"]
                producer["records"].append(entry)
            path=root/"producer-summary.json"
            require(not path.exists(),"PRODUCER_NO_OVERWRITE")
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|
                       getattr(os,"O_NOFOLLOW",0),0o600)
            with os.fdopen(fd,"wb") as f:
                f.write(model.canonical(producer)+b"\n")
                f.flush()
                os.fsync(f.fileno())
        print(json.dumps({k:report[k] for k in (
            "registered_races","new_A_B_same_job_encrypted",
            "race_source_pair_attempts","venue_index_public_GETs",
            "provider_abort","statuses","source_meeting_link_structure")},sort_keys=True))
        return 0
    except (OSError,ValueError,KeyError,TypeError,
            storage.AutoSealError):
        print('{"state":"HOLD_NIGHT_BATCH_NOT_VERIFIED","new_A_B_same_job_encrypted":0}')
        return 2


if __name__=="__main__":
    raise SystemExit(main())
