"""Full pre-cutoff odds from ONE independently authorized KEIRIN provider export.

The existing licensed source endpoint already performs a single authorized GET.
This module never makes another request or invents a provider grant.
Only explicit V2 exports whose real source, rights, provenance, full 210/504
prices and cutoff all pass are admitted. The original odds are immutable and
the time they enter the owner process is never backdated.
"""
from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
from itertools import permutations
import math
from pathlib import Path

from .keirin_non_rakuten_sources import is_rakuten_url
from .keirin_permissioned_owner import LicenseDeliveryError, _write_private_once
from .keirin_result_delivery import canonical, utc
from .keirin_variable_selection import ODDS_SCHEMA

SCHEMA = "RACE_AI_KEIRIN_LICENSED_ODDS_EXPORT_ROW_V1"
MARGIN_SECONDS=65
MAX_AGE_SECONDS=1800
MAX_ROWS=504


def require(ok,code):
    if not ok:
        raise LicenseDeliveryError(code)


def normalize_licensed_odds(value, race, *, checked_at, admitted):
    require(type(value) is dict and set(value)=={
        "schema","race_id","official_cutoff_at","published_at",
        "source_url","rights_ref","prices"
    } and value["schema"]==SCHEMA, "ODDS_EXPORT_FIELDS_INVALID")
    require(type(race) is dict and type(value["race_id"]) is str
            and value["race_id"]==race.get("race_id")
            and value["official_cutoff_at"]==race.get("official_cutoff_at"),
            "ODDS_RACE_OR_CUTOFF_MISMATCH")
    require(type(value["source_url"]) is str and
            value["source_url"].startswith("https://") and
            not is_rakuten_url(value["source_url"]) and
            type(value["rights_ref"]) is str and
            bool(value["rights_ref"]) and callable(admitted),
            "ODDS_PROVIDER_PROVENANCE_REQUIRED")
    require(all(admitted(value["source_url"],value["rights_ref"],purpose)
                is True for purpose in
                ("automated_fetch","analysis","pre_race","private_retention")),
            "ODDS_PROVIDER_RIGHTS_NOT_ADMITTED")
    now=utc(checked_at)
    cutoff=utc(value["official_cutoff_at"])
    published=utc(value["published_at"])
    require(published<=now and
            timedelta(0)<=now-published<=timedelta(seconds=MAX_AGE_SECONDS),
            "ODDS_NOT_FRESH_OR_NOT_YET_PUBLISHED")
    require(now+timedelta(seconds=MARGIN_SECONDS)<cutoff,
            "ODDS_OUTSIDE_PRE_CUTOFF_MARGIN")
    competitors=race.get("starters")
    require(type(competitors) is list and len(competitors) in (7,9),
            "ODDS_ROSTER_REQUIRED")
    numbers=[]
    for r in competitors:
        require(type(r) is dict and
                type(r.get("number")) is int and
                1<=r["number"]<=9, "ODDS_RIDER_IDENTITY_INVALID")
        numbers.append(r["number"])
    require(len(set(numbers))==len(numbers), "ODDS_DUPLICATE_ENTRANT")
    universe=set(permutations(numbers,3))
    rows=value["prices"]
    require(type(rows) is list and
            len(rows)==len(universe) and len(rows)<=MAX_ROWS,
            "ODDS_FULL_210_OR_504_REQUIRED")
    found={}
    for row in rows:
        require(type(row) is dict and set(row)=={
            "triple","decimal_odds"} and type(row["triple"]) is list and
            len(row["triple"])==3 and
            all(type(n) is int for n in row["triple"]),
            "ODDS_PROVIDER_TRIPLE_INVALID")
        ticket=tuple(row["triple"])
        require(ticket in universe and ticket not in found,
                "ODDS_DUPLICATED_OR_UNKNOWN_TRIPLE")
        price=row["decimal_odds"]
        require(type(price) in (int,float) and math.isfinite(price) and
                1.0<price<=1_000_000 and float(price)!=9999.9,
                "ODDS_PRICE_MISSING_OR_AMBIGUOUS")
        found[ticket]=float(price)
    require(set(found)==universe, "ODDS_UNIVERSE_NOT_COVERED")
    return {
        "schema":ODDS_SCHEMA,
        "race_id":value["race_id"],
        "captured_at":now.isoformat(),
        "source_ref":value["source_url"],
        "source_rights_ref":value["rights_ref"],
        "prices":[{"triple":list(t),"decimal_odds":found[t]}
                  for t in sorted(universe)],
    }


