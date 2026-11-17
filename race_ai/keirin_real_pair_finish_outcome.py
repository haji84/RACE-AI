"""Read-only joining of real predicted line pairs to POST-RACE finish texts.

A finish order can corroborate a historical co-appearance and final placing.
It cannot establish who followed whom at BELL/HOME/BACK/CORNER or whether
the trailing rider remained with the leader. Keep HELD/GAPPED/SWITCHED UNKNOWN.
No source fetching, no model modification, no betting or production promotion.
"""
from __future__ import annotations

from datetime import date
from urllib.parse import urlsplit, parse_qs

from . import keirin_real_line_evidence as planned

SCHEMA = "RACE_AI_KEIRIN_PUBLIC_HISTORICAL_PAIR_FINISHES_V1"
REPORT = "RACE_AI_KEIRIN_PUBLIC_PAIR_FINAL_PLACING_RESEARCH_V1"
HOSTS = frozenset({"www.keirin-mobile.jp","keirinhex.jp",
                   "www.chariloto.com","keirin.netkeiba.com"})


class PairFinishError(ValueError):
    pass


def require(ok, code):
    if not ok:
        raise PairFinishError(code)


def _date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError,ValueError):
        raise PairFinishError("DATE_INVALID") from None


def validate_results(doc):
    require(type(doc) is dict and
            set(doc) == {"schema","checked_on_jst","remarks","races"} and
            doc.get("schema")==SCHEMA and type(doc.get("remarks")) is str,
            "HISTORICAL_FINISH_PACKET_SCHEMA")
    checked=_date(doc["checked_on_jst"])
    require(type(doc["races"]) is list and 1<=len(doc["races"])<=10000,
            "HISTORICAL_FINISH_PACKET_SIZE")
    fields={"race_id","winner_3ren_tan","finish_order","disqualified_cars",
            "leader_car","follower_car","leader_kimari","follower_kimari",
            "public_result_urls","organizer_result_independently_attested",
            "source_html_bytes_sha256","tactical_follow_outcome"}
    seen=set()
    for row in doc["races"]:
        require(type(row) is dict and set(row)==fields,
                "HISTORICAL_FINISH_ROW_SCHEMA")
        rid=row["race_id"]
        require(type(rid) is str and planned.RACE.fullmatch(rid) and
                _date(rid[:4]+"-"+rid[4:6]+"-"+rid[6:8])<checked and
                rid not in seen,"RACE_DATE_OR_DUPLICATE_INVALID")
        seen.add(rid)
        placed=row["finish_order"]; dq=row["disqualified_cars"]
        require(type(placed) is list and type(dq) is list and
                len(placed) in range(3,10) and
                len(set(placed))==len(placed) and
                all(type(i) is int and 1<=i<=9 for i in placed+dq) and
                not set(placed).intersection(dq) and
                len(set(dq))==len(dq),
                "FINAL_ORDER_OR_DISQUALIFICATION_INVALID")
        require(type(row["winner_3ren_tan"]) is list and
                len(row["winner_3ren_tan"])==3 and
                row["winner_3ren_tan"]==placed[:3],
                "WINNING_TRIPLE_NOT_MATCH_FINAL_ORDER")
        require(type(row["leader_car"]) is int and
                type(row["follower_car"]) is int and
                row["leader_car"]!=row["follower_car"] and
                row["leader_car"] in placed+dq and
                row["follower_car"] in placed+dq,
                "HISTORICAL_PAIR_NOT_IN_RESULT")
        require(row["leader_kimari"] in ("NIGE","MAKURI","SASHI","MARK",None) and
                row["follower_kimari"] in ("NIGE","MAKURI","SASHI","MARK",None),
                "RESULT_METHOD_SCHEMA")
        urls=row["public_result_urls"]
        require(type(urls) is list and len(urls)>=2 and len(urls)<=5,
                "TWO_RESULT_SOURCES_REQUIRED")
        hosts=set()
        for url in urls:
            require(type(url) is str and len(url)<=2048,
                    "RESULT_URL_REQUIRED")
            try:
                u=urlsplit(url)
                valid=(u.scheme=="https" and u.hostname in HOSTS and
                       u.port is None and u.username is None and
                       u.password is None and not u.fragment)
            except ValueError:
                valid=False
            require(valid,"RESULT_SOURCE_HOST_INVALID")
            hosts.add(u.hostname)
            d, v, n = rid[:8], rid[8:10], rid[10:12]
            if u.hostname == "www.keirin-mobile.jp":
                identity = (u.path == "/top/result.php" and
                            parse_qs(u.query) == {
                                "date": [d], "jcode": [v], "race": [n]})
            elif u.hostname == "keirinhex.jp":
                identity = (u.path == "/races/" + d + "/" + n + v + d + "/"
                            and not u.query)
            elif u.hostname == "www.chariloto.com":
                identity = (u.path == "/keirin/results/" + v + "/" +
                            d[:4] + "-" + d[4:6] + "-" + d[6:] + "/"
                            and not u.query)
            else:  # netkeirin
                identity = (parse_qs(u.query).get("race_id") == [rid])
            require(identity, "RESULT_SOURCE_NOT_BOUND_TO_RACE_DATE_VENUE")
        require(len(hosts)>=2 and len(set(urls))==len(urls),
                "INDEPENDENT_RESULT_HOSTS_REQUIRED")
        require(row["organizer_result_independently_attested"] is False and
                row["source_html_bytes_sha256"] is None and
                row["tactical_follow_outcome"]=="UNKNOWN",
                "RESULT_TEXT_IS_NOT_SIGNED_TACTICAL_OR_ORGANIZER_PROOF")
    return doc


