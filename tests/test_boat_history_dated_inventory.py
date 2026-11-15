"""Synthetic published listings and actual checkpoint codec; no provider calls."""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import boat_venue_history as cli
from tests.test_boat_history_catalog import index
from tests.test_boat_venue_history import archive
from tests.test_boat_pdca_recipient import OWNER

OLD_AT='2026-11-06T10:00:00Z'
NEW_AT='2026-11-07T10:00:00Z'

def menu(months=('202611',)):
    return ('<script>var dir="/od2/K/";</script><select>'+''.join(f'<option value="{m}">x</option>' for m in months)+'</select>').encode()

class DatedInventoryTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.find_spec('race_ai.boat_history_dated_inventory')
        self.assertIsNotNone(spec,'explicit authenticated dated inventory extension is missing')
        from race_ai import boat_history_dated_inventory as api
        self.api=api
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        env=patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(OWNER).decode());env.start();self.addCleanup(env.stop)

    def parent(self,*,raw=None):
        out=self.root/'parent';out.mkdir(mode=0o700)
        with patch.object(cli,'_now',return_value=OLD_AT),patch.object(cli,'_http',side_effect=[(menu(),OLD_AT),(index(days=('06',)),OLD_AT),(archive(day='2026-11-06') if raw is None else raw,OLD_AT)]):
            report=cli.capture_month(out/'202611/attempt-000001',month='202611',not_after='2026-11-06')
        state=dict(schema='RACE_AI_ALL_PUBLISHED_HISTORY_PROGRESS_V1',months=['202611'],menu_sha256=hashlib.sha256(menu()).hexdigest(),captured_at=OLD_AT,not_after='2026-11-06',heads={'202611':dict(kind='ENCRYPTED',folder='202611/attempt-000001',ciphertext_sha256=report['ciphertext_sha256'],attempt=1,generation=1,month_complete=report['catalog']['month_complete'])})
        cli._store_progress(out,state)
        return out

    def extend(self,parent,*,listing=None,max_files=31,day_raw=None):
        calls=[]
        def fetch(url):
            calls.append(url)
            if url==cli.MENU:return menu(),NEW_AT
            if url.endswith('/mday.html'):return index(days=('06','07')) if listing is None else listing,NEW_AT
            if url.endswith('/k261107.lzh'):return archive(day='2026-11-07') if day_raw is None else day_raw,NEW_AT
            raise AssertionError('known original must never be downloaded: '+url)
        with patch.object(cli,'_now',return_value=NEW_AT),patch.object(cli,'_http',side_effect=fetch):
            result=self.api.extend_collection(parent,self.root/'delta',not_after='2026-11-07',max_files=max_files)
        return result,calls

    def test_only_new_day_is_downloaded_and_old_plain_and_cipher_facts_are_unchanged(self):
        parent=self.parent();before={p.relative_to(parent).as_posix():p.read_bytes() for p in parent.rglob('*') if p.is_file()}
        old,_=cli.restore_month(parent/'202611/attempt-000001',expected_month='202611')
        oldmeta=old.db.execute('SELECT * FROM meta').fetchall();oldobs=old.db.execute('SELECT * FROM observations').fetchall();oldraw=old.db.execute('SELECT * FROM archives').fetchall();old.db.close()
        result,calls=self.extend(parent)
        self.assertEqual(calls,[cli.MENU,'https://www1.mbrace.or.jp/od2/K/202611/mday.html','https://www1.mbrace.or.jp/od2/K/202611/k261107.lzh'])
        self.assertEqual(result['newly_listed_days'],1);self.assertEqual(result['upstream_gets'],3)
        self.assertEqual(before,{p.relative_to(parent).as_posix():p.read_bytes() for p in parent.rglob('*') if p.is_file()})
        record=json.loads((self.root/'delta/collection.json').read_text());s=record['state']
        self.assertEqual(s['captured_at'],OLD_AT);self.assertEqual(s['not_after'],'2026-11-07')
        catalog,_=cli.restore_month(self.root/'delta'/s['heads']['202611']['folder'],expected_month='202611')
        self.assertEqual(catalog.db.execute('SELECT * FROM meta').fetchall(),oldmeta)
        self.assertEqual(catalog.db.execute('SELECT * FROM observations ORDER BY id LIMIT 1').fetchall(),oldobs)
        self.assertEqual(catalog.db.execute('SELECT * FROM archives WHERE sha=?',(oldraw[0][0],)).fetchall(),oldraw)
        self.assertEqual(catalog.summary()['parsed_days'],2);catalog.db.close()
        proof=self.api.validate_inventory(self.root/'delta',s,manifest_raw=(self.root/'delta/collection.json').read_bytes())
        self.assertEqual(proof['inventory_captured_at'],NEW_AT)
        self.assertEqual(proof['parent_manifest_sha256'],hashlib.sha256(before['collection.json']).hexdigest())
        with patch.object(cli,'_http',side_effect=AssertionError('repeat requires zero GET')):
            again=self.api.collect_delta(self.root/'delta')
        self.assertEqual(again['upstream_gets'],0)

    def test_old_waiting_publication_is_preserved_without_refetch_or_empty_success(self):
        from tests.test_boat_entry_observations import uncompressed_lzh
        raw=uncompressed_lzh('STARTK\n01KBGN\nボートレース桐生\nデータは、この場の全レース終了後に登録されます。\n01KEND\nFINALK'.encode('cp932'),'K261106.TXT')
        parent=self.parent(raw=raw);result,calls=self.extend(parent)
        s=json.loads((self.root/'delta/collection.json').read_text())['state'];c,_=cli.restore_month(self.root/'delta'/s['heads']['202611']['folder'],expected_month='202611')
        self.assertEqual(c.summary()['waiting_publication_days'],1);self.assertFalse(c.summary()['month_complete'])
        self.assertEqual(c.pending(),['2026-11-06']);self.assertEqual(result['newly_listed_days'],1)
        self.assertFalse(any(u.endswith('k261106.lzh') for u in calls));c.db.close()

    def test_listing_removal_is_rejected_before_any_archive_request(self):
        parent=self.parent()
        with self.assertRaisesRegex(ValueError,'INVENTORY.*REGRESSION'):
            self.extend(parent,listing=index(days=('07',)))

    def test_no_owner_key_means_no_source_requests(self):
        with patch.dict(os.environ,{},clear=True),patch.object(cli,'_http',side_effect=AssertionError('no source without owner key')):
            result=self.api.extend_collection(self.root/'absent',self.root/'delta',not_after='2026-11-07')
        self.assertEqual(result['upstream_gets'],0);self.assertEqual(result['status'],'HOLD_OWNER_STATE_KEY_MISSING')

    def test_active_parent_retry_after_prevents_menu_and_archive_requests(self):
        from race_ai.source_retry_policy import plan_http_wait
        parent=self.parent();record=json.loads((parent/'collection.json').read_text());head=record['state']['heads']['202611']
        c,old=cli.restore_month(parent/head['folder'],expected_month='202611')
        c.set_wait(plan_http_wait(429,{'Retry-After':'3600'},NEW_AT))
        r=cli.seal_catalog(parent/'202611/attempt-000002',c,cli._scope(2,old['ciphertext_sha256']));c.db.close()
        record['state']['heads']['202611']=dict(head,folder='202611/attempt-000002',ciphertext_sha256=r['ciphertext_sha256'],generation=2,attempt=2)
        cli._store_progress(parent,record['state'])
        with patch.object(cli,'_now',return_value=NEW_AT),patch.object(cli,'_http',side_effect=AssertionError('active wait must make zero GET')):
            result=self.api.extend_collection(parent,self.root/'delta',not_after='2026-11-07')
        self.assertEqual(result['status'],'HOLD_SOURCE_WAIT');self.assertEqual(result['upstream_gets'],0)

    def test_inventory_wait_is_durable_and_same_output_resume_does_not_retry_early(self):
        from race_ai.source_retry_policy import SourceWait,plan_http_wait
        parent=self.parent();plan=plan_http_wait(429,{'Retry-After':'3600'},NEW_AT)
        exc=SourceWait(plan['reason'],plan['retry_at'],state=plan['state']);exc.plan=plan;exc.upstream_attempted=True
        with patch.object(cli,'_now',return_value=NEW_AT),patch.object(cli,'_http',side_effect=exc) as fetch:
            first=self.api.extend_collection(parent,self.root/'delta',not_after='2026-11-07')
        self.assertEqual(fetch.call_count,1);self.assertEqual(first['upstream_gets'],1)
        with patch.object(cli,'_now',return_value=NEW_AT),patch.object(cli,'_http',side_effect=AssertionError('durable429')):
            second=self.api.extend_collection(parent,self.root/'delta',not_after='2026-11-07')
        self.assertEqual(second['status'],'HOLD_SOURCE_WAIT');self.assertEqual(second['upstream_gets'],0)

    def test_interrupted_after_inventory_resumes_only_new_archive_without_reobserving_menu(self):
        parent=self.parent()
        with patch.object(self.api,'collect_delta',side_effect=RuntimeError('synthetic interruption')):
            with self.assertRaisesRegex(RuntimeError,'synthetic interruption'):self.extend(parent)
        calls=[]
        def fetch(url):
            calls.append(url)
            self.assertTrue(url.endswith('k261107.lzh'))
            return archive(day='2026-11-07'),NEW_AT
        with patch.object(cli,'_now',return_value=NEW_AT),patch.object(cli,'_http',side_effect=fetch):
            r=self.api.extend_collection(parent,self.root/'delta',not_after='2026-11-07')
        self.assertEqual(r['upstream_gets'],1);self.assertEqual(len(calls),1)

    def test_new_daily_capture_before_listing_or_after_now_is_rejected(self):
        for bad in ('2026-11-07T09:59:59Z','2026-11-07T10:00:01Z'):
            with self.subTest(clock=bad):
                # A separate source/output is used for each deliberately bad source clock.
                case=self.root/bad[-3:-1];case.mkdir();previous=self.root;self.root=case
                parent=self.parent()
                def fetch(url):
                    if url==cli.MENU:return menu(),NEW_AT
                    if url.endswith('mday.html'):return index(days=('06','07')),NEW_AT
                    return archive(day='2026-11-07'),bad
                with patch.object(cli,'_now',return_value=NEW_AT),patch.object(cli,'_http',side_effect=fetch):
                    with self.assertRaisesRegex(ValueError,'INVENTORY.*CLOCK|DELTA.*CLOCK|REPARSE_CLOCK'):
                        self.api.extend_collection(parent,case/'delta',not_after='2026-11-07')
                self.root=previous

    def test_complete_orphan_checkpoint_is_reused_after_pointer_write_interruption(self):
        parent=self.parent();real=cli._store_progress;calls=[]
        def interrupted(root,state):
            calls.append(1)
            if len(calls)==2:raise OSError('synthetic pointer write interruption')
            return real(root,state)
        with patch.object(cli,'_store_progress',side_effect=interrupted):
            with self.assertRaisesRegex(OSError,'synthetic pointer'):self.extend(parent)
        with patch.object(cli,'_now',return_value=NEW_AT),patch.object(cli,'_http',side_effect=AssertionError('authenticated orphan must be reused')):
            r=self.api.collect_delta(self.root/'delta')
        self.assertEqual(r['upstream_gets'],0)

    def test_signed_progress_survives_interruption_before_atomic_pointer_replace(self):
        parent=self.parent();real=cli.os.replace;calls=[]
        def interrupted(source,target):
            calls.append(1)
            if len(calls)==2:raise OSError('synthetic atomic pointer interruption')
            return real(source,target)
        with patch.object(cli.os,'replace',side_effect=interrupted):
            with self.assertRaisesRegex(OSError,'synthetic atomic'):self.extend(parent)
        with patch.object(cli,'_now',return_value=NEW_AT),patch.object(cli,'_http',side_effect=AssertionError('latest signed progress already has raw')):
            result=self.api.collect_delta(self.root/'delta')
        self.assertEqual(result['upstream_gets'],0)
        state=json.loads((self.root/'delta/collection.json').read_text())['state']
        self.assertEqual(state['heads']['202611']['generation'],3)

    def test_month_rollover_reuses_november_and_fetches_only_observed_december_day(self):
        parent=self.parent();calls=[];at='2026-12-01T10:00:00Z'
        def fetch(url):
            calls.append(url)
            if url==cli.MENU:return menu(('202611','202612')),at
            if url.endswith('202611/mday.html'):return index(days=('06',)),at
            if url.endswith('202612/mday.html'):return index(month='202612',days=('01',)),at
            if url.endswith('k261201.lzh'):return archive(day='2026-12-01'),at
            raise AssertionError('no known day GET')
        with patch.object(cli,'_now',return_value=at),patch.object(cli,'_http',side_effect=fetch):
            r=self.api.extend_collection(parent,self.root/'delta',not_after='2026-12-01')
        self.assertEqual(r['upstream_gets'],4);self.assertEqual(r['newly_listed_days'],1)
        s=json.loads((self.root/'delta/collection.json').read_text())['state']
        self.assertEqual(s['months'],['202611','202612']);self.assertFalse(any(u.endswith('k261106.lzh') for u in calls))
        with patch.object(cli,'_now',return_value=at):self.api.validate_inventory(self.root/'delta',s)

    def test_next_dated_generation_keeps_both_parent_proofs_and_reuses_old_sources(self):
        parent=self.parent();self.extend(parent);first=(self.root/'delta/collection.json').read_bytes();calls=[];at='2026-11-08T10:00:00Z'
        def fetch(url):
            calls.append(url)
            if url==cli.MENU:return menu(),at
            if url.endswith('mday.html'):return index(days=('06','07','08')),at
            if url.endswith('k261108.lzh'):return archive(day='2026-11-08'),at
            raise AssertionError('old source must remain byte reusable')
        with patch.object(cli,'_now',return_value=at),patch.object(cli,'_http',side_effect=fetch):
            r=self.api.extend_collection(self.root/'delta',self.root/'second',not_after='2026-11-08')
            state=json.loads((self.root/'second/collection.json').read_text())['state']
            verified=self.api.validate_inventory(self.root/'second',state)
        self.assertEqual(r['upstream_gets'],3);self.assertEqual(len(state['inventory_lineage']),2)
        self.assertEqual(verified['parent_manifest_sha256'],hashlib.sha256(first).hexdigest())
        self.assertEqual((self.root/'delta/collection.json').read_bytes(),first)

    def test_invalid_new_archive_is_explicit_quarantine_and_never_empty_history(self):
        parent=self.parent();r,_=self.extend(parent,day_raw=b'authored invalid LZH')
        state=json.loads((self.root/'delta/collection.json').read_text())['state'];c,_=cli.restore_month(self.root/'delta'/state['heads']['202611']['folder'],expected_month='202611')
        self.assertEqual(c.summary()['quarantined_days'],1);self.assertEqual(c.summary()['parsed_days'],1)
        self.assertFalse(r['all_available_period_complete']);self.assertFalse(c.summary()['month_complete']);c.db.close()

    def test_future_listed_day_is_not_acquired_and_future_requested_scope_is_rejected(self):
        parent=self.parent();r,calls=self.extend(parent,listing=index(days=('06','07','08')))
        self.assertEqual(r['newly_listed_days'],1);self.assertFalse(any(u.endswith('k261108.lzh') for u in calls))
        with patch.object(cli,'_now',return_value=NEW_AT),patch.object(cli,'_http',side_effect=AssertionError('future scope source0')):
            with self.assertRaisesRegex(ValueError,'SCOPE_REGRESSION'):
                self.api.extend_collection(parent,self.root/'future',not_after='2026-11-08')

    def test_cli_exposes_only_safe_counts_and_preserves_v1_collect_guard(self):
        from contextlib import redirect_stdout
        import io
        parent=self.parent();calls=[]
        def fetch(url):
            calls.append(url)
            if url==cli.MENU:return menu(),NEW_AT
            if url.endswith('mday.html'):return index(days=('06','07')),NEW_AT
            return archive(day='2026-11-07'),NEW_AT
        output=io.StringIO()
        with patch.object(cli,'_now',return_value=NEW_AT),patch.object(cli,'_http',side_effect=fetch),redirect_stdout(output):
            r=cli.main(['extend-all','--source-dir',str(parent),'--out-dir',str(self.root/'delta'),'--not-after','2026-11-07'])
        self.assertEqual(json.loads(output.getvalue()),r);self.assertNotIn('raw_base64',output.getvalue())
        with patch.object(cli,'_http',side_effect=AssertionError('explicit delta command required')):
            with self.assertRaisesRegex(ValueError,'EXPLICIT_COLLECT_DELTA'):
                cli.collect_all(self.root/'delta')

    def test_resigned_child_cannot_retime_any_old_observation(self):
        parent=self.parent();self.extend(parent);root=self.root/'delta';record=json.loads((root/'collection.json').read_text());state=record['state'];head=state['heads']['202611']
        c,old=cli.restore_month(root/head['folder'],expected_month='202611')
        with c.db:c.db.execute("UPDATE observations SET captured_at='2026-11-06T10:00:01Z' WHERE day='2026-11-06'")
        r=cli.seal_catalog(root/'202611/attempt-000004',c,cli._scope(4,old['ciphertext_sha256']));c.db.close()
        state['heads']['202611']=dict(head,folder='202611/attempt-000004',generation=4,attempt=4,ciphertext_sha256=r['ciphertext_sha256'])
        cli._store_progress(root,state)
        with patch.object(cli,'_now',return_value=NEW_AT),patch.object(cli,'_http',side_effect=AssertionError('bad provenance source0')):
            with self.assertRaisesRegex(ValueError,'OLD_OBSERVATION_CHANGED'):
                self.api.collect_delta(root)

    def test_unlisted_new_day_remains_unknown_and_is_never_guessed(self):
        parent=self.parent();r,calls=self.extend(parent,listing=index(days=('06',)))
        self.assertEqual(r['upstream_gets'],2);self.assertEqual(r['newly_listed_days'],0)
        self.assertFalse(r['all_available_period_complete']);self.assertTrue(r['source_gaps_require_separate_review'])
        self.assertFalse(any(u.endswith('.lzh') for u in calls))

    def test_future_signed_parent_clock_is_rejected_before_any_inventory_request(self):
        parent=self.parent();state=json.loads((parent/'collection.json').read_text())['state']
        state['captured_at']='2026-11-08T10:00:00Z';cli._store_progress(parent,state)
        with patch.object(cli,'_now',return_value=NEW_AT),patch.object(cli,'_http',side_effect=AssertionError('invalid parent clock source0')):
            with self.assertRaisesRegex(ValueError,'INVENTORY.*CLOCK'):
                self.api.extend_collection(parent,self.root/'delta',not_after='2026-11-07')

    def validation_report(self):
        return dict(checked_at=OLD_AT,disputed_payout_races=0,numeric_finish_rows=18,
            parsed_source_days=1,parser_revision=13,past_day_states={'PARSED':1},
            requested_end='2026-11-05',requested_start='2026-11-01',source_set_sha256='c'*64,
            st_centisecond_sum=100,st_centisecond_sum2=1000,st_ok_rows=18,typed_row_count=18,
            unknown_actual_course_rows=0,unreported_venue_days=0)

    def test_existing_full_archive_validation_remains_ancestral_and_interrupted_v2_resumes(self):
        parent=self.parent();state=json.loads((parent/'collection.json').read_text())['state']
        original=self.validation_report();state['full_archive_validation']=original;cli._store_progress(parent,state)
        with patch.object(self.api,'collect_delta',side_effect=RuntimeError('inventory complete, no new day yet')):
            with self.assertRaisesRegex(RuntimeError,'inventory complete'):self.extend(parent)
        out=self.root/'delta';record=json.loads((out/'collection.json').read_text());self.assertEqual(record['state']['full_archive_validation'],original)
        calls=[]
        def fetch(url):
            calls.append(url);self.assertTrue(url.endswith('k261107.lzh'))
            return archive(day='2026-11-07'),NEW_AT
        with patch.object(cli,'_now',return_value=NEW_AT),patch.object(cli,'_http',side_effect=fetch):
            r=self.api.collect_delta(out)
        self.assertEqual(r['upstream_gets'],1);self.assertEqual(len(calls),1)
        current=json.loads((out/'collection.json').read_text())['state']
        self.assertEqual(current['full_archive_validation'],original)
        self.assertEqual(current['full_archive_validation']['requested_end'],'2026-11-05')
        for field,value in [('requested_end','2026-11-07'),('checked_at',NEW_AT),('typed_row_count',24),(None,None)]:
            changed=json.loads(json.dumps(current))
            if field is None:changed.pop('full_archive_validation')
            else:changed['full_archive_validation'][field]=value
            cli._store_progress(out,changed)
            with patch.object(cli,'_now',return_value=NEW_AT),patch.object(cli,'_http',side_effect=AssertionError('changed ancestral report source0')):
                with self.assertRaisesRegex(ValueError,'ANCESTRAL_METADATA'):
                    self.api.collect_delta(out)

    def test_unknown_parent_extra_remains_hold_before_source_request(self):
        parent=self.parent();state=json.loads((parent/'collection.json').read_text())['state']
        state['unknown_validation_extension']={'arbitrary':True};cli._store_progress(parent,state)
        with patch.object(cli,'_now',return_value=NEW_AT),patch.object(cli,'_http',side_effect=AssertionError('unknown parent metadata source0')):
            with self.assertRaisesRegex(ValueError,'ANCESTRAL|FIELDS_INVALID'):
                self.api.extend_collection(parent,self.root/'delta',not_after='2026-11-07')

    def test_uncommitted_encrypted_inventory_holds_before_reobserving_sources(self):
        parent=self.parent()
        with patch.object(cli,'seal_catalog',side_effect=OSError('interrupted after inventory seal')):
            with self.assertRaisesRegex(OSError,'after inventory seal'):self.extend(parent)
        out=self.root/'delta';self.assertTrue(list((out/'dated-inventory').glob('*/inventory.checkpoint')))
        calls=[]
        def fetch(url):
            calls.append(url)
            return (menu() if url==cli.MENU else index(days=('06','07'))),NEW_AT
        error=None
        with patch.object(cli,'_now',return_value=NEW_AT),patch.object(cli,'_http',side_effect=fetch):
            try:self.api.extend_collection(parent,out,not_after='2026-11-07')
            except ValueError as exc:error=str(exc)
        self.assertEqual(calls,[],'retained or uncertain inventory acquisition must not be repeated')
        self.assertIn('UNCOMMITTED_INVENTORY_HOLD',error or '')
