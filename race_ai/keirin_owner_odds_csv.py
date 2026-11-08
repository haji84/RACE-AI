"""Offline owner-saved, full-universe pre-cutoff KEIRIN odds CSV intake.

No site fetch, scraping, API access, model probabilities, purchases, or
claim of data rights. Accept only already lawfully acquired private 210/504
row CSVs with a separate owner-authored SHA256 provenance manifest.
The runtime's NOW is the conservative capture time; never backdate to a
claimed provider publish time.
"""
from __future__ import annotations

import csv
from datetime import timedelta
from hashlib import sha256
import io
from itertools import permutations
import json
import math
import os
from pathlib import Path

from .keirin_result_delivery import canonical, utc
from .keirin_non_rakuten_sources import is_rakuten_url
from .keirin_variable_selection import ODDS_SCHEMA

HEADER=("first","second","third","decimal_odds")
MAX_BYTES=200_000
MAX_FILES=40
MARGIN_SECONDS=65

class OwnerOddsCsvError(ValueError):
    pass


def require(ok,code):
    if not ok:
        raise OwnerOddsCsvError(code)


def private_json(file):
    require(file.is_file() and not file.is_symlink()
            and 0<file.stat().st_size<=8192,"ODDS_META_FILE_INVALID")
    def unique(pairs):
        value={}
        for key, item in pairs:
            require(key not in value,"ODDS_DUPLICATE_META_KEY")
            value[key]=item
        return value
    return json.loads(file.read_text(encoding="utf-8"),
                      object_pairs_hook=unique)


def parse_full_odds_csv(content,meta,*,now,grant_check):
    require(type(content) is bytes and 0<len(content)<=MAX_BYTES,
            "ODDS_CSV_SIZE")
    require(type(meta) is dict and set(meta)=={
        "race_id","official_cutoff_at","starters",
        "source_url","rights_ref","csv_sha256"
    }, "ODDS_META_FIELDS_REQUIRED")
    require(type(meta["race_id"]) is str and 0<len(meta["race_id"])<=200,
            "ODDS_RACE_ID_REQUIRED")
    require(type(meta["starters"]) is list
            and len(meta["starters"]) in (7,9)
            and all(type(n) is int and 1<=n<=9 for n in meta["starters"])
            and len(set(meta["starters"]))==len(meta["starters"]),
            "ODDS_VALID_STARTERS_REQUIRED")
    require(type(meta["source_url"]) is str
            and meta["source_url"].startswith("https://")
            and not is_rakuten_url(meta["source_url"]),
            "ODDS_NON_RAKUTEN_HTTPS_SOURCE_REQUIRED")
    require(type(meta["rights_ref"]) is str and bool(meta["rights_ref"])
            and callable(grant_check)
            and grant_check(meta["source_url"],meta["rights_ref"],
                            "analysis") is True,
            "ODDS_PRIVATE_SOURCE_ADMISSION_REQUIRED")
    require(type(meta["csv_sha256"]) is str
            and sha256(content).hexdigest()==meta["csv_sha256"],
            "ODDS_ORIGINAL_CSV_HASH_MISMATCH")
    clock=utc(now)
    cutoff=utc(meta["official_cutoff_at"])
    require(clock+timedelta(seconds=MARGIN_SECONDS)<cutoff,
            "ODDS_SAVED_AFTER_CUTOFF_MARGIN")
    try:
        raw=content.decode("utf-8-sig")
    except UnicodeError as exc:
        raise OwnerOddsCsvError("ODDS_CSV_UTF8_REQUIRED") from exc
    reader=csv.DictReader(io.StringIO(raw, newline=""))
    require(tuple(reader.fieldnames or ())==HEADER, "ODDS_CSV_HEADER_INVALID")
    starters=sorted(meta["starters"])
    expected=set(permutations(starters,3))
    values={}
    for row in reader:
        require(type(row) is dict and set(row)==set(HEADER)
                and None not in row
                and all(type(row[k]) is str for k in HEADER),
                "ODDS_CSV_ROW_INVALID")
        try:
            triple=tuple(int(row[k]) for k in HEADER[:3])
            decimal=float(row["decimal_odds"])
        except (ValueError,TypeError) as exc:
            raise OwnerOddsCsvError("ODDS_NUMBER_INVALID") from exc
        require(all(str(n)==row[k].strip() for n,k in zip(triple,HEADER[:3]))
                and triple in expected and triple not in values,
                "ODDS_UNKNOWN_OR_DUPLICATE_TICKET")
        # 9999.9 is frequently an ambiguity/cap in odds tables, not
        # necessarily an executable price: refuse until source semantics
        # prove it is a genuine displayed price.
        require(math.isfinite(decimal) and 1<decimal<=1_000_000
                and decimal!=9999.9, "ODDS_MISSING_CAPPED_OR_NONFINITE")
        values[triple]=decimal
    require(set(values)==expected,
            "ODDS_COMPLETE_210_OR_504_UNIVERSE_REQUIRED")
    return {
        "schema":ODDS_SCHEMA,
        "race_id":meta["race_id"],
        "captured_at":clock.isoformat(),
        "source_ref":meta["source_url"],
        "source_rights_ref":meta["rights_ref"],
        "prices":[{"triple":list(t),"decimal_odds":values[t]}
                  for t in sorted(expected)],
    }


