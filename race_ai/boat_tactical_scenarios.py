"""BOAT scenario-oriented C shadow from externally verified BEFORE-RACE history.

A/B remain unchanged. This C model is an untrained candidate, not a
replacement. Histories are explicitly separated from current exhibition;
the caller must independently attest official K/venue source authenticity.

Per-racer descriptors include actual course from historical K results, frame
entry patterns, recent form, course-specific winner methods and displaced
top-three rate. The winner's "kimarite" describes the RACE, not a proven
causal weakness of the losing racer. No age bonuses; young skilled racers are
not penalized for lacking a long national-win-rate history.
"""
from __future__ import annotations

from datetime import datetime
import itertools
import math
import re

from .boat_ab_shadow import _valid, _rank, _digest, _time

SCHEMA="RACE_AI_BOAT_TACTICAL_CANDIDATE_V1"
MODEL_ID="boat-course-entry-method-scenarios-v0.1-UNTRAINED"
MODES=("nige","sashi","makuri","makurizashi","other")
ALPHA_COURSE=12.
ALPHA_ENTRY=18.
ALPHA_METHOD=8.
MAX_SCENARIOS=12
HISTORY_SHA=re.compile(r"[0-9a-f]{64}\Z")


def _need(ok, message):
    if not ok: raise ValueError(message)


def _count(v):
    return type(v) is int and 0<=v<=1_000_000


def _number(v,lo,hi):
    return type(v) in (int,float) and math.isfinite(v) and lo<=v<=hi


def _time_no_future(v,decision):
    return _time(v)<=_time(decision)


def _profiles(profiles, boats,generated_at):
    _need(isinstance(profiles, list) and len(profiles)==len(boats),
          "all active racer historical profiles required; no absent profile fabricated")
    output={}
    keys={"racer_id","as_of","sample_races","actual_entry_course_history",
          "by_frame_actual_course_counts","wins_by_actual_course_and_kimarite",
          "recent_form","tendencies","source_receipt"}
    for x in profiles:
        _need(isinstance(x,dict) and set(x)==keys,"strict pre-race historical profile")
        rid=x["racer_id"]
        _need(isinstance(rid,str) and re.fullmatch(r"\d{4}",rid) and rid not in output,
              "duplicate or malformed historical racer")
        _need(_time_no_future(x["as_of"],generated_at),"history must predate future forecast")
        receipt=x["source_receipt"]
        _need(isinstance(receipt,dict) and set(receipt)==
              {"official_source_sha256","captured_at","upstream_identity_verified"},
              "historical source receipt incomplete")
        _need(receipt["upstream_identity_verified"] is True
              and isinstance(receipt["official_source_sha256"],str)
              and HISTORY_SHA.fullmatch(receipt["official_source_sha256"])
              and _time_no_future(receipt["captured_at"],generated_at),
              "unverified or post-forecast history")
        _need(_count(x["sample_races"]),"history sample count")
        actual=x["actual_entry_course_history"]
        frame_course=x["by_frame_actual_course_counts"]
        winners=x["wins_by_actual_course_and_kimarite"]
        _need(isinstance(actual,dict) and isinstance(frame_course,dict)
              and isinstance(winners,dict) and set(actual)==set(frame_course)==set(winners)==
                  {str(i) for i in range(1,7)},
              "all six historical courses must be explicit")
        for course in range(1,7):
            c=str(course);item=actual[c]
            _need(isinstance(item,dict) and all(_count(item.get(k)) for k in
                  ("starts","wins","top2","top3")),"strict historic course count")
            _need(item["wins"]<=item["top2"]<=item["top3"]<=item["starts"],
                  "historical course arithmetic")
            _need(isinstance(winners[c],dict) and all(_count(winners[c].get(m)) for m in MODES if m!="other"),
                  "historic winner-method count missing")
            _need(isinstance(frame_course[c],dict) and set(frame_course[c])==
                  {str(j) for j in range(1,7)} and
                  all(_count(n) for n in frame_course[c].values()),
                  "historic frame-to-course counts")
        if sum(actual[str(c)]["starts"] for c in range(1,7))!=x["sample_races"]:
            raise ValueError("racer course sample denominator conflict")
        if sum(frame_course[str(f)][str(c)] for f in range(1,7) for c in range(1,7))!=x["sample_races"]:
            raise ValueError("racer entry sample denominator conflict")
        for c in range(1,7):
            if sum(winners[str(c)][m] for m in winners[str(c)])!=actual[str(c)]["wins"]:
                raise ValueError("winner method count and course winner inconsistent")
        recent=x["recent_form"]
        _need(isinstance(recent,dict) and set(recent)=={"last_10","last_30"},
              "recent form schema")
        for key,limit in (("last_10",10),("last_30",30)):
            row=recent[key]
            _need(isinstance(row,dict) and all(_count(row.get(k)) for k in
                  ("starts","wins","top3")) and
                  row["wins"]<=row["top3"]<=row["starts"]<=min(limit,x["sample_races"]),
                  "recent samples cannot exceed verified records")
        t=x["tendencies"]
        _need(isinstance(t,dict) and all(_count(t.get(k)) for k in
              ("crossed_by_outer_frame","crossed_by_outer_frame_top3",
               "in1_starts","in1_wins")),
              "historic challenged entry counts required")
        _need(t["crossed_by_outer_frame_top3"]<=t["crossed_by_outer_frame"]<=x["sample_races"]
              and t["in1_wins"]<=t["in1_starts"]<=x["sample_races"],
              "historic victim/defender denominator conflict")
        losses=t.get("in1_losses_by_winner_method")
        _need(isinstance(losses,dict) and all(_count(v) for v in losses.values()),
              "historic method of winner for inside course losses required")
        output[rid]=x
    _need(set(output)=={x["racer_id"] for x in boats},
          "history and official program do not have same active racers")
    return output


