"""Only fictional downloads; real source coverage is a separate private probe."""
from pathlib import Path
import tempfile
from unittest.mock import patch
import unittest,os
from scripts.boat_venue_history import inspect_sources,capture_month,collect_all
from tests.test_boat_racer_database import term_archive
from tests.test_boat_history_catalog import menu,index
from tests.test_boat_venue_history import archive

class VenueCLITests(unittest.TestCase):
    def test_full_grid_with_partial_actual_input_and_no_individual_public_output(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'menu.html').write_bytes(menu());(p/'index.html').write_bytes(index());(p/'term.lzh').write_bytes(term_archive());(p/'k261104.lzh').write_bytes(archive())
            report=inspect_sources(p,term_file=p/'term.lzh',menu_file=p/'menu.html',end='2026-11-05')
            self.assertEqual(report['known_racers'],6);self.assertEqual(report['grid_cells'],144)
            self.assertEqual(report['observed_starts'],18);self.assertFalse(report['all_venue_player_history_complete'])
            self.assertNotIn('profiles',report);self.assertEqual(report['published_months_count'],2)
            self.assertEqual(len(report['venue_counts']),24)
    def test_owner_key_absence_blocks_month_and_all_period_fetch(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{},clear=True),patch('scripts.boat_venue_history._http',side_effect=AssertionError('unexpected GET')):
            report=capture_month(Path(folder)/'month',month='200501')
            self.assertEqual(report['status'],'HOLD_OWNER_STATE_KEY_MISSING');self.assertEqual(report['upstream_gets'],0)
            report=collect_all(Path(folder)/'all')
            self.assertEqual(report['status'],'HOLD_OWNER_STATE_KEY_MISSING')

    def test_month_encrypted_capture_partial_resume_and_whole_period_walk(self):
        import base64,hashlib
        from scripts import boat_venue_history as cli
        from datetime import datetime,timezone
        now=datetime.now(timezone.utc).isoformat();key=base64.b64encode(os.urandom(32)).decode()
        def fetch(url):
            if url.endswith('/dmenu.html'):return b'<script>var dir="/od2/K/";</script><option value="202611">x</option>',now
            if url.endswith('/mday.html'):return index(),now
            day='2026-11-04' if url.endswith('k261104.lzh') else '2026-11-05'
            return archive(day=day),now
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'RACE_AI_STATE_KEY':key}),patch.object(cli,'_http',side_effect=fetch):
            p=Path(folder)
            a=capture_month(p/'a',month='202611',max_files=1);self.assertEqual(a['catalog']['parsed_days'],1)
            b=capture_month(p/'b',month='202611',resume=p/'a',max_files=1)
            self.assertEqual(b['catalog']['parsed_days'],2);self.assertEqual(b['scope']['previous_cipher_sha256'],a['ciphertext_sha256'])
            result=collect_all(p/'all',initialize=True,max_months=1)
            self.assertEqual(result['complete_months'],1)
            with patch.object(cli,'_http',side_effect=AssertionError('already collected')):
                self.assertEqual(collect_all(p/'all')['months_processed_this_invocation'],0)
    def test_source_failure_wait_must_survive_initial_capture(self):
        import base64
        from scripts import boat_venue_history as cli
        from race_ai.source_retry_policy import SourceWait,plan_http_wait
        key=base64.b64encode(os.urandom(32)).decode();wait=SourceWait('HTTP_RATE_LIMIT',state='RATE_LIMIT_WAIT')
        wait.plan=plan_http_wait(429,{'Retry-After':'3600'},'2030-01-01T00:00:00Z')
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'RACE_AI_STATE_KEY':key}),patch.object(cli,'_http',side_effect=wait):
            report=capture_month(Path(folder)/'a',month='202611')
            self.assertEqual(report['status'],'HOLD_SOURCE_WAIT');self.assertFalse(report['encrypted_checkpoint_created'])
            with patch.object(cli,'_http',side_effect=AssertionError('Retry-After bypass')):
                report=capture_month(Path(folder)/'b',month='202611',resume=Path(folder)/'a')
                self.assertEqual(report['upstream_gets'],0)

    def test_whole_collection_initial_wait_and_orphan_hold_recover_safely(self):
        import base64,json
        from scripts import boat_venue_history as cli
        from race_ai.source_retry_policy import SourceWait,plan_http_wait
        key=base64.b64encode(os.urandom(32)).decode();wait=SourceWait('HTTP_RATE_LIMIT',state='RATE_LIMIT_WAIT')
        wait.plan=plan_http_wait(429,{'Retry-After':'3600'},'2030-01-01T00:00:00Z')
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'RACE_AI_STATE_KEY':key}):
            p=Path(folder)
            with patch.object(cli,'_http',side_effect=wait):
                report=collect_all(p/'initial',initialize=True)
                self.assertEqual(report['status'],'HOLD_SOURCE_WAIT')
            with patch.object(cli,'_http',side_effect=AssertionError('retry bypass')):
                self.assertEqual(collect_all(p/'initial')['upstream_gets'],0)
            root=p/'orphan';root.mkdir()
            state=dict(schema='RACE_AI_ALL_PUBLISHED_HISTORY_PROGRESS_V1',months=['202611'],menu_sha256='a'*64,captured_at='2026-11-01T00:00:00Z',heads={})
            (root/'collection.json').write_text(json.dumps(dict(state=state,mac=cli._manifest_mac(state))))
            with patch.object(cli,'_http',side_effect=wait):capture_month(root/'202611'/'attempt-000001',month='202611')
            with patch.object(cli,'_http',side_effect=AssertionError('orphan re-fetch')):
                self.assertEqual(collect_all(root)['complete_months'],0)

    def test_bootstrap_and_atomic_pointer_crash_can_resume(self):
        import base64
        from scripts import boat_venue_history as cli
        from datetime import datetime,timezone
        key=base64.b64encode(os.urandom(32)).decode();now=datetime.now(timezone.utc).isoformat()
        def fetch(url):
            if url.endswith('/dmenu.html'):return b'<script>var dir="/od2/K/";</script><option value="202611">x</option>',now
            if url.endswith('/mday.html'):return index(),now
            return archive(day='2026-11-04' if url.endswith('04.lzh') else '2026-11-05'),now
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'RACE_AI_STATE_KEY':key}),patch.object(cli,'_http',side_effect=fetch):
            p=Path(folder)/'state'
            with patch('os.replace',side_effect=OSError('simulated pointer crash')):
                with self.assertRaises(OSError):collect_all(p,initialize=True,max_months=1)
            self.assertEqual(collect_all(p,max_months=1)['complete_months'],1)

    def test_published_current_day_is_not_omitted_as_yesterday(self):
        import base64
        from scripts import boat_venue_history as cli
        from datetime import datetime,timezone
        key=base64.b64encode(os.urandom(32)).decode();now='2026-11-05T09:00:00Z'
        def fetch(url):
            if url.endswith('/dmenu.html'):return b'<script>var dir="/od2/K/";</script><option value="202611">x</option>',now
            if url.endswith('/mday.html'):return index(),now
            return archive(day='2026-11-04' if url.endswith('04.lzh') else '2026-11-05'),now
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'RACE_AI_STATE_KEY':key}),patch.object(cli,'_http',side_effect=fetch),patch.object(cli,'datetime') as clock:
            clock.now.return_value=datetime(2026,11,5,9,tzinfo=timezone.utc)
            report=collect_all(Path(folder)/'state',initialize=True,max_months=1)
            c,_=cli.restore_month(Path(folder)/'state'/'202611'/'attempt-000001',expected_month='202611')
            self.assertEqual(c.summary()['parsed_days'],2)
