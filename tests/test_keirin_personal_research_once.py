"""No-network, fictional tests for private personal one-race evaluation."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

from tests.test_keirin_candidate_audit import fixture, RID, CUTOFF
from race_ai.keirin_personal_research_once import (
    PersonalResearchError, compare_personal_once, read_private_json,
    save_private_once
)


class PersonalModeTests(unittest.TestCase):
    def test_private_one_result_without_licence_receipt(self):
        src, ref = fixture()
        original = copy.deepcopy(ref)
        result = compare_personal_once(
            result_probe=src, original_reference=ref,
            race_id=RID, cutoff_at=CUTOFF,
            personal_scope="USER_PRIVATE_NONCOMMERCIAL_RESEARCH")
        self.assertFalse(result["research_comparison"]["research_hit8"])
        self.assertTrue(result["user_private_use_no_individual_license_token_required"])
        self.assertFalse(result["provider_automated_fetch_rights_claimed"])
        self.assertIsNone(result["formal_hit_at_8_all"])
        self.assertFalse(result["new_future_prediction_saved"])
        self.assertEqual(ref, original)

    def test_personal_mode_is_explicit_and_not_commercial(self):
        src, ref = fixture()
        for bad in ("", "COMMERCIAL", "UNLIMITED_SCRAPING", None):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(PersonalResearchError, "PERSONAL_NONCOMMERCIAL_SCOPE_REQUIRED"):
                    compare_personal_once(result_probe=src,
                        original_reference=ref, race_id=RID,
                        cutoff_at=CUTOFF, personal_scope=bad)

    def test_invalid_or_late_source_cannot_count_as_a_hit(self):
        src, ref = fixture()
        src["candidate_result"]["state"] = "NO_UNAMBIGUOUS_TRIFECTA"
        with self.assertRaises(PersonalResearchError):
            compare_personal_once(result_probe=src,
                original_reference=ref, race_id=RID,
                cutoff_at=CUTOFF,
                personal_scope="USER_PRIVATE_NONCOMMERCIAL_RESEARCH")

    def test_result_and_reference_must_match_race(self):
        src, ref = fixture()
        with self.assertRaises(PersonalResearchError):
            compare_personal_once(result_probe=src,
                original_reference=ref, race_id="202611033602",
                cutoff_at=CUTOFF,
                personal_scope="USER_PRIVATE_NONCOMMERCIAL_RESEARCH")

    def test_save_once_cannot_overwrite_and_mode_is_private(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"audit.json"
            sample={"scope":"USER_PRIVATE_NONCOMMERCIAL_RESEARCH","ok":True}
            info=save_private_once(sample, path)
            self.assertEqual(info["status"],"PERSONAL_RESEARCH_SAVED_ONCE")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")),sample)
            if os.name == "posix":
                self.assertEqual(path.stat().st_mode & 0o777,0o600)
            with self.assertRaisesRegex(PersonalResearchError,"CREATE_ONLY_OUTPUT_EXISTS"):
                save_private_once({"ok":False}, path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")),sample)

    def test_input_readback_and_size_limit(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"reference.json"
            path.write_text('{"safe": true}', encoding="utf-8")
            self.assertEqual(read_private_json(path, limit=1024),{"safe":True})
            with self.assertRaisesRegex(PersonalResearchError,"INPUT_TOO_LARGE"):
                read_private_json(path,limit=4)
            if hasattr(os, "symlink"):
                alias=Path(d)/"alias.json"
                try:
                    os.symlink(path,alias)
                except OSError:
                    return
                with self.assertRaisesRegex(PersonalResearchError,"REGULAR_PRIVATE_INPUT_REQUIRED"):
                    read_private_json(alias,limit=1024)

    def test_real_reference_shape_without_fake_external_stamp(self):
        src,ref=fixture()
        ref["version"]="20261103-am-reference-v1"
        result=compare_personal_once(result_probe=src,original_reference=ref,
             race_id=RID,cutoff_at=CUTOFF,
             personal_scope="USER_PRIVATE_NONCOMMERCIAL_RESEARCH")
        self.assertFalse(result["third_party_result_authenticated"])
        self.assertFalse(result["research_comparison"]["third_party_forecast_freeze_verified"])

    def test_personal_one_get_then_compare_without_licence_token(self):
        from unittest.mock import patch
        from race_ai.keirin_personal_research_once import one_private_fetch_and_compare
        src,ref=fixture()
        with patch("race_ai.keirin_mobile_one_shot.probe_one",
                   return_value=src) as mocked:
            output=one_private_fetch_and_compare(
                original_reference=ref,
                race_id=RID, cutoff_at=CUTOFF,
                ymd="20261103", venue_code=36, race_no=1,
                personal_scope="USER_PRIVATE_NONCOMMERCIAL_RESEARCH",
                one_get_acknowledgement="USER_EXPLICIT_ONE_RESULT_GET")
            self.assertFalse(output["research_comparison"]["research_hit8"])
            self.assertEqual(mocked.call_count, 1)
            self.assertEqual(mocked.call_args.kwargs["route"], "legacy")

    def test_one_get_must_be_explicit(self):
        from unittest.mock import patch
        from race_ai.keirin_personal_research_once import one_private_fetch_and_compare
        src,ref=fixture()
        with patch("race_ai.keirin_mobile_one_shot.probe_one") as mocked:
            with self.assertRaisesRegex(PersonalResearchError,
                                        "ONE_GET_EXPLICIT_ACTION_REQUIRED"):
                one_private_fetch_and_compare(
                    original_reference=ref,
                    race_id=RID, cutoff_at=CUTOFF,
                    ymd="20261103",venue_code=36,race_no=1,
                    personal_scope="USER_PRIVATE_NONCOMMERCIAL_RESEARCH",
                    one_get_acknowledgement="UNSCHEDULED_AUTO_GET")
            mocked.assert_not_called()

    def test_mismatched_race_never_fetches(self):
        from unittest.mock import patch
        from race_ai.keirin_personal_research_once import one_private_fetch_and_compare
        _,ref=fixture()
        with patch("race_ai.keirin_mobile_one_shot.probe_one") as mocked:
            with self.assertRaisesRegex(PersonalResearchError,
                                        "REQUESTED_RACE_ID_MISMATCH"):
                one_private_fetch_and_compare(
                    original_reference=ref,
                    race_id=RID,cutoff_at=CUTOFF,
                    ymd="20261103",venue_code=36,race_no=2,
                    personal_scope="USER_PRIVATE_NONCOMMERCIAL_RESEARCH",
                    one_get_acknowledgement="USER_EXPLICIT_ONE_RESULT_GET")
            mocked.assert_not_called()


if __name__=="__main__":
    unittest.main()