def _venue(venue,generated_at):
    _need(isinstance(venue,dict) and set(venue)=={
        "venue_code","captured_at","official_source_sha256",
        "frame_course_counts","course_win_rate","course_top3_rate","winner_method_rates",
        "source_identity_verified"},
        "exact independently identified venue baseline required")
    _need(venue["source_identity_verified"] is True
          and isinstance(venue["venue_code"],str)
          and re.fullmatch(r"0[1-9]|1\d|2[0-4]",venue["venue_code"])
          and isinstance(venue["official_source_sha256"],str)
          and HISTORY_SHA.fullmatch(venue["official_source_sha256"])
          and _time_no_future(venue["captured_at"],generated_at),
          "unverified or future venue baseline")
    mat=venue["frame_course_counts"]
    _need(isinstance(mat,list) and len(mat)==6 and all(
        isinstance(row,list) and len(row)==6 and all(_count(v) for v in row)
        and sum(row)>0 for row in mat),
        "official venue frame-to-course matrix missing")
    for key in ("course_win_rate","course_top3_rate"):
        v=venue[key]
        _need(isinstance(v,list) and len(v)==6 and all(_number(x,0,1) for x in v),
              "official venue historical course rates")
    methods=venue["winner_method_rates"]
    _need(isinstance(methods,dict) and set(methods)==set(MODES)
          and all(_number(x,0,1) for x in methods.values())
          and math.isclose(math.fsum(methods.values()),1.,abs_tol=1e-8),
          "official historical winning-method distribution")
    return venue


def _entry_probability(hist,venue,frame,course):
    prior=venue["frame_course_counts"][frame-1]
    venue_p=prior[course-1]/sum(prior)
    racer=hist["by_frame_actual_course_counts"][str(frame)]
    return (racer[str(course)]+ALPHA_ENTRY*venue_p)/(sum(racer.values())+ALPHA_ENTRY)


