"""Extract source-grounded riders from ordinary WINTICKET racecard HTML.

Works with the public SSR window.__PRELOADED_STATE__ already observed on
2026-11-09 Aomori 3R. No hidden API, additional GET, source-value guessing,
new model, or publication of names/scores. Missing line order, weather or
other facts remain UNAVAILABLE and must not be promoted into formal PR71.

Reads a supplied *already fetched* HTML document only. A race identity,
actual racers, source timestamps and source-value fields are checked before
any owner-only archive is eligible.
"""
from __future__ import annotations

from datetime import datetime,timezone,timedelta
from hashlib import sha256
import json
import math
import re
from urllib.parse import urlsplit

from .keirin_winticket_embedded_odds import (
    read_preloaded_json,checked_race_and_url,EmbeddedOddsError
)
from .keirin_preflight import expected_keys
from .keirin_result_delivery import canonical,utc

SCHEMA="RACE_AI_KEIRIN_WINTICKET_RACECARD_SOURCE_PARTIAL_V1"


class EmbeddedRacecardError(ValueError):
    pass


def require(condition,code):
    if not condition:
        raise EmbeddedRacecardError(code)


def _distinct_documents(candidates,*,reason):
    # The same SSR data can be cached by multiple query keys.
    # Conflicting versions of the same race/source are unsafe.
    found={}
    for data in candidates:
        h=sha256(canonical(data)).hexdigest()
        found[h]=data
    require(len(found)==1,reason)
    return next(iter(found.values()))


def _number(v,*,lo=0,hi=None):
    if type(v) not in (int,float) or not math.isfinite(v):
        return None
    if v<lo or (hi is not None and v>hi):
        return None
    return v


def _source_wind_mps(raw):
    """Use only an explicitly labelled m/s reading, never bare digits.

    Provider display may omit wind before the event, or return a different
    unit. Such values remain unavailable rather than guessed or converted.
    This is source observation only, not rights or forecast authorization.
    """
    if type(raw) is not str:
        return None
    m=re.fullmatch(r"\\s*(?:0|[1-9][0-9]?)(?:\\.[0-9]{1,3})?\\s*m/s\\s*",raw)
    if m is None:
        return None
    try:
        v=float(raw.strip().removesuffix("m/s").strip())
    except ValueError:
        return None
    return v if math.isfinite(v) and 0<=v<=40 else None


def _clock(v):
    try:
        if type(v) is int and 1_500_000_000<v<2_400_000_000:
            return datetime.fromtimestamp(v,timezone.utc)
        if type(v) is str:
            return utc(v)
    except (TypeError,ValueError,OverflowError):
        return None
    return None


