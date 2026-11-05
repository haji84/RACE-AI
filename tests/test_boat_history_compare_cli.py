from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
import io
import json
import tempfile
import unittest

from tests.test_boat_history_comparison import current,NOW
from tests.test_boat_history_store import archives,DAY
from race_ai.boat_history_store import HistoryStore,instant


class CompareCliTests(unittest.TestCase):
    def test_missing_history_database_is_not_silently_recreated(self):
        from scripts import boat_history_compare as cli
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'snapshot.json';source.write_text(json.dumps(current()))
            missing=root/'missing.sqlite'
            argv=['compare','prepare','--snapshot',str(source),'--history-db',str(missing),'--private-dir',str(root/'pairs')]
            with patch('sys.argv',argv),patch.object(cli,'clock',return_value=instant(NOW)),redirect_stdout(io.StringIO()),self.assertRaises(ValueError):
                cli.main()
            self.assertFalse(missing.exists())

    def test_prepare_retains_first_pair_and_records_entire_declared_cohort(self):
        try:from scripts import boat_history_compare as cli
        except ImportError:cli=None
        self.assertIsNotNone(cli,'prospective comparison CLI missing')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=HistoryStore(root/'history.sqlite')
            raw,proof=archives();store.ingest_day(DAY,raw['B'],raw['K'],proof['B'],proof['K']);store.close()
            source=root/'snapshot.json';source.write_text(json.dumps(current()))
            out=root/'pairs'
            argv=['compare','prepare','--snapshot',str(source),'--history-db',str(root/'history.sqlite'),'--private-dir',str(out)]
            with patch('sys.argv',argv),patch.object(cli,'clock',return_value=instant(NOW)),redirect_stdout(io.StringIO()):cli.main()
            path=out/'20261106-17-01-P0.json';before=path.read_bytes()
            with patch('sys.argv',argv),patch.object(cli,'clock',return_value=instant('2026-11-06T01:31:00+09:00')),redirect_stdout(io.StringIO()):cli.main()
            self.assertEqual(path.read_bytes(),before)
            protocol=json.loads((out/'protocol.json').read_text())
            self.assertEqual(protocol['scheduled_race_ids'],['20261106-17-01'])
            result=json.loads((out/'preparation-report.json').read_text())
            self.assertEqual(result['prepared'],1);self.assertEqual(result['reused'],1)
            self.assertFalse(result['accuracy_improvement_proven'])
