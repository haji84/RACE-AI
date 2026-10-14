"""Synthetic equivalents of an observed payout-only official result layout.

No source HTML is retained here. Values/names are synthetic; the seven market
bodies, continuation rowspans and empty auxiliary tables reflect observation.
"""
from datetime import date
import hashlib
import re
import unittest

from race_ai.core import SourceError
from race_ai.official_race_updates import parse_update,endpoint
from tests.test_official_race_updates import page,results,starts

DAY=date(2026,10,15)
CAPTURE='2026-10-15T09:00:00+09:00'


def payout_table(*,omit=None,duplicate=False):
    markets=[('3連単',['1-2-3'],2),('3連<br>複',['1=2=3'],2),('2連単',['1-2'],2),
             ('2連複',['1=2'],2),('拡連複',['1=2','1=3','2=3'],5),('単勝',['1'],2),('複勝',['1','2'],3)]
    bodies=[]
    for label,combinations,size in markets:
        if label==omit:continue
        rows=[]
        for n in range(size):
            kind=f'<td rowspan="{size}">{label}</td>' if n==0 else ''
            row=('<td>'+combinations[n]+'</td><td>¥610</td><td>1</td>') if n<len(combinations) else '<td></td><td></td><td></td>'
            rows.append('<tr>'+kind+row+'</tr>')
        bodies.append('<tbody>'+''.join(rows)+'</tbody>')
    if duplicate:bodies.append(bodies[0])
    return '<table class="is-w495"><thead><tr><th>勝式</th><th>組番</th><th>払戻金</th><th>人気</th></tr></thead>'+''.join(bodies)+'</table>'


def auxiliary():
    return ''.join('<table><thead><tr><th>'+label+'</th></tr></thead><tbody><tr><td></td></tr></tbody></table>' for label in ('返還','決まり手','備考'))


def source(body):
    return page('raceresult',body).replace(b'jcd=18',b'jcd=14').replace(b'08:43',b'08:35')


def program():
    return [dict(lane=n,racer_registration_id=str(4000+n),name='選手'+str(n)) for n in range(1,7)]


class OfficialResultLiveShapeTests(unittest.TestCase):
    def parse(self,body,entries=None,**changes):
        arguments=dict(kind='raceresult',day=DAY,venue='14',race_no=1,
            source_url=endpoint(DAY,'14',1,'raceresult'),captured_at=CAPTURE,entries=entries)
        arguments.update(changes)
        return parse_update(source(body),**arguments)

    def full_body(self):
        # Replace only the synthetic legacy payout table, retaining six finish
        # rows and six actual-ST records from the existing fixture.
        return re.sub(r'<table><thead><tr><th>勝式.*?</table>',payout_table(),results())

    def test_exact_payout_only_profile_is_pending_without_inferred_finish_or_settlement(self):
        body=payout_table()+auxiliary();parsed=self.parse(body,program())
        self.assertEqual(parsed['status'],'PENDING')
        self.assertEqual(parsed['missing_reason'],'OFFICIAL_RESULT_PAYOUT_ONLY')
        self.assertIsNone(parsed['data']);self.assertTrue(parsed['body_identity_verified'])
        self.assertEqual(parsed['information_phase'],'official_result')
        self.assertFalse(parsed['eligible_pre_race'])
        self.assertEqual(parsed['source_sha256'],hashlib.sha256(source(body)).hexdigest())
        self.assertEqual(parsed['captured_at'],CAPTURE)
        self.assertEqual(parsed['available_at'],CAPTURE)
        self.assertIsNone(parsed['upstream_published_at'])

    def test_incomplete_duplicate_unknown_markets_and_malformed_prices_fail_closed(self):
        for body in (payout_table(omit='複勝')+auxiliary(),payout_table(duplicate=True)+auxiliary(),
                     (payout_table()+auxiliary()).replace('単勝','未知式'),
                     (payout_table()+auxiliary()).replace('¥610','NaN',1),
                     (payout_table()+auxiliary()).replace('¥610','¥0',1),
                     (payout_table()+auxiliary()).replace('rowspan="5"','rowspan="4"')):
            with self.subTest(body=body[:70]),self.assertRaises(SourceError):self.parse(body)

    def test_nonblank_auxiliary_or_partial_finish_start_sections_do_not_become_pending(self):
        body=payout_table()+auxiliary()
        invalids=[body.replace('<th>備考</th></tr></thead><tbody><tr><td></td>',
                               '<th>備考</th></tr></thead><tbody><tr><td>未検証'),
                  body.replace('<th>返還</th></tr></thead><tbody><tr><td></td>',
                               '<th>返還</th></tr></thead><tbody><tr><td><span class="numberSet1_number">6</span></td>'),
                  body+'<table><thead><tr><th>着</th><th>枠</th></tr></thead><tbody><tr><td>1</td><td>1</td></tr></tbody></table>',
                  body+starts('スタート情報')]
        for invalid in invalids:
            with self.subTest(body=invalid[-80:]),self.assertRaises(SourceError):self.parse(invalid)

    def test_full_results_accept_enclosing_program_context_when_race_id_absent(self):
        parsed=self.parse(self.full_body(),program())
        self.assertEqual(parsed['status'],'AVAILABLE')
        self.assertEqual(parsed['data']['top3'],[1,2,3])
        self.assertEqual(len(parsed['data']['results']),6)
        self.assertEqual(len(parsed['data']['payouts']),10)
        self.assertEqual(parsed['data']['entry_reconciliation'],'RESULT_EVIDENCE_JOINED_NOT_INDEPENDENTLY_REVIEWED')
        self.assertTrue(parsed['data']['confirmed']);self.assertTrue(parsed['data']['settlement_ready'])

    def test_explicit_wrong_null_race_id_and_roster_mismatches_are_never_overridden(self):
        for field,value in [('race_id',None),('race_id','20261015-14-02'),('race_id','20261014-14-01'),
                            ('racer_registration_id','4999'),('lane',2),('name','別選手')]:
            entries=program();entries[0][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(SourceError):self.parse(self.full_body(),entries)
            if field=='race_id':
                with self.subTest(pending_race_id=value),self.assertRaises(SourceError):self.parse(payout_table()+auxiliary(),entries)

    def test_existing_partial_market_readiness_and_source_date_guards_remain(self):
        partial=self.parse(results(),program())
        self.assertEqual(partial['data']['verified_market_types'],['trifecta'])
        self.assertFalse(partial['data']['confirmed']);self.assertFalse(partial['data']['settlement_ready'])
        body=payout_table()+auxiliary()
        with self.assertRaises(SourceError):self.parse(body,source_url=endpoint(DAY,'13',1,'raceresult'))
        with self.assertRaises(SourceError):self.parse(body,day=DAY.replace(day=14))
        with self.assertRaises(SourceError):self.parse(body,captured_at='2026-10-15T08:00:00+09:00')


if __name__=='__main__':unittest.main()
