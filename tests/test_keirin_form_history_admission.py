"""All names, official IDs and event sources here are fictional test data."""
from copy import deepcopy
from hashlib import sha256
import json
import unittest

from race_ai import keirin_form_history_admission as admission
from race_ai import keirin_form_fall_shadow as shadow
from race_ai import keirin_nationwide_auto_generator as baseline
from tests.test_keirin_nationwide_auto_generator import fixture

AT = "2026-11-18T09:01:00+09:00"
ASOF = "2026-11-18T09:00:00+09:00"
SOURCE_URL = "https://example.org/authorized-owner-history.json"


def simulated_export(snap=None):
    snap = snap or fixture()
    ident = snap["riders"][0]["athlete_id"]
    data = {
        "schema": admission.SCHEMA,
        "race_id": snap["race_id"],
        "issued_at": "2026-11-18T09:00:20+09:00",
        "rights_ref": "synthetic-local-test-not-actual-provider-license",
        "allowed_uses": sorted(admission.USES),
        "riders": [{
            "car": 1, "registration_id": ident,
            "results": [
                {"registration_id": ident,
                 "race_id": f"202611{day:02d}2601",
                 "race_date": f"2026-11-{day:02d}", "status": "FINISHED",
                 "place": 1 if day < 10 else 7,
                 "field_size": 7, "source_ref": "THIS_EXPORT",
                 "published_at": "2026-11-18T08:30:00+09:00"}
                for day in (1,2,3,10,11,12)],
            "absences": [
                {"registration_id": ident, "start": "2026-11-04",
                 "end": "2026-11-05",
                 "source_ref": "THIS_EXPORT",
                 "published_at": "2026-11-17T12:00:00+09:00"}],
            "comments": [
                {"registration_id": ident, "speaker": "RIDER",
                 "text": "前のラインで走ります",
                 "source_ref": "THIS_EXPORT",
                 "published_at": "2026-11-17T12:00:00+09:00"}]
        }]
    }
    return data


def raw(data):
    return json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")


def rights(ref, url, digest, uses):
    # Pure fixture callback. Never a real operator or provider permission.
    return (ref == "synthetic-local-test-not-actual-provider-license" and
            url == SOURCE_URL and len(digest) == 64 and
            uses == tuple(sorted(admission.USES)))


def identity(rid, car, registered_id, roster_refs):
    # A fake verifier used ONLY by this source-free test.
    return (rid == "202611182601" and car == 1 and
            registered_id == fixture()["riders"][0]["athlete_id"] and
            bool(roster_refs))


def build(data=None, snap=None, **kw):
    snap = snap or fixture()
    data = data or simulated_export(snap)
    return admission.build_supplement(
        raw_export=raw(data), source_url=SOURCE_URL,
        captured_at=AT, snapshot=snap,
        independently_authorize_source=rights,
        independently_verify_identity=identity, **kw)


