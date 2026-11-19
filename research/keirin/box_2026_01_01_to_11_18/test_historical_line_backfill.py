"""Source extractor offline tests. No provider request and no synthetic race promoted."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from historical_line_backfill import extract,read_jsonl

class ArchiveLineTests(unittest.TestCase):
    def test_actual_page_sections(self):
        html="""<html><nav>01R 02R</nav>
          <h2>01R 1-5-8 12.5倍</h2><div>ライン並び4 7│3 6│1 5 8│2 9</div>
          <h2>02R 1-9-5 52.6倍</h2><div>ライン並び9 1 6│2 7│4 3│8 5</div>
        </html>"""
        groups,bad=extract(html)
        self.assertEqual(groups[1],"4 7│3 6│1 5 8│2 9")
        self.assertEqual(groups[2],"9 1 6│2 7│4 3│8 5")
        self.assertEqual(bad,set())
    def test_disagreeing_source_sections_are_conflicted(self):
        groups,bad=extract("<h2>01R</h2>ライン並び1 2│3 4"
                           "<h2>01R</h2>ライン並び1 3│2 4")
        self.assertEqual(bad,{1})
    def test_unseen_checkpoint_is_empty(self):
        self.assertEqual(read_jsonl(Path("/this/path/does/not/exist.jsonl")),[])
if __name__=="__main__":unittest.main()
