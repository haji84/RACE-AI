"""Authored complete wire with the real browser's nested DOM filename."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import unittest
from race_ai.actions_contract import digest
from race_ai import all_existing_model_official_continuation as continuation
from scripts import all_existing_model_official_result_collect as collector
from tests import test_official_result_browser_refund_404 as sources


def fixture():
    f=sources.BrowserRefund404Tests();f.setUp()
    try:
        nested=f.root/'case-01/rendered-dom.html';nested.parent.mkdir(mode=0o700)
        old=f.root/'dom.html';nested.write_bytes(old.read_bytes());nested.chmod(0o600);old.unlink()
        f.index['cases'][0]['rendered_dom']['file']='case-01/rendered-dom.html'
        collector._write(f.root/'capture-index.json',json.dumps(f.index,indent=2).encode())
        captures,_,originals=f.run_sources()
        journal=dict(browser_attempt=dict(started_at=sources.START.isoformat(),completed_at=f.finish.isoformat()),
            browser_index=collector._index_diagnostic(f.index,f.planned),captures=[c[2] for c in captures],browser_captures=originals,
            browser_quarantine=collector._browser_quarantine(f.index,f.root,maximum_json=12*1024*1024))
        return journal,f.planned[0]
    finally:f.doCleanups()


class NestedOriginalPathTests(unittest.TestCase):
    def test_nested_original_dom_replays_exactly_without_renaming_or_changing_any_proof(self):
        journal,case=fixture();before=deepcopy(journal)
        continuation._replay_probe_wire(journal,case)
        self.assertEqual(journal,before)
        self.assertIn('case-01/rendered-dom.html',[f['file'] for f in journal['browser_quarantine']['files']])
    def test_absolute_parent_and_noncanonical_relative_names_are_rejected(self):
        for name in ('../rendered-dom.html','/tmp/rendered-dom.html','case-01/../rendered-dom.html','case-01//rendered-dom.html','./rendered-dom.html'):
            journal,case=fixture();q=journal['browser_quarantine'];file=next(f for f in q['files'] if f['kind']=='RENDERED_DOM')
            old=file['file'];file['file']=name
            next(f for f in q['inventory'] if f['file']==old)['file']=name;q['inventory_sha256']=digest(q['inventory'])
            with self.subTest(name=name),self.assertRaises(ValueError):continuation._replay_probe_wire(journal,case)
    def test_nested_original_cannot_be_replaced_by_a_symlink_before_validation(self):
        from scripts import boat_all_racers
        journal,case=fixture();write=boat_all_racers._write
        with tempfile.TemporaryDirectory() as folder:
            outside=Path(folder)/'outside.body';outside.write_bytes(b'invented outside original');outside.chmod(0o600)
            def swapped(path,raw):
                if path.name=='rendered-dom.html':path.symlink_to(outside)
                else:write(path,raw)
            with patch.object(boat_all_racers,'_write',side_effect=swapped),self.assertRaises(ValueError):
                continuation._replay_probe_wire(journal,case)
