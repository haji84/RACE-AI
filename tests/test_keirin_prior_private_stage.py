"""Synthetic prior-result source lineage and private create-once replay tests.

No authentic vendor rights, real forecast, plaintext Git artifact or purchase.
"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import os
import unittest

from race_ai.keirin_winticket_prior_events import observed_prior_candidates, PriorSourceError
from race_ai.keirin_prior_private_stage import (
    private_research_packet, stage_owner_private_prior_research,
    read_private_research_packet,
)
from tests.test_keirin_winticket_prior_events import (
    PriorEventContractTests, CAPTURE, TARGET,
)


class PriorPrivateStagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reference = PriorEventContractTests().refs()
        self.events = [PriorEventContractTests().result()]
        self.derived = observed_prior_candidates(
            self.reference,self.events,as_of=CAPTURE)
        self.cardsha = sha256(b'FICTIONAL-RACECARD').hexdigest()
        self.idxsha = sha256(b'FICTIONAL-PUBLISHED-INDEX').hexdigest()

    def packet(self):
        return private_research_packet(
            self.reference,self.events,self.derived,
            racecard_sha256=self.cardsha,day_index_sha256=self.idxsha,
            as_of=CAPTURE)

    def test_private_original_bound_to_each_prior_source_sha_and_replayable(self):
        packet=self.packet()
        with patch.dict(os.environ,{"GITHUB_WORKSPACE":""}):
            created=stage_owner_private_prior_research(self.root,packet)
            repeated=stage_owner_private_prior_research(self.root,packet)
        self.assertTrue(created["new_private_packet"])
        self.assertFalse(repeated["new_private_packet"])
        self.assertEqual(created["private_packet_sha256"],
                         repeated["private_packet_sha256"])
        self.assertFalse(created["approved_for_pr71_input"])
        self.assertFalse(created["production_aes_archived"])
        self.assertFalse(created["official_predictions_generated"])
        self.assertEqual(created["past_results_preserved"],1)
        record=self.root/"keirin_prior_research"/(
            created["private_packet_sha256"]+".json")
        read=read_private_research_packet(
            record,expected_sha256=created["private_packet_sha256"])
        self.assertEqual(read["target_race_id"],TARGET)
        self.assertEqual(read["candidate_snapshot"],self.derived)
        self.assertEqual(read["prior_events"],self.events)
        self.assertNotIn("fiction-",str(created))
        self.assertNotIn("12.1",str(created))
        self.assertEqual(len(list(record.parent.glob("*.json"))),1)

    def test_public_git_checkout_private_storage_refused(self):
        root=self.root/"public"
        root.mkdir()
        inside=root/"evidence"
        inside.mkdir()
        with patch.dict(os.environ,{"GITHUB_WORKSPACE":str(root)}):
            with self.assertRaisesRegex(PriorSourceError,
                                         "PUBLIC_GIT_CHECKOUT_PRIVATE_RESULTS_FORBIDDEN"):
                stage_owner_private_prior_research(inside,self.packet())
        self.assertFalse((inside/"keirin_prior_research").exists())

    def test_tamper_existing_private_packet_rejected_not_overwritten(self):
        packet=self.packet()
        with patch.dict(os.environ,{"GITHUB_WORKSPACE":""}):
            created=stage_owner_private_prior_research(self.root,packet)
            file=self.root/"keirin_prior_research"/(
                created["private_packet_sha256"]+".json")
            original=file.read_bytes()
            file.write_bytes(original+b' ')
            with self.assertRaises(PriorSourceError):
                stage_owner_private_prior_research(self.root,packet)
            self.assertEqual(file.read_bytes(),original+b' ')

    def test_source_cannot_forge_later_candidate_or_self_approve(self):
        injected=deepcopy(self.derived)
        injected["riders"]["fiction-1"]["features"]["finishing_power"][
            "candidate_value"]=0.99
        with self.assertRaisesRegex(PriorSourceError,
                                    "PRIOR_CANDIDATE_REPLAY_OR_ADMISSION_CONFLICT"):
            private_research_packet(
                self.reference,self.events,injected,
                racecard_sha256=self.cardsha,day_index_sha256=self.idxsha,
                as_of=CAPTURE)
        approved=deepcopy(self.derived)
        approved["model_input_admitted"]=True
        with self.assertRaises(PriorSourceError):
            private_research_packet(
                self.reference,self.events,approved,
                racecard_sha256=self.cardsha,day_index_sha256=self.idxsha,
                as_of=CAPTURE)

    def test_future_or_unrelated_prior_page_not_staged(self):
        future=deepcopy(self.events)
        future[0]["result_captured_at"]="2030-01-15T09:26:00+09:00"
        with self.assertRaises(PriorSourceError):
            private_research_packet(
                self.reference,future,self.derived,
                racecard_sha256=self.cardsha,day_index_sha256=self.idxsha,
                as_of=CAPTURE)
        unrelated=deepcopy(self.events)
        unrelated[0]["result_source_url"]="https://example.invalid/unrelated"
        with self.assertRaisesRegex(PriorSourceError,
                                   "PAST_RESULT_NOT_BOUND_TO_CAPTURED_REFERENCE"):
            private_research_packet(
                self.reference,unrelated,self.derived,
                racecard_sha256=self.cardsha,day_index_sha256=self.idxsha,
                as_of=CAPTURE)

    def test_source_url_and_race_identity_cannot_be_collusively_swapped(self):
        # Matching fake reference URLs and event URLs must still be rejected.
        refs=deepcopy(self.reference)
        refs["references"][0]["url"]="https://example.invalid/old/result"
        events=deepcopy(self.events)
        events[0]["result_source_url"]=refs["references"][0]["url"]
        with self.assertRaises(PriorSourceError):
            private_research_packet(
                refs,events,self.derived,racecard_sha256=self.cardsha,
                day_index_sha256=self.idxsha,as_of=CAPTURE)

    def test_source_probe_stage_returns_only_replay_counts_and_sha(self):
        from datetime import datetime
        from scripts import keirin_prior_real_input_probe as probe
        target_url=(
            "https://www.winticket.jp/keirin/aomori/racecard/2030011312/3/3"
        )
        past_url=self.reference["references"][0]["url"]
        pages={target_url:b"FICTIONAL CARD",
               "https://www.winticket.jp/keirin/odds/20300115":b"FICTIONAL INDEX",
               past_url:b"FICTIONAL PAST RESULT"}
        requests=[]
        def fake_get(url):
            requests.append(url)
            return pages[url]
        roster={"riders":[{"source_player_id":rid}
                          for rid in self.reference["rider_ids"]]}
        with patch.dict(os.environ,{"GITHUB_WORKSPACE":""}),patch.object(
                probe,"racecard_from_public_html",return_value=roster
        ),patch.object(
                probe,"documents_from_html",return_value=[{"records":[]}]
        ),patch.object(
                probe,"history_references",return_value=self.reference
        ),patch.object(
                probe,"normalize_result_event",return_value=self.events[0]
        ):
            safe=probe.probe(
                race_id=TARGET,racecard_url=target_url,max_pages=3,
                fetch=fake_get,
                clock=lambda:datetime.fromisoformat(CAPTURE),
                private_evidence_dir=self.root)
        self.assertEqual(len(requests),3)
        self.assertTrue(safe["private_candidate_packet_saved"])
        self.assertTrue(safe["private_candidate_replay_verified"])
        self.assertFalse(safe["private_candidate_encrypted_git_archived"])
        self.assertFalse(safe["actual_four_model_forecast_saved"])
        self.assertEqual(safe["prior_result_pages_verified"],1)
        self.assertNotIn("fiction-",str(safe))
        self.assertNotIn("FICTIONAL PAST RESULT",str(safe))
        out=self.root/"keirin_prior_research"/(
            safe["private_candidate_packet_sha256"]+".json")
        private=read_private_research_packet(
            out,expected_sha256=safe["private_candidate_packet_sha256"])
        self.assertEqual(private["racecard_original_sha256"],
                         sha256(pages[target_url]).hexdigest())
        self.assertEqual(private["day_index_original_sha256"],
                         sha256(pages[requests[1]]).hexdigest())
        self.assertFalse(private["provider_automated_training_rights_verified"])

    def test_symlink_rejected_and_untrusted_full_public_payload_never_returned(self):
        with patch.dict(os.environ,{"GITHUB_WORKSPACE":""}):
            root=self.root/"owner"
            root.mkdir()
            (root/"keirin_prior_research").symlink_to(self.root,
                                                      target_is_directory=True)
            with self.assertRaisesRegex(PriorSourceError,
                                        "PRIOR_PRIVATE_DIR_SYMLINK_FORBIDDEN"):
                stage_owner_private_prior_research(root,self.packet())
            self.assertFalse(list(self.root.glob("*.json")))


if __name__=="__main__":
    unittest.main()