def stage_licensed_odds_export(inbox, odds_rows, deliveries, *,
                               checked_at, grant_check):
    """Already fetched and admitted provider V2 body. Zero new network calls.

    Fail a malformed batch before writing any market files. Only the FIRST
    admitted odds set is kept for a given race; never rewrite a frozen
    original or change its timestamp on rerun.
    """
    root=Path(inbox).expanduser()
    require(root.is_absolute() and root.is_dir() and not root.is_symlink()
            and callable(grant_check),
            "PRIVATE_ODDS_ROOT_REQUIRED")
    require(type(odds_rows) is list and 0<=len(odds_rows)<=100
            and type(deliveries) is list,
            "LICENSED_ODDS_BATCH_INVALID")
    races={}
    for packet in deliveries:
        require(type(packet) is dict and type(packet.get("race")) is dict,
                "DELIVERY_RACE_PACKET_INVALID")
        race=packet["race"]
        rid=race.get("race_id")
        require(type(rid) is str and rid not in races,
                "DUPLICATE_DELIVERY_RACE")
        races[rid]=race
    staged={}
    for row in odds_rows:
        require(type(row) is dict and row.get("race_id") in races,
                "ORPHAN_ODDS_OUTSIDE_AUTHORIZED_DELIVERY")
        rid=row["race_id"]
        require(rid not in staged,"DUPLICATE_ODDS_SNAPSHOT_RACE")
        staged[rid]=normalize_licensed_odds(
            row,races[rid],checked_at=checked_at,admitted=grant_check)
    folder=root/"odds"
    require(not folder.is_symlink(), "ODDS_OUTPUT_SYMLINK")
    if not folder.exists():
        folder.mkdir(mode=0o700)
    require(folder.is_dir(), "ODDS_OUTPUT_NOT_A_DIRECTORY")
    new=old=0
    for rid,row in sorted(staged.items()):
        name=sha256(rid.encode("utf-8")).hexdigest()+".json"
        dest=folder/name
        require(not dest.is_symlink(),"ODDS_OUTPUT_SYMLINK")
        if dest.exists():
            require(dest.is_file() and dest.stat().st_size<=2_000_000,
                    "ODDS_ORIGINAL_UNSAFE")
            from json import loads
            previous=loads(dest.read_text(encoding="utf-8"))
            require(type(previous) is dict and
                    previous.get("schema")==ODDS_SCHEMA and
                    previous.get("race_id")==rid,
                    "EXISTING_ODDS_PROVENANCE_INVALID")
            # Preserve original capture time. Exact repeat from the same
            # provider source is idempotent even across agent restarts.
            require(all(previous.get(k)==row[k] for k in (
                "source_ref","source_rights_ref","prices")),
                "EXISTING_ODDS_IMMUTABLE_CONFLICT")
            require(utc(previous["captured_at"])<=utc(checked_at),
                    "ODDS_EXISTING_RECORD_FROM_FUTURE")
            old+=1
        else:
            require(_write_private_once(dest,row),
                    "ODDS_CREATE_ONCE_FAILED")
            require(dest.read_bytes()==canonical(row),
                    "ODDS_FIRST_WRITE_READBACK_FAILED")
            new+=1
    return {
        "schema":"RACE_AI_KEIRIN_LICENSED_FULL_ODDS_STAGE_V1",
        "full_odds_created":new,
        "full_odds_already_staged":old,
        "full_odds_validated":len(staged),
        "network_requests":0,
        "official_provider_legal_rights_certified_by_code":False,
        "pre_cutoff_source_external_time_witness_verified":False,
        "automatic_betting":False,
    }
