"""Owner-saved, non-Rakuten UTF-8 racecard CSV -> existing private JSON bridge.

This module NEVER fetches websites. Raw CSV rows MUST have been legitimately
supplied/captured for strictly personal offline research. It only records
actual fields, never promotes speculation into a verified observation.
Output is not an official pre-cutoff timestamp or a live provider licence.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import csv
import io
import json
from pathlib import Path

from .keirin_non_rakuten_sources import source_id, is_rakuten_url
from .keirin_owner_manual import PERSONAL_MARKER
from .keirin_permissioned_owner import _write_private_once
from .keirin_result_delivery import canonical, utc

SCHEMA = "RACE_AI_KEIRIN_OWNER_NON_RAKUTEN_CSV_META_V1"
MAX_CSV_BYTES = 150_000
MAX_ROWS = 9
MAX_FILE_PER_TICK = 50
FIELDS = (
    "car_no","rider_name","grade","style","race_score","starts",
    "wins","seconds","thirds","unplaced","s_count","h_count",
    "b_count","escape_count","makuri_count","sashi_count",
    "mark_count","gear",
)
STYLE = {"逃":"front","両":"allround","追":"stalker",
         "front":"front","allround":"allround","stalker":"stalker",
         "closer":"closer","unknown":"unknown"}


class OwnerRacecardError(ValueError):
    pass


def _need(ok, reason):
    if not ok:
        raise OwnerRacecardError(reason)


def _int(raw, label, *, minimum=0):
    _need(type(raw) is str and raw.isascii() and raw.isdigit(),
          label+"_INTEGER_REQUIRED")
    v = int(raw)
    _need(v >= minimum, label+"_NEGATIVE_OR_ZERO")
    return v


def _decimal(raw, label):
    _need(type(raw) is str and len(raw) <= 120, label+"_INVALID")
    try:
        x = Decimal(raw)
    except InvalidOperation as exc:
        raise OwnerRacecardError(label+"_NOT_NUMERIC") from exc
    _need(x.is_finite() and x >= 0, label+"_NONFINITE_OR_NEGATIVE")
    _need(x <= Decimal("1e100"), label+"_OVERFLOW_FOR_FINITE_MODEL_INPUT")
    return float(x)


def _meta(meta):
    _need(type(meta) is dict and set(meta) == {
        "schema","source_url","source_observed_at",
        "race","source_sha256","observed_race_facts"
    } and meta["schema"] == SCHEMA, "META_SCHEMA_INVALID")
    _need(type(meta["source_url"]) is str and
          not is_rakuten_url(meta["source_url"]) and
          source_id(meta["source_url"]) is not None,
          "NON_RAKUTEN_VERIFIED_SOURCE_URL_REQUIRED")
    _need(type(meta["source_sha256"]) is str and
          len(meta["source_sha256"]) == 64 and
          all(c in "0123456789abcdef" for c in meta["source_sha256"]),
          "OWNER_RAW_SOURCE_DIGEST_REQUIRED")
    now = utc(meta["source_observed_at"])
    race = meta["race"]
    _need(type(race) is dict and set(race) == {
        "race_id","venue","event_date_jst","race_kind","race_revision",
        "distance_m","as_of","official_cutoff_at","starters",
    }, "RACE_META_INVALID")
    _need(utc(race["as_of"]) == now and
          now < utc(race["official_cutoff_at"]),
          "OWNER_SOURCE_NOT_OBSERVED_PRE_CUTOFF")
    _need(type(race["race_revision"]) is int and race["race_revision"] >= 1,
          "REVISION_INVALID")
    _need(type(race["starters"]) is list and len(race["starters"]) in (7, 9),
          "SEVEN_OR_NINE_STARTERS_REQUIRED")
    _need(type(meta["observed_race_facts"]) is dict and
          set(meta["observed_race_facts"]) <= {
            "race_id_date_venue_no","event_grade_and_class","race_stage",
            "advancement_and_points_rules","race_distance","start_time",
            "official_sales_cutoff", "late_scratches_substitutions_revisions",
            "line_order_all_riders","line_roles_and_solo_riders",
            "source_access_permission_and_asof"
          }, "RACE_FACTS_NOT_APPROVED")
    return race, now


def _make_obs(meta,key,value,sample_n):
    return {
        "key":key,"value":value,
        "source_url":meta["source_url"],
        "rights_ref":PERSONAL_MARKER,
        # The first owner's observation is a conservative publication
        # upper bound; NOT an independently proven upstream published_at.
        "published_at":meta["source_observed_at"],
        "captured_at":meta["source_observed_at"],
        "sample_n":sample_n,
    }


def import_owner_saved_csv(raw:bytes, meta:dict):
    """Convert an owner-saved CSV into partial actual observations.

    No missing field is filled. Arithmetic inconsistency keeps scores but
    invalidates derived rate observations. Promotion to a model happens later
    only if every critical source is independently present and as-of-safe.
    """
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_CSV_BYTES,
          "CSV_NOT_BOUNDED")
    race, _ = _meta(meta)
    _need(sha256(raw).hexdigest() == meta["source_sha256"],
          "SOURCE_CSV_SHA_MISMATCH")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise OwnerRacecardError("UTF8_CSV_REQUIRED") from exc
    rd = csv.DictReader(io.StringIO(text, newline=""))
    _need(tuple(rd.fieldnames or ()) == FIELDS, "CSV_FIELDS_NOT_EXACT")
    rows = list(rd)
    _need(len(rows) == len(race["starters"]) and len(rows) <= MAX_ROWS,
          "ROSTER_ROW_COUNT_MISMATCH")
    starters = {}
    for p in race["starters"]:
        _need(type(p) is dict and set(p) == {
            "number","identity","style","group_id"
        }, "STARTER_SCHEMA_INVALID")
        _need(type(p["number"]) is int and
              p["number"] not in starters and
              type(p["identity"]) is str and bool(p["identity"]) and
              p["style"] in STYLE.values() and
              (p["group_id"] is None or
               type(p["group_id"]) is str),
              "STARTER_IDENTITY_INVALID")
        starters[p["number"]] = p
    _need(sorted(starters) == list(range(1,len(rows)+1)),
          "NONCONTIGUOUS_ROSTER_INVALID")
    by_no = {}
    counters_disagree = []
    observations = []
    def add(key,val,sample=1):
        observations.append(_make_obs(meta,key,val,sample))
    facts = meta["observed_race_facts"]
    for key,val in facts.items():
        add("race/"+key,val)
    # Ensure that the source actually contains the selected class and roster:
    # meta alone does not independently authenticate race condition claims.
    for row in rows:
        _need(type(row) is dict and set(row) == set(FIELDS) and
              all(type(v) is str for v in row.values()),
              "CSV_ROW_SHAPE_INVALID")
        n = _int(row["car_no"],"CAR",minimum=1)
        _need(n in starters and n not in by_no, "RIDER_NUMBER_MISMATCH")
        p = starters[n]
        _need(row["rider_name"].strip() == p["identity"] and
              row["style"] in STYLE and
              STYLE[row["style"]] == p["style"] and
              type(row["grade"]) is str and row["grade"].strip(),
              "RIDER_CSV_IDENTITY_OR_STYLE_MISMATCH")
        by_no[n] = row
        add("rider/%d/identity_number_and_grade"%n,
            {"number":n,"identity":p["identity"],"grade":row["grade"].strip()})
        score = _decimal(row["race_score"],"RACE_SCORE")
        add("rider/%d/race_score"%n,score)
        starts = _int(row["starts"],"STARTS",minimum=1)
        counts = {c:_int(row[c],c.upper()) for c in FIELDS[6:17]}
        for field,key in (
            ("s_count","start_S_count"),
            ("h_count","home_H_count"),
            ("b_count","back_B_count"),
        ):
            _need(counts[field] <= starts,"SHB_COUNT_EXCEEDS_RACES")
            add("rider/%d/%s"%(n,key),counts[field],starts)
        for field,key in (
            ("escape_count","style_escape"),
            ("makuri_count","style_makuri"),
            ("sashi_count","style_sashi"),
            ("mark_count","style_mark"),
        ):
            _need(counts[field] <= starts,"STYLE_COUNT_EXCEEDS_RACES")
            add("rider/%d/%s"%(n,key),counts[field]/starts,starts)
        if (sum(counts[x] for x in ("wins","seconds","thirds","unplaced"))
                != starts):
            counters_disagree.append(n)
        else:
            add("rider/%d/win_rate"%n,counts["wins"]/starts,starts)
            add("rider/%d/second_place_rate"%n,counts["seconds"]/starts,starts)
            add("rider/%d/third_place_rate"%n,counts["thirds"]/starts,starts)
            add("rider/%d/top_three_rate"%n,
                (counts["wins"]+counts["seconds"]+counts["thirds"])/starts,
                starts)
        if row["gear"].strip():
            _decimal(row["gear"],"GEAR")  # not "change history"; audit only
    _need(len(by_no) == len(starters),"NOT_ALL_RIDERS_COVERED")
    # These two fields are obtained from the CSV, NOT a separate source GET.
    add("race/all_entrants_and_vehicle_numbers",
        [{"number":n,"identity":starters[n]["identity"]}
         for n in sorted(starters)])
    output_race = {k:v for k,v in race.items()}
    output_race["permission_ref"] = PERSONAL_MARKER
    delivery = {
        "schema":"RACE_AI_KEIRIN_PERMISSIONED_DELIVERY_V1",
        "race":output_race,
        "observations":observations,
    }
    return {
        "schema":"RACE_AI_KEIRIN_OWNER_SAVED_CSV_IMPORT_V1",
        "delivery":delivery,
        "observed_fields":len(observations),
        "roster_count":len(starters),
        "race_count_conflict_riders":counters_disagree,
        "raw_source_sha256":sha256(raw).hexdigest(),
        "source_type":"OWNER_MANUALLY_SAVED_CSV_NO_HTTP",
        "independently_attested_published_at":False,
        "official_sales_cutoff_independently_verified":False,
        "provider_automated_access_authorized":False,
        "forecast_generated":False,
    }


def stage_owner_saved_csv(inbox, *, now):
    """Watch already supplied csv/<digest>.csv + matching .meta.json.

    Creation is idempotent. Never modifies old pre-race forecasts. The regular
    private processor checks cutoff and all missing keys afterwards.
    """
    root=Path(inbox).expanduser()
    _need(root.is_absolute() and root.is_dir() and
          not root.is_symlink(),"PRIVATE_OWNER_INBOX_REQUIRED")
    folder=root/"csv"
    if not folder.exists():
        return {"staged_csv":0,"unchanged_csv":0,"blocked_csv":0,
                "provider_http_requests":0}
    _need(folder.is_dir() and not folder.is_symlink(),
          "OWNER_CSV_FOLDER_INVALID")
    files=sorted(folder.glob("*.csv"))
    _need(len(files)<=MAX_FILE_PER_TICK,"TOO_MANY_OWNER_CSV_FILES")
    (root/"raw").mkdir(mode=0o700,exist_ok=True)
    status={"staged_csv":0,"unchanged_csv":0,"blocked_csv":0,
            "provider_http_requests":0}
    for file in files:
        try:
            _need(not file.is_symlink(),"SYMLINKED_CSV_FORBIDDEN")
            info=file.with_suffix(".meta.json")
            _need(info.is_file() and not info.is_symlink() and
                  0<info.stat().st_size<=100_000,
                  "SOURCE_META_FILE_REQUIRED")
            meta=json.loads(info.read_text(encoding="utf-8"))
            assembled=import_owner_saved_csv(file.read_bytes(),meta)
            _need(utc(meta["source_observed_at"])<=utc(now)<
                  utc(meta["race"]["official_cutoff_at"]),
                  "SOURCE_NOT_PRESERVED_BEFORE_CUTOFF")
            k=sha256(canonical(assembled["delivery"])).hexdigest()
            created=_write_private_once(root/"raw"/(k+".json"),
                                         assembled["delivery"])
            status["staged_csv" if created else "unchanged_csv"]+=1
        except (ValueError,TypeError,KeyError,OSError,UnicodeError):
            status["blocked_csv"]+=1
    return status
