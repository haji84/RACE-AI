"""Strict synthetic snapshot adapter around PR64's PL baseline. No fitted model."""
from datetime import date, datetime, timezone, timedelta
import hashlib
import itertools
import json
import math
import re
from .legacy_boat_rank import PredictionError, plackett_luce

class ContractError(PredictionError):
    pass

FEATURES = {"boat":"historical_rating", "keirin":"competition_points",
            "autorace":"trial_rating", "horse":"form_rating"}
MODEL = {"id":"synthetic-pl", "version":"1", "trained_until":"2029-01-01T00:00:00+00:00",
         "status":"UNTRAINED_SYNTHETIC", "feature_allowlist_sha":None}
def canonical(value):
    try:
        return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)
    except (ValueError,TypeError) as exc:
        raise ContractError("finite canonical JSON required") from exc

def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

MODEL["feature_allowlist_sha"]=digest(FEATURES)

def stamp(value):
    if not isinstance(value,str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})",value):
        raise ContractError("timezone-aware timestamp required")
    try:
        return datetime.fromisoformat(value.replace("Z","+00:00")).astimezone(timezone.utc)
    except ValueError as exc:
        raise ContractError("invalid timestamp") from exc

def exact(value,keys):
    if not isinstance(value,dict) or set(value)!=set(keys.split()):
        raise ContractError("unsupported fields; only explicit odds-free schema allowed")

def race_key(snapshot):
    return digest(snapshot["race_id"])

def validate_snapshot(raw, *, require_features=True):
    s=json.loads(canonical(raw))
    exact(s,"race_id revision scheduled_start_at sales_cutoff_at status trifecta_offered source participants as_of snapshot_hash scope")
    if s["scope"]!="SYNTHETIC_ONLY":
        raise ContractError("real data requires separate rights/storage admission")
    if s["snapshot_hash"]!=digest({k:v for k,v in s.items() if k!="snapshot_hash"}):
        raise ContractError("input hash mismatch")
    r=s["race_id"]
    exact(r,"sport organizer venue meeting event_date_jst race_no")
    if r["sport"] not in FEATURES or type(r["race_no"]) is not int or not 1<=r["race_no"]<=99:
        raise ContractError("invalid sport/race identity")
    for key in ("organizer","venue","meeting"):
        if not isinstance(r[key],str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}",r[key]):
            raise ContractError("explicit stable identity required")
    try: day=date.fromisoformat(r["event_date_jst"])
    except (ValueError,TypeError) as exc: raise ContractError("JST day required") from exc
    if r["event_date_jst"]!=day.isoformat():
        raise ContractError("canonical YYYY-MM-DD JST identity required")
    if type(s["revision"]) is not int or s["revision"]<1 or s["status"] not in ("scheduled","cancelled","postponed"):
        raise ContractError("invalid revision/status")
    if type(s["trifecta_offered"]) is not bool:
        raise ContractError("explicit trifecta offering required")
    cutoff,start,asof=map(stamp,(s["sales_cutoff_at"],s["scheduled_start_at"],s["as_of"]))
    if not asof<cutoff<=start or cutoff.astimezone(timezone(timedelta(hours=9))).date()!=day:
        raise ContractError("as-of / authoritative sales cutoff / JST day mismatch")
    src=s["source"]
    exact(src,"url permission_id available_at observed_at fetched_at registered_at transform_version")
    if src["url"]!="synthetic://fixture" or src["permission_id"]!="synthetic-v1" or src["transform_version"]!="fixture-v1":
        raise ContractError("synthetic provider only")
    times=[stamp(src[k]) for k in ("available_at","observed_at","fetched_at","registered_at")]
    if times!=sorted(times) or times[-1]>asof or stamp(MODEL["trained_until"])>=asof:
        raise ContractError("future or inconsistent feature provenance")
    rows=s["participants"]
    if not isinstance(rows,list) or not 3<=len(rows)<=18:
        raise ContractError("3..18 explicit participants required")
    if r["sport"]=="boat" and len(rows)!=6 or r["sport"]=="keirin" and len(rows) not in (7,9):
        raise ContractError("unsupported sport field size")
    seen=set()
    for row in rows:
        exact(row,"participant features")
        p=row["participant"]
        if type(p) is not int or not 1<=p<=99 or p in seen:
            raise ContractError("unique participant identities required")
        seen.add(p)
        exact(row["features"],FEATURES[r["sport"]])
        strength=row["features"][FEATURES[r["sport"]]]
        if strength is None and not require_features:
            continue
        if type(strength) not in (int,float) or not math.isfinite(strength) or not 1e-9<=strength<=1e9:
            raise ContractError("missing/nonfinite/unavailable rating")
    return s

def forecast(raw):
    s=validate_snapshot(raw)
    field=FEATURES[s["race_id"]["sport"]]
    strengths={r["participant"]:r["features"][field] for r in s["participants"]}
    if s["race_id"]["sport"]=="boat" and set(strengths)==set(range(1,7)):
        candidates=[{"combination":r["combination"],"score":r["probability"]}
                    for r in plackett_luce(strengths)["triples"]]
    else:
        # Same sequential conditional PL formula as the reused six-boat kernel;
        # enumerate top-three only (never N! horse full-order permutations).
        candidates=[]
        for order in itertools.permutations(sorted(strengths),3):
            remaining=list(sorted(strengths))
            probability=1.0
            for p in order:
                probability*=strengths[p]/math.fsum(strengths[q] for q in remaining)
                remaining.remove(p)
            candidates.append({"combination":list(order),"score":probability})
        mass=math.fsum(r["score"] for r in candidates)
        for row in candidates: row["score"]/=mass
    candidates.sort(key=lambda row:(-row["score"],row["combination"]))
    value={"snapshot_hash":s["snapshot_hash"],"race_key":race_key(s),"revision":s["revision"],
           "model":dict(MODEL),"as_of":s["as_of"],"generated_at":s["as_of"],
           "candidates":candidates,"full_candidate_hash":digest(candidates),
           "ordered_top8":[r["combination"] for r in candidates[:8]],
           "validation_status":"UNVALIDATED","official_prediction":False,
           "scope":"SYNTHETIC_ONLY","purchase_decision":"NO_BET"}
    value["prediction_hash"]=digest(value)
    return value
