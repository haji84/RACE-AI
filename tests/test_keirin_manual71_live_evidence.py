"""Source-free fail-closed tests for the one-real-race acceptance guard."""
import unittest
from race_ai.keirin_manual71_live_evidence import examine

CIPHER = "a"*64
RESULT = "b"*64
HTML = "c"*64
ROWSET = "d"*64
REV = "e"*64


def simulated():
    return (
        {"state":"CLOUD_PR71_ENCRYPTED_GIT_HISTORY_READBACK_VERIFIED",
         "generation":3,"cipher_sha256":CIPHER,
         "manual71_pilot":{"state":"PRIVATE_MANUAL71_PILOT_RESEARCH_STORED",
                           "new_audits":1,
                           "source_revision_sha256":REV,
                           "audit_rowset_sha256":ROWSET,
                           "latest_html_sha256":HTML,
                           "official_results_authenticated":False}},
        {"state":"PR71_SEPARATE_GITHUB_RUNNER_AES_GCM_READBACK_OK",
         "generation":3,
         "manual71_pilot_readback":{
            "state":"PRIVATE_MANUAL71_AUDIT_SHA_READBACK_VERIFIED",
            "verified_rows":1, "audit_rowset_sha256":ROWSET,
            "latest_html_sha256":HTML,
            "official_results_authenticated":False}},
    )


class PilotLiveGateTest(unittest.TestCase):
    def test_no_live_producer_never_looks_like_a_completed_race(self):
        v=examine(producer={},readback={},action_run_id="44013678282",
                  producer_job_id="cycle",reader_job_id="reader",trusted_main=False)
        self.assertEqual(v["overall"],"HOLD")
        self.assertEqual(sum(x=="PASS" for x in v["gates"].values()),0)

    def test_private_reference_and_encrypted_archive_not_official_result(self):
        p,r=simulated()
        v=examine(producer=p,readback=r,action_run_id="44013678282",
                  producer_job_id="cycle",reader_job_id="reader",trusted_main=True)
        self.assertEqual(v["overall"],"HOLD")
        self.assertEqual(v["gates"]["result_fetch"],"HOLD")
        self.assertEqual(v["gates"]["result_match"],"HOLD")
        self.assertEqual(v["gates"]["encrypted_save"],"PASS")
        self.assertEqual(v["gates"]["fresh_runner_readback"],"PASS")
        self.assertEqual(v["gates"]["html_display"],"HOLD")

    def test_same_job_cannot_pass_fresh_runner(self):
        p,r=simulated()
        v=examine(producer=p,readback=r,action_run_id="44013678282",
                  producer_job_id="cycle",reader_job_id="cycle",trusted_main=True)
        self.assertEqual(v["gates"]["fresh_runner_readback"],"HOLD")

    def test_different_generation_never_passes_readback(self):
        p,r=simulated()
        r["generation"]=4
        v=examine(producer=p,readback=r,action_run_id="44013678282",
                  producer_job_id="cycle",reader_job_id="reader",trusted_main=True)
        self.assertEqual(v["gates"]["encrypted_save"],"PASS")
        self.assertEqual(v["gates"]["fresh_runner_readback"],"HOLD")

    def test_ordinary_html_sha_and_flag_cannot_fake_browser_evidence(self):
        p,r=simulated()
        v=examine(producer=p,readback=r,action_run_id="44013678282",
                  producer_job_id="cycle",reader_job_id="reader",trusted_main=True,
                  viewer_receipt={"race_id":"202611177507",
                                  "encrypted_generation":3,
                                  "rendered_html_sha256":HTML,
                                  "browser_opened":True})
        self.assertEqual(v["gates"]["html_display"],"HOLD")

    def test_a_wrong_race_source_does_not_attest_a_result(self):
        p,r=simulated()
        v=examine(producer=p,readback=r,action_run_id="44013678282",
                  producer_job_id="cycle",reader_job_id="reader",trusted_main=True,
                  source_receipt={"race_id":"202611177506",
                                  "result_revision_sha256":REV},
                  independently_verify_source=lambda x: True)
        self.assertEqual(v["gates"]["result_fetch"],"HOLD")

    def test_callbacks_are_required_and_are_not_replaced_by_boolean_flags(self):
        p,r=simulated()
        src={"race_id":"202611177507","result_revision_sha256":REV,
             "official":True}
        v=examine(producer=p,readback=r,action_run_id="44013678282",
                  producer_job_id="cycle",reader_job_id="reader",trusted_main=True,
                  source_receipt=src)
        self.assertEqual(v["gates"]["result_fetch"],"HOLD")

    def test_hypothetical_complete_evidence_has_all_five_contracts(self):
        # Fictional synthetic proof only. No official data, actual Actions
        # run, authorized source, or browser is created by this unit test.
        p,r=simulated()
        v=examine(producer=p,readback=r,action_run_id="44013678282",
                  producer_job_id="cycle",reader_job_id="reader",trusted_main=True,
                  source_receipt={"race_id":"202611177507",
                                  "result_revision_sha256":REV},
                  independently_verify_source=lambda x: True,
                  viewer_receipt={"race_id":"202611177507",
                                  "encrypted_generation":3,
                                  "rendered_html_sha256":HTML},
                  independently_verify_browser=lambda x: True)
        self.assertEqual(v["overall"],"PASS")
        self.assertFalse(v["expanded_to_71"])

    def test_wrong_result_revision_same_race_must_not_pass_source(self):
        p,r=simulated()
        v=examine(producer=p,readback=r,action_run_id="44013678282",
                  producer_job_id="cycle",reader_job_id="reader",trusted_main=True,
                  source_receipt={"race_id":"202611177507",
                                  "result_revision_sha256":RESULT},
                  independently_verify_source=lambda x: True)
        self.assertEqual(v["gates"]["result_fetch"],"HOLD")

    def test_archive_and_reader_rowset_must_match(self):
        p,r=simulated()
        r["manual71_pilot_readback"]["audit_rowset_sha256"]=RESULT
        v=examine(producer=p,readback=r,action_run_id="44013678282",
                  producer_job_id="cycle",reader_job_id="reader",trusted_main=True)
        self.assertEqual(v["gates"]["fresh_runner_readback"],"HOLD")

if __name__=="__main__":
    unittest.main()
