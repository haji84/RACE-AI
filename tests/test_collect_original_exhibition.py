"""Bounded TSV collection with actual-clock simulation and no network."""
import copy
from datetime import timedelta
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
from contextlib import redirect_stdout
from io import StringIO

from tests.test_original_prediction_contract import fixture,NOW
from tests.test_boatcast_original import original,companion
from race_ai.tokuyama_day_worker import FetchResponse

ROOT=Path(__file__).resolve().parents[1]
SCOPES=[dict(component='original_numeric',origin='https://race.boatcast.jp',path_template='/txt/{venue}/bc_oriten_{day}_{venue}_{race}.txt'),
        dict(component='standard_numeric',origin='https://race.boatcast.jp',path_template='/hp_txt/{venue}/bc_j_tkz_{day}_{venue}_{race}.txt')]


def load_script(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/(name+'.py'));module=importlib.util.module_from_spec(spec)
    with patch.object(sys,'path',[str(ROOT/'scripts')]+sys.path):spec.loader.exec_module(module)
    return module


def inputs():
    _,_,_,race=fixture()
    feed=dict(date_jst='2026-10-15',schedule_verified=True,redistribution_authorized=True,
        venues=[dict(venue='18',status='READY',races=[race])]+[dict(venue=f'{n:02}',status='NO_EVENT',races=[]) for n in range(1,25) if n!=18])
    review=dict(review_type='owner_attestation',evidence_reference='user-confirmation-2026-10-15-exhibition-private-analysis',
        reviewed_at=(NOW-timedelta(hours=1)).isoformat(),reviewed_by='test-owner',owner_statement='test confirmation',
        original_numeric_ingest=True,original_numeric_store=True,original_numeric_protected_preview=True,
        venue_codes=[f'{n:02}' for n in range(1,25)],source_scopes=copy.deepcopy(SCOPES))
    return feed,review,race


class OriginalCollectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:cls.c=load_script('collect_original_exhibition')
        except FileNotFoundError:cls.c=None

    def setUp(self):self.assertIsNotNone(self.c,'bounded original collector required')

    def run_collect(self,folder,feed=None,review=None,transport=None,clock=None):
        default,policy,race=inputs();feed=feed or default;review=review or policy
        day_path=Path(folder)/'day.json';review_path=Path(folder)/'review.json'
        day_path.write_text(json.dumps(feed),encoding='utf-8');review_path.write_text(json.dumps(review),encoding='utf-8')
        with redirect_stdout(StringIO()):
            return self.c.run(day_path,race['race_id'],review_path,Path(folder)/'output',execute=True,transport=transport,clock=clock or (lambda:NOW))

    def transport(self,calls,missing=False):
        def get(url,**kwargs):
            calls.append((url,kwargs));raw=original() if '/txt/' in url else companion().replace(b'6.81',b'6.92')
            if missing and '/txt/' in url:raw=raw.replace(b'36.42',b'-',1)
            return FetchResponse(raw,url,200,'text/plain')
        return get

    def test_exact_two_gets_no_originals_and_runner_clock_after_exclusive_readback(self):
        calls=[]
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'output'
            def clock():return NOW+timedelta(seconds=1) if (output/'observation.json').exists() else NOW
            result=self.run_collect(folder,transport=self.transport(calls),clock=clock)
            packet=json.loads((output/'input.json').read_text(encoding='utf-8'))
            self.assertEqual(packet['runner_saved_at'],'2026-10-14T22:34:01.000000+00:00')
            self.assertEqual(packet['observation'],json.loads((output/'observation.json').read_text(encoding='utf-8')))
            self.assertEqual(result['official_source_requests'],2)
            self.assertEqual({path.name for path in output.iterdir()},{'input.json','observation.json','manifest.json'})
        self.assertEqual([url for url,_ in calls],['https://race.boatcast.jp/txt/18/bc_oriten_20261015_18_01.txt',
            'https://race.boatcast.jp/hp_txt/18/bc_j_tkz_20261015_18_01.txt'])
        self.assertTrue(all(options==dict(timeout=15,max_bytes=1048576) for _,options in calls))

    def test_stale_nearly_closed_invalid_review_and_missing_scope_never_fetch(self):
        for kind in ['day','margin','review','scope']:
            feed,review,race=inputs();transport=Mock()
            if kind=='day':feed['date_jst']='2026-10-14'
            if kind=='margin':race['closed_at']=(NOW+timedelta(seconds=120)).isoformat()
            if kind=='review':review['original_numeric_ingest']=False
            if kind=='scope':review['source_scopes'].pop()
            with tempfile.TemporaryDirectory() as folder,self.subTest(kind=kind),self.assertRaises(ValueError):
                self.run_collect(folder,feed=feed,review=review,transport=transport)
            transport.assert_not_called()

    def test_source_margin_rechecked_at_actual_clock_before_first_get(self):
        feed,review,race=inputs();race['closed_at']=(NOW+timedelta(seconds=121)).isoformat();transport=Mock()
        ticks=iter([NOW,NOW,NOW+timedelta(seconds=1)])
        with tempfile.TemporaryDirectory() as folder,self.assertRaises(ValueError):
            self.run_collect(folder,feed=feed,review=review,transport=transport,clock=lambda:next(ticks))
        transport.assert_not_called()

    def test_partial24_metrics_are_retained_as_partial_not_imputed(self):
        with tempfile.TemporaryDirectory() as folder:
            result=self.run_collect(folder,transport=self.transport([],True))
            packet=json.loads((Path(folder)/'output/input.json').read_text(encoding='utf-8'))
            self.assertEqual(packet['observation']['status'],'PARTIAL')
            self.assertIsNone(packet['observation']['boats'][0]['original_times']['lap_s'])
            self.assertEqual(result['status'],'PARTIAL')

    def test_redirect_html_oversize_wrong_names_and_invalid_numbers_fail_closed(self):
        for kind in ['redirect','html','oversize','name','number']:
            calls=[]
            def transport(url,**kwargs):
                calls.append(url);raw=original() if '/txt/' in url else companion()
                if kind=='name':raw=raw.replace('選手1'.encode(),'別人'.encode())
                if kind=='number':raw=raw.replace(b'36.42',b'NaN')
                if kind=='oversize':raw=b'x'*1048577
                return FetchResponse(raw,url+'?bad' if kind=='redirect' else url,200,'text/html' if kind=='html' else 'text/plain')
            with tempfile.TemporaryDirectory() as folder,self.subTest(kind=kind),self.assertRaises(ValueError):
                self.run_collect(folder,transport=transport)
            self.assertLessEqual(len(calls),2)

    def test_dryrun_has_no_read_network_or_file_side_effects(self):
        transport=Mock();out=StringIO()
        with tempfile.TemporaryDirectory() as folder,redirect_stdout(out):
            result=self.c.run(Path('absent'),'20261015-18-01',Path('absent'),Path(folder)/'out',transport=transport)
            self.assertFalse((Path(folder)/'out').exists())
        transport.assert_not_called();self.assertEqual(result['official_source_requests'],0)

    def test_existing_output_or_duplicate_program_identity_rejected_before_fetch(self):
        feed,review,race=inputs();feed['venues'][0]['races'].append(copy.deepcopy(race));transport=Mock()
        with tempfile.TemporaryDirectory() as folder,self.assertRaises(ValueError):self.run_collect(folder,feed=feed,transport=transport)
        transport.assert_not_called()
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'output').mkdir()
            with self.assertRaises(ValueError):self.run_collect(folder,transport=transport)
        transport.assert_not_called()


if __name__=='__main__':unittest.main()
