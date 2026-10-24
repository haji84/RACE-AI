"""Fictional archive bytes -> existing B-stage transport tests only.

Neither the fake extractor nor mock normalizer validates a real LZH. No
BOATRACE data is collected; rights and pre-cutoff save are NOT authenticated.
"""
import copy
import hashlib
import tempfile
from pathlib import Path
import unittest

from race_ai.boat_b_offline_archive_intake import stage_supplied_b_archive
from race_ai.comprehensive_four_sport_models import digest
from race_ai.permissioned_source_delivery import SourceDeliveryError, PermissionPolicy
from tests.test_boat_b_program_bridge import (
    BURL, B_RIGHTS, AT, CAPTURE, RACE, DAY, b_handoff, approved_policy
)
from tests.test_permissioned_source_delivery import policy_doc, KEY

PR64_REF = "haji84/RACE-AI@27f3df12ddca3971833d4dbf03f6fbcc88df6b07:official_b_snapshot_adapter"
RAW = b"FICTIONAL_ARCHIVE_DO_NOT_TREAT_AS_REAL_LZH_" * 3
TEXT = b"FICTIONAL_EXTRACTED_B_PROGRAM_TEXT_DO_NOT_TREAT_AS_REAL" * 2


def fake_extractor(raw, expected_name):
    assert raw == RAW and expected_name == "B300115.TXT"
    return TEXT


def fake_normalizer(text, *, day, source_url, observed_at,
                    require_details, archive_sha256):
    assert text == TEXT and str(day) == DAY and require_details is True
    parsed = copy.deepcopy(b_handoff()["extract"])
    parsed["source_url"] = source_url
    parsed["source_sha256"] = archive_sha256
    parsed["extracted_text_sha256"] = hashlib.sha256(text).hexdigest()
    parsed["source_hash_scope"] = "downloaded_archive"
    parsed["first_observed_at"] = observed_at
    return parsed


def run(path, **overrides):
    kwargs = {
        "day": DAY, "source_url": BURL, "observed_at": CAPTURE,
        "rights_ref": B_RIGHTS, "parser_ref": PR64_REF, "race_id": RACE,
        "policy": approved_policy(), "now": AT,
        "extract_lzh": fake_extractor, "normalize_b": fake_normalizer
    }
    kwargs.update(overrides)
    return stage_supplied_b_archive(path, **kwargs)


class BoatBOfflineArchiveIntakeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "fictional-b.lzh"
        self.path.write_bytes(RAW)

    def tearDown(self):
        self.folder.cleanup()

    def test_offline_byte_hash_and_previous_pr64_parser_contract(self):
        out = run(self.path)
        self.assertEqual(out["source_archive_sha256"], hashlib.sha256(RAW).hexdigest())
        self.assertEqual(out["extracted_text_sha256"], hashlib.sha256(TEXT).hexdigest())
        self.assertEqual(out["source_url"], BURL)
        self.assertEqual(out["program_stage"]["known_b_races"], 12)
        self.assertEqual(out["program_stage"]["race_id"], RACE)
        self.assertEqual(out["receipt_sha256"],
                         digest({k:v for k,v in out.items() if k != "receipt_sha256"}))
        self.assertFalse(out["eligible_hit_at_8"])
        self.assertFalse(out["official_prediction"])
        self.assertFalse(out["official_b_bytes_independently_authenticated"])
        self.assertIsNone(out["external_freeze_receipt"])

    def test_missing_reviewed_purpose_rejected_before_extraction(self):
        policy=PermissionPolicy(policy_doc(),KEY,at=AT)
        def never_extract(*args):
            raise AssertionError("read without approved source grant")
        with self.assertRaisesRegex(SourceDeliveryError,"B_SOURCE_PERMISSION_NOT_ADMITTED"):
            run(self.path,policy=policy,extract_lzh=never_extract)

    def test_reject_host_mismatch_and_malformed_parser_reference(self):
        with self.assertRaisesRegex(SourceDeliveryError,"B_SOURCE_NOT_OFFICIAL"):
            run(self.path,source_url="https://private.invalid/od2/B/203001/b300115.lzh")
        with self.assertRaisesRegex(SourceDeliveryError,"PARSER_CALLBACKS_REQUIRED"):
            run(self.path,parser_ref="haji84/RACE-AI@HEAD:official_b_snapshot_adapter")

    def test_refuse_parser_that_renames_source_or_forges_hash(self):
        def bad_sha(*args, **kwargs):
            row = fake_normalizer(*args,**kwargs)
            row["extracted_text_sha256"]="0"*64
            return row
        with self.assertRaisesRegex(SourceDeliveryError,"SHA_MISMATCH"):
            run(self.path,normalize_b=bad_sha)
        def bad_source(*args, **kwargs):
            row=fake_normalizer(*args,**kwargs)
            row["source_url"]="https://not-source.example/other.lzh"
            return row
        with self.assertRaisesRegex(SourceDeliveryError,"SHA_MISMATCH"):
            run(self.path,normalize_b=bad_source)

    def test_no_fabricated_late_pre_cutoff_prediction(self):
        result=run(self.path,now="2030-01-15T10:30:00+09:00")
        self.assertEqual(result["program_stage"]["status"],"MISSED_DEADLINE")
        self.assertEqual(result["status"],"MISSED_DEADLINE_NOT_FROZEN")
        self.assertFalse(result["eligible_hit_at_8"])

    def test_truncated_and_excessive_raw_file_blocked(self):
        self.path.write_bytes(b"short")
        with self.assertRaisesRegex(SourceDeliveryError,"SIZE_INVALID"):
            run(self.path)
        self.path.write_bytes(b"x"*(4*1024*1024+1))
        with self.assertRaisesRegex(SourceDeliveryError,"SIZE_INVALID"):
            run(self.path)

    def test_extracted_data_and_unknown_callable_cannot_pass(self):
        def no_text(*_args):
            return b""
        with self.assertRaisesRegex(SourceDeliveryError,"TEXT_SIZE_INVALID"):
            run(self.path,extract_lzh=no_text)
        with self.assertRaisesRegex(SourceDeliveryError,"PARSER_CALLBACKS_REQUIRED"):
            run(self.path,extract_lzh=None)

    def test_no_upload_network_or_private_raw_bytes_saved_by_adapter(self):
        out=run(self.path)
        self.assertNotIn("bytes",out)
        self.assertNotIn("raw_archive",out)
        self.assertEqual(sorted(p.name for p in Path(self.folder.name).iterdir()),
                         ["fictional-b.lzh"])


if __name__ == "__main__":
    unittest.main()
