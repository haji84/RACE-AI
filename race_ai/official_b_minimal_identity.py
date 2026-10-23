"""Bridge actual PR64 minimal official B parser records into PR72 audit ledger.

No model inference and NO guessed sales cutoff. The PR64 strict detailed
parser may reject real archive revisions, but the minimal six-entrant race
identity can still be audited separately, never elevated to a forecast.
"""
from __future__ import annotations
from datetime import date
from collections import defaultdict
from hashlib import sha256
import json,re
from .operator_export_intake import transform,SCHEMA,IntakeError
from .official_bk_archive_transport import archive_url

class MinimalOfficialBError(ValueError):pass

def to_audit(parsed_racers,*,event_date_jst,source_url,archive_sha256,
             observed_at_claimed,rights_ref):
    try:
        d=date.fromisoformat(event_date_jst)
    except (TypeError,ValueError) as exc:
        raise MinimalOfficialBError("invalid official B event day") from exc
    if d.isoformat()!=event_date_jst or archive_url(d,"B")!=source_url:
        raise MinimalOfficialBError("event date / B source URL mismatch")
    if not isinstance(archive_sha256,str) or not re.fullmatch(r"[0-9a-f]{64}",archive_sha256):
        raise MinimalOfficialBError("raw archive SHA256 required")
    if not isinstance(rights_ref,str) or not rights_ref.strip() or len(rights_ref)>256:
        raise MinimalOfficialBError("source rights reference required, not approved by adapter")
    if not isinstance(parsed_racers,list) or not 6<=len(parsed_racers)<=24*12*6:
        raise MinimalOfficialBError("bounded official B parsed racers required")
    groups=defaultdict(dict)
    expected_head=d.strftime("%Y%m%d")
    for item in parsed_racers:
        if not isinstance(item,dict) or not {"race_id","lane","racer_id"}<=set(item):
            raise MinimalOfficialBError("minimal parsed racer identity missing")
        ident=item["race_id"]
        if not isinstance(ident,str) or not re.fullmatch(r"\d{8}-\d{2}-\d{2}",ident):
            raise MinimalOfficialBError("official B race ID invalid")
        day,venue,number=ident.split("-")
        if day!=expected_head or not 1<=int(venue)<=24 or not 1<=int(number)<=12:
            raise MinimalOfficialBError("official B race ID/event day mismatch")
        lane=item["lane"]
        reg=item["racer_id"]
        if type(lane) is not int or not 1<=lane<=6 or not isinstance(reg,str) or not re.fullmatch(r"\d{4}",reg):
            raise MinimalOfficialBError("illegal lane or official registration")
        if lane in groups[ident]:
            raise MinimalOfficialBError("duplicate lane")
        groups[ident][lane]=reg
    if not groups or any(set(r)!=set(range(1,7)) or len(set(r.values()))!=6
                         for r in groups.values()):
        raise MinimalOfficialBError("incomplete or duplicate six-boat roster")
    manifest={"schema":SCHEMA,"event_date_jst":d.isoformat(),
              "source_ref":source_url,"source_rights_ref":rights_ref,
              "captured_at":observed_at_claimed,
              "races":[{"sport":"boat","venue":"boatrace-jcd-"+rid.split("-")[1],
                        "race_no":int(rid.split("-")[2]),
                        "sales_cutoff_at":None,"offering_status":"UNKNOWN"}
                       for rid in sorted(groups)]}
    report=transform(manifest,archive_sha256)
    report["minimal_b_real_source_audit"]={
        "schema":"RACE_AI_OFFICIAL_B_MINIMAL_IDENTITY_GATE_V1",
        "event_date_jst":event_date_jst,
        "source_url":source_url,
        "archive_sha256":archive_sha256,
        "race_id_count":len(groups),
        "entrant_rows_count":len(parsed_racers),
        "venue_count":len({r.split("-")[1] for r in groups}),
        "racer_registration_numbers_not_republished":True,
        "raw_archive_not_embedded":True,
        "true_sales_cutoff_verified":False,
        "source_original_first_published_at":None,
        "sample_n":None,
        "model_feature_ready":False,
        "prediction_generated":False,
        "official_result_verified":False,
        "complete_all_venues_verified":False,
        "collection_rights_approved_by_adapter":False,
        "status":"OFFICIAL_B_MINIMAL_ROSTERS_AUDIT_ONLY"}
    return report
