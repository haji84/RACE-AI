import unittest
from race_ai.boat_k_day_methods import method_of

class KMethodEvidence(unittest.TestCase):
    def test_printed_winner_or_separate_label_only(self):
        self.assertEqual(method_of(' 01  1 4444 AB 1.50.4   まくり差し\n 02 2 4111 CD 1.51.3'), 'makurizashi')
        self.assertEqual(method_of('   逃 げ\n 01  1 4444 AB'), 'nige')
        self.assertIsNone(method_of(' 01  1 逃げ田'))
        self.assertIsNone(method_of('   逃げ\n   差し'))
        self.assertIsNone(method_of(' 02  2 4123 AB 1.53.4    逃げ'))

    def test_official_result_table_header_method_is_explicit_evidence(self):
        header = "  着 艇 登番  選 手 名  モーター ボート 展示 進入 スタートタイミンク レースタイム 逃げ   "
        self.assertEqual(method_of(header), "nige")
        self.assertEqual(method_of(header.replace("逃げ", "まくり差し")), "makurizashi")
        self.assertIsNone(method_of(header + "\n" + header.replace("逃げ", "差し")))
        self.assertIsNone(method_of("レースタイム 逃げ"))
