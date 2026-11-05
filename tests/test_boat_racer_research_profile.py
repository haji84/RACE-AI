from datetime import datetime,timezone
from pathlib import Path
import tempfile
import unittest

from tests.test_boat_history_store import archives,DAY
from tests.test_boat_racer_database import term_archive
from race_ai.boat_history_store import HistoryStore
from race_ai.boat_racer_database import RacerDatabase
from race_ai.boat_racer_term import term_info


class ResearchProfileTests(unittest.TestCase):
    def test_term_and_recent_history_are_joined_by_id_with_separate_periods_and_denominators(self):
        from race_ai.boat_racer_research_profile import assemble_profile
        now=datetime(2030,1,1,tzinfo=timezone.utc)
        racers=RacerDatabase(clock=lambda:now)
        racers.import_term(term_archive(),term='2026-2',source_url=term_info('2026-2')['source_url'],captured_at=now.isoformat())
        with tempfile.TemporaryDirectory() as folder:
            history=HistoryStore(Path(folder)/'history.sqlite');raw,proof=archives(start='BROKEN')
            history.ingest_day(DAY,raw['B'],raw['K'],proof['B'],proof['K'])
            p=assemble_profile(history,racers,'4001',as_of=now.isoformat(),allow_source=lambda *a:True)
            self.assertEqual(p['racer_id'],'4001');self.assertEqual(p['official_term']['racer_id'],'4001')
            self.assertEqual(p['recent_history']['opportunities'],3)
            self.assertEqual(p['recent_history']['unresolved_opportunities'],1)
            self.assertEqual(p['official_term']['period_end'],'2026-04-30')
            self.assertEqual(p['recent_history']['last_program']['program_day'],'2026-11-04')
            self.assertFalse(p['features_applied_to_predictions']);self.assertFalse(p['all_career_history_complete'])
            missing=assemble_profile(history,racers,'4999',as_of=now.isoformat(),allow_source=lambda *a:True)
            self.assertIsNone(missing['official_term']);self.assertEqual(missing['recent_history']['starts'],0)
            history.close()
