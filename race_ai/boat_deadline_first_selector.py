"""Pure deadline-first selector from a parsed first-party official B closing map.

No odds, results, I/O, provider permissions or predictive claims.
"""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import re

ID=re.compile(r"(?P<day>\d{8})-(?P<venue>0[1-9]|1\d|2[0-4])-(?P<no>0[1-9]|1[0-2])\Z")
JST=ZoneInfo("Asia/Tokyo")
class CloseWindowError(ValueError):pass

def all_closing_candidates(closing, *, now, day_jst, min_minutes=0, max_minutes=None):
    if not isinstance(closing,dict) or not isinstance(now,datetime) or now.utcoffset() is None:
        raise CloseWindowError("official deadline map and aware clock required")
    if not isinstance(day_jst,str) or not re.fullmatch(r"\d{8}",day_jst):
        raise CloseWindowError("exact event day required")
    if not isinstance(min_minutes,(float,int)) or isinstance(min_minutes,bool) or not 0<=min_minutes<60:
        raise CloseWindowError("invalid minimum cutoff lead time")
    if max_minutes is not None and (not isinstance(max_minutes,(float,int)) or isinstance(max_minutes,bool) or not min_minutes<max_minutes<=1440):
        raise CloseWindowError("invalid optional maximum lead time")
    candidates=[]
    for key,value in closing.items():
        m=ID.fullmatch(key) if isinstance(key,str) else None
        if m is None or not isinstance(value,str):
            raise CloseWindowError("invalid B race/deadline identity")
        if m["day"]!=day_jst:raise CloseWindowError("B schedule date mismatch")
        try:cutoff=datetime.fromisoformat(value.replace("Z","+00:00"))
        except ValueError as exc:raise CloseWindowError("unparseable cutoff") from exc
        if cutoff.utcoffset() is None or cutoff.astimezone(JST).strftime("%Y%m%d")!=day_jst:
            raise CloseWindowError("cutoff timezone or race date mismatch")
        delta=cutoff-now
        if delta.total_seconds()>0 and delta>=timedelta(minutes=min_minutes) and (max_minutes is None or delta<=timedelta(minutes=max_minutes)):
            candidates.append({"race_id":key,"venue_code":m["venue"],
                "race_no":int(m["no"]),"scheduled_cutoff":value,
                "minutes_remaining_at_selection":round(delta.total_seconds()/60,3)})
    return sorted(candidates,key=lambda x:(x["scheduled_cutoff"],x["race_id"]))

def pick_first_ready(audits):
    """Earliest complete pre-cutoff preview among audited candidates."""
    if not isinstance(audits,list):raise CloseWindowError("audits list required")
    valid=[]
    for row in audits:
        if not isinstance(row,dict) or not isinstance(row.get("race_id"),str):
            raise CloseWindowError("invalid audit record")
        if (row.get("preview_identity_matched") is True
            and row.get("display_numeric_count")==6
            and row.get("ST_numeric_count")==6
            and row.get("wind_available") is True
            and row.get("wave_available") is True
            and row.get("collected_before_scheduled_cutoff") is True):
            valid.append(row)
    return min(valid,key=lambda x:(x["scheduled_cutoff"],x["race_id"])) if valid else None


def pick_first_published_preview(audits):
    """Use observed first-party beforeinfo AVAILABLE; no cutoff-distance limit.

    Observed availability is NOT proof of original source publication clock,
    purpose-specific reuse permission, numeric completeness or model entry.
    An available preview with nonnumeric F/L/ST is still a *published*
    observation but cannot enter PR71 FULL unless all mandatory inputs pass.
    """
    if not isinstance(audits,list):
        raise CloseWindowError("pre-race observation list required")
    published=[]
    for row in audits:
        if not isinstance(row,dict) or not isinstance(row.get("race_id"),str):
            raise CloseWindowError("invalid beforeinfo observation")
        if (row.get("preview_status")=="AVAILABLE" and
            row.get("preview_identity_matched") is True and
            row.get("collected_before_scheduled_cutoff") is True and
            row.get("scheduled_cutoff")):
            published.append(row)
    return min(published,key=lambda x:(x["scheduled_cutoff"],x["race_id"])) if published else None
