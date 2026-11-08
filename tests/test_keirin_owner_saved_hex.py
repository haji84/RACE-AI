"""Owner-provided synthetic KEIRIN HEX-style Markdown, NO site requests."""
import csv
from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
import unittest

from race_ai.keirin_owner_saved_hex import (
    convert_owner_saved_hex_markdown, stage_owner_saved_hex_markdown
)
from race_ai.keirin_owner_saved_csv import (
    OwnerRacecardError, stage_owner_saved_csv
)
from race_ai.keirin_owner_manual import PersonalOwnerObservations
from race_ai.keirin_allowed_delivery import assemble_permitted_pre_race
from test_keirin_owner_saved_csv import (
    fictitious_csv, meta as owner_meta, NOW
)

URL = "https://keirinhex.jp/races/20300115/013620300115/"


def saved_page(*, contradictory=False):
    rows=list(csv.DictReader(io.StringIO(
        fictitious_csv(contradict=contradictory).decode("utf-8"))))
    out=[
        "# fictional-venue 1R 2030年01月15日",
        "## KEIRIN HEX の印",
        "主導権の見込みは 1-2-3 が64%と表示（モデルへ入力禁止）",
        "## 並び",
        "並び予想は 1-2-3／4-5-6-7。公式確定ラインではありません。",
        "## 出走表",
        "車  | 選手  | 競走得点  | 脚質 | etc",
        "---|---|---",
    ]
    for r in rows:
        n=int(r["car_no"])
        vals=[
            r["car_no"],
            ("◎" if n==1 else "☆")+r["rider_name"]+"県・A3・125期",
            r["race_score"],r["style"],
            "架空の過去成績","架空の前場所",
            r["starts"],
            ("45%" if n==1 else "10%"),
            ("65%" if n==1 else "30%"),
            ("70%" if n==1 else "45%"),
            r["wins"],r["seconds"],r["thirds"],r["unplaced"],
            r["s_count"],r["h_count"],r["b_count"],
            r["escape_count"],r["makuri_count"],r["sashi_count"],
            r["mark_count"],r["gear"]
        ]
        out.append("  |  ".join(vals))
    out+=["## 結果", "これ以降は予想時点で未知。取り込まない。"]
    return "\n".join(out)


def checked_meta(page):
    base=owner_meta(fictitious_csv(),source_url=URL)
    base["source_sha256"]=sha256(page.encode("utf-8")).hexdigest()
    return base


class MarkdownRacecardTests(unittest.TestCase):
    def test_saved_visible_table_converts_realistic_scores_without_predictions(self):
        page=saved_page()
        parsed=convert_owner_saved_hex_markdown(page,checked_meta(page))
        self.assertEqual(parsed["provider_network_requests"],0)
        self.assertTrue(parsed["source_lineup_is_prediction_only"])
        self.assertFalse(parsed["upstream_marks_and_probabilities_used"])
        self.assertFalse(parsed["provider_data_rights_independently_proven"])
        self.assertEqual(parsed["placing_count_conflict_riders"],[])
        self.assertGreater(parsed["converted_observation_count"],50)
        self.assertIn(b"306.15",parsed["csv"])
        self.assertNotIn(b"64%",parsed["csv"])
        self.assertNotIn("◎".encode("utf-8"),parsed["csv"])
        self.assertIn(b"car_no,rider_name",parsed["csv"])

    def test_saved_markdown_can_be_staged_into_existing_347_audit(self):
        page=saved_page()
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            (p/"markdown").mkdir()
            (p/"markdown"/"one.md").write_text(page,encoding="utf-8")
            (p/"markdown"/"one.meta.json").write_text(
                json.dumps(checked_meta(page)),encoding="utf-8")
            report=stage_owner_saved_hex_markdown(p,now=NOW)
            self.assertEqual(report["translated_markdown"],1)
            self.assertEqual(report["provider_http_requests"],0)
            csv_report=stage_owner_saved_csv(p,now=NOW)
            self.assertEqual(csv_report["staged_csv"],1)
            raw_json=next((p/"raw").glob("*.json"))
            packet=json.loads(raw_json.read_text(encoding="utf-8"))
            grant=PersonalOwnerObservations(
                source_hosts=["keirinhex.jp"],now=NOW)
            audit=assemble_permitted_pre_race(
                packet,grant_check=grant.allowed,checked_at=NOW)
            self.assertEqual(audit["status"]["checked_count"],347)
            self.assertGreater(audit["status"]["verified_items"],0)
            self.assertIsNone(audit["private_snapshot"])
            # An incomplete web table is NOT enough for model predictions.
            self.assertGreater(len(audit["status"]["missing_model_inputs"]),0)
            replay=stage_owner_saved_hex_markdown(p,now=NOW)
            self.assertEqual(replay["already_translated"],1)

    def test_source_lineup_mismatch_blocks(self):
        page=saved_page()
        info=checked_meta(page)
        info["observed_race_facts"]["line_order_all_riders"]["lines"][0]["order"]=[1,3,2]
        with self.assertRaisesRegex(OwnerRacecardError,"LINEUP_SOURCE_DISAGREES"):
            convert_owner_saved_hex_markdown(page,info)

    def test_markdown_hash_and_non_rakuten_host_bound(self):
        page=saved_page()
        info=checked_meta(page)
        info["source_sha256"]="0"*64
        with self.assertRaisesRegex(OwnerRacecardError,"SHA_MISMATCH"):
            convert_owner_saved_hex_markdown(page,info)
        info=checked_meta(page)
        info["source_url"]="https://keirin.kdreams.jp/race/2030"
        with self.assertRaisesRegex(OwnerRacecardError,"KEIRIN_HEX_OWNER_SOURCE"):
            convert_owner_saved_hex_markdown(page,info)

    def test_truncated_table_and_missing_roster_never_promoted(self):
        page=saved_page()
        shortened=page.splitlines()
        shortened=[x for x in shortened if not x.startswith("7  |")]
        partial="\n".join(shortened)
        with self.assertRaisesRegex(OwnerRacecardError,"NOT_ALL_STARTERS"):
            convert_owner_saved_hex_markdown(partial,checked_meta(partial))

    def test_synthetic_past_capture_cannot_be_backdated_by_the_runner(self):
        page=saved_page()
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            (p/"markdown").mkdir()
            (p/"markdown"/"sample.md").write_text(page,encoding="utf-8")
            (p/"markdown"/"sample.meta.json").write_text(
                json.dumps(checked_meta(page)),encoding="utf-8")
            result=stage_owner_saved_hex_markdown(
                p,now="2030-01-15T10:01:00+09:00")
            self.assertEqual(result["rejected_markdown"],1)
            self.assertEqual(list((p/"csv").glob("*.csv")),[])


if __name__=="__main__":
    unittest.main()