class AuthorizedHistoryAdmission(unittest.TestCase):
    def test_identity_and_source_digest_admitted_to_existing_form_shadow(self):
        snap = fixture()
        d = simulated_export(snap)
        b = build(d,snap)
        self.assertEqual(b["race_id"],snap["race_id"])
        self.assertEqual(b["schema"],shadow.SUPPLEMENT_SCHEMA)
        self.assertEqual(b["source_pages"][0]["bytes_sha256"],sha256(raw(d)).hexdigest())
        self.assertEqual(b["condition_evidence"]["riders"][0]["car"],1)
        self.assertEqual(b["condition_evidence"]["riders"][0]["results"][0]["source_sha256"],
                         sha256(raw(d)).hexdigest())
        self.assertNotIn("registration_id",b["condition_evidence"]["riders"][0])
        base = baseline.generate_A_B(snap, generated_at=AT)
        research = shadow.generate_shadow(snap,b,baseline=base,generated_at=AT)
        self.assertEqual(research["rider_assessments"][0]["trend"],"DECLINING")
        self.assertEqual(research["baseline_prediction_sha256"],base["prediction_sha256"])
        self.assertNotIn("前のラインで走ります",str(research))

    def test_unknown_roster_registration_rejects_not_mapped_by_car(self):
        snap=fixture()
        snap["riders"][0]["athlete_id"]=None
        with self.assertRaisesRegex(admission.HistoryAdapterError,
                                    "HISTORY_ROSTER_REGISTRATION_IDS_UNVERIFIED"):
            build(snap=snap)

    def test_wrong_athlete_history_even_with_matching_car_is_rejected(self):
        d=simulated_export()
        d["riders"][0]["registration_id"]="999999"
        with self.assertRaisesRegex(admission.HistoryAdapterError,
                                    "HISTORY_OFFICIAL_ID_AND_STARTER_MISMATCH"):
            build(data=d)
        d=simulated_export()
        d["riders"][0]["results"][0]["registration_id"]="999999"
        with self.assertRaisesRegex(admission.HistoryAdapterError,
                                    "HISTORY_EVENT_OFFICIAL_ID_OR_SHA_MISMATCH"):
            build(data=d)

    def test_events_need_exact_document_pointer_and_pre_cutoff_publication(self):
        d=simulated_export()
        d["riders"][0]["results"][0]["source_ref"]="ANOTHER_DOCUMENT"
        with self.assertRaisesRegex(admission.HistoryAdapterError,
                                    "HISTORY_EVENT_OFFICIAL_ID_OR_SHA_MISMATCH"):
            build(data=d)
        d=simulated_export()
        d["riders"][0]["comments"][0]["published_at"]="2026-11-18T10:00:00+09:00"
        with self.assertRaisesRegex(admission.HistoryAdapterError,
                                    "FORM_PUBLISHED_AFTER_INPUT_CUTOFF"):
            build(data=d)

    def test_rights_callback_is_required_and_rejection_has_no_fallback(self):
        snap=fixture()
        d=simulated_export()
        with self.assertRaisesRegex(admission.HistoryAdapterError,
                                    "HISTORY_EXTERNAL_RIGHTS_VALIDATOR_REQUIRED"):
            admission.build_supplement(
                raw_export=raw(d), source_url=SOURCE_URL,
                captured_at=AT, snapshot=snap,
                independently_authorize_source=None,
                independently_verify_identity=identity)
        with self.assertRaisesRegex(admission.HistoryAdapterError,
                                    "HISTORY_INDEPENDENT_RIGHTS_NOT_VERIFIED"):
            admission.build_supplement(
                raw_export=raw(d), source_url=SOURCE_URL,
                captured_at=AT, snapshot=snap,
                independently_authorize_source=lambda *_: False,
                independently_verify_identity=identity)


    def test_independent_roster_registration_witness_is_mandatory(self):
        snap=fixture()
        rawdoc=raw(simulated_export(snap))
        with self.assertRaisesRegex(admission.HistoryAdapterError,
                                    "HISTORY_EXTERNAL_IDENTITY_VALIDATOR_REQUIRED"):
            admission.build_supplement(
                raw_export=rawdoc, source_url=SOURCE_URL,
                captured_at=AT, snapshot=snap,
                independently_authorize_source=rights,
                independently_verify_identity=None)
        with self.assertRaisesRegex(admission.HistoryAdapterError,
                                    "HISTORY_INDEPENDENT_ROSTER_ID_NOT_VERIFIED"):
            admission.build_supplement(
                raw_export=rawdoc, source_url=SOURCE_URL,
                captured_at=AT, snapshot=snap,
                independently_authorize_source=rights,
                independently_verify_identity=lambda *_: False)

    def test_different_race_or_future_document_has_no_forecast(self):
        d=simulated_export()
        d["race_id"]="202611182602"
        with self.assertRaisesRegex(admission.HistoryAdapterError,
                                    "HISTORY_EXPORT_SCHEMA_OR_RIGHTS_MISMATCH"):
            build(data=d)
        d=simulated_export()
        d["issued_at"]="2026-11-18T10:00:00+09:00"
        with self.assertRaisesRegex(admission.HistoryAdapterError,
                                    "HISTORY_EXPORT_NOT_PROSPECTIVE"):
            build(data=d)

    def test_none_and_unknown_instead_of_guessing_fall_or_rest(self):
        d=simulated_export()
        d["riders"][0]["results"]=[]
        d["riders"][0]["absences"]=[]
        d["riders"][0]["comments"]=[]
        output=build(data=d)
        self.assertEqual(output["condition_evidence"]["riders"][0]["results"],[])
        snap=fixture()
        baseline_prediction=baseline.generate_A_B(snap,generated_at=AT)
        conditioned=shadow.generate_shadow(snap,output,
                    baseline=baseline_prediction,generated_at=AT)
        self.assertEqual(conditioned["rider_assessments"][0]["trend"],
                         "INSUFFICIENT_DATA")
        self.assertIsNone(conditioned["rider_assessments"][0]["documented_absence_days"])


if __name__ == "__main__":
    unittest.main()
