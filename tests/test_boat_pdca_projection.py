"""Saved-pair projection never predicts or changes the retained journal."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from race_ai.boat_pdca_state import PdcaState
from race_ai.boat_history_store import wire
from race_ai.actions_contract import digest
from tests.test_boat_pdca_github_handoff import invented_research_state
from tests.test_boat_pdca_state import result


class PdcaProjectionTests(unittest.TestCase):
    def setUp(self):
        from race_ai.boat_pdca_projection import project_pdca
        self.project=project_pdca;self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);path,self.pair=invented_research_state(self.root)
        self.state=PdcaState(path);self.addCleanup(self.state.close)

    def test_exact_four_original_variants_and_physical_receipts_are_preserved(self):
        before=self.state.inventory();view=self.project(self.state)
        self.assertEqual(self.state.inventory(),before)
        self.assertEqual(view['schema'],'RACE_AI_PRIVATE_CYCLE_VIEW_V1')
        self.assertEqual(view['dataset_status'],'REAL_REPORTED')
        row=view['records'][0];predictions=[row['prediction'],*row['comparison_predictions']]
        self.assertEqual(row['offering_status'],'UNKNOWN')
        self.assertEqual(len(predictions),4)
        self.assertEqual({p['variant'] for p in predictions},{'HISTORY_BASELINE','HISTORY_ADDED'})
        for p in predictions:
            variant='baseline' if p['variant']=='HISTORY_BASELINE' else 'history'
            original=self.pair[variant]['suite']['models'][p['model_id']]
            self.assertEqual(p['ordered_top8'],original['ordered_top8'])
            self.assertEqual(p['prediction_sha256'],original['prediction_sha256'])
            self.assertEqual(p['as_of'],original['as_of'])
            self.assertEqual(p['odds_independent'],original.get('odds_independent'))
            self.assertFalse(p['external_receipt_verified'])
        self.assertEqual(row['result']['status'],'final')
        self.assertEqual(len(row['result_observations']),1)
        self.assertEqual(row['result_revisions'],[])

    def test_opening_saved_originals_never_executes_the_model_again(self):
        with patch('race_ai.boat_history_comparison.prepare_pair',side_effect=AssertionError('view regenerated prediction')),\
             patch('race_ai.boat_history_comparison.run',side_effect=AssertionError('view executed model')):
            view=self.project(self.state)
        original=self.pair['baseline']['suite']['models']
        self.assertEqual(view['records'][0]['prediction']['prediction_sha256'],original[view['records'][0]['prediction']['model_id']]['prediction_sha256'])

    def test_existing_browser_parser_keeps_both_variants_and_research_scope(self):
        view=self.project(self.state)
        script="""
const fs=require('node:fs'),assert=require('node:assert/strict');
const Data=require('./web/product-data.js');
const view=Data.parse(fs.readFileSync(0,'utf8'));
assert.equal(view.records.length,1);
assert.equal(view.records[0].scope,'research');
assert.equal(Data.candidates(view.records[0]).length,4);
assert.equal(Data.modelGroups(view.records).length,4);
console.log('FOUR_SAVED_VARIANTS_VALID');
"""
        proc=subprocess.run(['node','-e',script],input=wire(view),text=True,capture_output=True,
                            cwd=Path(__file__).resolve().parents[1],timeout=20)
        self.assertEqual(proc.returncode,0,proc.stderr)

    def test_later_pending_observation_does_not_fall_back_to_older_final(self):
        pending=result(self.pair);pending.update(captured_at='2026-11-06T11:30:00+09:00',status='PENDING',data=None)
        self.state.score(self.pair['pair_sha256'],pending,'2026-11-06T12:00:00+09:00')
        view=self.project(self.state);row=view['records'][0]
        self.assertEqual(row['result']['status'],'pending')
        self.assertEqual(len(row['result_observations']),2)

    def test_resealed_late_physical_receipt_is_rejected(self):
        pair_sha=self.pair['pair_sha256']
        receipt_sha=self.state.db.execute('SELECT receipt_sha FROM pairs WHERE sha=?',(pair_sha,)).fetchone()[0]
        receipt=json.loads(self.state._get(receipt_sha));receipt['write_completed_at']=self.pair['cutoff_at']
        receipt['receipt_sha256']=digest({k:v for k,v in receipt.items() if k!='receipt_sha256'})
        with self.state.db:
            updated=self.state._put(f'pairs/{pair_sha}.receipt.json',(wire(receipt)+'\n').encode())
            self.state.db.execute('UPDATE pairs SET receipt_sha=? WHERE sha=?',(updated,pair_sha))
        with self.assertRaises(ValueError):self.project(self.state)
