"""Owner-private prospective PR101 sparse 8 vs PR103 variable 0..12 trial.

Both are frozen on ONE source-grounded, future race. Pre-race odds are a
separate authenticated-by-owner input; no provider network or bet placement.
The shadow score is an UNTRAINED relative ranking, NEVER a calibrated win
probability or proven expected return. No fake PR71 features are introduced.
"""
from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
from itertools import permutations
import json
import math
import sqlite3

from .keirin_owner_sqlite import PrivateKeirinStore, _checked_clock
from .keirin_result_delivery import canonical, utc
from .keirin_real_rider_shadow import SCHEMA as SHADOW_SCHEMA, MODEL as SHADOW_MODEL
from .keirin_variable_selection import ODDS_SCHEMA

SELECTION_SCHEMA = "RACE_AI_KEIRIN_SHADOW_VARIABLE_RESEARCH_SELECTION_V1"
AUDIT_SCHEMA = "RACE_AI_KEIRIN_SHADOW_VARIABLE_RESEARCH_COMPARISON_V1"
MIN_MARGIN_SECONDS = 65


class ShadowPairError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise ShadowPairError(code)


def fingerprint(document):
    return sha256(canonical(document)).hexdigest()


def checked_shadow(shadow):
    require(type(shadow) is dict and shadow.get("schema")==SHADOW_SCHEMA
            and shadow.get("model_id")==SHADOW_MODEL
            and shadow.get("official_prediction") is False
            and shadow.get("probabilities_calibrated") is False
            and shadow.get("full_pr71_model_ran") is False
            and shadow.get("independent_pre_cutoff_timestamp_verified") is False,
            "SOURCE_GROUNDED_UNCALIBRATED_SHADOW_REQUIRED")
    seal=shadow.get("research_sha256")
    require(type(seal) is str and len(seal)==64
            and fingerprint({k:v for k,v in shadow.items()
                             if k!="research_sha256"})==seal,
            "SHADOW_ORIGINAL_HASH_MISMATCH")
    rows=shadow.get("ranked_candidates_untrained_not_probabilities")
    starters=shadow.get("starters")
    require(type(starters) is list and len(starters) in (7,9)
            and len(set(starters))==len(starters)
            and all(type(x) is int and 1<=x<=9 for x in starters),
            "INVALID_SHADOW_STARTERS")
    universe=set(permutations(starters,3))
    require(type(rows) is list and len(rows)==len(universe)
            and shadow.get("candidate_count")==len(universe),
            "COMPLETE_PROSPECTIVE_SCORE_UNIVERSE_REQUIRED")
    scores={}
    prior=None
    for row in rows:
        require(type(row) is dict and set(row)=={"triple","relative_score"},
                "INVALID_SHADOW_SCORE_ROW")
        ticket=row["triple"]
        require(type(ticket) is list and len(ticket)==3
                and all(type(n) is int for n in ticket),
                "INVALID_SHADOW_TRIPLE")
        t=tuple(ticket)
        require(t in universe and t not in scores,"DUPLICATE_OR_INVALID_SHADOW_TRIPLE")
        score=row["relative_score"]
        require(type(score) in (float,int) and math.isfinite(score)
                and score>=0, "INVALID_RELATIVE_SCORE")
        require(prior is None or score<=prior+1e-15,
                "SHADOW_SCORE_ORDER_CHANGED")
        scores[t]=float(score)
        prior=float(score)
    require(set(scores)==universe
            and math.isclose(math.fsum(scores.values()),1.0,
                             rel_tol=0,abs_tol=1e-8)
            and shadow.get("ordered_top8")==
                [row["triple"] for row in rows[:8]],
            "SHADOW_SCORE_MASS_OR_TOP8_CHANGED")
    return scores


def checked_selection(selection):
    require(type(selection) is dict
            and selection.get("schema")==SELECTION_SCHEMA
            and selection.get("research_only") is True
            and selection.get("market_probabilities_used_as_model") is False
            and selection.get("calibrated_probabilities") is False
            and selection.get("betting_action")=="NONE",
            "INVALID_UNVERIFIED_VARIABLE_SELECTION")
    h=selection.get("selection_sha256")
    require(type(h) is str and fingerprint({
        k:v for k,v in selection.items() if k!="selection_sha256"
    })==h, "VARIABLE_SELECTION_HASH_MISMATCH")
    return selection