def racecard_from_public_html(html,*,url,race_id,captured_at,
                              expected_cutoff_at=None):
    """Owner-private partial evidence, never automatically a complete 347 gate.

    The output includes raw publicly shown source values but is NOT suitable
    for public Git, stdout or an Action artifact. Only counts/SHA/statuses
    should enter public logs. Incoming data is held only in memory.
    """
    require(type(url) is str and "/racecard/" in url,
            "WINTICKET_RACECARD_URL_REQUIRED")
    odds_url=url.replace("/racecard/","/odds/",1)
    try:
        expected_id=checked_race_and_url(url=odds_url,race_id=race_id)
    except EmbeddedOddsError:
        raise EmbeddedRacecardError("UNTRUSTED_WINTICKET_RACECARD_ORIGIN") from None
    require(type(html) is bytes,"HTML_BYTES_REQUIRED")
    now=utc(captured_at)
    state=read_preloaded_json(html)
    queries=state.get("tanStackQuery")
    require(type(queries) is dict and
            type(queries.get("queries")) is list and
            len(queries["queries"])<=250,
            "RACECARD_QUERY_STRUCTURE_INVALID")
    entries_candidates=[]
    player_candidates=[]
    record_candidates=[]
    race_candidates=[]
    for query in queries["queries"]:
        if type(query) is not dict or type(query.get("state")) is not dict:
            continue
        data=query["state"].get("data")
        if type(data) is not dict:
            continue
        entr=data.get("entries")
        if type(entr) is list and len(entr) in (7,9):
            if all(type(row) is dict and
                   row.get("raceId")==expected_id and
                   type(row.get("number")) is int and
                   row.get("playerId") is not None for row in entr):
                entries_candidates.append(entr)
        for k,candidates in (("players",player_candidates),
                             ("records",record_candidates)):
            seq=data.get(k)
            if type(seq) is list and len(seq) in (7,9):
                candidates.append(seq)
        races=data.get("races")
        if type(races) is list:
            for item in races:
                if type(item) is dict and item.get("id")==expected_id:
                    race_candidates.append(item)
        if data.get("raceId")==expected_id and type(data.get("race")) is dict:
            race_candidates.append(data["race"])
    require(bool(entries_candidates),"EXACT_RACE_ENTRIES_MISSING")
    entries=_distinct_documents(entries_candidates,reason="CONFLICTING_RACE_ENTRIES")
    entrants=len(entries)
    require(entrants in (7,9),"UNSUPPORTED_ENTRANT_COUNT")
    by_car={}
    for e in entries:
        car=e["number"]
        require(1<=car<=entrants and car not in by_car and
                e.get("absent") is False and
                type(e["playerId"]) in (str,int),
                "ENTRANT_WITHDRAWAL_ID_OR_NUMBER_UNVERIFIED")
        by_car[car]=e
    require(set(by_car)==set(range(1,entrants+1)),
            "MISSING_OR_DUPLICATED_CAR_NUMBERS")
    ids={str(e["playerId"]) for e in entries}
    require(len(ids)==entrants,"DUPLICATED_ATHLETE_ID")

    def match_collections(all_candidates,id_name):
        eligible=[]
        for rows in all_candidates:
            if not all(type(v) is dict and
                       v.get(id_name) is not None for v in rows):
                continue
            indexed={str(v[id_name]):v for v in rows}
            if len(indexed)==entrants and set(indexed)==ids:
                eligible.append(indexed)
        require(bool(eligible),"RIDER_SOURCE_COLLECTION_NOT_FOUND")
        return _distinct_documents(
            eligible,reason="CONFLICTING_RIDER_SOURCE_COLLECTIONS")

    players=match_collections(player_candidates,"id")
    records=match_collections(record_candidates,"playerId")
    require(bool(race_candidates),"RACE_SCHEDULE_ID_NOT_FOUND")
    racemeta=_distinct_documents(race_candidates,reason="CONFLICTING_RACE_SCHEDULE")

    require(racemeta.get("id",expected_id)==expected_id and
            racemeta.get("number")==int(race_id[-2:]),
            "RACE_SCHEDULE_IDENTITY_MISMATCH")
    published_cutoff=_clock(racemeta.get("closeAt"))
    require(published_cutoff is not None,
            "PUBLISHED_RACE_CUTOFF_NOT_VERIFIABLE")
    require(now<published_cutoff,
            "PUBLIC_RACECARD_WAS_CAPTURED_AFTER_CUTOFF")
    if expected_cutoff_at is not None:
        require(published_cutoff==utc(expected_cutoff_at),
                "PUBLISHED_AND_EXPECTED_CUTOFF_DIFFER")
    scheduled_start=_clock(racemeta.get("startAt"))
    if scheduled_start is not None:
        require(published_cutoff<scheduled_start,
                "RACE_START_BEFORE_SALES_CUTOFF")

    verified={}
    starters=[]
    for n in range(1,entrants+1):
        entry=by_car[n]
        person=players[str(entry["playerId"])]
        recent=records[str(entry["playerId"])]
        name=person.get("name")
        require(type(name) is str and 1<=len(name)<=100,
                "RIDER_NAME_NOT_VERIFIED")
        grade=entry.get("playerCurrentTermClass")
        if type(grade) is not str:
            grade=person.get("class")
        grade=grade if type(grade) is str and grade else None
        row={
            "car_number":n,"source_player_id":str(entry["playerId"]),
            "name":name,"grade":grade,
            "race_point":_number(recent.get("racePoint")),
            "style_displayed":recent.get("style") if
                   type(recent.get("style")) is str else None,
            "standing_count":_number(recent.get("standing")),
            "home_count":_number(recent.get("home")),
            "back_count":_number(recent.get("back")),
            "gear_ratio":_number(recent.get("gearRatio")),
            "first_rate":_number(recent.get("firstRate"),hi=100),
            "second_rate":_number(recent.get("secondRate"),hi=100),
            "third_rate":_number(recent.get("thirdRate"),hi=100),
            "comment":recent.get("comment") if
                    type(recent.get("comment")) is str else None,
        }
        starters.append(row)
        # Age and training term are publicly observable when BOTH rider
        # identity-matched fields are actually present. This is an optional
        # audit fact, not the numeric required input for any PR71 model.
        age=person.get("age")
        term=person.get("term")
        if (type(age) is int and 16<=age<=110 and
                type(term) is int and 1<=term<=250):
            verified[f"rider/{n}/age_term_experience"]={
                "age_years":age,"training_term_number":term}
        if grade:
            verified[f"rider/{n}/identity_number_and_grade"]={
                "number":n,"identity":name,"grade":grade}
        if row["race_point"] is not None:
            verified[f"rider/{n}/race_score"]=row["race_point"]
        if type(recent.get("standing")) is int and recent["standing"]>=0:
            verified[f"rider/{n}/start_S_count"]=recent["standing"]
        # WINTICKET publishes H/Home as the final-home lead count.
        # Only admit the actual observed integer; a blank or malformed
        # home count stays unavailable, never zero-filled.
        if type(recent.get("home")) is int and recent["home"]>=0:
            verified[f"rider/{n}/home_H_count"]=recent["home"]
        if type(recent.get("back")) is int and recent["back"]>=0:
            verified[f"rider/{n}/back_B_count"]=recent["back"]
        if row["comment"]:
            verified[f"rider/{n}/athlete_comments_and_intent"]=row["comment"]
        # WINTICKET publicly labels the three source fields as cumulative
        # 1st-place, top-2 and top-3 finish percentages. Source definition:
        # https://www.winticket.jp/support/beginner (着順・勝率 section).
        # Derive EXACT second/third-place shares by adjacent differences.
        # Never SUM cumulative rates or invent a missing denominator.
        # Disordered, missing or invalid rates must remain unavailable.
        # Provider usage rights and source timing remain separate gates.
        rates=(row["first_rate"],row["second_rate"],row["third_rate"])
        if (all(type(v) in (int,float) and math.isfinite(v)
                and 0 <= v <= 100 for v in rates)
                and rates[0] <= rates[1] <= rates[2]):
            rate_values={
                "win_rate":rates[0]/100,
                "second_place_rate":(rates[1]-rates[0])/100,
                "third_place_rate":(rates[2]-rates[1])/100,
                "top_three_rate":rates[2]/100,
            }
            for key,value in rate_values.items():
                verified[f"rider/{n}/{key}"]=value
    verified["race/race_id_date_venue_no"]={
        "race_id":race_id,"event_date_jst":
            datetime.strptime(race_id[:8],"%Y%m%d").date().isoformat(),
        "venue":urlsplit(url).path.split("/")[2]}
    verified["race/all_entrants_and_vehicle_numbers"]=[
        {"number":x["car_number"],"identity":x["name"]}
        for x in starters]
    # A bookie's published closeAt is not a primary independent
    # certification of the organizer's official cutoff.
    if expected_cutoff_at is not None:
        verified["race/official_sales_cutoff"]=published_cutoff.isoformat()
    # Source-published event start is an observable pre-event schedule, not
    # a signed organizer timestamp nor evidence of the earlier source release.
    if scheduled_start is not None:
        verified["race/start_time"]=scheduled_start.isoformat()
    distance=_number(racemeta.get("distance"),lo=1)
    if distance is not None:
        verified["race/race_distance"]=distance
    # The published race detail can expose a wind-speed string. Require
    # explicit m/s units. A numeric-only/unknown/postrace wind value does not
    # establish a pre-race environmental reading. Timestamps and rights still
    # require the independent source admission process.
    wind=_source_wind_mps(racemeta.get("windSpeed"))
    if wind is not None:
        verified["race/wind_speed"]=wind

    keys=set(expected_keys(list(range(1,entrants+1))))
    verified={k:v for k,v in verified.items() if k in keys}
    # No auto-generated line topology, illness, unavailable weather,
    # late scratches or >300 other absent factors.
    missing=sorted(keys-set(verified))
    return {
        "schema":SCHEMA,
        "source_url":url,"race_id":race_id,
        "html_sha256":sha256(html).hexdigest(),
        "source_capture_at_utc":now.isoformat(),
        "source_published_cutoff_at_utc":published_cutoff.isoformat(),
        "source_scheduled_start_at_utc":
            scheduled_start.isoformat() if scheduled_start else None,
        "source_proof_kind":"PUBLIC_WINTICKET_RACECARD_SSR_ONLY",
        "riders":starters,
        "direct_verified_fields":verified,
        "verified_registry_keys":sorted(verified),
        "unavailable_registry_keys":missing,
        "registry_checked_count":len(keys),
        "registry_verified_count":len(verified),
        "registry_unavailable_count":len(missing),
        "full_347_or_437_verified":len(missing)==0,
        "rate_transform":"WINTICKET_CUMULATIVE_TOP1_TOP2_TOP3_TO_EXCLUSIVE_V2",
        "rate_denominator_and_reporting_period_independently_verified":False,
        "source_field_rights_independently_verified":False,
        "official_organizer_cutoff_certified":False,
        "independent_pre_cutoff_receipt_verified":False,
        "forecasts_created":False,
        "plaintext_public_git_written":False
    }




