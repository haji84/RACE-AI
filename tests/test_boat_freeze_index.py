"""Only registry/bookkeeping tests; no actual odds or fabricated live forecasts."""
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
import unittest

from race_ai.boat_freeze_index import load_original_race_ids

ROOT=Path(__file__).resolve().parents[1]
REAL=ROOT/"docs/evidence/2026-11-03/boat-canonical-freeze-index.json"
CHECK_AT="2026-11-03T15:00:00+09:00"


class CrossChatFreezeIndexTest(unittest.TestCase):
    def setUp(self):
        self.data=json.loads(REAL.read_text(encoding="utf-8"))

    def check(self,change):
        document=deepcopy(self.data)
        change(document)
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/"registry.json"
            p.write_text(json.dumps(document,ensure_ascii=False),encoding="utf-8")
            return load_original_race_ids(p,as_of=CHECK_AT)

    def test_single_nine_originals_with_national_batch_links(self):
        ids=load_original_race_ids(REAL,as_of=CHECK_AT)
        self.assertEqual(len(ids),9)
        self.assertIn("20261103-17-02",ids)
        self.assertIn("20261103-17-03",ids)
        self.assertIn("20261103-17-04",ids)
        self.assertIn("20261103-04-06",ids)
        self.assertIn("20261103-22-06",ids)
        self.assertIn("20261103-09-07",ids)
        self.assertIn("20261103-06-07",ids)
        self.assertIn("20261103-02-07",ids)

    def test_no_duplicate_and_no_aftercutoff_backfill(self):
        for mutation in (
            lambda d:d["entries"].append(deepcopy(d["entries"][0])),
            lambda d:d["entries"][0].update(server_created_at=d["entries"][0]["cutoff_at"]),
            lambda d:d["entries"][0].update(server_created_at="2026-11-03T10:54:30+09:00"),
            lambda d:d["entries"][0].update(race_id="20261103-99-02"),
            lambda d:d["entries"][0].update(bundle_sha256="a"),
            lambda d:d.update(scope="ALL_NATIONAL"),
            lambda d:d["entries"][0].update(predicted_hit=1),
            lambda d:d["entries"][4].update(json_sha256="0"*64),
        ):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.check(mutation)

    def test_next_day_uses_same_original_index_only_as_dedup(self):
        ids=load_original_race_ids(REAL,as_of="2026-11-04T09:00:00+09:00")
        self.assertEqual(ids,load_original_race_ids(REAL,as_of=CHECK_AT))
        with self.assertRaises(ValueError):
            load_original_race_ids(REAL,as_of="2026-11-03T10:00:00+09:00")

    def test_duplicate_json_keys_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/"registry.json"
            p.write_text('{"schema":"A","schema":"B"}')
            with self.assertRaises(ValueError):
                load_original_race_ids(p,as_of=CHECK_AT)


if __name__=="__main__":
    unittest.main()
