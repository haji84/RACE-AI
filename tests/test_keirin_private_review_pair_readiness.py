"""Source-free checks of the non-promoting owner-private review readiness gate."""
import base64
import re

import cv2
import numpy as np
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
    frames = []
    for i in range(46):
        original = np.zeros((8, 12, 3), dtype=np.uint8)
        original[:, :] = (i + 1, (i * 3) % 255, (i * 5) % 255)
        displayed = original.copy()
        if one_frame_changed and i == 7:
            displayed[2, 4, 0] = (int(displayed[2, 4, 0]) + 1) % 255
        ok, png = cv2.imencode(".png", displayed)
        if not ok:
            raise AssertionError("synthetic PNG encode failed")
        frames.append({
            "frame_sha256": sha256(original.tobytes()).hexdigest(),
            "recording_sec": i * 2,
            "image_data_url": "data:image/png;base64," +
            base64.b64encode(png.tobytes()).decode("ascii"),
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
        self.assertEqual(r["decoded_BGR_pixel_source_sha_matches_each_packet"], 46)
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
                gate.ReviewReadinessError, "PRIVATE_FRAME_SOURCE_BGR_SHA_MISMATCH"):
            self.run_check()

    def test_equal_png_but_forged_frame_sha_rejected(self):
        text = self.b.read_text(encoding="utf-8")
        match = re.search(
            r'(<script id="payload" type="application/json">)(.*?)(</script>)',
            text, re.DOTALL)
        self.assertIsNotNone(match)
        data = json.loads(match.group(2))
        data["frames"][3]["frame_sha256"] = "f" * 64
        self.b.write_text(
            text[:match.start(2)] + json.dumps(data, separators=(",", ":")) +
            text[match.end(2):], encoding="utf-8")
        with self.assertRaisesRegex(
                gate.ReviewReadinessError, "PRIVATE_FRAME_SOURCE_BGR_SHA_MISMATCH"):
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
