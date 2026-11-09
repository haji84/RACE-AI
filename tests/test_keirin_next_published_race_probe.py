"""Synthetic WINTICKET day index => next pre-cutoff race source-only probe."""
from __future__ import annotations

from datetime import datetime
import json
import unittest

from scripts.keirin_next_published_race_probe import discover_and_probe
from test_keirin_winticket_day_index import synthetic_day,RACES,START_DAY
from test_keirin_winticket_embedded_racecard import fixture as card_fixture
from test_keirin_winticket_embedded_odds import page as odds_fixture

INDEX="https://www.winticket.jp/keirin/odds/20261110"
CARD="https://www.winticket.jp/keirin/aomori/racecard/2026110812/3/3"
ODDS="https://www.winticket.jp/keirin/aomori/odds/2026110812/3/3"
NOW=datetime.fromisoformat("2026-11-10T09:00:00+09:00")


def published_catalog(doc,links):
    data=doc["tanStackQuery"]["queries"][0]["state"]["data"]
    values=[]
    venues=[]
    for rid,slug,code,dno,no in RACES:
        sid="20261110"+code
        values.append({"id":sid,"cupId":START_DAY+code,
                       "date":"20261110","day":dno,"index":1})
        venues.append({"id":code,"slug":slug})
        row=next(x for x in data["races"] if x["id"]==rid)
        row["scheduleId"]=sid
        links.append(f'<a href="/keirin/{slug}/odds">Venue</a>')
    data["schedules"]=values
    data["venues"]=venues
    links[:]=[a for a in links if "/odds/20261108" not in a]


def modified_html(original,*,kind):
    raw=original.decode("utf-8").split(
        "window.__PRELOADED_STATE__ = ",1)[1].split(";</script>",1)[0]
    state=json.loads(raw)
    data=state["tanStackQuery"]["queries"][0]["state"]["data"]
    race_id="031220261110"
    if kind=="card":
        for e in data["entries"]:e["raceId"]=race_id
        race=data["races"][0]
        race["id"]=race_id
        race["closeAt"]=int(datetime.fromisoformat(
            "2026-11-10T09:26:00+09:00").timestamp())
        race["startAt"]=int(datetime.fromisoformat(
            "2026-11-10T09:31:00+09:00").timestamp())
    else:
        for o in data["trifecta"]:o["raceId"]=race_id
        data["oddsUpdatedAt"]=int(datetime.fromisoformat(
            "2026-11-10T08:57:00+09:00").timestamp())
    return ("<html><script>window.__PRELOADED_STATE__ = "+
            json.dumps(state,separators=(",",":"))+
            ";</script></html>").encode()


