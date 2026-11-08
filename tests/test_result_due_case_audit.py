"""Private per-race reason classification; use real bitset and no network."""
import unittest
from race_ai import result_due_ledger as D, result_due_case_audit as C

NOW='2026-11-08T11:01:00+00:00'

def row(rid,status,**kwargs):
    return dict(sport='boat',race_id=rid,event_date_jst=D._rid_day(rid),
                result=dict(status=status),**kwargs)

class DueCaseReasonTests(unittest.TestCase):
    def fresh(self):
        control={}
        return control,D.ledger(control,now=NOW)

    def test_62_cases_are_individually_private_and_public_summary_is_count_only(self):
        control,due=self.fresh()
        rows=[row(f'20261108-{(n//12)+1:02d}-{(n%12)+1:02d}',
                  'missing' if n%3==0 else 'pending' if n%3==1 else 'unsupported')
              for n in range(62)]
        D.update(due,rows,now=NOW)
        counts=C.record(control,due,rows)
        self.assertEqual(counts['outstanding'],62)
        self.assertEqual(sum(counts['status_counts'].values()),62)
        self.assertEqual(sum(counts['reason_counts'].values()),62)
        for item in rows:
            self.assertNotIn(item['race_id'],str(counts))
        self.assertEqual(len(control['result_due_case_reasons']['cases']),62)
        self.assertEqual(C.summary(control,due),counts)

    def test_silent_loss_and_tampered_private_reason_are_rejected(self):
        control,due=self.fresh()
        rid='20261107-02-07'
        D.update(due,[row(rid,'missing')],now=NOW)
        C.record(control,due,[row(rid,'missing')])
        control['result_due_case_reasons']['cases'][rid]['reason']='RESULT_NOT_FINAL'
        with self.assertRaisesRegex(ValueError,'RESULT_DUE_CASE_CHECKSUM_INVALID'):
            C.summary(control,due)

    def test_unknown_old_saved_day_is_not_declared_resolved(self):
        control,due=self.fresh()
        rid='20170101-12-07'
        D.update(due,[row(rid,'pending')],now=NOW)
        result=C.record(control,due,[])
        self.assertEqual(result['outstanding'],1)
        self.assertEqual(result['reason_counts']['UNSCANNED_SAVED_DAY'],1)
        self.assertEqual(result['unattributed'],1)

    def test_reference_only_or_failed_model_proof_cannot_count_as_final(self):
        control,due=self.fresh()
        a=row('20261107-01-01','final')
        a['result']['cutoff_reference']={'formal_eligible':False}
        b=row('20261107-01-02','final',
              prediction={'cutoff_at':'2026-11-07T10:00:00+09:00',
                          'persisted_at':'2026-11-07T10:01:00+09:00'})
        D.update(due,[a,b],now=NOW)
        D.hold_model_ids(due,[b],[b['race_id']],now=NOW)
        summary=C.record(control,due,[a,b])
        self.assertEqual(summary['outstanding'],2)
        self.assertEqual(summary['reason_counts'],{
            'RESULT_REFERENCE_ONLY':1,'MODEL_PRE_CUTOFF_PROOF_MISSING':1})

    def test_resolved_case_does_not_erase_other_pending_cases(self):
        control,due=self.fresh()
        x=row('20261107-01-01','pending')
        y=row('20261107-01-02','pending')
        D.update(due,[x,y],now=NOW)
        C.record(control,due,[x,y])
        D.update(due,[row(x['race_id'],'final')],now=NOW)
        result=C.record(control,due,[row(x['race_id'],'final'),y])
        self.assertEqual(result['outstanding'],1)
        self.assertEqual(result['resolved_total'],1)
        self.assertEqual(set(control['result_due_case_reasons']['cases']),{y['race_id']})
        self.assertTrue(result['all_cases_accounted_for'])

if __name__=='__main__':
    unittest.main()
