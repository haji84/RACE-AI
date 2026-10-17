import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from race_ai.preview_feed_pipeline import prepare


def official_b():
    rows = ["STARTB", "18BBGN", "2026/10/14", "１Ｒ 予選 Ｈ１８００ｍ"]
    rows.extend(f"{i} {4000+i} 選手" for i in range(1,7))
    rows.append("18BEND")
    return ("\n".join(rows) + "\n").encode("cp932")


class PreviewFeedPipelineTests(unittest.TestCase):
    def test_unapproved_source_never_writes_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, approval, output = root/"official.txt",root/"approval.json",root/"web/data/today.json"
            source.write_bytes(official_b())
            approval.write_text("{}",encoding="utf-8")
            with self.assertRaises(ValueError):
                prepare(source=source,approval=approval,output=output,
                    day=date(2026,10,14),source_url="https://example.org/official",
                    observed_at="2026-10-14T08:00:00+09:00")
            self.assertFalse(output.exists())

    def test_approved_fixture_writes_expected_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, approval, output = root/"official.txt",root/"approval.json",root/"web/data/today.json"
            source.write_bytes(official_b())
            approval.write_text(json.dumps({
                "redistribution_authorized":True,
                "source_url":"https://example.org/official",
                "evidence_reference":"synthetic-fixture-only",
                "reviewed_by":"test"}),encoding="utf-8")
            prepare(source=source,approval=approval,output=output,
                day=date(2026,10,14),source_url="https://example.org/official",
                observed_at="2026-10-14T08:00:00+09:00")
            value=json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(value["races"],1)
            self.assertIsNone(value["venues"][0]["races"][0]["boats"][0]["motor_no"])
