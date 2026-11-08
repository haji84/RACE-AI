"""Owner-private, append-only ranking audit for frozen KEIRIN shadow predictions.

Research-only: scores are untrained and not calibrated win probabilities.
Never recalculate a prediction after the result, fetch providers, or place bets.
"""
from collections import Counter
from hashlib import sha256
import json

from .keirin_owner_sqlite import PrivateKeirinStore, _checked_clock
from .keirin_result_delivery import canonical, utc
from .keirin_shadow_variable_pair import (
    ShadowVariablePairLedger, checked_shadow, fingerprint, require
)

SCHEMA = "RACE_AI_KEIRIN_MANSHA_RANK_AUDIT_V1"
MANSHA_THRESHOLD_YEN_PER_100 = 10000
MODES = ("top8", "top12", "variable")


def rank_band(n):
    for bound, name in ((8, "01-08"), (12, "09-12"), (24, "13-24"),
                        (50, "25-50"), (100, "51-100")):
        if n <= bound:
            return name
    return "101+"


def evaluate(pair, result, revision, result_sha256):
    shadow = pair["shadow"]
    checked_shadow(shadow)
    ranks = shadow["ranked_candidates_untrained_not_probabilities"]
    require(len(ranks) == shadow["candidate_count"]
            and len(ranks) in (210, 504), "FULL_FROZEN_RANKING_REQUIRED")
    require(type(revision) is int and revision > 0
            and type(result_sha256) is str and len(result_sha256) == 64,
            "RESULT_REVISION_REQUIRED")
    require(result.get("race_id") == shadow["race_id"]
            and utc(result["observed_at"]) >= utc(shadow["declared_cutoff"]),
            "RESULT_PROVENANCE_OR_TIME_INVALID")
    require((utc(shadow["declared_cutoff"])
             - utc(pair["persisted_at"])).total_seconds() > 65,
            "PAIR_NOT_FROZEN_BEFORE_CUTOFF")
    index = {tuple(r["triple"]): i+1 for i, r in enumerate(ranks)}
    require(len(index) == len(ranks), "RANKING_DUPLICATED")
    if pair.get("odds") is None or pair.get("variable") is None:
        market_rank = {}
        selections = None  # Absent odds is NOT a pre-decided zero-pick skip.
    else:
        market = {tuple(x["triple"]): x["decimal_odds"]
                  for x in pair["odds"]["prices"]}
        require(len(market) == len(index) and set(market) == set(index),
                "UNFROZEN_MARKET_UNIVERSE")
        market_rank = {t: i+1 for i, t in enumerate(
            sorted(market, key=lambda t: (market[t], t)))}
        selections = [tuple(t["triple"]) for t in pair["variable"]["tickets"]]
        require(len(selections) <= 12 and len(set(selections)) == len(selections)
                and set(selections).issubset(index)
                and len(selections) == pair["variable"]["pick_count"]
                and all(t["reference_stake_yen"] == 100
                        for t in pair["variable"]["tickets"]),
                "UNTRUSTED_VARIABLE_SELECTION")
    settled = (result.get("status") == "FINAL_NORMAL"
               and result.get("refund_status") == "NONE")
    payouts = {}
    winners = []
    if settled:
        wins = result.get("winning_triples")
        payments = result.get("payouts_100yen")
        require(type(wins) is list and type(payments) is list
                and 0 < len(wins) == len(payments),
                "INVALID_FINAL_RESULT")
        for p in payments:
            require(type(p) is dict and set(p) == {"triple", "yen"}
                    and type(p["yen"]) is int and p["yen"] > 0,
                    "INVALID_FINAL_PAYOUT")
            t = tuple(p["triple"])
            require(t in index and t not in payouts,
                    "PAYOUT_DUPLICATE_OR_BAD_TRIPLE")
            payouts[t] = p["yen"]
        require({tuple(t) for t in wins} == set(payouts)
                and len(wins) == len(payouts), "PAYOUT_WINNER_MISMATCH")
        winners = [{
            "triple": list(t), "payout_yen_per_100": yen,
            "is_mansha": yen >= MANSHA_THRESHOLD_YEN_PER_100,
            "pre_cutoff_model_rank": index[t],
            "pre_cutoff_relative_score_uncalibrated": ranks[index[t]-1][
                "relative_score"],
            "pre_cutoff_odds_rank_not_final_market_popularity": market_rank.get(t),
            "rank_band": rank_band(index[t]),
        } for t, yen in sorted(payouts.items(), key=lambda r: index[r[0]])]
    mansha = {t for t, yen in payouts.items()
              if yen >= MANSHA_THRESHOLD_YEN_PER_100}

    def calculate(tickets):
        if tickets is None:
            return {"state": "NO_PRE_CUTOFF_ODDS", "picks": None,
                    "hit": None, "mansha_captured": None,
                    "investment_yen": None, "payout_yen": None,
                    "profit_yen": None, "roi": None}
        if not settled:
            return {"state": "UNSETTLED", "picks": len(tickets),
                    "hit": None, "mansha_captured": None,
                    "investment_yen": None, "payout_yen": None,
                    "profit_yen": None, "roi": None}
        if not tickets:
            return {"state": "SKIPPED", "picks": 0,
                    "hit": None, "mansha_captured": False,
                    "investment_yen": 0, "payout_yen": 0,
                    "profit_yen": 0, "roi": None}
        investment = 100*len(tickets)
        paid = sum(payouts.get(t, 0) for t in tickets)
        return {"state": "REFERENCE_PURCHASE", "picks": len(tickets),
                "hit": any(t in payouts for t in tickets),
                "mansha_captured": bool(set(tickets) & mansha),
                "investment_yen": investment, "payout_yen": paid,
                "profit_yen": paid-investment, "roi": paid/investment}

    report = {
        "schema": SCHEMA, "research_only": True,
        "race_id": shadow["race_id"],
        "model_id": shadow["model_id"],
        "model_version": shadow["model_version"],
        "source_input_sha256": shadow["input_sha256"],
        "source_input_persisted_privately": pair.get("input_snapshot_frozen", False),
        "pre_cutoff_forecast_sha256": shadow["research_sha256"],
        "generated_at": shadow["generated_at"],
        "local_db_persisted_at": pair["persisted_at"],
        "declared_cutoff_at": shadow["declared_cutoff"],
        "full_ranked_candidates": len(ranks),
        "uncalibrated_relative_score": True,
        "result_revision": revision, "result_sha256": result_sha256,
        "status": "SETTLED_RESEARCH" if settled else "UNSETTLED",
        "winners": winners,
        "mansha_winning_tickets": len(mansha) if settled else None,
        "modes": {
            "top8": calculate([tuple(r["triple"]) for r in ranks[:8]]),
            "top12": calculate([tuple(r["triple"]) for r in ranks[:12]]),
            "variable": calculate(selections)},
        "variable_skip_pre_decided": (not selections) if selections is not None else None,
        "independent_pre_cutoff_time_proven": False,
        "official_result_independently_authenticated": False,
        "formal_hit_rate": None, "formal_roi": None,
        "actual_purchases": None,
    }
    report["audit_sha256"] = fingerprint(report)
    return report


