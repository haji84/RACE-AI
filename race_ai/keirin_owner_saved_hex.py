"""Offline KEIRIN HEX-style Markdown table -> strict owner racecard CSV.

No provider GET, prediction imports, AI marks, public odds or redistribution.
The page may be subject to third-party terms: OWNER-LOCALLY-SAVED ONLY.
This parser deliberately rejects changing/ambiguous table schemas.
"""
from __future__ import annotations

from hashlib import sha256
import csv
import io
import re

from .keirin_non_rakuten_sources import source_id
from .keirin_owner_saved_csv import (
    FIELDS, OwnerRacecardError, import_owner_saved_csv
)

BOARD_HEADING = "## 出走表"
ROW_NUMBER = re.compile(r"^[1-9]$")
DEC = re.compile(r"^\d+(?:\.\d+)?$")
INTEGER = re.compile(r"^\d+$")
PCT = re.compile(r"^(100|\d{1,2})%$")
LINE = re.compile(r"並び予想は\s*([0-9\s\-／/]+)")
MARKS = re.compile(r"^[◎○▲☆△×✕注印]")

# After two recent-meeting text cells, the public table carries:
# starts, rates, placing counts, S/H/B, decision counts and gear. Do not
# misread indicator ranks (◎ etc) as model inputs.
INDEX = {
    "number":0,"label":1,"score":2,"style":3,
    "recent_1":4,"recent_2":5,
    "starts":6, "win_pct":7, "two_pct":8, "three_pct":9,
    "wins":10,"seconds":11,"thirds":12,"unplaced":13,
    "s_count":14,"h_count":15,"b_count":16,
    "escape_count":17,"makuri_count":18,"sashi_count":19,
    "mark_count":20,"gear":21,
}


def _need(ok, why):
    if not ok:
        raise OwnerRacecardError(why)


def _split_table(markdown):
    _need(type(markdown) is str and 0<len(markdown)<=500_000,
          "OWNER_SAVED_MARKDOWN_INVALID")
    start=markdown.find(BOARD_HEADING)
    _need(start>=0, "MISSING_RACECARD_SECTION")
    body=markdown[start+len(BOARD_HEADING):]
    following=re.search(r"(?m)^## ",body)
    if following:
        body=body[:following.start()]
    return [line.strip() for line in body.splitlines() if line.strip()]


def _lineup_from_text(markdown, starters):
    matches=list(LINE.finditer(markdown))
    _need(len(matches)<=1, "AMBIGUOUS_LINEUP_TEXT")
    if not matches:
        return None
    raw=matches[0].group(1).strip().strip("。")
    tokens=[a.strip() for a in re.split(r"[／/]",raw) if a.strip()]
    lines=[]
    solos=[]
    seen=[]
    for token in tokens:
        nums=[int(x) for x in re.findall(r"\d+",token)]
        _need(nums and all(1<=n<=9 for n in nums) and
              len(nums)==len(set(nums)), "LINEUP_TOKENS_INVALID")
        seen.extend(nums)
        if len(nums)==1:
            solos.extend(nums)
        else:
            lines.append(nums)
    _need(sorted(seen)==sorted(starters) and len(seen)==len(set(seen)),
          "PREDICTED_LINEUP_INCOMPLETE_OR_WRONG")
    return {"lines":lines,"solos":solos}


