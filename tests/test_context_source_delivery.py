"""Supplemental context transport contract: only pre-cutoff, licensed, unmodeled evidence.

Fictional 2030 observations. No live sources or forecast receipts.
"""
import json
import unittest

from tests.test_permissioned_source_delivery import (
    raw_feed, SRC, AT, gate, policy_doc
)
from race_ai.permissioned_source_delivery import deliver, SourceDeliveryError

SPORT_FEATURE = (
    ("boat","historical_1m_to_2m_transition"),
    ("keirin","time_band_win_rate"),
    ("autorace","same_handicap_grid_order"),
    ("horse","early_pace_pressure"),
)


def supplement(key, participant=1):
    return {
        "feature_key":key, "subject_number":participant,
        "value":0.61, "published_at":"2030-01-15T08:00:00+09:00",
        "captured_at":"2030-01-15T08:01:00+09:00",
        "source_ref":SRC,"source_rights_ref":"fictional-permission-1",
        "sample_n":18,"transform_id":"synthetic-historical-precutoff-only",
    }


def payload(sport,key):
    data=json.loads(raw_feed(sport))
    data["supplemental"]=[supplement(key)]
    return data


class SupplementalEvidenceTests(unittest.TestCase):
    def test_four_sports_preserve_context_but_do_not_inject_untrained_weights(self):
        for sport,key in SPORT_FEATURE:
            with self.subTest(sport=sport):
                standard=deliver(raw_feed(sport),gate(),at=AT)
                extra=deliver(json.dumps(payload(sport,key)).encode(),gate(),at=AT)
                self.assertEqual(extra["supplemental_evidence"][0]["feature_key"],key)
                self.assertFalse(extra["supplemental_features_used_by_models"])
                self.assertEqual(extra["research_suite"],standard["research_suite"])
                self.assertNotEqual(extra["source_payload_sha256"],standard["source_payload_sha256"])
                self.assertNotEqual(extra["delivery_sha256"],standard["delivery_sha256"])
                self.assertFalse(extra["official_prediction"])

    def test_context_rejects_after_cutoff_or_as_of(self):
        data=payload("boat","historical_1m_to_2m_transition")
        data["supplemental"][0]["captured_at"]="2030-01-15T10:20:00+09:00"
        with self.assertRaisesRegex(SourceDeliveryError,"published after as_of"):
            deliver(json.dumps(data).encode(),gate(),at=AT)

    def test_context_rejects_unobserved_real_turn_of_current_race(self):
        data=payload("boat","first_turn_actual_finish")
        with self.assertRaisesRegex(SourceDeliveryError,"unsupported or post-race"):
            deliver(json.dumps(data).encode(),gate(),at=AT)

    def test_context_rejects_unsigned_source_unknown_subject_duplicate(self):
        data=payload("autorace","same_handicap_grid_order")
        data["supplemental"][0]["source_ref"]="https://unreviewed.example/false"
        with self.assertRaisesRegex(SourceDeliveryError,"SOURCE_PERMISSION_NOT_ADMITTED"):
            deliver(json.dumps(data).encode(),gate(),at=AT)
        data=payload("autorace","same_handicap_grid_order")
        data["supplemental"][0]["subject_number"]=99
        with self.assertRaisesRegex(SourceDeliveryError,"subject mismatch"):
            deliver(json.dumps(data).encode(),gate(),at=AT)
        data=payload("autorace","same_handicap_grid_order")
        data["supplemental"].append(dict(data["supplemental"][0]))
        with self.assertRaisesRegex(SourceDeliveryError,"duplicate supplemental"):
            deliver(json.dumps(data).encode(),gate(),at=AT)

    def test_context_rejects_market_leak_in_supplement(self):
        data=payload("horse","early_pace_pressure")
        data["supplemental"][0]["race_result"]=9
        with self.assertRaisesRegex(SourceDeliveryError,"market or result"):
            deliver(json.dumps(data).encode(),gate(),at=AT)

    def test_context_rejects_without_storage_rights(self):
        doc=policy_doc(["collection","analysis","private_derived"])
        data=payload("keirin","time_band_win_rate")
        with self.assertRaisesRegex(SourceDeliveryError,"SOURCE_PERMISSION_NOT_ADMITTED"):
            deliver(json.dumps(data).encode(),gate(doc),at=AT)


if __name__ == "__main__":
    unittest.main()
