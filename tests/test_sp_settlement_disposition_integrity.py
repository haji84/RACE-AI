"""Contradictory official start/finish fields never acquire monetary finality."""
from copy import deepcopy
import unittest
from tests.test_boat_sp_settlement import document
from tests.intraday_fixture import packet
from tests.test_racer_daily import NOW
from race_ai.boat_sp_settlement import parse_settlement


class DispositionTests(unittest.TestCase):
    def parse(self,doc):
        raw,receipt=packet(doc,captured=NOW.isoformat())
        return parse_settlement(raw,receipt,now=NOW)

    def test_numeric_finish_cannot_hide_an_explicit_false_or_late_start(self):
        for disposition in ('F','L'):
            for refunds in ([],['6']):
                doc=document()
                next(r for r in doc['maindata']['stinfolist'] if r['teino']=='6')['st']=disposition+'0.12'
                doc['maindata']['returnlist']=refunds
                with self.subTest(disposition=disposition,refunds=refunds),self.assertRaises(ValueError):self.parse(doc)

    def test_consistent_nonfinisher_and_start_dispositions_remain_supported(self):
        for disposition in ('F','L'):
            doc=document();doc['maindata']['teiinfolist'][-1]['chk']=disposition
            next(r for r in doc['maindata']['stinfolist'] if r['teino']=='6')['st']=disposition+'0.12'
            doc['maindata']['returnlist']=['6']
            observation=self.parse(doc)
            self.assertEqual(observation['data']['refund_boats'],[6])
            wrong=deepcopy(doc)
            next(r for r in wrong['maindata']['stinfolist'] if r['teino']=='6')['st']='L0.12' if disposition=='F' else 'F0.12'
            with self.assertRaises(ValueError):self.parse(wrong)

    def test_other_nonfinisher_codes_cannot_hide_false_or_late_start_refunds(self):
        for disposition in ('F','L'):
            for finish in ('転','失','妨','不','エ'):
                doc=document();doc['maindata']['teiinfolist'][-1]['chk']=finish
                next(r for r in doc['maindata']['stinfolist'] if r['teino']=='6')['st']=disposition+'0.12'
                with self.subTest(start=disposition,finish=finish),self.assertRaises(ValueError):self.parse(doc)


if __name__=='__main__':unittest.main()
