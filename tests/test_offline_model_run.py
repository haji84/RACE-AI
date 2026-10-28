"""Authored fictional inputs only; real SQLite/processes and existing local models."""
from copy import deepcopy
from contextlib import closing
from datetime import datetime
import hashlib
import importlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import race_ai
import tests

REFERENCE = ROOT / "pr71-private-transport-reference"
race_ai.__path__.append(str(REFERENCE / "race_ai"))
tests.__path__.append(str(REFERENCE / "tests"))

MODEL_PIN = "ebe93f13062cf0461b81b924a5dc0482ada37b56"
CONTRACT_PIN = "2a99473c4755932e2d395b9e785be4f4835aef99"
MODELS = ("multisport-factor-interaction-v1", "multisport-scenario-ensemble-v1",
          "multisport-conditional-duel-v1", "multisport-race-trajectory-v1")
VERSIONS = {name: "0.1.0-UNTRAINED" for name in MODELS}
AT = "2030-01-15T09:15:00+09:00"
LATE = "2030-01-15T11:05:00+09:00"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class Clock:
    def __init__(self, at=AT):
        self.at = at

    def __call__(self):
        return datetime.fromisoformat(self.at)


def case(ready=("boat",), cutoffs=None):
    from tests.test_permissioned_source_delivery import raw_feed, gate
    from race_ai.comprehensive_four_sport_models import digest
    policy = gate()
    raws, rows, jobs = {}, [], []
    for sport in ("boat", "keirin", "autorace", "horse"):
        source_sport = "horse_local" if sport == "horse" else sport
        feed = json.loads(raw_feed(sport))
        if cutoffs and sport in cutoffs:
            feed["snapshot"]["race"]["sales_cutoff_at"] = cutoffs[sport]
        raw = canonical(feed).encode()
        race = feed["snapshot"]["race"]
        for number in (1, 2):
            race_id = f"{source_sport}:2030-01-15:fictional-venue:{number}"
            rows.append({"race_id": race_id, "sport": source_sport,
                         "venue": "fictional-venue", "race_no": number,
                         "sales_cutoff_at": race["sales_cutoff_at"],
                         "cutoff_verified": False, "prediction": None, "result": None})
            check = {"as_of": race["as_of"], "source_payload_sha256": sha(raw),
                     "policy_record_sha256": policy.document_sha256,
                     "feature_snapshot_sha256": digest(feed["snapshot"])}
            jobs.append({"race_id": race_id,
                         "input_check": check if number == 1 and sport in ready else None})
            if number == 1:
                raws[race_id] = raw
    manifest = {"schema": "RACE_AI_SYNTHETIC_ADVANCED_RUN_V1", "scope": "SYNTHETIC_ONLY",
                "planned_as_of": AT,
                "source_pins": {"model": MODEL_PIN, "settlement_contract_base": CONTRACT_PIN},
                "expected_model_ids": list(MODELS), "expected_model_versions": dict(VERSIONS),
                "ledger": {"schema": "RACE_AI_FORECAST_AUDIT_V1", "dataset_status": "AUDIT_ONLY",
                           "event_date_jst": "2030-01-15", "records": rows}, "jobs": jobs}
    results = [{"race_id": row["race_id"], "status": "FINAL", "trifecta_offered": True,
                "payouts": [{"combination": [1, 2, 3], "yen_per_100": 1000}],
                "refund_status": "NONE", "revision_no": 1,
                "confirmed_at": "2030-01-15T11:00:00+09:00",
                "source_ref": "https://example.org/fictional-result"} for row in rows]
    return manifest, raws, policy, results


def open_journal(path, clock, policy):
    from race_ai import private_delivery_codec as codec
    from race_ai.comprehensive_four_sport_models import validate
    module = importlib.import_module("race_ai.offline_model_run")
    return module.SyntheticModelJournal(path, clock=clock, codec=codec,
                                       validate_snapshot=validate, allow_source=policy.authorize)


def factory(raws, policy, calls=None):
    from race_ai.permissioned_source_delivery import deliver

    def produce(job, *, at):
        if calls is not None:
            calls.append(job["race_id"])
        return deliver(raws[job["race_id"]], policy, at=at, persist=False)
    return produce


