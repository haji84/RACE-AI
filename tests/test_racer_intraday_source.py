"""Wrong course/identity/chronology must never enter athlete statistics."""
from copy import deepcopy
from datetime import datetime,timezone
import unittest
from tests.intraday_fixture import result_document,packet
try:
    from race_ai import racer_intraday_source as source
except ImportError:source=None

NOW=datetime(2026,11,7,2,tzinfo=timezone.utc)

class SourceTests(unittest.TestCase):
    def parse(self,doc=None,*,captured='2026-11-07T01:10:00Z',edit=None):
        self.assertIsNotNone(source,'per-race official facts must be connected')
        raw,receipt=packet(doc,captured=captured)
        if edit:edit(receipt)
        return source.parse_result(raw,receipt,now=NOW)
    def test_explicit_course_and_registration_join_is_independent_of_array_or_frame_order(self):
        out=self.parse();rows={r['racer_id']:r for r in out['rows']}
        self.assertEqual(out['status'],'CONFIRMED');self.assertEqual(out['race_id'],'20261107-01-01')
        self.assertEqual((rows['4001']['lane'],rows['4001']['course'],rows['4001']['finish'],rows['4001']['st']),(1,2,1,.11))
        self.assertEqual((rows['4006']['lane'],rows['4006']['course']),(6,5))
        self.assertEqual(len(out['deadlines']),12)
    def test_same_facts_with_a_new_server_clock_are_not_a_new_result_revision(self):
        a=self.parse();d=result_document();d['dataheader']['cdatetime']='another server time'
        self.assertEqual(a['fact_sha256'],self.parse(d,captured='2026-11-07T01:20:00Z')['fact_sha256'])
    def test_non_numeric_disposition_revision_is_retained_without_inventing_k_code_translation(self):
        d=result_document();d['maindata']['teiinfolist'][2]['chk']='転';a=self.parse(d)
        d['maindata']['teiinfolist'][2]['chk']='妨';b=self.parse(d)
        self.assertNotEqual(a['fact_sha256'],b['fact_sha256'])
        self.assertIsNotNone(a.get('statistics_sha256'),'cross-source comparison must distinguish code vocabulary from actual aggregate inputs')
        self.assertEqual(a['statistics_sha256'],b['statistics_sha256'])
    def test_f_l_and_confirmed_absence_keep_separate_start_semantics(self):
        d=result_document();d['maindata']['teiinfolist'][0]['chk']='Ｆ';d['maindata']['teiinfolist'][1]['chk']='L';d['maindata']['teiinfolist'][5]['chk']='欠'
        for r in d['maindata']['stinfolist']:
            if r['teino']=='1':r['st']='F.02'
            if r['teino']=='2':r['st']='L1.10'
            if r['teino']=='6':r.update(cs=0,csdisp='0',boatflag=0,st='')
        rows={r['racer_id']:r for r in self.parse(d)['rows']}
        self.assertEqual((rows['4001']['finish'],rows['4001']['st_status']),(None,'F'))
        self.assertEqual(rows['4002']['st_status'],'L')
        self.assertEqual((rows['4006']['st_status'],rows['4006']['course']),('ABSENT',None))
    def test_pending_unknown_finish_and_explicit_cancellation_do_not_create_starts(self):
        self.assertEqual(self.parse(result_document(pending=True))['status'],'PENDING')
        d=result_document();d['maindata']['teiinfolist'][0]['chk']='00'
        self.assertEqual(self.parse(d)['rows'],[])
        d=result_document();d['maindata'].update(rstop=1,teiinfolist=[],stinfolist=[])
        self.assertEqual(self.parse(d)['status'],'CANCELLED');self.assertEqual(self.parse(d)['rows'],[])
    def test_absent_reserved_slot_is_not_mistaken_for_an_actual_entry_course(self):
        d=result_document();d['maindata']['teiinfolist'][5]['chk']='欠'
        for r in d['maindata']['stinfolist']:
            if r['teino']=='6':r.update(cs=6,csdisp='0',boatflag=0,st='')
        try:out=self.parse(d)
        except ValueError as e:self.fail('the real absent-boat display slot must remain absent: '+str(e))
        own=next(r for r in out['rows'] if r['racer_id']=='4006')
        self.assertEqual((own['st_status'],own['course']),('ABSENT',None))
    def test_wrong_race_course_binding_hash_or_future_clock_is_rejected(self):
        mutations=[lambda d:d['holdingheader'].update(hd='20261106'),lambda d:d['maindata'].update(rno=2),lambda d:d['raceheader'].update(rno=3),
          lambda d:d['maindata']['teiinfolist'][0].update(registno='4002'),lambda d:d['maindata']['stinfolist'][0].update(cs=2),lambda d:d['maindata']['stinfolist'][0].update(csdisp='3')]
        for change in mutations:
            d=result_document();change(d)
            with self.subTest(change=change),self.assertRaises(ValueError):self.parse(d)
        with self.assertRaises(ValueError):self.parse(edit=lambda r:r.update(source_sha256='0'*64))
        with self.assertRaises(ValueError):self.parse(captured='2026-11-07T03:00:00Z')
        with self.assertRaises(ValueError):self.parse(captured='2026-11-07T00:55:00Z')
