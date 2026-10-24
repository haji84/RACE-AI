"""Offline schema/rights/identity test fixtures. No network required."""
from datetime import date, datetime
from pathlib import Path
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch

from race_ai.core import SourceError
from race_ai.public_day_feed import endpoint, normalize, fetch_one_day, MAX_BYTES

DAY=date(2026,10,14)
URL=endpoint(DAY)
OBSERVED="2026-10-14T05:55:00Z"


def make_provider(day="2026-10-14", motor_a=11, motor_b=12, result=False):
    boats={str(i):dict(entry_number=i,name="仮選手"+str(i),
                        number=4000+i,motor_number=(motor_a if i==1 else motor_b if i==2 else i+30),
                        average_start_timing=.14,motor_top_2_percent=32.4)
           for i in range(1,7)}
    preview_racers={str(i):dict(entry_number=i,course_number=i,
                               start_timing=.12,exhibition_time=6.75) for i in range(1,7)}
    rr={str(i):dict(entry_number=i,course_number=i,number=4000+i,
                     start_timing=.13,place_number=i) for i in range(1,7)} if result else {}
    return {"programs":{"stadiums":{"19":{"races":{"9":{
         "date":day,"stadium_number":19,"race_number":9,"racers":boats,
         "preview":{"racers":preview_racers,"wind_speed":2,"wave_height":2},
         "result":{"racers":rr} if result else {}
    }}}}}}


def convert(obj):
    raw=json.dumps(obj,ensure_ascii=False).encode()
    return normalize(raw,day=DAY,received_at=OBSERVED,source_url=URL,
                     source_sha256=hashlib.sha256(raw).hexdigest())


class ProviderSchemaTests(unittest.TestCase):
    def test_normalize_one_venue_six_racers_but_not_24_motors(self):
        result=convert(make_provider())
        self.assertEqual(result["venues_with_races"],1)
        self.assertEqual(result["races"],1)
        self.assertEqual(result["complete_six_boat_races"],1)
        self.assertEqual(result["previews"],1)
        self.assertEqual(result["results"],0)
        self.assertFalse(result["official_result_verified"])
        self.assertFalse(result["nationwide_active_motor_inventory_complete"])
        self.assertFalse(result["original_exhibition_supported"])
        boat=result["venues"][0]["races"][0]["boats"][0]
        self.assertEqual(boat["motor_no"],11)
        self.assertIsNone(boat["original_lap"])
        self.assertIsNone(boat["original_turn"])
        self.assertIsNone(boat["original_straight"])
        self.assertEqual(boat["preview_st"],.12)

    def test_motor_racer_map_and_result(self):
        result=convert(make_provider(result=True))
        self.assertEqual(result["results"],1)
        self.assertEqual(result["venues"][0]["races"][0]["boats"][1]["finish"],2)

    def test_bad_day_rejected_no_relabel(self):
        with self.assertRaises(SourceError):
            convert(make_provider(day="2026-10-13"))

    def test_duplicate_motor_in_race_rejected(self):
        with self.assertRaises(SourceError):
            convert(make_provider(motor_a=11,motor_b=11))

    def test_unexpected_host_and_bad_checksum_rejected(self):
        payload=json.dumps(make_provider()).encode()
        with self.assertRaises(SourceError):
            normalize(payload,day=DAY,received_at=OBSERVED,
                      source_url="https://example.com/today.json",
                      source_sha256=hashlib.sha256(payload).hexdigest())
        with self.assertRaises(SourceError):
            normalize(payload,day=DAY,received_at=OBSERVED,
                      source_url=URL,source_sha256="0"*64)

    def test_no_unacknowledged_upstream_download(self):
        with self.assertRaises(SourceError):
            fetch_one_day(DAY)
        self.assertEqual(URL,"https://boatraceopenapi.github.io/api/v1/2026/20261014.json")

    def test_incomplete_boats_are_partial(self):
        p=make_provider()
        p["programs"]["stadiums"]["19"]["races"]["9"]["racers"].pop("3")
        result=convert(p)
        self.assertEqual(result["complete_six_boat_races"],0)
        self.assertEqual(result["venues"][0]["races"][0]["boat_count"],5)

    def test_no_result_leakage_before_observation_time(self):
        result=convert(make_provider(result=True))
        self.assertEqual(datetime.fromisoformat(result["first_observed_at"]),
                         datetime.fromisoformat(OBSERVED.replace("Z", "+00:00")))
        self.assertIsNone(result["upstream_published_at"])
        self.assertNotIn("official_available_at"," ".join(result))

    def test_invalid_huge_source_rejected(self):
        with self.assertRaises(SourceError):
            normalize(b"x"*(MAX_BYTES+1),day=DAY,received_at=OBSERVED,
                      source_url=URL,source_sha256="a"*64)


if __name__=="__main__":
    unittest.main()
