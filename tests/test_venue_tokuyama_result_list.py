import unittest
from datetime import date
from race_ai.core import SourceError
from race_ai.venue_tokuyama_result_list import parse_result_list

URL="https://www.boatrace-tokuyama.jp/modules/raceinfo/?page=index_resultlist&resultday=20261013"
ROW="<tr><td>3R</td><td>1-2-6</td><td>1,130円</td><td>1-2</td><td>270円</td><td></td><td>リプレイ</td></tr>"

class TokuyamaResultListTests(unittest.TestCase):
    def test_payout_only(self):
        result=parse_result_list("<table>"+ROW+"</table>",source_url=URL,day=date(2026,10,13))
        self.assertEqual(result["races"][0]["trifecta_lanes"],[1,2,6])
        self.assertEqual(result["races"][0]["trifecta_payout_yen"],1130)
        self.assertFalse(result["races"][0]["result_detail_verified"])
        self.assertNotIn("actual_course",result["races"][0])

    def test_wrong_date_rejected(self):
        with self.assertRaises(SourceError):
            parse_result_list("<table>"+ROW+"</table>",source_url=URL,day=date(2026,10,14))

    def test_mismatched_2t_rejected(self):
        with self.assertRaises(SourceError):
            parse_result_list("<table>"+ROW.replace("<td>1-2</td>","<td>2-1</td>")+"</table>",
                              source_url=URL,day=date(2026,10,13))

    def test_no_results_rejected(self):
        with self.assertRaises(SourceError):
            parse_result_list("<table><tr><td>更新までしばらくお待ちください</td></tr></table>",
                              source_url=URL,day=date(2026,10,13))