def choose_shadow_variable(shadow, odds, *, decided_at, odds_allowed):
    """Rank research-only hypothetical gross return proxies, not true EV."""
    scores=checked_shadow(shadow)
    require(callable(odds_allowed),"SOURCE_ADMISSION_REQUIRED")
    require(type(odds) is dict and set(odds)=={
        "schema","race_id","captured_at","source_ref","source_rights_ref","prices"
    } and odds["schema"]==ODDS_SCHEMA and odds["race_id"]==shadow["race_id"],
    "ODDS_SNAPSHOT_RACE_OR_SCHEMA_MISMATCH")
    require(odds_allowed(odds["source_ref"],odds["source_rights_ref"],
                         "analysis") is True,"ODDS_SOURCE_NOT_ADMITTED")
    now=utc(decided_at)
    generated=utc(shadow["generated_at"])
    captured=utc(odds["captured_at"])
    cutoff=utc(shadow["declared_cutoff"])
    require(generated<=now and captured<=now and
            (cutoff-now).total_seconds()>MIN_MARGIN_SECONDS,
            "OUTSIDE_PROSPECTIVE_SELECTION_WINDOW")
    prices=odds["prices"]
    require(type(prices) is list and len(prices)==len(scores),
            "FULL_TRIFECTA_ODDS_REQUIRED")
    observed={}
    for item in prices:
        require(type(item) is dict and set(item)=={"triple","decimal_odds"}
                and type(item["triple"]) is list
                and len(item["triple"])==3 and
                all(type(x) is int for x in item["triple"]),
                "INVALID_ODDS_TICKET")
        ticket=tuple(item["triple"])
        require(ticket in scores and ticket not in observed,
                "ODDS_DUPLICATE_OR_UNKNOWN_TRIPLE")
        price=item["decimal_odds"]
        require(type(price) in (int,float) and math.isfinite(price)
                and 1.0<price<=1_000_000,"INVALID_ODDS_NUMBER")
        observed[ticket]=float(price)
    require(set(scores)==set(observed),"ODDS_UNIVERSE_INCOMPLETE")
    effective=1/math.fsum(p*p for p in scores.values())
    cap=12 if effective>25 else 8
    ranked=sorted((
        (scores[t]*price-1.0,scores[t],t,price)
        for t,price in observed.items()
        if scores[t]*price>1.0+1e-10
    ),key=lambda x:(-x[0],-x[1],x[2]))
    chosen=ranked[:cap]
    rows=[{"triple":list(t),"reference_stake_yen":100,
           "uncalibrated_relative_score":s,
           "pre_cutoff_decimal_odds":price,
           "hypothetical_score_times_odds":s*price}
          for edge,s,t,price in chosen]
    selection={
        "schema":SELECTION_SCHEMA,
        "race_id":shadow["race_id"],
        "model_id":shadow["model_id"],
        "model_version":shadow["model_version"],
        "original_shadow_sha256":shadow["research_sha256"],
        "source_packet_sha256":shadow["input_sha256"],
        "odds_sha256":fingerprint(odds),
        "odds_captured_at":odds["captured_at"],
        "selected_at":decided_at,
        "official_cutoff_at":shadow["declared_cutoff"],
        "candidate_count":len(scores),
        "selection_rule":"UNCALIBRATED_SCORE_X_ODDS_POSITIVE_PROXY_V1",
        "wide_scenario_proxy_effective_outcomes":effective,
        "limit":cap,
        "pick_count":len(rows),
        "tickets":rows,
        "reference_investment_yen":len(rows)*100,
        "state":"RESEARCH_ONLY" if rows else "SKIP_NO_POSITIVE_PROXY",
        "research_only":True,
        "market_probabilities_used_as_model":False,
        "calibrated_probabilities":False,
        "actual_expected_value_calculated":False,
        "independent_forecast_timestamp_verified":False,
        "official_result_authenticated":False,
        "betting_action":"NONE",
    }
    selection["selection_sha256"]=fingerprint(selection)
    return selection