def join_planned_and_finishes(planned_doc, result_doc, *, as_of):
    planned.validate_packet(planned_doc)
    validate_results(result_doc)
    # When date-only sources were checked, do not retroactively claim they
    # were available earlier that day. Both source checks must be old enough.
    at=planned._utc(as_of)
    available=at.date()>max(_date(planned_doc["checked_on_jst"]),
                            _date(result_doc["checked_on_jst"]))
    by_rid={row["race_id"]:row for row in result_doc["races"]}
    outputs=[]
    for line in planned_doc["records"]:
        result=by_rid.get(line["race_id"])
        require(result is not None and
                result["leader_car"]==line["leader_car"] and
                result["follower_car"]==line["follower_car"],
                "PLANNED_AND_FINISH_RIDER_PAIR_MISMATCH")
        placed=result["finish_order"]
        leader=placed.index(result["leader_car"])+1 if result["leader_car"] in placed else None
        follower=placed.index(result["follower_car"])+1 if result["follower_car"] in placed else None
        outputs.append({
            "race_id":line["race_id"],
            "leader_athlete_id":line["leader_athlete_id"],
            "follower_athlete_id":line["follower_athlete_id"],
            "role":"SECOND_WHEEL",
            "leader_finish_rank":leader if available else None,
            "follower_finish_rank":follower if available else None,
            "paired_top_two_placing":(leader==1 and follower==2) if available else None,
            "follower_mark_method_public_text":(
                result["follower_kimari"]=="MARK") if available else None,
            "tactical_follow_outcome":"UNKNOWN",
            "observed_as_historical_finish_only":available,
        })
    require(len({x["race_id"] for x in outputs})==len(outputs),
            "DUPLICATE_PLANNED_RACE_PAIRS_UNSUPPORTED")
    return {
        "schema":REPORT,
        "as_of":as_of,
        "planned_pair_packet_sha256":planned.digest(planned_doc),
        "public_finish_packet_sha256":planned.digest(result_doc),
        "status":"HISTORICAL_FINAL_PLACING_ONLY" if available else
                 "HOLD_SOURCE_DATE_NOT_YET_AVAILABLE",
        "planned_co_appearance_rows":len(outputs) if available else 0,
        "co_finish_1st_2nd_count":sum(
            x["paired_top_two_placing"] is True for x in outputs),
        "independent_organizer_source_bytes_attested":0,
        "validated_on_track_follow_outcome_labels":0,
        "eligible_as_C_model_held_gapped_switched_history":False,
        "eligible_for_formal_A_B_C_prospective_result":False,
        "rows":outputs,
    }
