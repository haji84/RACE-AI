"""Offline, provenance-preserving result overlay for owner-authored KEIRIN picks.

This is a RESEARCH/VIEWER adapter. It never fetches websites, never authenticates
an official result, never changes forecasts, and never settles the PR71 models.
Only independently admitted, private result-row *candidates* from the existing
licensed V3 provider path may be passed here. No production score is claimed.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re

JST = timezone(timedelta(hours=9))
SCHEMA = "RACE_AI_KEIRIN_MANUAL_71_RESULT_AUDIT_V1"
SOURCE_SCHEMA = "RACE_AI_KEIRIN_LICENSED_RESULT_REVISION_V1"
SHA = re.compile(r"[a-f0-9]{64}\Z")
RID = re.compile(r"([0-9]{2})-([0-9]{2})\Z")
RESULT_ID = re.compile(r"20\d{10}\Z")
CATEGORY = {"solid": "信頼度高め", "upset": "波乱警戒", "other": "その他"}
MAX_JSON = 2_000_000


class ManualSyncError(ValueError):
    pass


def need(cond, code):
    if not cond:
        raise ManualSyncError(code)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def dt(value):
    need(type(value) is str, "TIMESTAMP_REQUIRED")
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ManualSyncError("INVALID_TIMESTAMP") from None
    need(d.utcoffset() is not None, "TIMEZONE_REQUIRED")
    return d


def triple(value):
    need(type(value) is list and len(value) == 3 and
         all(type(n) is int and 1 <= n <= 9 for n in value) and
         len(set(value)) == 3, "INVALID_THREE_CAR_TICKET")
    return tuple(value)


def read_json(path, *, maximum=MAX_JSON):
    p = Path(path)
    need(p.is_file() and not p.is_symlink() and 0 < p.stat().st_size <= maximum,
         "INVALID_PRIVATE_INPUT")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError):
        raise ManualSyncError("INVALID_JSON") from None


def read_forecast(path, *, expected_file_sha256, baseline_file):
    """Caller must pin the exact uploaded source bytes; the source is not changed."""
    need(type(expected_file_sha256) is str and SHA.fullmatch(expected_file_sha256),
         "FORECAST_SHA_PIN_REQUIRED")
    p = Path(path)
    need(p.is_file() and not p.is_symlink() and p.stat().st_size <= MAX_JSON,
         "INVALID_FORECAST_FILE")
    raw = p.read_bytes()
    need(sha256(raw).hexdigest() == expected_file_sha256,
         "FORECAST_SOURCE_SHA_MISMATCH")
    d = read_json(p)
    need(type(d) is dict and d.get("date") == "2026-11-17" and
         d.get("timezone") == "Asia/Tokyo" and
         type(d.get("races")) is list and len(d["races"]) == 71,
         "NOV17_FORECAST_SNAPSHOT_REQUIRED")
    need(d.get("pre_race_rank_1_changed") is False,
         "FIRST_RANK_REVISION_UNEXPECTED")
    base_pub = dt(d.get("baseline_v2_publication_time"))
    final_pub = dt(d.get("generated_at"))
    orig_pub = dt(d.get("original_pre_race_snapshot_time"))
    need(orig_pub <= base_pub <= final_pub and
         all(x.astimezone(JST).date().isoformat() == d["date"] for x in
             (orig_pub, base_pub, final_pub)), "PREDICTION_PUBLICATION_ORDER_INVALID")
    # The v3 metadata field "prior_research_first" is inconsistent for some
    # races; only the SHA-verified actual v2 ranked list is authoritative.
    old_file = Path(baseline_file)
    need(old_file.is_file() and not old_file.is_symlink() and
         old_file.stat().st_size <= MAX_JSON,
         "BASELINE_V2_FILE_REQUIRED")
    need(sha256(old_file.read_bytes()).hexdigest() == d.get("baseline_v2_sha256"),
         "BASELINE_V2_SHA_MISMATCH")
    old = read_json(old_file)
    need(type(old) is dict and old.get("date") == d["date"] and
         type(old.get("ranked_races")) is list and
         len(old["ranked_races"]) == 71,
         "BASELINE_V2_RACE_SET_MISMATCH")
    old_races = {r.get("id"):r for r in old["ranked_races"]}
    need(len(old_races) == 71, "BASELINE_V2_DUPLICATE_RACE")
    seen = set()
    for r in d["races"]:
        need(type(r) is dict and type(r.get("id")) is str and
             RID.fullmatch(r["id"]) and r["id"] not in seen,
             "BAD_OR_DUPLICATE_RACE_ID")
        seen.add(r["id"])
        code, rn = (int(x) for x in RID.fullmatch(r["id"]).groups())
        need(code in range(1, 100) and rn in range(1, 13) and
             r.get("race") == rn and type(r.get("venue")) is str and
             bool(r["venue"]), "RACE_ID_OR_VENUE_MISMATCH")
        need(type(r.get("start")) is str and
             re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", r["start"]),
             "START_TIME_REQUIRED")
        need(type(r.get("ranked_picks")) is list and
             1 <= len(r["ranked_picks"]) <= 12 and
             type(r.get("v2_count")) is int and
             type(r.get("v3_count")) is int and
             1 <= r["v2_count"] <= r["v3_count"] == len(r["ranked_picks"]),
             "RANK_COUNTS_INVALID")
        tickets = []
        for i, pick in enumerate(r["ranked_picks"], 1):
            need(type(pick) is dict and pick.get("rank") == i,
                 "RANK_ORDER_MISMATCH")
            tickets.append(triple(pick.get("cars")))
        old_row = old_races.get(r["id"])
        need(type(old_row) is dict and old_row.get("venue") == r["venue"] and
             old_row.get("start") == r["start"] and
             type(old_row.get("ranked_picks")) is list and
             len(old_row["ranked_picks"]) == r["v2_count"],
             "BASELINE_RACE_OR_SCHEDULE_MISMATCH")
        need(len(tickets) == len(set(tickets)) and
             tickets[:r["v2_count"]] ==
                 [triple(z.get("cars")) for z in old_row["ranked_picks"]] and
             type(r.get("new_candidate_ranks")) is list and
             r["new_candidate_ranks"] == list(range(r["v2_count"]+1,
                                                     r["v3_count"]+1)),
             "INHERITED_PICKS_OR_RANKS_TAMPERED")
    return d


def read_categories(html_path, forecasts):
    """Read existing user-facing category tags; never invent confidence odds."""
    if html_path is None:
        return {}
    p = Path(html_path)
    need(p.is_file() and not p.is_symlink() and p.stat().st_size <= 1_000_000,
         "INVALID_CATEGORY_HTML")
    txt = p.read_text(encoding="utf-8")
    # Original static cards: each id and category on the SAME opening tag.
    rows = re.findall(r'<article\s+[^>]*>', txt)
    got = {}
    expected = {r["id"] for r in forecasts["races"]}
    for tag in rows:
        rid = re.search(r'\bid="r(\d\d-\d\d)"',tag)
        kind = re.search(r'\bdata-kind="(solid|upset|other)"',tag)
        if rid and kind:
            need(rid.group(1) not in got, "DUPLICATE_HTML_RACE_CARD")
            got[rid.group(1)] = kind.group(1)
    need(set(got) == expected, "CATEGORY_HTML_NOT_SAME_71_RACES")
    return got


def _source_result_id(row):
    rid = row.get("race_id")
    need(type(rid) is str and RESULT_ID.fullmatch(rid), "INVALID_RESULT_ID")
    # Existing authorized result stage uses YYYYMMDD + XX (venue) + RR (race).
    need(rid[:8] == "20261117", "RESULT_FROM_DIFFERENT_DAY")
    return rid[8:10] + "-" + rid[10:12]


def read_result_candidates(folder, *, as_of):
    """Only already staged V3 rows. Never fetch network or certify their truth."""
    now = dt(as_of)
    directory = Path(folder)
    if not directory.exists():
        return {}
    need(directory.is_dir() and not directory.is_symlink(),
         "PRIVATE_RESULT_DIR_REQUIRED")
    files = sorted(directory.iterdir())
    need(len(files) <= 2000, "RESULT_FILE_LIMIT")
    revisions = defaultdict(list)
    for p in files:
        need(p.suffix == ".json" and SHA.fullmatch(p.stem) and
             p.is_file() and not p.is_symlink() and 0 < p.stat().st_size <= 65536,
             "RESULT_PRIVATE_FILE_REJECTED")
        raw = p.read_bytes()
        obj = read_json(p, maximum=65536)
        need(sha256(canonical(obj)).hexdigest() == p.stem,
             "RESULT_ROW_DIGEST_MISMATCH")
        need(type(obj) is dict and obj.get("schema") == SOURCE_SCHEMA,
             "EXISTING_LICENSED_RESULT_SCHEMA_REQUIRED")
        rid = _source_result_id(obj)
        need(obj.get("status") in {"FINAL_NORMAL","PENDING","CANCELLED",
            "NOT_OFFERED","SOURCE_UNAVAILABLE","CUTOFF_MISMATCH",
            "UNSUPPORTED_SPECIAL"} and obj.get("refund_status") in
            {"NONE","PARTIAL","FULL","UNKNOWN"}, "RESULT_STATE_INVALID")
        source_at, observed = dt(obj.get("source_published_at")), dt(obj.get("observed_at"))
        need(source_at <= observed <= now, "RESULT_CLOCK_OUTSIDE_OBSERVATION")
        need(type(obj.get("provider_revision_ref")) is str and
             1 <= len(obj["provider_revision_ref"]) <= 256,
             "RESULT_REVISION_REQUIRED")
        winners = obj.get("winning_triples")
        payments = obj.get("payouts_100yen")
        need(type(winners) is list and type(payments) is list and
             len(winners) <= 20 and len(winners) == len(payments),
             "RESULT_TICKET_PAYOUT_MISMATCH")
        triples = [triple(x) for x in winners]
        payout = {}
        for it in payments:
            need(type(it) is dict and set(it) == {"triple", "yen"} and
                 type(it["yen"]) is int and 0 < it["yen"] <= 1_000_000_000,
                 "RESULT_PAYOUT_INVALID")
            t = triple(it["triple"])
            need(t not in payout, "DUPLICATE_PAYOUT")
            payout[t] = it["yen"]
        need((obj["status"] == "FINAL_NORMAL" and
              set(triples) == set(payout) and bool(triples)) or
             (obj["status"] != "FINAL_NORMAL" and not triples),
             "INVALID_RESULT_SETTLEMENT")
        revisions[rid].append((observed, obj["provider_revision_ref"], p.stem,
                               obj, payout))
    chosen = {}
    for rid, seq in revisions.items():
        seq.sort(key=lambda t: (t[0],t[1]))
        by_ref = {}
        for item in seq:
            rev = item[1]
            need(rev not in by_ref or by_ref[rev] == item[2],
                 "SAME_REVISION_CONTENT_CHANGED")
            by_ref[rev] = item[2]
        chosen[rid] = seq[-1]
    return chosen


def _start_at(day, time):
    return datetime.fromisoformat(day+"T"+time+":00").replace(tzinfo=JST)


def _score(tickets, result):
    hits = [i+1 for i,t in enumerate(tickets) if t in result]
    return {"rank1_hit": bool(tickets and tickets[0] in result),
            "hit_any": bool(hits), "hit_ranks":hits,
            "stake_yen":100*len(tickets),
            "payout_yen":sum(result.get(t,0) for t in tickets),
            "tickets":len(tickets)}


def evaluate(snapshot, results, *, categories=None):
    """Result candidates are provisional, even if the normalized row says final."""
    categories = categories or {}
    base_pub = dt(snapshot["baseline_v2_publication_time"])
    expanded_pub = dt(snapshot["generated_at"])
    rows = []
    sums = defaultdict(lambda: {"races":0,"observed":0,"paired":0,
                                "base_hit1":0,"base_hitall":0,"new_hit1":0,
                                "new_hitall":0,"base_stake":0,"base_payout":0,
                                "new_stake":0,"new_payout":0})
    for row in snapshot["races"]:
        rid = row["id"]
        start = _start_at(snapshot["date"],row["start"])
        baseline = [triple(p["cars"]) for p in row["ranked_picks"][:row["v2_count"]]]
        extra = [triple(p["cars"]) for p in row["ranked_picks"][row["v2_count"]:]]
        base_early = base_pub < start
        expanded_early = expanded_pub < start
        # An expanded candidate published after the planned START is invalid
        # even for provisional pre-start analysis. Before START != before CUTOFF.
        can_include_extra = expanded_early
        news = baseline + (extra if can_include_extra else [])
        rec = results.get(rid)
        status = "RESULT_UNOBSERVED"
        payout = None
        if rec:
            obj = rec[3]
            if obj["status"] == "FINAL_NORMAL" and obj["refund_status"] == "NONE":
                payout = rec[4]
                status = "PROVISIONAL_RESULT_CANDIDATE"
            else:
                status = "RESULT_UNSETTLED_OR_REFUND"
        eligible = base_early and payout is not None
        audit = {"race_id":rid, "venue":row["venue"],"race":row["race"],
                 "start":row["start"],"category":categories.get(rid,"other"),
                 "result_state":status,
                 "official_result_independently_authenticated":False,
                 "official_sales_cutoff_attested":False,
                 "baseline_prior_to_planned_start":base_early,
                 "expansion_prior_to_planned_start":expanded_early,
                 "base_count":len(baseline),"new_count":len(news),
                 "late_added_candidates_excluded":len(extra) if not can_include_extra else 0,
                 "reference_comparison":None,
                 "forecast_source":"CHATGPT_MANUAL_RESEARCH_NOT_PR71"}
        if payout is not None:
            audit["observed_triples"] = [list(t) for t in payout]
            audit["payouts_100yen"] = {"-".join(map(str,t)):v for t,v in payout.items()}
            audit["source_revision_sha256"] = rec[2]
        if eligible:
            audit["reference_comparison"] = {"baseline":_score(baseline,payout),
                                              "expanded":_score(news,payout)}
        rows.append(audit)
        for group in ("all", row["venue"], "category:"+audit["category"]):
            s = sums[group]
            s["races"] += 1
            if payout is not None:
                s["observed"] += 1
            if eligible:
                s["paired"] += 1
                bs = audit["reference_comparison"]["baseline"]
                ns = audit["reference_comparison"]["expanded"]
                for pre, scores in (("base",bs),("new",ns)):
                    s[pre+"_hit1"] += int(scores["rank1_hit"])
                    s[pre+"_hitall"] += int(scores["hit_any"])
                    s[pre+"_stake"] += scores["stake_yen"]
                    s[pre+"_payout"] += scores["payout_yen"]
    return {"schema":SCHEMA, "event_date_jst":snapshot["date"],
            "source_type":"USER_CHAT_MANUAL_PREDICTIONS",
            "evaluation_type":"PROVISIONAL_PRE_START_PROXY_NOT_OFFICIAL",
            "official_results_authenticated":False,
            "official_cutoffs_verified":False,
            "signed_result_revisions_verified":False,
            "all_races":len(rows),"summary":dict(sums),"rows":rows}


def public_counters(report):
    """Only counts (not car numbers, payouts or private data) in Actions logs."""
    need(report.get("schema") == SCHEMA, "AUDIT_SCHEMA_REQUIRED")
    return {"state":"MANUAL_RESULT_RESEARCH_ONLY",
            "date":report["event_date_jst"],
            "total_races":report["all_races"],
            "results_observed_unverified":report["summary"]["all"]["observed"],
            "provisional_paired_races":report["summary"]["all"]["paired"],
            "official_result_authenticated":False,
            "official_cutoffs_verified":False,
            "formal_hit_at_1":None,"formal_hit_at_all":None,
            "formal_roi":None}


def render_html(report, forecast, *, template_text):
    """Local PRIVATE HTML for display; do not publish as GitHub artifacts."""
    need(report.get("schema") == SCHEMA and type(template_text) is str and
         "<html" in template_text.lower() and
         template_text.count("</body>") == 1,
         "ORIGINAL_HTML_TEMPLATE_REQUIRED")
    cards = {row["race_id"]:row for row in report["rows"]}
    safe = {"RESULT_UNOBSERVED":"結果待ち",
            "RESULT_UNSETTLED_OR_REFUND":"審議・返還など／採点保留",
            "PROVISIONAL_RESULT_CANDIDATE":"参考結果（未認証）"}
    def inject(m):
        tag=m.group(0)
        id_m = re.search(r'\bid="r(\d\d-\d\d)"',tag)
        if not id_m or id_m.group(1) not in cards:
            return tag
        row=cards[id_m.group(1)]
        label=safe[row["result_state"]]
        if row["reference_comparison"] is None:
            desc="正式な的中判定は保留"
        else:
            sr=row["reference_comparison"]["expanded"]
            desc=("第1候補的中" if sr["rank1_hit"] else
                  ("候補内的中" if sr["hit_any"] else "候補内不的中"))
            desc += "（参考）"
        result_text=""
        if row.get("observed_triples"):
            result_text=" / ".join("-".join(map(str,x)) for x in row["observed_triples"])
        return (tag+'<div class="keirin-auto-result">'
                +'<strong>'+escape(label)+'</strong> '
                +escape(result_text)+' <span>'+escape(desc)+'</span></div>')
    html = re.sub(r'<article\s+[^>]*>',inject,template_text)
    need(html.count('class="keirin-auto-result"') == 71,
         "NOT_ALL_71_RACES_RENDERED")
    style="""<style>