def _base_strength(row,hist,venue,course,model_mode,field):
    rate=max(row["national_win_rate"] if row["national_win_rate"] is not None else 1.0,.01)
    mean=field["mean_exhibition"]
    value=math.log(rate)+mean-row["exhibition_time_seconds"]
    raw=hist["actual_entry_course_history"][str(course)]
    baseline=max(.015,venue["course_win_rate"][course-1])
    shrunk_win=(raw["wins"]+ALPHA_COURSE*baseline)/(raw["starts"]+ALPHA_COURSE)
    value+=.45*math.log(max(.001,shrunk_win)/baseline)
    # Recent form, unlike age or lifetime grade, benefits a genuine recent
    # improvement but is strongly shrunk when the racer has few starts.
    form=hist["recent_form"]
    newest=form["last_10"];longer=form["last_30"]
    if newest["starts"] and longer["starts"]:
        p10=newest["top3"]/newest["starts"]
        p30=longer["top3"]/longer["starts"]
        value+=.38*(p10-p30)*newest["starts"]/(newest["starts"]+12)
    # Source-framed historical displacement describes observed results. It
    # cannot establish that a particular rival CAUSED the displacement.
    t=hist["tendencies"]
    if course>row["lane"] and t["crossed_by_outer_frame"]:
        prior=venue["course_top3_rate"][course-1]
        resilience=(t["crossed_by_outer_frame_top3"]+10*prior)/(t["crossed_by_outer_frame"]+10)
        value+=.4*(resilience-prior)
    if course==1 and t["in1_starts"]>0:
        prior=max(.015,venue["course_win_rate"][0])
        defense=(t["in1_wins"]+12*prior)/(t["in1_starts"]+12)
        value+=.40*math.log(max(.001,defense)/prior)
        if model_mode in ("sashi","makuri"):
            total_losses=max(1,t["in1_starts"]-t["in1_wins"])
            observed=t["in1_losses_by_winner_method"].get(model_mode,0)/total_losses
            value-=.12*min(1,observed)
    if model_mode!="other":
        by_mode=hist["wins_by_actual_course_and_kimarite"][str(course)]
        old_wins=sum(by_mode.values())
        ref=max(.01,venue["winner_method_rates"][model_mode])
        shrunk=(by_mode.get(model_mode,0)+ALPHA_METHOD*ref)/(old_wins+ALPHA_METHOD)
        value+=.30*math.log(max(.001,shrunk)/ref)
    return math.exp(max(-20.,min(20.,value)))


