"""Read-only verification of two owner-private Takeo 2R *draft* review packets.

Verify actual file SHA256, payload binding, 46 decoded BGR-crop frame\nSHA256 values, displayed PNG bytes and A/B concordance. The declared source-video/frame SHA is not by itself a replay
verification of the raw video, and two pending drafts are NOT two reviewers.
No internet, no private pixels in output, no model/PDCA changes.
"""
from __future__ import annotations

import argparse
import base64
from hashlib import sha256
import json
from pathlib import Path
import re

import cv2
import numpy as np

SCHEMA = "RACE_AI_KEIRIN_REAL_TAKEO_REVIEW_READINESS_V1"
HEX = re.compile(r"^[a-f0-9]{64}$")
PAYLOAD = re.compile(
    r'<script id="payload" type="application/json">(.*?)</script>',
    re.DOTALL)
PNG = b"\x89PNG\r\n\x1a\n"


class ReviewReadinessError(ValueError):
    pass


def need(ok, code):
    if not ok:
        raise ReviewReadinessError(code)


def is_sha(s):
    return type(s) is str and HEX.fullmatch(s) is not None


def inspect_html(path, *, expected_sha, race_id, video_sha, proposal_sha,
                 expected_reviewer):
    need(all(is_sha(x) for x in (expected_sha, video_sha, proposal_sha)),
         "EXPECTED_SHA_INVALID")
    p = Path(path)
    need(p.is_file() and not p.is_symlink() and p.stat().st_size <= 25_000_000,
         "PRIVATE_HTML_MISSING_OR_OVERSIZED")
    raw = p.read_bytes()
    actual = sha256(raw).hexdigest()
    need(actual == expected_sha, "PRIVATE_HTML_BYTE_SHA_MISMATCH")
    try:
        html = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ReviewReadinessError("PRIVATE_HTML_UTF8_INVALID") from None
    matches = list(PAYLOAD.finditer(html))
    need(len(matches) == 1, "ONE_BLIND_DRAFT_PAYLOAD_REQUIRED")
    try:
        payload = json.loads(matches[0].group(1))
    except (ValueError, TypeError):
        raise ReviewReadinessError("PRIVATE_BLIND_DRAFT_JSON_INVALID") from None
    need(type(payload) is dict and set(payload) == {
        "draft_schema", "race_id", "recording_sha256", "proposal_sha256",
        "reviewer_id", "target_kind", "packet_manifest_sha256", "frames"},
        "BLIND_DRAFT_SCHEMA_MISMATCH")
    need(
        payload["draft_schema"] ==
        "RACE_AI_KEIRIN_PRIVATE_BLIND_ANNOTATION_DRAFT_V1" and
        payload["race_id"] == race_id and
        payload["recording_sha256"] == video_sha and
        payload["proposal_sha256"] == proposal_sha and
        payload["reviewer_id"] == expected_reviewer and
        payload["target_kind"] == "JERSEY_COLOR_REGION" and
        is_sha(payload["packet_manifest_sha256"]),
        "BLIND_DRAFT_RACE_PROPOSAL_OR_REVIEWER_MISMATCH")
    frames = payload["frames"]
    need(type(frames) is list and len(frames) == 46,
         "EXACT_46_DISPLAYED_FRAMES_REQUIRED")
    checked = []
    for index, frame in enumerate(frames):
        need(type(frame) is dict and set(frame) ==
             {"frame_sha256", "recording_sec", "image_data_url"},
             "PRIVATE_FRAME_METADATA_INVALID")
        need(is_sha(frame["frame_sha256"]) and
             type(frame["recording_sec"]) in (int, float) and
             frame["recording_sec"] == index * 2,
             "PRIVATE_FRAME_SHA_OR_SECONDS_INVALID")
        url = frame["image_data_url"]
        need(type(url) is str and url.startswith("data:image/png;base64,"),
             "PRIVATE_FRAME_MUST_BE_LOCAL_PNG")
        try:
            png_bytes = base64.b64decode(
                url[len("data:image/png;base64,"):], validate=True)
        except (ValueError, base64.binascii.Error):
            raise ReviewReadinessError("PRIVATE_FRAME_BASE64_INVALID") from None
        need(png_bytes.startswith(PNG) and len(png_bytes) >= 24,
             "PRIVATE_FRAME_PNG_INVALID")
        # OpenCV encodes/decodes these owner-private source crops in BGR.
        # Compare the actual decoded pixels against the frozen frame SHA,
        # not merely equal PNG files that might share a forged frame ID.
        pixels = cv2.imdecode(
            np.frombuffer(png_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        need(pixels is not None and pixels.ndim == 3 and
             pixels.shape[2] == 3 and
             0 < pixels.shape[0] <= 2160 and 0 < pixels.shape[1] <= 3840,
             "PRIVATE_FRAME_PNG_DECODE_OR_SHAPE_INVALID")
        need(sha256(pixels.tobytes()).hexdigest() == frame["frame_sha256"],
             "PRIVATE_FRAME_SOURCE_BGR_SHA_MISMATCH")
        checked.append((frame["frame_sha256"],
                        frame["recording_sec"],
                        sha256(png_bytes).hexdigest()))
    need(len({x[0] for x in checked}) == len(checked),
         "PRIVATE_FRAME_SHA_REUSED")
    return {
        "file_sha256": actual,
        "reviewer_id": expected_reviewer,
        "manifest_claim_sha256": payload["packet_manifest_sha256"],
        "race_id": race_id,
        "video_declared_sha256": payload["recording_sha256"],
        "proposal_declared_sha256": payload["proposal_sha256"],
        "displayed_frame_count": len(checked),
        "_frame_fingerprints": checked,
    }


def inspect_pair(a, b, *, expected_a_sha, expected_b_sha, race_id,
                 video_sha, proposal_sha):
    first = inspect_html(a, expected_sha=expected_a_sha, race_id=race_id,
                         video_sha=video_sha, proposal_sha=proposal_sha,
                         expected_reviewer="reviewer_A_pending")
    second = inspect_html(b, expected_sha=expected_b_sha, race_id=race_id,
                          video_sha=video_sha, proposal_sha=proposal_sha,
                          expected_reviewer="reviewer_B_pending")
    need(first["file_sha256"] != second["file_sha256"] and
         first["manifest_claim_sha256"] != second["manifest_claim_sha256"],
         "REVIEW_PACKETS_NOT_SEPARATE")
    paired = sum(x == y for x, y in zip(first["_frame_fingerprints"],
                                       second["_frame_fingerprints"]))
    need(paired == 46, "REVIEW_PACKET_VISIBLE_FRAME_BYTES_MISMATCH")
    return {
        "schema": SCHEMA,
        "race_id": race_id,
        "source_video_sha256": video_sha,
        "source_video_sha_is_declared_not_newly_replayed": True,
        "frozen_color_proposal_sha256": proposal_sha,
        "html_a_sha256_verified": first["file_sha256"],
        "html_b_sha256_verified": second["file_sha256"],
        "distinct_packet_manifest_claims": True,
        "displayed_frames_per_packet": 46,
        "decoded_BGR_pixel_source_sha_matches_each_packet": 46,
        "frame_png_bytes_and_declared_frame_id_equal_pairs": paired,
        "independent_signed_reviews_present": 0,
        "independent_reviewers_verified": 0,
        "actual_follow_outcome_labels_verified": 0,
        "state": "HOLD_PENDING_TWO_INDEPENDENT_REVIEWS_AND_TACTICAL_LABELS",
        "no_frame_pixels_or_private_coordinate_data_exported": True,
        "no_training_or_prospective_forecast_promotion": True,
    }


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--html-a", type=Path, required=True)
    p.add_argument("--html-b", type=Path, required=True)
    p.add_argument("--sha-a", required=True)
    p.add_argument("--sha-b", required=True)
    p.add_argument("--video-sha", required=True)
    p.add_argument("--proposal-sha", required=True)
    p.add_argument("--race-id", required=True)
    p.add_argument("--report", type=Path)
    x = p.parse_args(argv)
    result = inspect_pair(
        x.html_a, x.html_b, expected_a_sha=x.sha_a, expected_b_sha=x.sha_b,
        race_id=x.race_id, video_sha=x.video_sha,
        proposal_sha=x.proposal_sha)
    text = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if x.report:
        need(x.report.parent.is_dir() and not x.report.is_symlink() and
             not x.report.exists(), "REPORT_MUST_BE_CREATE_ONCE")
        x.report.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
