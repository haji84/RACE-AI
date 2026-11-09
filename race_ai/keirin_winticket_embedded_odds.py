"""Actual WINTICKET SSR 210/504-trifecta odds -> private snapshot.

No hidden API, HTTP GET, credentials or HTML logging. The caller supplies
already obtained ordinary public-page HTML. Vetted for the exact
WINTICKET venue/date/day/race identity. A snapshot is withheld unless ALL
210/504 ordered triples and each real decimal price pass, source update time is
fresh, and observation was genuinely before the published sales cutoff.

This is only an odds extractor, NOT a legal machine licence, independent
source timestamp witness, 347-factor rider feed or calibrated forecast.
"""
from __future__ import annotations

from datetime import datetime,timedelta,timezone
from hashlib import sha256
from itertools import permutations
import json
import math
import re
from urllib.parse import urlsplit

from .keirin_owner_manual import PERSONAL_MARKER
from .keirin_result_delivery import canonical,utc
from .keirin_variable_selection import ODDS_SCHEMA

MAX_HTML=8_000_000
MARGIN_SECONDS=65
MAX_AGE_SECONDS=1800
RACE_ID=re.compile(r"^[0-9]{12}$")
EVENT_PATH=re.compile(
    r"^/keirin/([a-z][a-z0-9-]{2,30})/odds/([0-9]{10})/([1-3])/([1-9][0-9]?)$"
)
PRELOADED=re.compile(r"window\.__PRELOADED_STATE__\s*=\s*")


class EmbeddedOddsError(ValueError):
    pass


def require(ok, code):
    if not ok:
        raise EmbeddedOddsError(code)


def checked_race_and_url(*, url,race_id):
    require(type(race_id) is str and RACE_ID.fullmatch(race_id),
            "CANONICAL_RACE_ID_REQUIRED")
    require(type(url) is str and len(url)<=512,
            "WINTICKET_SOURCE_URL_REQUIRED")
    parts=urlsplit(url)
    require(parts.scheme=="https" and
            parts.hostname in ("www.winticket.jp","winticket.jp") and
            parts.username is None and parts.password is None and
            parts.port is None and not parts.query and not parts.fragment,
            "UNTRUSTED_WINTICKET_ODDS_ORIGIN")
    m=EVENT_PATH.fullmatch(parts.path)
    require(m is not None,"WINTICKET_PUBLIC_ODDS_RACE_URL_REQUIRED")
    venue_slug,event,day_str,race_no=m.groups()
    require(venue_slug not in ("internal","api","auth"),
            "WINTICKET_VENUE_SLUG_INVALID")
    require(event[-2:]==race_id[8:10] and
            int(race_no)==int(race_id[10:12]),
            "WINTICKET_VENUE_OR_RACE_NO_MISMATCH")
    try:
        start=datetime.strptime(event[:8],"%Y%m%d").date()
        actual=datetime.strptime(race_id[:8],"%Y%m%d").date()
    except ValueError:
        raise EmbeddedOddsError("INVALID_WINTICKET_DATE") from None
    require(start+timedelta(days=int(day_str)-1)==actual,
            "WINTICKET_EVENT_DAY_MISMATCH")
    return race_id[10:12]+race_id[8:10]+race_id[:8]


def read_preloaded_json(html):
    require(type(html) is bytes and 0<len(html)<=MAX_HTML,
            "WINTICKET_HTML_SIZE_INVALID")
    try:
        text=html.decode("utf-8")
    except UnicodeError:
        raise EmbeddedOddsError("WINTICKET_HTML_NOT_UTF8") from None
    matches=list(PRELOADED.finditer(text))
    require(len(matches)==1,"MISSING_OR_AMBIGUOUS_PRELOADED_STATE")
    source=text[matches[0].end():].lstrip()
    require(source.startswith("{"),"PRELOADED_STATE_NOT_DIRECT_JSON")
    def unique(pairs):
        out={}
        for key,value in pairs:
            require(key not in out,"DUPLICATE_EMBEDDED_JSON_KEY")
            out[key]=value
        return out
    decoder=json.JSONDecoder(
        object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(
            EmbeddedOddsError("NONFINITE_EMBEDDED_JSON")))
    try:
        state,_=decoder.raw_decode(source)
    except (ValueError,RecursionError):
        raise EmbeddedOddsError("PRELOADED_JSON_MALFORMED") from None
    require(type(state) is dict,"PRELOADED_STATE_NOT_OBJECT")
    return state