def _csv_from_markdown(markdown,meta):
    _need(type(meta) is dict and
          source_id(meta.get("source_url"))=="keirin_hex",
          "KEIRIN_HEX_OWNER_SOURCE_REQUIRED")
    _need(meta.get("source_sha256") ==
          sha256(markdown.encode("utf-8")).hexdigest(),
          "OWNER_SAVED_MARKDOWN_SHA_MISMATCH")
    try:
        entrants=meta["race"]["starters"]
    except (KeyError,TypeError):
        raise OwnerRacecardError("OWNER_ROSTER_METADATA_REQUIRED") from None
    roster={p["number"]:p for p in entrants}
    board=_split_table(markdown)
    extracted={}
    for line in board:
        if "|" not in line:
            continue
        vals=[x.strip() for x in line.strip("|").split("|")]
        if not ROW_NUMBER.fullmatch(vals[0]):
            continue
        _need(len(vals)==22,"CHANGE_IN_PROVIDER_TABLE_SCHEMA")
        n=int(vals[0])
        _need(n in roster and n not in extracted,
              "DUPLICATE_OR_UNKNOWN_RIDER")
        target=roster[n]
        label=re.sub(r"[\s\u3000]+","",vals[1])
        label=MARKS.sub("",label)
        target_name=re.sub(r"[\s\u3000]+","",target["identity"])
        _need(label.startswith(target_name) and
              vals[3] in ("逃","両","追"),
              "SOURCE_IDENTITY_OR_RUNNING_STYLE_NOT_CONFIRMED")
        _need(DEC.fullmatch(vals[2]) is not None,
              "INVALID_UNCAPPED_RACE_SCORE")
        _need(DEC.fullmatch(vals[21]) is not None,
              "INVALID_GEAR_RATIO")
        for i in range(6,21):
            if i in (7,8,9):
                _need(PCT.fullmatch(vals[i]) is not None,
                      "PUBLIC_RATE_FORMAT_INVALID")
            else:
                _need(INTEGER.fullmatch(vals[i]) is not None,
                      "PUBLIC_COUNT_FORMAT_INVALID")
        if n in extracted:
            raise OwnerRacecardError("DUPLICATE_CSV_NUMBER")
        extracted[n]={
            "car_no":str(n),"rider_name":target["identity"],
            "grade":vals[1].split("・")[-2] if "・" in vals[1] else "UNKNOWN",
            "style":vals[3],"race_score":vals[2],
            "starts":vals[6],"wins":vals[10],"seconds":vals[11],
            "thirds":vals[12],"unplaced":vals[13],
            "s_count":vals[14],"h_count":vals[15],"b_count":vals[16],
            "escape_count":vals[17],"makuri_count":vals[18],
            "sashi_count":vals[19],"mark_count":vals[20],"gear":vals[21],
        }
    _need(len(extracted)==len(roster),
          "SOURCE_RACECARD_NOT_ALL_STARTERS")
    source_lineup=_lineup_from_text(markdown,extracted)
    original_lineup=meta["observed_race_facts"].get("line_order_all_riders")
    if original_lineup is not None and source_lineup is not None:
        expected=([line["order"] for line in original_lineup["lines"]],
                  original_lineup["solos"])
        _need(expected==(source_lineup["lines"],source_lineup["solos"]),
              "LINEUP_SOURCE_DISAGREES_WITH_OPERATOR_METADATA")
    # Extract only the pre-race lineup topology from the published page.
    # Assign group identity only if it matches the operator-declared roster.
    # Do NOT import the site's model probabilities, ◎ marks or buy picks.
    derived=meta["observed_race_facts"].copy()
    if source_lineup is not None and original_lineup is None:
        detected=[]
        for nums in source_lineup["lines"]:
            group_id=meta["race"]["starters"][nums[0]-1]["group_id"]
            _need(type(group_id) is str and group_id and
                  all(meta["race"]["starters"][n-1]["group_id"]==group_id
                      for n in nums),
                  "PREDICTED_LINEUP_ROSTER_ID_MISMATCH")
            detected.append({"group_id":group_id,"order":nums})
        _need(all(meta["race"]["starters"][n-1]["group_id"] is None
                  for n in source_lineup["solos"]),
              "PREDICTED_SOLOS_ROSTER_ID_MISMATCH")
        derived["line_order_all_riders"]={
            "lines":detected,
            "solos":source_lineup["solos"],
        }
    output=io.StringIO()
    writer=csv.DictWriter(output,fieldnames=FIELDS,lineterminator="\n")
    writer.writeheader()
    for n in sorted(extracted):
        writer.writerow(extracted[n])
    data=output.getvalue().encode("utf-8")
    doc={**meta,"source_sha256":sha256(data).hexdigest(),
         "observed_race_facts":derived}
    # Never assume that a lineup in a preview is official. A copied line
    # is an independently authored guess by the page operator, not a
    # confirmed actual race formation.
    return {
        "csv":data,
        "meta":doc,
        "original_markdown_sha256":sha256(markdown.encode("utf-8")).hexdigest(),
        "source_lineup_is_prediction_only":True,
        "lineup_extracted":source_lineup,
        "upstream_marks_and_probabilities_used":False,
        "provider_network_requests":0,
    }


