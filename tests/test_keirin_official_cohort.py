"""Synthetic official response shapes; no live source or result documents."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import unittest
from urllib.parse import parse_qs, urlsplit

from race_ai import keirin_dynamic_nationwide_registry as dynamic
from race_ai import keirin_nationwide_AB_results as outcomes
from race_ai import keirin_official_cohort as cohort
from race_ai import keirin_official_public_source as official
from tests.test_keirin_official_public_source import fixtures


DAY = "2026-10-02"
NOW = datetime(2026, 10, 2, 8, tzinfo=timezone.utc)


def schedule(venues, *, day=DAY, minutes=0, first_cutoff="10:47"):
    """Each venue/count becomes a real parser output from fictional raw bytes."""
    source = fixtures()
    registry = deepcopy(source["JSJ057"])
    registry["kInfo"] = []
    registry["reqprm"]["kday"] = day.replace("-", "")
    by_token = {}
    for code, count in venues:
        token = f"synthetic-cohort-event-{code}-0001"
        venue = deepcopy(source["JSJ057"]["kInfo"][0])
        venue.update(KeirinCd=code, bKeirinCd=code, jyoName=f"架空場{code}", encPrm=token)
        registry["kInfo"].append(venue)
        payload = deepcopy(source["JSJ017"])
        payload.update(keirinCd=code, kaisaihi=day.replace("-", ""),
                       reqprm={"bkcd": code, "kday": day.replace("-", "")},
                       lastUpdateTime=day.replace("-", "/") + " 07:00&nbsp;更新")
        payload["rInfo"] = payload["rInfo"][:count]
        payload["rInfo"][0]["denTime"] = first_cutoff
        by_token[token] = payload

    def get(url):
        params = parse_qs(urlsplit(url).query)
        if params["type"] == ["JSJ057"]:
            value = registry
        else:
            assert params["type"] == ["JSJ017"]
            value = by_token[params["encp"][0]]
        return json.dumps(value, ensure_ascii=False).encode("utf-8")

    observed = datetime.fromisoformat(day + "T08:00:00+00:00") + timedelta(minutes=minutes)
    return official.fetch_day_schedule(day, fetcher=get, clock=lambda: observed)


class VerifiedOfficialCumulativeCohort(unittest.TestCase):
    def test_replaced_venue_preserves_old_races_and_registers_new_races(self):
        old = schedule([("26", 2)])
        new = schedule([("27", 2)], minutes=10)
        original = deepcopy([old, new])
        value = cohort.build_registered_cohort([old, new])
        self.assertEqual(set(value), {"registry", "races_by_id", "latest_schedule",
                                      "active_race_ids", "removed_race_ids"})
        self.assertEqual(set(value["races_by_id"]), {
            "202610022601", "202610022602", "202610022701", "202610022702"})
        self.assertEqual(value["active_race_ids"], ["202610022701", "202610022702"])
        self.assertEqual(value["removed_race_ids"], ["202610022601", "202610022602"])
        self.assertEqual(value["latest_schedule"], new)
        registry = dynamic.checked_day(value["registry"])
        self.assertEqual(registry["captured_race_count"], 4)
        self.assertEqual(registry["captured_venue_count"], 2)
        self.assertEqual(registry["expected_venue_codes"], ["26", "27"])
        self.assertEqual(registry["registered_cohort_scope"],
                         "UNION_OF_VERIFIED_OFFICIAL_DAY_REVISIONS")
        self.assertEqual([old, new], original)
        scorecard = outcomes.summarize(registry=registry, paired_reports=[])
        self.assertEqual(scorecard["registered_races"], 4)
        self.assertEqual(scorecard["not_yet_independently_scored_races"], 4)
        self.assertIsNone(scorecard["A_existing"]["hit_at_all_rate"])

    def test_expansion_uses_new_actual_rows_without_rewriting_earlier_source_count(self):
        old = schedule([("26", 1)])
        new = schedule([("26", 2)], minutes=10, first_cutoff="10:46")
        value = cohort.build_registered_cohort([old, new])
        self.assertEqual(value["registry"]["captured_race_count"], 2)
        self.assertEqual(value["removed_race_ids"], [])
        self.assertEqual(value["races_by_id"]["202610022601"], new["races"][0])
        self.assertEqual([v["race_count"] for v in value["registry"]["source_venues"]], [1, 2])
        self.assertEqual(old["venue_snapshots"][0]["race_numbers"], [1])
        self.assertTrue(official.reparse_day_schedule(old))
        self.assertTrue(official.reparse_day_schedule(new))

    def test_shrink_keeps_removed_race_with_its_last_actual_source(self):
        old = schedule([("26", 2)])
        new = schedule([("26", 1)], minutes=10, first_cutoff="10:46")
        value = cohort.build_registered_cohort([old, new])
        self.assertEqual(value["registry"]["captured_race_count"], 2)
        self.assertEqual(value["active_race_ids"], ["202610022601"])
        self.assertEqual(value["removed_race_ids"], ["202610022602"])
        self.assertEqual(value["races_by_id"]["202610022601"], new["races"][0])
        self.assertEqual(value["races_by_id"]["202610022602"], old["races"][1])
        self.assertEqual([v["race_count"] for v in value["registry"]["source_venues"]], [2, 1])

    def test_individual_registry_digests_and_source_receipts_bind_each_real_revision(self):
        versions = [schedule([("26", 2)]), schedule([("27", 2)], minutes=10)]
        value = cohort.build_registered_cohort(versions)
        combined = value["registry"]
        self.assertEqual(combined["source_venues_scope"], "PER_VERIFIED_OFFICIAL_DAY_REVISION")
        for index, actual in enumerate(versions):
            individual = cohort.build_registry(actual)
            link = combined["verified_official_day_revisions"][index]
            self.assertEqual(link["revision_index"], index)
            self.assertEqual(link["registry_sha256"], individual["registry_sha256"])
            self.assertEqual(link["race_ids"], [r["race_id"] for r in actual["races"]])
            self.assertEqual(link["source_receipts"], [{
                "url": s["url"], "source_sha256": s["source_sha256"],
                "observed_at": s["observed_at"]} for s in actual["snapshots"]])
            sources = [s for s in combined["source_venues"] if s["revision_index"] == index]
            self.assertEqual([{k: v for k, v in s.items()
                               if k not in {"revision_index", "source_registry_sha256"}}
                              for s in sources], individual["source_venues"])
            self.assertTrue(all(s["source_registry_sha256"] == individual["registry_sha256"]
                                for s in sources))

    def test_pure_empty_day_remains_a_verified_zero_cohort_with_source_evidence(self):
        actual = schedule([])
        value = cohort.build_registered_cohort([actual])
        registry = dynamic.checked_day(value["registry"])
        self.assertEqual(registry["captured_race_count"], 0)
        self.assertEqual(registry["source_venues"], [])
        self.assertEqual(value["races_by_id"], {})
        self.assertEqual(value["active_race_ids"], [])
        self.assertEqual(value["removed_race_ids"], [])
        self.assertEqual(len(registry["verified_official_day_revisions"]), 1)
        self.assertEqual(len(registry["verified_official_day_revisions"][0]["source_receipts"]), 1)

    def test_empty_revision_does_not_erase_registered_races_and_reappearance_restores_activity(self):
        old = schedule([("26", 2)])
        empty = schedule([], minutes=10)
        removed = cohort.build_registered_cohort([old, empty])
        self.assertEqual(removed["registry"]["captured_race_count"], 2)
        self.assertEqual(removed["active_race_ids"], [])
        self.assertEqual(removed["removed_race_ids"], ["202610022601", "202610022602"])
        restored = schedule([("26", 2)], minutes=20)
        value = cohort.build_registered_cohort([old, empty, restored])
        self.assertEqual(value["registry"]["captured_race_count"], 2)
        self.assertEqual(value["removed_race_ids"], [])
        self.assertEqual(value["races_by_id"]["202610022601"], restored["races"][0])

    def test_different_days_and_absent_revision_list_are_rejected(self):
        for versions in (None, [], {}, [schedule([]), schedule([], day="2026-10-03")]):
            with self.subTest(kind=type(versions).__name__), self.assertRaises(ValueError):
                cohort.build_registered_cohort(versions)

    def test_tampered_raw_or_normalized_source_cannot_enter_cumulative_registry(self):
        actual = schedule([("26", 2)])
        for mutate in (
            lambda s: s["races"][0].update(official_cutoff_at=DAY + "T10:40:00+09:00"),
            lambda s: s["snapshots"][0].update(source_sha256="0" * 64),
            lambda s: s["snapshots"][1].update(raw_bytes=b"{}"),
            lambda s: s["snapshots"][1].update(url="https://example.invalid/source"),
            lambda s: s["venue_snapshots"][0].update(race_numbers=[1, 2, 3]),
        ):
            changed = deepcopy(actual)
            mutate(changed)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                cohort.build_registered_cohort([actual, changed])

    def test_latest_observed_race_row_is_selected_without_mutating_any_actual_schedule(self):
        newer = schedule([("26", 2)], minutes=10, first_cutoff="10:46")
        older = schedule([("26", 1)])
        value = cohort.build_registered_cohort([newer, older])
        self.assertEqual(value["races_by_id"]["202610022601"], newer["races"][0])
        self.assertEqual(value["latest_schedule"], older)
        self.assertEqual(value["registry"]["registered_at"], "2026-10-02T08:10:00+00:00")
        value["races_by_id"]["202610022601"]["starters"].clear()
        self.assertTrue(official.reparse_day_schedule(newer))
        self.assertTrue(official.reparse_day_schedule(older))


if __name__ == "__main__":
    unittest.main()
