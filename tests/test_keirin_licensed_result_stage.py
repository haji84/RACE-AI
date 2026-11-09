"""Synthetic result V3 feed -> existing immutable four-model PDCA.

The website result/provider grant and the entire race are fictional. These
tests NEVER certify official result identity, real winnings or a live feed.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import unittest

from race_ai.keirin_licensed_api_ingest import (
    EXPORT_SCHEMA_V3,fetch_licensed_export_once,LicenseDeliveryError
)
from race_ai.keirin_licensed_result_stage import (
    ROW_SCHEMA,stage_licensed_result_export,apply_existing_frozen_results
)
from race_ai.keirin_permissioned_owner import load_operator_grants
from race_ai.keirin_owner_sqlite import PrivateKeirinStore
from race_ai.keirin_pr71_four_model_rank import FourModelRankLedger
from race_ai.four_sport_model_suite import ALL_MODELS
from test_keirin_pr71_model_adapter import make_sources,RID
import test_keirin_permissioned_owner as prior

URL="https://example.invalid/fictional-feed/results/revisions"
RIGHTS="FICTIONAL_TEST_RIGHTS_ONLY"
SAMPLE_TIME="2030-01-15T10:40:00+09:00"


def result(*,rev="rev-1",at="2030-01-15T10:15:00+09:00",
           winner=None,pay=18700):
    win=winner or [1,2,3]
    return {
        "schema":ROW_SCHEMA,
        "race_id":RID,
        "source_url":URL,
        "rights_ref":RIGHTS,
        "source_published_at":at,
        "observed_at":at,
        "provider_revision_ref":rev,
        "status":"FINAL_NORMAL",
        "refund_status":"NONE",
        "winning_triples":[win],
        "payouts_100yen":[{"triple":win,"yen":pay}],
    }


class LicensedProviderResultStageTests(unittest.TestCase):
    def setUp(self):
        prior.LicensedSourceStageTests.setUp(self)
        self.addCleanup(prior.LicensedSourceStageTests.tearDown,self)
        self.endpoint="https://example.invalid/fictional-feed/api/daily"
        self.clock=["2030-01-15T09:21:00+09:00"]
        self.dbpath=self.root/"pr71-private.sqlite3"

    def grant(self,*,results=True):
        m=json.loads(self.manifest.read_text())
        m["grants"][0]["purposes"].append("automated_fetch")
        if results:
            m["grants"][0]["purposes"].extend(
                ["result_collection","result_analysis"])
        self.manifest.write_text(json.dumps(m))
        return load_operator_grants(self.manifest,now=SAMPLE_TIME)

    def body(self,rows,*,odds=None,deliveries=None):
        return json.dumps({
            "schema":EXPORT_SCHEMA_V3,
            "bundle_id":"FIXTURE_APPROVED_BUNDLE",
            "deliveries":[] if deliveries is None else deliveries,
            "odds_snapshots":[] if odds is None else odds,
            "result_observations":rows,
        }).encode()

    def intake(self,grants,rows):
        return fetch_licensed_export_once(
            self.root,grants,endpoint=self.endpoint,rights_ref=RIGHTS,
            transport=lambda *_:self.body(rows))

    def frozen_store(self):
        store=PrivateKeirinStore(
            self.dbpath,clock=lambda:datetime.fromisoformat(self.clock[0]))
        ledger=FourModelRankLedger(store)
        self.assertEqual(ledger.freeze_once(make_sources()[0]),
                         "FOUR_MODELS_FROZEN_ONCE")
        source_sha=ledger.read_suite(RID)["suite"]["suite_sha256"]
        self.clock[0]=SAMPLE_TIME
        return store,source_sha

    def test_same_licensed_get_future_originals_then_result_pdca_is_idempotent(self):
        grants=self.grant()
        record=self.intake(grants,[result()])
        self.assertEqual(record["licensed_result_rows_staged"][
            "private_results_created"],1)
        self.assertEqual(record["provider_packets_created"],0)
        with self.frozen_store()[0] as store:
            prior_sha=FourModelRankLedger(store).read_suite(RID)[
                "suite"]["suite_sha256"]
            first=apply_existing_frozen_results(
                self.root,store,grants,checked_at=SAMPLE_TIME)
            self.assertEqual(first["results_appended"],1)
            self.assertFalse(first["official_authentication_independently_verified"])
            ledger=FourModelRankLedger(store)
            reports=ledger.audit_revision(RID)
            self.assertEqual(set(reports),set(ALL_MODELS))
            self.assertTrue(all(x["result_revision"]==1 for x in reports.values()))
            self.assertTrue(all(x["official_result_independently_authenticated"] is False
                                for x in reports.values()))
            self.assertEqual(ledger.replay_all()["latest_model_race_audits"],4)
            second=apply_existing_frozen_results(
                self.root,store,grants,checked_at=SAMPLE_TIME)
            self.assertEqual(second["results_appended"],0)
            self.assertEqual(second["results_already_present"],1)
            self.assertEqual(ledger.read_suite(RID)["suite"]["suite_sha256"],
                             prior_sha)
            self.assertEqual(store.db.execute(
                "SELECT COUNT(*) FROM result_revisions").fetchone()[0],1)

    def test_result_feed_alone_never_creates_post_result_prediction(self):
        grants=self.grant()
        self.intake(grants,[result()])
        with PrivateKeirinStore(
            self.dbpath,clock=lambda:datetime.fromisoformat(SAMPLE_TIME)
        ) as store:
            report=apply_existing_frozen_results(
                self.root,store,grants,checked_at=SAMPLE_TIME)
            self.assertEqual(report["results_appended"],0)
            self.assertEqual(report["results_held"],1)
            self.assertEqual(store.db.execute(
                "SELECT COUNT(*) FROM result_revisions").fetchone()[0],0)

    def test_wrong_result_rights_future_timestamp_or_bad_payout_refused(self):
        for mutate in ("rights","clock","payout","duplicate","before_cutoff"):
            with self.subTest(mutation=mutate):
                row=result()
                if mutate=="rights":
                    row["rights_ref"]="UNAPPROVED_RESULT_RIGHTS"
                if mutate=="clock":
                    row["observed_at"]="2030-01-15T11:10:00+09:00"
                if mutate=="payout":
                    row["payouts_100yen"][0]["yen"]=-1
                if mutate=="before_cutoff":
                    row["source_published_at"]="2030-01-15T09:50:00+09:00"
                    row["observed_at"]="2030-01-15T09:50:00+09:00"
                grants=self.grant_again()
                rows=[row,row] if mutate=="duplicate" else [row]
                if mutate=="before_cutoff":
                    self.intake(grants,rows)
                    with self.frozen_store()[0] as store:
                        report=apply_existing_frozen_results(
                            self.root,store,grants,checked_at=SAMPLE_TIME)
                        self.assertEqual(report["results_appended"],0)
                        self.assertGreaterEqual(report["results_held"],1)
                else:
                    with self.assertRaises(LicenseDeliveryError):
                        self.intake(grants,rows)
                    self.assertEqual(
                        list((self.root/"licensed_result_rows").glob("*.json"))
                        if (self.root/"licensed_result_rows").exists() else [],[])

    def grant_again(self):
        # Avoid appending the same purposes on repeated test subcases.
        m=json.loads(self.manifest.read_text())
        purposes=set(m["grants"][0]["purposes"])
        purposes.update({"automated_fetch","result_collection",
                         "result_analysis"})
        m["grants"][0]["purposes"]=sorted(purposes)
        self.manifest.write_text(json.dumps(m))
        return load_operator_grants(self.manifest,now=SAMPLE_TIME)

    def test_corrections_reuse_existing_result_revisions_not_new_scorer(self):
        grants=self.grant()
        self.intake(grants,[result()])
        self.intake(grants,[result(
            rev="rev-2",at="2030-01-15T10:20:00+09:00",
            winner=[4,5,6],pay=32000)])
        with self.frozen_store()[0] as store:
            report=apply_existing_frozen_results(
                self.root,store,grants,checked_at=SAMPLE_TIME)
            self.assertEqual(report["results_appended"],2)
            ledger=FourModelRankLedger(store)
            audited=ledger.audit_revision(RID)
            self.assertTrue(all(x["result_revision"]==2
                                for x in audited.values()))
            self.assertEqual(store.db.execute(
                "SELECT COUNT(*) FROM result_revisions").fetchone()[0],2)
            self.assertEqual(ledger.read_suite(RID)["suite"]["model_count"],4)
            self.assertEqual(apply_existing_frozen_results(
                self.root,store,grants,checked_at=SAMPLE_TIME)[
                "results_already_present"],2)


if __name__=="__main__":
    unittest.main()
