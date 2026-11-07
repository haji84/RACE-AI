"""Cache selection precedes the existing live API and expiry filters."""
import os
import unittest
from unittest.mock import patch
from race_ai.cycle_recovery import artifact_pages
from scripts import github_existing_cycle as cycle


class ClosedOriginals:
    def __init__(self):self.calls=[]
    def __call__(self,path):self.calls.append(path);raise AssertionError('live GET forbidden')
    def archived_artifact_pages(self,run):return [{'id':7,'expired':False,'name':'boat-p0-existing-1'}]


class RecoveryIntegrationTests(unittest.TestCase):
    def test_closed_run_inventory_is_selected_before_any_live_listing(self):
        reader=ClosedOriginals()
        rows=artifact_pages(reader,1)
        self.assertEqual([r['id'] for r in rows],[7]);self.assertEqual(reader.calls,[])

    def test_explicit_runtime_reader_routes_originals_without_live_retry(self):
        self.assertTrue(hasattr(cycle,'original_reader'),'explicit archive reader integration required')
        class Reader:
            def __call__(self,path):return b'archived exact response'
            def is_archived(self,ident):return ident==7
            def archived_artifact_pages(self,run):return [{'id':7}]
        reader=Reader()
        with patch.object(cycle,'original_reader',return_value=reader),patch.object(cycle,'_live_gh',side_effect=AssertionError('live GET')):
            self.assertEqual(cycle.gh('actions/artifacts/7'),b'archived exact response')
            self.assertTrue(cycle.gh.is_archived(7))
            self.assertEqual(cycle.gh.archived_artifact_pages(1),[{'id':7}])

    def test_disabled_recovery_preserves_existing_denial_stop(self):
        self.assertTrue(hasattr(cycle,'original_reader'),'explicit archive reader integration required')
        with patch.dict(os.environ,{},clear=True),patch.object(cycle,'_live_gh',side_effect=RuntimeError('GITHUB_API_READ_HTTP_429_HALT')) as live:
            with self.assertRaisesRegex(RuntimeError,'HTTP_429'):cycle.gh('actions/artifacts/7')
            self.assertEqual(live.call_count,1)


if __name__=='__main__':unittest.main()
