"""Fictional saved-page observations never become forecasts or results."""
from collections import Counter
from copy import deepcopy
import importlib
import json
import unittest
from unittest.mock import patch

try:
    projection = importlib.import_module("race_ai.saved_card_projection")
except ModuleNotFoundError:
    projection = None


def captured_cards():
    sources = []
    for sport, count in (("keirin", 75), ("horse", 59), ("autorace", 20)):
        for index in range(count):
            venue, race = index // 12 + 1, index % 12 + 1
            if sport == "horse":
                url = ("https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/DebaTable?"
                       f"k_raceDate=2030%2F04%2F01&k_babaCode={venue:02d}&k_raceNo={race}")
            else:
                url = (f"https://www.winticket.jp/{sport}/fixture-{venue}/"
                       f"racecard/2030040101/1/{race}")
            sources.append(dict(sport=sport, url=url, final_url=url,
                observed_at="2030-04-01T00:30:00+00:00", source_sha256="a" * 64,
                visible_text="2030年4月1日\nFICTIONAL_PRIVATE_MARKET_SENTINEL",
                table_rows=[["馬名", "オッズ", "人気"], ["Fictional entrant", "3.4", "1"]],
                links=[], state="CURRENT_DATE_CARD_OBSERVED"))
    return dict(schema="RACE_AI_OWNER_REQUESTED_PUBLIC_CARDS_V1", date_jst="2030-04-01",
                forecast_count=0, not_all_models_ready=True, sources=sources,
                source_failures=[], source_request_count=155,
                boat_missing_race_layout={"race_slices": {"1": "FICTIONAL_BOAT_TEXT"}},
                completed_at="2030-04-01T00:35:00+00:00")


