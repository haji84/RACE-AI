import unittest
from race_ai.b_layout_shape_diagnostic import summarize_b_layout


def synthetic(rows, header='１Ｒ 予選 Ｈ１８００ｍ 電話投票締切予定０８：４３'):
    return ('STARTB\n18BBGN\n２０２６年１０月１５日\n' + header + '\n' + '\n'.join(rows) + '\n18BEND\n').encode('cp932')


def row(i):
    return f'{i} {4000+i}選手名字42三重55A2 6.32 46.72 5.55 30.00 {10+i} 50.00{130+i} 23.68'


class RedactedBLayoutDiagnosticsTests(unittest.TestCase):
    def test_structurally_valid_synthetic_rows(self):
        data = summarize_b_layout(synthetic([row(i) for i in range(1, 7)]))
        self.assertEqual(data['counts']['recognized_race_headers'], 1)
        self.assertEqual(data['counts']['strict_detail_regex_matches'], 6)
        self.assertEqual(data['counts']['strict_detail_regex_mismatches_after_header'], 0)
        self.assertEqual(data['classification'], 'NOT_IDENTIFIED_BY_AGGREGATE_SHAPE')
        self.assertNotIn('選手', str(data))
        self.assertNotIn('4001', str(data))

    def test_detects_structural_mismatch_without_source_data(self):
        data = summarize_b_layout(synthetic([row(1), '2 4002短い形式']))
        self.assertEqual(data['counts']['strict_detail_regex_matches'], 1)
        self.assertEqual(data['counts']['strict_detail_regex_mismatches_after_header'], 1)
        self.assertEqual(data['classification'], 'DETAIL_ROW_PATTERN_MISMATCH_DETECTED')
        self.assertNotIn('短い', str(data))

    def test_reports_unbound_entry_and_cutoff(self):
        raw = ('STARTB\n18BBGN\n' + row(1) + '\n１Ｒ 予選 Ｈ１８００ｍ\n18BEND\n').encode('cp932')
        data = summarize_b_layout(raw)
        self.assertEqual(data['counts']['entry_like_rows_before_header'], 1)
        self.assertEqual(data['counts']['headers_without_same_line_cutoff'], 1)
        self.assertEqual(data['classification'], 'POSSIBLE_ENTRY_BEFORE_HEADER')

    def test_rejects_bad_encoding_and_oversize(self):
        for content in (b'', b'\x81', b'0' * 4_000_001):
            with self.assertRaises(ValueError):
                summarize_b_layout(content)


if __name__ == '__main__':
    unittest.main()
