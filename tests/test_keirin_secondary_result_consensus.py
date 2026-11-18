"""Fictional HTML source-free tests, not official results or real coverage."""
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import Mock
import unittest

from race_ai import keirin_secondary_result_consensus as result
from scripts import keirin_secondary_result_poll as poll
from scripts import keirin_capture_public_two_sources as source

RID="202611182601"
KD="https://keirin.kdreams.jp/seibuen/racedetail/2620261118010001/?pageType=result"
NET="https://keirin.netkeiba.com/race/result/?race_id=202611182601"
AT="2026-11-18T07:00:00+00:00"
HTML = ('''<html><title>西武園競輪 2026年11月18日 1R 結果・払戻</title>
<h2>1R 結果・払戻金</h2><p>結果確定</p>
<table><tr><th>３連単</th><td>7&gt;3&gt;4</td>
<td>5,590円</td><td>24人気</td></tr></table></html>''').encode()


class TwoSourceResearchResult(unittest.TestCase):
    def test_exact_real_style_pair_is_only_provisional(self):
        a=result.parse_observation(raw=HTML,provider="Kdreams",
                                   source_url=KD,race_id=RID,observed_at=AT)
        b=result.parse_observation(raw=HTML,provider="netkeirin",
                                   source_url=NET,race_id=RID,observed_at=AT)
        self.assertEqual(a["winning_triple"], [7,3,4])
        self.assertEqual(a["payout_per_100yen"], 5590)
        comparison=result.compare_sources(a,b)
        self.assertEqual(comparison["state"],
                         "SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL")
        self.assertFalse(comparison["official_primary_result_authenticated"])
        self.assertFalse(comparison["qualifies_for_formal_settlement"])
        self.assertEqual(len(comparison["provider_receipts"]),2)


    def test_kdreams_separated_payout_grid_without_adjacent_trifecta_label(self):
        # Real pages have '3 連 勝 複' and distant '単 7-3-4 5,590円'.
        kd_grid = ('''<html><title>西武園 2026年11月18日 1R 結果</title>
        <h2>1R 結果・払戻金</h2>
        <table><tr><td>3</td><td>連</td><td>単</td></tr>
        <tr><td>単</td><td>7-3-4</td><td>5,590円(24)</td></tr>
        </table></html>''').encode()
        obs = result.parse_observation(raw=kd_grid,provider="Kdreams",
             source_url=KD,race_id=RID,observed_at=AT)
        self.assertEqual(obs["winning_triple"], [7,3,4])
        self.assertEqual(obs["payout_per_100yen"], 5590)
        self.assertFalse(obs["official_organizer_result"])

    def test_wrong_date_or_race_hold_before_accepting_money(self):
        for bad in (HTML.replace(b"1R",b"2R"),
                    HTML.replace(b"2026",b"2025")):
            with self.assertRaises(result.ResultConsensusError):
                result.parse_observation(
                    raw=bad,provider="Kdreams",
                    source_url=KD,race_id=RID,observed_at=AT)

    def test_wrong_race_url_and_provider_not_accepted(self):
        bad=[
            ("Kdreams",KD.replace("0001/","0002/")),
            ("Kdreams",KD.replace("https:","http:")),
            ("netkeirin",NET.replace(RID,"202611182602")),
            ("netkeirin",NET.replace("netkeiba.com","bad.netkeiba.com")),
        ]
        for provider,url in bad:
            with self.subTest(url=url):
                with self.assertRaises(result.ResultConsensusError):
                    result.check_race_url(
                        provider=provider,url=url,race_id=RID)

    def test_not_final_or_refund_or_conflict_hold(self):
        bodies=[
            HTML.replace("5,590円".encode(), b"---"),
            HTML.replace("結果確定".encode(), "返還".encode()),
            HTML + "<p>３連単 1-2-3 900円</p>".encode(),
        ]
        for raw in bodies:
            with self.assertRaises(result.ResultConsensusError):
                result.parse_observation(
                    raw=raw,provider="Kdreams",
                    source_url=KD,race_id=RID,observed_at=AT)

    def test_disagreement_is_not_official_result(self):
        a=result.parse_observation(raw=HTML,provider="Kdreams",
                                   source_url=KD,race_id=RID,observed_at=AT)
        b=deepcopy(a)
        b["provider"]="netkeirin"
        b["payout_per_100yen"]=1234
        combined=result.compare_sources(a,b)
        self.assertEqual(combined["state"],
                         "HOLD_SECONDARY_RESULT_DISAGREEMENT")
        self.assertIsNone(combined["winning_triple"])

    def test_one_real_manifest_pair_one_get_each(self):
        manifest={"schema":source.SCHEMA,
                  "day_jst":"2026-11-18",
                  "source_use_scope":"OWNER_PERSONAL_RESEARCH_ONLY",
                  "races":[{
                      "race_id":RID,
                      "kdreams_url":KD.replace("?pageType=result",""),
                      "netkeirin_url":
                          "https://keirin.netkeiba.com/race/entry/?race_id="+RID,
                      "cutoff_hint":None,
                  }]}
        fetch=Mock(return_value=HTML)
        result_obj=poll.poll(manifest=manifest,race_id=RID,fetch=fetch,
                             clock=lambda:datetime(2026,11,18,7,tzinfo=timezone.utc))
        self.assertEqual(fetch.call_count,2)
        self.assertEqual(result_obj["payout_per_100yen"],5590)
        self.assertEqual(fetch.call_args_list[0].args[0],KD)
        self.assertEqual(fetch.call_args_list[1].args[0],NET)


if __name__=="__main__":
    unittest.main()
