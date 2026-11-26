"""Synthetic racecard layouts for the result-unread input boundary."""

import unittest

from race_ai.keirin_nationwide_auto_generator import generate_evidence_analysis
from race_ai.keirin_result_unread_racecard import snapshot_from_cards


RACE_ID = "203001159803"
# Meeting day two uses the meeting start date in Kdreams' URL.
KDREAMS_URL = "https://keirin.kdreams.jp/fictional/racedetail/9820300114020003/"
NETKEIRIN_URL = f"https://keirin.netkeiba.com/race/entry/?race_id={RACE_ID}"


def line_cars(cars):
    spans = []
    for car in cars:
        if car == "space":
            spans.append('<span class="icon_p space"></span>')
        elif car in ("bracket_open", "bracket_close"):
            spans.append(f'<span class="icon_p {car}"></span>')
        else:
            car, role = car if isinstance(car, tuple) else (car, '追込')
            spans.append(f'<span class="icon_p"><span class="p00{car}">{car}</span>'
                         f'<span>{role}</span></span>')
    return '<div class="line_position">' + ''.join(spans) + '</div>'


def kdreams_card(*, cars=(1, 2, 3, 4, 5), scratch=(), class_label="Ａ級予選",
                 formation=(1, 2, "space", 3, 4, 5), misleading_dom="", points=None):
    header = ''.join(f'<th rowspan="2">{text}</th>' for text in
                     ('予 想', '好 気 合', '総 評', '枠 番', '車 番',
                      '選手名<br>府県/年齢/期別', '級 班', '脚 質', 'ギヤ 倍数'))
    header += '<th colspan="14">直近4ヶ月の成績</th>'
    rows = [f'<tr>{header}</tr>', '<tr><th>競走得点</th>' + '<th>例</th>' * 13 + '</tr>']
    for car in cars:
        notice = '<span class="absence">欠場</span>' if car in scratch else ''
        score = points[car] if points is not None else 91.25 - car
        rows.append(
            f'<tr class="n{car}"><td class="tip">{"◎" if car == 1 else ""}</td>'
            '<td class="kiai"></td><td class="evaluation bdr_r"></td>'
            f'<td class="bracket">{car}</td><td class="num">{car}</td>'
            f'<td class="rider bdr_r">例示選手{car}<br><span class="home">例県</span>'
            f'/26/100{notice}</td><td>A2</td><td class="bdr_r">{"逃" if car == 1 else "追"}</td>'
            f'<td>3.92</td><td class="bdr_r">{score}</td>'
            + '<td>99</td>' * 13 + '</tr>'
        )
    predicted = f'<dt>並び予想</dt><dd>{line_cars(formation)}</dd>' if formation else ''
    # The same widget also appears under a non-predictive heading.
    finish = f'<dt>確定着順</dt><dd>{line_cars((5, 4, 3, 2, 1))}</dd>' if misleading_dom else ''
    return (
        f'<html><head><link rel="canonical" href="{KDREAMS_URL}"></head><body>'
        f'{misleading_dom}<section class="section raceinfo_section">'
        '<div class="raceinfo_contents-wrapper"><div class="raceinfo_contents">'
        f'<div class="racecard_header"><div class="inner"><h2 class="title">'
        f'<span class="status">{class_label}</span></h2></div></div>'
        '<div class="racecard_contents">'
        '<table class="racecard_table"><tbody>' + ''.join(rows) + '</tbody></table>'
        '<table class="racecard_table past_racecard_table none">'
        '<tr><td class="num">9</td><td class="rider">今開催の着順</td></tr>'
        '</table></div><dl class="racecard_footer-contents">'
        f'{finish}{predicted}</dl></div></div></section></body></html>'
    ).encode()


def snapshot(raw, **kwargs):
    return snapshot_from_cards(race_id=RACE_ID, kdreams_raw=raw,
                               kdreams_url=KDREAMS_URL, **kwargs)


def conditional_b(raw, **kwargs):
    from race_ai.keirin_result_unread_racecard import contested_hypotheses_from_card

    return contested_hypotheses_from_card(race_id=RACE_ID, kdreams_raw=raw,
                                         kdreams_url=KDREAMS_URL, **kwargs)


