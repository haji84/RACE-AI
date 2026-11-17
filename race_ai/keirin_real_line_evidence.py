"""Public, manually transcribed pre-race line formations for future research.

This adapter DOES NOT claim that a predicted lineup actually held on the
track. No winner/order/B indicator proves a follower stayed attached. A planned
pair cannot become a HELD/GAPPED/SWITCHED training label through this module.
Only source text independently archived/reviewed can establish its provenance.

No provider GET, scraping, model-promotion, staking or production mutation.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from urllib.parse import parse_qs, urlsplit

SCHEMA = "RACE_AI_KEIRIN_PUBLIC_PLANNED_PAIR_RESEARCH_V1"
SUMMARY = "RACE_AI_KEIRIN_PUBLIC_PLANNED_PAIR_SUMMARY_V1"
JST = timezone(timedelta(hours=9))
ID = re.compile(r"^0[0-9]{5}$")
RACE = re.compile(r"^20[0-9]{10}$")
LINE_HOSTS = frozenset({
    "keirin.tokyo-sports.co.jp", "keirin.netkeiba.com",
    "keirin.kdreams.jp", "www.keirin-mobile.jp"
})
PROFILE_HOSTS = frozenset({"www.keirin.jp", "keirin.jp"})


class PlannedPairError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise PlannedPairError(reason)


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(obj):
    return sha256(canonical(obj)).hexdigest()


def _utc(value):
    require(type(value) is str, "AS_OF_TIMESTAMP_REQUIRED")
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise PlannedPairError("AS_OF_TIMESTAMP_INVALID") from None
    require(t.utcoffset() is not None, "AS_OF_OFFSET_REQUIRED")
    return t.astimezone(JST)


def _url(value, allowed_hosts):
    require(type(value) is str and len(value) <= 2048, "URL_REQUIRED")
    try:
        u = urlsplit(value)
        good = (u.scheme == "https" and u.hostname in allowed_hosts
                and u.username is None and u.password is None
                and u.port is None and not u.fragment)
    except ValueError:
        good = False
    require(good, "UNTRUSTED_SOURCE_HOST")
    return u


def validate_packet(packet):
    require(type(packet) is dict and
            set(packet) == {"schema", "checked_on_jst", "records", "notes"} and
            packet.get("schema") == SCHEMA, "PLANNED_PAIR_PACKET_SCHEMA")
    try:
        checked = date.fromisoformat(packet["checked_on_jst"])
    except (TypeError, ValueError):
        raise PlannedPairError("CHECK_DATE_INVALID") from None
    require(type(packet["records"]) is list and
            1 <= len(packet["records"]) <= 10000 and
            type(packet["notes"]) is str, "PLANNED_PAIR_PACKET_SIZE")
    keys = {"race_id", "leader_athlete_id", "follower_athlete_id",
            "leader_car", "follower_car", "expected_line_cars",
            "role", "line_evidence", "tactical_follow_outcome",
            "line_source_urls", "identity_source_urls"}
    seen = set()
    for row in packet["records"]:
        require(type(row) is dict and set(row) == keys,
                "PLANNED_PAIR_ROW_SCHEMA")
        rid = row["race_id"]
        require(type(rid) is str and RACE.fullmatch(rid) is not None,
                "RACE_ID_INVALID")
        try:
            raced = date.fromisoformat(rid[:4] + "-" + rid[4:6] + "-" + rid[6:8])
        except ValueError:
            raise PlannedPairError("HISTORICAL_RACE_DATE_INVALID") from None
        require(raced < checked, "LINE_SOURCE_NOT_HISTORICAL_ON_CHECK_DATE")
        lead = row["leader_athlete_id"]
        follow = row["follower_athlete_id"]
        require(type(lead) is str and type(follow) is str and
                ID.fullmatch(lead) and ID.fullmatch(follow) and lead != follow,
                "RIDER_REGISTRATION_IDS_REQUIRED")
        lc, fc = row["leader_car"], row["follower_car"]
        line = row["expected_line_cars"]
        require(type(lc) is int and type(fc) is int and
                type(line) is list and 2 <= len(line) <= 9 and
                all(type(x) is int and 1 <= x <= 9 for x in line) and
                len(line) == len(set(line)) and line[:2] == [lc, fc] and
                row["role"] == "SECOND_WHEEL", "LINE_POSITION_OR_ROLE_INVALID")
        require(row["line_evidence"] == "PRE_RACE_PREDICTED_LINE_ONLY" and
                row["tactical_follow_outcome"] == "UNKNOWN",
                "UNVERIFIED_PLANNED_PAIR_CANNOT_BE_FOLLOW_RESULT")
        urls = row["line_source_urls"]
        require(type(urls) is list and len(urls) >= 2 and len(urls) <= 5,
                "TWO_LINE_SOURCES_REQUIRED")
        hosts = {_url(u, LINE_HOSTS).hostname for u in urls}
        require(len(hosts) >= 2 and len(set(urls)) == len(urls),
                "INDEPENDENT_LINE_HOSTS_REQUIRED")
        profiles = row["identity_source_urls"]
        require(type(profiles) is dict and
                set(profiles) == {"leader", "follower"},
                "OFFICIAL_PROFILES_REQUIRED")
        for athlete, role in ((lead, "leader"), (follow, "follower")):
            u = _url(profiles[role], PROFILE_HOSTS)
            require(u.path == "/pc/racerprofile" and
                    parse_qs(u.query) == {"snum": [athlete]},
                    "RIDER_ID_AND_OFFICIAL_PROFILE_MISMATCH")
        marker = (rid, lead, follow, row["role"])
        require(marker not in seen, "DUPLICATE_RACE_PAIR")
        seen.add(marker)
    return packet


def summarize_planned_pairs(packet, *, as_of, independently_archive_verified=None):
    """Count *planned* pair appearances only after conservative availability.

    Source checks with only a JST DATE are treated as available on the NEXT
    JST calendar day, never retroactively at midnight of the checked day.
    An external verifier returning True can attest source archive integrity,
    but it still CANNOT create a tactical follow label from a planned line.
    """
    validate_packet(packet)
    t = _utc(as_of)
    checked = date.fromisoformat(packet["checked_on_jst"])
    usable = t.date() > checked
    pairs = defaultdict(list)
    attested = defaultdict(list)
    for row in packet["records"]:
        key = (row["leader_athlete_id"],
               row["follower_athlete_id"], row["role"])
        if not usable:
            continue
        pairs[key].append(row["race_id"])
        ok = False
        if callable(independently_archive_verified):
            try:
                ok = independently_archive_verified(row) is True
            except Exception:
                ok = False
        if ok:
            attested[key].append(row["race_id"])
    return {
        "schema": SUMMARY,
        "source_packet_sha256": digest(packet),
        "as_of": as_of,
        "source_checked_on_jst": packet["checked_on_jst"],
        "candidate_planned_pair_rows": (
            len(packet["records"]) if usable else 0),
        "unusable_until_next_jst_day": not usable,
        "by_athlete_pair": [
            {"leader_athlete_id": k[0], "follower_athlete_id": k[1],
             "role": k[2], "planned_race_ids": sorted(set(pairs[k])),
             "planned_pair_races": len(set(pairs[k])),
             "source_archive_attested_races": len(set(attested[k]))}
            for k in sorted(pairs)
        ],
        "independent_source_archive_verified_count": sum(
            len(set(v)) for v in attested.values()),
        "observed_follow_outcome_labels": 0,
        "no_held_gapped_switched_inference": True,
        "cohesion_model_training_eligible": False,
        "historical_planned_line_is_not_verified_actual_line": True,
        "forward_three_arm_accuracy_proven": False,
    }
