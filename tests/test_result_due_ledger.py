"""Pure tests: no Git credentials, source GET, or real race results."""
from datetime import datetime, timezone
import unittest
from race_ai import result_due_ledger as L
NOW = '2026-11-08T09:00:00+00:00'


def row(rid, status=None):
    return {'race_id': rid, 'result': {'status': status} if status else None}


class ResultDueLedgerTests(unittest.TestCase):
    def fresh(self):
        return L.ledger({}, now=NOW)

    def test_unresolved_survives_day_rollover_and_finished_is_acknowledged(self):
        d = self.fresh()
        rid = '20261104-01-01'
        L.update(d, [row(rid, 'unsupported')], now=NOW)
        self.assertEqual(d['pending'][rid]['last_status'], 'unsupported')
        self.assertEqual(L.choose_older_day(d, all_days=['2026-11-04','2026-11-07','2026-11-08'],
                                             recent_days=['2026-11-08','2026-11-07']), '2026-11-04')
        L.record_scanned(d,'2026-11-04')
        L.update(d, [row(rid, 'pending')], now=NOW)
        self.assertEqual(d['pending'][rid]['last_status'], 'pending')
        L.update(d, [row(rid, 'final')], now=NOW)
        self.assertNotIn(rid,d['pending'])

    def test_old_historical_days_are_scanned_even_when_no_ledger_exists(self):
        d = self.fresh()
        days=['2026-10-30','2026-10-31','2026-11-07','2026-11-08']
        a=L.choose_older_day(d, all_days=days, recent_days=days[-2:]); L.record_scanned(d,a)
        b=L.choose_older_day(d, all_days=days, recent_days=days[-2:]); L.record_scanned(d,b)
        self.assertEqual([a,b],['2026-10-30','2026-10-31'])
        self.assertIsNone(L.choose_older_day(d,all_days=days,recent_days=days[-2:]))

    def test_old_unresolved_and_unscanned_are_not_starved(self):
        d=self.fresh()
        L.update(d,[row('20261001-01-01','pending')],now=NOW)
        dates=['2026-10-01','2026-10-02','2026-10-03','2026-11-07','2026-11-08']
        picks=[]
        for _ in range(6):
            selected=L.choose_older_day(d, all_days=dates, recent_days=dates[-2:])
            picks.append(selected);L.record_scanned(d,selected)
        self.assertIn('2026-10-01',picks)
        self.assertIn('2026-10-02',picks)
        self.assertIn('2026-10-03',picks)

    def test_bad_or_missing_history_blocks_without_discarding_pending(self):
        d=self.fresh()
        L.update(d,[row('20261104-01-01','unsupported')],now=NOW)
        self.assertIsNone(L.choose_older_day(d,all_days=['2026-11-07','2026-11-08'],recent_days=['2026-11-07','2026-11-08']))
        self.assertEqual(L.unavailable_days(d,['2026-11-07','2026-11-08']),1)
        self.assertIn('20261104-01-01',d['pending'])

    def test_reject_forged_final_state_and_invalid_ids(self):
        d=self.fresh()
        with self.assertRaisesRegex(ValueError,'RESULT_DUE_UNKNOWN_RESULT_STATE'):
            L.update(d,[row('20261104-01-01','unverified_success')],now=NOW)
        with self.assertRaisesRegex(ValueError,'RESULT_DUE_RACE_ID_INVALID'):
            L.update(d,[row('20261104-XX-01','pending')],now=NOW)

    def test_duplicate_conflict_fails_closed(self):
        d=self.fresh()
        r=row('20261104-01-01','pending')
        with self.assertRaisesRegex(ValueError,'RESULT_DUE_DUPLICATE_RACE'):
            L.update(d,[r,r],now=NOW)

    def test_display_only_reference_does_not_close_formal_pending_case(self):
        d=self.fresh()
        r=row('20261104-01-01','final')
        r['result']['cutoff_reconciliation']={'formal_eligible':False,'basis':'REFERENCE_ONLY'}
        L.update(d,[r],now=NOW)
        self.assertIn(r['race_id'],d['pending'])
        self.assertEqual(d['pending'][r['race_id']]['last_status'],'unsupported')
        r['result'].pop('cutoff_reconciliation')
        L.update(d,[r],now=NOW)
        self.assertNotIn(r['race_id'],d['pending'])

    def test_upper_bound_is_not_silently_evicted(self):
        d=self.fresh()
        d['scanned_days']=[f'2024-01-{n:02}' for n in range(1,32)]
        d['scanned_days'].append('2024-01-01')
        with self.assertRaisesRegex(ValueError,'RESULT_DUE_SCAN_BOUND'):
            L.ledger({'result_due_ledger':d},now=NOW)

    def test_jst_day_boundary_does_not_invalidate_current_day(self):
        d=L.ledger({},now='2026-11-07T15:04:00+00:00')
        L.update(d,[row('20261108-01-01','pending')],now='2026-11-07T15:04:00+00:00')
        self.assertEqual(L.ledger({'result_due_ledger':d},now='2026-11-07T15:04:00+00:00'),d)

    def test_only_aware_clocks_accepted_and_first_seen_is_immutable(self):
        d=self.fresh()
        with self.assertRaisesRegex(ValueError,'RESULT_DUE_CLOCK_INVALID'):
            L.ledger({},now='2026-11-08T09:00:00')
        L.update(d,[row('20261104-01-01','pending')],now=NOW)
        first=d['pending']['20261104-01-01']['first_seen_at']
        L.update(d,[row('20261104-01-01','unsupported')],now='2026-11-08T10:00:00+00:00')
        self.assertEqual(d['pending']['20261104-01-01']['first_seen_at'],first)


if __name__=='__main__': unittest.main()
