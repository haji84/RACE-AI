"""Actual WINTICKET publicly rendered, preloaded 210-trifecta odds -> private snapshot.

No hidden API, HTTP GET, credentials or HTML logging. The caller supplies
already obtained ordinary public-page HTML. Vetted only for exact WINTICKET
Aomori URLs and their day/race identity. A snapshot is withheld unless ALL
210 ordered triples and each real decimal price pass, source update time is
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
    r"^/keirin/aomori/odds/([0-9]{10})/([1-3])/([1-9][0-9]?)$"
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
    event,day_str,race_no=m.groups()
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
        require(len(rows)==210,"AOMORI_7_RIDER_210_ONLY")
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
        universe=set(permutations(range(1,8),3))
        odds={}
        for row in rows:
            combo=row.get("key")
            require(type(combo) is list and len(combo)==3 and
                    all(type(n) is int and 1<=n<=7 for n in combo) and
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
        require(set(odds)==universe and len(odds)==210,
                "ODDS_FULL_UNIVERSE_MISSING")
        prices=[{"triple":list(key),"decimal_odds":odds[key]}
                for key in sorted(universe)]
        digest=sha256(canonical(prices)).hexdigest()
        admitted.append((digest,prices,source_time))
    require(bool(admitted),"NO_FULL_210_LIVE_ODDS_IN_EMBEDDED_STATE")
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
        "schema":"RACE_AI_KEIRIN_WINTICKET_210_VERIFIED_RECEIPT_V1",
        "race_id":race_id,
        "winticket_race_id":expected_site_id,
        "html_sha256":sha256(html).hexdigest(),
        "full_210_prices_sha256":price_sha,
        "private_odds_snapshot_sha256":sha256(canonical(normalized)).hexdigest(),
        "source_odds_updated_at_utc":updated.isoformat(),
        "owner_capture_at_utc":observed.isoformat(),
        "official_cutoff_at":cutoff.isoformat(),
        "combination_count":210,
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
