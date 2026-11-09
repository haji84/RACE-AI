"""Strict optional result revisions from the SAME authorized provider V3 JSON.

No new HTTP endpoint, new result scorer, signed official claim, model input,
payment, source-rights grant, public plaintext, or retroactive prediction.
Only already frozen PR71 four-model races may receive append-only results.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit
import json
import os
import re

from .keirin_permissioned_owner import (
    LicenseDeliveryError, OperatorLicenseGrants, _write_private_once
)
from .keirin_owner_sqlite import PrivateKeirinStore, OwnerStoreError
from .keirin_pr71_four_model_rank import FourModelRankLedger
from .keirin_result_delivery import canonical, utc
from .keirin_non_rakuten_sources import is_rakuten_url

ROW_SCHEMA="RACE_AI_KEIRIN_LICENSED_RESULT_REVISION_V1"
MAX_RESULTS=2000
HEX=re.compile(r"^[0-9a-f]{64}$")
RACE=re.compile(r"^(?:20[0-9]{10}|keirin:\d{4}-\d\d-\d\d:[a-z0-9_-]{2,40}:[1-9]\d?)$")
STATES=frozenset({"FINAL_NORMAL","PENDING","CANCELLED","NOT_OFFERED",
                  "SOURCE_UNAVAILABLE","CUTOFF_MISMATCH","UNSUPPORTED_SPECIAL"})
REFUNDS=frozenset({"NONE","PARTIAL","FULL","UNKNOWN"})
PURPOSES=("automated_fetch","result_collection","result_analysis",
          "private_retention")


def need(ok,code):
    if not ok:
        raise LicenseDeliveryError(code)


def _root(inbox):
    folder=Path(inbox).expanduser()
    need(folder.is_absolute() and folder.is_dir() and
         not folder.is_symlink(),"PRIVATE_RESULT_INBOX_REQUIRED")
    workspace=os.environ.get("GITHUB_WORKSPACE")
    if workspace:
        public=Path(workspace).resolve()
        private=folder.resolve()
        need(private!=public and public not in private.parents,
             "PUBLIC_GITHUB_WORKSPACE_RESULT_DATA_FORBIDDEN")
    return folder


def validate_result(row, grants, *, checked_at):
    """Validate one delivered record; its source is NOT officially signed."""
    need(isinstance(grants,OperatorLicenseGrants),
         "OWNER_AUTHORIZED_RESULT_GRANTS_REQUIRED")
    need(type(row) is dict and set(row)=={
        "schema","race_id","source_url","rights_ref",
        "source_published_at","observed_at","provider_revision_ref",
        "status","refund_status","winning_triples","payouts_100yen",
    } and row["schema"]==ROW_SCHEMA,
         "RESULT_PROVIDER_SCHEMA_INVALID")
    rid=row["race_id"]
    need(type(rid) is str and RACE.fullmatch(rid),
         "RESULT_RACE_ID_INVALID")
    url=row["source_url"]
    try:
        u=urlsplit(url)
        good=(type(url) is str and len(url)<=1024 and
              u.scheme=="https" and bool(u.hostname) and
              u.username is None and u.password is None and
              u.port is None and not u.fragment)
    except (TypeError,ValueError):
        good=False
    need(good and not is_rakuten_url(url),"RESULT_PROVIDER_ORIGIN_INVALID")
    rights=row["rights_ref"]
    need(type(rights) is str and bool(rights) and
         all(grants.allowed(url,rights,p) is True for p in PURPOSES),
         "RESULT_SOURCE_PURPOSES_NOT_AUTHORIZED")
    revision=row["provider_revision_ref"]
    need(type(revision) is str and 1<=len(revision)<=256,
         "RESULT_PROVIDER_REVISION_REQUIRED")
    try:
        at=utc(row["observed_at"])
        published=utc(row["source_published_at"])
        now=utc(checked_at)
    except (ValueError,TypeError,KeyError):
        raise LicenseDeliveryError("RESULT_SOURCE_CLOCK_UNVERIFIED") from None
    need(published<=at<=now, "RESULT_PUBLISHED_OBSERVED_CLOCK_INVALID")
    status=row["status"]
    refund=row["refund_status"]
    need(type(status) is str and status in STATES and
         type(refund) is str and refund in REFUNDS,
         "RESULT_STATUS_REFUND_INVALID")
    winners=row["winning_triples"]
    payments=row["payouts_100yen"]
    need(type(winners) is list and type(payments) is list and
         len(winners)<=20 and len(payments)<=20,
         "RESULT_PAYOUT_LIST_INVALID")
    def triple(x):
        need(type(x) is list and len(x)==3 and
             all(type(v) is int and 1<=v<=9 for v in x) and
             len(set(x))==3, "RESULT_TRIPLE_INVALID")
        return tuple(x)
    wins=[triple(x) for x in winners]
    paid=[]
    for row_payment in payments:
        need(type(row_payment) is dict and
             set(row_payment)=={"triple","yen"} and
             type(row_payment["yen"]) is int and
             0<row_payment["yen"]<=10**9,
             "RESULT_PAYOUT_INVALID")
        paid.append(triple(row_payment["triple"]))
    need(len(set(wins))==len(wins) and
         len(set(paid))==len(paid) and
         ((bool(wins) and set(wins)==set(paid) and refund!="FULL")
          if status=="FINAL_NORMAL" else (not wins and not paid)),
         "RESULT_SETTLEMENT_INCONSISTENT")
    return row


def stage_licensed_result_export(inbox,rows,*,checked_at,grants):
    """V3 rows are checked ALL-at-once before ANY file is written."""
    root=_root(inbox)
    need(type(rows) is list and len(rows)<=MAX_RESULTS,
         "RESULT_EXPORT_BATCH_BOUNDS_INVALID")
    validated=[]
    identities=set()
    for row in rows:
        checked=validate_result(row,grants,checked_at=checked_at)
        rid=checked["race_id"]
        need(rid not in identities,"DUPLICATE_PROVIDER_RESULT_RACE")
        identities.add(rid)
        validated.append(checked)
    folder=root/"licensed_result_rows"
    need(not folder.is_symlink(),"RESULT_FOLDER_SYMLINK_REFUSED")
    folder.mkdir(mode=0o700,exist_ok=True)
    made=already=0
    for row in validated:
        digest=sha256(canonical(row)).hexdigest()
        if _write_private_once(folder/(digest+".json"),row):
            made+=1
        else:
            already+=1
    return {"schema":"RACE_AI_KEIRIN_LICENSED_RESULT_STAGE_V1",
            "source_rows_admitted":len(validated),
            "private_results_created":made,
            "private_results_unchanged":already,
            "network_requests":0,
            "model_predictions_created":0,
            "provider_machine_rights_independently_certified":False,
            "official_result_independently_authenticated":False}


def apply_existing_frozen_results(inbox,store,grants,*,checked_at):
    """Reuse existing PrivateKeirinStore and FourModelRankLedger scorer only.

    Reject results not bound to an existing prospective suite. A same provider
    revision cannot silently change contents. Do not infer an official result
    signature from an owner-supplied grant manifest or provider URL.
    """
    root=_root(inbox)
    need(isinstance(store,PrivateKeirinStore) and
         isinstance(grants,OperatorLicenseGrants),
         "EXISTING_OWNER_STORE_AND_RESULT_GRANTS_REQUIRED")
    folder=root/"licensed_result_rows"
    if not folder.exists():
        return {"results_appended":0,"results_already_present":0,
                "results_held":0,"no_forecast_backfilled":True}
    need(folder.is_dir() and not folder.is_symlink(),
         "RESULT_FOLDER_UNSAFE")
    files=sorted(folder.glob("*.json"))
    need(len(files)<=MAX_RESULTS,"RESULT_IMPORT_BATCH_TOO_LARGE")
    ledger=FourModelRankLedger(store)
    appended=already=held=0
    # Distinct provider corrections must be replayed by actual observation
    # time, not arbitrary SHA filename order. Verify every candidate's SHA
    # and rights before mutating any record for that candidate.
    candidates=[]
    for path in files:
        try:
            need(path.is_file() and not path.is_symlink() and
                 0<path.stat().st_size<=20_000 and
                 HEX.fullmatch(path.stem),
                 "RESULT_ROW_FILE_INVALID")
            raw=path.read_bytes()
            need(sha256(raw).hexdigest()==path.stem,
                 "RESULT_ROW_FILE_SHA_MISMATCH")
            row=json.loads(raw.decode("utf-8"))
            validate_result(row,grants,checked_at=checked_at)
            candidates.append((utc(row["observed_at"]),path.stem,row))
        except (OSError,ValueError,KeyError,TypeError,OwnerStoreError,
                UnicodeError):
            held+=1
    for _,digest,row in sorted(candidates,key=lambda entry:(entry[0],entry[1])):
        try:
            rid=row["race_id"]
            frozen=ledger.read_suite(rid)
            need(frozen is not None,"NO_FROZEN_FOUR_MODEL_SOURCE")
            cutoff=utc(frozen["suite"]["sales_cutoff_at"])
            need(cutoff<=utc(row["source_published_at"])<=
                 utc(row["observed_at"]) and
                 utc(frozen["persisted_at"])<cutoff,
                 "RESULT_NOT_AFTER_FROZEN_CUTOFF")
            roster=set(frozen["source"]["starters"])
            for triple in row["winning_triples"]:
                need(set(triple)<=roster,"RESULT_WINNER_NOT_ON_FROZEN_CARD")
            # Use this candidate's checked bytes, never the last scanned path.
            event={
                "race_id":rid,"source_sha256":digest,
                "observed_at":row["observed_at"],
                "status":row["status"],
                "refund_status":row["refund_status"],
                "winning_triples":row["winning_triples"],
                "payouts_100yen":row["payouts_100yen"],
                "source_url":row["source_url"],
                "source_rights_ref":row["rights_ref"],
                "source_published_at":row["source_published_at"],
                "provider_revision_ref":row["provider_revision_ref"],
            }
            history=store.db.execute(
                "SELECT payload FROM result_revisions WHERE race_id=? "
                "ORDER BY revision",(rid,)).fetchall()
            # Every old provider revision remains immutable after a corrected
            # result arrives. A repeat of rev-1 is not a NEW rev-3.
            matched=False
            for record in history:
                prior=json.loads(record["payload"])
                if prior.get("provider_revision_ref")==row["provider_revision_ref"]:
                    need(prior==event,"SAME_PROVIDER_REVISION_CHANGED")
                    matched=True
                    break
            if matched:
                already+=1
                continue
            report=store.add_result_observation(
                event,independently_authenticated=False)
            if report["state"]=="ALREADY_PRESENT":
                already+=1
            else:
                appended+=1
        except (OSError,ValueError,KeyError,TypeError,OwnerStoreError,
                UnicodeError):
            held+=1
    return {"results_appended":appended,
            "results_already_present":already,
            "results_held":held,"no_forecast_backfilled":True,
            "official_authentication_independently_verified":False,
            "formal_hit_rate_admitted":False}
