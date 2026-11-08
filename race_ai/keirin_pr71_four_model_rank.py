"""Owner-private freeze and result audit for the EXISTING four PR71 KEIRIN models.

No new predictor. The pinned PR71 suite must pass the existing full pre-race
source, rights, 347-factor and deadline gate. Frozen model scores are untrained
and uncalibrated. No provider HTTP, external witness, logs of owner data, or bet.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
from itertools import permutations
import json
import math
from pathlib import Path

from .comprehensive_four_sport_models import digest as model_digest
from .four_sport_model_suite import ALL_MODELS, run_suite, verify_suite
from .keirin_owner_sqlite import PrivateKeirinStore, _checked_clock
from .keirin_pr71_model_adapter import run_pr71_for_next_race
from .keirin_result_delivery import canonical, utc
from .keirin_variable_integration import PrivateVariableLedger

SCHEMA = "RACE_AI_KEIRIN_PR71_FOUR_MODEL_RANK_AUDIT_V1"
SUMMARY = "RACE_AI_KEIRIN_PR71_FOUR_MODEL_RANK_SUMMARY_V1"
MIN_CUTOFF_MARGIN_SECONDS = 65
MANSHA_YEN_PER_100 = 10000


class FourModelRankError(ValueError):
    pass


def need(ok, code):
    if not ok:
        raise FourModelRankError(code)


def _hash_bytes(value):
    return sha256(value).hexdigest()


def _checked_candidates(model, starters):
    expected = set(permutations(starters, 3))
    rows = model.get("candidates")
    need(type(rows) is list and len(rows) == len(expected) and
         model.get("candidate_count") == len(expected),
         "PR71_FULL_210_OR_504_CANDIDATES_REQUIRED")
    seen = set()
    previous = float("inf")
    scores = []
    for item in rows:
        need(type(item) is dict and set(item) == {"combination", "score"},
             "BAD_CANDIDATE_RECORD")
        t = item["combination"]
        need(type(t) is list and len(t) == 3 and
             all(type(n) is int for n in t), "INVALID_CANDIDATE_TRIPLE")
        key = tuple(t)
        v = item["score"]
        need(key in expected and key not in seen and
             type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 and
             v <= previous + 1e-14, "RANK_UNIVERSE_OR_SORT_TAMPER")
        scores.append(float(v))
        seen.add(key)
        previous = v
    need(seen == expected and math.isclose(
        math.fsum(scores), 1.0, rel_tol=0, abs_tol=1e-8),
        "PR71_SCORE_MASS_INVALID")
    need(model["ordered_top8"] == [r["combination"] for r in rows[:8]],
         "PR71_TOP8_RANK_DISAGREEMENT")
    return rows


def checked_four_model_suite(snapshot, suite):
    need(verify_suite(suite) is True and
         tuple(suite["models"]) == ALL_MODELS and len(ALL_MODELS) == 4 and
         suite["sport"] == "keirin" and
         suite["race_id"] == snapshot["race_id"] and
         suite["sales_cutoff_at"] == snapshot["official_cutoff_at"] and
         suite["as_of"] == snapshot["as_of"] and
         suite["input_sha256"] == model_digest(
             snapshot["facts"]["pr71_evidenced_snapshot"]) and
         suite["official_prediction"] is False,
         "PR71_UNVERIFIED_FOUR_MODEL_SUITE")
    starters = sorted(snapshot["starters"])
    need(len(starters) in (7, 9) and
         len(set(starters)) == len(starters),
         "PR71_SEVEN_OR_NINE_RIDERS_REQUIRED")
    for model_id in ALL_MODELS:
        model = suite["models"][model_id]
        need(model.get("model_id") == model_id and
             model.get("model_version") == "0.1.0-UNTRAINED" and
             model.get("trained") is False and
             model.get("calibrated") is False and
             model.get("odds_independent") is True and
             model.get("official_prediction") is False and
             model.get("snapshot_sha256") == suite["input_sha256"] and
             model.get("prediction_sha256") == model_digest({
                 k: v for k, v in model.items()
                 if k != "prediction_sha256"}),
             "PR71_MODEL_IDENTITY_OR_HASH_INVALID")
        _checked_candidates(model, starters)


def _payout_modes(model, payouts, variable_tickets, *, settled):
    def mode(tickets):
        if not settled:
            return {"state": "UNSETTLED", "picks": len(tickets)
                    if tickets is not None else None,
                    "hit": None, "mansha_captured": None,
                    "investment_yen": None, "payout_yen": None,
                    "profit_yen": None, "roi": None}
        if tickets is None:
            return {"state": "NO_PRE_CUTOFF_VARIABLE_SELECTION",
                    "picks": None, "hit": None, "mansha_captured": None,
                    "investment_yen": None, "payout_yen": None,
                    "profit_yen": None, "roi": None}
        if not tickets:
            return {"state": "PRE_DECIDED_SKIP", "picks": 0,
                    "hit": None, "mansha_captured": False,
                    "investment_yen": 0, "payout_yen": 0,
                    "profit_yen": 0, "roi": None}
        spent = 100 * len(tickets)
        paid = sum(payouts.get(t, 0) for t in tickets)
        big = {t for t, yen in payouts.items()
               if yen >= MANSHA_YEN_PER_100}
        return {"state": "REFERENCE_PURCHASE", "picks": len(tickets),
                "hit": any(t in payouts for t in tickets),
                "mansha_captured": bool(big & set(tickets)),
                "investment_yen": spent, "payout_yen": paid,
                "profit_yen": paid-spent, "roi": paid/spent}
    rows = model["candidates"]
    return {"top8": mode([tuple(r["combination"]) for r in rows[:8]]),
            "top12": mode([tuple(r["combination"]) for r in rows[:12]]),
            "variable": mode(variable_tickets)}


class FourModelRankLedger:
    def __init__(self, store):
        need(isinstance(store, PrivateKeirinStore),
             "OWNER_PRIVATE_STORE_REQUIRED")
        self.store, self.db = store, store.db
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS keirin_pr71_four_model_suites (
            race_id TEXT PRIMARY KEY,
            source_sha256 TEXT NOT NULL,
            suite_sha256 TEXT NOT NULL,
            suite_body_sha256 TEXT NOT NULL,
            source_payload BLOB NOT NULL,
            suite_payload BLOB NOT NULL,
            persisted_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS keirin_pr71_four_model_rank_audits (
            race_id TEXT NOT NULL,
            model_id TEXT NOT NULL,
            model_version TEXT NOT NULL,
            revision INTEGER NOT NULL,
            model_prediction_sha256 TEXT NOT NULL,
            result_sha256 TEXT NOT NULL,
            audit_sha256 TEXT NOT NULL,
            payload BLOB NOT NULL,
            PRIMARY KEY (race_id,model_id,model_version,revision)
        );
        """)

    def freeze_once(self, private_snapshot, *, source_admission=None):
        """Strictly prospective: full PR71 adapter gate BEFORE all four freeze."""
        at = _checked_clock(self.store.clock)
        need(type(private_snapshot) is dict and
             type(private_snapshot.get("official_cutoff_at")) is str and
             (utc(private_snapshot["official_cutoff_at"])-at).total_seconds() >
                MIN_CUTOFF_MARGIN_SECONDS,
             "PR71_FOUR_MODEL_NOT_BEFORE_CUTOFF")
        baseline = run_pr71_for_next_race(
            private_snapshot, run_suite=run_suite, verify_suite=verify_suite,
            source_admission=source_admission,
            model_id="multisport-scenario-ensemble-v1",
            issued_at=at.isoformat())
        evidence = private_snapshot["facts"]["pr71_evidenced_snapshot"]
        suite = run_suite(evidence, allow_source=source_admission)
        checked_four_model_suite(private_snapshot, suite)
        need(suite["models"]["multisport-scenario-ensemble-v1"][
                 "ordered_top8"] == baseline["top8"],
             "PR71_BASELINE_TOP8_MISMATCH")
        source_data = canonical(private_snapshot)
        # Retain the model roster order. verify_suite checks that order,
        # whereas canonical(sorted-keys) would alphabetize the model dict.
        suite_data = json.dumps(suite, ensure_ascii=False, allow_nan=False,
                                separators=(",", ":")).encode("utf-8")
        source_sha = _hash_bytes(source_data)
        suite_body_sha = _hash_bytes(suite_data)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            clock = _checked_clock(self.store.clock)
            need((utc(private_snapshot["official_cutoff_at"])-clock
                  ).total_seconds() > MIN_CUTOFF_MARGIN_SECONDS,
                 "PR71_FOUR_MODEL_WRITE_CUTOFF_EXPIRED")
            prior = self.db.execute(
                "SELECT source_sha256,suite_sha256,suite_body_sha256 "
                "FROM keirin_pr71_four_model_suites WHERE race_id=?",
                (private_snapshot["race_id"],)).fetchone()
            if prior is None:
                self.db.execute(
                    "INSERT INTO keirin_pr71_four_model_suites VALUES "
                    "(?,?,?,?,?,?,?)",
                    (private_snapshot["race_id"], source_sha,
                     suite["suite_sha256"], suite_body_sha,
                     source_data, suite_data, clock.isoformat()))
                state = "FOUR_MODELS_FROZEN_ONCE"
            else:
                need(prior["source_sha256"] == source_sha and
                     prior["suite_sha256"] == suite["suite_sha256"] and
                     prior["suite_body_sha256"] == suite_body_sha,
                     "PR71_ORIGINAL_ALREADY_DIFFERENT")
                state = "FOUR_MODELS_ALREADY_FROZEN_IDENTICAL"
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        verified = self.read_suite(private_snapshot["race_id"])
        need(verified is not None and
             verified["source_sha256"] == source_sha and
             verified["suite"]["suite_sha256"] == suite["suite_sha256"],
             "PR71_PRIVATE_INDEPENDENT_READBACK_MISMATCH")
        return state

    def read_suite(self, race_id):
        row = self.db.execute(
            "SELECT * FROM keirin_pr71_four_model_suites WHERE race_id=?",
            (race_id,)).fetchone()
        if row is None:
            return None
        need(_hash_bytes(row["source_payload"]) == row["source_sha256"] and
             _hash_bytes(row["suite_payload"]) == row["suite_body_sha256"],
             "PR71_PRIVATE_SOURCE_OR_MODEL_TAMPER")
        source = json.loads(row["source_payload"])
        suite = json.loads(row["suite_payload"])
        checked_four_model_suite(source, suite)
        need(suite["suite_sha256"] == row["suite_sha256"] and
             source["race_id"] == race_id,
             "PR71_PRIVATE_HASH_OR_ID_TAMPER")
        return {"source": source, "suite": suite,
                "source_sha256": row["source_sha256"],
                "persisted_at": row["persisted_at"]}

    def audit_revision(self, race_id, revision=None):
        saved = self.read_suite(race_id)
        if saved is None:
            return None
        if revision is None:
            row = self.db.execute(
                "SELECT * FROM result_revisions WHERE race_id=? "
                "ORDER BY revision DESC LIMIT 1", (race_id,)).fetchone()
        else:
            need(type(revision) is int and revision >= 1,
                 "INVALID_RESULT_REVISION")
            row = self.db.execute(
                "SELECT * FROM result_revisions WHERE race_id=? "
                "AND revision=?", (race_id,revision)).fetchone()
        if row is None:
            return None
        need(_hash_bytes(row["payload"]) == row["payload_sha256"],
             "PR71_RESULT_REVISION_HASH_CHANGED")
        event = json.loads(row["payload"])
        suite = saved["suite"]
        need(event.get("race_id") == race_id and
             utc(event["observed_at"]) >= utc(suite["sales_cutoff_at"]) and
             (utc(suite["sales_cutoff_at"])-utc(saved["persisted_at"])
              ).total_seconds() > MIN_CUTOFF_MARGIN_SECONDS,
             "PR71_RESULT_TIME_OR_FORECAST_TIME_INVALID")
        settled = (event.get("status") == "FINAL_NORMAL" and
                   event.get("refund_status") == "NONE")
        payments = {}
        if settled:
            wins = event.get("winning_triples")
            rows = event.get("payouts_100yen")
            need(type(wins) is list and type(rows) is list and
                 len(wins) == len(rows) and bool(wins),
                 "BAD_FINAL_TRIFECTA_RESULT")
            for p in rows:
                need(type(p) is dict and set(p) == {"triple","yen"} and
                     type(p["yen"]) is int and p["yen"] > 0,
                     "INVALID_RESULT_PAYOUT")
                t = tuple(p["triple"])
                need(t not in payments, "DUPLICATE_WINNING_TRIFECTA")
                payments[t] = p["yen"]
            need({tuple(t) for t in wins} == set(payments) and
                 len(wins) == len(payments),
                 "INCONSISTENT_FINAL_WINNERS")
        results = {}
        variable_ledger = PrivateVariableLedger(self.store)
        for model_id in ALL_MODELS:
            model = suite["models"][model_id]
            ranks = {tuple(t["combination"]): i+1
                     for i,t in enumerate(model["candidates"])}
            if settled:
                need(set(payments).issubset(ranks),
                     "RESULT_WINNER_NOT_IN_FROZEN_UNIVERSE")
            selection = variable_ledger.selection(race_id, model_id)
            variable = None
            if selection is not None:
                detail = selection["selection"]
                need(detail["model_prediction_sha256"] ==
                         model["prediction_sha256"] and
                     detail["suite_sha256"] == suite["suite_sha256"] and
                     detail["model_version"] == model["model_version"] and
                     detail["official_cutoff_at"] == suite["sales_cutoff_at"] and
                     utc(selection["persisted_at"]) <
                         utc(suite["sales_cutoff_at"]),
                     "VARIABLE_SELECTION_NOT_BOUND_TO_FROZEN_MODEL")
                variable = [tuple(r["triple"]) for r in detail["tickets"]]
                need(len(variable) == detail["pick_count"] and
                     len(variable) <= 12 and len(set(variable)) == len(variable)
                     and set(variable).issubset(ranks) and
                     all(r["reference_stake_yen"] == 100
                         for r in detail["tickets"]),
                     "BAD_PRESELECTED_VARIABLE_TICKETS")
            winners = [{
                "triple": list(t),
                "payout_yen_per_100": yen,
                "is_mansha": yen >= MANSHA_YEN_PER_100,
                "pre_cutoff_model_rank": ranks[t],
                "pre_cutoff_model_score_uncalibrated":
                    model["candidates"][ranks[t]-1]["score"],
            } for t,yen in sorted(payments.items(),key=lambda r:ranks[r[0]])]
            report = {
                "schema": SCHEMA, "race_id": race_id,
                "model_id": model_id,
                "model_version": model["model_version"],
                "model_prediction_sha256": model["prediction_sha256"],
                "suite_sha256": suite["suite_sha256"],
                "source_sha256": saved["source_sha256"],
                "generated_as_of": suite["as_of"],
                "persisted_at_local_clock": saved["persisted_at"],
                "declared_cutoff_at": suite["sales_cutoff_at"],
                "complete_pre_cutoff_rank_count": len(ranks),
                "result_revision": row["revision"],
                "result_payload_sha256": row["payload_sha256"],
                "result_status": "SETTLED_RESEARCH" if settled else "UNSETTLED",
                "winning_tickets": winners if settled else [],
                "mansha_winning_tickets_count": sum(
                    t["is_mansha"] for t in winners) if settled else None,
                "modes": _payout_modes(model, payments, variable,
                                       settled=settled),
                "model_probabilities_calibrated": False,
                "independent_external_cutoff_receipt_verified": False,
                "official_result_independently_authenticated": False,
                "provider_authentication_claim_present":
                    bool(row["provider_auth_verified"]),
                "actual_purchase_evidence": None,
                "formal_hit_rate": None,
                "formal_roi": None,
            }
            report["audit_sha256"] = _hash_bytes(canonical(report))
            results[model_id] = report
        self.db.execute("BEGIN IMMEDIATE")
        try:
            for model_id, report in results.items():
                rowkey = (race_id, model_id, report["model_version"],
                          report["result_revision"])
                previous = self.db.execute(
                    "SELECT payload FROM keirin_pr71_four_model_rank_audits "
                    "WHERE race_id=? AND model_id=? AND model_version=? "
                    "AND revision=?", rowkey).fetchone()
                if previous is None:
                    self.db.execute(
                        "INSERT INTO keirin_pr71_four_model_rank_audits "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (*rowkey,report["model_prediction_sha256"],
                         report["result_payload_sha256"],
                         report["audit_sha256"],canonical(report)))
                else:
                    need(previous["payload"] == canonical(report),
                         "PR71_RESULT_AUDIT_IMMUTABILITY_CONFLICT")
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return results

    def replay_all(self, *, max_races=2000, max_revisions=50000):
        need(type(max_races) is int and 1 <= max_races <= 2000 and
             type(max_revisions) is int and 1 <= max_revisions <= 50000,
             "PR71_REPLAY_LIMIT_INVALID")
        races = self.db.execute(
            "SELECT race_id FROM keirin_pr71_four_model_suites "
            "ORDER BY race_id LIMIT ?",(max_races+1,)).fetchall()
        need(len(races) <= max_races, "PR71_RACE_LIMIT_REACHED")
        all_latest = []
        missing_result = revised = 0
        for record in races:
            versions = self.db.execute(
                "SELECT revision FROM result_revisions WHERE race_id=? "
                "ORDER BY revision",(record["race_id"],)).fetchall()
            if not versions:
                missing_result += 1
                continue
            for v in versions:
                need(revised < max_revisions,"PR71_REVISION_LIMIT_REACHED")
                reports = self.audit_revision(record["race_id"],v["revision"])
                revised += 1
            all_latest.extend(reports.values())
        result_models = {}
        for model_id in ALL_MODELS:
            model_reports = [x for x in all_latest if x["model_id"] == model_id]
            settled = [x for x in model_reports
                       if x["result_status"] == "SETTLED_RESEARCH"]
            mansha = [x for x in settled
                      if x["mansha_winning_tickets_count"] > 0]
            buckets = Counter(
                ("Top8" if t["pre_cutoff_model_rank"]<=8 else
                 "9-12" if t["pre_cutoff_model_rank"]<=12 else
                 "13-24" if t["pre_cutoff_model_rank"]<=24 else
                 "25-50" if t["pre_cutoff_model_rank"]<=50 else
                 "51-100" if t["pre_cutoff_model_rank"]<=100 else
                 "101+")
                for report in mansha for t in report["winning_tickets"]
                if t["is_mansha"])
            modes = {}
            for mode in ("top8","top12","variable"):
                active = [x["modes"][mode] for x in settled
                          if x["modes"][mode]["state"]=="REFERENCE_PURCHASE"]
                skipped = sum(x["modes"][mode]["state"]=="PRE_DECIDED_SKIP"
                              for x in settled)
                eligible_mansha = [x for x in mansha
                                   if x["modes"][mode]["mansha_captured"]
                                      is not None]
                caught = sum(x["modes"][mode]["mansha_captured"] is True
                             for x in eligible_mansha)
                cost = sum(x["investment_yen"] for x in active)
                paid = sum(x["payout_yen"] for x in active)
                modes[mode] = {
                    "active_races": len(active),
                    "pre_decided_skips": skipped,
                    "unassessable_due_to_missing_selection":
                        sum(x["modes"][mode]["state"] ==
                            "NO_PRE_CUTOFF_VARIABLE_SELECTION"
                            for x in settled),
                    "hits": sum(x["hit"] is True for x in active),
                    "hit_rate_on_active_races":
                        sum(x["hit"] is True for x in active) / len(active)
                        if active else None,
                    "mansha_races_evaluable": len(eligible_mansha),
                    "mansha_races_captured": caught,
                    "mansha_capture_rate":
                        caught/len(eligible_mansha) if eligible_mansha else None,
                    "reference_investment_yen":cost,
                    "reference_payout_yen":paid,
                    "reference_profit_yen":paid-cost,
                    "reference_roi":paid/cost if cost else None,
                }
            result_models[model_id] = {
                "model_version":"0.1.0-UNTRAINED",
                "settled_races":len(settled),
                "unsettled_races":len(model_reports)-len(settled),
                "mansha_races":len(mansha),
                "mansha_rank_bands":dict(sorted(buckets.items())),
                "modes":modes,
            }
        return {
            "schema": SUMMARY,
            "existing_pr71_models_evaluated":list(ALL_MODELS),
            "ranked_forecast_races":len(races),
            "races_missing_result":missing_result,
            "replayed_result_revisions":revised,
            "latest_model_race_audits":len(all_latest),
            "models":result_models,
            "national_race_coverage_verified":False,
            "independent_pre_cutoff_witness_verified":False,
            "official_results_authenticated_independently":False,
            "formal_hit_rate":None, "formal_roi":None,
        }


