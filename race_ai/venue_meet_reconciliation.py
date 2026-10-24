"""Strict same-meet identity and full-day lane reconciliation (offline only)."""
from datetime import date
import re
from .core import SourceError
from .venue_detail_join import canonical_name


def reconcile(index, allocations, *, day: date, meet, race_meet_id, motor_meet_id):
    mid=meet.get("meet_id")
    if not isinstance(mid,str) or not re.fullmatch(r"18-\d{8}-\d{8}",mid):
        raise SourceError("invalid meet ID")
    start=date.fromisoformat(meet["start_date"])
    end=date.fromisoformat(meet["end_date"])
    if (mid!=f"18-{start:%Y%m%d}-{end:%Y%m%d}" or
        mid!=race_meet_id or mid!=motor_meet_id or
        not start<=day<=end or meet.get("identity_verified") is not True):
        raise SourceError("meet mismatch or unverified")
    if index.get("venue")!="18" or index.get("date_jst")!=day.isoformat():
        raise SourceError("wrong race date/venue")
    races=index.get("races",[])
    if len(races)!=12 or {r["race_id"] for r in races}!={f"{day:%Y%m%d}-18-{n:02d}" for n in range(1,13)}:
        raise SourceError("incomplete race list")
    motors={}
    for row in allocations:
        name=canonical_name(row.get("name"))
        if row.get("meet_id")!=mid or not name or name in motors:
            raise SourceError("ambiguous or wrong-meet motor row")
        motors[name]=row
    entries=[]
    for race in races:
        boats=race.get("boats",[])
        if len(boats)!=6 or {b.get("lane") for b in boats}!={1,2,3,4,5,6}:
            raise SourceError("missing/duplicate lane")
        for boat in boats:
            if boat.get("status") in ("ABSENT","REPLACED"):
                raise SourceError("entry change requires updated verified list")
            motor=motors.get(canonical_name(boat.get("name")))
            if motor is None:
                raise SourceError("unmatched racer")
            registration=motor.get("racer_registration_id")
            number=motor.get("motor_no")
            if not isinstance(registration,str) or not re.fullmatch(r"\d{4}",registration):
                raise SourceError("invalid registration")
            if type(number) is not int or not 1<=number<=999:
                raise SourceError("invalid motor")
            entries.append({"race_id":race["race_id"],"lane":boat["lane"],
                            "racer_registration_id":registration,"motor_no":number})
    if len(entries)!=72:
        raise SourceError("incomplete entries")
    return {"date_jst":day.isoformat(),"meet_id":mid,"races":12,"entries":entries,
            "status":"STRUCTURAL_JOIN_NOT_PUBLICATION_PERMISSION"}
