"""Fictional source-only cases; no model, retained data, clock or source calls."""
from copy import deepcopy
import hashlib
import json
import unittest

from race_ai.boat_beforeinfo_research_case import (
    BeforeinfoCaseError, project_beforeinfo_display_case,
)


AS_OF = "2030-04-01T01:40:00+00:00"
RIGHTS = "user-confirmation-2026-10-15-official-facts"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def fixture():
    """Complete fictional converter/parse_update shapes for independent review."""
    b = dict(race_id="20300401-18-01", venue="18", date_jst="2030-04-01",
        closed_at="2030-04-01T10:59:00+09:00",
        source_url="https://www1.mbrace.or.jp/od2/B/203004/b300401.lzh",
        first_observed_at="2030-03-31T23:00:00+00:00",
        source_archive_sha256="a" * 64, source_original_published_at=None,
        original_publication_verification=False, source_rights_verified=False,
        source_use_status="CANDIDATE_NOT_ADMITTED",
        boats=[dict(lane=i, racer_registration_id=str(4000+i), motor_no=20+i,
                    national_win_rate=float(i), local_win_rate=3.0,
                    motor_top2_rate=30.0) for i in range(1, 7)])
    p = dict(schema_version=1, race_id=b["race_id"], kind="beforeinfo",
        status="AVAILABLE", body_identity_verified=True, closed_at=b["closed_at"],
        captured_at="2030-04-01T01:35:00+00:00",
        available_at="2030-04-01T01:35:00+00:00",
        saved_at="2030-04-01T01:35:01+00:00", upstream_published_at=None,
        source_url="https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno=1&jcd=18&hd=20300401",
        source_sha256="b" * 64, snapshot_id="c" * 64,
        information_phase="pre_race_observation", rights_review=RIGHTS,
        eligible_pre_race=True, storage_eligible_pre_race=True,
        data={"boats": [dict(lane=i, racer_registration_id=str(4000+i),
            name="Fictional " + str(i), display_time=6.0+i/10, tilt=0.0,
            preview_st=.12, preview_st_status="OK", preview_raw_st=".12",
            preview_course=None, actual_course=None) for i in range(1, 7)],
            "weather": dict(air_temperature_c=20.0, water_temperature_c=18.0,
                wind_speed_mps=2.0, wave_height_cm=3.0, wind_direction_source_code=4,
                weather_label="fictional", source_reported_local_time="10:35",
                reported_at=None, freshness_status="UNKNOWN_SOURCE_TIME_HAS_NO_DATE")})
    return b, p


def pins(b, p):
    return dict(racelist_sha256=digest(b), preview_snapshot_sha256=digest(p))


def project(b, p, **kwargs):
    args = dict(as_of=AS_OF, input_pins=kwargs.get("input_pins")
                if "input_pins" in kwargs else pins(b, p), source_rights_ref=RIGHTS)
    args.update(kwargs)
    return project_beforeinfo_display_case(b, p, **args)


def pending(p):
    p["status"] = "PENDING"
    p["data"] = None
    p["observed_racers"] = [dict(lane=i, racer_registration_id=str(4000+i))
                             for i in range(1, 7)]
    p["missing_reason"] = "OFFICIAL_PREVIEW_EMPTY_EXHIBITION_GRID"


