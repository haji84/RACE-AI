"""Synthetic-only tests for new authored forecasts and their saved grades."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import contextlib
import io
import json
import stat
import tempfile
import unittest

from race_ai import keirin_authored_confidence as authored
from race_ai import keirin_nationwide_auto_generator as model

AT = "2030-01-15T01:00:00+00:00"
CUTOFF = "2030-01-15T02:00:00+00:00"


def universe_fixture():
    phases = ["架空の初周", "架空の打鐘", "架空の最終ホーム", "架空の最終バック",
              "架空の4コーナー", "架空のゴール"]
    return {
        "schema": "RACE_AI_KEIRIN_CONFIDENCE_UNIVERSE_V1",
        "race_id": "203001159801", "source_as_of": "2030-01-15T00:58:00+00:00",
        "cutoff": CUTOFF, "source_prediction_sha256": "a" * 64,
        "source_facts_sha256": "b" * 64, "cars": [1, 2, 3, 4, 5, 6, 7],
        "evidence_kind": "authored_goals", "candidate_origin": "independent_preselection_v1",
        "source_status": {"lineup": "published_prediction", "required_missing": [],
                          "conflicting_fields": []},
        "scenarios": [
            {"id": "main1", "role": "main", "counter_family": None,
             "phases": phases, "goal_candidates": {"3t": [[1, 2, 3]], "2t": [[1, 2]]},
             "research_weight": None},
            {"id": "counter1", "role": "counter", "counter_family": "follower_sashi",
             "phases": phases, "goal_candidates": {"3t": [[2, 1, 3]], "2t": [[2, 1]]},
             "research_weight": None},
        ],
    }


def selection_fixture(market="3t", strategy="normal"):
    combos = ["1-2-3", "2-1-3"] if market == "3t" else ["1-2", "2-1"]
    if strategy == "rollover":
        combos = combos[:1]
    return {"market": market, "strategy": strategy, "headline": "架空の検証用予想",
            "reason": "独立した二つの仮説を比較する架空テスト", "risk": "候補外の展開もある",
            "tickets": [{"combo": c, "role": "本線"} for c in combos]}


def request_fixture():
    return {"schema": authored.REQUEST_SCHEMA, "races": [{
        "universe": universe_fixture(), "selections": [
            selection_fixture(market, strategy)
            for market in ("3t", "2t") for strategy in ("normal", "rollover")]}]}


def fixed_clock():
    return datetime.fromisoformat(AT)


class AuthoredConfidenceTests(unittest.TestCase):
    def test_all_four_selections_preserve_one_independent_universe(self):
        request = request_fixture()
        before = deepcopy(request)
        files = authored.create_files(request, clock=fixed_clock)
        self.assertEqual(request, before)
        self.assertEqual(set(files), {"data/2030-01-15/forecasts.json",
                                     "data/2030-01-15/two_car_forecasts.json",
                                     "data/2030-01-15/three_car_rollover_forecasts.json"})
        normal = files["data/2030-01-15/forecasts.json"][0]
        two = files["data/2030-01-15/two_car_forecasts.json"][0]
        rollover = files["data/2030-01-15/three_car_rollover_forecasts.json"][0]
        rows = [normal, two, rollover, two["rollover"]]
        self.assertEqual(len({r["confidence_assessment"]["scenario_universe_sha256"]
                              for r in rows}), 1)
        for row in rows:
            bundle = row["confidence_assessment"]
            entry = bundle["evaluations"]["selected"]
            self.assertEqual(entry["market"], row["market"])
            self.assertEqual(entry["strategy"], row["strategy"])
            self.assertEqual(bundle["source_prediction_sha256"], authored.prediction_sha256(row))
            self.assertIs(authored.checked_forecast(row), row)
        self.assertEqual(normal["confidence_assessment"]["evaluations"]["selected"]["grade"], "激アツ")
        for original, narrow in [(normal, rollover), (two, two["rollover"])]:
            self.assertLessEqual(narrow["confidence_assessment"]["evaluations"]["selected"]["rank"],
                                 original["confidence_assessment"]["evaluations"]["selected"]["rank"])

    def test_saved_grade_and_ticket_tampering_are_rejected(self):
        row = authored.create_forecast(universe_fixture(), selection_fixture(), generated_at=AT)
        for mutate in [
            lambda r: r["confidence_assessment"]["evaluations"]["selected"].update(grade="高", rank=3),
            lambda r: r["tickets"][0].update(combo="1-3-2"),
            lambda r: r["confidence_assessment"].update(extra=True),
            lambda r: r.update(confidence="激アツ"),
        ]:
            with self.subTest(mutation=mutate):
                changed = deepcopy(row)
                mutate(changed)
                with self.assertRaises(ValueError):
                    authored.checked_forecast(changed)

    def test_no_backdating_or_legacy_goal_candidate_upgrade(self):
        for at in ["2030-01-15T00:57:59+00:00", "2030-01-15T01:59:00+00:00", CUTOFF]:
            with self.subTest(at=at), self.assertRaises(ValueError):
                authored.create_forecast(universe_fixture(), selection_fixture(), generated_at=at)
        legacy = universe_fixture()
        legacy["candidate_origin"] = "tickets_extracted"
        with self.assertRaises(ValueError):
            authored.create_forecast(legacy, selection_fixture(), generated_at=AT)
        selection = selection_fixture()
        selection["analysis_created_at"] = AT
        with self.assertRaises(ValueError):
            authored.create_forecast(universe_fixture(), selection, generated_at=AT)

    def test_create_once_private_files_can_be_imported(self):
        from race_ai import keirin_note_view
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            result = authored.write_new_site(request_fixture(), site_root=root, clock=fixed_clock)
            self.assertEqual(result, {"files_created": 3, "forecasts_created": 4})
            originals = {p: p.read_bytes() for p in root.rglob("*.json")}
            self.assertTrue(all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in originals))
            packet = keirin_note_view.import_site(root, source_commit="c" * 40, clock=fixed_clock)
            self.assertEqual(len(packet["files"]), 3)
            with self.assertRaises(ValueError):
                authored.write_new_site(request_fixture(), site_root=root, clock=fixed_clock)
            self.assertEqual(originals, {p: p.read_bytes() for p in originals})

    def test_whole_batch_is_validated_before_writing(self):
        request = request_fixture()
        broken = deepcopy(request["races"][0])
        broken["universe"]["race_id"] = "203001159802"
        broken["universe"]["cutoff"] = AT
        request["races"].append(broken)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            with self.assertRaises(ValueError):
                authored.write_new_site(request, site_root=root, clock=fixed_clock)
            self.assertEqual(list(root.iterdir()), [])

    def test_expired_save_window_rejects_the_batch_before_any_output(self):
        times = iter([fixed_clock()] * 4 + [datetime.fromisoformat(CUTOFF)])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            with self.assertRaisesRegex(ValueError, "SAVE_WINDOW_EXPIRED"):
                authored.write_new_site(request_fixture(), site_root=root, clock=lambda: next(times))
            self.assertEqual(list(root.iterdir()), [])

    def test_cli_prints_only_counts_and_offers_no_timestamp_override(self):
        from scripts import keirin_note_create_forecasts
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "request.json", root / "new-output"
            source.write_text(json.dumps(request_fixture()), encoding="utf-8")
            source.chmod(0o600)
            output.mkdir(mode=0o700)
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                code = keirin_note_create_forecasts.main(
                    ["--input", str(source), "--output", str(output)], clock=fixed_clock)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stream.getvalue()), {"files_created": 3, "forecasts_created": 4})


if __name__ == "__main__":
    unittest.main()
