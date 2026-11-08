"""Synthetic end-to-end: private rider packet + one Open-Meteo forecast.

Demonstrates feature-origin provenance only. No real rider source is accessed,
nor does passing this test establish a live real race forecast.
"""
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

from race_ai.keirin_open_meteo_stage import (
    VENUES_SCHEMA,stage_one_free_weather
)
from race_ai.keirin_open_meteo_weather import SOURCE
from race_ai.keirin_owner_manual import (
    PersonalOwnerObservations, PERSONAL_MARKER
)
from race_ai.keirin_permissioned_owner import stage_permissioned_deliveries
from race_ai.keirin_private_spool import KeirinPrivateSpool
from race_ai.keirin_owner_sqlite import PrivateKeirinStore
from race_ai.four_sport_model_suite import run_suite,verify_suite
from race_ai.keirin_result_delivery import canonical
from test_keirin_owner_manual import manual_fixture

NOW="2030-01-15T09:15:00+09:00"
START="2030-01-15T10:05:00+09:00"
RID="keirin:2030-01-15:fictional-venue:1"
WH={"race/air_temperature","race/humidity","race/rainfall",
    "race/wind_speed","race/wind_direction"}


def fixture():
    obj=manual_fixture()
    obj["observations"]=[item for item in obj["observations"]
                         if item["key"] not in WH]
    for item in obj["observations"]:
        if item["key"]=="race/start_time":
            item["value"]=START
    return obj


def weather_json():
    data={
        "latitude":33.81,"longitude":132.75,"timezone":"Asia/Tokyo",
        "utc_offset_seconds":32400,
        "hourly_units":{
            "time":"iso8601","temperature_2m":"°C",
            "relative_humidity_2m":"%","precipitation":"mm",
            "wind_speed_10m":"m/s","wind_direction_10m":"°"
        },
        "hourly":{
            "time":["2030-01-15T09:00","2030-01-15T10:00",
                    "2030-01-15T11:00"],
            "temperature_2m":[18,17,16],
            "relative_humidity_2m":[60,65,67],
            "precipitation":[0,0.5,0],
            "wind_speed_10m":[2.0,2.5,3.0],
            "wind_direction_10m":[150,160,170]
        }
    }
    return json.dumps(data,ensure_ascii=False).encode("utf-8")


class NoncommercialWeatherStageTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/"raw").mkdir()
        (self.root/"raw"/"owner.json").write_bytes(canonical(fixture()))
        self.coords=self.root/"coords.json"
        self.coords.write_text(json.dumps({
            "schema":VENUES_SCHEMA,
            "locations":[{
                "venue":"fictional-venue","latitude":33.8093572,
                "longitude":132.7459764,
                "location_scope":"NEARBY_PARK_COORDINATES_APPROX_ONLY",
                "location_source_url":"https://example.invalid/fictional-coordinate"
            }]
        }),encoding="utf-8")
        self.calls=[]

    def mock(self,url):
        self.calls.append(url)
        return weather_json()

    def grants(self):
        return PersonalOwnerObservations(
            source_hosts=["example.invalid"],
            now="2030-01-15T09:16:00+09:00",
            allow_noncommercial_modelled_weather=True)

    def test_one_real_weather_source_to_complete_model_without_outcome_leak(self):
        result=stage_one_free_weather(
            self.root,self.coords,now=NOW,fetch=self.mock)
        self.assertEqual(result["eligible"],1)
        self.assertEqual(result["weather_packets_created"],1)
        self.assertEqual(result["provider_get_requests"],0)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(len(list((self.root/"weather").glob("*.json"))),1)
        packets=[json.loads(x.read_text()) for x in
                 (self.root/"raw").glob("*.json")]
        self.assertEqual(len(packets),2)
        merged=next(p for p in packets if any(
            o["rights_ref"]==SOURCE for o in p["observations"]))
        self.assertEqual(merged["race"]["as_of"],
                         "2030-01-15T00:15:00+00:00")
        weather_keys=[o["key"] for o in merged["observations"]
                      if o["rights_ref"]==SOURCE]
        self.assertEqual(set(weather_keys),WH)
        self.assertNotIn("odds",json.dumps(merged))
        stage=stage_permissioned_deliveries(
            self.root,self.grants(),now="2030-01-15T09:16:00+09:00")
        self.assertEqual(stage["new_pre_race_inputs"],1)
        self.assertEqual(stage["blocked_or_invalid_inputs"],1)
        active=json.loads(next((self.root/"pre").glob("*.json")).read_text())
        audit=active["facts"]["keirin_pre_race_audit_v1"]
        self.assertEqual(len(audit["items"]),347)
        self.assertEqual(len([o for o in audit["items"]
                              if o["rights_ref"]==SOURCE]),5)
        clock=lambda: datetime.fromisoformat("2030-01-15T09:16:00+09:00")
        with PrivateKeirinStore(self.root/"owner.sqlite3",clock=clock) as db:
            owner=KeirinPrivateSpool(
                db,clock=clock,model_suite=run_suite,
                model_verifier=verify_suite,
                source_attestor=self.grants().certificate,
                source_observation_gate=self.grants().allowed,witness=None)
            tick=owner.tick(self.root)
            self.assertEqual(tick["private_forecasts_saved_this_tick"],1,tick)
            first=db.get_persisted_forecast(RID)
            self.assertEqual(len(first["forecast"]["top8"]),8)
            self.assertFalse(first["external_receipt_verified"])
            self.assertFalse(first["forecast"]["officially_frozen"])

    def test_do_not_refetch_for_one_race(self):
        self.assertEqual(stage_one_free_weather(
            self.root,self.coords,now=NOW,fetch=self.mock)[
                "weather_packets_created"],1)
        self.assertEqual(stage_one_free_weather(
            self.root,self.coords,now=NOW,fetch=self.mock)[
                "weather_packets_created"],0)
        self.assertEqual(len(self.calls),1)

    def test_no_location_no_provider_request(self):
        self.coords.write_text(json.dumps({
            "schema":VENUES_SCHEMA,"locations":[{
                "venue":"different-venue","latitude":33.8,
                "longitude":132.7,
                "location_scope":"NEARBY_PARK_COORDINATES_APPROX_ONLY",
                "location_source_url":"https://example.invalid/coord"
            }]
        }))
        got=stage_one_free_weather(
            self.root,self.coords,now=NOW,fetch=self.mock)
        self.assertEqual(got["weather_packets_created"],0)
        self.assertEqual(self.calls,[])

    def test_past_cutoff_no_provider_request(self):
        got=stage_one_free_weather(
            self.root,self.coords,now="2030-01-15T10:02:00+09:00",
            fetch=self.mock)
        self.assertEqual(got["weather_packets_created"],0)
        self.assertEqual(self.calls,[])


if __name__=="__main__":
    unittest.main()