class NextSourceProbeTests(unittest.TestCase):
    def setUp(self):
        self.index=synthetic_day(alter=published_catalog)
        self.card=modified_html(card_fixture(),kind="card")
        self.odds=modified_html(odds_fixture(),kind="odds")
        self.calls=[]

    def fake(self,url):
        self.calls.append(url)
        values={INDEX:self.index,CARD:self.card,ODDS:self.odds}
        if url not in values:raise AssertionError("UNDECLARED_PUBLIC_URL")
        return values[url]

    def test_first_eligible_future_race_gets_full_210_and_partial_preflight(self):
        report=discover_and_probe(
            event_day="2026-11-10",clock=lambda:NOW,fetch=self.fake)
        self.assertEqual(self.calls,[INDEX,CARD,ODDS])
        self.assertEqual(report["status"],
                         "LIVE_TRIFECTA_PRICE_UNIVERSE_VERIFIED")
        self.assertEqual(report["source_races_observed"],3)
        self.assertEqual(report["source_derived_candidate_page_count"],3)
        self.assertEqual(report["race_id"],"202611101203")
        self.assertTrue(report["real_full_odds_verified"])
        self.assertEqual(report["observed_trifecta_rows"],210)
        self.assertEqual(report["preflight_checked_count"],347)
        self.assertEqual(report["required_source_slots_total"],93)
        self.assertEqual(report["required_source_slots_A_observed"],14)
        self.assertEqual(report["required_source_slots_A_missing"],79)
        self.assertEqual(report["required_source_slots_B_observed"],14)
        self.assertEqual(report["required_source_slots_B_missing"],79)
        self.assertGreater(report["critical_preflight_source_slots_missing"],0)
        self.assertGreater(report["preflight_unavailable_count"],200)
        self.assertFalse(report["formal_model_input_preflight_completed"])
        self.assertFalse(report["actual_model_prediction_saved"])
        self.assertFalse(report["production_aead_checkpoint_saved"])
        self.assertNotIn("fictional-rider",str(report))

    def test_after_cutoff_margin_no_new_price_page_request(self):
        later=datetime.fromisoformat("2026-11-10T09:23:00+09:00")
        report=discover_and_probe(
            event_day="2026-11-10",clock=lambda:later,fetch=self.fake)
        self.assertEqual(self.calls,[INDEX])
        self.assertFalse(report["target_selected"])
        self.assertEqual(report["status"],
                         "NO_UPCOMING_SOURCE_ELIGIBLE_EVENT")
        self.assertFalse(report["real_full_odds_verified"])

    def test_different_index_without_schedule_venue_ref_cannot_request_race(self):
        raw=synthetic_day()
        calls=[]
        report=discover_and_probe(
            event_day="2026-11-10",clock=lambda:NOW,
            fetch=lambda u:calls.append(u) or raw)
        self.assertEqual(calls,[INDEX])
        self.assertFalse(report["target_selected"])
        self.assertEqual(report["status"],
                         "NO_UPCOMING_SOURCE_ELIGIBLE_EVENT")



    def test_explicit_future_target_can_use_existing_real_code_path(self):
        report=discover_and_probe(
            event_day="2026-11-10",race_id="202611101203",
            clock=lambda:NOW,fetch=self.fake)
        self.assertEqual(self.calls,[INDEX,CARD,ODDS])
        self.assertEqual(report["race_id"],"202611101203")
        self.assertEqual(report["explicit_research_target"],"202611101203")
        self.assertTrue(report["target_seen_in_public_index"])
        self.assertTrue(report["target_page_source_confirmed"])
        self.assertEqual(report["preflight_checked_count"],347)
        self.assertEqual(report["required_source_slots_total"],93)
        self.assertEqual(report["required_source_slots_A_observed"],14)
        self.assertEqual(report["required_source_slots_A_missing"],79)
        self.assertEqual(report["required_source_slots_B_observed"],14)
        self.assertEqual(report["required_source_slots_B_missing"],79)
        self.assertGreater(report["critical_preflight_source_slots_missing"],0)
        self.assertGreater(report["preflight_unavailable_count"],200)
        self.assertFalse(report["actual_model_prediction_saved"])
        self.assertFalse(report["formal_model_input_preflight_completed"])

    def test_explicit_target_absent_must_not_probe_other_race(self):
        report=discover_and_probe(
            event_day="2026-11-10",race_id="202611102109",
            clock=lambda:NOW,fetch=self.fake)
        self.assertEqual(self.calls,[INDEX])
        self.assertFalse(report["target_selected"])
        self.assertFalse(report["target_seen_in_public_index"])
        self.assertFalse(report["target_page_source_confirmed"])
        self.assertFalse(report["real_full_odds_verified"])

    def test_explicit_target_but_cutoff_too_close_no_extra_page_get(self):
        approaching=datetime.fromisoformat("2026-11-10T09:23:00+09:00")
        report=discover_and_probe(
            event_day="2026-11-10",race_id="202611101203",
            clock=lambda:approaching,fetch=self.fake)
        self.assertEqual(self.calls,[INDEX])
        self.assertFalse(report["target_selected"])
        self.assertTrue(report["target_seen_in_public_index"])
        self.assertFalse(report["actual_model_prediction_saved"])

    def test_wrong_day_and_malformed_target_rejected_before_http(self):
        for rid in ("202611091203","20261110120X","123","202611101203?x"):
            with self.subTest(rid=rid):
                self.calls.clear()
                with self.assertRaises(ValueError):
                    discover_and_probe(
                        event_day="2026-11-10",race_id=rid,
                        clock=lambda:NOW,fetch=self.fake)
                self.assertEqual(self.calls,[])


if __name__=="__main__":
    unittest.main()