def stage_existing_owner_pre_races(inbox, store, *,
                                   source_admission=None, max_files=150):
    """Bounded local pre/ only. No network, secret, race ID or URL in output."""
    need(type(max_files) is int and 1 <= max_files <= 150,
         "INVALID_OWNER_FILE_WINDOW")
    root = Path(inbox).expanduser()
    need(root.is_absolute() and root.is_dir() and not root.is_symlink(),
         "PRIVATE_OWNER_INBOX_REQUIRED")
    directory = root/"pre"
    if not directory.exists():
        return {"states":{"no_private_pre_input":1},
                "private_four_model_predictions_saved":0,
                "provider_network_requests":0}
    need(directory.is_dir() and not directory.is_symlink(),
         "PRIVATE_PRE_RACE_DIRECTORY_UNSAFE")
    all_files = list(directory.glob("*.json"))
    latest = sorted(all_files, key=lambda p: (p.stat().st_mtime_ns,str(p)),
                    reverse=True)
    states = Counter()
    ledger = FourModelRankLedger(store)
    for p in latest[:max_files]:
        try:
            need(not p.is_symlink() and
                 0 < p.stat().st_size <= 2_000_000,
                 "UNTRUSTED_PRIVATE_SOURCE_FILE")
            source = json.loads(p.read_text(encoding="utf-8"))
            if source.get("schema") != "RACE_AI_KEIRIN_PRIVATE_PRE_RACE_V1":
                states["unsupported_source_shape"] += 1
                continue
            ledger.freeze_once(source,source_admission=source_admission)
            states["prospective_four_model_rank_frozen"] += 1
        except (ValueError,KeyError,TypeError,OSError):
            states["incomplete_rights_or_cutoff_or_input"] += 1
    if len(latest) > max_files:
        states["older_files_outside_scan_window"] = len(latest)-max_files
    return {"schema":"RACE_AI_OWNER_PR71_FOUR_MODEL_PRIVATE_STAGE_V1",
            "states":dict(sorted(states.items())),
            "private_four_model_predictions_saved":
                states["prospective_four_model_rank_frozen"],
            "provider_network_requests":0,
            "external_receipt_issued":False,
            "official_prediction":False}