class SavedCardProjectionTests(unittest.TestCase):
    def project(self, document=None, **changes):
        self.assertIsNotNone(projection, "saved-card observation projection is missing")
        arguments = dict(artifact_id=123, original_json_sha256="b" * 64,
                         dataset_status="REAL_REPORTED")
        arguments.update(changes)
        return projection.project_saved_cards(captured_cards() if document is None else document,
                                              **arguments)

    def test_all_154_observations_preserve_exact_source_identity_and_provenance(self):
        document = captured_cards()
        before = deepcopy(document)
        view = self.project(document)
        self.assertEqual(document, before)
        self.assertEqual(view["schema"], "RACE_AI_PRIVATE_CYCLE_VIEW_V1")
        self.assertEqual(view["dataset_status"], "REAL_REPORTED")
        self.assertEqual(Counter(r["sport"] for r in view["records"]),
                         {"keirin": 75, "horse": 59, "autorace": 20})
        self.assertEqual([r["race_id"] for r in view["records"]],
                         [s["url"] for s in document["sources"]])
        observation = view["records"][0]["source_observation"]
        self.assertEqual(observation["source_url"], document["sources"][0]["url"])
        self.assertEqual(observation["source_sha256"], "a" * 64)
        self.assertEqual(observation["observed_at"], "2030-04-01T00:30:00+00:00")
        self.assertEqual(observation["artifact_id"], 123)
        self.assertEqual(observation["original_json_sha256"], "b" * 64)
        self.assertEqual(view["original_document_references"],
                         [dict(artifact_id=123, member_name="cards.json", member_sha256="b" * 64)])
        self.assertFalse(view["independent_source_verified"])
        self.assertFalse(view["independent_receipt_verified"])

    def test_unknown_metadata_stays_null_and_every_row_is_observation_only(self):
        for row in self.project()["records"]:
            for field in ("venue", "race_no", "cutoff_at", "prediction", "result"):
                self.assertIsNone(row[field], field)
            for field in ("participants", "comparison_predictions", "history", "result_observations", "result_revisions"):
                self.assertEqual(row[field], [], field)
            self.assertEqual(row["offering_status"], "UNKNOWN")
            self.assertEqual(row["scope"], "research")
            self.assertTrue(row["source_observation_view"])
            for reason in ("SOURCE_OBSERVATION_ONLY", "NO_QUALIFIED_NATIVE_FEATURE_SNAPSHOT", "OFFICIAL_CUTOFF_NOT_SAVED"):
                self.assertIn(reason, row["missing_reasons"])

    def test_private_text_tables_market_and_claimed_predictions_are_never_copied(self):
        document = captured_cards()
        document["independent_source_verified"] = True
        document["official_prediction"] = {"top8": [[1, 2, 3]]}
        for source in document["sources"]:
            source.update(prediction={"top8": [[1, 2, 3]]}, result={"winner": 1},
                          odds={"1-2-3": 3.4}, official=True, cutoff_at="2030-04-01T12:00:00+09:00")
        wire = json.dumps(self.project(document))
        for private in ("FICTIONAL_PRIVATE_MARKET_SENTINEL", "Fictional entrant", "FICTIONAL_BOAT_TEXT",
                        '"visible_text"', '"table_rows"', '"odds"', '"top8"', '"winner"'):
            self.assertNotIn(private, wire)
        self.assertFalse(json.loads(wire)["independent_source_verified"])

    def test_synthetic_status_never_becomes_research_or_verified(self):
        view = self.project(dataset_status="SYNTHETIC_ONLY")
        self.assertTrue(all(r["scope"] == "synthetic" for r in view["records"]))
        for status in ("REAL_VERIFIED", "AUDIT_ONLY", True, None):
            with self.subTest(status=status), self.assertRaises(ValueError):
                self.project(dataset_status=status)

    def test_duplicate_source_url_is_rejected(self):
        document = captured_cards()
        document["sources"].append(deepcopy(document["sources"][0]))
        with self.assertRaises(ValueError):
            self.project(document)

    def test_schema_forecast_count_source_state_day_and_provenance_are_checked(self):
        edits = [
            lambda d: d.update(schema="UNKNOWN"),
            lambda d: d.update(forecast_count=1),
            lambda d: d.update(forecast_count=False),
            lambda d: d.update(date_jst="2030-4-1"),
            lambda d: d["sources"][0].update(state="OFFICIAL_RESULT"),
            lambda d: d["sources"][0].update(source_sha256="bad"),
            lambda d: d["sources"][0].update(observed_at="2030-04-01T00:30:00"),
            lambda d: d["sources"][0].update(observed_at="2030-04-02T00:30:00Z"),
            lambda d: d["sources"][0].update(visible_text="2030年4月2日"),
            lambda d: d["sources"][0].update(sport="boat"),
            lambda d: d.update(sources=[]),
        ]
        for edit in edits:
            document = captured_cards()
            edit(document)
            with self.subTest(edit=edits.index(edit)), self.assertRaises(ValueError):
                self.project(document)
        for arguments in (dict(artifact_id=True), dict(artifact_id=0),
                          dict(original_json_sha256="bad")):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                self.project(**arguments)

    def test_url_identity_rejects_wrong_domains_sports_dates_credentials_and_redirects(self):
        changes = [
            dict(url="http://www.winticket.jp/keirin/fixture/racecard/2030040101/1/1"),
            dict(url="https://www.winticket.jp.evil.invalid/keirin/fixture/racecard/2030040101/1/1"),
            dict(url="https://user:secret@www.winticket.jp/keirin/fixture/racecard/2030040101/1/1"),
            dict(url="https://www.winticket.jp/autorace/fixture/racecard/2030040101/1/1"),
            dict(url="https://www.winticket.jp/keirin/fixture/racecard/2030040101/1/1#fragment"),
            dict(final_url="https://www.winticket.jp/keirin/other/racecard/2030040101/1/1"),
        ]
        for change in changes:
            document = captured_cards()
            document["sources"][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.project(document)
        document = captured_cards()
        horse = next(s for s in document["sources"] if s["sport"] == "horse")
        horse["url"] = horse["final_url"] = horse["url"].replace("2030%2F04%2F01", "2030%2F04%2F02")
        with self.assertRaises(ValueError):
            self.project(document)

    def test_projection_has_no_network_file_or_process_side_effects(self):
        document = captured_cards()
        with patch("socket.socket", side_effect=AssertionError("network forbidden")), \
             patch("subprocess.Popen", side_effect=AssertionError("process forbidden")), \
             patch("builtins.open", side_effect=AssertionError("file I/O forbidden")):
            view = self.project(document)
        self.assertEqual(len(view["records"]), 154)

    def test_winticket_meeting_day_must_match_rendered_and_document_day(self):
        for replacement in ("2099123101/1/1", "2030040101/2/1", "2030023001/1/1"):
            document = captured_cards()
            source = document["sources"][0]
            source["url"] = source["final_url"] = source["url"].replace("2030040101/1/1", replacement)
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                self.project(document)

    def test_unrepresentable_jst_clocks_are_rejected_without_overflow(self):
        document = captured_cards()
        document["completed_at"] = "9999-12-31T23:59:59Z"
        try:
            self.project(document)
        except Exception as error:
            self.assertIsInstance(error, ValueError)
        else:
            self.fail("unrepresentable local clock was accepted")


if __name__ == "__main__":
    unittest.main()