def private_winticket_trifecta(html,*,url,race_id,captured_at,
                              official_cutoff_at):
    """Returns private {odds,receipt}; never writes or prints these values."""
    expected_site_id=checked_race_and_url(url=url,race_id=race_id)
    observed=utc(captured_at)
    cutoff=utc(official_cutoff_at)
    require(observed+timedelta(seconds=MARGIN_SECONDS)<cutoff,
            "PRE_CUTOFF_ODDS_MARGIN_NOT_MET")
    state=read_preloaded_json(html)
    all_queries=state.get("tanStackQuery")
    require(type(all_queries) is dict and
            type(all_queries.get("queries")) is list and
            len(all_queries["queries"])<=250,
            "PRELOADED_QUERY_CACHE_INVALID")
    admitted=[]
    for query in all_queries["queries"]:
        if not isinstance(query,dict):
            continue
        s=query.get("state")
        data=s.get("data") if isinstance(s,dict) else None
        if not isinstance(data,dict):
            continue
        rows=data.get("trifecta")
        if not isinstance(rows,list) or len(rows) not in (210,504):
            continue
        entrants=7 if len(rows)==210 else 9
        require(all(isinstance(row,dict) and
                    row.get("raceId")==expected_site_id for row in rows),
                "SOURCE_RACE_ID_MISMATCH")
        updated=data.get("oddsUpdatedAt")
        require(type(updated) is int and
                1_500_000_000<=updated<=2_400_000_000,
                "ODDS_PROVIDER_UPDATE_CLOCK_REQUIRED")
        source_time=datetime.fromtimestamp(updated,timezone.utc)
        require(source_time<=observed and
                timedelta(0)<=observed-source_time<=
                    timedelta(seconds=MAX_AGE_SECONDS) and
                source_time<cutoff,
                "ODDS_PROVIDER_UPDATE_NOT_FRESH_PRE_CUTOFF")
        require(data.get("oddsDelayed") is False and
                data.get("isAggregated") is True and
                data.get("finalOdds") is False,
                "ODDS_PROVIDER_STATUS_NOT_LIVE")
        universe=set(permutations(range(1,entrants+1),3))
        odds={}
        for row in rows:
            combo=row.get("key")
            require(type(combo) is list and len(combo)==3 and
                    all(type(n) is int and 1<=n<=entrants for n in combo) and
                    len(set(combo))==3,
                    "ODDS_SOURCE_TRIPLE_INVALID")
            key=tuple(combo)
            require(key in universe and key not in odds,
                    "ODDS_SOURCE_TRIPLE_DUPLICATE_OR_UNKNOWN")
            price=row.get("odds")
            require(type(price) in (int,float) and math.isfinite(price) and
                    1.0<price<1_000_000 and price!=9999.9 and
                    row.get("absent") is False,
                    "ODDS_MISSING_CAPPED_OR_NONFINITE")
            string=row.get("oddsStr")
            require(type(string) is str and
                    re.fullmatch(r"[0-9][0-9,]*(?:\.[0-9]+)?",string)
                    is not None,
                    "DISPLAYED_SOURCE_ODDS_REQUIRED")
            try:
                displayed=float(string.replace(",",""))
            except ValueError:
                raise EmbeddedOddsError("DISPLAYED_SOURCE_ODDS_INVALID") from None
            require(math.isclose(price,displayed,rel_tol=0,abs_tol=1e-7),
                    "ODDS_SOURCE_DISPLAY_NUMERIC_MISMATCH")
            odds[key]=float(price)
        require(set(odds)==universe and len(odds)==len(universe),
                "ODDS_FULL_UNIVERSE_MISSING")
        prices=[{"triple":list(key),"decimal_odds":odds[key]}
                for key in sorted(universe)]
        digest=sha256(canonical(prices)).hexdigest()
        admitted.append((digest,prices,source_time))
    require(bool(admitted),"NO_FULL_210_OR_504_LIVE_ODDS_IN_EMBEDDED_STATE")
    require(len({x[0] for x in admitted})==1,
            "CONFLICTING_EMBEDDED_ODDS_SNAPSHOTS")
    price_sha,prices,updated=admitted[0]
    normalized={
        "schema":ODDS_SCHEMA,
        "race_id":race_id,
        "captured_at":observed.isoformat(),
        "source_ref":url,
        "source_rights_ref":PERSONAL_MARKER,
        "prices":prices,
    }
    receipt={
        "schema":f"RACE_AI_KEIRIN_WINTICKET_{len(prices)}_VERIFIED_RECEIPT_V1",
        "race_id":race_id,
        "winticket_race_id":expected_site_id,
        "html_sha256":sha256(html).hexdigest(),
        f"full_{len(prices)}_prices_sha256":price_sha,
        "private_odds_snapshot_sha256":sha256(canonical(normalized)).hexdigest(),
        "source_odds_updated_at_utc":updated.isoformat(),
        "owner_capture_at_utc":observed.isoformat(),
        "official_cutoff_at":cutoff.isoformat(),
        "combination_count":len(prices),
        "all_combinations_unique":True,
        "all_observed_price_numbers_valid":True,
        "all_source_display_odds_equal":True,
        "publisher_timestamp_independently_attested":False,
        "provider_machine_rights_independently_verified":False,
        "real_ability_model_inputs_ready":False,
        "production_forecasts_saved":False,
        "private_plaintext_published":False,
    }
    return {"odds":normalized,"receipt":receipt}


