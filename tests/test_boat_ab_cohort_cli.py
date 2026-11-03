"""Offline-only cohort CLI tests. All examples are fictional."""
from copy import deepcopy
import json
import unittest

from scripts.boat_ab_cohort_report import parse_ledger, report
from tests.test_boat_ab_cohort import fake_case

REGISTRY={
    "source_url":"https://www.boatrace.jp/owpc/pc/race/racelist?hd=20301103&jcd=17&rno=1",
    "source_sha256":"a"*64,
    "independently_verified":True,
    "coverage_scope":"ONE_VENUE_DAY",
    "source_captured_at":"2030-11-03T09:00:00+09:00",
}


def packet(rows, registry=None):
    return json.dumps({"schema":"RACE_AI_BOAT_AB_EVIDENCE_LEDGER_V1",
                       "registry":registry or REGISTRY,
                       "rows":rows},ensure_ascii=False,separators=(",",":")).encode("utf-8")


class CohortCliTest(unittest.TestCase):
    def test_selected_only_cannot_look_like_all_day(self):
        out=report(packet([fake_case()]))
        self.assertEqual(out["conclusion_scope"],"SELECTED_RACES_NOT_ALL_EVENTS")
        self.assertFalse(out["all_race_denominator_authenticated"])
        self.assertEqual(out["officially_settled_eligible"],1)
        self.assertEqual(len(out["source_ledger_sha256"]),64)

    def test_no_official_coverage_without_independent_schedule(self):
        scope=deepcopy(REGISTRY)
        scope["independently_verified"]=False
        out=report(packet([fake_case()],scope))
        self.assertFalse(out["all_race_denominator_authenticated"])

    def test_malformed_malicious_ledger_fails(self):
        cases=[
            b'{"schema":"x","schema":"y"}',
            b'{"schema":"x","registry":{},"rows":[]}',
            b'{"schema":"RACE_AI_BOAT_AB_EVIDENCE_LEDGER_V1","registry":{},"rows":[]}',
            packet([fake_case(),fake_case()]),
        ]
        for case in cases:
            with self.subTest(case=case[:25]),self.assertRaises(ValueError):
                report(case)

    def test_input_does_not_modify_existing_rows(self):
        r=fake_case()
        raw=packet([r])
        original=deepcopy(r)
        out=report(raw)
        self.assertEqual(r,original)
        self.assertFalse(out["model_auto_promoted"])
        self.assertEqual(out["models"][0]["hypothetical_only"],True)


if __name__=="__main__":
    unittest.main()