def predict_tactical_shadow(source, histories, venue, generated_at, *,
                           max_ticket_count=8, preclose_odds=None):
    """Third C shadow, never silently substitute for A/B or promise man-shu.

    Source has exactly the A/B official confirmed active entrant data schema.
    Histories must be extracted from genuine prior results upstream; per-source
    receipt flags are claims and must be authenticated independently before
    this research output is eligible for a real prospective study.
    """
    _need(type(max_ticket_count) is int and 1<=max_ticket_count<=8,
          "bounded original Hit@8 ticket count required")
    boats=_valid(source,generated_at)
    verified=_profiles(histories,boats,generated_at)
    venue=_venue(venue,generated_at)
    _need(source["race_id"][9:11]==venue["venue_code"],
          "venue source and selected race identity mismatch")
    # All bijective active-entrant entry permutations are candidates. The official
    # preview parser currently does NOT verify a future actual course, so the
    # entrant's assigned course must remain an inferred scenario, not a fact.
    scenarios=[]
    for arrangement in itertools.permutations(range(1,len(boats)+1)):
        p=1.
        for row,course in zip(boats,arrangement):
            p*=_entry_probability(verified[row["racer_id"]],venue,row["lane"],course)
        if p>0:
            scenarios.append((arrangement,p))
    total_mass=math.fsum(p for _,p in scenarios)
    _need(total_mass>0,"no admissible entry configuration")
    scenarios=[(courses,p/total_mass) for courses,p in scenarios]
    all_tickets=list(itertools.permutations([row["lane"] for row in boats],3))
    distribution={ticket:0. for ticket in all_tickets}
    mode_mass={mode:venue["winner_method_rates"][mode] for mode in MODES}
    field={"mean_exhibition":math.fsum(x["exhibition_time_seconds"] for x in boats)/len(boats)}
    for courses,p_course in scenarios:
        for mode in MODES:
            method_weight=mode_mass[mode]*p_course
            if method_weight<=0: continue
            strengths={row["lane"]:_base_strength(row,verified[row["racer_id"]],venue,course,mode,field)
                       for row,course in zip(boats,courses)}
            total=math.fsum(strengths.values())
            for a,b,c in all_tickets:
                sa,sb,sc=strengths[a],strengths[b],strengths[c]
                distribution[(a,b,c)]+=method_weight*sa/total*sb/(total-sa)*sc/(total-sa-sb)
    total=math.fsum(distribution.values())
    _need(math.isclose(total,1.,rel_tol=0,abs_tol=1e-7),"scenario mixture probabilities not normalized")
    ranked=sorted(({"ticket":"-".join(map(str,t)),"score":p/total}
                   for t,p in distribution.items()),key=lambda x:(-x["score"],x["ticket"]))
    main=ranked[:max_ticket_count]
    # Without verified cutoff-available trifecta odds, no claim that a ticket
    # pays >=10,000 yen is possible. Preserve unrelated tail watch separately
    # from the core Hit@8 accuracy denominator.
    man_shu=[]
    if preclose_odds is not None:
        _need(isinstance(preclose_odds,dict) and set(preclose_odds)=={
              "captured_at","official_source_sha256","source_identity_verified","decimal_odds"},
              "strict preclose 120 odds snapshot required")
        _need(preclose_odds["source_identity_verified"] is True
              and _time_no_future(preclose_odds["captured_at"],generated_at)
              and isinstance(preclose_odds["official_source_sha256"],str)
              and HISTORY_SHA.fullmatch(preclose_odds["official_source_sha256"]),
              "odds source not independently available by forecast time")
        odds=preclose_odds["decimal_odds"]
        _need(isinstance(odds,dict) and set(odds)=={x["ticket"] for x in ranked}
              and all(_number(v,1,1_000_000) for v in odds.values()),
              "official complete 120 preclose prices required")
        # Man-shu means 3連単 >= 10,000 yen on a 100 yen ticket; odds >=100.
        man_shu=sorted(({"ticket":x["ticket"],"score_uncalibrated":x["score"],
                         "decimal_odds":odds[x["ticket"]],
                         "pseudo_value_not_calibrated":x["score"]*odds[x["ticket"]]}
                        for x in ranked if odds[x["ticket"]]>=100),
                       key=lambda x:(-x["pseudo_value_not_calibrated"],x["ticket"]))[:4]
    out={
        "schema":SCHEMA,"model_id":MODEL_ID,
        "race_id":source["race_id"],"cutoff_at":source["cutoff_at"],
        "generated_at":generated_at,
        "source_snapshot_sha256":_digest(source),
        "history_attested_by_model":False,
        "historical_sources_require_external_authentication":True,
        "venue_source_sha256":venue["official_source_sha256"],
        "prospective_entry_course_is_inferred_not_observed":True,
        "entry_scenario_count":len(scenarios),
        "top_entry_scenarios":[
             {"courses":list(courses),"mass":p}
             for courses,p in sorted(scenarios,key=lambda x:-x[1])[:MAX_SCENARIOS]
        ],
        "research_scenario_weights":dict(mode_mass),
        "racer_history_sample_sizes":[
            {"lane":row["lane"],"racer_id":row["racer_id"],
             "sample_races":verified[row["racer_id"]]["sample_races"],
             "recent_starts":verified[row["racer_id"]]["recent_form"]["last_10"]["starts"]}
            for row in boats],
        "full_120":ranked,"main_top8":main,
        "main_top8_mass_uncalibrated":math.fsum(x["score"] for x in main),
        "man_shu_watch":man_shu,
        "man_shu_priced":preclose_odds is not None,
        "wagering_enabled":False,"automatically_promoted":False,
        "validated_accuracy":False,
        "explanation":"Untrained historical entry-course/method scenario mixture; verified historical source/venue receipts must be checked by upstream adapter.",
    }
    out["bundle_sha256"]=_digest(out)
    return out