def convert_owner_saved_hex_markdown(markdown,meta):
    result=_csv_from_markdown(markdown,meta)
    # The strict existing CSV converter decides if placing counts and rates
    # actually reconcile. Never promote contradictory counts into model inputs.
    verified=import_owner_saved_csv(result["csv"],result["meta"])
    return {
        **result,
        "converted_observation_count":verified["observed_fields"],
        "placing_count_conflict_riders":verified["race_count_conflict_riders"],
        "provider_data_rights_independently_proven":False,
        "prospective_forecast_ready":False,
    }


def stage_owner_saved_hex_markdown(inbox, *, now):
    """Private, create-only translation of owner-saved pages to CSV inbox.

    The owner supplies the visible Markdown and separately sourced race
    metadata. No pages are retrieved, no predictions or forecasts are
    generated here. A late capture is not a historical pre-race forecast.
    """
    from pathlib import Path
    import json
    import os
    from .keirin_permissioned_owner import _write_private_once
    from .keirin_result_delivery import utc

    root=Path(inbox).expanduser()
    _need(root.is_absolute() and root.is_dir() and
          not root.is_symlink(),"PRIVATE_OWNER_INBOX_REQUIRED")
    folder=root/"markdown"
    if not folder.exists():
        return {"translated_markdown":0,"already_translated":0,
                "rejected_markdown":0,"provider_http_requests":0}
    _need(folder.is_dir() and not folder.is_symlink(),
          "MARKDOWN_INBOX_SYMLINK_OR_TYPE_INVALID")
    files=sorted(folder.glob("*.md"))
    _need(len(files)<=50,"MARKDOWN_BATCH_LIMIT")
    (root/"csv").mkdir(mode=0o700,exist_ok=True)
    result={"translated_markdown":0,"already_translated":0,
            "rejected_markdown":0,"provider_http_requests":0}
    for path in files:
        try:
            _need(not path.is_symlink() and
                  0<path.stat().st_size<=500_000,
                  "MARKDOWN_SOURCE_FILE_INVALID")
            metadata=path.with_suffix(".meta.json")
            _need(metadata.is_file() and not metadata.is_symlink() and
                  0<metadata.stat().st_size<=100_000,
                  "SOURCE_METADATA_REQUIRED")
            page=path.read_text(encoding="utf-8")
            info=json.loads(metadata.read_text(encoding="utf-8"))
            _need(utc(info["source_observed_at"])<=utc(now)<
                  utc(info["race"]["official_cutoff_at"]),
                  "NOT_A_VALID_PRE_CUTOFF_OBSERVATION")
            converted=convert_owner_saved_hex_markdown(page,info)
            key=converted["original_markdown_sha256"]
            target=root/"csv"/(key+".csv")
            targetmeta=root/"csv"/(key+".meta.json")
            _write_private_once(targetmeta,converted["meta"])
            data=converted["csv"]
            try:
                fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            except FileExistsError:
                _need(target.is_file() and not target.is_symlink() and
                      target.read_bytes()==data,
                      "OWNER_CSV_READBACK_CONFLICT")
                result["already_translated"]+=1
            else:
                with os.fdopen(fd,"wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                result["translated_markdown"]+=1
        except (OSError,ValueError,TypeError,KeyError,UnicodeError):
            result["rejected_markdown"]+=1
    return result