def stage_owner_saved_odds_csv(inbox, *, grant_check, now):
    root=Path(inbox).expanduser()
    require(root.is_absolute() and root.is_dir() and not root.is_symlink(),
            "ODDS_PRIVATE_ROOT_REQUIRED")
    source=root/"odds_csv"
    target=root/"odds"
    if source.is_symlink() or target.is_symlink():
        raise OwnerOddsCsvError("ODDS_SYMLINK_DIRECTORY_FORBIDDEN")
    if not source.exists():
        return {"schema":"RACE_AI_OWNER_ODDS_CSV_STAGE_V1",
                "files_seen":0,"created":0,"already_same":0,"rejected":0,
                "provider_network_requests":0,"official_rights_verified":False,
                "external_capture_time_verified":False}
    require(source.is_dir(),"ODDS_CSV_SOURCE_NOT_DIRECTORY")
    if not target.exists():
        target.mkdir(mode=0o700)
    require(target.is_dir(),"ODDS_PRIVATE_OUTPUT_REQUIRED")
    files=sorted(source.glob("*.csv"))
    require(len(files)<=MAX_FILES,"ODDS_INBOX_BATCH_LIMIT")
    created=identical=rejected=0
    for file in files:
        try:
            require(file.is_file() and not file.is_symlink()
                    and 0<file.stat().st_size<=MAX_BYTES,
                    "ODDS_CSV_FILE_INVALID")
            content=file.read_bytes()
            meta=private_json(file.with_suffix(".meta.json"))
            odds=parse_full_odds_csv(
                content,meta,now=now,grant_check=grant_check)
            name=sha256(meta["race_id"].encode("utf-8")).hexdigest()+".json"
            output=target/name
            require(not output.is_symlink(),"ODDS_TARGET_SYMLINK_FORBIDDEN")
            body=canonical(odds)
            try:
                flags=os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,"O_NOFOLLOW",0)
                handle=os.open(output,flags,0o600)
            except FileExistsError:
                require(output.is_file() and output.read_bytes()==body,
                        "ODDS_IMMUTABLE_SOURCE_CONFLICT")
                identical+=1
                continue
            with os.fdopen(handle,"wb") as saved:
                saved.write(body)
                saved.flush()
                os.fsync(saved.fileno())
            require(output.read_bytes()==body,"ODDS_PRIVATE_READBACK_FAILED")
            created+=1
        except (OSError,UnicodeError,TypeError,ValueError,KeyError):
            rejected+=1
    return {"schema":"RACE_AI_OWNER_ODDS_CSV_STAGE_V1",
            "files_seen":len(files),"created":created,"already_same":identical,
            "rejected":rejected,"provider_network_requests":0,
            "official_rights_verified":False,
            "external_capture_time_verified":False}
