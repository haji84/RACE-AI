"""NAR 54-column payout schema parser, all fictional 2030 data."""
import unittest

from race_ai.nar_official_payback_adapter import (
    stage_nar_payback, NarFormatError, RESULT_SCHEMA, COLUMNS
)
from tests.test_nar_official_csv_adapter import (
    csv_bytes, DAY, VENUE, OBS
)
from tests.test_permissioned_source_delivery import (
    SRC, KEY, gate, policy_doc
)

AFTER = "2030-01-15T11:00:00+09:00"
START = "2030-01-15T10:00:00+09:00"


def payback_row(*, triple=(1,2,3), yen="10020", race="7"):
    row=[""]*COLUMNS
    row[:4]=[VENUE,"20300115",race,"架空レース名"]
    if triple is not None:
        row[49:52]=[str(i) for i in triple]
        row[52]=yen
        row[53]="999" # popularity column must never appear in output
    return row


def stage(rows=None, *, policy=None, obs=AFTER, now=AFTER, header=False):
    parts=rows or [payback_row()]
    if header:
        parts=[["競馬場","競走年月日","レース番号"]+[""]*(COLUMNS-3)]+parts
    return stage_nar_payback(
        csv_bytes(parts),policy or gate(at=AFTER),
        at=now,observed_at=obs,source_ref=SRC,
        rights_ref="fictional-permission-1",event_date_jst=DAY,
        venue=VENUE,race_no=7,scheduled_start_at=START,
        encoding="utf-8-sig",has_header=header
    )


class SettlementTests(unittest.TestCase):
    def test_single_result_kept_separate_from_forecast(self):
        v=stage()
        self.assertEqual(v["schema"],RESULT_SCHEMA)
        self.assertEqual(v["winning_trifectas_reported"],
                         [{"combination":[1,2,3],"official_stated_payback_yen":10020}])
        self.assertFalse(v["official_result_authenticated"])
        self.assertFalse(v["may_count_in_hit_at_8"])
        self.assertFalse(v["forecast_changed"])
        self.assertNotIn("popularity",str(v).lower())
        self.assertNotIn("999",str(v))
        self.assertEqual(len(v["settlement_stage_sha256"]),64)

    def test_dead_heat_two_rows_different_winners(self):
        got=stage([payback_row(triple=(1,2,3),yen="2350"),
                   payback_row(triple=(1,3,2),yen="1200")])
        self.assertEqual(len(got["winning_trifectas_reported"]),2)
        self.assertTrue(got["dead_heat_multiple_combinations"])
        self.assertFalse(got["result_revision_confirmed"])

    def test_no_winner_is_unknown_not_counted_as_miss(self):
        v=stage([payback_row(triple=None)])
        self.assertEqual(v["race_outcome_status"],"NOT_EVALUABLE_UNKNOWN")
        self.assertFalse(v["may_count_in_hit_at_8"])

    def test_result_time_guard_and_missing_permissions(self):
        with self.assertRaisesRegex(NarFormatError,"before scheduled start"):
            stage(obs=OBS,now=AFTER)
        restricted=gate(policy_doc(["collection","analysis"]),at=AFTER)
        with self.assertRaisesRegex(NarFormatError,"SOURCE_PERMISSION_NOT_ADMITTED"):
            stage(policy=restricted)

    def test_malformed_duplicate_and_wrong_schema_rejected(self):
        with self.assertRaisesRegex(NarFormatError,"duplicate/invalid"):
            stage([payback_row(),payback_row()])
        with self.assertRaisesRegex(NarFormatError,"duplicate/invalid"):
            stage([payback_row(triple=(1,1,2))])
        row=payback_row()
        row[49]=""
        with self.assertRaisesRegex(NarFormatError,"incomplete"):
            stage([row])
        with self.assertRaisesRegex(NarFormatError,"54 columns"):
            stage([payback_row()[:-1]])
        with self.assertRaisesRegex(NarFormatError,"no matching"):
            stage([payback_row(race="6")])

    def test_header_requires_declared_mode(self):
        self.assertEqual(stage(header=True)["race_no"],7)
        row=["競馬場","競走年月日","レース番号"]+[""]*(COLUMNS-3)
        with self.assertRaisesRegex(NarFormatError,"unexpected payback header"):
            stage([row,payback_row()],header=False)


if __name__=="__main__":
    unittest.main()
