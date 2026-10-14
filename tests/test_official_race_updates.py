"""Synthetic HTML reflecting the separately observed official DOM structure."""
from datetime import date
import re
import unittest

from race_ai.core import SourceError
from race_ai.official_race_updates import parse_update, endpoint, settlement_for_market

DAY=date(2026,10,15)
CAPTURE='2026-10-15T07:00:00+09:00'


def page(kind,body,day=DAY):
    heads=''.join(f'<th{(" class=\"is-thColor2\"" if n!=1 else "")}><a href="/owpc/pc/race/{kind}?rno={n}&amp;jcd=18&amp;hd={day:%Y%m%d}">{n}R</a></th>' for n in range(1,13))
    return ('<div class="contentsFrame1_inner"><table><thead><tr><th>レース</th>'+heads+
            '</tr></thead><tbody><tr><td>締切予定時刻</td>'+''.join('<td>08:43</td>' for _ in range(12))+
            '</tr></tbody></table>'+body+'</div>').encode()


def starts(label='スタート展示'):
    return '<table><thead><tr><th>'+label+'</th></tr></thead><tbody>'+''.join(
        f'<tr><td><span class="table1_boatImage1Number is-type{i}">{i}</span>'
        f'<img src="/static_extra/pc/images/img_boat2_{i}.png"><span class="table1_boatImage1Time">.1{i}</span></td></tr>'
        for i in range(1,7))+'</tbody></table>'


def preview():
    rows=''.join(f'<tbody><tr><td class="is-boatColor{i}">{i}</td><td><img></td>'
        f'<td><a href="/owpc/pc/data/racersearch/profile?toban={4000+i}">選手{i}</a></td>'
        '<td>52.0kg</td><td>6.92</td><td>0.0</td></tr></tbody>' for i in range(1,7))
    return '<table><thead><tr><th>枠 写真 ボートレーサー 体重 展示 タイム チルト</th></tr></thead>'+rows+'</table>'+starts()+(
        '<div class="weather1"><p class="weather1_title">水面気象情報 08:00現在</p>'
        '<div class="weather1_bodyUnit is-wind"><span class="weather1_bodyUnitLabelTitle">風速</span><span class="weather1_bodyUnitLabelData">6m</span></div>'
        '<div class="weather1_bodyUnit is-wave"><span class="weather1_bodyUnitLabelTitle">波高</span><span class="weather1_bodyUnitLabelData">6cm</span></div></div>')