def stage_private_winticket_odds(inbox, verified):
    """Create-once complete odds at the existing owner-agent inbox/odds path.

    Never replace a historical first-capture odds record: later prices may
    arrive, but a previously frozen prediction must remain reproducible.
    The caller supplies validated data from private_winticket_trifecta().
    No provider data is written into a public Git checkout or CI artifact.
    """
    from pathlib import Path
    import os
    from .keirin_permissioned_owner import _write_private_once
    root=Path(inbox).expanduser()
    require(root.is_absolute() and root.is_dir() and not root.is_symlink(),
            "OWNER_PRIVATE_INBOX_REQUIRED")
    workspace=os.environ.get("GITHUB_WORKSPACE")
    if workspace:
        public=Path(workspace).resolve()
        private=root.resolve()
        require(public!=private and public not in private.parents,
                "PUBLIC_GIT_WORKSPACE_PRIVATE_INPUT_FORBIDDEN")
    if os.environ.get("GITHUB_ACTIONS")=="true":
        require(os.environ.get("RACE_AI_PERSISTENT_PRIVATE_VOLUME")==
                "ACKNOWLEDGED",
                "EPHEMERAL_ACTIONS_DB_NOT_PERSISTENT")
    require(type(verified) is dict and
            set(verified)=={"odds","receipt"},
            "VERIFIED_PRICE_AND_RECEIPT_REQUIRED")
    odds=verified["odds"]
    evidence=verified["receipt"]
    require(type(odds) is dict and type(evidence) is dict and
            odds.get("schema")==ODDS_SCHEMA and
            odds.get("race_id")==evidence.get("race_id") and
            len(odds.get("prices",[])) in (210,504) and
            evidence.get("combination_count")==len(odds["prices"]) and
            evidence.get("schema")==(
                f"RACE_AI_KEIRIN_WINTICKET_{len(odds['prices'])}_VERIFIED_RECEIPT_V1") and
            sha256(canonical(odds)).hexdigest()==
                evidence.get("private_odds_snapshot_sha256") and
            sha256(canonical(odds["prices"])).hexdigest()==
                evidence.get(f"full_{len(odds['prices'])}_prices_sha256"),
            "ODDS_SNAPSHOT_OR_SHA_NOT_AUTHENTICATED")
    folder=root/"odds"
    audit=root/"odds_winticket_receipts"
    for directory in (folder,audit):
        require(not directory.is_symlink(),"PRIVATE_ODDS_SYMLINK_REFUSED")
        if not directory.exists():
            directory.mkdir(mode=0o700)
        require(directory.is_dir(),"PRIVATE_ODDS_NOT_DIRECTORY")
    rid=odds["race_id"]
    file=folder/(sha256(rid.encode("utf-8")).hexdigest()+".json")
    require(not file.is_symlink(),"PRIVATE_ODDS_ORIGINAL_SYMLINK")
    fresh=False
    changed_candidate=False
    if file.exists():
        require(file.is_file() and file.stat().st_size<=250000,
                "PRIVATE_ODDS_ORIGINAL_INVALID")
        try:
            old=json.loads(file.read_text(encoding="utf-8"))
        except (OSError,ValueError):
            raise EmbeddedOddsError("PRIVATE_ODDS_ORIGINAL_UNREADABLE") from None
        require(type(old) is dict and
                old.get("schema")==ODDS_SCHEMA and
                old.get("race_id")==rid and
                old.get("source_ref")==odds["source_ref"] and
                type(old.get("prices")) is list and
                len(old["prices"])==len(odds["prices"]),
                "PRIVATE_ODDS_ORIGINAL_NOT_SAME_RACE")
        require(utc(old["captured_at"])<=utc(odds["captured_at"]),
                "PRIVATE_ODDS_EXISTING_FUTURE_CLOCK")
        changed_candidate=canonical(old["prices"])!=canonical(odds["prices"])
        # Capture history must never alter the original used by an earlier
        # forecast. Changing the source price is ordinary, not an overwrite.
    else:
        fresh=_write_private_once(file,odds)
        require(fresh and file.read_bytes()==canonical(odds),
                "PRIVATE_ODDS_CREATE_AND_READBACK_FAILED")
    receipt_name=sha256(canonical(evidence)).hexdigest()+".json"
    saved=_write_private_once(audit/receipt_name,evidence)
    require((audit/receipt_name).read_bytes()==canonical(evidence),
            "PRIVATE_ODDS_RECEIPT_READBACK_FAILED")
    return {
        "schema":"RACE_AI_KEIRIN_WINTICKET_ODDS_PRIVATE_STAGE_V1",
        "race_id":rid,
        "full_210_observed_rows":210 if len(odds["prices"])==210 else 0,
        "full_504_observed_rows":504 if len(odds["prices"])==504 else 0,
        "observed_trifecta_rows":len(odds["prices"]),
        "private_odds_created":int(fresh),
        "private_odds_original_preserved":not fresh,
        "newer_price_candidate_not_overwritten":changed_candidate,
        "private_provenance_receipt_created":bool(saved),
        "observed_price_set_sha256":
            evidence[f"full_{len(odds['prices'])}_prices_sha256"],
        "plaintext_public_git_written":False,
        "official_pre_cutoff_timestamp_witness":False,
        "actual_forecast_saved":False,
    }
