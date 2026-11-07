"""Offline probe CLI contract with synthetic sources only."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from scripts.teiai_history_probe import main
from tests.test_teiai_feature_adapter import inputs
from tests.test_teiai_history import race_json
import json

class ProbeTests(unittest.TestCase):
    def test_summary_has_no_source_rows_or_private_model_inputs(self):
        _,histories,official=inputs()
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)
            for name,raw in [('history.csv',histories['4001']['raw']),('race.json',json.dumps(race_json()).encode()),
                             ('official.lzh',official['2030-03-30']['raw']),
                             ('racer.json',json.dumps(dict(source='fictional',racer={'regno':4001},stats={})).encode())]:
                (p/name).write_bytes(raw)
            output=StringIO()
            with redirect_stdout(output):
                main(['--history',str(p/'history.csv'),'--racer',str(p/'racer.json'),'--registration','4001',
                      '--race',str(p/'race.json'),'--race-id','20300330-01-01','--official-k',str(p/'official.lzh')])
            report=json.loads(output.getvalue())
            self.assertEqual(report['race']['matched_rows'],0) # ST fixture intentionally .12 vs .10
            self.assertEqual(report['race']['mismatched_rows'],6)
            self.assertEqual(report['history']['matched_rows'],1)
            self.assertNotIn('accepted',report['history']);self.assertNotIn('snapshot',report)
            self.assertFalse(report['future_race_verified'])