def odds(final=False,missing=False):
    headers=''.join(f'<th class="is-boatColor{i}">{i}</th><th colspan="2" class="is-boatColor{i}">選手{i}</th>' for i in range(1,7))
    rows=[]
    for n in range(20):
        cells=[]
        for first in range(1,7):
            second=[x for x in range(1,7) if x!=first][n//4]
            third=[x for x in range(1,7) if x not in (first,second)][n%4]
            if n%4==0: cells.append(f'<td rowspan="4">{second}</td>')
            cells.append(f'<td>{third}</td><td class="oddsPoint">'+('--' if missing else '15.5')+'</td>')
        rows.append('<tr>'+''.join(cells)+'</tr>')
    return '<p class="tab4_time">'+('締切時オッズ' if final else '08:00現在')+'</p><table><thead><tr>'+headers+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table>'


def results(refund=False):
    rows=''.join(f'<tr><td>{i}</td><td class="is-boatColor{i}">{i}</td><td>{4000+i} 選手{i}</td><td>1\'51"7</td></tr>' for i in range(1,7))
    return '<table><thead><tr><th>着</th><th>枠</th><th>ボートレーサー</th><th>レースタイム</th></tr></thead><tbody>'+rows+'</tbody></table>'+starts('スタート情報')+(
        '<table><thead><tr><th>勝式</th><th>組番</th><th>払戻金</th><th>人気</th></tr></thead><tbody><tr><td>3連単</td><td>1-2-3</td><td>¥610</td><td>1</td></tr></tbody></table>'
        '<table><thead><tr><th>返還</th></tr></thead><tbody><tr><td>'+('<span class="numberSet1_number is-type6">6</span>' if refund else '')+'</td></tr></tbody></table>')


class OfficialUpdateTests(unittest.TestCase):
    def parse(self,kind,body,stamp=CAPTURE):
        return parse_update(page(kind,body),kind=kind,day=DAY,venue='18',race_no=1,
                            source_url=endpoint(DAY,'18',1,kind),captured_at=stamp)

    def test_preview_identity_display_st_and_weather_are_separate_from_actuals(self):
        data=self.parse('beforeinfo',preview())
        self.assertEqual(len(data['data']['boats']),6)
        self.assertEqual(data['data']['boats'][0]['display_time'],6.92)
        self.assertEqual(data['data']['boats'][0]['preview_st'],0.11)
        self.assertIsNone(data['data']['boats'][0]['actual_course'])
        self.assertEqual(data['data']['weather']['wind_speed_mps'],6)
        self.assertTrue(data['eligible_pre_race'])
        self.assertNotIn('actual_st',data['data']['boats'][0])
        upcoming=page('beforeinfo',preview()).replace(b'is-thColor2',b'is-thColor3')
        self.assertEqual(parse_update(upcoming,kind='beforeinfo',day=DAY,venue='18',race_no=1,
            source_url=endpoint(DAY,'18',1,'beforeinfo'),captured_at=CAPTURE)['status'],'AVAILABLE')

    def test_odds_enumerate_all120_and_final_odds_cannot_be_prerace_features(self):
        data=self.parse('odds3t',odds())
        self.assertEqual(len(data['data']['odds']),120)
        self.assertEqual(data['data']['odds'][0]['odds'],'15.5')
        self.assertTrue(data['eligible_pre_race'])
        final=self.parse('odds3t',odds(final=True))
        self.assertFalse(final['eligible_pre_race'])
        self.assertEqual(final['data']['odds_phase'],'final')

    def test_missing_market_and_preview_values_are_pending_not_zero(self):
        data=self.parse('odds3t',odds(missing=True))
        self.assertEqual(data['status'],'PENDING')
        self.assertTrue(all(row['odds'] is None for row in data['data']['odds']))
        data=self.parse('beforeinfo',preview().replace('6.92','--').replace('.11','--').replace('.12','--').replace('.13','--').replace('.14','--').replace('.15','--').replace('.16','--'))
        self.assertEqual(data['status'],'PENDING')
        self.assertIsNone(data['data']['boats'][0]['display_time'])

    def test_observed_empty_exhibition_grid_is_pending_only_with_six_entry_identities(self):
        blank='<table><thead><tr><th>スタート展示</th></tr></thead><tbody>'+''.join('<tr><td></td></tr>' for _ in range(6))+'</tbody></table>'
        body=preview().replace(starts(),blank).replace('6.92','').replace('<td>0.0</td>','<td></td>')
        data=self.parse('beforeinfo',body)
        self.assertEqual(data['status'],'PENDING');self.assertTrue(data['body_identity_verified'])
        self.assertIsNone(data['data'])
        self.assertEqual(data['missing_reason'],'OFFICIAL_PREVIEW_EMPTY_EXHIBITION_GRID')
        self.assertEqual(data['observed_racers'][0]['racer_registration_id'],'4001')
        arguments=dict(kind='beforeinfo',day=DAY,venue='18',race_no=1,source_url=endpoint(DAY,'18',1,'beforeinfo'),captured_at=CAPTURE)
        entries=[dict(racer) for racer in data['observed_racers']]
        self.assertEqual(parse_update(page('beforeinfo',body),entries=entries,**arguments)['status'],'PENDING')
        entries[0]['racer_registration_id']='4999'
        with self.assertRaises(SourceError): parse_update(page('beforeinfo',body),entries=entries,**arguments)
        for invalid in (body.replace('toban=4001','toban=4002'),body.replace(blank,blank.replace('<tr><td></td></tr>','',1)),
                        body.replace(blank,blank.replace('<td></td>','<td>.11</td>',1))):
            with self.assertRaises(SourceError): self.parse('beforeinfo',invalid)

    def test_all_zero_odds_placeholder_requires_complete_grid_and_update_clock(self):
        body=odds().replace('15.5','0.0').replace('<p class="tab4_time">08:00現在</p>',
            '<p class="title2_add">オッズ更新時間 <span>6:48</span></p>')
        data=self.parse('odds3t',body)
        self.assertEqual(data['status'],'PENDING');self.assertTrue(data['body_identity_verified'])
        self.assertIsNone(data['data'])
        self.assertEqual(data['missing_reason'],'OFFICIAL_ODDS_ALL_ZERO_PLACEHOLDER')
        self.assertIsNone(data['observed_racers'][0]['racer_registration_id'])
        entries=[dict(lane=n,racer_registration_id=str(4000+n),name='選手'+str(n)) for n in range(1,7)]
        entries[0]['name']='別選手'
        with self.assertRaises(SourceError):
            parse_update(page('odds3t',body),kind='odds3t',day=DAY,venue='18',race_no=1,
                source_url=endpoint(DAY,'18',1,'odds3t'),captured_at=CAPTURE,entries=entries)
        for invalid in (body.replace('0.0','15.5',1),body.replace('オッズ更新時間','不明'),
                        body.replace('6:48','26:48'),body.replace('rowspan="4"','rowspan="3"',1)):
            with self.assertRaises(SourceError): self.parse('odds3t',invalid)

    def test_result_finish_actual_st_payout_and_refund_are_explicit(self):
        data=self.parse('raceresult',results(),stamp='2026-10-15T09:00:00+09:00')
        self.assertFalse(data['eligible_pre_race'])
        self.assertEqual(data['data']['results'][0]['actual_st'],0.11)
        self.assertEqual(data['data']['payouts'][0]['payout_per_100_yen'],610)
        self.assertTrue(data['data']['finish_confirmed'])
        self.assertFalse(data['data']['confirmed'])
        self.assertFalse(data['data']['settlement_ready'])
        self.assertEqual(data['data']['verified_market_types'],['trifecta'])
        self.assertTrue(settlement_for_market(data,'trifecta')['confirmed'])
        with self.assertRaises(SourceError): settlement_for_market(data,'exacta')
        self.assertEqual(self.parse('raceresult',results(refund=True),stamp='2026-10-15T09:00:00+09:00')['data']['refund_boats'],[6])

    def test_no_data_is_pending_without_verified_body_identity_or_fake_results(self):
        data=parse_update('<p>データがありません。</p>'.encode(),kind='raceresult',day=DAY,venue='18',race_no=1,
            source_url=endpoint(DAY,'18',1,'raceresult'),captured_at=CAPTURE)
        self.assertEqual(data['status'],'PENDING')
        self.assertFalse(data['body_identity_verified'])
        self.assertIsNone(data['data'])

    def test_explicit_result_pending_and_cancelled_are_distinct(self):
        pending=self.parse('raceresult','<p>結果はまだありません。</p>')
        self.assertEqual(pending['status'],'PENDING')
        self.assertTrue(pending['body_identity_verified'])
        cancelled=self.parse('raceresult','<span class="heading1_mainLabel">レース中止</span>')
        self.assertEqual(cancelled['data']['status'],'cancelled')
        self.assertEqual(cancelled['data']['payouts'],[])
        self.assertTrue(cancelled['data']['confirmed'])
        postponed=self.parse('raceresult','<span class="heading1_mainLabel">レース延期</span>')
        self.assertEqual(postponed['status'],'PENDING')
        self.assertFalse(postponed['data']['confirmed'])
        self.assertIsNone(postponed['data']['refunds'])

    def test_special_payout_and_dead_heat_use_only_explicit_source_values(self):
        special=self.parse('raceresult',results().replace('1-2-3','特払い').replace('¥610','¥70'),stamp='2026-10-15T09:00:00+09:00')
        self.assertEqual(special['data']['status'],'special')
        self.assertEqual(special['data']['special_payouts'][0]['payout_per_100_yen'],70)
        tied=self.parse('raceresult',results().replace('<td>2</td><td class="is-boatColor2">','<td>1</td><td class="is-boatColor2">'),stamp='2026-10-15T09:00:00+09:00')
        self.assertEqual(tied['data']['status'],'dead_heat')
        self.assertIsNone(tied['data']['top3'])

    def test_ties_and_multihit_markets_require_complete_winner_coverage(self):
        def body(label,combinations,tie=False):
            payout='<table><thead><tr><th>勝式</th><th>組番</th><th>払戻金</th><th>人気</th></tr></thead><tbody>'+''.join(
                f'<tr><td>{label}</td><td>{combo}</td><td>¥610</td><td>1</td></tr>' for combo in combinations)+'</tbody></table>'
            result=re.sub(r'<table><thead><tr><th>勝式.*?</table>',payout,results())
            return result.replace('<td>2</td><td class="is-boatColor2">','<td>1</td><td class="is-boatColor2">') if tie else result
        tied=self.parse('raceresult',body('単勝',['1'],tie=True),stamp='2026-10-15T09:00:00+09:00')
        self.assertNotIn('win',tied['data']['verified_market_types'])
        with self.assertRaises(SourceError): settlement_for_market(tied,'win')
        for label,market,incomplete,complete in (('複勝','place',['1'],['1','2']),
                ('拡連複','quinella_place',['1=2'],['1=2','1=3','2=3'])):
            partial=self.parse('raceresult',body(label,incomplete),stamp='2026-10-15T09:00:00+09:00')
            self.assertNotIn(market,partial['data']['verified_market_types'])
            full=self.parse('raceresult',body(label,complete),stamp='2026-10-15T09:00:00+09:00')
            self.assertIn(market,full['data']['verified_market_types'])

    def test_stale_swapped_malformed_and_duplicate_structures_fail_closed(self):
        for kind,body in (('beforeinfo',preview().replace('toban=4001','toban=4002')),
                          ('odds3t',odds().replace('15.5','NaN',1)),
                          ('raceresult',results().replace('4001','4002'))):
            with self.subTest(kind=kind),self.assertRaises(SourceError): self.parse(kind,body)
        with self.assertRaises(SourceError):
            parse_update(page('beforeinfo',preview(),DAY.replace(day=14)),kind='beforeinfo',day=DAY,venue='18',race_no=1,
                source_url=endpoint(DAY,'18',1,'beforeinfo'),captured_at=CAPTURE)

    def test_program_registration_reconciliation_reuses_existing_result_bridge(self):
        entries=[dict(race_id='20261015-18-01',lane=i,racer_registration_id=str(4000+i),motor_no=i) for i in range(1,7)]
        arguments=dict(kind='raceresult',day=DAY,venue='18',race_no=1,source_url=endpoint(DAY,'18',1,'raceresult'),captured_at='2026-10-15T09:00:00+09:00')
        result=parse_update(page('raceresult',results()),entries=entries,**arguments)
        self.assertIn('RESULT_EVIDENCE_JOINED',result['data']['entry_reconciliation'])
        entries[0]['racer_registration_id']='4999'
        with self.assertRaises(SourceError): parse_update(page('raceresult',results()),entries=entries,**arguments)