def gates(manifest, results):
    known = {sha(canonical(result).encode()) for result in results}
    declaration = tuple((name, VERSIONS[name], MODEL_PIN) for name in MODELS)
    return {"admit_model_roster": lambda value: value == declaration,
            "verify_result": lambda value: sha(canonical(value).encode()) in known,
            "verify_cutoff": lambda row: row in manifest["ledger"]["records"],
            "verify_coverage": lambda ledger: ledger == manifest["ledger"]}


def events(path):
    with closing(sqlite3.connect(path)) as db:
        return db.execute("SELECT seq,event_key,kind,recorded_at,metadata,content,"
                          "previous_sha256,event_sha256 FROM advanced_events ORDER BY seq").fetchall()


def corrupt(path, transform):
    """Attacker can recompute local checksums; semantic checks must still reject."""
    with closing(sqlite3.connect(path)) as db:
        trigger = db.execute("SELECT sql FROM sqlite_master WHERE name='advanced_events_no_update'").fetchone()[0]
        db.execute("DROP TRIGGER advanced_events_no_update")
        previous = "0" * 64
        for seq, key, kind, at, text, content, _, old_hash in events(path):
            metadata = json.loads(text)
            at, metadata, content = transform(kind, at, metadata, content)
            digest = sha(b"RACE_AI_SYNTHETIC_ADVANCED_JOURNAL_V1\0" +
                         canonical([seq, key, kind, at, metadata, sha(content), previous]).encode())
            db.execute("UPDATE advanced_events SET recorded_at=?,metadata=?,content=?,"
                       "previous_sha256=?,event_sha256=? WHERE seq=?",
                       (at, canonical(metadata), content, previous, digest, seq))
            previous = digest
        db.execute(trigger)
        db.commit()


class OfflineModelRunTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("race_ai.offline_model_run"),
                             "durable advanced-model runner is missing")
        self.module = importlib.import_module("race_ai.offline_model_run")
        self.temp = tempfile.TemporaryDirectory(prefix="race-ai-authored-run-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "synthetic.sqlite"
        self.clock = Clock()
        self.manifest, self.raws, self.policy, self.results = case()
        self.network = patch("socket.create_connection", side_effect=AssertionError("network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def journal(self):
        journal = open_journal(self.path, self.clock, self.policy)
        self.addCleanup(journal.close)
        return journal

    def run_one(self):
        journal = self.journal()
        states = journal.run(self.manifest, delivery_factory=factory(self.raws, self.policy))
        return journal, states

    def test_four_sports_sixteen_models_roundtrip_and_shared_missing_denominator(self):
        self.manifest, self.raws, self.policy, self.results = case(
            ("boat", "keirin", "autorace", "horse"))
        calls = []
        journal = self.journal()
        states = journal.run(self.manifest, delivery_factory=factory(self.raws, self.policy, calls))
        self.assertEqual(len(calls), 4)
        self.assertEqual([row["state"] for row in states], ["DELIVERY", "NO_FORECAST"] * 4)
        self.assertEqual(sum(row["prepared_anchor_count"] for row in states), 16)
        before = [(row[1], row[5]) for row in events(self.path) if row[2] == "DELIVERY"]
        journal.close()
        self.clock.at = LATE
        journal = self.journal()
        self.assertEqual(journal.run(self.manifest, delivery_factory=lambda *a, **k: self.fail("rerun")), states)
        self.assertEqual([(row[1], row[5]) for row in events(self.path) if row[2] == "DELIVERY"], before)
        journal.add_results(self.results)
        report = journal.report()
        self.assertEqual(report["scope"], "SYNTHETIC_ONLY")
        self.assertEqual(len(report["jobs"]), 8)
        self.assertFalse(report["external_time_attested"])
        for comparison in report["settlement"]["models"].values():
            self.assertEqual(comparison["source_records_preserved"], 8)
            self.assertEqual(comparison["freeze_verified_subset"], 0)
            self.assertIsNone(comparison["formal_hit_at_8_all"])
        simulated = journal.report(synthetic_gates=gates(self.manifest, self.results))
        for comparison in simulated["settlement"]["models"].values():
            self.assertEqual(comparison["eligible_verified_subset"], 8)
            self.assertEqual(comparison["freeze_verified_subset"], 0)
            self.assertEqual(comparison["formal_capture_rate"], 0)
        self.assertEqual(journal.report(synthetic_gates=gates(self.manifest, self.results)), simulated)

    def test_partial_failure_keeps_all_eight_report_rows_and_committed_original(self):
        self.manifest, self.raws, self.policy, self.results = case(("boat", "keirin"),
            {"boat": "2030-01-15T09:40:00+09:00", "keirin": "2030-01-15T09:50:00+09:00"})
        journal = self.journal()
        produce = factory(self.raws, self.policy)
        def fail_second(job, *, at):
            if job["race_id"].startswith("keirin:"):
                raise RuntimeError("authored factory failure")
            return produce(job, at=at)
        with self.assertRaises(RuntimeError):
            journal.run(self.manifest, delivery_factory=fail_second)
        report = journal.report()
        self.assertEqual(len(report["jobs"]), 8)
        self.assertEqual(report["jobs"][0]["state"], "DELIVERY")
        self.assertEqual(report["jobs"][2]["state"], "NOT_RUN")
        self.assertEqual(len(report["settlement"]["models"][MODELS[0]]["rows"]), 8)

    def test_cutoff_priority_ignores_caller_job_order_and_retains_missing_inputs(self):
        self.manifest, self.raws, self.policy, self.results = case(("boat", "keirin"),
            {"keirin": "2030-01-15T09:30:00+09:00", "boat": "2030-01-15T09:40:00+09:00"})
        self.manifest["jobs"].reverse()
        calls = []
        states = self.journal().run(self.manifest, delivery_factory=factory(self.raws, self.policy, calls))
        self.assertTrue(calls[0].startswith("keirin:"))
        self.assertTrue(calls[1].startswith("boat:"))
        self.assertEqual(len(states), 8)
        self.assertEqual([row["race_id"] for row in states],
                         [row["race_id"] for row in self.manifest["ledger"]["records"]])

    def test_null_inputs_never_call_factory(self):
        self.manifest, self.raws, self.policy, self.results = case(())
        states = self.journal().run(self.manifest, delivery_factory=lambda *a, **k: self.fail("factory"))
        self.assertEqual([row["reason"] for row in states], ["MISSING_INPUT"] * 8)

    def test_cutoff_crossing_rolls_back_output_and_retry_records_missing(self):
        journal = self.journal()
        produce = factory(self.raws, self.policy)
        def crossing(job, *, at):
            value = produce(job, at=at)
            self.clock.at = "2030-01-15T10:00:00+09:00"
            return value
        with self.assertRaises(ValueError):
            journal.run(self.manifest, delivery_factory=crossing)
        self.assertFalse(any(row[2] == "DELIVERY" for row in events(self.path)))
        states = journal.run(self.manifest, delivery_factory=lambda *a, **k: self.fail("late factory"))
        self.assertEqual(states[0]["reason"], "MISSED_DEADLINE")

    def test_deadline_crossing_after_insert_before_commit_rolls_back_delivery(self):
        journal = self.journal()
        append = journal._append
        def advance_after_insert(key, kind, at, metadata, content=b""):
            append(key, kind, at, metadata, content)
            if kind == "DELIVERY":
                self.clock.at = LATE
        with patch.object(journal, "_append", side_effect=advance_after_insert):
            with self.assertRaises(ValueError):
                journal.run(self.manifest, delivery_factory=factory(self.raws, self.policy))
        self.assertFalse(any(row[2] == "DELIVERY" for row in events(self.path)))

    def test_manifest_and_factory_job_are_copied_without_output_normalization(self):
        original = deepcopy(self.manifest)
        produce = factory(self.raws, self.policy)
        def mutating(job, *, at):
            value = produce(job, at=at)
            job["input_check"]["as_of"] = "tampered by factory"
            return value
        self.journal().run(self.manifest, delivery_factory=mutating)
        self.assertEqual(self.manifest, original)

    def test_conflicting_manifest_hash_or_source_pin_is_rejected(self):
        journal, _ = self.run_one()
        changed = deepcopy(self.manifest)
        changed["jobs"][0]["input_check"]["source_payload_sha256"] = "f" * 64
        with self.assertRaises(ValueError):
            journal.run(changed, delivery_factory=lambda *a, **k: self.fail("conflict"))
        for pin in ("model", "settlement_contract_base"):
            changed = deepcopy(self.manifest)
            changed["source_pins"][pin] = "f" * 40
            with self.assertRaises(ValueError):
                journal.run(changed, delivery_factory=lambda *a, **k: self.fail("pin"))

    def test_wrong_source_policy_snapshot_asof_or_partial_model_output_rolls_back(self):
        from race_ai.comprehensive_four_sport_models import digest
        from tests.test_model_suite_settlement import rehash
        for field in ("source_payload_sha256", "policy_record_sha256", "feature_snapshot_sha256",
                      "as_of", "partial_models", "model_version"):
            with self.subTest(field=field):
                path = Path(self.temp.name) / (field + ".sqlite")
                journal = open_journal(path, self.clock, self.policy)
                self.addCleanup(journal.close)
                produce = factory(self.raws, self.policy)
                def wrong(job, *, at):
                    value = produce(job, at=at)
                    if field in ("source_payload_sha256", "policy_record_sha256", "feature_snapshot_sha256"):
                        value[field] = "f" * 64
                    elif field == "as_of":
                        value["snapshot"]["race"]["as_of"] = "2030-01-15T09:11:00+09:00"
                    elif field == "partial_models":
                        value["research_suite"]["models"].pop(MODELS[-1])
                    else:
                        value["research_suite"]["models"][MODELS[0]]["model_version"] = "new-version"
                    rehash(value)
                    return value
                with self.assertRaises(ValueError):
                    journal.run(self.manifest, delivery_factory=wrong)
                self.assertFalse(any(row[2] == "DELIVERY" for row in events(path)))

    def test_actual_validator_denial_and_unexpected_error_roll_back(self):
        from race_ai import private_delivery_codec as codec
        for failure in (False, RuntimeError("validator failed")):
            with self.subTest(failure=str(failure)):
                def validator(snapshot, *, allow_source):
                    if isinstance(failure, Exception):
                        raise failure
                    allow_source("not-admitted", "not-admitted", "analysis")
                    from race_ai.comprehensive_four_sport_models import digest
                    return {"snapshot_sha256": digest(snapshot)}
                path = Path(self.temp.name) / ("denied" if failure is False else "error")
                journal = self.module.SyntheticModelJournal(path, clock=self.clock, codec=codec,
                    validate_snapshot=validator, allow_source=self.policy.authorize)
                self.addCleanup(journal.close)
                with self.assertRaises((ValueError, RuntimeError)):
                    journal.run(self.manifest, delivery_factory=factory(self.raws, self.policy))
                self.assertFalse(any(row[2] == "DELIVERY" for row in events(path)))

    def test_clock_rollback_rejected_after_reopen_and_on_committed_retry(self):
        journal, _ = self.run_one()
        journal.close()
        self.clock.at = "2030-01-15T09:14:59+09:00"
        journal = self.journal()
        with self.assertRaises(ValueError):
            journal.run(self.manifest, delivery_factory=lambda *a, **k: self.fail("rollback"))

    def test_revisions_append_evaluations_without_replacing_forecasts_or_claims(self):
        journal, _ = self.run_one()
        original = [(row[1], row[5]) for row in events(self.path) if row[2] == "DELIVERY"]
        self.clock.at = LATE
        journal.add_results(self.results)
        first = journal.report(synthetic_gates=gates(self.manifest, self.results))
        self.assertEqual(journal.add_results(deepcopy(self.results)), self.results)
        revised = deepcopy(self.results[0])
        revised.update(revision_no=2, confirmed_at="2030-01-15T11:10:00+09:00")
        revised["payouts"][0]["combination"] = [3, 2, 1]
        self.clock.at = "2030-01-15T11:11:00+09:00"
        journal.add_results([revised])
        second = journal.report(synthetic_gates=gates(self.manifest, self.results + [revised]))
        self.assertNotEqual(first["evaluation_sha256"], second["evaluation_sha256"])
        self.assertEqual(len([row for row in events(self.path) if row[2] == "RESULT"]), 9)
        self.assertEqual(len([row for row in events(self.path) if row[2] == "EVALUATION"]), 2)
        self.assertEqual([(row[1], row[5]) for row in events(self.path) if row[2] == "DELIVERY"], original)
        journal.close()
        self.journal().report()  # replay both earlier, independently classified evaluations

    def test_result_gap_conflict_and_future_confirmation_are_atomic(self):
        journal, _ = self.run_one()
        self.clock.at = LATE
        bad = deepcopy(self.results)
        bad[-1]["revision_no"] = 2
        with self.assertRaises(ValueError):
            journal.add_results(bad)
        self.assertFalse(any(row[2] == "RESULT" for row in events(self.path)))
        future = deepcopy(self.results[0])
        future["confirmed_at"] = "2030-01-15T12:00:00+09:00"
        with self.assertRaises(ValueError):
            journal.add_results([future])
        journal.add_results(self.results)
        conflict = deepcopy(self.results[0])
        conflict["payouts"][0]["yen_per_100"] = 2000
        with self.assertRaises(ValueError):
            journal.add_results([conflict])

    def test_unknown_freeze_gate_cannot_promote_prepared_plans(self):
        journal, _ = self.run_one()
        with self.assertRaises(ValueError):
            journal.report(synthetic_gates={"verify_model_freeze": lambda *a: True})

    def test_idempotent_result_retry_does_not_bypass_exact_type_validation(self):
        journal, _ = self.run_one()
        self.clock.at = LATE
        journal.add_results(self.results)
        before = events(self.path)
        changes = (("revision_bool", lambda claim: claim.update(revision_no=True)),
                   ("revision_float", lambda claim: claim.update(revision_no=1.0)),
                   ("offered_int", lambda claim: claim.update(trifecta_offered=1)),
                   ("payout_float", lambda claim: claim["payouts"][0].update(yen_per_100=1000.0)))
        for name, mutate in changes:
            with self.subTest(name=name):
                changed = deepcopy(self.results[0])
                mutate(changed)
                with self.assertRaises(ValueError):
                    journal.add_results([changed])
                self.assertEqual(events(self.path), before)

    def test_rehashed_report_false_cannot_be_replaced_with_numeric_zero(self):
        journal, _ = self.run_one()
        journal.report()
        journal.close()
        def change(kind, at, metadata, content):
            if kind == "EVALUATION":
                metadata["report"]["official_prediction"] = 0
            return at, metadata, content
        corrupt(self.path, change)
        with self.assertRaises(ValueError):
            self.journal()

    def test_rehashed_prepared_plan_false_cannot_be_replaced_with_numeric_zero(self):
        journal, _ = self.run_one()
        journal.close()
        def change(kind, at, metadata, content):
            if kind == "DELIVERY":
                metadata["plans"][0]["eligible_for_hit_at_8"] = 0
            return at, metadata, content
        corrupt(self.path, change)
        with self.assertRaises(ValueError):
            self.journal()

    def test_foreign_database_is_rejected_without_any_file_or_schema_change(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("CREATE TABLE owner_data(value TEXT)")
            db.execute("INSERT INTO owner_data VALUES('fictional unrelated data')")
            db.commit()
            before_schema = db.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name").fetchall()
        before = self.path.read_bytes()
        rejected = False
        candidate = None
        try:
            candidate = open_journal(self.path, self.clock, self.policy)
        except ValueError:
            rejected = True
        finally:
            if candidate is not None:
                candidate.close()
        self.assertEqual(self.path.read_bytes(), before)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name").fetchall(), before_schema)
        self.assertTrue(rejected, "foreign SQLite database must be rejected")

    def test_existing_journal_wrong_identity_is_not_adopted_or_repaired(self):
        journal, _ = self.run_one()
        journal.close()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("PRAGMA application_id=12345")
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            candidate = open_journal(self.path, self.clock, self.policy)
            candidate.close()
        self.assertEqual(self.path.read_bytes(), before)

    def test_all_missing_jobs_still_require_canonical_date_and_matching_jst_cutoff_day(self):
        for variant in ("compact_date", "different_cutoff_day"):
            with self.subTest(variant=variant):
                manifest, raws, policy, results = case(())
                if variant == "compact_date":
                    manifest["ledger"]["event_date_jst"] = "20300115"
                    for row, job in zip(manifest["ledger"]["records"], manifest["jobs"]):
                        row["race_id"] = row["race_id"].replace("2030-01-15", "20300115")
                        job["race_id"] = row["race_id"]
                else:
                    for row in manifest["ledger"]["records"]:
                        row["sales_cutoff_at"] = "2030-01-16T10:00:00+09:00"
                path = Path(self.temp.name) / (variant + ".sqlite")
                journal = open_journal(path, self.clock, policy)
                self.addCleanup(journal.close)
                with self.assertRaises(ValueError):
                    journal.run(manifest, delivery_factory=lambda *a, **k: self.fail("no model calls"))

    def test_equivalent_cutoff_timezone_and_unknown_cutoff_keep_all_jobs(self):
        self.manifest, self.raws, self.policy, self.results = case(())
        for row in self.manifest["ledger"]["records"]:
            row["sales_cutoff_at"] = "2030-01-15T01:00:00+00:00"
        self.manifest["jobs"][0]["input_check"] = case()[0]["jobs"][0]["input_check"]
        self.manifest["ledger"]["records"][0]["sales_cutoff_at"] = None
        journal = self.journal()
        states = journal.run(self.manifest, delivery_factory=lambda *a, **k: self.fail("no model calls"))
        self.assertEqual(states[0]["reason"], "CUTOFF_UNKNOWN")
        self.assertEqual(len(journal.report()["jobs"]), 8)

    def test_rehashed_wrong_input_transport_is_rejected_on_reopen(self):
        from race_ai import private_delivery_codec as codec
        from race_ai.comprehensive_four_sport_models import digest
        journal, _ = self.run_one()
        journal.close()
        def change(kind, at, metadata, content):
            if kind == "DELIVERY":
                value = codec.deserialize_private_delivery(content)
                value["source_payload_sha256"] = "f" * 64
                value["delivery_sha256"] = digest({k: v for k, v in value.items() if k != "delivery_sha256"})
                content = codec.serialize_private_delivery(value)
                metadata["delivery_sha256"] = value["delivery_sha256"]
            return at, metadata, content
        corrupt(self.path, change)
        with self.assertRaises(ValueError):
            self.journal()

    def test_rehashed_anchor_or_timestamp_tamper_is_semantically_rejected(self):
        journal, _ = self.run_one()
        journal.close()
        def change(kind, at, metadata, content):
            if kind == "DELIVERY":
                metadata["plans"][0]["anchor"]["prediction_sha256"] = "f" * 64
            return at, metadata, content
        corrupt(self.path, change)
        with self.assertRaises(ValueError):
            self.journal()

    def test_recorded_at_is_bound_in_chain_and_replayed_chronology(self):
        journal, _ = self.run_one()
        journal.close()
        with closing(sqlite3.connect(self.path)) as db:
            trigger = db.execute("SELECT sql FROM sqlite_master WHERE name='advanced_events_no_update'").fetchone()[0]
            db.execute("DROP TRIGGER advanced_events_no_update")
            db.execute("UPDATE advanced_events SET recorded_at=? WHERE kind='DELIVERY'",
                       ("2030-01-15T09:16:00+09:00",))
            db.execute(trigger)
            db.commit()
        with self.assertRaises(ValueError):
            self.journal()

    def test_reopen_replays_recorded_source_verdicts_without_renewed_authority_callback(self):
        from race_ai import private_delivery_codec as codec
        from race_ai.comprehensive_four_sport_models import validate
        journal, _ = self.run_one()
        self.clock.at = LATE
        journal.add_results(self.results)
        original = journal.report(synthetic_gates=gates(self.manifest, self.results))
        journal.close()
        def forbidden(*args, **kwargs):
            raise AssertionError("authority callback must not run on replay")
        replay = self.module.SyntheticModelJournal(self.path, clock=self.clock, codec=codec,
            validate_snapshot=validate, allow_source=forbidden)
        self.addCleanup(replay.close)
        self.assertEqual(replay.report(synthetic_gates=gates(self.manifest, self.results)), original)

    def test_rehashed_generation_cannot_start_before_previous_committed_event(self):
        from race_ai import private_delivery_codec as codec
        from race_ai.comprehensive_four_sport_models import digest
        journal, _ = self.run_one()
        journal.close()
        def change(kind, at, metadata, content):
            if kind == "DELIVERY":
                value = codec.deserialize_private_delivery(content)
                value["ingested_at"] = "2030-01-15T09:14:00+09:00"
                value["delivery_sha256"] = digest({k: v for k, v in value.items() if k != "delivery_sha256"})
                metadata["started_at"] = value["ingested_at"]
                metadata["delivery_sha256"] = value["delivery_sha256"]
                content = codec.serialize_private_delivery(value)
            return at, metadata, content
        corrupt(self.path, change)
        with self.assertRaises(ValueError):
            self.journal()

    def test_real_process_crash_during_compute_rolls_back_then_late_retry_is_missing(self):
        completed = subprocess.run([sys.executable, "-B", "-X", "utf8", __file__,
                                    "--worker", "before", str(self.path)], capture_output=True, timeout=30)
        self.assertEqual(completed.returncode, 71, completed.stderr.decode())
        self.assertFalse(any(row[2] == "DELIVERY" for row in events(self.path)))
        self.clock.at = LATE
        states = self.journal().run(self.manifest, delivery_factory=lambda *a, **k: self.fail("late"))
        self.assertEqual(states[0]["reason"], "MISSED_DEADLINE")

    def test_real_process_crash_after_commit_reuses_exact_wire_without_inference(self):
        completed = subprocess.run([sys.executable, "-B", "-X", "utf8", __file__,
                                    "--worker", "after", str(self.path)], capture_output=True, timeout=30)
        self.assertEqual(completed.returncode, 72, completed.stderr.decode())
        before = events(self.path)
        self.clock.at = LATE
        states = self.journal().run(self.manifest, delivery_factory=lambda *a, **k: self.fail("recomputed"))
        self.assertEqual(states[0]["state"], "DELIVERY")
        self.assertEqual(events(self.path), before)

    def test_two_real_processes_serialize_factory_and_keep_one_original(self):
        marker = str(Path(self.temp.name) / "calls.txt")
        command = [sys.executable, "-B", "-X", "utf8", __file__, "--worker", "concurrent", str(self.path), marker]
        children = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
        for child in children:
            stdout, stderr = child.communicate(timeout=40)
            self.assertEqual(child.returncode, 0, stderr.decode())
        self.assertEqual(Path(marker).read_text().splitlines(), ["factory"])
        self.assertEqual(len([row for row in events(self.path) if row[2] == "DELIVERY"]), 1)
        self.journal().report()


def worker(mode, path, marker=None):
    manifest, raws, policy, results = case()
    journal = open_journal(path, Clock(), policy)
    produce = factory(raws, policy)
    def invoke(job, *, at):
        value = produce(job, at=at)
        if mode == "before":
            os._exit(71)
        if mode == "concurrent":
            with open(marker, "a", encoding="utf-8") as stream:
                stream.write("factory\n")
            time.sleep(0.15)
        return value
    with patch("socket.create_connection", side_effect=AssertionError("network forbidden")):
        journal.run(manifest, delivery_factory=invoke)
    if mode == "after":
        os._exit(72)
    journal.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        worker(*sys.argv[2:])
    else:
        unittest.main()