def safe_public_racecard_key_inventory(packet, html):
    """Report ONLY SSR field names already used for this exact race.

    Source values, rider IDs, names, scores, odds and raw HTML never leave
    owner memory. Collection keys indicate *potential* data availability,
    not fact completeness, publication time, use rights or model scores.
    """
    require(type(packet) is dict and packet.get("schema")==SCHEMA
            and type(html) is bytes and
            sha256(html).hexdigest()==packet.get("html_sha256"),
            "SOURCE_KEY_INVENTORY_ORIGINAL_BYTES_REQUIRED")
    state=read_preloaded_json(html)
    cache=state.get("tanStackQuery",{})
    q=cache.get("queries") if type(cache) is dict else None
    require(type(q) is list and len(q)<=250,
            "SOURCE_KEY_INVENTORY_QUERIES_REQUIRED")
    # Exact source athlete IDs from the already vetted private racecard;
    # the identifier values are never returned or printed.
    accepted={r.get("source_player_id") for r in packet["riders"]}
    entrant_count=len(packet["riders"])
    require(len(accepted)==entrant_count,"RIDER_ID_SET_INCONSISTENT")
    fields={k:set() for k in ("entries","players","records","races")}
    types={k:{} for k in fields}
    nested_shapes={}
    # Names are public schema identifiers, never player IDs or observed scores.
    known_nested=("currentCupResults","latestCupResults","latestVenueResults",
                  "trackDistance400","frontRunner","deepCloser","stalker",
                  "exCompete","exSnatch","exSpurt","exThrust","lineCompete",
                  "raceTypeQualifyingRound","gradeRaceSummaries")
    def safe_key(k):
        return type(k) is str and bool(
            re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}",k))
    def shape(v):
        return ("null" if v is None else "bool" if type(v) is bool else
                "integer" if type(v) is int else
                "number" if type(v) is float else
                "string" if type(v) is str else
                "object" if type(v) is dict else
                "array" if type(v) is list else "unrecognized")
    def observe(collection,row):
        for k,v in row.items():
            if not safe_key(k):continue
            fields[collection].add(k)
            types[collection].setdefault(k,set()).add(shape(v))
            if collection=="records" and k in known_nested:
                if type(v) is dict:
                    children=[key for key in v if safe_key(key)]
                elif type(v) is list:
                    children=[key for obj in v[:4] if type(obj) is dict
                              for key in obj if safe_key(key)]
                else:
                    children=[]
                nested_shapes.setdefault(k,set()).update(children)
    source_counts={k:0 for k in fields}
    for entry in q:
        if type(entry) is not dict or type(entry.get("state")) is not dict:
            continue
        data=entry["state"].get("data")
        if type(data) is not dict:continue
        for coll in ("entries","players","records"):
            rows=data.get(coll)
            if type(rows) is not list or len(rows)!=entrant_count or not all(
                type(x) is dict for x in rows
            ):
                continue
            key={"entries":"playerId","players":"id",
                 "records":"playerId"}[coll]
            ids={str(r.get(key)) for r in rows}
            if ids!=accepted:
                continue
            if coll=="entries" and not all(
                r.get("number") in range(1,entrant_count+1)
                for r in rows
            ):
                continue
            source_counts[coll]+=1
            for row in rows:
                observe(coll,row)
        rr=data.get("races")
        if type(rr) is list:
            for row in rr:
                if (type(row) is dict and
                        row.get("id") == (
                            packet["race_id"][-2:] +
                            packet["race_id"][8:10] +
                            packet["race_id"][:8])):
                    source_counts["races"]+=1
                    observe("races",row)
    require(all(source_counts[k]>=1 for k in fields),
            "SOURCE_COLLECTIONS_NOT_JOINED_TO_EXACT_RACE")
    return {
        "schema":"RACE_AI_KEIRIN_WINTICKET_SOURCE_FIELD_NAMES_ONLY_V1",
        "race_id":packet["race_id"],
        "source_original_html_sha256":packet["html_sha256"],
        "collection_field_names":{k:sorted(v)[:120] for k,v in fields.items()},
        "collection_field_types_only":{
            k:{name:sorted(kinds) for name,kinds in sorted(types[k].items())}
            for k in sorted(types)},
        "selected_nested_field_names_only":{
            key:sorted(value)[:70] for key,value in sorted(
                nested_shapes.items())},
        "field_names_not_observation_values":True,
        "count_as_verified_347_factors":False,
        "new_source_rights_granted":False,
        "public_rider_values_or_names_logged":False,
    }

def safe_public_racecard_counts(packet):
    """Only public-safe structural counts + SHA for CI or monitoring logs."""
    require(type(packet) is dict and packet.get("schema")==SCHEMA,
            "INVALID_PRIVATE_RACECARD_PACKET")
    return {
        "schema":"RACE_AI_KEIRIN_WINTICKET_RACECARD_COUNTS_V1",
        "race_id":packet["race_id"],
        "raw_html_sha256":packet["html_sha256"],
        "captured_at_utc":packet["source_capture_at_utc"],
        "rider_identity_count":len(packet["riders"]),
        "registry_checked_count":packet["registry_checked_count"],
        "registry_verified_count":packet["registry_verified_count"],
        "registry_unavailable_count":packet["registry_unavailable_count"],
        "full_model_input_verified":packet["full_347_or_437_verified"],
        "formal_prediction_saved":False,
        "publication": "STRUCTURAL_COUNTS_ONLY_NO_RIDER_CONTENT",
    }
