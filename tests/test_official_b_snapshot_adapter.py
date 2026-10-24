import unittest
from datetime import date
from race_ai.core import SourceError
from race_ai.official_b_snapshot_adapter import normalize_b_snapshot


def fixture():
    lines = ["STARTB", "18BBGN", "2026/10/14", "１Ｒ 予選 Ｈ１８００ｍ"]
    lines += [f"{i} {4000+i} 選手" for i in range(1,7)]
    lines += ["18BEND"]
    return ("\n".join(lines) + "\n").encode("cp932")


class OfficialBSnapshotTests(unittest.TestCase):
    def test_no_motor_data_is_explicitly_unknown(self):
        result = normalize_b_snapshot(fixture(), day=date(2026,10,14),
            source_url="https://example.org/official", observed_at="2026-10-14T08:00:00+09:00")
        self.assertIsNone(result["venues"][0]["races"][0]["boats"][0]["motor_no"])

    def test_valid_motor_join_preserves_unknown_fields(self):
        motors = {(f"20261014-18-01", i): i+10 for i in range(1,7)}
        result = normalize_b_snapshot(fixture(), day=date(2026,10,14),
            source_url="https://example.org/official", observed_at="2026-10-14T08:00:00+09:00",
            motors=motors)
        self.assertEqual(result["races"], 1)
        self.assertEqual(result["complete_six_boat_races"], 1)
        self.assertIsNone(result["venues"][0]["races"][0]["boats"][0]["display_time"])

    def test_wrong_day_is_rejected(self):
        with self.assertRaises(SourceError):
            normalize_b_snapshot(fixture(), day=date(2026,10,13),
                source_url="https://example.org/official", observed_at="2026-10-13T08:00:00+09:00")

    def test_strict_program_details_and_closing_time_are_parsed_from_official_layout(self):
        raw = ('STARTB\n18BBGN\n２０２６年１０月１５日\n' + ''.join(
            f' {n}Ｒ 予選 Ｈ１８００ｍ 電話投票締切予定０８：４３\n'
            '艇 選手 選手 年 支 体級 全国 当地 モーター ボート\n'
            '番 登番 名 齢 部 重別 勝率 2率 勝率 2率 NO 2率 NO 2率\n' + ''.join(
                f'{i} {4000+i}選手名字42三重55A2 6.32 46.72 5.55 30.00 {10+i} 50.00{130+i} 23.68\n'
                for i in range(1,7)) for n in range(1,13)) + '18BEND\n').encode('cp932')
        result = normalize_b_snapshot(raw, day=date(2026,10,15), source_url='https://example.org/B',
            observed_at='2026-10-15T03:00:00+09:00', require_details=True, archive_sha256='b' * 64)
        first = result['venues'][0]['races'][0]
        self.assertEqual(first['closed_at'], '2026-10-15T08:43:00+09:00')
        self.assertEqual((first['boats'][0]['name'],first['boats'][0]['motor_no'],first['boats'][0]['boat_no']), ('選手名字',11,131))
        self.assertIsNone(first['boats'][0]['average_st'])
        self.assertEqual(result['source_sha256'], 'b' * 64)
        for changed in (raw.replace('２０２６年１０月１５日'.encode('cp932'),'２０２６年１０月１４日'.encode('cp932')),
                        raw.replace(b'11 50.00131', b'00 50.00131', 1)):
            with self.assertRaises(SourceError):
                normalize_b_snapshot(changed, day=date(2026,10,15), source_url='https://example.org/B',
                    observed_at='2026-10-15T03:00:00+09:00', require_details=True)

    def test_adjacent_rate_columns_with_100_percent_not_misparsed(self):
        rows = []
        for race in range(1, 13):
            rows.append(f'{race}Ｒ 予選 Ｈ１８００ｍ 電話投票締切予定０８：４３')
            for lane in range(1, 7):
                stats = '6.3246.725.55100.00' if lane == 1 else '6.32 46.72 5.55 30.00'
                rows.append(
                    f'{lane} {4000+lane}選手名字42三重55A2 {stats} '
                    f'{10+lane} 50.00{130+lane} 23.68'
                )
        program = ('STARTB\n18BBGN\n２０２６年１０月１５日\n' +
                   '\n'.join(rows) + '\n18BEND\n').encode('cp932')
        result = normalize_b_snapshot(
            program, day=date(2026, 10, 15),
            source_url='https://example.org/B',
            observed_at='2026-10-15T03:00:00+09:00',
            require_details=True
        )
        self.assertEqual(result['races'], 12)
        first = result['venues'][0]['races'][0]['boats'][0]
        self.assertEqual(first['national_win_rate'], 6.32)
        self.assertEqual(first['national_top2_rate'], 46.72)
        self.assertEqual(first['local_win_rate'], 5.55)
        self.assertEqual(first['local_top2_rate'], 100.0)
        self.assertEqual(first['motor_no'], 11)
        # Concatenation does not justify accepting an impossible >100% rate.
        bad = program.replace(b'5.55100.00', b'5.55101.00', 1)
        with self.assertRaises(SourceError):
            normalize_b_snapshot(
                bad, day=date(2026, 10, 15),
                source_url='https://example.org/B',
                observed_at='2026-10-15T03:00:00+09:00',
                require_details=True
            )
