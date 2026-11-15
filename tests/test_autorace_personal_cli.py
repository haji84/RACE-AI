"""Synthetic-only test of the actual no-network private file commands."""
import copy
from datetime import datetime
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from race_ai.autorace_personal_cli import run_predict, run_compare, _read
from tests.test_autorace_personal_baseline import sample
from race_ai.autorace_ab_pdca import PHASES


@unittest.skipUnless(os.name == "posix", "POSIX owner-only filesystem required")
class PersonalCLIFlow(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)/"secret"
        self.root.mkdir(mode=0o700)
        self.clock = lambda: datetime.fromisoformat("2030-01-15T09:22:00+09:00")

    def write(self,name,value):
        path=self.root/name
        path.write_text(json.dumps(value,ensure_ascii=False),encoding="utf-8")
        path.chmod(0o600)
        return path

    def test_same_race_a_b_file_storage_and_separate_result_preview(self):
        a = self.write("a-input.json",sample())
        b = self.write("b-input.json",sample(PHASES[1]))
        aout = self.root/"a.json"
        bout = self.root/"b.json"
        x=run_predict(a,aout,clock=self.clock)
        y=run_predict(b,bout,clock=self.clock)
        self.assertFalse(x["formal_hit_at_8_eligible"])
        self.assertEqual(x["phase"],PHASES[0])
        self.assertEqual(y["phase"],PHASES[1])
        self.assertEqual(stat.S_IMODE(aout.stat().st_mode),0o600)
        pa,pb=_read(aout),_read(bout)
        self.assertNotEqual(pa["input_sha256"],pb["input_sha256"])
        self.assertEqual(len(pb["ordered_top8"]),8)
        self.assertEqual(len(pb["supplemental_four"]),4)
        original=copy.deepcopy(pa)
        result=self.write("result.json",{
            "race_id":pa["race_id"],
            "winning_order":pa["ordered_top8"][0],
            "source_url":"https://example.test/fictional-finish",
            "captured_at":"2030-01-15T10:10:00+09:00",
        })
        scored=self.root/"preview.json"
        checked=run_compare(aout,result,scored,clock=lambda: datetime.fromisoformat(
            "2030-01-15T10:20:00+09:00"))
        self.assertEqual(checked["classification"],"USER_RECORDED_UNVERIFIED_RESEARCH")
        self.assertFalse(_read(scored)["formal_hit_at_8_eligible"])
        self.assertEqual(_read(scored)["hit8_personal"],1)
        self.assertEqual(_read(aout),original)
        with self.assertRaises(FileExistsError):
            run_predict(a,aout,clock=self.clock)
        with self.assertRaises(FileExistsError):
            run_compare(aout,result,scored,clock=lambda:datetime.fromisoformat(
                "2030-01-15T10:20:00+09:00"))

    def test_missing_or_duplicate_json_never_creates_forecast(self):
        p=self.root/"bad.json"
        p.write_text('{"schema":"A","schema":"B"}',encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"DUPLICATE_INPUT_JSON_KEY"):
            run_predict(p,self.root/"invalid-out.json",clock=self.clock)
        self.assertFalse((self.root/"invalid-out.json").exists())

    def test_untrusted_output_dir_refused(self):
        shared=Path(self.t.name)/"public"
        shared.mkdir(mode=0o755)
        shared.chmod(0o755)
        src=self.write("src.json",sample())
        with self.assertRaisesRegex(ValueError,"OUTPUT_DIRECTORY_NOT_PRIVATE"):
            run_predict(src,shared/"leak.json",clock=self.clock)

    def test_one_minute_before_cutoff_is_not_a_valid_predicted_forecast(self):
        src=self.write("input.json",sample())
        with self.assertRaisesRegex(ValueError,"AFTER_CUTOFF_OR_CAPTURE"):
            run_predict(src,self.root/"too-late.json",
                        clock=lambda:datetime.fromisoformat("2030-01-15T09:59:00+09:00"))
        self.assertFalse((self.root/"too-late.json").exists())


if __name__=="__main__":
    unittest.main()