def netkeirin_card(*, cars=(1, 2, 3, 4, 5), scratch=(), conflicting_name=None):
    rows = []
    for car in cars:
        name = '別の例示選手' if car == conflicting_name else f'例示選手{car}'
        notice = '<span class="absence">出走取消</span>' if car in scratch else ''
        rows.append(
            f'<tr id="player-{car}" class="PlayerList"><td class="RaceCardCell01"></td>'
            f'<td class="RaceCardCell01 Waku{car}">{car}</td>'
            '<td class="Player_Select"></td><td class="RaceCardCell01 Yoso01"></td>'
            f'<td class="Player_Info"><a class="Player01"><dl><dt class="PlayerName">'
            f'{name}<svg><title>お気に入り</title></svg></dt></dl></a>{notice}</td>'
            '<td class="RaceCardCell01 GroupLeft">99.99</td></tr>'
        )
    return (
        f'<html><head><link rel="canonical" href="{NETKEIRIN_URL}"></head><body>'
        '<div class="RaceList_NameBox"><div class="RaceList_NameBox_inner">'
        '<div class="Race_Num">3R</div></div>'
        f'<a class="Active" href="{NETKEIRIN_URL}&amp;rf=courselist">3R</a></div>'
        '<div class="RaceCard_PlayerList01"><div class="RaceCard_Simple_Table_Static">'
        '<table id="RaceCard_Table_Static" class="RaceCard_Table RaceCard_Simple_Table"><tbody>'
        + ''.join(rows) + '</tbody></table></div></div>'
        '<table id="RaceCard_Table_Fixed" class="RaceCard_Table"><tbody>'
        '<tr id="player-9" class="PlayerList"><td>確定着順</td></tr></tbody></table>'
        '</body></html>'
    ).encode()


