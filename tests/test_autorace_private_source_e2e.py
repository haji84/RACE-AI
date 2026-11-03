"""Offline 2030 synthetic provider, local persistence and result E2E only."""
from copy import deepcopy
from datetime import datetime
import os
from pathlib import Path
import stat
import tempfile
import unittest

from race_ai.autorace_ab_pdca import PHASES, tick, audit_cycle
from race_ai.autorace_private_store import LocalPrivateJournal
from race_ai.autorace_source_contract import admit, local_feed_acquire, SCHEMA
from race_ai.comprehensive_four_sport_models import digest
from tests.test_comprehensive_four_sport_models import sample, obs


class LocalAuthorizedAutoraceE2E(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        private_dir = Path(self.temp.name)/"private"
        self.store_path = private_dir/"autorace.sqlite3"
        self.store = LocalPrivateJournal(self.store_path)
        self.now = datetime.fromisoformat("2030-01-15T09:22:00+09:00")
        self.a = sample("autorace",size=8,scope="OPERATOR_SUPPLIED_RESEARCH")
        self.b = deepcopy(self.a)
        self.b["race"]["as_of"] = "2030-01-15T09:20:00+09:00"
        for p in self.b["participants"]:
            val = obs(.25 + p["number"]*.05)
            val["published_at"] = "2030-01-15T09:14:00+09:00"
            val["captured_at"] = "2030-01-15T09:18:00+09:00"
            p["features"]["trial_time_quality"] = val
        self.row = {
            "race_id":self.a["race"]["race_id"],"sport":"autorace",
            "venue":"fictional-venue","race_no":1,
            "cutoff_at":"2030-01-15T10:00:00+09:00",
            "cutoff_verified":True,"source_permission_approved":True,
            "entrants":list(range(1,9)),"trifecta_offered":True}
        self.model="multisport-factor-interaction-v1"
        self.rights=lambda *args: True  # Explicit synthetic stand-in, not a real grant.
        self.observations=lambda *args: True  # Explicit synthetic stand-in.
        self.features=lambda ref,license_ref,purpose: (
            ref=="synthetic://fixture" and license_ref=="synthetic-fixture"
            and purpose=="analysis")
        self.feeds={(self.row["race_id"],phase): self.bundle(phase) for phase in PHASES}

    def bundle(self,phase):
        snapshot=deepcopy(self.a if phase==PHASES[0] else self.b)
        src = {"url":"https://example.test/fictional-authorized-feed",
               "sha256":"d"*64,"snapshot_sha256":digest(snapshot),
               "captured_at":"2030-01-15T08:02:00+09:00" if phase==PHASES[0]
                             else "2030-01-15T09:19:00+09:00",
               "published_at":"2030-01-15T08:00:00+09:00" if phase==PHASES[0]
                             else "2030-01-15T09:14:00+09:00",
               "license_ref":"SYNTHETIC_ONLY_NOT_REAL_RIGHTS",
               "expires_at":"2030-02-01T00:00:00+09:00"}
        return {"schema":SCHEMA,"phase":phase,
                "race_id":self.row["race_id"],"snapshot":snapshot,
                "source":src,"trial_publication":("NOT_YET_PUBLISHED"
                  if phase==PHASES[0] else "PUBLISHED_COMPLETE"),
                "participant_ids":list(range(1,9)), "revision":1}

    def feed(self):
        return local_feed_acquire(self.feeds,clock=lambda:self.now,
            rights_reviewer=self.rights,observation_reviewer=self.observations)

    def do_tick(self):
        # Fake receipt test hook only. The production path MUST replace this
        # with a trusted external server witness and independent timestamp.
        def submit(row,phase,forecast):
            return self.store.submit_once(row["race_id"],phase,forecast)
        def verify(row,phase,forecast):
            return self.store.attest(row["race_id"],phase,forecast,
                {"schema":"SYNTHETIC_TEST_RECEIPT_ONLY"}, 
                independent_verifier=lambda *args: True)
        return tick([self.row], clock=lambda:self.now,
          readback=lambda r,p:self.store.readback(r["race_id"],p,self.model),
          acquire=self.feed(),
          claim=lambda r,p,f:self.store.claim(r["race_id"],p,f),
          submit=submit, verify=verify, authorize_feature=self.features)

    def test_private_storage_permissions_and_stable_identity(self):
        self.assertEqual(stat.S_IMODE(self.store_path.parent.stat().st_mode),0o700)
        self.assertEqual(stat.S_IMODE(self.store_path.stat().st_mode),0o600)
        self.assertEqual(self.store.readback(self.row["race_id"],PHASES[0],self.model)["state"],
                         "ABSENT")
        shared = Path(self.temp.name)/"public"
        shared.mkdir(mode=0o755)
        shared.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "DIRECTORY_NOT_PRIVATE"):
            LocalPrivateJournal(shared/"world-readable.sqlite")

    def test_offline_a_b_stored_and_read_after_restart_and_result_pdca(self):
        first=self.do_tick()
        self.assertEqual([x["state"] for x in first["states"]],
                         ["FROZEN_READBACK_VERIFIED_BY_ADAPTER"]*2)
        self.assertEqual(first["source_acquire_calls"],2)
        a=self.store.original(self.row["race_id"],PHASES[0],self.model)
        b=self.store.original(self.row["race_id"],PHASES[1],self.model)
        self.assertEqual(len(a["ordered_top8"]),8)
        self.assertEqual(len(b["supplemental_four"]),4)
        self.assertNotEqual(a["prediction_sha256"],b["prediction_sha256"])
        self.assertFalse(first["real_provider_polling_enabled"])
        self.store=LocalPrivateJournal(self.store_path)  # Simulate a process restart
        self.assertEqual(self.store.original(self.row["race_id"],PHASES[0],self.model),a)
        self.assertEqual([x["state"] for x in self.do_tick()["states"]],
                         ["ALREADY_FROZEN","ALREADY_FROZEN"])
        with self.assertRaises(ValueError):
            self.store.submit_once(self.row["race_id"],PHASES[0],a)
        self.now=datetime.fromisoformat("2030-01-15T11:00:00+09:00")
        result={"race_id":self.row["race_id"],"status":"FINAL_NORMAL",
                "published_at":"2030-01-15T10:05:00+09:00",
                "captured_at":"2030-01-15T10:06:00+09:00",
                "winning_triples":[a["ordered_top8"][0]],
                "revision":1,"source_sha256":"f"*64}
        def audit(x):
            return audit_cycle([self.row],clock=lambda:self.now,
                load_forecast=lambda row,phase:self.store.original(
                    row["race_id"],phase,self.model),
                load_result=lambda row:x, verify_forecast=lambda *args:True,
                verify_result=lambda *args:True,
                latest_audit=self.store.latest_audit,
                append_audit=self.store.append_audit,
                read_audit=self.store.read_audit)
        report=audit(result)
        self.assertEqual(report["events"][0]["state"],"AUDIT_APPENDED_AND_READBACK")
        self.assertEqual(report["kpis"][PHASES[0]]["hit8_all"],1)
        self.assertEqual(audit(result)["events"][0]["state"],"ALREADY_SAVED")
        fixed={**result,"winning_triples":[[8,7,6]],"revision":2,
               "source_sha256":"a"*64}
        r2=audit(fixed)
        self.assertEqual(r2["events"][0]["revision"],2)
        self.assertEqual(self.store.latest_audit(self.row["race_id"])["revision"],2)
        self.assertEqual(self.store.original(self.row["race_id"],PHASES[0],self.model),a)

    def test_license_rejected_by_default_and_tampered_source_rejected(self):
        envelope=self.bundle(PHASES[0])
        blocked=admit(envelope,race=self.row,phase=PHASES[0],
            clock=lambda:self.now,rights_reviewer=lambda *_:False,
            observation_reviewer=lambda *_:True)
        self.assertEqual(blocked["status"],"RIGHTS_BLOCKED")
        tampered=deepcopy(envelope)
        tampered["snapshot"]["participants"][0]["features"]["ability"]["value"]=.99
        self.assertEqual(admit(tampered,race=self.row,phase=PHASES[0],
            clock=lambda:self.now,rights_reviewer=self.rights,
            observation_reviewer=self.observations)["status"],"UNAVAILABLE")

    def test_publication_and_rights_cannot_be_inferred_from_document(self):
        envelope=self.bundle(PHASES[1])
        envelope["trial_publication"]="NOT_YET_PUBLISHED"
        self.assertEqual(admit(envelope,race=self.row,phase=PHASES[1],
            clock=lambda:self.now,rights_reviewer=self.rights,
            observation_reviewer=self.observations)["status"],"PENDING")
        envelope=self.bundle(PHASES[1])
        self.assertEqual(admit(envelope,race=self.row,phase=PHASES[1],
            clock=lambda:self.now,rights_reviewer=self.rights,
            observation_reviewer=lambda *_:False)["status"],"UNAVAILABLE")
        envelope=self.bundle(PHASES[1])
        envelope["source"]["expires_at"]="2030-01-15T09:30:00+09:00"
        self.assertEqual(admit(envelope,race=self.row,phase=PHASES[1],
            clock=lambda:self.now,rights_reviewer=self.rights,
            observation_reviewer=self.observations)["status"],"UNAVAILABLE")

    def test_uncertain_local_post_is_sticky_and_does_not_fake_attestation(self):
        self.store.claim(self.row["race_id"],PHASES[0],self._make_synthetic_forecast())
        # An independently authenticated receipt is absent, claim remains held.
        self.assertEqual(self.store.readback(self.row["race_id"],PHASES[0],self.model)["state"],
                         "CLAIMED")
        self.assertEqual(self.do_tick()["states"][0]["state"],
                         "UNCERTAIN_OR_RESERVED_DO_NOT_REPOST")

    def _make_synthetic_forecast(self):
        from race_ai.four_sport_model_suite import run_suite
        from race_ai.autorace_ab_pdca import _primary
        suite=run_suite(self.a,allow_source=self.features)
        return _primary(suite,self.model,PHASES[0],self.now)


if __name__=="__main__":
    unittest.main()