.keirin-auto-result{padding:8px 13px;background:#eaf2f6;color:#193b53;font-size:12px;border-bottom:1px solid #c9dbe5}
.keirin-auto-result strong{font-weight:850}.keirin-auto-result span{color:#536574}
</style>"""
    # Important: the existing 71 race/venue view and ranking is never replaced.
    html=html.replace("</head>",style+"</head>",1)
    banner=("<div class=\"keirin-result-audit-banner\" style=\"padding:13px;"
            "background:#e9f0f5;color:#234358;font-size:14px;"
            "font-weight:700;text-align:center\">"
            "結果照合：公式結果の自動取得・認証は未接続。"
            "現在の表示は結果待ち／参考検証のみ（実購入の収支ではありません）。"
            "</div>")
    summaries = report["summary"]
    keys = ["all", "category:solid", "category:upset", "category:other"]
    venues = sorted({r["venue"] for r in report["rows"]})
    keys.extend(venues)
    def short_row(key):
        r = summaries.get(key,{})
        comparable = r.get("paired",0)
        label = {"all":"全71レース", "category:solid":"信頼度高め",
                 "category:upset":"波乱警戒", "category:other":"その他"}.get(key,key)
        first = (str(r.get("new_hit1",0))+"/"+str(comparable)
                 if comparable else "未照合")
        all_hit = (str(r.get("new_hitall",0))+"/"+str(comparable)
                   if comparable else "未照合")
        stake = r.get("new_stake",0)
        roi = (("%.1f%%" % (100*r.get("new_payout",0)/stake))
               if stake else "未算定")
        return ("<tr><th>"+escape(label)+"</th><td>"+str(r.get("races",0))+"</td>"
                "<td>"+first+"</td><td>"+all_hit+"</td><td>"+roi+"</td></tr>")
    main_rows = "".join(short_row(k) for k in keys[:4])
    venue_rows = "".join(short_row(k) for k in keys[4:])
    header = "<thead><tr><th>区分</th><th>全R</th><th>第1候補</th><th>全候補</th><th>仮想回収率</th></tr></thead>"
    panel = ("<section class=\"manual-audit-summary\" aria-label=\"自動照合状況\">"
             "<h2>結果照合・暫定集計</h2><p>公式結果・正式締切の独立認証前です。"
             "未照合は不的中に含めません。第1候補／全候補／100円均等仮想回収率を分離。</p>"
             "<div class=\"manual-audit-table\"><table>"+header+
             "<tbody>"+main_rows+"</tbody></table></div>"
             "<details><summary>会場別の照合状況を見る</summary>"
             "<div class=\"manual-audit-table\"><table>"+header+
             "<tbody>"+venue_rows+"</tbody></table></div></details></section>")
    extra_style = """<style>
.manual-audit-summary{max-width:1080px;margin:12px auto;padding:15px;border-radius:12px;background:#fff;box-shadow:0 2px 10px #0001;color:#1a3245}
.manual-audit-summary h2{font-size:19px;margin:0 0 6px}.manual-audit-summary p{font-size:12px;margin:0 0 12px;color:#5c6d78}
.manual-audit-table{overflow-x:auto}.manual-audit-table table{border-collapse:collapse;width:100%;min-width:340px;font-size:12px}
.manual-audit-table th,.manual-audit-table td{padding:7px 5px;text-align:center;border-bottom:1px solid #dbe3e8}
.manual-audit-table th:first-child{text-align:left;white-space:nowrap}
.manual-audit-table thead{background:#e8f0f4}
.manual-audit-summary summary{cursor:pointer;padding:10px 0;color:#0a6257;font-weight:750}
</style>"""
    html=html.replace("</head>",extra_style+"</head>",1)
    html=html.replace("<body>","<body>"+banner+panel,1)
    return html
