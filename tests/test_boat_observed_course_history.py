"""Authored measured histories only; no model, source request or stored originals."""
from copy import deepcopy
import importlib
import hashlib
import io
import json
from pathlib import Path
import sys
import types
import traceback
import tracemalloc
import unittest
from unittest.mock import patch

RACERS = [str(4001 + i) for i in range(6)]
ASOF = "2030-04-01T10:00:00+09:00"
DAY = "2030-04-01"


def source(day="2030-03-25", sha="a" * 64, published="2030-03-26T08:00:00+09:00", captured="2030-03-26T09:00:00+09:00"):
    return {"event_date_jst": day, "source_url": "https://www1.mbrace.or.jp/od2/K/" + day[:7].replace("-", "") + "/k" + day[2:].replace("-", "") + ".lzh",
            "source_sha256": sha, "published_at": published, "captured_at": captured}


def row(no=1, lane=1, course=2, pid="4001", status="OK", st=.12, finish=1, day="2030-03-25", sha="a" * 64, venue="18"):
    return {"race_id": day.replace("-", "") + "-" + venue + "-" + str(no).zfill(2), "lane": lane,
            "racer_id": pid, "course": course, "st": st, "st_status": status, "finish": finish,
            "race_at": day + "T00:00:00+00:00", "source_sha256": sha}


class ObservedCourseHistoryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("race_ai.boat_observed_course_history"),
                             "measured course/ST projection API is missing")
        self.module = importlib.import_module("race_ai.boat_observed_course_history")

    def project(self, rows, sources=None, **kw):
        options = {"event_date_jst": DAY, "as_of": ASOF, "racer_ids": RACERS}
        options.update(kw)
        return self.module.project_boat_course_history(rows, sources if sources is not None else [source()], **options)

    def racer(self, result, pid="4001"):
        return next(r for r in result["racers"] if r["racer_id"] == pid)

    def course(self, result, course=2, count=5):
        return self.racer(result)["by_actual_course"][str(course)][str(count)]

    def test_actual_course_and_lane_are_independent_and_core_stats_unchanged(self):
        rows = [row(no=i + 1, st=.1 + i / 100, finish=(i % 6) + 1) for i in range(6)]
        result = self.project(rows)
        core = self.module._load_core()
        expected = core.summarize(sorted(rows, key=lambda r: r["race_id"], reverse=True), 5)
        self.assertEqual(self.course(result)["summary"], expected)
        self.assertEqual(self.course(result, 1)["summary"]["n"], 0)
        self.assertEqual(self.racer(result)["by_lane_10"]["1"]["summary"]["n"], 6)
        self.assertEqual(result["pr64_source_sha40"], "761247bee0209e37b1af6b8885e92cad3e9260a5")
        self.assertEqual(result["evidence_status"], "SUPPLIED_METADATA_CONSISTENCY_ONLY")

    def test_latest_unknown_source_is_diagnostic_only_without_old_fallback(self):
        newer = source(sha="b" * 64, published=None, captured="2030-03-27T09:00:00+09:00")
        result = self.project([row(), row(sha="b" * 64)], [source(), newer])
        self.assertEqual(self.course(result)["summary"]["n"], 0)
        self.assertEqual(result["qualified_row_count"], 0)
        self.assertEqual(self.racer(result)["observations"][-1]["disposition"], "UNKNOWN_PUBLICATION")

    def test_latest_empty_source_never_revives_older_rows(self):
        newer = source(sha="b" * 64, captured="2030-03-27T09:00:00+09:00")
        result = self.project([row()], [source(), newer])
        self.assertEqual(self.course(result)["summary"]["n"], 0)
        self.assertEqual(result["selected_sources"][0]["source_sha256"], "b" * 64)

    def test_mixed_venue_is_withheld_and_not_falsely_empty(self):
        result = self.project([row(), row(no=2, venue="19")])
        window = self.course(result)
        self.assertEqual(window["status"], "WITHHELD_AMBIGUOUS_ORDER")
        self.assertIsNone(window["summary"])
        self.assertIsNone(window["valid_finish_n"])
        self.assertEqual(window["row_refs"], [])
        empty = next(r for r in result["racers"] if r["racer_id"] == "4002")["overall_10"]
        self.assertEqual(empty["status"], "EMPTY_ELIGIBLE_HISTORY")
        self.assertEqual(empty["summary"]["n"], 0)

    def test_all_statuses_real_zero_and_finish_denominator_remain_distinct(self):
        rows = [row(no=1, st=0), row(no=2, status="F", st=None, finish=None),
                row(no=3, status="L", st=None, finish=None), row(no=4, status="MISSING", st=None, finish=None),
                row(no=5, status="ABSENT", st=None, course=None, finish=None)]
        result = self.project(rows)
        window = self.course(result)
        self.assertEqual(window["summary"]["n"], 4)
        self.assertEqual(window["summary"]["valid_st"], 1)
        self.assertEqual(window["summary"]["mean_st"], 0)
        self.assertEqual(window["summary"]["sd_st"], 0)
        self.assertEqual(window["summary"]["first_rate"], .25)
        self.assertEqual(window["valid_finish_n"], 1)
        self.assertEqual(window["status_counts"], {"OK": 1, "F": 1, "L": 1, "MISSING": 1, "ABSENT": 0})
        self.assertFalse(window["full_window"])
        self.assertEqual(self.racer(result)["observations"][-1]["disposition"], "ABSENT")

    def test_windows_report_requested_actual_and_numeric_sample_counts(self):
        result = self.project([row(no=i, st=.1 + i / 100) for i in range(1, 7)])
        for n in (5, 10, 20):
            window = self.course(result, count=n)
            self.assertEqual(window["requested"], n)
            self.assertEqual(window["summary"]["n"], min(n, 6))
            self.assertEqual(window["summary"]["valid_st"], min(n, 6))
            self.assertEqual(window["full_window"], n == 5)
            self.assertEqual(len(window["row_refs"]), min(n, 6))

    def test_future_capture_does_not_suppress_current_visible_source(self):
        newer = source(sha="b" * 64, captured="2030-04-01T11:00:00+09:00")
        result = self.project([row(), row(sha="b" * 64, st=.3)], [source(), newer])
        self.assertEqual(self.course(result)["summary"]["mean_st"], .12)
        self.assertEqual(result["selected_sources"][0]["source_sha256"], "a" * 64)

    def test_missing_row_in_new_source_does_not_use_old_racer(self):
        newer = source(sha="b" * 64, captured="2030-03-27T09:00:00+09:00")
        result = self.project([row(), row(pid="4002", sha="b" * 64)], [source(), newer])
        self.assertEqual(self.course(result)["summary"]["n"], 0)
        self.assertEqual(self.racer(result, "4002")["overall_10"]["summary"]["n"], 1)

    def test_tied_revisions_compare_utc_instants_and_deny_ambiguous_content(self):
        first = source(captured="2030-03-26T10:00:00+09:00")
        second = source(sha="b" * 64, captured="2030-03-26T01:30:00+00:00")
        result = self.project([row(), row(sha="b" * 64, st=.2)], [first, second])
        self.assertEqual(self.course(result)["summary"]["mean_st"], .2)
        second["captured_at"] = "2030-03-26T01:00:00+00:00"
        with self.assertRaises(ValueError):
            self.project([], [first, second])

    def test_exact_duplicates_collapse_but_conflicting_metadata_and_rows_deny(self):
        result = self.project([row(), row()], [source(), source()])
        self.assertEqual(result["deduplicated_row_count"], 1)
        self.assertEqual(self.course(result)["summary"]["n"], 1)
        for rows, sources in (([row(), row(st=.3)], [source()]),
                              ([], [source(), source(captured="2030-03-27T09:00:00+09:00")])):
            with self.assertRaises(ValueError):
                self.project(rows, sources)

    def test_targetday_source_is_excluded_and_midnight_is_only_date_sentinel(self):
        day = source(day=DAY, published="2030-04-01T08:00:00+09:00", captured="2030-04-01T09:00:00+09:00")
        result = self.project([row(day=DAY)], [day])
        self.assertEqual(self.course(result)["summary"]["n"], 0)
        self.assertEqual(self.racer(result)["observations"][0]["disposition"], "TARGET_DAY_OR_FUTURE")
        with self.assertRaises(ValueError):
            self.project([{**row(), "race_at": "2030-03-25T12:00:00+00:00"}])

    def test_wrong_source_date_hash_and_native_types_deny_safely(self):
        class Exotic(str):
            pass
        bad_rows = [{**row(), "source_sha256": "f" * 64}, row(day="2030-03-24"),
            {**row(), "course": True}, {**row(), "lane": 1.0}, {**row(), "st": float("nan")},
            {**row(), "finish": True}, {**row(), "course": 0}, {**row(), "racer_id": "FOUR"},
            {**row(), "st_status": "F"}, {**row(), "course": 1, "st_status": "ABSENT", "st": None, "finish": None},
            {**row(), "market_odds": 4}]
        for bad in bad_rows:
            with self.subTest(row=bad), self.assertRaises(ValueError):
                self.project([bad])
        for bad in ({**source(), "source_url": Exotic(source()["source_url"])},
                    {**source(), "published_at": "2030-03-28T10:00:00+09:00"}):
            with self.subTest(source=bad), self.assertRaises(ValueError):
                self.project([], [bad])

    def test_input_is_unchanged_and_report_deterministic_across_iteration_order(self):
        rows = [row(no=2), row(no=1, pid="4002")]
        sources = [source()]
        before = json.dumps([rows, sources, RACERS], sort_keys=True)
        first = self.project(rows, sources)
        second = self.project(list(reversed(rows)), list(reversed(sources)), racer_ids=list(reversed(RACERS)))
        self.assertEqual(first, second)
        self.assertEqual(before, json.dumps([rows, sources, RACERS], sort_keys=True))
        self.assertTrue(all(first[k] is False for k in ("source_bytes_authenticated", "publication_authenticated",
            "source_rights_verified", "model_admission", "forecast_generated", "official_prediction")))

    def test_non_absent_course_is_required_and_never_invented_from_lane(self):
        for status in ("OK", "F", "L", "MISSING"):
            with self.subTest(status=status), self.assertRaises(ValueError):
                self.project([row(course=None, status=status, st=.12 if status == "OK" else None)])
        result = self.project([row(course=None, status="ABSENT", st=None, finish=None)])
        self.assertEqual(self.racer(result)["overall_10"]["summary"]["n"], 0)
        self.assertIsNone(self.racer(result)["observations"][0]["course"])

    def test_pre_event_day_source_times_deny_future_result_relative_to_asof(self):
        for publication, capture, asof in (
            ("2030-03-19T00:00:00Z", "2030-03-19T01:00:00Z", "2030-03-20T01:00:00Z"),
            ("2030-03-24T14:59:59Z", "2030-03-25T00:00:00+09:00", ASOF),
            (None, "2030-03-24T23:59:59+09:00", ASOF)):
            with self.subTest(publication=publication, capture=capture), self.assertRaises(ValueError):
                self.project([row()], [source(published=publication, captured=capture)], as_of=asof)

    def test_jst_event_day_lower_bound_compares_equivalent_offset_instants(self):
        boundary = source(published="2030-03-24T15:00:00Z", captured="2030-03-25T00:00:00+09:00")
        result = self.project([row()], [boundary])
        self.assertEqual(self.course(result)["summary"]["n"], 1)
        self.assertEqual(result["source_records"][0], boundary)
        boundary["published_at"] = None
        result = self.project([row()], [boundary])
        self.assertEqual(self.course(result)["summary"]["n"], 0)
        self.assertEqual(self.racer(result)["observations"][0]["disposition"], "UNKNOWN_PUBLICATION")

    def test_wrong_preloaded_core_and_changed_fixed_core_bytes_deny(self):
        fake = types.ModuleType("race_ai.core")
        fake.summarize = lambda *a: {"n": 999}
        with patch.dict(sys.modules, {"race_ai.core": fake}), self.assertRaises(ValueError):
            self.project([])
        with patch.object(Path, "open", side_effect=lambda *a, **kw: io.BytesIO(b"FICTIONAL_CHANGED_CORE")), self.assertRaises(ValueError):
            self.project([])
        actual = self.module._load_core()
        with patch.dict(sys.modules, {"race_ai.core": actual}):
            self.assertEqual(self.project([])["pr64_core_sha256"], self.module.CORE_SHA256)

    def test_record_bounds_and_huge_integer_fail_before_copy(self):
        huge = -(1 << 64000000)
        bad = row(course=huge)
        tracemalloc.start()
        try:
            with self.assertRaises(ValueError):
                self.project([bad])
            # Whole fixed17KiB core compilation/import uses about1.3MiB;
            # a forbidden abs(huge) copy would add8.5MiB beyond this margin.
            self.assertLess(tracemalloc.get_traced_memory()[1], 2 * 1024 * 1024)
        finally:
            tracemalloc.stop()
        for rows, sources in (([row()] * 100001, [source()]), ([], [source()] * 61), ([row()], [])):
            with self.assertRaises(ValueError):
                self.project(rows, sources)

    def test_private_bad_field_is_not_echoed_in_public_error_traceback(self):
        bad = [{**source(), "captured_at": "FICTIONAL_PRIVATE_TIME_VALUE"}]
        try:
            self.project([row()], bad)
        except ValueError as error:
            self.assertNotIn("FICTIONAL_PRIVATE_TIME_VALUE", "".join(traceback.format_exception(error)))
        else:
            self.fail("bad supplied metadata accepted")

    def test_authored_cp932_pinned_parse_k_to_api_preserves_actual_course_and_status(self):
        core = self.module._load_core()
        lines = ["STARTK", "18KBGN", "2030/03/25", "1R 架空 H1800m"]
        for rank, lane, course, st in (("01", 1, 2, "0.00"), ("F", 2, 1, "F.02"),
                                       ("L", 3, 3, "L.01"), ("04", 4, 4, "--"), ("05", 5, 5, ".15")):
            lines.append(f"{rank} {lane} {4000+lane} 架空 56 47 6.82 {course} {st} 1.50.3")
        lines += ["欠 6 4006 架空", "18KEND", "ENDK"]
        raw = ("\n".join(lines) + "\n").encode("cp932")
        parsed = core.parse_k(raw, "2030-03-25")
        digest = hashlib.sha256(raw).hexdigest()
        rows = [{**r, "source_sha256": digest} for r in parsed]
        result = self.project(rows, [source(sha=digest, published=None)])
        self.assertEqual(len(parsed), 6)
        self.assertEqual(result["qualified_row_count"], 0)
        observations = [o for r in result["racers"] for o in r["observations"]]
        self.assertEqual({r["st_status"] for r in observations}, {"OK", "F", "L", "MISSING", "ABSENT"})
        self.assertEqual(self.racer(result)["observations"][0]["course"], 2)
        self.assertIsNone(self.racer(result)["observations"][0]["published_at"])
        self.assertEqual(self.racer(result)["overall_10"]["summary"]["n"], 0)
