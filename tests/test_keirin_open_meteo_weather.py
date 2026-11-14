"""Fictional weather payloads; no live-provider access in these unit tests."""
import json
import math
import unittest
from datetime import timedelta

from race_ai.keirin_open_meteo_weather import (
    API, SOURCE, WEATHER_KEYS, WeatherSourceError, request_url,
    parse_one_forecast, fetch_one_weather_forecast
)

LAT=33.8093572
LON=132.7459764
RID="202611097501"  # fictitious test identifier, NOT verified event schedule
CAPTURED="2026-11-08T20:57:00+09:00"
CUTOFF="2026-11-09T20:35:00+09:00"
START="2026-11-09T20:40:00+09:00"


def payload():
    return json.dumps({
        "latitude":33.81, "longitude":132.75, "timezone":"Asia/Tokyo",
        "utc_offset_seconds":32400,
        "hourly_units":{
            "time":"iso8601","temperature_2m":"°C",
            "relative_humidity_2m":"%",
            "precipitation":"mm",
            "wind_speed_10m":"m/s",
            "wind_direction_10m":"°",
        },
        "hourly":{
            "time":["2026-11-09T19:00","2026-11-09T20:00",
                    "2026-11-09T21:00","2026-11-09T22:00"],
            "temperature_2m":[17.0,16.5,16.0,15.0],
            "relative_humidity_2m":[56,60,63,65],
            "precipitation":[0,0,0.8,0.6],
            "wind_speed_10m":[4.1,4.4,5.0,5.3],
            "wind_direction_10m":[270,280,285,290],
        }
    },ensure_ascii=False).encode("utf-8")


def parse(raw=None, **overrides):
    fields={
        "latitude":LAT, "longitude":LON, "race_id":RID,
        "race_start_at":START,"official_cutoff_at":CUTOFF,
        "captured_at":CAPTURED
    }
    fields.update(overrides)
    return parse_one_forecast(raw if raw is not None else payload(),**fields)


class OpenMeteoWeather(unittest.TestCase):
    def test_bounded_weather_is_not_called_a_venue_measurement(self):
        item=parse()
        self.assertEqual(item["race_id"],RID)
        self.assertEqual(item["model_inputs"]["air_temperature"],16.0)
        self.assertEqual(item["model_inputs"]["wind_speed"],5.0)
        self.assertEqual(item["model_inputs"]["rainfall"],0.8)
        self.assertEqual(item["forecast_hour_at"],
                         "2026-11-09T21:00:00+09:00")
        self.assertEqual(item["source_rights_ref"],SOURCE)
        self.assertFalse(item["published_at_independently_verified"])
        self.assertFalse(item["rider_data_present"])
        self.assertFalse(item["official_forecast_frozen"])
        self.assertIn("MODELLED",item["value_kind"])
        self.assertIn("https://creativecommons.org/licenses/by/4.0/",
                      item["license_url"])

    def test_one_bounded_provider_request_after_private_noncommercial_optin(self):
        requests=[]
        def mocked(url):
            requests.append(url)
            return payload()
        item=fetch_one_weather_forecast(
            race_id=RID, latitude=LAT, longitude=LON,
            race_start_at=START,official_cutoff_at=CUTOFF,
            captured_at=CAPTURED,owner_noncommercial=True,fetch=mocked)
        self.assertEqual(len(requests),1)
        self.assertTrue(requests[0].startswith(API+"?"))
        self.assertNotIn("api_key",requests[0])
        self.assertEqual(item["provider_get_count"],1)

    def test_commercial_disabled_and_no_network(self):
        requests=[]
        with self.assertRaisesRegex(WeatherSourceError,"NONCOMMERCIAL_ONLY"):
            fetch_one_weather_forecast(
                race_id=RID,latitude=LAT,longitude=LON,
                race_start_at=START,official_cutoff_at=CUTOFF,
                captured_at=CAPTURED,owner_noncommercial=False,
                fetch=lambda _:requests.append(True) or payload())
        self.assertEqual(requests,[])

    def test_late_cutoff_fails_before_network(self):
        requests=[]
        with self.assertRaisesRegex(WeatherSourceError,"WEATHER_CUTOFF_TOO_LATE"):
            fetch_one_weather_forecast(
                race_id=RID,latitude=LAT,longitude=LON,
                race_start_at=START,official_cutoff_at=CUTOFF,
                captured_at="2026-11-09T20:40:01+09:00",
                owner_noncommercial=True,
                fetch=lambda _:requests.append(True) or payload())
        self.assertEqual(requests,[])

    def test_coordinates_must_be_supplied_and_finite(self):
        for lat,lon in ((float("nan"),LON),(None,LON),
                        (90.01,LON),(LAT,-181),(True,LON)):
            with self.subTest(lat=lat,lon=lon):
                with self.assertRaisesRegex(
                    WeatherSourceError,"VERIFIED_VENUE_COORDINATES_REQUIRED"):
                    request_url(lat,lon)

    def test_missing_forecast_field_refused_not_zero(self):
        obj=json.loads(payload())
        del obj["hourly"]["precipitation"]
        with self.assertRaisesRegex(WeatherSourceError,
                                    "WEATHER_FIELD_OR_UNITS_INVALID"):
            parse(json.dumps(obj).encode())

    def test_mismatched_units_and_weather_grid_refused(self):
        obj=json.loads(payload())
        obj["hourly_units"]["wind_speed_10m"]="km/h"
        with self.assertRaisesRegex(WeatherSourceError,"WEATHER_FIELD_OR_UNITS"):
            parse(json.dumps(obj).encode())
        obj=json.loads(payload())
        obj["latitude"]=40.0
        with self.assertRaisesRegex(WeatherSourceError,"WEATHER_GRID_OR_TIMEZONE"):
            parse(json.dumps(obj).encode())

    def test_nan_and_unrealistic_values_refused(self):
        obj=json.loads(payload())
        obj["hourly"]["wind_speed_10m"][2]=400
        with self.assertRaisesRegex(WeatherSourceError,
                                    "WEATHER_VALUE_OUTSIDE_MEANINGFUL_RANGE"):
            parse(json.dumps(obj).encode())
        obj=json.loads(payload())
        obj["hourly"]["temperature_2m"][2]=float("nan")
        with self.assertRaisesRegex(WeatherSourceError,"WEATHER_JSON_INVALID"):
            parse(json.dumps(obj).encode())

    def test_only_hourly_bin_near_future_start_can_be_used(self):
        with self.assertRaisesRegex(WeatherSourceError,
                                    "WEATHER_NO_RACE_START_TIME_BIN"):
            parse(race_start_at="2026-11-09T23:30:00+09:00")


if __name__ == "__main__":
    unittest.main()
