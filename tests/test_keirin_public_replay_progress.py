import gzip
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from scripts import keirin_public_replay_progress as progress
from scripts.keirin_video_corpus import setup


class PublicReplayProgress(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.work = Path(tmp.name)
        self.corpus = self.work / "census.sqlite"
        self.state = self.work / "review.sqlite"
        self.out = self.work / "progress.jsonl"
        self.key = "20240805-11-01"
        self.url = "https://keirin.kdreams.jp/yenjoy/keirin-kaisai/race-card/result/1120240804/11202408040200/01/"
        with closing(sqlite3.connect(self.corpus)) as db:
            setup(db)
            db.execute("INSERT INTO race VALUES(?,?,?,?,?)", (self.key, "2024-08-05", 0, "unknown", None))
            db.execute("INSERT INTO race VALUES(?,?,?,?,?)", ("20240805-11-02", "2024-08-05", 0, "cancelled_reported", None))
            db.commit()

    def import_rows(self, *rows, index=None, checkpoints=None):
        path = self.work / "notes.jsonl.gz"
        with gzip.open(path, "wt", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row) + "\n")
        return progress.update(self.corpus, self.state, [path], index, self.out, checkpoints)

    def record(self, **attrs):
        return {"race": self.key.replace("-", ""), "source_url": self.url, "evidence": "viewed in player", **attrs}

    def test_failed_played_unreadable_observed_survive_retry(self):
        for state in ("failed", "playback_only", "unreadable"):
            self.assertEqual(self.import_rows(self.record(status=state))["in_census"][state], 1)
        known = self.record(back_car=4, back_seconds=48.5, corner_car=None)
        for _ in range(2):
            self.assertEqual(self.import_rows(known)["in_census"]["observed"], 1)
        row = json.loads(self.out.read_text().splitlines()[0])
        self.assertEqual(row["reported_leaders"], {"back": [4]})
        self.assertEqual(len(row["receipts"]), 4)
        self.import_rows(self.record(back_car=2, back_seconds=48.5))
        row = json.loads(self.out.read_text().splitlines()[0])
        self.assertEqual(row["status"], "conflicting_observations")
        self.assertEqual(row["reported_leaders"]["back"], [2, 4])

    def test_adjudicated_unknown_does_not_revalidate_a_previous_positive_label(self):
        initial = self.record(back_car=4, back_seconds=46, corner_car=2, corner_seconds=58)
        adjudicated = dict(initial, back_car=None, adjudication={"reason": "riders overlap"})
        self.import_rows(initial, adjudicated)
        row = json.loads(self.out.read_text().splitlines()[0])
        self.assertEqual(row["status"], "conflicting_observations")
        self.assertEqual(row["disputed_phases"], ["back"])
        self.assertEqual(len(row["receipts"]), 2)

    def test_incorrect_note_cannot_replace_ledger_or_commit_earlier_rows_in_batch(self):
        self.import_rows(self.record(status="failed"))
        previous = self.out.read_bytes()
        wrong = self.record(source_url=self.url.replace("11202408040200", "11202408040300"), status="unreadable")
        with self.assertRaises(ValueError):
            self.import_rows(self.record(status="playback_only"), wrong)
        self.assertEqual(self.out.read_bytes(), previous)
        with closing(sqlite3.connect(self.state)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM public_player_note").fetchone()[0], 1)
        for unsupported in (self.record(), self.record(status="failed", back_car=4, back_seconds=42),
                            self.record(back_car=True, back_seconds=40), self.record(corner_car=4),
                            self.record(back_car=3, back_seconds=45, corner_car=4, corner_seconds=40)):
            with self.subTest(row=unsupported), self.assertRaises(ValueError):
                self.import_rows(unsupported)

    def test_historical_button_and_wrong_archive_identity_do_not_count_as_playback(self):
        idx = self.work / "archive.jsonl"
        link = "https://keirin.kdreams.jp/stadium/digest/?kyogijoCd=11&kaisaiDate=20240805&raceNo=1"
        refs = {"a" * 64: {"url": link, "surface": "normal_markup"}}
        row = {"race_id": self.key, "published_replay_references": refs}
        idx.write_text(json.dumps(row) + "\n")
        self.assertEqual(self.import_rows(index=idx)["in_census"]["published_button"], 1)
        refs["a" * 64]["url"] = link.replace("raceNo=1", "raceNo=2")
        idx.write_text(json.dumps(row) + "\n")
        with self.assertRaises(ValueError):
            self.import_rows(index=idx)

    def test_complete_roster_rejects_absent_leader_and_follower_but_preserves_follower_only(self):
        with closing(sqlite3.connect(self.corpus)) as db:
            db.execute("UPDATE race SET complete_roster=1 WHERE id=?", (self.key,))
            db.executemany("INSERT INTO starter VALUES(?,?,?)", [(self.key, n, None) for n in range(1, 8)])
            db.commit()
        for field in ("back_car", "back_nearest_follower_car", "back_second_car", "back_runner_up"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "absent from the complete roster"):
                self.import_rows(self.record(back_seconds=42, **{field: 8}))
        self.import_rows(self.record(back_car=None, back_second_car=4, back_seconds=42))
        row = json.loads(self.out.read_text().splitlines()[0])
        self.assertEqual(row["status"], "observed")
        self.assertEqual(row["reported_leaders"], {})
        self.assertEqual(row["reported_followers"], {"back": [4]})
        self.import_rows(self.record(back_car=None, back_second_car=1, back_seconds=42))
        disputed = json.loads(self.out.read_text().splitlines()[0])
        self.assertEqual(disputed["disputed_phases"], ["back"])

    def test_old_checkpoints_need_matching_race_source_and_frame_digest(self):
        frame = "a" * 64
        row = {"race_id": self.key, "source_ref": self.url, "checkpoints": [
            {"checkpoint": "back", "ordered_front_cars": [2], "at_ms": 30000, "sha256": frame}]}
        path = self.work / "old.jsonl"
        path.write_text(json.dumps(row) + "\n")
        with closing(sqlite3.connect(self.corpus)) as db:
            db.execute("INSERT INTO media VALUES(?,?,?,?,?)",
                       (self.key, self.url, "frames", "frames", json.dumps({"30000": frame})))
            db.commit()
        self.assertEqual(self.import_rows(checkpoints=path)["in_census"]["prior_rider_review"], 1)
        row["checkpoints"][0]["sha256"] = "b" * 64
        path.write_text(json.dumps(row) + "\n")
        with self.assertRaises(ValueError):
            self.import_rows(checkpoints=path)

    def test_missing_race_inside_window_and_cancelled_race_reject_observation(self):
        for suffix in ("2", "3"):
            data = self.record(race=self.key.replace("-", "")[:-1] + suffix,
                               source_url=self.url[:-3] + suffix + "/", back_car=1, back_seconds=25)
            with self.subTest(race=suffix), self.assertRaises(ValueError):
                self.import_rows(data)
        outside = self.record(race="202408061101", source_url=self.url.replace("11202408040200", "11202408040300"),
                              back_car=3, back_seconds=25)
        result = self.import_rows(outside)
        self.assertEqual(result["outside_window"], {"observed": 1})
        self.assertEqual(result["in_census"], {"calendar_only": 1, "cancelled_reported": 1})


if __name__ == "__main__":
    unittest.main()
