"""Pure tests: no external Git, actual people, secrets or HTTP."""
from datetime import date, datetime, timedelta, timezone
from race_ai import result_due_ledger as L
import unittest

NOW='2026-11-08T09:00:00+00:00'

def row(rid, status=None, **extra):
    return dict(race_id=rid,event_date_jst=L._rid_day(rid),result=dict(status=status,**extra) if status else None)

class AllHistoryLedgerTests(unittest.TestCase):
    def fresh(self):
        return L.ledger({},now=NOW)

    def test_private_aggregate_counts_without_exporting_race_ids(self):
        d=self.fresh()
        ids=['20261104-01-01','20261104-01-02','20261104-01-03']
        result=L.update(d,[row(ids[0],'missing'),row(ids[1],'pending'),row(ids[2],'unsupported')],now=NOW)
        self.assertEqual(result['pending_by_status'],{'missing':1,'pending':1,'unsupported':1})
        self.assertEqual(result['pending'],3)
        self.assertFalse(any(rid in str(result) for rid in ids))
        self.assertTrue(result['all_saved_dates_retained'])

    def test_actual_local_encrypted_git_restart_preserves_2017_backlog(self):
        from pathlib import Path
        import tempfile,subprocess
        from tests.test_racer_intraday_handoff import FixtureGit
        from race_ai.boat_pdca_github_handoff import TRANSFER_REF
        from race_ai.racer_intraday_handoff import load_intraday,save_intraday
        stamp=datetime(2026,11,8,9,tzinfo=timezone.utc)
        key=bytes(range(32))   # Test-only ephemeral key, never a real owner key.
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);repo=root/'repo';repo.mkdir();remote=root/'remote.git'
            for command in (['git','init','--bare',str(remote)],
                    ['git','-C',str(remote),'config','uploadpack.allowFilter','true'],
                    ['git','init',str(repo)],['git','-C',str(repo),'remote','add','origin',remote.as_uri()]):
                subprocess.run(command,check=True,capture_output=True)
            git=FixtureGit(repo,ref=TRANSFER_REF)
            rootsha=git.commit({'state/other/unchanged.enc':b'ORIGINAL'},None);git.push(rootsha,None)
            original=load_intraday(repo,initialize=True,key=key,transport=git,now=stamp)
            ledger=L.ledger(original['state'].control,now=stamp.isoformat())
            L.update(ledger,[row('20170101-01-01','missing')],now=stamp.isoformat())
            one=save_intraday(original,catalogue_sha256='a'*64,now=stamp,key=key)
            rawcipher=git.read(one['source_commit'],one['cipher_path'],32*1024*1024)
            later=load_intraday(repo,key=key,transport=git,now=stamp+timedelta(minutes=5))
            self.assertEqual(L.pending_count(L.ledger(later['state'].control,now=(stamp+timedelta(minutes=5)).isoformat())),1)
            L.update(later['state'].control['result_due_ledger'],
                     [row('20170101-01-01','final')],now=(stamp+timedelta(minutes=5)).isoformat())
            two=save_intraday(later,catalogue_sha256='a'*64,now=stamp+timedelta(minutes=5),key=key)
            reopened=load_intraday(repo,key=key,transport=git,now=stamp+timedelta(minutes=6))
            self.assertEqual(L.pending_count(reopened['state'].control['result_due_ledger']),0)
            self.assertEqual(git.read(two['source_commit'],one['cipher_path'],32*1024*1024),rawcipher)
            self.assertEqual(git.read(two['source_commit'],'state/other/unchanged.enc',64),b'ORIGINAL')

    def test_legacy_cutoff_reference_is_unverified_and_retained_as_due(self):
        doc=self.fresh()
        result=row('20261104-01-01','final')
        result['result']['cutoff_reference']={'formal_eligible':False}
        self.assertEqual(L.reconciled_status(result),'unsupported')
        out=L.update(doc,[result],now=NOW)
        self.assertEqual(out['pending_by_status']['unsupported'],1)
        self.assertEqual(L.pending_count(doc),1)
        result['result'].pop('cutoff_reference')
        L.update(doc,[result],now=NOW)
        self.assertEqual(L.pending_count(doc),0)

    def test_new_old_pending_and_formal_close(self):
        doc=self.fresh();rid='20261104-01-01'
        L.update(doc,[row(rid,'pending')],now=NOW)
        self.assertEqual(L.pending_count(doc),1)
        dates=['2026-11-04','2026-11-07','2026-11-08']
        self.assertEqual(L.choose_older_day(doc,all_days=dates,recent_days=dates[1:]),dates[0])
        L.record_scanned(doc,dates[0]);self.assertTrue(L.is_scanned(doc,dates[0]))
        L.update(doc,[row(rid,'unsupported')],now=NOW)
        self.assertEqual(doc['pending_days'][dates[0]]['u'],'1')
        L.update(doc,[row(rid,'final')],now=NOW)
        self.assertEqual(L.pending_count(doc),0)
        self.assertEqual(doc['pending_days'],{})
        self.assertTrue(L.is_scanned(doc,dates[0]))

    def test_no_two_day_or_ninety_day_or_1200_day_expiry(self):
        doc=self.fresh()
        start=date(2017,1,1)
        history=[(start+timedelta(days=k)).isoformat() for k in range(3610)]
        old=history[0]
        L.update(doc,[row('20170101-24-12','missing')],now=NOW)
        self.assertEqual(L.choose_older_day(doc,all_days=history,recent_days=history[-2:]),old)
        for day in history[:2000]: L.record_scanned(doc,day)
        self.assertEqual(len(doc['scanned_months']),66)
        self.assertEqual(L.pending_count(doc),1)
        self.assertTrue(L.is_scanned(doc,old))
        self.assertFalse(L.is_scanned(doc,history[-1]))
        self.assertEqual(L.ledger({'result_due_ledger':doc},now=NOW),doc)

    def test_every_unscanned_day_eventually_selected_with_pending_and_recent(self):
        doc=self.fresh();days=['2026-10-01','2026-10-02','2026-10-03','2026-11-07','2026-11-08']
        L.update(doc,[row('20261001-01-01','missing')],now=NOW)
        selected=[]
        for k in range(12):
            day=L.choose_older_day(doc,all_days=days,recent_days=days[-2:])
            selected.append(day)
            if day:L.record_scanned(doc,day)
        self.assertTrue(set(days[:3]) <= set(selected))
        self.assertEqual(L.count_older(doc,days[-2:]),1)

    def test_full_race_slot_24_12_without_collisions_and_correct_removal(self):
        doc=self.fresh();d='2026-11-08'
        rows=[row(f'20261108-{venue:02d}-{n:02d}','pending') for venue in range(1,25) for n in range(1,13)]
        L.update(doc,rows,now=NOW)
        self.assertEqual(L.pending_count(doc),288)
        self.assertEqual(L._mask(doc['pending_days'][d]['p']).bit_count(),288)
        L.update(doc,[row('20261108-24-12','void'),row('20261108-01-01','final')],now=NOW)
        self.assertEqual(L.pending_count(doc),286)
        self.assertEqual(L._mask(doc['pending_days'][d]['p']).bit_count(),286)

    def test_reference_formal_eligibility_false_is_not_resolution(self):
        doc=self.fresh();rid='20261104-01-01'
        L.update(doc,[row(rid,'final',formal_eligible=False)],now=NOW)
        self.assertEqual(L.pending_count(doc),1)
        L.update(doc,[row(rid,'final',cutoff_reconciliation={'formal_eligible':False})],now=NOW)
        self.assertEqual(L.pending_count(doc),1)
        L.update(doc,[row(rid,'final')],now=NOW)
        self.assertEqual(L.pending_count(doc),0)

    def test_no_silent_eviction_if_saved_day_is_temporarily_unavailable(self):
        doc=self.fresh();L.update(doc,[row('20170101-04-02','unsupported')],now=NOW)
        self.assertEqual(L.choose_older_day(doc,all_days=['2026-11-07','2026-11-08'],recent_days=['2026-11-07','2026-11-08']),None)
        self.assertEqual(L.unavailable_days(doc,['2026-11-07','2026-11-08']),1)
        self.assertEqual(L.pending_count(doc),1)

    def test_first_seen_is_not_replaced_by_later_runs(self):
        doc=self.fresh();row0=row('20261104-01-01','pending');L.update(doc,[row0],now=NOW)
        first=doc['pending_days']['2026-11-04']['first_seen_at']
        L.update(doc,[row('20261104-01-01','unsupported')],now='2026-11-08T10:00:00Z')
        self.assertEqual(first,doc['pending_days']['2026-11-04']['first_seen_at'])

    def test_cannot_make_future_or_invalid_or_duplicate_or_wrong_day_records(self):
        doc=self.fresh()
        with self.assertRaisesRegex(ValueError,'RESULT_DUE_RACE_ID_INVALID'):
            L.update(doc,[row('20261104-25-01','pending')],now=NOW)
        with self.assertRaisesRegex(ValueError,'RESULT_DUE_UNKNOWN_RESULT_STATE'):
            L.update(doc,[row('20261104-01-01','sent')],now=NOW)
        r=row('20261104-01-01','pending')
        with self.assertRaisesRegex(ValueError,'RESULT_DUE_DUPLICATE_RACE'):
            L.update(doc,[r,r],now=NOW)
        with self.assertRaisesRegex(ValueError,'RESULT_DUE_DAY_IDENTITY_CONFLICT'):
            L.update(doc,[dict(r,event_date_jst='2026-11-03')],now=NOW)
        future=row('2026'+'1109'+'-01-01','pending')
        with self.assertRaisesRegex(ValueError,'RESULT_DUE_FUTURE_RACE_INVALID'):
            L.update(doc,[future],now=NOW)

    def test_invalid_masks_fail_closed_without_dropping_other_days(self):
        doc=self.fresh();L.update(doc,[row('20261104-01-01','pending')],now=NOW)
        doc['pending_days']['2026-11-04']['m']='1'
        with self.assertRaisesRegex(ValueError,'RESULT_DUE_ENTRY_MASK_CONFLICT'):
            L.ledger({'result_due_ledger':doc},now=NOW)

    def test_day_bitset_retains_leap_day(self):
        doc=self.fresh();L.record_scanned(doc,'2024-02-29');self.assertTrue(L.is_scanned(doc,'2024-02-29'))
        self.assertEqual(L.ledger({'result_due_ledger':doc},now=NOW),doc)
        with self.assertRaisesRegex(ValueError,'RESULT_DUE_DAY_INVALID'):
            L.record_scanned(doc,'2025-02-29')

    def test_old_pending_get_one_existing_budget_slot_under_current_load(self):
        fresh=[f'f{k}' for k in range(12)]
        order=L.ordered_result_targets(fresh=fresh,bootstrap=[],new_stats=[],old=['old1','old2'],
                                      other_due=[],revisions=[],max_requests=12,used_requests=0)
        self.assertEqual(order[:12],fresh[:11]+['old1'])
        self.assertEqual(order[12:],['f11','old2'])
        with_start=L.ordered_result_targets(fresh=fresh,bootstrap=[],new_stats=[],old=['old1'],
                                     other_due=[],revisions=[],max_requests=12,used_requests=1)
        self.assertEqual(with_start[:11],fresh[:10]+['old1'])
        no_old=L.ordered_result_targets(fresh=fresh,bootstrap=[],new_stats=[],old=[],
                                     other_due=[],revisions=[],max_requests=12,used_requests=1)
        self.assertEqual(no_old,fresh)
        with self.assertRaisesRegex(ValueError,'RESULT_DUE_SOURCE_BUDGET_INVALID'):
            L.ordered_result_targets(fresh=[],bootstrap=[],new_stats=[],old=[],other_due=[],
                                     revisions=[],max_requests=13,used_requests=0)

    def test_venue_bootstrap_is_not_displaced_by_old_backlog(self):
        q=L.ordered_result_targets(fresh=[],bootstrap=['v1','v2','v3','v4'],new_stats=[],
            old=['old1','old2'],other_due=[],revisions=[],max_requests=4,used_requests=1)
        self.assertEqual(q[:4],['v1','v2','v3','v4'])
        self.assertEqual(q[4:],['old1','old2'])

    def test_single_current_slot_is_not_stolen_by_old_backlog(self):
        q=L.ordered_result_targets(fresh=['current1'],bootstrap=[],new_stats=[],
            old=['old1'],other_due=[],revisions=[],max_requests=1,used_requests=0)
        self.assertEqual(q[:2],['current1','old1'])

    def test_old_due_has_a_slot_after_current_venue_bootstrap(self):
        q=L.ordered_result_targets(fresh=['current1','current2'],bootstrap=['venue1','venue2','venue3'],
           new_stats=['stat'+str(i) for i in range(6)],old=['old1'],
           other_due=[],revisions=[],max_requests=9,used_requests=0)
        self.assertEqual(q[:5],['current1','current2','venue1','venue2','venue3'])
        self.assertEqual(q[8],'old1')
        self.assertEqual(len(q),12)

    def test_resume_does_not_reset_scanned_months(self):
        doc=self.fresh();L.record_scanned(doc,'2024-01-01');L.record_scanned(doc,'2025-01-01')
        again=L.ledger({'result_due_ledger':doc},now=NOW)
        self.assertTrue(L.is_scanned(again,'2024-01-01'))
        self.assertTrue(L.is_scanned(again,'2025-01-01'))
        self.assertEqual(len(again['scanned_months']),2)

if __name__=='__main__':unittest.main()