class ResultUnreadRacecardTests(unittest.TestCase):
    def test_only_the_scoped_entry_and_predicted_line_feed_the_model(self):
        other_tables = (
            '<div class="result"><table class="racecard_table"><tr>'
            '<td class="num">8</td><td class="rider">確定着順</td><td>88880円</td>'
            '</tr></table><div class="odds">54.1</div>'
            '<dl class="racecard_footer-contents"><dt>並び予想</dt>'
            f'<dd>{line_cars((5, 4, 3, 2, 1))}</dd></dl></div>'
        )
        result = snapshot(kdreams_card(misleading_dom=other_tables))
        self.assertEqual(result, snapshot(kdreams_card()))
        self.assertEqual(result['race_id'], RACE_ID)
        self.assertEqual(result['competition'], 'A1_A2')
        self.assertEqual(result['line_groups'], [[1, 2], [3, 4, 5]])
        self.assertEqual(result['riders'], [
            dict(car=1, name='例示選手1', competition_points=90.25, style='NIGE', mark_rank=1),
            dict(car=2, name='例示選手2', competition_points=89.25, style='MARK', mark_rank='UNMARKED'),
            dict(car=3, name='例示選手3', competition_points=88.25, style='MARK', mark_rank='UNMARKED'),
            dict(car=4, name='例示選手4', competition_points=87.25, style='MARK', mark_rank='UNMARKED'),
            dict(car=5, name='例示選手5', competition_points=86.25, style='MARK', mark_rank='UNMARKED'),
        ])
        analysis = generate_evidence_analysis(result)
        for arm in ('A', 'B'):
            self.assertEqual(analysis[arm]['state'], 'GENERATED_RESEARCH_ONLY')
        observed = analysis['feature_audit']['riders'][0]['observed']
        self.assertEqual(observed['competition_points'], 90.25)
        self.assertTrue(all(value is None for key, value in observed.items() if key != 'competition_points'))

    def test_marked_scratches_preserve_real_non_contiguous_car_numbers(self):
        result = snapshot(kdreams_card(cars=(1, 2, 3, 4, 5, 6, 7), scratch=(2, 5),
                                      formation=(1, 3, 'space', 4, 6, 7)))
        self.assertEqual([rider['car'] for rider in result['riders']], [1, 3, 4, 6, 7])
        self.assertEqual(result['line_groups'], [[1, 3], [4, 6, 7]])
        analysis = generate_evidence_analysis(result)
        self.assertEqual(analysis['B']['state'], 'GENERATED_RESEARCH_ONLY')
        self.assertTrue(all(set(ticket) <= {1, 3, 4, 6, 7}
                            for ticket in analysis['B']['ranked_tickets']))

    def test_girls_preserve_published_order_as_individual_positions(self):
        result = snapshot(kdreams_card(class_label='Ｌ級ガールズ予選', formation=(3, 1, 5, 4, 2)))
        self.assertEqual(result['competition'], 'GIRLS')
        self.assertEqual(result['line_groups'], [[3], [1], [5], [4], [2]])

    def test_optional_selected_entry_crosschecks_identity_and_can_mark_scratches(self):
        cars = (1, 2, 3, 4, 5, 6, 7)
        raw = kdreams_card(cars=cars, formation=(1, 3, 'space', 4, 6, 7))
        result = snapshot(raw, netkeirin_raw=netkeirin_card(cars=cars, scratch=(2, 5)),
                          netkeirin_url=NETKEIRIN_URL)
        self.assertEqual([rider['car'] for rider in result['riders']], [1, 3, 4, 6, 7])
        self.assertEqual(result['riders'][0]['competition_points'], 90.25)
        self.assertEqual(result['line_groups'], [[1, 3], [4, 6, 7]])
        with self.assertRaisesRegex(ValueError, 'NETKEIRIN_ROSTER_CONFLICT'):
            snapshot(raw, netkeirin_raw=netkeirin_card(cars=cars, conflicting_name=1),
                     netkeirin_url=NETKEIRIN_URL)
        with self.assertRaisesRegex(ValueError, 'NETKEIRIN_ROSTER_CONFLICT'):
            snapshot(raw, netkeirin_raw=netkeirin_card(), netkeirin_url=NETKEIRIN_URL)

    def test_line_with_a_named_scratch_is_held_as_stale(self):
        result = snapshot(kdreams_card(cars=(1, 2, 3, 4, 5, 6), scratch=(2,),
                                      formation=(1, 2, 3, 'space', 4, 5, 6)))
        self.assertEqual([rider['car'] for rider in result['riders']], [1, 3, 4, 5, 6])
        self.assertIsNone(result['line_groups'])
        self.assertIn('並び予想の車番と出走表が一致しません。', result['line_warnings'])

    def test_missing_mismatched_and_contested_formation_hold_only_b(self):
        for formation, expected_warning in (
            ((), '並び予想を取得できません。'),
            ((1, 2, 'space', 4, 5, 7), '並び予想の車番と出走表が一致しません。'),
            ((1, 'bracket_open', 2, 3, 'bracket_close', 'space', 4, 5),
             '並び予想に競りの記載があり、単一の並びを確定できません。'),
            ((1, (2, '競り'), 3, 'space', 4, 5),
             '並び予想に競りの記載があり、単一の並びを確定できません。'),
        ):
            with self.subTest(formation=formation):
                result = snapshot(kdreams_card(formation=formation, misleading_dom='<aside>非対象</aside>'))
                self.assertIsNone(result['line_groups'])
                self.assertIn(expected_warning, result['line_warnings'])
                analysis = generate_evidence_analysis(result)
                self.assertEqual(analysis['A']['state'], 'GENERATED_RESEARCH_ONLY')
                self.assertEqual(analysis['B']['state'], 'UNGENERATED_LINE_EVIDENCE_MISSING')

    def test_rejects_missing_card_roster_or_wrong_source_binding(self):
        with self.assertRaisesRegex(ValueError, 'STARTER_ROSTER'):
            snapshot(kdreams_card(cars=(1, 2, 3, 4)))
        with self.assertRaisesRegex(ValueError, 'CANONICAL'):
            snapshot(kdreams_card().replace(KDREAMS_URL.encode(), KDREAMS_URL.replace('0003/', '0004/').encode()))
        with self.assertRaisesRegex(ValueError, 'KDREAMS_RACE_DETAIL_ID_MISMATCH'):
            snapshot_from_cards(race_id=RACE_ID[:-1] + '4', kdreams_raw=kdreams_card(),
                                kdreams_url=KDREAMS_URL)
        with self.assertRaisesRegex(ValueError, 'KDREAMS_ORDINARY_RACECARD'):
            snapshot_from_cards(race_id=RACE_ID, kdreams_raw=kdreams_card(),
                                kdreams_url=KDREAMS_URL + '?pageType=showResult')

    def test_single_contest_generates_two_hypothetical_b_candidate_lists(self):
        points = {1: 103, 2: 101, 3: 91, 4: 92, 5: 89, 6: 72, 7: 72}
        raw = kdreams_card(cars=tuple(points), points=points, formation=(
            1, 'bracket_open', (2, '競り'), (3, '競り'), 'bracket_close', 4, 'space', 5, 6, 'space', 7,
        ))
        base = snapshot(raw)
        self.assertIsNone(base['line_groups'])
        hypotheses = conditional_b(raw)
        self.assertEqual([(case['cars'], case['independent_cars'], case['line_groups']) for case in hypotheses], [
            ([2], [3], [[1, 2, 4], [5, 6], [7], [3]]),
            ([3], [2], [[1, 3, 4], [5, 6], [7], [2]]),
        ])
        for case, groups in zip(hypotheses, ([[1, 2, 4], [5, 6], [7], [3]], [[1, 3, 4], [5, 6], [7], [2]])):
            self.assertIn('単独', case['condition'])
            self.assertIn('仮定', case['condition'])
            model = generate_evidence_analysis(dict(base, line_groups=groups))['B']
            self.assertTrue(model['ranked_tickets'])
            self.assertEqual(case['tickets'], {'3t': model['ranked_tickets'], '2t': model['ranked_2ren_tan']})
        self.assertFalse(hypotheses[1]['tickets']['2t'])

    def test_two_contests_generate_the_four_joint_full_roster_partitions(self):
        points = {1: 103, 2: 101, 3: 91, 4: 92, 5: 89, 6: 72, 7: 72}
        raw = kdreams_card(cars=tuple(points), points=points, formation=(
            1, 'bracket_open', (2, '競り'), (3, '競り'), 'bracket_close',
            'bracket_open', (4, '競り'), (5, '競り'), 'bracket_close', 'space', 6, 7,
        ))
        hypotheses = conditional_b(raw)
        self.assertEqual([(case['cars'], case['independent_cars'], case['line_groups']) for case in hypotheses], [
            ([2, 4], [3, 5], [[1, 2, 4], [6, 7], [3], [5]]),
            ([2, 5], [3, 4], [[1, 2, 5], [6, 7], [3], [4]]),
            ([3, 4], [2, 5], [[1, 3, 4], [6, 7], [2], [5]]),
            ([3, 5], [2, 4], [[1, 3, 5], [6, 7], [2], [4]]),
        ])
        self.assertTrue(all('1か所目' in case['condition'] and '2か所目' in case['condition'] for case in hypotheses))
        self.assertFalse(hypotheses[1]['tickets']['3t'])
        self.assertTrue(hypotheses[1]['tickets']['2t'])

    def test_conditional_card_holds_when_every_trifecta_branch_abstains(self):
        raw = kdreams_card(cars=(1, 2, 3, 4, 5, 6, 7), formation=(
            1, 'bracket_open', (2, '競り'), (3, '競り'), 'bracket_close', 4, 'space', 5, 6, 'space', 7,
        ))
        with self.assertRaisesRegex(ValueError, 'RACECARD_CONTEST_NO_TRIFECTA_SELECTION'):
            conditional_b(raw)

    def test_conditional_path_requires_explicit_two_rider_brackets_and_exact_car_set(self):
        for formation, error in (
            ((1, 'bracket_open', (2, '競り'), 3, 'bracket_close', 'space', 4, 5),
             'RACECARD_CONTEST_BRACKET_UNSUPPORTED'),
            ((1, (2, '競り'), (3, '競り'), 'space', 4, 5), 'RACECARD_CONTEST_BRACKET_UNSUPPORTED'),
            ((1, 'bracket_open', (2, '競り'), (3, '競り'), (4, '競り'), 'bracket_close', 5),
             'RACECARD_CONTEST_BRACKET_UNSUPPORTED'),
            ((1, 'bracket_open', (2, '競り'), (3, '競り'), 'bracket_close', 'space', 2, 5),
             'RACECARD_CONTEST_ROSTER_CONFLICT'),
        ):
            with self.subTest(formation=formation), self.assertRaisesRegex(ValueError, error):
                conditional_b(kdreams_card(formation=formation))

        off_scope = ('<dl class="racecard_footer-contents"><dt>並び予想</dt><dd>'
                     + line_cars((1, 'bracket_open', (2, '競り'), (3, '競り'), 'bracket_close', 4, 5))
                     + '</dd></dl>')
        with self.assertRaisesRegex(ValueError, 'RACECARD_CONTEST_BRACKET_REQUIRED'):
            conditional_b(kdreams_card(formation=(), misleading_dom=off_scope))
