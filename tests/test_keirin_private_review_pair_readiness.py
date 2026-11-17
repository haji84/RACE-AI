"""Source-free checks of the non-promoting owner-private review readiness gate."""
import base64
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from scripts import keirin_private_review_pair_readiness as gate

VIDEO = "a" * 64
PROPOSAL = "b" * 64
RACE = "202611098402"


def make_html(name, *, one_frame_changed=False):
    png = b"\x89PNG\r\n\x1a\n" + b"fake-source-free-payload"
    frames = []
    for i in range(46):
        image = png + (b"CHANGED" if one_frame_changed and i == 7 else b"")
        frames.append({
            "frame_sha256": f"{i+1:064x}",
            "recording_sec": i * 2,
            "image_data_url": "data:image/png;base64," +
            base64.b64encode(image).decode("ascii"),
        })
    payload = {
        "draft_schema": "RACE_AI_KEIRIN_PRIVATE_BLIND_ANNOTATION_DRAFT_V1",
        "race_id": RACE, "recording_sha256": VIDEO,
        "proposal_sha256": PROPOSAL, "reviewer_id": name,
        "target_kind": "JERSEY_COLOR_REGION",
        "packet_manifest_sha256":
            ("c" if name.startswith("reviewer_A") else "d") * 64,
        "frames": frames}
    return ('<!doctype html><script id="payload" type="application/json">' +
            json.dumps(payload, separators=(",", ":")) + "</script>")


class RealPrivatePacketGate(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.a, self.b = [Path(self.t.name, n) for n in ("a.html", "b.html")]
        self.a.write_text(make_html("reviewer_A_pending"), encoding="utf-8")
        self.b.write_text(make_html("reviewer_B_pending"), encoding="utf-8")

    def run_check(self, **kwargs):
        v = dict(a=self.a, b=self.b,
                 expected_a_sha=sha256(self.a.read_bytes()).hexdigest(),
                 expected_b_sha=sha256(self.b.read_bytes()).hexdigest(),
                 race_id=RACE, video_sha=VIDEO, proposal_sha=PROPOSAL)
        v.update(kwargs)
        return gate.inspect_pair(**v)

    def test_exact_drafts_match_but_do_not_count_as_reviews(self):
        r = self.run_check()
        self.assertEqual(r["displayed_frames_per_packet"], 46)
        self.assertEqual(r["frame_png_bytes_and_declared_frame_id_equal_pairs"], 46)
        self.assertEqual(r["independent_signed_reviews_present"], 0)
        self.assertEqual(r["actual_follow_outcome_labels_verified"], 0)
        self.assertIn("HOLD", r["state"])

    def test_modified_file_rejected_against_previous_source_receipt(self):
        old = sha256(self.a.read_bytes()).hexdigest()
        self.a.write_text(self.a.read_text() + "\n", encoding="utf-8")
        with self.assertRaisesRegex(
                gate.ReviewReadinessError, "BYTE_SHA_MISMATCH"):
            self.run_check(expected_a_sha=old)

    def test_different_png_same_declared_frame_sha_rejected(self):
        self.b.write_text(make_html("reviewer_B_pending", one_frame_changed=True),
                          encoding="utf-8")
        with self.assertRaisesRegex(
                gate.ReviewReadinessError, "VISIBLE_FRAME_BYTES_MISMATCH"):
            self.run_check()

    def test_review_a_cannot_impersonate_review_b(self):
        self.b.write_text(make_html("reviewer_A_pending"), encoding="utf-8")
        with self.assertRaisesRegex(
                gate.ReviewReadinessError, "REVIEWER_MISMATCH"):
            self.run_check()

    def test_late_or_changed_video_lineage_is_rejected(self):
        with self.assertRaisesRegex(
                gate.ReviewReadinessError, "PROPOSAL_OR_REVIEWER_MISMATCH"):
            self.run_check(video_sha="e" * 64)

    def test_original_sha_is_not_inferred_from_png(self):
        r = self.run_check()
        self.assertTrue(r["source_video_sha_is_declared_not_newly_replayed"])
        self.assertTrue(r["no_training_or_prospective_forecast_promotion"])


if __name__ == "__main__":
    unittest.main()