class BeforeinfoResearchCaseTests(unittest.TestCase):
    def test_exact_sorted_static_case_and_bound_manifest(self):
        b, p = fixture()
        b["boats"].reverse()
        p["data"]["boats"] = p["data"]["boats"][2:] + p["data"]["boats"][:2]
        before = deepcopy((b, p))
        out = project(b, p)
        self.assertEqual(out["status"], "READY_DISPLAY_RESEARCH_CASE")
        self.assertEqual(out["case"], dict(case_id="20300401-18-01", stage="P1",
            legacy={"boats": [dict(lane=i, national_win_rate=float(i), display_time_s=6.0+i/10)
                               for i in range(1, 7)]},
            source_manifest_sha256=digest(out["source_manifest"])))
        m = out["source_manifest"]
        self.assertEqual(m["input_pins"], pins(b, p))
        self.assertEqual(m["as_of"], AS_OF)
        self.assertEqual(m["sources"]["preview"]["source_url"], p["source_url"])
        self.assertEqual(m["sources"]["B"]["published_at"], None)
        self.assertEqual(m["participants"], [dict(lane=i, registration_no=str(4000+i)) for i in range(1, 7)])
        self.assertEqual((b, p), before)
        self.assertEqual(project(b, p), out)
        out["diagnostics"]["preview_st_by_lane"]["1"]["status"] = "changed"
        self.assertEqual(project(b, p)["diagnostics"]["preview_st_by_lane"]["1"]["status"], "OK")

    def test_f_l_missing_st_does_not_remove_display_boats(self):
        b, p = fixture()
        for row, status in zip(p["data"]["boats"], ("F", "L", "PENDING", "ABSENT", "MISSING", "UNKNOWN")):
            row.update(preview_st_status=status, preview_st=None)
            row.pop("preview_raw_st")
        p["data"]["boats"][0]["preview_raw_st"] = "F.03"
        p["data"]["boats"][1]["preview_raw_st"] = "L"
        out = project(b, p)
        self.assertEqual(out["status"], "READY_DISPLAY_RESEARCH_CASE")
        self.assertEqual(len(out["case"]["legacy"]["boats"]), 6)
        self.assertEqual(out["diagnostics"]["preview_st_by_lane"]["1"],
                         {"status": "F", "value": None, "missing_reason": "NON_NUMERIC_F_L"})
        self.assertEqual(out["diagnostics"]["preview_st_by_lane"]["2"]["status"], "L")
        self.assertEqual(out["diagnostics"]["legacy_readiness_status"], "BLOCKED_INTEGRATION_SOURCE_GATES")

    def test_st_raw_value_disposition_conflicts_rejected(self):
        for fields in (dict(preview_st_status="F"), dict(preview_st_status="L"),
                       dict(preview_st_status="F", preview_st=None, preview_raw_st="L.01"),
                       dict(preview_raw_st=".99"), dict(preview_raw_st={}),
                       dict(preview_st_status=True), dict(preview_st=True),
                       dict(preview_st_status="PENDING", preview_st=None, preview_raw_st=".12")):
            with self.subTest(fields=fields):
                b, p = fixture(); p["data"]["boats"][0].update(fields)
                with self.assertRaises(BeforeinfoCaseError): project(b, p)

    def test_pending_missing_and_range_dispositions(self):
        b, p = fixture(); pending(p)
        out = project(b, p)
        self.assertEqual((out["status"], out["case"]), ("BLOCKED_DISPLAY_NOT_COMPLETE", None))
        self.assertEqual(len(out["diagnostics"]["display_missing_by_lane"]), 6)
        b, p = fixture(); p["data"]["boats"][0]["display_time"] = None
        out = project(b, p)
        self.assertEqual(out["status"], "BLOCKED_DISPLAY_NOT_COMPLETE")
        self.assertEqual(out["diagnostics"]["display_missing_by_lane"], {"1": "NOT_PUBLISHED"})
        p["data"]["boats"][0]["display_time"] = .5
        self.assertEqual(project(b, p)["status"], "BLOCKED_DISPLAY_OUTSIDE_PROJECTOR_RANGE")
        for val in (1, 20):
            p["data"]["boats"][0]["display_time"] = val
            self.assertIsNotNone(project(b, p)["case"])

    def test_pending_payload_is_validated_but_never_promoted(self):
        b, p = fixture(); data = p["data"]; pending(p); p["data"] = data
        self.assertIsNone(project(b, p)["case"])
        for bad in ([], False, "", {"boats": []}, {"result": []}):
            p["data"] = bad
            with self.subTest(bad=bad), self.assertRaises(BeforeinfoCaseError): project(b, p)

    def test_race_date_cutoff_and_source_identity_rejected(self):
        changes = [("b", "race_id", "20300230-18-01"), ("b", "venue", "19"),
            ("b", "date_jst", "2030-04-02"), ("b", "race_id", "20300401-25-01"),
            ("p", "race_id", "20300401-18-02"), ("p", "closed_at", "2030-04-01T10:58:00+09:00"),
            ("p", "source_url", "https://www.boatrace.jp/owpc/pc/race/beforeinfo"),
            ("b", "source_url", "https://www1.mbrace.or.jp/od2/B/203004/b300402.lzh"),
            ("p", "source_url", "https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno=2&jcd=18&hd=20300401"),
            ("p", "source_sha256", "B" * 64), ("b", "source_archive_sha256", "a" * 63)]
        for group, key, val in changes:
            with self.subTest(group=group, key=key, val=val):
                b, p = fixture(); (b if group == "b" else p)[key] = val
                with self.assertRaises(BeforeinfoCaseError): project(b, p)

    def test_identity_types_duplicates_and_swaps_rejected(self):
        for group in ("b", "p"):
            for key, value in (("lane", True), ("lane", "1"), ("lane", 2),
                               ("racer_registration_id", 4001), ("racer_registration_id", "４００１"),
                               ("racer_registration_id", "4002")):
                b, p = fixture(); rows = b["boats"] if group == "b" else p["data"]["boats"]
                rows[0][key] = value
                with self.subTest(group=group, key=key, val=value), self.assertRaises(BeforeinfoCaseError): project(b, p)
        b, p = fixture(); rows = p["data"]["boats"]
        rows[0]["racer_registration_id"], rows[1]["racer_registration_id"] = "4002", "4001"
        with self.assertRaises(BeforeinfoCaseError): project(b, p)

    def test_observed_grid_cannot_hide_wrong_identity(self):
        b, p = fixture(); pending(p); p["observed_racers"][0]["racer_registration_id"] = "4999"
        with self.assertRaises(BeforeinfoCaseError): project(b, p)
        p["observed_racers"][0]["racer_registration_id"] = "4001"
        p["observed_racers"].append(deepcopy(p["observed_racers"][0]))
        with self.assertRaises(BeforeinfoCaseError): project(b, p)

    def test_finite_numeric_values_and_motor_identity_required(self):
        for group, key, vals in (("b", "national_win_rate", [None, True, "3", -1, 11]),
                ("b", "motor_no", [None, True, 0, 1000]),
                ("b", "local_win_rate", [[], True, -1]),
                ("p", "display_time", [True, "6.1", 0, 20.01]),
                ("p", "preview_st", [True, -1, 1.01])):
            for val in vals:
                b, p = fixture(); (b["boats"] if group == "b" else p["data"]["boats"])[0][key] = val
                with self.subTest(group=group, key=key, val=val), self.assertRaises(BeforeinfoCaseError): project(b, p)

    def test_temporal_boundaries_and_no_naive_clock(self):
        for group, key, val in (("b", "first_observed_at", "2030-04-01T01:40:01Z"),
                ("p", "captured_at", "2030-04-01T01:40:01Z"),
                ("p", "captured_at", "2030-03-31T14:59:00Z"),
                ("p", "captured_at", "2030-04-01T01:35:00"),
                ("p", "available_at", "2030-04-01T01:34:59Z"),
                ("p", "available_at", "2030-04-01T01:35:02Z"),
                ("p", "saved_at", "2030-04-01T01:40:01Z"),
                ("p", "upstream_published_at", "2030-04-01T01:35:01Z"),
                ("b", "source_original_published_at", "2030-04-01T00:00:01Z")):
            b, p = fixture(); (b if group == "b" else p)[key] = val
            with self.subTest(group=group, key=key), self.assertRaises(BeforeinfoCaseError): project(b, p)
        b, p = fixture()
        for asof in (b["closed_at"], "2030-04-02T01:40:00Z", "2030-04-01T01:40:00"):
            with self.subTest(asof=asof), self.assertRaises(BeforeinfoCaseError): project(b, p, as_of=asof)

    def test_equivalent_instants_and_prior_day_b_capture_are_preserved(self):
        b, p = fixture(); b["first_observed_at"] = "2030-03-30T23:00:00Z"
        p["closed_at"] = "2030-04-01T01:59:00Z"
        p["captured_at"] = "2030-04-01T10:40:00+09:00"
        p["available_at"] = p["saved_at"] = AS_OF
        out = project(b, p)
        self.assertEqual(out["source_manifest"]["sources"]["preview"]["captured_at"], p["captured_at"])
        self.assertEqual(out["source_manifest"]["sources"]["B"]["captured_at"], b["first_observed_at"])

    def test_jst_calendar_overflow_is_a_projector_rejection(self):
        b, p = fixture()
        b.update(race_id="99991231-18-01", date_jst="9999-12-31",
            closed_at="9999-12-31T23:59:00-23:59", first_observed_at="9999-12-31T01:00:00Z",
            source_url="https://www1.mbrace.or.jp/od2/B/999912/b991231.lzh")
        p.update(race_id=b["race_id"], closed_at=b["closed_at"], captured_at="9999-12-31T01:30:00Z",
            available_at="9999-12-31T01:30:00Z", saved_at="9999-12-31T01:30:01Z",
            source_url="https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno=1&jcd=18&hd=99991231")
        with self.assertRaises(BeforeinfoCaseError):
            project(b, p, as_of="9999-12-31T01:40:00Z")

    def test_optional_authority_flags_and_metadata_types_are_exact(self):
        for group, key, val in (("b", "original_publication_verification", True),
                ("b", "source_rights_verified", 0), ("b", "source_use_status", {}),
                ("p", "body_identity_verified", 1), ("p", "eligible_pre_race", 1),
                ("p", "storage_eligible_pre_race", False), ("p", "rights_review", {}),
                ("p", "schema_version", True), ("p", "snapshot_id", []),
                ("p", "information_phase", "official_result"), ("p", "missing_reason", {})):
            for block in (False, True):
                b, p = fixture()
                if block: pending(p)
                (b if group == "b" else p)[key] = val
                with self.subTest(group=group, key=key, block=block), self.assertRaises(BeforeinfoCaseError): project(b, p)

    def test_re_pinned_leakage_rejected_at_every_owned_boundary(self):
        for mode in ("ready", "pending", "missing"):
            for boundary in ("b", "bboat", "p", "data", "pboat", "weather", "observed"):
                b, p = fixture()
                if mode == "pending":
                    data = p["data"]; pending(p); p["data"] = data
                if mode == "missing": p["data"]["boats"][0]["display_time"] = None
                if boundary == "observed" and mode != "pending": continue
                node = {"b": b, "bboat": b["boats"][0], "p": p, "data": p["data"],
                        "pboat": p["data"]["boats"][0], "weather": p["data"]["weather"],
                        "observed": p.get("observed_racers", [{}])[0]}[boundary]
                node["odds"] = {"1-2-3": 10}
                with self.subTest(mode=mode, boundary=boundary), self.assertRaises(BeforeinfoCaseError): project(b, p)
        for key in ("result", "finish", "payout", "probability", "strength", "lap_s", "turn_s"):
            b, p = fixture(); p["data"]["boats"][0][key] = 1
            with self.subTest(key=key), self.assertRaises(BeforeinfoCaseError): project(b, p)

    def test_optional_scalars_cannot_hide_payloads(self):
        for field in ("name", "tilt", "preview_raw_st", "preview_course", "actual_course"):
            b, p = fixture(); p["data"]["boats"][0][field] = {"result": [1, 2, 3]}
            with self.subTest(field=field), self.assertRaises(BeforeinfoCaseError): project(b, p)
        b, p = fixture(); p["data"]["boats"][0]["actual_course"] = 1
        with self.assertRaises(BeforeinfoCaseError): project(b, p)

    def test_weather_fallback_and_scalar_smuggling_rejected(self):
        for value in (None, [], False, "", {"wind_speed_mps": True},
                {"weather_label": {}}, {"wind_direction_source_code": []},
                {"source_reported_local_time": "25:00"},
                {"reported_at": "2030-04-01T01:30:00Z"},
                {"freshness_status": "VERIFIED"}):
            for block in (False, True):
                b, p = fixture()
                if block:
                    data = p["data"]; pending(p); p["data"] = data
                p["data"]["weather"] = value
                with self.subTest(value=value, block=block), self.assertRaises(BeforeinfoCaseError): project(b, p)

    def test_input_pins_and_declared_rights_not_arbitrary(self):
        b, p = fixture(); good = pins(b, p)
        for bad in ({}, {**good, "extra": "x"}, {**good, "preview_snapshot_sha256": "d" * 64},
                    {**good, "racelist_sha256": "A" * 64}):
            with self.subTest(bad=bad), self.assertRaises(BeforeinfoCaseError): project(b, p, input_pins=bad)
        for bad in (None, True, "independent-rights-granted", {"reference": RIGHTS}):
            with self.subTest(bad=bad), self.assertRaises(BeforeinfoCaseError): project(b, p, source_rights_ref=bad)

    def test_non_string_keys_nonfinite_cycles_and_bounds_fail_before_json_coercion(self):
        b, p = fixture(); good = pins(b, p)
        for bad in (float("nan"), float("inf"), 10**1000, "x" * 20000, {1: "hidden"}, (1, 2)):
            p2 = deepcopy(p); p2["data"]["weather"]["weather_label"] = bad
            with self.subTest(bad=type(bad)), self.assertRaises(BeforeinfoCaseError): project(b, p2, input_pins=good)
        p["data"]["weather"]["weather_label"] = p
        with self.assertRaises(BeforeinfoCaseError): project(b, p, input_pins=good)
        b, p = fixture(); p[1] = "collision"; p["1"] = "collision"
        with self.assertRaises(BeforeinfoCaseError): project(b, p, input_pins=good)

    def test_fixed_denial_flags_and_no_derived_inference_fields(self):
        out = project(*fixture())
        self.assertIs(out["research_only"], True)
        for key in ("forecast_executed", "official_prediction", "formal_hit_at_8_eligible",
                    "historical_pre_cutoff_freeze_claimed", "actual_publication_verified_by_module",
                    "actual_rights_verified_by_module", "individual_receipt_verified"):
            self.assertIs(out[key], False)
        self.assertEqual(set(out["case"]), {"case_id", "stage", "legacy", "source_manifest_sha256"})
        self.assertNotIn("generated_at", out)
        self.assertNotIn("saved_at", out)


if __name__ == "__main__":
    unittest.main()