class KeirinManshaRankLedger:
    def __init__(self, store):
        require(isinstance(store, PrivateKeirinStore),
                "OWNER_PRIVATE_SQLITE_REQUIRED")
        self.store, self.db = store, store.db
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS keirin_mansha_rank_audits (
            race_id TEXT NOT NULL,
            model_id TEXT NOT NULL,
            model_version TEXT NOT NULL,
            revision INTEGER NOT NULL,
            forecast_sha256 TEXT NOT NULL,
            result_sha256 TEXT NOT NULL,
            audit_sha256 TEXT NOT NULL,
            payload BLOB NOT NULL,
            PRIMARY KEY (race_id,model_id,model_version,revision)
          );
        """)

    def audit_revision(self, race_id, revision=None):
        pair = ShadowVariablePairLedger(self.store).read_pair(race_id)
        if pair is None:
            return None
        if revision is None:
            row = self.db.execute(
                "SELECT revision,payload,payload_sha256 FROM result_revisions "
                "WHERE race_id=? ORDER BY revision DESC LIMIT 1",
                (race_id,)).fetchone()
        else:
            require(type(revision) is int and revision >= 1,
                    "INVALID_RESULT_REVISION")
            row = self.db.execute(
                "SELECT revision,payload,payload_sha256 FROM result_revisions "
                "WHERE race_id=? AND revision=?", (race_id,revision)).fetchone()
        if row is None:
            return None
        require(sha256(row["payload"]).hexdigest() == row["payload_sha256"],
                "RESULT_REVISION_HASH_MISMATCH")
        report = evaluate(pair, json.loads(row["payload"]),
                          row["revision"], row["payload_sha256"])
        self.db.execute("BEGIN IMMEDIATE")
        try:
            previous = self.db.execute(
                "SELECT payload FROM keirin_mansha_rank_audits "
                "WHERE race_id=? AND model_id=? AND model_version=? "
                "AND revision=?", (race_id,report["model_id"],
                                   report["model_version"],
                                   row["revision"])).fetchone()
            if previous is None:
                self.db.execute(
                    "INSERT INTO keirin_mansha_rank_audits VALUES "
                    "(?,?,?,?,?,?,?,?)",
                    (race_id,report["model_id"],report["model_version"],
                     row["revision"],report["pre_cutoff_forecast_sha256"],
                     row["payload_sha256"],report["audit_sha256"],
                     canonical(report)))
            else:
                require(previous["payload"] == canonical(report),
                        "IMMUTABLE_RANK_REVISION_CONFLICT")
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return report

    def replay_all(self, *, max_pairs=2000, max_revisions=50000):
        require(type(max_pairs) is int and 1 <= max_pairs <= 2000
                and type(max_revisions) is int and 1 <= max_revisions <= 50000,
                "RANK_REPLAY_BOUNDS")
        races = self.db.execute(
            "SELECT race_id FROM keirin_shadow_variable_pairs "
            "ORDER BY race_id LIMIT ?", (max_pairs+1,)).fetchall()
        require(len(races) <= max_pairs, "RANK_RACE_LIMIT")
        latest = []
        revised = missing = 0
        for r in races:
            versions = self.db.execute(
                "SELECT revision FROM result_revisions WHERE race_id=? "
                "ORDER BY revision", (r["race_id"],)).fetchall()
            if not versions:
                missing += 1
                continue
            for v in versions:
                require(revised < max_revisions, "RANK_REVISIONS_LIMIT")
                report = self.audit_revision(r["race_id"],v["revision"])
                revised += 1
            latest.append(report)
        settled = [r for r in latest if r["status"] == "SETTLED_RESEARCH"]
        manshas = [r for r in settled if r["mansha_winning_tickets"] > 0]
        bands = Counter(w["rank_band"] for r in manshas
                        for w in r["winners"] if w["is_mansha"])
        modes = {}
        for mode in MODES:
            used = [r["modes"][mode] for r in settled
                    if r["modes"][mode]["state"] == "REFERENCE_PURCHASE"]
            spent = sum(t["investment_yen"] for t in used)
            paid = sum(t["payout_yen"] for t in used)
            caught = sum(r["modes"][mode]["mansha_captured"] for r in manshas)
            hits = sum(t["hit"] is True for t in used)
            modes[mode] = {
                "active_races": len(used),
                "skipped_races": sum(r["modes"][mode]["state"] == "SKIPPED"
                                     for r in settled),
                "hits": hits,
                "hit_rate_on_active_races": hits/len(used) if used else None,
                "mansha_races_captured": caught,
                "mansha_capture_rate_on_mansha_races":
                    caught/len(manshas) if manshas else None,
                "reference_investment_yen": spent,
                "reference_payout_yen": paid,
                "reference_profit_yen": paid-spent,
                "reference_roi": paid/spent if spent else None,
            }
        return {
            "schema": "RACE_AI_KEIRIN_MANSHA_RANK_SUMMARY_V1",
            "paired_forecast_races": len(races),
            "without_result": missing,
            "result_revisions_replayed": revised,
            "latest_settled_races": len(settled),
            "mansha_races": len(manshas),
            "mansha_winning_tickets": sum(
                r["mansha_winning_tickets"] for r in manshas),
            "mansha_rank_bands": dict(sorted(bands.items())),
            "models_in_scope": sorted({r["model_id"] for r in latest}),
            "modes": modes,
            "full_national_race_coverage_verified": False,
            "independent_time_receipt_verified": False,
            "official_results_authentication_complete": False,
            "formal_hit_rate": None, "formal_roi": None,
        }
