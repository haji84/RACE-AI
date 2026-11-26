"""All names, official IDs and event sources here are fictional test data."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
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


UP = "状態は良くなってきています。しっかり仕掛けたい。"
STEADY = "調子は変わらず。"
TACTIC = "先行したいですね。"
VERIFIED = "d" * 64


def interview(day, text, *, post=False, observed=None, car=1):
    route, tab = ("raceresult", "race_result_interview") if post else (
        "racecard", "inspection_day_interview")
    race = f"202611{day:02d}26"
    return dict(
        registration_id=fixture()["riders"][0]["athlete_id"], source_ref="THIS_EXPORT",
        speaker="RIDER", text=text, published_at=None,
        winticket=dict(race_id=race + "01", car=car,
                      url=f"https://www.winticket.jp/keirin/seibuen/{route}/{race}/1/1?type={tab}",
                      observed_at=observed or f"2026-11-{day:02d}T{'14' if post else '08'}:00:00+09:00",
                      cutoff_at=f"2026-11-{day:02d}T12:00:00+09:00"))


def result(day, place):
    return dict(registration_id=fixture()["riders"][0]["athlete_id"], source_ref="THIS_EXPORT",
                race_id=f"202611{day:02d}2601", race_date=f"2026-11-{day:02d}",
                status="FINISHED", place=place, field_size=7,
                published_at=f"2026-11-{day:02d}T13:00:00+09:00")


def export(entries, results):
    return dict(schema=admission.SCHEMA, race_id=fixture()["race_id"], issued_at=AT,
                rights_ref="synthetic-local-test-not-actual-provider-license", allowed_uses=sorted(admission.USES),
                riders=[dict(car=1, registration_id=fixture()["riders"][0]["athlete_id"],
                             results=results, absences=[], comments=entries)])


def supplement(document, *, verify=True):
    return admission.build_supplement(
        raw_export=raw(document), source_url=SOURCE_URL, captured_at=AT, snapshot=fixture(),
        independently_authorize_source=rights, independently_verify_identity=identity,
        independently_verify_interview=lambda *args: VERIFIED if verify else None,
        independently_verify_finish=lambda *args: VERIFIED if verify else None)


def forecast(document):
    snapshot = fixture()
    original = baseline.generate_A_B(snapshot, generated_at=AT)
    accepted = supplement(document)
    candidate = shadow.generate_shadow(snapshot, accepted, baseline=original, generated_at=AT)
    return original, candidate, accepted


def reviewed_export(raw_pages, snapshot, record):
    encoded = raw(record)
    digest = sha256(encoded).hexdigest()
    original = raw_pages / (digest + ".html")
    original.write_bytes(encoded)
    original.chmod(0o600)
    roster_sha = snapshot["source_pages"][0]["bytes_sha256"]
    registration = snapshot["riders"][0]["athlete_id"]

    def verified_binding(rid, car, ident, sources):
        return (rid, car, ident) == (snapshot["race_id"], 1, registration) and any(
            sha == roster_sha for _, sha in sources)

    loader = admission.verified_history_loader(
        reviewed_export_for_race=lambda race_id: dict(url=SOURCE_URL, bytes_sha256=digest, captured_at=AT)
        if race_id == snapshot["race_id"] else None,
        independently_authorize_source=lambda ref, url, sha, uses: sha == digest and rights(ref, url, sha, uses),
        independently_verify_identity=verified_binding,
        independently_verify_interview=lambda sha, ident, _: VERIFIED
        if sha == digest and ident == registration else None,
        independently_verify_finish=lambda sha, ident, _: VERIFIED
        if sha == digest and ident == registration else None)
    return loader, original


class WinticketInterviewResearch(unittest.TestCase):
    def test_pre_race_form_signal_learns_from_earlier_finishes_and_changes_shadow_weights(self):
        past = [interview(n, UP if n <= 3 else STEADY) for n in range(1, 7)]
        outcomes = [result(n, 1 if n <= 3 else 7) for n in range(1, 7)]
        baseline, candidate, accepted = forecast(export(past + [interview(18, UP)], outcomes))
        _, without, _ = forecast(export(past, outcomes))
        rider = candidate["rider_assessments"][0]["winticket_interview"]
        self.assertEqual(rider["phase"], "PRE_RACE")
        self.assertEqual(rider["signal"], "FORM_UP")
        self.assertEqual((rider["matched_finishes"], rider["comparison_finishes"]), (3, 3))
        self.assertGreater(rider["score_adjustment"], 0)
        self.assertNotEqual(candidate["B_research"]["branch_condition_factors"],
                            without["B_research"]["branch_condition_factors"])
        self.assertEqual(candidate["baseline_prediction_sha256"], baseline["prediction_sha256"])
        self.assertNotIn(UP, json.dumps(candidate, ensure_ascii=False))
        record = accepted["condition_evidence"]["riders"][0]
        self.assertIsNone(record["comments"][-1]["published_at"])
        self.assertEqual(record["comments"][-1]["verification_sha256"], VERIFIED)
        self.assertEqual(record["results"][-1]["verification_sha256"], VERIFIED)

    def test_an_interview_at_the_existing_score_limit_has_no_realized_adjustment(self):
        past = [interview(n, STEADY if n <= 3 else UP) for n in range(1, 7)]
        outcomes = [result(n, 7 if n <= 3 else 1) for n in range(1, 7)]
        _, candidate, _ = forecast(export(past + [interview(18, UP)], outcomes))
        rider = candidate["rider_assessments"][0]["winticket_interview"]
        self.assertGreater(rider["estimated_score_adjustment"], 0)
        self.assertEqual(rider["score_adjustment"], 0)

    def test_post_race_interview_learns_against_the_next_verified_start(self):
        past = [interview(n, UP if n <= 3 else STEADY, post=True) for n in range(1, 7)]
        outcomes = [result(1, 7)] + [result(n, 1 if n <= 4 else 7) for n in range(2, 8)]
        outcomes.append(result(17, 7))
        _, candidate, _ = forecast(export(past + [interview(17, UP, post=True)], outcomes))
        rider = candidate["rider_assessments"][0]["winticket_interview"]
        self.assertEqual(rider["phase"], "PRIOR_POST_RACE")
        self.assertEqual((rider["matched_finishes"], rider["comparison_finishes"]), (3, 3))
        self.assertGreater(rider["score_adjustment"], 0)

    def test_post_race_revision_after_a_later_start_preserves_the_earlier_training_input(self):
        past = [interview(n, UP if n <= 3 else STEADY, post=True) for n in range(1, 7)]
        past.append(interview(1, STEADY, post=True, observed="2026-11-03T16:00:00+09:00"))
        outcomes = [result(1, 7)] + [result(n, 1 if n <= 4 else 7) for n in range(2, 8)]
        outcomes.append(result(17, 7))
        _, candidate, _ = forecast(export(past + [interview(17, UP, post=True)], outcomes))
        rider = candidate["rider_assessments"][0]["winticket_interview"]
        self.assertEqual((rider["matched_finishes"], rider["comparison_finishes"]), (3, 3))

    def test_interviews_require_independently_verified_finished_races_for_learning(self):
        past = interview(1, UP)
        doc = export([past, interview(18, UP)], [result(1, 1)])
        with self.assertRaisesRegex(ValueError, "INTERVIEW_FINISH_NOT_VERIFIED"):
            admission.build_supplement(
                raw_export=raw(doc), source_url=SOURCE_URL, captured_at=AT, snapshot=fixture(),
                independently_authorize_source=rights, independently_verify_identity=identity,
                independently_verify_interview=lambda *_: VERIFIED)

    def test_no_training_examples_cannot_change_the_research_weights(self):
        _, candidate, _ = forecast(export([interview(18, TACTIC)], []))
        _, no_comments, _ = forecast(export([], []))
        rider = candidate["rider_assessments"][0]["winticket_interview"]
        self.assertEqual(rider["signal"], "TACTIC_LEAD")
        self.assertEqual(rider["score_adjustment"], 0)
        self.assertEqual(candidate["B_research"]["branch_condition_factors"],
                         no_comments["B_research"]["branch_condition_factors"])

    def test_opponent_and_negated_attack_are_not_the_riders_declaration(self):
        for text in ("前の選手が先行したいと言っていた。先行したいわけではない。",
                     "調子は良い、とは言えない。",
                     "先行したい？ いや、そんなつもりはない。"):
            with self.subTest(text=text):
                _, candidate, _ = forecast(export([interview(18, text)], []))
                rider = candidate["rider_assessments"][0]["winticket_interview"]
                self.assertIsNone(rider["signal"])

    def test_same_race_post_wrong_car_unverified_and_wrong_source_are_refused(self):
        wrong_source = interview(18, UP)
        wrong_source["winticket"]["url"] = wrong_source["winticket"]["url"].replace(
            "2026111826/1/1", "2026111826/1/2")
        for entry, verified, code in (
            (interview(18, UP, post=True), True, "INTERVIEW_TARGET_RESULT"),
            (interview(18, UP, car=2), True, "INTERVIEW_TARGET_BINDING"),
            (interview(18, UP), False, "INTERVIEW_SOURCE_NOT_VERIFIED"),
            (wrong_source, True, "INTERVIEW_URL_RACE_MISMATCH"),
        ):
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, code):
                supplement(export([entry], []), verify=verified)

    def test_earlier_reported_publication_does_not_authorize_late_observation(self):
        late = interview(14, UP, observed="2026-11-14T14:00:00+09:00")
        late["published_at"] = "2026-11-14T08:00:00+09:00"
        with self.assertRaisesRegex(ValueError, "INTERVIEW_PRE_RACE_TOO_LATE"):
            supplement(export([late], [result(14, 1)]))

    def test_reviewed_loader_checks_exact_export_bytes_and_roster(self):
        with TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            root.chmod(0o700)
            raw_pages = root / "raw"
            raw_pages.mkdir(mode=0o700)
            snap = fixture()
            record = export([interview(18, UP)], [])
            load, original = reviewed_export(raw_pages, snap, record)
            result = load(snapshot=snap, raw_pages_dir=raw_pages, captured_at=AT)
            self.assertEqual(result["condition_evidence"]["riders"][0]["comments"][0]["text"], UP)
            original.write_bytes(b"Changed after review.")
            with self.assertRaisesRegex(ValueError, "HISTORY_REVIEW_EXPORT_SHA_MISMATCH"):
                load(snapshot=snap, raw_pages_dir=raw_pages, captured_at=AT)


if __name__ == "__main__":
    unittest.main()