class ShadowVariablePairLedger:
    """Write the two prospective versions together into existing private DB."""

    def __init__(self,store):
        require(isinstance(store,PrivateKeirinStore),
                "OWNER_PRIVATE_SQLITE_REQUIRED")
        self.store=store
        self.db=store.db
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS keirin_shadow_variable_pairs (
            race_id TEXT PRIMARY KEY,
            shadow_sha256 TEXT NOT NULL,
            variable_sha256 TEXT NOT NULL,
            odds_sha256 TEXT NOT NULL,
            shadow_payload BLOB NOT NULL,
            variable_payload BLOB NOT NULL,
            odds_payload BLOB NOT NULL,
            persisted_at TEXT NOT NULL
          );
          CREATE TABLE IF NOT EXISTS keirin_shadow_variable_audits (
            race_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            result_payload_sha256 TEXT NOT NULL,
            audit_sha256 TEXT NOT NULL,
            payload BLOB NOT NULL,
            PRIMARY KEY(race_id,revision)
          );
        """)

    def read_pair(self,race_id):
        row=self.db.execute(
            "SELECT * FROM keirin_shadow_variable_pairs WHERE race_id=?",
            (race_id,)).fetchone()
        if not row:
            return None
        shadow=json.loads(row["shadow_payload"])
        selection=json.loads(row["variable_payload"])
        odds=json.loads(row["odds_payload"])
        checked_shadow(shadow)
        checked_selection(selection)
        require(row["shadow_sha256"]==shadow["research_sha256"]
                and row["variable_sha256"]==selection["selection_sha256"]
                and row["odds_sha256"]==fingerprint(odds)
                and selection["original_shadow_sha256"]==
                    shadow["research_sha256"]
                and selection["odds_sha256"]==fingerprint(odds),
                "PRIVATE_PAIR_READBACK_HASH_MISMATCH")
        return {"shadow":shadow,"variable":selection,"odds":odds,
                "persisted_at":row["persisted_at"]}

    def freeze_pair_once(self, shadow, variable, odds):
        checked_shadow(shadow)
        checked_selection(variable)
        require(shadow["race_id"]==variable["race_id"]==odds["race_id"]
                and shadow["research_sha256"]==
                   variable["original_shadow_sha256"]
                and shadow["input_sha256"]==
                    variable["source_packet_sha256"]
                and fingerprint(odds)==variable["odds_sha256"],
                "SHADOW_VARIABLE_SOURCE_PROVENANCE_MISMATCH")
        at=_checked_clock(self.store.clock)
        require(utc(shadow["generated_at"])<=utc(variable["selected_at"])<=at
                and (utc(shadow["declared_cutoff"])-at).total_seconds()>
                    MIN_MARGIN_SECONDS,
                "PAIR_NOT_FROZEN_BEFORE_CUTOFF")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            previous=self.db.execute(
                "SELECT shadow_sha256,variable_sha256,odds_sha256 "
                "FROM keirin_shadow_variable_pairs WHERE race_id=?",
                (shadow["race_id"],)).fetchone()
            if previous is not None:
                require(previous["shadow_sha256"]==shadow["research_sha256"]
                        and previous["variable_sha256"]==
                            variable["selection_sha256"]
                        and previous["odds_sha256"]==fingerprint(odds),
                        "IMMUTABLE_PAIR_CONFLICT")
                self.db.execute("COMMIT")
                require(self.read_pair(shadow["race_id"])["variable"]==variable,
                        "EXISTING_PAIR_READBACK_MISMATCH")
                return "ALREADY_FROZEN_IDENTICAL"
            at=_checked_clock(self.store.clock)
            require((utc(shadow["declared_cutoff"])-at).total_seconds()>
                    MIN_MARGIN_SECONDS,
                    "PAIR_CUTOFF_DURING_TRANSACTION")
            self.db.execute(
                "INSERT INTO keirin_shadow_variable_pairs VALUES "
                "(?,?,?,?,?,?,?,?)",
                (shadow["race_id"],shadow["research_sha256"],
                 variable["selection_sha256"],fingerprint(odds),
                 canonical(shadow),canonical(variable),canonical(odds),
                 at.isoformat()))
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        require(self.read_pair(shadow["race_id"])["variable"]==variable,
                "PAIR_READBACK_FAILED")
        return "CREATED_PAIR_ONCE"

    def audit_revision(self,race_id,revision=None):
        pair=self.read_pair(race_id)
        if pair is None:
            return None
        if revision is None:
            row=self.db.execute(
                "SELECT revision,payload,payload_sha256 FROM result_revisions "
                "WHERE race_id=? ORDER BY revision DESC LIMIT 1",
                (race_id,)).fetchone()
        else:
            require(type(revision) is int and revision>=1,
                    "INVALID_RESULT_REVISION")
            row=self.db.execute(
                "SELECT revision,payload,payload_sha256 FROM result_revisions "
                "WHERE race_id=? AND revision=?", (race_id,revision)).fetchone()
        if row is None:
            return None
        require(sha256(row["payload"]).hexdigest()==row["payload_sha256"],
                "RESULT_SOURCE_REVISION_HASH_MISMATCH")
        result=json.loads(row["payload"])
        require(result.get("race_id")==race_id and
                utc(result["observed_at"])>=
                    utc(pair["shadow"]["declared_cutoff"]),
                "RESULT_RACE_OR_CUTOFF_MISMATCH")
        status="PENDING_OR_REFUND"
        investA=800
        investB=pair["variable"]["reference_investment_yen"]
        hitA=hitB=payoutA=payoutB=profitA=profitB=roiA=roiB=None
        if result.get("status")=="FINAL_NORMAL" and (
                result.get("refund_status")=="NONE"):
            wins=result.get("winning_triples")
            payouts=result.get("payouts_100yen")
            require(type(wins) is list and type(payouts) is list
                    and len(wins)>0 and len(wins)==len(payouts),
                    "INVALID_SETTLED_PAYOUT")
            winset={tuple(t) for t in wins}
            pays={}
            for r in payouts:
                require(type(r) is dict and set(r)=={"triple","yen"}
                        and type(r["yen"]) is int and r["yen"]>0,
                        "INVALID_SETTLED_PAYOUT")
                key=tuple(r["triple"])
                require(key not in pays,"DUPLICATE_SETTLED_PAYOUT")
                pays[key]=r["yen"]
            require(set(pays)==winset,"RESULT_PAYOUT_MISMATCH")
            a={tuple(t) for t in pair["shadow"]["ordered_top8"]}
            b={tuple(t["triple"]) for t in pair["variable"]["tickets"]}
            hitA=bool(a&winset)
            payoutA=sum(pays.get(t,0) for t in a)
            profitA=payoutA-investA
            roiA=payoutA/investA
            status="SETTLED_RESEARCH"
            if b:
                hitB=bool(b&winset)
                payoutB=sum(pays.get(t,0) for t in b)
                profitB=payoutB-investB
                roiB=payoutB/investB
            else:
                status="SETTLED_VARIABLE_SKIPPED"
        audit={
            "schema":AUDIT_SCHEMA,
            "race_id":race_id,
            "result_revision":row["revision"],
            "result_sha256":row["payload_sha256"],
            "original_sha256":pair["shadow"]["research_sha256"],
            "variable_sha256":pair["variable"]["selection_sha256"],
            "status":status,
            "fixed8_hit":hitA,
            "fixed8_investment_yen":investA,
            "fixed8_payout_yen":payoutA,
            "fixed8_profit_yen":profitA,
            "fixed8_roi":roiA,
            "variable_hit":hitB,
            "variable_investment_yen":investB,
            "variable_payout_yen":payoutB,
            "variable_profit_yen":profitB,
            "variable_roi":roiB,
            "original_predictions_unchanged":True,
            "independently_authenticated_pre_cutoff":False,
            "result_officially_authenticated":False,
            "formal_hit_rate":None,
            "real_purchases_yen":None,
        }
        audit["audit_sha256"]=fingerprint(audit)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            previous=self.db.execute(
                "SELECT payload FROM keirin_shadow_variable_audits "
                "WHERE race_id=? AND revision=?",
                (race_id,row["revision"])).fetchone()
            if previous is None:
                self.db.execute(
                    "INSERT INTO keirin_shadow_variable_audits VALUES "
                    "(?,?,?,?,?)",
                    (race_id,row["revision"],row["payload_sha256"],
                     audit["audit_sha256"],canonical(audit)))
            else:
                require(previous["payload"]==canonical(audit),
                        "IMMUTABLE_RESEARCH_RESULT_REVISION_CONFLICT")
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return audit

    def replay_all(self, *, max_pairs=2000, max_revisions=50000):
        """Replay all stored revisions, count missing, never backfill old picks."""
        require(type(max_pairs) is int and 1<=max_pairs<=2000
                and type(max_revisions) is int and 1<=max_revisions<=50000,
                "UNSAFE_REPLAY_BOUNDS")
        races=self.db.execute(
            "SELECT race_id FROM keirin_shadow_variable_pairs "
            "ORDER BY race_id LIMIT ?",(max_pairs+1,)).fetchall()
        require(len(races)<=max_pairs,"PAIR_REPLAY_LIMIT")
        revisions_run=0
        without_results=0
        for item in races:
            revisions=self.db.execute(
                "SELECT revision FROM result_revisions WHERE race_id=? "
                "ORDER BY revision",(item["race_id"],)).fetchall()
            if not revisions:
                without_results+=1
            for r in revisions:
                require(revisions_run<max_revisions,"REVISION_REPLAY_LIMIT")
                self.audit_revision(item["race_id"],r["revision"])
                revisions_run+=1
        recent=self.db.execute(
            "SELECT a.payload FROM keirin_shadow_variable_audits a "
            "JOIN (SELECT race_id,MAX(revision) AS revision "
            "FROM result_revisions GROUP BY race_id) x "
            "ON a.race_id=x.race_id AND a.revision=x.revision").fetchall()
        summaries=[json.loads(r["payload"]) for r in recent]
        settled=[x for x in summaries
                 if x["status"] in ("SETTLED_RESEARCH",
                                    "SETTLED_VARIABLE_SKIPPED")]
        a_invest=sum(x["fixed8_investment_yen"] for x in settled)
        b_invest=sum(x["variable_investment_yen"] for x in settled)
        a_paid=sum(x["fixed8_payout_yen"] for x in settled)
        b_paid=sum(x["variable_payout_yen"] or 0 for x in settled)
        b_active=[x for x in settled if x["variable_investment_yen"]>0]
        result={
            "schema":"RACE_AI_KEIRIN_SHADOW_VARIABLE_PAIR_REPLAY_V1",
            "saved_dual_forecast_races":len(races),
            "without_any_result":without_results,
            "replayed_result_revisions":revisions_run,
            "settled_compared_races":len(settled),
            "fixed8_reference_hit_rate":
                sum(x["fixed8_hit"] is True for x in settled)/len(settled)
                if settled else None,
            "variable_reference_hit_rate":
                sum(x["variable_hit"] is True for x in b_active)/len(b_active)
                if b_active else None,
            "fixed8_investment_yen":a_invest,
            "fixed8_payout_yen":a_paid,
            "fixed8_profit_yen":a_paid-a_invest,
            "fixed8_roi":a_paid/a_invest if a_invest else None,
            "variable_investment_yen":b_invest,
            "variable_payout_yen":b_paid,
            "variable_profit_yen":b_paid-b_invest,
            "variable_roi":b_paid/b_invest if b_invest else None,
            "full_official_source_coverage_verified":False,
            "independent_pre_cutoff_time_verified":False,
            "model_probabilities_calibrated":False,
            "formal_roi":None,
            "actual_purchases":None,
        }
        return result
