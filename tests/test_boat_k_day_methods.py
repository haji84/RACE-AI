import unittest
from race_ai.boat_k_day_methods import method_of

class KMethodEvidence(unittest.TestCase):
    def test_printed_winner_or_separate_label_only(self):
        self.assertEqual(method_of(' 01  1 4444 AB 1.50.4   まくり差し\n 02 2 4111 CD 1.51.3'), 'makurizashi')
        self.assertEqual(method_of('   逃 げ\n 01  1 4444 AB'), 'nige')
        self.assertIsNone(method_of(' 01  1 逃げ田'))
        self.assertIsNone(method_of('   逃げ\n   差し'))
        self.assertIsNone(method_of(' 02  2 4123 AB 1.53.4    逃げ'))
